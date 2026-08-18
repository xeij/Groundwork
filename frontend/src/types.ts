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
  page: number | null;
}

export interface FinancialFinding {
  summary: string;
  citation: Citation | null;
  confidence: Confidence;
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

export interface FinancialSummary {
  intro: string;
  verdict: Verdict;
  keyMetrics: KeyMetrics | null;
  categories: FinancialCategory[];
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
