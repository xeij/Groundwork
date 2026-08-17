import json
import os

import boto3
from fastapi import APIRouter

from ..models import AnalyzeRequest, AnalyzeResponse, document_type_from_s3_key
from ..services.summary_store import generate_summary_id, save_pending

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    summary_id = generate_summary_id()
    document_type = document_type_from_s3_key(request.s3Key)
    save_pending(summary_id, request.s3Key, document_type)

    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"summaryId": summary_id, "s3Key": request.s3Key}).encode(),
    )

    return AnalyzeResponse(summaryId=summary_id)
