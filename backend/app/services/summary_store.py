import os
import time
import uuid

import boto3

TTL_DAYS = 90
PENDING_TTL_HOURS = 1


def _table():
    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    return dynamodb.Table(os.getenv("DYNAMODB_TABLE_NAME", ""))


def generate_summary_id() -> str:
    return uuid.uuid4().hex[:8]


def save_pending(summary_id: str, s3_key: str, document_type: str = "lease") -> None:
    created_at = int(time.time())
    _table().put_item(
        Item={
            "summaryId": summary_id,
            "status": "pending",
            "s3Key": s3_key,
            "documentType": document_type,
            "createdAt": created_at,
            "ttl": created_at + PENDING_TTL_HOURS * 3600,
        }
    )


def update_progress(summary_id: str, step: str) -> None:
    _table().update_item(
        Key={"summaryId": summary_id},
        UpdateExpression="SET step = :step",
        ExpressionAttributeValues={":step": step},
    )


def update_summary(summary_id: str, summary: dict) -> None:
    _table().update_item(
        Key={"summaryId": summary_id},
        UpdateExpression="SET #s = :s, summary = :summary, #t = :t",
        ExpressionAttributeNames={"#s": "status", "#t": "ttl"},
        ExpressionAttributeValues={
            ":s": "done",
            ":summary": summary,
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
            "summary": summary,
            "documentType": document_type,
            "createdAt": created_at,
            "ttl": created_at + TTL_DAYS * 86400,
        }
    )
    return summary_id


def get_summary(summary_id: str) -> dict | None:
    response = _table().get_item(Key={"summaryId": summary_id})
    return response.get("Item")
