export type Severity = "red" | "yellow" | "green";
export type Verdict = "standard" | "review" | "concern";

export type CategoryName =
  | "Auto-Renewal Clauses"
  | "Deposit Conditions"
  | "Unusual Fees"
  | "Missing Standard Clauses";

export interface Finding {
  summary: string;
  quote: string | null;
  action: string | null;
}

export interface Category {
  name: CategoryName;
  severity: Severity;
  findings: Finding[];
}

export interface KeyNumbers {
  monthlyRent: string | null;
  securityDeposit: string | null;
  leaseLength: string | null;
  lateFee: string | null;
  earlyTerminationFee: string | null;
}

export interface Summary {
  intro: string;
  verdict: Verdict;
  keyNumbers: KeyNumbers | null;
  categories: Category[];
}

export type DocumentType = "lease" | "filing";
export type Confidence = "high" | "medium" | "low";

export interface Citation {
  quote: string;
  // A filing pulled from EDGAR is HTML and has no pages, so it is located by Item
  // heading instead. A filing uploaded as a PDF still carries a page number.
  page: number | null;
  section?: string | null;
}

export type VerificationStatus = "verified" | "paraphrased" | "unverified" | "rejected";

export interface Verification {
  status: VerificationStatus;
  method?: string | null;
  score?: number | null;
  matchedText?: string | null;
  detail?: string | null;
}

export interface FinancialFinding {
  summary: string;
  citation: Citation | null;
  // Retained for summaries stored before verification existed. New analyses carry
  // `verification`, which reports a mechanical check rather than the model's opinion.
  confidence: Confidence;
  verification?: Verification | null;
}

export type FinancialCategoryName =
  | "Risk Factors"
  | "MD&A / Financial Performance"
  | "Liquidity & Capital Resources"
  | "Related-Party Transactions"
  | "Legal Proceedings & Contingencies"
  | "Accounting Policy Changes";

export interface FinancialCategory {
  name: FinancialCategoryName;
  severity: Severity;
  findings: FinancialFinding[];
}

export interface KeyMetrics {
  totalRevenue: string | null;
  netIncome: string | null;
  totalDebt: string | null;
  cashAndEquivalents: string | null;
  operatingCashFlow: string | null;
  tickerSymbol: string | null;
}

export interface StockPricePoint {
  date: string;
  close: number;
}

export interface StockChartData {
  ticker: string;
  points: StockPricePoint[];
  changePercent: number;
}

export interface CompanyProfile {
  cik: string;
  name: string;
  ticker?: string | null;
  sic?: string | null;
  sicDescription?: string | null;
  fiscalYear?: number | null;
  filingDate?: string | null;
  periodEnd?: string | null;
  filingUrl?: string | null;
  accessionNumber?: string | null;
}

export type RedlineOp = "equal" | "insert" | "delete" | "ellipsis";

export interface RedlineSegment {
  op: RedlineOp;
  text: string;
}

export type ChangeType = "added" | "removed" | "reworded";

export interface SectionChange {
  changeType: ChangeType;
  heading: string;
  severity: Severity;
  significance: string;
  quote?: string | null;
  redline?: RedlineSegment[] | null;
  similarity?: number | null;
}

export interface DiffStats {
  unchanged: number;
  reworded: number;
  added: number;
  removed: number;
  priorTotal: number;
  currentTotal: number;
}

export interface SectionDiff {
  section: string;
  priorYear?: number | null;
  currentYear?: number | null;
  stats: DiffStats;
  changes: SectionChange[];
  omittedChangeCount?: number;
  analyzedChangeCount?: number;
  droppedForUnverifiedQuoteCount?: number;
}

export type MetricUnit = "percent" | "days" | "ratio" | "usd" | "x";

export interface RatioValue {
  label: string;
  value: number;
  priorValue?: number | null;
  change?: number | null;
  unit: MetricUnit;
}

export interface ForensicScreen {
  key: string;
  label: string;
  value?: number | null;
  severity: Severity;
  interpretation: string;
  components?: Record<string, number | null>;
  basis?: string | null;
}

export interface DivergenceFlag {
  key: string;
  label: string;
  severity: Severity;
  interpretation: string;
  detail?: Record<string, number | null>;
}

export interface PeerValue {
  ticker: string;
  value: number;
}

export interface PeerMetric {
  key: string;
  label: string;
  unit: MetricUnit;
  subjectValue: number;
  percentile: number;
  rank: number;
  cohortSize: number;
  median?: number | null;
  best?: number | null;
  worst?: number | null;
  higherIsBetter: boolean;
  severity: Severity;
  interpretation: string;
  peerValues: PeerValue[];
}

export interface PeerRef {
  cik: string;
  ticker?: string | null;
  name: string;
}

export interface PeerComparison {
  sic?: string | null;
  sicDescription?: string | null;
  cohortSize: number;
  peers: PeerRef[];
  metrics: PeerMetric[];
  unavailableReason?: string | null;
}

export interface VerificationStats {
  verified: number;
  paraphrased: number;
  unverified: number;
  rejected: number;
}

/** One fiscal year of tagged XBRL data. Keys are metric names; values are USD or null. */
export interface FiscalYearMetrics {
  fiscalYear: number;
  periodEnd: string;
  [metric: string]: number | string | null;
}

/**
 * Everything past `categories` is optional: each enrichment depends on an external
 * source that can be missing or slow, and a filing analyzed before those existed still
 * renders. Components must treat every one of them as possibly absent.
 */
export interface FinancialSummary {
  intro: string;
  verdict: Verdict;
  keyMetrics: KeyMetrics | null;
  categories: FinancialCategory[];
  company?: CompanyProfile | null;
  financialHistory?: FiscalYearMetrics[];
  ratios?: Record<string, RatioValue>;
  screens?: ForensicScreen[];
  flags?: DivergenceFlag[];
  diffs?: SectionDiff[];
  peers?: PeerComparison | null;
  verificationStats?: VerificationStats | null;
  coverageNote?: string | null;
}

export type FilingAnalysis = FinancialSummary;

export interface CompanySearchResult {
  cik: string;
  ticker: string;
  name: string;
}

export interface LeaseSummaryRecord {
  summaryId: string;
  documentType: "lease";
  summary: Summary;
  createdAt: number;
}

export interface FilingSummaryRecord {
  summaryId: string;
  documentType: "filing";
  summary: FinancialSummary;
  createdAt: number;
}

export type SummaryRecord = LeaseSummaryRecord | FilingSummaryRecord;

export interface UploadUrlResponse {
  presignedUrl: string;
  s3Key: string;
}

export interface AnalyzeResponse {
  summaryId: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Real backend processing steps for a document that's still being analyzed, in order.
// The first three are the PDF-upload path; the rest are the EDGAR ticker path.
export type AnalysisStep =
  | "extracting_text"
  | "analyzing"
  | "finalizing"
  | "fetching_filing"
  | "reading_financials"
  | "comparing_years"
  | "benchmarking"
  | "verifying";

export class PendingError extends Error {
  constructor(
    public step: AnalysisStep | null,
    public detail: string | null = null,
  ) {
    super("pending");
  }
}
