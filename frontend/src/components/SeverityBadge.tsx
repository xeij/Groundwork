import type { Severity } from "../types";

const CONFIG: Record<Severity, { label: string; bg: string; color: string; border: string }> = {
  red: { label: "Watch out", bg: "var(--red-wash)", color: "var(--red)", border: "var(--red-border)" },
  yellow: { label: "Worth asking", bg: "var(--amber-wash)", color: "var(--amber)", border: "var(--amber-border)" },
  green: { label: "All clear", bg: "var(--green-wash)", color: "var(--green)", border: "var(--green-border)" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { label, bg, color, border } = CONFIG[severity];
  return (
    <span
      style={{
        background: bg,
        color,
        border: `1px solid ${border}`,
        borderRadius: 999,
        padding: "3px 10px",
        fontSize: "0.75rem",
        fontWeight: 600,
        display: "inline-flex",
        alignItems: "center",
        letterSpacing: "0.01em",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
