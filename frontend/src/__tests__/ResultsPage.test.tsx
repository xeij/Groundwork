import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { ResultsPage } from "../pages/ResultsPage";
import * as apiClient from "../api/client";
import type { SummaryRecord, FilingSummaryRecord } from "../types";

vi.mock("../api/client");

const _ok = { summary: "Nothing concerning here.", quote: null, action: "No action needed." };

const RECORD: SummaryRecord = {
  summaryId: "abc12345",
  documentType: "lease",
  createdAt: 1714176000,
  summary: {
    intro: "Your lease looks mostly fine with one thing to watch.",
    verdict: "review",
    keyNumbers: {
      monthlyRent: "$1,500/month",
      securityDeposit: "$3,000",
      leaseLength: "12 months",
      lateFee: null,
      earlyTerminationFee: null,
    },
    categories: [
      {
        name: "Auto-Renewal Clauses",
        severity: "red",
        findings: [
          {
            summary: "Auto-renews without notice.",
            quote: "This lease shall automatically renew...",
            action: "Ask for a 60-day notice requirement.",
          },
        ],
      },
      { name: "Deposit Conditions",       severity: "green",  findings: [_ok] },
      { name: "Unusual Fees",             severity: "yellow", findings: [{ summary: "$25/month admin fee is uncommon.", quote: null, action: "Ask the landlord to remove it." }] },
      { name: "Missing Standard Clauses", severity: "green",  findings: [_ok] },
    ],
  },
};

function renderPage(summaryId = "abc12345") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/summary/${summaryId}`]}>
        <Routes>
          <Route path="/summary/:id" element={<ResultsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders intro paragraph when loaded", async () => {
  vi.mocked(apiClient.getSummary).mockResolvedValue(RECORD);
  renderPage();
  expect(await screen.findByText(RECORD.summary.intro)).toBeInTheDocument();
});

test("renders all four category cards", async () => {
  vi.mocked(apiClient.getSummary).mockResolvedValue(RECORD);
  renderPage();
  await screen.findByText(RECORD.summary.intro);
  expect(screen.getByText("Auto-Renewal Clauses")).toBeInTheDocument();
  expect(screen.getByText("Deposit Conditions")).toBeInTheDocument();
  expect(screen.getByText("Unusual Fees")).toBeInTheDocument();
  expect(screen.getByText("Missing Standard Clauses")).toBeInTheDocument();
});

test("shows expired message on 404", async () => {
  vi.mocked(apiClient.getSummary).mockRejectedValue(
    Object.assign(new Error("Summary not found or has expired."), { status: 404 }),
  );
  renderPage("00000000");
  expect(await screen.findByText(/expired/i)).toBeInTheDocument();
});

const FILING_RECORD: FilingSummaryRecord = {
  summaryId: "flg12345",
  documentType: "filing",
  createdAt: 1714176000,
  summary: {
    intro: "This filing shows steady revenue growth with one notable litigation risk.",
    verdict: "review",
    keyMetrics: {
      totalRevenue: "$4.2B",
      netIncome: "$310M",
      totalDebt: "$1.1B",
      cashAndEquivalents: "$600M",
      operatingCashFlow: "$450M",
      tickerSymbol: "ACME",
    },
    categories: [
      {
        name: "Risk Factors",
        severity: "yellow",
        findings: [
          {
            summary: "Pending litigation could materially affect results.",
            citation: { quote: "The Company is subject to a pending lawsuit.", page: 14 },
            confidence: "medium",
          },
        ],
      },
      { name: "MD&A / Financial Performance", severity: "green", findings: [{ summary: "Nothing material to report.", citation: null, confidence: "high" }] },
      { name: "Liquidity & Capital Resources", severity: "green", findings: [{ summary: "Nothing material to report.", citation: null, confidence: "high" }] },
      { name: "Related-Party Transactions", severity: "green", findings: [{ summary: "Nothing material to report.", citation: null, confidence: "high" }] },
      { name: "Legal Proceedings & Contingencies", severity: "green", findings: [{ summary: "Nothing material to report.", citation: null, confidence: "high" }] },
      { name: "Accounting Policy Changes", severity: "green", findings: [{ summary: "Nothing material to report.", citation: null, confidence: "high" }] },
    ],
  },
};

test("renders filing-specific layout for filing document type", async () => {
  vi.mocked(apiClient.getSummary).mockResolvedValue(FILING_RECORD);
  vi.mocked(apiClient.getStockChart).mockImplementation(() => new Promise(() => {}));
  renderPage("flg12345");
  expect(await screen.findByText(FILING_RECORD.summary.intro)).toBeInTheDocument();
  expect(screen.getByText("Filing Summary")).toBeInTheDocument();
  expect(screen.getByText("Risk Factors")).toBeInTheDocument();
  expect(screen.getByText(/pending litigation/i)).toBeInTheDocument();
  expect(screen.getByText(/medium confidence/i)).toBeInTheDocument();
  expect(screen.getByText(/page 14/i)).toBeInTheDocument();
});

test("renders stock chart when the filing has a ticker symbol", async () => {
  vi.mocked(apiClient.getSummary).mockResolvedValue(FILING_RECORD);
  vi.mocked(apiClient.getStockChart).mockResolvedValue({
    ticker: "ACME",
    points: [
      { date: "2026-01-02", close: 100 },
      { date: "2026-06-15", close: 110 },
    ],
    changePercent: 10,
  });
  renderPage("flg12345");
  expect(await screen.findByText(/ACME/)).toBeInTheDocument();
  expect(await screen.findByText("+10.00%")).toBeInTheDocument();
});

test("omits stock chart when the filing has no ticker symbol", async () => {
  const noTickerRecord: FilingSummaryRecord = {
    ...FILING_RECORD,
    summary: {
      ...FILING_RECORD.summary,
      keyMetrics: { ...FILING_RECORD.summary.keyMetrics!, tickerSymbol: null },
    },
  };
  vi.mocked(apiClient.getSummary).mockResolvedValue(noTickerRecord);
  renderPage("flg12345");
  await screen.findByText(FILING_RECORD.summary.intro);
  expect(screen.queryByText(/loading price chart/i)).not.toBeInTheDocument();
});

// A filing sourced from EDGAR carries every enrichment; one uploaded as a PDF, or
// analyzed before those existed, carries none. Both must render.
const ENRICHED_RECORD: FilingSummaryRecord = {
  ...FILING_RECORD,
  summaryId: "edg12345",
  summary: {
    ...FILING_RECORD.summary,
    company: {
      cik: "0000320193",
      name: "Apple Inc.",
      ticker: "AAPL",
      sic: "3571",
      sicDescription: "Electronic Computers",
      fiscalYear: 2025,
      filingDate: "2025-10-31",
      periodEnd: "2025-09-27",
      filingUrl: "https://www.sec.gov/Archives/edgar/data/320193/x.htm",
      accessionNumber: "0000320193-25-000079",
    },
    financialHistory: [
      { fiscalYear: 2025, periodEnd: "2025-09-27", revenue: 416_161_000_000, netIncome: 112_010_000_000 },
    ],
    ratios: {
      grossMargin: { label: "Gross Margin", value: 46.91, priorValue: 46.2, change: 0.71, unit: "percent" },
    },
    screens: [
      {
        key: "altman_z",
        label: "Altman Z'-Score",
        value: 2.35,
        severity: "yellow",
        interpretation: "Sits in the model's grey zone.",
        components: { X1_workingCapitalToAssets: 0.29 },
        basis: "FY2025",
      },
    ],
    flags: [
      {
        key: "receivables_divergence",
        label: "Receivables Growing Faster Than Sales",
        severity: "yellow",
        interpretation: "Receivables grew 19% while revenue grew 6%.",
        detail: { revenueGrowth: 6.4 },
      },
    ],
    diffs: [
      {
        section: "Item 1A. Risk Factors",
        priorYear: 2024,
        currentYear: 2025,
        stats: { unchanged: 17, reworded: 1, added: 1, removed: 1, priorTotal: 19, currentTotal: 19 },
        changes: [
          {
            changeType: "removed",
            heading: "Single manufacturing partner",
            severity: "red",
            significance: "A risk disclosed last year is gone this year.",
            quote: "We depend on a single partner.",
            redline: null,
            similarity: null,
          },
        ],
        omittedChangeCount: 0,
      },
    ],
    peers: {
      sic: "3571",
      sicDescription: "Electronic Computers",
      cohortSize: 8,
      peers: [{ cik: "0000826083", ticker: "DELL", name: "Dell Technologies" }],
      metrics: [
        {
          key: "grossMargin",
          label: "Gross Margin",
          unit: "percent",
          subjectValue: 46.91,
          percentile: 82,
          rank: 2,
          cohortSize: 9,
          median: 31.2,
          best: 52.1,
          worst: 12.4,
          higherIsBetter: true,
          severity: "green",
          interpretation: "Margins are stronger than 7 of the 9 comparable filers.",
          peerValues: [{ ticker: "DELL", value: 22.1 }],
        },
      ],
      unavailableReason: null,
    },
    verificationStats: { verified: 5, paraphrased: 1, unverified: 2, rejected: 1 },
    coverageNote: "Analyzed 17 sections covering 96% of the filing text.",
  },
};

test("an EDGAR-sourced filing renders every enrichment", async () => {
  vi.mocked(apiClient.getSummary).mockResolvedValue(ENRICHED_RECORD);
  vi.mocked(apiClient.getStockChart).mockImplementation(() => new Promise(() => {}));
  renderPage("edg12345");
  await screen.findByText(ENRICHED_RECORD.summary.intro);

  expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /original filing on SEC EDGAR/i })).toHaveAttribute(
    "href",
    "https://www.sec.gov/Archives/edgar/data/320193/x.htm",
  );
  expect(screen.getByText(/Item 1A\. Risk Factors — what changed/i)).toBeInTheDocument();
  expect(screen.getByText(/a risk disclosed last year is gone/i)).toBeInTheDocument();
  expect(screen.getByText(/reported financials/i)).toBeInTheDocument();
  expect(screen.getByText(/earnings-quality screens/i)).toBeInTheDocument();
  expect(screen.getByText(/divergences worth a look/i)).toBeInTheDocument();
  expect(screen.getByText(/how it ranks against its industry/i)).toBeInTheDocument();
  expect(screen.getByText(/of 9 findings quote the filing word for word/i)).toBeInTheDocument();
  expect(screen.getByText(/96% of the filing text/i)).toBeInTheDocument();
});

test("a filing without enrichments renders its categories and omits the rest", async () => {
  vi.mocked(apiClient.getSummary).mockResolvedValue(FILING_RECORD);
  vi.mocked(apiClient.getStockChart).mockImplementation(() => new Promise(() => {}));
  renderPage("flg12345");
  await screen.findByText(FILING_RECORD.summary.intro);

  expect(screen.getByText("Risk Factors")).toBeInTheDocument();
  expect(screen.queryByText(/what changed/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/reported financials/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/how it ranks against its industry/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/how this was checked/i)).not.toBeInTheDocument();
});
