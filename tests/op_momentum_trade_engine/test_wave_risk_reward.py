import math

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import wave_risk_reward
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    WaveRiskRewardParams,
    add_moving_averages,
    analyze_bars,
    find_consolidation,
    regular_hours,
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


def _box(low, high, median_wave_size=1.0, start="2026-09-01 09:30", end="2026-09-01 10:00"):
    return {
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

        result = analyze_bars(bars)

        first, second = result["waves"]
        assert first.end == _timestamp("2026-09-01 15:55")
        assert first.next_wave is second
        assert second.start == _timestamp("2026-09-02 09:30")

    def test_wave_history_carries_across_sessions(self):
        bars = pd.concat([
            _bars("2026-09-01 15:45", [100.0, 101.0, 102.0]),
            _bars("2026-09-02 09:30", [103.0, 104.0]),
        ])

        result = analyze_bars(bars)

        assert result["snapshots"]["lookback_waves"].iloc[-1] == 1

    def test_breakout_fires_once_when_close_clears_box_high(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-01 10:00", [100.5, 101.5, 101.8])

        result = analyze_bars(bars)

        assert [(s["time"], s["signal"]) for s in result["signals"]] == [
            (_timestamp("2026-09-01 10:05"), "breakout")
        ]

    def test_breakdown_fires_when_close_drops_below_box_low(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-01 10:00", [100.5, 99.5])

        result = analyze_bars(bars)

        assert result["signals"][0]["signal"] == "breakdown"
        assert result["signals"][0]["price"] == 99.5

    def test_box_retires_once_wave_in_progress_outgrows_small_wave_size(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=1.0))
        bars = _bars("2026-09-01 10:00", [100.5, 102.0, 99.0])

        result = analyze_bars(bars)

        assert [s["signal"] for s in result["signals"]] == ["breakout"]
        assert result["boxes"][0]["active_until"] == _timestamp("2026-09-01 10:05")

    def test_snapshot_records_risk_reward_per_bar(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        mocker.patch(f"{MODULE}.risk_reward", return_value={"stop": 100.0, "target": 103.0, "rr": 2.0})
        bars = _bars("2026-09-01 10:00", [100.5, 100.6])

        snapshots = analyze_bars(bars, WaveRiskRewardParams())["snapshots"]

        assert list(snapshots["long_rr"]) == [2.0, 2.0]
        assert list(snapshots["box_low"]) == [100.0, 100.0]

    def test_custom_minimum_wave_price_change_reaches_every_wave(self, mocker):
        new_wave = mocker.spy(wave_risk_reward, "Wave")
        bars = pd.concat([
            _bars("2026-09-01 15:50", [100.0, 101.0]),
            _bars("2026-09-02 09:30", [103.0]),
        ])

        analyze_bars(bars, WaveRiskRewardParams(minimum_wave_price_change=0.004))

        assert new_wave.call_count == 2
        assert all(c.kwargs["minimum_wave_price_change"] == 0.004 for c in new_wave.call_args_list)

    def test_wave_size_scales_with_average_bar_range(self, mocker):
        new_wave = mocker.spy(wave_risk_reward, "Wave")
        bars = _bars("2026-09-01 10:00", [100.0], bar_range=1.0)

        analyze_bars(bars, WaveRiskRewardParams(min_wave_bar_ranges=2.0))

        assert new_wave.call_args.kwargs["minimum_wave_price_change"] == pytest.approx(0.02)

    def test_in_progress_wave_threshold_follows_latest_bar_range(self):
        bars = _bars("2026-09-01 10:00", [100.0, 100.0], bar_range=1.0)
        bars.iloc[1, bars.columns.get_loc("high")] = 101.5
        bars.iloc[1, bars.columns.get_loc("low")] = 98.5

        result = analyze_bars(bars, WaveRiskRewardParams(min_wave_bar_ranges=2.0))

        assert result["waves"][-1].minimum_wave_price_change == pytest.approx(0.04)


class TestAnalyzeBarsSignalLabels:
    def test_breakout_on_session_open_from_prior_session_box_is_gap(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = pd.concat([
            _bars("2026-09-01 15:55", [100.5]),
            _bars("2026-09-02 09:30", [101.5]),
        ])

        signal = analyze_bars(bars)["signals"][0]

        assert signal["signal"] == "breakout"
        assert signal["gap"] is True

    def test_breakout_later_in_session_is_not_gap(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = _bars("2026-09-02 09:30", [100.5, 101.5])

        signal = analyze_bars(bars)["signals"][0]

        assert signal["gap"] is False

    def test_snapshot_labels_gap_signal(self, mocker):
        mocker.patch(f"{MODULE}.find_consolidation", return_value=_box(100.0, 101.0, median_wave_size=10.0))
        bars = pd.concat([
            _bars("2026-09-01 15:55", [100.5]),
            _bars("2026-09-02 09:30", [101.5]),
        ])

        snapshots = analyze_bars(bars)["snapshots"]

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

        result = analyze_bars(bars)

        assert [s["time"] for s in result["signals"]] == [_timestamp("2026-09-02 10:05")]
        assert [s["time"] for s in result["suppressed_signals"]] == [_timestamp("2026-09-02 10:10")]

    def test_same_direction_repeat_beyond_overlap_tolerance_fires(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._redrawn_box(102.5)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 103.0], bar_range=1.0)

        result = analyze_bars(bars)

        assert len(result["signals"]) == 2
        assert result["suppressed_signals"] == []

    def test_repeat_fires_after_opposite_signal(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._first_box(), self._redrawn_box(101.4)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 99.5, 101.6], bar_range=1.0)

        result = analyze_bars(bars)

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

        result = analyze_bars(bars)

        assert len(result["signals"]) == 2

    def test_overlap_tolerance_is_configurable(self, mocker):
        mocker.patch(
            f"{MODULE}.find_consolidation",
            side_effect=[self._first_box(), self._first_box(), self._redrawn_box(101.4)],
        )
        bars = _bars("2026-09-02 10:00", [100.5, 101.5, 101.6], bar_range=1.0)

        result = analyze_bars(bars, WaveRiskRewardParams(repeat_overlap_bars=0.2))

        assert len(result["signals"]) == 2
