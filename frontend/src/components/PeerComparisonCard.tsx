import type { PeerComparison, PeerMetric } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { formatMetric, ordinal } from "@/lib/format";

/**
 * A percentile bar oriented so that further right is always healthier, whichever
 * direction the underlying metric runs in. Without that normalisation a reader has to
 * remember per metric whether high is good, which defeats the point of ranking.
 */
function PercentileBar({ metric }: { metric: PeerMetric }) {
  const pct = Math.max(0, Math.min(100, metric.percentile));
  const tone =
    metric.severity === "red"
      ? "bg-destructive"
      : metric.severity === "yellow"
        ? "bg-warning"
        : "bg-success";

  return (
    <div
      className="relative h-1.5 w-full rounded-full bg-secondary"
      role="img"
      aria-label={`${metric.label}: ${ordinal(metric.rank)} of ${metric.cohortSize}, ${pct}th percentile`}
    >
      <div className={`h-1.5 rounded-full ${tone}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function MetricRow({ metric }: { metric: PeerMetric }) {
  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-semibold text-foreground">{metric.label}</span>
        <div className="flex items-baseline gap-2.5">
          <span className="font-mono text-sm text-foreground">
            {formatMetric(metric.subjectValue, metric.unit)}
          </span>
          <SeverityBadge severity={metric.severity} />
        </div>
      </div>

      <PercentileBar metric={metric} />

      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{metric.interpretation}</p>

      {metric.median != null && (
        <p className="mt-1 text-xs text-muted-foreground">
          {ordinal(metric.rank)} of {metric.cohortSize} &middot; peer median{" "}
          {formatMetric(metric.median, metric.unit)}
          {metric.best != null && ` · best ${formatMetric(metric.best, metric.unit)}`}
        </p>
      )}
    </div>
  );
}

export function PeerComparisonCard({ peers }: { peers: PeerComparison }) {
  const hasMetrics = peers.metrics.length > 0;

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-1">
        <CardTitle>How it ranks against its industry</CardTitle>
        {peers.sicDescription && (
          <span className="text-xs text-muted-foreground">
            SIC {peers.sic} &middot; {peers.sicDescription} &middot; {peers.cohortSize} listed peers
          </span>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {hasMetrics ? (
          <>
            {peers.metrics.map((metric) => (
              <MetricRow key={metric.key} metric={metric} />
            ))}
            {peers.peers.length > 0 && (
              <p className="text-xs leading-relaxed text-muted-foreground">
                Compared against{" "}
                {peers.peers.map((p) => p.ticker ?? p.name).filter(Boolean).join(", ")}.
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            {peers.unavailableReason ??
              "Not enough comparable filers in this industry to rank against."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
