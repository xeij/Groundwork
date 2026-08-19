import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { TickerSearch } from "../components/TickerSearch";
import * as apiClient from "../api/client";

vi.mock("../api/client");

// Call counts are asserted below, so they must not accumulate across tests.
beforeEach(() => {
  vi.clearAllMocks();
});

const APPLE = { cik: "0000320193", ticker: "AAPL", name: "Apple Inc." };
const APPLIED = { cik: "0000006951", ticker: "AMAT", name: "APPLIED MATERIALS INC /DE" };

test("searches EDGAR as the user types and lists the matches", async () => {
  vi.mocked(apiClient.searchCompanies).mockResolvedValue([APPLE, APPLIED]);
  render(<TickerSearch onSelect={() => {}} selected={null} />);

  await userEvent.type(screen.getByRole("combobox"), "appl");

  expect(await screen.findByRole("option", { name: /apple inc/i })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /applied materials/i })).toBeInTheDocument();
});

test("choosing a result reports it to the parent", async () => {
  vi.mocked(apiClient.searchCompanies).mockResolvedValue([APPLE]);
  const onSelect = vi.fn();
  render(<TickerSearch onSelect={onSelect} selected={null} />);

  await userEvent.type(screen.getByRole("combobox"), "aapl");
  await userEvent.click(await screen.findByRole("option", { name: /apple inc/i }));

  expect(onSelect).toHaveBeenCalledWith(APPLE);
});

test("the keyboard can move through and pick a result", async () => {
  vi.mocked(apiClient.searchCompanies).mockResolvedValue([APPLE, APPLIED]);
  const onSelect = vi.fn();
  render(<TickerSearch onSelect={onSelect} selected={null} />);

  const input = screen.getByRole("combobox");
  await userEvent.type(input, "appl");
  await screen.findByRole("option", { name: /apple inc/i });

  await userEvent.keyboard("{ArrowDown}{Enter}");
  expect(onSelect).toHaveBeenCalledWith(APPLIED);
});

test("the chosen company stays visible after the list closes", () => {
  render(<TickerSearch onSelect={() => {}} selected={APPLE} />);
  expect(screen.getByText(/apple inc/i)).toBeInTheDocument();
  expect(screen.getByText("AAPL")).toBeInTheDocument();
});

test("a failed lookup clears the list instead of surfacing an error", async () => {
  vi.mocked(apiClient.searchCompanies).mockRejectedValue(new Error("network down"));
  render(<TickerSearch onSelect={() => {}} selected={null} />);

  await userEvent.type(screen.getByRole("combobox"), "aapl");

  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("no lookup is made for a query that is only whitespace", async () => {
  vi.mocked(apiClient.searchCompanies).mockResolvedValue([]);
  render(<TickerSearch onSelect={() => {}} selected={null} />);

  await userEvent.type(screen.getByRole("combobox"), "   ");

  expect(apiClient.searchCompanies).not.toHaveBeenCalled();
});
