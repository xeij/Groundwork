import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DropZone } from "../components/DropZone";
import { ProgressIndicator } from "../components/ProgressIndicator";
import { ErrorBanner } from "../components/ErrorBanner";
import { Header } from "../components/Header";
import { TickerSearch } from "../components/TickerSearch";
import { Button } from "../components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useDocumentAnalysis } from "../hooks/useDocumentAnalysis";
import type { CompanySearchResult, DocumentType } from "../types";

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
      "Name a public company and we'll pull its latest 10-K straight from SEC EDGAR, then tell you what " +
      "changed since last year's filing, what the tagged financials say that the narrative doesn't, and " +
      "how it ranks against its industry peers. Every quote is checked back against the filing text.",
    caption: "10-K filings only",
    button: "Analyze this filing",
  },
};

export function UploadPage() {
  const navigate = useNavigate();
  const { phase, step, source, log, summaryId, errorMessage, run, runTicker, reset } =
    useDocumentAnalysis();
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>("lease");
  const [company, setCompany] = useState<CompanySearchResult | null>(null);

  useEffect(() => {
    if (phase === "done" && summaryId) {
      navigate(`/summary/${summaryId}`);
    }
  }, [phase, summaryId, navigate]);

  const isRunning = phase === "uploading" || phase === "analyzing";
  const copy = COPY[documentType];
  const isFiling = documentType === "filing";

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

        {!isRunning && isFiling && (
          <>
            <TickerSearch onSelect={setCompany} selected={company} />
            <Button
              onClick={() => company && runTicker(company.ticker)}
              disabled={!company}
              className="mt-4 w-full"
              size="lg"
            >
              {company ? `Analyze ${company.ticker}'s latest 10-K` : "Analyze the latest 10-K"}
            </Button>

            <div className="my-7 flex items-center gap-3">
              <span className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or upload a PDF</span>
              <span className="h-px flex-1 bg-border" />
            </div>
          </>
        )}

        {!isRunning && (
          <>
            <DropZone onFile={setFile} captionLabel={copy.caption} />
            <Button
              onClick={() => file && run(file, documentType)}
              disabled={!file}
              className="mt-4 w-full"
              size="lg"
              variant={isFiling ? "outline" : "default"}
            >
              {copy.button}
            </Button>
            {isFiling && (
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                A PDF is analyzed on its own. Pulling the filing from EDGAR instead is what makes the
                year-over-year comparison, peer ranking and XBRL cross-check possible.
              </p>
            )}
          </>
        )}

        <ProgressIndicator
          phase={phase}
          step={step}
          log={log}
          documentType={documentType}
          source={source}
        />
      </div>
    </div>
  );
}
