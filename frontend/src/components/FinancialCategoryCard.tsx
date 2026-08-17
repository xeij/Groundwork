import type { FinancialCategory, FinancialFinding } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { ConfidenceBadge } from "./ConfidenceBadge";

const QUOTE_BORDER: Record<string, string> = {
  red: "#f85149",
  yellow: "#d29922",
  green: "#3fb950",
};

function FindingItem({ finding, severity }: { finding: FinancialFinding; severity: string }) {
  return (
    <div style={{ paddingBottom: "1rem", marginBottom: "1rem", borderBottom: "1px solid #21262d" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem", marginBottom: "0.5rem" }}>
        <p style={{ margin: 0, color: "#e6edf3", lineHeight: 1.6 }}>{finding.summary}</p>
        <ConfidenceBadge confidence={finding.confidence} />
      </div>
      {finding.citation && (
        <blockquote
          style={{
            margin: 0,
            padding: "0.5rem 0.75rem",
            borderLeft: `3px solid ${QUOTE_BORDER[severity] ?? "#30363d"}`,
            background: "#0d1117",
            color: "#8b949e",
            fontSize: "0.85rem",
            fontStyle: "italic",
            borderRadius: "0 4px 4px 0",
            lineHeight: 1.5,
          }}
        >
          &ldquo;{finding.citation.quote}&rdquo;
          {finding.citation.page != null && (
            <span style={{ display: "block", marginTop: "0.35rem", fontStyle: "normal", fontSize: "0.78rem", opacity: 0.75 }}>
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
    <div
      style={{
        border: `1px solid ${allClear ? "#21262d" : "#30363d"}`,
        borderRadius: 10,
        background: "#161b22",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0.875rem 1.25rem",
          borderBottom: allClear ? "none" : "1px solid #21262d",
          background: allClear ? "#161b22" : "#1c2128",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 600, color: "#e6edf3" }}>
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
        <div style={{ padding: "0.5rem 1.25rem 0.875rem", color: "#8b949e", fontSize: "0.875rem" }}>
          {category.findings[0]?.summary}
        </div>
      )}
    </div>
  );
}
