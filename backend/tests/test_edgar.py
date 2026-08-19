from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services import edgar
from app.services.edgar import EdgarError

TICKER_PAYLOAD = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "2": {"cik_str": 6951, "ticker": "AMAT", "title": "APPLIED MATERIALS INC /DE"},
}

SUBMISSIONS = {
    "cik": "320193",
    "name": "Apple Inc.",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "fiscalYearEnd": "0926",
    "exchanges": ["Nasdaq"],
    "tickers": ["AAPL"],
    "filings": {
        "recent": {
            "form": ["10-Q", "10-K", "8-K", "10-K/A", "10-K"],
            "accessionNumber": [
                "0000320193-25-000010",
                "0000320193-25-000079",
                "0000320193-25-000050",
                "0000320193-24-000200",
                "0000320193-24-000123",
            ],
            "filingDate": ["2025-08-01", "2025-10-31", "2025-09-02", "2024-12-01", "2024-11-01"],
            "reportDate": ["2025-06-28", "2025-09-27", "", "2024-09-28", "2024-09-28"],
            "primaryDocument": [
                "aapl-20250628.htm",
                "aapl-20250927.htm",
                "aapl-8k.htm",
                "aapl-20240928a.htm",
                "aapl-20240928.htm",
            ],
        },
        "files": [],
    },
}


@pytest.fixture(autouse=True)
def clear_ticker_cache():
    edgar._ticker_map_cache = None
    yield
    edgar._ticker_map_cache = None


def _response(payload=None, text=""):
    response = MagicMock()
    response.json.return_value = payload
    response.text = text
    response.raise_for_status.return_value = None
    return response


def test_pad_cik_zero_pads_to_ten_digits():
    assert edgar.pad_cik(320193) == "0000320193"
    assert edgar.pad_cik("0000320193") == "0000320193"


def test_pad_cik_rejects_non_numeric():
    with pytest.raises(EdgarError, match="Invalid CIK"):
        edgar.pad_cik("not-a-cik")


def test_resolve_ticker_returns_padded_cik_and_name():
    with patch("app.services.edgar.httpx.get", return_value=_response(TICKER_PAYLOAD)):
        assert edgar.resolve_ticker("aapl") == {
            "cik": "0000320193",
            "ticker": "AAPL",
            "name": "Apple Inc.",
        }


def test_resolve_ticker_rejects_path_traversal():
    with pytest.raises(EdgarError, match="Invalid ticker"):
        edgar.resolve_ticker("../../etc/passwd")


def test_resolve_ticker_raises_for_unlisted_symbol():
    with patch("app.services.edgar.httpx.get", return_value=_response(TICKER_PAYLOAD)):
        with pytest.raises(EdgarError, match="No SEC filer found"):
            edgar.resolve_ticker("ZZZZ")


def test_ticker_map_is_fetched_once_and_cached():
    with patch("app.services.edgar.httpx.get", return_value=_response(TICKER_PAYLOAD)) as get:
        edgar.resolve_ticker("AAPL")
        edgar.resolve_ticker("NVDA")
    assert get.call_count == 1


def test_list_annual_filings_skips_amendments_and_other_forms():
    filings = edgar.list_annual_filings(SUBMISSIONS, limit=5)
    assert [f["accessionNumber"] for f in filings] == [
        "0000320193-25-000079",
        "0000320193-24-000123",
    ]
    assert filings[0]["fiscalYear"] == 2025


def test_list_annual_filings_respects_limit():
    assert len(edgar.list_annual_filings(SUBMISSIONS, limit=1)) == 1


def test_list_annual_filings_raises_when_company_has_none():
    empty = {"filings": {"recent": {"form": ["8-K"], "accessionNumber": ["x"],
                                    "filingDate": ["2025-01-01"], "primaryDocument": ["x.htm"]}}}
    with pytest.raises(EdgarError, match="no 10-K filings"):
        edgar.list_annual_filings(empty)


def test_list_annual_filings_follows_overflow_files():
    """A heavy Form 4 filer can push its own 10-Ks out of the `recent` window."""
    submissions = {
        "filings": {
            "recent": {"form": ["4"], "accessionNumber": ["a"], "filingDate": ["2025-01-01"],
                       "reportDate": [""], "primaryDocument": ["a.htm"]},
            "files": [{"name": "CIK0000320193-submissions-001.json"}],
        }
    }
    overflow = {
        "form": ["10-K"],
        "accessionNumber": ["0000320193-22-000108"],
        "filingDate": ["2022-10-28"],
        "reportDate": ["2022-09-24"],
        "primaryDocument": ["aapl-20220924.htm"],
    }
    with patch("app.services.edgar._get_json", return_value=overflow) as get_json:
        filings = edgar.list_annual_filings(submissions, limit=2)
    assert filings[0]["fiscalYear"] == 2022
    assert "CIK0000320193-submissions-001.json" in get_json.call_args.args[0]


def test_company_profile_extracts_sic():
    profile = edgar.company_profile(SUBMISSIONS)
    assert profile["sic"] == "3571"
    assert profile["sicDescription"] == "Electronic Computers"
    assert profile["cik"] == "0000320193"


def test_filing_document_url_strips_dashes_and_pads():
    url = edgar.filing_document_url("0000320193", "0000320193-25-000079", "aapl-20250927.htm")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000079/aapl-20250927.htm"
    )


@pytest.mark.parametrize("document", ["../../../etc/passwd", "sub/dir.htm", ""])
def test_filing_document_url_rejects_traversal_in_document_name(document):
    with pytest.raises(EdgarError, match="Invalid primary document"):
        edgar.filing_document_url("0000320193", "0000320193-25-000079", document)


def test_filing_document_url_rejects_malformed_accession():
    with pytest.raises(EdgarError, match="Invalid accession"):
        edgar.filing_document_url("0000320193", "not-an-accession", "a.htm")


def test_http_error_is_wrapped_as_edgar_error():
    failing = MagicMock()
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock(status_code=403)
    )
    with patch("app.services.edgar.httpx.get", return_value=failing):
        with pytest.raises(EdgarError, match="EDGAR returned 403"):
            edgar.fetch_submissions("0000320193")


def test_transport_error_is_wrapped_as_edgar_error():
    with patch("app.services.edgar.httpx.get", side_effect=httpx.ConnectError("no route")):
        with pytest.raises(EdgarError, match="Could not reach EDGAR"):
            edgar.fetch_submissions("0000320193")


def test_requests_send_a_contact_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Groundwork/1.0 (me@example.com)")
    with patch("app.services.edgar.httpx.get", return_value=_response({})) as get:
        edgar.fetch_submissions("320193")
    assert get.call_args.kwargs["headers"]["User-Agent"] == "Groundwork/1.0 (me@example.com)"


def test_search_companies_ranks_exact_ticker_first():
    with patch("app.services.edgar.httpx.get", return_value=_response(TICKER_PAYLOAD)):
        results = edgar.search_companies("aapl")
    assert results[0]["ticker"] == "AAPL"


def test_search_companies_matches_on_name():
    with patch("app.services.edgar.httpx.get", return_value=_response(TICKER_PAYLOAD)):
        results = edgar.search_companies("nvidia")
    assert [r["ticker"] for r in results] == ["NVDA"]


def test_search_companies_returns_empty_for_blank_query():
    assert edgar.search_companies("   ") == []


# --- User-Agent contact address ------------------------------------------------------
#
# www.sec.gov serves the filing documents and returns 403 for a User-Agent with no email
# address, while data.sec.gov accepts one. Losing the address is therefore a half-broken
# pipeline rather than a clean failure, which is what these guard.


def test_configured_user_agent_with_a_contact_address_is_used(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Acme Research (analyst@acme.com)")
    assert edgar._user_agent() == "Acme Research (analyst@acme.com)"


def test_user_agent_without_a_contact_address_falls_back(monkeypatch, caplog):
    monkeypatch.setenv("SEC_USER_AGENT", "Groundwork/1.0")
    with caplog.at_level("WARNING"):
        agent = edgar._user_agent()

    assert agent == edgar._DEFAULT_USER_AGENT
    assert "contact address" in caplog.text


@pytest.mark.parametrize("value", ["", "   "])
def test_unset_or_blank_user_agent_falls_back_silently(monkeypatch, caplog, value):
    monkeypatch.setenv("SEC_USER_AGENT", value)
    with caplog.at_level("WARNING"):
        assert edgar._user_agent() == edgar._DEFAULT_USER_AGENT
    assert caplog.text == ""


def test_the_shipped_default_carries_a_contact_address():
    """The out-of-the-box default must satisfy www.sec.gov or nothing downloads."""
    assert edgar._CONTACT_RE.search(edgar._DEFAULT_USER_AGENT)
