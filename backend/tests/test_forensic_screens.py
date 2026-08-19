"""Worked examples for the earnings-quality screens.

Every expected score below is written as the arithmetic that produces it rather than as
a magic number, so a reviewer can check the formula against the published model without
running anything.
"""

import pytest

from app.services.forensic_screens import (
    accrual_ratio,
    altman_z_score,
    beneish_m_score,
    divergence_flags,
    piotroski_f_score,
    run_all_screens,
)

# Round numbers chosen so every index below divides out cleanly by hand.
PRIOR = {
    "fiscalYear": 2023,
    "periodEnd": "2023-12-31",
    "revenue": 1000.0,
    "costOfRevenue": 600.0,
    "grossProfit": 400.0,
    "operatingIncome": 160.0,
    "netIncome": 100.0,
    "sgaExpense": 200.0,
    "totalAssets": 1000.0,
    "currentAssets": 500.0,
    "currentLiabilities": 200.0,
    "totalLiabilities": 500.0,
    "stockholdersEquity": 500.0,
    "retainedEarnings": 350.0,
    "cash": 120.0,
    "receivables": 100.0,
    "inventory": 80.0,
    "ppeNet": 300.0,
    "longTermDebt": 300.0,
    "totalDebt": 300.0,
    "operatingCashFlow": 150.0,
    "investingCashFlow": -60.0,
    "financingCashFlow": -20.0,
    "capex": 60.0,
    "depreciationAmortization": 100.0,
    "shareBasedCompensation": 15.0,
    "interestExpense": 10.0,
    "incomeTaxExpense": 50.0,
    "dilutedShares": 100.0,
}

LATEST = {
    **PRIOR,
    "fiscalYear": 2024,
    "periodEnd": "2024-12-31",
    "revenue": 1200.0,
    "costOfRevenue": 780.0,
    "grossProfit": 420.0,
    "operatingIncome": 190.0,
    "netIncome": 140.0,
    "sgaExpense": 230.0,
    "totalAssets": 1200.0,
    "currentAssets": 600.0,
    "currentLiabilities": 250.0,
    "totalLiabilities": 600.0,
    "stockholdersEquity": 600.0,
    "retainedEarnings": 400.0,
    "receivables": 180.0,
    "ppeNet": 350.0,
    "longTermDebt": 350.0,
    "totalDebt": 350.0,
    "operatingCashFlow": 120.0,
    "investingCashFlow": -80.0,
    "depreciationAmortization": 105.0,
    "dilutedShares": 105.0,
}

HISTORY = [PRIOR, LATEST]


def _without(year: dict, field: str) -> dict:
    return {**year, field: None}


# --- Beneish ------------------------------------------------------------------------


def test_beneish_components_match_the_published_definitions():
    result = beneish_m_score(HISTORY)
    c = result["components"]

    # DSRI: receivables/sales, this year over last.  (180/1200) / (100/1000) = 1.5
    assert c["DSRI"] == pytest.approx(1.5)
    # GMI inverts — a *falling* gross margin pushes it above 1.  0.40 / 0.35
    assert c["GMI"] == pytest.approx(round((400 / 1000) / (420 / 1200), 4))
    # AQI: share of assets that is neither working capital nor plant.
    assert c["AQI"] == pytest.approx(round((1 - 950 / 1200) / (1 - 800 / 1000), 4))
    # SGI: plain sales growth.  1200/1000
    assert c["SGI"] == pytest.approx(1.2)
    # DEPI also inverts: a *slowing* depreciation rate pushes it above 1.
    assert c["DEPI"] == pytest.approx(round((100 / 400) / (105 / 455), 4))
    # SGAI: SG&A/sales, this year over last.  (230/1200) / (200/1000)
    assert c["SGAI"] == pytest.approx(round((230 / 1200) / (200 / 1000), 4))
    # LVGI: (current liabilities + long-term debt) / assets, unchanged at 0.5 both years.
    assert c["LVGI"] == pytest.approx(1.0)
    # TATA: accruals over assets.  (140 - 120) / 1200
    assert c["TATA"] == pytest.approx(round(20 / 1200, 4))


def test_beneish_m_score_matches_a_hand_computed_value():
    expected = (
        -4.84
        + 0.920 * 1.5
        + 0.528 * ((400 / 1000) / (420 / 1200))
        + 0.404 * ((1 - 950 / 1200) / (1 - 800 / 1000))
        + 0.892 * 1.2
        + 0.115 * ((100 / 400) / (105 / 455))
        - 0.172 * ((230 / 1200) / (200 / 1000))
        + 4.679 * (20 / 1200)
        - 0.327 * 1.0
    )
    assert beneish_m_score(HISTORY)["value"] == pytest.approx(round(expected, 2))


def test_beneish_flags_red_above_the_manipulation_threshold():
    result = beneish_m_score(HISTORY)
    assert result["value"] > -1.78
    assert result["severity"] == "red"


def test_beneish_is_green_for_a_company_that_did_not_move():
    """Identical years produce the model's neutral profile, well below the threshold."""
    flat = [PRIOR, {**PRIOR, "fiscalYear": 2024}]
    result = beneish_m_score(flat)
    assert result["severity"] == "green"
    assert result["value"] < -2.22


def test_beneish_returns_none_when_any_input_is_untagged():
    """A score computed from partial inputs still looks like a score to a reader."""
    for field in ("receivables", "grossProfit", "ppeNet", "sgaExpense", "operatingCashFlow"):
        assert beneish_m_score([PRIOR, _without(LATEST, field)]) is None, field


def test_beneish_returns_none_without_a_prior_year():
    assert beneish_m_score([LATEST]) is None
    assert beneish_m_score([]) is None


def test_beneish_reports_the_years_it_compared():
    assert beneish_m_score(HISTORY)["basis"] == "FY2023 → FY2024"


# --- Altman -------------------------------------------------------------------------


def test_altman_z_matches_a_hand_computed_value():
    x1 = (600 - 250) / 1200      # working capital / assets
    x2 = 400 / 1200              # retained earnings / assets
    x3 = 190 / 1200              # EBIT / assets
    x4 = 600 / 600               # book equity / total liabilities (the private-firm Z')
    x5 = 1200 / 1200             # sales / assets
    expected = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5
    assert altman_z_score(HISTORY)["value"] == pytest.approx(round(expected, 2))


def test_altman_uses_the_private_firm_coefficients_not_the_market_ones():
    """The Z' variant is not interchangeable with the classic market-value Z."""
    result = altman_z_score(HISTORY)
    assert "Z'" in result["label"]
    assert "book rather than market" in result["interpretation"]
    assert set(result["components"]) == {
        "X1_workingCapitalToAssets",
        "X2_retainedEarningsToAssets",
        "X3_ebitToAssets",
        "X4_equityToLiabilities",
        "X5_salesToAssets",
    }


@pytest.mark.parametrize(
    "operating_income,expected_severity",
    [(190.0, "yellow"), (2000.0, "green"), (-400.0, "red")],
)
def test_altman_zones(operating_income, expected_severity):
    year = {**LATEST, "operatingIncome": operating_income}
    assert altman_z_score([PRIOR, year])["severity"] == expected_severity


def test_altman_rebuilds_ebit_when_no_operating_subtotal_is_tagged():
    """Some filers never tag an operating income line; EBIT comes back from the bottom up."""
    year = _without(LATEST, "operatingIncome")
    result = altman_z_score([PRIOR, year])
    rebuilt_ebit = 140 + 50 + 10  # net income + tax + interest
    assert result["components"]["X3_ebitToAssets"] == pytest.approx(round(rebuilt_ebit / 1200, 4))


def test_altman_returns_none_without_the_balance_sheet():
    for field in ("retainedEarnings", "totalLiabilities", "stockholdersEquity", "currentAssets"):
        assert altman_z_score([PRIOR, _without(LATEST, field)]) is None, field


# --- Piotroski ----------------------------------------------------------------------


def test_piotroski_scores_each_of_the_nine_signals():
    result = piotroski_f_score(HISTORY)
    signals = result["components"]

    assert signals["positiveNetIncome"] == 1.0                 # 140 > 0
    assert signals["positiveOperatingCashFlow"] == 1.0         # 120 > 0
    assert signals["improvingReturnOnAssets"] == 1.0           # 140/1200 > 100/1000
    assert signals["cashFlowExceedsNetIncome"] == 0.0          # 120 < 140
    assert signals["fallingLeverage"] == 1.0                   # 350/1200 < 300/1000
    assert signals["improvingCurrentRatio"] == 0.0             # 2.40 < 2.50
    assert signals["noShareDilution"] == 0.0                   # 105 > 100
    assert signals["improvingGrossMargin"] == 0.0              # 0.35 < 0.40
    assert signals["improvingAssetTurnover"] == 0.0            # 1.00 not > 1.00

    assert result["value"] == 4.0
    assert result["severity"] == "yellow"


def test_piotroski_is_bounded_to_the_zero_to_nine_range():
    strong = {
        **LATEST, "netIncome": 400.0, "operatingCashFlow": 500.0, "longTermDebt": 100.0,
        "currentAssets": 900.0, "currentLiabilities": 100.0, "dilutedShares": 90.0,
        "grossProfit": 800.0, "revenue": 1600.0,
    }
    weak = {**LATEST, "netIncome": -50.0, "operatingCashFlow": -70.0}

    assert piotroski_f_score([PRIOR, strong])["value"] == 9.0
    assert piotroski_f_score([PRIOR, strong])["severity"] == "green"
    assert piotroski_f_score([PRIOR, weak])["value"] <= 3.0
    assert piotroski_f_score([PRIOR, weak])["severity"] == "red"


def test_piotroski_returns_none_when_share_count_is_untagged():
    assert piotroski_f_score([PRIOR, _without(LATEST, "dilutedShares")]) is None


# --- Sloan accruals -----------------------------------------------------------------


def test_accrual_ratio_matches_a_hand_computed_value():
    accruals = 140 - 120 - (-80)          # net income - operating CF - investing CF
    average_assets = (1200 + 1000) / 2
    expected_percent = accruals / average_assets * 100   # 100 / 1100 = 9.09%
    result = accrual_ratio(HISTORY)
    assert result["value"] == pytest.approx(round(expected_percent, 2))
    assert result["components"]["averageTotalAssets"] == 1100.0
    assert result["components"]["accruals"] == 100.0


@pytest.mark.parametrize(
    "net_income,expected_severity",
    [(90.0, "green"), (140.0, "yellow"), (300.0, "red")],
)
def test_accrual_ratio_severity_bands(net_income, expected_severity):
    year = {**LATEST, "netIncome": net_income}
    assert accrual_ratio([PRIOR, year])["severity"] == expected_severity


def test_accrual_ratio_needs_the_prior_year_for_average_assets():
    assert accrual_ratio([LATEST]) is None


def test_accrual_ratio_returns_none_without_investing_cash_flow():
    assert accrual_ratio([PRIOR, _without(LATEST, "investingCashFlow")]) is None


# --- divergence flags ---------------------------------------------------------------


def test_receivables_outrunning_revenue_is_flagged():
    """Revenue +20% against receivables +80% is the classic channel-stuffing shape."""
    keys = {flag["key"] for flag in divergence_flags(HISTORY)}
    assert any("receivable" in key.lower() for key in keys), keys


def test_net_income_rising_while_cash_flow_falls_is_flagged():
    flags = divergence_flags(HISTORY)
    assert any(
        "cash" in flag["key"].lower() or "cash" in flag["label"].lower() for flag in flags
    ), [f["key"] for f in flags]


def test_every_flag_carries_the_fields_the_frontend_renders():
    for flag in divergence_flags(HISTORY):
        assert set(flag) >= {"key", "label", "severity", "interpretation", "detail", "basis"}
        assert flag["severity"] in ("red", "yellow", "green")
        assert flag["interpretation"].strip()


def test_a_company_that_did_not_move_raises_no_flags():
    assert divergence_flags([PRIOR, {**PRIOR, "fiscalYear": 2024}]) == []


def test_divergence_flags_need_two_years():
    assert divergence_flags([LATEST]) == []
    assert divergence_flags([]) == []


# --- aggregation --------------------------------------------------------------------


def test_run_all_screens_collects_screens_and_flags():
    result = run_all_screens(HISTORY)
    assert {screen["key"] for screen in result["screens"]} == {
        "beneish_m", "altman_z", "piotroski_f", "accrual_ratio",
    }
    assert result["flags"]


def test_run_all_screens_omits_screens_it_cannot_compute():
    """A filer missing receivables loses Beneish but keeps everything else."""
    result = run_all_screens([PRIOR, _without(LATEST, "receivables")])
    keys = {screen["key"] for screen in result["screens"]}
    assert "beneish_m" not in keys
    assert {"altman_z", "piotroski_f", "accrual_ratio"} <= keys


def test_run_all_screens_on_empty_history_returns_empty_not_an_error():
    assert run_all_screens([]) == {"screens": [], "flags": []}


def test_every_screen_carries_the_fields_the_frontend_renders():
    for screen in run_all_screens(HISTORY)["screens"]:
        assert set(screen) >= {
            "key", "label", "value", "severity", "interpretation", "components", "basis",
        }
        assert screen["severity"] in ("red", "yellow", "green")
        assert screen["interpretation"].strip()
