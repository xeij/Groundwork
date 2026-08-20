"""Measurements of the filing as a document, taken without a model.

Everything here is arithmetic over the extracted text, which means it is reproducible,
free, and immune to the failure mode that matters most in this codebase: a language
model asserting something about a document that the document does not say. If this
module reports that the phrase "substantial doubt about our ability to continue as a
going concern" appears in Item 7, the sentence it appears in is attached to the finding.

Three things are measured:

* **Size and shape.** How long each Item is and how much it grew. A risk-factor section
  that gains a third of its length in a year has had something added to it, and the
  count of individually comparable risk blocks says whether that was new risks or longer
  ones.
* **How hard it is to read.** Long sentences and long words are how disclosure hides in
  plain sight. Both halves of the Fog index are reported separately because only one of
  them survives scrutiny on filings -- see `readability` below.
* **Tripwires.** A short list of phrases that mean something specific in an annual
  report: going-concern doubt, a material weakness in internal control, a restatement,
  a government investigation. Each one is reported with the sentence it fired on, and
  hypothetical uses are separated from statements of fact, because Item 1A is full of
  sentences describing what *would* happen if a material weakness were ever found.
"""

import re
from typing import Optional

from .filing_sections import section_label

# Sections worth measuring individually. Item 8's notes are mostly numeric schedules,
# so prose metrics computed over them describe the tables, not the disclosure.
_PROSE_ITEMS = ("1", "1A", "3", "7", "7A", "9A")

# Fog counts a word as complex at three or more syllables. Inflected endings do not
# count toward that, which is why they are stripped before syllables are counted.
_COMPLEX_SYLLABLES = 3
_INFLECTIONS = ("es", "ed", "ing")

# Grade-level bands for the Fog index. A 10-K rarely reads below 14 -- roughly the
# level of a college textbook -- so the bands start where filings actually sit.
_FOG_DENSE = 22.0
_FOG_HEAVY = 19.0

# Words per sentence is the half of Fog that holds up on filings; these bands are set
# against the range 10-Ks actually occupy rather than against general-prose norms.
_LONG_SENTENCE_WORDS = 32.0
_VERY_LONG_SENTENCE_WORDS = 40.0

# A compact subset of the Loughran-McDonald uncertainty word list -- the terms that
# carry the signal in narrative disclosure without dragging in the ordinary business
# vocabulary that inflates a raw hedging count.
_UNCERTAINTY_WORDS = frozenset(
    """
    may might could would possibly possible probable probably perhaps uncertain
    uncertainty uncertainties approximate approximately estimate estimates estimated
    assume assumes assumed assumption assumptions believe believes believed anticipate
    anticipates anticipated expect expects expected intend intends tend tends
    fluctuate fluctuates fluctuation fluctuations unpredictable unforeseen indefinite
    contingent contingency sometimes seldom occasionally exposure exposures risky
    speculative unknown unclear vague ambiguous pending preliminary
    """.split()
)

# Growth in a section's length that is worth remarking on.
_SECTION_GROWTH_NOTABLE = 15.0

_MAX_QUOTE_CHARS = 320
_MAX_TRIPWIRE_HITS = 3

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")
_WS_RE = re.compile(r"\s+")

# Sentence splitting that does not break on the abbreviations filings are full of.
_ABBREVIATIONS = (
    "inc",
    "corp",
    "co",
    "ltd",
    "llc",
    "lp",
    "no",
    "vs",
    "u.s",
    "u.k",
    "mr",
    "ms",
    "dr",
    "jr",
    "sr",
    "st",
    "approx",
    "fig",
    "et al",
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

# A sentence carrying one of these is describing something that might happen, not
# something that did. Item 1A is written almost entirely in this voice.
_HYPOTHETICAL_RE = re.compile(
    r"\b(if|could|may|might|would|should|were to|in the event|risk that|any failure|"
    r"we cannot assure|no assurance|potential|potentially)\b",
    re.IGNORECASE,
)

_TRIPWIRES: tuple[dict, ...] = (
    {
        "key": "going_concern",
        "label": "Going-concern doubt",
        "severity": "red",
        "pattern": re.compile(r"going concern", re.IGNORECASE),
        "explanation": (
            "The phrase \"going concern\" in an annual report is a term of art: it is the "
            "language auditors and management use when there is substantial doubt that the "
            "company can keep operating for another twelve months."
        ),
    },
    {
        "key": "material_weakness",
        "label": "Material weakness in internal control",
        "severity": "red",
        "pattern": re.compile(r"material weakness(?:es)?", re.IGNORECASE),
        "explanation": (
            "A material weakness means the company's own controls could fail to catch a "
            "material misstatement. It is management's own conclusion, disclosed under "
            "Item 9A, and it is the disclosure most predictive of a later restatement."
        ),
    },
    {
        "key": "significant_deficiency",
        "label": "Significant deficiency in internal control",
        "severity": "yellow",
        "pattern": re.compile(r"significant deficienc(?:y|ies)", re.IGNORECASE),
        "explanation": (
            "A significant deficiency is the tier below a material weakness -- less severe, "
            "but still a control that did not work as intended."
        ),
    },
    {
        "key": "restatement",
        "label": "Restatement of previously issued financials",
        "severity": "red",
        "pattern": re.compile(r"restat(?:e|ed|ement|ements)\b", re.IGNORECASE),
        "explanation": (
            "A restatement means figures the company already published were wrong and have "
            "been reissued. Note that companies also use this word for ordinary "
            "reclassifications, so the sentence matters more than the match."
        ),
    },
    {
        "key": "government_investigation",
        "label": "Government investigation or subpoena",
        "severity": "yellow",
        "pattern": re.compile(
            r"(?:subpoena|civil investigative demand|(?:SEC|Department of Justice|DOJ|FTC|"
            r"grand jury)[^.]{0,60}investigation|formal order of investigation)",
            re.IGNORECASE,
        ),
        "explanation": (
            "An open investigation or a subpoena from a regulator is disclosed here long "
            "before any outcome is known."
        ),
    },
    {
        "key": "covenant_trouble",
        "label": "Debt covenant waiver or default",
        "severity": "yellow",
        "pattern": re.compile(
            r"(?:waiver of[^.]{0,40}covenant|covenant[^.]{0,40}waiv|event of default|"
            r"breach(?:ed)? (?:of )?(?:a |the )?(?:financial )?covenant)",
            re.IGNORECASE,
        ),
        "explanation": (
            "A waiver or a default means the company failed a term of its own loan "
            "agreements and had to ask its lenders for relief."
        ),
    },
    {
        "key": "auditor_change",
        "label": "Change of auditor discussed in the filing",
        "severity": "yellow",
        "pattern": re.compile(r"dismiss(?:ed|al) of[^.]{0,40}(?:auditor|accountant)", re.IGNORECASE),
        "explanation": "The filing discusses dismissing its independent accountant.",
    },
)


def build_text_metrics(
    sections: dict[str, str],
    prior_sections: Optional[dict[str, str]] = None,
    current_year: Optional[int] = None,
    prior_year: Optional[int] = None,
) -> Optional[dict]:
    """Measure the filing. `prior_sections` enables every year-over-year figure."""
    if not sections:
        return None

    prior_sections = prior_sections or {}
    return {
        "currentYear": current_year,
        "priorYear": prior_year if prior_sections else None,
        "sections": _section_sizes(sections, prior_sections),
        "riskFactors": _risk_factor_counts(sections, prior_sections),
        "readability": _readability(sections),
        "hedging": _hedging(sections, prior_sections),
        "tripwires": _tripwires(sections),
    }


# --- size ------------------------------------------------------------------------------


def _section_sizes(sections: dict[str, str], prior_sections: dict[str, str]) -> list[dict]:
    rows = []
    for item, text in sections.items():
        words = _word_count(text)
        prior_text = prior_sections.get(item)
        prior_words = _word_count(prior_text) if prior_text else None
        change = (
            (words / prior_words - 1) * 100 if prior_words else None
        )
        rows.append(
            {
                "item": item,
                "label": section_label(item),
                "words": words,
                "priorWords": prior_words,
                "changePercent": None if change is None else round(change, 1),
                "notable": change is not None and abs(change) >= _SECTION_GROWTH_NOTABLE,
            }
        )
    rows.sort(key=lambda row: row["words"], reverse=True)
    return rows


def _risk_factor_counts(sections: dict[str, str], prior_sections: dict[str, str]) -> Optional[dict]:
    """How many individually comparable risk blocks Item 1A carries, this year and last.

    The block count comes from the same splitter the year-over-year diff aligns on, so
    the two features cannot disagree about what a risk factor is. It counts comparable
    blocks rather than headline risks: filers that write one long risk per heading and
    filers that write ten short ones do not produce comparable counts, which is why the
    change matters here and the absolute number does not.
    """
    current = sections.get("1A")
    if not current:
        return None

    from .section_diff import split_into_units

    count = len(split_into_units(current))
    prior_text = prior_sections.get("1A")
    prior_count = len(split_into_units(prior_text)) if prior_text else None

    words = _word_count(current)
    prior_words = _word_count(prior_text) if prior_text else None

    return {
        "count": count,
        "priorCount": prior_count,
        "change": None if prior_count is None else count - prior_count,
        "words": words,
        "priorWords": prior_words,
        "wordChangePercent": (
            None if not prior_words else round((words / prior_words - 1) * 100, 1)
        ),
    }


# --- readability -------------------------------------------------------------------------


def _readability(sections: dict[str, str]) -> Optional[dict]:
    """The Fog index over the filing's prose, with its two halves kept separate.

    Fog = 0.4 × (words per sentence + percentage of complex words). It is the measure
    the disclosure literature standardised on, but Loughran and McDonald showed in 2014
    that its complex-word half misfires badly on filings: business English is full of
    long words that every reader of a 10-K already knows ("corporation", "regulatory",
    "amortization"), so a filing scores as dense for using its own vocabulary. Words per
    sentence is the half that survives that critique, so it is reported alongside and
    the verdict is based on it.
    """
    text = "\n".join(sections[item] for item in _PROSE_ITEMS if sections.get(item))
    if not text:
        return None

    sentences = _sentences(text)
    words = _WORD_RE.findall(text)
    if len(sentences) < 20 or len(words) < 500:
        return None

    words_per_sentence = len(words) / len(sentences)
    complex_words = sum(1 for word in words if _is_complex(word))
    complex_percent = complex_words / len(words) * 100
    fog = 0.4 * (words_per_sentence + complex_percent)

    if words_per_sentence >= _VERY_LONG_SENTENCE_WORDS:
        severity = "red"
        verdict = (
            "That is long even by the standards of annual reports, and length of that kind "
            "is where qualifications get buried: the clause that changes the meaning of a "
            "sentence sits forty words after the claim it qualifies."
        )
    elif words_per_sentence >= _LONG_SENTENCE_WORDS:
        severity = "yellow"
        verdict = "That is on the long side for an annual report, though not unusual."
    else:
        severity = "green"
        verdict = "That is short for an annual report -- this filing is easier to read than most."

    return {
        "fogIndex": round(fog, 1),
        "wordsPerSentence": round(words_per_sentence, 1),
        "complexWordPercent": round(complex_percent, 1),
        "wordCount": len(words),
        "sentenceCount": len(sentences),
        "severity": severity,
        "interpretation": (
            f"The narrative sections average {words_per_sentence:.0f} words per sentence. "
            f"{verdict} The Fog index works out at {fog:.0f}, but the complex-word half of "
            "that formula counts ordinary business vocabulary as difficult, so sentence "
            "length is the more reliable half and the reading above is based on it."
        ),
    }


def _is_complex(word: str) -> bool:
    """Three or more syllables, not counting the ones an inflected ending adds."""
    stem = word.lower()
    for ending in _INFLECTIONS:
        if stem.endswith(ending) and len(stem) > len(ending) + 2:
            stem = stem[: -len(ending)]
            break
    return _syllables(stem) >= _COMPLEX_SYLLABLES


def _syllables(word: str) -> int:
    """Vowel groups, less a silent trailing 'e'. Approximate by construction, and only
    ever used in aggregate over tens of thousands of words."""
    stem = word.lower().strip("'-")
    if not stem:
        return 0
    if stem.endswith("e") and not stem.endswith(("le", "ee")) and len(stem) > 2:
        stem = stem[:-1]
    return max(len(_VOWEL_GROUP_RE.findall(stem)), 1)


def _sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(_WS_RE.sub(" ", text))
    merged: list[str] = []
    for part in parts:
        # A split that landed straight after a known abbreviation was not a sentence end.
        if merged and _ends_with_abbreviation(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return [part.strip() for part in merged if len(part.strip()) > 1]


def _ends_with_abbreviation(sentence: str) -> bool:
    tail = sentence.rstrip().rstrip(".").lower()
    return any(tail.endswith(abbreviation) for abbreviation in _ABBREVIATIONS)


# --- hedging ------------------------------------------------------------------------------


def _hedging(sections: dict[str, str], prior_sections: dict[str, str]) -> Optional[dict]:
    """Uncertainty vocabulary per thousand words, against last year's filing."""
    current = _uncertainty_density(sections)
    if current is None:
        return None

    prior = _uncertainty_density(prior_sections) if prior_sections else None
    change = None if prior is None else current["per1000"] - prior["per1000"]

    if change is None:
        severity = "green"
        trend = "There is no prior-year filing to compare that against."
    elif change >= 4:
        severity = "yellow"
        trend = (
            f"That is up {change:.1f} per thousand words on last year's filing. Management "
            "is hedging more than it did a year ago, which tends to precede the news rather "
            "than follow it."
        )
    elif change <= -4:
        severity = "green"
        trend = f"That is down {abs(change):.1f} per thousand words on last year's filing."
    else:
        severity = "green"
        trend = "That is in line with last year's filing."

    return {
        "per1000": round(current["per1000"], 1),
        "priorPer1000": None if prior is None else round(prior["per1000"], 1),
        "change": None if change is None else round(change, 1),
        "wordCount": current["words"],
        "topTerms": current["top"],
        "severity": severity,
        "interpretation": (
            f"Words expressing uncertainty -- may, could, approximately, believe -- appear "
            f"{current['per1000']:.1f} times per thousand words. {trend} The list is a "
            "compact subset of the Loughran-McDonald uncertainty dictionary, the standard "
            "word list for this measurement in the accounting literature."
        ),
    }


def _uncertainty_density(sections: dict[str, str]) -> Optional[dict]:
    text = "\n".join(sections[item] for item in _PROSE_ITEMS if sections.get(item))
    words = _WORD_RE.findall(text.lower())
    if len(words) < 500:
        return None

    counts: dict[str, int] = {}
    hits = 0
    for word in words:
        if word in _UNCERTAINTY_WORDS:
            hits += 1
            counts[word] = counts.get(word, 0) + 1

    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    return {
        "per1000": hits / len(words) * 1000,
        "words": len(words),
        "top": [{"term": term, "count": count} for term, count in top],
    }


# --- tripwires ----------------------------------------------------------------------------


def _tripwires(sections: dict[str, str]) -> list[dict]:
    """Phrases that mean something specific, reported with the sentence they appear in."""
    found = []
    for tripwire in _TRIPWIRES:
        hits = _match_sentences(tripwire["pattern"], sections)
        stated = [hit for hit in hits if not hit["hypothetical"]]
        if not stated:
            # Every occurrence was conditional -- "if we were to identify a material
            # weakness" is Item 1A boilerplate, not a disclosure that one exists.
            continue
        found.append(
            {
                "key": tripwire["key"],
                "label": tripwire["label"],
                "severity": tripwire["severity"],
                "count": len(stated),
                "hypotheticalCount": len(hits) - len(stated),
                "explanation": tripwire["explanation"],
                "occurrences": stated[:_MAX_TRIPWIRE_HITS],
            }
        )
    return found


def _match_sentences(pattern: re.Pattern, sections: dict[str, str]) -> list[dict]:
    hits = []
    for item, text in sections.items():
        if not pattern.search(text):
            continue  # cheap gate: splitting a 250k-char section is not free
        for sentence in _sentences(text):
            if not pattern.search(sentence):
                continue
            hits.append(
                {
                    "section": section_label(item),
                    "quote": _clip(sentence),
                    "hypothetical": bool(_HYPOTHETICAL_RE.search(sentence)),
                }
            )
    # A statement of fact outranks a conditional mention of the same phrase.
    hits.sort(key=lambda hit: hit["hypothetical"])
    return hits


def _clip(sentence: str) -> str:
    collapsed = _WS_RE.sub(" ", sentence).strip()
    if len(collapsed) <= _MAX_QUOTE_CHARS:
        return collapsed
    return collapsed[:_MAX_QUOTE_CHARS].rsplit(" ", 1)[0] + "..."


def _word_count(text: Optional[str]) -> int:
    return len(_WORD_RE.findall(text)) if text else 0
