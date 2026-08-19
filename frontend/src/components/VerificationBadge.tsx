import type { Verification, VerificationStatus } from "../types";
import { Badge } from "./ui/badge";

/**
 * Reports a mechanical check, not the model's opinion of itself: every quote is matched
 * back against the filing text it claims to come from. That is why this replaces the
 * self-assessed confidence label wherever a verification result exists.
 */
const CONFIG: Record<
  VerificationStatus,
  { label: string; variant: "success" | "warning" | "destructive" | "outline"; title: string }
> = {
  verified: {
    label: "Verified quote",
    variant: "success",
    title: "This quote was found in the filing text, word for word.",
  },
  paraphrased: {
    label: "Paraphrased",
    variant: "warning",
    title: "Close to a real passage in the filing, but not word for word — read the source.",
  },
  unverified: {
    label: "No citation",
    variant: "outline",
    title: "No quote was attached, so there was nothing to check against the filing.",
  },
  rejected: {
    label: "Failed check",
    variant: "destructive",
    title: "This quote could not be found in the filing and was discarded.",
  },
};

export function VerificationBadge({ verification }: { verification: Verification }) {
  const config = CONFIG[verification.status];
  if (!config) return null;
  return (
    <Badge variant={config.variant} title={verification.detail ?? config.title}>
      {config.label}
    </Badge>
  );
}

export function VerificationSummary({
  stats,
}: {
  stats: { verified: number; paraphrased: number; unverified: number; rejected: number };
}) {
  const checked = stats.verified + stats.paraphrased;
  const total = checked + stats.unverified + stats.rejected;
  if (total === 0) return null;

  return (
    <p className="text-xs leading-relaxed text-muted-foreground">
      <span className="font-semibold text-foreground">{stats.verified}</span> of {total} findings
      quote the filing word for word
      {stats.paraphrased > 0 && `, ${stats.paraphrased} paraphrase it`}
      {stats.rejected > 0 && `, and ${stats.rejected} were discarded for quoting text the filing does not contain`}.
    </p>
  );
}
