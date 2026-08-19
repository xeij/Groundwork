import type { FinancialCategory, FinancialFinding } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";

function FindingItem({ finding }: { finding: FinancialFinding }) {
  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="mb-2 flex items-start justify-between gap-3">
        <p className="text-sm leading-relaxed text-foreground">{finding.summary}</p>
        <ConfidenceBadge confidence={finding.confidence} />
      </div>
      {finding.citation && (
        <blockquote className="rounded-r border-l-2 border-border bg-background px-3 py-2 text-sm italic leading-relaxed text-muted-foreground">
          &ldquo;{finding.citation.quote}&rdquo;
          {finding.citation.page != null && (
            <span className="mt-1.5 block text-xs not-italic opacity-75">Page {finding.citation.page}</span>
          )}
        </blockquote>
      )}
    </div>
  );
}

export function FinancialCategoryCard({ category }: { category: FinancialCategory }) {
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
          {category.findings[0]?.summary}
        </CardContent>
      )}
    </Card>
  );
}
