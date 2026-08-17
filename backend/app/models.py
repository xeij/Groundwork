import re
from typing import Literal, Optional
from pydantic import BaseModel, field_validator

_S3_KEY_RE = re.compile(
    r"^(?P<prefix>leases|filings)/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$"
)
_PREFIX_TO_DOC_TYPE = {"leases": "lease", "filings": "filing"}


def document_type_from_s3_key(s3_key: str) -> str:
    match = _S3_KEY_RE.match(s3_key)
    if not match:
        raise ValueError(f"Cannot determine document type from s3Key: {s3_key}")
    return _PREFIX_TO_DOC_TYPE[match.group("prefix")]


class UploadResponse(BaseModel):
    presignedUrl: str
    s3Key: str


class AnalyzeRequest(BaseModel):
    s3Key: str

    @field_validator("s3Key")
    @classmethod
    def validate_s3_key(cls, v: str) -> str:
        if not _S3_KEY_RE.match(v):
            raise ValueError("Invalid s3Key")
        return v


class AnalyzeResponse(BaseModel):
    summaryId: str


class Finding(BaseModel):
    summary: str
    quote: Optional[str] = None
    action: Optional[str] = None


class Category(BaseModel):
    name: Literal[
        "Auto-Renewal Clauses",
        "Deposit Conditions",
        "Unusual Fees",
        "Missing Standard Clauses",
    ]
    severity: Literal["red", "yellow", "green"]
    findings: list[Finding]

    @field_validator("findings", mode="before")
    @classmethod
    def coerce_string_findings(cls, v: list) -> list:
        return [f if isinstance(f, dict) else {"summary": f} for f in v]


class KeyNumbers(BaseModel):
    monthlyRent: Optional[str] = None
    securityDeposit: Optional[str] = None
    leaseLength: Optional[str] = None
    lateFee: Optional[str] = None
    earlyTerminationFee: Optional[str] = None


class Summary(BaseModel):
    intro: str
    verdict: Literal["standard", "review", "concern"] = "review"
    keyNumbers: Optional[KeyNumbers] = None
    categories: list[Category]


class SummaryRecord(BaseModel):
    summaryId: str
    documentType: Literal["lease"] = "lease"
    summary: Summary
    createdAt: int


_NOTHING_MATERIAL = "Nothing material to report."


class Citation(BaseModel):
    quote: str
    page: Optional[int] = None


class FinancialFinding(BaseModel):
    summary: str
    citation: Optional[Citation] = None
    confidence: Literal["high", "medium", "low"] = "medium"

    @field_validator("citation")
    @classmethod
    def require_citation_unless_placeholder(cls, v, info):
        if v is None and info.data.get("summary") != _NOTHING_MATERIAL:
            raise ValueError(
                "citation is required for every finding except the standard "
                "'Nothing material to report.' placeholder"
            )
        return v


class FinancialCategory(BaseModel):
    name: Literal[
        "Risk Factors",
        "MD&A / Financial Performance",
        "Liquidity & Capital Resources",
        "Related-Party Transactions",
        "Legal Proceedings & Contingencies",
        "Accounting Policy Changes",
    ]
    severity: Literal["red", "yellow", "green"]
    findings: list[FinancialFinding]


class KeyMetrics(BaseModel):
    totalRevenue: Optional[str] = None
    netIncome: Optional[str] = None
    totalDebt: Optional[str] = None
    cashAndEquivalents: Optional[str] = None
    operatingCashFlow: Optional[str] = None


class FinancialFilingSummary(BaseModel):
    intro: str
    verdict: Literal["standard", "review", "concern"] = "review"
    keyMetrics: Optional[KeyMetrics] = None
    categories: list[FinancialCategory]


class FilingSummaryRecord(BaseModel):
    summaryId: str
    documentType: Literal["filing"] = "filing"
    summary: FinancialFilingSummary
    createdAt: int
