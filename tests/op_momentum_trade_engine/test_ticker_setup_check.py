from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_setup_check import (
    drive_breakdown,
    split_stats,
    summary_table,
    trade_stats,
)

ET = pytz.timezone("America/New_York")
DAYS = [date(2026, 10, 12) + timedelta(days=i) for i in range(4)]


def _daily(opens, closes):
    return pd.DataFrame({"Open": opens, "Close": closes}, index=DAYS[:len(opens)])


def _session(day, bars):
    index = pd.DatetimeIndex([ET.localize(datetime.combine(day, time(9, 30)) + timedelta(minutes=5 * i))
                              for i in range(len(bars))])
    return pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=index)


class TestSplitStats:
    def test_intraday_and_overnight_from_daily_bars(self):
        stats = split_stats(_daily([100, 110, 99], [105, 100, 99]), DAYS[0])

        assert stats["intraday"] == pytest.approx((105 / 100 * 100 / 110 * 99 / 99 - 1) * 100)
        assert stats["overnight"] == pytest.approx((110 / 105 * 99 / 100 - 1) * 100)

    def test_win_rates_and_worst_gap(self):
        stats = split_stats(_daily([100, 110, 99], [105, 100, 99]), DAYS[0])

        assert (stats["intraday_win"], stats["overnight_win"]) == (pytest.approx(100 / 3), 50.0)
        assert (stats["worst_gap"], stats["worst_gap_day"]) == (pytest.approx(-1.0), DAYS[2])

    def test_no_gap_into_the_first_session(self):
        stats = split_stats(_daily([50, 100], [100, 100]), DAYS[1])

        assert (stats["overnight"], stats["sessions"]) == (0.0, 1)

    def test_buy_and_hold_from_the_first_open(self):
        assert split_stats(_daily([100, 110], [105, 120]), DAYS[0])["buy_hold"] == pytest.approx(20.0)


class TestTradeStats:
    def test_totals_and_drawdown(self):
        stats = trade_stats({DAYS[0]: [1.0], DAYS[1]: [-2.0, -0.5], DAYS[2]: [1.5]})

        assert (stats["trades"], stats["won"], stats["total"]) == (4, 50.0, 0.0)
        assert stats["max_dd"] == pytest.approx(-250.0)

    def test_no_trades(self):
        stats = trade_stats({})

        assert (stats["trades"], stats["total"], stats["max_dd"]) == (0, 0.0, 0.0)
        assert np.isnan(stats["won"])


class TestDriveBreakdown:
    def test_parts_add_up_to_the_open_close_moves(self):
        held_to_close = _session(DAYS[0], [(100, 101.5, 99.5, 101), (101, 103, 100.8, 103)])
        stopped_then_recovered = _session(DAYS[1], [(100, 101, 99.8, 100.5), (100.4, 100.5, 99.0, 99.2),
                                                    (99.2, 102, 99.1, 102)])
        red_first_bar = _session(DAYS[2], [(100, 100.2, 98.8, 99), (99, 99.1, 97.9, 98)])
        bars = pd.concat([held_to_close, stopped_then_recovered, red_first_bar])

        out = drive_breakdown(bars)

        assert out["skipped"] == pytest.approx(-2.0)
        assert (out["skipped_days"], out["stops"]) == (1, 1)
        assert out["first_bar"] == pytest.approx(1.0 + 0.5)
        assert out["after_stop"] == pytest.approx(2.2)
        assert out["skipped"] + out["first_bar"] + out["after_stop"] + out["kept"] == pytest.approx(out["open_close"])


class TestSummaryTable:
    def test_one_row_per_ticker(self):
        split = {"intraday": 1.0, "intraday_win": 50.0, "overnight": 2.0, "overnight_win": 60.0, "worst_gap": -3.0}
        setups = {k: {"total": 1.0} for k in ("drive long", "drive-trail", "overnight ma200")}
        results = [{"ticker": t, "splits": {"period": split, "last 20": split}, "setups": setups} for t in ("MU", "LLY")]

        table = summary_table(results, 20)

        assert [line.split()[0] for line in table.splitlines()[1:]] == ["MU", "LLY"]
