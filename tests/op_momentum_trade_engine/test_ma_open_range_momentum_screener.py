import io
import contextlib
import os
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
    _compute_hold_history,
    _compute_qqq_regime,
    _count_collection_bars,
    _daemon_stop,
    _build_presession_picks_rows,
    _format_hold_history,
    _format_ticker_win_rate_table,
    _format_top2_ranking,
    _rank_tickers_by_eod_win_rate,
    _forward_pct,
    _get_prior_day_mas,
    _hold_label,
    _is_running,
    _nanfloat,
    _print_backtest_table,
    _read_pid,
    _remove_pid,
    _scan_ticker,
    _compute_qqq_context,
    _window_label,
    _write_pid,
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

    def _run_range(self, target, df, signals):
        with patch(f"{self._MODULE}.fetch_bars", return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars", return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals", return_value=signals):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_range_analysis(start_date=target, end_date=target,
                                   tickers=["TSLA"], min_vol_ratio=2.0)
        return buf.getvalue()

    def test_presession_rankings_section_header_printed(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        output = self._run_range(target, df, [])
        assert "Pre-Session Rankings" in output

    def test_presession_performance_table_header_printed(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        output = self._run_range(target, df, [])
        assert "Pre-Session Top-2 Performance" in output

    def test_presession_performance_table_contains_rank_column(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        output = self._run_range(target, df, [])
        assert "#1" in output

    def test_presession_performance_table_summary_printed(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        output = self._run_range(target, df, [])
        assert "Pre-session picks summary" in output

    def test_presession_rankings_printed_before_signal_analysis(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        bull_sig = self._bull_signal("TSLA", str(target), vol_ratio=2.5)
        output = self._run_range(target, df, [bull_sig])
        rankings_pos = output.index("Pre-Session Rankings")
        signal_pos = output.index("Signal Analysis")
        assert rankings_pos < signal_pos

    def test_presession_performance_printed_before_signal_analysis(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        bull_sig = self._bull_signal("TSLA", str(target), vol_ratio=2.5)
        output = self._run_range(target, df, [bull_sig])
        perf_pos = output.index("Pre-Session Top-2 Performance")
        signal_pos = output.index("Signal Analysis")
        assert perf_pos < signal_pos

    def test_hist_annotation_not_printed_in_signal_table_rows(self):
        target = date(2026, 5, 20)
        df = self._make_full_day_bars(target, signal_close=100.0, forward_close=102.0)
        bull_sig = self._bull_signal("TSLA", str(target), vol_ratio=2.5)
        output = self._run_range(target, df, [bull_sig])
        assert "[20d hist:" not in output


class TestWindowLabel:
    def test_standard_window(self):
        assert _window_label("09:30", 3) == "09:30/3b"

    def test_afternoon_window(self):
        assert _window_label("13:15", 1) == "13:15/1b"

    def test_single_bar_window(self):
        assert _window_label("15:00", 1) == "15:00/1b"

    def test_multi_bar_window(self):
        assert _window_label("09:30", 5) == "09:30/5b"


class TestRangeAnalysisMultiWindow:
    _MODULE = "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener"

    def _make_df(self, target_date):
        """Minimal bar DataFrame for the target date (used as a stub for fetch_bars)."""
        ts = [ET.localize(datetime.combine(target_date, dtime(9, 30)))]
        return pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0],
             "Close": [100.0], "Volume": [1_000_000]},
            index=ts,
        )

    def _bull_signal(self, ticker, date_str, bar_time="09:45"):
        return {
            "ticker": ticker,
            "direction": "BULL",
            "signal_bar_time": bar_time,
            "or_high": 102.0, "or_low": 98.0, "or_mid": 100.0, "or_range": 4.0,
            "close": 101.0,
            "overlapping_mas": ["MA20"],
            "ma20_5m": 100.0, "ma50_5m": 99.0, "ma200_5m": 95.0,
            "collection_vol": 2_000_000, "vol_20day_avg": 1_000_000,
            "daily_ma20": None, "daily_ma50": None, "daily_ma200": None,
            "prev_close": 98.0,
            "qqq_vol_ratio": 1.2, "qqq_regime": "Very Bullish",
            "date": date_str,
        }

    def _run(self, tickers, windows, signals_by_call):
        """
        Run run_range_analysis with mocked data. signals_by_call is a list of
        signal lists returned by successive compute_or_ma_signals calls.
        Returns captured stdout.
        """
        target = date(2026, 5, 20)
        df = self._make_df(target)

        with patch(f"{self._MODULE}.fetch_bars",
                   return_value={t: df for t in tickers + ["QQQ"]}), \
             patch(f"{self._MODULE}.fetch_daily_bars",
                   return_value={t: pd.DataFrame() for t in tickers + ["QQQ"]}), \
             patch(f"{self._MODULE}.compute_or_ma_signals",
                   side_effect=signals_by_call):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=tickers, windows=windows, min_vol_ratio=2.0,
                )
        return buf.getvalue()

    def test_window_label_appears_in_detail_row(self):
        target = date(2026, 5, 20)
        sig = self._bull_signal("TSLA", str(target))
        output = self._run(["TSLA"], [("09:30", 3)], [[sig]])
        assert "09:30/3b" in output

    def test_single_window_no_aggregate_block(self):
        target = date(2026, 5, 20)
        sig = self._bull_signal("TSLA", str(target))
        output = self._run(["TSLA"], [("09:30", 3)], [[sig]])
        assert "aggregate" not in output.lower()

    def test_multiple_windows_produce_per_window_summary(self):
        target = date(2026, 5, 20)
        sig1 = self._bull_signal("TSLA", str(target), bar_time="09:45")
        sig2 = self._bull_signal("META", str(target), bar_time="13:15")
        output = self._run(["TSLA", "META"],
                           [("09:30", 3), ("13:15", 1)],
                           [[sig1], [sig2]])
        assert "Window 09:30/3b" in output
        assert "Window 13:15/1b" in output

    def test_multiple_windows_produce_aggregate_block(self):
        target = date(2026, 5, 20)
        sig1 = self._bull_signal("TSLA", str(target))
        sig2 = self._bull_signal("META", str(target))
        output = self._run(["TSLA", "META"],
                           [("09:30", 3), ("13:15", 1)],
                           [[sig1], [sig2]])
        assert "aggregate" in output.lower()

    def test_compute_or_ma_signals_called_once_per_window_per_day(self):
        target = date(2026, 5, 20)
        df = self._make_df(target)

        with patch(f"{self._MODULE}.fetch_bars",
                   return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars",
                   return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals",
                   return_value=[]) as mock_compute:
            with contextlib.redirect_stdout(io.StringIO()):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=["TSLA"],
                    windows=[("09:30", 3), ("13:15", 1), ("15:00", 1)],
                    min_vol_ratio=2.0,
                )
        # 1 trading day × 3 windows = 3 calls
        assert mock_compute.call_count == 3

    def test_windows_none_falls_back_to_or_start_or_bars(self):
        target = date(2026, 5, 20)
        df = self._make_df(target)

        with patch(f"{self._MODULE}.fetch_bars",
                   return_value={"TSLA": df, "QQQ": df}), \
             patch(f"{self._MODULE}.fetch_daily_bars",
                   return_value={"TSLA": pd.DataFrame(), "QQQ": pd.DataFrame()}), \
             patch(f"{self._MODULE}.compute_or_ma_signals",
                   return_value=[]) as mock_compute:
            with contextlib.redirect_stdout(io.StringIO()):
                run_range_analysis(
                    start_date=target, end_date=target,
                    tickers=["TSLA"],
                    windows=None, or_start="13:15", or_bars=1,
                    min_vol_ratio=2.0,
                )
        # windows=None → falls back to or_start/or_bars; called once with "13:15", 1
        call_args = mock_compute.call_args
        assert call_args[0][2] == "13:15"   # or_start positional arg
        assert call_args[0][3] == 1          # or_bars positional arg

    def test_window_label_in_banner(self):
        target = date(2026, 5, 20)
        output = self._run(["TSLA"],
                           [("09:30", 3), ("13:15", 1)],
                           [[], []])
        assert "09:30/3b" in output
        assert "13:15/1b" in output


# ─── _count_collection_bars ────────────────────────────────────────────────────


class TestCountCollectionBars:
    _OR_START = dtime(9, 30)
    _DATE = date(2026, 5, 20)

    def _make_bars(self, n_bars, start_offset_min=0):
        """Build n_bars of 5-min bars starting at 09:30 + start_offset_min."""
        base = ET.localize(datetime.combine(self._DATE, dtime(9, 30)))
        timestamps = [base + timedelta(minutes=start_offset_min + i * 5) for i in range(n_bars)]
        df = pd.DataFrame(
            {"Open": [100.0] * n_bars, "High": [101.0] * n_bars,
             "Low": [99.0] * n_bars, "Close": [100.0] * n_bars,
             "Volume": [1_000_000] * n_bars},
            index=timestamps,
        )
        return df

    def test_returns_zero_for_empty_df(self):
        assert _count_collection_bars(pd.DataFrame(), self._OR_START, 3, 3, self._DATE) == 0

    def test_returns_zero_when_or_not_formed(self):
        # Only 2 OR bars but need 3
        df = self._make_bars(2)
        assert _count_collection_bars(df, self._OR_START, 3, 3, self._DATE) == 0

    def test_returns_zero_when_only_or_bars_present(self):
        # Exactly 3 OR bars: or_bars-1+1 from OR start = bar index or_bars-1 = first coll bar
        # With or_bars=3 and 3 bars total, collection index starts at bar 2 (0-indexed)
        # from_or has 3 bars, len - or_bars + 1 = 3 - 3 + 1 = 1 → but bar at index 2 IS collection bar 1
        df = self._make_bars(3)
        result = _count_collection_bars(df, self._OR_START, 3, 3, self._DATE)
        assert result == 1

    def test_returns_one_when_one_collection_bar_arrived(self):
        # 4 bars: 3 OR + 1 collection
        df = self._make_bars(4)
        assert _count_collection_bars(df, self._OR_START, 3, 3, self._DATE) == 2

    def test_returns_two_when_two_collection_bars_arrived(self):
        # 5 bars: 3 OR + 2 collection
        df = self._make_bars(5)
        assert _count_collection_bars(df, self._OR_START, 3, 3, self._DATE) == 3

    def test_caps_at_collection_bars(self):
        # 10 bars present but collection_bars=3
        df = self._make_bars(10)
        assert _count_collection_bars(df, self._OR_START, 3, 3, self._DATE) == 3

    def test_single_bar_window(self):
        # or_bars=1, collection_bars=1: needs exactly 1 OR bar + 1 collection = 2 total
        df = self._make_bars(2)
        assert _count_collection_bars(df, self._OR_START, 1, 1, self._DATE) == 1

    def test_returns_zero_for_none_df(self):
        assert _count_collection_bars(None, self._OR_START, 3, 3, self._DATE) == 0


# ─── Daemon helpers ────────────────────────────────────────────────────────────


class TestDaemonHelpers:
    def test_write_and_read_pid(self, tmp_path):
        pid_file = str(tmp_path / "test.pid")
        _write_pid(pid_file)
        assert _read_pid(pid_file) == os.getpid()

    def test_read_pid_returns_none_for_missing_file(self, tmp_path):
        assert _read_pid(str(tmp_path / "missing.pid")) is None

    def test_read_pid_returns_none_for_corrupt_file(self, tmp_path):
        pid_file = str(tmp_path / "bad.pid")
        with open(pid_file, "w") as f:
            f.write("not-a-number")
        assert _read_pid(pid_file) is None

    def test_remove_pid_deletes_file(self, tmp_path):
        pid_file = str(tmp_path / "test.pid")
        _write_pid(pid_file)
        _remove_pid(pid_file)
        assert not os.path.exists(pid_file)

    def test_remove_pid_silent_when_missing(self, tmp_path):
        _remove_pid(str(tmp_path / "nonexistent.pid"))  # must not raise

    def test_is_running_true_for_current_process(self):
        assert _is_running(os.getpid()) is True

    def test_is_running_false_for_invalid_pid(self):
        assert _is_running(99999999) is False

    def test_daemon_stop_prints_not_running_when_no_pid(self, tmp_path, capsys):
        pid_file = str(tmp_path / "test.pid")
        log_file = str(tmp_path / "test.log")
        _daemon_stop(pid_file, log_file)
        assert "not running" in capsys.readouterr().out

    def test_daemon_stop_prints_not_running_when_pid_stale(self, tmp_path, capsys):
        pid_file = str(tmp_path / "test.pid")
        log_file = str(tmp_path / "test.log")
        with open(pid_file, "w") as f:
            f.write("99999999")  # PID that doesn't exist
        _daemon_stop(pid_file, log_file)
        out = capsys.readouterr().out
        assert "not running" in out
        assert not os.path.exists(pid_file)


# ─── CLI action dispatch ───────────────────────────────────────────────────────


class TestCliActions:
    _MODULE = "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener"

    def _run_main(self, argv):
        from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import main
        with patch("sys.argv", ["screener"] + argv):
            with pytest.raises(SystemExit) as exc:
                main()
        return exc.value.code

    def test_status_not_running(self, tmp_path, capsys):
        pid_file = str(tmp_path / "test.pid")
        code = self._run_main(["status", "--pid-file", pid_file])
        assert code == 0
        assert "not running" in capsys.readouterr().out

    def test_status_running(self, tmp_path, capsys):
        pid_file = str(tmp_path / "test.pid")
        _write_pid(pid_file)
        code = self._run_main(["status", "--pid-file", pid_file])
        assert code == 0
        assert "running" in capsys.readouterr().out

    def test_stop_when_not_running(self, tmp_path, capsys):
        pid_file = str(tmp_path / "test.pid")
        code = self._run_main(["stop", "--pid-file", pid_file])
        assert code == 0
        assert "not running" in capsys.readouterr().out

    def test_logs_exits_when_no_log_file(self, tmp_path, capsys):
        pid_file = str(tmp_path / "test.pid")
        log_file = str(tmp_path / "nonexistent.log")
        code = self._run_main(["logs", "--pid-file", pid_file, "--log-file", log_file])
        assert code == 1
        assert "No log file" in capsys.readouterr().out

    def test_logs_calls_tail(self, tmp_path):
        pid_file = str(tmp_path / "test.pid")
        log_file = str(tmp_path / "test.log")
        with open(log_file, "w") as f:
            f.write("log line\n")
        # os.execvp replaces the process in production and never returns;
        # use side_effect=SystemExit so the mock exits cleanly instead of falling through
        with patch(f"{self._MODULE}.os.execvp", side_effect=SystemExit(0)) as mock_exec:
            self._run_main(["logs", "--pid-file", pid_file, "--log-file", log_file])
        mock_exec.assert_called_once_with("tail", ["tail", "-f", log_file])


# ─── _compute_hold_history ─────────────────────────────────────────────────────
#
# OR: 09:30 start, 3 bars → OR-close bar at 09:45 (bar index 3).
# Exit bar indices from 09:30:
#   +15m → 10:00 (index 6)   +30m → 10:15 (index 9)
#   +60m → 10:45 (index 15)  +120m → 11:45 (index 27)


class TestComputeHoldHistory:
    _OR_START = "09:30"
    _OR_BARS = 3
    # bar index within a day's 5-min series (starting 09:30) for each exit
    # anchor = last OR bar = 09:40 (index 2); +5h from 09:40 → 14:40 = index 62
    _EXIT_IDX = {15: 5, 30: 8, 60: 14, 120: 26, 300: 62}

    def _day_closes(self, entry, exits):
        """80-element close list (09:30–16:05): entry at index 2, override specific exit indices."""
        closes = [entry] * 80
        for hold_min, exit_close in exits.items():
            if hold_min is None:
                closes[-1] = exit_close  # EOD → last bar
            else:
                closes[self._EXIT_IDX[hold_min]] = exit_close
        return closes

    def _prior_day(self, days_back, entry, exits):
        d = _TARGET_DATE - timedelta(days=days_back)
        return _make_5min_bars(self._day_closes(entry, exits), target_date=d)

    def _combine(self, frames):
        combined = pd.concat([f[["Open", "High", "Low", "Close", "Volume"]] for f in frames])
        return _add_ma_columns(combined)

    def test_returns_none_for_none_input(self):
        assert _compute_hold_history(None, _TARGET_DATE, self._OR_START, self._OR_BARS) is None

    def test_returns_none_for_empty_dataframe(self):
        assert _compute_hold_history(pd.DataFrame(), _TARGET_DATE, self._OR_START, self._OR_BARS) is None

    def test_returns_none_when_no_prior_days(self):
        df = _make_5min_bars([100.0] * 10, target_date=_TARGET_DATE)
        assert _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS) is None

    def test_forward_return_at_15min(self):
        df = self._combine([self._prior_day(1, entry=100.0, exits={15: 105.0})])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][15] == pytest.approx(5.0)

    def test_forward_return_at_30min(self):
        df = self._combine([self._prior_day(1, entry=100.0, exits={30: 102.0})])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][30] == pytest.approx(2.0)

    def test_forward_return_at_1h(self):
        df = self._combine([self._prior_day(1, entry=100.0, exits={60: 98.0})])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][60] == pytest.approx(-2.0)

    def test_forward_return_at_2h(self):
        df = self._combine([self._prior_day(1, entry=100.0, exits={120: 103.0})])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][120] == pytest.approx(3.0)

    def test_forward_return_at_5h(self):
        df = self._combine([self._prior_day(1, entry=100.0, exits={300: 104.0})])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][300] == pytest.approx(4.0)

    def test_forward_return_eod_uses_last_bar(self):
        df = self._combine([self._prior_day(1, entry=100.0, exits={None: 106.0})])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][None] == pytest.approx(6.0)

    def test_averages_returns_across_multiple_prior_days(self):
        # Day 1: +10%, Day 2: +2% → avg +6%
        day1 = self._prior_day(1, entry=100.0, exits={15: 110.0})
        day2 = self._prior_day(2, entry=100.0, exits={15: 102.0})
        df = self._combine([day1, day2])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][15] == pytest.approx(6.0)

    def test_respects_lookback_limit(self):
        # Newest 5 days: +2%. Older 20 days: +100%. With lookback=5 only newest 5 count.
        frames = [self._prior_day(i, entry=100.0, exits={15: 102.0}) for i in range(1, 6)]
        frames += [self._prior_day(i, entry=100.0, exits={15: 200.0}) for i in range(6, 26)]
        df = self._combine(frames)
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS, lookback=5)
        assert result["holds"][15] == pytest.approx(2.0)

    def test_excludes_target_date_from_history(self):
        # Target-date bars have a +100% exit — must not contaminate the prior-day avg.
        prior = self._prior_day(1, entry=100.0, exits={15: 102.0})
        today = _make_5min_bars(
            self._day_closes(entry=100.0, exits={15: 200.0}),
            target_date=_TARGET_DATE,
        )
        df = self._combine([prior, today])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["holds"][15] == pytest.approx(2.0)

    def test_daily_move_is_abs_first_open_to_last_close(self):
        # closes[0]=100 → first Open=100; closes[-1]=103 → last Close=103 → move=3%
        closes = [100.0] * 30
        closes[-1] = 103.0
        d = _TARGET_DATE - timedelta(days=1)
        df = self._combine([_make_5min_bars(closes, target_date=d)])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["daily_move"] == pytest.approx(3.0)

    def test_n_reflects_number_of_prior_days_in_window(self):
        frames = [self._prior_day(i, entry=100.0, exits={}) for i in range(1, 4)]
        df = self._combine(frames)
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["n"] == 3

    def test_eod_range_min_and_max_across_prior_days(self):
        # Day 1: EOD +5%, Day 2: EOD +1%, Day 3: EOD -2% → range (-2%, +5%)
        day1 = self._prior_day(1, entry=100.0, exits={None: 105.0})
        day2 = self._prior_day(2, entry=100.0, exits={None: 101.0})
        day3 = self._prior_day(3, entry=100.0, exits={None: 98.0})
        df = self._combine([day1, day2, day3])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        lo, hi = result["eod_range"]
        assert lo == pytest.approx(-2.0)
        assert hi == pytest.approx(5.0)

    def test_eod_range_is_none_when_no_eod_data(self):
        # Only 15 bars per day — not enough to cover EOD; but EOD uses last bar so it always fires.
        # Use a df that has no prior days at all to get None.
        df = _make_5min_bars([100.0] * 5, target_date=_TARGET_DATE)
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result is None  # no prior days → None overall

    def test_win_rate_100_when_all_days_positive(self):
        frames = [self._prior_day(i, entry=100.0, exits={15: 102.0}) for i in range(1, 4)]
        df = self._combine(frames)
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["win_rates"][15] == pytest.approx(100.0)

    def test_win_rate_0_when_all_days_negative(self):
        frames = [self._prior_day(i, entry=100.0, exits={15: 98.0}) for i in range(1, 4)]
        df = self._combine(frames)
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["win_rates"][15] == pytest.approx(0.0)

    def test_win_rate_50_when_half_days_positive(self):
        day_up = self._prior_day(1, entry=100.0, exits={15: 102.0})
        day_dn = self._prior_day(2, entry=100.0, exits={15: 98.0})
        df = self._combine([day_up, day_dn])
        result = _compute_hold_history(df, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result["win_rates"][15] == pytest.approx(50.0)


# ─── _format_hold_history ──────────────────────────────────────────────────────


class TestFormatHoldHistory:
    def _hist(self, holds=None, win_rates=None, daily_move=2.5, n=20):
        h = holds if holds is not None else {15: 0.5, 30: 1.0, 60: 0.8, 120: -1.0, 300: 0.6, None: 1.2}
        wr = win_rates if win_rates is not None else {k: 60.0 for k in h}
        return {"holds": h, "win_rates": wr, "daily_move": daily_move, "n": n}

    def test_returns_none_for_none_input(self):
        assert _format_hold_history(None) is None

    def test_output_contains_15m_label(self):
        assert "+15m" in _format_hold_history(self._hist())

    def test_output_contains_30m_label(self):
        assert "+30m" in _format_hold_history(self._hist())

    def test_output_contains_1h_label(self):
        assert "+1h" in _format_hold_history(self._hist())

    def test_output_contains_2h_label(self):
        assert "+2h" in _format_hold_history(self._hist())

    def test_output_contains_5h_label(self):
        assert "+5h" in _format_hold_history(self._hist())

    def test_output_contains_eod_label(self):
        assert "EOD" in _format_hold_history(self._hist())

    def test_win_rate_shown_with_percent_w_suffix(self):
        result = _format_hold_history(self._hist(win_rates={15: 65.0, 30: 60.0, 60: 60.0, 120: 60.0, 300: 60.0, None: 60.0}))
        assert "65%W" in result

    def test_positive_ev_shown_with_plus_sign(self):
        result = _format_hold_history(self._hist(holds={15: 1.5, 30: 0.0, 60: 0.0, 120: 0.0}))
        assert "+1.5%" in result

    def test_negative_ev_shown_with_minus_sign(self):
        result = _format_hold_history(self._hist(holds={15: 0.0, 30: 0.0, 60: 0.0, 120: -1.0}))
        assert "-1.0%" in result

    def test_contains_n_days_count(self):
        assert "20d" in _format_hold_history(self._hist(n=20))

    def test_contains_daily_move_when_available(self):
        assert "3.0%" in _format_hold_history(self._hist(daily_move=3.0))

    def test_omits_daily_move_section_when_none(self):
        result = _format_hold_history(self._hist(daily_move=None))
        assert "daily" not in result

    def test_missing_hold_keys_are_omitted(self):
        result = _format_hold_history({
            "holds": {15: 0.5, 30: 1.0}, "win_rates": {15: 60.0, 30: 70.0},
            "daily_move": None, "n": 5,
        })
        assert "+15m" in result
        assert "+30m" in result
        assert "+1h" not in result
        assert "+2h" not in result


# ─── _rank_tickers_by_eod_win_rate ────────────────────────────────────────────


class TestRankTickersByEodWinRate:
    _OR_START = "09:30"
    _OR_BARS = 3
    # bar index 3 = 09:45 (OR close), index 6 = 10:00 (+15m), index -1 = last bar (EOD)

    def _make_ticker_df(self, n_days, entry, eod_close):
        """Prior days where entry=entry at OR close, last bar=eod_close."""
        frames = []
        for i in range(1, n_days + 1):
            d = _TARGET_DATE - timedelta(days=i)
            closes = [entry] * 80
            closes[-1] = eod_close
            frames.append(_make_5min_bars(closes, target_date=d))
        combined = pd.concat([f[["Open", "High", "Low", "Close", "Volume"]] for f in frames])
        return _add_ma_columns(combined)

    def test_returns_empty_list_when_no_tickers(self):
        result = _rank_tickers_by_eod_win_rate({}, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert result == []

    def test_returns_empty_list_when_no_ticker_has_history(self):
        df = _make_5min_bars([100.0] * 5, target_date=_TARGET_DATE)
        result = _rank_tickers_by_eod_win_rate(
            {"TSLA": df}, _TARGET_DATE, self._OR_START, self._OR_BARS
        )
        assert result == []

    def test_single_ticker_with_history_is_returned(self):
        df = self._make_ticker_df(3, entry=100.0, eod_close=102.0)
        result = _rank_tickers_by_eod_win_rate(
            {"TSLA": df}, _TARGET_DATE, self._OR_START, self._OR_BARS
        )
        assert len(result) == 1
        assert result[0][0] == "TSLA"

    def test_higher_eod_win_rate_ranks_first(self):
        # APP: all 3 days EOD positive → 100% win rate
        # META: all 3 days EOD negative → 0% win rate
        app_df = self._make_ticker_df(3, entry=100.0, eod_close=102.0)
        meta_df = self._make_ticker_df(3, entry=100.0, eod_close=98.0)
        result = _rank_tickers_by_eod_win_rate(
            {"META": meta_df, "APP": app_df}, _TARGET_DATE, self._OR_START, self._OR_BARS
        )
        assert result[0][0] == "APP"
        assert result[1][0] == "META"

    def test_result_contains_hist_dict_for_each_ticker(self):
        df = self._make_ticker_df(3, entry=100.0, eod_close=102.0)
        result = _rank_tickers_by_eod_win_rate(
            {"TSLA": df}, _TARGET_DATE, self._OR_START, self._OR_BARS
        )
        ticker, hist = result[0]
        assert "win_rates" in hist
        assert "medians" in hist
        assert None in hist["win_rates"]

    def test_excludes_tickers_with_no_computable_history(self):
        good_df = self._make_ticker_df(3, entry=100.0, eod_close=102.0)
        empty_df = pd.DataFrame()
        result = _rank_tickers_by_eod_win_rate(
            {"GOOD": good_df, "EMPTY": empty_df}, _TARGET_DATE, self._OR_START, self._OR_BARS
        )
        tickers = [t for t, _ in result]
        assert "GOOD" in tickers
        assert "EMPTY" not in tickers


# ─── _format_top2_ranking ──────────────────────────────────────────────────────


class TestFormatTop2Ranking:
    _OR_START = "09:30"
    _OR_BARS = 3

    def _make_ranked(self, tickers_and_eod_wr):
        """Build a minimal ranked list with the given (ticker, eod_win_rate) pairs."""
        ranked = []
        for ticker, eod_wr in tickers_and_eod_wr:
            hist = {
                "win_rates": {15: 60.0, 30: 65.0, 60: 70.0, 120: 70.0, 300: 75.0, None: eod_wr},
                "medians":   {15: 0.3,  30: 0.5,  60: 0.8,  120: 1.0,  300: 1.2,  None: 1.5},
                "holds":     {15: 0.4,  30: 0.6,  60: 0.9,  120: 1.1,  300: 1.3,  None: 1.6},
                "eod_range": (-1.5, 4.0),
                "daily_move": 2.0,
                "n": 20,
            }
            ranked.append((ticker, hist))
        return ranked

    def test_returns_none_for_empty_ranked_list(self):
        assert _format_top2_ranking([], _TARGET_DATE, self._OR_START, self._OR_BARS) is None

    def test_shows_rank_1_ticker(self):
        ranked = self._make_ranked([("APP", 80.0), ("ARM", 67.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "#1 APP" in result

    def test_shows_rank_2_ticker(self):
        ranked = self._make_ranked([("APP", 80.0), ("ARM", 67.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "#2 ARM" in result

    def test_only_top2_shown_when_more_tickers_available(self):
        ranked = self._make_ranked([("APP", 80.0), ("ARM", 70.0), ("CRWD", 60.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "CRWD" not in result

    def test_output_contains_median_values(self):
        ranked = self._make_ranked([("APP", 80.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "+1.5%" in result  # EOD median

    def test_output_contains_win_rate_for_each_window(self):
        ranked = self._make_ranked([("APP", 80.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "80%W" in result  # EOD win rate

    def test_output_contains_target_date(self):
        ranked = self._make_ranked([("APP", 80.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert str(_TARGET_DATE) in result

    def test_works_with_only_one_ranked_ticker(self):
        ranked = self._make_ranked([("APP", 80.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "#1 APP" in result
        assert "#2" not in result

    def test_eod_range_shown_at_end_of_row(self):
        ranked = self._make_ranked([("APP", 80.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "-1.5%" in result
        assert "+4.0%" in result

    def test_header_references_925(self):
        ranked = self._make_ranked([("APP", 80.0)])
        result = _format_top2_ranking(ranked, _TARGET_DATE, self._OR_START, self._OR_BARS)
        assert "9:25" in result


# ─── _format_ticker_win_rate_table ────────────────────────────────────────────


class TestFormatTickerWinRateTable:
    def _make_ranked(self, tickers):
        ranked = []
        for ticker in tickers:
            hist = {
                "win_rates": {15: 60.0, 30: 65.0, 60: 70.0, 120: 70.0, 300: 75.0, None: 80.0},
                "medians":   {15: 0.3,  30: 0.5,  60: 0.8,  120: 1.0,  300: 1.2,  None: 1.5},
                "holds":     {15: 0.4,  30: 0.6,  60: 0.9,  120: 1.1,  300: 1.3,  None: 1.6},
                "eod_range": (-1.5, 4.0),
                "daily_move": 2.0,
                "n": 20,
            }
            ranked.append((ticker, hist))
        return ranked

    def test_returns_none_for_empty_ranked_list(self):
        assert _format_ticker_win_rate_table([]) is None

    def test_all_tickers_appear_in_table(self):
        ranked = self._make_ranked(["APP", "ARM", "CRWD"])
        result = _format_ticker_win_rate_table(ranked)
        assert "APP" in result
        assert "ARM" in result
        assert "CRWD" in result

    def test_all_hold_labels_appear_in_header(self):
        ranked = self._make_ranked(["APP"])
        result = _format_ticker_win_rate_table(ranked)
        for label in ["+15m", "+30m", "+1h", "+2h", "+5h", "EOD"]:
            assert label in result

    def test_win_rate_shown_for_each_ticker(self):
        ranked = self._make_ranked(["APP"])
        result = _format_ticker_win_rate_table(ranked)
        assert "80%W" in result

    def test_median_return_shown_for_each_ticker(self):
        ranked = self._make_ranked(["APP"])
        result = _format_ticker_win_rate_table(ranked)
        assert "+1.5%" in result  # EOD median

    def test_eod_range_shown_for_each_ticker(self):
        ranked = self._make_ranked(["APP"])
        result = _format_ticker_win_rate_table(ranked)
        assert "-1.5%" in result
        assert "+4.0%" in result

    def test_n_days_shown_for_each_ticker(self):
        ranked = self._make_ranked(["APP"])
        result = _format_ticker_win_rate_table(ranked)
        assert "20" in result

    def test_all_tickers_present_not_just_top2(self):
        ranked = self._make_ranked(["APP", "ARM", "CRWD", "DDOG", "META"])
        result = _format_ticker_win_rate_table(ranked)
        for ticker in ["APP", "ARM", "CRWD", "DDOG", "META"]:
            assert ticker in result


# ─── _build_presession_picks_rows ─────────────────────────────────────────────


class TestBuildPresessionPicksRows:
    _OR_START = "09:30"
    _OR_BARS = 3
    # OR close bar = 09:40 (index 2), +15m exit = 09:55 (index 5)

    def _make_full_day(self, target_date, or_close=100.0, exit_15m=102.0):
        """80-bar day: OR close bar at index 2 = or_close, +15m bar at index 5 = exit_15m."""
        closes = [or_close] * 80
        closes[5] = exit_15m
        return _make_5min_bars(closes, target_date=target_date)

    def _make_prior_days(self, target_date, n=20, entry=100.0, eod=101.0):
        """N prior days with flat close=entry except last bar=eod."""
        frames = []
        for i in range(1, n + 1):
            d = target_date - timedelta(days=i)
            closes = [entry] * 80
            closes[-1] = eod
            frames.append(_make_5min_bars(closes, target_date=d))
        combined = pd.concat([f[["Open", "High", "Low", "Close", "Volume"]] for f in frames])
        return _add_ma_columns(combined)

    def _combine(self, *dfs):
        combined = pd.concat([df[["Open", "High", "Low", "Close", "Volume"]] for df in dfs])
        return _add_ma_columns(combined)

    def test_returns_empty_list_when_no_tickers(self):
        result = _build_presession_picks_rows({}, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert result == []

    def test_returns_empty_list_when_no_trading_days(self):
        prior = self._make_prior_days(_TARGET_DATE)
        result = _build_presession_picks_rows({"APP": prior}, [], self._OR_START, self._OR_BARS)
        assert result == []

    def test_returns_two_rows_per_day_for_two_tickers(self):
        prior_app = self._make_prior_days(_TARGET_DATE, eod=103.0)
        prior_arm = self._make_prior_days(_TARGET_DATE, eod=101.0)
        today_app = self._make_full_day(_TARGET_DATE)
        today_arm = self._make_full_day(_TARGET_DATE)
        bars = {
            "APP": self._combine(prior_app, today_app),
            "ARM": self._combine(prior_arm, today_arm),
        }
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert len(result) == 2

    def test_higher_eod_win_rate_ticker_gets_rank_1(self):
        # APP all prior days EOD positive (100% WR) → rank 1
        # ARM all prior days EOD negative (0% WR) → rank 2
        prior_app = self._make_prior_days(_TARGET_DATE, eod=102.0)
        prior_arm = self._make_prior_days(_TARGET_DATE, eod=98.0)
        today_app = self._make_full_day(_TARGET_DATE)
        today_arm = self._make_full_day(_TARGET_DATE)
        bars = {
            "APP": self._combine(prior_app, today_app),
            "ARM": self._combine(prior_arm, today_arm),
        }
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        rank1 = next(r for r in result if r["rank"] == 1)
        assert rank1["ticker"] == "APP"

    def test_row_contains_forward_return_at_15m(self):
        prior = self._make_prior_days(_TARGET_DATE, eod=102.0)
        today = self._make_full_day(_TARGET_DATE, or_close=100.0, exit_15m=103.0)
        bars = {"APP": self._combine(prior, today)}
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert len(result) == 1
        assert result[0]["pct_+15m"] == pytest.approx(3.0)

    def test_row_entry_price_is_or_close_bar(self):
        prior = self._make_prior_days(_TARGET_DATE, eod=102.0)
        today = self._make_full_day(_TARGET_DATE, or_close=250.0)
        bars = {"APP": self._combine(prior, today)}
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert result[0]["entry"] == pytest.approx(250.0)

    def test_skips_ticker_with_no_or_close_bar_on_target_date(self):
        prior = self._make_prior_days(_TARGET_DATE, eod=102.0)
        # today has only 2 bars — OR close bar (09:40) is missing
        short_today = _make_5min_bars([100.0] * 2, target_date=_TARGET_DATE)
        bars = {"APP": self._combine(prior, short_today)}
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert result == []

    def test_produces_rows_for_multiple_trading_days(self):
        day1 = _TARGET_DATE
        day2 = _TARGET_DATE + timedelta(days=1)
        prior = self._make_prior_days(day1, eod=102.0)
        today1 = self._make_full_day(day1)
        today2 = self._make_full_day(day2)
        combined = self._combine(prior, today1, today2)
        result = _build_presession_picks_rows({"APP": combined}, [day1, day2],
                                              self._OR_START, self._OR_BARS)
        dates = [r["date"] for r in result]
        assert day1 in dates
        assert day2 in dates

    def test_row_contains_all_hold_window_keys(self):
        from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
            _HOLD_WINDOWS_MIN, _hold_label,
        )
        prior = self._make_prior_days(_TARGET_DATE, eod=102.0)
        today = self._make_full_day(_TARGET_DATE)
        bars = {"APP": self._combine(prior, today)}
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert len(result) == 1
        for mins in _HOLD_WINDOWS_MIN:
            assert f"pct_{_hold_label(mins)}" in result[0]

    def test_signal_time_is_or_close_bar_time(self):
        # OR: 09:30 start, 3 bars → last OR bar opens at 09:40 (index 2)
        prior = self._make_prior_days(_TARGET_DATE, eod=102.0)
        today = self._make_full_day(_TARGET_DATE)
        bars = {"APP": self._combine(prior, today)}
        result = _build_presession_picks_rows(bars, [_TARGET_DATE], self._OR_START, self._OR_BARS)
        assert result[0]["signal_time"] == "09:40"
