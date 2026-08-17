import { render, screen } from "@testing-library/react";
import { ConfidenceBadge } from "../components/ConfidenceBadge";

test("renders high confidence label", () => {
  render(<ConfidenceBadge confidence="high" />);
  expect(screen.getByText(/high confidence/i)).toBeInTheDocument();
});

test("renders medium confidence label", () => {
  render(<ConfidenceBadge confidence="medium" />);
  expect(screen.getByText(/medium confidence/i)).toBeInTheDocument();
});

test("renders low confidence label", () => {
  render(<ConfidenceBadge confidence="low" />);
  expect(screen.getByText(/low confidence/i)).toBeInTheDocument();
});
