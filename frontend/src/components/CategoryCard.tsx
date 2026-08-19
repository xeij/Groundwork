import type { Category, Finding } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";

function FindingItem({ finding: raw }: { finding: Finding | string }) {
  const finding: Finding = typeof raw === "string" ? { summary: raw, quote: null, action: null } : raw;
  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <p className="mb-2 text-sm leading-relaxed text-foreground">{finding.summary}</p>
      {finding.quote && (
        <blockquote className="mb-2 rounded-r border-l-2 border-border bg-background px-3 py-2 text-sm italic leading-relaxed text-muted-foreground">
          &ldquo;{finding.quote}&rdquo;
        </blockquote>
      )}
      {finding.action && finding.action !== "No action needed." && (
        <p className="text-sm leading-relaxed text-foreground">
          <span className="font-medium">Ask: </span>
          {finding.action}
        </p>
      )}
    </div>
  );
}

export function CategoryCard({ category }: { category: Category }) {
  const allClear = category.severity === "green";

  return (
    <Card>
      <CardHeader className={allClear ? "border-b-0" : undefined}>
        <CardTitle>{category.name}</CardTitle>
        <SeverityBadge severity={category.severity} />
      </CardHeader>

      {!allClear && (
        <CardContent className="space-y-4 pt-2">
          {category.findings.map((f, i) => (
            <FindingItem key={i} finding={f} />
          ))}
        </CardContent>
      )}

      {allClear && (
        <CardContent className="pt-0 pb-3.5 text-sm text-muted-foreground">
          {(() => {
            const f = category.findings[0];
            return f ? (typeof f === "string" ? f : f.summary) : null;
          })()}
        </CardContent>
      )}
    </Card>
  );
}
