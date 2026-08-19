"""Tests for SIC peer benchmarking.

Every network seam is patched: browse-edgar (via _fetch_feed_page / httpx.get), the
companyfacts download (via _fetch_company_facts) and the xbrl_metrics module (via the
_xbrl_metrics indirection, so this suite passes whether or not that module exists yet).
"""

import threading
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services import peers
from app.services.peers import (
    PeerError,
    build_peer_comparison,
    fetch_peer_metrics,
    find_peer_ciks,
    rank_metrics,
)

# --------------------------------------------------------------------------- fixtures

ATOM_NS = 'xmlns="http://www.w3.org/2005/Atom"'


def _atom_feed(ciks: list[str], namespaced: bool = True) -> str:
    """A browse-edgar company feed, reproducing the upstream bugs verbatim.

    The `title` and `name` attributes really do contain Perl reference dumps in the
    live feed, which is why the parser must never read a company name from here.
    """
    entries = "".join(
        f"""
        <entry title="ARRAY(0x5645c382c{index:03x})">
          <content type="text/xml">
            <company-info name="ARRAY(0x5645c382d{index:03x})">
              <addresses><address type="business"><state>CA</state></address></addresses>
              <cik>{cik}</cik>
              <irs-number></irs-number>
              <sic>3571</sic>
            </company-info>
          </content>
          <id>urn:tag:www.sec.gov:cik={cik}</id>
          <summary type="html">&lt;strong&gt;CIK:&lt;/strong&gt; {cik}</summary>
        </entry>"""
        for index, cik in enumerate(ciks)
    )
    ns = f" {ATOM_NS}" if namespaced else ""
    return f'<?xml version="1.0" encoding="ISO-8859-1" ?><feed{ns}>{entries}</feed>'


TICKER_MAP_BY_CIK = {
    "0000320193": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
    "0001571996": {"cik": "0001571996", "ticker": "DELL", "name": "Dell Technologies Inc."},
    "0001375365": {"cik": "0001375365", "ticker": "SMCI", "name": "Super Micro Computer"},
    "0000926326": {"cik": "0000926326", "ticker": "OMCL", "name": "OMNICELL, INC."},
    "0000944075": {"cik": "0000944075", "ticker": "SCKT", "name": "SOCKET MOBILE, INC."},
}


def _ratio(value, unit="ratio", label=None):
    return {"label": label or "Ratio", "value": value, "priorValue": None,
            "change": None, "unit": unit}


def _subject(**ratios) -> dict:
    return {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.",
            "history": [], "ratios": ratios}


def _peer(ticker: str, **ratios) -> dict:
    return {"cik": "9" * 10, "ticker": ticker, "name": f"{ticker} Corp",
            "history": [], "ratios": ratios}


def _cohort(key: str, values: list[float], unit="ratio") -> list[dict]:
    return [_peer(f"P{i}", **{key: _ratio(v, unit)}) for i, v in enumerate(values)]


# ----------------------------------------------------------------------- feed parsing


def test_parse_cik_feed_extracts_ciks_from_namespaced_feed():
    ciks = peers._parse_cik_feed(_atom_feed(["0000320193", "0001571996"]))
    assert ciks == ["0000320193", "0001571996"]


def test_parse_cik_feed_handles_feed_without_atom_namespace():
    # EDGAR has served this feed both with and without the default xmlns; local-name
    # matching must cover both.
    ciks = peers._parse_cik_feed(_atom_feed(["0000320193"], namespaced=False))
    assert ciks == ["0000320193"]


def test_parse_cik_feed_ignores_the_broken_name_attributes():
    xml_text = _atom_feed(["0000320193"])
    assert "ARRAY(0x" in xml_text  # guard: the fixture really does contain the garbage
    ciks = peers._parse_cik_feed(xml_text)
    assert ciks == ["0000320193"]
    assert not any("ARRAY" in cik for cik in ciks)


def test_parse_cik_feed_pads_and_deduplicates():
    xml_text = _atom_feed(["320193", "0000320193", "1571996"])
    assert peers._parse_cik_feed(xml_text) == ["0000320193", "0001571996"]


def test_parse_cik_feed_skips_non_numeric_and_empty_ciks():
    xml_text = _atom_feed(["0000320193"]).replace(
        "<cik>0000320193</cik>", "<cik>0000320193</cik><cik></cik><cik>N/A</cik>"
    )
    assert peers._parse_cik_feed(xml_text) == ["0000320193"]


def test_parse_cik_feed_returns_empty_for_a_feed_with_no_entries():
    assert peers._parse_cik_feed(_atom_feed([])) == []


def test_parse_cik_feed_raises_on_malformed_xml():
    with pytest.raises(PeerError, match="unparseable"):
        peers._parse_cik_feed("<feed><entry>")


# ------------------------------------------------------------------- feed HTTP layer


def _mock_response(text: str, status_ok: bool = True):
    response = MagicMock()
    response.text = text
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        error_response = MagicMock()
        error_response.status_code = 503
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=error_response
        )
    return response


def test_fetch_feed_page_sends_sec_user_agent_and_paging_params():
    with patch("app.services.peers.httpx.get", return_value=_mock_response("<feed/>")) as get:
        peers._fetch_feed_page("3571", 100)

    kwargs = get.call_args.kwargs
    assert kwargs["params"]["SIC"] == "3571"
    assert kwargs["params"]["start"] == "100"
    assert kwargs["params"]["output"] == "atom"
    assert "User-Agent" in kwargs["headers"]


def test_fetch_feed_page_wraps_http_errors_in_peer_error():
    with patch("app.services.peers.httpx.get", return_value=_mock_response("", status_ok=False)):
        with pytest.raises(PeerError, match="503"):
            peers._fetch_feed_page("3571", 0)


def test_fetch_feed_page_wraps_transport_errors_in_peer_error():
    with patch("app.services.peers.httpx.get", side_effect=httpx.ConnectTimeout("slow")):
        with pytest.raises(PeerError, match="Could not reach EDGAR"):
            peers._fetch_feed_page("3571", 0)


# ------------------------------------------------------------------- peer discovery


def test_find_peer_ciks_intersects_feed_with_ticker_map():
    feed = _atom_feed(["0000320193", "0000000001", "0001571996", "0000000002"])
    with patch.object(peers, "_fetch_feed_page", return_value=feed), \
         patch.object(peers, "_cik_to_company", return_value=TICKER_MAP_BY_CIK):
        found = find_peer_ciks("3571", exclude_cik="0000000099")

    # The two unlisted filers are dropped: no ticker means no useful comparable.
    assert found == [
        {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        {"cik": "0001571996", "ticker": "DELL", "name": "Dell Technologies Inc."},
    ]


def test_find_peer_ciks_excludes_the_subject_company():
    feed = _atom_feed(["0000320193", "0001571996", "0001375365"])
    with patch.object(peers, "_fetch_feed_page", return_value=feed), \
         patch.object(peers, "_cik_to_company", return_value=TICKER_MAP_BY_CIK):
        found = find_peer_ciks("3571", exclude_cik="320193")  # unpadded on purpose

    assert [peer["ticker"] for peer in found] == ["DELL", "SMCI"]


def test_find_peer_ciks_honours_the_limit():
    feed = _atom_feed(list(TICKER_MAP_BY_CIK))
    with patch.object(peers, "_fetch_feed_page", return_value=feed), \
         patch.object(peers, "_cik_to_company", return_value=TICKER_MAP_BY_CIK):
        found = find_peer_ciks("3571", exclude_cik="", limit=2)

    assert len(found) == 2


def test_find_peer_ciks_returns_empty_for_a_non_positive_limit():
    with patch.object(peers, "_fetch_feed_page") as fetch:
        assert find_peer_ciks("3571", exclude_cik="", limit=0) == []
    fetch.assert_not_called()


def test_find_peer_ciks_stops_paging_when_a_page_is_short():
    feed = _atom_feed(["0000320193"])
    with patch.object(peers, "_fetch_feed_page", return_value=feed) as fetch, \
         patch.object(peers, "_cik_to_company", return_value=TICKER_MAP_BY_CIK):
        found = find_peer_ciks("3571", exclude_cik="")

    assert len(found) == 1
    assert fetch.call_count == 1


def test_find_peer_ciks_pages_until_the_limit_is_filled():
    full_page = _atom_feed([str(n).zfill(10) for n in range(1, peers._FEED_PAGE_SIZE + 1)])
    second_page = _atom_feed(["0000320193", "0001571996"])
    with patch.object(peers, "_fetch_feed_page", side_effect=[full_page, second_page]) as fetch, \
         patch.object(peers, "_cik_to_company", return_value=TICKER_MAP_BY_CIK):
        found = find_peer_ciks("3571", exclude_cik="")

    assert [peer["ticker"] for peer in found] == ["AAPL", "DELL"]
    assert fetch.call_count == 2
    assert fetch.call_args_list[1].args == ("3571", peers._FEED_PAGE_SIZE)


def test_find_peer_ciks_never_returns_the_same_filer_twice_across_pages():
    page = _atom_feed(["0000320193"] + [str(n).zfill(10) for n in range(1, peers._FEED_PAGE_SIZE)])
    with patch.object(peers, "_fetch_feed_page", return_value=page), \
         patch.object(peers, "_cik_to_company", return_value=TICKER_MAP_BY_CIK):
        found = find_peer_ciks("3571", exclude_cik="")

    assert [peer["cik"] for peer in found] == ["0000320193"]


@pytest.mark.parametrize("bad_sic", ["", None, "abc", "35711", "3", "35 71"])
def test_find_peer_ciks_rejects_invalid_sic_codes(bad_sic):
    with pytest.raises(PeerError, match="Invalid SIC"):
        find_peer_ciks(bad_sic, exclude_cik="0000320193")


def test_cik_to_company_inverts_edgars_cached_ticker_map():
    forward = {
        "AAPL": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        # Share classes share a CIK; the first (highest market cap) entry wins.
        "GOOGL": {"cik": "0001652044", "ticker": "GOOGL", "name": "Alphabet Inc."},
        "GOOG": {"cik": "0001652044", "ticker": "GOOG", "name": "Alphabet Inc."},
    }
    peers._cik_map_cache = None
    try:
        with patch("app.services.peers.edgar._load_ticker_map", return_value=forward) as load:
            first = peers._cik_to_company()
            second = peers._cik_to_company()
    finally:
        peers._cik_map_cache = None

    assert first["0000320193"]["ticker"] == "AAPL"
    assert first["0001652044"]["ticker"] == "GOOGL"
    assert second is first
    assert load.call_count == 1  # cached across calls for warm Lambda containers


# ------------------------------------------------------------------ concurrent fetch


class _FakeMetrics:
    """Stand-in for the xbrl_metrics module, which this suite must not import."""

    def __init__(self, history=None, ratios=None):
        self._history = history if history is not None else [{"fiscalYear": 2025}]
        self._ratios = ratios if ratios is not None else {"currentRatio": _ratio(1.5)}

    def build_financial_history(self, company_facts, max_years=6):
        return self._history

    def derived_ratios(self, history):
        return self._ratios


def test_fetch_peer_metrics_returns_history_and_ratios_per_peer():
    candidates = [
        {"cik": "0000000002", "ticker": "DELL", "name": "Dell"},
        {"cik": "0000000001", "ticker": "AAPL", "name": "Apple"},
    ]
    with patch.object(peers, "_fetch_company_facts", return_value={"facts": {}}), \
         patch.object(peers, "_xbrl_metrics", return_value=_FakeMetrics()):
        results = fetch_peer_metrics(candidates, budget_seconds=5.0)

    # Threads finish out of order, so output is sorted by ticker for reproducibility.
    assert [peer["ticker"] for peer in results] == ["AAPL", "DELL"]
    assert results[0]["history"] == [{"fiscalYear": 2025}]
    assert results[0]["ratios"]["currentRatio"]["value"] == 1.5
    assert results[0]["name"] == "Apple"


def test_fetch_peer_metrics_returns_empty_for_no_peers():
    with patch.object(peers, "_fetch_company_facts") as fetch:
        assert fetch_peer_metrics([], budget_seconds=5.0) == []
    fetch.assert_not_called()


def test_fetch_peer_metrics_skips_a_peer_whose_fetch_raises():
    candidates = [
        {"cik": "0000000001", "ticker": "AAPL", "name": "Apple"},
        {"cik": "0000000002", "ticker": "BOOM", "name": "Explodes"},
        {"cik": "0000000003", "ticker": "DELL", "name": "Dell"},
    ]

    def flaky(cik):
        if cik == "0000000002":
            raise RuntimeError("EDGAR returned 404")
        return {"facts": {}}

    with patch.object(peers, "_fetch_company_facts", side_effect=flaky), \
         patch.object(peers, "_xbrl_metrics", return_value=_FakeMetrics()):
        results = fetch_peer_metrics(candidates, budget_seconds=5.0)

    assert [peer["ticker"] for peer in results] == ["AAPL", "DELL"]


def test_fetch_peer_metrics_skips_a_peer_with_unusable_xbrl():
    candidates = [{"cik": "0000000001", "ticker": "AAPL", "name": "Apple"}]
    with patch.object(peers, "_fetch_company_facts", return_value={"facts": {}}), \
         patch.object(peers, "_xbrl_metrics", return_value=_FakeMetrics(history=[])):
        assert fetch_peer_metrics(candidates, budget_seconds=5.0) == []


def test_fetch_peer_metrics_skips_a_peer_with_no_derivable_ratios():
    candidates = [{"cik": "0000000001", "ticker": "AAPL", "name": "Apple"}]
    with patch.object(peers, "_fetch_company_facts", return_value={"facts": {}}), \
         patch.object(peers, "_xbrl_metrics", return_value=_FakeMetrics(ratios={})):
        assert fetch_peer_metrics(candidates, budget_seconds=5.0) == []


def test_fetch_peer_metrics_downloads_nothing_when_the_budget_is_already_spent():
    candidates = [{"cik": "000000000%d" % n, "ticker": f"P{n}", "name": "P"} for n in range(3)]
    with patch.object(peers, "_fetch_company_facts") as fetch, \
         patch.object(peers, "_xbrl_metrics", return_value=_FakeMetrics()):
        results = fetch_peer_metrics(candidates, budget_seconds=0.0)

    assert results == []
    fetch.assert_not_called()


def test_fetch_peer_metrics_returns_partial_results_when_the_budget_expires():
    release = threading.Event()
    candidates = [
        {"cik": "0000000001", "ticker": "FAST1", "name": "Fast One"},
        {"cik": "0000000002", "ticker": "FAST2", "name": "Fast Two"},
        {"cik": "0000000003", "ticker": "SLOW1", "name": "Slow One"},
        {"cik": "0000000004", "ticker": "SLOW2", "name": "Slow Two"},
    ]

    def slow_for_some(peer):
        if peer["ticker"].startswith("SLOW"):
            release.wait(timeout=10)
        return {"cik": peer["cik"], "ticker": peer["ticker"], "name": peer["name"],
                "history": [], "ratios": {}}

    started = time.monotonic()
    try:
        with patch.object(peers, "_load_one_peer", side_effect=slow_for_some):
            results = fetch_peer_metrics(candidates, budget_seconds=0.4)
    finally:
        release.set()  # let the abandoned workers exit so the interpreter can shut down
    elapsed = time.monotonic() - started

    assert [peer["ticker"] for peer in results] == ["FAST1", "FAST2"]
    assert elapsed < 3.0  # returned on the budget, not on the slow peers


# ----------------------------------------------------------------------- rank_metrics


def test_rank_metrics_hand_worked_lower_is_better_odd_cohort():
    # Subject DSO 61.2 against ten peers: eight are strictly better (lower), so the
    # subject ranks 9th of an 11-company cohort, i.e. it beats 2 of 11 -> 18th pctile.
    peer_values = [21.0, 30.0, 35.0, 40.0, 44.0, 48.0, 55.0, 58.0, 70.0, 78.5]
    subject = _subject(
        daysSalesOutstanding=_ratio(61.2, "days", "Days Sales Outstanding")
    )
    cohort = _cohort("daysSalesOutstanding", peer_values, unit="days")

    (metric,) = rank_metrics(subject, cohort)

    assert metric["key"] == "daysSalesOutstanding"
    assert metric["label"] == "Days Sales Outstanding"
    assert metric["unit"] == "days"
    assert metric["higherIsBetter"] is False
    assert metric["subjectValue"] == 61.2
    assert metric["rank"] == 9
    assert metric["cohortSize"] == 11
    assert metric["percentile"] == 18
    assert metric["median"] == 48.0  # 6th of 11 sorted values
    assert metric["best"] == 21.0
    assert metric["worst"] == 78.5
    assert metric["severity"] == "red"
    assert len(metric["peerValues"]) == 10
    assert metric["peerValues"][0]["value"] == 21.0  # best-first for lower-is-better


def test_rank_metrics_median_of_an_even_cohort_averages_the_middle_two():
    subject = _subject(currentRatio=_ratio(6.0, "ratio", "Current Ratio"))
    cohort = _cohort("currentRatio", [1.0, 2.0, 3.0, 4.0, 5.0])

    (metric,) = rank_metrics(subject, cohort)

    assert metric["cohortSize"] == 6
    assert metric["median"] == 3.5  # (3.0 + 4.0) / 2
    assert metric["rank"] == 1
    assert metric["percentile"] == 83  # round(5 / 6 * 100)
    assert metric["severity"] == "green"
    assert metric["best"] == 6.0
    assert metric["worst"] == 1.0


def test_rank_metrics_polarity_flips_the_ranking_for_identical_numbers():
    numbers = [20.0, 30.0, 40.0, 50.0, 60.0]
    subject = _subject(
        grossMargin=_ratio(10.0, "percent", "Gross Margin"),
        daysSalesOutstanding=_ratio(10.0, "days", "Days Sales Outstanding"),
    )
    cohort = [
        _peer(
            f"P{i}",
            grossMargin=_ratio(value, "percent"),
            daysSalesOutstanding=_ratio(value, "days"),
        )
        for i, value in enumerate(numbers)
    ]

    ranked = {metric["key"]: metric for metric in rank_metrics(subject, cohort)}

    # Same 10.0 in a six-company cohort: worst possible margin, best possible DSO.
    assert ranked["grossMargin"]["higherIsBetter"] is True
    assert ranked["grossMargin"]["rank"] == 6
    assert ranked["grossMargin"]["percentile"] == 0
    assert ranked["grossMargin"]["severity"] == "red"
    assert ranked["grossMargin"]["best"] == 60.0

    assert ranked["daysSalesOutstanding"]["higherIsBetter"] is False
    assert ranked["daysSalesOutstanding"]["rank"] == 1
    assert ranked["daysSalesOutstanding"]["percentile"] == 83
    assert ranked["daysSalesOutstanding"]["severity"] == "green"
    assert ranked["daysSalesOutstanding"]["best"] == 10.0


def test_rank_metrics_ties_share_the_best_available_rank():
    # Competition ranking: nobody is strictly better, so the tied subject ranks 1st.
    subject = _subject(currentRatio=_ratio(2.0, "ratio", "Current Ratio"))
    cohort = _cohort("currentRatio", [2.0, 2.0, 2.0, 2.0, 1.0])

    (metric,) = rank_metrics(subject, cohort)

    assert metric["rank"] == 1
    assert metric["cohortSize"] == 6
    assert metric["percentile"] == 83


def test_rank_metrics_ties_do_not_count_as_better_for_lower_is_better():
    subject = _subject(debtToEquity=_ratio(1.0, "ratio", "Debt to Equity"))
    cohort = _cohort("debtToEquity", [0.5, 1.0, 1.0, 1.0, 2.0])

    (metric,) = rank_metrics(subject, cohort)

    assert metric["higherIsBetter"] is False
    assert metric["rank"] == 2  # only the 0.5 filer is strictly better
    assert metric["cohortSize"] == 6
    assert metric["percentile"] == 67
    assert metric["median"] == 1.0


def test_rank_metrics_requires_a_minimum_number_of_usable_peers():
    subject = _subject(currentRatio=_ratio(2.0, "ratio", "Current Ratio"))
    three_peers = _cohort("currentRatio", [1.0, 2.0, 3.0])
    assert len(three_peers) == peers._MIN_USABLE_PEERS - 1

    assert rank_metrics(subject, three_peers) == []
    assert rank_metrics(subject, _cohort("currentRatio", [1.0, 2.0, 3.0, 4.0])) != []


def test_rank_metrics_ignores_peers_missing_or_holding_unusable_values():
    subject = _subject(currentRatio=_ratio(2.0, "ratio", "Current Ratio"))
    cohort = _cohort("currentRatio", [1.0, 2.0, 3.0, 4.0])
    cohort.append(_peer("NONE", currentRatio=_ratio(None)))
    cohort.append(_peer("NAN", currentRatio=_ratio(float("nan"))))
    cohort.append(_peer("INF", currentRatio=_ratio(float("inf"))))
    cohort.append(_peer("TEXT", currentRatio=_ratio("1.2")))
    cohort.append(_peer("EMPTY"))

    (metric,) = rank_metrics(subject, cohort)

    assert metric["cohortSize"] == 5
    assert {entry["ticker"] for entry in metric["peerValues"]} == {"P0", "P1", "P2", "P3"}


def test_rank_metrics_skips_metrics_with_no_declared_polarity():
    subject = _subject(wibbleFactor=_ratio(2.0, "ratio", "Wibble Factor"))
    cohort = _cohort("wibbleFactor", [1.0, 2.0, 3.0, 4.0, 5.0])

    assert rank_metrics(subject, cohort) == []
    assert "wibbleFactor" not in peers.METRIC_POLARITY


def test_rank_metrics_skips_dollar_denominated_metrics():
    # Absolute dollars are not comparable across companies of wildly different size.
    subject = _subject(returnOnAssets=_ratio(2.0, "usd", "Return on Assets"))
    cohort = _cohort("returnOnAssets", [1.0, 2.0, 3.0, 4.0, 5.0], unit="usd")

    assert rank_metrics(subject, cohort) == []


def test_rank_metrics_skips_metrics_the_subject_did_not_report():
    subject = _subject(currentRatio=_ratio(None, "ratio", "Current Ratio"))
    cohort = _cohort("currentRatio", [1.0, 2.0, 3.0, 4.0, 5.0])

    assert rank_metrics(subject, cohort) == []


def test_rank_metrics_orders_the_worst_standing_first():
    subject = _subject(
        currentRatio=_ratio(9.0, "ratio", "Current Ratio"),       # best -> green
        debtToEquity=_ratio(9.0, "ratio", "Debt to Equity"),      # worst -> red
        grossMargin=_ratio(3.0, "percent", "Gross Margin"),       # middle -> yellow
    )
    cohort = [
        _peer(
            f"P{i}",
            currentRatio=_ratio(value),
            debtToEquity=_ratio(value),
            grossMargin=_ratio(value, "percent"),
        )
        for i, value in enumerate([1.0, 2.0, 4.0, 5.0, 6.0])
    ]

    ranked = rank_metrics(subject, cohort)

    assert [metric["key"] for metric in ranked] == [
        "debtToEquity", "grossMargin", "currentRatio"
    ]
    assert [metric["severity"] for metric in ranked] == ["red", "yellow", "green"]


def test_rank_metrics_interpretation_names_the_rank_and_the_cohort():
    subject = _subject(
        daysSalesOutstanding=_ratio(61.2, "days", "Days Sales Outstanding")
    )
    cohort = _cohort(
        "daysSalesOutstanding", [21.0, 30.0, 35.0, 40.0, 44.0, 48.0, 55.0, 58.0, 70.0, 78.5],
        unit="days",
    )

    (metric,) = rank_metrics(subject, cohort)

    assert "9th" in metric["interpretation"]
    assert "11 SIC peers" in metric["interpretation"]
    assert "61.2 days" in metric["interpretation"]
    assert "Days Sales Outstanding" in metric["interpretation"]


def test_rank_metrics_tolerates_a_subject_with_no_ratios():
    assert rank_metrics({}, _cohort("currentRatio", [1.0, 2.0, 3.0, 4.0, 5.0])) == []
    assert rank_metrics({"ratios": None}, []) == []


def test_ordinal_covers_the_teens_and_the_suffix_cycle():
    assert [peers._ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th",
        "21st", "22nd", "23rd", "101st", "111th",
    ]


# --------------------------------------------------------------- build_peer_comparison


def _full_cohort():
    return [
        _peer(f"P{i}", currentRatio=_ratio(float(i) + 1.0, "ratio", "Current Ratio"))
        for i in range(5)
    ]


def test_build_peer_comparison_returns_a_full_panel():
    candidates = [{"cik": f"000000000{i}", "ticker": f"P{i}", "name": f"P{i} Corp"}
                  for i in range(5)]
    subject = _subject(currentRatio=_ratio(6.0, "ratio", "Current Ratio"))

    with patch.object(peers, "find_peer_ciks", return_value=candidates) as find, \
         patch.object(peers, "fetch_peer_metrics", return_value=_full_cohort()):
        result = build_peer_comparison("3571", "Electronic Computers", subject,
                                       limit=12, budget_seconds=30.0)

    assert result["sic"] == "3571"
    assert result["sicDescription"] == "Electronic Computers"
    assert result["cohortSize"] == 5
    assert result["peers"][0] == {"ticker": "P0", "name": "P0 Corp", "cik": "9999999999"}
    assert result["unavailableReason"] is None
    assert [metric["key"] for metric in result["metrics"]] == ["currentRatio"]
    assert result["metrics"][0]["rank"] == 1
    find.assert_called_once_with("3571", "0000320193", limit=12)


def test_build_peer_comparison_forwards_the_budget_to_the_fetcher():
    candidates = [{"cik": "0000000001", "ticker": "P0", "name": "P0 Corp"}]
    with patch.object(peers, "find_peer_ciks", return_value=candidates), \
         patch.object(peers, "fetch_peer_metrics", return_value=[]) as fetch:
        build_peer_comparison("3571", "Electronic Computers", _subject(), budget_seconds=12.5)

    assert fetch.call_args.kwargs["budget_seconds"] == 12.5


def test_build_peer_comparison_explains_a_missing_sic_code():
    result = build_peer_comparison(None, None, _subject())

    assert result["sic"] is None
    assert result["metrics"] == []
    assert result["peers"] == []
    assert "SIC industry code" in result["unavailableReason"]


def test_build_peer_comparison_explains_an_empty_cohort():
    with patch.object(peers, "find_peer_ciks", return_value=[]):
        result = build_peer_comparison("3571", "Electronic Computers", _subject())

    assert result["cohortSize"] == 0
    assert "No other exchange-listed" in result["unavailableReason"]


def test_build_peer_comparison_explains_a_peer_lookup_failure():
    with patch.object(peers, "find_peer_ciks", side_effect=PeerError("EDGAR returned 503")):
        result = build_peer_comparison("3571", "Electronic Computers", _subject())

    assert result["metrics"] == []
    assert "503" in result["unavailableReason"]


def test_build_peer_comparison_explains_a_cohort_that_is_too_thin_to_rank():
    candidates = [{"cik": f"000000000{i}", "ticker": f"P{i}", "name": f"P{i} Corp"}
                  for i in range(8)]
    thin = _full_cohort()[:3]

    with patch.object(peers, "find_peer_ciks", return_value=candidates), \
         patch.object(peers, "fetch_peer_metrics", return_value=thin):
        result = build_peer_comparison("3571", "Electronic Computers",
                                       _subject(currentRatio=_ratio(6.0)))

    assert result["cohortSize"] == 3
    assert result["metrics"] == []
    assert "Only 3 of 8" in result["unavailableReason"]
    assert str(peers._MIN_USABLE_PEERS) in result["unavailableReason"]


def test_build_peer_comparison_explains_a_cohort_with_no_shared_metrics():
    candidates = [{"cik": f"000000000{i}", "ticker": f"P{i}", "name": f"P{i} Corp"}
                  for i in range(5)]
    subject = _subject(grossMargin=_ratio(40.0, "percent", "Gross Margin"))

    with patch.object(peers, "find_peer_ciks", return_value=candidates), \
         patch.object(peers, "fetch_peer_metrics", return_value=_full_cohort()):
        result = build_peer_comparison("3571", "Electronic Computers", subject)

    assert result["cohortSize"] == 5
    assert result["metrics"] == []
    assert "no single ratio was reported" in result["unavailableReason"]


# ------------------------------------------------------------------------- throttling


def test_throttle_spaces_out_consecutive_request_starts():
    peers._last_request_at = 0.0
    with patch("app.services.peers.time.monotonic", side_effect=[100.0, 100.0, 100.05, 100.05]), \
         patch("app.services.peers.time.sleep") as sleep:
        peers._throttle()
        peers._throttle()

    sleep.assert_called_once()
    assert sleep.call_args.args[0] == pytest.approx(peers._MIN_REQUEST_INTERVAL_SECONDS - 0.05)


def test_fetch_company_facts_throttles_then_delegates_to_edgar():
    with patch.object(peers, "_throttle") as throttle, \
         patch("app.services.peers.edgar.fetch_company_facts", return_value={"facts": {}}) as fetch:
        assert peers._fetch_company_facts("0000320193") == {"facts": {}}

    throttle.assert_called_once()
    fetch.assert_called_once_with("0000320193")


def test_polarity_table_covers_the_shipped_ratio_keys():
    """Guards the seam with xbrl_metrics: an unlisted key is silently never ranked.

    Hardcoded rather than imported so this suite stays independent of that module.
    Keys deliberately left out because their direction is a judgement call, not a
    fact: daysPayableOutstanding, capexIntensity. freeCashFlow is USD, so the unit
    filter drops it regardless.
    """
    shipped = {
        "grossMargin", "operatingMargin", "netMargin", "returnOnAssets", "returnOnEquity",
        "currentRatio", "quickRatio", "daysSalesOutstanding", "daysInventoryOutstanding",
        "cashConversionCycle", "interestCoverage", "netDebtToEbitda", "debtToEquity",
        "fcfMargin", "sbcPercentOfOcf", "revenueGrowth", "dilutedShareChange",
    }
    assert shipped <= set(peers.METRIC_POLARITY)
    assert peers.METRIC_POLARITY["fcfMargin"] is True
    assert peers.METRIC_POLARITY["sbcPercentOfOcf"] is False
    assert peers.METRIC_POLARITY["dilutedShareChange"] is False
    assert "daysPayableOutstanding" not in peers.METRIC_POLARITY
    assert "capexIntensity" not in peers.METRIC_POLARITY
