import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.price_factors import factor_frames, jump_days, listed_between


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
