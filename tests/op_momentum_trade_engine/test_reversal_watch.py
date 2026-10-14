from pathlib import Path

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.reversal_watch import ReversalSignal, ReversalWatch, reversal_message

ET = pytz.timezone("America/New_York")
FIXTURES = Path(__file__).parent / "fixtures"


def _amd_bars(day):
    """AMD 5-min bars (SIP, split-adjusted) for `day` and the session before it."""
    frame = pd.read_csv(FIXTURES / f"amd_5min_{day}.csv", index_col="time")
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(ET)
    return frame


def _fired(watch, frame):
    signals = []
    for stamp, row in frame.iterrows():
        signals += watch.update(stamp, row.to_dict())
    return [(f"{s.time:%Y-%m-%d %H:%M}", s.pattern, s.side) for s in signals]


def _signal(pattern, side, price=454.095):
    return ReversalSignal(ticker="AMD", time=ET.localize(pd.Timestamp("2026-09-01 10:30").to_pydatetime()),
                          side=side, pattern=pattern, price=price, extreme=452.3, move_bars=5.48)


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

    def test_fires_nothing_before_the_average_bar_is_known(self):
        frame = _amd_bars("2026-09-01")

        fired = _fired(ReversalWatch("AMD"), frame[frame.index.date == frame.index[-1].date()])

        assert not [f for f in fired if f[0] < "2026-09-01 11:10"]


class TestReversalWatchReplay:
    def test_replay_fires_nothing_and_the_next_bar_still_fires(self):
        frame = _amd_bars("2026-09-01")
        watch = ReversalWatch("AMD")
        signal_bar = frame.index.get_loc(pd.Timestamp("2026-09-01 10:30", tz=ET))

        watch.replay(frame.iloc[:signal_bar])
        fired = watch.update(frame.index[signal_bar], frame.iloc[signal_bar].to_dict())

        assert {(s.pattern, s.side) for s in fired} == {("piercing", "bottom"), ("push", "bottom")}

    def test_ignores_a_bar_it_has_already_seen(self):
        frame = _amd_bars("2026-09-01")
        watch = ReversalWatch("AMD")
        signal_bar = frame.index.get_loc(pd.Timestamp("2026-09-01 10:30", tz=ET))
        watch.replay(frame.iloc[:signal_bar + 1])

        assert watch.update(frame.index[signal_bar], frame.iloc[signal_bar].to_dict()) == []


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
