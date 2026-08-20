import type { FilingEvent, FilingLag, FilingTrackRecord } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { cn } from "@/lib/utils";

/**
 * The filing lag as a row of bars, one per year, so a widening gap is visible before
 * the sentence explaining it is read. Bars are scaled against the longest year rather
 * than against the deadline, because the shape of the trend is the point.
 */
function LagTrend({ lag }: { lag: FilingLag }) {
  if (lag.trend.length < 2) return null;
  const longest = Math.max(...lag.trend.map((year) => year.days));

  return (
    <div className="mt-3 space-y-1.5">
      {lag.trend.map((year, i) => {
        const isCurrent = i === lag.trend.length - 1;
        const width = longest > 0 ? (year.days / longest) * 100 : 0;
        return (
          <div key={year.periodEnd} className="flex items-center gap-2.5">
            <span className="w-20 shrink-0 text-right font-mono text-xs text-muted-foreground">
              {year.periodEnd}
            </span>
            <div className="h-1.5 flex-1 rounded-full bg-secondary">
              <div
                className={cn("h-1.5 rounded-full", isCurrent ? "bg-foreground" : "bg-muted-foreground/40")}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="w-16 shrink-0 font-mono text-xs text-foreground">{year.days} days</span>
          </div>
        );
      })}
    </div>
  );
}

function EventItem({ event }: { event: FilingEvent }) {
  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2.5">
          <span className="text-sm font-semibold text-foreground">{event.label}</span>
          {event.count > 1 && (
            <span className="font-mono text-xs text-muted-foreground">{event.count}×</span>
          )}
        </div>
        <SeverityBadge severity={event.severity} />
      </div>

      <p className="text-sm leading-relaxed text-muted-foreground">{event.interpretation}</p>

      {event.occurrences.length > 0 && (
        <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
          {event.occurrences.map((occurrence) => (
            <li key={`${occurrence.date}-${occurrence.form}`} className="text-xs text-muted-foreground">
              {occurrence.url ? (
                <a
                  href={occurrence.url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline-offset-4 hover:text-foreground hover:underline"
                >
                  {occurrence.date} · {occurrence.form}
                </a>
              ) : (
                <span>
                  {occurrence.date} · {occurrence.form}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FilingTrackRecordCard({ record }: { record: FilingTrackRecord }) {
  const { events, filingLag, cadence, coverage } = record;
  const cadenceChange = cadence.eightKPrior12Months > 0
    ? cadence.eightKLast12Months / cadence.eightKPrior12Months - 1
    : null;

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-1">
        <CardTitle>How this company files</CardTitle>
        <span className="text-xs text-muted-foreground">
          From the company's SEC filing index, not from the annual report
          {record.filerCategory ? ` · ${record.filerCategory}` : ""}
        </span>
      </CardHeader>

      <CardContent className="space-y-4">
        {events.length > 0 ? (
          events.map((event) => <EventItem key={event.key} event={event} />)
        ) : (
          <p className="text-sm leading-relaxed text-muted-foreground">
            Nothing notable in the last {record.windowYears} years of filings: no restatement
            notice, no auditor change, no late-filing notification.
          </p>
        )}

        {filingLag && (
          <div className="border-t border-border pt-4">
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-foreground">Time taken to file</span>
              <SeverityBadge severity={filingLag.severity} />
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{filingLag.interpretation}</p>
            <LagTrend lag={filingLag} />
          </div>
        )}

        {cadence.eightKLast12Months > 0 && (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {cadence.eightKLast12Months} 8-K announcements in the last 12 months against{" "}
            {cadence.eightKPrior12Months} the year before
            {cadenceChange != null && Math.abs(cadenceChange) >= 0.5
              ? `, a ${cadenceChange > 0 ? "rise" : "fall"} of ${Math.abs(Math.round(cadenceChange * 100))}%`
              : ""}
            . Volume alone is not a warning — an acquisitive year generates 8-Ks — but it is
            context for everything above.
          </p>
        )}

        {!coverage.complete && coverage.note && (
          <p className="text-xs leading-relaxed text-muted-foreground">{coverage.note}</p>
        )}
      </CardContent>
    </Card>
  );
}
