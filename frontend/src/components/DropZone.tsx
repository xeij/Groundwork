import { useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";

const MAX_BYTES = 20 * 1024 * 1024;

interface Props {
  onFile: (file: File | null) => void;
  captionLabel?: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function PdfIcon() {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" fill="none" aria-hidden="true">
      <path
        d="M8 2h13l6 6v22a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"
        fill="var(--surface-raised)"
        stroke="var(--border-strong)"
        strokeWidth="1.2"
      />
      <path d="M21 2v6h6" fill="none" stroke="var(--border-strong)" strokeWidth="1.2" strokeLinejoin="round" />
      <text x="17" y="24" textAnchor="middle" fontSize="8.5" fontWeight="700" fill="var(--accent)" fontFamily="var(--font-sans)">
        PDF
      </text>
    </svg>
  );
}

export function DropZone({ onFile, captionLabel = "Lease documents only" }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function validate(file: File): string | null {
    if (file.type !== "application/pdf") return "Please upload a PDF file.";
    if (file.size > MAX_BYTES) return "File must be under 20MB.";
    return null;
  }

  function handleFile(file: File) {
    const err = validate(file);
    if (err) {
      setError(err);
      setSelected(null);
      onFile(null);
      return;
    }
    setError(null);
    setSelected(file);
    onFile(file);
  }

  function clearFile(e?: React.MouseEvent) {
    e?.stopPropagation();
    setSelected(null);
    setError(null);
    onFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  if (selected) {
    return (
      <div className="card file-chip" style={{ padding: "1rem 1.1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.9rem" }}>
          <PdfIcon />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                color: "var(--text-primary)",
                fontWeight: 600,
                fontSize: "0.92rem",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={selected.name}
            >
              {selected.name}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.2rem" }}>
              <svg width="13" height="13" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <circle cx="10" cy="10" r="9" fill="var(--green-wash)" />
                <path d="M6 10.2l2.6 2.6L14.5 7" stroke="var(--green)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />
              </svg>
              <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>
                Ready to analyze &middot; {formatSize(selected.size)}
              </span>
            </div>
          </div>
          <button
            onClick={clearFile}
            aria-label="Remove file"
            className="btn-ghost"
            style={{
              width: 30,
              height: 30,
              borderRadius: "var(--radius-sm)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              padding: 0,
            }}
          >
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      onDrop={onDrop}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onClick={() => inputRef.current?.click()}
      className={`dropzone${dragging ? " dragging" : ""}`}
      style={{ padding: "2.5rem 2rem", textAlign: "center", cursor: "pointer" }}
    >
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none" style={{ marginBottom: "0.85rem" }} aria-hidden="true">
        <path
          d="M12 15V4M12 4L8 8M12 4l4 4"
          stroke="var(--text-tertiary)"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"
          stroke="var(--text-tertiary)"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <p style={{ margin: "0 0 0.35rem", color: "var(--text-primary)", fontWeight: 500, fontSize: "0.95rem" }}>
        Drag &amp; drop your PDF here, or click to select
      </p>
      <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--text-secondary)" }}>
        {captionLabel} &middot; max size 20 megabytes
      </p>
      {error && <p style={{ color: "var(--red)", margin: "0.85rem 0 0", fontSize: "0.85rem" }}>{error}</p>}
      <input
        ref={inputRef}
        data-testid="file-input"
        type="file"
        accept="application/pdf"
        style={{ display: "none" }}
        onChange={onChange}
      />
    </div>
  );
}
