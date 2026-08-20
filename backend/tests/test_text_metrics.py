"""Document-level measurements of a filing.

Nothing here talks to a model or a network, so every expected number is arithmetic a
reader can check against the fixture text directly above it.
"""

from app.services import text_metrics
from app.services.text_metrics import build_text_metrics

# ~600 words of plausible filing prose, which is the floor the density measures need.
FILLER = (
    "The company operates in a competitive market and competes on price and service. "
    "Revenue is recognized when control of the product transfers to the customer. "
) * 30


def sections(**items) -> dict[str, str]:
    return {item: text for item, text in items.items() if text}


def tripwire(result: dict, key: str) -> dict | None:
    return next((t for t in result["tripwires"] if t["key"] == key), None)


# --- size ---------------------------------------------------------------------------


def test_section_sizes_are_measured_against_last_year():
    current = sections(**{"1A": "alpha beta gamma delta", "7": "one two"})
    prior = sections(**{"1A": "alpha beta", "7": "one two"})

    rows = build_text_metrics(current, prior)["sections"]
    risk = next(row for row in rows if row["item"] == "1A")

    assert risk["words"] == 4
    assert risk["priorWords"] == 2
    assert risk["changePercent"] == 100.0
    assert risk["notable"] is True


def test_sections_are_listed_longest_first():
    current = sections(**{"1A": "a b c", "7": "a b c d e", "3": "a"})

    rows = build_text_metrics(current)["sections"]

    assert [row["item"] for row in rows] == ["7", "1A", "3"]
    assert all(row["changePercent"] is None for row in rows)


def test_a_section_with_no_prior_year_counterpart_reports_no_change():
    rows = build_text_metrics(sections(**{"1A": "a b c"}), sections(**{"7": "x"}))["sections"]

    assert rows[0]["priorWords"] is None
    assert rows[0]["notable"] is False


def test_risk_factor_blocks_are_counted_both_years():
    risk_factors = "\n\n".join(f"Risk number {i}. " + FILLER for i in range(4))
    prior_risk_factors = "\n\n".join(f"Risk number {i}. " + FILLER for i in range(2))

    result = build_text_metrics(
        sections(**{"1A": risk_factors}), sections(**{"1A": prior_risk_factors})
    )

    counts = result["riskFactors"]
    assert counts["count"] > counts["priorCount"]
    assert counts["change"] == counts["count"] - counts["priorCount"]
    assert counts["wordChangePercent"] > 0


def test_risk_factor_counts_are_absent_when_the_filing_has_no_item_1a():
    assert build_text_metrics(sections(**{"7": FILLER}))["riskFactors"] is None


# --- readability --------------------------------------------------------------------


def test_readability_reports_both_halves_of_the_fog_index():
    result = build_text_metrics(sections(**{"7": FILLER}))["readability"]

    assert result["wordsPerSentence"] > 0
    assert result["complexWordPercent"] > 0
    assert result["fogIndex"] == round(
        0.4 * (result["wordsPerSentence"] + result["complexWordPercent"]), 1
    )
    # The verdict rests on sentence length, and says so.
    assert "sentence length is the more reliable half" in result["interpretation"]


def test_very_long_sentences_are_graded_red():
    long_sentence = (
        "The company believes that its results of operations for the period presented "
        "were affected by a number of factors including but not limited to competitive "
        "pricing pressure supply chain disruption regulatory developments and general "
        "macroeconomic conditions in the markets in which it operates worldwide. "
    ) * 40

    result = build_text_metrics(sections(**{"7": long_sentence}))["readability"]

    assert result["wordsPerSentence"] >= 40
    assert result["severity"] == "red"


def test_short_sentences_are_graded_green():
    result = build_text_metrics(sections(**{"7": FILLER}))["readability"]

    assert result["severity"] == "green"


def test_readability_is_omitted_on_too_little_prose():
    assert build_text_metrics(sections(**{"7": "Short filing."}))["readability"] is None


def test_sentence_splitting_does_not_break_on_abbreviations():
    text = "Acme Corp. sells widgets in the U.S. market. Revenue grew."

    assert text_metrics._sentences(text) == [
        "Acme Corp. sells widgets in the U.S. market.",
        "Revenue grew.",
    ]


def test_inflected_endings_do_not_make_a_word_complex():
    # Fog's own rule: "expected" reaches three syllables only because of the -ed.
    assert text_metrics._is_complex("expected") is False
    # "operated" is complex on its own stem (op-er-at), so the rule does not save it.
    assert text_metrics._is_complex("operated") is True
    assert text_metrics._is_complex("amortization") is True
    assert text_metrics._is_complex("market") is False


# --- hedging ------------------------------------------------------------------------


def test_uncertainty_density_is_measured_per_thousand_words():
    hedged = ("The company may possibly experience uncertain results. " * 60) + FILLER

    result = build_text_metrics(sections(**{"7": hedged}))["hedging"]

    assert result["per1000"] > 0
    assert {term["term"] for term in result["topTerms"]} & {"may", "possibly", "uncertain"}


def test_rising_hedging_against_last_year_is_flagged():
    hedged = ("Results may possibly prove uncertain and could fluctuate. " * 80) + FILLER
    plain = FILLER * 2

    result = build_text_metrics(sections(**{"7": hedged}), sections(**{"7": plain}))["hedging"]

    assert result["change"] > 0
    assert result["severity"] == "yellow"
    assert "up" in result["interpretation"]


def test_steady_hedging_is_not_flagged():
    result = build_text_metrics(sections(**{"7": FILLER}), sections(**{"7": FILLER}))["hedging"]

    assert result["severity"] == "green"
    assert result["change"] == 0.0


def test_hedging_is_omitted_on_too_little_prose():
    assert build_text_metrics(sections(**{"7": "Too short."}))["hedging"] is None


# --- tripwires ----------------------------------------------------------------------


def test_going_concern_language_is_found_with_its_sentence():
    text = (
        FILLER
        + "These conditions raise substantial doubt about our ability to continue as a "
        "going concern for the twelve months following issuance of these statements."
    )

    found = tripwire(build_text_metrics(sections(**{"7": text})), "going_concern")

    assert found["severity"] == "red"
    assert "substantial doubt" in found["occurrences"][0]["quote"]
    assert found["occurrences"][0]["section"] == "Item 7. Management's Discussion and Analysis"


def test_hypothetical_risk_factor_language_does_not_fire_a_tripwire():
    """Item 1A describes what would happen if a weakness were ever found. It is not one."""
    boilerplate = (
        FILLER
        + "If we identify a material weakness in our internal control over financial "
        "reporting, investors could lose confidence in our reported results."
    )

    assert tripwire(build_text_metrics(sections(**{"1A": boilerplate})), "material_weakness") is None


def test_a_stated_material_weakness_fires_and_counts_the_hypothetical_mentions_apart():
    filing = sections(
        **{
            "1A": FILLER
            + "If we fail to remediate, a material weakness could harm our share price.",
            "9A": "Management concluded that a material weakness existed in our controls "
            "over revenue recognition as of December 31, 2025.",
        }
    )

    found = tripwire(build_text_metrics(filing), "material_weakness")

    assert found["count"] == 1
    assert found["hypotheticalCount"] == 1
    assert found["occurrences"][0]["section"].startswith("Item 9A")


def test_statements_of_fact_are_listed_before_conditional_mentions():
    filing = sections(
        **{
            "3": "The Company received a subpoena from the SEC in March 2026 seeking "
            "documents related to its revenue recognition practices.",
            "1A": FILLER + "We may receive a subpoena in the future, which could be costly.",
        }
    )

    found = tripwire(build_text_metrics(filing), "government_investigation")

    assert found["occurrences"][0]["quote"].startswith("The Company received a subpoena")


def test_covenant_default_language_is_found():
    text = "An event of default occurred under our credit agreement in June 2026."

    found = tripwire(build_text_metrics(sections(**{"7": text})), "covenant_trouble")

    assert found["severity"] == "yellow"


def test_a_clean_filing_fires_no_tripwires():
    assert build_text_metrics(sections(**{"7": FILLER, "1A": FILLER}))["tripwires"] == []


def test_long_sentences_are_clipped_in_the_quote():
    sentence = "The Company received a subpoena " + ("and more text " * 80) + "in 2026."

    found = tripwire(build_text_metrics(sections(**{"3": sentence})), "government_investigation")

    assert len(found["occurrences"][0]["quote"]) <= 324
    assert found["occurrences"][0]["quote"].endswith("...")


def test_at_most_three_occurrences_are_kept():
    text = " ".join(
        f"The Company received a subpoena from the SEC in case number {i}." for i in range(6)
    )

    found = tripwire(build_text_metrics(sections(**{"3": text})), "government_investigation")

    assert found["count"] == 6
    assert len(found["occurrences"]) == 3


# --- degradation --------------------------------------------------------------------


def test_no_sections_returns_none():
    assert build_text_metrics({}) is None


def test_everything_degrades_independently_of_the_prior_year():
    result = build_text_metrics(sections(**{"1A": FILLER, "7": FILLER}), None, current_year=2026)

    assert result["priorYear"] is None
    assert result["readability"] is not None
    assert result["hedging"]["priorPer1000"] is None
    assert result["riskFactors"]["priorCount"] is None
