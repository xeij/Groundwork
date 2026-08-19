import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getSummary } from "../api/client";
import { CategoryCard } from "../components/CategoryCard";
import { SummaryIntro } from "../components/SummaryIntro";
import { FinancialCategoryCard } from "../components/FinancialCategoryCard";
import { FilingSummaryIntro } from "../components/FilingSummaryIntro";
import { CompanyHeader } from "../components/CompanyHeader";
import { FinancialsCard } from "../components/FinancialsCard";
import { ForensicScreensCard } from "../components/ForensicScreensCard";
import { PeerComparisonCard } from "../components/PeerComparisonCard";
import { SectionDiffCard } from "../components/SectionDiffCard";
import { VerificationSummary } from "../components/VerificationBadge";
import { StockChart } from "../components/StockChart";
import { ShareButton } from "../components/ShareButton";
import { ErrorBanner } from "../components/ErrorBanner";
import { Header } from "../components/Header";
import type { FinancialSummary } from "../types";

const BACK_LINK = (
  <Link to="/" className="text-sm text-muted-foreground no-underline hover:text-foreground">
    Analyze another document
  </Link>
);

function FilingResults({ summary }: { summary: FinancialSummary }) {
  // Every enrichment below is optional — an analysis of a company with no prior 10-K, no
  // usable XBRL, or too thin an industry cohort still renders everything else it did get.
  const diffs = summary.diffs ?? [];
  const screens = summary.screens ?? [];
  const flags = summary.flags ?? [];
  const history = summary.financialHistory ?? [];
  const ratios = summary.ratios ?? {};

  return (
    <>
      {summary.company && <CompanyHeader company={summary.company} />}
      <FilingSummaryIntro summary={summary} />
      {summary.keyMetrics?.tickerSymbol && <StockChart ticker={summary.keyMetrics.tickerSymbol} />}

      {diffs.length > 0 && (
        <div className="mb-8 flex flex-col gap-3">
          {diffs.map((diff) => (
            <SectionDiffCard key={diff.section} diff={diff} />
          ))}
        </div>
      )}

      {(history.length > 0 || Object.keys(ratios).length > 0) && (
        <div className="mb-8">
          <FinancialsCard history={history} ratios={ratios} />
        </div>
      )}

      {(screens.length > 0 || flags.length > 0) && (
        <div className="mb-8">
          <ForensicScreensCard screens={screens} flags={flags} />
        </div>
      )}

      {summary.peers && (
        <div className="mb-8">
          <PeerComparisonCard peers={summary.peers} />
        </div>
      )}

      <div className="mb-8 flex flex-col gap-3">
        {summary.categories.map((cat) => (
          <FinancialCategoryCard key={cat.name} category={cat} />
        ))}
      </div>

      {(summary.verificationStats || summary.coverageNote) && (
        <div className="mb-8 space-y-1.5 rounded-lg border border-border px-5 py-4">
          <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            How this was checked
          </p>
          {summary.verificationStats && <VerificationSummary stats={summary.verificationStats} />}
          {summary.coverageNote && (
            <p className="text-xs leading-relaxed text-muted-foreground">{summary.coverageNote}</p>
          )}
        </div>
      )}
    </>
  );
}

export function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ["summary", id],
    queryFn: () => getSummary(id!),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="min-h-screen">
        <Header />
        <div className="px-4 py-20 text-center text-muted-foreground">
          <div className="spinner-ring mx-auto mb-4 h-6 w-6" />
          Loading summary...
        </div>
      </div>
    );
  }

  if (error) {
    const msg =
      error instanceof Error && error.message.includes("expired")
        ? "This summary has expired or doesn't exist. Summaries are kept for 90 days."
        : "Failed to load summary. Please try again.";
    return (
      <div className="min-h-screen">
        <Header />
        <div className="mx-auto max-w-xl px-5 py-10">
          <ErrorBanner message={msg} />
          <Link to="/" className="mt-4 block text-sm text-muted-foreground no-underline hover:text-foreground">
            Analyze another document
          </Link>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const isFiling = data.documentType === "filing";

  return (
    <div className="min-h-screen">
      <Header right={BACK_LINK} />
      <div className="mx-auto max-w-2xl px-5 py-10 pb-14">
        <h1 className="mb-7 text-2xl font-semibold tracking-tight text-foreground">
          {isFiling ? "Filing Summary" : "Lease Summary"}
        </h1>

        {isFiling ? (
          <FilingResults summary={data.summary} />
        ) : (
          <>
            <SummaryIntro summary={data.summary} />
            <div className="mb-8 flex flex-col gap-3">
              {data.summary.categories.map((cat) => (
                <CategoryCard key={cat.name} category={cat} />
              ))}
            </div>
          </>
        )}

        <div className="flex flex-wrap gap-3 border-t border-border pt-5">
          <ShareButton />
        </div>
      </div>
    </div>
  );
}
