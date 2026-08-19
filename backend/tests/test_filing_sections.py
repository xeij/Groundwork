from app.services import filing_sections as fs
from app.services.filing_sections import (
    extract_filing_sections,
    html_to_text,
    section_label,
    split_sections,
)


def _body(item: str, filler: str, chars: int = 800) -> str:
    return f"Item {item}. Heading\n{(filler + ' ') * chars}\n"


def test_html_to_text_drops_script_and_style():
    html = "<html><head><style>p{color:red}</style><script>alert(1)</script></head><body><p>Real prose.</p></body></html>"
    assert html_to_text(html) == "Real prose."


def test_html_to_text_drops_inline_xbrl_header():
    """EDGAR filings carry a large machine-readable ix:header that is not prose."""
    html = (
        "<html><body><ix:header><ix:hidden>context ref noise</ix:hidden>"
        "<div>more plumbing</div></ix:header><p>Item 1. Business</p></body></html>"
    )
    text = html_to_text(html)
    assert "noise" not in text and "plumbing" not in text
    assert "Item 1. Business" in text


def test_html_to_text_unescapes_entities_and_normalizes_nbsp():
    assert html_to_text("<p>Tom&nbsp;&amp;&nbsp;Jerry</p>") == "Tom & Jerry"


def test_html_to_text_separates_block_elements():
    text = html_to_text("<p>First</p><p>Second</p>")
    assert "First" in text and "Second" in text
    assert "FirstSecond" not in text


def test_html_to_text_keeps_table_cells_apart():
    text = html_to_text("<table><tr><td>Revenue</td><td>391,035</td></tr></table>")
    assert "Revenue" in text and "391,035" in text
    assert "Revenue391,035" not in text


def test_split_sections_finds_items_and_bounds_them():
    text = _body("1", "business") + _body("1A", "risk") + _body("7", "mdna")
    sections = split_sections(text)
    assert set(sections) == {"1", "1A", "7"}
    assert "business" in sections["1"] and "risk" not in sections["1"]
    assert "risk" in sections["1A"]


def test_split_sections_drops_the_contents_page():
    """A contents page lists every Item back to back; those are not section starts."""
    toc = "\n".join(f"Item {i}. Title {i}" for i in
                    ["1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8"])
    text = toc + "\n" + _body("1", "business") + _body("1A", "risk")
    sections = split_sections(text)
    assert "business" in sections["1"]
    # The Item 1 body must start at the real heading, not at the contents entry.
    assert "Title 1A" not in sections["1"]


def test_split_sections_keeps_part_iii_stubs_despite_tight_spacing():
    """Part III items are short and closely spaced but are real sections, not a TOC."""
    text = _body("1", "business", 2000) + "".join(
        f"Item {i}. Heading\nThe information required is incorporated by reference. " * 6 + "\n"
        for i in ["10", "11", "12", "13", "14"]
    )
    sections = split_sections(text)
    assert {"10", "11", "12", "13", "14"} <= set(sections)


def test_split_sections_ignores_backward_cross_references():
    """Prose saying 'see Item 1A' must not restart the risk factors section."""
    text = (
        _body("1", "business")
        + _body("1A", "risk")
        + "Item 7. MD&A\n" + ("discussion " * 500)
        + "For more detail see Item 1A above.\n"
        + ("more discussion " * 300)
    )
    sections = split_sections(text)
    assert "discussion" in sections["7"]
    assert "more discussion" in sections["7"]


def test_split_sections_drops_sections_below_the_minimum_length():
    text = _body("1", "business") + "Item 1B. Unresolved Staff Comments\nNone.\n" + _body("7", "mdna")
    assert "1B" not in split_sections(text)


def test_split_sections_returns_empty_for_text_without_items():
    assert split_sections("Just some prose with no item headings at all.") == {}


def test_section_label_uses_the_canonical_title():
    assert section_label("1A") == "Item 1A. Risk Factors"
    assert section_label("99") == "Item 99"


def test_extract_filing_sections_returns_text_and_sections():
    html = "<html><body>" + "".join(
        f"<p>Item {i}. Heading</p><p>{'word ' * 400}</p>" for i in ["1", "1A", "7"]
    ) + "</body></html>"
    text, sections = extract_filing_sections(html)
    assert set(sections) == {"1", "1A", "7"}
    assert len(text) > 1000


def test_toc_detection_requires_a_long_run_near_the_front():
    """Two adjacent headings are not a contents page, however close together."""
    matches = [("1", 100), ("1A", 150)]
    assert fs._drop_table_of_contents(matches, 100_000) == matches
