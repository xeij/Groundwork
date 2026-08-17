import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from moto import mock_aws
import pytest

from app.main import app

client = TestClient(app)

VALID_S3_KEY = "leases/12345678-1234-1234-1234-123456789abc.pdf"
VALID_FILING_S3_KEY = "filings/12345678-1234-1234-1234-123456789abc.pdf"

_FINDING_OK = {"summary": "Nothing concerning here.", "quote": None, "action": "No action needed."}
_FILING_FINDING_OK = {"summary": "Nothing material to report.", "citation": None, "confidence": "high"}

SAMPLE_FILING_RESPONSE = {
    "intro": "This filing shows steady revenue growth with one notable litigation risk.",
    "verdict": "review",
    "keyMetrics": {
        "totalRevenue": "$4.2B",
        "netIncome": "$310M",
        "totalDebt": "$1.1B",
        "cashAndEquivalents": "$600M",
        "operatingCashFlow": "$450M",
    },
    "categories": [
        {
            "name": "Risk Factors",
            "severity": "yellow",
            "findings": [
                {
                    "summary": "Pending litigation could materially affect results.",
                    "citation": {"quote": "The Company is subject to a pending lawsuit.", "page": 14},
                    "confidence": "medium",
                }
            ],
        },
        {"name": "MD&A / Financial Performance", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Liquidity & Capital Resources", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Related-Party Transactions", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Legal Proceedings & Contingencies", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Accounting Policy Changes", "severity": "green", "findings": [_FILING_FINDING_OK]},
    ],
}

SAMPLE_CLAUDE_RESPONSE = {
    "intro": "Overall this lease is standard.",
    "verdict": "standard",
    "keyNumbers": {
        "monthlyRent": "$1,500/month",
        "securityDeposit": "$3,000",
        "leaseLength": "12 months",
        "lateFee": None,
        "earlyTerminationFee": None,
    },
    "categories": [
        {"name": "Auto-Renewal Clauses", "severity": "green", "findings": [_FINDING_OK]},
        {"name": "Deposit Conditions", "severity": "green", "findings": [_FINDING_OK]},
        {"name": "Unusual Fees", "severity": "green", "findings": [_FINDING_OK]},
        {"name": "Missing Standard Clauses", "severity": "green", "findings": [_FINDING_OK]},
    ],
}


@mock_aws
def test_post_upload_returns_presigned_url_and_key(s3_bucket):
    response = client.post("/upload")
    assert response.status_code == 200
    data = response.json()
    assert "presignedUrl" in data
    assert data["presignedUrl"].startswith("https://")
    assert data["s3Key"].startswith("leases/")
    assert data["s3Key"].endswith(".pdf")


@mock_aws
def test_post_upload_with_filing_document_type_uses_filings_prefix(s3_bucket):
    response = client.post("/upload?documentType=filing")
    assert response.status_code == 200
    data = response.json()
    assert data["s3Key"].startswith("filings/")


@mock_aws
def test_post_analyze_returns_summary_id_immediately(s3_bucket, dynamodb_table):
    with patch("app.routes.analyze.boto3") as mock_boto3:
        mock_boto3.client.return_value.invoke.return_value = {}
        response = client.post("/analyze", json={"s3Key": VALID_S3_KEY})

    assert response.status_code == 200
    data = response.json()
    assert "summaryId" in data
    assert len(data["summaryId"]) == 8
    mock_boto3.client.return_value.invoke.assert_called_once()


@mock_aws
def test_post_analyze_stores_pending_record(s3_bucket, dynamodb_table):
    with patch("app.routes.analyze.boto3") as mock_boto3:
        mock_boto3.client.return_value.invoke.return_value = {}
        response = client.post("/analyze", json={"s3Key": VALID_S3_KEY})

    summary_id = response.json()["summaryId"]
    from app.services.summary_store import get_summary
    item = get_summary(summary_id)
    assert item is not None
    assert item["status"] == "pending"


@mock_aws
def test_get_summary_returns_202_when_pending(dynamodb_table):
    from app.services.summary_store import save_pending
    save_pending("test1234", VALID_S3_KEY)

    response = client.get("/summary/test1234")
    assert response.status_code == 202
    assert response.json()["status"] == "pending"


@mock_aws
def test_post_analyze_rejects_invalid_s3_key(dynamodb_table):
    response = client.post("/analyze", json={"s3Key": "leases/../secrets.pdf"})
    assert response.status_code == 422


@mock_aws
def test_post_analyze_rejects_non_uuid_s3_key(dynamodb_table):
    response = client.post("/analyze", json={"s3Key": "leases/test.pdf"})
    assert response.status_code == 422


@mock_aws
def test_get_summary_returns_stored_summary(dynamodb_table):
    from app.services.summary_store import save_summary
    summary_id = save_summary(SAMPLE_CLAUDE_RESPONSE)

    response = client.get(f"/summary/{summary_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["summaryId"] == summary_id
    assert data["summary"]["intro"] == SAMPLE_CLAUDE_RESPONSE["intro"]
    assert len(data["summary"]["categories"]) == 4


@mock_aws
def test_get_summary_returns_404_for_unknown_id(dynamodb_table):
    response = client.get("/summary/00000000")
    assert response.status_code == 404


@mock_aws
def test_get_summary_returns_filing_shape_for_filing_document_type(dynamodb_table):
    from app.services.summary_store import save_summary

    summary_id = save_summary(SAMPLE_FILING_RESPONSE, document_type="filing")

    response = client.get(f"/summary/{summary_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["documentType"] == "filing"
    assert len(data["summary"]["categories"]) == 6
    assert data["summary"]["keyMetrics"]["totalRevenue"] == "$4.2B"


@mock_aws
def test_process_async_stores_completed_filing_summary(s3_bucket, dynamodb_table):
    from app.services.summary_store import save_pending, get_summary
    from app.main import _process_async
    import json as _json

    sample_pdf = open("tests/fixtures/sample_lease.pdf", "rb").read()
    s3_bucket.put_object(Bucket="test-lease-bucket", Key=VALID_FILING_S3_KEY, Body=sample_pdf)
    save_pending("filng123", VALID_FILING_S3_KEY, "filing")

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=_json.dumps(SAMPLE_FILING_RESPONSE))]

    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_msg
        _process_async("filng123", VALID_FILING_S3_KEY)

    item = get_summary("filng123")
    assert item["status"] == "done"
    assert item["documentType"] == "filing"
    assert item["summary"]["intro"] == SAMPLE_FILING_RESPONSE["intro"]


@mock_aws
def test_process_async_stores_completed_summary(s3_bucket, dynamodb_table):
    from app.services.summary_store import save_pending, get_summary
    from app.main import _process_async
    import json as _json

    sample_pdf = open("tests/fixtures/sample_lease.pdf", "rb").read()
    s3_bucket.put_object(Bucket="test-lease-bucket", Key=VALID_S3_KEY, Body=sample_pdf)
    save_pending("proc1234", VALID_S3_KEY)

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=_json.dumps(SAMPLE_CLAUDE_RESPONSE))]

    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_msg
        _process_async("proc1234", VALID_S3_KEY)

    item = get_summary("proc1234")
    assert item["status"] == "done"
    assert item["summary"]["intro"] == SAMPLE_CLAUDE_RESPONSE["intro"]
