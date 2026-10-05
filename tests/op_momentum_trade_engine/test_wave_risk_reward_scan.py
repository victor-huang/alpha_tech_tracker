from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import (
    evaluate_setup,
    half_stats,
    recommend,
    session_split,
    split_halves,
)

MARKET_TZ = "America/New_York"
HALVES = (date(2025, 1, 2), date(2025, 6, 30), date(2025, 7, 1), date(2025, 12, 31))


def _trade(day, pnl):
    return {"entry_time": pd.Timestamp(day, tz=MARKET_TZ), "net_pct": pnl}


def _row(first_total, second_total, first_trades=10, second_trades=10):
    return {"exit": "target",
            "first": {"trades": first_trades, "total": first_total, "win": 0.5},
            "second": {"trades": second_trades, "total": second_total, "win": 0.5}}


class TestSplitHalves:
    def test_splits_sessions_by_count(self):
        sessions = [date(2025, 1, d) for d in range(2, 8)]

        assert split_halves(sessions) == (date(2025, 1, 2), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 7))


class TestHalfStats:
    def test_counts_only_trades_inside_the_half(self):
        trades = [_trade("2025-03-03 10:00", 1.0), _trade("2025-03-04 10:00", -0.5), _trade("2025-08-01 10:00", 2.0)]

        stats = half_stats(trades, date(2025, 1, 2), date(2025, 6, 30))

        assert (stats["trades"], stats["total"], stats["win"]) == (2, pytest.approx(0.5), 0.5)


class TestEvaluateSetup:
    def test_exit_is_chosen_on_the_first_half(self):
        trades_by_exit = {
            "target": [_trade("2025-03-03 10:00", 2.0), _trade("2025-09-01 10:00", -1.0)],
            "target-trail": [_trade("2025-03-03 10:00", 1.0), _trade("2025-09-01 10:00", 5.0)],
            "giveback": [_trade("2025-03-03 10:00", 0.5)],
            "eod": [_trade("2025-03-03 10:00", -1.0)],
        }

        row = evaluate_setup(trades_by_exit, HALVES, overnight=False)

        assert row["exit"] == "target"
        assert row["second"]["total"] == pytest.approx(-1.0)

    def test_overnight_setup_uses_its_single_exit(self):
        trades_by_exit = {mode: [_trade("2025-03-03 15:55", 1.0)] for mode in ("target", "target-trail", "giveback", "eod")}

        assert evaluate_setup(trades_by_exit, HALVES, overnight=True)["exit"] == "next open"


class TestRecommend:
    def test_keeps_setups_positive_in_both_halves(self):
        rows = {"drive long": _row(5.0, 3.0), "bounce short": _row(4.0, -1.0)}

        assert recommend(rows, min_trades=5) == ["drive long"]

    def test_requires_enough_trades_in_each_half(self):
        rows = {"drive long": _row(5.0, 3.0, second_trades=3)}

        assert recommend(rows, min_trades=5) == []

    def test_keeps_one_setup_per_family_by_first_half(self):
        rows = {"pullback long": _row(2.0, 6.0), "pullback long C1": _row(3.0, 1.0),
                "overnight always": _row(10.0, 20.0), "overnight ma200": _row(12.0, 15.0)}

        assert recommend(rows, min_trades=5) == ["pullback long C1", "overnight ma200"]


class TestSessionSplit:
    def test_splits_return_into_overnight_and_in_session(self):
        index = pd.DatetimeIndex([pd.Timestamp(t, tz=MARKET_TZ) for t in
                                  ("2025-01-02 09:30", "2025-01-02 15:55", "2025-01-03 09:30", "2025-01-03 15:55")])
        bars = pd.DataFrame({"open": [100.0, 101.0, 105.0, 106.0], "close": [101.0, 102.0, 106.0, 110.0]}, index=index)

        overnight, session = session_split(bars, date(2025, 1, 3), date(2025, 1, 3))

        assert overnight == pytest.approx(105.0 / 102.0 * 100 - 100)
        assert session == pytest.approx(110.0 / 105.0 * 100 - 100)
