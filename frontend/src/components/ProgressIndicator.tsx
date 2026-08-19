import type { AnalysisPhase } from "../hooks/useDocumentAnalysis";
import type { AnalysisStep, DocumentType } from "../types";

// The single source of truth for "what's happening right now" is the backend: each key below
// is a real stage the upload/Lambda pipeline passes through (see useDocumentAnalysis + the
// backend's _process_async), not a simulated message. That's why there's exactly one label per
// stage instead of a rotating list — each stage is reported once, in order, and never repeats.
type ChecklistKey = "uploading" | AnalysisStep;

const CHECKLIST: { key: ChecklistKey; label: Record<DocumentType, string> }[] = [
  {
    key: "uploading",
    label: { lease: "Uploading your lease", filing: "Uploading your filing" },
  },
  {
    key: "extracting_text",
    label: { lease: "Reading the document", filing: "Reading the filing" },
  },
  {
    key: "analyzing",
    label: { lease: "Analyzing with AI", filing: "Analyzing with AI" },
  },
  {
    key: "finalizing",
    label: { lease: "Finalizing your summary", filing: "Finalizing your summary" },
  },
];

interface Props {
  phase: AnalysisPhase;
  step: AnalysisStep | null;
  documentType?: DocumentType;
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M3 8.5L6.2 12L13 4"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ProgressIndicator({ phase, step, documentType = "lease" }: Props) {
  if (phase !== "uploading" && phase !== "analyzing") return null;

  // Until the backend reports a step, "extracting_text" is the earliest true stage of
  // analysis — it's what the Lambda does first, so it's an honest default, not a guess.
  const currentKey: ChecklistKey = phase === "uploading" ? "uploading" : (step ?? "extracting_text");
  const currentIndex = CHECKLIST.findIndex((item) => item.key === currentKey);
  const visible = CHECKLIST.slice(0, currentIndex + 1);

  return (
    <div style={{ padding: "2.5rem 1rem 1rem" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.7rem", maxWidth: 340, margin: "0 auto" }}>
        {visible.map((item, i) => {
          const isDone = i < currentIndex;
          return (
            <div
              key={item.key}
              className={i === currentIndex ? "fade-msg" : undefined}
              style={{ display: "flex", alignItems: "center", gap: "0.65rem" }}
            >
              <span
                style={{
                  flexShrink: 0,
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  border: isDone ? "1px solid var(--accent)" : "none",
                  background: isDone ? "var(--accent-wash)" : "transparent",
                }}
              >
                {isDone ? <CheckIcon /> : <span className="spinner-ring" style={{ width: 14, height: 14 }} />}
              </span>
              <span
                style={{
                  fontSize: "0.92rem",
                  color: isDone ? "var(--text-secondary)" : "var(--text-primary)",
                  fontWeight: isDone ? 400 : 600,
                }}
              >
                {item.label[documentType]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
