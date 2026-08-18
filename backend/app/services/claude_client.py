import json
import os
import time

import anthropic

SYSTEM_PROMPT = """You are a lease analysis assistant helping first-time renters understand their residential lease.

Analyze the lease and return ONLY this JSON — no markdown fences, no extra text:

{
  "intro": "2-4 plain-English sentences covering the most important things a first-time renter needs to know about this lease",
  "verdict": "standard" | "review" | "concern",
  "keyNumbers": {
    "monthlyRent": "dollar amount and frequency extracted from lease, or null",
    "securityDeposit": "dollar amount extracted from lease, or null",
    "leaseLength": "duration extracted from lease, or null",
    "lateFee": "amount and grace period extracted from lease, or null",
    "earlyTerminationFee": "amount or formula extracted from lease, or null"
  },
  "categories": [
    {
      "name": "Auto-Renewal Clauses",
      "severity": "red" | "yellow" | "green",
      "findings": [
        {
          "summary": "Plain-English explanation of what this means for the tenant",
          "quote": "Verbatim excerpt from the lease this is based on (max 200 chars), or null for missing clauses",
          "action": "Specific thing the tenant should say or ask for"
        }
      ]
    }
  ]
}

Rules:
- verdict: "standard" = nothing unusual; "review" = 1-2 yellow flags; "concern" = any red flag present
- severity: red = harmful to tenant; yellow = worth clarifying; green = nothing to worry about
- Always return all four categories: Auto-Renewal Clauses, Deposit Conditions, Unusual Fees, Missing Standard Clauses
- If a category has no issues: severity "green", one finding with summary "Nothing concerning here.", quote null, action "No action needed."
- quote: copy text verbatim from the lease. Never paraphrase. For Missing Standard Clauses, always null.
- action: be specific (e.g. "Ask the landlord to change the notice period from 60 days to 30 days").
- keyNumbers: extract actual values. Set each field to null if not found in the lease.
- Return ONLY valid JSON. No markdown. No explanation."""

STRICT_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + "\n\nCRITICAL: Your previous response was not valid JSON. Return ONLY a raw JSON object. No ```json wrapper."
)

MAX_INPUT_CHARS = 80_000  # ~20k tokens; keeps per-request cost under $0.09

FINANCIAL_SYSTEM_PROMPT = """You are a financial-filing analysis assistant helping a reader understand a company's 10-K annual report.

The filing text is broken into pages, each preceded by a marker like [PAGE 3]. Use the marker
immediately before a passage to determine that passage's page number.

Analyze the filing and return ONLY this JSON — no markdown fences, no extra text:

{
  "intro": "2-4 plain-English sentences on the most important things a reader should know about this filing",
  "verdict": "standard" | "review" | "concern",
  "keyMetrics": {
    "totalRevenue": "dollar amount extracted from the filing, or null",
    "netIncome": "dollar amount extracted from the filing, or null",
    "totalDebt": "dollar amount extracted from the filing, or null",
    "cashAndEquivalents": "dollar amount extracted from the filing, or null",
    "operatingCashFlow": "dollar amount extracted from the filing, or null",
    "tickerSymbol": "the trading symbol from the filing's cover page (e.g. AAPL), or null if not found"
  },
  "categories": [
    {
      "name": "Risk Factors",
      "severity": "red" | "yellow" | "green",
      "findings": [
        {
          "summary": "Plain-English explanation of what this finding means for a reader",
          "citation": {
            "quote": "Verbatim excerpt from the filing this is based on (max 300 chars)",
            "page": 12
          },
          "confidence": "high" | "medium" | "low"
        }
      ]
    }
  ]
}

Rules:
- verdict: "standard" = nothing unusual; "review" = 1-2 yellow flags; "concern" = any red flag present
- severity: red = high materiality/investor risk; yellow = worth noting; green = routine, nothing notable
- Always return all six categories: Risk Factors, MD&A / Financial Performance, Liquidity & Capital Resources,
  Related-Party Transactions, Legal Proceedings & Contingencies, Accounting Policy Changes
- If a category has nothing material: severity "green", one finding with summary "Nothing material to report.",
  citation null, confidence "high"
- citation is MANDATORY for every finding except the "Nothing material to report." placeholder. Never omit it,
  never fabricate a quote — if you cannot find a supporting passage, do not report the finding.
- citation.quote: copy text verbatim (character-for-character) from the filing. Never paraphrase.
- citation.page: the page number from the nearest [PAGE N] marker preceding the quoted text. Use null only if
  genuinely undeterminable.
- confidence: "high" = directly and unambiguously supported by the cited text; "medium" = supported but requires
  some inference; "low" = a plausible reading but the filing language is ambiguous or the quote is indirect.
- keyMetrics: extract actual values. Set each field to null if not found in the filing.
- tickerSymbol: the cover page of a 10-K lists "Trading Symbol(s)" alongside the exchange it trades on
  (e.g. "AAPL" / "The Nasdaq Stock Market LLC"). Extract the symbol exactly as printed. Set to null if the
  filing has no cover-page trading symbol (e.g. private company, no listed equity).
- Return ONLY valid JSON. No markdown. No explanation."""

FINANCIAL_STRICT_SYSTEM_PROMPT = (
    FINANCIAL_SYSTEM_PROMPT
    + "\n\nCRITICAL: Your previous response was not valid JSON, or was missing a required citation. "
      "Return ONLY a raw JSON object. No ```json wrapper. Every finding except the placeholder must include "
      "a citation with a verbatim quote."
)

MAX_FILING_INPUT_CHARS = 500_000  # ~125-165k tokens; ~$0.50/request ceiling on claude-sonnet-4-6's 1M context

# Wall-clock budgets for the *entire* _call_claude_with_retry call, including both attempts.
# Must stay comfortably under the async Lambda's function timeout (see template.yaml) to leave
# room for S3 fetch, PDF extraction, and the DynamoDB write that follows.
LEASE_CLAUDE_BUDGET_SECONDS = 90
FILING_CLAUDE_BUDGET_SECONDS = 260

_MIN_CALL_SECONDS = 10  # don't attempt a call with less runway than this left in the budget


def _call_claude_with_retry(
    system: str, strict_system: str, user_content: str, max_tokens: int, budget_seconds: float
) -> dict:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    deadline = time.monotonic() + budget_seconds

    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining < _MIN_CALL_SECONDS:
            raise TimeoutError(
                f"Exhausted the {budget_seconds}s Claude budget before completing analysis "
                f"({remaining:.1f}s remaining)"
            )
        active_system = system if attempt == 0 else strict_system
        # max_retries=0: our own attempt loop already retries once on malformed JSON. The SDK's
        # built-in retry-on-timeout would otherwise multiply wall-clock time up to
        # timeout * (max_retries + 1), which could blow past the deadline we're tracking here.
        message = client.with_options(timeout=remaining, max_retries=0).messages.create(
            model=model,
            max_tokens=max_tokens,
            system=active_system,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 1:
                raise ValueError(f"Claude returned invalid JSON after 2 attempts: {raw[:200]}")

    raise ValueError("Unreachable")


def analyze_lease(lease_text: str) -> dict:
    lease_text = lease_text[:MAX_INPUT_CHARS]
    return _call_claude_with_retry(
        SYSTEM_PROMPT,
        STRICT_SYSTEM_PROMPT,
        f"Analyze this lease:\n\n{lease_text}",
        max_tokens=2048,
        budget_seconds=LEASE_CLAUDE_BUDGET_SECONDS,
    )


def analyze_financial_filing(filing_text: str) -> dict:
    filing_text = filing_text[:MAX_FILING_INPUT_CHARS]
    return _call_claude_with_retry(
        FINANCIAL_SYSTEM_PROMPT,
        FINANCIAL_STRICT_SYSTEM_PROMPT,
        f"Analyze this 10-K filing:\n\n{filing_text}",
        max_tokens=4096,
        budget_seconds=FILING_CLAUDE_BUDGET_SECONDS,
    )
