import { useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";

const MAX_BYTES = 20 * 1024 * 1024;

interface Props {
  onFile: (file: File) => void;
  captionLabel?: string;
}

export function DropZone({ onFile, captionLabel = "Lease documents only" }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
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
      return;
    }
    setError(null);
    onFile(file);
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

  return (
    <div
      onDrop={onDrop}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onClick={() => inputRef.current?.click()}
      style={{
        border: `2px dashed ${dragging ? "#58a6ff" : "#30363d"}`,
        borderRadius: 10,
        padding: "2.25rem 2rem",
        textAlign: "center",
        cursor: "pointer",
        background: dragging ? "rgba(88,166,255,0.05)" : "#161b22",
        transition: "border-color 0.15s, background 0.15s",
      }}
    >
      <div style={{ fontSize: "2rem", marginBottom: "0.75rem", opacity: 0.5 }}>&#128196;</div>
      <p style={{ margin: "0 0 0.35rem", color: "#e6edf3", fontWeight: 500 }}>
        Drag &amp; drop your PDF here, or click to select
      </p>
      <p style={{ margin: 0, fontSize: "0.875rem", color: "#8b949e" }}>
        {captionLabel} &middot; max size 20 megabytes
      </p>
      {error && <p style={{ color: "#f85149", marginTop: "0.75rem", margin: "0.75rem 0 0", fontSize: "0.875rem" }}>{error}</p>}
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
