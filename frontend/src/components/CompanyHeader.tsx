import type { CompanyProfile } from "../types";
import { Card, CardContent } from "./ui/card";

export function CompanyHeader({ company }: { company: CompanyProfile }) {
  const filed = company.filingDate ? new Date(company.filingDate + "T00:00:00Z") : null;

  return (
    <Card className="mb-3">
      <CardContent className="py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              {company.name}
              {company.ticker && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  {company.ticker}
                </span>
              )}
            </h2>
            {company.sicDescription && (
              <p className="mt-0.5 text-xs text-muted-foreground">{company.sicDescription}</p>
            )}
          </div>
          <div className="text-right">
            {company.fiscalYear != null && (
              <p className="text-sm font-semibold text-foreground">FY{company.fiscalYear} 10-K</p>
            )}
            {filed && (
              <p className="text-xs text-muted-foreground">
                Filed{" "}
                {filed.toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                  timeZone: "UTC",
                })}
              </p>
            )}
          </div>
        </div>

        {company.filingUrl && (
          <a
            href={company.filingUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-2.5 inline-block text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Read the original filing on SEC EDGAR &rarr;
          </a>
        )}
      </CardContent>
    </Card>
  );
}
