import pytest
from app.services.pdf_parser import extract_text, extract_pages, format_paginated_text, validate_text


def _make_pdf(text: str) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


def test_extract_text_returns_text_from_valid_pdf():
    pdf_bytes = _make_pdf("This is a sample lease agreement with enough content.")
    result = extract_text(pdf_bytes)
    assert "lease" in result.lower()


def test_extract_text_returns_string():
    pdf_bytes = _make_pdf("Hello world")
    assert isinstance(extract_text(pdf_bytes), str)


def test_validate_text_passes_on_sufficient_text():
    long_text = "x" * 600
    validate_text(long_text)  # should not raise


def test_validate_text_raises_on_short_text():
    with pytest.raises(ValueError, match="scanned image"):
        validate_text("too short")


def test_extract_pages_returns_one_string_per_page():
    pdf_bytes = _make_pdf("This is a sample filing with enough content.")
    pages = extract_pages(pdf_bytes)
    assert isinstance(pages, list)
    assert len(pages) == 1
    assert "filing" in pages[0].lower()


def test_format_paginated_text_emits_ordered_page_markers():
    result = format_paginated_text(["first page text", "second page text"])
    assert "[PAGE 1]\nfirst page text" in result
    assert "[PAGE 2]\nsecond page text" in result
    assert result.index("[PAGE 1]") < result.index("[PAGE 2]")
