import { cn } from "@/lib/utils";
import type { AnalysisPhase } from "../hooks/useDocumentAnalysis";
import type { AnalysisStep, DocumentType } from "../types";

// The single source of truth for "what's happening right now" is the backend: each key below
// is a real stage the upload/Lambda pipeline passes through (see useDocumentAnalysis + the
// backend's _process_async), not a simulated message. That's why there's exactly one label per
// stage instead of a rotating list — each stage is reported once, in order, and never repeats.
type ChecklistKey = "uploading" | AnalysisStep;

const CHECKLIST: { key: ChecklistKey; label: Record<DocumentType, string> }[] = [
  { key: "uploading", label: { lease: "Uploading your lease", filing: "Uploading your filing" } },
  { key: "extracting_text", label: { lease: "Reading the document", filing: "Reading the filing" } },
  { key: "analyzing", label: { lease: "Analyzing with AI", filing: "Analyzing with AI" } },
  { key: "finalizing", label: { lease: "Finalizing your summary", filing: "Finalizing your summary" } },
];

interface Props {
  phase: AnalysisPhase;
  step: AnalysisStep | null;
  documentType?: DocumentType;
}

export function ProgressIndicator({ phase, step, documentType = "lease" }: Props) {
  if (phase !== "uploading" && phase !== "analyzing") return null;

  // Until the backend reports a step, "extracting_text" is the earliest true stage of
  // analysis — it's what the Lambda does first, so it's an honest default, not a guess.
  const currentKey: ChecklistKey = phase === "uploading" ? "uploading" : (step ?? "extracting_text");
  const currentIndex = CHECKLIST.findIndex((item) => item.key === currentKey);
  const visible = CHECKLIST.slice(0, currentIndex + 1);

  return (
    <div className="mx-auto max-w-sm py-8">
      <ol className="divide-y divide-border rounded-lg border border-border">
        {visible.map((item, i) => {
          const isDone = i < currentIndex;
          return (
            <li key={item.key} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <span className={cn(isDone ? "text-muted-foreground" : "font-medium text-foreground")}>
                {item.label[documentType]}
              </span>
              <span className="shrink-0 text-xs tracking-wide text-muted-foreground uppercase">
                {isDone ? "Done" : "In progress"}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
