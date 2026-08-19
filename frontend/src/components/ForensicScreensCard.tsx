import { useState } from "react";
import type { DivergenceFlag, ForensicScreen } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

function Components({ components }: { components: Record<string, number | null> }) {
  const entries = Object.entries(components).filter(([, v]) => v != null);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-4 gap-y-1.5 rounded border border-border bg-background px-3 py-2.5">
      {entries.map(([name, value]) => (
        <div key={name} className="flex items-baseline justify-between gap-2">
          <dt className="truncate text-xs text-muted-foreground">{name}</dt>
          <dd className="font-mono text-xs text-foreground">{(value as number).toFixed(4)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ScreenItem({ screen }: { screen: ForensicScreen }) {
  const [open, setOpen] = useState(false);
  const hasComponents = !!screen.components && Object.keys(screen.components).length > 0;

  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2.5">
          <span className="text-sm font-semibold text-foreground">{screen.label}</span>
          {screen.value != null && (
            <span className="font-mono text-sm text-foreground">{screen.value}</span>
          )}
        </div>
        <SeverityBadge severity={screen.severity} />
      </div>

      <p className="text-sm leading-relaxed text-muted-foreground">{screen.interpretation}</p>

      {screen.basis && <p className="mt-1 text-xs text-muted-foreground">Based on {screen.basis}</p>}

      {hasComponents && (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-1.5 text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            {open ? "Hide" : "Show"} the inputs
          </button>
          {open && <Components components={screen.components!} />}
        </>
      )}
    </div>
  );
}

interface Props {
  screens: ForensicScreen[];
  flags: DivergenceFlag[];
}

export function ForensicScreensCard({ screens, flags }: Props) {
  if (screens.length === 0 && flags.length === 0) return null;

  return (
    <div className="space-y-3">
      {flags.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Divergences worth a look</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {flags.map((flag) => (
              <div key={flag.key} className="border-b border-border pb-4 last:border-b-0 last:pb-0">
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-foreground">{flag.label}</span>
                  <SeverityBadge severity={flag.severity} />
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">{flag.interpretation}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {screens.length > 0 && (
        <Card>
          <CardHeader className="flex-col items-start gap-1">
            <CardTitle>Earnings-quality screens</CardTitle>
            <span className="text-xs text-muted-foreground">
              Computed from the company's own tagged XBRL data, not from the narrative
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            {screens.map((screen) => (
              <ScreenItem key={screen.key} screen={screen} />
            ))}
            <p className="text-xs leading-relaxed text-muted-foreground">
              These are published screens, not verdicts. They flag profiles worth reading the
              footnotes for; false positives are common among fast-growing and capital-intensive
              companies.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
