from pathlib import Path

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy import reversal_watch as reversal_module
from alpha_tech_tracker.op_momentum_strategy.reversal_watch import (
    MIN_AVERAGE_BARS,
    ReversalSignal,
    ReversalWatch,
    reversal_message,
)

ET = pytz.timezone("America/New_York")
FIXTURES = Path(__file__).parent / "fixtures"


def _amd_bars(day):
    """AMD 5-min bars (SIP, split-adjusted) for `day` and the session before it."""
    frame = pd.read_csv(FIXTURES / f"amd_5min_{day}.csv", index_col="time")
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(ET)
    return frame


def _ts(text):
    return pd.Timestamp(text, tz=ET)


def _fired(watch, frame):
    signals = []
    for stamp, row in frame.iterrows():
        signals += watch.update(stamp, row.to_dict())
    return [(f"{s.time:%Y-%m-%d %H:%M}", s.pattern, s.side) for s in signals]


def _signal(pattern, side, price=454.095):
    return ReversalSignal(ticker="AMD", time=_ts("2026-09-01 10:30"), side=side, pattern=pattern, price=price,
                          extreme=452.3, move_bars=5.48)


def _bar(price):
    return {"open": price, "high": price + 1.0, "low": price - 1.0, "close": price}


class TestReversalWatchSignals:
    def test_piercing_and_push_fire_at_a_wave_low(self):
        fired = _fired(ReversalWatch("AMD"), _amd_bars("2026-09-01"))

        assert ("2026-09-01 10:30", "piercing", "bottom") in fired
        assert ("2026-09-01 10:30", "push", "bottom") in fired

    def test_confirmed_long_tail_fires_on_the_confirming_bar(self):
        fired = _fired(ReversalWatch("AMD"), _amd_bars("2026-09-01"))

        assert ("2026-09-01 09:45", "long_tail", "bottom") in fired

    def test_dark_cloud_and_push_fire_at_a_wave_high(self):
        fired = _fired(ReversalWatch("AMD"), _amd_bars("2026-09-16"))

        assert ("2026-09-16 10:00", "piercing", "top") in fired
        assert ("2026-09-16 10:00", "push", "top") in fired

    def test_fires_only_the_chosen_patterns(self):
        fired = _fired(ReversalWatch("AMD", patterns=["push"]), _amd_bars("2026-09-01"))

        assert {pattern for _, pattern, _ in fired} == {"push"}


class TestReversalWatchCandidates:
    def test_no_average_bar_before_enough_bars(self):
        watch = ReversalWatch("AMD")
        frame = _amd_bars("2026-09-01")

        _fired(watch, frame.iloc[:MIN_AVERAGE_BARS])

        assert watch.previous["average_bar"] is None

    def test_average_bar_once_enough_bars(self):
        watch = ReversalWatch("AMD")
        frame = _amd_bars("2026-09-01")

        _fired(watch, frame.iloc[:MIN_AVERAGE_BARS + 1])

        assert watch.previous["average_bar"] == pytest.approx((frame.high - frame.low).iloc[:MIN_AVERAGE_BARS].mean())

    def test_no_signal_on_the_sessions_first_two_bars(self, mocker):
        mocker.patch.object(ReversalWatch, "_candidate_sides", return_value=[("bottom", 3.0, 99.0)])
        mocker.patch.object(reversal_module, "push_reversal", return_value=True)

        fired = _fired(ReversalWatch("AMD", patterns=["push"]), _amd_bars("2026-09-01"))

        assert [f[0] for f in fired if f[0] >= "2026-08-31 15:55"][:2] == ["2026-08-31 15:55", "2026-09-01 09:40"]


class TestReversalWatchBadBars:
    def test_zero_price_bar_is_skipped(self):
        watch = ReversalWatch("AMD")

        assert watch.update(_ts("2026-09-01 09:30"), {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0}) == []
        assert watch.last_time is None

    def test_nan_bar_is_skipped(self):
        watch = ReversalWatch("AMD")

        watch.update(_ts("2026-09-01 09:30"), {**_bar(100.0), "high": float("nan")})

        assert (watch.last_time, len(watch.ranges)) == (None, 0)

    def test_signals_after_a_skipped_bar_are_unchanged(self):
        frame = _amd_bars("2026-09-01")
        watch = ReversalWatch("AMD")
        _fired(watch, frame[frame.index < _ts("2026-09-01 10:30")])
        watch.update(_ts("2026-09-01 10:26"), {**_bar(450.0), "close": float("nan")})

        fired = watch.update(_ts("2026-09-01 10:30"), frame.loc[_ts("2026-09-01 10:30")].to_dict())

        assert {(s.pattern, s.side) for s in fired} == {("piercing", "bottom"), ("push", "bottom")}

    def test_ignores_a_bar_it_has_already_seen(self):
        frame = _amd_bars("2026-09-01")
        watch = ReversalWatch.from_bars("AMD", frame[frame.index <= _ts("2026-09-01 10:30")])

        assert watch.update(_ts("2026-09-01 10:30"), frame.loc[_ts("2026-09-01 10:30")].to_dict()) == []


class TestReversalWatchFromBars:
    def test_replay_fires_nothing_and_the_next_bar_still_fires(self):
        frame = _amd_bars("2026-09-01")
        watch = ReversalWatch.from_bars("AMD", frame[frame.index < _ts("2026-09-01 10:30")])

        fired = watch.update(_ts("2026-09-01 10:30"), frame.loc[_ts("2026-09-01 10:30")].to_dict())

        assert {(s.pattern, s.side) for s in fired} == {("piercing", "bottom"), ("push", "bottom")}

    def test_matches_a_full_replay(self):
        frame = pd.concat([_amd_bars("2026-09-01"), _amd_bars("2026-09-16")])
        cut = _ts("2026-09-16 09:50")
        full = ReversalWatch("AMD")
        _fired(full, frame[frame.index < cut])

        fast = ReversalWatch.from_bars("AMD", frame[frame.index < cut])

        rest = frame[frame.index >= cut]
        assert _fired(fast, rest) == _fired(full, rest)

    def test_replays_only_the_recent_sessions(self, mocker):
        frame = pd.concat([_amd_bars("2026-09-01"), _amd_bars("2026-09-16")])
        update = mocker.spy(ReversalWatch, "update")

        ReversalWatch.from_bars("AMD", frame)

        assert update.call_args_list[0].args[1] == _ts("2026-09-15 09:30")

    def test_skips_invalid_rows(self):
        frame = _amd_bars("2026-09-01")
        frame.loc[frame.index[-1], "close"] = float("nan")

        assert ReversalWatch.from_bars("AMD", frame).last_time == frame.index[-2]

    def test_empty_frame(self):
        assert ReversalWatch.from_bars("AMD", _amd_bars("2026-09-01").iloc[:0]).last_time is None


class TestReversalMessage:
    def test_one_pattern(self):
        assert reversal_message([_signal("piercing", "bottom")]) == (
            "LOW? AMD | piercing | ~454.10 (10:30 bar close) | wave down 5.5 avg bars, low 452.30")

    def test_patterns_on_one_bar_share_an_alert(self):
        assert reversal_message([_signal("piercing", "top"), _signal("push", "top")]) == (
            "HIGH? AMD | dark cloud + push | ~454.10 (10:30 bar close) | wave up 5.5 avg bars, high 452.30")

    @pytest.mark.parametrize("pattern,side,name", [("long_tail", "bottom", "long tail + confirm"),
                                                   ("piercing", "top", "dark cloud")])
    def test_names_the_pattern(self, pattern, side, name):
        assert f"| {name} |" in reversal_message([_signal(pattern, side)])
