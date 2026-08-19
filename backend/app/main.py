import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from .routes import upload, analyze, summary, stock_chart, company

logger = logging.getLogger(__name__)

app = FastAPI(title="Groundwork API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(summary.router)
app.include_router(stock_chart.router)
app.include_router(company.router)

_mangum = Mangum(app)


def handler(event, context):
    # Direct async invocation — runs the long Claude analysis outside API Gateway's 30s limit
    if "summaryId" in event and "s3Key" in event:
        _process_async(event["summaryId"], event["s3Key"])
        return
    if "summaryId" in event and "ticker" in event:
        _process_ticker_async(event["summaryId"], event["ticker"])
        return

    return _mangum(event, context)


def _process_ticker_async(summary_id: str, ticker: str) -> None:
    """Full EDGAR-sourced analysis: no S3 object is involved, so nothing to clean up."""
    from .services import filing_pipeline
    from .services.summary_store import update_summary, mark_failed, update_progress

    def report(step: str, detail: str | None = None) -> None:
        update_progress(summary_id, step, detail)

    try:
        result = filing_pipeline.analyze_ticker(ticker, progress=report)
        update_summary(summary_id, result)
    except Exception as e:
        logger.exception("Ticker analysis failed for %s (%s)", summary_id, ticker)
        mark_failed(summary_id, str(e))


def _process_async(summary_id: str, s3_key: str) -> None:
    from .models import document_type_from_s3_key
    from .services import storage, pdf_parser, claude_client
    from .services.summary_store import update_summary, mark_failed, update_progress

    document_type = document_type_from_s3_key(s3_key)

    def report_page_progress(current: int, total: int) -> None:
        update_progress(summary_id, "extracting_text", f"Reading page {current} of {total}")

    try:
        update_progress(summary_id, "extracting_text")
        pdf_bytes = storage.fetch_pdf(s3_key)
        try:
            if document_type == "filing":
                pages = pdf_parser.extract_pages(pdf_bytes, on_progress=report_page_progress)
                pdf_parser.validate_text("\n\n".join(pages))
                text = pdf_parser.format_paginated_text(pages)
            else:
                text = pdf_parser.extract_text(pdf_bytes, on_progress=report_page_progress)
                pdf_parser.validate_text(text)
        except Exception as e:
            storage.delete_pdf(s3_key)
            mark_failed(summary_id, str(e))
            return
        update_progress(summary_id, "analyzing")
        if document_type == "filing":
            result = claude_client.analyze_financial_filing(text)
        else:
            result = claude_client.analyze_lease(text)
        update_progress(summary_id, "finalizing")
        storage.delete_pdf(s3_key)
        update_summary(summary_id, result)
    except Exception:
        logger.exception("Async processing failed for %s", summary_id)
        try:
            storage.delete_pdf(s3_key)
        except Exception:
            pass
        mark_failed(summary_id, "Unexpected error during analysis.")
