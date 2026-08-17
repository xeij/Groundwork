import type { Confidence } from "../types";

const CONFIG: Record<Confidence, { label: string; bg: string; color: string; dot: string }> = {
  high:   { label: "High confidence",   bg: "rgba(63,185,80,0.15)",   color: "#3fb950", dot: "#3fb950" },
  medium: { label: "Medium confidence", bg: "rgba(210,153,34,0.15)",  color: "#d29922", dot: "#d29922" },
  low:    { label: "Low confidence",    bg: "rgba(248,81,73,0.15)",   color: "#f85149", dot: "#f85149" },
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const { label, bg, color, dot } = CONFIG[confidence];
  return (
    <span
      style={{
        background: bg,
        color,
        borderRadius: 999,
        padding: "3px 10px 3px 8px",
        fontSize: "0.78rem",
        fontWeight: 600,
        display: "inline-flex",
        alignItems: "center",
        gap: "5px",
        letterSpacing: "0.01em",
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: dot, display: "inline-block", flexShrink: 0 }} />
      {label}
    </span>
  );
}
