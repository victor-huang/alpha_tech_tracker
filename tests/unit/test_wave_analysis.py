"""
Unit tests for Wave analysis critical paths.

Tests the wave direction detection and statistical analysis that drives trading decisions.
These tests ensure wave metrics (up_waves_ratio, up_magnitude_ratio) are calculated correctly.

Coverage Target: Critical decision-making paths
"""

import pytest
import datetime
import pandas as pd
from alpha_tech_tracker.wave import Wave


class TestWaveCreation:
    """Test Wave initialization and basic properties."""

    def test_create_wave(self):
        """Wave should be created with start date and price data."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)

        assert wave.start == date
        assert wave.high == 105.0
        assert wave.low == 98.0
        assert wave.high_date == date
        assert wave.low_date == date
        assert wave.end is None

    def test_wave_defaults(self):
        """Wave should have sensible defaults."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)

        assert wave.num_high == 1
        assert wave.num_low == 1
        assert wave.maximum_wave_length == 78  # Trading day intervals
        assert wave.minimum_wave_length == 7


class TestWaveDirection:
    """Test wave direction determination - CRITICAL for trading decisions."""

    def test_direction_not_available_initially(self):
        """Direction should be 'n/a' when num_high + num_low < 3."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)
        # Initial: num_high=1, num_low=1, total=2 < 3

        assert wave.direction() == "n/a"

    def test_direction_up_wave(self):
        """Wave direction should be 'up' when num_high > num_low."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)
        wave.num_high = 5
        wave.num_low = 2

        assert wave.direction() == "up"

    def test_direction_down_wave(self):
        """Wave direction should be 'down' when num_low >= num_high."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)
        wave.num_high = 2
        wave.num_low = 5

        assert wave.direction() == "down"

    def test_direction_down_when_equal(self):
        """When num_high == num_low, direction should be 'down'."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)
        wave.num_high = 3
        wave.num_low = 3

        # When equal, it goes to else branch (down)
        assert wave.direction() == "down"


class TestWaveStatistics:
    """Test waves_stats() - CRITICAL method for trading decisions."""

    def test_single_up_wave_stats(self):
        """Should calculate correct stats for single up wave."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 110.0, "low": 100.0, "close": 108.0}

        wave = Wave(date, price_data)
        wave.num_high = 5
        wave.num_low = 2

        waves = [wave]
        stats = Wave.waves_stats(waves)

        # Only up waves, so ratio should be 1.0
        assert stats["up_waves_ratio"] == 1.0
        # Only up movement, so magnitude ratio should be 1.0
        assert stats["up_magnitude_ratio"] == 1.0
        assert stats["number_of_up_waves"] == 1
        assert stats["number_of_down_waves"] == 0

    def test_single_down_wave_stats(self):
        """Should calculate correct stats for single down wave."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 100.0, "low": 90.0, "close": 92.0}

        wave = Wave(date, price_data)
        wave.num_high = 2
        wave.num_low = 5

        waves = [wave]
        stats = Wave.waves_stats(waves)

        # Only down waves, so ratio should be 0.0
        assert stats["up_waves_ratio"] == 0.0
        # Only down movement, so magnitude ratio should be 0.0
        assert stats["up_magnitude_ratio"] == 0.0
        assert stats["number_of_up_waves"] == 0
        assert stats["number_of_down_waves"] == 1

    def test_mixed_waves_stats(self):
        """Should calculate correct ratios for mixed up/down waves."""
        # Up wave: 100 -> 110 (range = 10)
        date1 = datetime.date(2024, 1, 1)
        wave1 = Wave(
            date1, {"open": 100.0, "high": 110.0, "low": 100.0, "close": 108.0}
        )
        wave1.num_high = 5
        wave1.num_low = 2

        # Down wave: 110 -> 105 (range = 5)
        date2 = datetime.date(2024, 1, 2)
        wave2 = Wave(
            date2, {"open": 110.0, "high": 110.0, "low": 105.0, "close": 106.0}
        )
        wave2.num_high = 2
        wave2.num_low = 5

        waves = [wave1, wave2]
        stats = Wave.waves_stats(waves)

        # 1 up out of 2 total = 0.5
        assert stats["up_waves_ratio"] == 0.5
        # Up movement: 10, Down movement: 5, Total: 15
        # up_magnitude_ratio = 10 / 15 = 0.6667
        assert stats["up_magnitude_ratio"] == pytest.approx(0.6667, rel=0.01)
        assert stats["number_of_up_waves"] == 1
        assert stats["number_of_down_waves"] == 1

    def test_multiple_up_waves_stats(self):
        """Should handle multiple up waves correctly."""
        # Up wave 1: range = 10
        wave1 = Wave(
            datetime.date(2024, 1, 1),
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 108.0},
        )
        wave1.num_high = 5
        wave1.num_low = 2

        # Up wave 2: range = 15
        wave2 = Wave(
            datetime.date(2024, 1, 2),
            {"open": 110.0, "high": 125.0, "low": 110.0, "close": 123.0},
        )
        wave2.num_high = 6
        wave2.num_low = 2

        # Down wave: range = 5
        wave3 = Wave(
            datetime.date(2024, 1, 3),
            {"open": 125.0, "high": 125.0, "low": 120.0, "close": 121.0},
        )
        wave3.num_high = 2
        wave3.num_low = 5

        waves = [wave1, wave2, wave3]
        stats = Wave.waves_stats(waves)

        # 2 up out of 3 total = 0.6667
        assert stats["up_waves_ratio"] == pytest.approx(0.6667, rel=0.01)
        # Up: 10+15=25, Down: 5, Total: 30
        # up_magnitude_ratio = 25/30 = 0.8333
        assert stats["up_magnitude_ratio"] == pytest.approx(0.8333, rel=0.01)
        assert stats["number_of_up_waves"] == 2
        assert stats["number_of_down_waves"] == 1

    def test_waves_stats_buy_trigger_scenario(self):
        """Test scenario that should trigger buy signal (strategy criteria)."""
        # Simulate strong uptrend: 3 up waves, 1 down wave
        # Strategy buy trigger: up_waves_ratio >= 0.4, up_magnitude_ratio >= 0.51

        waves = []

        # Up wave 1: range = 20
        wave1 = Wave(
            datetime.date(2024, 1, 1),
            {"open": 100.0, "high": 120.0, "low": 100.0, "close": 118.0},
        )
        wave1.num_high = 6
        wave1.num_low = 2
        waves.append(wave1)

        # Up wave 2: range = 15
        wave2 = Wave(
            datetime.date(2024, 1, 2),
            {"open": 120.0, "high": 135.0, "low": 120.0, "close": 133.0},
        )
        wave2.num_high = 5
        wave2.num_low = 2
        waves.append(wave2)

        # Down wave: range = 5
        wave3 = Wave(
            datetime.date(2024, 1, 3),
            {"open": 135.0, "high": 135.0, "low": 130.0, "close": 131.0},
        )
        wave3.num_high = 2
        wave3.num_low = 5
        waves.append(wave3)

        # Up wave 3: range = 10
        wave4 = Wave(
            datetime.date(2024, 1, 4),
            {"open": 130.0, "high": 140.0, "low": 130.0, "close": 138.0},
        )
        wave4.num_high = 5
        wave4.num_low = 2
        waves.append(wave4)

        stats = Wave.waves_stats(waves)

        # 3 up out of 4 = 0.75 >= 0.4 ✓
        assert stats["up_waves_ratio"] >= 0.4
        # Up: 20+15+10=45, Down: 5, Total: 50
        # 45/50 = 0.9 >= 0.51 ✓
        assert stats["up_magnitude_ratio"] >= 0.51

        # This should trigger a buy signal
        assert stats["up_waves_ratio"] == 0.75
        assert stats["up_magnitude_ratio"] == 0.9

    def test_waves_stats_no_buy_trigger_scenario(self):
        """Test scenario that should NOT trigger buy (choppy market)."""
        # Simulate choppy market: equal up/down waves

        waves = []

        # Up wave: range = 10
        wave1 = Wave(
            datetime.date(2024, 1, 1),
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 108.0},
        )
        wave1.num_high = 5
        wave1.num_low = 2
        waves.append(wave1)

        # Down wave: range = 10
        wave2 = Wave(
            datetime.date(2024, 1, 2),
            {"open": 110.0, "high": 110.0, "low": 100.0, "close": 102.0},
        )
        wave2.num_high = 2
        wave2.num_low = 5
        waves.append(wave2)

        stats = Wave.waves_stats(waves)

        # 1 up out of 2 = 0.5 >= 0.4 ✓ (passes)
        # Up: 10, Down: 10, Total: 20
        # 10/20 = 0.5 < 0.51 ✗ (fails magnitude threshold)
        assert stats["up_waves_ratio"] == 0.5
        assert stats["up_magnitude_ratio"] == 0.5
        assert stats["up_magnitude_ratio"] < 0.51  # Should NOT trigger buy


class TestWaveMeasurements:
    """Test wave measurement methods."""

    def test_wave_length(self):
        """Wave length should match DataFrame length."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}

        wave = Wave(date, price_data)

        # Initial wave has 1 row
        assert wave.length() == 1

    def test_price_range(self):
        """Price range should be absolute difference between high and low."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0}

        wave = Wave(date, price_data)

        # Range: 110 - 95 = 15
        assert wave.price_range() == 15.0

    def test_price_range_zero(self):
        """Price range should handle zero range."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}

        wave = Wave(date, price_data)

        assert wave.price_range() == 0.0


class TestWaveSummary:
    """Test wave summary generation."""

    def test_wave_summary(self):
        """Should generate summary with key metrics."""
        date = datetime.date(2024, 1, 1)
        price_data = {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0}

        wave = Wave(date, price_data)
        wave.num_high = 5
        wave.num_low = 2

        summary = wave.summary()

        assert summary["start"] == "2024-01-01"
        assert summary["end"] is None  # Wave not ended
        assert summary["length"] == 1
        assert summary["price_range"] == 15.0
        assert summary["direction"] == "up"
        assert "movement_in_percentage" in summary


class TestWaveStatsEdgeCases:
    """Test edge cases in wave statistics."""

    def test_empty_waves_list(self):
        """Empty waves list should raise error (division by zero)."""
        with pytest.raises(ZeroDivisionError):
            Wave.waves_stats([])

    def test_strong_wave_indices_default(self):
        """Strong wave indices should default to -1 when no strong waves."""
        # Short waves that don't exceed threshold
        wave1 = Wave(
            datetime.date(2024, 1, 1),
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 108.0},
        )
        wave1.num_high = 5
        wave1.num_low = 2

        wave2 = Wave(
            datetime.date(2024, 1, 2),
            {"open": 110.0, "high": 110.0, "low": 105.0, "close": 106.0},
        )
        wave2.num_high = 2
        wave2.num_low = 5

        waves = [wave1, wave2]
        stats = Wave.waves_stats(waves)

        # No strong waves (length=1 < 60% of 78)
        assert stats["strong_up_wave_index"] == -1
        assert stats["strong_down_wave_index"] == -1

    def test_average_wave_length_calculation(self):
        """Should calculate average wave length correctly."""
        # Wave 1: length 1
        wave1 = Wave(
            datetime.date(2024, 1, 1),
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 108.0},
        )
        wave1.num_high = 5
        wave1.num_low = 2

        # Wave 2: length 1
        wave2 = Wave(
            datetime.date(2024, 1, 2),
            {"open": 110.0, "high": 120.0, "low": 110.0, "close": 118.0},
        )
        wave2.num_high = 5
        wave2.num_low = 2

        # Wave 3: Add extra rows to make length = 3
        wave3 = Wave(
            datetime.date(2024, 1, 3),
            {"open": 120.0, "high": 120.0, "low": 115.0, "close": 116.0},
        )
        wave3.num_high = 2
        wave3.num_low = 5
        wave3.df.loc[datetime.date(2024, 1, 4)] = {
            "open": 115.0,
            "high": 115.0,
            "low": 114.0,
            "close": 114.5,
        }
        wave3.df.loc[datetime.date(2024, 1, 5)] = {
            "open": 114.5,
            "high": 115.0,
            "low": 113.0,
            "close": 113.5,
        }

        waves = [wave1, wave2, wave3]
        stats = Wave.waves_stats(waves)

        # Average: (1 + 1 + 3) / 3 = 1.6667
        assert stats["average_wave_length"] == pytest.approx(1.6667, rel=0.01)


class TestYahooDataConversion:
    """Test Yahoo data format conversion."""

    def test_yahoo_data_to_data_dict(self):
        """Should convert Yahoo pandas series to data dict."""
        # Mock pandas series
        yahoo_series = pd.Series(
            {"Open": 100.0, "Close": 105.0, "High": 107.0, "Low": 99.0}
        )

        data_dict = Wave.yahoo_data_to_data_dict(yahoo_series)

        assert data_dict["open"] == 100.0
        assert data_dict["close"] == 105.0
        assert data_dict["high"] == 107.0
        assert data_dict["low"] == 99.0
