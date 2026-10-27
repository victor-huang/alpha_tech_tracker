from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import (
    plans,
    summarize,
    trail_reentry,
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


class TestSummarize:
    def test_totals_and_drawdown(self):
        trades = pd.DataFrame({"day": [DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)],
                               "pct": [2.0, -3.0, 1.0], "dollars": [50.0, -75.0, 25.0]})

        result = summarize(trades, 10000.0)

        assert (result["trades"], result["P&L $"], result["return %"]) == (3, 0.0, 0.0)
        assert (result["won %"], result["max DD $"]) == (pytest.approx(200 / 3), -75.0)

    def test_no_trades(self):
        assert summarize(pd.DataFrame(columns=["day", "pct", "dollars"]), 10000.0)["trades"] == 0
