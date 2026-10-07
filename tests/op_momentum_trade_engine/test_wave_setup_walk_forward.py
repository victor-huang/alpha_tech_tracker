from datetime import date, timedelta

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import REPORT_EXITS
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_walk_forward import (
    period_table,
    plan_blocks,
    select_setups,
    trade_block,
    walk_forward,
)

SESSIONS = [date(2026, 7, 1) + timedelta(days=i) for i in range(8)]


def _trades(rows):
    """rows of (ticker, setup, day index, net %)."""
    return pd.DataFrame([{"ticker": t, "setup": s, "exit": REPORT_EXITS[s], "day": SESSIONS[i], "net_pct": pnl}
                         for t, s, i, pnl in rows])


class TestPlanBlocks:
    def test_steps_hold_sessions_with_the_lookback_before_each(self):
        blocks = plan_blocks(SESSIONS, SESSIONS[2], lookback=2, hold=3)

        assert blocks == [(SESSIONS[0:2], SESSIONS[2:5]), (SESSIONS[3:5], SESSIONS[5:8])]

    def test_needs_enough_sessions_before_the_start(self):
        with pytest.raises(ValueError):
            plan_blocks(SESSIONS, SESSIONS[1], lookback=2, hold=3)


class TestSelectSetups:
    def test_ranks_only_the_lookback_days(self):
        trades = _trades([("AMD", "drive long", 0, 2.0), ("AMD", "bounce long", 0, 1.0),
                          ("AMD", "bounce long", 5, 50.0)])

        picked = select_setups(trades, "AMD", SESSIONS[0:2], top_n=3)

        assert picked == [("drive long", 2.0), ("bounce long", 1.0)]

    def test_leaves_out_losing_setups(self):
        trades = _trades([("AMD", "drive long", 0, -2.0)])

        assert select_setups(trades, "AMD", SESSIONS[0:2], top_n=3) == []


class TestTradeBlock:
    def test_sizes_each_trade_by_the_sleeve(self):
        trades = _trades([("AMD", "drive long", 2, 1.5), ("AMD", "bounce long", 2, 9.0)])

        chosen = trade_block(trades, "AMD", ["drive long"], SESSIONS[2:5], sleeve=2000.0)

        assert list(chosen["pnl"]) == [pytest.approx(30.0)]


class TestWalkForward:
    def test_each_block_trades_the_previous_lookbacks_winners(self):
        trades = _trades([
            ("AMD", "drive long", 0, 1.0), ("AMD", "bounce long", 1, -1.0),
            ("AMD", "drive long", 2, -3.0), ("AMD", "bounce long", 2, 4.0),
            ("AMD", "drive long", 4, 0.5), ("AMD", "bounce long", 3, 2.0),
            ("AMD", "drive long", 5, 7.0), ("AMD", "bounce long", 6, 1.0),
        ])

        traded, selections = walk_forward(trades, ["AMD"], SESSIONS, SESSIONS[2], lookback=2, hold=3, top_n=1,
                                          capital=1000.0)

        assert [s["setups"] for s in selections] == ["drive long (+1.00%)", "bounce long (+2.00%)"]
        assert list(zip(traded["setup"], traded["pnl"])) == [
            ("drive long", pytest.approx(-30.0)), ("drive long", pytest.approx(5.0)),
            ("bounce long", pytest.approx(10.0))]


class TestPeriodTable:
    def test_totals_by_ticker_and_period(self):
        traded = _trades([("AMD", "drive long", 0, 0.0), ("META", "drive long", 1, 0.0)]).assign(pnl=[10.0, -4.0])

        grid = period_table(traded, ["AMD", "META"], lambda d: f"{d:%Y-%m}", 1000.0)

        assert grid.loc["All", "Total"] == pytest.approx(6.0)
        assert grid.loc["META", "2026-07"] == pytest.approx(-4.0)
