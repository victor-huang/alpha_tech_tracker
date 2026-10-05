import math
from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import wave_risk_reward
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    WaveRiskRewardParams,
    add_moving_averages,
    analyze_bars,
    find_consolidation,
    is_reversion_box,
    ma_stack_regime,
    advance_bounce_setup,
    advance_pullback_setup,
    bounce_levels,
    bounce_risk_reward,
    new_bounce_setup,
    fib_level,
    new_pullback_setup,
    opening_drive_risk_reward,
    pullback_risk_reward,
    opening_drive_signal,
    opening_range_bias,
    needs_earnings_calendar,
    overnight_filter_ok,
    regime_allows,
    regular_hours,
    reversion_box_risk_reward,
    risk_reward,
    select_lookback_waves,
)
from alpha_tech_tracker.wave import Wave

MARKET_TZ = "America/New_York"
MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward"


def _timestamp(text):
    return pd.Timestamp(text, tz=MARKET_TZ)


def _wave(start, low, high, direction, length=1):
    """Finished wave spanning [low, high]; `length` bars from `start` at 5-min spacing."""
    bar_open, bar_close = (low, high) if direction == "up" else (high, low)
    start_ts = _timestamp(start)
    wave = Wave(start_ts, {"open": bar_open, "high": high, "low": low, "close": bar_close})
    for offset in range(1, length):
        wave.df.loc[start_ts + pd.Timedelta(minutes=5 * offset)] = wave.df.iloc[0]
    wave.num_high, wave.num_low = (3, 1) if direction == "up" else (1, 3)
    return wave


def _bars(start, closes, bar_range=0.0):
    index = pd.date_range(_timestamp(start), periods=len(closes), freq="5min")
    closes = pd.Series(closes, index=index)
    return pd.DataFrame(
        {"open": closes, "high": closes + bar_range / 2, "low": closes - bar_range / 2, "close": closes}
    )


def _params(**overrides):
    """Params with the regime switch off, so box mechanics are tested on their own."""
    return WaveRiskRewardParams(**dict({"regime_switch": "off"}, **overrides))


def _bars_with_mas(start, closes, mas):
    """`_bars` plus constant MA 8/20/50/200 columns, e.g. mas=(4, 3, 2, 1) for a trend-up stack."""
    bars = _bars(start, closes)
    for period, value in zip((8, 20, 50, 200), mas):
        bars[f"ma_{period}"] = value
    return bars


def _box(low, high, median_wave_size=1.0, start="2026-09-01 09:30", end="2026-09-01 10:00", bar_length=0.0):
    return {
        "bar_length": bar_length,
        "start": _timestamp(start),
        "end": _timestamp(end),
        "low": low,
        "high": high,
        "num_waves": 3,
        "median_wave_size": median_wave_size,
    }


class TestRegularHours:
    def test_drops_pre_and_after_market_bars(self):
        index = pd.DatetimeIndex(
            [_timestamp(t) for t in ("2026-09-01 09:25", "2026-09-01 09:30", "2026-09-01 15:55", "2026-09-01 16:00")]
        )
        raw = pd.DataFrame(
            {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 10}, index=index
        )

        frame = regular_hours(raw)

        assert list(frame.index) == [_timestamp("2026-09-01 09:30"), _timestamp("2026-09-01 15:55")]

    def test_keeps_lowercase_ohlc_columns_only(self):
        index = pd.DatetimeIndex([_timestamp("2026-09-01 09:30")])
        raw = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}, index=index)

        frame = regular_hours(raw)

        assert list(frame.columns) == ["open", "high", "low", "close"]


class TestAddMovingAverages:
    def test_moving_average_is_nan_until_period_is_filled(self):
        frame = add_moving_averages(_bars("2026-09-01 09:30", [float(i) for i in range(1, 9)]), periods=(8,))

        assert math.isnan(frame["ma_8"].iloc[6])
        assert frame["ma_8"].iloc[7] == pytest.approx(4.5)


class TestSelectLookbackWaves:
    def test_by_wave_count_returns_most_recent_oldest_first(self):
        waves = [_wave(f"2026-09-01 {9 + i}:30", 100, 101, "up") for i in range(5)]

        selected = select_lookback_waves(waves, lookback_waves=3)

        assert selected == waves[2:]

    def test_by_bar_count_covers_at_least_the_requested_bars(self):
        waves = [_wave(f"2026-09-01 {9 + i}:30", 100, 101, "up", length=4) for i in range(5)]

        selected = select_lookback_waves(waves, lookback_bars=10)

        assert selected == waves[2:]


class TestFindConsolidation:
    def _history(self):
        return [
            _wave("2026-09-01 09:30", 100.0, 104.0, "up"),
            _wave("2026-09-01 10:00", 101.0, 104.0, "down"),
            _wave("2026-09-01 10:30", 101.0, 102.0, "up"),
            _wave("2026-09-01 11:00", 101.2, 102.0, "down"),
            _wave("2026-09-01 11:30", 101.2, 101.9, "up"),
        ]

    def test_box_spans_trailing_run_of_small_waves(self):
        box = find_consolidation(self._history(), min_box_waves=3, small_wave_ratio=1.0, max_box_height_ratio=1.5)

        assert box["low"] == 101.0
        assert box["high"] == 102.0
        assert box["num_waves"] == 3
        assert box["start"] == _timestamp("2026-09-01 10:30")

    def test_box_records_average_bar_length_of_its_waves(self):
        waves = self._history()
        for wave in waves[-3:]:
            wave.df["high"] = wave.df["low"] + 0.4

        box = find_consolidation(waves, min_box_waves=3, small_wave_ratio=1.0, max_box_height_ratio=1.5)

        assert box["bar_length"] == pytest.approx(0.4)

    def test_no_box_when_small_wave_run_is_too_short(self):
        box = find_consolidation(self._history(), min_box_waves=4, small_wave_ratio=1.0, max_box_height_ratio=1.5)

        assert box is None

    def test_no_box_when_small_waves_drift_beyond_height_cap(self):
        drifting = [
            _wave("2026-09-01 09:30", 100.0, 101.0, "up"),
            _wave("2026-09-01 10:00", 101.0, 102.0, "up"),
            _wave("2026-09-01 10:30", 102.0, 103.0, "up"),
        ]

        box = find_consolidation(drifting, min_box_waves=3, small_wave_ratio=1.0, max_box_height_ratio=1.5)

        assert box is None


class TestRiskReward:
    def _waves(self):
        return [
            _wave("2026-09-01 09:30", 100.0, 102.0, "up"),
            _wave("2026-09-01 10:00", 99.0, 102.0, "down"),
            _wave("2026-09-01 10:30", 99.0, 103.0, "up"),
            _wave("2026-09-01 11:00", 100.5, 103.0, "down"),
        ]

    def test_long_stop_sits_box_stop_ratio_below_box_high(self):
        result = risk_reward("up", 102.0, self._waves(), _box(101.0, 102.0), min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(101.8)
        assert result["target"] == pytest.approx(105.0)
        assert result["rr"] == pytest.approx(15.0)

    def test_short_stop_sits_box_stop_ratio_above_box_low(self):
        result = risk_reward("down", 100.0, self._waves(), _box(100.0, 101.0), min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(100.2)
        assert result["target"] == pytest.approx(97.25)
        assert result["rr"] == pytest.approx(13.75)

    def test_box_stop_ratio_of_one_stops_at_opposite_box_edge(self):
        result = risk_reward(
            "up", 102.0, self._waves(), _box(101.0, 101.8), min_risk_pct=0.0, box_stop_ratio=1.0
        )

        assert result["stop"] == pytest.approx(101.0)

    def test_long_inside_box_below_stop_has_no_risk_reward(self):
        assert risk_reward("up", 101.5, self._waves(), _box(101.0, 102.0), min_risk_pct=0.0) is None

    def test_long_without_box_stops_at_latest_down_wave_low_below_entry(self):
        result = risk_reward("up", 101.0, self._waves(), None, min_risk_pct=0.0)

        assert result["stop"] == 100.5

    def test_long_without_box_skips_swing_lows_above_entry(self):
        result = risk_reward("up", 100.0, self._waves(), None, min_risk_pct=0.0)

        assert result["stop"] == 99.0

    def test_risk_is_floored_as_fraction_of_price(self):
        result = risk_reward("up", 101.0, self._waves(), _box(100.0, 101.25), min_risk_pct=0.001)

        assert result["risk"] == pytest.approx(0.101)

    def test_box_height_is_target_when_larger_than_median_wave(self):
        result = risk_reward("up", 104.5, self._waves(), _box(100.0, 104.0), min_risk_pct=0.0)

        assert result["target"] == pytest.approx(108.5)
        assert result["rr"] == pytest.approx(4.0 / 1.3)

    def test_none_without_waves_in_trade_direction(self):
        down_only = [wave for wave in self._waves() if wave.direction() == "down"]

        assert risk_reward("up", 101.0, down_only, _box(100.0, 101.8)) is None


class TestAnalyzeBars:
    def test_wave_in_progress_ends_at_session_close(self):
        bars = pd.concat([
            _bars("2026-09-01 15:45", [100.0, 101.0, 102.0]),
            _bars("2026-09-02 09:30", [103.0, 104.0]),
        ])

        result = analyze_bars(bars, _params())

        first, second = result["waves"]
        assert first.end == _timestamp("2026-09-01 15:55")
        assert first.next_wave is second
        assert second.start == _timestamp("2026-09-02 09:30")

    def test_wave_history_carries_across_sessions(self):
        bars = pd.concat([
            _bars("2026-09-01 15:45", [100.0, 101.0, 102.0]),
            _bars("2026-09-02 09:30", [103.0, 104.0]),
        ])

        result = analyze_bars(bars, _params())

        assert result["snapshots"]["lookback_waves"].iloc[-1] == 1

    def test_breakout_fires_once_when_close_clears_box_high(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-01 10:00", [100.5, 101.5, 101.8])

        result = analyze_bars(bars, _params())

        assert [(s["time"], s["signal"]) for s in result["signals"]] == [
            (_timestamp("2026-09-01 10:05"), "breakout")
        ]

    def test_breakdown_fires_when_close_drops_below_box_low(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-01 10:00", [100.5, 99.5])

        result = analyze_bars(bars, _params())

        assert result["signals"][0]["signal"] == "breakdown"
        assert result["signals"][0]["price"] == 99.5

    def test_box_retires_once_wave_in_progress_outgrows_small_wave_size(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=1.0))
        bars = _bars("2026-09-01 10:00", [100.5, 102.0, 99.0])

        result = analyze_bars(bars, _params(small_wave_ratio=1.0))

        assert [s["signal"] for s in result["signals"]] == ["breakout"]
        assert result["boxes"][0]["active_until"] == _timestamp("2026-09-01 10:05")

    def test_snapshot_records_risk_reward_per_bar(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        mocker.patch(f"{MODULE}.risk_reward", return_value={"stop": 100.0, "target": 103.0, "rr": 2.0})
        bars = _bars("2026-09-01 10:00", [100.5, 100.6])

        snapshots = analyze_bars(bars, _params())["snapshots"]

        assert list(snapshots["long_rr"]) == [2.0, 2.0]
        assert list(snapshots["box_low"]) == [100.0, 100.0]

    def test_custom_minimum_wave_price_change_reaches_every_wave(self, mocker):
        new_wave = mocker.spy(wave_risk_reward, "Wave")
        bars = pd.concat([
            _bars("2026-09-01 15:50", [100.0, 101.0]),
            _bars("2026-09-02 09:30", [103.0]),
        ])

        analyze_bars(bars, _params(minimum_wave_price_change=0.004))

        assert new_wave.call_count == 2
        assert all(c.kwargs["minimum_wave_price_change"] == 0.004 for c in new_wave.call_args_list)

    def test_wave_size_scales_with_average_bar_range(self, mocker):
        new_wave = mocker.spy(wave_risk_reward, "Wave")
        bars = _bars("2026-09-01 10:00", [100.0], bar_range=1.0)

        analyze_bars(bars, _params(min_wave_bar_ranges=2.0))

        assert new_wave.call_args.kwargs["minimum_wave_price_change"] == pytest.approx(0.02)

    def test_in_progress_wave_threshold_follows_latest_bar_range(self):
        bars = _bars("2026-09-01 10:00", [100.0, 100.0], bar_range=1.0)
        bars.iloc[1, bars.columns.get_loc("high")] = 101.5
        bars.iloc[1, bars.columns.get_loc("low")] = 98.5

        result = analyze_bars(bars, _params(min_wave_bar_ranges=2.0))

        assert result["waves"][-1].minimum_wave_price_change == pytest.approx(0.04)


class TestAnalyzeBarsSignalLabels:
    def test_breakout_on_session_open_from_prior_session_box_is_gap(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = pd.concat([
            _bars("2026-09-01 15:55", [100.5]),
            _bars("2026-09-02 09:30", [101.5]),
        ])

        signal = analyze_bars(bars, _params())["signals"][0]

        assert signal["signal"] == "breakout"
        assert signal["gap"] is True

    def test_breakout_later_in_session_is_not_gap(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-02 09:30", [100.5, 101.5])

        signal = analyze_bars(bars, _params())["signals"][0]

        assert signal["gap"] is False

    def test_snapshot_labels_gap_signal(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = pd.concat([
            _bars("2026-09-01 15:55", [100.5]),
            _bars("2026-09-02 09:30", [101.5]),
        ])

        snapshots = analyze_bars(bars, _params())["snapshots"]

        assert snapshots["signal"].iloc[-1] == "gap breakout"


class TestAnalyzeBarsRepeatSuppression:
    def _first_box(self):
        return _box(100.0, 101.0, median_wave_size=10.0)

    def _redrawn_box(self, high):
        return _box(100.2, high, median_wave_size=10.0, start="2026-09-02 09:45", end="2026-09-02 10:10")

    def test_same_direction_repeat_with_nearby_edge_is_suppressed(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._redrawn_box(101.4)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 101.6], bar_range=1.0)

        result = analyze_bars(bars, _params())

        assert [s["time"] for s in result["signals"]] == [_timestamp("2026-09-02 10:05")]
        assert [s["time"] for s in result["suppressed_signals"]] == [_timestamp("2026-09-02 10:10")]

    def test_same_direction_repeat_beyond_overlap_tolerance_fires(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._redrawn_box(102.5)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 103.0], bar_range=1.0)

        result = analyze_bars(bars, _params())

        assert len(result["signals"]) == 2
        assert result["suppressed_signals"] == []

    def test_repeat_fires_after_opposite_signal(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._first_box(), self._redrawn_box(101.4)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 99.5, 101.6], bar_range=1.0)

        result = analyze_bars(bars, _params())

        assert [s["signal"] for s in result["signals"]] == ["breakout", "breakdown", "breakout"]

    def test_repeat_in_next_session_fires(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._redrawn_box(101.4)],
        )
        bars = pd.concat([
            _bars("2026-09-01 15:50", [100.5, 101.5], bar_range=1.0),
            _bars("2026-09-02 10:15", [101.6], bar_range=1.0),
        ])

        result = analyze_bars(bars, _params())

        assert len(result["signals"]) == 2

    def test_overlap_tolerance_is_configurable(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._redrawn_box(101.4)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 101.6], bar_range=1.0)

        result = analyze_bars(bars, _params(repeat_overlap_bars=0.2))

        assert len(result["signals"]) == 2


class TestIsReversionBox:
    def test_box_at_least_n_bar_lengths_tall_is_reversion(self):
        assert is_reversion_box(_box(100.0, 103.0, bar_length=0.5), reversion_box_bars=6) is True

    def test_box_under_n_bar_lengths_tall_is_not_reversion(self):
        assert is_reversion_box(_box(100.0, 102.9, bar_length=0.5), reversion_box_bars=6) is False

    def test_zero_bar_length_is_not_reversion(self):
        assert is_reversion_box(_box(100.0, 103.0, bar_length=0.0), reversion_box_bars=6) is False


class TestReversionBoxRiskReward:
    def _wide_box(self):
        return _box(100.0, 103.0, bar_length=0.5)

    def _waves(self):
        return [_wave("2026-09-01 09:30", 100.0, 104.0, "up"), _wave("2026-09-01 10:00", 99.0, 102.0, "down")]

    def test_short_near_box_high_fades_to_box_low(self):
        result = reversion_box_risk_reward("down", 102.8, self._waves(), self._wide_box(), min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(103.5)
        assert result["target"] == pytest.approx(100.0)
        assert result["rr"] == pytest.approx(2.8 / 0.7)

    def test_long_near_box_low_fades_to_box_high(self):
        result = reversion_box_risk_reward("up", 100.2, self._waves(), self._wide_box(), min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(99.5)
        assert result["target"] == pytest.approx(103.0)

    def test_long_past_fade_stop_is_breakout_with_stop_at_box_high(self):
        result = reversion_box_risk_reward("up", 103.6, self._waves(), self._wide_box(), min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(103.0)
        assert result["target"] == pytest.approx(107.6)

    def test_short_past_fade_stop_is_breakdown_with_stop_at_box_low(self):
        result = reversion_box_risk_reward("down", 99.4, self._waves(), self._wide_box(), min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(100.0)
        assert result["target"] == pytest.approx(96.4)

    def test_long_fade_above_box_high_has_no_reward(self):
        assert reversion_box_risk_reward("up", 103.2, self._waves(), self._wide_box()) is None

    def test_short_fade_below_fade_stop_is_none(self):
        assert reversion_box_risk_reward("down", 103.6, self._waves(), self._wide_box()) is None


class TestAnalyzeBarsReversionBox:
    def _patch_wide_box(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            return_value=_box(100.0, 103.0, median_wave_size=1.0, bar_length=0.5),
        )

    def test_close_in_upper_edge_zone_fires_fade_short(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 102.7])

        signal = analyze_bars(bars, _params())["signals"][0]

        assert signal["signal"] == "fade_short"
        assert signal["risk_reward"]["stop"] == pytest.approx(103.5)
        assert signal["risk_reward"]["target"] == pytest.approx(100.0)

    def test_close_in_lower_edge_zone_fires_fade_long(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 100.3])

        assert analyze_bars(bars, _params())["signals"][0]["signal"] == "fade_long"

    def test_close_above_box_high_within_one_bar_is_not_a_breakout(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 103.3])

        assert [s["signal"] for s in analyze_bars(bars, _params())["signals"]] == ["fade_short"]

    def test_break_past_fade_stop_stops_and_reverses_into_breakout(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 102.7, 103.6])

        signals = analyze_bars(bars, _params(stop_and_reverse=True))["signals"]

        assert [s["signal"] for s in signals] == ["fade_short", "breakout"]
        assert signals[1]["reverses"] == "fade_short"
        assert signals[1]["risk_reward"]["stop"] == pytest.approx(103.0)

    def test_stop_and_reverse_is_skipped_by_default(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 102.7, 103.6])

        result = analyze_bars(bars, _params())

        assert [s["signal"] for s in result["signals"]] == ["fade_short"]
        assert [s["signal"] for s in result["reversal_skipped_signals"]] == ["breakout"]

    def test_skipped_stop_and_reverse_still_retires_wide_box(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 102.7, 103.6, 100.3])

        result = analyze_bars(bars, _params())

        assert [s["signal"] for s in result["signals"]] == ["fade_short"]
        assert result["boxes"][0]["active_until"] == _timestamp("2026-09-01 10:10")

    def test_breakout_without_prior_fade_fires_by_default(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 103.6])

        assert [s["signal"] for s in analyze_bars(bars, _params())["signals"]] == ["breakout"]

    def test_breakout_without_prior_fade_does_not_reverse(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 103.6])

        signal = analyze_bars(bars, _params())["signals"][0]

        assert signal["signal"] == "breakout"
        assert signal["reverses"] is None

    def test_wide_box_survives_large_wave_until_it_breaks(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [102.7, 100.3, 103.6, 103.0])

        result = analyze_bars(bars, _params(stop_and_reverse=True))

        assert [s["signal"] for s in result["signals"]] == ["fade_short", "fade_long", "breakout"]
        assert result["boxes"][0]["active_until"] == _timestamp("2026-09-01 10:10")

    def test_reversion_box_bars_threshold_is_configurable(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars("2026-09-01 10:00", [101.5, 103.3])

        signals = analyze_bars(bars, _params(reversion_box_bars=10))["signals"]

        assert [s["signal"] for s in signals] == ["breakout"]


class TestMaStackRegime:
    def test_fully_stacked_rising_mas_are_up(self):
        assert ma_stack_regime({"ma_8": 4.0, "ma_20": 3.0, "ma_50": 2.0, "ma_200": 1.0}) == "up"

    def test_fully_stacked_falling_mas_are_down(self):
        assert ma_stack_regime({"ma_8": 1.0, "ma_20": 2.0, "ma_50": 3.0, "ma_200": 4.0}) == "down"

    def test_tangled_mas_are_range(self):
        assert ma_stack_regime({"ma_8": 4.0, "ma_20": 2.0, "ma_50": 3.0, "ma_200": 1.0}) == "range"

    def test_unfilled_ma_is_range(self):
        assert ma_stack_regime({"ma_8": 4.0, "ma_20": 3.0, "ma_50": 2.0, "ma_200": float("nan")}) == "range"


class TestRegimeAllows:
    @pytest.mark.parametrize("regime, allowed", [
        ("up", {"breakout"}),
        ("down", {"breakdown"}),
        ("range", {"fade_long", "fade_short"}),
    ])
    def test_each_regime_allows_only_its_signals(self, regime, allowed):
        names = ("breakout", "breakdown", "fade_long", "fade_short")

        assert {name for name in names if regime_allows(name, regime)} == allowed


class TestAnalyzeBarsRegimeSwitch:
    TREND_UP = (4.0, 3.0, 2.0, 1.0)
    TREND_DOWN = (1.0, 2.0, 3.0, 4.0)
    RANGE = (4.0, 2.0, 3.0, 1.0)

    def _patch_narrow_box(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))

    def _patch_wide_box(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            return_value=_box(100.0, 103.0, median_wave_size=10.0, bar_length=0.5),
        )

    def test_trend_up_fires_breakout(self, mocker):
        self._patch_narrow_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [100.5, 101.5], self.TREND_UP)

        result = analyze_bars(bars)

        assert [s["signal"] for s in result["signals"]] == ["breakout"]
        assert result["signals"][0]["regime"] == "up"

    def test_trend_down_skips_breakout(self, mocker):
        self._patch_narrow_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [100.5, 101.5], self.TREND_DOWN)

        result = analyze_bars(bars)

        assert result["signals"] == []
        assert [s["signal"] for s in result["regime_skipped_signals"]] == ["breakout"]

    def test_range_skips_narrow_box_breakout(self, mocker):
        self._patch_narrow_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [100.5, 101.5], self.RANGE)

        assert analyze_bars(bars)["signals"] == []

    def test_range_fires_fade(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [101.5, 102.7], self.RANGE)

        assert [s["signal"] for s in analyze_bars(bars)["signals"]] == ["fade_short"]

    def test_trend_up_skips_fade(self, mocker):
        self._patch_wide_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [101.5, 102.7], self.TREND_UP)

        result = analyze_bars(bars)

        assert result["signals"] == []
        assert [s["signal"] for s in result["regime_skipped_signals"]] == ["fade_short"]

    def test_regime_switch_off_fires_every_signal(self, mocker):
        self._patch_narrow_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [100.5, 101.5], self.TREND_DOWN)

        signals = analyze_bars(bars, WaveRiskRewardParams(regime_switch="off"))["signals"]

        assert [s["signal"] for s in signals] == ["breakout"]

    def test_snapshot_records_regime(self, mocker):
        self._patch_narrow_box(mocker)
        bars = _bars_with_mas("2026-09-01 10:00", [100.5, 100.6], self.TREND_UP)

        snapshots = analyze_bars(bars)["snapshots"]

        assert list(snapshots["regime"]) == ["up", "up"]


class TestOpeningRangeBias:
    def test_close_below_opening_range_just_under_ma200_is_bearish(self):
        assert opening_range_bias(99.0, 101.0, 100.0, ma_200=99.5, avg_bar_range=0.2, max_ma200_distance_bars=10) == "bearish"

    def test_close_above_opening_range_just_over_ma200_is_bullish(self):
        assert opening_range_bias(102.0, 101.0, 100.0, ma_200=101.5, avg_bar_range=0.2, max_ma200_distance_bars=10) == "bullish"

    def test_close_inside_opening_range_has_no_bias(self):
        assert opening_range_bias(100.5, 101.0, 100.0, ma_200=101.5, avg_bar_range=0.2, max_ma200_distance_bars=10) is None

    def test_close_below_opening_range_but_above_ma200_has_no_bias(self):
        assert opening_range_bias(99.0, 101.0, 100.0, ma_200=98.0, avg_bar_range=0.2, max_ma200_distance_bars=10) is None

    def test_close_too_far_below_ma200_has_no_bias(self):
        assert opening_range_bias(97.0, 101.0, 100.0, ma_200=99.5, avg_bar_range=0.2, max_ma200_distance_bars=10) is None

    def test_unfilled_ma200_has_no_bias(self):
        assert opening_range_bias(99.0, 101.0, 100.0, ma_200=float("nan"), avg_bar_range=0.2, max_ma200_distance_bars=10) is None


class TestAnalyzeBarsOpeningRangeBias:
    """Opening range = first 3 bars at 100.5-101.0; later closes are tested against it."""

    RANGE_STACK = (4.0, 2.0, 3.0, 1.0)

    def _bars(self, later_closes, ma_200):
        closes = [100.5, 101.0, 100.6] + later_closes
        bars = _bars("2026-09-01 09:30", closes, bar_range=0.2)
        for period, value in zip((8, 20, 50), self.RANGE_STACK[:3]):
            bars[f"ma_{period}"] = value
        bars["ma_200"] = ma_200
        return bars

    def _params(self, **overrides):
        return WaveRiskRewardParams(**dict({"regime_switch": "opening-range"}, **overrides))

    def _patch_box(self, mocker, low, high, bar_length=0.2):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            return_value=_box(low, high, median_wave_size=10.0, bar_length=bar_length),
        )

    def test_bearish_bias_shorts_top_of_narrow_box(self, mocker):
        self._patch_box(mocker, 99.0, 99.6)
        bars = self._bars([99.5], ma_200=100.0)

        signals = analyze_bars(bars, self._params())["signals"]

        assert [(s["signal"], s["bias"]) for s in signals] == [("fade_short", "bearish")]
        assert signals[0]["risk_reward"]["stop"] == pytest.approx(99.8)
        assert signals[0]["risk_reward"]["target"] == pytest.approx(99.0)

    def test_bullish_bias_buys_bottom_of_box(self, mocker):
        self._patch_box(mocker, 101.4, 102.0)
        bars = self._bars([101.5], ma_200=101.2)

        signals = analyze_bars(bars, self._params())["signals"]

        assert [(s["signal"], s["bias"]) for s in signals] == [("fade_long", "bullish")]

    def test_bearish_bias_ignores_box_bottom(self, mocker):
        self._patch_box(mocker, 99.4, 100.4)
        bars = self._bars([99.45], ma_200=100.0)

        assert analyze_bars(bars, self._params())["signals"] == []

    def test_no_bias_during_opening_range_falls_back_to_ma_stack(self, mocker):
        self._patch_box(mocker, 99.0, 100.55, bar_length=0.0)
        bars = self._bars([], ma_200=101.0)

        result = analyze_bars(bars, self._params())

        assert result["signals"] == []
        assert [s["regime"] for s in result["regime_skipped_signals"]] == ["range"]

    def test_too_far_from_ma200_falls_back_to_ma_stack(self, mocker):
        self._patch_box(mocker, 99.0, 99.6)
        bars = self._bars([99.5], ma_200=100.0)

        last = analyze_bars(bars, self._params(max_ma200_distance_bars=1))["snapshots"].iloc[-1]

        assert last["bias"] is None
        assert last["regime"] == "range"

    def test_opening_range_bars_is_configurable(self, mocker):
        self._patch_box(mocker, 99.0, 99.6)
        bars = self._bars([99.5], ma_200=100.0)

        snapshots = analyze_bars(bars, self._params(opening_range_bars=4))["snapshots"]

        assert snapshots["or_low"].isna().all()
        assert snapshots["bias"].isna().all()

    def test_snapshot_records_opening_range_and_bias(self, mocker):
        self._patch_box(mocker, 99.0, 99.6)
        bars = self._bars([99.5], ma_200=100.0)

        last = analyze_bars(bars, self._params())["snapshots"].iloc[-1]

        assert (last["or_high"], last["or_low"]) == (pytest.approx(101.1), pytest.approx(100.4))
        assert last["bias"] == "bearish"
        assert last["regime"] == "or-bearish"


class TestOpeningDriveSignal:
    def test_green_first_bar_is_drive_long_with_stop_at_low(self):
        bar = {"open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0}

        assert opening_drive_signal(bar, "both") == ("drive_long", 99.5)

    def test_red_first_bar_is_drive_short_with_stop_at_high(self):
        bar = {"open": 100.0, "high": 100.5, "low": 98.5, "close": 99.0}

        assert opening_drive_signal(bar, "both") == ("drive_short", 100.5)

    def test_flat_first_bar_has_no_signal(self):
        bar = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0}

        assert opening_drive_signal(bar, "both") is None

    def test_long_mode_ignores_red_bar(self):
        bar = {"open": 100.0, "high": 100.5, "low": 98.5, "close": 99.0}

        assert opening_drive_signal(bar, "long") is None

    def test_short_mode_ignores_green_bar(self):
        bar = {"open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0}

        assert opening_drive_signal(bar, "short") is None


class TestOpeningDriveRiskReward:
    def _waves(self):
        return [
            _wave("2026-09-01 09:30", 100.0, 102.0, "up"),
            _wave("2026-09-01 10:00", 99.0, 102.0, "down"),
            _wave("2026-09-01 10:30", 99.0, 103.0, "up"),
        ]

    def test_long_targets_median_up_wave(self):
        result = opening_drive_risk_reward("up", 101.0, 100.0, self._waves(), min_risk_pct=0.0)

        assert result["target"] == pytest.approx(104.0)
        assert result["rr"] == pytest.approx(3.0)

    def test_short_targets_median_down_wave(self):
        result = opening_drive_risk_reward("down", 101.0, 102.0, self._waves(), min_risk_pct=0.0)

        assert result["target"] == pytest.approx(98.0)

    def test_none_without_waves_in_trade_direction(self):
        up_only = [wave for wave in self._waves() if wave.direction() == "up"]

        assert opening_drive_risk_reward("down", 101.0, 102.0, up_only) is None


class TestAnalyzeBarsOpeningDrive:
    RANGE_STACK = (4.0, 2.0, 3.0, 1.0)

    def _session(self, first_bar, start="2026-09-02 09:30"):
        bars = _bars_with_mas(start, [first_bar[3], first_bar[3]], self.RANGE_STACK)
        for column, value in zip(("open", "high", "low", "close"), first_bar):
            bars.iloc[0, bars.columns.get_loc(column)] = value
        return bars

    def test_off_by_default(self):
        bars = self._session((100.0, 101.5, 99.5, 101.0))

        assert analyze_bars(bars)["signals"] == []

    def test_green_first_bar_fires_drive_long_at_close(self):
        bars = self._session((100.0, 101.5, 99.5, 101.0))

        signals = analyze_bars(bars, WaveRiskRewardParams(opening_drive="both"))["signals"]

        assert [(s["signal"], s["time"], s["price"]) for s in signals] == [
            ("drive_long", _timestamp("2026-09-02 09:30"), 101.0)
        ]

    def test_fires_in_range_regime_despite_ma_stack_switch(self):
        bars = self._session((100.0, 101.5, 99.5, 101.0))

        result = analyze_bars(bars, WaveRiskRewardParams(opening_drive="both", regime_switch="ma-stack"))

        assert [s["signal"] for s in result["signals"]] == ["drive_long"]
        assert result["signals"][0]["regime"] == "range"

    def test_fires_once_per_session_on_first_bar_only(self):
        bars = pd.concat([
            self._session((100.0, 101.5, 99.5, 101.0), start="2026-09-01 15:50"),
            self._session((100.0, 100.5, 98.5, 99.0), start="2026-09-02 09:30"),
        ])

        signals = analyze_bars(bars, WaveRiskRewardParams(opening_drive="both"))["signals"]

        assert [(s["signal"], s["time"]) for s in signals] == [
            ("drive_long", _timestamp("2026-09-01 15:50")),
            ("drive_short", _timestamp("2026-09-02 09:30")),
        ]

    def test_snapshot_labels_drive_signal(self):
        bars = self._session((100.0, 101.5, 99.5, 101.0))

        snapshots = analyze_bars(bars, WaveRiskRewardParams(opening_drive="both"))["snapshots"]

        assert snapshots["signal"].iloc[0] == "drive long"


class TestAnalyzeBarsEarnings:
    WINDOWS = {"reaction": {date(2026, 9, 2)}, "eve": {date(2026, 9, 1)}}

    def _bars(self):
        sessions = TestAnalyzeBarsOpeningDrive()
        return pd.concat([
            sessions._session((100.0, 101.5, 99.5, 101.0), start="2026-09-01 15:50"),
            sessions._session((100.0, 100.5, 98.5, 99.0), start="2026-09-02 09:30"),
        ])

    def test_skip_drops_signals_on_the_reaction_session(self):
        result = analyze_bars(self._bars(), WaveRiskRewardParams(opening_drive="both", earnings="skip"), self.WINDOWS)

        assert [s["time"] for s in result["signals"]] == [_timestamp("2026-09-01 15:50")]
        assert [s["time"] for s in result["earnings_skipped_signals"]] == [_timestamp("2026-09-02 09:30")]

    def test_only_keeps_signals_on_the_reaction_session(self):
        result = analyze_bars(self._bars(), WaveRiskRewardParams(opening_drive="both", earnings="only"), self.WINDOWS)

        assert [s["time"] for s in result["signals"]] == [_timestamp("2026-09-02 09:30")]

    def test_off_ignores_the_windows(self):
        result = analyze_bars(self._bars(), WaveRiskRewardParams(opening_drive="both"), self.WINDOWS)

        assert len(result["signals"]) == 2
        assert result["earnings_skipped_signals"] == []

    def test_skip_without_windows_keeps_every_signal(self):
        result = analyze_bars(self._bars(), WaveRiskRewardParams(opening_drive="both", earnings="skip"))

        assert len(result["signals"]) == 2


class TestAnalyzeBarsOvernightEarnings:
    WINDOWS = {"reaction": {date(2026, 9, 2)}, "eve": {date(2026, 9, 1)}}

    def _bars(self):
        return pd.concat([
            _bars("2026-09-01 15:50", [100.0, 101.0]),
            _bars("2026-09-02 15:50", [102.0, 103.0]),
            _bars("2026-09-03 09:30", [104.0]),
        ])

    def test_skips_the_hold_into_a_release_by_default(self):
        result = analyze_bars(self._bars(), _params(overnight_hold="always"), self.WINDOWS)

        assert [s["time"] for s in result["signals"]] == [_timestamp("2026-09-02 15:55")]
        assert [s["time"] for s in result["earnings_skipped_signals"]] == [_timestamp("2026-09-01 15:55")]

    def test_holds_into_the_release_when_switched_off(self):
        params = _params(overnight_hold="always", overnight_skip_earnings=False)

        result = analyze_bars(self._bars(), params, self.WINDOWS)

        assert len(result["signals"]) == 2

    def test_earnings_only_overrides_the_default_skip(self):
        result = analyze_bars(self._bars(), _params(overnight_hold="always", earnings="only"), self.WINDOWS)

        assert [s["time"] for s in result["signals"]] == [_timestamp("2026-09-01 15:55")]


class TestNeedsEarningsCalendar:
    @pytest.mark.parametrize("overrides, expected", [
        ({}, False),
        ({"overnight_hold": "always"}, True),
        ({"overnight_hold": "always", "overnight_skip_earnings": False}, False),
        ({"earnings": "skip"}, True),
    ])
    def test_loads_the_calendar_only_when_used(self, overrides, expected):
        assert needs_earnings_calendar(WaveRiskRewardParams(**overrides)) is expected


def _up_setup():
    return {"direction": "up", "low": 100.0, "high": 110.0, "touched": False}


def _down_setup():
    return {"direction": "down", "low": 100.0, "high": 110.0, "touched": False}


class TestNewPullbackSetup:
    def _lookback(self, impulse_size):
        impulse = _wave("2026-09-01 11:00", 100.0, 100.0 + impulse_size, "up")
        small = [_wave(f"2026-09-01 {9 + i}:30", 100.0, 101.0, "down") for i in range(2)]
        return impulse, small + [impulse]

    def test_strong_up_wave_starts_setup(self):
        impulse, lookback = self._lookback(2.5)

        setup = new_pullback_setup(impulse, lookback, strong_wave_ratio=2.0, mode="both")

        assert (setup["direction"], setup["low"], setup["high"]) == ("up", 100.0, 102.5)

    def test_ordinary_wave_has_no_setup(self):
        impulse, lookback = self._lookback(1.5)

        assert new_pullback_setup(impulse, lookback, strong_wave_ratio=2.0, mode="both") is None

    def test_short_mode_ignores_up_impulse(self):
        impulse, lookback = self._lookback(2.5)

        assert new_pullback_setup(impulse, lookback, strong_wave_ratio=2.0, mode="short") is None

    def test_needs_two_other_waves_to_measure_strength(self):
        impulse, lookback = self._lookback(2.5)

        assert new_pullback_setup(impulse, lookback[1:], strong_wave_ratio=2.0, mode="both") is None


class TestFibLevel:
    def test_up_impulse_levels_measure_down_from_high(self):
        assert fib_level(_up_setup(), 0.5) == pytest.approx(105.0)
        assert fib_level(_up_setup(), 0.786) == pytest.approx(102.14)

    def test_down_impulse_levels_measure_up_from_low(self):
        assert fib_level(_down_setup(), 0.382) == pytest.approx(103.82)


class TestAdvancePullbackSetup:
    def test_no_signal_before_touching_382(self):
        setup = _up_setup()

        assert advance_pullback_setup(setup, {"open": 107.0, "high": 107.6, "low": 106.9, "close": 107.5}) is None

    def test_green_bar_after_touch_fires(self):
        setup = _up_setup()
        advance_pullback_setup(setup, {"open": 106.8, "high": 106.9, "low": 105.0, "close": 105.2})

        outcome = advance_pullback_setup(setup, {"open": 105.2, "high": 106.0, "low": 105.1, "close": 105.9})

        assert outcome == "fire"

    def test_touch_and_bounce_on_same_bar_fires(self):
        setup = _up_setup()

        assert advance_pullback_setup(setup, {"open": 105.5, "high": 106.4, "low": 105.0, "close": 106.2}) == "fire"

    def test_red_bar_after_touch_waits(self):
        setup = _up_setup()

        assert advance_pullback_setup(setup, {"open": 106.5, "high": 106.6, "low": 105.0, "close": 105.4}) is None
        assert setup["touched"] is True

    def test_green_bar_below_618_does_not_fire(self):
        setup = _up_setup()
        advance_pullback_setup(setup, {"open": 104.0, "high": 104.1, "low": 103.0, "close": 103.2})

        assert advance_pullback_setup(setup, {"open": 103.0, "high": 103.7, "low": 102.9, "close": 103.6}) is None

    def test_reaching_786_cancels(self):
        setup = _up_setup()

        assert advance_pullback_setup(setup, {"open": 104.0, "high": 104.1, "low": 102.0, "close": 103.0}) == "cancel"

    def test_close_above_impulse_high_cancels(self):
        setup = _up_setup()

        assert advance_pullback_setup(setup, {"open": 109.0, "high": 110.6, "low": 108.9, "close": 110.5}) == "cancel"

    def test_down_impulse_fires_on_red_bar_after_rally(self):
        setup = _down_setup()

        assert advance_pullback_setup(setup, {"open": 104.5, "high": 105.0, "low": 103.8, "close": 104.0}) == "fire"


class TestPullbackCustomLevels:
    def _setup(self, **levels):
        return dict(_up_setup(), **levels)

    def test_deeper_touch_level_waits_for_deeper_pullback(self):
        setup = self._setup(touch_fib=0.5)

        assert advance_pullback_setup(setup, {"open": 105.5, "high": 106.4, "low": 105.4, "close": 106.2}) is None
        assert setup["touched"] is False

    def test_wider_stop_survives_786(self):
        setup = self._setup(stop_fib=1.0)

        assert advance_pullback_setup(setup, {"open": 104.0, "high": 104.1, "low": 102.0, "close": 103.0}) is None

    def test_target_extension_beyond_impulse_high(self):
        result = pullback_risk_reward(self._setup(target_ext=1.272), 105.5, min_risk_pct=0.0)

        assert result["target"] == pytest.approx(112.72)

    def test_stop_at_impulse_start(self):
        result = pullback_risk_reward(self._setup(stop_fib=1.0), 105.5, min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(100.0)


class TestPullbackRiskReward:
    def test_long_stops_at_786_and_targets_impulse_high(self):
        result = pullback_risk_reward(_up_setup(), 105.5, min_risk_pct=0.0)

        assert result["stop"] == pytest.approx(102.14)
        assert result["target"] == 110.0
        assert result["rr"] == pytest.approx(4.5 / 3.36)

    def test_short_mirrors(self):
        result = pullback_risk_reward(_down_setup(), 104.5, min_risk_pct=0.0)

        assert (result["stop"], result["target"]) == (pytest.approx(107.86), 100.0)


class TestAnalyzeBarsWavePullback:
    """Ten rising bars make an up wave (100 -> 110); a 25% drop ends it; then the pullback."""

    def _bars(self, after_split):
        rising = [(c - 1.0, c + 0.2, c - 1.2, c) for c in [101.0 + i for i in range(10)]]
        split = [(110.0, 110.1, 107.3, 107.5)]
        index = pd.date_range(_timestamp("2026-09-01 10:00"), periods=11 + len(after_split), freq="5min")
        return pd.DataFrame(rising + split + after_split, columns=["open", "high", "low", "close"], index=index)

    def _patch_setup(self, mocker):
        return mocker.patch(f"{MODULE}.new_pullback_setup", side_effect=lambda *a: _up_setup())

    def test_off_by_default(self, mocker):
        setup = self._patch_setup(mocker)

        analyze_bars(self._bars([(106.2, 106.8, 106.0, 106.5)]))

        setup.assert_not_called()

    def test_bounce_after_strong_wave_fires_pullback_long(self, mocker):
        self._patch_setup(mocker)
        bars = self._bars([(106.2, 106.8, 106.0, 106.5)])

        signals = analyze_bars(bars, WaveRiskRewardParams(wave_pullback="both"))["signals"]

        assert [(s["signal"], s["time"], s["price"]) for s in signals] == [
            ("pullback_long", _timestamp("2026-09-01 10:55"), 106.5)
        ]
        assert signals[0]["risk_reward"]["target"] == 110.0

    def test_setup_expires_at_session_close(self, mocker):
        self._patch_setup(mocker)
        bars = pd.concat([
            self._bars([]),
            _bars("2026-09-02 09:30", [106.5]).assign(open=106.2, high=106.8, low=106.0),
        ])

        signals = analyze_bars(bars, WaveRiskRewardParams(wave_pullback="both"))["signals"]

        assert signals == []

    def test_strong_wave_ratio_reaches_setup(self, mocker):
        setup = self._patch_setup(mocker)

        analyze_bars(self._bars([]), WaveRiskRewardParams(wave_pullback="both", strong_wave_ratio=3.0))

        assert setup.call_args.args[2:4] == (3.0, "both")

    def test_pullback_levels_reach_setup(self, mocker):
        setup = self._patch_setup(mocker)
        params = WaveRiskRewardParams(wave_pullback="long", pullback_touch_fib=0.5, pullback_floor_fib=0.7,
                                      pullback_stop_fib=1.0, pullback_target_ext=1.272)

        analyze_bars(self._bars([]), params)

        assert setup.call_args.args[4:] == (0.5, 0.7, 1.0, 1.272)


class TestAnalyzeBarsSignalSwitches:
    def test_no_box_signals_keeps_boxes_but_fires_nothing(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-01 10:00", [100.5, 101.5])

        result = analyze_bars(bars, _params(box_signals=False))

        assert result["signals"] == []
        assert len(result["boxes"]) == 1

    def test_no_box_signals_keeps_opening_drive(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-02 09:30", [101.5, 101.6]).assign(open=[100.5, 101.5])

        signals = analyze_bars(bars, _params(box_signals=False, opening_drive="both"))["signals"]

        assert [s["signal"] for s in signals] == ["drive_long"]

    def test_no_gap_signals_skips_gap_breakout(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = pd.concat([
            _bars("2026-09-01 15:55", [100.5]),
            _bars("2026-09-02 09:30", [101.5]),
        ])

        result = analyze_bars(bars, _params(gap_signals=False))

        assert result["signals"] == []
        assert [s["signal"] for s in result["gap_skipped_signals"]] == ["breakout"]

    def test_no_gap_signals_keeps_in_session_breakout(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-02 09:30", [100.5, 101.5])

        signals = analyze_bars(bars, _params(gap_signals=False))["signals"]

        assert [s["signal"] for s in signals] == ["breakout"]


def _long_bounce():
    return {"side": "up", "low": 100.0, "high": 110.0, "target_fib": 0.5, "stop_buffer": 0.1}


class TestNewBounceSetup:
    def _lookback(self, wave_size, direction="down"):
        wave = _wave("2026-09-01 11:00", 100.0, 100.0 + wave_size, direction)
        small = [_wave(f"2026-09-01 {9 + i}:30", 100.0, 101.0, "up") for i in range(2)]
        return wave, small + [wave]

    def test_deep_down_wave_sets_up_long(self):
        wave, lookback = self._lookback(2.5)

        setup = new_bounce_setup(wave, lookback, deep_wave_ratio=2.0, mode="both")

        assert (setup["side"], setup["low"], setup["high"]) == ("up", 100.0, 102.5)

    def test_big_up_wave_sets_up_short(self):
        wave, lookback = self._lookback(2.5, direction="up")

        assert new_bounce_setup(wave, lookback, deep_wave_ratio=2.0, mode="both")["side"] == "down"

    def test_shallow_wave_has_no_setup(self):
        wave, lookback = self._lookback(1.5)

        assert new_bounce_setup(wave, lookback, deep_wave_ratio=2.0, mode="both") is None

    def test_long_mode_ignores_up_wave(self):
        wave, lookback = self._lookback(2.5, direction="up")

        assert new_bounce_setup(wave, lookback, deep_wave_ratio=2.0, mode="long") is None


class TestBounceLevels:
    def test_long_stop_below_low_and_target_half_way(self):
        assert bounce_levels(_long_bounce()) == (pytest.approx(99.0), pytest.approx(105.0))

    def test_short_mirrors(self):
        setup = dict(_long_bounce(), side="down")

        assert bounce_levels(setup) == (pytest.approx(111.0), pytest.approx(105.0))


class TestAdvanceBounceSetup:
    def test_green_bar_below_target_fires(self):
        assert advance_bounce_setup(_long_bounce(), {"open": 102.0, "high": 103.2, "low": 101.8, "close": 103.0}) == "fire"

    def test_red_bar_waits(self):
        assert advance_bounce_setup(_long_bounce(), {"open": 103.0, "high": 103.2, "low": 101.8, "close": 102.0}) is None

    def test_close_past_target_cancels(self):
        assert advance_bounce_setup(_long_bounce(), {"open": 104.0, "high": 105.5, "low": 103.8, "close": 105.2}) == "cancel"

    def test_stop_cancels(self):
        assert advance_bounce_setup(_long_bounce(), {"open": 101.0, "high": 101.2, "low": 98.9, "close": 100.5}) == "cancel"


class TestBounceRiskReward:
    def test_long_reward_to_target_over_risk_to_stop(self):
        result = bounce_risk_reward(_long_bounce(), 103.0, min_risk_pct=0.0)

        assert (result["stop"], result["target"]) == (pytest.approx(99.0), pytest.approx(105.0))
        assert result["rr"] == pytest.approx(2.0 / 4.0)


class TestAnalyzeBarsDeepBounce:
    """Ten falling bars make a down wave (110 -> 100); a 25% bounce ends it."""

    def _bars(self, after_split):
        falling = [(c + 1.0, c + 1.2, c - 0.2, c) for c in [109.0 - i for i in range(10)]]
        split = [(100.0, 102.7, 99.9, 102.5)]
        index = pd.date_range(_timestamp("2026-09-01 10:00"), periods=11 + len(after_split), freq="5min")
        return pd.DataFrame(falling + split + after_split, columns=["open", "high", "low", "close"], index=index)

    def _patch_setup(self, mocker):
        return mocker.patch(f"{MODULE}.new_bounce_setup", side_effect=lambda *a: _long_bounce())

    def test_off_by_default(self, mocker):
        setup = self._patch_setup(mocker)

        analyze_bars(self._bars([]))

        setup.assert_not_called()

    def test_split_bar_bounce_fires_bounce_long(self, mocker):
        self._patch_setup(mocker)

        signals = analyze_bars(self._bars([]), WaveRiskRewardParams(deep_bounce="long"))["signals"]

        assert [(s["signal"], s["time"], s["price"]) for s in signals] == [
            ("bounce_long", _timestamp("2026-09-01 10:50"), 102.5)
        ]
        assert signals[0]["risk_reward"]["target"] == pytest.approx(105.0)

    def test_settings_reach_setup(self, mocker):
        setup = self._patch_setup(mocker)
        params = WaveRiskRewardParams(deep_bounce="long", deep_wave_ratio=3.0, deep_bounce_target_fib=1.0,
                                      deep_bounce_stop_buffer=0.2)

        analyze_bars(self._bars([]), params)

        assert setup.call_args.args[2:] == (3.0, "long", 1.0, 0.2)


class TestOvernightFilterOk:
    def test_always_allows(self):
        assert overnight_filter_ok("always", [100.0]) is True

    def test_ma200_needs_close_above_daily_ma200(self):
        closes = [100.0] * 199 + [110.0]

        assert overnight_filter_ok("ma200", closes) is True

    def test_ma200_blocks_close_below_daily_ma200(self):
        closes = [100.0] * 199 + [90.0]

        assert overnight_filter_ok("ma200", closes) is False

    def test_ma200_blocks_without_200_sessions(self):
        assert overnight_filter_ok("ma200", [100.0] * 150 + [110.0]) is False

    def test_ma20_ma200_needs_both(self):
        closes = [100.0] * 180 + [120.0] * 19 + [110.0]

        assert overnight_filter_ok("ma20-ma200", closes) is False

    def test_ma50_rising(self):
        closes = [100.0 + i for i in range(60)]

        assert overnight_filter_ok("ma50-rising", closes) is True

    def test_ma50_falling_blocks(self):
        closes = [160.0 - i for i in range(60)]

        assert overnight_filter_ok("ma50-rising", closes) is False


class TestAnalyzeBarsOvernightHold:
    def _two_sessions(self):
        return pd.concat([
            _bars("2026-09-01 15:45", [100.0, 100.5, 101.0]),
            _bars("2026-09-02 09:30", [102.0]),
        ])

    def test_off_by_default(self):
        assert analyze_bars(self._two_sessions(), _params())["signals"] == []

    def test_buys_the_1555_close(self):
        signals = analyze_bars(self._two_sessions(), _params(overnight_hold="always"))["signals"]

        assert [(s["signal"], s["time"], s["price"]) for s in signals] == [
            ("overnight_long", _timestamp("2026-09-01 15:55"), 101.0)
        ]

    def test_ma200_filter_blocks_without_history(self):
        assert analyze_bars(self._two_sessions(), _params(overnight_hold="ma200"))["signals"] == []

    def test_daily_closes_feed_the_filter(self, mocker):
        allow = mocker.patch(f"{MODULE}.overnight_filter_ok", return_value=True)
        bars = pd.concat([self._two_sessions(), _bars("2026-09-02 15:55", [103.0])])

        analyze_bars(bars, _params(overnight_hold="ma200"))

        assert allow.call_args_list[-1].args == ("ma200", [101.0, 103.0])
