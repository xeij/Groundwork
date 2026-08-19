import { useEffect, useState } from "react";
import type { AnalysisPhase } from "../hooks/useDocumentAnalysis";
import type { DocumentType } from "../types";

const UPLOADING_MESSAGES: Record<DocumentType, string[]> = {
  lease: [
    "Uploading your lease...",
    "Sending your document securely...",
    "Getting your lease ready...",
  ],
  filing: [
    "Uploading your filing...",
    "Sending your document securely...",
    "Getting your filing ready...",
  ],
};

const ANALYZING_MESSAGES: Record<DocumentType, string[]> = {
  lease: [
    "Reading through your lease...",
    "Spotting auto-renewal clauses...",
    "Checking deposit conditions...",
    "Looking for unusual fees...",
    "Scanning for missing standard clauses...",
    "Reviewing the fine print...",
    "Flagging anything you should know about...",
    "Putting it all together...",
    "Almost there...",
    "Writing up your summary...",
  ],
  filing: [
    "Reading through the filing...",
    "Scanning risk factors...",
    "Reviewing financial performance...",
    "Checking liquidity and capital resources...",
    "Looking for related-party transactions...",
    "Checking legal proceedings...",
    "Verifying citations against the source text...",
    "Scoring confidence on each finding...",
    "Almost there...",
    "Writing up your summary...",
  ],
};

interface Props {
  phase: AnalysisPhase;
  documentType?: DocumentType;
}

export function ProgressIndicator({ phase, documentType = "lease" }: Props) {
  const [index, setIndex] = useState(0);

  const messages =
    phase === "uploading"
      ? UPLOADING_MESSAGES[documentType]
      : phase === "analyzing"
        ? ANALYZING_MESSAGES[documentType]
        : null;

  useEffect(() => {
    if (!messages) return;
    setIndex(0);
    const id = setInterval(
      () => setIndex((i) => (i + 1) % messages.length),
      phase === "uploading" ? 1500 : 2500,
    );
    return () => clearInterval(id);
  }, [phase, documentType]);

  if (!messages) return null;

  return (
    <div style={{ textAlign: "center", padding: "2.5rem 1rem 1rem" }}>
      <div className="spinner-ring" style={{ width: 30, height: 30, margin: "0 auto 1.1rem" }} />
      <p key={index} className="fade-msg" style={{ minHeight: "1.5em", margin: 0, color: "var(--text-primary)", fontSize: "0.92rem" }}>
        {messages[index]}
      </p>
    </div>
  );
}
