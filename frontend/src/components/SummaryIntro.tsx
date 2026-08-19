import type { Summary, Verdict } from "../types";
import { Badge } from "./ui/badge";
import { Card, CardContent } from "./ui/card";

const VERDICT_CONFIG: Record<Verdict, { label: string; variant: "success" | "warning" | "destructive" }> = {
  standard: { label: "No major concerns", variant: "success" },
  review: { label: "A few things to review", variant: "warning" },
  concern: { label: "Has concerning clauses", variant: "destructive" },
};

const KEY_LABELS: Record<string, string> = {
  monthlyRent: "Monthly Rent",
  securityDeposit: "Security Deposit",
  leaseLength: "Lease Length",
  lateFee: "Late Fee",
  earlyTerminationFee: "Early Termination",
};

export function SummaryIntro({ summary }: { summary: Summary }) {
  const verdict = summary.verdict ?? "review";
  const vc = VERDICT_CONFIG[verdict];

  const numbers = summary.keyNumbers ? Object.entries(summary.keyNumbers).filter(([, v]) => v != null) : [];

  return (
    <div className="mb-6 space-y-3">
      <Card>
        <CardContent className="py-4">
          <Badge variant={vc.variant} className="mb-2.5">
            {vc.label}
          </Badge>
          <p className="text-sm leading-relaxed text-foreground">{summary.intro}</p>
        </CardContent>
      </Card>

      {numbers.length > 0 && (
        <Card>
          <CardContent>
            <p className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Key Numbers</p>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
              {numbers.map(([key, value]) => (
                <div key={key}>
                  <div className="mb-0.5 text-xs text-muted-foreground">{KEY_LABELS[key] ?? key}</div>
                  <div className="text-sm font-semibold text-foreground">{value}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
