import type { FinancialCategory, FinancialFinding } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { ConfidenceBadge } from "./ConfidenceBadge";

const QUOTE_BORDER: Record<string, string> = {
  red: "var(--red)",
  yellow: "var(--amber)",
  green: "var(--green)",
};

function FindingItem({ finding, severity }: { finding: FinancialFinding; severity: string }) {
  return (
    <div style={{ paddingBottom: "1rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem", marginBottom: "0.5rem" }}>
        <p style={{ margin: 0, color: "var(--text-primary)", lineHeight: 1.6, fontSize: "0.94rem" }}>{finding.summary}</p>
        <ConfidenceBadge confidence={finding.confidence} />
      </div>
      {finding.citation && (
        <blockquote
          style={{
            margin: 0,
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
          &ldquo;{finding.citation.quote}&rdquo;
          {finding.citation.page != null && (
            <span style={{ display: "block", marginTop: "0.35rem", fontStyle: "normal", fontSize: "0.76rem", opacity: 0.75 }}>
              &mdash; Page {finding.citation.page}
            </span>
          )}
        </blockquote>
      )}
    </div>
  );
}

export function FinancialCategoryCard({ category }: { category: FinancialCategory }) {
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
          {category.findings[0]?.summary}
        </div>
      )}
    </div>
  );
}
