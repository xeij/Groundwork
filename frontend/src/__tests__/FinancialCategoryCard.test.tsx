import { render, screen } from "@testing-library/react";
import { FinancialCategoryCard } from "../components/FinancialCategoryCard";
import type { FinancialCategory } from "../types";

const YELLOW_CATEGORY: FinancialCategory = {
  name: "Risk Factors",
  severity: "yellow",
  findings: [
    {
      summary: "Pending litigation could materially affect results.",
      citation: { quote: "The Company is subject to a pending lawsuit.", page: 14 },
      confidence: "medium",
    },
  ],
};

const GREEN_CATEGORY: FinancialCategory = {
  name: "Related-Party Transactions",
  severity: "green",
  findings: [{ summary: "Nothing material to report.", citation: null, confidence: "high" }],
};

test("renders category name, finding summary, and citation with page", () => {
  render(<FinancialCategoryCard category={YELLOW_CATEGORY} />);
  expect(screen.getByText("Risk Factors")).toBeInTheDocument();
  expect(screen.getByText("Pending litigation could materially affect results.")).toBeInTheDocument();
  expect(screen.getByText(/subject to a pending lawsuit/i)).toBeInTheDocument();
  expect(screen.getByText(/page 14/i)).toBeInTheDocument();
});

test("renders confidence badge for the finding", () => {
  render(<FinancialCategoryCard category={YELLOW_CATEGORY} />);
  expect(screen.getByText(/medium confidence/i)).toBeInTheDocument();
});

test("renders green severity badge with 'All clear' label", () => {
  render(<FinancialCategoryCard category={GREEN_CATEGORY} />);
  expect(screen.getByText(/all clear/i)).toBeInTheDocument();
});
