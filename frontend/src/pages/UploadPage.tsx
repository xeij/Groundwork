import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DropZone } from "../components/DropZone";
import { ProgressIndicator } from "../components/ProgressIndicator";
import { ErrorBanner } from "../components/ErrorBanner";
import { Header } from "../components/Header";
import { useDocumentAnalysis } from "../hooks/useDocumentAnalysis";
import type { DocumentType } from "../types";

const COPY: Record<DocumentType, { subheading: string; caption: string; button: string }> = {
  lease: {
    subheading:
      "Upload your residential lease and see what actually matters: auto-renewal traps, deposit conditions, " +
      "hidden fees, and anything standard that's missing. You'll get the exact quote for each issue and " +
      "something specific to ask your landlord.",
    caption: "Lease documents only",
    button: "Analyze my lease",
  },
  filing: {
    subheading:
      "Upload a 10-K and we'll flag the risk factors, financial performance, and liquidity issues worth knowing " +
      "about. Every finding points back to the exact page it came from, plus how confident we are in it.",
    caption: "10-K filings only",
    button: "Analyze this filing",
  },
};

export function UploadPage() {
  const navigate = useNavigate();
  const { phase, step, summaryId, errorMessage, run, reset } = useDocumentAnalysis();
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
    <div style={{ minHeight: "100vh" }}>
      <Header />
      <div style={{ maxWidth: 560, margin: "0 auto", padding: "3.5rem 1.25rem 3rem" }}>
        <div style={{ marginBottom: "2.5rem" }}>
          <p
            style={{
              margin: "0 0 0.6rem",
              color: "var(--accent)",
              fontSize: "0.78rem",
              fontWeight: 600,
              letterSpacing: "0.09em",
              textTransform: "uppercase",
            }}
          >
            Document intelligence
          </p>
          <h1
            style={{
              fontFamily: "var(--font-serif)",
              fontSize: "2rem",
              fontWeight: 500,
              margin: "0 0 0.75rem",
              color: "var(--text-primary)",
              lineHeight: 1.2,
              letterSpacing: "-0.01em",
            }}
          >
            Know what's actually in the document.
          </h1>
          <p style={{ color: "var(--text-secondary)", margin: 0, lineHeight: 1.65, fontSize: "0.96rem" }}>
            {copy.subheading}
          </p>
        </div>

        {!isRunning && (
          <div
            role="group"
            aria-label="Document type"
            style={{
              display: "flex",
              gap: "0.25rem",
              marginBottom: "1.5rem",
              padding: "0.25rem",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
            }}
          >
            {(["lease", "filing"] as DocumentType[]).map((type) => (
              <button
                key={type}
                onClick={() => setDocumentType(type)}
                style={{
                  flex: 1,
                  padding: "0.55rem",
                  background: documentType === type ? "var(--surface-raised)" : "transparent",
                  color: documentType === type ? "var(--text-primary)" : "var(--text-secondary)",
                  border: documentType === type ? "1px solid var(--border-strong)" : "1px solid transparent",
                  borderRadius: "calc(var(--radius) - 4px)",
                  fontWeight: 600,
                  fontSize: "0.85rem",
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
              className="btn btn-primary"
              style={{ marginTop: "1rem", width: "100%", padding: "0.85rem" }}
            >
              {copy.button}
            </button>
          </>
        )}

        <ProgressIndicator phase={phase} step={step} documentType={documentType} />
      </div>
    </div>
  );
}
