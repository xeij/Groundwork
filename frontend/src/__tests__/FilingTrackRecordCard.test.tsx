import { render, screen } from "@testing-library/react";
import { FilingTrackRecordCard } from "../components/FilingTrackRecordCard";
import type { FilingTrackRecord } from "../types";

const RECORD: FilingTrackRecord = {
  windowYears: 3,
  windowStart: "2023-08-20",
  filerCategory: "Large accelerated filer",
  coverage: { earliestFilingDate: "2022-01-04", complete: true, note: null },
  cadence: { eightKLast12Months: 9, eightKPrior12Months: 4, amendments: 1 },
  events: [
    {
      key: "non_reliance",
      label: "Told investors not to rely on previously issued financials",
      severity: "red",
      count: 1,
      interpretation: "Filed once, on 2026-03-02. This is a restatement announced by the company.",
      occurrences: [
        { date: "2026-03-02", form: "8-K", url: "https://www.sec.gov/Archives/edgar/data/1/2/a.htm" },
      ],
    },
    {
      key: "officer_departure",
      label: "Officer or director departures and appointments",
      severity: "yellow",
      count: 4,
      interpretation: "Filed 4× in the last 3 years (2026-01-05, 2025-06-05, 2024-11-05 and 1 more).",
      occurrences: [
        { date: "2026-01-05", form: "8-K", url: null },
        { date: "2025-06-05", form: "8-K", url: null },
      ],
    },
  ],
  filingLag: {
    days: 74,
    periodEnd: "2025-12-31",
    filingDate: "2026-03-15",
    typicalDays: 40,
    driftDays: 34,
    deadlineDays: 60,
    severity: "red",
    interpretation: "This 10-K was filed 74 days after the fiscal year ended.",
    trend: [
      { periodEnd: "2023-12-31", filingDate: "2024-02-10", days: 41 },
      { periodEnd: "2024-12-31", filingDate: "2025-02-08", days: 39 },
      { periodEnd: "2025-12-31", filingDate: "2026-03-15", days: 74 },
    ],
  },
};

test("events are listed with their severity and repeat count", () => {
  render(<FilingTrackRecordCard record={RECORD} />);

  expect(screen.getByText(/Told investors not to rely/)).toBeInTheDocument();
  expect(screen.getByText("4×")).toBeInTheDocument();
});

test("an occurrence links to the filing it came from", () => {
  render(<FilingTrackRecordCard record={RECORD} />);

  const link = screen.getByRole("link", { name: /2026-03-02/ });
  expect(link).toHaveAttribute("href", "https://www.sec.gov/Archives/edgar/data/1/2/a.htm");
});

test("an occurrence with no link still shows its date", () => {
  render(<FilingTrackRecordCard record={RECORD} />);

  expect(screen.getByText("2025-06-05 · 8-K")).toBeInTheDocument();
});

test("the filing lag renders one bar per year", () => {
  render(<FilingTrackRecordCard record={RECORD} />);

  expect(screen.getByText("74 days")).toBeInTheDocument();
  expect(screen.getByText("41 days")).toBeInTheDocument();
});

test("8-K volume is given with last year's count as context", () => {
  render(<FilingTrackRecordCard record={RECORD} />);

  expect(screen.getByText(/9 8-K announcements in the last 12 months against\s+4/)).toBeInTheDocument();
  expect(screen.getByText(/rise of 125%/)).toBeInTheDocument();
});

test("a clean record says so rather than rendering an empty card", () => {
  render(<FilingTrackRecordCard record={{ ...RECORD, events: [] }} />);

  expect(screen.getByText(/Nothing notable in the last 3 years/)).toBeInTheDocument();
});

test("a truncated filing index is disclosed", () => {
  render(
    <FilingTrackRecordCard
      record={{
        ...RECORD,
        coverage: {
          earliestFilingDate: "2025-06-01",
          complete: false,
          note: "EDGAR's recent-filing index only reaches back to 2025-06-01 for this company.",
        },
      }}
    />,
  );

  expect(screen.getByText(/only reaches back to 2025-06-01/)).toBeInTheDocument();
});

test("a filer with no comparable filing history omits the lag section", () => {
  render(<FilingTrackRecordCard record={{ ...RECORD, filingLag: null }} />);

  expect(screen.queryByText("Time taken to file")).not.toBeInTheDocument();
});
