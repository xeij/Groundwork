import boto3
import pytest
from moto import mock_aws
from app.services.storage import generate_upload_url, fetch_pdf, delete_pdf


@mock_aws
def test_generate_upload_url_returns_presigned_url_and_key(s3_bucket):
    url, key = generate_upload_url()
    assert url.startswith("https://")
    assert key.startswith("leases/")
    assert key.endswith(".pdf")


@mock_aws
def test_generate_upload_url_for_filing_uses_filings_prefix(s3_bucket):
    url, key = generate_upload_url("filing")
    assert url.startswith("https://")
    assert key.startswith("filings/")
    assert key.endswith(".pdf")


@mock_aws
def test_fetch_pdf_returns_bytes(s3_bucket):
    s3_bucket.put_object(Bucket="test-lease-bucket", Key="leases/test.pdf", Body=b"PDF content")
    result = fetch_pdf("leases/test.pdf")
    assert result == b"PDF content"


@mock_aws
def test_delete_pdf_removes_object(s3_bucket):
    s3_bucket.put_object(Bucket="test-lease-bucket", Key="leases/del.pdf", Body=b"data")
    delete_pdf("leases/del.pdf")
    objects = s3_bucket.list_objects_v2(Bucket="test-lease-bucket").get("Contents", [])
    assert not any(o["Key"] == "leases/del.pdf" for o in objects)


@mock_aws
def test_delete_pdf_does_not_raise_on_missing_object(s3_bucket):
    delete_pdf("leases/nonexistent.pdf")  # should not raise
