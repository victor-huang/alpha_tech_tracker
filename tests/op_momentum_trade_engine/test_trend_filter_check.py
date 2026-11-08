from datetime import date, timedelta

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.trend_filter_check import (
    compare,
    load_report_trades,
    mark_kept,
)

SESSION = date(2026, 8, 30)


def _daily(closes, start=date(2026, 7, 1)):
    index = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"high": [c + 1.0 for c in closes], "close": closes}, index=index)


RISING = _daily([100.0 + i for i in range(60)])
FALLING = _daily([160.0 - i for i in range(60)])


def _trades(rows):
    return pd.DataFrame(rows, columns=["ticker", "setup", "day", "pct"])


class TestLoadReportTrades:
    def test_keeps_the_fixed_exit_only(self, tmp_path):
        path = tmp_path / "trades.csv"
        pd.DataFrame({"ticker": ["AMD", "AMD"], "setup": ["pullback long", "pullback long"],
                      "exit": ["target-trail", "eod"], "entry_time": ["2026-08-30 10:05:00-04:00"] * 2,
                      "net_pct": [1.5, -0.5]}).to_csv(path, index=False)

        trades = load_report_trades(path)

        assert trades.values.tolist() == [["AMD", "pullback long", SESSION, 1.5]]


class TestMarkKept:
    def test_pullback_kept_on_a_higher_high_only(self):
        trades = _trades([("AMD", "pullback long", SESSION, 1.0), ("META", "pullback long C1", SESSION, -1.0)])

        marked = mark_kept(trades, {"QQQ": RISING, "AMD": RISING, "META": FALLING}, ["pullback"])

        assert marked["kept"].tolist() == [True, False]

    def test_unfiltered_setups_are_kept(self):
        trades = _trades([("AMD", "drive long", SESSION, 1.0), ("AMD", "pullback long", SESSION, 1.0)])

        marked = mark_kept(trades, {"QQQ": RISING, "AMD": FALLING}, ["overnight"])

        assert (marked["filter"].tolist(), marked["kept"].tolist()) == ([None, None], [True, True])

    def test_overnight_follows_qqq(self):
        trades = _trades([("AMD", "overnight always", SESSION, 1.0)])

        assert mark_kept(trades, {"QQQ": FALLING, "AMD": RISING}, ["overnight"])["kept"].tolist() == [False]

    def test_drive_short_needs_qqq_and_the_ticker_down(self):
        trades = _trades([("AMD", "drive short", SESSION, 1.0), ("META", "drive short", SESSION, 1.0)])

        marked = mark_kept(trades, {"QQQ": FALLING, "AMD": FALLING, "META": RISING}, ["drive-short"])

        assert marked["kept"].tolist() == [True, False]


class TestCompare:
    def test_kept_and_dropped_per_trade(self):
        trades = _trades([("AMD", "pullback long", SESSION, 2.0), ("AMD", "pullback long", SESSION, -1.0)])
        trades["filter"], trades["kept"] = "pullback", [True, False]

        row = compare(trades).loc["pullback long"]

        assert (row["all n"], row["kept %/trade"], row["dropped %/trade"], row["all sum %"]) == (2, 2.0, -1.0, 1.0)
