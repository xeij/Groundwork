"""Year-over-year diffing of a 10-K's narrative sections.

Companies copy-paste risk factors between filings, so the signal is entirely in what
was added, deleted, or materially reworded. Handing both 260k-char sections to a model
and asking "what changed" is slow, expensive, and invites hallucination, so the work is
split in two:

Stage 1 (deterministic, no network): carve each year's section into individually
comparable units, align them across years with ``difflib``, and reduce every reworded
pair to a compact word-level redline.

Stage 2 (model, residual only): send Claude *only* the additions, deletions, and
redlines — never the unchanged bulk — and ask why each one matters to an investor.
Every quote it returns is then exact-matched back against the source text; anything that
does not appear verbatim is dropped rather than shown to a user.
"""

import json
import os
import re
import time
from difflib import SequenceMatcher

import anthropic


class SectionDiffError(Exception):
    pass


# --------------------------------------------------------------------------------------
# Stage 1 tuning
# --------------------------------------------------------------------------------------

# A heading line survives HTML-to-text extraction as its own short line. Anything longer
# than this is prose, not a heading, no matter how it is punctuated.
HEADING_MAX_CHARS = 200
HEADING_MAX_WORDS = 24

# Filers vary wildly in how they mark up risk factors. Some emit a short bolded title per
# risk ("Supply chain concentration"); others — Apple among them — use a full-sentence
# bolded lead-in that is indistinguishable from body prose once the tags are stripped.
# To stay useful in both worlds, units are additionally cut at paragraph boundaries once
# they grow past a soft ceiling, and at short single-sentence paragraphs that read like a
# lead-in. Both rules are content-derived, so the same cut points fall in both years.
UNIT_SOFT_MAX_CHARS = 2_500
UNIT_MIN_CHARS = 600
LEADIN_MAX_CHARS = 400

# Alignment thresholds, measured as difflib's ratio over normalized word tokens.
UNCHANGED_THRESHOLD = 0.98
SIMILARITY_FLOOR = 0.60

# Cheap gates run before the expensive ratio(). The Dice coefficient over word *sets*
# ignores order and duplication, so it sits above the sequence ratio in practice; the
# margin keeps the gate conservative rather than exact.
_DICE_MARGIN = 0.10

# Words of surrounding context kept on each side of a change in a redline.
REDLINE_CONTEXT_WORDS = 20

# Running headers/footers ("Apple Inc. | 2025 Form 10-K | 12") survive HTML extraction as
# short standalone lines and repeat once per page. Left in, they are read as headings and
# chop units at page boundaries — boundaries that move between years, which turns otherwise
# unchanged text into a cascade of spurious rewordings. A short line whose digit-stripped
# form repeats this many times is page furniture, not content.
_FURNITURE_MAX_CHARS = 120
_FURNITURE_MIN_REPEATS = 3

_SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]?$")
_ENUMERATED_RE = re.compile(r"^(?:[•▪◦\-–—*]|\(?[0-9]{1,2}[.)]|\(?[a-zA-Z][.)]|[IVXLC]{1,5}\.)\s+\S")
_PUNCT_RE = re.compile(r"[^\w\s]+")
_WS_RE = re.compile(r"\s+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — the comparison view of a unit."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text.lower())).strip()


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _paragraphs(text: str) -> list[str]:
    """Blank-line-separated blocks, falling back to single lines when there are none.

    ``filing_sections.html_to_text`` collapses runs of blank lines to exactly one, so
    paragraphs are reliably ``\\n\\n``-separated. Some filers' markup produces no blank
    lines at all, in which case each line is its own block.
    """
    blocks = [_collapse_ws(b) for b in _PARAGRAPH_SPLIT_RE.split(text)]
    blocks = [b for b in blocks if b]
    if len(blocks) > 1:
        return blocks
    return [line.strip() for line in text.split("\n") if line.strip()]


def _drop_running_furniture(paragraphs: list[str]) -> list[str]:
    """Strip repeated page headers/footers and bare page numbers."""
    counts: dict[str, int] = {}
    for paragraph in paragraphs:
        if len(paragraph) <= _FURNITURE_MAX_CHARS:
            key = re.sub(r"\d+", "#", paragraph.lower())
            counts[key] = counts.get(key, 0) + 1

    kept = []
    for paragraph in paragraphs:
        if re.fullmatch(r"[\d\s.\-–—|]+", paragraph):
            continue
        if len(paragraph) <= _FURNITURE_MAX_CHARS:
            if counts.get(re.sub(r"\d+", "#", paragraph.lower()), 0) >= _FURNITURE_MIN_REPEATS:
                continue
        kept.append(paragraph)
    return kept


def _is_title_cased(line: str) -> bool:
    words = [w for w in line.split() if len(w) > 3]
    if len(words) < 2:
        return False
    capitalized = sum(1 for w in words if w[0].isupper())
    return capitalized / len(words) >= 0.6


def _is_heading(line: str) -> bool:
    """Does this line look like a risk-factor / subsection heading?"""
    if not line or len(line) > HEADING_MAX_CHARS:
        return False
    if len(line.split()) > HEADING_MAX_WORDS:
        return False
    if not any(c.isalpha() for c in line):
        return False
    if _ENUMERATED_RE.match(line):
        return True
    if not _SENTENCE_END_RE.search(line):
        return True
    return _is_title_cased(line)


def _is_leadin(paragraph: str) -> bool:
    """A short single-sentence paragraph, i.e. a bolded lead-in that lost its bold."""
    if len(paragraph) > LEADIN_MAX_CHARS:
        return False
    # One terminal sentence mark at the very end and none in the middle.
    interior = paragraph[:-1]
    return bool(_SENTENCE_END_RE.search(paragraph)) and not re.search(r"[.!?]\s", interior)


def _derive_heading(body: str) -> str:
    """Label a unit that had no explicit heading line with its opening sentence."""
    first = _collapse_ws(body)
    match = re.search(r"[.!?]\s", first)
    if match:
        first = first[: match.start() + 1]
    return first[:HEADING_MAX_CHARS].strip()


def split_into_units(text: str) -> list[dict]:
    """Break a section into individually comparable units.

    Returns ``[{"heading": str, "body": str, "index": int}, ...]`` in document order.
    """
    if not text or not text.strip():
        return []

    paragraphs = _drop_running_furniture(_paragraphs(text))
    units: list[dict] = []
    heading = ""
    body_parts: list[str] = []
    body_len = 0

    def flush() -> None:
        nonlocal heading, body_parts, body_len
        body = "\n\n".join(body_parts).strip()
        if body or heading:
            units.append(
                {
                    "heading": heading or _derive_heading(body),
                    "body": body or heading,
                    "index": len(units),
                }
            )
        heading = ""
        body_parts = []
        body_len = 0

    for paragraph in paragraphs:
        if _is_heading(paragraph):
            flush()
            heading = paragraph
            continue
        start_new = body_len >= UNIT_SOFT_MAX_CHARS or (
            body_len >= UNIT_MIN_CHARS and _is_leadin(paragraph)
        )
        if start_new:
            flush()
        body_parts.append(paragraph)
        body_len += len(paragraph) + 2

    flush()
    return units


# --------------------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------------------


def _unit_signature(unit: dict) -> dict:
    heading = unit.get("heading", "")
    body = unit.get("body", "")
    # A derived heading is the body's own opening sentence; counting it twice would
    # over-weight the opening line when scoring.
    combined = body if body.startswith(heading) else f"{heading} {body}"
    tokens = _normalize(combined).split()
    return {"unit": unit, "tokens": tokens, "words": set(tokens), "length": len(tokens)}


def _dice(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def _similarity(left: dict, right: dict, matcher: SequenceMatcher) -> float:
    """Similarity of two unit signatures, with progressively more expensive gates.

    ``ratio()`` is bounded above by ``2 * min(len) / (len_a + len_b)``, so the length gate
    is exact and free. The Dice gate is a cheap set-overlap approximation, and difflib's
    own ``real_quick_ratio``/``quick_ratio`` are true upper bounds on ``ratio``.
    """
    total = left["length"] + right["length"]
    if total == 0:
        return 0.0
    if 2 * min(left["length"], right["length"]) / total < SIMILARITY_FLOOR:
        return 0.0
    if _dice(left["words"], right["words"]) < SIMILARITY_FLOOR - _DICE_MARGIN:
        return 0.0
    matcher.set_seq1(left["tokens"])
    if matcher.real_quick_ratio() < SIMILARITY_FLOOR:
        return 0.0
    if matcher.quick_ratio() < SIMILARITY_FLOOR:
        return 0.0
    return matcher.ratio()


def align_units(prior_units: list[dict], current_units: list[dict]) -> list[dict]:
    """Pair units across two years and classify each pairing.

    Returns one entry per prior unit, current unit, or matched pair::

        {"status": "unchanged"|"reworded"|"added"|"removed",
         "similarity": float | None,
         "prior": unit | None,
         "current": unit | None}
    """
    prior_sigs = [_unit_signature(u) for u in prior_units]
    current_sigs = [_unit_signature(u) for u in current_units]

    candidates: list[tuple[float, int, int]] = []
    for j, current in enumerate(current_sigs):
        # difflib indexes seq2 once and reuses it across set_seq1 calls, so holding the
        # current-year unit fixed in the inner loop is what keeps this affordable.
        matcher = SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(current["tokens"])
        for i, prior in enumerate(prior_sigs):
            score = _similarity(prior, current, matcher)
            if score >= SIMILARITY_FLOOR:
                candidates.append((score, i, j))

    # Greedy best-first pairing: the strongest available match wins, and both of its
    # units leave the pool. Cheap, order-independent, and good enough at this scale.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    prior_taken: dict[int, tuple[int, float]] = {}
    current_taken: dict[int, tuple[int, float]] = {}
    for score, i, j in candidates:
        if i in prior_taken or j in current_taken:
            continue
        prior_taken[i] = (j, score)
        current_taken[j] = (i, score)

    results: list[dict] = []
    for j, current in enumerate(current_units):
        if j in current_taken:
            i, score = current_taken[j]
            status = "unchanged" if score >= UNCHANGED_THRESHOLD else "reworded"
            results.append(
                {
                    "status": status,
                    "similarity": round(score, 4),
                    "prior": prior_units[i],
                    "current": current,
                }
            )
        else:
            results.append(
                {"status": "added", "similarity": None, "prior": None, "current": current}
            )
    for i, prior in enumerate(prior_units):
        if i not in prior_taken:
            results.append(
                {"status": "removed", "similarity": None, "prior": prior, "current": None}
            )
    return results


# --------------------------------------------------------------------------------------
# Redline
# --------------------------------------------------------------------------------------


def _emit_equal(segments: list[dict], words: list[str], is_first: bool, is_last: bool) -> None:
    """Append an ``equal`` run, eliding the middle (or the outer edge) when it is long."""
    if not words:
        return
    context = REDLINE_CONTEXT_WORDS
    if is_first and is_last:
        segments.append({"op": "equal", "text": " ".join(words)})
        return
    if is_first:
        if len(words) > context:
            segments.append(
                {"op": "equal", "text": " ".join(words[-context:]), "elided": len(words) - context}
            )
        else:
            segments.append({"op": "equal", "text": " ".join(words)})
        return
    if is_last:
        if len(words) > context:
            segments.append(
                {"op": "equal", "text": " ".join(words[:context]), "elided": len(words) - context}
            )
        else:
            segments.append({"op": "equal", "text": " ".join(words)})
        return
    if len(words) > 2 * context:
        segments.append({"op": "equal", "text": " ".join(words[:context])})
        segments.append(
            {"op": "equal", "text": "…", "elided": len(words) - 2 * context}
        )
        segments.append({"op": "equal", "text": " ".join(words[-context:])})
    else:
        segments.append({"op": "equal", "text": " ".join(words)})


def word_level_redline(prior_body: str, current_body: str) -> list[dict]:
    """Word-granularity redline of one reworded pair.

    Returns ``[{"op": "equal"|"insert"|"delete", "text": "..."}, ...]``. Long stretches of
    unchanged text are trimmed to ``REDLINE_CONTEXT_WORDS`` on each side of a change and
    replaced with an ellipsis segment carrying an ``elided`` word count, so the frontend
    renders only the changed neighbourhoods.
    """
    prior_words = prior_body.split()
    current_words = current_body.split()
    opcodes = SequenceMatcher(None, prior_words, current_words, autojunk=False).get_opcodes()

    segments: list[dict] = []
    for n, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            _emit_equal(
                segments,
                prior_words[i1:i2],
                is_first=(n == 0),
                is_last=(n == len(opcodes) - 1),
            )
        elif tag == "delete":
            segments.append({"op": "delete", "text": " ".join(prior_words[i1:i2])})
        elif tag == "insert":
            segments.append({"op": "insert", "text": " ".join(current_words[j1:j2])})
        elif tag == "replace":
            segments.append({"op": "delete", "text": " ".join(prior_words[i1:i2])})
            segments.append({"op": "insert", "text": " ".join(current_words[j1:j2])})
    return segments


def _render_redline(segments: list[dict]) -> str:
    """Flatten a redline into the inline-marker form the model reads."""
    parts = []
    for segment in segments:
        text = segment["text"]
        if segment["op"] == "insert":
            parts.append(f"{{+{text}+}}")
        elif segment["op"] == "delete":
            parts.append(f"[-{text}-]")
        elif segment.get("elided"):
            parts.append(text if text == "…" else f"{text} …")
        else:
            parts.append(text)
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------------------
# Stage 2 — Claude on the residual
# --------------------------------------------------------------------------------------

DIFF_SYSTEM_PROMPT = """You are a financial-filing analyst comparing one narrative section of a company's 10-K against the same section in the prior year's 10-K.

The unchanged bulk of the section has already been removed. You are shown ONLY what changed:
- ADDED: a passage that appears in the current year and had no counterpart last year.
- REMOVED: a passage that appeared last year and has no counterpart this year.
- REWORDED: a passage present in both years. You are shown an annotated redline where
  [-text-] was deleted and {+text+} was inserted ("…" marks unchanged text trimmed for
  brevity), followed by the clean prior-year and current-year wording. Read the redline to
  see what changed; quote only from the clean wording.

For each item, explain why the change matters to an investor. Return ONLY this JSON — no
markdown fences, no extra text:

{
  "changes": [
    {
      "id": 3,
      "severity": "red" | "yellow" | "green",
      "significance": "one plain-English sentence on why an investor should care",
      "quote": "Verbatim excerpt from the item's text supporting this (max 300 chars)"
    }
  ]
}

Rules:
- Return exactly one object per item you are given, reusing that item's "id". Do not invent ids.
- severity: red = materially worse or newly disclosed exposure an investor should act on;
  yellow = worth noting, ambiguous or moderate; green = boilerplate, cosmetic, or immaterial
  (legal-language tidying, reordering, updated dates or figures with no change in substance).
- A REMOVED risk is high signal: a company dropping a disclosed risk is asserting that the
  exposure is gone or immaterial. Say what its removal implies. Never rate a removal green
  purely because the text is short.
- significance: one sentence, plain English, specific to THIS company and THIS change.
  No hedging boilerplate like "this could affect the business."
- quote: copy a span character-for-character from a block labelled "QUOTE FROM HERE".
  Never quote from the annotated redline block — its [-...-], {+...+} and "…" markers do not
  appear in the filing, so any span containing them fails verification. For a REWORDED item
  use the current-year wording, or the prior-year wording when your point is about language
  that was removed. Never paraphrase and never merge two separated spans. Every quote is
  exact-matched against the filing and findings whose quote is not found are discarded, so an
  unverifiable quote loses the whole finding.
- Return ONLY valid JSON. No markdown. No explanation."""

DIFF_STRICT_SYSTEM_PROMPT = (
    DIFF_SYSTEM_PROMPT
    + "\n\nCRITICAL: Your previous response was not valid JSON. Return ONLY a raw JSON object "
      'with a top-level "changes" array. No ```json wrapper. Every entry needs an id that was '
      "given to you and a verbatim quote."
)

# ~30k tokens of residual; well under a dollar a request and leaves headroom for the reply.
MAX_DIFF_INPUT_CHARS = 120_000
# Per-item excerpt cap, so one enormous risk factor cannot eat the whole budget.
MAX_ITEM_CHARS = 4_000
DIFF_CLAUDE_BUDGET_SECONDS = 180
_MIN_CALL_SECONDS = 10

_MAX_QUOTE_CHARS = 600

# A 10-K's narrative Items carry financial tables inline, and once flattened to text a
# table row splits into its own "unit". Diffing those produces noise like "Statutory
# federal income tax rate 21 % 21 % 21 %" — technically changed, never worth reading.
# The financial history table already shows the numbers properly.
# Kept low deliberately: real risk factors can be a single short sentence, so length
# alone is a poor filter. Numeric density does most of the work here.
_MIN_NARRATIVE_WORDS = 6
_MAX_NUMERIC_TOKEN_SHARE = 0.35
_NUMERIC_TOKEN_RE = re.compile(r"^[\$\(\)%,.\d/–—-]+$")


def _is_narrative(text: str) -> bool:
    """True when a unit reads as prose rather than as a flattened table row."""
    tokens = text.split()
    if len(tokens) < _MIN_NARRATIVE_WORDS:
        return False
    numeric = sum(1 for token in tokens if _NUMERIC_TOKEN_RE.match(token))
    return numeric / len(tokens) < _MAX_NUMERIC_TOKEN_SHARE


def narrative_units(units: list[dict]) -> list[dict]:
    """Drop flattened table rows so the diff reports prose changes only."""
    return [unit for unit in units if _is_narrative(unit.get("body", ""))]


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
                f"Exhausted the {budget_seconds}s Claude budget before completing the diff "
                f"({remaining:.1f}s remaining)"
            )
        active_system = system if attempt == 0 else strict_system
        # max_retries=0 for the same reason as claude_client: our own loop already retries
        # once, and the SDK's retry would multiply wall-clock time past the deadline.
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


def _render_items(items: list[dict], section_label: str, prior_year: int, current_year: int) -> str:
    lines = [
        f"Section: {section_label}",
        f"Prior filing: FY{prior_year}    Current filing: FY{current_year}",
        f"Changed items: {len(items)}",
        "",
    ]
    for item in items:
        lines.append(f"--- ITEM id={item['id']} type={item['changeType'].upper()} ---")
        if item.get("heading"):
            lines.append(f"Heading: {item['heading']}")
        if item.get("similarity") is not None:
            lines.append(f"Similarity to prior year: {item['similarity']:.2f}")
        if item.get("redlineText"):
            lines.append("What changed (annotated redline — do NOT quote from this block):")
            lines.append(item["redlineText"])
            lines.append("Current-year wording (QUOTE FROM HERE):")
            lines.append(item["text"])
            if item.get("priorText"):
                lines.append(
                    "Prior-year wording (QUOTE FROM HERE if your point is about removed language):"
                )
                lines.append(item["priorText"])
        else:
            lines.append("Passage (QUOTE FROM HERE):")
            lines.append(item["text"])
        lines.append("")
    return "\n".join(lines)


def analyze_section_diff(
    items: list[dict], section_label: str, prior_year: int, current_year: int
) -> dict:
    """Default Stage-2 implementation: ask Claude why the residual changes matter."""
    return _call_claude_with_retry(
        DIFF_SYSTEM_PROMPT,
        DIFF_STRICT_SYSTEM_PROMPT,
        _render_items(items, section_label, prior_year, current_year),
        max_tokens=4096,
        budget_seconds=DIFF_CLAUDE_BUDGET_SECONDS,
    )


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------

_TYPE_RANK = {"removed": 0, "added": 1, "reworded": 2}
_SEVERITY_RANK = {"red": 0, "yellow": 1, "green": 2}


def _candidate_changes(alignment: list[dict]) -> list[dict]:
    """Turn alignment entries into ranked change candidates, most load-bearing first.

    A deletion is the single highest-signal finding this feature produces, so removals sort
    ahead of additions and both sort ahead of rewordings. When the payload has to be
    trimmed it is trimmed from the tail, which means rewordings go first and deletions
    are never dropped in favour of one.
    """
    candidates: list[dict] = []
    for entry in alignment:
        status = entry["status"]
        if status == "unchanged":
            continue
        redline_text = None
        prior_text = None
        if status == "added":
            unit = entry["current"]
            text = unit["body"][:MAX_ITEM_CHARS]
            redline = None
        elif status == "removed":
            unit = entry["prior"]
            text = unit["body"][:MAX_ITEM_CHARS]
            redline = None
        else:
            unit = entry["current"]
            redline = word_level_redline(entry["prior"]["body"], unit["body"])
            # The rendered redline is annotation, not filing text: its [-...-] and {+...+}
            # markers appear nowhere in the source, so a quote taken from it can never pass
            # the verbatim check. The model gets it for context and quotes from the clean
            # prior/current wording instead.
            redline_text = _render_redline(redline)[:MAX_ITEM_CHARS]
            text = unit["body"][: MAX_ITEM_CHARS // 2]
            prior_text = entry["prior"]["body"][: MAX_ITEM_CHARS // 2]
        candidates.append(
            {
                "changeType": status,
                "heading": unit.get("heading", ""),
                "text": text,
                "redlineText": redline_text,
                "priorText": prior_text,
                "redline": redline,
                "similarity": entry["similarity"],
                "_order": (
                    _TYPE_RANK[status],
                    # Within rewordings, the most-changed pair (lowest similarity) is the
                    # most likely to be substantive, so it survives trimming longest.
                    entry["similarity"] if entry["similarity"] is not None else 0.0,
                    -len(text),
                ),
            }
        )
    candidates.sort(key=lambda c: c["_order"])
    for i, candidate in enumerate(candidates):
        candidate["id"] = i
        del candidate["_order"]
    return candidates


def _budget(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split candidates into (kept, omitted) under the payload character cap."""
    kept: list[dict] = []
    omitted: list[dict] = []
    used = 0
    for candidate in candidates:
        cost = (
            len(candidate["text"])
            + len(candidate.get("redlineText") or "")
            + len(candidate.get("priorText") or "")
            + len(candidate["heading"])
            + 160
        )
        # Once anything is dropped, everything after it is dropped too: candidates are
        # already in priority order, so skipping ahead to a cheaper low-signal item would
        # defeat the ordering. The highest-priority item always goes, whatever it costs.
        if kept and (omitted or used + cost > MAX_DIFF_INPUT_CHARS):
            omitted.append(candidate)
        else:
            kept.append(candidate)
            used += cost
    return kept, omitted


def _quote_is_verbatim(quote: str, haystacks: list[str]) -> bool:
    """Whitespace-normalized exact containment. Anything else is a hallucination."""
    if not quote or not quote.strip():
        return False
    needle = _collapse_ws(quote)
    if len(needle) > _MAX_QUOTE_CHARS:
        return False
    return any(needle in hay for hay in haystacks)


def diff_section(
    prior_text: str,
    current_text: str,
    section_label: str,
    prior_year: int,
    current_year: int,
    analyze=None,
) -> dict:
    """Diff one 10-K Item against the prior year's and explain what changed.

    ``analyze`` is the Stage-2 seam: a callable
    ``(items, section_label, prior_year, current_year) -> dict``. It defaults to
    :func:`analyze_section_diff`, which calls Claude; tests inject a stub.

    Raises :class:`SectionDiffError` if either text is empty or Stage 2 fails.
    """
    if not prior_text or not prior_text.strip():
        raise SectionDiffError("prior_text is empty")
    if not current_text or not current_text.strip():
        raise SectionDiffError("current_text is empty")

    prior_units = narrative_units(split_into_units(prior_text))
    current_units = narrative_units(split_into_units(current_text))
    alignment = align_units(prior_units, current_units)

    stats = {
        "unchanged": sum(1 for e in alignment if e["status"] == "unchanged"),
        "reworded": sum(1 for e in alignment if e["status"] == "reworded"),
        "added": sum(1 for e in alignment if e["status"] == "added"),
        "removed": sum(1 for e in alignment if e["status"] == "removed"),
        "priorTotal": len(prior_units),
        "currentTotal": len(current_units),
    }

    result = {
        "section": section_label,
        "priorYear": prior_year,
        "currentYear": current_year,
        "stats": stats,
        "changes": [],
        "omittedChangeCount": 0,
        "analyzedChangeCount": 0,
        "droppedForUnverifiedQuoteCount": 0,
    }

    candidates = _candidate_changes(alignment)
    if not candidates:
        return result

    kept, omitted = _budget(candidates)
    result["analyzedChangeCount"] = len(kept)
    result["omittedChangeCount"] = len(omitted)

    analyzer = analyze or analyze_section_diff
    try:
        response = analyzer(kept, section_label, prior_year, current_year)
    except SectionDiffError:
        raise
    except Exception as e:
        raise SectionDiffError(f"Failed to analyze changed sections: {e}") from e

    if not isinstance(response, dict):
        raise SectionDiffError("Stage-2 analyzer returned a non-object response")

    by_id = {}
    for entry in response.get("changes") or []:
        if isinstance(entry, dict) and entry.get("id") is not None:
            try:
                by_id[int(entry["id"])] = entry
            except (TypeError, ValueError):
                continue

    prior_haystack = _collapse_ws(prior_text)
    current_haystack = _collapse_ws(current_text)

    changes: list[dict] = []
    dropped = 0
    for candidate in kept:
        entry = by_id.get(candidate["id"])
        if entry is None:
            # The model skipped this item; there is nothing to show a user without a
            # significance line, so it is reported as omitted rather than rendered blank.
            dropped += 1
            continue
        if candidate["changeType"] == "removed":
            haystacks = [prior_haystack]
        elif candidate["changeType"] == "added":
            haystacks = [current_haystack]
        else:
            haystacks = [current_haystack, prior_haystack]
        quote = entry.get("quote") or ""
        if not _quote_is_verbatim(quote, haystacks):
            dropped += 1
            continue
        severity = entry.get("severity")
        if severity not in _SEVERITY_RANK:
            severity = "yellow"
        changes.append(
            {
                "changeType": candidate["changeType"],
                "heading": candidate["heading"],
                "severity": severity,
                "significance": (entry.get("significance") or "").strip(),
                "quote": _collapse_ws(quote),
                "redline": candidate["redline"],
                "similarity": candidate["similarity"],
            }
        )

    changes.sort(
        key=lambda c: (
            _TYPE_RANK[c["changeType"]],
            _SEVERITY_RANK[c["severity"]],
            c["similarity"] if c["similarity"] is not None else 0.0,
        )
    )
    result["changes"] = changes
    result["droppedForUnverifiedQuoteCount"] = dropped
    result["omittedChangeCount"] += dropped
    result["analyzedChangeCount"] = len(changes)
    return result
