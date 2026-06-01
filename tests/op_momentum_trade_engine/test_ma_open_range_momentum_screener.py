import io
import contextlib
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
import pytz

from datetime import time as dtime

from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _add_ma_columns,
    _add_daily_ma_columns,
    _compute_collection_vol_20day_avg,
    _compute_qqq_regime,
    _forward_pct,
    _get_prior_day_mas,
    _hold_label,
    _nanfloat,
    _print_backtest_table,
    _scan_ticker,
    _compute_qqq_context,
    compute_or_ma_signals,
    format_sms,
    run_range_analysis,
)

ET = pytz.timezone("America/New_York")
_TARGET_DATE = date(2026, 5, 29)
_OR_START = "09:30"
_OR_START_TIME = datetime.strptime(_OR_START, "%H:%M").time()


def _make_5min_bars(closes, highs=None, lows=None, volumes=None, start_offset_min=0,
                    target_date=_TARGET_DATE):
    """Build a 5-min bar DataFrame with MA columns pre-applied."""
    n = len(closes)
    base = ET.localize(datetime.combine(target_date, datetime.min.time()))
    timestamps = [
        base + timedelta(hours=9, minutes=30 + start_offset_min + i * 5)
        for i in range(n)
    ]
    highs = highs or [c + 1.0 for c in closes]
    lows = lows or [c - 1.0 for c in closes]
    volumes = volumes or [1_000_000] * n
    df = pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=timestamps,
    )
    return _add_ma_columns(df)


def _make_qqq_bars(closes, volumes=None, target_date=_TARGET_DATE):
    return _make_5min_bars(closes, volumes=volumes, target_date=target_date)


class TestAddMaColumns:
    def test_adds_price_ma_columns(self):
        df = _make_5min_bars([100.0] * 10)
        assert {"MA20", "MA50", "MA200"}.issubset(df.columns)

    def test_does_not_add_vol_ma_columns(self):
        df = _make_5min_bars([100.0] * 10)
        assert "VolMA20" not in df.columns
        assert "VolMA200" not in df.columns

    def test_ma20_equals_rolling_mean_of_close(self):
        closes = list(range(1, 26))
        df = _make_5min_bars(closes)
        expected_last = sum(closes[-20:]) / 20
        assert abs(df["MA20"].iloc[-1] - expected_last) < 1e-9

    def test_does_not_mutate_input(self):
        df = _make_5min_bars([100.0] * 5)
        original_cols = set(df.columns)
        _add_ma_columns(df)
        assert set(df.columns) == original_cols


class TestAddDailyMaColumns:
    def test_adds_daily_ma_columns(self):
        dates = [date(2026, 1, i + 1) for i in range(10)]
        df = pd.DataFrame({"Close": [100.0] * 10}, index=dates)
        result = _add_daily_ma_columns(df)
        assert {"DailyMA20", "DailyMA50", "DailyMA200"}.issubset(result.columns)

    def test_daily_ma20_uses_min_periods(self):
        dates = [date(2026, 1, i + 1) for i in range(5)]
        df = pd.DataFrame({"Close": [100.0, 102.0, 104.0, 106.0, 108.0]}, index=dates)
        result = _add_daily_ma_columns(df)
        assert not result["DailyMA20"].isna().any()


class TestGetPriorDayMas:
    def _make_daily_df(self, closes, start_date=date(2026, 5, 1)):
        dates = [start_date + timedelta(days=i) for i in range(len(closes))]
        df = pd.DataFrame({"Close": closes}, index=dates)
        return _add_daily_ma_columns(df)

    def test_returns_none_for_empty_df(self):
        result = _get_prior_day_mas(pd.DataFrame(), _TARGET_DATE)
        assert result == {"daily_ma20": None, "daily_ma50": None, "daily_ma200": None, "prev_close": None}

    def test_returns_last_row_before_target_date(self):
        daily_df = self._make_daily_df([100.0] * 30, start_date=date(2026, 4, 1))
        result = _get_prior_day_mas(daily_df, _TARGET_DATE)
        assert result["daily_ma20"] is not None

    def test_excludes_target_date_row(self):
        dates = [_TARGET_DATE - timedelta(days=1), _TARGET_DATE]
        df = pd.DataFrame({"Close": [100.0, 999.0]}, index=dates)
        df = _add_daily_ma_columns(df)
        result = _get_prior_day_mas(df, _TARGET_DATE)
        # The last row before target is the prior day with Close=100
        assert result["daily_ma20"] is not None
        assert result["daily_ma20"] != pytest.approx(999.0)

    def test_returns_none_when_no_prior_days(self):
        dates = [_TARGET_DATE]
        df = pd.DataFrame({"Close": [100.0]}, index=dates)
        df = _add_daily_ma_columns(df)
        result = _get_prior_day_mas(df, _TARGET_DATE)
        assert result["daily_ma20"] is None

    def test_returns_prev_close_of_last_day_before_target(self):
        dates = [_TARGET_DATE - timedelta(days=2), _TARGET_DATE - timedelta(days=1)]
        df = pd.DataFrame({"Close": [99.0, 105.0]}, index=dates)
        df = _add_daily_ma_columns(df)
        result = _get_prior_day_mas(df, _TARGET_DATE)
        assert result["prev_close"] == pytest.approx(105.0)

    def test_prev_close_is_none_for_empty_df(self):
        result = _get_prior_day_mas(pd.DataFrame(), _TARGET_DATE)
        assert result["prev_close"] is None


class TestNanfloat:
    def test_returns_float_for_valid_value(self):
        assert _nanfloat(3.14) == pytest.approx(3.14)

    def test_returns_none_for_nan(self):
        assert _nanfloat(float("nan")) is None

    def test_returns_none_for_none(self):
        assert _nanfloat(None) is None

    def test_returns_none_for_pd_na(self):
        assert _nanfloat(pd.NA) is None


class TestComputeCollectionVol20DayAvg:
    def _make_bars_two_days(self, yesterday_vols, today_vols):
        yesterday = _TARGET_DATE - timedelta(days=1)
        yesterday_df = _make_5min_bars(
            [100.0] * len(yesterday_vols), volumes=yesterday_vols, target_date=yesterday
        )
        today_df = _make_5min_bars(
            [100.0] * len(today_vols), volumes=today_vols, target_date=_TARGET_DATE
        )
        combined = pd.concat([
            yesterday_df[["Open", "High", "Low", "Close", "Volume"]],
            today_df[["Open", "High", "Low", "Close", "Volume"]],
        ])
        return _add_ma_columns(combined)

    def test_returns_mean_volume_of_collection_window_on_prior_days(self):
        # Yesterday: bars 0-9 (09:30-10:15). Collection window for 3-bar OR + 3 collection_bars
        # = bars at 09:40, 09:45, 09:50 (indices 2, 3, 4) on prior day.
        vols = [100_000] * 2 + [500_000, 600_000, 700_000] + [100_000] * 5
        df = self._make_bars_two_days(vols, [100_000] * 5)
        result = _compute_collection_vol_20day_avg(df, _OR_START_TIME, 3, 3, _TARGET_DATE)
        assert result == pytest.approx((500_000 + 600_000 + 700_000) / 3, rel=1e-3)

    def test_returns_none_when_no_prior_days(self):
        df = _make_5min_bars([100.0] * 5)
        result = _compute_collection_vol_20day_avg(df, _OR_START_TIME, 3, 3, _TARGET_DATE)
        assert result is None

    def test_uses_at_most_lookback_days(self):
        # Build 25 prior days; only the 20 most recent should be used
        frames = []
        for i in range(25):
            d = _TARGET_DATE - timedelta(days=i + 1)
            vol = 1_000_000 if i < 20 else 9_999_999  # older days have anomalous vol
            frames.append(_make_5min_bars([100.0] * 5, volumes=[vol] * 5, target_date=d))
        today = _make_5min_bars([100.0] * 5, target_date=_TARGET_DATE)
        combined = pd.concat(
            [f[["Open", "High", "Low", "Close", "Volume"]] for f in frames + [today]]
        )
        result = _compute_collection_vol_20day_avg(
            _add_ma_columns(combined), _OR_START_TIME, 3, 3, _TARGET_DATE, lookback_days=20
        )
        assert result == pytest.approx(1_000_000, rel=0.01)


class TestComputeQqqContext:
    def _make_two_day_qqq(self, warmup_vols, today_vols, today_date=_TARGET_DATE):
        """Build a QQQ bar series spanning two days with MA columns applied to the combined DF."""
        yesterday = today_date - timedelta(days=1)
        warmup_df = _make_5min_bars(
            [400.0] * len(warmup_vols), volumes=warmup_vols, target_date=yesterday
        )
        today_df = _make_5min_bars(
            [400.0] * len(today_vols), volumes=today_vols, target_date=today_date
        )
        combined = pd.concat([warmup_df[["Open", "High", "Low", "Close", "Volume"]],
                               today_df[["Open", "High", "Low", "Close", "Volume"]]])
        return _add_ma_columns(combined)

    def _make_multi_day_qqq(self, prior_vols_per_day, today_vols, target_date=_TARGET_DATE):
        """
        Build a QQQ bar series where each prior day has `prior_vols_per_day` bars
        and today has `today_vols` bars — all on distinct calendar dates.
        Each day has bars_per_day 5-min bars starting at 09:30.
        """
        frames = []
        n_prior = len(prior_vols_per_day)
        for i, vols in enumerate(prior_vols_per_day):
            d = target_date - timedelta(days=n_prior - i)
            frames.append(_make_5min_bars([400.0] * len(vols), volumes=vols, target_date=d))
        frames.append(_make_5min_bars([400.0] * len(today_vols), volumes=today_vols,
                                      target_date=target_date))
        combined = pd.concat([f[["Open", "High", "Low", "Close", "Volume"]] for f in frames])
        return _add_ma_columns(combined)

    def test_vol_ratio_above_1_when_today_collection_vol_exceeds_20day_avg(self):
        # 20 prior days: collection bars (indices 2,3,4 = 09:40,09:45,09:50) at 500K.
        # Today: collection bars at 1M. Ratio = 1M / 500K = 2.0.
        prior = [[500_000] * 5] * 20
        today = [500_000, 500_000, 1_000_000, 1_000_000, 1_000_000]
        df = self._make_multi_day_qqq(prior, today)
        result = _compute_qqq_context(df, _TARGET_DATE, _OR_START_TIME, 3, collection_bars=3)
        assert result["qqq_vol_ratio"] is not None
        assert result["qqq_vol_ratio"] > 1.0

    def test_vol_ratio_below_1_when_today_collection_vol_below_20day_avg(self):
        # 20 prior days: collection bars at 1M. Today: collection bars at 100K. Ratio < 1.
        prior = [[1_000_000] * 5] * 20
        today = [1_000_000, 1_000_000, 100_000, 100_000, 100_000]
        df = self._make_multi_day_qqq(prior, today)
        result = _compute_qqq_context(df, _TARGET_DATE, _OR_START_TIME, 3, collection_bars=3)
        assert result["qqq_vol_ratio"] is not None
        assert result["qqq_vol_ratio"] < 1.0

    def test_vol_ratio_is_none_for_empty_df(self):
        result = _compute_qqq_context(pd.DataFrame(), _TARGET_DATE, _OR_START_TIME, 3)
        assert result["qqq_vol_ratio"] is None

    def test_vol_ratio_is_none_when_no_or_start_time_provided(self):
        df = self._make_two_day_qqq([500_000] * 200, [500_000, 500_000, 500_000])
        result = _compute_qqq_context(df, _TARGET_DATE)
        assert result["qqq_vol_ratio"] is None

    def test_context_includes_qqq_regime_key(self):
        prior = [[500_000] * 5] * 20
        today = [500_000, 500_000, 500_000]
        df = self._make_multi_day_qqq(prior, today)
        result = _compute_qqq_context(df, _TARGET_DATE, _OR_START_TIME, 3)
        assert "qqq_regime" in result


class TestComputeQqqRegime:
    def _make_qqq_with_close_vs_mas(self, warmup_close, today_closes, target_date=_TARGET_DATE):
        """
        Build a QQQ bar series where warmup bars establish the MA baseline and
        today_closes are the bars on target_date starting at 09:30.
        All bars use the given close as both Open/High/Low/Close.
        """
        yesterday = target_date - timedelta(days=1)
        warmup_df = _make_5min_bars([warmup_close] * 250, target_date=yesterday)
        today_df = _make_5min_bars(today_closes, target_date=target_date)
        combined = pd.concat([
            warmup_df[["Open", "High", "Low", "Close", "Volume"]],
            today_df[["Open", "High", "Low", "Close", "Volume"]],
        ])
        return _add_ma_columns(combined)

    def test_very_bullish_when_close_above_all_mas(self):
        # Warmup at 100 → MA20/50/200 ≈ 100. Today close = 120 > all MAs.
        df = self._make_qqq_with_close_vs_mas(100.0, [120.0, 120.0, 120.0])
        result = _compute_qqq_regime(df, _TARGET_DATE, _OR_START_TIME, 3)
        assert result == "Very Bullish"

    def test_bullish_when_close_above_ma200_but_below_ma20_and_ma50(self):
        # Warmup at 120 → MA20/50/200 ≈ 120. Today close = 110 — below MA20/50 but
        # still above MA200 (which lags and stays near 120 after 250 warmup bars).
        # To reliably get close above MA200 but below MA20/MA50, use a recent dip:
        # warmup at 100 for 248 bars, then spike to 130 for 2 bars (today bars 1-2),
        # then dip back to 80 at bar 3. MA200 ≈ 100, MA20 ≈ raised slightly, close=80.
        # That gives close < MA200 too. Let me instead use:
        # warmup at 50 (250 bars) → MA200 ≈ 50. Today bars go to 80.
        # MA20 would have been updating... let's be direct:
        # 250 warmup bars at 50 → MA200=50, MA50=50, MA20=50.
        # Today's 3 bars at 80: MA20 starts updating but still ~50+something,
        # MA50 and MA200 still ~50. close=80 > MA200(~50) AND > MA20 AND > MA50 → Very Bullish.
        # For a clean Bullish test: warmup at 120 for 250 bars, today drop to 100.
        # MA200 ≈ 120 (very slow to move), MA50 ≈ 120, MA20 ≈ 119 (updated slightly by 3 bars).
        # close=100 < MA20(~119) AND < MA50(~120) BUT < MA200(~120) too → Bearish, not Bullish.
        # This is tricky because with stable warmup, MA200 ≈ MA50 ≈ MA20 ≈ warmup_close.
        # To get close > MA200 but < MA20: need MA200 low and MA20 high.
        # Use warmup at 100 for 200 bars then 130 for 50 bars → MA200 ≈ 107, MA20 ≈ 130, MA50 ≈ 115.
        # Today close = 115: > MA200(107) but < MA20(130) and < MA50(115) → Bullish!
        yesterday = _TARGET_DATE - timedelta(days=1)
        warmup_low = [100.0] * 200
        warmup_high = [130.0] * 50
        all_warmup = warmup_low + warmup_high
        warmup_df = _make_5min_bars(all_warmup, target_date=yesterday)
        today_df = _make_5min_bars([115.0, 115.0, 115.0], target_date=_TARGET_DATE)
        combined = pd.concat([
            warmup_df[["Open", "High", "Low", "Close", "Volume"]],
            today_df[["Open", "High", "Low", "Close", "Volume"]],
        ])
        df = _add_ma_columns(combined)
        result = _compute_qqq_regime(df, _TARGET_DATE, _OR_START_TIME, 3)
        assert result == "Bullish"

    def test_bearish_when_close_below_all_mas_and_no_prev_bar_for_slope(self):
        # or_bars=1: only one OR bar, no previous bar to compare → slope check skipped.
        # close=80 < all MAs (~120) → Bearish, not Very Bearish.
        df = self._make_qqq_with_close_vs_mas(120.0, [80.0])
        result = _compute_qqq_regime(df, _TARGET_DATE, _OR_START_TIME, 1)
        assert result == "Bearish"

    def test_very_bearish_when_close_below_all_mas_and_mas_sloping_down(self):
        # Build a long declining series so MA20 and MA50 are both sloping down at OR close.
        # Use 250 bars of a downtrend: starts at 120, drops 0.1 per bar.
        yesterday = _TARGET_DATE - timedelta(days=1)
        warmup_closes = [120.0 - i * 0.1 for i in range(250)]
        warmup_df = _make_5min_bars(warmup_closes, target_date=yesterday)
        # Today: 3 bars continuing the drop, far below all MAs.
        today_df = _make_5min_bars([90.0, 89.0, 88.0], target_date=_TARGET_DATE)
        combined = pd.concat([
            warmup_df[["Open", "High", "Low", "Close", "Volume"]],
            today_df[["Open", "High", "Low", "Close", "Volume"]],
        ])
        df = _add_ma_columns(combined)
        result = _compute_qqq_regime(df, _TARGET_DATE, _OR_START_TIME, 3)
        assert result == "Very Bearish"

    def test_returns_none_for_empty_df(self):
        result = _compute_qqq_regime(pd.DataFrame(), _TARGET_DATE, _OR_START_TIME, 3)
        assert result is None

    def test_returns_none_when_insufficient_or_bars(self):
        df = self._make_qqq_with_close_vs_mas(100.0, [120.0])
        # or_bars=3 but only 1 bar on target date → None
        result = _compute_qqq_regime(df, _TARGET_DATE, _OR_START_TIME, 3)
        assert result is None


class TestScanTicker:
    def _make_bull_setup(self):
        """
        Bull setup: MA20 inside OR range, close above OR mid, high OR vol.
        OR bars: closes 98, 100, 102 → OR_High=103, OR_Low=97, OR_mid=100.
        Post-OR bar: close=101 (above mid=100), MA20 ≈ inside OR range,
        or_vol > vol_ma200.
        """
        # Build 250 warmup bars (needed for MA200 and VolMA200)
        warmup_closes = [100.0] * 247
        warmup_vols = [500_000] * 247

        # 3 OR bars: OR_High=103, OR_Low=97, OR_mid=100.
        # 3rd bar close = 100 = OR_mid → bull requires close > mid (strict), so 09:40 doesn't fire.
        or_closes = [98.0, 100.0, 100.0]
        or_highs = [99.0, 101.0, 103.0]
        or_lows = [97.0, 99.0, 97.0]
        or_vols = [2_000_000, 2_000_000, 2_000_000]  # well above warmup avg

        # post-OR bar at 09:45: close = 101 > OR_mid (100) → fires here
        post_closes = [101.0]
        post_vols = [2_000_000]

        all_closes = warmup_closes + or_closes + post_closes
        all_highs = [c + 1.0 for c in warmup_closes] + or_highs + [102.0]
        all_lows = [c - 1.0 for c in warmup_closes] + or_lows + [100.0]
        all_vols = warmup_vols + or_vols + post_vols

        base = ET.localize(datetime.combine(_TARGET_DATE, datetime.min.time()))
        # Warmup bars: day before target, starting 09:30
        yesterday = _TARGET_DATE - timedelta(days=1)
        warmup_ts = [
            ET.localize(datetime.combine(yesterday, datetime.min.time()))
            + timedelta(hours=9, minutes=30 + i * 5)
            for i in range(247)
        ]
        or_ts = [
            base + timedelta(hours=9, minutes=30 + i * 5)
            for i in range(3)
        ]
        post_ts = [base + timedelta(hours=9, minutes=45)]

        timestamps = warmup_ts + or_ts + post_ts
        df = pd.DataFrame(
            {
                "Open": all_closes,
                "High": all_highs,
                "Low": all_lows,
                "Close": all_closes,
                "Volume": all_vols,
            },
            index=timestamps,
        )
        return _add_ma_columns(df)

    def test_bull_signal_fires_when_all_conditions_met(self):
        df = self._make_bull_setup()
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": 1.5}, None, collection_bars=3,
        )
        assert result is not None
        assert result["direction"] == "BULL"
        assert result["ticker"] == "TSLA"

    def test_bull_signal_includes_overlapping_mas(self):
        df = self._make_bull_setup()
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": 1.5}, None, collection_bars=3,
        )
        assert result is not None
        assert len(result["overlapping_mas"]) > 0

    def test_no_signal_when_no_bars_for_date(self):
        df = _make_5min_bars([100.0] * 5, target_date=date(2026, 1, 1))
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": None}, None, collection_bars=3,
        )
        assert result is None

    def test_no_signal_when_insufficient_or_bars(self):
        df = _make_5min_bars([100.0] * 2)
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": None}, None, collection_bars=3,
        )
        assert result is None

    def test_no_signal_when_or_range_is_zero(self):
        df = _make_5min_bars(
            [100.0] * 10,
            highs=[100.0] * 10,
            lows=[100.0] * 10,
        )
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": None}, None, collection_bars=3,
        )
        assert result is None

    def test_no_signal_when_no_ma_inside_or_range(self):
        closes = [205.0] * 5
        highs = [210.0, 210.0, 210.0, 210.0, 210.0]
        lows = [200.0, 200.0, 200.0, 200.0, 200.0]
        df = _make_5min_bars(closes, highs=highs, lows=lows)
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": None}, None, collection_bars=3,
        )
        assert result is None

    def test_bear_no_signal_when_close_above_ma20(self):
        # Build a bear-like setup but with close above MA20 → should be suppressed.
        yesterday = _TARGET_DATE - timedelta(days=1)
        # Warmup at high price (110) → MA20/MA200 ≈ 110
        warmup_closes = [110.0] * 247
        warmup_vols = [2_000_000] * 247  # high historical vol so today's low vol is bear

        # OR bars: high=111, low=97 → OR_High=111, OR_Low=97, OR_mid=104
        or_closes = [105.0, 103.0, 103.0]  # 3rd bar close = 103 < mid (104) ✓
        or_highs = [106.0, 104.0, 111.0]
        or_lows = [104.0, 102.0, 97.0]
        or_vols = [100_000, 100_000, 100_000]  # low vol (bear vol condition ✓)

        # Post-OR bar: close stays below mid but ABOVE MA20 (~110) — MA gate blocks bear
        post_closes = [103.0]  # close < mid (✓) but close (103) < MA20 (≈110) — wait, 103 < 110 means close IS below MA20
        # Actually I need close >= MA20 to BLOCK bear. Let me use close = 111 (above MA20).
        # But then close > or_mid, which would be bull territory...
        # Let me redesign: warmup at 100, OR mid = 104, close at 103 (below mid), MA20 ≈ 100.
        # To block bear: close (103) >= MA20 (100). That means close > MA20, so MA gate blocks.
        # Warmup at 100 → MA20 ≈ 100. close = 103 >= MA20 (100) → bear blocked ✓

        warmup_closes = [100.0] * 247
        warmup_vols = [2_000_000] * 247

        all_closes = warmup_closes + or_closes + post_closes
        all_highs = [c + 1.0 for c in warmup_closes] + or_highs + [104.0]
        all_lows = [c - 1.0 for c in warmup_closes] + or_lows + [102.0]
        all_vols = warmup_vols + or_vols + [100_000]

        warmup_ts = [
            ET.localize(datetime.combine(yesterday, datetime.min.time()))
            + timedelta(hours=9, minutes=30 + i * 5)
            for i in range(247)
        ]
        base = ET.localize(datetime.combine(_TARGET_DATE, datetime.min.time()))
        or_ts = [base + timedelta(hours=9, minutes=30 + i * 5) for i in range(3)]
        post_ts = [base + timedelta(hours=9, minutes=45)]

        df = pd.DataFrame(
            {"Open": all_closes, "High": all_highs, "Low": all_lows,
             "Close": all_closes, "Volume": all_vols},
            index=warmup_ts + or_ts + post_ts,
        )
        df = _add_ma_columns(df)
        # MA20 at post-OR bar ≈ 100 (warmup dominates). close = 103 >= MA20 → bear blocked.
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": None}, None, collection_bars=3,
        )
        assert result is None

    def test_no_signal_on_empty_dataframe(self):
        result = _scan_ticker(
            "TSLA", pd.DataFrame(), _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": None}, None, collection_bars=3,
        )
        assert result is None

    def test_signal_latches_on_first_qualifying_bar(self):
        df = self._make_bull_setup()
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": 1.5}, None, collection_bars=3,
        )
        assert result is not None
        # OR close bar (09:40) sits at midpoint so it doesn't fire; first fire is at 09:45.
        assert result["signal_bar_time"] == "09:45"

    def test_no_signal_when_qualifying_bar_is_outside_collection_window(self):
        df = self._make_bull_setup()
        # Signal fires at 09:45 (2nd collection bar). With collection_bars=1 (only 09:40
        # is evaluated), the signal should be suppressed.
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": 1.5}, None, collection_bars=1,
        )
        assert result is None

    def test_signal_fires_when_within_extended_collection_window(self):
        df = self._make_bull_setup()
        # With collection_bars=3, the scan covers bars at 09:40, 09:45, 09:50 — signal fires.
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": 1.5}, None, collection_bars=3,
        )
        assert result is not None

    def test_signal_dict_has_required_keys(self):
        df = self._make_bull_setup()
        result = _scan_ticker(
            "TSLA", df, _OR_START_TIME, 3, _TARGET_DATE,
            {"qqq_vol_ratio": 1.5}, None, collection_bars=3,
        )
        assert result is not None
        required = {
            "ticker", "direction", "signal_bar_time",
            "or_high", "or_low", "or_mid", "or_range",
            "close", "overlapping_mas",
            "ma20_5m", "ma50_5m", "ma200_5m",
            "collection_vol", "vol_20day_avg",
            "daily_ma20", "daily_ma50", "daily_ma200",
            "prev_close",
            "qqq_vol_ratio", "date",
        }
        assert required.issubset(result.keys())


class TestComputeOrMaSignals:
    def test_returns_list(self):
        result = compute_or_ma_signals({}, pd.DataFrame(), _OR_START, 3, _TARGET_DATE)
        assert isinstance(result, list)

    def test_skips_qqq_ticker_in_bars_5m(self):
        qqq_df = _make_5min_bars([400.0] * 5)
        result = compute_or_ma_signals(
            {"QQQ": qqq_df}, pd.DataFrame(), _OR_START, 3, _TARGET_DATE
        )
        assert result == []

    def test_returns_signal_for_qualifying_ticker(self):
        fake_signal = {"ticker": "TSLA", "direction": "BULL"}
        _module = "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener"
        with patch(f"{_module}._scan_ticker", return_value=fake_signal):
            df = _make_5min_bars([100.0] * 5)
            result = compute_or_ma_signals(
                {"TSLA": df}, pd.DataFrame(), _OR_START, 3, _TARGET_DATE
            )
        assert result == [fake_signal]

    def test_excludes_none_results(self):
        _module = "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener"
        with patch(f"{_module}._scan_ticker", return_value=None):
            df = _make_5min_bars([100.0] * 5)
            result = compute_or_ma_signals(
                {"TSLA": df}, pd.DataFrame(), _OR_START, 3, _TARGET_DATE
            )
        assert result == []


class TestFormatSms:
    def _make_bull_signal(self):
        return {
            "ticker": "TSLA",
            "direction": "BULL",
            "signal_bar_time": "09:45",
            "or_high": 345.20,
            "or_low": 342.10,
            "or_mid": 343.65,
            "or_range": 3.10,
            "close": 344.50,
            "overlapping_mas": ["MA20"],
            "ma20_5m": 343.80,
            "ma50_5m": 341.00,
            "ma200_5m": 338.50,
            "collection_vol": 1_250_000,
            "vol_20day_avg": 850_000,
            "daily_ma20": 340.00,
            "daily_ma50": 335.00,
            "daily_ma200": 310.00,
            "qqq_vol_ratio": 1.5,
            "date": "2026-05-29",
        }

    def _make_bear_signal(self):
        sig = self._make_bull_signal()
        sig["direction"] = "BEAR"
        sig["close"] = 342.00
        sig["collection_vol"] = 500_000
        sig["vol_20day_avg"] = 850_000
        return sig

    def test_bull_sms_contains_direction_and_ticker(self):
        sms = format_sms(self._make_bull_signal())
        assert "BULL SIGNAL: TSLA" in sms

    def test_bull_sms_contains_or_range(self):
        sms = format_sms(self._make_bull_signal())
        assert "342.10-345.20" in sms

    def test_bull_sms_contains_ma_in_or(self):
        sms = format_sms(self._make_bull_signal())
        assert "MA20 in OR" in sms

    def test_bull_sms_contains_20day_avg_ratio(self):
        sms = format_sms(self._make_bull_signal())
        assert "20dAvg" in sms

    def test_bear_sms_contains_20day_avg_ratio(self):
        sms = format_sms(self._make_bear_signal())
        assert "20dAvg" in sms

    def test_multiple_overlapping_mas_joined_with_slash(self):
        sig = self._make_bull_signal()
        sig["overlapping_mas"] = ["MA20", "MA50"]
        sms = format_sms(sig)
        assert "MA20/MA50 in OR" in sms


class TestSignalSorting:
    def _make_signal(self, ticker, close, prev_close, ma_names, collection_vol,
                     vol_20day_avg=1_000_000):
        return {
            "ticker": ticker,
            "direction": "BULL",
            "signal_bar_time": "09:45",
            "or_high": close + 1.0,
            "or_low": close - 2.0,
            "or_mid": close - 0.5,
            "or_range": 3.0,
            "close": close,
            "overlapping_mas": ma_names,
            "ma20_5m": close,
            "ma50_5m": close,
            "ma200_5m": close,
            "collection_vol": collection_vol,
            "vol_20day_avg": vol_20day_avg,
            "daily_ma20": None,
            "daily_ma50": None,
            "daily_ma200": None,
            "prev_close": prev_close,
            "qqq_vol_ratio": 1.5,
            "date": str(_TARGET_DATE),
        }

    def _table_ticker_order(self, signals):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_backtest_table(
                signals, [s["ticker"] for s in signals],
                {}, _OR_START, 3, _TARGET_DATE, print_all=False, collection_bars=3,
            )
        parts = [l.split() for l in buf.getvalue().splitlines() if l]
        return [p[0] for p in parts if len(p) > 1 and p[1] in ("BULL", "BEAR")]

    def test_sorts_by_up_pct_descending(self):
        # A: +5%, B: +2%, C: -1% — expected order A, B, C
        signals = [
            self._make_signal("C", 99.0, 100.0, ["MA20"], 1_000_000),
            self._make_signal("A", 105.0, 100.0, ["MA20"], 1_000_000),
            self._make_signal("B", 102.0, 100.0, ["MA20"], 1_000_000),
        ]
        order = self._table_ticker_order(signals)
        assert order == ["A", "B", "C"]

    def test_sorts_by_ma_count_when_up_pct_equal(self):
        # Same up% (+2%), A has 2 MAs, B has 1 MA — expected order A, B
        signals = [
            self._make_signal("B", 102.0, 100.0, ["MA20"], 1_000_000),
            self._make_signal("A", 102.0, 100.0, ["MA20", "MA50"], 1_000_000),
        ]
        order = self._table_ticker_order(signals)
        assert order == ["A", "B"]

    def test_sorts_by_vol_ratio_when_up_pct_and_ma_count_equal(self):
        # Same up% and MA count, A has 2x vol, B has 1x vol — expected order A, B
        signals = [
            self._make_signal("B", 102.0, 100.0, ["MA20"], 1_000_000, vol_20day_avg=1_000_000),
            self._make_signal("A", 102.0, 100.0, ["MA20"], 2_000_000, vol_20day_avg=1_000_000),
        ]
        order = self._table_ticker_order(signals)
        assert order == ["A", "B"]

    def test_up_pct_displayed_in_table(self):
        signals = [self._make_signal("TSLA", 105.0, 100.0, ["MA20"], 1_000_000)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_backtest_table(
                signals, ["TSLA"], {}, _OR_START, 3, _TARGET_DATE,
                print_all=False, collection_bars=3,
            )
        assert "+5.00%" in buf.getvalue()

    def test_negative_up_pct_displayed(self):
        signals = [self._make_signal("TSLA", 95.0, 100.0, ["MA20"], 1_000_000)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_backtest_table(
                signals, ["TSLA"], {}, _OR_START, 3, _TARGET_DATE,
                print_all=False, collection_bars=3,
            )
        assert "-5.00%" in buf.getvalue()

    def test_up_pct_shown_as_question_mark_when_no_prev_close(self):
        sig = self._make_signal("TSLA", 105.0, None, ["MA20"], 1_000_000)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_backtest_table(
                [sig], ["TSLA"], {}, _OR_START, 3, _TARGET_DATE,
                print_all=False, collection_bars=3,
            )
        output = buf.getvalue()
        tsla_line = next(l for l in output.splitlines() if l.startswith("TSLA"))
        assert "?" in tsla_line


class TestHoldLabel:
    def test_minutes_under_60(self):
        assert _hold_label(15) == "+15m"
        assert _hold_label(30) == "+30m"
        assert _hold_label(45) == "+45m"

    def test_exact_hours(self):
        assert _hold_label(60) == "+1h"
        assert _hold_label(120) == "+2h"
        assert _hold_label(180) == "+3h"
        assert _hold_label(360) == "+6h"
        assert _hold_label(420) == "+7h"

    def test_mixed_hours_and_minutes(self):
        assert _hold_label(90) == "+1h30m"

    def test_eod_sentinel(self):
        assert _hold_label(None) == "EOD"


class TestForwardPct:
    def _make_day_bars(self, times_and_closes, target_date=_TARGET_DATE):
        timestamps = [
            ET.localize(datetime.combine(target_date, t))
            for t, _ in times_and_closes
        ]
        closes = [c for _, c in times_and_closes]
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes,
             "Close": closes, "Volume": [100_000] * len(closes)},
            index=timestamps,
        )
        return df

    def test_returns_pct_change_at_hold_minutes(self):
        # Entry 09:45 close=100, exit 10:00 close=102 → +2%
        bars = [
            (dtime(9, 45), 100.0),
            (dtime(9, 50), 101.0),
            (dtime(9, 55), 101.5),
            (dtime(10, 0), 102.0),
        ]
        df = self._make_day_bars(bars)
        result = _forward_pct(df, dtime(9, 45), _TARGET_DATE, 15)
        assert result == pytest.approx(2.0)

    def test_negative_pct_when_price_drops(self):
        bars = [
            (dtime(9, 45), 100.0),
            (dtime(10, 0), 98.0),
        ]
        df = self._make_day_bars(bars)
        result = _forward_pct(df, dtime(9, 45), _TARGET_DATE, 15)
        assert result == pytest.approx(-2.0)

    def test_eod_uses_last_bar(self):
        # Entry 09:45 close=100, last bar 15:55 close=105 → +5%
        bars = [
            (dtime(9, 45), 100.0),
            (dtime(10, 0), 102.0),
            (dtime(15, 55), 105.0),
        ]
        df = self._make_day_bars(bars)
        result = _forward_pct(df, dtime(9, 45), _TARGET_DATE, None)
        assert result == pytest.approx(5.0)

    def test_falls_back_to_last_bar_when_exit_past_close(self):
        # +420 min from 09:45 = 16:45, past market close — falls back to last bar
        bars = [
            (dtime(9, 45), 100.0),
            (dtime(15, 55), 103.0),
        ]
        df = self._make_day_bars(bars)
        result = _forward_pct(df, dtime(9, 45), _TARGET_DATE, 420)
        assert result == pytest.approx(3.0)

    def test_returns_none_when_signal_bar_not_found(self):
        bars = [(dtime(9, 50), 100.0)]
        df = self._make_day_bars(bars)
        result = _forward_pct(df, dtime(9, 45), _TARGET_DATE, 15)
        assert result is None

    def test_returns_none_for_empty_df(self):
        result = _forward_pct(pd.DataFrame(), dtime(9, 45), _TARGET_DATE, 15)
        assert result is None

    def test_zero_pct_when_price_unchanged(self):
        bars = [
            (dtime(9, 45), 100.0),
            (dtime(10, 0), 100.0),
        ]
        df = self._make_day_bars(bars)
        result = _forward_pct(df, dtime(9, 45), _TARGET_DATE, 15)
        assert result == pytest.approx(0.0)


class TestRangeAnalysis:
    _MODULE = "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener"

    def _make_full_day_bars(self, target_date, signal_close, forward_close):
        """
        Build a full trading day of 5-min bars where:
        - Bars before 09:45 close at signal_close - 1 (OR bars)
        - 09:45 bar closes at signal_close (signal fires here)
        - All later bars close at forward_close
        Includes 20 identical prior days at signal_close for vol_20day_avg baseline.
        """
        signal_time = dtime(9, 45)
        frames = []
        for days_back in range(1, 22):
            d = target_date - timedelta(days=days_back)
            bars = []
            t = datetime.combine(d, dtime(9, 30))
            while t.time() <= dtime(15, 55):
                bars.append((t.time(), signal_close))
                t += timedelta(minutes=5)
            ts = [ET.localize(datetime.combine(d, bt)) for bt, _ in bars]
            closes = [c for _, c in bars]
            frames.append(pd.DataFrame(
                {"Open": closes, "High": closes, "Low": closes,
                 "Close": closes, "Volume": [1_000_000] * len(closes)},
                index=ts,
            ))
        # Today
        today_bars = []
        t = datetime.combine(target_date, dtime(9, 30))
        while t.time() <= dtime(15, 55):
            if t.time() == signal_time:
                close = signal_close
            elif t.time() > signal_time:
                close = forward_close
            else:
                close = signal_close - 1.0
            today_bars.append(close)
            t += timedelta(minutes=5)
        n = len(today_bars)
        ts_today = [
            ET.localize(datetime.combine(target_date, dtime(9, 30)) + timedelta(minutes=5 * i))
            for i in range(n)
        ]
        frames.append(pd.DataFrame(
            {"Open": today_bars, "High": today_bars, "Low": today_bars,
             "Close": today_bars, "Volume": [3_000_000] * n},
            index=ts_today,
        ))
        combined = pd.concat(frames)
        return _add_ma_columns(combined)

    def _bull_signal(self, ticker, date_str, vol_ratio):
        close = 100.0
        avg = 1_000_000
        return {
            "ticker": ticker,
            "direction": "BULL",
            "signal_bar_time": "09:45",
            "or_high": 102.0,
            "or_low": 98.0,
            "or_mid": 100.0,
            "or_range": 4.0,
            "close": close,
            "overlapping_mas": ["MA20"],
            "ma20_5m": 100.0,
            "ma50_5m": 99.0,
            "ma200_5m": 95.0,
            "collection_vol": int(avg * vol_ratio),
            "vol_20day_avg": avg,
            "daily_ma20": None,
            "daily_ma50": None,
            "daily_ma200": None,
            "prev_close": 98.0,
            "qqq_vol_ratio": 1.2,
            "qqq_regime": "Very Bullish",
            "date": date_str,
        }

    def test_qualifying_signal_appears_in_output(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        bull_sig = self._bull_signal("TSLA", str(target), vol_ratio=2.5)

        with patch(f"{self._MODULE}.fetch_bars", return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars", return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals", return_value=[bull_sig]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=["TSLA"], min_vol_ratio=2.0,
                )
        assert "TSLA" in buf.getvalue()

    def test_signal_below_min_vol_ratio_excluded(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        low_vol_sig = self._bull_signal("TSLA", str(target), vol_ratio=1.5)

        with patch(f"{self._MODULE}.fetch_bars", return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars", return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals", return_value=[low_vol_sig]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=["TSLA"], min_vol_ratio=2.0,
                )
        assert "No qualifying" in buf.getvalue()

    def test_bear_signal_excluded(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=98.0)
        bear_sig = self._bull_signal("TSLA", str(target), vol_ratio=3.0)
        bear_sig["direction"] = "BEAR"

        with patch(f"{self._MODULE}.fetch_bars", return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars", return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals", return_value=[bear_sig]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=["TSLA"], min_vol_ratio=2.0,
                )
        assert "No qualifying" in buf.getvalue()

    def test_summary_shows_all_hold_windows(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        bull_sig = self._bull_signal("TSLA", str(target), vol_ratio=2.5)

        with patch(f"{self._MODULE}.fetch_bars", return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars", return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals", return_value=[bull_sig]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=["TSLA"], min_vol_ratio=2.0,
                )
        output = buf.getvalue()
        for label in ["+15m", "+30m", "+1h", "+2h", "+3h", "+6h", "+7h", "EOD"]:
            assert label in output
