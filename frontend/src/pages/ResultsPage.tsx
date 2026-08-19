import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getSummary } from "../api/client";
import { CategoryCard } from "../components/CategoryCard";
import { SummaryIntro } from "../components/SummaryIntro";
import { FinancialCategoryCard } from "../components/FinancialCategoryCard";
import { FilingSummaryIntro } from "../components/FilingSummaryIntro";
import { StockChart } from "../components/StockChart";
import { ShareButton } from "../components/ShareButton";
import { ErrorBanner } from "../components/ErrorBanner";
import { Header } from "../components/Header";

const BACK_LINK = (
  <Link to="/" className="text-sm text-muted-foreground no-underline hover:text-foreground">
    Analyze another document
  </Link>
);

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
          <>
            <FilingSummaryIntro summary={data.summary} />
            {data.summary.keyMetrics?.tickerSymbol && <StockChart ticker={data.summary.keyMetrics.tickerSymbol} />}
            <div className="mb-8 flex flex-col gap-3">
              {data.summary.categories.map((cat) => (
                <FinancialCategoryCard key={cat.name} category={cat} />
              ))}
            </div>
          </>
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
