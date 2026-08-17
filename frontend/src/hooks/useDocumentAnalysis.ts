import { useState } from "react";
import { getUploadUrl, uploadPdfToS3, analyzeLease, getSummary } from "../api/client";
import { ApiError } from "../types";
import type { DocumentType } from "../types";

export type AnalysisPhase = "idle" | "uploading" | "analyzing" | "done" | "error";

export interface UseDocumentAnalysisResult {
  phase: AnalysisPhase;
  summaryId: string | null;
  errorMessage: string | null;
  run: (file: File, documentType?: DocumentType) => Promise<void>;
  reset: () => void;
}

const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 40; // 2 minutes max

export function useDocumentAnalysis(): UseDocumentAnalysisResult {
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const [summaryId, setSummaryId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function run(file: File, documentType: DocumentType = "lease") {
    setPhase("uploading");
    setErrorMessage(null);
    try {
      const { presignedUrl, s3Key } = await getUploadUrl(documentType);
      await uploadPdfToS3(presignedUrl, file);
      setPhase("analyzing");

      const { summaryId: id } = await analyzeLease(s3Key);

      for (let attempt = 0; attempt < MAX_POLLS; attempt++) {
        await new Promise<void>((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        try {
          await getSummary(id);
          setSummaryId(id);
          setPhase("done");
          return;
        } catch (err) {
          if (err instanceof ApiError && err.status === 202) continue;
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
    setSummaryId(null);
    setErrorMessage(null);
  }

  return { phase, summaryId, errorMessage, run, reset };
}
