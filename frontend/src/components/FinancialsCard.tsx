import type { FiscalYearMetrics, RatioValue } from "../types";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { formatChange, formatMetric, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

// The lines worth showing as a trend. Everything else stays in the ratio grid.
const HISTORY_ROWS: { key: string; label: string }[] = [
  { key: "revenue", label: "Revenue" },
  { key: "grossProfit", label: "Gross profit" },
  { key: "operatingIncome", label: "Operating income" },
  { key: "netIncome", label: "Net income" },
  { key: "operatingCashFlow", label: "Operating cash flow" },
  { key: "freeCashFlowDerived", label: "Free cash flow" },
  { key: "receivables", label: "Receivables" },
  { key: "inventory", label: "Inventory" },
  { key: "totalDebt", label: "Total debt" },
  { key: "cash", label: "Cash & equivalents" },
];

function numeric(year: FiscalYearMetrics, key: string): number | null {
  if (key === "freeCashFlowDerived") {
    const ocf = year.operatingCashFlow;
    const capex = year.capex;
    if (typeof ocf !== "number" || typeof capex !== "number") return null;
    return ocf - Math.abs(capex);
  }
  const value = year[key];
  return typeof value === "number" ? value : null;
}

function HistoryTable({ history }: { history: FiscalYearMetrics[] }) {
  const years = history.slice(-4);
  const rows = HISTORY_ROWS.filter((row) => years.some((y) => numeric(y, row.key) != null));
  if (rows.length === 0 || years.length === 0) return null;

  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[420px] border-collapse text-sm">
        <thead>
          <tr>
            <th scope="col" className="py-1.5 pr-3 text-left text-xs font-medium text-muted-foreground">
              Fiscal year
            </th>
            {years.map((year) => (
              <th
                key={year.fiscalYear}
                scope="col"
                className="py-1.5 pl-3 text-right text-xs font-medium text-muted-foreground"
              >
                FY{year.fiscalYear}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-border">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted-foreground">
                {row.label}
              </th>
              {years.map((year) => {
                const value = numeric(year, row.key);
                return (
                  <td
                    key={year.fiscalYear}
                    className="py-1.5 pl-3 text-right font-mono text-xs text-foreground"
                  >
                    {value == null ? "—" : formatUsd(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RatioGrid({ ratios }: { ratios: Record<string, RatioValue> }) {
  const entries = Object.entries(ratios);
  if (entries.length === 0) return null;

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-4 gap-y-3">
      {entries.map(([key, ratio]) => (
        <div key={key}>
          <div className="mb-0.5 truncate text-xs text-muted-foreground" title={ratio.label}>
            {ratio.label}
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-sm font-semibold text-foreground">
              {formatMetric(ratio.value, ratio.unit)}
            </span>
            {ratio.change != null && ratio.change !== 0 && (
              <span
                className={cn(
                  "text-xs",
                  ratio.change > 0 ? "text-success" : "text-destructive",
                )}
              >
                {formatChange(ratio.change, ratio.unit)}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

interface Props {
  history: FiscalYearMetrics[];
  ratios: Record<string, RatioValue>;
}

export function FinancialsCard({ history, ratios }: Props) {
  const hasHistory = history.length > 0;
  const hasRatios = Object.keys(ratios).length > 0;
  if (!hasHistory && !hasRatios) return null;

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-1">
        <CardTitle>Reported financials</CardTitle>
        <span className="text-xs text-muted-foreground">
          Straight from the company's XBRL filings with the SEC — not read off the page by a model
        </span>
      </CardHeader>
      <CardContent className="space-y-5">
        {hasHistory && <HistoryTable history={history} />}
        {hasRatios && (
          <div>
            <p className="mb-2.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Derived ratios
              <span className="ml-2 font-normal normal-case">
                (change shown against the prior year)
              </span>
            </p>
            <RatioGrid ratios={ratios} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
