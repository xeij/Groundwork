import { useEffect, useRef, useState } from "react";
import { getUploadUrl, uploadPdfToS3, analyzeLease, analyzeTicker, getSummary } from "../api/client";
import { PendingError, ApiError } from "../types";
import type { DocumentType, AnalysisStep } from "../types";

export type AnalysisPhase = "idle" | "uploading" | "analyzing" | "done" | "error";

/** Where the document came from. The two paths report different backend steps. */
export type AnalysisSource = "upload" | "edgar";

export interface ProgressLogEntry {
  step: AnalysisStep;
  detail: string;
}

export interface UseDocumentAnalysisResult {
  phase: AnalysisPhase;
  step: AnalysisStep | null;
  source: AnalysisSource;
  log: ProgressLogEntry[];
  summaryId: string | null;
  errorMessage: string | null;
  run: (file: File, documentType?: DocumentType) => Promise<void>;
  runTicker: (ticker: string) => Promise<void>;
  reset: () => void;
}

// Budgets are tuned to the backend's actual worst-case processing time (see
// LEASE_CLAUDE_BUDGET_SECONDS / FILING_CLAUDE_BUDGET_SECONDS + Lambda Timeout in claude_client.py /
// template.yaml), with margin — filings involve a much larger Claude call than leases.
const POLL_CONFIG: Record<DocumentType, { intervalMs: number; maxPolls: number }> = {
  lease: { intervalMs: 3000, maxPolls: 40 }, // ~2 minutes
  filing: { intervalMs: 5000, maxPolls: 70 }, // ~5.8 minutes
};

// An EDGAR analysis does strictly more work than a PDF upload: six category calls, two
// year-over-year section diffs and a dozen peer XBRL fetches. This window must stay above
// the Lambda Timeout in template.yaml, which in turn sits above the Claude budgets in
// filing_analysis.py — if these three drift apart, a healthy-but-slow analysis looks broken.
const EDGAR_POLL_CONFIG = { intervalMs: 5000, maxPolls: 108 }; // ~9 minutes

export function useDocumentAnalysis(): UseDocumentAnalysisResult {
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const [step, setStep] = useState<AnalysisStep | null>(null);
  const [source, setSource] = useState<AnalysisSource>("upload");
  const [log, setLog] = useState<ProgressLogEntry[]>([]);
  const [summaryId, setSummaryId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Polling runs as a plain async loop, not inside an effect, so nothing cancels it on unmount
  // by default — this ref lets each iteration check whether it should keep going, so a
  // navigated-away-from (or unmounted) analysis stops polling instead of running forever.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function pollUntilDone(id: string, intervalMs: number, maxPolls: number) {
    for (let attempt = 0; attempt < maxPolls; attempt++) {
      await new Promise<void>((resolve) => setTimeout(resolve, intervalMs));
      if (!mountedRef.current) return;
      try {
        await getSummary(id);
        if (!mountedRef.current) return;
        setSummaryId(id);
        setPhase("done");
        return;
      } catch (err) {
        if (!mountedRef.current) return;
        if (err instanceof PendingError) {
          if (err.step) setStep(err.step);
          if (err.step && err.detail) {
            const entry = { step: err.step, detail: err.detail };
            setLog((prev) => (prev[prev.length - 1]?.detail === entry.detail ? prev : [...prev, entry]));
          }
          continue;
        }
        throw err;
      }
    }

    throw new ApiError(408, "Analysis is taking longer than expected. Please try again.");
  }

  function fail(err: unknown) {
    if (!mountedRef.current) return;
    const message = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
    setErrorMessage(message);
    setPhase("error");
  }

  function begin(nextSource: AnalysisSource, nextPhase: AnalysisPhase) {
    setSource(nextSource);
    setPhase(nextPhase);
    setStep(null);
    setLog([]);
    setErrorMessage(null);
  }

  async function run(file: File, documentType: DocumentType = "lease") {
    begin("upload", "uploading");
    try {
      const { presignedUrl, s3Key } = await getUploadUrl(documentType);
      await uploadPdfToS3(presignedUrl, file);
      if (!mountedRef.current) return;
      setPhase("analyzing");

      const { summaryId: id } = await analyzeLease(s3Key);
      const { intervalMs, maxPolls } = POLL_CONFIG[documentType];
      await pollUntilDone(id, intervalMs, maxPolls);
    } catch (err) {
      fail(err);
    }
  }

  async function runTicker(ticker: string) {
    begin("edgar", "analyzing");
    try {
      const { summaryId: id } = await analyzeTicker(ticker);
      if (!mountedRef.current) return;
      await pollUntilDone(id, EDGAR_POLL_CONFIG.intervalMs, EDGAR_POLL_CONFIG.maxPolls);
    } catch (err) {
      fail(err);
    }
  }

  function reset() {
    setPhase("idle");
    setStep(null);
    setLog([]);
    setSummaryId(null);
    setErrorMessage(null);
  }

  return { phase, step, source, log, summaryId, errorMessage, run, runTicker, reset };
}
