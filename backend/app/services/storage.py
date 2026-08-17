import logging
import os
import uuid

import boto3

logger = logging.getLogger(__name__)


def _s3():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _bucket() -> str:
    return os.getenv("S3_BUCKET_NAME", "")


_PREFIX = {"lease": "leases", "filing": "filings"}


def generate_upload_url(document_type: str = "lease") -> tuple[str, str]:
    s3_key = f"{_PREFIX[document_type]}/{uuid.uuid4()}.pdf"
    url = _s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": _bucket(), "Key": s3_key, "ContentType": "application/pdf"},
        ExpiresIn=300,
    )
    return url, s3_key


def fetch_pdf(s3_key: str) -> bytes:
    response = _s3().get_object(Bucket=_bucket(), Key=s3_key)
    return response["Body"].read()


def delete_pdf(s3_key: str) -> None:
    try:
        _s3().delete_object(Bucket=_bucket(), Key=s3_key)
    except Exception:
        logger.exception("Failed to delete %s from S3 — continuing", s3_key)
