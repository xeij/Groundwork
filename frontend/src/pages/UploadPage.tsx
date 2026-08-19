import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DropZone } from "../components/DropZone";
import { ProgressIndicator } from "../components/ProgressIndicator";
import { ErrorBanner } from "../components/ErrorBanner";
import { Header } from "../components/Header";
import { Button } from "../components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
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
    <div className="min-h-screen">
      <Header />
      <div className="mx-auto max-w-xl px-5 py-14">
        <div className="mb-10">
          <p className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Document intelligence
          </p>
          <h1 className="mb-3 text-3xl font-semibold tracking-tight text-foreground">
            Know what's actually in the document.
          </h1>
          <p className="text-sm leading-relaxed text-muted-foreground">{copy.subheading}</p>
        </div>

        {!isRunning && (
          <Tabs
            value={documentType}
            onValueChange={(v) => setDocumentType(v as DocumentType)}
            className="mb-6"
          >
            <TabsList aria-label="Document type" className="w-full">
              <TabsTrigger value="lease">Lease</TabsTrigger>
              <TabsTrigger value="filing">10-K Filing</TabsTrigger>
            </TabsList>
          </Tabs>
        )}

        {errorMessage && (
          <div className="mb-4">
            <ErrorBanner message={errorMessage} onDismiss={reset} />
          </div>
        )}

        {!isRunning && (
          <>
            <DropZone onFile={setFile} captionLabel={copy.caption} />
            <Button onClick={() => file && run(file, documentType)} disabled={!file} className="mt-4 w-full" size="lg">
              {copy.button}
            </Button>
          </>
        )}

        <ProgressIndicator phase={phase} step={step} documentType={documentType} />
      </div>
    </div>
  );
}
