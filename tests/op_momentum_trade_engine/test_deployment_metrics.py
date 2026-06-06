"""
Tests for deployment metric calculations in _capital_stats_from_trades:
  - total_deployed: sum of slot_capital across all non-skipped rows
  - capital_utilization: avg(daily_deployed / initial_capital)
  - pnl_per_dollar_deployed: total_cap_pnl / total_deployed
  - deployment_weighted_sharpe: Sharpe on daily RODC, weighted by deployment size
"""
import math
from datetime import date

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _capital_stats_from_trades,
)


def _row(d, cap_pnl, slot_capital, skipped=False):
    return {"date": d, "cap_pnl": cap_pnl, "slot_capital": slot_capital, "skipped": skipped}


INITIAL = 10000.0

JAN2 = date(2026, 1, 2)
JAN3 = date(2026, 1, 3)
JAN6 = date(2026, 1, 6)
JAN7 = date(2026, 1, 7)


class TestTotalDeployed:
    def test_sums_slot_capital_across_all_active_rows(self):
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN2, cap_pnl=-50.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=200.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["total_deployed"] == 15000.0

    def test_excludes_skipped_rows(self):
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=0.0, slot_capital=5000.0, skipped=True),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["total_deployed"] == 5000.0

    def test_rows_missing_slot_capital_contribute_zero(self):
        rows = [
            {"date": JAN2, "cap_pnl": 100.0, "skipped": False},
            _row(JAN3, cap_pnl=200.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["total_deployed"] == 5000.0

    def test_multiple_rows_same_day_are_all_counted(self):
        rows = [
            _row(JAN2, cap_pnl=50.0, slot_capital=2500.0),
            _row(JAN2, cap_pnl=80.0, slot_capital=2500.0),
            _row(JAN2, cap_pnl=-30.0, slot_capital=2500.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["total_deployed"] == 7500.0

    def test_zero_deployed_when_all_rows_skipped(self):
        rows = [_row(JAN2, cap_pnl=0.0, slot_capital=5000.0, skipped=True)]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["total_deployed"] == 0.0


class TestPnlPerDollarDeployed:
    def test_divides_total_pnl_by_total_deployed(self):
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=200.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["pnl_per_dollar_deployed"] - 300.0 / 10000.0) < 1e-9

    def test_negative_pnl_gives_negative_ratio(self):
        rows = [_row(JAN2, cap_pnl=-200.0, slot_capital=5000.0)]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["pnl_per_dollar_deployed"] < 0

    def test_zero_deployed_returns_zero_ratio(self):
        rows = [_row(JAN2, cap_pnl=0.0, slot_capital=5000.0, skipped=True)]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["pnl_per_dollar_deployed"] == 0.0


class TestCapitalUtilization:
    def test_averages_daily_deployed_fraction_across_trading_days(self):
        # Day 1: $5000 / $10000 = 50%; Day 2: $10000 / $10000 = 100% → avg 75%
        rows = [
            _row(JAN2, cap_pnl=50.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=100.0, slot_capital=10000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["capital_utilization"] - 0.75) < 1e-9

    def test_full_deployment_every_day_gives_one_hundred_percent(self):
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=10000.0),
            _row(JAN3, cap_pnl=-50.0, slot_capital=10000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["capital_utilization"] - 1.0) < 1e-9

    def test_multiple_slots_same_day_accumulated_before_averaging(self):
        # Day 1: two $3000 slots → $6000 deployed; Day 2: one $4000 slot
        # utilization = avg(6000/10000, 4000/10000) = avg(0.6, 0.4) = 0.5
        rows = [
            _row(JAN2, cap_pnl=50.0, slot_capital=3000.0),
            _row(JAN2, cap_pnl=60.0, slot_capital=3000.0),
            _row(JAN3, cap_pnl=40.0, slot_capital=4000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["capital_utilization"] - 0.5) < 1e-9

    def test_skipped_rows_excluded_from_daily_deployed_sum(self):
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN2, cap_pnl=0.0, slot_capital=5000.0, skipped=True),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        # Only the active $5000 counts → 5000/10000 = 50%
        assert abs(stats["capital_utilization"] - 0.5) < 1e-9


class TestMeanDailyRodc:
    def test_averages_per_day_pnl_over_deployed_capital(self):
        # Day 1: $100 / $5000 = 2%; Day 2: $50 / $2500 = 2% → mean = 2%
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=50.0, slot_capital=2500.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["mean_daily_rodc"] - 0.02) < 1e-9

    def test_differs_from_pnl_per_dollar_when_deployment_varies(self):
        # Day 1: $10 on $9000 → RODC = 0.11%
        # Day 2: $500 on $1000 → RODC = 50%
        # mean daily RODC = 25.06%; P&L per $ deployed = $510/$10000 = 5.1%
        rows = [
            _row(JAN2, cap_pnl=10.0, slot_capital=9000.0),
            _row(JAN3, cap_pnl=500.0, slot_capital=1000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["mean_daily_rodc"] != stats["pnl_per_dollar_deployed"]
        # mean daily RODC gives equal weight to both days
        expected_mean_rodc = (10.0 / 9000.0 + 500.0 / 1000.0) / 2
        assert abs(stats["mean_daily_rodc"] - expected_mean_rodc) < 1e-9

    def test_returns_none_when_no_deployment(self):
        rows = [_row(JAN2, cap_pnl=0.0, slot_capital=5000.0, skipped=True)]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["mean_daily_rodc"] is None

    def test_multi_row_same_day_sums_before_averaging(self):
        # Day 1: two rows → pnl=150, deployed=10000 → RODC=1.5%
        # Day 2: one row → pnl=50, deployed=5000 → RODC=1.0%
        # mean = 1.25%
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN2, cap_pnl=50.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=50.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["mean_daily_rodc"] - 0.0125) < 1e-9

    def test_negative_rodc_when_losses_exceed_gains(self):
        rows = [
            _row(JAN2, cap_pnl=-200.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=-100.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["mean_daily_rodc"] < 0


class TestDeploymentWeightedSharpe:
    def test_returns_none_for_single_trading_day(self):
        rows = [_row(JAN2, cap_pnl=100.0, slot_capital=5000.0)]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["deployment_weighted_sharpe"] is None

    def test_returns_none_for_zero_variance_rodcs(self):
        # All days same RODC → std = 0 → Sharpe undefined
        rows = [
            _row(JAN2, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN6, cap_pnl=100.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["deployment_weighted_sharpe"] is None

    def test_positive_sharpe_when_returns_consistently_positive(self):
        rows = [
            _row(JAN2, cap_pnl=200.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=150.0, slot_capital=5000.0),
            _row(JAN6, cap_pnl=100.0, slot_capital=5000.0),
            _row(JAN7, cap_pnl=50.0, slot_capital=5000.0),
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert stats["deployment_weighted_sharpe"] is not None
        assert stats["deployment_weighted_sharpe"] > 0

    def test_equal_weights_matches_standard_sharpe_on_rodc(self):
        # Equal deployment every day → weights cancel → DW-Sharpe == standard Sharpe on RODC
        slot_cap = 5000.0
        pnls = [100.0, 200.0, -50.0, 150.0]
        rodcs = [p / slot_cap for p in pnls]
        mean_r = sum(rodcs) / len(rodcs)
        # Use population variance (consistent with DW-Sharpe formula)
        w = [1.0] * len(rodcs)
        w_sum = sum(w)
        w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
        w_var = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
        expected_sharpe = w_mean / math.sqrt(w_var) * math.sqrt(252)

        rows = [
            _row(date(2026, 1, 2 + i), cap_pnl=p, slot_capital=slot_cap)
            for i, p in enumerate(pnls)
        ]
        stats = _capital_stats_from_trades(rows, INITIAL)
        assert abs(stats["deployment_weighted_sharpe"] - expected_sharpe) < 1e-6

    def test_high_deployment_days_weighted_more_heavily(self):
        # Day 1: small profit on large deployment → drags down weighted return
        # Day 2: large profit on small deployment → under-weighted
        # DW-Sharpe should be lower than naive equal-weight Sharpe
        rows_equal = [
            _row(JAN2, cap_pnl=10.0, slot_capital=5000.0),
            _row(JAN3, cap_pnl=500.0, slot_capital=5000.0),
        ]
        rows_weighted = [
            _row(JAN2, cap_pnl=10.0, slot_capital=9000.0),
            _row(JAN3, cap_pnl=500.0, slot_capital=1000.0),
        ]
        stats_equal = _capital_stats_from_trades(rows_equal, INITIAL)
        stats_weighted = _capital_stats_from_trades(rows_weighted, INITIAL)
        # The large-deployment day has tiny RODC (10/9000) while small-deployment
        # day has great RODC (500/1000) — weighting by deployment hurts the Sharpe
        assert stats_weighted["deployment_weighted_sharpe"] < stats_equal["deployment_weighted_sharpe"]
