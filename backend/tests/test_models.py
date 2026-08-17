import pytest
from pydantic import ValidationError

from app.models import FinancialFinding, document_type_from_s3_key


def test_finding_with_citation_is_valid():
    finding = FinancialFinding(
        summary="Pending litigation could materially affect results.",
        citation={"quote": "The Company is subject to a pending lawsuit.", "page": 14},
        confidence="medium",
    )
    assert finding.citation.page == 14


def test_placeholder_finding_without_citation_is_valid():
    finding = FinancialFinding(summary="Nothing material to report.", citation=None, confidence="high")
    assert finding.citation is None


def test_non_placeholder_finding_without_citation_raises():
    with pytest.raises(ValidationError, match="citation is required"):
        FinancialFinding(summary="Revenue declined sharply.", citation=None, confidence="medium")


def test_document_type_from_s3_key_lease():
    assert document_type_from_s3_key("leases/12345678-1234-1234-1234-123456789abc.pdf") == "lease"


def test_document_type_from_s3_key_filing():
    assert document_type_from_s3_key("filings/12345678-1234-1234-1234-123456789abc.pdf") == "filing"


def test_document_type_from_s3_key_rejects_malformed_key():
    with pytest.raises(ValueError, match="Cannot determine document type"):
        document_type_from_s3_key("leases/../secrets.pdf")
