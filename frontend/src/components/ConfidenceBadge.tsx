import type { Confidence } from "../types";

const CONFIG: Record<Confidence, { label: string; color: string; border: string }> = {
  high: { label: "High confidence", color: "var(--green)", border: "var(--green-border)" },
  medium: { label: "Medium confidence", color: "var(--amber)", border: "var(--amber-border)" },
  low: { label: "Low confidence", color: "var(--red)", border: "var(--red-border)" },
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const { label, color, border } = CONFIG[confidence];
  return (
    <span
      style={{
        color,
        border: `1px solid ${border}`,
        borderRadius: 999,
        padding: "2px 9px",
        fontSize: "0.72rem",
        fontWeight: 600,
        display: "inline-flex",
        alignItems: "center",
        letterSpacing: "0.01em",
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {label}
    </span>
  );
}
