import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SectionDiffCard } from "../components/SectionDiffCard";
import type { SectionDiff } from "../types";

const DIFF: SectionDiff = {
  section: "Item 1A. Risk Factors",
  priorYear: 2024,
  currentYear: 2025,
  stats: { unchanged: 17, reworded: 2, added: 1, removed: 1, priorTotal: 20, currentTotal: 20 },
  changes: [
    {
      changeType: "removed",
      heading: "Dependence on a single manufacturing partner",
      severity: "red",
      significance: "The company dropped a risk it disclosed last year without explanation.",
      quote: "We depend on a single partner for final assembly.",
      redline: null,
      similarity: null,
    },
    {
      changeType: "added",
      heading: "Artificial intelligence regulation",
      severity: "yellow",
      significance: "A newly disclosed regulatory exposure that was absent last year.",
      quote: "New AI regulations may increase our compliance costs.",
      redline: null,
      similarity: null,
    },
    {
      changeType: "reworded",
      heading: "Supply chain concentration",
      severity: "yellow",
      significance: "Language hardened from 'concentrated' to 'dependent on a single supplier'.",
      quote: "We are dependent on a single supplier.",
      similarity: 0.83,
      redline: [
        { op: "equal", text: "Our supply chain is " },
        { op: "delete", text: "concentrated" },
        { op: "insert", text: "dependent on a single supplier" },
        { op: "ellipsis", text: "" },
      ],
    },
  ],
  omittedChangeCount: 2,
};

test("shows the section, the years compared, and the change counts", () => {
  render(<SectionDiffCard diff={DIFF} />);
  expect(screen.getByRole("heading", { name: /Item 1A\. Risk Factors — what changed/i })).toBeInTheDocument();
  expect(screen.getByText(/FY2024 filing compared with FY2025/i)).toBeInTheDocument();
  expect(screen.getByText("17")).toBeInTheDocument();
  expect(screen.getByText(/carried over unchanged/i)).toBeInTheDocument();
});

test("labels dropped, new and reworded changes distinctly", () => {
  render(<SectionDiffCard diff={DIFF} />);
  expect(screen.getByText("Dropped")).toBeInTheDocument();
  expect(screen.getByText("New")).toBeInTheDocument();
  expect(screen.getByText("Reworded")).toBeInTheDocument();
});

test("explains why each change matters and quotes the filing", () => {
  render(<SectionDiffCard diff={DIFF} />);
  expect(screen.getByText(/dropped a risk it disclosed last year/i)).toBeInTheDocument();
  expect(screen.getByText(/single partner for final assembly/i)).toBeInTheDocument();
});

test("the redline is collapsed until asked for, then shows insertions and deletions", async () => {
  render(<SectionDiffCard diff={DIFF} />);
  expect(screen.queryByText("concentrated")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /show what changed/i }));

  const removed = screen.getByText("concentrated");
  const added = screen.getByText("dependent on a single supplier");
  expect(removed.tagName).toBe("DEL");
  expect(added.tagName).toBe("INS");
});

test("surfaces how much of a reworded factor is unchanged", () => {
  render(<SectionDiffCard diff={DIFF} />);
  expect(screen.getByRole("button", { name: /83% unchanged/i })).toBeInTheDocument();
});

test("reports changes it did not have room to show", () => {
  render(<SectionDiffCard diff={DIFF} />);
  expect(screen.getByText(/2 lower-signal changes not shown/i)).toBeInTheDocument();
});

test("a discarded quote is reported as a failed check, not as omitted for space", () => {
  // omittedChangeCount is inclusive of the discarded ones, so 5 - 3 = 2 were omitted for
  // space. Reporting all 5 as "lower-signal" would hide that 3 failed verification.
  render(
    <SectionDiffCard
      diff={{ ...DIFF, omittedChangeCount: 5, droppedForUnverifiedQuoteCount: 3 }}
    />,
  );
  expect(screen.getByText(/2 lower-signal changes not shown/i)).toBeInTheDocument();
  expect(
    screen.getByText(/3 discarded for quoting text the filing does not contain/i),
  ).toBeInTheDocument();
});

test("says so plainly when nothing changed between filings", () => {
  const unchanged: SectionDiff = {
    ...DIFF,
    changes: [],
    omittedChangeCount: 0,
    stats: { ...DIFF.stats, added: 0, removed: 0, reworded: 0 },
  };
  render(<SectionDiffCard diff={unchanged} />);
  expect(screen.getByText(/nothing material changed in this section/i)).toBeInTheDocument();
});
