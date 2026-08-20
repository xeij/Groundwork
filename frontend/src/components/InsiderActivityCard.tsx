import type { InsiderActivity, InsiderRecord, InsiderWindowSummary } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { formatShares, formatUsd } from "@/lib/format";

/**
 * Bought against sold, as one bar split by side. Both halves are scaled against the
 * larger of the two so the ratio between them is what the eye picks up.
 */
function BuySellBar({ summary }: { summary: InsiderWindowSummary }) {
  const total = summary.buyShares + summary.sellShares;
  if (total <= 0) return null;
  const boughtPercent = (summary.buyShares / total) * 100;

  return (
    <div
      className="flex h-2 w-full overflow-hidden rounded-full bg-secondary"
      role="img"
      aria-label={`${formatShares(summary.buyShares)} shares bought, ${formatShares(summary.sellShares)} sold`}
    >
      <div className="h-2 bg-success" style={{ width: `${boughtPercent}%` }} />
      <div className="h-2 bg-destructive" style={{ width: `${100 - boughtPercent}%` }} />
    </div>
  );
}

function Total({
  label,
  shares,
  value,
  valueComplete,
  people,
}: {
  label: string;
  shares: number;
  value: number;
  valueComplete: boolean;
  people: number;
}) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold text-foreground">{formatShares(shares)} shares</div>
      {value > 0 && (
        <div className="text-xs text-muted-foreground">
          {/* A trade filed without a price makes the dollar total a floor, and says so. */}
          {valueComplete ? "" : "at least "}
          {formatUsd(value)} · {people} {people === 1 ? "insider" : "insiders"}
        </div>
      )}
    </div>
  );
}

function InsiderRow({ insider }: { insider: InsiderRecord }) {
  const net = insider.buyShares - insider.sellShares;
  const planned =
    insider.openMarketSales > 0 && insider.plannedSales === insider.openMarketSales
      ? "10b5-1 plan"
      : insider.plannedSales > 0
        ? `${insider.plannedSales} of ${insider.openMarketSales} on a plan`
        : null;

  return (
    <tr className="border-t border-border">
      <th scope="row" className="py-1.5 pr-3 text-left font-normal">
        <span className="text-foreground">{insider.name}</span>
        <span className="block text-xs text-muted-foreground">{insider.title ?? insider.role}</span>
      </th>
      <td className="py-1.5 pl-3 text-right font-mono text-xs">
        <span className={net >= 0 ? "text-success" : "text-destructive"}>
          {net >= 0 ? "+" : ""}
          {formatShares(net)}
        </span>
        {planned && <span className="block text-muted-foreground">{planned}</span>}
      </td>
      <td className="py-1.5 pl-3 text-right font-mono text-xs text-muted-foreground">
        {insider.sharesOwnedAfter == null ? "—" : formatShares(insider.sharesOwnedAfter)}
      </td>
    </tr>
  );
}

export function InsiderActivityCard({ activity }: { activity: InsiderActivity }) {
  const { summary, signals, insiders, coverage, windowMonths } = activity;
  const tradedOnTheOpenMarket = summary.buyTransactions > 0 || summary.sellTransactions > 0;

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-1">
        <CardTitle>What insiders did with their own shares</CardTitle>
        <span className="text-xs text-muted-foreground">
          Open-market trades from Form 4 filings over the last {windowMonths} months
        </span>
      </CardHeader>

      <CardContent className="space-y-4">
        {tradedOnTheOpenMarket && (
          <div className="space-y-2.5">
            <div className="grid grid-cols-2 gap-4">
              <Total
                label="Bought"
                shares={summary.buyShares}
                value={summary.buyValue}
                valueComplete={summary.buyValueComplete}
                people={summary.buyers}
              />
              <Total
                label="Sold"
                shares={summary.sellShares}
                value={summary.sellValue}
                valueComplete={summary.sellValueComplete}
                people={summary.sellers}
              />
            </div>
            <BuySellBar summary={summary} />
          </div>
        )}

        {signals.map((signal) => (
          <div key={signal.key} className="border-t border-border pt-4">
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-foreground">{signal.label}</span>
              <SeverityBadge severity={signal.severity} />
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{signal.interpretation}</p>
          </div>
        ))}

        {insiders.length > 0 && (
          <div className="-mx-1 overflow-x-auto border-t border-border pt-3">
            <table className="w-full min-w-[360px] border-collapse text-sm">
              <thead>
                <tr>
                  <th scope="col" className="py-1.5 pr-3 text-left text-xs font-medium text-muted-foreground">
                    Insider
                  </th>
                  <th scope="col" className="py-1.5 pl-3 text-right text-xs font-medium text-muted-foreground">
                    Net shares traded
                  </th>
                  <th scope="col" className="py-1.5 pl-3 text-right text-xs font-medium text-muted-foreground">
                    Still held
                  </th>
                </tr>
              </thead>
              <tbody>
                {insiders.map((insider) => (
                  <InsiderRow key={insider.name} insider={insider} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs leading-relaxed text-muted-foreground">
          Only open-market purchases and sales are counted above. Grants
          {summary.grantedShares > 0 ? ` (${formatShares(summary.grantedShares)} shares)` : ""},
          option exercises and shares withheld to cover tax
          {summary.taxWithheldShares > 0 ? ` (${formatShares(summary.taxWithheldShares)})` : ""} are
          compensation rather than decisions about the stock, so they are excluded from every
          figure here.
          {coverage.note ? ` ${coverage.note}` : ""}
        </p>
      </CardContent>
    </Card>
  );
}
