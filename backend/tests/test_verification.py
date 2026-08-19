import random
import string
import time

import pytest

from app.services.verification import (
    FUZZY_MIN_SCORE,
    METRIC_TO_XBRL_FIELD,
    PLACEHOLDER_SUMMARY,
    VERIFICATION_STATUSES,
    VerificationError,
    _normalized_source,
    extract_figures,
    normalize_for_matching,
    parse_monetary,
    verify_figure,
    verify_finding,
    verify_findings,
    verify_key_metrics,
    verify_quote,
)

# A short stretch of filing prose with the typography EDGAR actually emits: a curly
# apostrophe, curly double quotes and an em dash.
SOURCE = (
    "Item 1A. Risk Factors\n"
    "The Company’s business is subject to a variety of risks. "
    "Total net sales increased 2% or $8.0 billion during 2024 compared to 2023 due "
    "primarily to higher net sales of Services. "
    "The Company is subject to various legal proceedings and claims that have arisen in "
    "the ordinary course of business and that have not been fully resolved — the "
    "outcome of litigation is inherently uncertain. "
    "The Company relies on “single source” outsourcing partners in Asia for the "
    "manufacture and assembly of most of its products, which subjects the Company to "
    "significant supply and pricing risks."
)


def _finding(summary, quote=None, section=None):
    citation = None if quote is None else {"quote": quote, "page": 12, "section": section}
    return {"summary": summary, "citation": citation}


# ---------------------------------------------------------------------------
# normalize_for_matching
# ---------------------------------------------------------------------------


def test_normalize_folds_curly_quotes_and_dashes():
    assert normalize_for_matching("The Company’s “plan”") == "the company's \"plan\""
    assert normalize_for_matching("2024–2025") == "2024-2025"
    assert normalize_for_matching("risk — factors") == "risk - factors"


def test_normalize_collapses_whitespace_and_case():
    assert normalize_for_matching("  Total   net\n\nsales   rose ") == "total net sales rose"


def test_normalize_strips_accents_and_zero_width_characters():
    # Precomposed and decomposed forms have to land on the same string, or a quote
    # retyped by the model would fail against an identical source.
    assert normalize_for_matching("Señor") == normalize_for_matching("Señor")
    assert normalize_for_matching("soft­hyphen") == "softhyphen"
    assert normalize_for_matching("zero​width") == "zerowidth"


def test_normalize_expands_ellipsis_to_periods():
    assert normalize_for_matching("and so on…") == "and so on..."


def test_normalize_handles_empty_input():
    assert normalize_for_matching("") == ""


# ---------------------------------------------------------------------------
# verify_quote: the ladder
# ---------------------------------------------------------------------------


def test_verify_quote_exact_match():
    quote = "Total net sales increased 2% or $8.0 billion during 2024"
    result = verify_quote(quote, SOURCE)

    assert result["status"] == "exact"
    assert result["score"] == 1.0
    assert result["matchedText"] == quote
    assert SOURCE[result["offset"]:result["offset"] + len(quote)] == quote


def test_verify_quote_curly_quotes_match_as_normalized():
    # The model retyped the curly apostrophe and curly double quotes as straight ones.
    quote = "The Company relies on \"single source\" outsourcing partners in Asia"
    result = verify_quote(quote, SOURCE)

    assert result["status"] == "normalized"
    assert result["score"] == 1.0
    assert "“single source”" in result["matchedText"]


def test_verify_quote_straight_apostrophe_matches_curly_source():
    result = verify_quote("The Company's business is subject to a variety of risks", SOURCE)
    assert result["status"] == "normalized"


def test_verify_quote_hyphen_matches_em_dash_as_normalized():
    quote = "have not been fully resolved - the outcome of litigation is inherently uncertain"
    result = verify_quote(quote, SOURCE)

    assert result["status"] == "normalized"
    assert "—" in result["matchedText"]


def test_verify_quote_whitespace_and_case_differences_are_normalized():
    quote = "TOTAL NET SALES INCREASED 2%\n  OR $8.0 BILLION"
    assert verify_quote(quote, SOURCE)["status"] == "normalized"


def test_verify_quote_ignores_added_ellipsis_and_trailing_punctuation():
    quote = "…higher net sales of Services,"
    assert verify_quote(quote, SOURCE)["status"] == "normalized"


def test_verify_quote_normalized_offset_maps_back_to_original_text():
    quote = "The Company's business is subject to a variety of risks"
    result = verify_quote(quote, SOURCE)

    start = result["offset"]
    assert SOURCE[start:start + len(result["matchedText"])] == result["matchedText"]
    assert normalize_for_matching(result["matchedText"]) == normalize_for_matching(quote)


def test_verify_quote_fabricated_quote_is_not_found():
    quote = (
        "The Company recorded a goodwill impairment charge related to its European "
        "reporting unit following the annual impairment test."
    )
    result = verify_quote(quote, SOURCE)

    assert result["status"] == "not_found"
    assert result["score"] < FUZZY_MIN_SCORE
    assert result["matchedText"] is None
    assert result["offset"] is None


def test_verify_quote_paraphrase_lands_in_fuzzy():
    # Same passage, reworded: a soft pass the caller must surface as a paraphrase.
    quote = (
        "The Company is subject to various legal proceedings and to claims arising in "
        "the ordinary course of its business that have not yet been fully resolved"
    )
    result = verify_quote(quote, SOURCE)

    assert result["status"] == "fuzzy"
    assert FUZZY_MIN_SCORE <= result["score"] < 1.0
    assert "legal proceedings" in result["matchedText"]
    start = result["offset"]
    assert SOURCE[start:start + len(result["matchedText"])] == result["matchedText"]


def test_similarity_floor_is_what_decides_fuzzy_versus_not_found(monkeypatch):
    quote = (
        "The Company is subject to various legal proceedings and to claims arising in "
        "the ordinary course of its business that have not yet been fully resolved"
    )
    baseline = verify_quote(quote, SOURCE)
    assert baseline["status"] == "fuzzy"

    # Raise the floor just past the score this match earned: same text, now a fail.
    monkeypatch.setattr("app.services.verification.FUZZY_MIN_SCORE", baseline["score"] + 0.001)
    assert verify_quote(quote, SOURCE)["status"] == "not_found"

    # Drop the floor to exactly the score: the boundary is inclusive, so it passes.
    monkeypatch.setattr("app.services.verification.FUZZY_MIN_SCORE", baseline["score"])
    assert verify_quote(quote, SOURCE)["status"] == "fuzzy"


def test_verify_quote_rejects_a_paraphrase_that_alters_the_figures():
    # Wording is 90%+ similar, but the filing says "increased 2% or $8.0 billion".
    # Restating it with different numbers is a fabricated claim, not a paraphrase.
    quote = (
        "Total net sales decreased 12% or $48.0 billion during 2024 compared to 2023 "
        "due primarily to lower net sales of Services."
    )
    result = verify_quote(quote, SOURCE)

    assert result["status"] == "not_found"
    assert result["score"] >= FUZZY_MIN_SCORE  # the wording alone would have passed


def test_altered_figure_rejection_can_be_switched_off(monkeypatch):
    monkeypatch.setattr("app.services.verification.REJECT_ON_ALTERED_FIGURES", False)
    quote = (
        "Total net sales decreased 12% or $48.0 billion during 2024 compared to 2023 "
        "due primarily to lower net sales of Services."
    )
    assert verify_quote(quote, SOURCE)["status"] == "fuzzy"


def test_verify_quote_tolerates_equivalent_figure_formatting():
    quote = "Total net sales increased 2% or $8 billion during 2024 as compared to 2023"
    assert verify_quote(quote, SOURCE)["status"] == "fuzzy"


def test_verify_quote_handles_empty_inputs():
    for result in (verify_quote("", SOURCE), verify_quote("anything", ""), verify_quote("   ", SOURCE)):
        assert result["status"] == "not_found"
        assert result["score"] == 0.0
        assert result["matchedText"] is None
        assert result["offset"] is None


def test_verify_quote_returns_only_documented_statuses():
    for quote in ("Total net sales increased 2%", "wholly invented sentence about nothing"):
        assert verify_quote(quote, SOURCE)["status"] in ("exact", "normalized", "fuzzy", "not_found")


# ---------------------------------------------------------------------------
# performance guard
# ---------------------------------------------------------------------------


def _large_source(target: str) -> str:
    """~250k characters of filing-shaped filler with `target` buried in the middle."""
    rng = random.Random(1234)
    vocabulary = [
        "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 11)))
        for _ in range(3000)
    ]
    filler = " ".join(rng.choices(vocabulary, k=34000))
    midpoint = len(filler) // 2
    text = filler[:midpoint] + " " + target + " " + filler[midpoint:]
    assert 240_000 <= len(text) <= 290_000, len(text)
    return text


LARGE_TARGET = (
    "The aggregate principal amount of senior notes outstanding was approximately "
    "$14.6 billion as of the end of the fiscal year, of which $2.1 billion matures "
    "within twelve months."
)


@pytest.mark.parametrize(
    "quote",
    [
        LARGE_TARGET,
        LARGE_TARGET.replace("approximately", "approx.").replace("of which", "and"),
        "The board of directors declared a special dividend payable to shareholders "
        "of record in December of the following year.",
    ],
    ids=["exact", "paraphrase", "fabricated"],
)
def test_verify_quote_is_fast_on_a_quarter_million_character_source(quote):
    source = _large_source(LARGE_TARGET)

    # Time the cold path: normalization of the source is part of what must stay fast.
    _normalized_source.cache_clear()
    started = time.perf_counter()
    result = verify_quote(quote, source)
    elapsed = time.perf_counter() - started

    assert result["status"] in ("exact", "normalized", "fuzzy", "not_found")
    assert elapsed < 1.0, f"verify_quote took {elapsed:.3f}s on {len(source)} characters"


def test_verify_quote_finds_a_buried_quote_in_a_large_source():
    source = _large_source(LARGE_TARGET)
    result = verify_quote(LARGE_TARGET, source)

    assert result["status"] == "exact"
    assert source[result["offset"]:result["offset"] + len(LARGE_TARGET)] == LARGE_TARGET


# ---------------------------------------------------------------------------
# parse_monetary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$391.0 billion", 391_000_000_000.0),
        ("$391.0 Billion", 391_000_000_000.0),
        ("$1.2 bn", 1_200_000_000.0),
        ("$1.2bn", 1_200_000_000.0),
        ("$1.2B", 1_200_000_000.0),
        ("$93,736 million", 93_736_000_000.0),
        ("$93,736 mm", 93_736_000_000.0),
        ("$5 M", 5_000_000.0),
        ("$412 thousand", 412_000.0),
        ("$412K", 412_000.0),
        ("$1.1 trillion", 1_100_000_000_000.0),
        ("$1.1T", 1_100_000_000_000.0),
        ("$391,035", 391_035.0),
        ("$1,234.56", 1_234.56),
        ("391035", 391_035.0),
        ("391,035", 391_035.0),
        ("3.5 billion", 3_500_000_000.0),
        ("USD 1.2 million", 1_200_000.0),
        ("revenue of $391,035", 391_035.0),
        ("$391.0 billion in fiscal 2024", 391_000_000_000.0),
        ("  $8.0 billion  ", 8_000_000_000.0),
    ],
)
def test_parse_monetary_supported_formats(text, expected):
    assert parse_monetary(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("(1,234)", -1234.0),
        ("$(1,234)", -1234.0),
        ("($1.2 billion)", -1_200_000_000.0),
        ("-$1.2 billion", -1_200_000_000.0),
        ("-1,234", -1234.0),
        ("−1,234", -1234.0),
    ],
)
def test_parse_monetary_negatives(text, expected):
    assert parse_monetary(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "N/A",
        "not disclosed",
        "12.5%",
        "$1.2 billion, up 12.5%",
        "3.5x",
        "AAPL",
        "1,234 shares outstanding",
        "fiscal 2024",
        123,
    ],
)
def test_parse_monetary_rejects_non_monetary_input(text):
    assert parse_monetary(text) is None


# ---------------------------------------------------------------------------
# extract_figures
# ---------------------------------------------------------------------------


def test_extract_figures_finds_monetary_and_percentage_values():
    sentence = "Revenue of $391.0 billion rose 2% while operating cash flow reached $118,254 million."
    figures = extract_figures(sentence)

    kinds = [(f["kind"], f["value"]) for f in figures]
    assert ("monetary", 391_000_000_000.0) in kinds
    assert ("percent", 2.0) in kinds
    assert ("monetary", 118_254_000_000.0) in kinds
    for figure in figures:
        assert sentence[figure["start"]:figure["end"]].strip() == figure["text"]


def test_extract_figures_skips_bare_numbers():
    # A year or an Item number is not a quantity to check against XBRL.
    assert extract_figures("In 2024 the Company filed its Item 7 disclosure.") == []


def test_extract_figures_handles_parenthesised_negative():
    figures = extract_figures("Other income/(expense) was $(1,234) for the period.")
    assert [f["value"] for f in figures] == [-1234.0]


def test_extract_figures_on_empty_input():
    assert extract_figures("") == []
    assert extract_figures(None) == []


# ---------------------------------------------------------------------------
# verify_figure
# ---------------------------------------------------------------------------


def test_verify_figure_accepts_rounding_down():
    result = verify_figure("$391.0 billion", 391_035_000_000.0)

    assert result["status"] == "match"
    assert result["stated"] == 391_000_000_000.0
    assert result["actual"] == 391_035_000_000.0
    assert result["deltaPercent"] == pytest.approx(0.009, abs=0.001)


def test_verify_figure_accepts_rounding_up():
    # Rounding direction must not matter: the tolerance is symmetric.
    result = verify_figure("$391.0 billion", 390_965_000_000.0)
    assert result["status"] == "match"
    assert result["deltaPercent"] == pytest.approx(0.009, abs=0.001)


def test_verify_figure_flags_a_real_mismatch():
    result = verify_figure("$391.0 billion", 294_000_000_000.0)

    assert result["status"] == "mismatch"
    assert result["deltaPercent"] > 1.0


def test_verify_figure_boundary_of_relative_tolerance():
    assert verify_figure("$100", 100.9)["status"] == "match"       # 0.89% off
    assert verify_figure("$100", 101.1)["status"] == "mismatch"    # 1.09% off
    assert verify_figure("$100", 101.0)["status"] == "match"       # exactly 0.99% off
    assert verify_figure("$100", 101.1, tolerance=0.05)["status"] == "match"


def test_verify_figure_is_unverifiable_when_xbrl_value_is_missing():
    result = verify_figure("$391.0 billion", None)

    assert result["status"] == "unverifiable"
    assert result["stated"] == 391_000_000_000.0
    assert result["actual"] is None
    assert result["deltaPercent"] is None


def test_verify_figure_is_unverifiable_when_the_statement_is_not_a_number():
    result = verify_figure("not disclosed", 391_035_000_000.0)

    assert result["status"] == "unverifiable"
    assert result["stated"] is None
    assert result["actual"] == 391_035_000_000.0


def test_verify_figure_handles_zero_and_negative_values():
    assert verify_figure("$0", 0.0)["status"] == "match"
    assert verify_figure("$1,000", 0.0)["status"] == "mismatch"
    assert verify_figure("$(1,234)", -1234.0)["status"] == "match"
    assert verify_figure("$1,234", -1234.0)["status"] == "mismatch"


def test_verify_figure_rejects_a_negative_tolerance():
    with pytest.raises(VerificationError, match="tolerance"):
        verify_figure("$100", 100.0, tolerance=-0.1)


# ---------------------------------------------------------------------------
# verify_key_metrics
# ---------------------------------------------------------------------------


FISCAL_YEAR = {
    "fiscalYear": 2024,
    "revenue": 391_035_000_000.0,
    "netIncome": 93_736_000_000.0,
    "totalDebt": None,
    "cash": 29_943_000_000.0,
    "operatingCashFlow": 118_254_000_000.0,
    "totalAssets": 364_980_000_000.0,
    "stockholdersEquity": 56_950_000_000.0,
}


def test_verify_key_metrics_reports_each_field():
    key_metrics = {
        "totalRevenue": "$391.0 billion",
        "netIncome": "$93.7 billion",
        "operatingCashFlow": "$118.3 billion",
        "cashAndEquivalents": "$40.8 billion",   # wrong: XBRL says 29.9
        "totalDebt": "$106.6 billion",           # never tagged
        "tickerSymbol": "AAPL",
    }
    result = verify_key_metrics(key_metrics, FISCAL_YEAR)
    metrics = result["metrics"]

    assert metrics["totalRevenue"]["status"] == "match"
    assert metrics["totalRevenue"]["xbrlField"] == "revenue"
    assert metrics["netIncome"]["status"] == "match"
    assert metrics["operatingCashFlow"]["status"] == "match"
    assert metrics["cashAndEquivalents"]["status"] == "mismatch"
    assert result["fiscalYear"] == 2024


def test_verify_key_metrics_never_calls_an_untagged_field_a_mismatch():
    result = verify_key_metrics({"totalDebt": "$106.6 billion"}, FISCAL_YEAR)

    entry = result["metrics"]["totalDebt"]
    assert entry["status"] == "unverifiable"
    assert entry["actual"] is None
    assert entry["stated"] == 106_600_000_000.0


def test_verify_key_metrics_skips_non_monetary_and_unstated_fields():
    result = verify_key_metrics(
        {"tickerSymbol": "AAPL", "totalRevenue": None, "netIncome": "", "somethingElse": "$5"},
        FISCAL_YEAR,
    )
    assert result["metrics"] == {}
    assert result["stats"] == {"match": 0, "mismatch": 0, "unverifiable": 0}


def test_verify_key_metrics_stats_add_up():
    key_metrics = {
        "totalRevenue": "$391.0 billion",
        "netIncome": "$93.7 billion",
        "cashAndEquivalents": "$40.8 billion",
        "totalDebt": "$106.6 billion",
    }
    result = verify_key_metrics(key_metrics, FISCAL_YEAR)

    assert result["stats"] == {"match": 2, "mismatch": 1, "unverifiable": 1}
    assert sum(result["stats"].values()) == len(result["metrics"])


def test_verify_key_metrics_handles_missing_inputs():
    assert verify_key_metrics(None, None)["metrics"] == {}
    assert verify_key_metrics({"totalRevenue": "$391.0 billion"}, {})["metrics"]["totalRevenue"][
        "status"
    ] == "unverifiable"


def test_metric_mapping_table_covers_the_model_key_metrics_fields():
    for field in ("totalRevenue", "netIncome", "totalDebt", "cashAndEquivalents", "operatingCashFlow"):
        assert field in METRIC_TO_XBRL_FIELD


# ---------------------------------------------------------------------------
# verify_finding / verify_findings
# ---------------------------------------------------------------------------


def test_verify_finding_exact_quote_is_verified():
    finding = _finding("Services drove growth.", "Total net sales increased 2% or $8.0 billion")
    verified = verify_finding(finding, SOURCE)

    assert verified["verification"]["status"] == "verified"
    assert verified["verification"]["method"] == "exact_quote_match"
    assert verified["verification"]["score"] == 1.0
    assert verified["verification"]["matchedText"]
    assert verified["verification"]["detail"]


def test_verify_finding_normalized_quote_is_verified():
    finding = _finding(
        "Concentration risk in Asia.",
        "The Company relies on \"single source\" outsourcing partners in Asia",
    )
    verified = verify_finding(finding, SOURCE)

    assert verified["verification"]["status"] == "verified"
    assert verified["verification"]["method"] == "normalized_quote_match"


def test_verify_finding_paraphrase_is_marked_paraphrased():
    finding = _finding(
        "Litigation exposure.",
        "The Company is subject to various legal proceedings and to claims arising in "
        "the ordinary course of its business that have not yet been fully resolved",
    )
    verified = verify_finding(finding, SOURCE)

    assert verified["verification"]["status"] == "paraphrased"
    assert verified["verification"]["method"] == "fuzzy_quote_match"
    assert "paraphrase" in verified["verification"]["detail"].lower()


def test_verify_finding_fabricated_quote_is_rejected_but_kept():
    finding = _finding(
        "Goodwill impairment.",
        "The Company recorded a goodwill impairment charge related to its European "
        "reporting unit following the annual impairment test.",
    )
    verified = verify_finding(finding, SOURCE)

    assert verified["verification"]["status"] == "rejected"
    # The finding itself survives untouched so the caller can see what the model did.
    assert verified["summary"] == "Goodwill impairment."
    assert verified["citation"] == finding["citation"]


def test_verify_finding_placeholder_passes_through_unverified():
    finding = {"summary": PLACEHOLDER_SUMMARY, "citation": None}
    verified = verify_finding(finding, SOURCE)

    assert verified["verification"]["status"] == "unverified"
    assert verified["verification"]["method"] == "no_citation"
    assert verified["verification"]["status"] != "rejected"
    assert "placeholder" in verified["verification"]["detail"].lower()


def test_verify_finding_missing_citation_is_unverified_not_rejected():
    for finding in (
        {"summary": "Something the model asserted."},
        _finding("Something else.", quote=""),
        {"summary": "Blank quote.", "citation": {"quote": "   "}},
    ):
        verification = verify_finding(finding, SOURCE)["verification"]
        assert verification["status"] == "unverified"
        assert verification["method"] == "no_citation"


def test_verify_finding_without_source_text_is_unverified():
    finding = _finding("Litigation exposure.", "Total net sales increased 2%")
    verification = verify_finding(finding, "")["verification"]

    assert verification["status"] == "unverified"
    assert verification["method"] == "no_source_text"


def test_verify_finding_does_not_mutate_the_input():
    finding = _finding("Services drove growth.", "Total net sales increased 2% or $8.0 billion")
    verify_finding(finding, SOURCE)
    assert "verification" not in finding


def test_verify_finding_rejects_non_dict_input():
    with pytest.raises(VerificationError):
        verify_finding("not a finding", SOURCE)


def test_verify_findings_stats_add_up():
    findings = [
        _finding("Verified.", "Total net sales increased 2% or $8.0 billion"),
        _finding("Also verified.", "The Company's business is subject to a variety of risks"),
        _finding(
            "Paraphrased.",
            "The Company is subject to various legal proceedings and to claims arising in "
            "the ordinary course of its business that have not yet been fully resolved",
        ),
        _finding(
            "Rejected.",
            "The Company recorded a goodwill impairment charge related to its European "
            "reporting unit following the annual impairment test.",
        ),
        {"summary": PLACEHOLDER_SUMMARY, "citation": None},
    ]

    result = verify_findings(findings, lambda _f: SOURCE)

    assert result["stats"] == {
        "verified": 2,
        "paraphrased": 1,
        "unverified": 1,
        "rejected": 1,
    }
    assert sum(result["stats"].values()) == len(result["findings"])
    assert len(result["findings"]) == len(findings)
    assert set(result["stats"]) == set(VERIFICATION_STATUSES)


def test_verify_findings_routes_each_finding_to_its_own_section():
    other_section = "Item 7. The Company repurchased $95.0 billion of its common stock."
    sections = {"1A": SOURCE, "7": other_section}
    findings = [
        _finding("Buybacks.", "repurchased $95.0 billion of its common stock", section="7"),
        _finding("Buybacks, wrong section.", "repurchased $95.0 billion of its common stock", section="1A"),
    ]

    result = verify_findings(findings, lambda f: sections.get(f["citation"]["section"]))

    assert result["findings"][0]["verification"]["status"] == "verified"
    assert result["findings"][1]["verification"]["status"] == "rejected"
    assert result["stats"]["verified"] == 1
    assert result["stats"]["rejected"] == 1


def test_verify_findings_accepts_a_plain_string_source():
    findings = [_finding("Verified.", "Total net sales increased 2% or $8.0 billion")]
    result = verify_findings(findings, SOURCE)
    assert result["stats"]["verified"] == 1


def test_verify_findings_treats_a_missing_section_as_unverified():
    findings = [_finding("Orphan finding.", "Total net sales increased 2%", section="9Z")]
    result = verify_findings(findings, lambda _f: None)

    assert result["findings"][0]["verification"]["status"] == "unverified"
    assert result["stats"]["unverified"] == 1


def test_verify_findings_on_an_empty_list_still_reports_every_status():
    result = verify_findings([], SOURCE)
    assert result["findings"] == []
    assert result["stats"] == {status: 0 for status in VERIFICATION_STATUSES}


def test_verify_findings_rejects_a_bad_source_lookup():
    with pytest.raises(VerificationError, match="source_lookup"):
        verify_findings([_finding("x", "y")], 42)
