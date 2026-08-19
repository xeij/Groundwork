"""Client for the SEC's public EDGAR data APIs.

Everything here is free and unauthenticated. The one requirement is a User-Agent
carrying a contact address, applied centrally in _get. The two hosts enforce it
differently: data.sec.gov accepts nearly any non-default User-Agent, while
www.sec.gov -- which serves the filing documents themselves -- returns 403 unless
the header contains an email address. EDGAR does not check that the address is
real, but the SEC's access policy expects a genuine one; set SEC_USER_AGENT.
"""

import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
_ACCESSION_RE = re.compile(r"^\d{10}-?\d{2}-?\d{6}$")

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SUBMISSIONS_ARCHIVE_URL = "https://data.sec.gov/submissions/"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"

_REQUEST_TIMEOUT_SECONDS = 30.0
_DEFAULT_USER_AGENT = "Groundwork/1.0 (groundwork-support@example.com)"

# The ticker->CIK map is ~800KB and changes at most daily. Caching it on the module
# keeps it alive across invocations on a warm Lambda container instead of re-fetching
# it for every analysis.
_ticker_map_cache: Optional[dict[str, dict]] = None


class EdgarError(Exception):
    pass


_CONTACT_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _user_agent() -> str:
    """The configured User-Agent, falling back if it carries no contact address.

    A User-Agent without an address fails only on www.sec.gov, so dropping the
    address turns into a confusing partial outage -- filing history and XBRL keep
    working while the filing documents themselves start 403ing. Falling back to a
    usable default beats failing half the pipeline.
    """
    configured = os.getenv("SEC_USER_AGENT", "").strip()
    if configured and _CONTACT_RE.search(configured):
        return configured
    if configured:
        logger.warning(
            "SEC_USER_AGENT (%r) contains no contact address; www.sec.gov rejects such "
            "requests, so falling back to the default. Set it to 'Name (you@example.com)'.",
            configured,
        )
    return _DEFAULT_USER_AGENT


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _user_agent(),
        "Accept-Encoding": "gzip, deflate",
    }


def _get(url: str) -> httpx.Response:
    try:
        response = httpx.get(
            url,
            headers=_headers(),
            timeout=_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as e:
        raise EdgarError(f"EDGAR returned {e.response.status_code} for {url}") from e
    except httpx.HTTPError as e:
        raise EdgarError(f"Could not reach EDGAR: {e}") from e


def _get_json(url: str) -> dict:
    response = _get(url)
    try:
        return response.json()
    except ValueError as e:
        raise EdgarError(f"EDGAR returned malformed JSON for {url}: {e}") from e


def pad_cik(cik: int | str) -> str:
    """EDGAR's JSON APIs key on a zero-padded 10-digit CIK; the archive paths don't."""
    digits = str(cik).lstrip("CIK").lstrip("0") or "0"
    if not digits.isdigit():
        raise EdgarError(f"Invalid CIK: {cik}")
    return digits.zfill(10)


def _load_ticker_map() -> dict[str, dict]:
    global _ticker_map_cache
    if _ticker_map_cache is None:
        payload = _get_json(_TICKER_MAP_URL)
        _ticker_map_cache = {
            entry["ticker"].upper(): {
                "cik": pad_cik(entry["cik_str"]),
                "ticker": entry["ticker"].upper(),
                "name": entry["title"],
            }
            for entry in payload.values()
        }
    return _ticker_map_cache


def resolve_ticker(ticker: str) -> dict:
    """Map a trading symbol to {cik, ticker, name}. Raises if EDGAR doesn't list it."""
    if not _TICKER_RE.match(ticker or ""):
        raise EdgarError(f"Invalid ticker symbol: {ticker}")

    company = _load_ticker_map().get(ticker.upper())
    if company is None:
        raise EdgarError(
            f"No SEC filer found for ticker {ticker.upper()}. "
            "Only companies that file with the SEC are available."
        )
    return dict(company)


def fetch_submissions(cik: str) -> dict:
    return _get_json(_SUBMISSIONS_URL.format(cik=pad_cik(cik)))


def fetch_company_facts(cik: str) -> dict:
    """Every XBRL fact the company has ever tagged. ~4MB for a mega-cap filer."""
    return _get_json(_COMPANY_FACTS_URL.format(cik=pad_cik(cik)))


def company_profile(submissions: dict) -> dict:
    return {
        "cik": pad_cik(submissions.get("cik", "0")),
        "name": submissions.get("name", ""),
        "sic": submissions.get("sic") or None,
        "sicDescription": submissions.get("sicDescription") or None,
        "fiscalYearEnd": submissions.get("fiscalYearEnd") or None,
        "exchanges": submissions.get("exchanges") or [],
        "tickers": submissions.get("tickers") or [],
    }


def _annual_filings_in_block(block: dict, limit: int) -> list[dict]:
    """Pull 10-Ks out of one of EDGAR's column-oriented filing blocks."""
    forms = block.get("form", [])
    report_dates = block.get("reportDate") or [""] * len(forms)
    filings = []

    for i, form in enumerate(forms):
        # "10-K/A" is an amendment to an already-filed 10-K, not an annual report of
        # its own; including it would diff a company against its own restated self.
        if form != "10-K":
            continue
        filings.append(
            {
                "form": form,
                "accessionNumber": block["accessionNumber"][i],
                "filingDate": block["filingDate"][i],
                "reportDate": report_dates[i],
                "primaryDocument": block["primaryDocument"][i],
                "fiscalYear": _fiscal_year(report_dates[i]),
            }
        )
        if len(filings) >= limit:
            break
    return filings


def list_annual_filings(submissions: dict, limit: int = 5) -> list[dict]:
    """The most recent 10-Ks, newest first.

    The `recent` block holds only about the last thousand filings. A company that
    files a high volume of Section 16 ownership forms can push its own 10-Ks out of
    that window entirely, so the paginated overflow files EDGAR lists alongside it
    are followed until enough annual reports are found.
    """
    filings_block = submissions.get("filings", {})
    filings = _annual_filings_in_block(filings_block.get("recent", {}), limit)

    for overflow in filings_block.get("files") or []:
        if len(filings) >= limit:
            break
        name = overflow.get("name")
        if not name:
            continue
        block = _get_json(f"{_SUBMISSIONS_ARCHIVE_URL}{name}")
        filings.extend(_annual_filings_in_block(block, limit - len(filings)))

    if not filings:
        raise EdgarError("This company has no 10-K filings on EDGAR.")
    return filings


def _fiscal_year(report_date: str) -> Optional[int]:
    match = re.match(r"^(\d{4})-", report_date or "")
    return int(match.group(1)) if match else None


def filing_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    if not _ACCESSION_RE.match(accession_number or ""):
        raise EdgarError(f"Invalid accession number: {accession_number}")
    if not primary_document or "/" in primary_document or ".." in primary_document:
        raise EdgarError(f"Invalid primary document: {primary_document}")
    return _ARCHIVE_URL.format(
        cik_int=int(pad_cik(cik)),
        accession=accession_number.replace("-", ""),
        document=primary_document,
    )


def fetch_filing_document(cik: str, accession_number: str, primary_document: str) -> str:
    url = filing_document_url(cik, accession_number, primary_document)
    return _get(url).text


def search_companies(query: str, limit: int = 10) -> list[dict]:
    """Typeahead over the ticker map: exact symbol first, then prefixes, then name matches."""
    needle = (query or "").strip().upper()
    if not needle:
        return []

    companies = _load_ticker_map()
    exact, ticker_prefix, name_prefix, name_contains = [], [], [], []
    for company in companies.values():
        name = company["name"].upper()
        if company["ticker"] == needle:
            exact.append(company)
        elif company["ticker"].startswith(needle):
            ticker_prefix.append(company)
        elif name.startswith(needle):
            name_prefix.append(company)
        elif needle in name:
            name_contains.append(company)

    ticker_prefix.sort(key=lambda c: c["ticker"])
    # Case-insensitively, so "Apple Inc." is not pushed below "APPLIED MATERIALS INC"
    # purely because uppercase sorts first.
    for bucket in (name_prefix, name_contains):
        bucket.sort(key=lambda c: (len(c["name"]), c["name"].upper()))

    ranked = exact + ticker_prefix + name_prefix + name_contains
    return [dict(c) for c in ranked[:limit]]
