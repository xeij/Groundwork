import pytest

from app.services.xbrl_metrics import (
    FISCAL_YEAR_FIELDS,
    XbrlMetricsError,
    build_financial_history,
    derived_ratios,
    latest_fiscal_year,
)


def _duration(val, start, end, **overrides):
    fact = {
        "start": start,
        "end": end,
        "val": val,
        "accn": "0000000000-24-000001",
        "fy": int(end[:4]),
        "fp": "FY",
        "form": "10-K",
        "filed": f"{int(end[:4]) + 1}-02-01",
    }
    fact.update(overrides)
    return fact


def _instant(val, end, **overrides):
    fact = {
        "end": end,
        "val": val,
        "accn": "0000000000-24-000001",
        "fy": int(end[:4]),
        "fp": "FY",
        "form": "10-K",
        "filed": f"{int(end[:4]) + 1}-02-01",
    }
    fact.update(overrides)
    return fact


def _company_facts(concepts):
    """concepts: {concept: {unit: [fact, ...]}} -> a minimal companyfacts payload."""
    return {
        "cik": 1234,
        "entityName": "Test Filer Inc.",
        "facts": {"us-gaap": {name: {"units": units} for name, units in concepts.items()}},
    }


def _annual_usd(concept_values, start, end, **overrides):
    return {
        concept: {"USD": [_duration(value, start, end, **overrides)]}
        for concept, value in concept_values.items()
    }


FY2024 = ("2024-01-01", "2024-12-31")
FY2023 = ("2023-01-01", "2023-12-31")


class TestConceptFallbackChains:
    def test_prefers_the_first_concept_in_the_chain(self):
        facts = _company_facts(
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"USD": [_duration(500, *FY2024)]},
                "Revenues": {"USD": [_duration(999, *FY2024)]},
                "SalesRevenueNet": {"USD": [_duration(111, *FY2024)]},
            }
        )
        assert build_financial_history(facts)[0]["revenue"] == 500

    def test_falls_through_to_a_legacy_tag_when_the_modern_one_is_absent(self):
        facts = _company_facts({"SalesRevenueNet": {"USD": [_duration(111, *FY2024)]}})
        assert build_financial_history(facts)[0]["revenue"] == 111

    def test_cost_of_revenue_chain_accepts_cost_of_goods_and_services_sold(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "CostOfGoodsAndServicesSold": {"USD": [_duration(600, *FY2024)]},
            }
        )
        assert build_financial_history(facts)[0]["costOfRevenue"] == 600

    def test_receivables_chain_falls_back_to_the_non_current_tag(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "AccountsReceivableNet": {"USD": [_instant(75, "2024-12-31")]},
            }
        )
        assert build_financial_history(facts)[0]["receivables"] == 75

    def test_equity_chain_falls_back_to_the_including_noncontrolling_tag(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": {
                    "USD": [_instant(300, "2024-12-31")]
                },
            }
        )
        assert build_financial_history(facts)[0]["stockholdersEquity"] == 300

    def test_shares_are_read_from_the_shares_unit_key(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "WeightedAverageNumberOfDilutedSharesOutstanding": {
                    "shares": [_duration(1_500_000, *FY2024)]
                },
            }
        )
        assert build_financial_history(facts)[0]["dilutedShares"] == 1_500_000

    def test_usd_unit_wins_over_a_non_monetary_duplicate(self):
        facts = _company_facts(
            {
                "Revenues": {
                    "pure": [_duration(1, *FY2024)],
                    "USD": [_duration(1000, *FY2024)],
                }
            }
        )
        assert build_financial_history(facts)[0]["revenue"] == 1000


class TestAnnualPeriodFiltering:
    def test_quarterly_facts_never_populate_an_annual_row(self):
        facts = _company_facts(
            {
                "Revenues": {
                    "USD": [
                        _duration(1000, *FY2024),
                        _duration(240, "2024-01-01", "2024-03-31", fp="Q1", form="10-Q"),
                        _duration(260, "2024-04-01", "2024-06-30", fp="Q2", form="10-Q"),
                    ]
                }
            }
        )
        history = build_financial_history(facts)
        assert len(history) == 1
        assert history[0]["revenue"] == 1000

    def test_year_to_date_nine_month_facts_are_excluded(self):
        facts = _company_facts(
            {
                "Revenues": {
                    "USD": [
                        _duration(1000, *FY2024),
                        _duration(700, "2024-01-01", "2024-09-30", fp="Q3", form="10-Q"),
                    ]
                }
            }
        )
        history = build_financial_history(facts)
        assert [row["periodEnd"] for row in history] == ["2024-12-31"]

    def test_a_fifty_three_week_retail_year_still_counts_as_annual(self):
        facts = _company_facts({"Revenues": {"USD": [_duration(1000, "2024-01-29", "2025-02-01")]}})
        history = build_financial_history(facts)
        assert len(history) == 1
        assert history[0]["revenue"] == 1000

    def test_since_inception_cumulative_periods_are_excluded(self):
        facts = _company_facts(
            {
                "Revenues": {
                    "USD": [
                        _duration(1000, *FY2024),
                        _duration(4000, "2019-01-01", "2024-12-31"),
                    ]
                }
            }
        )
        assert build_financial_history(facts)[0]["revenue"] == 1000

    def test_only_annual_forms_get_a_vote_on_where_a_fiscal_year_falls(self):
        # A 10-Q carrying a trailing-twelve-month period must not invent a fiscal year.
        facts = _company_facts(
            {
                "Revenues": {
                    "USD": [
                        _duration(1000, *FY2024),
                        _duration(1050, "2024-04-01", "2025-03-31", fp="Q1", form="10-Q"),
                    ]
                }
            }
        )
        assert [row["periodEnd"] for row in build_financial_history(facts)] == ["2024-12-31"]


class TestRestatementPreference:
    def test_the_most_recently_filed_accession_wins(self):
        facts = _company_facts(
            {
                "Revenues": {
                    "USD": [
                        _duration(1000, *FY2023, accn="0000000000-24-000001", filed="2024-02-01"),
                        _duration(950, *FY2023, accn="0000000000-26-000009", filed="2026-02-01", fy=2025),
                        _duration(980, *FY2023, accn="0000000000-25-000005", filed="2025-02-01", fy=2024),
                    ]
                }
            }
        )
        assert build_financial_history(facts)[0]["revenue"] == 950

    def test_restatement_preference_applies_to_balance_sheet_facts_too(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2023)]},
                "Assets": {
                    "USD": [
                        _instant(500, "2023-12-31", filed="2024-02-01"),
                        _instant(480, "2023-12-31", filed="2025-02-01", accn="0000000000-25-000005"),
                    ]
                },
            }
        )
        assert build_financial_history(facts)[0]["totalAssets"] == 480

    def test_original_filing_sets_the_fiscal_year_label_not_the_restating_one(self):
        # `fy` is the fiscal focus of the *filing*, so a FY2023 comparative repeated in the
        # FY2025 10-K carries fy=2025. The smallest plausible candidate is the right label.
        facts = _company_facts(
            {
                "Revenues": {
                    "USD": [
                        _duration(1000, *FY2023, fy=2023, filed="2024-02-01"),
                        _duration(1000, *FY2023, fy=2024, filed="2025-02-01"),
                        _duration(1000, *FY2023, fy=2025, filed="2026-02-01"),
                    ]
                }
            }
        )
        assert build_financial_history(facts)[0]["fiscalYear"] == 2023

    def test_fiscal_year_falls_back_to_the_calendar_year_when_fy_is_implausible(self):
        facts = _company_facts({"Revenues": {"USD": [_duration(1000, *FY2023, fy=2019)]}})
        assert build_financial_history(facts)[0]["fiscalYear"] == 2023

    def test_january_year_end_keeps_the_filers_own_fiscal_label(self):
        facts = _company_facts(
            {"Revenues": {"USD": [_duration(1000, "2023-01-29", "2024-01-28", fy=2023)]}}
        )
        row = build_financial_history(facts)[0]
        assert row["fiscalYear"] == 2023
        assert row["periodEnd"] == "2024-01-28"


class TestMissingData:
    def test_untagged_fields_are_none_not_zero(self):
        facts = _company_facts({"Revenues": {"USD": [_duration(1000, *FY2024)]}})
        row = build_financial_history(facts)[0]
        assert row["revenue"] == 1000
        for field in FISCAL_YEAR_FIELDS:
            if field != "revenue":
                assert row[field] is None, f"{field} should be None when never tagged"

    def test_a_genuinely_zero_tagged_value_is_preserved(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "ResearchAndDevelopmentExpense": {"USD": [_duration(0, *FY2024)]},
            }
        )
        assert build_financial_history(facts)[0]["rndExpense"] == 0

    def test_every_row_carries_the_full_field_set(self):
        facts = _company_facts({"Revenues": {"USD": [_duration(1000, *FY2024)]}})
        row = build_financial_history(facts)[0]
        assert set(row) == {"fiscalYear", "periodEnd", *FISCAL_YEAR_FIELDS}


class TestDerivableGaps:
    def test_gross_profit_is_backed_out_of_revenue_less_cost(self):
        facts = _company_facts(_annual_usd({"Revenues": 1000, "CostOfRevenue": 600}, *FY2024))
        assert build_financial_history(facts)[0]["grossProfit"] == 400

    def test_tagged_gross_profit_is_not_overwritten_by_the_derivation(self):
        facts = _company_facts(
            _annual_usd({"Revenues": 1000, "CostOfRevenue": 600, "GrossProfit": 390}, *FY2024)
        )
        assert build_financial_history(facts)[0]["grossProfit"] == 390

    def test_cost_of_revenue_is_backed_out_of_revenue_less_gross_profit(self):
        facts = _company_facts(_annual_usd({"Revenues": 1000, "GrossProfit": 400}, *FY2024))
        assert build_financial_history(facts)[0]["costOfRevenue"] == 600

    def test_gross_profit_stays_none_when_neither_input_exists(self):
        facts = _company_facts({"Revenues": {"USD": [_duration(1000, *FY2024)]}})
        assert build_financial_history(facts)[0]["grossProfit"] is None

    def test_total_liabilities_is_backed_out_of_the_balance_sheet_identity(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "Assets": {"USD": [_instant(900, "2024-12-31")]},
                "StockholdersEquity": {"USD": [_instant(350, "2024-12-31")]},
            }
        )
        assert build_financial_history(facts)[0]["totalLiabilities"] == 550

    def test_tagged_total_liabilities_wins_over_the_identity(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "Assets": {"USD": [_instant(900, "2024-12-31")]},
                "Liabilities": {"USD": [_instant(540, "2024-12-31")]},
                "StockholdersEquity": {"USD": [_instant(350, "2024-12-31")]},
            }
        )
        assert build_financial_history(facts)[0]["totalLiabilities"] == 540


class TestSummedFields:
    def test_total_debt_sums_short_and_long_term_borrowings(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "CommercialPaper": {"USD": [_instant(20, "2024-12-31")]},
                "LongTermDebtCurrent": {"USD": [_instant(30, "2024-12-31")]},
                "LongTermDebtNoncurrent": {"USD": [_instant(200, "2024-12-31")]},
            }
        )
        assert build_financial_history(facts)[0]["totalDebt"] == 250

    def test_debt_current_short_circuits_the_narrower_current_tags(self):
        # DebtCurrent is already the whole current-debt line; adding LongTermDebtCurrent
        # on top of it would double count the current portion of term debt.
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "DebtCurrent": {"USD": [_instant(50, "2024-12-31")]},
                "LongTermDebtCurrent": {"USD": [_instant(30, "2024-12-31")]},
                "CommercialPaper": {"USD": [_instant(20, "2024-12-31")]},
                "LongTermDebtNoncurrent": {"USD": [_instant(200, "2024-12-31")]},
            }
        )
        assert build_financial_history(facts)[0]["totalDebt"] == 250

    def test_total_debt_survives_a_long_term_only_capital_structure(self):
        facts = _company_facts(
            {
                "Revenues": {"USD": [_duration(1000, *FY2024)]},
                "LongTermDebtNoncurrent": {"USD": [_instant(200, "2024-12-31")]},
            }
        )
        assert build_financial_history(facts)[0]["totalDebt"] == 200

    def test_total_debt_is_none_for_a_debt_free_filer(self):
        facts = _company_facts({"Revenues": {"USD": [_duration(1000, *FY2024)]}})
        assert build_financial_history(facts)[0]["totalDebt"] is None

    def test_sga_sums_selling_and_administrative_when_the_combined_tag_is_absent(self):
        facts = _company_facts(
            _annual_usd(
                {
                    "Revenues": 1000,
                    "SellingAndMarketingExpense": 220,
                    "GeneralAndAdministrativeExpense": 80,
                },
                *FY2024,
            )
        )
        assert build_financial_history(facts)[0]["sgaExpense"] == 300

    def test_combined_sga_tag_short_circuits_the_two_halves(self):
        facts = _company_facts(
            _annual_usd(
                {
                    "Revenues": 1000,
                    "SellingGeneralAndAdministrativeExpense": 290,
                    "SellingAndMarketingExpense": 220,
                    "GeneralAndAdministrativeExpense": 80,
                },
                *FY2024,
            )
        )
        assert build_financial_history(facts)[0]["sgaExpense"] == 290


class TestHistoryShape:
    def _multi_year_facts(self, count=8):
        facts = []
        for offset in range(count):
            year = 2017 + offset
            facts.append(_duration(1000 + offset, f"{year}-01-01", f"{year}-12-31", fy=year))
        return _company_facts({"Revenues": {"USD": facts}})

    def test_history_is_sorted_oldest_first(self):
        history = build_financial_history(self._multi_year_facts(), max_years=8)
        assert [row["fiscalYear"] for row in history] == list(range(2017, 2025))

    def test_max_years_keeps_the_most_recent_years(self):
        history = build_financial_history(self._multi_year_facts(), max_years=3)
        assert [row["fiscalYear"] for row in history] == [2022, 2023, 2024]

    def test_default_max_years_is_six(self):
        assert len(build_financial_history(self._multi_year_facts())) == 6

    def test_history_is_empty_when_no_durational_annual_facts_exist(self):
        facts = _company_facts({"Assets": {"USD": [_instant(900, "2024-12-31")]}})
        assert build_financial_history(facts) == []

    def test_rejects_a_payload_without_us_gaap_facts(self):
        with pytest.raises(XbrlMetricsError, match="no us-gaap"):
            build_financial_history({"facts": {"dei": {}}})

    def test_rejects_a_non_dict_payload(self):
        with pytest.raises(XbrlMetricsError, match="companyfacts JSON"):
            build_financial_history([])

    def test_rejects_a_nonsensical_max_years(self):
        with pytest.raises(XbrlMetricsError, match="max_years"):
            build_financial_history(self._multi_year_facts(), max_years=0)


class TestLatestFiscalYear:
    def test_returns_the_last_row(self):
        history = [{"fiscalYear": 2023}, {"fiscalYear": 2024}]
        assert latest_fiscal_year(history)["fiscalYear"] == 2024

    def test_returns_none_for_an_empty_history(self):
        assert latest_fiscal_year([]) is None


def _year(**overrides):
    row = {field: None for field in FISCAL_YEAR_FIELDS}
    row.update({"fiscalYear": 2024, "periodEnd": "2024-12-31"})
    row.update(overrides)
    return row


class TestDerivedRatios:
    def test_margins_are_computed_from_revenue(self):
        # 400/1000 = 40%, 150/1000 = 15%, 100/1000 = 10%
        history = [_year(revenue=1000, grossProfit=400, operatingIncome=150, netIncome=100)]
        ratios = derived_ratios(history)
        assert ratios["grossMargin"]["value"] == 40.0
        assert ratios["operatingMargin"]["value"] == 15.0
        assert ratios["netMargin"]["value"] == 10.0
        assert ratios["grossMargin"]["unit"] == "percent"

    def test_return_on_assets_uses_average_assets_when_a_prior_year_exists(self):
        # 150 / ((1000 + 1400)/2) = 150/1200 = 12.5%
        history = [
            _year(fiscalYear=2023, netIncome=100, totalAssets=1000),
            _year(fiscalYear=2024, netIncome=150, totalAssets=1400),
        ]
        assert derived_ratios(history)["returnOnAssets"]["value"] == 12.5

    def test_return_on_assets_uses_ending_assets_for_a_single_year(self):
        history = [_year(netIncome=150, totalAssets=1500)]
        assert derived_ratios(history)["returnOnAssets"]["value"] == 10.0

    def test_days_sales_outstanding_matches_the_hand_computation(self):
        # 200/1200 * 365 = 60.833... -> 60.83 days
        history = [_year(revenue=1200, receivables=200)]
        entry = derived_ratios(history)["daysSalesOutstanding"]
        assert entry["value"] == 60.83
        assert entry["unit"] == "days"
        assert entry["label"] == "Days Sales Outstanding"

    def test_cash_conversion_cycle_is_dso_plus_dio_minus_dpo(self):
        # DSO 200/1200*365 = 60.83; DIO 150/900*365 = 60.83; DPO 300/900*365 = 121.67
        # 60.83 + 60.83 - 121.67 = 0.0
        history = [_year(revenue=1200, receivables=200, costOfRevenue=900, inventory=150, accountsPayable=300)]
        assert derived_ratios(history)["cashConversionCycle"]["value"] == 0.0

    def test_quick_ratio_strips_inventory_from_current_assets(self):
        # (500 - 120)/200 = 1.9
        history = [_year(currentAssets=500, inventory=120, currentLiabilities=200)]
        assert derived_ratios(history)["quickRatio"]["value"] == 1.9

    def test_quick_ratio_equals_current_ratio_when_there_is_no_inventory(self):
        history = [_year(currentAssets=500, currentLiabilities=200)]
        ratios = derived_ratios(history)
        assert ratios["quickRatio"]["value"] == ratios["currentRatio"]["value"] == 2.5

    def test_free_cash_flow_and_margin(self):
        # 300 - 120 = 180; 180/1000 = 18%
        history = [_year(revenue=1000, operatingCashFlow=300, capex=120)]
        ratios = derived_ratios(history)
        assert ratios["freeCashFlow"]["value"] == 180.0
        assert ratios["freeCashFlow"]["unit"] == "usd"
        assert ratios["fcfMargin"]["value"] == 18.0

    def test_net_debt_to_ebitda(self):
        # EBITDA 150 + 50 = 200; net debt 600 - 200 = 400; 400/200 = 2.0x
        history = [_year(operatingIncome=150, depreciationAmortization=50, totalDebt=600, cash=200)]
        entry = derived_ratios(history)["netDebtToEbitda"]
        assert entry["value"] == 2.0
        assert entry["unit"] == "x"

    def test_net_debt_to_ebitda_is_omitted_when_ebitda_is_negative(self):
        history = [_year(operatingIncome=-150, depreciationAmortization=50, totalDebt=600, cash=200)]
        assert "netDebtToEbitda" not in derived_ratios(history)

    def test_interest_coverage(self):
        # 150/30 = 5.0x
        history = [_year(operatingIncome=150, interestExpense=30)]
        assert derived_ratios(history)["interestCoverage"]["value"] == 5.0

    def test_growth_entries_require_a_prior_year(self):
        assert "revenueGrowth" not in derived_ratios([_year(revenue=1000)])

    def test_revenue_growth_and_share_change(self):
        # 1200/1000 - 1 = 20%; 950/1000 - 1 = -5%
        history = [
            _year(fiscalYear=2023, revenue=1000, dilutedShares=1000),
            _year(fiscalYear=2024, revenue=1200, dilutedShares=950),
        ]
        ratios = derived_ratios(history)
        assert ratios["revenueGrowth"]["value"] == 20.0
        assert ratios["dilutedShareChange"]["value"] == -5.0

    def test_prior_value_and_change_are_attached_when_the_prior_year_computes(self):
        # 45% this year against 40% last year -> +5.0 points
        history = [
            _year(fiscalYear=2023, revenue=1000, grossProfit=400),
            _year(fiscalYear=2024, revenue=1000, grossProfit=450),
        ]
        entry = derived_ratios(history)["grossMargin"]
        assert entry["value"] == 45.0
        assert entry["priorValue"] == 40.0
        assert entry["change"] == 5.0

    def test_prior_value_is_omitted_rather_than_nulled_when_last_year_lacks_inputs(self):
        history = [_year(fiscalYear=2023), _year(fiscalYear=2024, revenue=1000, grossProfit=450)]
        entry = derived_ratios(history)["grossMargin"]
        assert entry["value"] == 45.0
        assert "priorValue" not in entry
        assert "change" not in entry

    def test_missing_inputs_omit_the_entry_entirely(self):
        ratios = derived_ratios([_year(revenue=1000)])
        assert "currentRatio" not in ratios
        assert "daysSalesOutstanding" not in ratios
        assert all(entry["value"] is not None for entry in ratios.values())

    def test_ratios_on_a_negative_denominator_are_omitted_rather_than_sign_flipped(self):
        # Negative equity would turn a leverage ratio into a reassuring negative number.
        history = [_year(netIncome=100, stockholdersEquity=-500, totalDebt=600)]
        ratios = derived_ratios(history)
        assert "returnOnEquity" not in ratios
        assert "debtToEquity" not in ratios

    def test_empty_history_yields_no_ratios(self):
        assert derived_ratios([]) == {}

    def test_every_unit_is_from_the_agreed_vocabulary(self):
        history = [
            _year(
                fiscalYear=2023,
                revenue=1000,
                costOfRevenue=600,
                grossProfit=400,
                operatingIncome=150,
                netIncome=100,
                totalAssets=2000,
                currentAssets=800,
                currentLiabilities=400,
                stockholdersEquity=900,
                cash=200,
                receivables=150,
                inventory=100,
                accountsPayable=120,
                totalDebt=500,
                operatingCashFlow=250,
                capex=100,
                depreciationAmortization=50,
                shareBasedCompensation=40,
                interestExpense=25,
                dilutedShares=1000,
            ),
            _year(
                fiscalYear=2024,
                revenue=1200,
                costOfRevenue=700,
                grossProfit=500,
                operatingIncome=180,
                netIncome=130,
                totalAssets=2200,
                currentAssets=900,
                currentLiabilities=450,
                stockholdersEquity=1000,
                cash=250,
                receivables=200,
                inventory=130,
                accountsPayable=140,
                totalDebt=520,
                operatingCashFlow=300,
                capex=120,
                depreciationAmortization=60,
                interestExpense=30,
                shareBasedCompensation=50,
                dilutedShares=980,
            ),
        ]
        ratios = derived_ratios(history)
        assert len(ratios) == 20
        assert {entry["unit"] for entry in ratios.values()} <= {"percent", "days", "ratio", "usd", "x"}
        assert all("label" in entry for entry in ratios.values())
