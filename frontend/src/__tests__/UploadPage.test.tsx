import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { UploadPage } from "../pages/UploadPage";
import * as apiClient from "../api/client";

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
  expect(await screen.findByText(/reading through/i)).toBeInTheDocument();
});

test("selecting 10-K Filing switches subheading and caption copy", async () => {
  renderPage();
  await userEvent.click(screen.getByRole("button", { name: /10-k filing/i }));
  expect(screen.getByText(/liquidity issues worth knowing/i)).toBeInTheDocument();
  expect(screen.getByText(/10-k filings only/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /analyze this filing/i })).toBeInTheDocument();
});

test("selecting 10-K Filing forwards documentType to getUploadUrl", async () => {
  vi.mocked(apiClient.getUploadUrl).mockResolvedValue({
    presignedUrl: "http://s3.example.com/upload",
    s3Key: "filings/x.pdf",
  });
  vi.mocked(apiClient.uploadPdfToS3).mockResolvedValue(undefined);
  vi.mocked(apiClient.analyzeLease).mockImplementation(() => new Promise(() => {}));

  renderPage();
  await userEvent.click(screen.getByRole("button", { name: /10-k filing/i }));
  await userEvent.upload(screen.getByTestId("file-input"), PDF_FILE);
  await userEvent.click(screen.getByRole("button", { name: /analyze this filing/i }));
  expect(apiClient.getUploadUrl).toHaveBeenCalledWith("filing");
});
