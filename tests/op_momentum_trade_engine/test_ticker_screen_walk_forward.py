from datetime import date, timedelta

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen_walk_forward import (
    cached_legs,
    core_trades,
    month_starts,
    parse_args,
    passers_by_month,
    summary,
    walk,
)

MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen_walk_forward"
JAN, FEB, MAR = date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)


def _sessions(start, count):
    return [start + timedelta(days=i) for i in range(count)]


def _trades(rows):
    return pd.DataFrame(rows, columns=["ticker", "day", "leg", "pct"])


class TestMonthStarts:
    def test_first_session_of_each_month_in_the_year(self):
        sessions = [date(2025, 12, 31), date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 2), date(2026, 2, 3)]

        assert month_starts(sessions, 2026) == [date(2026, 1, 2), date(2026, 2, 2)]


class TestPassersByMonth:
    def test_uses_only_bars_before_the_month(self):
        days = _sessions(date(2025, 10, 1), 120)
        wide_later = pd.DataFrame({"Close": 100.0, "High": [101.0] * 90 + [110.0] * 30, "Low": 99.0, "Volume": 1e7},
                                  index=days)
        start = days[90]

        assert passers_by_month({"AMD": wide_later}, [start], 10, 4.0, 10.0) == {start: []}
        assert passers_by_month({"AMD": wide_later}, [days[-1]], 10, 4.0, 10.0)[days[-1]] == ["AMD"]


class TestCoreTrades:
    def test_keeps_drive_long_and_allowed_overnight_nights(self):
        legs = _trades([("AMD", JAN, "drive long", 1.0), ("AMD", JAN, "overnight long", 2.0),
                        ("AMD", FEB, "overnight long", 3.0)])

        assert core_trades(legs, {JAN: True, FEB: False}).pct.tolist() == [1.0, 2.0]


class TestWalk:
    def _core(self):
        rows = [("A", JAN - timedelta(days=i), "drive long", 1.0) for i in range(1, 11)]
        rows += [("B", JAN - timedelta(days=i), "drive long", 2.0) for i in range(1, 11)]
        rows += [("A", JAN, "drive long", 5.0), ("B", JAN, "drive long", -4.0), ("B", FEB, "drive long", 3.0)]
        return _trades(rows)

    def test_picks_the_best_trailing_ticker_and_trades_its_month(self):
        sessions = sorted(set(self._core().day))

        trades, chosen = walk(self._core(), {JAN: ["A", "B"]}, sessions, [JAN], picks=1, lookback=63, capital=10000)

        assert chosen == {JAN: ["B"]}
        assert trades[["ticker", "pct", "dollars"]].values.tolist() == [["B", -4.0, -400.0], ["B", 3.0, 300.0]]

    def test_only_screen_passers_are_picked(self):
        sessions = sorted(set(self._core().day))

        _, chosen = walk(self._core(), {JAN: ["A"]}, sessions, [JAN], picks=1, lookback=63, capital=10000)

        assert chosen == {JAN: ["A"]}

    def test_month_ends_at_the_next_month_start(self):
        sessions = sorted(set(self._core().day))

        trades, _ = walk(self._core(), {JAN: ["B"], FEB: []}, sessions, [JAN, FEB], picks=1, lookback=63,
                         capital=10000)

        assert trades.pct.tolist() == [-4.0]


class TestSummary:
    def test_pnl_drawdown_and_months(self):
        trades = pd.DataFrame({"day": [JAN, FEB, MAR], "pct": [1.0, -2.0, 0.5], "dollars": [100.0, -200.0, 50.0],
                               "month": ["2026-01", "2026-02", "2026-03"]})

        assert summary(trades) == {"trades": 3, "won %": 66.7, "per trade %": -0.167, "P&L $": -50, "max DD $": -200,
                                   "months +": 2}


class TestCachedLegs:
    def test_computes_missing_tickers_once(self, tmp_path, mocker):
        legs = _trades([("AMD", JAN, "drive long", 1.0), ("AMD", JAN, "overnight short", 9.0)])
        pool = mocker.patch(f"{MODULE}.ProcessPoolExecutor")
        pool.return_value.__enter__.return_value.map.return_value = [legs]

        first = cached_legs(["AMD"], JAN, MAR, tmp_path, 1)
        second = cached_legs(["AMD"], JAN, MAR, tmp_path, 1)

        assert first.leg.tolist() == second.leg.tolist() == ["drive long"]
        assert pool.call_count == 1


class TestParseArgs:
    def test_defaults_match_the_screen(self):
        args = parse_args(["--years", "2025"])

        assert (args.top_volume, args.min_range, args.lookback, args.picks, args.capital) == (150, 4.0, 63, 5, 10000.0)
