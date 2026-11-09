from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_process_walk_forward import (
    cached_short_legs,
    gate_days,
    month_days,
    month_trades,
    parse_args,
    refresh_setups,
    run_plan,
    summary,
)

MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_process_walk_forward"
JAN, FEB = date(2026, 1, 2), date(2026, 2, 2)


def _report(rows):
    """Setup report rows (ticker, setup, day, net_pct) at each setup's fixed exit."""
    exits = {"drive long": "eod", "bounce long": "target", "pullback long": "target-trail",
             "overnight always": "next open", "box break": "target"}
    return pd.DataFrame([{"ticker": t, "setup": s, "exit": exits[s], "day": d, "net_pct": p} for t, s, d, p in rows],
                        columns=["ticker", "setup", "exit", "day", "net_pct"])


def _legs(rows):
    return pd.DataFrame(rows, columns=["ticker", "day", "leg", "pct"])


NO_GATES = (set(), set(), {})


class TestMonthDays:
    def test_splits_sessions_at_month_starts(self):
        sessions = [date(2026, 1, 2), date(2026, 1, 30), date(2026, 2, 2), date(2026, 2, 3), date(2026, 2, 4)]

        assert month_days([JAN, FEB], sessions, date(2026, 2, 3)) == {
            JAN: [date(2026, 1, 2), date(2026, 1, 30)], FEB: [date(2026, 2, 2), date(2026, 2, 3)]}


class TestRefreshSetups:
    def test_top_positive_long_setups_with_enough_trades(self):
        past = [JAN - timedelta(days=k) for k in range(1, 6)]
        rows = [("AMD", "drive long", d, 1.0) for d in past] + [("AMD", "bounce long", d, 0.5) for d in past]
        rows += [("AMD", "pullback long", d, -1.0) for d in past] + [("AMD", "box break", d, 5.0) for d in past]
        rows += [("AMD", "overnight always", past[0], 9.0)]

        assert refresh_setups(_report(rows), ["AMD", "MU"], past, top_n=3, min_trades=3) == {
            "AMD": ["drive long", "bounce long"], "MU": []}

    def test_ignores_trades_outside_the_lookback(self):
        rows = [("AMD", "drive long", JAN, 1.0)] * 3

        assert refresh_setups(_report(rows), ["AMD"], [JAN - timedelta(days=1)], 3, 3) == {"AMD": []}


class TestMonthTrades:
    def test_keeps_only_the_chosen_setups(self):
        report = _report([("AMD", "drive long", JAN, 1.0), ("AMD", "bounce long", JAN, 2.0)])

        trades = month_trades(report, _legs([]), {"AMD": ["drive long"]}, [JAN], NO_GATES, with_shorts=False)

        assert trades.setup.tolist() == ["drive long"]

    def test_overnight_long_needs_the_trend_filter_and_no_overnight_short(self):
        report = _report([("AMD", "overnight always", JAN, 1.0), ("AMD", "overnight always", FEB, 1.0)])
        gates = (set(), {FEB}, {JAN: True, FEB: True})

        trades = month_trades(report, _legs([]), {"AMD": ["overnight always"]}, [JAN, FEB], gates, with_shorts=True)

        assert trades.day.tolist() == [JAN]

    def test_gated_shorts_on_the_picks_and_qqq(self):
        legs = _legs([("AMD", JAN, "drive short + re-entry", 1.0), ("QQQ", JAN, "overnight short", 2.0),
                      ("MU", JAN, "drive short + re-entry", 3.0), ("AMD", FEB, "drive short + re-entry", 4.0)])
        gates = ({JAN}, {JAN}, {})

        trades = month_trades(_report([]), legs, {"AMD": []}, [JAN, FEB], gates, with_shorts=True)

        assert trades[["ticker", "setup"]].values.tolist() == [["AMD", "drive short + re-entry"], ["QQQ", "overnight short"]]

    def test_no_shorts_without_with_shorts(self):
        legs = _legs([("AMD", JAN, "drive short + re-entry", 1.0)])

        assert month_trades(_report([]), legs, {"AMD": []}, [JAN], ({JAN}, set(), {}), with_shorts=False).empty


class TestRunPlan:
    def _data(self):
        report = _report([("AMD", "drive long", JAN - timedelta(days=k), 1.0) for k in range(1, 4)] +
                         [("AMD", "drive long", JAN, 2.0), ("AMD", "bounce long", JAN, 4.0)])
        sessions = sorted(set(report.day))
        return {"trades": report, "fixed_exit": report, "short_legs": _legs([]), "sessions": sessions,
                "months": {JAN: [JAN]}, "gates": NO_GATES}

    def _args(self):
        return SimpleNamespace(refresh_lookback=63, top_setups=3, min_trades=3, fixed_setups=["bounce long"],
                               capital=10000.0, picks=5)

    def test_refresh_uses_past_trades_only(self):
        trades, chosen = run_plan("refresh", False, {JAN: ["AMD"]}, self._data(), self._args())

        assert chosen == {JAN: {"AMD": ["drive long"]}}
        assert trades[["setup", "dollars"]].values.tolist() == [["drive long", 40.0]]

    def test_fixed_setups(self):
        trades, _ = run_plan("fixed", False, {JAN: ["AMD"]}, self._data(), self._args())

        assert trades.setup.tolist() == ["bounce long"]


class TestSummary:
    def test_pnl_drawdown_and_months(self):
        trades = pd.DataFrame({"day": [JAN, FEB], "pct": [1.0, -2.0], "dollars": [100.0, -200.0],
                               "month": ["2026-01", "2026-02"]})

        assert summary(trades) == {"trades": 2, "won %": 50.0, "per trade %": -0.5, "P&L $": -100, "max DD $": -200,
                                   "months +": "1/2"}


class TestGateDays:
    def test_off_is_no_days(self):
        assert gate_days("off", JAN, FEB) == set()


class TestCachedShortLegs:
    def test_computes_missing_tickers_once_and_keeps_short_legs(self, tmp_path, mocker):
        legs = _legs([("AMD", JAN, "drive short + re-entry", 1.0), ("AMD", JAN, "drive long", 2.0)])
        pool = mocker.patch(f"{MODULE}.ProcessPoolExecutor")
        pool.return_value.__enter__.return_value.map.return_value = [legs]

        first = cached_short_legs(["AMD"], JAN, FEB, tmp_path, 1)
        second = cached_short_legs(["AMD"], JAN, FEB, tmp_path, 1)

        assert first.leg.tolist() == second.leg.tolist() == ["drive short + re-entry"]
        assert pool.call_count == 1


class TestParseArgs:
    def test_defaults_match_the_monitor(self):
        args = parse_args(["--year", "2026"])

        assert (args.picks, args.top_setups, args.refresh_lookback, args.min_trades, args.short_gate,
                args.overnight_short_gate) == (5, 3, 63, 3, "qqq-ma50-down10", "qqq-ma200")
