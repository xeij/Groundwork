import type { UploadUrlResponse, AnalyzeResponse, SummaryRecord, DocumentType } from "../types";
import { ApiError } from "../types";

const API_URL = import.meta.env.VITE_API_URL ?? "";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new ApiError(res.status, (body as { detail?: string }).detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

export async function getUploadUrl(documentType: DocumentType = "lease"): Promise<UploadUrlResponse> {
  const res = await fetch(`${API_URL}/upload?documentType=${documentType}`, { method: "POST" });
  return handleResponse<UploadUrlResponse>(res);
}

export async function uploadPdfToS3(presignedUrl: string, file: File): Promise<void> {
  const res = await fetch(presignedUrl, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": "application/pdf" },
  });
  if (!res.ok) throw new ApiError(res.status, "Failed to upload file to storage");
}

export async function analyzeLease(s3Key: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_URL}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ s3Key }),
  });
  return handleResponse<AnalyzeResponse>(res);
}

export async function getSummary(summaryId: string): Promise<SummaryRecord> {
  const res = await fetch(`${API_URL}/summary/${summaryId}`);
  if (res.status === 202) throw new ApiError(202, "pending");
  return handleResponse<SummaryRecord>(res);
}
