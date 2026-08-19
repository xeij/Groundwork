import type { Severity } from "../types";
import { Badge } from "./ui/badge";

const CONFIG: Record<Severity, { label: string; variant: "destructive" | "warning" | "secondary" }> = {
  red: { label: "Watch out", variant: "destructive" },
  yellow: { label: "Worth asking", variant: "warning" },
  green: { label: "All clear", variant: "secondary" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { label, variant } = CONFIG[severity];
  return <Badge variant={variant}>{label}</Badge>;
}
