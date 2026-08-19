"""Section-aware, multi-pass analysis of a 10-K.

The original single-call approach clipped the filing to a fixed character budget
taken from the front of the document, so anything past roughly Item 7 — including
the notes to the financial statements, where the substantive disclosures live —
never reached the model at all.

Here each category is analysed against only the Items that actually govern it, in
parallel, and a short reduce pass writes the overview from the category results.
That keeps every individual request small enough to answer well, covers the back
of the filing, and lets each finding cite the section it came from.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import anthropic

from .filing_sections import section_label

# Which Items govern each category, and the keywords used to locate relevant passages
# inside Item 8 (the notes run to 60k+ characters and are mostly boilerplate schedules).
CATEGORY_SOURCES = {
    "Risk Factors": {
        "items": ["1A"],
        "keywords": [],
        "focus": "material risks the company discloses, prioritising ones that are specific to this company rather than boilerplate every filer includes",
    },
    "MD&A / Financial Performance": {
        "items": ["7", "7A"],
        "keywords": [],
        "focus": "how management explains the year's results — revenue and margin drivers, segment performance, and any explanation that does not fit the numbers",
    },
    "Liquidity & Capital Resources": {
        "items": ["7", "8"],
        "keywords": [
            "liquidity", "capital resources", "credit facility", "revolving",
            "covenant", "maturities", "commercial paper", "debt", "going concern",
        ],
        "focus": "the company's ability to fund itself — cash position, credit facilities, debt maturities, covenant headroom, and going-concern language",
    },
    "Related-Party Transactions": {
        "items": ["13", "8"],
        "keywords": ["related part", "affiliate", "director", "officer", "equity method"],
        "focus": "transactions with insiders, affiliates, or entities under common control",
    },
    "Legal Proceedings & Contingencies": {
        "items": ["3", "8"],
        "keywords": [
            "legal proceeding", "litigation", "contingenc", "lawsuit",
            "investigation", "settlement", "claim", "regulatory",
        ],
        "focus": "pending litigation, regulatory investigations, and loss contingencies, including whether the company quantifies its exposure",
    },
    "Accounting Policy Changes": {
        "items": ["8"],
        "keywords": [
            "accounting polic", "recently adopted", "recently issued",
            "estimate", "critical audit matter", "restat", "ASU ", "revenue recognition",
        ],
        "focus": "changes in accounting policy or estimate, newly adopted standards, restatements, and critical audit matters",
    },
}

CATEGORY_NAMES = tuple(CATEGORY_SOURCES)

MAX_CATEGORY_CHARS = 120_000
_KEYWORD_WINDOW_CHARS = 3_000
_SECTION_SEPARATOR = "\n\n[...]\n\n"

CATEGORY_BUDGET_SECONDS = 150
OVERVIEW_BUDGET_SECONDS = 60
_MAX_PARALLEL_CATEGORIES = 3

NOTHING_MATERIAL = "Nothing material to report."


class FilingAnalysisError(Exception):
    pass


CATEGORY_SYSTEM_PROMPT = """You are a financial-filing analyst examining one section of a company's 10-K annual report.

You are analysing exactly one category: {category}.
Focus on: {focus}

The text below is drawn from: {sections}.

Return ONLY this JSON — no markdown fences, no extra text:

{{
  "severity": "red" | "yellow" | "green",
  "findings": [
    {{
      "summary": "Plain-English explanation of what this finding means for an investor",
      "citation": {{
        "quote": "Verbatim excerpt from the text below (max 300 chars)",
        "section": "the Item this quote came from, e.g. Item 1A. Risk Factors"
      }}
    }}
  ]
}}

Rules:
- severity: red = high materiality/investor risk; yellow = worth noting; green = routine, nothing notable
- Report at most 5 findings. Prefer a few substantive findings over many trivial ones.
- Prefer findings that are specific to THIS company. Boilerplate language that appears in
  every filer's 10-K is not a finding.
- citation is MANDATORY for every finding except the placeholder below. Never omit it and
  never fabricate a quote — if you cannot find a supporting passage, do not report the finding.
- citation.quote: copy text character-for-character from the text below. Never paraphrase.
  Every quote is mechanically checked against the source and a quote that does not match is discarded.
- citation.section: the "Item N." heading the quote sits under, exactly as it appears.
- If there is nothing material in this category: severity "green", one finding with summary
  "Nothing material to report." and citation null.
- Return ONLY valid JSON. No markdown. No explanation."""

OVERVIEW_SYSTEM_PROMPT = """You are a financial-filing analyst writing the headline summary of a 10-K annual report.

You are given the per-category findings already extracted from the filing, the company's
reported financial history, and any computed forensic screens. Write the overview.

Return ONLY this JSON — no markdown fences, no extra text:

{
  "intro": "3-5 plain-English sentences on the most important things a reader should know about this filing. Lead with what changed or what is unusual, not with what the company does.",
  "verdict": "standard" | "review" | "concern",
  "keyMetrics": {
    "totalRevenue": "dollar amount, or null",
    "netIncome": "dollar amount, or null",
    "totalDebt": "dollar amount, or null",
    "cashAndEquivalents": "dollar amount, or null",
    "operatingCashFlow": "dollar amount, or null",
    "tickerSymbol": "trading symbol, or null"
  }
}

Rules:
- verdict: "standard" = nothing unusual; "review" = 1-2 yellow flags; "concern" = any red flag present
- Write the intro for someone who will not read the rest of the page. Name specific numbers
  and specific changes. Do not write generic filler like "the company faces various risks".
- keyMetrics: copy the values from the reported financial history you are given. Do not
  recompute or estimate them. Use null where the history has no value.
- Return ONLY valid JSON. No markdown. No explanation."""

_STRICT_SUFFIX = (
    "\n\nCRITICAL: Your previous response was not valid JSON. Return ONLY a raw JSON object. "
    "No ```json wrapper."
)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _call_json(system: str, user_content: str, max_tokens: int, budget_seconds: float) -> dict:
    """One Claude call with a single strict retry, bounded by a wall-clock budget."""
    deadline = time.monotonic() + budget_seconds
    client = _client()
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining < 10:
            raise FilingAnalysisError(
                f"Exhausted the {budget_seconds}s analysis budget ({remaining:.1f}s left)"
            )
        active_system = system if attempt == 0 else system + _STRICT_SUFFIX
        # max_retries=0: the loop here already retries once, and the SDK's own
        # retry-on-timeout would multiply wall-clock time past the deadline above.
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
                raise FilingAnalysisError(
                    f"Claude returned invalid JSON after 2 attempts: {raw[:200]}"
                )
    raise FilingAnalysisError("Unreachable")


def _keyword_windows(text: str, keywords: list[str], max_chars: int) -> str:
    """Excerpt the neighbourhoods of keyword hits, merging overlapping windows.

    Used to make a 60k-character notes section fit a category budget without simply
    truncating it, which would drop the later notes entirely.
    """
    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    for keyword in keywords:
        start = 0
        needle = keyword.lower()
        while True:
            hit = lowered.find(needle, start)
            if hit == -1:
                break
            spans.append(
                (max(0, hit - _KEYWORD_WINDOW_CHARS // 2), min(len(text), hit + _KEYWORD_WINDOW_CHARS // 2))
            )
            start = hit + len(needle)

    if not spans:
        return text[:max_chars]

    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    out: list[str] = []
    used = 0
    for start, end in merged:
        chunk = text[start:end]
        if used + len(chunk) > max_chars:
            chunk = chunk[: max_chars - used]
        out.append(chunk)
        used += len(chunk)
        if used >= max_chars:
            break
    return _SECTION_SEPARATOR.join(out)


def build_category_input(sections: dict[str, str], category: str) -> tuple[str, list[str]]:
    """Assemble the text for one category, and the Item labels it was drawn from."""
    spec = CATEGORY_SOURCES[category]
    available = [item for item in spec["items"] if sections.get(item)]
    if not available:
        return "", []

    # Split the budget across the Items so a large Item 8 cannot crowd out Item 3.
    per_item = max(MAX_CATEGORY_CHARS // len(available), 8_000)
    parts = []
    for item in available:
        text = sections[item]
        if len(text) > per_item:
            text = (
                _keyword_windows(text, spec["keywords"], per_item)
                if spec["keywords"]
                else text[:per_item]
            )
        parts.append(f"=== {section_label(item)} ===\n{text}")

    return "\n\n".join(parts), [section_label(item) for item in available]


def analyze_category(sections: dict[str, str], category: str) -> dict:
    """Analyse one category. Returns a category dict ready for the summary payload."""
    text, labels = build_category_input(sections, category)
    if not text:
        return {
            "name": category,
            "severity": "green",
            "findings": [{"summary": NOTHING_MATERIAL, "citation": None, "confidence": "high"}],
        }

    system = CATEGORY_SYSTEM_PROMPT.format(
        category=category,
        focus=CATEGORY_SOURCES[category]["focus"],
        sections=", ".join(labels),
    )
    result = _call_json(system, text, max_tokens=2048, budget_seconds=CATEGORY_BUDGET_SECONDS)

    findings = result.get("findings") or []
    if not findings:
        findings = [{"summary": NOTHING_MATERIAL, "citation": None}]
    for finding in findings:
        finding.setdefault("confidence", "medium")

    return {
        "name": category,
        "severity": result.get("severity", "green"),
        "findings": findings,
    }


def analyze_categories(sections: dict[str, str]) -> list[dict]:
    """Run every category concurrently.

    Concurrency is capped rather than unbounded: six simultaneous long-context requests
    is enough to trip Anthropic rate limits on smaller accounts, and the Lambda has the
    wall-clock room for two waves.
    """
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_CATEGORIES) as pool:
        futures = {
            category: pool.submit(analyze_category, sections, category)
            for category in CATEGORY_NAMES
        }
        results = []
        for category, future in futures.items():
            try:
                results.append(future.result())
            except Exception as e:
                # One category failing should not lose the other five. Surface it in place.
                results.append(
                    {
                        "name": category,
                        "severity": "green",
                        "findings": [
                            {
                                "summary": f"This category could not be analyzed ({e}).",
                                "citation": None,
                                "confidence": "low",
                            }
                        ],
                    }
                )
    return results


def _category_digest(categories: list[dict]) -> str:
    lines = []
    for category in categories:
        lines.append(f"## {category['name']} — severity {category['severity']}")
        for finding in category["findings"]:
            lines.append(f"- {finding['summary']}")
    return "\n".join(lines)


def analyze_overview(
    categories: list[dict],
    company: dict,
    history: list[dict],
    screens: Optional[dict] = None,
) -> dict:
    payload = {
        "company": company,
        "reportedFinancialHistory": history[-3:] if history else [],
        "forensicScreens": (screens or {}).get("screens", []),
        "divergenceFlags": (screens or {}).get("flags", []),
    }
    user_content = (
        f"{json.dumps(payload, default=str)}\n\n"
        f"Category findings:\n{_category_digest(categories)}"
    )
    return _call_json(
        OVERVIEW_SYSTEM_PROMPT,
        user_content,
        max_tokens=1024,
        budget_seconds=OVERVIEW_BUDGET_SECONDS,
    )
