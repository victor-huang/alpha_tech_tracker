import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.price_factors import (
    breakout_events,
    days_since_previous,
    factor_frames,
    jump_days,
    listed_between,
    ma_rising,
)


def _days(n):
    return pd.bdate_range("2024-01-01", periods=n)


def _wiggle(n, level=100.0):
    return level * (1 + 0.002 * np.sin(np.arange(n)))


class TestJumpDays:

    def test_big_move_on_heavy_volume_is_a_jump(self):
        prices = _wiggle(80)
        prices[70:] = prices[69] * 1.15
        close = pd.DataFrame({"A": prices}, index=_days(80))
        dollar_volume = close * 1e5
        dollar_volume.iloc[70] *= 5

        jumps = jump_days(close, dollar_volume)

        assert bool(jumps["up"]["A"].iloc[70])
        assert jumps["up"]["A"].sum() == 1

    def test_big_move_on_normal_volume_is_not_a_jump(self):
        prices = _wiggle(80)
        prices[70:] = prices[69] * 1.15
        close = pd.DataFrame({"A": prices}, index=_days(80))

        jumps = jump_days(close, close * 1e5)

        assert not jumps["up"]["A"].any()


class TestFactorFrames:

    def _jump_then(self, after):
        n = 400
        prices = _wiggle(n)
        prices[380:] = prices[379] * 1.20
        prices[390:] = after
        close = pd.DataFrame({"A": prices}, index=_days(n))
        dollar_volume = close * 1e5
        dollar_volume.iloc[380] *= 5
        return factor_frames(close, dollar_volume)

    def test_jump_still_mostly_kept_counts_as_held(self):
        frames = self._jump_then(after=119.0)

        assert bool(frames["jump_held_60d"]["A"].iloc[-1])
        assert not bool(frames["jump_faded_60d"]["A"].iloc[-1])

    def test_jump_given_back_counts_as_faded(self):
        frames = self._jump_then(after=102.0)

        assert bool(frames["jump_faded_60d"]["A"].iloc[-1])

    def test_turnaround_needs_deep_drawdown_then_fresh_reclaim_of_200_day_average(self):
        prices = np.r_[np.linspace(100, 30, 300), np.linspace(30, 60, 100)]
        close = pd.DataFrame({"A": prices}, index=_days(400))

        frames = factor_frames(close, close * 1e5)

        flagged = frames["turnaround"]["A"]
        assert flagged.iloc[300:].any()
        assert not flagged.iloc[:300].any()

    def test_shallow_dip_is_not_a_turnaround(self):
        prices = np.r_[np.linspace(100, 70, 300), np.linspace(70, 90, 100)]
        close = pd.DataFrame({"A": prices}, index=_days(400))

        frames = factor_frames(close, close * 1e5)

        assert not frames["turnaround"]["A"].any()


class TestListedBetween:

    def test_age_counts_trading_days_since_first_bar(self):
        close = pd.DataFrame({"OLD": 1.0, "NEW": [np.nan] * 300 + [1.0] * 100}, index=_days(400))

        result = listed_between(close, 0, 250)

        assert result["NEW"].iloc[-1] == 1.0
        assert result["OLD"].iloc[-1] == 0.0

    def test_age_bucket_unknown_while_cache_start_hides_the_listing_date(self):
        close = pd.DataFrame({"OLD": 1.0}, index=_days(400))

        result = listed_between(close, 250, 750)

        assert np.isnan(result["OLD"].iloc[-1])
        assert result["OLD"].iloc[100] != pytest.approx(1.0)


class TestBreakoutEvents:

    def _close(self, tail):
        base = list(np.linspace(100, 120, 260)) + [115.0] * 70
        return pd.DataFrame({"A": base + tail}, index=pd.bdate_range("2024-01-01", periods=len(base) + len(tail)))

    def test_first_52_week_high_after_a_quiet_spell_is_a_breakout(self):
        close = self._close([121.0])
        up = pd.DataFrame(False, index=close.index, columns=close.columns)

        events = breakout_events(close, up)

        assert events["high_breakout"]["A"].iloc[-1]

    def test_new_high_soon_after_another_is_not_fresh(self):
        close = self._close([121.0, 122.0])
        up = pd.DataFrame(False, index=close.index, columns=close.columns)

        events = breakout_events(close, up)

        assert not events["high_breakout"]["A"].iloc[-1]

    def test_jump_below_the_200_day_average_is_not_a_gap_breakout(self):
        close = pd.DataFrame({"A": list(np.linspace(200, 100, 260)) + [112.0]},
                             index=pd.bdate_range("2024-01-01", periods=261))
        up = pd.DataFrame(False, index=close.index, columns=close.columns)
        up.iloc[-1] = True

        events = breakout_events(close, up)

        assert not events["gap"]["A"].iloc[-1]


class TestMaRising:

    def test_steady_uptrend_has_all_averages_rising(self):
        close = pd.DataFrame({"A": np.linspace(50, 150, 260)}, index=pd.bdate_range("2024-01-01", periods=260))

        assert ma_rising(close, (8, 20, 50)).iloc[-1, 0]

    def test_a_short_pullback_turns_the_8_day_average_down(self):
        values = list(np.linspace(50, 150, 250)) + [150 - 4 * i for i in range(1, 11)]
        close = pd.DataFrame({"A": values}, index=pd.bdate_range("2024-01-01", periods=260))

        assert not ma_rising(close, (8, 20, 50)).iloc[-1, 0]


class TestBaseBuilding:

    def test_rising_short_averages_under_a_falling_200_day_count_as_a_base(self):
        values = list(np.linspace(200, 80, 300)) + list(np.linspace(80, 110, 60))
        close = pd.DataFrame({"A": values}, index=pd.bdate_range("2024-01-01", periods=len(values)))
        dollar_volume = close * 1e6

        frames = factor_frames(close, dollar_volume)

        assert frames["base_building"]["A"].iloc[-1]


class TestDaysSincePrevious:

    def test_counts_days_back_to_the_previous_flag(self):
        flags = pd.DataFrame({"A": [True, False, False, True, False]})

        result = days_since_previous(flags, cap=250)["A"].tolist()

        assert result == [250, 1, 2, 3, 1]
