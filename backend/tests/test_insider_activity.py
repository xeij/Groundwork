"""Form 4 parsing and the insider signals built on top of it.

The XML fixtures are written out in full rather than captured, because the whole point
of this module is which transaction codes count as a decision and which do not, and that
distinction has to be legible in the test.
"""

from datetime import date
from unittest.mock import patch

import pytest

from app.services import insider_activity
from app.services.insider_activity import (
    build_insider_activity,
    ownership_filings,
    parse_ownership_form,
    summarize,
)

TODAY = date(2026, 8, 19)
WINDOW_START = date(2025, 8, 19)


def transaction(
    code: str,
    shares: float,
    price: float | None = 100.0,
    when: str = "2026-03-02",
    acquired: str = "D",
    owned_after: float | None = 50_000,
    footnote: str | None = None,
) -> str:
    price_block = (
        f"<transactionPricePerShare><value>{price}</value></transactionPricePerShare>"
        if price is not None
        # A price the filer could not state carries a footnote reference in place of a value.
        else '<transactionPricePerShare><footnoteId id="F9"/></transactionPricePerShare>'
    )
    owned_block = (
        f"<postTransactionAmounts><sharesOwnedFollowingTransaction><value>{owned_after}"
        "</value></sharesOwnedFollowingTransaction></postTransactionAmounts>"
        if owned_after is not None
        else ""
    )
    footnote_ref = f'<footnoteId id="{footnote}"/>' if footnote else ""
    return f"""
      <nonDerivativeTransaction>
        <securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>{when}</value></transactionDate>
        <transactionCoding><transactionFormType>4</transactionFormType>
          <transactionCode>{code}</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>{shares}</value></transactionShares>
          {price_block}
          <transactionAcquiredDisposedCode><value>{acquired}</value></transactionAcquiredDisposedCode>
          {footnote_ref}
        </transactionAmounts>
        {owned_block}
      </nonDerivativeTransaction>"""


def form4(
    name: str = "COOK TIMOTHY D",
    *,
    transactions: str = "",
    derivatives: str = "",
    officer: bool = True,
    director: bool = False,
    ten_percent: bool = False,
    title: str = "Chief Executive Officer",
    footnotes: str = "",
    plan_flag: bool = False,
) -> str:
    return f"""<?xml version="1.0"?>
    <ownershipDocument>
      <documentType>4</documentType>
      <periodOfReport>2026-03-02</periodOfReport>
      {'<aff10b5One>1</aff10b5One>' if plan_flag else ''}
      <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
      <reportingOwner>
        <reportingOwnerId><rptOwnerCik>0001214128</rptOwnerCik><rptOwnerName>{name}</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship>
          <isDirector>{int(director)}</isDirector>
          <isOfficer>{int(officer)}</isOfficer>
          <isTenPercentOwner>{int(ten_percent)}</isTenPercentOwner>
          <officerTitle>{title}</officerTitle>
        </reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>{transactions}</nonDerivativeTable>
      <derivativeTable>{derivatives}</derivativeTable>
      <footnotes>{footnotes}</footnotes>
    </ownershipDocument>"""


def parsed(*, filing_date: str = "2026-03-03", **kwargs) -> dict:
    form = parse_ownership_form(form4(**kwargs))
    form["filingDate"] = date.fromisoformat(filing_date)
    return form


# --- parsing --------------------------------------------------------------------------


def test_parses_owner_and_transaction():
    result = parse_ownership_form(form4(transactions=transaction("S", 511_000, price=169.4)))

    assert result["owner"]["name"] == "Cook Timothy D"
    assert result["owner"]["isOfficer"] is True
    assert result["owner"]["title"] == "Chief Executive Officer"

    sale = result["transactions"][0]
    assert sale["code"] == "S"
    assert sale["shares"] == 511_000
    assert sale["value"] == pytest.approx(511_000 * 169.4)
    assert sale["sharesOwnedAfter"] == 50_000
    assert sale["derivative"] is False


def test_missing_price_reports_no_value_rather_than_zero():
    result = parse_ownership_form(form4(transactions=transaction("S", 1_000, price=None)))

    assert result["transactions"][0]["shares"] == 1_000
    assert result["transactions"][0]["value"] is None


def test_grant_at_zero_price_claims_no_dollar_value():
    result = parse_ownership_form(form4(transactions=transaction("A", 1_000, price=0)))

    assert result["transactions"][0]["value"] is None


def test_holding_rows_are_not_transactions():
    holding = """
      <nonDerivativeHolding>
        <securityTitle><value>Common Stock</value></securityTitle>
        <postTransactionAmounts><sharesOwnedFollowingTransaction><value>900</value>
        </sharesOwnedFollowingTransaction></postTransactionAmounts>
      </nonDerivativeHolding>"""

    result = parse_ownership_form(form4(transactions=holding))

    assert result["transactions"] == []


def test_derivative_transactions_are_parsed_but_marked():
    derivative = """
      <derivativeTransaction>
        <transactionDate><value>2026-03-02</value></transactionDate>
        <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>2000</value></transactionShares>
          <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
        </transactionAmounts>
      </derivativeTransaction>"""

    result = parse_ownership_form(form4(derivatives=derivative))

    assert result["transactions"][0]["derivative"] is True


def test_10b5_1_plan_detected_from_a_referenced_footnote():
    footnotes = '<footnote id="F1">Sale under a Rule 10b5-1 trading plan adopted 2025-11-01.</footnote>'
    result = parse_ownership_form(
        form4(transactions=transaction("S", 100, footnote="F1"), footnotes=footnotes)
    )

    assert result["transactions"][0]["planned"] is True


def test_unrelated_footnote_does_not_mark_a_sale_as_planned():
    footnotes = '<footnote id="F1">Shares held by a family trust.</footnote>'
    result = parse_ownership_form(
        form4(transactions=transaction("S", 100, footnote="F1"), footnotes=footnotes)
    )

    assert result["transactions"][0]["planned"] is False


def test_10b5_1_plan_detected_from_the_document_level_checkbox():
    result = parse_ownership_form(form4(transactions=transaction("S", 100), plan_flag=True))

    assert result["transactions"][0]["planned"] is True


def test_namespaced_ownership_xml_parses():
    namespaced = form4(transactions=transaction("P", 100)).replace(
        "<ownershipDocument>", '<ownershipDocument xmlns="http://www.sec.gov/edgar/ownership">'
    )

    assert parse_ownership_form(namespaced)["transactions"][0]["code"] == "P"


def test_malformed_xml_returns_none_rather_than_raising():
    assert parse_ownership_form("<ownershipDocument><unclosed>") is None
    assert parse_ownership_form("") is None


def test_owner_name_casing_is_left_alone_when_the_filer_used_mixed_case():
    assert parse_ownership_form(form4(name="Jane Q. Adams"))["owner"]["name"] == "Jane Q. Adams"


def test_role_falls_back_through_officer_director_then_ten_percent():
    forms = [
        parsed(name="A", officer=False, director=True, title=""),
        parsed(name="B", officer=False, director=False, ten_percent=True, title=""),
    ]
    result = summarize(
        [
            {**forms[0], "transactions": [{**parse_ownership_form(form4(transactions=transaction("P", 10)))["transactions"][0]}]},
        ],
        WINDOW_START,
        TODAY,
    )

    assert result["insiders"][0]["role"] == "director"


# --- listing the filings to fetch -----------------------------------------------------


def submissions(rows: list[tuple[str, str]]) -> dict:
    return {
        "filings": {
            "recent": {
                "form": [form for form, _ in rows],
                "filingDate": [when for _, when in rows],
                "accessionNumber": [f"0000320193-26-{i:06d}" for i in range(len(rows))],
                "primaryDocument": ["xslF345X03/wf-form4.xml"] * len(rows),
            }
        }
    }


def test_only_form_4s_inside_the_window_are_listed_newest_first():
    rows = [
        ("4", "2026-03-02"),
        ("8-K", "2026-03-01"),
        ("3", "2026-02-01"),  # initial holdings statement: no transactions
        ("4/A", "2026-05-02"),
        ("4", "2019-01-01"),  # outside the window
    ]

    filings = ownership_filings(submissions(rows), since=date(2024, 8, 19))

    assert [f["filingDate"].isoformat() for f in filings] == ["2026-05-02", "2026-03-02"]


def test_no_ownership_filings_yields_an_empty_list():
    assert ownership_filings(submissions([("10-K", "2026-02-14")]), since=date(2024, 1, 1)) == []
    assert ownership_filings({}, since=date(2024, 1, 1)) == []


# --- aggregation ----------------------------------------------------------------------


def test_grants_and_tax_withholding_stay_out_of_the_buy_sell_totals():
    forms = [
        parsed(name="A", transactions=transaction("A", 10_000, price=0)),
        parsed(name="B", transactions=transaction("F", 4_000)),
        parsed(name="C", transactions=transaction("P", 1_000)),
    ]

    result = summarize(forms, WINDOW_START, TODAY)

    assert result["buys"]["shares"] == 1_000
    assert result["sells"]["shares"] == 0
    assert result["grantedShares"] == 10_000
    assert result["taxWithheldShares"] == 4_000


def test_option_exercises_are_excluded_from_the_totals():
    derivative = """
      <derivativeTransaction>
        <transactionDate><value>2026-03-02</value></transactionDate>
        <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>9000</value></transactionShares>
          <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
        </transactionAmounts>
      </derivativeTransaction>"""

    result = summarize([parsed(derivatives=derivative)], WINDOW_START, TODAY)

    assert result["buys"]["shares"] == 0
    assert result["insiders"] == []


def test_transactions_outside_the_window_are_ignored():
    forms = [parsed(transactions=transaction("P", 1_000, when="2024-01-01"))]

    assert summarize(forms, WINDOW_START, TODAY)["buys"]["shares"] == 0


def test_partial_prices_mark_the_dollar_total_as_a_floor():
    forms = [
        parsed(name="A", transactions=transaction("S", 100, price=10.0)),
        parsed(name="B", transactions=transaction("S", 100, price=None)),
    ]

    result = summarize(forms, WINDOW_START, TODAY)

    assert result["sells"]["value"] == 1_000
    assert result["sells"]["valueKnown"] is False


def test_insiders_are_counted_once_across_several_forms():
    forms = [
        parsed(name="COOK TIMOTHY D", transactions=transaction("S", 100)),
        parsed(name="COOK TIMOTHY D", transactions=transaction("S", 200, when="2026-04-02")),
    ]

    result = summarize(forms, WINDOW_START, TODAY)

    assert result["sells"]["insiders"] == 1
    assert result["insiders"][0]["sellShares"] == 300


def test_holdings_are_taken_from_the_most_recent_transaction():
    forms = [
        parsed(transactions=transaction("S", 100, when="2026-01-02", owned_after=900)),
        parsed(transactions=transaction("S", 100, when="2026-04-02", owned_after=800)),
    ]

    result = summarize(forms, WINDOW_START, TODAY)

    assert result["insiders"][0]["sharesOwnedAfter"] == 800
    assert result["insiders"][0]["lastTransactionDate"] == "2026-04-02"


# --- signals --------------------------------------------------------------------------


def signals_for(forms: list[dict], prior: list[dict] | None = None) -> dict:
    current = summarize(forms, WINDOW_START, TODAY)
    prior_window = summarize(prior or [], date(2024, 8, 19), WINDOW_START)
    return {s["key"]: s for s in insider_activity._signals(current, prior_window, 12)}


def buyer(name: str, when: str, shares: float = 1_000) -> dict:
    return parsed(name=name, transactions=transaction("P", shares, when=when, acquired="A"))


def test_three_insiders_buying_together_is_flagged_as_a_cluster():
    forms = [
        buyer("ADAMS JANE", "2026-03-02"),
        buyer("BROWN SAM", "2026-03-20"),
        buyer("CHEN LI", "2026-04-15"),
    ]

    signals = signals_for(forms)

    assert signals["cluster_buying"]["severity"] == "green"
    assert "3 insiders" in signals["cluster_buying"]["interpretation"]


def test_buying_spread_across_the_year_is_not_a_cluster():
    forms = [
        buyer("ADAMS JANE", "2025-09-02"),
        buyer("BROWN SAM", "2026-01-20"),
        buyer("CHEN LI", "2026-06-15"),
    ]

    signals = signals_for(forms)

    assert "cluster_buying" not in signals
    assert signals["net_buying"]["severity"] == "green"


def test_selling_most_of_the_groups_holdings_is_graded_on_the_share_sold():
    def sold(shares: float, remaining: float) -> str:
        return summarize(
            [parsed(transactions=transaction("S", shares, owned_after=remaining))],
            WINDOW_START,
            TODAY,
        )

    assert insider_activity._selling_pressure(sold(10, 990), 12) is None  # 1%
    assert insider_activity._selling_pressure(sold(300, 700), 12)["severity"] == "yellow"
    assert insider_activity._selling_pressure(sold(600, 400), 12)["severity"] == "red"


def test_planned_sales_are_called_out_as_weaker_evidence():
    footnotes = '<footnote id="F1">Sold under a Rule 10b5-1 plan.</footnote>'
    forms = [
        parsed(
            transactions=transaction("S", 600, owned_after=400, footnote="F1"),
            footnotes=footnotes,
        )
    ]

    interpretation = signals_for(forms)["heavy_insider_selling"]["interpretation"]

    assert "10b5-1" in interpretation


def test_discretionary_sales_are_called_out_as_stronger_evidence():
    forms = [parsed(transactions=transaction("S", 600, owned_after=400))]

    interpretation = signals_for(forms)["heavy_insider_selling"]["interpretation"]

    assert "discretionary" in interpretation


def test_an_insider_selling_most_of_their_own_position_is_named():
    forms = [
        parsed(name="COOK TIMOTHY D", transactions=transaction("S", 900, owned_after=100)),
    ]

    signals = signals_for(forms)
    exit_signal = signals["insider_exit_cook_timothy_d"]

    assert exit_signal["severity"] == "red"
    assert "Cook Timothy D" in exit_signal["label"]
    assert exit_signal["detail"]["percentOfPositionSold"] == 90.0


def test_no_open_market_trades_says_so_explicitly():
    forms = [parsed(transactions=transaction("A", 5_000, price=0))]

    signals = signals_for(forms)

    assert signals["no_open_market_activity"]["severity"] == "green"
    assert "is a decision about the stock" in signals["no_open_market_activity"]["interpretation"]


def test_doubled_selling_against_the_prior_year_is_flagged():
    current = [parsed(transactions=transaction("S", 1_000, owned_after=100_000))]
    prior = [parsed(transactions=transaction("S", 400, when="2025-01-02", owned_after=100_000))]

    signals = signals_for(current, prior)

    assert signals["selling_accelerated"]["detail"]["changePercent"] == 150.0


def test_flat_selling_against_the_prior_year_is_not_flagged():
    current = [parsed(transactions=transaction("S", 1_000, owned_after=100_000))]
    prior = [parsed(transactions=transaction("S", 900, when="2025-01-02", owned_after=100_000))]

    assert "selling_accelerated" not in signals_for(current, prior)


# --- entry point ----------------------------------------------------------------------


def test_build_reports_coverage_and_drops_internal_bookkeeping():
    rows = [("4", "2026-03-02"), ("4", "2026-04-02")]
    forms = [
        parsed(name="ADAMS JANE", transactions=transaction("P", 500, when="2026-03-02", acquired="A")),
        parsed(name="BROWN SAM", transactions=transaction("S", 200, when="2026-04-02")),
    ]

    with patch.object(insider_activity, "fetch_forms", return_value=forms):
        result = build_insider_activity("0000320193", submissions(rows), today=TODAY)

    assert result["coverage"] == {
        "formsFound": 2,
        "formsRead": 2,
        "complete": True,
        "note": None,
    }
    assert result["summary"]["buyShares"] == 500
    assert result["summary"]["sellShares"] == 200
    assert "buyDates" not in result["summary"]
    assert result["insiders"][0]["name"] in {"Adams Jane", "Brown Sam"}


def test_build_marks_the_record_incomplete_when_forms_could_not_be_read():
    rows = [("4", "2026-03-02"), ("4", "2026-04-02")]
    forms = [parsed(transactions=transaction("S", 200, when="2026-04-02"))]

    with patch.object(insider_activity, "fetch_forms", return_value=forms):
        result = build_insider_activity("0000320193", submissions(rows), today=TODAY)

    assert result["coverage"]["complete"] is False
    assert "a floor" in result["coverage"]["note"]
    # Without a complete record there is no honest baseline to compare against.
    assert result["priorSummary"] is None


def test_build_returns_none_when_there_are_no_form_4s():
    assert build_insider_activity("0000320193", submissions([("10-K", "2026-02-14")]), today=TODAY) is None


def test_build_returns_none_when_no_form_could_be_read():
    with patch.object(insider_activity, "fetch_forms", return_value=[]):
        result = build_insider_activity("0000320193", submissions([("4", "2026-03-02")]), today=TODAY)

    assert result is None


def test_fetch_forms_skips_a_form_that_fails_to_download():
    filings = [
        {"accessionNumber": "0000320193-26-000001", "filingDate": TODAY, "primaryDocument": "a.xml"},
        {"accessionNumber": "0000320193-26-000002", "filingDate": TODAY, "primaryDocument": "b.xml"},
    ]

    def flaky(cik, accession, document):
        if document == "a.xml":
            raise RuntimeError("404")
        return form4(transactions=transaction("P", 100))

    with patch.object(insider_activity.edgar, "fetch_ownership_document", side_effect=flaky):
        forms = insider_activity.fetch_forms("0000320193", filings)

    assert len(forms) == 1


def test_fetch_forms_stops_starting_work_once_the_budget_is_spent():
    filings = [
        {"accessionNumber": f"0000320193-26-{i:06d}", "filingDate": TODAY, "primaryDocument": "a.xml"}
        for i in range(4)
    ]

    with patch.object(insider_activity.edgar, "fetch_ownership_document") as fetch:
        forms = insider_activity.fetch_forms("0000320193", filings, budget_seconds=0)

    assert forms == []
    fetch.assert_not_called()
