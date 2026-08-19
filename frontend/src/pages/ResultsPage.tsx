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
  <Link to="/" className="link-muted" style={{ fontSize: "0.85rem", display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
    &#8592; Analyze another document
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
      <div style={{ minHeight: "100vh" }}>
        <Header />
        <div style={{ textAlign: "center", padding: "5rem 1rem", color: "var(--text-secondary)" }}>
          <div className="spinner-ring" style={{ width: 26, height: 26, margin: "0 auto 1rem" }} />
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
      <div style={{ minHeight: "100vh" }}>
        <Header />
        <div style={{ maxWidth: 560, margin: "0 auto", padding: "2.5rem 1.25rem" }}>
          <ErrorBanner message={msg} />
          <Link to="/" className="link-muted" style={{ display: "block", marginTop: "1rem" }}>
            Analyze another document
          </Link>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const isFiling = data.documentType === "filing";

  return (
    <div style={{ minHeight: "100vh" }}>
      <Header right={BACK_LINK} />
      <div style={{ maxWidth: 660, margin: "0 auto", padding: "2.5rem 1.25rem 3.5rem" }}>
        <h1
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "1.6rem",
            fontWeight: 500,
            margin: "0 0 1.75rem",
            color: "var(--text-primary)",
            letterSpacing: "-0.01em",
          }}
        >
          {isFiling ? "Filing Summary" : "Lease Summary"}
        </h1>

        {isFiling ? (
          <>
            <FilingSummaryIntro summary={data.summary} />
            {data.summary.keyMetrics?.tickerSymbol && <StockChart ticker={data.summary.keyMetrics.tickerSymbol} />}
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2rem" }}>
              {data.summary.categories.map((cat) => (
                <FinancialCategoryCard key={cat.name} category={cat} />
              ))}
            </div>
          </>
        ) : (
          <>
            <SummaryIntro summary={data.summary} />
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2rem" }}>
              {data.summary.categories.map((cat) => (
                <CategoryCard key={cat.name} category={cat} />
              ))}
            </div>
          </>
        )}

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", paddingTop: "1.25rem", borderTop: "1px solid var(--border)" }}>
          <ShareButton />
        </div>
      </div>
    </div>
  );
}
