"""End-to-end analysis of a company's latest 10-K, sourced from EDGAR.

Stages fan out where they can: the XBRL/peer branch talks only to data.sec.gov while
the narrative branch talks only to Claude, so they overlap almost entirely.

Every enrichment past the core category analysis is best-effort. A company with no
prior 10-K still gets categories and financials; a thin SIC cohort still gets a
year-over-year diff. `_safe` is what makes that true: an enrichment that raises is
recorded as absent, never fatal. A partial analysis beats a failed one.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from . import edgar
from .filing_sections import extract_filing_sections, section_label
from . import filing_analysis

logger = logging.getLogger(__name__)

# Only Item 1A is diffed. Risk factors are copy-pasted between years, so what a company
# adds, drops or rewords is real signal, and the section is almost pure prose.
#
# Item 7 (MD&A) was tried and removed: once its inline financial tables are flattened to
# text, most of the "changes" it yields are this year's numbers differing from last
# year's — noise that buries the Item 1A findings, and worse than what the XBRL history
# and ratio table already show. Re-adding it needs a table-aware extractor, not a
# different diff threshold.
DIFFABLE_ITEMS = ["1A"]

PEER_LIMIT = 12
PEER_BUDGET_SECONDS = 45.0

ProgressFn = Callable[[str, Optional[str]], None]

_EMPTY_FINANCIALS = {
    "financialHistory": [],
    "ratios": {},
    "screens": [],
    "flags": [],
    "peers": None,
}


class FilingPipelineError(Exception):
    pass


def _noop_progress(step: str, detail: Optional[str] = None) -> None:
    pass


def _safe(label: str, fn, *args, **kwargs):
    """Run an optional enrichment; log and return None if it fails."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("Optional analysis stage %r failed — continuing without it", label)
        return None


# --- data branch ---------------------------------------------------------------------


def _financials_branch(cik: str, sic: Optional[str], progress: ProgressFn) -> dict:
    from . import xbrl_metrics, forensic_screens, peers as peers_service

    progress("reading_financials", "Pulling tagged financial data from SEC XBRL")
    facts = _safe("companyfacts", edgar.fetch_company_facts, cik)
    history = _safe("history", xbrl_metrics.build_financial_history, facts) if facts else None
    history = history or []

    ratios = _safe("ratios", xbrl_metrics.derived_ratios, history) if history else None
    screens = _safe("screens", forensic_screens.run_all_screens, history) if history else None

    peer_comparison = None
    if history and sic:
        progress("benchmarking", "Ranking against SIC industry peers")
        subject = {"cik": cik, "history": history, "ratios": ratios or {}}
        peer_comparison = _safe(
            "peers",
            peers_service.build_peer_comparison,
            sic,
            None,
            subject,
            PEER_LIMIT,
            PEER_BUDGET_SECONDS,
        )

    return {
        "financialHistory": history,
        "ratios": ratios or {},
        "screens": (screens or {}).get("screens", []),
        "flags": (screens or {}).get("flags", []),
        "peers": peer_comparison,
    }


# --- narrative branch ----------------------------------------------------------------


def _diff_branch(
    cik: str,
    current_sections: dict[str, str],
    prior_filing: Optional[dict],
    current_year: Optional[int],
    progress: ProgressFn,
) -> list[dict]:
    if not prior_filing:
        return []

    from . import section_diff

    progress("comparing_years", f"Comparing against the FY{prior_filing.get('fiscalYear')} filing")
    prior_html = _safe(
        "prior filing",
        edgar.fetch_filing_document,
        cik,
        prior_filing["accessionNumber"],
        prior_filing["primaryDocument"],
    )
    if not prior_html:
        return []

    _, prior_sections = extract_filing_sections(prior_html)

    diffs = []
    for item in DIFFABLE_ITEMS:
        prior_text = prior_sections.get(item)
        current_text = current_sections.get(item)
        if not prior_text or not current_text:
            continue
        diff = _safe(
            f"diff Item {item}",
            section_diff.diff_section,
            prior_text,
            current_text,
            section_label(item),
            prior_filing.get("fiscalYear"),
            current_year,
        )
        if diff:
            diffs.append(diff)
    return diffs


# --- verification --------------------------------------------------------------------


def _apply_verification(
    categories: list[dict], sections: dict[str, str], full_text: str
) -> Optional[dict]:
    """Check every finding's quote against the filing text it was drawn from."""
    from . import verification

    label_to_item = {section_label(item): item for item in sections}

    def source_for(finding: dict) -> str:
        citation = finding.get("citation") or {}
        item = label_to_item.get(citation.get("section") or "")
        # Fall back to the whole filing: a model that mislabels which Item a quote came
        # from has still quoted the filing, and that is what is being checked here.
        return sections.get(item) or full_text

    findings = [f for category in categories for f in category["findings"]]
    result = verification.verify_findings(findings, source_for)

    # verify_findings returns the same finding dicts, annotated in place by index.
    for finding, verified in zip(findings, result["findings"]):
        finding["verification"] = verified.get("verification")

    for category in categories:
        category["findings"] = [
            f
            for f in category["findings"]
            if (f.get("verification") or {}).get("status") != "rejected"
        ] or [
            {
                "summary": filing_analysis.NOTHING_MATERIAL,
                "citation": None,
                "confidence": "high",
            }
        ]

    return result["stats"]


# --- entry point ---------------------------------------------------------------------


def analyze_ticker(ticker: str, progress: Optional[ProgressFn] = None) -> dict:
    progress = progress or _noop_progress

    progress("fetching_filing", f"Looking up {ticker} on SEC EDGAR")
    company = edgar.resolve_ticker(ticker)
    cik = company["cik"]

    submissions = edgar.fetch_submissions(cik)
    profile = edgar.company_profile(submissions)
    filings = edgar.list_annual_filings(submissions, limit=2)
    current, prior = filings[0], (filings[1] if len(filings) > 1 else None)

    progress("fetching_filing", f"Downloading the FY{current['fiscalYear']} 10-K")
    html = edgar.fetch_filing_document(cik, current["accessionNumber"], current["primaryDocument"])
    full_text, sections = extract_filing_sections(html)
    if not sections:
        raise FilingPipelineError(
            "This filing's sections could not be identified. It may be an unusual format."
        )

    company_profile = {
        "cik": cik,
        "name": profile["name"] or company["name"],
        "ticker": company["ticker"],
        "sic": profile["sic"],
        "sicDescription": profile["sicDescription"],
        "fiscalYear": current["fiscalYear"],
        "filingDate": current["filingDate"],
        "periodEnd": current["reportDate"],
        "accessionNumber": current["accessionNumber"],
        "filingUrl": edgar.filing_document_url(
            cik, current["accessionNumber"], current["primaryDocument"]
        ),
    }

    progress("analyzing", "Reading the filing section by section")
    with ThreadPoolExecutor(max_workers=3) as pool:
        # Both enrichment branches go through _safe so a failure in either one degrades
        # the analysis rather than losing the category findings that already succeeded.
        financials_future = pool.submit(
            _safe, "financials", _financials_branch, cik, profile["sic"], progress
        )
        diff_future = pool.submit(
            _safe, "diffs", _diff_branch, cik, sections, prior, current["fiscalYear"], progress
        )
        categories_future = pool.submit(filing_analysis.analyze_categories, sections)

        categories = categories_future.result()
        diffs = diff_future.result() or []
        financials = financials_future.result() or _EMPTY_FINANCIALS

    progress("verifying", "Checking every quote against the filing text")
    verification_stats = _safe("verification", _apply_verification, categories, sections, full_text)

    progress("finalizing", "Writing the overview")
    overview = _safe(
        "overview",
        filing_analysis.analyze_overview,
        categories,
        company_profile,
        financials["financialHistory"],
        {"screens": financials["screens"], "flags": financials["flags"]},
    ) or {"intro": _fallback_intro(company_profile), "verdict": "review", "keyMetrics": None}

    key_metrics = overview.get("keyMetrics") or {}
    key_metrics.setdefault("tickerSymbol", company["ticker"])

    return {
        "intro": overview.get("intro", ""),
        "verdict": overview.get("verdict", "review"),
        "company": company_profile,
        "keyMetrics": key_metrics,
        "categories": categories,
        "financialHistory": financials["financialHistory"],
        "ratios": financials["ratios"],
        "screens": financials["screens"],
        "flags": financials["flags"],
        "diffs": diffs,
        "peers": financials["peers"],
        "verificationStats": verification_stats,
        "coverageNote": _coverage_note(sections, full_text, prior),
    }


def _fallback_intro(company_profile: dict) -> str:
    return (
        f"Analysis of {company_profile['name']}'s FY{company_profile.get('fiscalYear')} "
        "annual report. The overview could not be generated, but the section findings "
        "and financial data below are complete."
    )


def _coverage_note(sections: dict[str, str], full_text: str, prior: Optional[dict]) -> str:
    covered = sum(len(v) for v in sections.values())
    pct = round(covered / len(full_text) * 100) if full_text else 0
    note = f"Analyzed {len(sections)} sections covering {pct}% of the filing text."
    if not prior:
        note += " No prior-year 10-K was available, so no year-over-year comparison is shown."
    return note
