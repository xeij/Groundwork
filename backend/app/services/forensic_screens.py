"""Published earnings-quality screens run over a normalized XBRL fiscal-year history.

Every screen takes the history produced by `xbrl_metrics.build_financial_history` and
returns None the moment a required input is missing. That refusal is deliberate: a
Beneish score computed with two of its eight variables silently zeroed still looks like
a Beneish score to the reader, and a confidently wrong forensic number is worse than an
absent one.

None of these are verdicts. They are the screens auditors and short sellers start from,
and their false-positive rates are high on fast-growing and capital-intensive filers.
"""

import math

_MANIPULATION_THRESHOLD = -1.78  # Beneish: above this, the profile resembles manipulators
_BENEISH_WATCH_THRESHOLD = -2.22

_ALTMAN_SAFE = 2.9
_ALTMAN_DISTRESS = 1.23

_ACCRUAL_HIGH = 0.10
_ACCRUAL_ELEVATED = 0.05

# Zmijewski scores above zero imply a modelled probability of distress above 50%.
_ZMIJEWSKI_DISTRESS = 0.0
_ZMIJEWSKI_WATCH = -1.5

# Montier's C-score counts six aggressive-accounting traits out of six.
_C_SCORE_HIGH = 4
_C_SCORE_ELEVATED = 2
_C_SCORE_ASSET_GROWTH = 10.0

# Nigrini's published mean-absolute-deviation bands for a first-digit test.
_BENFORD_ACCEPTABLE_MAD = 0.012
_BENFORD_MARGINAL_MAD = 0.015
# Below this many distinct figures the digit distribution is noise, not a test.
_BENFORD_MIN_SAMPLE = 300
_BENFORD_MIN_VALUE = 100.0
# Benford's law: the share of naturally occurring figures whose first digit is d.
_BENFORD_EXPECTED = {digit: math.log10(1 + 1 / digit) for digit in range(1, 10)}

_BENEISH_FIELDS = (
    "revenue",
    "receivables",
    "grossProfit",
    "currentAssets",
    "ppeNet",
    "totalAssets",
    "depreciationAmortization",
    "sgaExpense",
    "currentLiabilities",
    "longTermDebt",
    "netIncome",
    "operatingCashFlow",
)

_ALTMAN_FIELDS = (
    "currentAssets",
    "currentLiabilities",
    "retainedEarnings",
    "totalAssets",
    "totalLiabilities",
    "stockholdersEquity",
    "revenue",
)

_PIOTROSKI_FIELDS = (
    "netIncome",
    "totalAssets",
    "operatingCashFlow",
    "longTermDebt",
    "currentAssets",
    "currentLiabilities",
    "dilutedShares",
    "grossProfit",
    "revenue",
)

_ACCRUAL_FIELDS = ("netIncome", "operatingCashFlow", "investingCashFlow", "totalAssets")

_ZMIJEWSKI_FIELDS = (
    "netIncome",
    "totalAssets",
    "totalLiabilities",
    "currentAssets",
    "currentLiabilities",
)

_C_SCORE_FIELDS = (
    "netIncome",
    "operatingCashFlow",
    "revenue",
    "receivables",
    "inventory",
    "costOfRevenue",
    "currentAssets",
    "cash",
    "totalAssets",
    "ppeNet",
    "depreciationAmortization",
)


def beneish_m_score(history: list[dict]) -> dict | None:
    """Beneish's eight-variable earnings-manipulation model, comparing t against t-1.

    Asset Quality follows the widely used simplification that treats current assets plus
    net PP&E as the "hard" assets; the original also nets out securities, which US filers
    tag too inconsistently to pull reliably.
    """
    latest, prior = _consecutive_years(history)
    if latest is None or not _has(latest, _BENEISH_FIELDS) or not _has(prior, _BENEISH_FIELDS):
        return None

    dsri = _ratio_of_ratios(latest["receivables"], latest["revenue"], prior["receivables"], prior["revenue"])
    # GMI inverts: a *falling* gross margin pushes the index above 1.
    gmi = _ratio_of_ratios(prior["grossProfit"], prior["revenue"], latest["grossProfit"], latest["revenue"])
    aqi = _div(_soft_asset_share(latest), _soft_asset_share(prior))
    sgi = _div(latest["revenue"], prior["revenue"])
    depi = _div(_depreciation_rate(prior), _depreciation_rate(latest))
    sgai = _ratio_of_ratios(latest["sgaExpense"], latest["revenue"], prior["sgaExpense"], prior["revenue"])
    lvgi = _div(_leverage(latest), _leverage(prior))
    tata = _div(latest["netIncome"] - latest["operatingCashFlow"], latest["totalAssets"])

    components = {
        "DSRI": dsri,
        "GMI": gmi,
        "AQI": aqi,
        "SGI": sgi,
        "DEPI": depi,
        "SGAI": sgai,
        "LVGI": lvgi,
        "TATA": tata,
    }
    if any(value is None for value in components.values()):
        return None

    score = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )

    if score > _MANIPULATION_THRESHOLD:
        severity = "red"
        interpretation = (
            "The accounting profile resembles that of companies later found to have "
            "manipulated earnings -- receivables, margins and accruals are moving the way "
            "they move when results are being flattered. It is a prompt to read the "
            "footnotes, not a finding of fraud."
        )
    elif score > _BENEISH_WATCH_THRESHOLD:
        severity = "yellow"
        interpretation = (
            "The model lands just under the manipulation threshold: nothing damning, but "
            "close enough that the trend is worth watching over the next year or two."
        )
    else:
        severity = "green"
        interpretation = (
            "The relationship between sales, receivables, margins and cash flow looks "
            "unremarkable -- no statistical resemblance to known earnings manipulators."
        )

    return {
        "key": "beneish_m",
        "label": "Beneish M-Score",
        "value": round(score, 2),
        "severity": severity,
        "interpretation": interpretation,
        "components": {name: round(value, 4) for name, value in components.items()},
        "basis": _basis(prior, latest),
    }


def altman_z_score(history: list[dict]) -> dict | None:
    """Altman's Z'-score, the private-firm variant of the bankruptcy model.

    The classic Z-score's X4 needs the market value of equity, which XBRL facts do not
    carry, so this uses Altman's own re-estimated Z' where X4 is book equity over total
    liabilities. The coefficients and the cut-offs differ from the market-value model;
    they are not interchangeable.
    """
    latest = history[-1] if history else None
    if latest is None or not _has(latest, _ALTMAN_FIELDS):
        return None

    ebit = _ebit(latest)
    total_assets = latest["totalAssets"]
    if ebit is None or not total_assets:
        return None

    x1 = _div(latest["currentAssets"] - latest["currentLiabilities"], total_assets)
    x2 = _div(latest["retainedEarnings"], total_assets)
    x3 = _div(ebit, total_assets)
    x4 = _div(latest["stockholdersEquity"], latest["totalLiabilities"])
    x5 = _div(latest["revenue"], total_assets)
    if any(value is None for value in (x1, x2, x3, x4, x5)):
        return None

    score = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5

    if score > _ALTMAN_SAFE:
        severity = "green"
        zone = (
            "sits in the model's safe zone, where bankruptcy within two years was rare in "
            "the original sample"
        )
    elif score >= _ALTMAN_DISTRESS:
        severity = "yellow"
        zone = "sits in the model's grey zone, where the signal is genuinely ambiguous"
    else:
        severity = "red"
        zone = (
            "sits in the model's distress zone, the range where a majority of the original "
            "sample filed for bankruptcy within two years"
        )

    return {
        "key": "altman_z",
        "label": "Altman Z'-Score",
        "value": round(score, 2),
        "severity": severity,
        "interpretation": (
            f"This company's financial-distress score {zone}. It is the private-firm Z' "
            "variant, which values equity at book rather than market, so a company the "
            "market prices well above book will score lower here than on the classic Z."
        ),
        "components": {
            "X1_workingCapitalToAssets": round(x1, 4),
            "X2_retainedEarningsToAssets": round(x2, 4),
            "X3_ebitToAssets": round(x3, 4),
            "X4_equityToLiabilities": round(x4, 4),
            "X5_salesToAssets": round(x5, 4),
        },
        "basis": f"FY{latest['fiscalYear']}",
    }


def piotroski_f_score(history: list[dict]) -> dict | None:
    """Piotroski's nine binary fundamental-strength signals, scored 0-9.

    Two deviations from the 2000 paper, both forced by only holding a few years of data:
    return on assets is computed on ending rather than beginning-of-year total assets,
    and the equity-issuance signal uses the diluted share count as its proxy.
    """
    latest, prior = _consecutive_years(history)
    if latest is None or not _has(latest, _PIOTROSKI_FIELDS) or not _has(prior, _PIOTROSKI_FIELDS):
        return None

    roa = _div(latest["netIncome"], latest["totalAssets"])
    prior_roa = _div(prior["netIncome"], prior["totalAssets"])
    leverage = _div(latest["longTermDebt"], latest["totalAssets"])
    prior_leverage = _div(prior["longTermDebt"], prior["totalAssets"])
    current_ratio = _div(latest["currentAssets"], latest["currentLiabilities"])
    prior_current_ratio = _div(prior["currentAssets"], prior["currentLiabilities"])
    margin = _div(latest["grossProfit"], latest["revenue"])
    prior_margin = _div(prior["grossProfit"], prior["revenue"])
    turnover = _div(latest["revenue"], latest["totalAssets"])
    prior_turnover = _div(prior["revenue"], prior["totalAssets"])

    signals = {
        "positiveNetIncome": roa is not None and roa > 0,
        "positiveOperatingCashFlow": latest["operatingCashFlow"] > 0,
        "improvingReturnOnAssets": _greater(roa, prior_roa),
        "cashFlowExceedsNetIncome": latest["operatingCashFlow"] > latest["netIncome"],
        "fallingLeverage": _greater(prior_leverage, leverage),
        "improvingCurrentRatio": _greater(current_ratio, prior_current_ratio),
        "noShareDilution": latest["dilutedShares"] <= prior["dilutedShares"],
        "improvingGrossMargin": _greater(margin, prior_margin),
        "improvingAssetTurnover": _greater(turnover, prior_turnover),
    }
    if any(value is None for value in (roa, prior_roa, leverage, prior_leverage, current_ratio, prior_current_ratio, margin, prior_margin, turnover, prior_turnover)):
        return None

    score = sum(1 for passed in signals.values() if passed)

    if score >= 7:
        severity = "green"
        verdict = "financially strong and improving on most fronts"
    elif score >= 4:
        severity = "yellow"
        verdict = "mixed -- improving in some areas while slipping in others"
    else:
        severity = "red"
        verdict = "weak, with most of the nine health checks failing"

    return {
        "key": "piotroski_f",
        "label": "Piotroski F-Score",
        "value": float(score),
        "severity": severity,
        "interpretation": (
            f"The company passes {score} of 9 basic tests of profitability, debt and "
            f"operating efficiency, which reads as {verdict}."
        ),
        "components": {name: (1.0 if passed else 0.0) for name, passed in signals.items()},
        "basis": _basis(prior, latest),
    }


def accrual_ratio(history: list[dict]) -> dict | None:
    """Sloan's cash-flow-statement accrual ratio.

    Uses the cash-flow variant -- (net income - operating cash flow - investing cash
    flow) / average total assets -- rather than the balance-sheet variant, because it is
    immune to the distortions acquisitions introduce into balance-sheet deltas. Average
    assets requires the prior year, so a single-year history returns None.
    """
    latest, prior = _consecutive_years(history)
    if latest is None or not _has(latest, _ACCRUAL_FIELDS) or prior.get("totalAssets") is None:
        return None

    average_assets = (latest["totalAssets"] + prior["totalAssets"]) / 2
    accruals = latest["netIncome"] - latest["operatingCashFlow"] - latest["investingCashFlow"]
    ratio = _div(accruals, average_assets)
    if ratio is None:
        return None

    if ratio > _ACCRUAL_HIGH:
        severity = "red"
        interpretation = (
            "A large share of reported profit is accounting entries rather than cash that "
            "arrived. Companies in this range have historically gone on to report weaker "
            "earnings than the headline number suggested. The measure counts investment "
            "alongside working-capital accruals, so an unusually heavy year of building "
            "factories or data centres can push it up with no aggression involved."
        )
    elif ratio > _ACCRUAL_ELEVATED:
        severity = "yellow"
        interpretation = (
            "Reported profit is running somewhat ahead of the cash the business actually "
            "generated -- worth checking whether receivables or inventory explain the gap."
        )
    else:
        severity = "green"
        interpretation = (
            "Reported profit is backed by cash rather than by accounting estimates, which "
            "is the pattern associated with earnings that persist."
        )

    return {
        "key": "accrual_ratio",
        "label": "Sloan Accrual Ratio",
        "value": round(ratio * 100, 2),
        "severity": severity,
        "interpretation": interpretation,
        "components": {
            "netIncome": float(latest["netIncome"]),
            "operatingCashFlow": float(latest["operatingCashFlow"]),
            "investingCashFlow": float(latest["investingCashFlow"]),
            "averageTotalAssets": round(average_assets, 2),
            "accruals": round(accruals, 2),
        },
        "basis": _basis(prior, latest),
    }


def zmijewski_score(history: list[dict]) -> dict | None:
    """Zmijewski's three-variable probit model of financial distress.

    Where Altman's Z' asks whether the balance sheet has a cushion, this asks a narrower
    question -- is the company profitable, levered and liquid -- and converts the answer
    into a modelled probability. It needs no market data and no prior year, so it is the
    distress screen most likely to be available at all.

    The liquidity coefficient is tiny (-0.004) and was statistically insignificant in
    the original 1984 estimation; it is kept because it is part of the published model,
    but it moves the score by almost nothing.
    """
    latest = history[-1] if history else None
    if latest is None or not _has(latest, _ZMIJEWSKI_FIELDS):
        return None

    roa = _div(latest["netIncome"], latest["totalAssets"])
    leverage = _div(latest["totalLiabilities"], latest["totalAssets"])
    liquidity = _div(latest["currentAssets"], latest["currentLiabilities"])
    if any(value is None for value in (roa, leverage, liquidity)):
        return None

    score = -4.336 - 4.513 * roa + 5.679 * leverage - 0.004 * liquidity
    probability = 1 / (1 + math.exp(-score)) if -700 < score < 700 else float(score > 0)

    if score > _ZMIJEWSKI_DISTRESS:
        severity = "red"
        interpretation = (
            f"The model puts the probability of financial distress at {probability * 100:.0f}%, "
            "above the 50% line where it classifies a company as distressed. That is driven "
            "by some combination of losses, liabilities that are large against assets, and "
            "thin current-asset cover."
        )
    elif score > _ZMIJEWSKI_WATCH:
        severity = "yellow"
        interpretation = (
            f"The modelled probability of distress is {probability * 100:.0f}%. Below the "
            "classification line, but not comfortably so: profitability or leverage is "
            "doing most of the work holding it there."
        )
    else:
        severity = "green"
        interpretation = (
            f"The modelled probability of distress is {probability * 100:.0f}%. Profitability "
            "and the liability load both sit where the model expects for a company that "
            "keeps operating normally."
        )

    return {
        "key": "zmijewski",
        "label": "Zmijewski Distress Score",
        "value": round(score, 2),
        "severity": severity,
        "interpretation": interpretation,
        "components": {
            "returnOnAssets": round(roa, 4),
            "liabilitiesToAssets": round(leverage, 4),
            "currentRatio": round(liquidity, 4),
            "probabilityOfDistress": round(probability, 4),
        },
        "basis": f"FY{latest['fiscalYear']}",
    }


def montier_c_score(history: list[dict]) -> dict | None:
    """Montier's C-score: six traits shared by companies that were cooking the books.

    Unlike Beneish this is not a regression -- each trait is a yes/no question, and the
    score is how many fired. Two substitutions are forced by what XBRL carries: "other
    current assets" is backed out of current assets less cash, receivables and inventory,
    and the depreciation trait is measured against net PP&E because gross PP&E is
    tagged too inconsistently to rely on. Both are noted in the components.
    """
    latest, prior = _consecutive_years(history)
    if latest is None or not _has(latest, _C_SCORE_FIELDS) or not _has(prior, _C_SCORE_FIELDS):
        return None

    traits = {
        "earningsOutrunningCash": _greater(
            latest["netIncome"] - latest["operatingCashFlow"],
            prior["netIncome"] - prior["operatingCashFlow"],
        ),
        "risingDaysSalesOutstanding": _greater(
            _days_sales_outstanding(latest), _days_sales_outstanding(prior)
        ),
        "risingDaysInventory": _greater(_days_inventory(latest), _days_inventory(prior)),
        "risingOtherCurrentAssets": _greater(
            _percent(_other_current_assets(latest), latest["revenue"]),
            _percent(_other_current_assets(prior), prior["revenue"]),
        ),
        "fallingDepreciationRate": _greater(
            _depreciation_rate(prior), _depreciation_rate(latest)
        ),
        "assetsGrowingFast": _asset_growth_exceeds(latest, prior, _C_SCORE_ASSET_GROWTH),
    }
    if any(value is None for value in traits.values()):
        return None

    score = sum(1 for fired in traits.values() if fired)

    if score >= _C_SCORE_HIGH:
        severity = "red"
        verdict = (
            "Most of the pattern is present at once. Each trait alone has an innocent "
            "explanation; together they are the profile Montier built the score to catch."
        )
    elif score >= _C_SCORE_ELEVATED:
        severity = "yellow"
        verdict = (
            "A few of the traits are present. That is common in a growth year and is a "
            "prompt to check the working-capital note rather than a conclusion."
        )
    else:
        severity = "green"
        verdict = "Almost none of the pattern is present."

    return {
        "key": "montier_c",
        "label": "Montier C-Score",
        "value": float(score),
        "severity": severity,
        "interpretation": (
            f"{score} of 6 aggressive-accounting traits are present: growing distance "
            "between profit and cash, slower collection, slower inventory turns, a rising "
            "bucket of other current assets, a falling depreciation rate, and fast asset "
            f"growth. {verdict}"
        ),
        "components": {name: (1.0 if fired else 0.0) for name, fired in traits.items()},
        "basis": _basis(prior, latest),
    }


def benford_digit_test(company_facts: dict | None) -> dict | None:
    """A first-digit test over every dollar figure the company has ever tagged.

    Naturally occurring financial figures start with 1 about 30% of the time and with 9
    about 4.6% of the time. Numbers that have been adjusted by hand tend not to, which
    is why this test is standard in forensic accounting -- and why it is reported here
    as at most a yellow: a filer with few distinct figures, heavy rounding, or a lot of
    bounded quantities can fail it while doing nothing wrong. It is evidence that a
    distribution looks unusual, never evidence of manipulation.

    Values are deduplicated on (concept, period, value) first, because the same figure
    is restated in every subsequent filing and would otherwise be counted many times.
    """
    values = _tagged_dollar_values(company_facts)
    if len(values) < _BENFORD_MIN_SAMPLE:
        return None

    counts = {digit: 0 for digit in range(1, 10)}
    for value in values:
        counts[_leading_digit(value)] += 1

    total = len(values)
    observed = {digit: counts[digit] / total for digit in counts}
    deviation = sum(abs(observed[d] - _BENFORD_EXPECTED[d]) for d in counts) / 9

    if deviation > _BENFORD_MARGINAL_MAD:
        severity = "yellow"
        interpretation = (
            f"Across {total:,} distinct tagged figures, the spread of leading digits sits "
            "outside the range Nigrini calls conforming. Rounded reporting, a small number "
            "of repeated figures and heavily bounded quantities all produce this without "
            "any manipulation, so treat it as a reason to look at the numbers rather than "
            "as a finding about them."
        )
    elif deviation > _BENFORD_ACCEPTABLE_MAD:
        severity = "green"
        interpretation = (
            f"Across {total:,} distinct tagged figures, the leading-digit spread is "
            "marginal against Nigrini's bands -- within the range ordinary rounding "
            "produces."
        )
    else:
        severity = "green"
        interpretation = (
            f"Across {total:,} distinct tagged figures, the leading digits follow the "
            "distribution naturally occurring financial data follows."
        )

    components = {f"digit{digit}Percent": round(observed[digit] * 100, 2) for digit in counts}
    components["sampleSize"] = float(total)
    components["meanAbsoluteDeviation"] = round(deviation, 5)

    return {
        "key": "benford",
        "label": "Benford First-Digit Test",
        "value": round(deviation * 100, 2),
        "severity": severity,
        "interpretation": interpretation,
        "components": components,
        "basis": "every USD figure in the company's XBRL history",
    }


def _tagged_dollar_values(company_facts: dict | None) -> list[float]:
    """Distinct USD-denominated facts, large enough for a first digit to mean anything."""
    if not isinstance(company_facts, dict):
        return []
    gaap = (company_facts.get("facts") or {}).get("us-gaap")
    if not isinstance(gaap, dict):
        return []

    seen: set[tuple] = set()
    values: list[float] = []
    for concept, detail in gaap.items():
        facts = (detail.get("units") or {}).get("USD") if isinstance(detail, dict) else None
        if not isinstance(facts, list):
            continue
        for fact in facts:
            value = fact.get("val")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            magnitude = abs(float(value))
            if magnitude < _BENFORD_MIN_VALUE:
                continue
            key = (concept, fact.get("start"), fact.get("end"), value)
            if key in seen:
                continue
            seen.add(key)
            values.append(magnitude)
    return values


def _leading_digit(value: float) -> int:
    text = f"{value:.10f}".replace(".", "").lstrip("0")
    return int(text[0]) if text else 1


def _days_inventory(year: dict) -> float | None:
    ratio = _percent(year.get("inventory"), year.get("costOfRevenue"))
    return None if ratio is None else ratio / 100 * 365.0


def _other_current_assets(year: dict) -> float | None:
    """Current assets less the three lines that are individually tagged.

    The residual is where prepayments and deferred charges sit -- the bucket that grows
    when costs are being parked on the balance sheet instead of expensed.
    """
    if year.get("currentAssets") is None:
        return None
    known = sum(year.get(field) or 0.0 for field in ("cash", "receivables", "inventory"))
    residual = year["currentAssets"] - known
    return residual if residual >= 0 else None


def _asset_growth_exceeds(latest: dict, prior: dict, threshold: float) -> bool | None:
    growth = _growth(latest.get("totalAssets"), prior.get("totalAssets"))
    return None if growth is None else growth > threshold


def divergence_flags(history: list[dict]) -> list[dict]:
    """Year-over-year relationships that should track each other and stopped doing so."""
    latest, prior = _consecutive_years(history)
    if latest is None:
        return []

    flags = []
    for detect in _DIVERGENCE_CHECKS:
        flag = detect(latest, prior)
        if flag is not None:
            flag["basis"] = _basis(prior, latest)
            flags.append(flag)
    return flags


def run_all_screens(history: list[dict], company_facts: dict | None = None) -> dict:
    """Every screen that has the inputs it needs.

    `company_facts` is optional because only the digit test reads the raw fact blob;
    everything else works off the normalized history.
    """
    screens = [
        screen
        for screen in (
            beneish_m_score(history),
            altman_z_score(history),
            zmijewski_score(history),
            piotroski_f_score(history),
            montier_c_score(history),
            accrual_ratio(history),
            benford_digit_test(company_facts),
        )
        if screen is not None
    ]
    return {"screens": screens, "flags": divergence_flags(history)}


def _receivables_divergence(latest: dict, prior: dict) -> dict | None:
    revenue_growth = _growth(latest.get("revenue"), prior.get("revenue"))
    receivables_growth = _growth(latest.get("receivables"), prior.get("receivables"))
    if revenue_growth is None or receivables_growth is None:
        return None

    gap = receivables_growth - revenue_growth
    if gap < 10:
        return None
    return {
        "key": "receivables_outpacing_revenue",
        "label": "Receivables Growing Faster Than Sales",
        "severity": "red" if gap >= 25 else "yellow",
        "interpretation": (
            f"Money owed by customers grew {receivables_growth:.1f}% while sales grew "
            f"{revenue_growth:.1f}%. Sales are being booked faster than they are being "
            "collected, which can mean looser credit terms, channel stuffing, or revenue "
            "recognized before the cash is really coming."
        ),
        "detail": {
            "revenueGrowthPercent": round(revenue_growth, 2),
            "receivablesGrowthPercent": round(receivables_growth, 2),
            "gapPercentagePoints": round(gap, 2),
        },
    }


def _inventory_divergence(latest: dict, prior: dict) -> dict | None:
    revenue_growth = _growth(latest.get("revenue"), prior.get("revenue"))
    inventory_growth = _growth(latest.get("inventory"), prior.get("inventory"))
    if revenue_growth is None or inventory_growth is None:
        return None

    gap = inventory_growth - revenue_growth
    if gap < 10:
        return None
    return {
        "key": "inventory_outpacing_revenue",
        "label": "Inventory Building Faster Than Sales",
        "severity": "red" if gap >= 25 else "yellow",
        "interpretation": (
            f"Inventory rose {inventory_growth:.1f}% against {revenue_growth:.1f}% sales "
            "growth. Goods are piling up faster than they sell, which often precedes "
            "discounting or a write-down that lands in a future quarter's margin."
        ),
        "detail": {
            "revenueGrowthPercent": round(revenue_growth, 2),
            "inventoryGrowthPercent": round(inventory_growth, 2),
            "gapPercentagePoints": round(gap, 2),
        },
    }


def _earnings_versus_cash(latest: dict, prior: dict) -> dict | None:
    if any(latest[field] is None or prior[field] is None for field in ("netIncome", "operatingCashFlow")):
        return None
    if not (latest.get("netIncome") > prior.get("netIncome") and latest.get("operatingCashFlow") < prior.get("operatingCashFlow")):
        return None

    decline = _growth(latest.get("operatingCashFlow"), prior.get("operatingCashFlow"))
    return {
        "key": "earnings_up_cash_down",
        "label": "Profit Rising While Cash Flow Falls",
        "severity": "red" if decline is not None and decline <= -10 else "yellow",
        "interpretation": (
            "Reported profit went up but the cash generated by the business went down. "
            "Over a single year that can be timing; sustained, it is the classic signature "
            "of earnings supported by accounting choices rather than trade."
        ),
        "detail": {
            "netIncome": float(latest.get("netIncome")),
            "priorNetIncome": float(prior.get("netIncome")),
            "operatingCashFlow": float(latest.get("operatingCashFlow")),
            "priorOperatingCashFlow": float(prior.get("operatingCashFlow")),
        },
    }


def _stock_comp_dependence(latest: dict, prior: dict) -> dict | None:
    share = _share_of_operating_cash_flow(latest)
    prior_share = _share_of_operating_cash_flow(prior)
    if share is None or share < 25:
        return None
    if prior_share is not None and share <= prior_share:
        return None

    return {
        "key": "cash_flow_leaning_on_stock_comp",
        "label": "Cash Flow Increasingly Driven by Stock Compensation",
        "severity": "red" if share >= 40 else "yellow",
        "interpretation": (
            f"Stock granted to employees accounts for {share:.0f}% of operating cash flow, "
            "up from the prior year. That expense is added back as if it were free, but it "
            "is paid for by shareholders through dilution rather than by the business."
        ),
        "detail": {
            "sbcPercentOfOperatingCashFlow": round(share, 2),
            "priorSbcPercentOfOperatingCashFlow": None if prior_share is None else round(prior_share, 2),
            "shareBasedCompensation": float(latest["shareBasedCompensation"]),
            "operatingCashFlow": float(latest.get("operatingCashFlow")),
        },
    }


def _margin_compression(latest: dict, prior: dict) -> dict | None:
    margin = _percent(latest.get("grossProfit"), latest.get("revenue"))
    prior_margin = _percent(prior.get("grossProfit"), prior.get("revenue"))
    if margin is None or prior_margin is None:
        return None

    drop = prior_margin - margin
    if drop < 2:
        return None
    return {
        "key": "margin_compression",
        "label": "Gross Margin Compression",
        "severity": "red" if drop >= 5 else "yellow",
        "interpretation": (
            f"Gross margin fell from {prior_margin:.1f}% to {margin:.1f}%. The company is "
            "keeping less of every sales dollar than it did a year ago -- rising input "
            "costs, price cuts, or a shift toward lower-margin products."
        ),
        "detail": {
            "grossMarginPercent": round(margin, 2),
            "priorGrossMarginPercent": round(prior_margin, 2),
            "declinePercentagePoints": round(drop, 2),
        },
    }


def _rising_days_sales_outstanding(latest: dict, prior: dict) -> dict | None:
    dso = _days_sales_outstanding(latest)
    prior_dso = _days_sales_outstanding(prior)
    if dso is None or prior_dso is None:
        return None

    change = _growth(dso, prior_dso)
    if change is None or change < 10:
        return None
    return {
        "key": "rising_days_sales_outstanding",
        "label": "Customers Taking Longer to Pay",
        "severity": "red" if change >= 25 else "yellow",
        "interpretation": (
            f"It now takes about {dso:.0f} days to collect a sale, up from {prior_dso:.0f}. "
            "Slower collection ties up cash and can be an early sign that customers are "
            "struggling or that sales were pulled forward on soft terms."
        ),
        "detail": {
            "daysSalesOutstanding": round(dso, 2),
            "priorDaysSalesOutstanding": round(prior_dso, 2),
            "changePercent": round(change, 2),
        },
    }


def _debt_outpacing_ebitda(latest: dict, prior: dict) -> dict | None:
    debt_growth = _growth(latest.get("totalDebt"), prior.get("totalDebt"))
    ebitda = _ebitda(latest)
    prior_ebitda = _ebitda(prior)
    if debt_growth is None or ebitda is None or prior_ebitda is None or prior_ebitda <= 0:
        return None
    if debt_growth <= 0:
        return None

    ebitda_growth = (ebitda / prior_ebitda - 1) * 100
    gap = debt_growth - ebitda_growth
    if gap < 20:
        return None

    leverage = None if ebitda <= 0 else (latest.get("totalDebt") - (latest.get("cash") or 0.0)) / ebitda
    return {
        "key": "debt_outpacing_ebitda",
        "label": "Borrowing Growing Faster Than Earnings",
        "severity": "red" if (leverage is not None and leverage > 3) or ebitda_growth < 0 else "yellow",
        "interpretation": (
            f"Debt rose {debt_growth:.1f}% while operating earnings before depreciation "
            f"moved {ebitda_growth:.1f}%. The company is adding borrowings faster than it is "
            "adding the earnings that have to service them."
        ),
        "detail": {
            "debtGrowthPercent": round(debt_growth, 2),
            "ebitdaGrowthPercent": round(ebitda_growth, 2),
            "netDebtToEbitda": None if leverage is None else round(leverage, 2),
            "totalDebt": float(latest.get("totalDebt")),
        },
    }


def _deferred_revenue_divergence(latest: dict, prior: dict) -> dict | None:
    """Revenue up, the pile of money customers have prepaid down.

    Deferred revenue is work already paid for and not yet delivered, so it leads the
    income statement. Recognised revenue rising while it falls means this year's growth
    is being drawn from a balance that is not being refilled.
    """
    revenue_growth = _growth(latest.get("revenue"), prior.get("revenue"))
    deferred_growth = _growth(latest.get("deferredRevenue"), prior.get("deferredRevenue"))
    if revenue_growth is None or deferred_growth is None:
        return None
    if revenue_growth < 5 or deferred_growth > -5:
        return None

    return {
        "key": "deferred_revenue_shrinking",
        "label": "Prepaid Customer Balances Falling While Sales Rise",
        "severity": "red" if deferred_growth <= -15 else "yellow",
        "interpretation": (
            f"Reported revenue grew {revenue_growth:.1f}% while deferred revenue -- money "
            f"customers have already paid for undelivered work -- fell {abs(deferred_growth):.1f}%. "
            "That balance normally leads sales, so this pattern means growth is being "
            "recognised out of a backlog that is not being replaced at the same rate."
        ),
        "detail": {
            "revenueGrowthPercent": round(revenue_growth, 2),
            "deferredRevenueGrowthPercent": round(deferred_growth, 2),
            "deferredRevenue": float(latest["deferredRevenue"]),
        },
    }


def _tax_rate_collapse(latest: dict, prior: dict) -> dict | None:
    """Profit helped along by the tax line rather than by the business."""
    rate = _percent(latest.get("incomeTaxExpense"), latest.get("pretaxIncome"))
    prior_rate = _percent(prior.get("incomeTaxExpense"), prior.get("pretaxIncome"))
    if rate is None or prior_rate is None:
        return None

    drop = prior_rate - rate
    if drop < 10:
        return None

    saving = latest["pretaxIncome"] * drop / 100
    share_of_profit = _percent(saving, latest.get("netIncome"))
    share = (
        f" That is worth about {saving:,.0f} of profit, {share_of_profit:.0f}% of the year's "
        "net income."
        if share_of_profit is not None
        else ""
    )
    return {
        "key": "tax_rate_collapse",
        "label": "Effective Tax Rate Dropped Sharply",
        "severity": "red" if drop >= 20 else "yellow",
        "interpretation": (
            f"The effective tax rate fell from {prior_rate:.1f}% to {rate:.1f}%.{share} Tax "
            "rates move for durable reasons and for one-off ones -- a settled dispute, a "
            "valuation-allowance release, a repatriation -- and only the durable kind "
            "repeats next year. The rate reconciliation in the tax note says which this is."
        ),
        "detail": {
            "effectiveTaxRatePercent": round(rate, 2),
            "priorEffectiveTaxRatePercent": round(prior_rate, 2),
            "dropPercentagePoints": round(drop, 2),
            "profitEffect": round(saving, 2),
        },
    }


_DIVERGENCE_CHECKS = (
    _receivables_divergence,
    _inventory_divergence,
    _earnings_versus_cash,
    _stock_comp_dependence,
    _margin_compression,
    _rising_days_sales_outstanding,
    _debt_outpacing_ebitda,
    _deferred_revenue_divergence,
    _tax_rate_collapse,
)


def _consecutive_years(history: list[dict]) -> tuple[dict | None, dict]:
    """The latest year and the one before it. Every screen here is a year-over-year test."""
    if not history or len(history) < 2:
        return None, {}
    return history[-1], history[-2]


def _has(year: dict, fields: tuple[str, ...]) -> bool:
    return all(year.get(field) is not None for field in fields)


def _basis(prior: dict, latest: dict) -> str:
    return f"FY{prior['fiscalYear']} → FY{latest['fiscalYear']}"


def _div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _ratio_of_ratios(
    numerator_now: float | None,
    base_now: float | None,
    numerator_then: float | None,
    base_then: float | None,
) -> float | None:
    return _div(_div(numerator_now, base_now), _div(numerator_then, base_then))


def _soft_asset_share(year: dict) -> float | None:
    """Beneish AQI's asset-quality term: the share of assets that is neither working
    capital nor plant, i.e. the capitalized-cost bucket where deferred charges hide."""
    hard = _div(year["currentAssets"] + year["ppeNet"], year["totalAssets"])
    return None if hard is None else 1 - hard


def _depreciation_rate(year: dict) -> float | None:
    base = year["depreciationAmortization"] + year["ppeNet"]
    return _div(year["depreciationAmortization"], base)


def _leverage(year: dict) -> float | None:
    return _div(year["currentLiabilities"] + year["longTermDebt"], year["totalAssets"])


def _ebit(year: dict) -> float | None:
    if year.get("operatingIncome") is not None:
        return float(year["operatingIncome"])
    # Rebuild EBIT from the bottom up for filers that never tag an operating subtotal.
    if year.get("netIncome") is None:
        return None
    return year["netIncome"] + (year.get("incomeTaxExpense") or 0.0) + (year.get("interestExpense") or 0.0)


def _ebitda(year: dict) -> float | None:
    if year.get("operatingIncome") is None or year.get("depreciationAmortization") is None:
        return None
    return year["operatingIncome"] + year["depreciationAmortization"]


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1) * 100


def _percent(numerator: float | None, denominator: float | None) -> float | None:
    if denominator is None or denominator <= 0 or numerator is None:
        return None
    return numerator / denominator * 100


def _share_of_operating_cash_flow(year: dict) -> float | None:
    return _percent(year.get("shareBasedCompensation"), year.get("operatingCashFlow"))


def _days_sales_outstanding(year: dict) -> float | None:
    ratio = _percent(year.get("receivables"), year.get("revenue"))
    return None if ratio is None else ratio / 100 * 365.0


def _greater(current: float | None, previous: float | None) -> bool | None:
    if current is None or previous is None:
        return None
    return current > previous
