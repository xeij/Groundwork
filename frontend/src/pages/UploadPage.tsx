import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DropZone } from "../components/DropZone";
import { ProgressIndicator } from "../components/ProgressIndicator";
import { ErrorBanner } from "../components/ErrorBanner";
import { useDocumentAnalysis } from "../hooks/useDocumentAnalysis";
import type { DocumentType } from "../types";

const COPY: Record<DocumentType, { subheading: string; caption: string; button: string }> = {
  lease: {
    subheading:
      "Upload your residential lease and get a plain-English breakdown of auto-renewal traps, " +
      "deposit conditions, unusual fees, and what's missing — with exact quotes and specific things to ask for.",
    caption: "Lease documents only",
    button: "Analyze my lease",
  },
  filing: {
    subheading:
      "Upload a 10-K annual report and get a structured breakdown of risk factors, financial performance, " +
      "and liquidity — every finding backed by a verbatim citation and a confidence score.",
    caption: "10-K filings only",
    button: "Analyze this filing",
  },
};

export function UploadPage() {
  const navigate = useNavigate();
  const { phase, summaryId, errorMessage, run, reset } = useDocumentAnalysis();
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>("lease");

  useEffect(() => {
    if (phase === "done" && summaryId) {
      navigate(`/summary/${summaryId}`);
    }
  }, [phase, summaryId, navigate]);

  const isRunning = phase === "uploading" || phase === "analyzing";
  const copy = COPY[documentType];

  return (
    <div
      style={{
        maxWidth: 560,
        margin: "0 auto",
        padding: "3rem 1.25rem 2rem",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <div style={{ marginBottom: "2.5rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, margin: "0 0 0.4rem", color: "#e6edf3" }}>
          honestLease
        </h1>
        <p style={{ color: "#8b949e", margin: 0, lineHeight: 1.6 }}>{copy.subheading}</p>
      </div>

      {!isRunning && (
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.25rem" }}>
          {(["lease", "filing"] as DocumentType[]).map((type) => (
            <button
              key={type}
              onClick={() => setDocumentType(type)}
              style={{
                flex: 1,
                padding: "0.6rem",
                background: documentType === type ? "#1f6feb" : "#161b22",
                color: documentType === type ? "#e6edf3" : "#8b949e",
                border: `1px solid ${documentType === type ? "#388bfd40" : "#30363d"}`,
                borderRadius: 8,
                fontWeight: 600,
                fontSize: "0.875rem",
                cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              {type === "lease" ? "Lease" : "10-K Filing"}
            </button>
          ))}
        </div>
      )}

      {errorMessage && (
        <div style={{ marginBottom: "1rem" }}>
          <ErrorBanner message={errorMessage} onDismiss={reset} />
        </div>
      )}

      {!isRunning && (
        <>
          <DropZone onFile={setFile} captionLabel={copy.caption} />
          <button
            onClick={() => file && run(file, documentType)}
            disabled={!file}
            style={{
              marginTop: "1rem",
              width: "100%",
              padding: "0.8rem",
              background: file ? "#1f6feb" : "#21262d",
              color: file ? "#e6edf3" : "#484f58",
              border: `1px solid ${file ? "#388bfd40" : "#30363d"}`,
              borderRadius: 8,
              fontWeight: 600,
              fontSize: "1rem",
              cursor: file ? "pointer" : "not-allowed",
              transition: "all 0.15s",
            }}
          >
            {copy.button}
          </button>
        </>
      )}

      <ProgressIndicator phase={phase} documentType={documentType} />
    </div>
  );
}
