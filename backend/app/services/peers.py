"""Peer benchmarking: rank a company's ratios against its SIC-industry cohort.

The value here is comparative context that no single filing contains. A 10-K will
tell you DSO is 61 days; only the cohort tells you that is fourth worst among the
listed companies in the same SIC code.

Peer discovery uses EDGAR's browse-edgar ATOM feed, which is the only free endpoint
that lists filers by SIC. The feed's human-readable fields are broken upstream (see
_parse_cik_feed), so names and tickers are recovered by intersecting the feed's CIKs
with the company_tickers.json map that `edgar` already caches.
"""

import math
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Optional

import httpx

from app.services import edgar

_BROWSE_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_REQUEST_TIMEOUT_SECONDS = 30.0

# browse-edgar caps a page at 100 entries. Most SIC codes hold well under 200 filers
# and only a small fraction are still listed, so a couple of pages is plenty to fill
# a 12-name cohort without hammering an endpoint that has no bulk equivalent.
_FEED_PAGE_SIZE = 100
_MAX_FEED_PAGES = 3

# companyfacts is ~4MB per filer. Four workers each spend most of their time streaming
# the body, so the sustained request rate lands near 4/s -- comfortably inside the SEC's
# published 10/s ceiling. _MIN_REQUEST_INTERVAL_SECONDS is a second guard for the case
# where responses come back fast (small filers, warm CDN edge).
_MAX_WORKERS = 4
_MIN_REQUEST_INTERVAL_SECONDS = 0.15

_DEFAULT_PEER_LIMIT = 12

# Below this many usable peers a percentile is noise dressed up as a statistic, so the
# metric is dropped entirely rather than reported with a caveat nobody reads.
_MIN_USABLE_PEERS = 4

# Ratios denominated in dollars are not comparable across companies of different sizes;
# only normalised units get ranked.
_COMPARABLE_UNITS = frozenset({"percent", "days", "ratio", "x"})

# Polarity per metric: True when a larger value is the healthier outcome. Kept as an
# explicit table because the direction is a domain judgement, not something derivable
# from the key or the unit -- a high current ratio is good, a high debt/equity is not.
# Metrics absent from this table are NOT ranked: an unknown polarity would flip the
# severity colour and the interpretation sentence, which is worse than staying silent.
# Deliberately omitted as genuinely ambiguous: daysPayableOutstanding (stretching
# suppliers preserves cash but signals strain), effectiveTaxRate, capexIntensity,
# researchAndDevelopmentIntensity, sgaRatio.
METRIC_POLARITY: dict[str, bool] = {
    # Margins and returns -- more is better.
    "grossMargin": True,
    "operatingMargin": True,
    "netMargin": True,
    "profitMargin": True,
    "ebitdaMargin": True,
    "freeCashFlowMargin": True,
    "fcfMargin": True,
    "operatingCashFlowMargin": True,
    "returnOnAssets": True,
    "returnOnEquity": True,
    "returnOnInvestedCapital": True,
    "returnOnCapitalEmployed": True,
    # Growth -- more is better.
    "revenueGrowth": True,
    "netIncomeGrowth": True,
    "earningsGrowth": True,
    # Liquidity and coverage -- more headroom is better.
    "currentRatio": True,
    "quickRatio": True,
    "interestCoverage": True,
    "cashRatio": True,
    # Efficiency -- turning capital over faster is better.
    "assetTurnover": True,
    "inventoryTurnover": True,
    "receivablesTurnover": True,
    "cashConversionRatio": True,
    # Working capital days -- shorter is better.
    "daysSalesOutstanding": False,
    "daysInventoryOutstanding": False,
    "cashConversionCycle": False,
    # Leverage -- less is better.
    "debtToEquity": False,
    "debtToAssets": False,
    "debtToEbitda": False,
    "netDebtToEbitda": False,
    "liabilitiesToAssets": False,
    "leverageRatio": False,
    # Earnings quality and dilution -- less is better.
    "accrualsRatio": False,
    "accrualRatio": False,
    "shareBasedCompensationRatio": False,
    "sbcPercentOfOcf": False,
    "dilutionRate": False,
    "dilutedShareChange": False,
    "goodwillToAssets": False,
}

_SEVERITY_ORDER = {"red": 0, "yellow": 1, "green": 2}

# Percentile is oriented so that higher is always healthier, regardless of polarity.
_GREEN_PERCENTILE = 60
_YELLOW_PERCENTILE = 30

_UNIT_SUFFIX = {"percent": "%", "days": " days", "x": "x", "ratio": "", "usd": ""}

# Inverted company_tickers.json, CIK -> {cik, ticker, name}. Built from edgar's own
# cached forward map so a warm Lambda container pays for that 800KB download once.
_cik_map_cache: Optional[dict[str, dict]] = None
_cik_map_lock = threading.Lock()

_throttle_lock = threading.Lock()
_last_request_at = 0.0


class PeerError(Exception):
    pass


def _throttle() -> None:
    """Serialise request *starts* so concurrent workers cannot burst past SEC limits."""
    global _last_request_at
    with _throttle_lock:
        gap = time.monotonic() - _last_request_at
        if gap < _MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - gap)
        _last_request_at = time.monotonic()


def _fetch_company_facts(cik: str) -> dict:
    """Indirection over edgar so peer fetching can be throttled and patched in tests."""
    _throttle()
    return edgar.fetch_company_facts(cik)


def _xbrl_metrics():
    """Imported lazily and through a function so tests can patch this seam wholesale."""
    from app.services import xbrl_metrics

    return xbrl_metrics


def _cik_to_company() -> dict[str, dict]:
    global _cik_map_cache
    with _cik_map_lock:
        if _cik_map_cache is None:
            forward = edgar._load_ticker_map()
            by_cik: dict[str, dict] = {}
            # A filer with multiple share classes appears once per ticker. The map is
            # ordered by market cap, so the first entry is the primary listing.
            for entry in forward.values():
                by_cik.setdefault(entry["cik"], dict(entry))
            _cik_map_cache = by_cik
        return _cik_map_cache


def _fetch_feed_page(sic: str, start: int) -> str:
    params = {
        "action": "getcompany",
        "SIC": sic,
        "type": "10-K",
        "dateb": "",
        "owner": "include",
        "count": str(_FEED_PAGE_SIZE),
        "start": str(start),
        "output": "atom",
    }
    try:
        # edgar exposes no browse-edgar helper, but its header discipline (the SEC
        # requires a contact User-Agent or it 403s) is reused verbatim.
        response = httpx.get(
            _BROWSE_EDGAR_URL,
            params=params,
            headers=edgar._headers(),
            timeout=_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        raise PeerError(
            f"EDGAR returned {e.response.status_code} for the SIC {sic} company list"
        ) from e
    except httpx.HTTPError as e:
        raise PeerError(f"Could not reach EDGAR to list SIC {sic} companies: {e}") from e


def _parse_cik_feed(xml_text: str) -> list[str]:
    """Pull zero-padded CIKs out of a browse-edgar ATOM company list.

    Two upstream quirks drive the implementation:
      1. <entry title> and <company-info name> are broken -- they serialise a Perl
         reference, e.g. "ARRAY(0x5645c382caa8)". Names must never be read from here.
      2. <feed> declares the Atom namespace as the default, so every descendant --
         including the SEC's own <cik> element -- inherits it. Matching on the local
         name after stripping "{ns}" is namespace-agnostic and survives EDGAR serving
         the feed with or without that declaration.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise PeerError(f"EDGAR returned an unparseable company feed: {e}") from e

    ciks: list[str] = []
    seen: set[str] = set()
    for element in root.iter():
        if element.tag.split("}")[-1] != "cik":
            continue
        raw = (element.text or "").strip()
        if not raw.isdigit():
            continue
        padded = edgar.pad_cik(raw)
        if padded not in seen:
            seen.add(padded)
            ciks.append(padded)
    return ciks


def find_peer_ciks(sic: str, exclude_cik: str, limit: int = _DEFAULT_PEER_LIMIT) -> list[dict]:
    """Listed companies sharing `sic`, excluding the subject. -> [{cik, ticker, name}]

    Unlisted filers are dropped: without a ticker they have no chart identity and are
    usually shells, subsidiaries or long-dead registrants that never left the SIC index.
    """
    sic_code = str(sic or "").strip()
    if not sic_code.isdigit() or not 2 <= len(sic_code) <= 4:
        raise PeerError(f"Invalid SIC code: {sic!r}")
    if limit <= 0:
        return []

    excluded = edgar.pad_cik(exclude_cik) if exclude_cik else None
    by_cik = _cik_to_company()

    peers: list[dict] = []
    seen: set[str] = set()
    for page in range(_MAX_FEED_PAGES):
        page_ciks = _parse_cik_feed(_fetch_feed_page(sic_code, page * _FEED_PAGE_SIZE))
        if not page_ciks:
            break

        for cik in page_ciks:
            if cik == excluded or cik in seen:
                continue
            company = by_cik.get(cik)
            if company is None:
                continue
            seen.add(cik)
            peers.append(
                {"cik": cik, "ticker": company["ticker"], "name": company["name"]}
            )
            if len(peers) >= limit:
                return peers

        # A short page means the SIC index is exhausted; asking for the next one just
        # buys an empty round trip.
        if len(page_ciks) < _FEED_PAGE_SIZE:
            break

    return peers


def _load_one_peer(peer: dict) -> dict:
    facts = _fetch_company_facts(peer["cik"])
    metrics = _xbrl_metrics()
    history = metrics.build_financial_history(facts)
    if not history:
        raise PeerError(f"No usable XBRL history for {peer.get('ticker')}")
    ratios = metrics.derived_ratios(history)
    if not ratios:
        raise PeerError(f"No derivable ratios for {peer.get('ticker')}")
    return {
        "cik": peer["cik"],
        "ticker": peer["ticker"],
        "name": peer["name"],
        "history": history,
        "ratios": ratios,
    }


def fetch_peer_metrics(peers: list[dict], budget_seconds: float = 60.0) -> list[dict]:
    """Fetch and derive metrics for each peer concurrently, within a wall-clock budget.

    Runs inside a Lambda with a hard timeout, so this is best-effort by design: a peer
    that 404s, times out or has unusable XBRL is skipped, and when the budget runs out
    whatever finished is returned rather than the whole comparison failing.
    """
    if not peers:
        return []

    deadline = time.monotonic() + max(budget_seconds, 0.0)
    results: list[dict] = []

    executor = ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(peers)))
    try:
        def guarded(peer: dict) -> Optional[dict]:
            # Checked inside the worker so queued peers are abandoned before they cost
            # a 4MB download, not merely ignored after paying for one.
            if time.monotonic() >= deadline:
                return None
            try:
                return _load_one_peer(peer)
            except Exception:
                return None

        pending = {executor.submit(guarded, peer) for peer in peers}
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                outcome = future.result()
                if outcome is not None:
                    results.append(outcome)
    finally:
        # Never block on in-flight downloads; the budget has already been honoured.
        executor.shutdown(wait=False, cancel_futures=True)

    # Threads complete out of order; a stable ticker sort keeps output reproducible.
    results.sort(key=lambda peer: peer["ticker"])
    return results


def _usable(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _format_value(value: float, unit: str) -> str:
    if unit == "usd":
        return f"${value:,.0f}"
    digits = 1 if unit in ("percent", "days") else 2
    return f"{value:.{digits}f}{_UNIT_SUFFIX.get(unit, '')}"


def _severity(percentile: int) -> str:
    if percentile >= _GREEN_PERCENTILE:
        return "green"
    if percentile >= _YELLOW_PERCENTILE:
        return "yellow"
    return "red"


def _rank_one_metric(
    key: str,
    label: str,
    unit: str,
    higher_is_better: bool,
    subject_value: float,
    peer_pairs: list[tuple[str, float]],
) -> dict:
    peer_values = [value for _, value in peer_pairs]
    cohort_values = peer_values + [subject_value]
    cohort_size = len(cohort_values)

    # Competition ranking (1224): rank 1 is the healthiest value given the polarity, and
    # everyone tied with the subject shares the subject's rank.
    if higher_is_better:
        better_count = sum(1 for value in peer_values if value > subject_value)
        best, worst = max(cohort_values), min(cohort_values)
    else:
        better_count = sum(1 for value in peer_values if value < subject_value)
        best, worst = min(cohort_values), max(cohort_values)
    rank = better_count + 1

    # Fraction of the cohort the subject strictly beats. Always oriented so that a
    # higher percentile is the healthier position, whichever way the metric points.
    percentile = int(round((cohort_size - rank) / cohort_size * 100))
    severity = _severity(percentile)

    ordered_peers = sorted(peer_pairs, key=lambda pair: pair[1], reverse=higher_is_better)

    return {
        "key": key,
        "label": label,
        "unit": unit,
        "subjectValue": round(subject_value, 4),
        "percentile": percentile,
        "rank": rank,
        "cohortSize": cohort_size,
        "median": round(_median(cohort_values), 4),
        "best": round(best, 4),
        "worst": round(worst, 4),
        "higherIsBetter": higher_is_better,
        "severity": severity,
        "interpretation": _interpretation(
            label, unit, subject_value, rank, cohort_size, _median(cohort_values), severity
        ),
        "peerValues": [
            {"ticker": ticker, "value": round(value, 4)} for ticker, value in ordered_peers
        ],
    }


def _interpretation(
    label: str,
    unit: str,
    subject_value: float,
    rank: int,
    cohort_size: int,
    median: float,
    severity: str,
) -> str:
    standing = {
        "green": "among the stronger names in the group",
        "yellow": "middle of the pack",
        "red": "among the weakest in the group",
    }[severity]
    return (
        f"{label} of {_format_value(subject_value, unit)} ranks {_ordinal(rank)} best "
        f"of {cohort_size} SIC peers (cohort median {_format_value(median, unit)}) — {standing}."
    )


def rank_metrics(subject: dict, peer_metrics: list[dict]) -> list[dict]:
    """Rank every comparable subject ratio against the peer cohort.

    `cohortSize` on each entry counts the subject plus the peers that actually reported
    that metric, so it varies per metric and is always at least _MIN_USABLE_PEERS + 1.
    """
    subject_ratios = (subject or {}).get("ratios") or {}
    if not isinstance(subject_ratios, dict):
        return []

    rankings: list[dict] = []
    for key, entry in subject_ratios.items():
        if not isinstance(entry, dict):
            continue
        higher_is_better = METRIC_POLARITY.get(key)
        if higher_is_better is None:
            continue

        unit = entry.get("unit") or "ratio"
        if unit not in _COMPARABLE_UNITS:
            continue

        subject_value = _usable(entry.get("value"))
        if subject_value is None:
            continue

        peer_pairs: list[tuple[str, float]] = []
        for peer in peer_metrics or []:
            peer_entry = (peer.get("ratios") or {}).get(key)
            if not isinstance(peer_entry, dict):
                continue
            peer_value = _usable(peer_entry.get("value"))
            if peer_value is None:
                continue
            peer_pairs.append((peer.get("ticker") or peer.get("cik") or "?", peer_value))

        if len(peer_pairs) < _MIN_USABLE_PEERS:
            continue

        rankings.append(
            _rank_one_metric(
                key,
                entry.get("label") or key,
                unit,
                higher_is_better,
                subject_value,
                peer_pairs,
            )
        )

    # Worst standing first: the point of the panel is to surface the outliers that a
    # single-filing read would never expose.
    rankings.sort(key=lambda item: (_SEVERITY_ORDER[item["severity"]], item["percentile"], item["key"]))
    return rankings


def build_peer_comparison(
    sic: str,
    sic_description: Optional[str],
    subject: dict,
    limit: int = _DEFAULT_PEER_LIMIT,
    budget_seconds: float = 60.0,
) -> dict:
    """Full peer panel for the analysed company, degrading gracefully to an explanation.

    Never raises for a thin or missing cohort — plenty of SIC codes have only one listed
    filer — so callers can render `unavailableReason` instead of losing the whole report.
    """
    result = {
        "sic": str(sic) if sic else None,
        "sicDescription": sic_description or None,
        "cohortSize": 0,
        "peers": [],
        "metrics": [],
        "unavailableReason": None,
    }

    if not sic:
        result["unavailableReason"] = "EDGAR does not list an SIC industry code for this filer."
        return result

    try:
        candidates = find_peer_ciks(str(sic), (subject or {}).get("cik") or "", limit=limit)
    except PeerError as e:
        result["unavailableReason"] = f"Could not list SIC {sic} peers: {e}"
        return result

    if not candidates:
        result["unavailableReason"] = (
            f"No other exchange-listed SEC filers share SIC {sic}."
        )
        return result

    peer_metrics = fetch_peer_metrics(candidates, budget_seconds=budget_seconds)
    result["cohortSize"] = len(peer_metrics)
    result["peers"] = [
        {"ticker": peer["ticker"], "name": peer["name"], "cik": peer["cik"]}
        for peer in peer_metrics
    ]

    if len(peer_metrics) < _MIN_USABLE_PEERS:
        result["unavailableReason"] = (
            f"Only {len(peer_metrics)} of {len(candidates)} SIC {sic} peers returned usable "
            f"XBRL data; at least {_MIN_USABLE_PEERS} are needed for a meaningful percentile."
        )
        return result

    result["metrics"] = rank_metrics(subject or {}, peer_metrics)
    if not result["metrics"]:
        result["unavailableReason"] = (
            f"{len(peer_metrics)} SIC {sic} peers were found, but no single ratio was "
            f"reported by both this company and at least {_MIN_USABLE_PEERS} of them."
        )
    return result
