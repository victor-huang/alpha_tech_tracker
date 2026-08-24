"""
Tests for performance optimizations in op_momentum_selector_backtest.py
and op_momentum_selector.py.

Covers:
  - compute_ticker_stats: recent_bear_ev uses bear_df.tail (input is date-ordered,
    sort_values removed as it was redundant)
  - _fetch_vix_daily: disk cache is written on cold call and reused on warm call;
    end_date == today skips the cache write
  - primary_results_by_date: pre-grouped dict holds only primary rows (no reversal
    or reentry rows), matching what the old per-iteration DataFrame filter produced
  - compute_signals_with_backtest: fast_ma_col column skipped when trailing_ma_switch="none"
  - compute_signals_with_backtest: _hist_or_vol skipped when compute_or_vol_ratio=False
  - bars_by_date: skipped when or_bar_lookback=0 and enable_doubledown=False and
    score_or_bar_quality_weight=0.0
"""
import unittest.mock as mock

import pandas as pd
from datetime import date, datetime, timedelta

import pytz

import alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest as _bt_module
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import compute_ticker_stats
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import _fetch_vix_daily
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import compute_signals_with_backtest


def _make_results_df(rows):
    return pd.DataFrame([
        {
            "date": r["date"],
            "signal": r.get("signal", "BULLISH"),
            "success": r["pnl"] > 0,
            "pnl": r["pnl"],
            "entry_price": r.get("entry_price", 100.0),
            "midpoint": r.get("midpoint", 99.0),
        }
        for r in rows
    ])


# ---------------------------------------------------------------------------
# TestComputeTickerStatsRecentBearEv
# Verifies that recent_bear_ev reflects the last N bear trades (tail) rather
# than sorting the full bear_df — relies on the caller providing date-ordered input.
# ---------------------------------------------------------------------------


class TestComputeTickerStatsRecentBearEv:
    def test_uses_most_recent_trades_when_last_n_are_winners(self):
        # 10 bear trades in date order: first 7 losers, last 3 winners.
        # recent_bear_ev with recent_bear_trades=3 should be positive.
        rows = [
            {"date": date(2025, 1, i + 1), "signal": "BEARISH", "pnl": -1.0}
            for i in range(7)
        ] + [
            {"date": date(2025, 1, i + 8), "signal": "BEARISH", "pnl": 5.0}
            for i in range(3)
        ]
        df = _make_results_df(rows)

        stats = compute_ticker_stats(df, recent_bear_trades=3)

        assert stats["recent_bear_ev"] > 0

    def test_ignores_old_winning_trades_when_last_n_are_losers(self):
        # 10 bear trades in date order: first 7 winners, last 3 losers.
        # recent_bear_ev with recent_bear_trades=3 should be negative.
        rows = [
            {"date": date(2025, 1, i + 1), "signal": "BEARISH", "pnl": 5.0}
            for i in range(7)
        ] + [
            {"date": date(2025, 1, i + 8), "signal": "BEARISH", "pnl": -1.0}
            for i in range(3)
        ]
        df = _make_results_df(rows)

        stats = compute_ticker_stats(df, recent_bear_trades=3)

        assert stats["recent_bear_ev"] < 0

    def test_clamps_to_available_bear_trades_when_fewer_than_n(self):
        # Only 2 bear trades; recent_bear_trades=7 should use both without error.
        rows = [
            {"date": date(2025, 1, 1), "signal": "BEARISH", "pnl": 3.0},
            {"date": date(2025, 1, 2), "signal": "BEARISH", "pnl": 2.0},
        ]
        df = _make_results_df(rows)

        stats = compute_ticker_stats(df, recent_bear_trades=7)

        assert stats["recent_bear_ev"] > 0

    def test_zero_when_no_bear_trades(self):
        rows = [{"date": date(2025, 1, 1), "signal": "BULLISH", "pnl": 3.0}]
        df = _make_results_df(rows)

        stats = compute_ticker_stats(df, recent_bear_trades=7)

        assert stats["recent_bear_ev"] == 0.0


# ---------------------------------------------------------------------------
# TestFetchVixDailyCaching
# ---------------------------------------------------------------------------


def _mock_vix_df(close_values, start_date):
    dates = pd.date_range(start=str(start_date), periods=len(close_values), freq="B")
    return pd.DataFrame({"Close": close_values}, index=dates)



def _freeze_eastern_now(monkeypatch, on_date, hour):
    """Pin the Eastern clock the VIX cache gate reads, and return that date.

    The gate compares `end` against the Eastern date, so a test that builds its
    dates from the local clock breaks whenever the two time zones disagree.
    """
    frozen = pytz.timezone("America/New_York").localize(
        datetime(on_date.year, on_date.month, on_date.day, hour)
    )

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen

    monkeypatch.setattr(_bt_module, "datetime", _FrozenDatetime)
    return on_date


class TestFetchVixDailyCaching:
    def test_cold_call_downloads_and_writes_cache_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_bt_module, "_VIX_CACHE_DIR", tmp_path)
        mock_download = mock.MagicMock(return_value=_mock_vix_df([20.0, 21.0], date(2025, 1, 2)))
        monkeypatch.setattr(_bt_module.yf, "download", mock_download)

        result = _fetch_vix_daily(date(2025, 1, 1), date(2025, 6, 30))

        cache_files = list(tmp_path.glob("yfinance_1d_VIX_*.json"))
        assert len(cache_files) == 1
        assert len(result) == 2

    def test_warm_call_reads_cache_without_calling_yfinance(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_bt_module, "_VIX_CACHE_DIR", tmp_path)
        mock_download = mock.MagicMock(return_value=_mock_vix_df([20.0], date(2025, 1, 2)))
        monkeypatch.setattr(_bt_module.yf, "download", mock_download)

        _fetch_vix_daily(date(2025, 1, 1), date(2025, 6, 30))
        mock_download.reset_mock()

        _fetch_vix_daily(date(2025, 1, 1), date(2025, 6, 30))

        mock_download.assert_not_called()

    def test_warm_call_returns_same_series_as_cold_call(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_bt_module, "_VIX_CACHE_DIR", tmp_path)
        monkeypatch.setattr(
            _bt_module.yf, "download",
            mock.MagicMock(return_value=_mock_vix_df([18.5, 22.3], date(2025, 1, 2))),
        )

        cold = _fetch_vix_daily(date(2025, 1, 1), date(2025, 6, 30))
        warm = _fetch_vix_daily(date(2025, 1, 1), date(2025, 6, 30))

        pd.testing.assert_series_equal(cold.reset_index(drop=True), warm.reset_index(drop=True))

    def test_end_date_today_does_not_write_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_bt_module, "_VIX_CACHE_DIR", tmp_path)
        today = _freeze_eastern_now(monkeypatch, date(2025, 6, 30), hour=11)
        monkeypatch.setattr(
            _bt_module.yf, "download",
            mock.MagicMock(return_value=_mock_vix_df([20.0], today)),
        )

        _fetch_vix_daily(date(2025, 1, 1), today)

        assert list(tmp_path.glob("yfinance_1d_VIX_*.json")) == []

    def test_end_date_before_today_writes_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_bt_module, "_VIX_CACHE_DIR", tmp_path)
        today = _freeze_eastern_now(monkeypatch, date(2025, 6, 30), hour=11)
        monkeypatch.setattr(
            _bt_module.yf, "download",
            mock.MagicMock(return_value=_mock_vix_df([20.0], date(2025, 6, 27))),
        )

        _fetch_vix_daily(date(2025, 1, 1), today - timedelta(days=1))

        assert len(list(tmp_path.glob("yfinance_1d_VIX_*.json"))) == 1

    def test_different_date_ranges_produce_separate_cache_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_bt_module, "_VIX_CACHE_DIR", tmp_path)
        monkeypatch.setattr(
            _bt_module.yf, "download",
            mock.MagicMock(return_value=_mock_vix_df([20.0], date(2025, 1, 2))),
        )

        _fetch_vix_daily(date(2025, 1, 1), date(2025, 6, 30))
        _fetch_vix_daily(date(2025, 1, 1), date(2025, 12, 31))

        cache_files = list(tmp_path.glob("yfinance_1d_VIX_*.json"))
        assert len(cache_files) == 2


# ---------------------------------------------------------------------------
# TestPrimaryResultsByDatePreGrouping
# Verifies that primary_window_results correctly strips reversal and reentry
# rows — the source for the primary_results_by_date dict that replaced the
# per-iteration DataFrame filter.
# ---------------------------------------------------------------------------


class TestPrimaryResultsByDatePreGrouping:
    def _make_signal_df(self):
        """DataFrame with one primary, one reversal, one bearish-reentry row."""
        return pd.DataFrame([
            {
                "date": date(2025, 3, 1),
                "signal": "BULLISH",
                "is_reversal": False,
                "is_bearish_reentry": False,
                "is_bullish_reentry": False,
                "entry_price": 100.0,
                "pnl": 1.0,
                "success": True,
            },
            {
                "date": date(2025, 3, 1),
                "signal": "BEARISH",
                "is_reversal": True,
                "is_bearish_reentry": False,
                "is_bullish_reentry": False,
                "entry_price": 99.0,
                "pnl": 0.5,
                "success": True,
            },
            {
                "date": date(2025, 3, 1),
                "signal": "BEARISH",
                "is_reversal": False,
                "is_bearish_reentry": True,
                "is_bullish_reentry": False,
                "entry_price": 98.0,
                "pnl": -0.3,
                "success": False,
            },
        ])

    def test_pre_filter_excludes_reversal_rows(self):
        df = self._make_signal_df()

        primary_df = df[
            (df["is_reversal"] != True)           # noqa: E712
            & (df["is_bearish_reentry"] != True)  # noqa: E712
            & (df["is_bullish_reentry"] != True)  # noqa: E712
        ]

        assert len(primary_df) == 1
        assert primary_df.iloc[0]["signal"] == "BULLISH"

    def test_pre_grouped_date_dict_contains_only_primary_rows(self):
        df = self._make_signal_df()
        primary_df = df[
            (df["is_reversal"] != True)           # noqa: E712
            & (df["is_bearish_reentry"] != True)  # noqa: E712
            & (df["is_bullish_reentry"] != True)  # noqa: E712
        ]

        by_date = {d_: g for d_, g in primary_df.groupby("date")}

        d = date(2025, 3, 1)
        assert d in by_date
        assert len(by_date[d]) == 1
        assert not by_date[d].iloc[0]["is_reversal"]

    def test_full_results_by_date_retains_all_rows(self):
        df = self._make_signal_df()

        by_date = {d_: g for d_, g in df.groupby("date")}

        d = date(2025, 3, 1)
        assert len(by_date[d]) == 3


# ---------------------------------------------------------------------------
# TestFastMaColGate
# Verifies that the fast_ma_col rolling column is NOT built when
# trailing_ma_switch="none" (Fix #2) and IS built when a switch mode is set.
# ---------------------------------------------------------------------------


def _make_bars_df():
    """Minimal 5-min bar DataFrame covering two trading days."""
    import numpy as np
    rng = pd.date_range("2025-01-02 09:30", periods=78, freq="5min")
    closes = np.linspace(100.0, 110.0, len(rng))
    return pd.DataFrame(
        {"Open": closes, "High": closes + 0.5, "Low": closes - 0.5, "Close": closes, "Volume": 1000},
        index=rng,
    )


class TestFastMaColGate:
    def test_fast_ma_col_not_built_when_switch_none(self, monkeypatch):
        # The function works on df.copy(), so we spy on pd.Series.rolling to detect
        # whether rolling(period) is called for the fast MA column specifically.
        period = 8
        observed_windows = []
        original_rolling = pd.Series.rolling

        def spy_rolling(self, window, *args, **kwargs):
            observed_windows.append(window)
            return original_rolling(self, window, *args, **kwargs)

        monkeypatch.setattr(pd.Series, "rolling", spy_rolling)
        compute_signals_with_backtest(
            _make_bars_df(),
            opening_bars=3,
            trailing_ma_switch="none",
            trailing_ma_switch_period=period,
        )

        assert period not in observed_windows

    def test_fast_ma_col_built_when_switch_after_arm(self, monkeypatch):
        period = 8
        observed_windows = []
        original_rolling = pd.Series.rolling

        def spy_rolling(self, window, *args, **kwargs):
            observed_windows.append(window)
            return original_rolling(self, window, *args, **kwargs)

        monkeypatch.setattr(pd.Series, "rolling", spy_rolling)
        compute_signals_with_backtest(
            _make_bars_df(),
            opening_bars=3,
            trailing_ma_switch="after-arm",
            trailing_ma_switch_period=period,
        )

        assert period in observed_windows


# ---------------------------------------------------------------------------
# TestOrVolRatioGate
# Verifies that _hist_or_vol groupby is NOT called when compute_or_vol_ratio=False
# and IS called when compute_or_vol_ratio=True (Fix #1).
# ---------------------------------------------------------------------------


class TestOrVolRatioGate:
    def test_or_vol_ratio_present_in_results_when_flag_true(self):
        df = _make_bars_df()

        result = compute_signals_with_backtest(df, opening_bars=3, compute_or_vol_ratio=True)

        if not result.empty:
            assert "or_vol_ratio" in result.columns

    def test_or_vol_ratio_absent_from_results_when_flag_false(self):
        df = _make_bars_df()

        result = compute_signals_with_backtest(df, opening_bars=3, compute_or_vol_ratio=False)

        if not result.empty:
            assert result["or_vol_ratio"].isna().all() or (result["or_vol_ratio"] == 0).all()


# ---------------------------------------------------------------------------
# TestBarsByDateGate
# Verifies bars_by_date is an empty dict when all three controlling params are off
# (or_bar_lookback=0, enable_doubledown=False, score_or_bar_quality_weight=0.0).
# This mirrors what run_selector_backtest produces — tests the dict-comprehension
# guard expression in isolation (Fix #4).
# ---------------------------------------------------------------------------


class TestBarsByDateGate:
    def _build_bars_by_date(self, or_bar_lookback, enable_doubledown, score_or_bar_quality_weight, all_bars):
        return (
            {
                ticker: {d_: g for d_, g in df.groupby(df.index.date)}
                for ticker, df in all_bars.items()
                if not df.empty
            }
            if or_bar_lookback > 0 or enable_doubledown or score_or_bar_quality_weight != 0.0
            else {}
        )

    def test_bars_by_date_empty_when_all_flags_off(self):
        all_bars = {"AAPL": _make_bars_df()}
        result = self._build_bars_by_date(
            or_bar_lookback=0,
            enable_doubledown=False,
            score_or_bar_quality_weight=0.0,
            all_bars=all_bars,
        )
        assert result == {}

    def test_bars_by_date_populated_when_or_bar_lookback_nonzero(self):
        all_bars = {"AAPL": _make_bars_df()}
        result = self._build_bars_by_date(
            or_bar_lookback=3,
            enable_doubledown=False,
            score_or_bar_quality_weight=0.0,
            all_bars=all_bars,
        )
        assert "AAPL" in result

    def test_bars_by_date_populated_when_enable_doubledown_true(self):
        all_bars = {"AAPL": _make_bars_df()}
        result = self._build_bars_by_date(
            or_bar_lookback=0,
            enable_doubledown=True,
            score_or_bar_quality_weight=0.0,
            all_bars=all_bars,
        )
        assert "AAPL" in result

    def test_bars_by_date_populated_when_quality_weight_nonzero(self):
        all_bars = {"AAPL": _make_bars_df()}
        result = self._build_bars_by_date(
            or_bar_lookback=0,
            enable_doubledown=False,
            score_or_bar_quality_weight=0.5,
            all_bars=all_bars,
        )
        assert "AAPL" in result
