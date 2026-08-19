import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.main import app
from app.services.edgar import EdgarError

client = TestClient(app)

APPLE = {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."}


# --- GET /companies ------------------------------------------------------------------


def test_search_companies_returns_matches():
    with patch("app.routes.company.edgar.search_companies", return_value=[APPLE]):
        response = client.get("/companies", params={"q": "aapl"})

    assert response.status_code == 200
    assert response.json() == [APPLE]


def test_search_companies_rejects_an_empty_query():
    assert client.get("/companies", params={"q": ""}).status_code == 422


def test_search_companies_rejects_an_absurdly_long_query():
    assert client.get("/companies", params={"q": "x" * 200}).status_code == 422


def test_search_companies_surfaces_an_edgar_outage_as_a_gateway_error():
    with patch("app.routes.company.edgar.search_companies", side_effect=EdgarError("EDGAR down")):
        response = client.get("/companies", params={"q": "aapl"})

    assert response.status_code == 502
    assert "EDGAR down" in response.json()["detail"]


# --- POST /analyze-ticker ------------------------------------------------------------


@pytest.fixture
def dynamo():
    with mock_aws():
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="test-summaries",
            KeySchema=[{"AttributeName": "summaryId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "summaryId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield


def test_analyze_ticker_accepts_the_job_and_invokes_the_worker(dynamo):
    lambda_client = MagicMock()
    with patch("app.routes.company.edgar.resolve_ticker", return_value=APPLE), \
         patch("app.routes.company.boto3.client", return_value=lambda_client):
        response = client.post("/analyze-ticker", json={"ticker": "aapl"})

    assert response.status_code == 200
    summary_id = response.json()["summaryId"]
    assert summary_id

    payload = json.loads(lambda_client.invoke.call_args.kwargs["Payload"].decode())
    assert payload == {"summaryId": summary_id, "ticker": "AAPL"}
    assert lambda_client.invoke.call_args.kwargs["InvocationType"] == "Event"


def test_analyze_ticker_records_the_job_as_pending(dynamo):
    from app.services.summary_store import get_summary

    with patch("app.routes.company.edgar.resolve_ticker", return_value=APPLE), \
         patch("app.routes.company.boto3.client", return_value=MagicMock()):
        summary_id = client.post("/analyze-ticker", json={"ticker": "AAPL"}).json()["summaryId"]

    item = get_summary(summary_id)
    assert item["status"] == "pending"
    assert item["documentType"] == "filing"
    assert item["ticker"] == "AAPL"
    # No PDF is involved in the EDGAR path, so no S3 object should be reserved.
    assert "s3Key" not in item


def test_analyze_ticker_rejects_an_unknown_symbol_up_front(dynamo):
    """Failing fast beats accepting the job and making the user poll for a failure."""
    lambda_client = MagicMock()
    with patch("app.routes.company.edgar.resolve_ticker", side_effect=EdgarError("No SEC filer found")), \
         patch("app.routes.company.boto3.client", return_value=lambda_client):
        response = client.post("/analyze-ticker", json={"ticker": "ZZZZ"})

    assert response.status_code == 404
    assert "No SEC filer found" in response.json()["detail"]
    lambda_client.invoke.assert_not_called()


@pytest.mark.parametrize("ticker", ["", "../../etc/passwd", "WAY-TOO-LONG-TICKER", "1234"])
def test_analyze_ticker_rejects_malformed_symbols(ticker):
    assert client.post("/analyze-ticker", json={"ticker": ticker}).status_code == 422


def test_analyze_ticker_normalizes_case_before_dispatching(dynamo):
    lambda_client = MagicMock()
    with patch("app.routes.company.edgar.resolve_ticker", return_value=APPLE) as resolve, \
         patch("app.routes.company.boto3.client", return_value=lambda_client):
        client.post("/analyze-ticker", json={"ticker": "  aapl  "})

    resolve.assert_called_once_with("AAPL")


# --- async worker dispatch -----------------------------------------------------------


def test_handler_routes_a_ticker_event_to_the_edgar_pipeline():
    from app import main

    with patch("app.services.filing_pipeline.analyze_ticker", return_value={"intro": "x"}) as run, \
         patch("app.services.summary_store.update_summary") as save, \
         patch("app.services.summary_store.update_progress"):
        main.handler({"summaryId": "abc12345", "ticker": "AAPL"}, None)

    assert run.call_args.args[0] == "AAPL"
    save.assert_called_once()
    assert save.call_args.args[0] == "abc12345"


def test_handler_marks_the_record_failed_when_the_pipeline_raises():
    from app import main

    with patch("app.services.filing_pipeline.analyze_ticker", side_effect=RuntimeError("EDGAR 403")), \
         patch("app.services.summary_store.mark_failed") as failed, \
         patch("app.services.summary_store.update_progress"):
        main.handler({"summaryId": "abc12345", "ticker": "AAPL"}, None)

    failed.assert_called_once()
    assert "EDGAR 403" in failed.call_args.args[1]


def test_handler_still_routes_s3_upload_events_to_the_pdf_pipeline():
    from app import main

    with patch.object(main, "_process_async") as pdf_path, \
         patch.object(main, "_process_ticker_async") as ticker_path:
        main.handler({"summaryId": "abc12345", "s3Key": "filings/x.pdf"}, None)

    pdf_path.assert_called_once_with("abc12345", "filings/x.pdf")
    ticker_path.assert_not_called()


def test_handler_reports_pipeline_progress_to_the_summary_record():
    from app import main

    steps = []
    with patch("app.services.filing_pipeline.analyze_ticker",
               side_effect=lambda t, progress: (progress("fetching_filing", "Looking up AAPL"), {"intro": "x"})[1]), \
         patch("app.services.summary_store.update_summary"), \
         patch("app.services.summary_store.update_progress",
               side_effect=lambda sid, step, detail=None: steps.append((sid, step, detail))):
        main.handler({"summaryId": "abc12345", "ticker": "AAPL"}, None)

    assert ("abc12345", "fetching_filing", "Looking up AAPL") in steps
