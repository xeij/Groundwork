# Groundwork

Dense documents hide the details that matter most, and most people don't have time to read the whole thing carefully. Groundwork lets you upload a PDF and get back a structured, plain-English breakdown of the parts worth paying attention to — every finding traceable back to the exact text it came from.

Two document types are supported today:

- **Residential leases** — auto-renewal clauses, deposit conditions, unusual fees, and missing standard protections. Each finding includes the exact quote from your lease and a specific thing you can ask the landlord to change.
- **10-K annual reports** — risk factors, financial performance (MD&A), liquidity and capital resources, related-party transactions, legal proceedings, and accounting policy changes. This is the analyst/compliance use case: every non-trivial finding is backed by a verbatim quote and a page number pulled from the filing itself, plus a high/medium/low confidence score reflecting how directly the cited text supports the claim.

The financial-filing side is where the "grounded, not just plausible" idea is enforced most strictly — see [Citation grounding](#citation-grounding-for-financial-filings) below.

## How it works

1. **Pick a document type and upload.** The frontend requests a presigned S3 URL from the backend (`POST /upload?documentType=lease|filing`), then PUTs the PDF directly to S3. The key it's stored under encodes the type — `leases/{uuid}.pdf` or `filings/{uuid}.pdf` — which is the single source of truth for how the document gets processed downstream; nothing else needs to track the type separately.
2. **Kick off analysis.** The frontend calls `POST /analyze` with that S3 key. The backend writes a `pending` record to DynamoDB and asynchronously re-invokes its own Lambda function with the key — this sidesteps API Gateway's 30-second timeout, since a full analysis (especially a 10-K) can take well over a minute. The API returns a summary ID immediately.
3. **Extract and analyze.** The async invocation fetches the PDF from S3, extracts text page-by-page with pdfplumber, and sends it to Claude with a prompt specific to the document type. Financial filings are extracted with `[PAGE N]` markers preserved so Claude can cite the page a quote came from; filings are budgeted up to ~500k characters (vs. ~80k for leases) since a full 10-K is much larger than a lease and Claude's context window comfortably covers it.
4. **Validate and store.** Claude's JSON response is parsed into a typed schema (see below) before it's saved. If parsing fails, or a financial finding is missing its required citation, the pipeline retries once with a stricter prompt; a second failure marks the record `failed` rather than storing something ungrounded. A successful result is written to DynamoDB and kept for 90 days, shareable by link. The original PDF is deleted from S3 as soon as analysis completes (success or failure).
5. **Poll for the result.** The frontend polls `GET /summary/{id}` until the record is no longer `pending`, then renders the type-appropriate results view. The polling budget is tuned per document type — filings get a longer window than leases, since a full 10-K analysis legitimately takes longer.

### Timing and timeouts

A large 10-K is a genuinely slow request: a big input plus a multi-category, citation-heavy output can take well over a minute of Claude generation time. Three numbers are deliberately kept in sync so a slow-but-healthy analysis never gets mistaken for a hang:

- The Claude call itself runs under a wall-clock budget (`FILING_CLAUDE_BUDGET_SECONDS` in `claude_client.py`) — if it can't complete within that budget, it fails cleanly with a catchable timeout rather than running indefinitely. The SDK's own retry-on-timeout behavior is deliberately disabled per-call (`max_retries=0`) here, since it would otherwise multiply the wait time past the budget.
- The Lambda function's own timeout (`template.yaml`) is set with headroom above that budget, to cover PDF extraction and the DynamoDB write on top of the Claude call.
- The frontend's polling window (`useDocumentAnalysis.ts`) is set with headroom above *that*, so it doesn't give up while the backend could still legitimately be working.

If any of these three get out of sync — e.g. the Claude budget is raised without raising the Lambda timeout or the frontend's poll window — a healthy-but-slow analysis can silently fail (Lambda hard-kills a still-pending record) or appear to fail (the frontend gives up before the backend resolves), producing a confusing "taking longer than expected" error even when nothing is actually broken.

### Citation grounding for financial filings

The "mandatory citation" requirement isn't just prompt wording — it's enforced in the data model. Every financial finding must include a `citation` (a verbatim quote plus, where determinable, a page number) unless it's the standard "nothing material to report" placeholder for a clean category. A finding that omits its citation fails schema validation and triggers the same retry-with-a-stricter-prompt path used for malformed JSON, rather than silently being stored. Confidence is a `high` / `medium` / `low` label rather than a raw score, on the theory that a small categorical judgment is something a model can apply consistently, while a precise-looking decimal usually isn't earning its precision.

**Known limitation:** truncation for large filings keeps the *front* of the document. In practice this has covered a full mega-cap 10-K (~200k characters) end-to-end including the financial statements, but a filing that runs past ~500k characters could lose coverage of later sections (e.g. deep footnotes or trailing exhibits). A section-aware extractor is a reasonable follow-up if that turns out to matter in practice.

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
