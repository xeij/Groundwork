import type { SectionSize, TextMetrics, Tripwire } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { cn } from "@/lib/utils";

function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string | null;
}) {
  return (
    <div>
      <div className="mb-0.5 text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold text-foreground">{value}</div>
      {detail && <div className="text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

function signed(value: number, suffix = ""): string {
  return `${value > 0 ? "+" : ""}${value}${suffix}`;
}

function SectionLengths({ sections }: { sections: SectionSize[] }) {
  const measured = sections.filter((section) => section.changePercent != null).slice(0, 6);
  if (measured.length === 0) return null;
  const longest = Math.max(...measured.map((section) => section.words));

  return (
    <div className="space-y-1.5">
      {measured.map((section) => (
        <div key={section.item} className="flex items-center gap-2.5">
          <span className="w-14 shrink-0 text-xs text-muted-foreground">Item {section.item}</span>
          <div className="h-1.5 flex-1 rounded-full bg-secondary">
            <div
              className="h-1.5 rounded-full bg-muted-foreground/40"
              style={{ width: `${longest > 0 ? (section.words / longest) * 100 : 0}%` }}
            />
          </div>
          <span className="w-16 shrink-0 text-right font-mono text-xs text-foreground">
            {section.words.toLocaleString()}
          </span>
          <span
            className={cn(
              "w-14 shrink-0 text-right font-mono text-xs",
              section.notable ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {signed(Math.round(section.changePercent!), "%")}
          </span>
        </div>
      ))}
    </div>
  );
}

function TripwireItem({ tripwire }: { tripwire: Tripwire }) {
  return (
    <div className="border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">{tripwire.label}</span>
        <SeverityBadge severity={tripwire.severity} />
      </div>

      <p className="text-sm leading-relaxed text-muted-foreground">{tripwire.explanation}</p>

      <ul className="mt-2 space-y-2">
        {tripwire.occurrences.map((occurrence, i) => (
          <li key={i} className="border-l-2 border-border pl-3">
            <p className="text-sm leading-relaxed text-foreground italic">"{occurrence.quote}"</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{occurrence.section}</p>
          </li>
        ))}
      </ul>

      {tripwire.hypotheticalCount > 0 && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          The same phrase appears {tripwire.hypotheticalCount} more{" "}
          {tripwire.hypotheticalCount === 1 ? "time" : "times"} in conditional language ("if we
          were to…"), which is not counted as a disclosure.
        </p>
      )}
    </div>
  );
}

export function DocumentMetricsCard({ metrics }: { metrics: TextMetrics }) {
  const { riskFactors, readability, hedging, tripwires, sections } = metrics;
  const hasStats = !!riskFactors || !!readability || !!hedging;
  if (!hasStats && tripwires.length === 0) return null;

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-1">
        <CardTitle>The document itself</CardTitle>
        <span className="text-xs text-muted-foreground">
          Measured, not interpreted — every figure below is arithmetic over the filing text
        </span>
      </CardHeader>

      <CardContent className="space-y-5">
        {hasStats && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-4 gap-y-3">
            {riskFactors && (
              <Stat
                label="Risk factors"
                value={`${riskFactors.count}`}
                detail={
                  riskFactors.change != null
                    ? `${signed(riskFactors.change)} on last year`
                    : "no prior filing to compare"
                }
              />
            )}
            {riskFactors && (
              <Stat
                label="Risk section length"
                value={`${riskFactors.words.toLocaleString()} words`}
                detail={
                  riskFactors.wordChangePercent != null
                    ? `${signed(Math.round(riskFactors.wordChangePercent), "%")} on last year`
                    : null
                }
              />
            )}
            {readability && (
              <Stat
                label="Sentence length"
                value={`${readability.wordsPerSentence} words`}
                detail={`Fog index ${readability.fogIndex}`}
              />
            )}
            {hedging && (
              <Stat
                label="Hedging language"
                value={`${hedging.per1000} / 1,000 words`}
                detail={hedging.change != null ? `${signed(hedging.change)} on last year` : null}
              />
            )}
          </div>
        )}

        {readability && (
          <div>
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-foreground">How hard it is to read</span>
              <SeverityBadge severity={readability.severity} />
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{readability.interpretation}</p>
          </div>
        )}

        {hedging && (
          <div>
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-foreground">Uncertainty in the language</span>
              <SeverityBadge severity={hedging.severity} />
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{hedging.interpretation}</p>
            {hedging.topTerms.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                Most frequent:{" "}
                {hedging.topTerms.map((term) => `${term.term} (${term.count})`).join(", ")}
              </p>
            )}
          </div>
        )}

        {sections.some((section) => section.changePercent != null) && (
          <div>
            <p className="mb-2.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Section length
              <span className="ml-2 font-normal normal-case">(words, and change on last year)</span>
            </p>
            <SectionLengths sections={sections} />
          </div>
        )}

        {tripwires.length > 0 && (
          <div className="space-y-4 border-t border-border pt-4">
            <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Phrases that mean something specific
            </p>
            {tripwires.map((tripwire) => (
              <TripwireItem key={tripwire.key} tripwire={tripwire} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
