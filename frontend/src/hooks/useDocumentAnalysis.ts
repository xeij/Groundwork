import { useState } from "react";
import { getUploadUrl, uploadPdfToS3, analyzeLease, getSummary } from "../api/client";
import { PendingError, ApiError } from "../types";
import type { DocumentType, AnalysisStep } from "../types";

export type AnalysisPhase = "idle" | "uploading" | "analyzing" | "done" | "error";

export interface UseDocumentAnalysisResult {
  phase: AnalysisPhase;
  step: AnalysisStep | null;
  summaryId: string | null;
  errorMessage: string | null;
  run: (file: File, documentType?: DocumentType) => Promise<void>;
  reset: () => void;
}

// Budgets are tuned to the backend's actual worst-case processing time (see
// LEASE_CLAUDE_BUDGET_SECONDS / FILING_CLAUDE_BUDGET_SECONDS + Lambda Timeout in claude_client.py /
// template.yaml), with margin — filings involve a much larger Claude call than leases.
const POLL_CONFIG: Record<DocumentType, { intervalMs: number; maxPolls: number }> = {
  lease: { intervalMs: 3000, maxPolls: 40 }, // ~2 minutes
  filing: { intervalMs: 5000, maxPolls: 70 }, // ~5.8 minutes
};

export function useDocumentAnalysis(): UseDocumentAnalysisResult {
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const [step, setStep] = useState<AnalysisStep | null>(null);
  const [summaryId, setSummaryId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function run(file: File, documentType: DocumentType = "lease") {
    setPhase("uploading");
    setStep(null);
    setErrorMessage(null);
    try {
      const { presignedUrl, s3Key } = await getUploadUrl(documentType);
      await uploadPdfToS3(presignedUrl, file);
      setPhase("analyzing");

      const { summaryId: id } = await analyzeLease(s3Key);
      const { intervalMs, maxPolls } = POLL_CONFIG[documentType];

      for (let attempt = 0; attempt < maxPolls; attempt++) {
        await new Promise<void>((resolve) => setTimeout(resolve, intervalMs));
        try {
          await getSummary(id);
          setSummaryId(id);
          setPhase("done");
          return;
        } catch (err) {
          if (err instanceof PendingError) {
            if (err.step) setStep(err.step);
            continue;
          }
          throw err;
        }
      }

      throw new ApiError(408, "Analysis is taking longer than expected. Please try again.");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      setErrorMessage(message);
      setPhase("error");
    }
  }

  function reset() {
    setPhase("idle");
    setStep(null);
    setSummaryId(null);
    setErrorMessage(null);
  }

  return { phase, step, summaryId, errorMessage, run, reset };
}
