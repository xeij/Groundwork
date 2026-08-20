"""What a company's filing *behaviour* says, read off the EDGAR submissions index.

None of this is in the 10-K. It comes from the same submissions JSON the pipeline
already downloads to find the filing, and it answers questions the annual report is
structurally incapable of answering about itself: has this company had to tell the
market its old numbers were wrong, has it changed auditors, how often do its officers
leave, and is it taking longer every year to close its books.

Three ideas do most of the work here:

* **8-K item codes are a machine-readable event log.** Every 8-K declares which of the
  SEC's numbered items triggered it. Item 4.02 is "the financial statements you already
  relied on should not be relied upon" -- a restatement, self-reported. Item 4.01 is an
  auditor change. Nobody has to read anything for these; they are already tagged.
* **Repeats matter more than instances.** One Item 5.02 is a director retiring. Four in
  two years is churn. Events are therefore grouped by kind and graded on their rate,
  never emitted one row per filing.
* **The gap between period end and filing date is a stress gauge.** It is stable for a
  healthy filer -- the same auditors close the same books on the same calendar. A year
  that lands materially later than the company's own norm is the cheapest early warning
  in the whole dataset, and an NT 10-K makes it explicit.

Everything is computed from the `recent` filing block, which EDGAR caps at roughly the
last thousand filings. For a company that files heavily that block can start *after* the
requested window, so the covered window is reported alongside the findings rather than
letting a quiet stretch be read as a clean record.
"""

import re
from datetime import date, timedelta
from typing import Optional

# Item codes carry their own meaning, so only the ones that say something about
# reporting quality or corporate stress are surfaced. Routine items (2.02 earnings
# releases, 7.01 Reg FD, 9.01 exhibits) fire constantly and are pure noise here.
_NOTABLE_8K_ITEMS: dict[str, dict] = {
    "4.02": {
        "key": "non_reliance",
        "label": "Told investors not to rely on previously issued financials",
        "severity": "red",
        "explanation": (
            "The company filed under Item 4.02, which is the SEC's designated way of "
            "saying that financial statements it already published should no longer be "
            "relied upon. This is a restatement announced by the company itself, not an "
            "outside allegation, and it is the single strongest reporting-quality signal "
            "in the 8-K vocabulary."
        ),
    },
    "1.03": {
        "key": "bankruptcy",
        "label": "Bankruptcy or receivership",
        "severity": "red",
        "explanation": (
            "An Item 1.03 filing reports a bankruptcy or receivership proceeding "
            "involving the company."
        ),
    },
    "3.01": {
        "key": "listing_deficiency",
        "label": "Delisting notice or listing-rule failure",
        "severity": "red",
        "explanation": (
            "Item 3.01 covers notice from an exchange that the company no longer meets "
            "the requirements to stay listed -- typically a share price, market value or "
            "late-filing failure."
        ),
    },
    "2.04": {
        "key": "obligation_acceleration",
        "label": "Event accelerating a debt obligation",
        "severity": "red",
        "explanation": (
            "Item 2.04 reports a triggering event that accelerates or increases a direct "
            "financial obligation -- in practice, usually a breached loan covenant. Debt "
            "that was long-term on the balance sheet can become due immediately."
        ),
    },
    "4.01": {
        "key": "auditor_change",
        "label": "Changed auditors",
        "severity": "yellow",
        "explanation": (
            "Item 4.01 reports a change of certifying accountant. Most auditor changes "
            "are ordinary -- fee negotiations, rotation policies, an acquirer aligning "
            "auditors -- but a change that follows a disagreement over accounting "
            "treatment has to be disclosed in the same filing, so the 8-K itself is worth "
            "opening."
        ),
    },
    "2.06": {
        "key": "material_impairment",
        "label": "Material impairment",
        "severity": "yellow",
        "explanation": (
            "Item 2.06 reports a write-down of assets whose carrying value the company no "
            "longer believes it can recover. It is an admission that something bought or "
            "built is worth materially less than the balance sheet said."
        ),
    },
    "5.02": {
        "key": "officer_departure",
        "label": "Officer or director departures and appointments",
        "severity": "yellow",
        "explanation": (
            "Item 5.02 covers departures, elections and appointments of directors and "
            "senior officers. Individually these are routine; a cluster of them, "
            "particularly around a fiscal year end, is the pattern worth noticing."
        ),
    },
    "5.03": {
        "key": "fiscal_year_change",
        "label": "Change of fiscal year or governing documents",
        "severity": "yellow",
        "explanation": (
            "Item 5.03 covers amendments to the articles or bylaws and changes to the "
            "fiscal year. A changed fiscal year end breaks year-over-year comparability, "
            "including for the numbers computed elsewhere in this analysis."
        ),
    },
}

# Forms that are themselves the signal, independent of any item code.
_NOTABLE_FORMS: dict[str, dict] = {
    "NT 10-K": {
        "key": "late_annual_report",
        "label": "Filed late notification for an annual report",
        "severity": "red",
        "explanation": (
            "Form 12b-25 (\"NT\") is filed when a company cannot deliver a report on "
            "time. For an annual report it usually means the audit is unfinished, and the "
            "reason given on the form is disclosed on the form itself."
        ),
    },
    "NT 10-Q": {
        "key": "late_quarterly_report",
        "label": "Filed late notification for a quarterly report",
        "severity": "yellow",
        "explanation": (
            "Form 12b-25 for a quarterly report. One can be a systems problem; a repeated "
            "pattern points at an accounting function that cannot close its books."
        ),
    },
    "10-K/A": {
        "key": "amended_annual_report",
        "label": "Amended an annual report after filing it",
        "severity": "yellow",
        "explanation": (
            "A 10-K/A amends an annual report already filed. Many are narrow -- adding "
            "Part III when a proxy slipped, fixing an exhibit -- but a full amendment "
            "restating the financial statements is filed the same way, so the amendment "
            "itself is worth opening to see which kind it is."
        ),
    },
    "10-Q/A": {
        "key": "amended_quarterly_report",
        "label": "Amended a quarterly report after filing it",
        "severity": "yellow",
        "explanation": "A 10-Q/A amends a quarterly report that was already filed.",
    },
}

# SEC filing deadlines, in days after fiscal year end, by the filer status EDGAR
# reports in `category`. A missed deadline is a legal fact, not a judgement call.
_DEADLINE_DAYS: dict[str, int] = {
    "large accelerated filer": 60,
    "accelerated filer": 75,
    "non-accelerated filer": 90,
}
_DEFAULT_DEADLINE_DAYS = 90

# A year that closes this many days later than the company's own norm is called out.
_LAG_DRIFT_YELLOW_DAYS = 7
_LAG_DRIFT_RED_DAYS = 21

# Departures/appointments in the window before the rate reads as churn rather than turnover.
_DEPARTURE_YELLOW_COUNT = 3
_DEPARTURE_RED_COUNT = 6

_ITEM_CODE_RE = re.compile(r"\b(\d\.\d\d)\b")
_ARCHIVE_FOLDER_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/"

DEFAULT_WINDOW_YEARS = 3
MAX_OCCURRENCES_PER_EVENT = 8

# Severity ordering for the event list; within a severity, most recent first.
_SEVERITY_RANK = {"red": 0, "yellow": 1, "green": 2}


def build_filing_history(
    submissions: dict,
    window_years: int = DEFAULT_WINDOW_YEARS,
    today: Optional[date] = None,
) -> Optional[dict]:
    """Grade a filer's disclosure record over the last `window_years`.

    Returns None only when the submissions blob carries no usable filing block at all;
    an uneventful filer returns a real result with an empty event list, because "we
    looked and found nothing" and "we could not look" are different answers.
    """
    if not isinstance(submissions, dict):
        return None

    recent = (submissions.get("filings") or {}).get("recent") or {}
    filings = _rows(recent)
    if not filings:
        return None

    today = today or date.today()
    window_start = today - timedelta(days=365 * max(window_years, 1))
    cik = str(submissions.get("cik") or "").lstrip("0") or "0"

    in_window = [f for f in filings if f["filingDate"] and f["filingDate"] >= window_start]
    events = _collect_events(in_window, cik, window_years)
    events.extend(_former_name_events(submissions, window_start))
    # Two stable passes: most recent first within each severity, worst severity first.
    events.sort(key=_latest_date, reverse=True)
    events.sort(key=lambda e: _SEVERITY_RANK.get(e["severity"], 3))

    return {
        "windowYears": window_years,
        "windowStart": window_start.isoformat(),
        "coverage": _coverage(filings, window_start),
        "filerCategory": (submissions.get("category") or "").strip() or None,
        "events": events,
        "filingLag": _filing_lag(filings, submissions.get("category")),
        "cadence": _cadence(filings, today),
    }


# --- reading the submissions block ----------------------------------------------------


def _rows(recent: dict) -> list[dict]:
    """EDGAR's filing block is column-oriented; transpose it into rows we can filter."""
    forms = recent.get("form")
    if not isinstance(forms, list) or not forms:
        return []

    def column(name: str) -> list:
        values = recent.get(name)
        return values if isinstance(values, list) and len(values) == len(forms) else [""] * len(forms)

    accessions = column("accessionNumber")
    filing_dates = column("filingDate")
    report_dates = column("reportDate")
    documents = column("primaryDocument")
    items = column("items")

    return [
        {
            "form": (forms[i] or "").strip(),
            "accessionNumber": accessions[i],
            "filingDate": _parse_date(filing_dates[i]),
            "reportDate": _parse_date(report_dates[i]),
            "primaryDocument": documents[i],
            "items": _ITEM_CODE_RE.findall(items[i] or ""),
        }
        for i in range(len(forms))
    ]


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _filing_url(cik: str, filing: dict) -> Optional[str]:
    """Link to the filing itself, falling back to its folder when the document is odd.

    Ownership forms and older filings carry primary documents that the archive path
    rules reject; the folder index always resolves, and a link that lands one click away
    beats a finding the reader cannot check.
    """
    accession = str(filing.get("accessionNumber") or "").replace("-", "")
    if not accession.isdigit():
        return None
    folder = _ARCHIVE_FOLDER_URL.format(cik_int=int(cik), accession=accession)
    document = str(filing.get("primaryDocument") or "")
    if document and ".." not in document:
        return folder + document
    return folder


# --- events ---------------------------------------------------------------------------


def _collect_events(filings: list[dict], cik: str, window_years: int) -> list[dict]:
    """Group notable filings by kind, newest occurrence first within each group."""
    grouped: dict[str, dict] = {}

    for filing in filings:
        for spec in _specs_for(filing):
            group = grouped.setdefault(
                spec["key"],
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "severity": spec["severity"],
                    "explanation": spec["explanation"],
                    "occurrences": [],
                },
            )
            group["occurrences"].append(
                {
                    "date": filing["filingDate"].isoformat(),
                    "form": filing["form"],
                    "url": _filing_url(cik, filing),
                }
            )

    events = []
    for group in grouped.values():
        group["occurrences"].sort(key=lambda o: o["date"], reverse=True)
        count = len(group["occurrences"])
        severity = _graded_severity(group["key"], group["severity"], count)
        events.append(
            {
                "key": group["key"],
                "label": group["label"],
                "severity": severity,
                "count": count,
                # Occurrences are capped for payload size; the count above is the truth.
                "occurrences": group["occurrences"][:MAX_OCCURRENCES_PER_EVENT],
                "interpretation": _event_interpretation(group, count, severity, window_years),
            }
        )
    return events


def _specs_for(filing: dict) -> list[dict]:
    form = filing["form"]
    if form in _NOTABLE_FORMS:
        return [_NOTABLE_FORMS[form]]
    if form.startswith("8-K"):
        return [_NOTABLE_8K_ITEMS[item] for item in filing["items"] if item in _NOTABLE_8K_ITEMS]
    return []


def _graded_severity(key: str, base: str, count: int) -> str:
    """Rate, not instance, for the events that are individually routine."""
    if key == "officer_departure":
        if count >= _DEPARTURE_RED_COUNT:
            return "red"
        return "yellow" if count >= _DEPARTURE_YELLOW_COUNT else "green"
    if key in ("late_quarterly_report", "amended_quarterly_report") and count >= 3:
        return "red"
    return base


def _event_interpretation(group: dict, count: int, severity: str, window_years: int) -> str:
    dates = ", ".join(o["date"] for o in group["occurrences"][:3])
    more = f" and {count - 3} more" if count > 3 else ""
    when = f"Filed {count}× in the last {window_years} years ({dates}{more}). "
    if count == 1:
        when = f"Filed once, on {group['occurrences'][0]['date']}. "

    tail = ""
    if group["key"] == "officer_departure":
        if severity == "green":
            tail = (
                " At this rate it reads as ordinary board and management turnover rather "
                "than instability."
            )
        else:
            tail = (
                " That is a high rate of change in the people who sign and certify these "
                "filings, which is worth understanding before trusting a turnaround story."
            )
    return when + group["explanation"] + tail


def _former_name_events(submissions: dict, window_start: date) -> list[dict]:
    """A recent name change is a fact about the company that the 10-K states nowhere."""
    former_names = submissions.get("formerNames")
    if not isinstance(former_names, list):
        return []

    recent_changes = []
    for entry in former_names:
        if not isinstance(entry, dict):
            continue
        changed_to = _parse_date(str(entry.get("to") or "")[:10])
        if changed_to and changed_to >= window_start and entry.get("name"):
            recent_changes.append({"date": changed_to.isoformat(), "name": entry["name"]})

    if not recent_changes:
        return []

    recent_changes.sort(key=lambda c: c["date"], reverse=True)
    names = ", ".join(c["name"] for c in recent_changes)
    return [
        {
            "key": "former_name",
            "label": "Changed its registered name recently",
            "severity": "yellow",
            "count": len(recent_changes),
            "occurrences": [
                {"date": c["date"], "form": "Name change", "url": None} for c in recent_changes
            ],
            "interpretation": (
                f"This filer previously reported to the SEC as {names}. A rename is often "
                "an ordinary rebrand or the result of a merger, but it also means that "
                "press coverage, analyst notes and litigation records from before the "
                "change are filed under a different name than the one on this report."
            ),
        }
    ]


def _latest_date(event: dict) -> str:
    return event["occurrences"][0]["date"] if event["occurrences"] else ""


# --- how long it takes them to close the books ----------------------------------------


def _filing_lag(filings: list[dict], category: Optional[str]) -> Optional[dict]:
    """Days from fiscal year end to 10-K filing, this year against the company's own norm."""
    lags = []
    for filing in filings:
        if filing["form"] != "10-K" or not filing["filingDate"] or not filing["reportDate"]:
            continue
        days = (filing["filingDate"] - filing["reportDate"]).days
        # A negative or absurd gap means the report date is mis-tagged, not that the
        # company filed early by a year.
        if 0 <= days <= 400:
            lags.append(
                {
                    "periodEnd": filing["reportDate"].isoformat(),
                    "filingDate": filing["filingDate"].isoformat(),
                    "days": days,
                }
            )

    if not lags:
        return None

    lags.sort(key=lambda entry: entry["periodEnd"])
    current = lags[-1]
    history = lags[:-1]
    deadline = _DEADLINE_DAYS.get((category or "").strip().lower(), _DEFAULT_DEADLINE_DAYS)

    typical = _median([entry["days"] for entry in history]) if history else None
    drift = None if typical is None else current["days"] - typical

    severity, interpretation = _lag_verdict(current, typical, drift, deadline, category)
    return {
        "days": current["days"],
        "periodEnd": current["periodEnd"],
        "filingDate": current["filingDate"],
        "typicalDays": None if typical is None else round(typical, 1),
        "driftDays": None if drift is None else round(drift, 1),
        "deadlineDays": deadline,
        "severity": severity,
        "interpretation": interpretation,
        "trend": lags[-6:],
    }


def _lag_verdict(
    current: dict,
    typical: Optional[float],
    drift: Optional[float],
    deadline: int,
    category: Optional[str],
) -> tuple[str, str]:
    filer = (category or "").strip() or "this filer class"
    took = (
        f"This 10-K was filed {current['days']} days after the fiscal year ended "
        f"({current['periodEnd']} to {current['filingDate']})."
    )

    if current["days"] > deadline:
        return (
            "red",
            f"{took} The SEC deadline for {filer} is {deadline} days, so this one landed "
            "past it. That normally requires a late-filing notification on Form 12b-25, "
            "and the reason it gives is the thing to read.",
        )

    if drift is None:
        return ("green", f"{took} There is no prior 10-K in the window to compare that against.")

    if drift >= _LAG_DRIFT_RED_DAYS:
        return (
            "red",
            f"{took} That is {drift:.0f} days slower than this company's own recent norm of "
            f"{typical:.0f} days. Closing the books materially later than usual, without "
            "missing the deadline, is a quiet signal: audits stretch when there is "
            "something to resolve.",
        )
    if drift >= _LAG_DRIFT_YELLOW_DAYS:
        return (
            "yellow",
            f"{took} That is {drift:.0f} days slower than its recent norm of {typical:.0f} "
            "days -- worth noting, not alarming on its own.",
        )
    if drift <= -_LAG_DRIFT_YELLOW_DAYS:
        return (
            "green",
            f"{took} That is {abs(drift):.0f} days faster than its recent norm of "
            f"{typical:.0f} days.",
        )
    return (
        "green",
        f"{took} That is in line with its recent norm of {typical:.0f} days and inside the "
        f"{deadline}-day deadline for {filer}.",
    )


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


# --- how much they file ---------------------------------------------------------------


def _cadence(filings: list[dict], today: date) -> dict:
    """8-K volume this year against last year.

    Not a red flag by itself -- an acquisitive year generates 8-Ks -- but a doubling is
    context for everything else on the page.
    """
    last_12 = today - timedelta(days=365)
    prior_12 = today - timedelta(days=730)

    def count(form_prefix: str, start: date, end: date) -> int:
        return sum(
            1
            for f in filings
            if f["form"].startswith(form_prefix) and f["filingDate"] and start <= f["filingDate"] < end
        )

    current = count("8-K", last_12, today + timedelta(days=1))
    prior = count("8-K", prior_12, last_12)
    return {
        "eightKLast12Months": current,
        "eightKPrior12Months": prior,
        "amendments": sum(1 for f in filings if f["form"].endswith("/A") and f["filingDate"] and f["filingDate"] >= prior_12),
    }


def _coverage(filings: list[dict], window_start: date) -> dict:
    """How far back the `recent` block actually reaches.

    EDGAR caps it at roughly a thousand filings. A company that files hundreds of
    ownership forms a year can exhaust that inside the requested window, and a truncated
    record must not be read as a clean one.
    """
    dates = [f["filingDate"] for f in filings if f["filingDate"]]
    earliest = min(dates) if dates else None
    complete = earliest is not None and earliest <= window_start
    note = None
    if not complete and earliest is not None:
        note = (
            f"EDGAR's recent-filing index only reaches back to {earliest.isoformat()} for "
            "this company, so anything before that date is outside what was checked."
        )
    return {
        "earliestFilingDate": earliest.isoformat() if earliest else None,
        "complete": complete,
        "note": note,
    }
