# honestLease

Most people sign a lease without fully understanding what they're agreeing to, and most readers of a 10-K don't have time to read the whole thing. honestLease lets you upload a PDF — a residential lease or a 10-K annual report — and get back a structured, plain-English breakdown of the parts that actually matter.

- **Leases**: auto-renewal clauses, deposit conditions, unusual fees, and missing standard protections. Each finding includes the exact quote from your lease and a specific thing you can ask the landlord to change.
- **10-K filings**: risk factors, financial performance, liquidity, related-party transactions, legal proceedings, and accounting policy changes. Every finding is backed by a verbatim citation (with page number) and a confidence score, so nothing is asserted without a traceable source in the document.

## How it works

The frontend uploads your PDF directly to S3 via a presigned URL (`leases/` or `filings/`, depending on the document type you pick), then sends the S3 key to the backend. A Lambda function extracts the text, sends it to Claude with a document-type-specific structured prompt, and stores the result in DynamoDB. Because Claude can take 40-60+ seconds on a full document, the API returns immediately with a summary ID and processes the analysis asynchronously — the frontend polls until it's ready. Summaries are stored for 90 days and shareable by link.

10-K filings are truncated to the first ~500k characters before analysis — large enough to cover the front of most filings (Business, Risk Factors, early MD&A) but not a guarantee of full-document coverage on very large filings.

## Tech stack

- React, TypeScript, Vite — frontend
- Python, FastAPI, Mangum — backend
- AWS Lambda, API Gateway, S3, DynamoDB — infrastructure
- AWS SAM — deployment
- AWS Amplify — frontend hosting
- Anthropic Claude API — lease and financial filing analysis
- pdfplumber — PDF text extraction
