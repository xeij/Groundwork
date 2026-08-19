# Groundwork

Dense documents hide the details that matter most, and most people don't have time to read the whole thing carefully. Groundwork gives you back a structured, plain-English breakdown of the parts worth paying attention to — every finding traceable to the exact text it came from.

Two document types are supported today:

- **Residential leases** — auto-renewal clauses, deposit conditions, unusual fees, and missing standard protections. Upload a PDF; each finding includes the exact quote from your lease and a specific thing you can ask the landlord to change.
- **10-K annual reports** — type a ticker and Groundwork pulls the latest 10-K straight from SEC EDGAR.

## What the 10-K analysis actually tells you

A summary of one filing is worth little: anything it says, a careful reader could get by reading the document. The value is in what a single document *cannot* tell you, which is where the four enrichments below come from. All of them are built on free, unauthenticated SEC endpoints.

- **Year over year — what changed.** Companies copy-paste risk factors between filings, so the signal is entirely in the delta. Item 1A is aligned factor-by-factor against last year's 10-K and each one classified as carried over, reworded, **added**, or **dropped**, with a word-level redline for rewordings. Deletions are the highest-value finding here and the hardest to catch by hand — nobody notices the paragraph that is no longer there.
- **Arithmetic the filing does not do for you.** Financials come from the company's own XBRL tags via `data.sec.gov`, not from a model reading numbers off a page. On top of that sit ~19 derived ratios and four published earnings-quality screens — Beneish M-score, Altman Z'-score, Piotroski F-score and the Sloan accrual ratio — plus divergence flags for relationships that should track each other and stopped (revenue against receivables, profit against operating cash flow, debt against EBITDA).
- **How it ranks against its peers.** The SIC industry cohort is pulled from EDGAR, each peer's XBRL fetched concurrently, and every comparable metric percentile-ranked. "Days sales outstanding rose 19 days and is now 4th worst of 11 listed peers" is a sentence that cannot be produced from one document.
- **Verification instead of self-reported confidence.** Every quote is mechanically matched back against the section it claims to come from, and findings whose quote is not in the filing are discarded rather than shown. The badge reports a check that was run, not the model's opinion of how sure it is.

Every one of these is best-effort and degrades independently: a company with no prior 10-K still gets financials and screens, a thin industry cohort still gets the year-over-year diff. A partial analysis is far more useful than a failed one.

## How it works

### The EDGAR path (10-K by ticker)

1. **Resolve the company.** `GET /companies?q=` searches every SEC filer with a listed ticker; `POST /analyze-ticker` resolves the symbol up front so an unknown ticker fails immediately rather than becoming a `failed` record the user has to poll for. The job is written to DynamoDB as `pending` and the Lambda re-invokes itself asynchronously, sidestepping API Gateway's 30-second limit.
2. **Fetch and segment.** The filing's HTML is pulled from EDGAR and carved into its numbered Items (`filing_sections.py`). Working from HTML rather than a rendered PDF is what makes whole-filing analysis possible — in practice 95–98% of the filing text lands inside an identified section, including the notes at the back.
3. **Fan out.** Three branches run concurrently: the six categories against the Items that actually govern them, the year-over-year diff against last year's filing, and the XBRL/peer branch against `data.sec.gov`. The narrative branch talks only to Claude and the data branch only to the SEC, so they overlap almost entirely.
4. **Verify, then summarize.** Every finding's quote is exact-matched against its source section; rejected findings are dropped. A short reduce pass writes the overview from the category results, the financial history and the screens.
5. **Poll for the result.** The frontend polls `GET /summary/{id}`, rendering the real pipeline stage the backend reports at each step.

### The upload path (lease, or a 10-K PDF)

1. **Pick a document type and upload.** The frontend requests a presigned S3 URL (`POST /upload?documentType=lease|filing`), then PUTs the PDF directly to S3. The key encodes the type — `leases/{uuid}.pdf` or `filings/{uuid}.pdf` — which is the single source of truth for how the document is processed downstream.
2. **Kick off analysis.** `POST /analyze` writes a `pending` record and re-invokes the Lambda asynchronously, returning a summary ID immediately.
3. **Extract, analyze, store.** Text is extracted page-by-page with pdfplumber and sent to Claude with a prompt specific to the document type. The result is parsed into a typed schema before being saved, retried once with a stricter prompt on malformed JSON or a missing citation, and kept for 90 days. The PDF is deleted from S3 as soon as analysis completes.

A PDF-uploaded 10-K gets the category findings only. The year-over-year comparison, peer ranking and XBRL cross-check all require the filing history that only the EDGAR path has.

### Section-aware analysis

Each category is analyzed against only the Items that govern it — Risk Factors against Item 1A, Legal Proceedings against Item 3 plus the contingencies note, Accounting Policy Changes against the Item 8 notes — rather than against a single truncated blob. Item 8 runs to 60k+ characters and is mostly boilerplate schedules, so where a category draws on it the relevant passages are excerpted by keyword rather than by clipping the front. The per-Item budget is split so a large Item 8 cannot crowd out a small Item 3.

This replaced a single call that clipped the filing to a fixed character budget taken from the front of the document, which meant nothing past roughly Item 7 — including the notes, where the substantive disclosures live — ever reached the model.

### Timing and timeouts

An EDGAR analysis is a genuinely slow request: six category calls, a year-over-year diff and a dozen 4MB peer XBRL fetches. Four numbers are deliberately kept in sync so a slow-but-healthy analysis is never mistaken for a hang:

- Each Claude call runs under its own wall-clock budget (`CATEGORY_BUDGET_SECONDS` / `OVERVIEW_BUDGET_SECONDS` in `filing_analysis.py`, `DIFF_CLAUDE_BUDGET_SECONDS` in `section_diff.py`). The SDK's retry-on-timeout is disabled per call (`max_retries=0`) since it would otherwise multiply wall-clock time past the budget the code is tracking.
- Category calls fan out with a capped worker count rather than all six at once — six simultaneous long-context requests is enough to trip rate limits on smaller accounts.
- The Lambda's own timeout (`template.yaml`) sits above the sum of those budgets, with headroom for EDGAR fetches and the DynamoDB write.
- The frontend's polling window (`useDocumentAnalysis.ts`) sits above *that*, so it never gives up while the backend is still legitimately working.

If these drift apart — e.g. a Claude budget is raised without raising the Lambda timeout or the poll window — a healthy-but-slow analysis either gets hard-killed mid-flight or appears to fail, producing a confusing "taking longer than expected" error when nothing is broken.

### Storing the results

DynamoDB's resource client rejects Python floats outright, and an analysis carries a lot of them — ratios, forensic scores, similarity, percentiles. `summary_store.py` converts floats to `Decimal` on write and back on read in one place rather than at every producer; NaN and infinity have no DynamoDB representation and are dropped to null rather than failing a whole analysis.

### Citation grounding and verification

Mandatory citation is enforced in the data model, not just in prompt wording: a financial finding without a citation fails schema validation and triggers a retry with a stricter prompt.

On top of that, every quote is now **checked**. `verification.py` matches each quote against the source section through a normalize-then-match ladder and reports which rung it landed on: an exact match, a match after Unicode/typography/whitespace folding (models routinely swap curly quotes and em dashes — that is not fabrication), or a fuzzy match above a similarity floor, which is surfaced as a paraphrase rather than a quote. Anything below the floor is a fabrication and the finding is discarded. Searching a 250k-character section is anchored on rare tokens from the quote rather than sliding a window over every offset, so it stays fast.

The year-over-year diff enforces the same rule in code: a change whose supporting quote is not found in the relevant filing text is dropped, and the count is reported separately from changes omitted for space — "we ran out of room" and "we caught the model making something up" are different claims and are never merged into one number.

The stored `confidence` field is retained so summaries written before verification existed still load, but new analyses render the verification result instead.

### The SEC User-Agent requirement

EDGAR rejects requests whose `User-Agent` does not carry a contact address. The two hosts enforce this differently, verified by probing them:

| `User-Agent` | `data.sec.gov` | `www.sec.gov` |
| --- | --- | --- |
| absent, or a library default (`python-requests/…`, curl) | 403 | 403 |
| a descriptive name with no address (`Groundwork/1.0`) | 200 | 403 |
| anything containing an email address | 200 | 200 |

`www.sec.gov` is the strict one and it serves the filing documents themselves, so an address is not optional — without one the analysis fails at the fetch step.

What EDGAR does *not* do is check that the address is real: `nobody@nowhere.invalid` is accepted. The reason to set `SecUserAgent` to a genuine address anyway is the SEC's stated access policy — it is how they reach you rather than blocking you if your traffic pattern looks abusive. The shipped default is a placeholder that works technically; replace it before running this at any volume.

### Known limitations

- **The year-over-year diff covers Item 1A only.** MD&A was tried and removed: once its inline financial tables are flattened to text, most of the "changes" it yields are this year's numbers differing from last year's — noise that buries the risk-factor findings, and worse than what the XBRL history already shows. Re-adding it needs a table-aware extractor, not a different diff threshold.
- **Forensic screens return nothing rather than something partial.** A Beneish score computed with two of its eight variables silently zeroed still looks like a Beneish score to a reader, so a screen missing any required input is omitted entirely.
- **Altman is the Z'-score**, the private-firm variant, because XBRL carries no market capitalization. Its coefficients and cut-offs are not interchangeable with the classic market-value Z.
- **Peer cohorts are SIC-based**, which is a coarse industry taxonomy, and only filers with a listed ticker and usable XBRL are included. Below a minimum cohort size no percentile is reported at all rather than a statistically meaningless one.
- **A PDF-uploaded filing gets no enrichments** — see the two paths above.

### Stock price chart

When Claude can extract a trading symbol from a 10-K's cover page (`keyMetrics.tickerSymbol`), the filing results view shows a small YTD closing-price chart for that ticker. `GET /stock-chart/{ticker}` proxies a public, no-key-required market data feed (Yahoo Finance's chart endpoint) server-side — this sidesteps the CORS restrictions that block that feed from being called directly from a browser, and keeps the frontend's data shape stable even if the upstream source is swapped later. This endpoint has no SLA or authentication of its own; if it's unavailable or the ticker has no data, the chart quietly reports itself unavailable rather than breaking the rest of the results page.

## Tech stack

- React, TypeScript, Vite — frontend
- Python, FastAPI, Mangum — backend
- AWS Lambda, API Gateway, S3, DynamoDB — infrastructure
- AWS SAM — deployment
- AWS Amplify — frontend hosting
- Anthropic Claude API — lease and financial filing analysis
- pdfplumber — PDF text extraction
- SEC EDGAR (`data.sec.gov`, `www.sec.gov`) — filing history, filing documents, XBRL company facts, and the SIC industry index. Free and unauthenticated, but see the `User-Agent` note below.
- No new Python dependencies — HTML parsing, diffing and fuzzy matching are all standard library, since dependencies are vendored into `backend/dependencies/` and committed
