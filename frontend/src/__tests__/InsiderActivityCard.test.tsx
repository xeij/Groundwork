import { render, screen } from "@testing-library/react";
import { InsiderActivityCard } from "../components/InsiderActivityCard";
import type { InsiderActivity, InsiderWindowSummary } from "../types";

const SUMMARY: InsiderWindowSummary = {
  buyShares: 25_000,
  buyValue: 2_500_000,
  buyTransactions: 3,
  buyers: 3,
  buyValueComplete: true,
  sellShares: 511_000,
  sellValue: 86_563_400,
  sellTransactions: 4,
  sellers: 2,
  sellValueComplete: true,
  netShares: -486_000,
  netValue: -84_063_400,
  grantedShares: 120_000,
  taxWithheldShares: 48_000,
  plannedSaleValue: 80_000_000,
};

const ACTIVITY: InsiderActivity = {
  windowMonths: 12,
  windowStart: "2025-08-20",
  asOf: "2026-08-20",
  summary: SUMMARY,
  priorSummary: null,
  coverage: { formsFound: 14, formsRead: 14, complete: true, note: null },
  signals: [
    {
      key: "heavy_insider_selling",
      label: "Insiders sold a large share of what they held",
      severity: "yellow",
      interpretation: "2 insiders sold 511k shares in the last 12 months — 24% of the stock they held.",
      detail: { percentOfHoldingsSold: 24 },
    },
  ],
  insiders: [
    {
      name: "Cook Timothy D",
      title: "Chief Executive Officer",
      role: "officer",
      buyShares: 0,
      buyValue: 0,
      sellShares: 511_000,
      sellValue: 86_563_400,
      sharesOwnedAfter: 3_280_342,
      plannedSales: 4,
      openMarketSales: 4,
      lastTransactionDate: "2026-04-02",
    },
    {
      name: "Adams Jane",
      title: "Director",
      role: "director",
      buyShares: 25_000,
      buyValue: 2_500_000,
      sellShares: 0,
      sellValue: 0,
      sharesOwnedAfter: 90_000,
      plannedSales: 0,
      openMarketSales: 0,
      lastTransactionDate: "2026-03-02",
    },
  ],
};

test("open-market buying and selling are totalled separately", () => {
  render(<InsiderActivityCard activity={ACTIVITY} />);

  expect(screen.getByText("25.0K shares")).toBeInTheDocument();
  expect(screen.getByText("511.0K shares")).toBeInTheDocument();
  expect(screen.getByText(/\$86\.6M · 2 insiders/)).toBeInTheDocument();
});

test("grants and tax withholding are named as excluded rather than folded in", () => {
  render(<InsiderActivityCard activity={ACTIVITY} />);

  expect(screen.getByText(/Only open-market purchases and sales are counted/)).toBeInTheDocument();
  expect(screen.getByText(/120.0K shares/)).toBeInTheDocument();
  expect(screen.getByText(/48.0K/)).toBeInTheDocument();
});

test("a dollar total built on a trade with no price is marked as a floor", () => {
  render(
    <InsiderActivityCard
      activity={{ ...ACTIVITY, summary: { ...SUMMARY, sellValueComplete: false } }}
    />,
  );

  expect(screen.getByText(/at least/)).toBeInTheDocument();
});

test("each insider's net position change and remaining holding are shown", () => {
  render(<InsiderActivityCard activity={ACTIVITY} />);

  expect(screen.getByText("Cook Timothy D")).toBeInTheDocument();
  expect(screen.getByText("-511.0K")).toBeInTheDocument();
  expect(screen.getByText("3.3M")).toBeInTheDocument();
  expect(screen.getByText("+25.0K")).toBeInTheDocument();
});

test("sales made entirely under a plan are labelled as such", () => {
  render(<InsiderActivityCard activity={ACTIVITY} />);

  expect(screen.getByText("10b5-1 plan")).toBeInTheDocument();
});

test("a partially planned seller shows how much ran through the plan", () => {
  const partial = {
    ...ACTIVITY,
    insiders: [{ ...ACTIVITY.insiders[0], plannedSales: 1, openMarketSales: 4 }],
  };
  render(<InsiderActivityCard activity={partial} />);

  expect(screen.getByText("1 of 4 on a plan")).toBeInTheDocument();
});

test("signals are rendered with their severity", () => {
  render(<InsiderActivityCard activity={ACTIVITY} />);

  expect(screen.getByText("Insiders sold a large share of what they held")).toBeInTheDocument();
});

test("a company whose insiders only received grants shows no buy/sell bar", () => {
  const quiet: InsiderActivity = {
    ...ACTIVITY,
    summary: {
      ...SUMMARY,
      buyShares: 0,
      buyValue: 0,
      buyTransactions: 0,
      buyers: 0,
      sellShares: 0,
      sellValue: 0,
      sellTransactions: 0,
      sellers: 0,
    },
    insiders: [],
    signals: [
      {
        key: "no_open_market_activity",
        label: "No insider bought or sold on the open market",
        severity: "green",
        interpretation: "The only movements were grants, vesting and tax withholding.",
      },
    ],
  };
  render(<InsiderActivityCard activity={quiet} />);

  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText("No insider bought or sold on the open market")).toBeInTheDocument();
});

test("an incomplete read of the Form 4 record is disclosed", () => {
  render(
    <InsiderActivityCard
      activity={{
        ...ACTIVITY,
        coverage: {
          formsFound: 40,
          formsRead: 22,
          complete: false,
          note: "22 of 40 Form 4s filed in this period were read before the time budget ran out.",
        },
      }}
    />,
  );

  expect(screen.getByText(/22 of 40 Form 4s/)).toBeInTheDocument();
});
