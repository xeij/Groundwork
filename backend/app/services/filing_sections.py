"""Turn a 10-K's HTML into plain text and carve it into its numbered Items.

Working from EDGAR's HTML rather than a rendered PDF is what makes whole-filing
analysis possible: sections can be extracted and budgeted individually, so the
footnotes at the back are no longer dropped by a front-of-document character cap.
"""

import re
from html import unescape
from html.parser import HTMLParser
from typing import Optional

# Tags whose text content is markup plumbing, not filing prose. EDGAR's inline-XBRL
# documents carry a large <ix:header> block of machine-readable facts near the top;
# left in, it lands in the middle of Item 1 as a wall of context-ref noise.
_DROP_TAGS = {"script", "style", "ix:header", "ix:hidden"}

_BLOCK_TAGS = {
    "p", "div", "br", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "ul", "ol", "section", "article", "header", "footer", "hr",
}

# Canonical 10-K Items, in the order Regulation S-K requires them to appear.
ITEM_SEQUENCE = [
    "1", "1A", "1B", "1C", "2", "3", "4",
    "5", "6", "7", "7A", "8", "9", "9A", "9B", "9C",
    "10", "11", "12", "13", "14", "15", "16",
]

ITEM_TITLES = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Selected Financial Data",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership of Certain Beneficial Owners",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

_ITEM_RE = re.compile(
    r"(?:^|\n)\s*Item\s+(?P<item>\d{1,2}[A-C]?)\s*[.:–—\-]?\s",
    re.IGNORECASE,
)

# A contents page lists every Item back-to-back, so its headings form a long run of
# tightly-spaced matches near the front of the document. Body headings have the
# section's prose between them. The Part III cross-reference stubs near the *end* of a
# 10-K are also short and tightly spaced, which is why position matters as well as
# density -- those stubs are real sections and must survive.
_TOC_MAX_ENTRY_GAP = 400
_TOC_MIN_RUN_LENGTH = 8
_TOC_MAX_START_FRACTION = 0.2

MIN_SECTION_CHARS = 200


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._suppress_depth = 0
        self._suppressing_tag: Optional[str] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._suppressing_tag is not None:
            if tag == self._suppressing_tag:
                self._suppress_depth += 1
            return
        if tag in _DROP_TAGS:
            self._suppressing_tag = tag
            self._suppress_depth = 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        elif tag == "td" or tag == "th":
            self._parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if self._suppressing_tag is not None:
            if tag == self._suppressing_tag:
                self._suppress_depth -= 1
                if self._suppress_depth <= 0:
                    self._suppressing_tag = None
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if self._suppressing_tag is None and tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._suppressing_tag is None:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = unescape(parser.text())
    text = text.replace("\xa0", " ").replace("​", "")
    # Collapse runs of spaces/tabs, then runs of blank lines, without gluing words together.
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _item_matches(text: str) -> list[tuple[str, int]]:
    return [
        (m.group("item").upper(), m.start())
        for m in _ITEM_RE.finditer(text)
    ]


def _drop_table_of_contents(
    matches: list[tuple[str, int]], text_length: int
) -> list[tuple[str, int]]:
    """Discard Item headings belonging to a contents page."""
    if not matches:
        return matches

    cutoff = text_length * _TOC_MAX_START_FRACTION
    order = {item: i for i, item in enumerate(ITEM_SEQUENCE)}

    # A run breaks on a wide gap, and also whenever the Item sequence stops advancing.
    # A contents page enumerates the Items in order and the body then starts again from
    # Item 1, so that restart is a reliable boundary even when the body follows the
    # contents page immediately with no intervening text.
    runs: list[list[int]] = [[0]]
    for i in range(1, len(matches)):
        close = matches[i][1] - matches[i - 1][1] <= _TOC_MAX_ENTRY_GAP
        ascending = order.get(matches[i][0], -1) > order.get(matches[i - 1][0], -1)
        if close and ascending:
            runs[-1].append(i)
        else:
            runs.append([i])

    dropped = {
        i
        for run in runs
        if len(run) >= _TOC_MIN_RUN_LENGTH and matches[run[0]][1] <= cutoff
        for i in run
    }
    kept = [m for i, m in enumerate(matches) if i not in dropped]
    # A filing with no discernible body headings (some smaller filers run everything
    # together) is better served by the unfiltered list than by nothing at all.
    return kept or matches


def _select_starts(matches: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """One offset per Item, walking ITEM_SEQUENCE forward so the result is ordered.

    Items get cross-referenced inside other sections ("see Item 1A"), so an Item can
    match many times. Taking the first occurrence at or after the previous Item's
    start keeps the walk monotonic and ignores backward references.
    """
    by_item: dict[str, list[int]] = {}
    for item, offset in matches:
        by_item.setdefault(item, []).append(offset)

    selected: list[tuple[str, int]] = []
    cursor = -1
    for item in ITEM_SEQUENCE:
        offsets = [o for o in by_item.get(item, []) if o > cursor]
        if not offsets:
            continue
        start = min(offsets)
        selected.append((item, start))
        cursor = start
    return selected


def split_sections(text: str) -> dict[str, str]:
    """Map Item number ("1A", "7") to that Item's text. Short/empty Items are dropped."""
    starts = _select_starts(_drop_table_of_contents(_item_matches(text), len(text)))
    if not starts:
        return {}

    sections: dict[str, str] = {}
    for i, (item, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        body = text[start:end].strip()
        if len(body) >= MIN_SECTION_CHARS:
            sections[item] = body
    return sections


def section_label(item: str) -> str:
    title = ITEM_TITLES.get(item)
    return f"Item {item}. {title}" if title else f"Item {item}"


def extract_filing_sections(html: str) -> tuple[str, dict[str, str]]:
    """Convenience wrapper: raw HTML in, (full text, sections by Item) out."""
    text = html_to_text(html)
    return text, split_sections(text)
