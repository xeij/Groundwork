"""What the people who run the company did with their own shares.

Officers, directors and 10% owners must report every trade in their company's stock on
a Form 4, filed within two business days, as structured XML. That makes insider
behaviour the highest-signal free dataset EDGAR carries -- and the easiest to read
wrongly, because most of what appears on a Form 4 is not a decision about the stock:

* **Only codes P and S are open-market decisions.** A purchase (P) or sale (S) is
  somebody choosing to move their own money. An award (A) is pay. An option exercise
  (M) is a deadline. Withholding shares to cover the tax on a vest (F) is arithmetic.
  Counting grants as "buying" is the single most common way insider data gets
  misreported, so grants and withholding are tallied separately and kept out of every
  buy/sell figure here.
* **Selling is weak evidence; buying is strong.** Insiders sell for tuition, divorces
  and diversification, and most large sales run on a 10b5-1 plan adopted months
  earlier. They buy for one reason. Cluster buying -- several insiders buying
  independently inside a short window -- is the pattern with the most durable published
  record, so it is graded separately from the aggregate.
* **Scale only means something relative to the holder.** A $2m sale is noise from a
  founder and everything from a division president, so sales are measured against what
  that insider still holds afterwards rather than in dollars.

Derivative transactions are parsed but deliberately excluded from the buy/sell totals:
an option exercise is compensation, and when the resulting shares are sold the sale
itself appears as an ordinary S in the non-derivative table, so counting both would
double the trade.

Every number here is best-effort. Form 4s are fetched concurrently under a wall-clock
budget and a hard cap, and whatever arrives in time is reported alongside how much of
the record was actually read.
"""

import logging
import re
import threading
import time
import xml.etree.ElementTree as ElementTree
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, timedelta
from typing import Optional

from . import edgar

logger = logging.getLogger(__name__)

# Form 4 amends and supersedes; 3 is an initial statement of holdings (no transactions)
# and 5 is an annual catch-up for exempt transactions. Only 4 and 4/A carry the
# open-market trades this module is about.
_OWNERSHIP_FORMS = ("4", "4/A")

WINDOW_MONTHS = 12
# Two windows are read so this year's behaviour has last year's as a baseline.
_COMPARISON_WINDOWS = 2

# A Form 4 is a few kilobytes, so the cap is about latency inside a Lambda rather than
# bandwidth. Sixty covers a year comfortably for all but the largest boards.
MAX_FORMS = 60
BUDGET_SECONDS = 25.0
_MAX_WORKERS = 4
# The SEC publishes a 10 requests/second ceiling across all its hosts. peers.py holds
# its own gate for its own concurrent branch; both are set well under the limit so the
# two branches together still sit inside it.
_MIN_REQUEST_INTERVAL_SECONDS = 0.15

# Open-market decisions. Everything else on a Form 4 is compensation mechanics.
_BUY_CODE = "P"
_SELL_CODE = "S"
_GRANT_CODE = "A"
_TAX_WITHHOLDING_CODE = "F"

# Distinct insiders buying inside this many days of each other counts as a cluster.
_CLUSTER_WINDOW_DAYS = 90
_CLUSTER_MIN_BUYERS = 3

# Share of aggregate insider holdings sold in the window before the rate is called out.
_HEAVY_SELLING_PERCENT = 20.0
_SEVERE_SELLING_PERCENT = 40.0
# Share of one insider's own position sold before that insider is named individually.
_INDIVIDUAL_EXIT_PERCENT = 50.0

_10B5_1_RE = re.compile(r"10b5[-\s]?1", re.IGNORECASE)
_TRUE_VALUES = {"1", "true", "yes"}

_throttle_lock = threading.Lock()
_last_request_at = 0.0


class InsiderActivityError(Exception):
    pass


# --- XML parsing ----------------------------------------------------------------------


def _localname(tag: str) -> str:
    """Ownership XML is served with and without a namespace depending on vintage."""
    return tag.rpartition("}")[2]


def _child(element, name: str):
    if element is None:
        return None
    for child in element:
        if _localname(child.tag) == name:
            return child
    return None


def _path(element, *names):
    for name in names:
        element = _child(element, name)
        if element is None:
            return None
    return element


def _text(element, *names) -> Optional[str]:
    found = _path(element, *names) if names else element
    if found is None:
        return None
    text = (found.text or "").strip()
    return text or None


def _value(element, *names) -> Optional[str]:
    """Most ownership fields wrap their content in a <value> child, some do not.

    The wrapper exists so a field can carry a footnote reference instead of a value --
    a price "to be determined", say -- which is exactly the case that must read as
    missing rather than as zero.
    """
    found = _path(element, *names) if names else element
    if found is None:
        return None
    inner = _child(found, "value")
    return _text(inner if inner is not None else found)


def _number(element, *names) -> Optional[float]:
    raw = _value(element, *names)
    if raw is None:
        return None
    try:
        return float(raw.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _flag(element, *names) -> bool:
    raw = _value(element, *names)
    return bool(raw) and raw.strip().lower() in _TRUE_VALUES


def parse_ownership_form(xml_text: str) -> Optional[dict]:
    """One Form 4 XML into {owner, transactions}. Returns None if it is not parseable."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None

    owner_element = _child(root, "reportingOwner")
    relationship = _path(owner_element, "reportingOwnerRelationship")
    owner = {
        "name": _clean_name(_value(owner_element, "reportingOwnerId", "rptOwnerName")),
        "cik": _value(owner_element, "reportingOwnerId", "rptOwnerCik"),
        "isOfficer": _flag(relationship, "isOfficer"),
        "isDirector": _flag(relationship, "isDirector"),
        "isTenPercentOwner": _flag(relationship, "isTenPercentOwner"),
        "title": _value(relationship, "officerTitle"),
    }
    if not owner["name"]:
        return None

    footnote_element = _child(root, "footnotes")
    footnotes = {
        note.get("id"): (note.text or "")
        for note in (footnote_element if footnote_element is not None else [])
        if _localname(note.tag) == "footnote"
    }
    # The Rule 10b5-1 checkbox at document level applies to the whole form; individual
    # transactions can also point at a footnote describing the plan.
    document_planned = _flag(root, "aff10b5One")

    transactions = []
    for table_name, derivative in (("nonDerivativeTable", False), ("derivativeTable", True)):
        table = _child(root, table_name)
        if table is None:
            continue
        for element in table:
            if not _localname(element.tag).endswith("Transaction"):
                continue  # a Holding row states a position, not a trade
            parsed = _parse_transaction(element, footnotes, document_planned, derivative)
            if parsed is not None:
                transactions.append(parsed)

    return {"owner": owner, "transactions": transactions}


def _parse_transaction(element, footnotes: dict, document_planned: bool, derivative: bool):
    code = _value(element, "transactionCoding", "transactionCode")
    shares = _number(element, "transactionAmounts", "transactionShares")
    if not code or shares is None:
        return None

    price = _number(element, "transactionAmounts", "transactionPricePerShare")
    acquired = (_value(element, "transactionAmounts", "transactionAcquiredDisposedCode") or "").upper()
    return {
        "date": _value(element, "transactionDate"),
        "code": code.upper(),
        "shares": abs(shares),
        "price": price,
        # A price of zero is what a grant reports; it is not a $0 trade, so no value is
        # claimed rather than a misleading zero.
        "value": abs(shares) * price if price else None,
        "acquired": acquired == "A",
        "sharesOwnedAfter": _number(element, "postTransactionAmounts", "sharesOwnedFollowingTransaction"),
        "security": _value(element, "securityTitle"),
        "derivative": derivative,
        "planned": document_planned or _references_10b5_1(element, footnotes),
    }


def _references_10b5_1(element, footnotes: dict) -> bool:
    for node in element.iter():
        if _localname(node.tag) == "footnoteId":
            note = footnotes.get(node.get("id"), "")
            if _10B5_1_RE.search(note):
                return True
    return False


def _clean_name(name: Optional[str]) -> Optional[str]:
    """EDGAR reports owners as "COOK TIMOTHY D"; title-case it without mangling initials."""
    if not name:
        return None
    collapsed = " ".join(name.split())
    if collapsed != collapsed.upper():
        return collapsed  # already mixed case; leave the filer's own formatting alone
    return " ".join(part.capitalize() if len(part) > 1 else part for part in collapsed.split(" "))


# --- fetching -------------------------------------------------------------------------


def _throttle() -> None:
    global _last_request_at
    with _throttle_lock:
        gap = time.monotonic() - _last_request_at
        if gap < _MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - gap)
        _last_request_at = time.monotonic()


def _fetch_one(cik: str, filing: dict) -> Optional[dict]:
    _throttle()
    xml_text = edgar.fetch_ownership_document(
        cik, filing["accessionNumber"], filing["primaryDocument"]
    )
    parsed = parse_ownership_form(xml_text)
    if parsed is not None:
        parsed["filingDate"] = filing["filingDate"]
    return parsed


def ownership_filings(submissions: dict, since: date) -> list[dict]:
    """Form 4 rows from the submissions index, newest first."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form")
    if not isinstance(forms, list):
        return []

    def column(name: str) -> list:
        values = recent.get(name)
        return values if isinstance(values, list) and len(values) == len(forms) else [""] * len(forms)

    accessions = column("accessionNumber")
    filing_dates = column("filingDate")
    documents = column("primaryDocument")

    filings = []
    for i, form in enumerate(forms):
        if (form or "").strip() not in _OWNERSHIP_FORMS:
            continue
        filed = _parse_date(filing_dates[i])
        if filed is None or filed < since:
            continue
        filings.append(
            {
                "accessionNumber": accessions[i],
                "filingDate": filed,
                "primaryDocument": documents[i],
            }
        )

    filings.sort(key=lambda f: f["filingDate"], reverse=True)
    return filings


def fetch_forms(
    cik: str, filings: list[dict], budget_seconds: float = BUDGET_SECONDS
) -> list[dict]:
    """Download and parse Form 4s concurrently, abandoning the rest when time runs out.

    Same posture as peer benchmarking: this runs inside a Lambda with a hard timeout, so
    a form that 404s or arrives late is skipped rather than failing the analysis.
    """
    if not filings:
        return []

    deadline = time.monotonic() + max(budget_seconds, 0.0)
    parsed: list[dict] = []

    executor = ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(filings)))
    try:
        def guarded(filing: dict) -> Optional[dict]:
            if time.monotonic() >= deadline:
                return None
            try:
                return _fetch_one(cik, filing)
            except Exception:
                logger.debug("Skipping unreadable Form 4 %s", filing.get("accessionNumber"))
                return None

        pending = {executor.submit(guarded, filing) for filing in filings}
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                form = future.result()
                if form is not None:
                    parsed.append(form)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return parsed


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# --- aggregation ----------------------------------------------------------------------


def _blank_side() -> dict:
    return {"transactions": 0, "shares": 0.0, "value": 0.0, "insiders": 0, "valueKnown": True}


def summarize(forms: list[dict], window_start: date, window_end: date) -> dict:
    """Roll parsed forms up into the totals for one window, per insider and overall."""
    insiders: dict[str, dict] = {}
    buys = _blank_side()
    sells = _blank_side()
    granted_shares = 0.0
    withheld_shares = 0.0
    planned_sale_value = 0.0
    buy_dates: dict[str, date] = {}

    for form in forms:
        owner = form["owner"]
        name = owner["name"]
        record = insiders.setdefault(
            name,
            {
                "name": name,
                "title": owner.get("title"),
                "role": _role(owner),
                "buyShares": 0.0,
                "buyValue": 0.0,
                "sellShares": 0.0,
                "sellValue": 0.0,
                "grantedShares": 0.0,
                "sharesOwnedAfter": None,
                "lastTransactionDate": None,
                "plannedSales": 0,
                "openMarketSales": 0,
            },
        )
        # An insider filing several forms may report a title on only one of them.
        record["title"] = record["title"] or owner.get("title")

        for transaction in form["transactions"]:
            when = _parse_date(transaction["date"])
            if when is None or not (window_start <= when <= window_end):
                continue

            # Ownership after the trade is tracked from the newest transaction seen,
            # whichever code it carried, since grants and vests move the position too.
            if transaction["sharesOwnedAfter"] is not None and not transaction["derivative"]:
                if record["lastTransactionDate"] is None or when >= _parse_date(record["lastTransactionDate"]):
                    record["sharesOwnedAfter"] = transaction["sharesOwnedAfter"]
                    record["lastTransactionDate"] = when.isoformat()

            if transaction["derivative"]:
                continue  # see the module docstring: exercises are not decisions

            code = transaction["code"]
            if code == _BUY_CODE:
                _add(buys, transaction)
                record["buyShares"] += transaction["shares"]
                record["buyValue"] += transaction["value"] or 0.0
                if name not in buy_dates or when < buy_dates[name]:
                    buy_dates[name] = when
            elif code == _SELL_CODE:
                _add(sells, transaction)
                record["sellShares"] += transaction["shares"]
                record["sellValue"] += transaction["value"] or 0.0
                record["openMarketSales"] += 1
                if transaction["planned"]:
                    record["plannedSales"] += 1
                    planned_sale_value += transaction["value"] or 0.0
            elif code == _GRANT_CODE:
                granted_shares += transaction["shares"]
                record["grantedShares"] += transaction["shares"]
            elif code == _TAX_WITHHOLDING_CODE:
                withheld_shares += transaction["shares"]

    buys["insiders"] = sum(1 for r in insiders.values() if r["buyShares"] > 0)
    sells["insiders"] = sum(1 for r in insiders.values() if r["sellShares"] > 0)

    return {
        "buys": buys,
        "sells": sells,
        "netShares": buys["shares"] - sells["shares"],
        "netValue": buys["value"] - sells["value"],
        "grantedShares": granted_shares,
        "taxWithheldShares": withheld_shares,
        "plannedSaleValue": planned_sale_value,
        "insiders": sorted(
            (r for r in insiders.values() if r["buyShares"] or r["sellShares"]),
            key=lambda r: r["sellValue"] + r["buyValue"],
            reverse=True,
        ),
        "buyDates": buy_dates,
    }


def _add(side: dict, transaction: dict) -> None:
    side["transactions"] += 1
    side["shares"] += transaction["shares"]
    if transaction["value"] is None:
        # One priceless row makes the dollar total an understatement, and saying so is
        # cheaper than quietly reporting a number that is too low.
        side["valueKnown"] = False
    else:
        side["value"] += transaction["value"]


def _role(owner: dict) -> str:
    if owner.get("isOfficer"):
        return "officer"
    if owner.get("isDirector"):
        return "director"
    if owner.get("isTenPercentOwner"):
        return "10% owner"
    return "insider"


# --- signals --------------------------------------------------------------------------


def _signals(current: dict, prior: dict, window_months: int) -> list[dict]:
    signals = []
    buys, sells = current["buys"], current["sells"]

    cluster = _cluster_buying(current)
    if cluster:
        signals.append(cluster)
    elif buys["insiders"] > 0 and sells["shares"] <= buys["shares"]:
        signals.append(
            {
                "key": "net_buying",
                "label": "Insiders were net buyers",
                "severity": "green",
                "interpretation": (
                    f"{_people(buys['insiders'])} bought {_shares(buys['shares'])} shares on "
                    f"the open market in the last {window_months} months, more than the "
                    "insider group sold. Insiders sell for many reasons and buy for one."
                ),
            }
        )

    selling = _selling_pressure(current, window_months)
    if selling:
        signals.append(selling)

    signals.extend(_individual_exits(current, window_months))

    if buys["transactions"] == 0 and sells["transactions"] == 0:
        signals.append(
            {
                "key": "no_open_market_activity",
                "label": "No insider bought or sold on the open market",
                "severity": "green",
                "interpretation": (
                    f"Over the last {window_months} months the only movements in insider "
                    "holdings were grants, vesting and shares withheld to cover tax. None "
                    "of those is a decision about the stock, so there is nothing to read "
                    "into them either way."
                ),
            }
        )

    trend = _selling_trend(current, prior, window_months)
    if trend:
        signals.append(trend)

    return signals


def _cluster_buying(current: dict) -> Optional[dict]:
    """Several insiders buying independently inside a short window."""
    dates = sorted(current["buyDates"].values())
    if len(dates) < _CLUSTER_MIN_BUYERS:
        return None

    for i, start in enumerate(dates):
        within = [d for d in dates[i:] if (d - start).days <= _CLUSTER_WINDOW_DAYS]
        if len(within) >= _CLUSTER_MIN_BUYERS:
            return {
                "key": "cluster_buying",
                "label": "Several insiders bought at once",
                "severity": "green",
                "interpretation": (
                    f"{_people(len(within))} bought shares on the open market within "
                    f"{_CLUSTER_WINDOW_DAYS} days of each other, starting "
                    f"{start.isoformat()}. Independent buying by several insiders at the "
                    "same time is the insider pattern with the most durable record in the "
                    "research; a single buyer is far weaker evidence."
                ),
                "detail": {
                    "buyers": float(len(within)),
                    "windowDays": float(_CLUSTER_WINDOW_DAYS),
                    "sharesBought": current["buys"]["shares"],
                },
            }
    return None


def _selling_pressure(current: dict, window_months: int) -> Optional[dict]:
    sells = current["sells"]
    if sells["shares"] <= 0:
        return None

    held_after = sum(r["sharesOwnedAfter"] or 0.0 for r in current["insiders"])
    base = held_after + sells["shares"]
    share_sold = (sells["shares"] / base * 100) if base > 0 else None
    if share_sold is None or share_sold < _HEAVY_SELLING_PERCENT:
        return None

    planned = current["plannedSaleValue"]
    planned_note = ""
    if sells["value"] > 0:
        planned_percent = planned / sells["value"] * 100
        if planned_percent >= 50:
            planned_note = (
                f" About {planned_percent:.0f}% of that was sold under 10b5-1 plans, which "
                "are adopted months in advance and are therefore weaker evidence about "
                "what insiders think today."
            )
        elif planned_percent <= 10:
            planned_note = (
                " Almost none of it ran through a 10b5-1 plan, so these were discretionary "
                "sales made with current knowledge rather than pre-scheduled ones."
            )

    return {
        "key": "heavy_insider_selling",
        "label": "Insiders sold a large share of what they held",
        "severity": "red" if share_sold >= _SEVERE_SELLING_PERCENT else "yellow",
        "interpretation": (
            f"{_people(sells['insiders'])} sold {_shares(sells['shares'])} shares in the "
            f"last {window_months} months -- {share_sold:.0f}% of the stock that group "
            f"held at the start.{planned_note}"
        ),
        "detail": {
            "percentOfHoldingsSold": round(share_sold, 1),
            "sharesSold": sells["shares"],
            "sellers": float(sells["insiders"]),
            "plannedSaleValue": planned,
        },
    }


def _individual_exits(current: dict, window_months: int) -> list[dict]:
    """Named insiders who sold most of their own position."""
    exits = []
    for record in current["insiders"]:
        held_after = record["sharesOwnedAfter"]
        if not record["sellShares"] or held_after is None:
            continue
        base = held_after + record["sellShares"]
        if base <= 0:
            continue
        percent = record["sellShares"] / base * 100
        if percent < _INDIVIDUAL_EXIT_PERCENT:
            continue
        title = record["title"] or record["role"]
        exits.append(
            {
                "key": f"insider_exit_{_slug(record['name'])}",
                "label": f"{record['name']} sold most of their position",
                "severity": "red" if percent >= 80 else "yellow",
                "interpretation": (
                    f"{record['name']} ({title}) sold {_shares(record['sellShares'])} shares "
                    f"in the last {window_months} months, {percent:.0f}% of what they held, "
                    f"leaving {_shares(held_after)}. Holdings are read from the Form 4s "
                    "themselves, which report only the securities on each form, so shares "
                    "held in other forms of ownership are not counted."
                ),
                "detail": {
                    "percentOfPositionSold": round(percent, 1),
                    "sharesSold": record["sellShares"],
                    "sharesRemaining": held_after,
                },
            }
        )
    return exits[:3]


def _selling_trend(current: dict, prior: Optional[dict], window_months: int) -> Optional[dict]:
    """This window's selling against the one before it, when both are readable."""
    if not prior or prior["sells"]["shares"] <= 0 or current["sells"]["shares"] <= 0:
        return None

    change = (current["sells"]["shares"] / prior["sells"]["shares"] - 1) * 100
    if change < 100:
        return None
    return {
        "key": "selling_accelerated",
        "label": "Insider selling accelerated",
        "severity": "yellow",
        "interpretation": (
            f"Insiders sold {_shares(current['sells']['shares'])} shares in the last "
            f"{window_months} months against {_shares(prior['sells']['shares'])} in the "
            f"{window_months} months before that, an increase of {change:.0f}%. A rising "
            "share price alone can produce this, since plan sales are often set in share "
            "counts rather than dollars."
        ),
        "detail": {
            "sharesSold": current["sells"]["shares"],
            "priorSharesSold": prior["sells"]["shares"],
            "changePercent": round(change, 1),
        },
    }


def _people(count: int) -> str:
    return "One insider" if count == 1 else f"{count} insiders"


def _shares(count: float) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}m"
    if count >= 1_000:
        return f"{count / 1_000:.0f}k"
    return f"{count:,.0f}"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# --- entry point ----------------------------------------------------------------------


def build_insider_activity(
    cik: str,
    submissions: dict,
    window_months: int = WINDOW_MONTHS,
    today: Optional[date] = None,
    max_forms: int = MAX_FORMS,
    budget_seconds: float = BUDGET_SECONDS,
) -> Optional[dict]:
    """Insider open-market activity over the last `window_months`, with the prior year
    as a baseline.

    Returns None when the company has no Form 4s in the window at all, which is a real
    answer for a filer with no Section 16 activity but is not worth a card.
    """
    today = today or date.today()
    window_days = int(round(window_months * 30.44))
    current_start = today - timedelta(days=window_days)
    prior_start = today - timedelta(days=window_days * _COMPARISON_WINDOWS)

    filings = ownership_filings(submissions, prior_start)
    if not filings:
        return None

    capped = filings[:max_forms]
    forms = fetch_forms(cik, capped, budget_seconds=budget_seconds)
    if not forms:
        return None

    current = summarize(forms, current_start, today)
    prior = summarize(forms, prior_start, current_start - timedelta(days=1))

    # The cap and the budget both bite oldest-first, so the prior window is the half
    # that degrades. Saying which half is incomplete keeps "quiet year" apart from
    # "we stopped reading".
    prior_complete = len(forms) == len(filings) == len(capped)

    return {
        "windowMonths": window_months,
        "windowStart": current_start.isoformat(),
        "asOf": today.isoformat(),
        "summary": _public_summary(current),
        "priorSummary": _public_summary(prior) if prior_complete else None,
        "signals": _signals(current, prior if prior_complete else None, window_months),
        "insiders": [_public_insider(r) for r in current["insiders"][:8]],
        "coverage": {
            "formsFound": len(filings),
            "formsRead": len(forms),
            "complete": prior_complete,
            "note": None
            if prior_complete
            else (
                f"{len(forms)} of {len(filings)} Form 4s filed in this period were read "
                "before the time budget ran out, so the totals below are a floor, not a "
                "complete tally."
            ),
        },
    }


def _public_summary(window: dict) -> dict:
    """The stored shape: internal bookkeeping (buyDates, per-insider rows) is dropped."""
    return {
        "buyShares": window["buys"]["shares"],
        "buyValue": window["buys"]["value"],
        "buyTransactions": window["buys"]["transactions"],
        "buyers": window["buys"]["insiders"],
        "buyValueComplete": window["buys"]["valueKnown"],
        "sellShares": window["sells"]["shares"],
        "sellValue": window["sells"]["value"],
        "sellTransactions": window["sells"]["transactions"],
        "sellers": window["sells"]["insiders"],
        "sellValueComplete": window["sells"]["valueKnown"],
        "netShares": window["netShares"],
        "netValue": window["netValue"],
        "grantedShares": window["grantedShares"],
        "taxWithheldShares": window["taxWithheldShares"],
        "plannedSaleValue": window["plannedSaleValue"],
    }


def _public_insider(record: dict) -> dict:
    return {
        "name": record["name"],
        "title": record["title"],
        "role": record["role"],
        "buyShares": record["buyShares"],
        "buyValue": record["buyValue"],
        "sellShares": record["sellShares"],
        "sellValue": record["sellValue"],
        "sharesOwnedAfter": record["sharesOwnedAfter"],
        "plannedSales": record["plannedSales"],
        "openMarketSales": record["openMarketSales"],
        "lastTransactionDate": record["lastTransactionDate"],
    }
