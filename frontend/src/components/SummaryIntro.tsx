import type { Summary, Verdict } from "../types";

const VERDICT_CONFIG: Record<Verdict, { label: string; color: string; bg: string; border: string }> = {
  standard: { label: "No major concerns", color: "var(--green)", bg: "var(--green-wash)", border: "var(--green-border)" },
  review: { label: "A few things to review", color: "var(--amber)", bg: "var(--amber-wash)", border: "var(--amber-border)" },
  concern: { label: "Has concerning clauses", color: "var(--red)", bg: "var(--red-wash)", border: "var(--red-border)" },
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

  const numbers = summary.keyNumbers
    ? Object.entries(summary.keyNumbers).filter(([, v]) => v != null)
    : [];

  return (
    <div style={{ marginBottom: "1.5rem" }}>
      <div
        style={{
          background: vc.bg,
          border: `1px solid ${vc.border}`,
          borderRadius: "var(--radius)",
          padding: "1rem 1.25rem",
          marginBottom: numbers.length > 0 ? "0.75rem" : 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.6rem" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: vc.color, display: "inline-block", flexShrink: 0 }} />
          <span style={{ color: vc.color, fontWeight: 600, fontSize: "0.8rem", letterSpacing: "0.05em", textTransform: "uppercase" }}>
            {vc.label}
          </span>
        </div>
        <p style={{ margin: 0, color: "var(--text-primary)", lineHeight: 1.7, fontSize: "0.95rem" }}>{summary.intro}</p>
      </div>

      {numbers.length > 0 && (
        <div className="card" style={{ padding: "0.875rem 1.25rem" }}>
          <p
            style={{
              margin: "0 0 0.75rem",
              fontSize: "0.72rem",
              fontWeight: 600,
              color: "var(--text-tertiary)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            Key Numbers
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.75rem" }}>
            {numbers.map(([key, value]) => (
              <div key={key}>
                <div style={{ fontSize: "0.74rem", color: "var(--text-secondary)", marginBottom: "0.2rem" }}>
                  {KEY_LABELS[key] ?? key}
                </div>
                <div style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--text-primary)" }}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
