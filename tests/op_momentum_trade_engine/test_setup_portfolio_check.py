from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import (
    gated_sessions,
    parse_args,
    plans,
    summarize,
    trail_reentry,
    trend_mask,
)

ET = pytz.timezone("America/New_York")
DAY = date(2026, 10, 13)


def _time(i):
    return ET.localize(datetime.combine(DAY, time(9, 30)) + timedelta(minutes=5 * i))


def _bar(i, o, h, l, c, turn=None, dip_low=None):
    return {"time": _time(i), "open": o, "high": h, "low": l, "close": c, "turn": turn, "dip_low": dip_low}


def _flat(i, price, **extra):
    return _bar(i, price, price + 0.2, price - 0.2, price, **extra)


class TestTrailReentry:
    def test_red_first_bar_no_trade(self):
        assert trail_reentry([_bar(0, 101, 101.5, 99.5, 100), _flat(1, 102)]) == []

    def test_held_to_the_close_with_the_stop_raised(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _flat(1, 103, turn="up", dip_low=102.0), _flat(2, 104)]

        assert trail_reentry(bars) == [(_time(0), 101, _time(2), 104, "close")]

    def test_re_entry_above_the_raised_stop_that_was_hit(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _flat(1, 103, turn="up", dip_low=102.0),
                _bar(2, 102.5, 102.6, 101.6, 101.8), _flat(3, 102.3), _flat(4, 105)]

        trades = trail_reentry(bars)

        assert trades[0] == (_time(0), 101, _time(2), 102.0, "stop")
        assert trades[1] == (_time(3), 102.3, _time(4), 105, "close")

    def test_only_one_re_entry(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _bar(1, 100, 100.1, 99.0, 99.3), _flat(2, 100),
                _bar(3, 99.9, 100.0, 98.5, 98.8), _flat(4, 100.2), _flat(5, 101)]

        assert len(trail_reentry(bars)) == 2

    def test_no_re_entry_from_1500(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _bar(1, 100, 100.1, 99.0, 99.3)]
        bars += [_flat(i, 99.2) for i in range(2, 66)] + [_flat(66, 100.0), _flat(67, 101)]

        assert len(trail_reentry(bars)) == 1


class TestPlans:
    def _trades(self):
        rows = [("drive long", False), ("drive long", True), ("drive short + re-entry", False),
                ("drive short + re-entry", True), ("overnight long", False), ("overnight long", True),
                ("overnight short", True), ("drive-trail", False)]
        return pd.DataFrame(rows, columns=["leg", "gated"])

    def test_monitor_rules_follow_the_gate(self):
        mask = plans()["monitor rules with drive long"](self._trades())

        assert self._trades()[mask].values.tolist() == [
            ["drive long", False], ["drive long", True], ["drive short + re-entry", True],
            ["overnight long", False], ["overnight short", True]]

    def test_variant_only_plan(self):
        mask = plans()["drive-trail only"](self._trades())

        assert self._trades()[mask]["leg"].tolist() == ["drive-trail"]

    def test_gated_drive_short_plan(self):
        mask = plans()["drive long + gated drive short"](self._trades())

        assert self._trades()[mask].values.tolist() == [["drive long", False], ["drive long", True],
                                                         ["drive short + re-entry", True]]

    def test_short_setups_drive_keeps_the_overnight_long_on_gated_days(self):
        mask = plans()["monitor with --short-setups drive (overnight long every allowed night)"](self._trades())

        assert self._trades()[mask].values.tolist() == [
            ["drive long", False], ["drive long", True], ["drive short + re-entry", True],
            ["overnight long", False], ["overnight long", True]]


class TestSummarize:
    def test_totals_and_drawdown(self):
        trades = pd.DataFrame({"day": [DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)],
                               "pct": [2.0, -3.0, 1.0], "dollars": [50.0, -75.0, 25.0]})

        result = summarize(trades, 10000.0)

        assert (result["trades"], result["P&L $"], result["return %"]) == (3, 0.0, 0.0)
        assert (result["won %"], result["max DD $"]) == (pytest.approx(200 / 3), -75.0)

    def test_no_trades(self):
        assert summarize(pd.DataFrame(columns=["day", "pct", "dollars"]), 10000.0)["trades"] == 0


class TestParseArgs:
    def test_overnight_mode_defaults_to_ma200(self):
        assert parse_args(["AMD", "--start", "2026-01-02"]).overnight_mode == "ma200"

    def test_overnight_mode_always(self):
        assert parse_args(["AMD", "--start", "2026-01-02", "--overnight-mode", "always"]).overnight_mode == "always"


def _daily(closes, start=date(2025, 7, 1)):
    index = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"high": [c + 1.0 for c in closes], "close": closes}, index=index)


RISING = _daily([100.0 + i for i in range(220)])
FALLING = _daily([320.0 - i for i in range(220)])
SESSION = date(2026, 2, 7)


class TestTrendMask:
    def _trades(self):
        rows = [("AMD", SESSION, "overnight long"), ("AMD", SESSION, "drive short + re-entry"),
                ("AMD", SESSION, "drive long"), ("META", SESSION, "drive short + re-entry")]
        return pd.DataFrame(rows, columns=["ticker", "day", "leg"])

    def test_overnight_long_dropped_when_qqq_fails(self):
        keep = trend_mask(self._trades(), ["overnight"], {"QQQ": FALLING})

        assert keep.tolist() == [False, True, True, True]

    def test_overnight_long_kept_when_qqq_passes(self):
        assert trend_mask(self._trades(), ["overnight"], {"QQQ": RISING}).all()


class TestPlansWithASeparateOvernightGate:
    def test_overnight_short_and_long_follow_the_overnight_gate(self):
        trades = pd.DataFrame([("drive short + re-entry", True, False), ("overnight short", True, False),
                               ("overnight long", True, False), ("overnight short", False, True)],
                              columns=["leg", "gated", "gated_overnight"])

        mask = plans()["monitor rules with drive long"](trades)

        assert mask.tolist() == [True, False, True, True]


class TestGatedSessions:
    def test_uses_the_monitor_gate_on_the_closes_before_each_day(self, mocker):
        closes = [120.0] * 199 + [100.0, 100.0]
        index = pd.to_datetime([date(2025, 1, 1) + timedelta(days=i) for i in range(len(closes))])
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check.fetch_daily_bars",
                     return_value={"QQQ": pd.DataFrame({"Close": closes}, index=index)})
        last, before = index[-1].date(), index[-2].date()

        assert gated_sessions(before, last, "qqq-ma200") == {last}

    def test_always_gates_every_day(self):
        assert gated_sessions(date(2026, 10, 12), date(2026, 10, 14), "always") == {
            date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)}


class TestTrendArguments:
    def test_defaults(self):
        args = parse_args(["AMD", "--start", "2026-01-02"])

        assert (args.short_gate, args.overnight_short_gate, args.trend_filters) == ("qqq-ma50", None, [])

    def test_new_gates(self):
        args = parse_args(["AMD", "--start", "2026-01-02", "--short-gate", "qqq-ma50-down10",
                           "--overnight-short-gate", "qqq-ma200"])

        assert (args.short_gate, args.overnight_short_gate) == ("qqq-ma50-down10", "qqq-ma200")

    def test_filters_and_gate(self):
        args = parse_args(["AMD", "--start", "2026-01-02", "--short-gate", "always", "--trend-filters", "overnight"])

        assert (args.short_gate, args.trend_filters) == ("always", ["overnight"])
