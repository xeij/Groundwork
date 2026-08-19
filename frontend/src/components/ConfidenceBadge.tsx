import type { Confidence } from "../types";
import { Badge } from "./ui/badge";

const CONFIG: Record<Confidence, { label: string; variant: "success" | "warning" | "destructive" }> = {
  high: { label: "High confidence", variant: "success" },
  medium: { label: "Medium confidence", variant: "warning" },
  low: { label: "Low confidence", variant: "destructive" },
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const { label, variant } = CONFIG[confidence];
  return <Badge variant={variant}>{label}</Badge>;
}
