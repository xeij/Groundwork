import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { AnalysisPhase, AnalysisSource, ProgressLogEntry } from "../hooks/useDocumentAnalysis";
import type { AnalysisStep, DocumentType } from "../types";

// The single source of truth for "what's happening right now" is the backend: each key below
// is a real stage the upload/Lambda pipeline passes through (see useDocumentAnalysis + the
// backend's _process_async / filing_pipeline.analyze_ticker), not a simulated message. The
// sub-lines under each step come from real backend progress reports, not a rotating list.
type ChecklistKey = "uploading" | AnalysisStep;

interface ChecklistItem {
  key: ChecklistKey;
  label: Record<DocumentType, string>;
}

const UPLOAD_CHECKLIST: ChecklistItem[] = [
  { key: "uploading", label: { lease: "Uploading your lease", filing: "Uploading your filing" } },
  { key: "extracting_text", label: { lease: "Reading the document", filing: "Reading the filing" } },
  { key: "analyzing", label: { lease: "Analyzing with AI", filing: "Analyzing with AI" } },
  { key: "finalizing", label: { lease: "Finalizing your summary", filing: "Finalizing your summary" } },
];

// The EDGAR pipeline runs its financial, diff and category stages concurrently, so these
// arrive interleaved rather than strictly in order — see the monotonic guard below.
const EDGAR_CHECKLIST: ChecklistItem[] = [
  { key: "fetching_filing", label: { lease: "Fetching the filing", filing: "Fetching the filing from EDGAR" } },
  { key: "analyzing", label: { lease: "Reading each section", filing: "Reading the filing section by section" } },
  { key: "reading_financials", label: { lease: "Pulling financials", filing: "Pulling tagged XBRL financials" } },
  { key: "comparing_years", label: { lease: "Comparing years", filing: "Comparing against last year's 10-K" } },
  { key: "benchmarking", label: { lease: "Benchmarking", filing: "Ranking against industry peers" } },
  { key: "reading_insiders", label: { lease: "Reading insider filings", filing: "Reading insider Form 4 filings" } },
  { key: "verifying", label: { lease: "Verifying quotes", filing: "Verifying every quote against the filing" } },
  { key: "finalizing", label: { lease: "Finalizing", filing: "Writing the overview" } },
];

const CHECKLISTS: Record<AnalysisSource, ChecklistItem[]> = {
  upload: UPLOAD_CHECKLIST,
  edgar: EDGAR_CHECKLIST,
};

interface Props {
  phase: AnalysisPhase;
  step: AnalysisStep | null;
  log: ProgressLogEntry[];
  documentType?: DocumentType;
  source?: AnalysisSource;
}

function StatusIcon({ done }: { done: boolean }) {
  return (
    <span className="relative inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center">
      <span
        className={cn(
          "spinner-ring absolute h-3.5 w-3.5 transition-all duration-300 ease-out",
          done ? "scale-50 opacity-0" : "scale-100 opacity-100",
        )}
      />
      <svg
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className={cn(
          "absolute h-3.5 w-3.5 text-foreground transition-all duration-300 ease-out",
          done ? "scale-100 opacity-100" : "scale-50 opacity-0",
        )}
      >
        <path d="M3 8.5l3.2 3.2L13 4.3" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function ProgressIndicator({
  phase,
  step,
  log,
  documentType = "lease",
  source = "upload",
}: Props) {
  const checklist = CHECKLISTS[source];

  // The EDGAR pipeline's branches run concurrently, so reported steps can arrive out of
  // list order. Tracking the furthest stage reached keeps the checklist from ticking
  // backwards, which would read as the analysis having regressed.
  const furthestRef = useRef(-1);
  useEffect(() => {
    if (phase === "idle" || phase === "error") furthestRef.current = -1;
  }, [phase]);

  if (phase !== "uploading" && phase !== "analyzing") return null;

  // Until the backend reports a step, fall back to the first *analysis* stage rather than
  // the first list entry — "uploading" is already finished by the time we are analyzing.
  // It's what the Lambda does first, so it's an honest default rather than a guess.
  const firstAnalysisKey = (checklist.find((item) => item.key !== "uploading") ?? checklist[0]).key;
  const currentKey: ChecklistKey =
    phase === "uploading" && source === "upload" ? "uploading" : (step ?? firstAnalysisKey);
  const reportedIndex = checklist.findIndex((item) => item.key === currentKey);
  furthestRef.current = Math.max(furthestRef.current, reportedIndex);
  const currentIndex = furthestRef.current;
  const visible = checklist.slice(0, currentIndex + 1);

  return (
    <div className="mx-auto max-w-sm py-8">
      <ol className="space-y-3">
        {visible.map((item, i) => {
          const isDone = i < currentIndex;
          const entries = item.key === "uploading" ? [] : log.filter((entry) => entry.step === item.key);
          return (
            <li key={item.key}>
              <div className="flex items-center gap-2.5">
                <StatusIcon done={isDone} />
                <span className={cn("text-sm", isDone ? "text-muted-foreground" : "font-medium text-foreground")}>
                  {item.label[documentType]}
                </span>
              </div>
              {entries.length > 0 && (
                <ul className="mt-1.5 ml-6 space-y-1">
                  {entries.map((entry, j) => (
                    <li key={j} className="log-line text-xs text-muted-foreground">
                      {entry.detail}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
