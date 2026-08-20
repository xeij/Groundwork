"""Filing-behaviour signals read off the EDGAR submissions index.

Every fixture here is a hand-built submissions block, so the dates and item codes that
drive each assertion are visible in the test rather than buried in a captured payload.
"""

from datetime import date

from app.services.filing_history import build_filing_history

TODAY = date(2026, 8, 19)


def submissions(filings: list[dict], **extra) -> dict:
    """Transpose row-shaped filings into the column-oriented block EDGAR actually serves."""
    columns = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument", "items")
    block = {column: [f.get(column, "") for f in filings] for column in columns}
    payload = {"cik": "0000320193", "filings": {"recent": block}}
    payload.update(extra)
    return payload


def filing(form: str, filing_date: str, **kwargs) -> dict:
    return {
        "form": form,
        "filingDate": filing_date,
        "accessionNumber": kwargs.get("accessionNumber", "0000320193-26-000001"),
        "reportDate": kwargs.get("reportDate", ""),
        "primaryDocument": kwargs.get("primaryDocument", "doc.htm"),
        "items": kwargs.get("items", ""),
    }


def event(result: dict, key: str) -> dict | None:
    return next((e for e in result["events"] if e["key"] == key), None)


# --- 8-K item codes -------------------------------------------------------------------


def test_non_reliance_item_is_flagged_red():
    result = build_filing_history(
        submissions([filing("8-K", "2026-03-02", items="4.02,9.01")]), today=TODAY
    )

    found = event(result, "non_reliance")
    assert found["severity"] == "red"
    assert found["count"] == 1
    assert "2026-03-02" in found["interpretation"]


def test_routine_8k_items_produce_no_events():
    # 2.02 (earnings release), 7.01 (Reg FD) and 9.01 (exhibits) fire constantly.
    result = build_filing_history(
        submissions(
            [
                filing("8-K", "2026-02-01", items="2.02,9.01"),
                filing("8-K", "2026-05-01", items="7.01"),
            ]
        ),
        today=TODAY,
    )

    assert result["events"] == []


def test_item_codes_are_read_from_prose_item_lists():
    # Older submissions rows spell the items out rather than listing bare codes.
    result = build_filing_history(
        submissions([filing("8-K", "2026-03-02", items="Item 4.01 Changes in Certifying Accountant")]),
        today=TODAY,
    )

    assert event(result, "auditor_change")["severity"] == "yellow"


def test_repeat_events_are_grouped_not_listed_separately():
    result = build_filing_history(
        submissions(
            [
                filing("8-K", "2026-01-05", items="5.02"),
                filing("8-K", "2025-06-05", items="5.02"),
                filing("8-K", "2024-11-05", items="5.02"),
            ]
        ),
        today=TODAY,
    )

    departures = event(result, "officer_departure")
    assert len(result["events"]) == 1
    assert departures["count"] == 3
    # Newest occurrence first, so the interpretation leads with the most recent date.
    assert [o["date"] for o in departures["occurrences"]] == [
        "2026-01-05",
        "2025-06-05",
        "2024-11-05",
    ]


def test_officer_departures_are_graded_on_rate_not_instance():
    def departures(count: int) -> str:
        rows = [filing("8-K", f"2026-0{i + 1}-05", items="5.02") for i in range(count)]
        return event(build_filing_history(submissions(rows), today=TODAY), "officer_departure")[
            "severity"
        ]

    assert departures(1) == "green"  # a director retiring
    assert departures(3) == "yellow"
    assert departures(6) == "red"  # churn


def test_occurrence_list_is_capped_but_count_is_not():
    rows = [filing("8-K", f"2026-01-{day:02d}", items="5.02") for day in range(1, 13)]
    result = build_filing_history(submissions(rows), today=TODAY)

    departures = event(result, "officer_departure")
    assert departures["count"] == 12
    assert len(departures["occurrences"]) == 8


def test_events_are_ordered_worst_first():
    result = build_filing_history(
        submissions(
            [
                filing("8-K", "2026-01-05", items="5.02"),
                filing("8-K", "2025-01-05", items="4.01"),
                filing("8-K", "2024-09-05", items="4.02"),
            ]
        ),
        today=TODAY,
    )

    assert [e["severity"] for e in result["events"]] == ["red", "yellow", "green"]
    assert result["events"][0]["key"] == "non_reliance"


def test_occurrences_link_to_the_filing_itself():
    result = build_filing_history(
        submissions(
            [
                filing(
                    "8-K",
                    "2026-03-02",
                    items="4.02",
                    accessionNumber="0000320193-26-000042",
                    primaryDocument="a8k.htm",
                )
            ]
        ),
        today=TODAY,
    )

    url = event(result, "non_reliance")["occurrences"][0]["url"]
    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000042/a8k.htm"


def test_unusable_primary_document_still_links_to_the_filing_folder():
    result = build_filing_history(
        submissions([filing("8-K", "2026-03-02", items="4.02", primaryDocument="")]), today=TODAY
    )

    assert event(result, "non_reliance")["occurrences"][0]["url"].endswith("/")


# --- forms that are themselves the signal ---------------------------------------------


def test_late_filing_notification_is_flagged():
    result = build_filing_history(
        submissions([filing("NT 10-K", "2026-03-02", reportDate="2025-12-31")]), today=TODAY
    )

    assert event(result, "late_annual_report")["severity"] == "red"


def test_amended_annual_report_is_flagged():
    result = build_filing_history(submissions([filing("10-K/A", "2026-05-02")]), today=TODAY)

    assert event(result, "amended_annual_report")["severity"] == "yellow"


def test_events_outside_the_window_are_excluded():
    result = build_filing_history(
        submissions([filing("8-K", "2020-03-02", items="4.02")]), window_years=3, today=TODAY
    )

    assert result["events"] == []


# --- filing lag -----------------------------------------------------------------------


def annual(period_end: str, filed: str) -> dict:
    return filing("10-K", filed, reportDate=period_end)


def test_filing_lag_measures_period_end_to_filing_date():
    result = build_filing_history(
        submissions([annual("2025-12-31", "2026-02-14")]), today=TODAY
    )

    assert result["filingLag"]["days"] == 45
    assert result["filingLag"]["typicalDays"] is None  # nothing to compare against yet


def test_filing_lag_compares_against_the_companys_own_norm():
    result = build_filing_history(
        submissions(
            [
                annual("2023-12-31", "2024-02-10"),  # 41 days
                annual("2024-12-31", "2025-02-08"),  # 39 days
                annual("2025-12-31", "2026-03-15"),  # 74 days
            ]
        ),
        today=TODAY,
    )

    lag = result["filingLag"]
    assert lag["days"] == 74
    assert lag["typicalDays"] == 40.0
    assert lag["driftDays"] == 34.0
    assert lag["severity"] == "red"
    assert "slower than this company's own recent norm" in lag["interpretation"]


def test_filing_inside_the_norm_is_green():
    result = build_filing_history(
        submissions(
            [
                annual("2023-12-31", "2024-02-10"),
                annual("2024-12-31", "2025-02-08"),
                annual("2025-12-31", "2026-02-12"),
            ]
        ),
        today=TODAY,
    )

    assert result["filingLag"]["severity"] == "green"


def test_missing_the_statutory_deadline_is_red_regardless_of_the_norm():
    # A filer whose own norm is slow still breaches the 60-day large-accelerated deadline.
    result = build_filing_history(
        submissions(
            [
                annual("2023-12-31", "2024-04-08"),  # 99 days
                annual("2024-12-31", "2025-04-08"),  # 98 days
                annual("2025-12-31", "2026-04-08"),  # 98 days: in line, still late
            ],
            category="Large accelerated filer",
        ),
        today=TODAY,
    )

    lag = result["filingLag"]
    assert lag["deadlineDays"] == 60
    assert lag["severity"] == "red"
    assert "past it" in lag["interpretation"]


def test_deadline_defaults_to_the_slowest_class_when_category_is_absent():
    result = build_filing_history(submissions([annual("2025-12-31", "2026-02-14")]), today=TODAY)

    assert result["filingLag"]["deadlineDays"] == 90


def test_mis_tagged_report_dates_are_ignored_rather_than_producing_absurd_lags():
    result = build_filing_history(
        submissions(
            [
                annual("2027-12-31", "2026-02-14"),  # period end after the filing date
                annual("2025-12-31", "2026-02-14"),
            ]
        ),
        today=TODAY,
    )

    assert result["filingLag"]["days"] == 45
    assert len(result["filingLag"]["trend"]) == 1


def test_filing_lag_is_absent_when_no_annual_report_carries_both_dates():
    result = build_filing_history(submissions([filing("8-K", "2026-03-02", items="4.02")]), today=TODAY)

    assert result["filingLag"] is None


# --- cadence and coverage -------------------------------------------------------------


def test_cadence_splits_8ks_into_this_year_and_last():
    result = build_filing_history(
        submissions(
            [
                filing("8-K", "2026-08-01"),
                filing("8-K", "2026-01-01"),
                filing("8-K", "2025-01-01"),
            ]
        ),
        today=TODAY,
    )

    assert result["cadence"]["eightKLast12Months"] == 2
    assert result["cadence"]["eightKPrior12Months"] == 1


def test_truncated_index_is_reported_rather_than_read_as_a_clean_record():
    # EDGAR's recent block caps out; a heavy filer can exhaust it inside the window.
    result = build_filing_history(
        submissions([filing("8-K", "2026-06-01")]), window_years=3, today=TODAY
    )

    coverage = result["coverage"]
    assert coverage["complete"] is False
    assert "2026-06-01" in coverage["note"]


def test_coverage_is_complete_when_the_index_predates_the_window():
    result = build_filing_history(
        submissions([filing("8-K", "2020-01-01"), filing("8-K", "2026-06-01")]),
        window_years=3,
        today=TODAY,
    )

    assert result["coverage"]["complete"] is True
    assert result["coverage"]["note"] is None


def test_recent_name_change_is_surfaced():
    result = build_filing_history(
        submissions(
            [filing("8-K", "2026-06-01")],
            formerNames=[{"name": "Legacy Holdings Corp", "from": "2015-01-01T00:00:00.000Z", "to": "2025-04-01T00:00:00.000Z"}],
        ),
        today=TODAY,
    )

    name_change = event(result, "former_name")
    assert name_change["severity"] == "yellow"
    assert "Legacy Holdings Corp" in name_change["interpretation"]


def test_old_name_changes_are_not_surfaced():
    result = build_filing_history(
        submissions(
            [filing("8-K", "2026-06-01")],
            formerNames=[{"name": "Ancient Corp", "from": "2001-01-01T00:00:00.000Z", "to": "2009-04-01T00:00:00.000Z"}],
        ),
        today=TODAY,
    )

    assert event(result, "former_name") is None


# --- degradation ----------------------------------------------------------------------


def test_no_filing_block_returns_none():
    assert build_filing_history({"cik": "0000320193", "filings": {}}) is None
    assert build_filing_history({}) is None
    assert build_filing_history(None) is None


def test_uneventful_filer_returns_a_result_with_no_events():
    """"We looked and found nothing" must be distinguishable from "we could not look"."""
    result = build_filing_history(
        submissions([annual("2025-12-31", "2026-02-14"), filing("8-K", "2026-02-14", items="2.02")]),
        today=TODAY,
    )

    assert result is not None
    assert result["events"] == []
    assert result["filingLag"]["severity"] == "green"


def test_ragged_columns_do_not_crash_the_reader():
    # EDGAR occasionally serves a block where an optional column is short or absent.
    block = {
        "form": ["8-K", "10-K"],
        "filingDate": ["2026-03-02", "2026-02-14"],
        "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
        "reportDate": ["", "2025-12-31"],
        "items": ["4.02"],  # short by one
    }

    result = build_filing_history({"cik": "0000320193", "filings": {"recent": block}}, today=TODAY)

    assert result is not None
    assert result["events"] == []  # the short items column is discarded wholesale
    assert result["filingLag"]["days"] == 45
