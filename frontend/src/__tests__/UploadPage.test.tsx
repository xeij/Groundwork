import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { UploadPage } from "../pages/UploadPage";
import * as apiClient from "../api/client";
import { PendingError } from "../types";

vi.mock("../api/client");

const PDF_FILE = new File(["content"], "lease.pdf", { type: "application/pdf" });

function renderPage() {
  return render(
    <MemoryRouter>
      <UploadPage />
    </MemoryRouter>,
  );
}

test("renders the upload heading", () => {
  renderPage();
  expect(screen.getByText(/groundwork/i)).toBeInTheDocument();
});

test("analyze button is disabled before file is selected", () => {
  renderPage();
  expect(screen.getByRole("button", { name: /analyze/i })).toBeDisabled();
});

test("analyze button enables after valid PDF is selected", async () => {
  renderPage();
  await userEvent.upload(screen.getByTestId("file-input"), PDF_FILE);
  expect(screen.getByRole("button", { name: /analyze/i })).toBeEnabled();
});

test("shows uploading state when analysis starts", async () => {
  vi.mocked(apiClient.getUploadUrl).mockResolvedValue({
    presignedUrl: "http://s3.example.com/upload",
    s3Key: "leases/x.pdf",
  });
  vi.mocked(apiClient.uploadPdfToS3).mockResolvedValue(undefined);
  vi.mocked(apiClient.analyzeLease).mockImplementation(() => new Promise(() => {}));

  renderPage();
  await userEvent.upload(screen.getByTestId("file-input"), PDF_FILE);
  await userEvent.click(screen.getByRole("button", { name: /analyze/i }));
  expect(await screen.findByText(/reading the document/i)).toBeInTheDocument();
});

test(
  "checklist adds a step with a checkmark as the backend reports progress, without repeating",
  async () => {
    vi.mocked(apiClient.getUploadUrl).mockResolvedValue({
      presignedUrl: "http://s3.example.com/upload",
      s3Key: "leases/x.pdf",
    });
    vi.mocked(apiClient.uploadPdfToS3).mockResolvedValue(undefined);
    vi.mocked(apiClient.analyzeLease).mockResolvedValue({ summaryId: "abc12345" });
    vi.mocked(apiClient.getSummary)
      .mockRejectedValueOnce(new PendingError("extracting_text"))
      .mockRejectedValueOnce(new PendingError("analyzing"));

    renderPage();
    await userEvent.upload(screen.getByTestId("file-input"), PDF_FILE);
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByText(/analyzing with ai/i, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getAllByText(/reading the document/i)).toHaveLength(1);
    expect(screen.getAllByText(/uploading your lease/i)).toHaveLength(1);
  },
  10000,
);

test(
  "stacks distinct backend progress details under the step they belong to, without duplicating repeats",
  async () => {
    vi.mocked(apiClient.getUploadUrl).mockResolvedValue({
      presignedUrl: "http://s3.example.com/upload",
      s3Key: "leases/x.pdf",
    });
    vi.mocked(apiClient.uploadPdfToS3).mockResolvedValue(undefined);
    vi.mocked(apiClient.analyzeLease).mockResolvedValue({ summaryId: "abc12345" });
    vi.mocked(apiClient.getSummary)
      .mockRejectedValueOnce(new PendingError("extracting_text", "Reading page 4 of 12"))
      .mockRejectedValueOnce(new PendingError("extracting_text", "Reading page 4 of 12"))
      .mockRejectedValueOnce(new PendingError("extracting_text", "Reading page 12 of 12"));

    renderPage();
    await userEvent.upload(screen.getByTestId("file-input"), PDF_FILE);
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByText(/reading page 12 of 12/i, {}, { timeout: 10000 })).toBeInTheDocument();
    expect(screen.getAllByText(/reading page 4 of 12/i)).toHaveLength(1);
  },
  12000,
);

test("selecting 10-K Filing switches subheading and caption copy", async () => {
  renderPage();
  await userEvent.click(screen.getByRole("tab", { name: /10-k filing/i }));
  expect(screen.getByText(/pull its latest 10-K straight from SEC EDGAR/i)).toBeInTheDocument();
  expect(screen.getByText(/10-k filings only/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /analyze this filing/i })).toBeInTheDocument();
});

test("the 10-K tab offers EDGAR lookup as the primary path, with PDF upload as a fallback", async () => {
  renderPage();
  await userEvent.click(screen.getByRole("tab", { name: /10-k filing/i }));

  expect(screen.getByRole("combobox", { name: /company ticker/i })).toBeInTheDocument();
  // Disabled until a company is chosen — there is nothing to analyze without one.
  expect(screen.getByRole("button", { name: /analyze the latest 10-k/i })).toBeDisabled();
  expect(screen.getByText(/or upload a PDF/i)).toBeInTheDocument();
});

test("choosing a company from the ticker search starts an EDGAR analysis for it", async () => {
  vi.mocked(apiClient.searchCompanies).mockResolvedValue([
    { cik: "0000320193", ticker: "AAPL", name: "Apple Inc." },
  ]);
  vi.mocked(apiClient.analyzeTicker).mockImplementation(() => new Promise(() => {}));

  renderPage();
  await userEvent.click(screen.getByRole("tab", { name: /10-k filing/i }));
  await userEvent.type(screen.getByRole("combobox", { name: /company ticker/i }), "aapl");

  await userEvent.click(await screen.findByRole("option", { name: /apple inc/i }));
  await userEvent.click(screen.getByRole("button", { name: /analyze AAPL's latest 10-K/i }));

  expect(apiClient.analyzeTicker).toHaveBeenCalledWith("AAPL");
  expect(await screen.findByText(/fetching the filing from edgar/i)).toBeInTheDocument();
});

test("selecting 10-K Filing forwards documentType to getUploadUrl", async () => {
  vi.mocked(apiClient.getUploadUrl).mockResolvedValue({
    presignedUrl: "http://s3.example.com/upload",
    s3Key: "filings/x.pdf",
  });
  vi.mocked(apiClient.uploadPdfToS3).mockResolvedValue(undefined);
  vi.mocked(apiClient.analyzeLease).mockImplementation(() => new Promise(() => {}));

  renderPage();
  await userEvent.click(screen.getByRole("tab", { name: /10-k filing/i }));
  await userEvent.upload(screen.getByTestId("file-input"), PDF_FILE);
  await userEvent.click(screen.getByRole("button", { name: /analyze this filing/i }));
  expect(apiClient.getUploadUrl).toHaveBeenCalledWith("filing");
});
