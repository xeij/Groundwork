import { useState } from "react";
import type { ChangeType, RedlineSegment, SectionChange, SectionDiff } from "../types";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { cn } from "@/lib/utils";

const CHANGE_CONFIG: Record<
  ChangeType,
  { label: string; variant: "destructive" | "warning" | "success"; blurb: string }
> = {
  removed: {
    label: "Dropped",
    variant: "destructive",
    blurb: "Present last year, gone this year",
  },
  added: { label: "New", variant: "warning", blurb: "Not in last year's filing" },
  reworded: { label: "Reworded", variant: "success", blurb: "Same risk, changed language" },
};

function Redline({ segments }: { segments: RedlineSegment[] }) {
  return (
    <p className="rounded border border-border bg-background px-3 py-2 text-sm leading-relaxed">
      {segments.map((segment, i) => {
        if (segment.op === "ellipsis") {
          return (
            <span key={i} className="px-1 text-muted-foreground select-none">
              &hellip;
            </span>
          );
        }
        if (segment.op === "insert") {
          return (
            <ins key={i} className="bg-success/20 text-foreground no-underline">
              {segment.text}
            </ins>
          );
        }
        if (segment.op === "delete") {
          return (
            <del key={i} className="bg-destructive/20 text-muted-foreground">
              {segment.text}
            </del>
          );
        }
        return (
          <span key={i} className="text-muted-foreground">
            {segment.text}
          </span>
        );
      })}
    </p>
  );
}

function ChangeItem({ change }: { change: SectionChange }) {
  const config = CHANGE_CONFIG[change.changeType];
  const [showRedline, setShowRedline] = useState(false);
  const hasRedline = !!change.redline && change.redline.length > 0;

  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Badge variant={config.variant}>{config.label}</Badge>
        <span className="text-sm font-semibold text-foreground">{change.heading}</span>
      </div>

      <p className="mb-2 text-sm leading-relaxed text-foreground">{change.significance}</p>

      {change.quote && (
        <blockquote className="mb-2 rounded-r border-l-2 border-border bg-background px-3 py-2 text-sm italic leading-relaxed text-muted-foreground">
          &ldquo;{change.quote}&rdquo;
        </blockquote>
      )}

      {hasRedline && (
        <>
          <button
            type="button"
            onClick={() => setShowRedline((v) => !v)}
            className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            {showRedline ? "Hide" : "Show"} what changed
            {change.similarity != null && ` (${Math.round(change.similarity * 100)}% unchanged)`}
          </button>
          {showRedline && (
            <div className="mt-2">
              <Redline segments={change.redline!} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatPill({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={cn("text-sm font-semibold", tone ?? "text-foreground")}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

export function SectionDiffCard({ diff }: { diff: SectionDiff }) {
  const { stats } = diff;
  const hasChanges = diff.changes.length > 0;
  // omittedChangeCount includes the discarded ones; the two have different meanings to a
  // reader, so the "not shown for space" figure is the difference between them.
  const dropped = diff.droppedForUnverifiedQuoteCount ?? 0;
  const notShown = Math.max(0, (diff.omittedChangeCount ?? 0) - dropped);

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-1">
        <CardTitle>{diff.section} — what changed</CardTitle>
        {diff.priorYear != null && diff.currentYear != null && (
          <span className="text-xs text-muted-foreground">
            FY{diff.priorYear} filing compared with FY{diff.currentYear}
          </span>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          <StatPill label="dropped" value={stats.removed} tone="text-destructive" />
          <StatPill label="new" value={stats.added} tone="text-warning" />
          <StatPill label="reworded" value={stats.reworded} />
          <StatPill label="carried over unchanged" value={stats.unchanged} tone="text-muted-foreground" />
        </div>

        {hasChanges ? (
          <div className="space-y-4">
            {diff.changes.map((change, i) => (
              <ChangeItem key={`${change.changeType}-${i}`} change={change} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Nothing material changed in this section between the two filings.
          </p>
        )}

        {(notShown > 0 || dropped > 0) && (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {notShown > 0 && (
              <>
                {notShown} lower-signal change{notShown === 1 ? "" : "s"} not shown.
              </>
            )}
            {notShown > 0 && dropped > 0 && " "}
            {dropped > 0 && (
              <>
                {dropped} discarded for quoting text the filing does not contain.
              </>
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
