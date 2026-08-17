import io

import pdfplumber

MIN_CHARS = 500


def extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages).strip()


def extract_pages(pdf_bytes: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def format_paginated_text(pages: list[str]) -> str:
    return "\n\n".join(f"[PAGE {i + 1}]\n{text}" for i, text in enumerate(pages))


def validate_text(text: str) -> None:
    if len(text) < MIN_CHARS:
        raise ValueError(
            "This lease appears to be a scanned image — "
            "we can only analyze text-based PDFs right now."
        )
