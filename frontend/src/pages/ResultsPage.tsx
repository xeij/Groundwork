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

export function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ["summary", id],
    queryFn: () => getSummary(id!),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div
        style={{
          textAlign: "center",
          padding: "4rem",
          fontFamily: "system-ui, -apple-system, sans-serif",
          color: "#8b949e",
        }}
      >
        Loading summary...
      </div>
    );
  }

  if (error) {
    const msg =
      error instanceof Error && error.message.includes("expired")
        ? "This summary has expired or doesn't exist. Summaries are kept for 90 days."
        : "Failed to load summary. Please try again.";
    return (
      <div
        style={{
          maxWidth: 560,
          margin: "2rem auto",
          padding: "0 1.25rem",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <ErrorBanner message={msg} />
        <Link to="/" style={{ display: "block", marginTop: "1rem", color: "#58a6ff", textDecoration: "none" }}>
          Analyze another lease
        </Link>
      </div>
    );
  }

  if (!data) return null;

  if (data.documentType === "filing") {
    return (
      <div
        style={{
          maxWidth: 660,
          margin: "0 auto",
          padding: "2.5rem 1.25rem 3rem",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <div style={{ marginBottom: "1.75rem" }}>
          <Link
            to="/"
            style={{ color: "#8b949e", textDecoration: "none", fontSize: "0.875rem", display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
          >
            &#8592; Analyze another document
          </Link>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: "0.75rem 0 0", color: "#e6edf3" }}>
            Filing Summary
          </h1>
        </div>

        <FilingSummaryIntro summary={data.summary} />

        {data.summary.keyMetrics?.tickerSymbol && (
          <StockChart ticker={data.summary.keyMetrics.tickerSymbol} />
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2rem" }}>
          {data.summary.categories.map((cat) => (
            <FinancialCategoryCard key={cat.name} category={cat} />
          ))}
        </div>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", paddingTop: "0.5rem", borderTop: "1px solid #21262d" }}>
          <ShareButton />
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        maxWidth: 660,
        margin: "0 auto",
        padding: "2.5rem 1.25rem 3rem",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <div style={{ marginBottom: "1.75rem" }}>
        <Link
          to="/"
          style={{ color: "#8b949e", textDecoration: "none", fontSize: "0.875rem", display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
        >
          &#8592; Analyze another lease
        </Link>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: "0.75rem 0 0", color: "#e6edf3" }}>
          Lease Summary
        </h1>
      </div>

      <SummaryIntro summary={data.summary} />

      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2rem" }}>
        {data.summary.categories.map((cat) => (
          <CategoryCard key={cat.name} category={cat} />
        ))}
      </div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", paddingTop: "0.5rem", borderTop: "1px solid #21262d" }}>
        <ShareButton />
      </div>
    </div>
  );
}
