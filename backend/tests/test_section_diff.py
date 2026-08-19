import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services import section_diff
from app.services.section_diff import (
    SectionDiffError,
    align_units,
    analyze_section_diff,
    diff_section,
    split_into_units,
    word_level_redline,
)

# --------------------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------------------

_SUPPLY_CHAIN_CLAUSE = (
    "A disruption at any one of these partners would materially reduce the Company's "
    "ability to deliver products on schedule."
)

# Each paragraph is one physical line so tests can rewrite clauses with a plain str.replace.
HEADED_SECTION = "\n\n".join([
    "Item 1A. Risk Factors",
    "The following summarizes factors that could have a material adverse effect on the "
    "Company's business, results of operations and financial condition. These risks are "
    "not exhaustive and should not be considered a complete statement of all potential "
    "risks the Company faces.",
    "Supply Chain Concentration",
    "The Company depends on a small number of outsourcing partners located outside the "
    "United States for the manufacture and assembly of substantially all of its hardware "
    "products. " + _SUPPLY_CHAIN_CLAUSE,
    "The Company does not maintain long-term supply contracts with most of these partners, "
    "and component pricing is negotiated on a rolling basis. Sudden increases in component "
    "cost are absorbed by the Company rather than passed through to customers.",
    "1. Regulatory Proceedings",
    "The Company is the subject of civil and criminal investigations by several regulators "
    "in Europe and the United States. An adverse outcome could result in substantial fines "
    "and mandated changes to the Company's commercial terms with developers, which could "
    "reduce the revenue the Company derives from its services business.",
    "• Climate and Environmental Exposure",
    "Physical climate risk threatens the Company's facilities and those of its suppliers. "
    "Severe weather events have already interrupted production at two supplier facilities "
    "in the last three years, and the frequency of such events is expected to increase.",
]) + "\n"

# Same section with the supply-chain factor materially reworded: a hedge is dropped and a
# new sentence about alternative sourcing is added.
REWORDED_SECTION = HEADED_SECTION.replace(
    _SUPPLY_CHAIN_CLAUSE,
    "A disruption at any one of these partners would eliminate the Company's ability to "
    "deliver products on schedule, and the Company has not qualified alternative sources "
    "for several critical components used in its flagship hardware products.",
)

PROSE_SECTION = (
    "The Company's operations depend significantly on global and regional economic conditions "
    "and adverse economic conditions can materially adversely affect the business.\n\n"
    "Adverse macroeconomic conditions, including slow growth or recession, high unemployment, "
    "inflation, tighter credit and higher interest rates, can adversely impact consumer "
    "confidence and spending and materially reduce demand for the Company's products. In "
    "addition, consumer confidence can be affected by changes in fiscal and monetary policy.\n\n"
    "Uncertainty about a decline in global economic conditions can also have a significant "
    "impact on the Company's suppliers, contract manufacturers, logistics providers and other "
    "channel partners. Potential outcomes include financial instability and insolvency.\n\n"
    "Adverse economic conditions can also lead to increased credit and collectibility risk on "
    "the Company's trade receivables and limitations on the Company's ability to issue new "
    "debt at acceptable rates.\n"
)


def _make_unit(heading: str, words: list[str]) -> dict:
    body = " ".join(words) + "."
    return {"heading": heading, "body": body, "index": 0}


def _numbered_words(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{i:03d}" for i in range(count)]


def _unit_pair_with_edits(edits: int, count: int = 100) -> tuple[dict, dict]:
    """Two units differing by exactly ``edits`` replaced words.

    difflib's ratio is 2*matches/total, so with a shared 3-word heading the pair scores
    exactly ``(count + 3 - edits) / (count + 3)`` — which lets the threshold boundaries be
    asserted precisely instead of approximately.
    """
    heading = "Alpha Beta Gamma"
    prior_words = _numbered_words("kappa", count)
    current_words = list(prior_words)
    for i in range(edits):
        current_words[i] = f"omega{i:03d}"
    return _make_unit(heading, prior_words), _make_unit(heading, current_words)


def _default_quote(item: dict) -> str:
    """A quote that is genuinely verbatim in the source, for either kind of item.

    For an addition or removal the item text *is* filing text. For a rewording the item
    text is a marked-up redline, so the longest unchanged run is used instead — those runs
    are contiguous spans lifted straight out of both years' prose.
    """
    if item["changeType"] != "reworded":
        return item["text"][:120]
    equals = [s["text"] for s in item["redline"] if s["op"] == "equal" and s["text"] != "\u2026"]
    return max(equals, key=len)[:200]


def _fake_analyze(quote_for=None, severities=None, skip_ids=()):
    """Stage-2 stub that echoes back one finding per item, quoting real source text."""
    captured = {}

    def analyze(items, section_label, prior_year, current_year):
        captured["items"] = items
        captured["section_label"] = section_label
        changes = []
        for item in items:
            if item["id"] in skip_ids:
                continue
            quote = quote_for(item) if quote_for else _default_quote(item)
            changes.append(
                {
                    "id": item["id"],
                    "severity": (severities or {}).get(item["id"], "yellow"),
                    "significance": f"Item {item['id']} matters because of {item['changeType']}.",
                    "quote": quote,
                }
            )
        return {"changes": changes}

    analyze.captured = captured
    return analyze


# --------------------------------------------------------------------------------------
# split_into_units
# --------------------------------------------------------------------------------------


def test_split_into_units_detects_realistic_heading_shapes():
    units = split_into_units(HEADED_SECTION)
    headings = [u["heading"] for u in units]

    assert "Supply Chain Concentration" in headings
    assert "1. Regulatory Proceedings" in headings
    assert "• Climate and Environmental Exposure" in headings
    assert "Item 1A. Risk Factors" in headings


def test_split_into_units_attaches_body_to_its_heading():
    units = {u["heading"]: u["body"] for u in split_into_units(HEADED_SECTION)}
    assert "outsourcing partners" in units["Supply Chain Concentration"]
    # The trailing paragraph before the next heading belongs to the same unit.
    assert "long-term supply contracts" in units["Supply Chain Concentration"]
    assert "outsourcing partners" not in units["1. Regulatory Proceedings"]


def test_split_into_units_indexes_sequentially():
    units = split_into_units(HEADED_SECTION)
    assert [u["index"] for u in units] == list(range(len(units)))


def test_split_into_units_falls_back_to_paragraph_grouping_without_headings():
    units = split_into_units(PROSE_SECTION)
    assert len(units) >= 1
    # Every unit is labelled even though the source has no heading lines.
    assert all(u["heading"] for u in units)
    assert all(u["body"] for u in units)
    # And the fallback keeps all the prose.
    joined = " ".join(u["body"] for u in units)
    assert "collectibility risk" in joined
    assert "contract manufacturers" in joined


def test_split_into_units_derives_heading_from_first_sentence():
    units = split_into_units(PROSE_SECTION)
    assert units[0]["heading"].startswith("The Company's operations depend significantly")
    assert units[0]["heading"].endswith(".")


def test_split_into_units_splits_oversized_units_at_paragraph_boundaries():
    paragraph = (
        "The Company faces intense competition in every market it serves and competitors "
        "frequently introduce products at lower price points which pressures margins. " * 4
    )
    text = "Competition\n\n" + "\n\n".join(f"{i}. {paragraph}" for i in range(6))
    units = split_into_units(text)
    assert len(units) > 1
    assert all(len(u["body"]) < 6000 for u in units)


def test_split_into_units_drops_running_page_furniture():
    pages = []
    for page in range(4):
        pages.append(f"Acme Corp. | 2025 Form 10-K | {page + 5}")
        pages.append(
            f"Paragraph number {page} describes an operational exposure the Company has "
            f"disclosed in its annual report for several consecutive fiscal years now."
        )
        pages.append(str(page + 5))
    units = split_into_units("\n\n".join(pages))
    joined = " ".join(u["heading"] + " " + u["body"] for u in units)
    assert "Form 10-K" not in joined
    assert "operational exposure" in joined


def test_split_into_units_on_empty_text():
    assert split_into_units("") == []
    assert split_into_units("   \n\n  ") == []


def test_split_into_units_handles_single_line_input():
    units = split_into_units("The Company may be unable to renew its principal lease.")
    assert len(units) == 1
    assert units[0]["body"].startswith("The Company may be unable")


# --------------------------------------------------------------------------------------
# align_units
# --------------------------------------------------------------------------------------


def test_align_units_marks_identical_units_unchanged():
    units = split_into_units(HEADED_SECTION)
    alignment = align_units(units, units)
    assert all(e["status"] == "unchanged" for e in alignment)
    assert len(alignment) == len(units)


def test_align_units_classifies_added_removed_and_reworded():
    prior = split_into_units(HEADED_SECTION)
    # Delete the climate factor entirely and introduce a brand-new one.
    current_text = REWORDED_SECTION.split("• Climate and Environmental Exposure")[0] + (
        "Artificial Intelligence Regulation\n\n"
        "New statutes governing the training and deployment of generative models impose "
        "disclosure obligations on the Company that did not exist in prior periods and may "
        "require the Company to withhold features from certain jurisdictions entirely.\n"
    )
    current = split_into_units(current_text)
    alignment = align_units(prior, current)

    by_status = {}
    for entry in alignment:
        unit = entry["current"] or entry["prior"]
        by_status.setdefault(entry["status"], []).append(unit["heading"])

    assert "Artificial Intelligence Regulation" in by_status["added"]
    assert "• Climate and Environmental Exposure" in by_status["removed"]
    assert "Supply Chain Concentration" in by_status["reworded"]
    assert "1. Regulatory Proceedings" in by_status["unchanged"]


def test_align_units_returns_one_entry_per_unit():
    prior = [_make_unit("Alpha Beta Gamma", _numbered_words("p", 40))]
    current = [
        _make_unit("Delta Epsilon Zeta", _numbered_words("c", 40)),
        _make_unit("Eta Theta Iota", _numbered_words("d", 40)),
    ]
    alignment = align_units(prior, current)
    assert len(alignment) == 3
    assert sorted(e["status"] for e in alignment) == ["added", "added", "removed"]


def test_align_units_unchanged_threshold_boundary():
    # 2 edits over 103 tokens -> 0.9806, at or above the 0.98 unchanged threshold.
    prior, current = _unit_pair_with_edits(2)
    entry = align_units([prior], [current])[0]
    assert entry["similarity"] >= section_diff.UNCHANGED_THRESHOLD
    assert entry["status"] == "unchanged"

    # 3 edits -> 0.9709, just under it.
    prior, current = _unit_pair_with_edits(3)
    entry = align_units([prior], [current])[0]
    assert entry["similarity"] < section_diff.UNCHANGED_THRESHOLD
    assert entry["status"] == "reworded"


def test_align_units_similarity_floor_boundary():
    # 41 edits over 103 tokens -> 0.6019, just above the 0.60 floor: still a pair.
    prior, current = _unit_pair_with_edits(41)
    alignment = align_units([prior], [current])
    assert len(alignment) == 1
    assert alignment[0]["status"] == "reworded"
    assert alignment[0]["similarity"] >= section_diff.SIMILARITY_FLOOR

    # 42 edits -> 0.5922, under the floor: the pair breaks into a removal and an addition.
    prior, current = _unit_pair_with_edits(42)
    alignment = align_units([prior], [current])
    assert sorted(e["status"] for e in alignment) == ["added", "removed"]
    assert all(e["similarity"] is None for e in alignment)


def test_align_units_prefilter_does_not_hide_a_real_match():
    """The cheap length/Dice/quick_ratio gates must never reject a pair above the floor."""
    for edits in (0, 5, 15, 25, 35, 41):
        prior, current = _unit_pair_with_edits(edits)
        statuses = [e["status"] for e in align_units([prior], [current])]
        assert statuses in (["unchanged"], ["reworded"]), (edits, statuses)


def test_align_units_pairs_greedily_with_the_best_candidate():
    base = _numbered_words("kappa", 100)
    near = list(base)
    near[0] = "omega000"
    far = list(base)
    for i in range(30):
        far[i] = f"omega{i:03d}"

    prior = [_make_unit("Alpha Beta Gamma", base)]
    current = [
        _make_unit("Alpha Beta Gamma", far),
        _make_unit("Alpha Beta Gamma", near),
    ]
    alignment = align_units(prior, current)
    matched = [e for e in alignment if e["prior"] is not None]
    assert len(matched) == 1
    # The prior unit pairs with the *near* variant, not the merely-acceptable one.
    assert matched[0]["current"]["body"] == _make_unit("Alpha Beta Gamma", near)["body"]


def test_align_units_handles_empty_sides():
    units = split_into_units(HEADED_SECTION)
    assert all(e["status"] == "added" for e in align_units([], units))
    assert all(e["status"] == "removed" for e in align_units(units, []))
    assert align_units([], []) == []


def test_align_units_60x60_is_fast():
    """O(n*m) is acceptable at this scale only because the cheap gates run first."""

    def make(seed: str, count: int) -> list[dict]:
        units = []
        for i in range(count):
            words = [f"{seed}{i:02d}w{j:03d}" for j in range(220)]
            units.append(
                {"heading": f"Risk Factor {i}", "body": " ".join(words) + ".", "index": i}
            )
        return units

    prior = make("p", 60)
    current = make("c", 60)
    # Make 40 of the current units close variants of their prior counterparts so the
    # expensive ratio() path is genuinely exercised, not gated away.
    for i in range(40):
        words = prior[i]["body"].split()
        for j in range(0, 30):
            words[j] = f"revised{j:03d}"
        current[i] = {"heading": prior[i]["heading"], "body": " ".join(words), "index": i}

    start = time.perf_counter()
    alignment = align_units(prior, current)
    elapsed = time.perf_counter() - start

    assert len(alignment) == 80  # 60 current + 20 unmatched prior
    assert sum(1 for e in alignment if e["status"] == "reworded") == 40
    assert elapsed < 5.0, f"60x60 alignment took {elapsed:.2f}s"


# --------------------------------------------------------------------------------------
# word_level_redline
# --------------------------------------------------------------------------------------


def test_word_level_redline_on_a_known_edit():
    prior = "The Company relies on a single supplier for memory components."
    current = "The Company relies on two suppliers for memory components."
    segments = word_level_redline(prior, current)

    assert [s["op"] for s in segments] == ["equal", "delete", "insert", "equal"]
    assert segments[0]["text"] == "The Company relies on"
    assert segments[1]["text"] == "a single supplier"
    assert segments[2]["text"] == "two suppliers"
    assert segments[3]["text"] == "for memory components."


def test_word_level_redline_pure_insertion_and_deletion():
    inserted = word_level_redline("alpha beta gamma", "alpha beta delta gamma")
    assert {"op": "insert", "text": "delta"} in inserted
    assert not any(s["op"] == "delete" for s in inserted)

    deleted = word_level_redline("alpha beta delta gamma", "alpha beta gamma")
    assert {"op": "delete", "text": "delta"} in deleted
    assert not any(s["op"] == "insert" for s in deleted)


def test_word_level_redline_identical_bodies_are_all_equal():
    segments = word_level_redline("alpha beta gamma", "alpha beta gamma")
    assert [s["op"] for s in segments] == ["equal"]
    assert segments[0]["text"] == "alpha beta gamma"


def test_word_level_redline_elides_the_unchanged_run_between_two_changes():
    filler = _numbered_words("w", 400)
    prior = " ".join(filler)
    current_words = list(filler)
    current_words[100] = "FIRSTCHANGE"
    current_words[300] = "SECONDCHANGE"
    current = " ".join(current_words)

    segments = word_level_redline(prior, current)
    context = section_diff.REDLINE_CONTEXT_WORDS

    ellipsis = [s for s in segments if s["text"] == "…"]
    assert ellipsis, "the 199-word run between the two changes should be elided"
    assert ellipsis[0]["elided"] == 199 - 2 * context

    for segment in segments:
        if segment["op"] == "equal" and segment["text"] != "…":
            assert len(segment["text"].split()) <= 2 * context

    # Both changes survive; only unchanged text is trimmed.
    assert {"op": "insert", "text": "FIRSTCHANGE"} in segments
    assert {"op": "insert", "text": "SECONDCHANGE"} in segments


def test_word_level_redline_trims_the_leading_and_trailing_context():
    filler = _numbered_words("w", 300)
    prior = " ".join(filler)
    current_words = list(filler)
    current_words[150] = "CHANGED"
    segments = word_level_redline(prior, " ".join(current_words))

    context = section_diff.REDLINE_CONTEXT_WORDS
    assert [s["op"] for s in segments] == ["equal", "delete", "insert", "equal"]
    # The head keeps the words immediately before the change, the tail the ones after.
    assert segments[0]["text"].split() == [f"w{i:03d}" for i in range(150 - context, 150)]
    assert segments[0]["elided"] == 150 - context
    assert segments[-1]["text"].split() == [f"w{i:03d}" for i in range(151, 151 + context)]
    assert segments[-1]["elided"] == 149 - context


def test_word_level_redline_keeps_short_unchanged_runs_intact():
    prior = "alpha beta gamma delta epsilon"
    current = "alpha beta ZETA delta epsilon"
    segments = word_level_redline(prior, current)
    assert not any(s["text"] == "…" for s in segments)
    assert not any("elided" in s for s in segments)


# --------------------------------------------------------------------------------------
# diff_section — orchestration
# --------------------------------------------------------------------------------------


def test_diff_section_rejects_empty_inputs():
    with pytest.raises(SectionDiffError, match="prior_text"):
        diff_section("", HEADED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=_fake_analyze())
    with pytest.raises(SectionDiffError, match="current_text"):
        diff_section(HEADED_SECTION, "  ", "Item 1A. Risk Factors", 2024, 2025, analyze=_fake_analyze())


def test_diff_section_with_no_changes_skips_the_model_entirely():
    calls = []

    def analyze(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Stage 2 must not run when nothing changed")

    result = diff_section(
        HEADED_SECTION, HEADED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze
    )
    assert calls == []
    assert result["changes"] == []
    assert result["stats"]["added"] == 0
    assert result["stats"]["removed"] == 0
    assert result["stats"]["reworded"] == 0
    assert result["stats"]["unchanged"] == result["stats"]["currentTotal"]
    assert result["omittedChangeCount"] == 0


def test_diff_section_never_sends_unchanged_units_to_the_model():
    analyze = _fake_analyze()
    diff_section(HEADED_SECTION, REWORDED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    items = analyze.captured["items"]
    assert items, "the reworded unit should have been sent"
    assert all(i["changeType"] in ("added", "removed", "reworded") for i in items)
    # The untouched regulatory factor is nowhere in the payload.
    assert not any("civil and criminal investigations" in i["text"] for i in items)


def test_diff_section_shape_and_stats():
    prior_units = [
        _make_unit("Alpha Beta Gamma", _numbered_words("a", 60)),
        _make_unit("Delta Epsilon Zeta", _numbered_words("b", 60)),
    ]
    prior_text = "\n\n".join(f"{u['heading']}\n\n{u['body']}" for u in prior_units)
    current_units = list(prior_units)
    current_text = prior_text + "\n\nEta Theta Iota\n\n" + " ".join(_numbered_words("n", 60)) + "."

    analyze = _fake_analyze()
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    assert result["section"] == "Item 1A. Risk Factors"
    assert result["priorYear"] == 2024
    assert result["currentYear"] == 2025
    assert set(result["stats"]) == {
        "unchanged", "reworded", "added", "removed", "priorTotal", "currentTotal",
    }
    assert result["stats"] == {
        "unchanged": 2, "reworded": 0, "added": 1, "removed": 0,
        "priorTotal": 2, "currentTotal": 3,
    }
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["changeType"] == "added"
    assert change["heading"] == "Eta Theta Iota"
    assert change["severity"] == "yellow"
    assert change["significance"]
    assert change["redline"] is None
    assert change["similarity"] is None
    assert result["omittedChangeCount"] == 0
    assert len(current_units) == 2  # fixture sanity: prior list was not mutated


def test_diff_section_reworded_change_carries_redline_and_similarity():
    analyze = _fake_analyze(quote_for=lambda item: "would eliminate the Company's ability")
    result = diff_section(
        HEADED_SECTION, REWORDED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze
    )

    reworded = [c for c in result["changes"] if c["changeType"] == "reworded"]
    assert reworded
    change = reworded[0]
    assert isinstance(change["redline"], list)
    assert {"op": "insert", "text": "eliminate"} in change["redline"]
    assert {"op": "delete", "text": "materially reduce"} in change["redline"]
    assert section_diff.SIMILARITY_FLOOR <= change["similarity"] < section_diff.UNCHANGED_THRESHOLD


def test_diff_section_payload_carries_inline_redline_markers():
    analyze = _fake_analyze()
    diff_section(HEADED_SECTION, REWORDED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    reworded = [i for i in analyze.captured["items"] if i["changeType"] == "reworded"]
    assert reworded
    assert "[-materially reduce-]" in reworded[0]["redlineText"]
    assert "{+eliminate+}" in reworded[0]["redlineText"]


def test_reworded_payload_keeps_the_quotable_wording_free_of_redline_markers():
    """The markers appear nowhere in the filing, so a quote containing one can never verify."""
    analyze = _fake_analyze()
    diff_section(HEADED_SECTION, REWORDED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    reworded = [i for i in analyze.captured["items"] if i["changeType"] == "reworded"][0]
    for marker in ("[-", "-]", "{+", "+}"):
        assert marker not in reworded["text"], reworded["text"]
        assert marker not in reworded["priorText"], reworded["priorText"]
    # Both clean blocks must be real filing text, compared the way the verbatim check
    # compares them, so either can be quoted and still verify.
    collapse = section_diff._collapse_ws
    assert collapse(reworded["text"]) in collapse(REWORDED_SECTION)
    assert collapse(reworded["priorText"]) in collapse(HEADED_SECTION)


def test_a_quote_taken_from_the_reworded_current_wording_survives_verification():
    """The end-to-end guarantee: quoting the block we point the model at actually works."""
    def analyze(items, section_label, prior_year, current_year):
        return {
            "changes": [
                {"id": item["id"], "severity": "yellow", "significance": "It matters.",
                 "quote": item["text"][:120]}
                for item in items
            ]
        }

    result = diff_section(
        HEADED_SECTION, REWORDED_SECTION, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze
    )
    assert result["droppedForUnverifiedQuoteCount"] == 0
    assert any(c["changeType"] == "reworded" for c in result["changes"])


def test_diff_section_sorts_removals_first_then_additions_then_rewordings():
    """Deletions are the highest-signal finding, so they lead; severity breaks ties."""
    prior_text = (
        "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n\n"
        "Beta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n\n"
        "Gamma Risk\n\n" + " ".join(_numbered_words("g", 60)) + ".\n"
    )
    gamma_current = _numbered_words("g", 60)
    gamma_current[0] = "mutated000"
    gamma_current[1] = "mutated001"
    gamma_current[2] = "mutated002"
    current_text = (
        "Beta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n\n"
        "Gamma Risk\n\n" + " ".join(gamma_current) + ".\n\n"
        "Delta Risk\n\n" + " ".join(_numbered_words("d", 60)) + ".\n\n"
        "Epsilon Risk\n\n" + " ".join(_numbered_words("e", 60)) + ".\n"
    )

    analyze = _fake_analyze()
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    order = [c["changeType"] for c in result["changes"]]
    assert order == ["removed", "added", "added", "reworded"]
    assert result["changes"][0]["heading"] == "Alpha Risk"


def test_diff_section_sorts_red_before_yellow_before_green_within_a_type():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = (
        prior_text
        + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"
        + "\nGamma Risk\n\n" + " ".join(_numbered_words("g", 60)) + ".\n"
        + "\nDelta Risk\n\n" + " ".join(_numbered_words("d", 60)) + ".\n"
    )

    def analyze(items, *args):
        wanted = {"Beta Risk": "green", "Gamma Risk": "red", "Delta Risk": "yellow"}
        return {
            "changes": [
                {
                    "id": i["id"],
                    "severity": wanted[i["heading"]],
                    "significance": "why it matters",
                    "quote": i["text"][:60],
                }
                for i in items
            ]
        }

    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert [c["heading"] for c in result["changes"]] == ["Gamma Risk", "Delta Risk", "Beta Risk"]
    assert [c["severity"] for c in result["changes"]] == ["red", "yellow", "green"]


# --------------------------------------------------------------------------------------
# Payload budget
# --------------------------------------------------------------------------------------


def _budget_fixture():
    """Two removals plus several rewordings, each unit large enough to matter."""
    removed = ["Removed One", "Removed Two"]
    kept = ["Shared One", "Shared Two", "Shared Three", "Shared Four"]

    prior_parts = []
    current_parts = []
    for name in removed:
        prefix = name.split()[1][:2].lower()
        prior_parts.append(f"{name}\n\n" + " ".join(_numbered_words(f"r{prefix}", 120)) + ".")
    for name in kept:
        prefix = name.split()[1][:3].lower()
        words = _numbered_words(f"s{prefix}", 120)
        prior_parts.append(f"{name}\n\n" + " ".join(words) + ".")
        mutated = list(words)
        for i in range(20):
            mutated[i] = f"mut{prefix}{i:03d}"
        current_parts.append(f"{name}\n\n" + " ".join(mutated) + ".")

    return "\n\n".join(prior_parts) + "\n", "\n\n".join(current_parts) + "\n"


def test_payload_budget_drops_rewordings_before_deletions(monkeypatch):
    prior_text, current_text = _budget_fixture()
    analyze = _fake_analyze()

    # Big enough for the two removals and roughly one rewording, no more.
    monkeypatch.setattr(section_diff, "MAX_DIFF_INPUT_CHARS", 2_600)
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    items = analyze.captured["items"]
    types = [i["changeType"] for i in items]
    assert types.count("removed") == 2, "both deletions must survive the budget"
    assert types.count("reworded") < 4, "rewordings must be the ones trimmed"
    assert result["omittedChangeCount"] == 6 - len(items)
    assert result["omittedChangeCount"] > 0
    # Deletions lead the payload, so trimming from the tail can never reach them.
    assert types[0] == "removed" and types[1] == "removed"


def test_payload_budget_keeps_everything_when_it_fits():
    prior_text, current_text = _budget_fixture()
    analyze = _fake_analyze()
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert len(analyze.captured["items"]) == 6
    assert result["omittedChangeCount"] == 0


def test_payload_budget_prefers_the_most_changed_rewordings(monkeypatch):
    """When rewordings must be trimmed, the ones that changed most are kept."""
    words = _numbered_words("base", 120)
    prior_parts = []
    current_parts = []
    for name, edits in (("Light Edit", 5), ("Heavy Edit", 50)):
        unique = [f"{name.split()[0].lower()}{w}" for w in words]
        prior_parts.append(f"{name}\n\n" + " ".join(unique) + ".")
        mutated = list(unique)
        for i in range(edits):
            mutated[i] = f"z{i:03d}"
        current_parts.append(f"{name}\n\n" + " ".join(mutated) + ".")

    analyze = _fake_analyze()
    monkeypatch.setattr(section_diff, "MAX_DIFF_INPUT_CHARS", 10)
    diff_section(
        "\n\n".join(prior_parts), "\n\n".join(current_parts),
        "Item 1A. Risk Factors", 2024, 2025, analyze=analyze,
    )
    items = analyze.captured["items"]
    assert len(items) == 1
    assert items[0]["heading"] == "Heavy Edit"


# --------------------------------------------------------------------------------------
# Verbatim-quote enforcement
# --------------------------------------------------------------------------------------


def test_hallucinated_quote_is_dropped():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = (
        prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"
        "\nGamma Risk\n\n" + " ".join(_numbered_words("g", 60)) + ".\n"
    )

    def analyze(items, *args):
        changes = []
        for item in items:
            quote = (
                "The Company has entered into a definitive merger agreement."
                if item["heading"] == "Beta Risk"
                else item["text"][:60]
            )
            changes.append(
                {"id": item["id"], "severity": "red", "significance": "matters", "quote": quote}
            )
        return {"changes": changes}

    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)

    headings = [c["heading"] for c in result["changes"]]
    assert "Beta Risk" not in headings
    assert "Gamma Risk" in headings
    assert result["droppedForUnverifiedQuoteCount"] == 1
    assert result["omittedChangeCount"] == 1
    assert result["analyzedChangeCount"] == 1


def test_quote_verification_tolerates_whitespace_differences():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = (
        prior_text
        + "\nBeta Risk\n\nThe Company depends on a single\nsupplier for display panels.\n"
    )

    analyze = _fake_analyze(
        quote_for=lambda item: "The Company depends on a  single   supplier for display panels."
    )
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert result["droppedForUnverifiedQuoteCount"] == 0
    assert result["changes"][0]["quote"] == (
        "The Company depends on a single supplier for display panels."
    )


def test_removed_change_quote_must_come_from_the_prior_filing():
    """A removal's supporting quote lives only in last year's text."""
    prior_text = (
        "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
        "\nRetail Stores\n\nThe Company's retail stores are subject to numerous risks.\n"
    )
    current_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"

    analyze = _fake_analyze(
        quote_for=lambda item: "The Company's retail stores are subject to numerous risks."
    )
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert [c["changeType"] for c in result["changes"]] == ["removed"]
    assert result["droppedForUnverifiedQuoteCount"] == 0


def test_added_change_quoting_only_prior_text_is_dropped():
    prior_text = "Retail Stores\n\nThe Company's retail stores are subject to numerous risks.\n"
    current_text = "Supply Chain\n\n" + " ".join(_numbered_words("s", 60)) + ".\n"

    def analyze(items, *args):
        return {
            "changes": [
                {
                    "id": i["id"],
                    "severity": "red",
                    "significance": "matters",
                    # Real filing text, but from the wrong year for an "added" change.
                    "quote": "The Company's retail stores are subject to numerous risks.",
                }
                for i in items
            ]
        }

    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    added = [c for c in result["changes"] if c["changeType"] == "added"]
    assert added == [], "an addition may only be supported by current-year text"
    assert result["droppedForUnverifiedQuoteCount"] == 1


def test_missing_and_empty_quotes_are_dropped():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = (
        prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"
        "\nGamma Risk\n\n" + " ".join(_numbered_words("g", 60)) + ".\n"
    )

    def analyze(items, *args):
        out = []
        for n, item in enumerate(items):
            quote = {0: None, 1: "   "}.get(n, item["text"][:60])
            out.append({"id": item["id"], "severity": "red", "significance": "m", "quote": quote})
        return {"changes": out}

    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert result["droppedForUnverifiedQuoteCount"] == 2


def test_items_the_model_skips_are_counted_as_omitted():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = (
        prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"
        "\nGamma Risk\n\n" + " ".join(_numbered_words("g", 60)) + ".\n"
    )
    analyze = _fake_analyze(skip_ids={0})
    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert len(result["changes"]) == 1
    assert result["omittedChangeCount"] == 1


def test_unknown_severity_falls_back_to_yellow():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"

    def analyze(items, *args):
        return {
            "changes": [
                {"id": i["id"], "severity": "critical", "significance": "m", "quote": i["text"][:60]}
                for i in items
            ]
        }

    result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)
    assert result["changes"][0]["severity"] == "yellow"


def test_analyzer_failure_becomes_section_diff_error():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"

    def analyze(*args):
        raise RuntimeError("upstream exploded")

    with pytest.raises(SectionDiffError, match="upstream exploded"):
        diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=analyze)


def test_analyzer_returning_garbage_becomes_section_diff_error():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"

    with pytest.raises(SectionDiffError, match="non-object"):
        diff_section(
            prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025,
            analyze=lambda *a: "not a dict",
        )


def test_analyzer_returning_no_changes_key_yields_no_findings():
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = prior_text + "\nBeta Risk\n\n" + " ".join(_numbered_words("b", 60)) + ".\n"
    result = diff_section(
        prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025, analyze=lambda *a: {}
    )
    assert result["changes"] == []
    assert result["omittedChangeCount"] == 1


# --------------------------------------------------------------------------------------
# analyze_section_diff — the real Stage 2, with the network mocked out
# --------------------------------------------------------------------------------------

_ITEMS = [
    {
        "id": 0,
        "changeType": "removed",
        "heading": "Retail Stores",
        "text": "The Company's retail stores are subject to numerous risks.",
        "similarity": None,
        "redline": None,
    },
    {
        "id": 1,
        "changeType": "reworded",
        "heading": "Supply Chain",
        "text": "The Company depends on [-a single supplier-] {+two suppliers+} for displays.",
        "similarity": 0.83,
        "redline": [],
    },
]

_MODEL_RESPONSE = {
    "changes": [
        {
            "id": 0,
            "severity": "red",
            "significance": "Dropping the retail risk implies the company sees store exposure as immaterial.",
            "quote": "The Company's retail stores are subject to numerous risks.",
        },
        {
            "id": 1,
            "severity": "yellow",
            "significance": "Second-sourcing displays reduces single-supplier concentration.",
            "quote": "two suppliers",
        },
    ]
}


def _mock_claude(response_text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.with_options.return_value = mock_client
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_analyze_section_diff_parses_response():
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(json.dumps(_MODEL_RESPONSE))
        result = analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)
    assert len(result["changes"]) == 2
    assert result["changes"][0]["severity"] == "red"


def test_analyze_section_diff_strips_markdown_fences():
    fenced = f"```json\n{json.dumps(_MODEL_RESPONSE)}\n```"
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(fenced)
        result = analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)
    assert len(result["changes"]) == 2


def test_analyze_section_diff_retries_once_with_the_strict_prompt():
    calls = []

    def side_effect(**kwargs):
        calls.append(kwargs)
        msg = MagicMock()
        msg.content = [MagicMock(text="oops" if len(calls) == 1 else json.dumps(_MODEL_RESPONSE))]
        return msg

    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = side_effect
        MockAnthropic.return_value = client
        result = analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)

    assert len(calls) == 2
    assert calls[0]["system"] == section_diff.DIFF_SYSTEM_PROMPT
    assert calls[1]["system"] == section_diff.DIFF_STRICT_SYSTEM_PROMPT
    assert len(result["changes"]) == 2


def test_analyze_section_diff_raises_after_two_malformed_responses():
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude("definitely not json")
        with pytest.raises(ValueError, match="invalid JSON"):
            analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)


def test_analyze_section_diff_bounds_timeout_and_disables_sdk_retries():
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        client = _mock_claude(json.dumps(_MODEL_RESPONSE))
        MockAnthropic.return_value = client
        analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)

    _, kwargs = client.with_options.call_args
    assert kwargs["max_retries"] == 0
    assert 0 < kwargs["timeout"] <= section_diff.DIFF_CLAUDE_BUDGET_SECONDS


def test_analyze_section_diff_raises_timeout_when_budget_exhausted():
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic, patch(
        "app.services.section_diff.time.monotonic"
    ) as monotonic:
        monotonic.side_effect = [0, 0, 10_000]
        client = _mock_claude("not json")
        MockAnthropic.return_value = client
        with pytest.raises(TimeoutError, match="budget"):
            analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)
    client.messages.create.assert_called_once()


def test_analyze_section_diff_prompt_contains_the_items():
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        client = _mock_claude(json.dumps(_MODEL_RESPONSE))
        MockAnthropic.return_value = client
        analyze_section_diff(_ITEMS, "Item 1A. Risk Factors", 2024, 2025)

    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Item 1A. Risk Factors" in content
    assert "FY2024" in content and "FY2025" in content
    assert "id=0 type=REMOVED" in content
    assert "id=1 type=REWORDED" in content
    assert "[-a single supplier-]" in content


def test_diff_section_defaults_to_the_real_analyzer():
    """No `analyze` argument means the module's own Claude call — mocked here, never live."""
    prior_text = "Alpha Risk\n\n" + " ".join(_numbered_words("a", 60)) + ".\n"
    current_text = prior_text + "\nBeta Risk\n\nThe Company added a brand new exposure.\n"

    response = {
        "changes": [
            {
                "id": 0,
                "severity": "red",
                "significance": "A new exposure appeared this year.",
                "quote": "The Company added a brand new exposure.",
            }
        ]
    }
    with patch("app.services.section_diff.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(json.dumps(response))
        result = diff_section(prior_text, current_text, "Item 1A. Risk Factors", 2024, 2025)

    assert len(result["changes"]) == 1
    assert result["changes"][0]["changeType"] == "added"
    assert result["changes"][0]["severity"] == "red"
