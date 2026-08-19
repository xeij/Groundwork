"""Mechanically verify model output against the filing it was drawn from.

The model self-reporting a confidence label is the model grading its own homework.
This module replaces that with checks the machine can make on its own: every quoted
passage is matched back against the source text, and every stated figure is compared
against the company's own XBRL-tagged numbers. What comes out distinguishes
"verified against source" from "unverified model inference" -- a claim the model
cannot inflate.

No network, no third-party packages: everything here operates on data handed in.
"""

import re
import unicodedata
from array import array
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Callable, Optional

# --- quote matching thresholds -------------------------------------------------

# Below this SequenceMatcher ratio a quote is treated as fabricated rather than
# paraphrased. 0.85 sits above where genuine rewordings of a filing sentence land
# (typically 0.88-0.97, because the model keeps the filing's nouns and numbers) and
# well above two unrelated sentences of legal boilerplate (0.4-0.6), which share
# enough connective tissue that a lower floor would wave invented quotes through.
FUZZY_MIN_SCORE = 0.85

# A whole-document sliding window is O(len(source)) SequenceMatcher runs, which on a
# 250k-character filing takes minutes. Instead we anchor: rare tokens from the quote
# are located in the source with str.find (C speed) and only those neighbourhoods are
# compared. These caps bound the worst case when a quote's tokens are common.
_MAX_ANCHOR_TOKENS = 12
_MAX_ANCHOR_WINDOWS = 240
_MIN_ANCHOR_TOKEN_LENGTH = 3

# Windows are padded either side of the anchor so a match still fits when the model
# dropped or added a clause relative to the source.
_WINDOW_PAD_MIN = 32
_WINDOW_PAD_FRACTION = 4  # pad = len(quote) // 4, floored at _WINDOW_PAD_MIN

# Two anchors landing this close describe the same neighbourhood; compare it once.
_WINDOW_DEDUPE_BUCKET = 16

# Tokens too common to narrow anything down; using them as anchors just burns the
# window budget on neighbourhoods that cannot match.
_ANCHOR_STOPWORDS = frozenset({
    "and", "the", "for", "with", "that", "this", "from", "our", "are", "was", "were",
    "have", "has", "had", "not", "any", "all", "may", "will", "which", "such", "its",
    "other", "than", "been", "their", "these", "those", "into", "under", "over",
    "company", "companys", "including", "certain", "also", "more", "most", "well",
})

# Characters the model swaps freely without changing meaning. Folding these is what
# separates a typographic difference from a substantive one.
_TYPOGRAPHIC_FOLDS = {
    # single quotes, primes, backticks
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "′": "'", "´": "'", "`": "'",
    # double quotes, guillemets
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "″": '"', "«": '"', "»": '"',
    # the whole dash family collapses onto a plain hyphen
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    "…": "...",
    # zero-width and formatting characters carry no meaning at all
    "​": "", "‌": "", "‍": "", "﻿": "", "­": "",
    "•": "",
}

# Edge punctuation a model trims or appends when lifting a passage: a quote that
# starts mid-sentence and ends without the source's comma is still the same quote.
_EDGE_PUNCTUATION = " \t\r\n.,;:!?'\"()[]{}-*…"

# Runs of already-normal characters need no per-character work; skipping them keeps
# normalisation of a 250k-character filing in the tens of milliseconds.
_PLAIN_RUN_RE = re.compile(r"[a-z0-9]+")

_ANCHOR_TOKEN_RE = re.compile(r"[a-z0-9]{%d,}" % _MIN_ANCHOR_TOKEN_LENGTH)

# A paraphrase keeps the filing's numbers; a quote that states a figure the matched
# passage does not contain is asserting something the filing did not say, however
# similar the surrounding words are. Set False to score on wording alone.
REJECT_ON_ALTERED_FIGURES = True

# Padding when checking figures, so a number sitting one character outside the trimmed
# match boundary is not mistaken for an invention.
_FIGURE_CHECK_PAD = 16

_NUMERIC_TOKEN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

QUOTE_STATUSES = ("exact", "normalized", "fuzzy", "not_found")

# --- figure parsing ------------------------------------------------------------

DEFAULT_FIGURE_TOLERANCE = 0.01  # relative; filings round, so 1% absorbs "$391.0 billion"

FIGURE_STATUSES = ("match", "mismatch", "unverifiable")

_SCALE_MULTIPLIERS = {
    "trillion": 1e12, "trillions": 1e12, "tn": 1e12, "t": 1e12,
    "billion": 1e9, "billions": 1e9, "bn": 1e9, "b": 1e9,
    "million": 1e6, "millions": 1e6, "mm": 1e6, "mn": 1e6, "m": 1e6,
    "thousand": 1e3, "thousands": 1e3, "k": 1e3,
}

_SCALE_ALTERNATION = "trillions?|billions?|millions?|thousands?|tn|bn|mm|mn|[tbmk]"

_NUMBER_PATTERN = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"

# The sign, currency symbol and opening parenthesis appear in several orders in real
# filings -- "$(1,234)", "($1,234)", "-$1.2bn" -- so they are matched as one loose
# prefix and interpreted afterwards rather than pinned to a fixed sequence.
_FIGURE_RE = re.compile(
    r"(?P<lead>(?:[(\-−]\s*){0,2}(?:(?:\$|USD)\s*)?(?:[(\-−]\s*){0,2})"
    r"(?P<number>" + _NUMBER_PATTERN + r")"
    r"(?:\s*(?P<scale>" + _SCALE_ALTERNATION + r")\b)?"
    r"(?:\s*(?P<percent>%|percent|percentage points?))?"
    r"\s*(?P<close>\))?",
    re.IGNORECASE,
)


def _lead_flags(lead: str) -> tuple[bool, bool, bool]:
    """Read (has_currency, has_open_paren, has_minus) out of a matched figure prefix."""
    lowered = (lead or "").lower()
    return ("$" in lowered or "usd" in lowered, "(" in lowered, "-" in lowered or "−" in lowered)

# A bare number is only a figure when something marks it as one. "2024" and "Item 7"
# are not quantities we should be checking against XBRL.
_MONETARY_ONLY_RE = re.compile(
    r"^\(?\s*(?:-|−)?\s*(?:\$|USD\s*)?\s*(?:" + _NUMBER_PATTERN + r")"
    r"(?:\s*(?:" + _SCALE_ALTERNATION + r"))?\s*\)?\.?$",
    re.IGNORECASE,
)

# Model metric field -> XBRL fiscal-year field. Explicit rather than derived: the two
# vocabularies were written by different people and only accidentally agree.
METRIC_TO_XBRL_FIELD = {
    "totalRevenue": "revenue",
    "revenue": "revenue",
    "netIncome": "netIncome",
    "totalDebt": "totalDebt",
    "cashAndEquivalents": "cash",
    "cashAndCashEquivalents": "cash",
    "cash": "cash",
    "operatingCashFlow": "operatingCashFlow",
    "totalAssets": "totalAssets",
    "stockholdersEquity": "stockholdersEquity",
}

# Metric fields that are not quantities; skipped silently rather than reported as
# unverifiable, because there is no authoritative number they could be checked against.
NON_MONETARY_METRIC_FIELDS = frozenset({"tickerSymbol", "fiscalYear", "period"})

# --- finding verification ------------------------------------------------------

VERIFICATION_STATUSES = ("verified", "paraphrased", "unverified", "rejected")

VERIFICATION_METHODS = (
    "exact_quote_match",
    "normalized_quote_match",
    "fuzzy_quote_match",
    "no_citation",
    "no_source_text",
)

_QUOTE_STATUS_TO_VERIFICATION = {
    "exact": ("verified", "exact_quote_match"),
    "normalized": ("verified", "normalized_quote_match"),
    "fuzzy": ("paraphrased", "fuzzy_quote_match"),
    "not_found": ("rejected", "fuzzy_quote_match"),
}

# The app emits this exact string for a category with nothing to report. It carries no
# citation by design and must never be rejected -- rejecting it would read as a model
# failure where there was none.
PLACEHOLDER_SUMMARY = "Nothing material to report."


class VerificationError(Exception):
    pass


# ------------------------------------------------------------------------------
# Part 1: quote verification
# ------------------------------------------------------------------------------

_decompose_cache: dict[str, str] = {}


def _decompose_char(ch: str) -> str:
    """Fold one character to its comparison form.

    NFKD (not NFKC) plus dropping combining marks, so that a precomposed "e-acute" and
    a decomposed one land on the same string. Doing it per character rather than over
    the whole document is what lets us keep a character-offset map back into the
    original text; decomposition is defined per character, so the results agree.
    """
    cached = _decompose_cache.get(ch)
    if cached is not None:
        return cached
    folded = _TYPOGRAPHIC_FOLDS.get(ch)
    if folded is None:
        decomposed = unicodedata.normalize("NFKD", ch)
        folded = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    _decompose_cache[ch] = folded
    return folded


def _normalize_with_offsets(text: str) -> tuple[str, array]:
    """Normalized text plus, for each normalized character, its index in `text`.

    The offset map is the whole point: a match found in normalized space has to be
    reported back as a span of the *original* filing so the UI can show real prose.
    """
    if not text:
        return "", array("i")

    parts: list[str] = []
    offsets = array("i")
    pending_space_at = -1
    i = 0
    length = len(text)

    while i < length:
        run = _PLAIN_RUN_RE.match(text, i)
        if run is not None:
            if pending_space_at >= 0 and parts:
                parts.append(" ")
                offsets.append(pending_space_at)
            pending_space_at = -1
            parts.append(run.group())
            offsets.extend(range(i, run.end()))
            i = run.end()
            continue

        ch = text[i]
        if ch.isspace():
            # Collapse whitespace runs to a single space, and drop leading whitespace.
            if pending_space_at < 0:
                pending_space_at = i
            i += 1
            continue

        replacement = _decompose_char(ch)
        if replacement:
            if pending_space_at >= 0 and parts:
                parts.append(" ")
                offsets.append(pending_space_at)
            pending_space_at = -1
            parts.append(replacement)
            offsets.extend([i] * len(replacement))
        i += 1

    return "".join(parts), offsets


def normalize_for_matching(text: str) -> str:
    """Fold text to the form quote comparison happens in.

    Unicode decomposition, typographic folding (curly quotes, dash family, ellipsis),
    whitespace collapsing and case folding. Anything this removes is a difference the
    model is allowed to introduce; anything it preserves -- above all, the words -- is
    a difference that means the quote was not lifted from the filing.
    """
    return _normalize_with_offsets(text or "")[0]


@lru_cache(maxsize=4)
def _normalized_source(source_text: str) -> tuple[str, array]:
    """Cached normalization of a filing section.

    A single analysis verifies many findings against the same handful of Item sections,
    and normalizing 250k characters per finding dominates the runtime otherwise. The
    cache is deliberately tiny -- the offset array is ~1MB per 250k characters.
    """
    return _normalize_with_offsets(source_text)


def _trim_edges(text: str) -> str:
    trimmed = text.strip(_EDGE_PUNCTUATION)
    # A quote made entirely of punctuation is nonsense to match on, but returning
    # nothing would score it 1.0 against everything.
    return trimmed or text.strip()


def _span_to_original(offsets: array, start: int, end: int) -> tuple[int, int]:
    """Map a [start, end) span in normalized space back to original character offsets."""
    original_start = offsets[start]
    original_end = offsets[end - 1] + 1
    return original_start, original_end


def _anchor_windows(quote_norm: str, source_norm: str) -> list[tuple[int, int]]:
    """Candidate [start, end) windows of `source_norm` worth comparing to the quote.

    Anchors are the quote's rarest tokens: if the model lifted the passage, at least
    one distinctive word survives, and its position in the source pins the window.
    """
    tokens: dict[str, int] = {}
    for match in _ANCHOR_TOKEN_RE.finditer(quote_norm):
        token = match.group()
        if token in _ANCHOR_STOPWORDS:
            continue
        # First occurrence only: it is enough to place the window.
        tokens.setdefault(token, match.start())

    if not tokens:
        # Nothing distinctive to anchor on (a very short or all-stopword quote); fall
        # back to any alphanumeric run so short quotes still get a chance.
        for match in re.finditer(r"[a-z0-9]+", quote_norm):
            tokens.setdefault(match.group(), match.start())

    scored = []
    for token, quote_pos in tokens.items():
        count = source_norm.count(token)
        if count:
            scored.append((count, len(token), token, quote_pos))
    if not scored:
        return []

    # Rarest first, longest as the tie-break: both correlate with a tighter anchor.
    scored.sort(key=lambda item: (item[0], -item[1]))

    pad = max(_WINDOW_PAD_MIN, len(quote_norm) // _WINDOW_PAD_FRACTION)
    span = len(quote_norm) + 2 * pad
    source_len = len(source_norm)

    windows: list[tuple[int, int]] = []
    seen_buckets: set[int] = set()
    for _count, _length, token, quote_pos in scored[:_MAX_ANCHOR_TOKENS]:
        search_from = 0
        while len(windows) < _MAX_ANCHOR_WINDOWS:
            found = source_norm.find(token, search_from)
            if found < 0:
                break
            search_from = found + 1
            start = max(0, found - quote_pos - pad)
            bucket = start // _WINDOW_DEDUPE_BUCKET
            if bucket in seen_buckets:
                continue
            seen_buckets.add(bucket)
            windows.append((start, min(source_len, start + span)))
        if len(windows) >= _MAX_ANCHOR_WINDOWS:
            break
    return windows


def _best_fuzzy_match(
    quote_norm: str, source_norm: str, offsets: array, source_text: str
) -> tuple[float, Optional[str], Optional[int], tuple[int, int]]:
    """Highest similarity between the quote and any span of the source, with that span.

    Scored against the *trimmed* span rather than the padded window: padding exists to
    tolerate a clause the model dropped, but leaving it in the denominator would
    penalise a perfectly good match for the unrelated prose sitting next to it.
    """
    windows = _anchor_windows(quote_norm, source_norm)
    if not windows:
        return 0.0, None, None, (0, 0)

    quote_len = len(quote_norm)
    best_ratio = 0.0
    best_span: Optional[tuple[int, int]] = None

    for start, end in windows:
        window = source_norm[start:end]
        matcher = SequenceMatcher(None, quote_norm, window, autojunk=False)
        if _trimmed_ratio_ceiling(quote_len, matcher.real_quick_ratio(), quote_len + len(window)) <= best_ratio:
            continue
        if _trimmed_ratio_ceiling(quote_len, matcher.quick_ratio(), quote_len + len(window)) <= best_ratio:
            continue

        blocks = [b for b in matcher.get_matching_blocks() if b.size]
        if not blocks:
            continue
        span_start = start + blocks[0].b
        span_end = start + blocks[-1].b + blocks[-1].size
        ratio = SequenceMatcher(
            None, quote_norm, source_norm[span_start:span_end], autojunk=False
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_span = (span_start, span_end)

    if best_span is None or best_span[1] <= best_span[0]:
        return best_ratio, None, None, (0, 0)

    original_start, original_end = _span_to_original(offsets, best_span[0], best_span[1])
    return best_ratio, source_text[original_start:original_end], original_start, best_span


def _trimmed_ratio_ceiling(quote_len: int, window_ratio: float, total_len: int) -> float:
    """Upper bound on the trimmed-span ratio, given an upper bound on the padded one.

    SequenceMatcher's quick ratios bound the number of matching characters M; the best
    any sub-span can then do is 2M / (len(quote) + M), since the span must be at least
    M characters long. Pruning on that keeps the bound honest -- a cheaper prefilter on
    the padded ratio alone would discard windows whose trimmed span would have won.
    """
    matches = window_ratio * total_len / 2
    if matches <= 0:
        return 0.0
    return 2 * matches / (quote_len + matches)


def _numeric_values(text: str) -> list[float]:
    values = []
    for token in _NUMERIC_TOKEN_RE.findall(text):
        try:
            values.append(float(token.replace(",", "").rstrip(".")))
        except ValueError:
            continue
    return values


def _figures_survive(quote_norm: str, span_norm: str) -> bool:
    """True when every number the quote states also appears in the matched passage."""
    quote_numbers = _numeric_values(quote_norm)
    if not quote_numbers:
        return True
    span_numbers = _numeric_values(span_norm)
    return all(
        any(stated == found for found in span_numbers)
        for stated in quote_numbers
    )


def verify_quote(quote: str, source_text: str) -> dict:
    """Match a model-supplied quote back against the filing text it claims to come from.

    Reports which rung of the ladder matched, because the rungs mean different things:
    "normalized" is a pass (the model retyped a curly quote), "fuzzy" is a soft pass
    that means the model paraphrased, and "not_found" means the passage is not in the
    filing at all.
    """
    quote = (quote or "").strip()
    source_text = source_text or ""
    if not quote or not source_text:
        return {"status": "not_found", "score": 0.0, "matchedText": None, "offset": None}

    # Rung 1: character-for-character.
    offset = source_text.find(quote)
    if offset >= 0:
        return {
            "status": "exact",
            "score": 1.0,
            "matchedText": source_text[offset:offset + len(quote)],
            "offset": offset,
        }

    source_norm, offsets = _normalized_source(source_text)
    quote_norm = _trim_edges(normalize_for_matching(quote))
    if not quote_norm or not source_norm:
        return {"status": "not_found", "score": 0.0, "matchedText": None, "offset": None}

    # Rung 2: identical once typography, whitespace and case are folded away.
    norm_offset = source_norm.find(quote_norm)
    if norm_offset >= 0:
        start, end = _span_to_original(offsets, norm_offset, norm_offset + len(quote_norm))
        return {
            "status": "normalized",
            "score": 1.0,
            "matchedText": source_text[start:end],
            "offset": start,
        }

    # Rung 3: close enough to be a paraphrase of a real passage, or nowhere near it.
    score, matched_text, matched_offset, span = _best_fuzzy_match(
        quote_norm, source_norm, offsets, source_text
    )
    # Compare on the same rounded value that gets reported, so a caller who reads a
    # score back and sets FUZZY_MIN_SCORE to it sees that quote pass rather than a
    # decision made on hidden digits it was never shown.
    score = round(score, 4)
    if score >= FUZZY_MIN_SCORE and matched_text is not None:
        padded = source_norm[
            max(0, span[0] - _FIGURE_CHECK_PAD): span[1] + _FIGURE_CHECK_PAD
        ]
        if not REJECT_ON_ALTERED_FIGURES or _figures_survive(quote_norm, padded):
            return {
                "status": "fuzzy",
                "score": score,
                "matchedText": matched_text,
                "offset": matched_offset,
            }
    return {
        "status": "not_found",
        "score": score,
        "matchedText": None,
        "offset": None,
    }


# ------------------------------------------------------------------------------
# Part 2: figure verification against XBRL
# ------------------------------------------------------------------------------


def parse_monetary(text: str) -> Optional[float]:
    """Turn a stated money string into a number. `None` if it is not a money quantity.

    Handles "$391.0 billion", "$93,736 million", "391035", "(1,234)" and "-$1.2bn".
    Percentages, multiples ("3.5x") and prose are not monetary and come back `None`,
    so that a caller never compares them against a tagged dollar amount.
    """
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate or "%" in candidate:
        return None

    has_currency = "$" in candidate or re.search(r"\busd\b", candidate, re.IGNORECASE)
    if not has_currency and not _MONETARY_ONLY_RE.match(candidate):
        # No currency marker and the string is not purely a number: it is prose, a
        # ratio, a share count -- something we have no business reading as dollars.
        return None

    if has_currency:
        # Anchor on the currency symbol so "$5 million in 2024" reads 5 million, not 2024,
        # then walk back over any sign or opening parenthesis in front of it so that
        # "-$1.2 billion" and "($1.2 billion)" keep their negativity.
        search_from = candidate.index("$") if "$" in candidate else 0
        while search_from > 0 and candidate[search_from - 1] in "(-− \t":
            search_from -= 1
        match = _FIGURE_RE.search(candidate, search_from)
    else:
        match = _FIGURE_RE.search(candidate)
    if match is None or not match.group("number"):
        return None
    if match.group("percent"):
        return None

    value = float(match.group("number").replace(",", ""))
    scale = match.group("scale")
    if scale:
        value *= _SCALE_MULTIPLIERS[scale.lower()]

    _, has_open, has_minus = _lead_flags(match.group("lead"))
    negative = has_minus
    # Accountants write negatives in parentheses; require both sides so "(see note 3)
    # $1,234" is not read as a negative.
    if has_open and (match.group("close") or candidate.rstrip().endswith(")")):
        negative = True
    return -value if negative else value


def extract_figures(text: str) -> list[dict]:
    """Every monetary or percentage quantity in a sentence, with its position.

    Bare numbers are skipped: without a currency symbol, a scale word or a percent
    sign there is nothing to say a token is a quantity rather than a year or an
    Item number, and a false positive here becomes a false "mismatch" downstream.
    """
    if not isinstance(text, str) or not text:
        return []

    figures: list[dict] = []
    for match in _FIGURE_RE.finditer(text):
        number = match.group("number")
        if not number:
            continue
        currency, has_open, has_minus = _lead_flags(match.group("lead"))
        scale = match.group("scale")
        percent = match.group("percent")
        # A bare number needs a marker to count as a quantity. A parenthesised number is
        # accounting notation for a negative, which is marker enough.
        if not (currency or scale or percent or (has_open and match.group("close"))):
            continue

        raw = match.group().strip()
        value = float(number.replace(",", ""))
        if percent:
            figures.append({
                "text": raw,
                "kind": "percent",
                "value": value,  # in percentage points, i.e. "12.5%" -> 12.5
                "start": match.start(),
                "end": match.end(),
            })
            continue

        if scale:
            value *= _SCALE_MULTIPLIERS[scale.lower()]
        if has_minus or (has_open and match.group("close")):
            value = -value
        figures.append({
            "text": raw,
            "kind": "monetary",
            "value": value,
            "start": match.start(),
            "end": match.end(),
        })
    return figures


def verify_figure(
    stated: str, actual: Optional[float], tolerance: float = DEFAULT_FIGURE_TOLERANCE
) -> dict:
    """Compare a stated figure against the authoritative XBRL value.

    The tolerance is *relative* because filings round: "$391.0 billion" against a
    tagged 391,035,000,000 is the same number stated to one decimal place, in either
    rounding direction, not a mismatch.
    """
    if tolerance < 0:
        raise VerificationError("tolerance must be non-negative")

    stated_value = parse_monetary(stated) if isinstance(stated, str) else stated
    if stated_value is not None and not isinstance(stated_value, (int, float)):
        stated_value = None

    if stated_value is None or actual is None:
        # Absence of a tagged value is not evidence of an error; it is absence of
        # evidence, and it has to render differently from a contradiction.
        return {
            "status": "unverifiable",
            "stated": stated_value,
            "actual": actual,
            "deltaPercent": None,
        }

    stated_value = float(stated_value)
    actual_value = float(actual)
    denominator = abs(actual_value) or abs(stated_value)
    if denominator == 0:
        relative = 0.0
    else:
        relative = abs(stated_value - actual_value) / denominator

    return {
        "status": "match" if relative <= tolerance else "mismatch",
        "stated": stated_value,
        "actual": actual_value,
        "deltaPercent": round(relative * 100, 3),
    }


def verify_key_metrics(
    key_metrics: Optional[dict],
    fiscal_year: Optional[dict],
    tolerance: float = DEFAULT_FIGURE_TOLERANCE,
) -> dict:
    """Check each model-extracted metric against one fiscal year of XBRL data.

    Metrics the model did not state are skipped (nothing was claimed); metrics the
    company never tagged come back "unverifiable" rather than "mismatch".
    """
    key_metrics = key_metrics or {}
    fiscal_year = fiscal_year or {}

    metrics: dict[str, dict] = {}
    stats = {"match": 0, "mismatch": 0, "unverifiable": 0}

    for field, stated in key_metrics.items():
        if field in NON_MONETARY_METRIC_FIELDS:
            continue
        xbrl_field = METRIC_TO_XBRL_FIELD.get(field)
        if xbrl_field is None:
            continue
        if stated is None or (isinstance(stated, str) and not stated.strip()):
            continue

        result = verify_figure(stated, fiscal_year.get(xbrl_field), tolerance=tolerance)
        result["field"] = field
        result["xbrlField"] = xbrl_field
        result["statedText"] = stated if isinstance(stated, str) else None
        metrics[field] = result
        stats[result["status"]] += 1

    return {
        "metrics": metrics,
        "stats": stats,
        "fiscalYear": fiscal_year.get("fiscalYear") or fiscal_year.get("year"),
    }


# ------------------------------------------------------------------------------
# Part 3: applying verification to findings
# ------------------------------------------------------------------------------


def _detail_for(status: str, quote_status: str, score: float) -> str:
    if quote_status == "exact":
        return "Quote matched the filing text character-for-character."
    if quote_status == "normalized":
        return "Quote matched the filing text after normalizing punctuation and whitespace."
    if quote_status == "fuzzy":
        return (
            f"Quote is a close paraphrase of filing text ({score:.0%} similarity), "
            "not a verbatim excerpt."
        )
    if status == "unverified":
        return "No citation supplied, so this finding could not be checked against the filing."
    return (
        f"No passage in the filing resembles this quote (best similarity {score:.0%}); "
        "the quote appears to be fabricated."
    )


def verify_finding(finding: dict, source_text: str) -> dict:
    """Return a copy of `finding` with a `verification` block attached.

    The finding is never dropped and never silently altered -- callers need to see a
    rejection to know the model failed.
    """
    if not isinstance(finding, dict):
        raise VerificationError("finding must be a dict")

    verified = dict(finding)
    citation = finding.get("citation") or {}
    quote = citation.get("quote") if isinstance(citation, dict) else None
    quote = quote.strip() if isinstance(quote, str) else ""

    if not quote:
        verified["verification"] = {
            "status": "unverified",
            "method": "no_citation",
            "score": 0.0,
            "matchedText": None,
            "detail": (
                "Standard placeholder finding; nothing to verify."
                if finding.get("summary") == PLACEHOLDER_SUMMARY
                else _detail_for("unverified", "none", 0.0)
            ),
        }
        return verified

    if not source_text:
        # A quote we have no source for is unchecked, not disproven.
        verified["verification"] = {
            "status": "unverified",
            "method": "no_source_text",
            "score": 0.0,
            "matchedText": None,
            "detail": "No source text was available for this finding's section.",
        }
        return verified

    result = verify_quote(quote, source_text)
    status, method = _QUOTE_STATUS_TO_VERIFICATION[result["status"]]
    verified["verification"] = {
        "status": status,
        "method": method,
        "score": result["score"],
        "matchedText": result["matchedText"],
        "detail": _detail_for(status, result["status"], result["score"]),
    }
    return verified


def verify_findings(findings: list[dict], source_lookup) -> dict:
    """Verify a list of findings, routing each to its own source text.

    `source_lookup` is a callable taking a finding and returning the text to check it
    against, so the caller can hand a Risk Factors finding Item 1A rather than the
    whole filing. A plain string is accepted as a convenience when every finding
    shares one source.
    """
    findings = findings or []
    if isinstance(source_lookup, str):
        source_text = source_lookup
        lookup: Callable[[dict], Optional[str]] = lambda _finding: source_text
    elif callable(source_lookup):
        lookup = source_lookup
    else:
        raise VerificationError("source_lookup must be a callable or a string")

    verified_findings = []
    stats = {status: 0 for status in VERIFICATION_STATUSES}
    for finding in findings:
        verified = verify_finding(finding, lookup(finding) or "")
        stats[verified["verification"]["status"]] += 1
        verified_findings.append(verified)

    return {"findings": verified_findings, "stats": stats}
