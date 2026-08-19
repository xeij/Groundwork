import io
from typing import Callable, Optional

import pdfplumber

MIN_CHARS = 500

OnProgress = Callable[[int, int], None]


def _report_every(total: int) -> int:
    """Cap real-time progress reports to ~10 for the whole document, regardless of length."""
    return max(1, total // 10)


def extract_text(pdf_bytes: bytes, on_progress: Optional[OnProgress] = None) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        interval = _report_every(total)
        parts = []
        for i, page in enumerate(pdf.pages, start=1):
            parts.append(page.extract_text() or "")
            if on_progress and (i % interval == 0 or i == total):
                on_progress(i, total)
    return "\n\n".join(parts).strip()


def extract_pages(pdf_bytes: bytes, on_progress: Optional[OnProgress] = None) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        interval = _report_every(total)
        pages = []
        for i, page in enumerate(pdf.pages, start=1):
            pages.append(page.extract_text() or "")
            if on_progress and (i % interval == 0 or i == total):
                on_progress(i, total)
    return pages


def format_paginated_text(pages: list[str]) -> str:
    return "\n\n".join(f"[PAGE {i + 1}]\n{text}" for i, text in enumerate(pages))


def validate_text(text: str) -> None:
    if len(text) < MIN_CHARS:
        raise ValueError(
            "This lease appears to be a scanned image — "
            "we can only analyze text-based PDFs right now."
        )
