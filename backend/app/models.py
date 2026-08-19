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
    # A filing pulled from EDGAR is HTML and has no pages, so it is located by the Item
    # heading instead. A filing uploaded as a PDF still carries a page number.
    page: Optional[int] = None
    section: Optional[str] = None


class Verification(BaseModel):
    """Result of mechanically checking a finding's quote against the source filing."""

    status: Literal["verified", "paraphrased", "unverified", "rejected"]
    method: Optional[str] = None
    score: Optional[float] = None
    matchedText: Optional[str] = None
    detail: Optional[str] = None


class FinancialFinding(BaseModel):
    summary: str
    citation: Optional[Citation] = None
    # Retained so summaries stored before verification existed still load. New analyses
    # populate `verification`, which reports a checked fact rather than the model's
    # own opinion of how sure it is.
    confidence: Literal["high", "medium", "low"] = "medium"
    verification: Optional[Verification] = None

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
    tickerSymbol: Optional[str] = None


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


class StockPricePoint(BaseModel):
    date: str
    close: float


class StockChartResponse(BaseModel):
    ticker: str
    points: list[StockPricePoint]
    changePercent: float


# --- Company and filing provenance ---------------------------------------------------


class CompanyProfile(BaseModel):
    cik: str
    name: str
    ticker: Optional[str] = None
    sic: Optional[str] = None
    sicDescription: Optional[str] = None
    fiscalYear: Optional[int] = None
    filingDate: Optional[str] = None
    periodEnd: Optional[str] = None
    filingUrl: Optional[str] = None
    accessionNumber: Optional[str] = None


# --- Year-over-year section diffs ----------------------------------------------------


class RedlineSegment(BaseModel):
    op: Literal["equal", "insert", "delete", "ellipsis"]
    text: str


class SectionChange(BaseModel):
    changeType: Literal["added", "removed", "reworded"]
    heading: str
    severity: Literal["red", "yellow", "green"] = "yellow"
    significance: str
    quote: Optional[str] = None
    redline: Optional[list[RedlineSegment]] = None
    similarity: Optional[float] = None


class DiffStats(BaseModel):
    unchanged: int = 0
    reworded: int = 0
    added: int = 0
    removed: int = 0
    priorTotal: int = 0
    currentTotal: int = 0


class SectionDiff(BaseModel):
    section: str
    priorYear: Optional[int] = None
    currentYear: Optional[int] = None
    stats: DiffStats = DiffStats()
    changes: list[SectionChange] = []
    # Changes the payload budget could not fit, plus those discarded below. Kept separate
    # from droppedForUnverifiedQuoteCount so "not shown for space" is never presented as
    # "we caught the model making something up", which is a different claim entirely.
    omittedChangeCount: int = 0
    analyzedChangeCount: int = 0
    droppedForUnverifiedQuoteCount: int = 0


# --- Computed financials -------------------------------------------------------------


class RatioValue(BaseModel):
    label: str
    value: float
    priorValue: Optional[float] = None
    change: Optional[float] = None
    unit: Literal["percent", "days", "ratio", "usd", "x"] = "ratio"


class ForensicScreen(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    severity: Literal["red", "yellow", "green"] = "green"
    interpretation: str
    components: dict[str, Optional[float]] = {}
    basis: Optional[str] = None


class DivergenceFlag(BaseModel):
    key: str
    label: str
    severity: Literal["red", "yellow", "green"] = "yellow"
    interpretation: str
    detail: dict[str, Optional[float]] = {}


# --- Peer benchmarking ---------------------------------------------------------------


class PeerValue(BaseModel):
    ticker: str
    value: float


class PeerMetric(BaseModel):
    key: str
    label: str
    unit: Literal["percent", "days", "ratio", "usd", "x"] = "ratio"
    subjectValue: float
    percentile: int
    rank: int
    cohortSize: int
    median: Optional[float] = None
    best: Optional[float] = None
    worst: Optional[float] = None
    higherIsBetter: bool = True
    severity: Literal["red", "yellow", "green"] = "green"
    interpretation: str
    peerValues: list[PeerValue] = []


class PeerRef(BaseModel):
    cik: str
    ticker: Optional[str] = None
    name: str


class PeerComparison(BaseModel):
    sic: Optional[str] = None
    sicDescription: Optional[str] = None
    cohortSize: int = 0
    peers: list[PeerRef] = []
    metrics: list[PeerMetric] = []
    unavailableReason: Optional[str] = None


# --- The full filing analysis --------------------------------------------------------


class VerificationStats(BaseModel):
    verified: int = 0
    paraphrased: int = 0
    unverified: int = 0
    rejected: int = 0


class FilingAnalysis(BaseModel):
    """A 10-K analysis sourced from EDGAR.

    Every field beyond `intro`/`verdict`/`categories` is optional: each enrichment
    (XBRL history, forensic screens, year-over-year diffs, peer ranking) depends on an
    external source that can be missing or slow, and a partial analysis is far more
    useful than a failed one.
    """

    intro: str
    verdict: Literal["standard", "review", "concern"] = "review"
    company: Optional[CompanyProfile] = None
    keyMetrics: Optional[KeyMetrics] = None
    categories: list[FinancialCategory] = []
    financialHistory: list[dict] = []
    ratios: dict[str, RatioValue] = {}
    screens: list[ForensicScreen] = []
    flags: list[DivergenceFlag] = []
    diffs: list[SectionDiff] = []
    peers: Optional[PeerComparison] = None
    verificationStats: Optional[VerificationStats] = None
    coverageNote: Optional[str] = None


class FilingAnalysisRecord(BaseModel):
    summaryId: str
    documentType: Literal["filing"] = "filing"
    summary: FilingAnalysis
    createdAt: int


class AnalyzeTickerRequest(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        cleaned = (v or "").strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", cleaned):
            raise ValueError("Invalid ticker symbol")
        return cleaned


class CompanySearchResult(BaseModel):
    cik: str
    ticker: str
    name: str
