import time
import pytest
from moto import mock_aws
from app.services.summary_store import save_summary, get_summary, generate_summary_id, save_pending

SAMPLE_SUMMARY = {
    "intro": "Your lease has a few things to watch out for.",
    "categories": [
        {
            "name": "Auto-Renewal Clauses",
            "severity": "red",
            "findings": ["Auto-renews 60 days before expiry."],
        }
    ],
}


def test_generate_summary_id_is_8_chars():
    sid = generate_summary_id()
    assert len(sid) == 8
    assert sid.isalnum()


@mock_aws
def test_save_summary_returns_8_char_id(dynamodb_table):
    sid = save_summary(SAMPLE_SUMMARY)
    assert len(sid) == 8


@mock_aws
def test_save_summary_stores_item_with_ttl(dynamodb_table):
    before = int(time.time())
    sid = save_summary(SAMPLE_SUMMARY)
    item = dynamodb_table.get_item(Key={"summaryId": sid})["Item"]
    assert item["summaryId"] == sid
    assert item["summary"] == SAMPLE_SUMMARY
    assert item["createdAt"] >= before
    assert item["ttl"] > item["createdAt"]


@mock_aws
def test_get_summary_returns_stored_item(dynamodb_table):
    sid = save_summary(SAMPLE_SUMMARY)
    result = get_summary(sid)
    assert result is not None
    assert result["summaryId"] == sid
    assert result["summary"] == SAMPLE_SUMMARY


@mock_aws
def test_get_summary_returns_none_for_unknown_id(dynamodb_table):
    result = get_summary("00000000")
    assert result is None


@mock_aws
def test_save_summary_persists_document_type(dynamodb_table):
    sid = save_summary(SAMPLE_SUMMARY, document_type="filing")
    result = get_summary(sid)
    assert result["documentType"] == "filing"


@mock_aws
def test_save_pending_persists_document_type(dynamodb_table):
    save_pending("pend1234", "filings/x.pdf", document_type="filing")
    result = get_summary("pend1234")
    assert result["documentType"] == "filing"
    assert result["status"] == "pending"


@mock_aws
def test_save_pending_defaults_document_type_to_lease(dynamodb_table):
    save_pending("pend5678", "leases/x.pdf")
    result = get_summary("pend5678")
    assert result["documentType"] == "lease"
