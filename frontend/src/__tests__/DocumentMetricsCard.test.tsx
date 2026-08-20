import { render, screen } from "@testing-library/react";
import { DocumentMetricsCard } from "../components/DocumentMetricsCard";
import type { TextMetrics } from "../types";

const METRICS: TextMetrics = {
  currentYear: 2025,
  priorYear: 2024,
  sections: [
    { item: "1A", label: "Item 1A. Risk Factors", words: 22_400, priorWords: 18_100, changePercent: 23.8, notable: true },
    { item: "7", label: "Item 7. MD&A", words: 12_000, priorWords: 11_800, changePercent: 1.7, notable: false },
    { item: "3", label: "Item 3. Legal Proceedings", words: 900, priorWords: null, changePercent: null, notable: false },
  ],
  riskFactors: {
    count: 41,
    priorCount: 35,
    change: 6,
    words: 22_400,
    priorWords: 18_100,
    wordChangePercent: 23.8,
  },
  readability: {
    fogIndex: 21.4,
    wordsPerSentence: 34.2,
    complexWordPercent: 19.3,
    wordCount: 42_000,
    sentenceCount: 1_228,
    severity: "yellow",
    interpretation: "The narrative sections average 34 words per sentence.",
  },
  hedging: {
    per1000: 28.4,
    priorPer1000: 22.1,
    change: 6.3,
    wordCount: 42_000,
    topTerms: [
      { term: "may", count: 310 },
      { term: "could", count: 190 },
    ],
    severity: "yellow",
    interpretation: "Words expressing uncertainty appear 28.4 times per thousand words.",
  },
  tripwires: [
    {
      key: "material_weakness",
      label: "Material weakness in internal control",
      severity: "red",
      count: 1,
      hypotheticalCount: 3,
      explanation: "A material weakness means the company's own controls could fail.",
      occurrences: [
        {
          section: "Item 9A. Controls and Procedures",
          quote: "Management concluded that a material weakness existed in our controls over revenue recognition.",
          hypothetical: false,
        },
      ],
    },
  ],
};

test("headline document stats are shown with their year-over-year change", () => {
  render(<DocumentMetricsCard metrics={METRICS} />);

  expect(screen.getByText("41")).toBeInTheDocument();
  expect(screen.getByText("+6 on last year")).toBeInTheDocument();
  expect(screen.getByText("22,400 words")).toBeInTheDocument();
  expect(screen.getByText("+24% on last year")).toBeInTheDocument();
});

test("both halves of the readability measure are shown", () => {
  render(<DocumentMetricsCard metrics={METRICS} />);

  expect(screen.getByText("34.2 words")).toBeInTheDocument();
  expect(screen.getByText("Fog index 21.4")).toBeInTheDocument();
});

test("hedging density lists the terms driving it", () => {
  render(<DocumentMetricsCard metrics={METRICS} />);

  expect(screen.getByText("28.4 / 1,000 words")).toBeInTheDocument();
  expect(screen.getByText(/may \(310\), could \(190\)/)).toBeInTheDocument();
});

test("a tripwire is shown with the sentence it fired on and its section", () => {
  render(<DocumentMetricsCard metrics={METRICS} />);

  expect(screen.getByText(/Management concluded that a material weakness existed/)).toBeInTheDocument();
  expect(screen.getByText("Item 9A. Controls and Procedures")).toBeInTheDocument();
});

test("conditional mentions are counted apart from the disclosure itself", () => {
  render(<DocumentMetricsCard metrics={METRICS} />);

  expect(screen.getByText(/appears 3 more times in conditional language/)).toBeInTheDocument();
});

test("sections with no prior-year counterpart are left out of the length comparison", () => {
  render(<DocumentMetricsCard metrics={METRICS} />);

  expect(screen.getByText("Item 1A")).toBeInTheDocument();
  expect(screen.queryByText("Item 3")).not.toBeInTheDocument();
});

test("a first-time filer still renders what could be measured", () => {
  const firstYear: TextMetrics = {
    ...METRICS,
    priorYear: null,
    sections: METRICS.sections.map((s) => ({ ...s, priorWords: null, changePercent: null, notable: false })),
    riskFactors: { count: 41, priorCount: null, change: null, words: 22_400, priorWords: null, wordChangePercent: null },
    hedging: { ...METRICS.hedging!, priorPer1000: null, change: null },
  };
  render(<DocumentMetricsCard metrics={firstYear} />);

  expect(screen.getByText("no prior filing to compare")).toBeInTheDocument();
  expect(screen.getByText("41")).toBeInTheDocument();
});

test("the card is omitted when there is nothing measurable to show", () => {
  const { container } = render(
    <DocumentMetricsCard
      metrics={{ sections: [], riskFactors: null, readability: null, hedging: null, tripwires: [] }}
    />,
  );

  expect(container).toBeEmptyDOMElement();
});
