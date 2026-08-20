from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services import filing_pipeline
from app.services.filing_pipeline import FilingPipelineError, analyze_ticker

FILING_HTML = "<html><body>" + "".join(
    f"<p>Item {i}. Heading</p><p>{'disclosure text ' * 300}</p>" for i in ["1", "1A", "3", "7", "8"]
) + "</body></html>"

CURRENT = {
    "accessionNumber": "0000320193-25-000079",
    "primaryDocument": "aapl-20250927.htm",
    "filingDate": "2025-10-31",
    "reportDate": "2025-09-27",
    "fiscalYear": 2025,
}
PRIOR = {**CURRENT, "accessionNumber": "0000320193-24-000123", "fiscalYear": 2024}

PROFILE = {
    "cik": "0000320193", "name": "Apple Inc.", "sic": "3571",
    "sicDescription": "Electronic Computers", "fiscalYearEnd": "0926",
    "exchanges": ["Nasdaq"], "tickers": ["AAPL"],
}

CATEGORIES = [
    {"name": "Risk Factors", "severity": "red",
     "findings": [{"summary": "Supplier concentration.",
                   "citation": {"quote": "disclosure text", "section": "Item 1A. Risk Factors"}}]}
]

OVERVIEW = {"intro": "Revenue grew.", "verdict": "review", "keyMetrics": {"totalRevenue": "$391B"}}

# Enough of a submissions index for the filing track record to have something to read.
# Dates are relative to today so the three-year window never ages out from under the test.
_FILED = (date.today() - timedelta(days=120)).isoformat()
_PERIOD_END = (date.today() - timedelta(days=160)).isoformat()
SUBMISSIONS = {
    "cik": "0000320193",
    "category": "Large accelerated filer",
    "filings": {
        "recent": {
            "form": ["10-K", "8-K"],
            "accessionNumber": ["0000320193-25-000079", "0000320193-25-000080"],
            "filingDate": [_FILED, _FILED],
            "reportDate": [_PERIOD_END, ""],
            "primaryDocument": ["aapl.htm", "a8k.htm"],
            "items": ["", "4.02"],
        }
    },
}


@pytest.fixture
def edgar_stub():
    with patch.multiple(
        "app.services.filing_pipeline.edgar",
        resolve_ticker=lambda t: {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        fetch_submissions=lambda cik: SUBMISSIONS,
        company_profile=lambda s: PROFILE,
        list_annual_filings=lambda s, limit=2: [CURRENT, PRIOR],
        fetch_filing_document=lambda *a: FILING_HTML,
        filing_document_url=lambda *a: "https://sec.gov/doc.htm",
    ):
        yield


@pytest.fixture
def branches_stub():
    with patch.object(filing_pipeline, "_financials_branch", return_value={
        "financialHistory": [{"fiscalYear": 2025, "revenue": 391e9}],
        "ratios": {"grossMargin": {"label": "Gross Margin", "value": 46.2, "unit": "percent"}},
        "screens": [{"key": "beneish_m", "value": -2.4}],
        "flags": [],
        "peers": {"sic": "3571", "cohortSize": 8, "metrics": []},
    }), patch.object(filing_pipeline, "_diff_branch", return_value={
        "diffs": [{"section": "Item 1A. Risk Factors"}],
        "priorSections": {"1A": "prior risk text " * 400},
    }), patch.object(filing_pipeline, "_insider_branch", return_value={
        "windowMonths": 12,
        "summary": {"sellShares": 1000.0},
        "signals": [{"key": "net_buying", "label": "Insiders were net buyers",
                     "severity": "green", "interpretation": "..."}],
    }), \
         patch.object(filing_pipeline, "_apply_verification", return_value={"verified": 1}), \
         patch("app.services.filing_pipeline.filing_analysis.analyze_categories", return_value=CATEGORIES), \
         patch("app.services.filing_pipeline.filing_analysis.analyze_overview", return_value=OVERVIEW):
        yield


def test_analyze_ticker_assembles_the_full_payload(edgar_stub, branches_stub):
    result = analyze_ticker("AAPL")

    assert result["intro"] == "Revenue grew."
    assert result["company"]["name"] == "Apple Inc."
    assert result["company"]["fiscalYear"] == 2025
    assert result["company"]["filingUrl"] == "https://sec.gov/doc.htm"
    assert result["categories"] == CATEGORIES
    assert result["financialHistory"][0]["revenue"] == 391e9
    assert result["screens"][0]["key"] == "beneish_m"
    assert result["diffs"][0]["section"] == "Item 1A. Risk Factors"
    assert result["peers"]["cohortSize"] == 8
    assert result["verificationStats"] == {"verified": 1}
    assert result["insiderActivity"]["signals"][0]["key"] == "net_buying"
    # Both of these are computed from data already fetched, so they are always present.
    assert result["filingTrackRecord"]["events"][0]["key"] == "non_reliance"
    assert result["textMetrics"]["sections"]


def test_analyze_ticker_reports_progress_steps(edgar_stub, branches_stub):
    steps = []
    analyze_ticker("AAPL", progress=lambda step, detail=None: steps.append(step))
    assert steps[0] == "fetching_filing"
    assert "analyzing" in steps and "verifying" in steps and "finalizing" in steps


def test_analyze_ticker_defaults_the_ticker_into_key_metrics(edgar_stub, branches_stub):
    with patch("app.services.filing_pipeline.filing_analysis.analyze_overview",
               return_value={"intro": "x", "verdict": "standard", "keyMetrics": {}}):
        result = analyze_ticker("AAPL")
    assert result["keyMetrics"]["tickerSymbol"] == "AAPL"


def test_analyze_ticker_raises_when_no_sections_are_identifiable(edgar_stub, branches_stub):
    with patch("app.services.filing_pipeline.edgar.fetch_filing_document",
               return_value="<html><body>no items here</body></html>"):
        with pytest.raises(FilingPipelineError, match="sections could not be identified"):
            analyze_ticker("AAPL")


def test_analysis_survives_the_financials_branch_failing(edgar_stub, branches_stub):
    """An SEC outage must not lose the narrative analysis that already succeeded."""
    with patch.object(filing_pipeline, "_financials_branch", side_effect=RuntimeError("sec down")):
        result = analyze_ticker("AAPL")
    assert result["categories"] == CATEGORIES
    assert result["financialHistory"] == []
    assert result["peers"] is None


def test_analysis_survives_the_diff_branch_failing(edgar_stub, branches_stub):
    with patch.object(filing_pipeline, "_diff_branch", side_effect=RuntimeError("prior 404")):
        result = analyze_ticker("AAPL")
    assert result["diffs"] == []
    assert result["categories"] == CATEGORIES
    # The document metrics lose their prior-year comparison but still measure this year.
    assert result["textMetrics"]["priorYear"] is None
    assert result["textMetrics"]["sections"]


def test_analysis_survives_the_insider_branch_failing(edgar_stub, branches_stub):
    with patch.object(filing_pipeline, "_insider_branch", side_effect=RuntimeError("form 4 404")):
        result = analyze_ticker("AAPL")
    assert result["insiderActivity"] is None
    assert result["categories"] == CATEGORIES


def test_the_prior_years_sections_are_reused_rather_than_downloaded_again(edgar_stub, branches_stub):
    """The diff branch already paid for that 4MB document; the text metrics ride along."""
    result = analyze_ticker("AAPL")

    risk_factors = next(s for s in result["textMetrics"]["sections"] if s["item"] == "1A")
    assert risk_factors["priorWords"] > 0


def test_analysis_falls_back_to_a_written_intro_when_the_overview_call_fails(edgar_stub, branches_stub):
    with patch("app.services.filing_pipeline.filing_analysis.analyze_overview",
               side_effect=RuntimeError("timeout")):
        result = analyze_ticker("AAPL")
    assert "Apple Inc." in result["intro"]
    assert result["verdict"] == "review"


def test_diff_branch_is_skipped_without_a_prior_filing(edgar_stub, branches_stub):
    seen = {}

    def record(cik, sections, prior, year, progress):
        seen["prior"] = prior
        return {"diffs": [], "priorSections": {}}

    with patch("app.services.filing_pipeline.edgar.list_annual_filings",
               return_value=[CURRENT]), \
         patch.object(filing_pipeline, "_diff_branch", side_effect=record):
        result = analyze_ticker("AAPL")

    assert seen["prior"] is None
    assert result["diffs"] == []
    assert "No prior-year 10-K" in result["coverageNote"]


def test_coverage_note_reports_how_much_of_the_filing_was_read(edgar_stub, branches_stub):
    result = analyze_ticker("AAPL")
    assert "sections covering" in result["coverageNote"]


def test_safe_swallows_failures_and_returns_none():
    assert filing_pipeline._safe("x", lambda: 1 / 0) is None
    assert filing_pipeline._safe("x", lambda: "ok") == "ok"
