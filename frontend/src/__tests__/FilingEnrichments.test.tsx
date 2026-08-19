import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FinancialsCard } from "../components/FinancialsCard";
import { ForensicScreensCard } from "../components/ForensicScreensCard";
import { PeerComparisonCard } from "../components/PeerComparisonCard";
import { VerificationBadge, VerificationSummary } from "../components/VerificationBadge";
import type { FiscalYearMetrics, PeerComparison, RatioValue } from "../types";

// --- financials -------------------------------------------------------------------

const HISTORY: FiscalYearMetrics[] = [
  { fiscalYear: 2024, periodEnd: "2024-09-28", revenue: 391_035_000_000, netIncome: 93_736_000_000, operatingCashFlow: 118_254_000_000, capex: 9_447_000_000, receivables: 33_410_000_000 },
  { fiscalYear: 2025, periodEnd: "2025-09-27", revenue: 416_161_000_000, netIncome: 112_010_000_000, operatingCashFlow: 111_524_000_000, capex: 12_000_000_000, receivables: 39_777_000_000 },
];

const RATIOS: Record<string, RatioValue> = {
  grossMargin: { label: "Gross Margin", value: 46.91, priorValue: 46.21, change: 0.7, unit: "percent" },
  daysSalesOutstanding: { label: "Days Sales Outstanding", value: 34.9, priorValue: 31.2, change: 3.7, unit: "days" },
};

test("financials render as a multi-year table in compact dollars", () => {
  render(<FinancialsCard history={HISTORY} ratios={{}} />);
  expect(screen.getByText("FY2025")).toBeInTheDocument();
  expect(screen.getByText("$416.2B")).toBeInTheDocument();
  expect(screen.getByText("$112.0B")).toBeInTheDocument();
});

test("free cash flow is derived when the filing does not tag it", () => {
  render(<FinancialsCard history={HISTORY} ratios={{}} />);
  // FY2025: operating cash flow 111.524B less capex 12.0B
  expect(screen.getByText("Free cash flow")).toBeInTheDocument();
  expect(screen.getByText("$99.5B")).toBeInTheDocument();
});

test("a metric with no tagged value renders as a dash rather than a zero", () => {
  const sparse: FiscalYearMetrics[] = [
    { fiscalYear: 2025, periodEnd: "2025-09-27", revenue: 1_000_000_000, netIncome: null },
  ];
  render(<FinancialsCard history={sparse} ratios={{}} />);
  expect(screen.queryByText("Net income")).not.toBeInTheDocument();
});

test("ratios show the change against the prior year", () => {
  render(<FinancialsCard history={[]} ratios={RATIOS} />);
  expect(screen.getByText("46.9%")).toBeInTheDocument();
  expect(screen.getByText("35 days")).toBeInTheDocument();
  // days are shown whole, matching the "35 days" value above
  expect(screen.getByText("+4d")).toBeInTheDocument();
});

test("the financials card is omitted entirely when there is nothing to show", () => {
  const { container } = render(<FinancialsCard history={[]} ratios={{}} />);
  expect(container).toBeEmptyDOMElement();
});

// --- forensic screens -------------------------------------------------------------

const SCREENS = [
  {
    key: "beneish_m",
    label: "Beneish M-Score",
    value: -1.65,
    severity: "red" as const,
    interpretation: "The accounting profile resembles that of companies later found to have manipulated earnings.",
    components: { DSRI: 1.5, GMI: 1.1429, TATA: 0.0167 },
    basis: "FY2024 → FY2025",
  },
];

const FLAGS = [
  {
    key: "receivables_divergence",
    label: "Receivables Growing Faster Than Sales",
    severity: "yellow" as const,
    interpretation: "Receivables grew 19% while revenue grew 6%.",
    detail: { revenueGrowth: 6.4, receivablesGrowth: 19.1 },
  },
];

test("screens show the score, the plain-English reading and the years compared", () => {
  render(<ForensicScreensCard screens={SCREENS} flags={[]} />);
  expect(screen.getByText("Beneish M-Score")).toBeInTheDocument();
  expect(screen.getByText("-1.65")).toBeInTheDocument();
  expect(screen.getByText(/resembles that of companies later found/i)).toBeInTheDocument();
  expect(screen.getByText(/based on FY2024 → FY2025/i)).toBeInTheDocument();
});

test("a screen's inputs are auditable rather than a black box", async () => {
  render(<ForensicScreensCard screens={SCREENS} flags={[]} />);
  expect(screen.queryByText("DSRI")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /show the inputs/i }));
  expect(screen.getByText("DSRI")).toBeInTheDocument();
  expect(screen.getByText("1.5000")).toBeInTheDocument();
});

test("screens are framed as prompts to investigate, not as verdicts", () => {
  render(<ForensicScreensCard screens={SCREENS} flags={[]} />);
  expect(screen.getByText(/published screens, not verdicts/i)).toBeInTheDocument();
});

test("divergence flags render separately from the scored screens", () => {
  render(<ForensicScreensCard screens={[]} flags={FLAGS} />);
  expect(screen.getByText(/divergences worth a look/i)).toBeInTheDocument();
  expect(screen.getByText(/receivables grew 19% while revenue grew 6%/i)).toBeInTheDocument();
});

test("nothing renders when there are no screens and no flags", () => {
  const { container } = render(<ForensicScreensCard screens={[]} flags={[]} />);
  expect(container).toBeEmptyDOMElement();
});

// --- peers ------------------------------------------------------------------------

const PEERS: PeerComparison = {
  sic: "3571",
  sicDescription: "Electronic Computers",
  cohortSize: 11,
  peers: [
    { cik: "0000826083", ticker: "DELL", name: "Dell Technologies" },
    { cik: "0001375365", ticker: "SMCI", name: "Super Micro Computer" },
  ],
  metrics: [
    {
      key: "daysSalesOutstanding",
      label: "Days Sales Outstanding",
      unit: "days",
      subjectValue: 61.2,
      percentile: 18,
      rank: 9,
      cohortSize: 11,
      median: 44,
      best: 21,
      worst: 78.5,
      higherIsBetter: false,
      severity: "red",
      interpretation: "Collections are slower than 8 of the 11 comparable filers.",
      peerValues: [{ ticker: "DELL", value: 44 }],
    },
  ],
  unavailableReason: null,
};

test("peer ranking names the position, the cohort and the median", () => {
  render(<PeerComparisonCard peers={PEERS} />);
  expect(screen.getByText(/electronic computers/i)).toBeInTheDocument();
  expect(screen.getByText(/collections are slower than 8 of the 11/i)).toBeInTheDocument();
  expect(screen.getByText(/9th of 11/i)).toBeInTheDocument();
  expect(screen.getByText(/peer median 44 days/i)).toBeInTheDocument();
});

test("the percentile bar is described for assistive technology", () => {
  render(<PeerComparisonCard peers={PEERS} />);
  expect(
    screen.getByRole("img", { name: /days sales outstanding: 9th of 11, 18th percentile/i }),
  ).toBeInTheDocument();
});

test("peers are named so the comparison can be checked", () => {
  render(<PeerComparisonCard peers={PEERS} />);
  expect(screen.getByText(/compared against DELL, SMCI/i)).toBeInTheDocument();
});

test("a cohort too thin to rank explains itself instead of showing a meaningless number", () => {
  render(
    <PeerComparisonCard
      peers={{ ...PEERS, metrics: [], unavailableReason: "Only 2 comparable filers had usable XBRL data." }}
    />,
  );
  expect(screen.getByText(/only 2 comparable filers had usable XBRL data/i)).toBeInTheDocument();
});

// --- verification -----------------------------------------------------------------

test("a verified quote is labelled as checked against the filing", () => {
  render(<VerificationBadge verification={{ status: "verified", method: "exact_quote_match", score: 1 }} />);
  expect(screen.getByText(/verified quote/i)).toBeInTheDocument();
});

test("a paraphrase is distinguished from a verbatim quote", () => {
  render(<VerificationBadge verification={{ status: "paraphrased", method: "fuzzy_quote_match", score: 0.89 }} />);
  expect(screen.getByText(/paraphrased/i)).toBeInTheDocument();
});

test("the verification summary counts what was checked, including discards", () => {
  render(<VerificationSummary stats={{ verified: 12, paraphrased: 2, unverified: 1, rejected: 3 }} />);
  expect(screen.getByText(/12/)).toBeInTheDocument();
  expect(screen.getByText(/of 18 findings quote the filing word for word/i)).toBeInTheDocument();
  expect(screen.getByText(/3 were discarded/i)).toBeInTheDocument();
});

test("the verification summary is omitted when nothing was checked", () => {
  const { container } = render(
    <VerificationSummary stats={{ verified: 0, paraphrased: 0, unverified: 0, rejected: 0 }} />,
  );
  expect(container).toBeEmptyDOMElement();
});
