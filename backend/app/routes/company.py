import json
import os

import boto3
from fastapi import APIRouter, HTTPException, Query

from ..models import AnalyzeResponse, AnalyzeTickerRequest, CompanySearchResult
from ..services import edgar
from ..services.summary_store import generate_summary_id, save_pending

router = APIRouter()

_MAX_SEARCH_RESULTS = 10


@router.get("/companies", response_model=list[CompanySearchResult])
def search_companies(q: str = Query(min_length=1, max_length=60)):
    """Typeahead over every SEC filer with a listed ticker."""
    try:
        companies = edgar.search_companies(q, limit=_MAX_SEARCH_RESULTS)
    except edgar.EdgarError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return [CompanySearchResult(**c) for c in companies]


@router.post("/analyze-ticker", response_model=AnalyzeResponse)
def analyze_ticker(request: AnalyzeTickerRequest):
    # Resolve before accepting the job so an unknown ticker fails fast with a clear
    # message, rather than becoming a `failed` record the user has to poll for.
    try:
        edgar.resolve_ticker(request.ticker)
    except edgar.EdgarError as e:
        raise HTTPException(status_code=404, detail=str(e))

    summary_id = generate_summary_id()
    save_pending(summary_id, document_type="filing", ticker=request.ticker)

    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"summaryId": summary_id, "ticker": request.ticker}).encode(),
    )

    return AnalyzeResponse(summaryId=summary_id)
