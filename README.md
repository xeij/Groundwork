# Groundwork

Dense documents hide the details that matter most, and most people don't have time to read the whole thing carefully. Groundwork gives you back a structured, plain-English breakdown of the parts worth paying attention to — every finding traceable to the exact text it came from.

Two document types are supported today:

- **Residential leases** — auto-renewal clauses, deposit conditions, unusual fees, and missing standard protections. Upload a PDF; each finding includes the exact quote from your lease and a specific thing you can ask the landlord to change.
- **10-K annual reports** — type a ticker and Groundwork pulls the latest 10-K straight from SEC EDGAR.

## What the 10-K analysis actually tells you

A summary of one filing is worth little: anything it says, a careful reader could get by reading the document. The value is in what a single document *cannot* tell you, which is where the enrichments below come from. All of them are built on free, unauthenticated SEC endpoints.

- **Year over year — what changed.** Companies copy-paste risk factors between filings, so the signal is entirely in the delta. Item 1A is aligned factor-by-factor against last year's 10-K and each one classified as carried over, reworded, **added**, or **dropped**, with a word-level redline for rewordings. Deletions are the highest-value finding here and the hardest to catch by hand — nobody notices the paragraph that is no longer there.
- **Arithmetic the filing does not do for you.** Financials come from the company's own XBRL tags via `data.sec.gov`, not from a model reading numbers off a page. On top of that sit ~31 derived ratios — margins, returns on assets, equity and invested capital, working-capital days, leverage, the Rule of 40, cash runway at the current burn — and six published earnings-quality screens: Beneish M-score, Altman Z'-score, Zmijewski's distress probability, Piotroski F-score, Montier's C-score and the Sloan accrual ratio, plus a Benford first-digit test over every dollar figure the company has ever tagged. Divergence flags catch relationships that should track each other and stopped: revenue against receivables, profit against operating cash flow, debt against EBITDA, sales against the deferred revenue that funds them, and profit growth against the tax rate that flattered it.
- **How it ranks against its peers.** The SIC industry cohort is pulled from EDGAR, each peer's XBRL fetched concurrently, and every comparable metric percentile-ranked. "Days sales outstanding rose 19 days and is now 4th worst of 11 listed peers" is a sentence that cannot be produced from one document.
- **What insiders did with their own shares.** Every officer and director trade is filed as Form 4 XML within two business days. The last twelve months are read directly from those filings: open-market buying against selling, cluster buys, how much of each insider's own position they sold, and how much of the selling ran through a 10b5-1 plan adopted months in advance. Grants, option exercises and shares withheld for tax are counted separately and kept out of every buy/sell figure — treating a pay package as a vote of confidence is the most common way this data gets misread.
- **How the company files, not just what it filed.** 8-K item codes are a machine-readable event log: Item 4.02 is the company telling the market its old numbers cannot be relied on, 4.01 is an auditor change, 5.02 is an officer leaving. Those are graded on their rate over three years, alongside late-filing notifications, amended annual reports, recent name changes, and the gap between fiscal year end and filing date measured against both the statutory deadline and the company's own norm — an audit that takes three weeks longer than usual is the cheapest early warning in the dataset.
- **The document as an object.** Risk-factor count and section lengths against last year, sentence length and Fog index, uncertainty-word density against last year's filing, and a set of tripwire phrases — going-concern doubt, material weakness, restatement, subpoena, covenant default — each reported with the sentence it fired on. Conditional uses are separated from statements of fact, because Item 1A is written almost entirely in the voice of things that *might* happen.
- **Verification instead of self-reported confidence.** Every quote is mechanically matched back against the section it claims to come from, and findings whose quote is not in the filing are discarded rather than shown. The badge reports a check that was run, not the model's opinion of how sure it is.

Every one of these is best-effort and degrades independently: a company with no prior 10-K still gets financials and screens, a thin industry cohort still gets the year-over-year diff. A partial analysis is far more useful than a failed one.

## How it works

### The EDGAR path (10-K by ticker)

1. **Resolve the company.** `GET /companies?q=` searches every SEC filer with a listed ticker; `POST /analyze-ticker` resolves the symbol up front so an unknown ticker fails immediately rather than becoming a `failed` record the user has to poll for. The job is written to DynamoDB as `pending` and the Lambda re-invokes itself asynchronously, sidestepping API Gateway's 30-second limit.
2. **Fetch and segment.** The filing's HTML is pulled from EDGAR and carved into its numbered Items (`filing_sections.py`). Working from HTML rather than a rendered PDF is what makes whole-filing analysis possible — in practice 95–98% of the filing text lands inside an identified section, including the notes at the back.
3. **Fan out.** Four branches run concurrently: the six categories against the Items that actually govern them, the year-over-year diff against last year's filing, the XBRL/peer branch against `data.sec.gov`, and the insider branch against the company's Form 4s. The narrative branch talks only to Claude and the data branches only to the SEC, so they overlap almost entirely. The filing track record and the document measurements are then computed with no further requests at all — the first reads the submissions index that was already downloaded to find the filing, the second reads the two years of section text the diff branch already extracted.
4. **Verify, then summarize.** Every finding's quote is exact-matched against its source section; rejected findings are dropped. A short reduce pass writes the overview from the category results, the financial history and the screens.
5. **Poll for the result.** The frontend polls `GET /summary/{id}`, rendering the real pipeline stage the backend reports at each step.

### The upload path (lease, or a 10-K PDF)

1. **Pick a document type and upload.** The frontend requests a presigned S3 URL (`POST /upload?documentType=lease|filing`), then PUTs the PDF directly to S3. The key encodes the type — `leases/{uuid}.pdf` or `filings/{uuid}.pdf` — which is the single source of truth for how the document is processed downstream.
2. **Kick off analysis.** `POST /analyze` writes a `pending` record and re-invokes the Lambda asynchronously, returning a summary ID immediately.
3. **Extract, analyze, store.** Text is extracted page-by-page with pdfplumber and sent to Claude with a prompt specific to the document type. The result is parsed into a typed schema before being saved, retried once with a stricter prompt on malformed JSON or a missing citation, and kept for 90 days. The PDF is deleted from S3 as soon as analysis completes.

A PDF-uploaded 10-K gets the category findings only. The year-over-year comparison, peer ranking, XBRL cross-check, insider activity and filing track record all require the filing history that only the EDGAR path has.

### Section-aware analysis

Each category is analyzed against only the Items that govern it — Risk Factors against Item 1A, Legal Proceedings against Item 3 plus the contingencies note, Accounting Policy Changes against the Item 8 notes — rather than against a single truncated blob. Item 8 runs to 60k+ characters and is mostly boilerplate schedules, so where a category draws on it the relevant passages are excerpted by keyword rather than by clipping the front. The per-Item budget is split so a large Item 8 cannot crowd out a small Item 3.

This replaced a single call that clipped the filing to a fixed character budget taken from the front of the document, which meant nothing past roughly Item 7 — including the notes, where the substantive disclosures live — ever reached the model.

### Timing and timeouts

An EDGAR analysis is a genuinely slow request: six category calls, a year-over-year diff, a dozen 4MB peer XBRL fetches and up to sixty Form 4s. Four numbers are deliberately kept in sync so a slow-but-healthy analysis is never mistaken for a hang:

- Each Claude call runs under its own wall-clock budget (`CATEGORY_BUDGET_SECONDS` / `OVERVIEW_BUDGET_SECONDS` in `filing_analysis.py`, `DIFF_CLAUDE_BUDGET_SECONDS` in `section_diff.py`). The SDK's retry-on-timeout is disabled per call (`max_retries=0`) since it would otherwise multiply wall-clock time past the budget the code is tracking.
- Category calls fan out with a capped worker count rather than all six at once — six simultaneous long-context requests is enough to trip rate limits on smaller accounts.
- The SEC-side branches carry their own wall-clock budgets (`PEER_BUDGET_SECONDS`, `INSIDER_BUDGET_SECONDS` in `filing_pipeline.py`), both set below the category fan-out they run alongside. Neither is on the critical path unless Claude finishes first, and both return whatever completed in time rather than failing.
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

### Insider activity

Section 16 requires officers, directors and 10% owners to report each trade on a Form 4 within two business days, and EDGAR serves those filings as XML. `insider_activity.py` reads the last twelve months of them, with the twelve months before that as a baseline.

The whole module turns on one distinction: **only transaction codes P and S are decisions.** A purchase or an open-market sale is somebody moving their own money. An award (A) is pay, an option exercise (M) is a deadline, and shares withheld to cover the tax on a vest (F) are arithmetic. Counting grants as "insider buying" is the single most common way this dataset gets misreported, so those codes are tallied separately and kept out of every buy/sell figure. Derivative transactions are parsed but excluded for the same reason — when the shares from an exercise are actually sold, that sale already appears as an ordinary S in the non-derivative table, and counting both would double it.

Two further judgements are built in:

- **Selling is weak evidence and buying is strong.** Insiders sell for tuition and diversification; they buy for one reason. So cluster buying — three or more insiders buying independently within 90 days — is graded on its own rather than being netted into an aggregate, and 10b5-1 plan sales are identified (from the document-level checkbox and from footnotes referenced by the transaction) and reported as the weaker evidence they are, since the plan was adopted months before the sale.
- **Scale only means something relative to the holder.** A $2m sale is noise from a founder and everything from a division president, so selling is measured against the shares that insider still holds afterwards, never in absolute dollars.

Form 4s are fetched concurrently under the same wall-clock budget and throttle discipline as peer XBRL, and the number actually read is reported alongside the totals: a partially read record is presented as a floor, never as a tally.

### The filing track record

Everything in `filing_history.py` comes from the submissions index the pipeline has already downloaded, so it costs nothing and cannot fail independently of the fetch that found the filing.

8-K item codes make this possible. Every 8-K declares which numbered item triggered it, so the events that matter are already tagged and need no reading: **4.02** (previously issued financials should no longer be relied upon — a self-reported restatement, and the strongest reporting-quality signal in the vocabulary), **4.01** (auditor change), **2.06** (material impairment), **3.01** (delisting notice), **2.04** (an event accelerating a debt obligation), **1.03** (bankruptcy), **5.02** (officer and director departures), **5.03** (a changed fiscal year, which breaks the comparability of everything else on the page). Routine items — 2.02 earnings releases, 7.01 Reg FD, 9.01 exhibits — fire constantly and are ignored.

Two rules keep the output honest:

- **Rate, not instance.** One Item 5.02 is a director retiring; six in three years is churn in the people who sign these filings. Repeats are grouped into a single event and graded on their frequency rather than listed one row per filing.
- **The window that was actually searched travels with the findings.** EDGAR's `recent` block caps at roughly the last thousand filings, and a company that files hundreds of ownership forms a year can exhaust that inside a three-year window. When that happens the card says how far back the index reached, because a truncated record read as a clean one is worse than no record.

Alongside the events sits the filing lag: days from fiscal year end to filing, for every 10-K in the window. It is compared against two different things — the statutory deadline for the filer's own category (60/75/90 days, taken from EDGAR's `category` field) and the company's own recent norm. Missing the deadline is a legal fact. Taking three weeks longer than usual while still making it is the quieter signal, and the one worth having.

### Measuring the document

`text_metrics.py` computes what can be counted without a model: risk-factor blocks and section lengths against last year, sentence length, uncertainty-word density, and a list of tripwire phrases.

Two decisions are worth calling out.

**Readability is reported as two numbers, not one.** The Fog index is what the disclosure literature standardised on, but Loughran and McDonald showed in 2014 that its complex-word half misfires on filings: business English is full of long words every reader of a 10-K already knows — "corporation", "regulatory", "amortization" — so a filing scores as impenetrable for using its own vocabulary. Words per sentence is the half that survives the critique, so both are shown and the verdict rests on sentence length.

**Hypothetical mentions are separated from statements of fact.** Item 1A is written almost entirely in the conditional: "if we identify a material weakness, investors could lose confidence" is boilerplate present in thousands of filings, and reporting it as a material weakness would make the feature worthless. Every tripwire match is classified by whether its sentence carries conditional language, only statements of fact are surfaced, and the conditional count is reported separately rather than merged in — the same distinction the diff already draws between "omitted for space" and "the quote was fabricated".

Every tripwire finding carries the sentence it fired on and the Item it came from, so nothing here has to be taken on trust.

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
- **Insider holdings are read off the Form 4s themselves**, which report only the securities on each form. Shares held through a trust or another form of indirect ownership that has not traded in the window are not counted, so "sold 60% of their position" means 60% of the position visible in the filings.
- **The Benford digit test is never graded worse than yellow.** A filer with few distinct figures, heavy rounding, or a lot of bounded quantities can fail a first-digit test while doing nothing wrong. It is evidence that a distribution looks unusual, never evidence about the company, and the interpretation says so on the card.
- **Ohlson's O-score is deliberately not implemented.** Its first term is total assets deflated by a GNP price-level index, which is not in XBRL; substituting a raw log would produce a number that looks like an O-score and is not one. Zmijewski's model needs no such substitution and is used instead.
- **Montier's C-score makes two documented substitutions**, both forced by what filers tag: "other current assets" is backed out of current assets less cash, receivables and inventory, and the depreciation trait is measured against net rather than gross PP&E. Both appear in the score's components.
- **The 8-K event log only sees what item codes declare.** A company that discloses something significant under Item 8.01 ("Other Events") is invisible to this feature, which is why it sits next to the narrative analysis rather than replacing it.
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
- SEC EDGAR (`data.sec.gov`, `www.sec.gov`) — filing history, filing documents, XBRL company facts, Section 16 ownership forms, and the SIC industry index. Free and unauthenticated, but see the `User-Agent` note below.
- No new Python dependencies — HTML parsing, XML parsing, diffing and fuzzy matching are all standard library, since dependencies are vendored into `backend/dependencies/` and committed
