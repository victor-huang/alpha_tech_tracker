from datetime import date

import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.sec_fundamentals import (
    CONCEPTS,
    FundamentalsCache,
    add_fundamental_factors,
    add_quality_factors,
    concept_facts,
    growth_table,
    quality_table,
    quarterly_values,
    sec_user_agent,
    share_change_table,
    ytd_quarterly_values,
)


def _fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def _facts(concepts, namespace="us-gaap", unit="USD"):
    return {"facts": {namespace: {name: {"units": {unit: rows}} for name, rows in concepts.items()}}}


def _dated(rows):
    facts = pd.DataFrame(rows)
    for col in ("start", "end", "filed"):
        facts[col] = pd.to_datetime(facts[col])
    return facts


def _instants(symbol, metric, values, first_end="2023-03-31"):
    ends = pd.date_range(first_end, periods=len(values), freq="Q")
    return pd.DataFrame({"symbol": symbol, "metric": metric, "end": ends, "val": values,
                         "known": ends + pd.Timedelta(days=30)})


def _quarters(symbol, revenue, income, first_end="2023-03-31"):
    """Quarterly rows known 30 days after each quarter end."""
    ends = pd.date_range(first_end, periods=len(revenue), freq="Q")
    rows = []
    for end, r, ni in zip(ends, revenue, income):
        known = end + pd.Timedelta(days=30)
        rows += [{"symbol": symbol, "metric": "revenue", "end": end, "val": r, "known": known},
                 {"symbol": symbol, "metric": "net_income", "end": end, "val": ni, "known": known}]
    return pd.DataFrame(rows)


class TestConceptFacts:

    def test_preferred_concept_and_first_filed_value_win(self):
        facts = _facts({
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                _fact("2024-01-01", "2024-03-31", 100, "2024-05-01"),
                _fact("2024-01-01", "2024-03-31", 105, "2025-05-01"),
            ],
            "Revenues": [_fact("2024-01-01", "2024-03-31", 999, "2024-04-20")],
        })

        result = concept_facts(facts, "revenue")

        assert result["val"].tolist() == [100]

    def test_instant_concepts_come_from_their_namespace_with_start_equal_to_end(self):
        facts = _facts({"EntityCommonStockSharesOutstanding": [
            {"end": "2024-04-25", "val": 1000, "filed": "2024-05-01", "form": "10-Q"}]}, namespace="dei",
            unit="shares")

        result = concept_facts(facts, "shares")

        assert result["val"].tolist() == [1000]
        assert (result["start"] == result["end"]).all()

    def test_ignores_non_periodic_forms(self):
        facts = _facts({"Revenues": [_fact("2024-01-01", "2024-03-31", 100, "2024-05-01", form="8-K")]})

        assert concept_facts(facts, "revenue").empty


class TestQuarterlyValues:

    def test_q4_derived_from_annual_minus_three_quarters_known_at_10k_filing(self):
        facts = pd.DataFrame([
            _fact("2024-01-01", "2024-03-31", 10, "2024-05-01"),
            _fact("2024-04-01", "2024-06-30", 20, "2024-08-01"),
            _fact("2024-07-01", "2024-09-30", 30, "2024-11-01"),
            _fact("2024-01-01", "2024-12-31", 100, "2025-02-20", form="10-K"),
        ]).drop(columns="form")
        for col in ("start", "end", "filed"):
            facts[col] = pd.to_datetime(facts[col])

        result = quarterly_values(facts).set_index("end")

        assert result.loc[pd.Timestamp("2024-12-31"), "val"] == 40
        assert result.loc[pd.Timestamp("2024-12-31"), "known"] == pd.Timestamp("2025-02-20")
        assert len(result) == 4


class TestYtdQuarterlyValues:

    def test_quarters_are_differences_of_year_to_date_totals(self):
        facts = _dated([
            {"start": "2024-01-01", "end": "2024-03-31", "val": 10, "filed": "2024-05-01"},
            {"start": "2024-01-01", "end": "2024-06-30", "val": 25, "filed": "2024-08-01"},
            {"start": "2024-01-01", "end": "2024-09-30", "val": 45, "filed": "2024-11-01"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 70, "filed": "2025-02-20"},
        ])

        result = ytd_quarterly_values(facts)

        assert result["val"].tolist() == [10, 15, 20, 25]
        assert result["known"].iloc[-1] == pd.Timestamp("2025-02-20")


class TestShareChangeTable:

    def test_one_year_change_in_shares_outstanding(self):
        shares = _instants("A", "shares", [100, 100, 100, 100, 115])

        result = share_change_table(shares)

        assert result["share_change"].iloc[-1] == pytest.approx(0.15)

    def test_split_sized_change_is_left_unscored(self):
        shares = _instants("A", "shares", [100, 100, 100, 100, 1000])

        result = share_change_table(shares)

        assert np.isnan(result["share_change"].iloc[-1])


class TestQualityTable:

    def test_trailing_gross_profit_over_assets_and_operating_cash_flow(self):
        quarters = pd.concat([
            _instants("A", "gross_profit", [10, 20, 30, 40]),
            _instants("A", "operating_cash_flow", [-5, -5, -5, -5]),
            _instants("A", "assets", [1000, 1000, 1000, 500]),
            _instants("A", "cash", [100, 100, 100, 60]),
        ])

        last = quality_table(quarters).iloc[-1]

        assert last["gp_assets"] == pytest.approx(100 / 500)
        assert last["ocf_ttm"] == pytest.approx(-20)

    def test_gross_profit_falls_back_to_revenue_minus_cost(self):
        quarters = pd.concat([
            _instants("A", "revenue", [50] * 4),
            _instants("A", "cost_of_revenue", [30] * 4),
            _instants("A", "assets", [400] * 4),
        ])

        assert quality_table(quarters).iloc[-1]["gp_assets"] == pytest.approx(80 / 400)


class TestAddQualityFactors:

    def _panel(self, checkpoint="2024-03-01"):
        return pd.DataFrame({"checkpoint": [pd.Timestamp(checkpoint)], "symbol": ["A"], "tier": ["Small"]})

    def test_cash_burner_with_under_four_quarters_of_cash_has_low_runway(self):
        quarters = pd.concat([_instants("A", "operating_cash_flow", [-10] * 4), _instants("A", "cash", [30] * 4)])

        row = add_quality_factors(self._panel(), quarters).iloc[0]

        assert row["cash_burn"] == 1.0
        assert row["low_runway"] == 1.0

    def test_cash_generator_is_never_low_runway(self):
        quarters = _instants("A", "operating_cash_flow", [10] * 4)

        row = add_quality_factors(self._panel(), quarters).iloc[0]

        assert row["cash_burn"] == 0.0
        assert row["low_runway"] == 0.0

    def test_dilution_flag_uses_shares_known_before_the_checkpoint(self):
        quarters = _instants("A", "shares", [100, 100, 100, 100, 120])

        row = add_quality_factors(self._panel("2024-05-01"), quarters).iloc[0]

        assert row["dilution_10"] == 1.0
        assert row["buyback_2"] == 0.0


class TestGrowthTable:

    def test_year_over_year_growth_and_acceleration(self):
        quarters = _quarters("A", revenue=[100, 100, 100, 100, 110, 125], income=[10, 10, 10, 10, 11, 15])

        g = growth_table(quarters).set_index("end")

        last = g.iloc[-1]
        assert last["rev_yoy"] == pytest.approx(0.25)
        assert last["rev_yoy_prev"] == pytest.approx(0.10)
        assert last["rev_accel"] == pytest.approx(0.15)
        assert last["ni_yoy"] == pytest.approx(0.5)

    def test_earnings_growth_undefined_from_a_loss(self):
        quarters = _quarters("A", revenue=[100] * 5, income=[-5, 10, 10, 10, 2])

        g = growth_table(quarters)

        assert np.isnan(g["ni_yoy"].iloc[-1])


class TestAddFundamentalFactors:

    def _panel(self, checkpoint):
        return pd.DataFrame({"checkpoint": [pd.Timestamp(checkpoint)], "symbol": ["A"], "tier": ["Large"]})

    def test_uses_only_quarters_filed_before_the_checkpoint(self):
        quarters = _quarters("A", revenue=[100, 100, 100, 100, 110, 125], income=[10] * 6)
        last_known = quarters["known"].max()

        before = add_fundamental_factors(self._panel(last_known), quarters).iloc[0]
        after = add_fundamental_factors(self._panel(last_known + pd.Timedelta(days=1)), quarters).iloc[0]

        assert before["rev_yoy"] == pytest.approx(0.10)
        assert after["rev_yoy"] == pytest.approx(0.25)
        assert after["sales_growth_25"] == 1.0
        assert after["sales_accel"] == 1.0

    def test_stale_report_gives_no_score(self):
        quarters = _quarters("A", revenue=[100, 100, 100, 100, 130], income=[10] * 5)

        row = add_fundamental_factors(self._panel("2025-06-30"), quarters).iloc[0]

        assert np.isnan(row["sales_growth_25"])


class TestFundamentalsCache:

    def test_reuses_fresh_extract_covering_the_symbols(self, tmp_path, mocker):
        quarters = _quarters("A", [1] * 4, [1] * 4)
        pd.to_pickle({"fetched_on": date(2026, 11, 1), "covered": ["A", "B"], "metrics": sorted(CONCEPTS),
                      "quarters": quarters},
                     str(tmp_path / "sec_quarters.pkl"))
        download = mocker.Mock()

        result = FundamentalsCache(str(tmp_path), user_agent_for=mocker.Mock(), download=download).load(
            ["A"], date(2026, 11, 8))

        download.assert_not_called()
        assert len(result) == len(quarters)

    def test_rebuilds_when_symbols_are_missing_and_deletes_the_zip(self, tmp_path, mocker):
        def fake_download(path, agent):
            open(path, "w").close()

        extract = mocker.Mock(return_value=_quarters("C", [1] * 4, [1] * 4))
        cache = FundamentalsCache(str(tmp_path), user_agent_for=lambda: "Name name@example.com",
                                  download=fake_download, ticker_ciks=lambda agent: {"C": 3, "D": 4},
                                  extract=extract, keep_zip=False)

        cache.load(["C"], date(2026, 11, 8))

        extract.assert_called_once_with(str(tmp_path / "companyfacts.zip"), {"C": 3})
        assert not (tmp_path / "companyfacts.zip").exists()
        assert pd.read_pickle(str(tmp_path / "sec_quarters.pkl"))["covered"] == ["C"]


    def test_keeps_a_fresh_zip_and_reuses_it_without_downloading(self, tmp_path, mocker):
        (tmp_path / "companyfacts.zip").write_text("")
        download = mocker.Mock()
        cache = FundamentalsCache(str(tmp_path), user_agent_for=lambda: "Name name@example.com", download=download,
                                  ticker_ciks=lambda agent: {"A": 1},
                                  extract=mocker.Mock(return_value=_quarters("A", [1] * 4, [1] * 4)))

        cache.load(["A"], date.today())

        download.assert_not_called()
        assert (tmp_path / "companyfacts.zip").exists()

    def test_rebuilds_an_extract_made_before_new_metrics_were_added(self, tmp_path, mocker):
        pd.to_pickle({"fetched_on": date(2026, 11, 1), "covered": ["A"], "metrics": ["revenue"],
                      "quarters": _quarters("A", [1] * 4, [1] * 4)}, str(tmp_path / "sec_quarters.pkl"))
        extract = mocker.Mock(return_value=_quarters("A", [1] * 4, [1] * 4))
        cache = FundamentalsCache(str(tmp_path), user_agent_for=lambda: "Name name@example.com",
                                  download=lambda path, agent: open(path, "w").close(),
                                  ticker_ciks=lambda agent: {"A": 1}, extract=extract)

        cache.load(["A"], date(2026, 11, 8))

        extract.assert_called_once()


class TestSecUserAgent:

    def test_requires_a_contact_email(self, mocker):
        mocker.patch.dict("os.environ", {"SEC_USER_AGENT": "anonymous"})

        with pytest.raises(RuntimeError):
            sec_user_agent()
