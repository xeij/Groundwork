import type { MetricUnit } from "../types";

/** Compact USD: 391_035_000_000 -> "$391.0B". Filings are read at this scale. */
export function formatUsd(value: number): string {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function formatMetric(value: number, unit: MetricUnit): string {
  switch (unit) {
    case "usd":
      return formatUsd(value);
    case "percent":
      return `${value.toFixed(1)}%`;
    case "days":
      return `${value.toFixed(0)} days`;
    case "x":
      return `${value.toFixed(2)}x`;
    default:
      return value.toFixed(2);
  }
}

/**
 * Signed change for display. Percentages and days are already differences, so they read
 * as "+9.2 days"; ratios and dollars read as their own delta.
 */
export function formatChange(change: number, unit: MetricUnit): string {
  const sign = change > 0 ? "+" : "";
  if (unit === "usd") return `${sign}${formatUsd(change)}`;
  if (unit === "percent") return `${sign}${change.toFixed(1)}pp`;
  if (unit === "days") return `${sign}${change.toFixed(0)}d`;
  if (unit === "x") return `${sign}${change.toFixed(2)}x`;
  if (unit === "years") return `${sign}${change.toFixed(1)}y`;
  return `${sign}${change.toFixed(2)}`;
}

/** Share counts read at their own scale: 511_000 -> "511.0K", 2_400_000 -> "2.4M". */
export function formatShares(count: number): string {
  const sign = count < 0 ? "-" : "";
  const abs = Math.abs(count);
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

/**
 * Which direction is healthy for a given ratio, mirroring the backend's peer-ranking
 * polarity table. Keys deliberately absent are the ones whose direction is a judgement
 * call rather than a fact -- a falling effective tax rate flatters this year's profit
 * and says nothing about whether the business improved -- and those render without a
 * colour rather than being coloured wrongly.
 */
const RATIO_POLARITY: Record<string, boolean> = {
  grossMargin: true,
  operatingMargin: true,
  netMargin: true,
  ebitdaMargin: true,
  fcfMargin: true,
  returnOnAssets: true,
  returnOnEquity: true,
  returnOnInvestedCapital: true,
  revenueGrowth: true,
  ruleOfForty: true,
  currentRatio: true,
  quickRatio: true,
  interestCoverage: true,
  assetTurnover: true,
  freeCashFlow: true,
  workingCapital: true,
  netCash: true,
  cashRunway: true,
  daysSalesOutstanding: false,
  daysInventoryOutstanding: false,
  cashConversionCycle: false,
  debtToEquity: false,
  netDebtToEbitda: false,
  sbcPercentOfOcf: false,
  dilutedShareChange: false,
  goodwillToAssets: false,
};

export type ChangeTone = "good" | "bad" | "neutral";

export function changeTone(key: string, change: number): ChangeTone {
  const higherIsBetter = RATIO_POLARITY[key];
  if (higherIsBetter === undefined || change === 0) return "neutral";
  return change > 0 === higherIsBetter ? "good" : "bad";
}

export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}
