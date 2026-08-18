import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { StockChart } from "../components/StockChart";
import * as apiClient from "../api/client";

vi.mock("../api/client");

function renderChart(ticker = "ACME") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StockChart ticker={ticker} />
    </QueryClientProvider>,
  );
}

test("shows loading state before data resolves", () => {
  vi.mocked(apiClient.getStockChart).mockImplementation(() => new Promise(() => {}));
  renderChart();
  expect(screen.getByText(/loading price chart/i)).toBeInTheDocument();
});

test("renders ticker and positive change percent", async () => {
  vi.mocked(apiClient.getStockChart).mockResolvedValue({
    ticker: "ACME",
    points: [
      { date: "2026-01-02", close: 100 },
      { date: "2026-03-01", close: 90 },
      { date: "2026-06-15", close: 120 },
    ],
    changePercent: 20,
  });
  renderChart();
  expect(await screen.findByText(/ACME/)).toBeInTheDocument();
  expect(screen.getByText("+20.00%")).toBeInTheDocument();
  expect(screen.getByText("2026-01-02")).toBeInTheDocument();
  expect(screen.getByText("2026-06-15")).toBeInTheDocument();
});

test("renders negative change percent without a plus sign", async () => {
  vi.mocked(apiClient.getStockChart).mockResolvedValue({
    ticker: "ACME",
    points: [
      { date: "2026-01-02", close: 100 },
      { date: "2026-06-15", close: 80 },
    ],
    changePercent: -20,
  });
  renderChart();
  expect(await screen.findByText("-20.00%")).toBeInTheDocument();
});

test("shows an unavailable message when the chart fails to load", async () => {
  vi.mocked(apiClient.getStockChart).mockRejectedValue(new Error("not found"));
  renderChart("ACME");
  expect(await screen.findByText(/unavailable for ACME/i)).toBeInTheDocument();
});

test("shows an unavailable message when fewer than two points are returned", async () => {
  vi.mocked(apiClient.getStockChart).mockResolvedValue({
    ticker: "ACME",
    points: [{ date: "2026-06-15", close: 100 }],
    changePercent: 0,
  });
  renderChart("ACME");
  expect(await screen.findByText(/unavailable for ACME/i)).toBeInTheDocument();
});
