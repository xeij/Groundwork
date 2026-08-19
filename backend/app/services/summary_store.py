import math
import os
import time
import uuid
from decimal import Decimal

import boto3

TTL_DAYS = 90
PENDING_TTL_HOURS = 1


def to_dynamo(value):
    """Recursively convert floats to Decimal on the way into DynamoDB.

    The resource-level DynamoDB client rejects Python floats outright. Analyses carry
    a lot of them (ratios, forensic scores, similarity, percentiles), so the conversion
    happens once here rather than at every producer. NaN and infinity have no DynamoDB
    representation and are dropped to None rather than blowing up a whole analysis.
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value):
    """Recursively convert DynamoDB Decimals back to int/float.

    Without this, Decimals reach FastAPI's JSON encoder inside loosely-typed fields
    such as `financialHistory` and fail to serialize.
    """
    if isinstance(value, Decimal):
        as_float = float(value)
        return int(as_float) if as_float.is_integer() else as_float
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def _table():
    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    return dynamodb.Table(os.getenv("DYNAMODB_TABLE_NAME", ""))


def generate_summary_id() -> str:
    return uuid.uuid4().hex[:8]


def save_pending(
    summary_id: str,
    s3_key: str | None = None,
    document_type: str = "lease",
    ticker: str | None = None,
) -> None:
    """Reserve a summary id. Sourced either from an uploaded PDF or from an EDGAR ticker."""
    created_at = int(time.time())
    item = {
        "summaryId": summary_id,
        "status": "pending",
        "documentType": document_type,
        "createdAt": created_at,
        "ttl": created_at + PENDING_TTL_HOURS * 3600,
    }
    if s3_key is not None:
        item["s3Key"] = s3_key
    if ticker is not None:
        item["ticker"] = ticker
    _table().put_item(Item=item)


def update_progress(summary_id: str, step: str, detail: str | None = None) -> None:
    # detail is always written (even as None) so a stale message from a prior step never
    # leaks forward onto the next one.
    _table().update_item(
        Key={"summaryId": summary_id},
        UpdateExpression="SET step = :step, detail = :detail",
        ExpressionAttributeValues={":step": step, ":detail": detail},
    )


def update_summary(summary_id: str, summary: dict) -> None:
    _table().update_item(
        Key={"summaryId": summary_id},
        UpdateExpression="SET #s = :s, summary = :summary, #t = :t",
        ExpressionAttributeNames={"#s": "status", "#t": "ttl"},
        ExpressionAttributeValues={
            ":s": "done",
            ":summary": to_dynamo(summary),
            ":t": int(time.time()) + TTL_DAYS * 86400,
        },
    )


def mark_failed(summary_id: str, error: str) -> None:
    _table().update_item(
        Key={"summaryId": summary_id},
        UpdateExpression="SET #s = :s, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": "failed", ":e": error},
    )


def save_summary(summary: dict, document_type: str = "lease") -> str:
    summary_id = generate_summary_id()
    created_at = int(time.time())
    _table().put_item(
        Item={
            "summaryId": summary_id,
            "status": "done",
            "summary": to_dynamo(summary),
            "documentType": document_type,
            "createdAt": created_at,
            "ttl": created_at + TTL_DAYS * 86400,
        }
    )
    return summary_id


def get_summary(summary_id: str) -> dict | None:
    response = _table().get_item(Key={"summaryId": summary_id})
    item = response.get("Item")
    return from_dynamo(item) if item is not None else None
