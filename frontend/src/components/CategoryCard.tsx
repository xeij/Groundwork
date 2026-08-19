import type { Category, Finding } from "../types";
import { SeverityBadge } from "./SeverityBadge";

const QUOTE_BORDER: Record<string, string> = {
  red: "var(--red)",
  yellow: "var(--amber)",
  green: "var(--green)",
};

function FindingItem({ finding: raw, severity }: { finding: Finding | string; severity: string }) {
  const finding: Finding = typeof raw === "string" ? { summary: raw, quote: null, action: null } : raw;
  return (
    <div style={{ paddingBottom: "1rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)" }}>
      <p style={{ margin: "0 0 0.5rem", color: "var(--text-primary)", lineHeight: 1.6, fontSize: "0.94rem" }}>{finding.summary}</p>
      {finding.quote && (
        <blockquote
          style={{
            margin: "0 0 0.5rem",
            padding: "0.5rem 0.75rem",
            borderLeft: `2px solid ${QUOTE_BORDER[severity] ?? "var(--border-strong)"}`,
            background: "var(--bg)",
            color: "var(--text-secondary)",
            fontSize: "0.84rem",
            fontStyle: "italic",
            borderRadius: "0 4px 4px 0",
            lineHeight: 1.55,
          }}
        >
          &ldquo;{finding.quote}&rdquo;
        </blockquote>
      )}
      {finding.action && finding.action !== "No action needed." && (
        <p style={{ margin: 0, color: "var(--accent)", fontSize: "0.86rem", lineHeight: 1.5 }}>
          <span style={{ marginRight: "0.35rem", opacity: 0.7 }}>&#8594;</span>
          {finding.action}
        </p>
      )}
    </div>
  );
}

export function CategoryCard({ category }: { category: Category }) {
  const allClear = category.severity === "green";

  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0.875rem 1.25rem",
          borderBottom: allClear ? "none" : "1px solid var(--border)",
          background: allClear ? "var(--surface)" : "var(--surface-raised)",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "0.92rem", fontWeight: 600, color: "var(--text-primary)" }}>
          {category.name}
        </h3>
        <SeverityBadge severity={category.severity} />
      </div>

      {!allClear && (
        <div style={{ padding: "1rem 1.25rem" }}>
          {category.findings.map((f, i) => (
            <div
              key={i}
              style={i === category.findings.length - 1 ? { paddingBottom: 0, marginBottom: 0, borderBottom: "none" } : undefined}
            >
              <FindingItem finding={f} severity={category.severity} />
            </div>
          ))}
        </div>
      )}

      {allClear && (
        <div style={{ padding: "0.5rem 1.25rem 0.875rem", color: "var(--text-secondary)", fontSize: "0.86rem" }}>
          {(() => { const f = category.findings[0]; return f ? (typeof f === "string" ? f : f.summary) : null; })()}
        </div>
      )}
    </div>
  );
}
