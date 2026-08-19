import { useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./ui/card";
import { Button } from "./ui/button";

const MAX_BYTES = 20 * 1024 * 1024;

interface Props {
  onFile: (file: File | null) => void;
  captionLabel?: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
      <Card className="p-4">
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground" title={selected.name}>
              {selected.name}
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              Ready to analyze &middot; {formatSize(selected.size)}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={clearFile} aria-label="Remove file">
            Remove
          </Button>
        </div>
      </Card>
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
      className={cn(
        "cursor-pointer rounded-lg border-2 border-dashed border-input bg-card px-8 py-10 text-center transition-colors hover:border-muted-foreground",
        dragging && "border-foreground bg-secondary",
      )}
    >
      <p className="mb-1 text-sm font-medium text-foreground">Drag &amp; drop your PDF here, or click to select</p>
      <p className="text-sm text-muted-foreground">{captionLabel} &middot; max size 20 megabytes</p>
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      <input
        ref={inputRef}
        data-testid="file-input"
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={onChange}
      />
    </div>
  );
}
