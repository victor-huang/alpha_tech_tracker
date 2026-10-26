from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.short_setups import (
    RETEST_MAX_PER_DAY,
    RallyTracker,
    RetestShort,
    gate_status,
    next_session_adr,
)

ET = pytz.timezone("America/New_York")
DAY = date(2026, 10, 13)


def _time(hh, mm, day=DAY):
    return ET.localize(datetime.combine(day, time(hh, mm)))


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def _watch(mocker, peaks):
    """A RetestShort whose rally tracker reports `peaks` (None or a rally high) bar by bar."""
    watch = RetestShort("AMD")
    watch.tracker = mocker.Mock(update=mocker.Mock(side_effect=list(peaks)))
    return watch


class TestGateStatus:
    def test_on_below_the_50_day_ma(self):
        on, text = gate_status("qqq-ma50", [100.0] * 49 + [90.0])

        assert on
        assert text == "short setups on: QQQ closed 90.00, below its 50-day MA 99.80"

    def test_off_above_the_50_day_ma(self):
        assert gate_status("qqq-ma50", [100.0] * 49 + [110.0])[0] is False

    def test_off_without_enough_history(self):
        assert gate_status("qqq-ma50", [100.0] * 10) == (
            False, "short setups off: QQQ has 10 daily closes, the gate needs 50")

    @pytest.mark.parametrize("gate,expected", [("always", True), ("off", False)])
    def test_fixed_gates(self, gate, expected):
        assert gate_status(gate, [])[0] is expected


class TestRallyTracker:
    def test_reports_the_rally_high_on_the_turn_down(self):
        closes = [100 + i for i in range(10)] + [107 - i for i in range(10)]
        tracker = RallyTracker(3, 0.236, 1.5)

        peaks = [tracker.update(_time(9, 30) + timedelta(minutes=5 * i), _bar(c, c + 0.3, c - 0.3, c))
                 for i, c in enumerate(closes)]

        assert [p for p in peaks if p is not None] == [pytest.approx(109.3)]

    def test_resets_at_a_new_session(self):
        tracker = RallyTracker(3, 0.236, 1.5)
        tracker.update(_time(15, 55, DAY - timedelta(days=1)), _bar(100, 101, 99, 100))

        tracker.update(_time(9, 30), _bar(50, 51, 49, 50))

        assert tracker.wave.df.index[0] == _time(9, 30)


class TestRetestShortEntry:
    def test_fills_on_a_later_bar_that_reaches_the_level(self, mocker):
        watch = _watch(mocker, [110.0, None])
        watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)

        events = watch.update(_time(10, 5), _bar(108, 109.8, 107.9, 109), 10.0, False)

        assert events[0] == {"kind": "entry", "fill": 109.5, "stop": 112.0, "stopped": False}

    def test_never_fills_on_the_bar_that_confirms_the_high(self, mocker):
        watch = _watch(mocker, [110.0])

        events = watch.update(_time(10, 0), _bar(108, 109.9, 107, 107.5), 10.0, False)

        assert not [e for e in events if e["kind"] == "entry"]

    def test_fill_at_a_higher_open(self, mocker):
        watch = _watch(mocker, [110.0, None])
        watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)

        events = watch.update(_time(10, 5), _bar(110.5, 111, 109, 109.2), 10.0, False)

        assert events[0]["fill"] == 110.5

    def test_bar_through_the_stop_is_stopped(self, mocker):
        watch = _watch(mocker, [110.0, None])
        watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)

        assert watch.update(_time(10, 5), _bar(108, 112.5, 107.9, 112), 10.0, False)[0]["stopped"] is True

    def test_needs_the_previous_close_below_the_level(self, mocker):
        watch = _watch(mocker, [110.0, None])
        watch.update(_time(10, 0), _bar(108, 109.9, 107, 109.7), 10.0, False)

        assert watch.update(_time(10, 5), _bar(109.7, 110, 109, 109.8), 10.0, False) == []

    def test_no_entry_before_1000(self, mocker):
        watch = _watch(mocker, [110.0, None])
        watch.update(_time(9, 50), _bar(108, 108.5, 107, 107.5), 10.0, False)

        assert not [e for e in watch.update(_time(9, 55), _bar(108, 109.8, 107.9, 109), 10.0, False)
                    if e["kind"] == "entry"]

    def test_at_most_two_entries_a_day(self, mocker):
        watch = _watch(mocker, [110.0] + [None] * 6)
        watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)
        fills = 0
        for k in range(1, 7):
            stamp = _time(10, 0) + timedelta(minutes=5 * k)
            bars = [_bar(108, 109.8, 107.9, 109), _bar(109, 109.2, 107, 107.5)]
            events = watch.update(stamp, bars[(k + 1) % 2], 10.0, False)
            fills += sum(e["kind"] == "entry" for e in events)

        assert fills == RETEST_MAX_PER_DAY

    def test_no_entry_while_in_position(self, mocker):
        watch = _watch(mocker, [110.0, None])
        watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)

        assert watch.update(_time(10, 5), _bar(108, 109.8, 107.9, 109), 10.0, True) == []


class TestRetestShortTrailAndArm:
    def test_trail_on_a_new_high_while_in_position(self, mocker):
        watch = _watch(mocker, [105.0])

        assert watch.update(_time(11, 0), _bar(104, 104.5, 103, 103.2), 10.0, True) == [
            {"kind": "trail", "peak": 105.0}]

    def test_arms_the_limit_for_the_next_bar_once(self, mocker):
        watch = _watch(mocker, [110.0, None])

        first = watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)
        second = watch.update(_time(10, 5), _bar(107.5, 108, 107, 107.2), 10.0, False)

        assert first == [{"kind": "arm", "level": 109.5, "stop": 112.0}]
        assert second == []

    def test_no_arm_after_the_window(self, mocker):
        watch = _watch(mocker, [110.0])

        assert watch.update(_time(14, 55), _bar(108, 108.5, 107, 107.5), 10.0, False) == []

    def test_new_session_forgets_yesterdays_high(self, mocker):
        watch = _watch(mocker, [110.0, None, None])
        watch.update(_time(14, 0, DAY - timedelta(days=1)), _bar(108, 108.5, 107, 107.5), 10.0, False)
        watch.update(_time(10, 0), _bar(108, 108.5, 107, 107.5), 10.0, False)

        assert watch.update(_time(10, 5), _bar(108, 109.8, 107.9, 109), 10.0, False) == []


class TestNextSessionAdr:
    def test_mean_range_of_the_previous_sessions(self):
        frames = []
        for k, rng in enumerate((2.0, 4.0)):
            day = DAY - timedelta(days=2 - k)
            index = pd.DatetimeIndex([_time(9, 30, day), _time(9, 35, day)])
            frames.append(pd.DataFrame({"high": [100 + rng, 100.0], "low": [100.0, 100.0]}, index=index))

        assert next_session_adr(pd.concat(frames), DAY, sessions=2) == pytest.approx(3.0)

    def test_none_without_enough_sessions(self):
        index = pd.DatetimeIndex([_time(9, 30, DAY - timedelta(days=1))])

        assert next_session_adr(pd.DataFrame({"high": [101.0], "low": [100.0]}, index=index), DAY) is None
