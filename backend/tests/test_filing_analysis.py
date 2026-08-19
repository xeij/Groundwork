import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import filing_analysis
from app.services.filing_analysis import (
    CATEGORY_NAMES,
    FilingAnalysisError,
    NOTHING_MATERIAL,
    analyze_categories,
    analyze_category,
    build_category_input,
)


def _claude_returning(*payloads):
    """Mock the Anthropic client so successive calls return successive payloads."""
    responses = [
        MagicMock(content=[MagicMock(text=p if isinstance(p, str) else json.dumps(p))])
        for p in payloads
    ]
    client = MagicMock()
    client.with_options.return_value.messages.create.side_effect = responses
    return client


SECTIONS = {
    "1A": "Item 1A. Risk Factors\n" + ("supply chain concentration risk " * 200),
    "3": "Item 3. Legal Proceedings\n" + ("antitrust litigation " * 200),
    "7": "Item 7. MD&A\n" + ("revenue grew on services " * 200),
    "8": "Item 8. Financial Statements\n" + ("accounting policy for revenue recognition " * 400),
    "13": "Item 13. Related Transactions\n" + ("related party lease " * 100),
}


def test_build_category_input_selects_the_governing_items():
    text, labels = build_category_input(SECTIONS, "Legal Proceedings & Contingencies")
    assert "antitrust litigation" in text
    assert "Item 3. Legal Proceedings" in labels
    assert "supply chain concentration" not in text


def test_build_category_input_reaches_the_notes_for_accounting_policies():
    """The old single-pass flow truncated before Item 8; this must not."""
    text, labels = build_category_input(SECTIONS, "Accounting Policy Changes")
    assert "revenue recognition" in text
    assert labels == ["Item 8. Financial Statements and Supplementary Data"]


def test_build_category_input_returns_empty_when_no_source_item_exists():
    assert build_category_input({"1A": "x" * 500}, "Related-Party Transactions") == ("", [])


def test_build_category_input_splits_the_budget_across_items():
    """A large Item 8 must not crowd out a small Item 3."""
    sections = {"3": "legal " * 100, "8": "notes " * 200_000}
    text, _ = build_category_input(sections, "Legal Proceedings & Contingencies")
    assert "legal" in text
    assert len(text) <= filing_analysis.MAX_CATEGORY_CHARS + 200


def test_keyword_windows_excerpt_around_hits_rather_than_truncating():
    text = ("filler " * 5000) + "covenant breach disclosed here" + (" filler" * 5000)
    excerpt = filing_analysis._keyword_windows(text, ["covenant"], max_chars=4000)
    assert "covenant breach disclosed here" in excerpt
    assert len(excerpt) <= 4000


def test_keyword_windows_merges_overlapping_spans():
    text = "alpha covenant one covenant two omega"
    excerpt = filing_analysis._keyword_windows(text, ["covenant"], max_chars=10_000)
    assert excerpt.count("covenant one") == 1


def test_keyword_windows_falls_back_to_truncation_without_hits():
    text = "no relevant terms here " * 100
    assert filing_analysis._keyword_windows(text, ["covenant"], 50) == text[:50]


def test_analyze_category_returns_findings_from_claude():
    payload = {
        "severity": "red",
        "findings": [
            {"summary": "Concentrated supplier risk.",
             "citation": {"quote": "supply chain concentration risk", "section": "Item 1A. Risk Factors"}}
        ],
    }
    with patch("app.services.filing_analysis._client", return_value=_claude_returning(payload)):
        result = analyze_category(SECTIONS, "Risk Factors")

    assert result["name"] == "Risk Factors"
    assert result["severity"] == "red"
    assert result["findings"][0]["summary"] == "Concentrated supplier risk."


def test_analyze_category_short_circuits_when_the_item_is_absent():
    """No Claude call should be made for a category with no source text."""
    with patch("app.services.filing_analysis._client") as client:
        result = analyze_category({"1A": "x" * 500}, "Related-Party Transactions")
    client.assert_not_called()
    assert result["findings"][0]["summary"] == NOTHING_MATERIAL
    assert result["severity"] == "green"


def test_analyze_category_substitutes_the_placeholder_for_an_empty_finding_list():
    with patch("app.services.filing_analysis._client",
               return_value=_claude_returning({"severity": "green", "findings": []})):
        result = analyze_category(SECTIONS, "Risk Factors")
    assert result["findings"][0]["summary"] == NOTHING_MATERIAL


def test_analyze_category_strips_markdown_fences():
    fenced = '```json\n{"severity": "yellow", "findings": [{"summary": "Noted."}]}\n```'
    with patch("app.services.filing_analysis._client", return_value=_claude_returning(fenced)):
        result = analyze_category(SECTIONS, "Risk Factors")
    assert result["severity"] == "yellow"


def test_analyze_category_retries_once_on_malformed_json():
    good = {"severity": "green", "findings": [{"summary": "Fine."}]}
    client = _claude_returning("not json at all", good)
    with patch("app.services.filing_analysis._client", return_value=client):
        result = analyze_category(SECTIONS, "Risk Factors")
    assert result["findings"][0]["summary"] == "Fine."
    assert client.with_options.return_value.messages.create.call_count == 2


def test_analyze_category_raises_after_two_malformed_responses():
    client = _claude_returning("nope", "still nope")
    with patch("app.services.filing_analysis._client", return_value=client):
        with pytest.raises(FilingAnalysisError, match="invalid JSON after 2 attempts"):
            analyze_category(SECTIONS, "Risk Factors")


def test_analyze_categories_covers_every_category():
    payload = {"severity": "green", "findings": [{"summary": NOTHING_MATERIAL, "citation": None}]}
    with patch("app.services.filing_analysis.analyze_category",
               side_effect=lambda s, c: {"name": c, "severity": "green", "findings": payload["findings"]}):
        results = analyze_categories(SECTIONS)
    assert {r["name"] for r in results} == set(CATEGORY_NAMES)


def test_analyze_categories_survives_one_category_failing():
    """Five good categories are worth more than a whole failed analysis."""
    def flaky(sections, category):
        if category == "Risk Factors":
            raise RuntimeError("rate limited")
        return {"name": category, "severity": "green", "findings": []}

    with patch("app.services.filing_analysis.analyze_category", side_effect=flaky):
        results = analyze_categories(SECTIONS)

    assert len(results) == len(CATEGORY_NAMES)
    failed = next(r for r in results if r["name"] == "Risk Factors")
    assert "could not be analyzed" in failed["findings"][0]["summary"]
    assert "rate limited" in failed["findings"][0]["summary"]


def test_analyze_overview_passes_screens_and_history_to_claude():
    payload = {"intro": "Revenue grew 8%.", "verdict": "review", "keyMetrics": {"totalRevenue": "$391B"}}
    client = _claude_returning(payload)
    with patch("app.services.filing_analysis._client", return_value=client):
        result = filing_analysis.analyze_overview(
            [{"name": "Risk Factors", "severity": "red", "findings": [{"summary": "Supplier risk."}]}],
            {"name": "Apple Inc.", "ticker": "AAPL"},
            [{"fiscalYear": 2025, "revenue": 391_000_000_000.0}],
            {"screens": [{"key": "beneish_m", "value": -2.4}], "flags": []},
        )

    sent = client.with_options.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "beneish_m" in sent
    assert "Supplier risk." in sent
    assert result["verdict"] == "review"
