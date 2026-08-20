"""Normalize the SEC's XBRL companyfacts blob into a comparable multi-year history.

Filers tag the same line item with different us-gaap concepts, so every field here
resolves through an ordered fallback chain instead of a single tag. Facts are also
reported many times over -- each 10-K repeats two prior years as comparatives -- so
the same (concept, period) arrives under several accessions; we keep the one from the
most recently filed accession, which is the restated figure the company stands behind
today.

Nothing here interpolates. A line item the company never tagged stays None, so callers
can tell "reported as zero" apart from "not disclosed".
"""

from datetime import date

_US_GAAP = "us-gaap"

# Forms whose durational facts we trust to delimit a fiscal year. 10-Q facts are
# indexed too (they restate balances) but never get a vote on where a year begins.
_ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# A "year" spans 52/53 weeks for retail-calendar filers and can run short in a fiscal
# transition year, so the window is deliberately loose. It still excludes quarterly
# (~91d), year-to-date (~182/273d) and since-inception (>400d) periods, which is the
# only filter standing between us and silently averaging a quarter into an annual row.
_MIN_ANNUAL_DAYS = 340
_MAX_ANNUAL_DAYS = 400

_DAYS_IN_YEAR = 365.0

# When one concept carries several unit keys, the monetary one is the one we want.
_UNIT_PREFERENCE = ("USD", "shares", "pure", "USD/shares")

# Ordered fallback chains: the first concept the filer actually tagged for the period
# wins. Order is "most specific / most modern tag" first, legacy pre-ASC-606 tags last.
_DURATION_CHAINS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RevenuesNetOfInterestExpense",
    ),
    "costOfRevenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfSales",
        "CostOfServices",
    ),
    "grossProfit": ("GrossProfit",),
    "operatingIncome": (
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ),
    "netIncome": (
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "rndExpense": (
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ),
    "operatingCashFlow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "investingCashFlow": (
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ),
    "financingCashFlow": (
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ),
    # Tagged as a positive cash outflow; free cash flow subtracts it.
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ),
    "depreciationAmortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "Depreciation",
    ),
    "shareBasedCompensation": (
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardCompensationCost",
    ),
    "interestExpense": (
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
        "InterestIncomeExpenseNet",
    ),
    "incomeTaxExpense": ("IncomeTaxExpenseBenefit", "CurrentIncomeTaxExpenseBenefit"),
    "dilutedShares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstandingAdjustment",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    # Pretax income is the denominator of the effective tax rate, which is the one
    # line of the income statement a company can move without selling anything.
    "pretaxIncome": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
    ),
    # Both are tagged as positive cash outflows, like capex.
    "dividendsPaid": (
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
        "PaymentsOfDividendsAndDividendEquivalentsOnCommonStockAndRestrictedStockUnits",
    ),
    "shareRepurchases": (
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ),
}

_INSTANT_CHAINS: dict[str, tuple[str, ...]] = {
    "totalAssets": ("Assets",),
    "currentAssets": ("AssetsCurrent",),
    "currentLiabilities": ("LiabilitiesCurrent",),
    "totalLiabilities": ("Liabilities",),
    "stockholdersEquity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations",
    ),
    "receivables": (
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
        "AccountsAndOtherReceivablesNetCurrent",
        "AccountsReceivableNet",
        "AccountsReceivableGrossCurrent",
    ),
    "inventory": ("InventoryNet", "InventoryGross", "FIFOInventoryAmount"),
    "accountsPayable": (
        "AccountsPayableCurrent",
        "AccountsPayableTradeCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ),
    "ppeNet": (
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ),
    "longTermDebt": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
        "ConvertibleLongTermNotesPayable",
        "ConvertibleDebtNoncurrent",
    ),
    "retainedEarnings": (
        "RetainedEarningsAccumulatedDeficit",
        "RetainedEarningsAccumulatedDeficitIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "goodwill": ("Goodwill",),
    # Current deferred revenue only. The noncurrent slice is a different promise on a
    # different horizon, and adding the two would make the year-over-year read on
    # near-term bookings meaningless.
    "deferredRevenue": (
        "ContractWithCustomerLiabilityCurrent",
        "DeferredRevenueCurrent",
        "ContractWithCustomerLiability",
    ),
}

# totalDebt is a sum, not a tag: no filer reports "total debt" as a single us-gaap fact.
# DebtCurrent, where present, is already the whole current-debt line (commercial paper
# plus the current portion of term debt), so it short-circuits the two narrower slots
# below it -- adding them on top would double count.
_SHORT_TERM_DEBT_TOTAL_CHAIN = ("DebtCurrent",)
_SHORT_TERM_BORROWING_CHAIN = (
    "ShortTermBorrowings",
    "CommercialPaper",
    "OtherShortTermBorrowings",
    "ShortTermNonBankLoansAndNotesPayable",
)
_CURRENT_LONG_TERM_DEBT_CHAIN = (
    "LongTermDebtCurrent",
    "LongTermDebtAndCapitalLeaseObligationsCurrent",
    "ConvertibleNotesPayableCurrent",
)

# Likewise for SG&A: filers that split the line report selling and administrative
# separately and never tag the combined concept, so the two halves are added back up.
_SGA_TOTAL_CHAIN = ("SellingGeneralAndAdministrativeExpense", "OtherSellingGeneralAndAdministrativeExpense")
_SELLING_EXPENSE_CHAIN = ("SellingAndMarketingExpense", "SellingExpense", "MarketingAndAdvertisingExpense")
_GENERAL_ADMIN_CHAIN = ("GeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpenseExcludingResearchAndDevelopment")

FISCAL_YEAR_FIELDS: tuple[str, ...] = (
    "revenue",
    "costOfRevenue",
    "grossProfit",
    "operatingIncome",
    "netIncome",
    "sgaExpense",
    "rndExpense",
    "totalAssets",
    "currentAssets",
    "currentLiabilities",
    "totalLiabilities",
    "stockholdersEquity",
    "cash",
    "receivables",
    "inventory",
    "accountsPayable",
    "ppeNet",
    "longTermDebt",
    "totalDebt",
    "operatingCashFlow",
    "investingCashFlow",
    "financingCashFlow",
    "capex",
    "depreciationAmortization",
    "shareBasedCompensation",
    "interestExpense",
    "incomeTaxExpense",
    "dilutedShares",
    "retainedEarnings",
    "pretaxIncome",
    "dividendsPaid",
    "shareRepurchases",
    "goodwill",
    "deferredRevenue",
)


class XbrlMetricsError(Exception):
    pass


def build_financial_history(company_facts: dict, max_years: int = 6) -> list[dict]:
    """Fiscal-year rows in raw USD, oldest first, at most `max_years` of the newest."""
    if not isinstance(company_facts, dict):
        raise XbrlMetricsError("company_facts must be the parsed companyfacts JSON object")
    if max_years < 1:
        raise XbrlMetricsError("max_years must be at least 1")

    gaap = company_facts.get("facts", {}).get(_US_GAAP)
    if not isinstance(gaap, dict) or not gaap:
        raise XbrlMetricsError("This filer has no us-gaap XBRL facts on EDGAR.")

    index, periods = _index_facts(gaap)
    return [_fiscal_year_row(index, period) for period in periods[-max_years:]]


def latest_fiscal_year(history: list[dict]) -> dict | None:
    """The most recent row, since history is ordered oldest first."""
    return history[-1] if history else None


def derived_ratios(history: list[dict]) -> dict:
    """Ratios the filing itself never states, each with its prior year and YoY change.

    Entries whose inputs are missing are omitted outright rather than emitted as null
    or zero -- a zero current ratio reads as "insolvent", not "not disclosed".
    """
    if not history:
        return {}

    latest = history[-1]
    prior = history[-2] if len(history) >= 2 else None
    prior_prior = history[-3] if len(history) >= 3 else None

    ratios: dict[str, dict] = {}
    for key, label, unit, compute in _RATIO_SPECS:
        value = compute(latest, prior)
        if value is None:
            continue
        entry = {"label": label, "value": round(value, 2), "unit": unit}
        prior_value = compute(prior, prior_prior) if prior else None
        if prior_value is not None:
            entry["priorValue"] = round(prior_value, 2)
            entry["change"] = round(value - prior_value, 2)
        ratios[key] = entry
    return ratios


def _index_facts(gaap: dict) -> tuple[dict, list[dict]]:
    """Collapse the fact firehose into {concept: {"duration"|"instant": {end: fact}}}.

    Also returns the fiscal periods, because deciding what counts as a fiscal year is a
    vote taken over the same facts and there is no reason to walk them twice.
    """
    index: dict[str, dict[str, dict]] = {}
    start_votes: dict[str, dict[str, int]] = {}
    fy_votes: dict[str, set[int]] = {}

    for concept, detail in gaap.items():
        units = detail.get("units")
        if not isinstance(units, dict):
            continue
        slots = index.setdefault(concept, {"duration": {}, "instant": {}})

        for unit, facts in units.items():
            unit_rank = _UNIT_PREFERENCE.index(unit) if unit in _UNIT_PREFERENCE else len(_UNIT_PREFERENCE)
            if not isinstance(facts, list):
                continue
            for fact in facts:
                end = fact.get("end")
                value = fact.get("val")
                if not end or value is None:
                    continue
                start = fact.get("start")
                if start:
                    span = _period_days(start, end)
                    if span is None or not _MIN_ANNUAL_DAYS <= span <= _MAX_ANNUAL_DAYS:
                        continue  # quarterly, year-to-date or since-inception
                    slot = "duration"
                    if str(fact.get("form", "")).startswith(_ANNUAL_FORMS):
                        start_votes.setdefault(end, {})
                        start_votes[end][start] = start_votes[end].get(start, 0) + 1
                        fiscal_year = fact.get("fy")
                        if isinstance(fiscal_year, int):
                            fy_votes.setdefault(end, set()).add(fiscal_year)
                else:
                    slot = "instant"

                key = (unit_rank, str(fact.get("filed", "")), str(fact.get("accn", "")))
                existing = slots[slot].get(end)
                # Lower unit_rank wins; within a unit the newest filing wins, which is
                # how a restatement supersedes the figure it corrected.
                if existing is None or _supersedes(key, existing["_key"]):
                    slots[slot][end] = {"val": value, "_key": key}

    return index, _annual_periods(start_votes, fy_votes)


def _supersedes(candidate: tuple, incumbent: tuple) -> bool:
    if candidate[0] != incumbent[0]:
        return candidate[0] < incumbent[0]
    return candidate[1:] > incumbent[1:]


def _annual_periods(start_votes: dict, fy_votes: dict) -> list[dict]:
    periods = []
    for end, starts in start_votes.items():
        start = max(starts.items(), key=lambda item: (item[1], item[0]))[0]
        periods.append({"start": start, "end": end, "fiscalYear": _fiscal_year(end, fy_votes.get(end))})
    periods.sort(key=lambda period: period["end"])
    return periods


def _fiscal_year(end: str, candidates: set[int] | None) -> int:
    """The filer's own label for the year, not the calendar year of the period end.

    A fact's `fy` is the fiscal focus of the *filing* it appeared in, so the same FY2022
    revenue carries fy=2024 when it shows up as a comparative in the FY2024 10-K. The
    smallest plausible candidate is the one from the filing where that year was current,
    which is also how a January-year-end retailer keeps its "fiscal 2023" label.
    """
    calendar_year = int(end[:4])
    plausible = [year for year in (candidates or set()) if abs(year - calendar_year) <= 1]
    return min(plausible) if plausible else calendar_year


def _period_days(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except (TypeError, ValueError):
        return None


def _fiscal_year_row(index: dict, period: dict) -> dict:
    end = period["end"]

    def duration(field: str) -> float | None:
        return _pick(index, _DURATION_CHAINS[field], "duration", end)

    def instant(field: str) -> float | None:
        return _pick(index, _INSTANT_CHAINS[field], "instant", end)

    row = {"fiscalYear": period["fiscalYear"], "periodEnd": end}
    for field in _DURATION_CHAINS:
        row[field] = duration(field)
    for field in _INSTANT_CHAINS:
        row[field] = instant(field)

    row["totalDebt"] = _total_debt(index, end)
    row["sgaExpense"] = _sga_expense(index, end)
    _fill_derivable_gaps(row, index, end)
    return {key: row[key] for key in ("fiscalYear", "periodEnd", *FISCAL_YEAR_FIELDS)}


def _pick(index: dict, chain: tuple[str, ...], slot: str, end: str) -> float | None:
    for concept in chain:
        fact = index.get(concept, {}).get(slot, {}).get(end)
        if fact is not None:
            return float(fact["val"])
    return None


def _total_debt(index: dict, end: str) -> float | None:
    short_term = _pick(index, _SHORT_TERM_DEBT_TOTAL_CHAIN, "instant", end)
    if short_term is None:
        borrowings = _pick(index, _SHORT_TERM_BORROWING_CHAIN, "instant", end)
        current_portion = _pick(index, _CURRENT_LONG_TERM_DEBT_CHAIN, "instant", end)
        parts = [part for part in (borrowings, current_portion) if part is not None]
        short_term = sum(parts) if parts else None

    long_term = _pick(index, _INSTANT_CHAINS["longTermDebt"], "instant", end)
    components = [part for part in (short_term, long_term) if part is not None]
    return sum(components) if components else None


def _sga_expense(index: dict, end: str) -> float | None:
    combined = _pick(index, _SGA_TOTAL_CHAIN, "duration", end)
    if combined is not None:
        return combined
    halves = [
        part
        for part in (
            _pick(index, _SELLING_EXPENSE_CHAIN, "duration", end),
            _pick(index, _GENERAL_ADMIN_CHAIN, "duration", end),
        )
        if part is not None
    ]
    return sum(halves) if halves else None


def _fill_derivable_gaps(row: dict, index: dict, end: str) -> None:
    """Close gaps that are pure arithmetic on figures the filer did tag.

    This is not interpolation: every value below is an identity that holds on the face
    of the statements, so nothing is invented from a trend or a neighbouring year.
    """
    if row["grossProfit"] is None and row["revenue"] is not None and row["costOfRevenue"] is not None:
        row["grossProfit"] = row["revenue"] - row["costOfRevenue"]
    if row["costOfRevenue"] is None and row["revenue"] is not None and row["grossProfit"] is not None:
        row["costOfRevenue"] = row["revenue"] - row["grossProfit"]

    if row["totalLiabilities"] is None:
        # Filers that omit a "total liabilities" subtotal still tag both sides of the
        # balance sheet identity, so back it out of assets less equity.
        total = row["totalAssets"] or _pick(index, ("LiabilitiesAndStockholdersEquity",), "instant", end)
        if total is not None and row["stockholdersEquity"] is not None:
            row["totalLiabilities"] = total - row["stockholdersEquity"]


def _div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _positive_div(numerator: float | None, denominator: float | None) -> float | None:
    """Guards ratios that are meaningless -- or sign-flipped -- on a negative base."""
    if denominator is None or denominator <= 0:
        return None
    return _div(numerator, denominator)


def _ebitda(year: dict) -> float | None:
    if year["operatingIncome"] is None or year["depreciationAmortization"] is None:
        return None
    return year["operatingIncome"] + year["depreciationAmortization"]


def _average(current: float | None, previous: float | None) -> float | None:
    if current is None:
        return None
    return current if previous is None else (current + previous) / 2


def _free_cash_flow(year: dict) -> float | None:
    if year["operatingCashFlow"] is None or year["capex"] is None:
        return None
    return year["operatingCashFlow"] - year["capex"]


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1) * 100


def _percent(numerator: float | None, denominator: float | None) -> float | None:
    ratio = _positive_div(numerator, denominator)
    return None if ratio is None else ratio * 100


def _effective_tax_rate(year: dict) -> float | None:
    """Tax expense over pretax profit. Meaningless on a loss, so a loss returns None."""
    return _positive_div(year["incomeTaxExpense"], year["pretaxIncome"])


def _nopat(year: dict) -> float | None:
    """Operating profit after tax, taxed at the rate the company actually paid.

    A made-up statutory rate would quietly turn ROIC into a different company's number,
    so a year with no usable effective rate yields no ROIC at all. The rate is clamped
    to a sane band because a one-off tax benefit can otherwise produce a NOPAT larger
    than the operating profit it came from.
    """
    if year["operatingIncome"] is None:
        return None
    rate = _effective_tax_rate(year)
    if rate is None:
        return None
    return year["operatingIncome"] * (1 - min(max(rate, 0.0), 0.5))


def _invested_capital(year: dict) -> float | None:
    """Debt plus equity less cash: the capital the business actually has at work."""
    if year["stockholdersEquity"] is None:
        return None
    capital = year["stockholdersEquity"] + (year["totalDebt"] or 0.0) - (year["cash"] or 0.0)
    return capital if capital > 0 else None


def _return_on_invested_capital(year: dict) -> float | None:
    return _percent(_nopat(year), _invested_capital(year))


def _rule_of_forty(year: dict, prior: dict | None) -> float | None:
    """Growth plus free-cash-flow margin, the software-industry health rule of thumb.

    A company growing 30% with a 15% FCF margin scores 45 and is doing fine; one growing
    30% while burning 25% of revenue scores 5 and is buying its growth.
    """
    growth = _growth(year["revenue"], prior["revenue"] if prior else None)
    margin = _percent(_free_cash_flow(year), year["revenue"])
    if growth is None or margin is None:
        return None
    return growth + margin


def _cash_runway_years(year: dict) -> float | None:
    """How long the cash lasts at last year's burn. Omitted when the company is not burning."""
    free_cash_flow = _free_cash_flow(year)
    if free_cash_flow is None or free_cash_flow >= 0 or year["cash"] is None:
        return None
    return year["cash"] / -free_cash_flow


def _shareholder_payout(year: dict) -> float | None:
    """Dividends plus buybacks as a share of free cash flow.

    Above 100% the company is returning cash it did not generate this year -- which is
    fine from a war chest and not fine from a revolver, a distinction the cash flow
    statement makes but the headline number does not.
    """
    returned = [part for part in (year["dividendsPaid"], year["shareRepurchases"]) if part is not None]
    if not returned:
        return None
    return _percent(sum(returned), _free_cash_flow(year))


def _working_capital(year: dict) -> float | None:
    if year["currentAssets"] is None or year["currentLiabilities"] is None:
        return None
    return year["currentAssets"] - year["currentLiabilities"]


def _net_cash(year: dict) -> float | None:
    if year["cash"] is None or year["totalDebt"] is None:
        return None
    return year["cash"] - year["totalDebt"]


def _asset_turnover(year: dict, prior: dict | None) -> float | None:
    return _div(year["revenue"], _average(year["totalAssets"], prior["totalAssets"] if prior else None))


# (key, label, unit, compute) -- compute takes the year and the year before it, so the
# same function yields both `value` and `priorValue` by shifting one row back.
_RATIO_SPECS: tuple[tuple[str, str, str, object], ...] = (
    ("grossMargin", "Gross Margin", "percent", lambda y, p: _percent(y["grossProfit"], y["revenue"])),
    ("operatingMargin", "Operating Margin", "percent", lambda y, p: _percent(y["operatingIncome"], y["revenue"])),
    ("netMargin", "Net Margin", "percent", lambda y, p: _percent(y["netIncome"], y["revenue"])),
    (
        "returnOnAssets",
        "Return on Assets",
        "percent",
        lambda y, p: _percent(y["netIncome"], _average(y["totalAssets"], p["totalAssets"] if p else None)),
    ),
    (
        "returnOnEquity",
        "Return on Equity",
        "percent",
        lambda y, p: _percent(
            y["netIncome"], _average(y["stockholdersEquity"], p["stockholdersEquity"] if p else None)
        ),
    ),
    ("currentRatio", "Current Ratio", "ratio", lambda y, p: _positive_div(y["currentAssets"], y["currentLiabilities"])),
    ("quickRatio", "Quick Ratio", "ratio", lambda y, p: _quick_ratio(y)),
    (
        "daysSalesOutstanding",
        "Days Sales Outstanding",
        "days",
        lambda y, p: _days(y["receivables"], y["revenue"]),
    ),
    (
        "daysInventoryOutstanding",
        "Days Inventory Outstanding",
        "days",
        lambda y, p: _days(y["inventory"], y["costOfRevenue"]),
    ),
    (
        "daysPayableOutstanding",
        "Days Payable Outstanding",
        "days",
        lambda y, p: _days(y["accountsPayable"], y["costOfRevenue"]),
    ),
    ("cashConversionCycle", "Cash Conversion Cycle", "days", lambda y, p: _cash_conversion_cycle(y)),
    ("interestCoverage", "Interest Coverage", "x", lambda y, p: _positive_div(y["operatingIncome"], y["interestExpense"])),
    ("netDebtToEbitda", "Net Debt / EBITDA", "x", lambda y, p: _net_debt_to_ebitda(y)),
    ("debtToEquity", "Debt / Equity", "ratio", lambda y, p: _positive_div(y["totalDebt"], y["stockholdersEquity"])),
    ("freeCashFlow", "Free Cash Flow", "usd", lambda y, p: _free_cash_flow(y)),
    ("fcfMargin", "Free Cash Flow Margin", "percent", lambda y, p: _percent(_free_cash_flow(y), y["revenue"])),
    (
        "sbcPercentOfOcf",
        "Stock Comp as % of Operating Cash Flow",
        "percent",
        lambda y, p: _percent(y["shareBasedCompensation"], y["operatingCashFlow"]),
    ),
    ("capexIntensity", "Capex Intensity", "percent", lambda y, p: _percent(y["capex"], y["revenue"])),
    ("revenueGrowth", "Revenue Growth", "percent", lambda y, p: _growth(y["revenue"], p["revenue"] if p else None)),
    (
        "dilutedShareChange",
        "Diluted Share Count Change",
        "percent",
        lambda y, p: _growth(y["dilutedShares"], p["dilutedShares"] if p else None),
    ),
    ("ebitdaMargin", "EBITDA Margin", "percent", lambda y, p: _percent(_ebitda(y), y["revenue"])),
    (
        "returnOnInvestedCapital",
        "Return on Invested Capital",
        "percent",
        lambda y, p: _return_on_invested_capital(y),
    ),
    ("assetTurnover", "Asset Turnover", "x", lambda y, p: _asset_turnover(y, p)),
    ("effectiveTaxRate", "Effective Tax Rate", "percent", lambda y, p: _percent(y["incomeTaxExpense"], y["pretaxIncome"])),
    ("rndIntensity", "R&D as % of Revenue", "percent", lambda y, p: _percent(y["rndExpense"], y["revenue"])),
    ("goodwillToAssets", "Goodwill as % of Assets", "percent", lambda y, p: _percent(y["goodwill"], y["totalAssets"])),
    ("ruleOfForty", "Rule of 40", "percent", lambda y, p: _rule_of_forty(y, p)),
    (
        "shareholderPayout",
        "Dividends + Buybacks as % of Free Cash Flow",
        "percent",
        lambda y, p: _shareholder_payout(y),
    ),
    ("workingCapital", "Working Capital", "usd", lambda y, p: _working_capital(y)),
    ("netCash", "Net Cash (Cash less Total Debt)", "usd", lambda y, p: _net_cash(y)),
    ("cashRunway", "Cash Runway at Current Burn", "years", lambda y, p: _cash_runway_years(y)),
)


def _quick_ratio(year: dict) -> float | None:
    if year["currentAssets"] is None:
        return None
    # Inventory is the illiquid part of current assets; an untagged inventory line on a
    # services filer means zero inventory, so treat the miss as nothing to subtract.
    liquid = year["currentAssets"] - (year["inventory"] or 0.0)
    return _positive_div(liquid, year["currentLiabilities"])


def _days(balance: float | None, flow: float | None) -> float | None:
    ratio = _positive_div(balance, flow)
    return None if ratio is None else ratio * _DAYS_IN_YEAR


def _cash_conversion_cycle(year: dict) -> float | None:
    dso = _days(year["receivables"], year["revenue"])
    dio = _days(year["inventory"], year["costOfRevenue"])
    dpo = _days(year["accountsPayable"], year["costOfRevenue"])
    if dso is None or dio is None or dpo is None:
        return None
    return dso + dio - dpo


def _net_debt_to_ebitda(year: dict) -> float | None:
    ebitda = _ebitda(year)
    if ebitda is None or ebitda <= 0 or year["totalDebt"] is None:
        return None
    return (year["totalDebt"] - (year["cash"] or 0.0)) / ebitda
