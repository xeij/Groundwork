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
