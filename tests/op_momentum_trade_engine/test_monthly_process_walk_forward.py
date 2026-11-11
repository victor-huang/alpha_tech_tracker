from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_process_walk_forward import (
    cap_positions,
    capital_in_use,
    cached_short_legs,
    drop_split_trades,
    gate_days,
    month_days,
    month_trades,
    parse_args,
    peak_positions,
    refresh_setups,
    run_plan,
    split_days,
    summary,
    with_costs,
)

MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_process_walk_forward"
JAN, FEB = date(2026, 1, 2), date(2026, 2, 2)


def _report(rows):
    """Setup report rows (ticker, setup, day, net_pct) at each setup's fixed exit."""
    exits = {"drive long": "eod", "bounce long": "target", "pullback long": "target-trail",
             "overnight always": "next open", "box break": "target"}
    out = {"open": "09:30", "close": "15:55"}
    return pd.DataFrame([{"ticker": t, "setup": s, "exit": exits[s], "day": d, "net_pct": p,
                          "entry_time": f"{d} {out['close'] if s.startswith('overnight') else out['open']}:00-05:00",
                          "exit_time": f"{d + timedelta(days=1) if s.startswith('overnight') else d} "
                                       f"{out['open'] if s.startswith('overnight') else out['close']}:00-05:00"}
                         for t, s, d, p in rows],
                        columns=["ticker", "setup", "exit", "day", "net_pct", "entry_time", "exit_time"])


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

        trades = month_trades(report, _legs([]), {"AMD": ["drive long"]}, [JAN], NO_GATES, drive_short=False, overnight_short=False)

        assert trades.setup.tolist() == ["drive long"]

    def test_overnight_long_needs_the_trend_filter_and_no_overnight_short(self):
        report = _report([("AMD", "overnight always", JAN, 1.0), ("AMD", "overnight always", FEB, 1.0)])
        gates = (set(), {FEB}, {JAN: True, FEB: True})

        trades = month_trades(report, _legs([]), {"AMD": ["overnight always"]}, [JAN, FEB], gates, drive_short=True,
                              overnight_short=True)

        assert trades.day.tolist() == [JAN]

    def test_gated_shorts_on_the_picks_and_qqq(self):
        legs = _legs([("AMD", JAN, "drive short + re-entry", 1.0), ("QQQ", JAN, "overnight short", 2.0),
                      ("MU", JAN, "drive short + re-entry", 3.0), ("AMD", FEB, "drive short + re-entry", 4.0)])
        gates = ({JAN}, {JAN}, {})

        trades = month_trades(_report([]), legs, {"AMD": []}, [JAN, FEB], gates, drive_short=True,
                              overnight_short=True)

        assert trades[["ticker", "setup"]].values.tolist() == [["AMD", "drive short + re-entry"], ["QQQ", "overnight short"]]

    def test_no_shorts_when_switched_off(self):
        legs = _legs([("AMD", JAN, "drive short + re-entry", 1.0)])

        assert month_trades(_report([]), legs, {"AMD": []}, [JAN], ({JAN}, set(), {}), False, False).empty


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
        trades, chosen = run_plan("refresh", False, False, {JAN: ["AMD"]}, self._data(), self._args())

        assert chosen == {JAN: {"AMD": ["drive long"]}}
        assert trades[["setup", "dollars"]].values.tolist() == [["drive long", 40.0]]

    def test_fixed_setups(self):
        trades, _ = run_plan("fixed", False, False, {JAN: ["AMD"]}, self._data(), self._args())

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
    def test_default_cap_is_twice_the_picks_and_costs_are_off(self):
        args = parse_args(["--year", "2026"])

        assert (args.max_positions, args.extra_cost_bps, args.borrow_bps) == (10, 0.0, 0.0)

    def test_defaults_match_the_monitor(self):
        args = parse_args(["--year", "2026"])

        assert (args.picks, args.top_setups, args.refresh_lookback, args.min_trades, args.short_gate,
                args.overnight_short_gate, args.rank_shorts) == (5, 3, 63, 3, "qqq-ma50-down10", "qqq-ma200", "none")


class TestSplits:
    def test_split_day_is_where_the_raw_to_adjusted_ratio_changes(self):
        days = [date(2024, 6, 6), date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)]
        raw = {"NVDA": pd.DataFrame({"Close": [1200.0, 1210.0, 121.0, 122.0]}, index=days)}
        adjusted = {"NVDA": pd.DataFrame({"Close": [120.0, 121.0, 121.0, 122.0]}, index=days)}

        assert split_days(raw, adjusted) == {"NVDA": {date(2024, 6, 10)}}

    def test_rounding_differences_are_not_splits(self):
        days = [date(2024, 6, 6), date(2024, 6, 7), date(2024, 6, 10)]
        raw = {"CVNA": pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=days)}
        adjusted = {"CVNA": pd.DataFrame({"Close": [100.01, 100.99, 102.02]}, index=days)}

        assert split_days(raw, adjusted) == {"CVNA": set()}

    def test_drops_only_trades_held_across_the_split(self):
        trades = pd.DataFrame({"ticker": ["NVDA", "NVDA", "AMD"], "day": [date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 7)],
                               "exit_time": ["2024-06-10 09:30:00-04:00", "2024-06-10 15:55:00-04:00",
                                             "2024-06-10 09:30:00-04:00"]})

        kept = drop_split_trades(trades, {"NVDA": {date(2024, 6, 10)}})

        assert kept[["ticker", "day"]].values.tolist() == [["NVDA", date(2024, 6, 10)], ["AMD", date(2024, 6, 7)]]


def _timed(rows):
    """(ticker, setup, entry "HH:MM", exit "HH:MM", pct) on JAN."""
    at = lambda hm: datetime.combine(JAN, datetime.strptime(hm, "%H:%M").time())
    return pd.DataFrame([{"ticker": t, "setup": s, "day": JAN, "pct": p, "entry": at(e), "exit": at(x)}
                         for t, s, e, x, p in rows])


class TestCapPositions:
    def test_skips_entries_while_the_slots_are_full(self):
        trades = _timed([("A", "drive long", "09:30", "15:55", 1.0), ("B", "drive long", "09:30", "15:55", 1.0),
                         ("C", "drive long", "09:35", "15:55", 1.0)])

        assert cap_positions(trades, 2).ticker.tolist() == ["A", "B"]

    def test_an_exit_frees_its_slot_for_an_entry_at_the_same_time(self):
        trades = _timed([("A", "drive long", "09:30", "10:00", 1.0), ("B", "pullback long", "10:00", "11:00", 1.0)])

        assert cap_positions(trades, 1).ticker.tolist() == ["A", "B"]

    def test_zero_is_no_cap(self):
        trades = _timed([("A", "drive long", "09:30", "15:55", 1.0), ("B", "drive long", "09:30", "15:55", 1.0)])

        assert len(cap_positions(trades, 0)) == 2


class TestPeakPositions:
    def test_most_open_at_once(self):
        trades = _timed([("A", "drive long", "09:30", "15:55", 1.0), ("B", "drive long", "09:35", "10:00", 1.0),
                         ("C", "drive long", "10:00", "11:00", 1.0)])

        assert peak_positions(trades) == 2


class TestWithCosts:
    def test_extra_cost_on_all_and_borrow_on_shorts(self):
        trades = _timed([("A", "drive long", "09:30", "15:55", 1.0), ("A", "drive short + re-entry", "09:30", "15:55", 1.0)])

        assert with_costs(trades, 5, 2).pct.round(4).tolist() == [0.95, 0.93]


class TestRefreshIgnoresHoldsExitingAfterIt:
    def test_last_session_overnight_hold_is_left_out(self):
        past = [JAN - timedelta(days=k) for k in range(3, 0, -1)]
        rows = [("AMD", "overnight always", d, 1.0) for d in past[:-1]] + [("AMD", "overnight always", past[-1], 9.0)]

        assert refresh_setups(_report(rows), ["AMD"], past, top_n=3, min_trades=3) == {"AMD": []}


class TestCapitalInUse:
    def test_average_of_each_days_most_money_open(self):
        jan2 = _timed([("A", "drive long", "09:30", "15:55", 1.0), ("B", "drive long", "09:35", "10:00", 1.0)])
        jan3 = _timed([("C", "drive long", "09:30", "15:55", 1.0)]).assign(
            entry=lambda f: f.entry + timedelta(days=4), exit=lambda f: f.exit + timedelta(days=4))

        assert capital_in_use(pd.concat([jan2, jan3]), 2000) == (3000.0, 4000.0)

    def test_overnight_hold_counts_on_the_morning_it_is_sold(self):
        hold = _timed([("A", "overnight always", "15:55", "15:55", 1.0)]).assign(exit=lambda f: f.exit + timedelta(hours=17, minutes=35))

        assert capital_in_use(hold, 2000) == (2000.0, 2000.0)
