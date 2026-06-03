import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _passes_regime_filter,
    _regime_hold_line,
    run_live,
)
from alpha_tech_tracker.op_momentum_strategy.regime_engine import (
    RegimeEngine,
    RegimeState,
)

ET = pytz.timezone("America/New_York")


def _state(direction="LONG", hold_window="EOD", regime_type="Rising Bull", source="rolling_confirmed"):
    return RegimeState(
        direction=direction,
        hold_window=hold_window,
        regime_type=regime_type,
        source=source,
        notes="test note",
    )


def _bull_sig(ticker="AAPL"):
    return {"ticker": ticker, "direction": "BULL", "signal_bar_time": "09:40", "date": "2026-05-29"}


def _bear_sig(ticker="TSLA"):
    return {"ticker": ticker, "direction": "BEAR", "signal_bar_time": "09:40", "date": "2026-05-29"}


# ─── _passes_regime_filter ────────────────────────────────────────────────────

class TestPassesRegimeFilter:
    def test_bull_signal_passes_in_long_regime(self):
        assert _passes_regime_filter(_bull_sig(), _state("LONG")) is True

    def test_bear_signal_passes_in_short_regime(self):
        assert _passes_regime_filter(_bear_sig(), _state("SHORT")) is True

    def test_bull_signal_blocked_in_short_regime(self):
        assert _passes_regime_filter(_bull_sig(), _state("SHORT")) is False

    def test_bear_signal_blocked_in_long_regime(self):
        assert _passes_regime_filter(_bear_sig(), _state("LONG")) is False

    def test_bull_signal_blocked_in_no_position_regime(self):
        assert _passes_regime_filter(_bull_sig(), _state("NO_POSITION")) is False

    def test_bear_signal_blocked_in_no_position_regime(self):
        assert _passes_regime_filter(_bear_sig(), _state("NO_POSITION")) is False

    def test_bull_signal_passes_in_neutral_regime(self):
        assert _passes_regime_filter(_bull_sig(), _state("NEUTRAL")) is True

    def test_bear_signal_passes_in_neutral_regime(self):
        assert _passes_regime_filter(_bear_sig(), _state("NEUTRAL")) is True


# ─── _regime_hold_line ────────────────────────────────────────────────────────

class TestRegimeHoldLine:
    def test_returns_hold_line_with_window_and_type(self):
        line = _regime_hold_line(_state("LONG", "+15m", "AM Pop-Fade"))
        assert "Hold: +15m" in line
        assert "AM Pop-Fade" in line

    def test_returns_eod_hold_line(self):
        line = _regime_hold_line(_state("LONG", "EOD", "Rising Bull"))
        assert "Hold: EOD" in line
        assert "Rising Bull" in line

    def test_returns_empty_string_when_no_hold_window(self):
        line = _regime_hold_line(_state("NO_POSITION", "", "Seasonal Default"))
        assert line == ""

    def test_returns_empty_string_for_neutral_with_no_window(self):
        line = _regime_hold_line(_state("NEUTRAL", "", "Seasonal Default"))
        assert line == ""


# ─── run_live() regime integration ───────────────────────────────────────────

def _make_market_data_client(today, or_start="09:30"):
    """Minimal mock market_data_client returning one bar past OR close."""
    client = MagicMock()
    bar_time = ET.localize(
        datetime.combine(today, datetime.strptime("09:45", "%H:%M").time())
    )
    df = pd.DataFrame(
        {"Open": [100.0], "High": [102.0], "Low": [99.0], "Close": [101.0], "Volume": [1_000_000]},
        index=pd.DatetimeIndex([bar_time]),
    )
    client.fetch_bars.return_value = {"AAPL": df, "QQQ": df.copy()}
    return client


def _past_or_close_time(today, or_bars=2, or_start="09:30"):
    """Return a time 1 minute after OR closes for the given or_bars."""
    base = datetime.combine(today, datetime.strptime(or_start, "%H:%M").time())
    return ET.localize(base + timedelta(minutes=or_bars * 5 + 1))


class TestRunLiveRegimeEngineStartup:
    def test_compute_and_add_metrics_called_at_startup(self, mocker):
        today = date(2026, 5, 29)
        yesterday = today - timedelta(days=1)
        mock_compute = mocker.patch.object(RegimeEngine, "compute_and_add_metrics", return_value=None)
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_bars",
            return_value={"AAPL": pd.DataFrame(), "QQQ": pd.DataFrame()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_daily_bars",
            return_value={},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._now_et",
            return_value=ET.localize(datetime.combine(today, datetime.strptime("16:01", "%H:%M").time())),
        )
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.time.sleep")

        client = _make_market_data_client(today)
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                run_live(
                    ["AAPL"],
                    market_data_client=client,
                    dry_run=True,
                    enable_regime_engine=True,
                    regime_data_dir=tmpdir,
                    _stop_after_iterations=1,
                )
            except StopIteration:
                pass

        mock_compute.assert_called_once()
        call_kwargs = mock_compute.call_args
        assert call_kwargs[0][1] == yesterday or call_kwargs[1].get("target_date") == yesterday

    def test_regime_engine_not_instantiated_when_disabled(self, mocker):
        today = date(2026, 5, 29)
        # RegimeEngine is lazily imported inside run_live; patch its compute method
        # which would be called if the engine were active
        mock_compute = mocker.patch.object(RegimeEngine, "compute_and_add_metrics")
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_bars",
            return_value={"AAPL": pd.DataFrame(), "QQQ": pd.DataFrame()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_daily_bars",
            return_value={},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._now_et",
            return_value=ET.localize(datetime.combine(today, datetime.strptime("16:01", "%H:%M").time())),
        )
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.time.sleep")

        client = _make_market_data_client(today)
        try:
            run_live(
                ["AAPL"],
                market_data_client=client,
                dry_run=True,
                enable_regime_engine=False,
                _stop_after_iterations=1,
            )
        except StopIteration:
            pass

        mock_compute.assert_not_called()


class TestRunLiveDirectionFilter:
    def _run_with_signal(self, mocker, regime_direction, signal_direction):
        """Run one loop iteration that produces one signal; return _notify call args."""
        today = date(2026, 5, 29)
        now_past_or = _past_or_close_time(today, or_bars=2)

        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_bars",
            return_value={"AAPL": pd.DataFrame(), "QQQ": pd.DataFrame()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_daily_bars",
            return_value={},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._now_et",
            return_value=now_past_or,
        )
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.time.sleep")
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.compute_or_ma_signals",
            return_value=[{"ticker": "AAPL", "direction": signal_direction,
                           "signal_bar_time": "09:40", "date": str(today),
                           "close": 101.0, "or_mid": 100.0, "overlapping_mas": ["MA20"],
                           "or_high": 102.0, "or_low": 99.0, "or_range": 3.0,
                           "ma20_5m": 100.0, "ma50_5m": 99.0, "ma200_5m": 98.0,
                           "collection_vol": 1000000, "vol_20day_avg": 800000,
                           "daily_ma20": 100.0, "daily_ma50": 99.0, "daily_ma200": 98.0,
                           "prev_close": 100.5, "qqq_vol_ratio": 1.1, "qqq_regime": "Bullish"}],
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._compute_hold_history",
            return_value=None,
        )
        regime = _state(regime_direction, "+15m" if regime_direction != "LONG" else "EOD")
        mocker.patch.object(RegimeEngine, "compute_and_add_metrics", return_value=None)
        mocker.patch.object(RegimeEngine, "get_current_regime", return_value=regime)
        mock_notify = mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._notify"
        )

        client = _make_market_data_client(today)
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                run_live(
                    ["AAPL"],
                    or_bars=2,
                    market_data_client=client,
                    dry_run=False,
                    enable_regime_engine=True,
                    regime_data_dir=tmpdir,
                    _stop_after_iterations=1,
                )
            except StopIteration:
                pass
        return mock_notify.call_args_list

    def test_bull_signal_sent_when_regime_long(self, mocker):
        calls = self._run_with_signal(mocker, "LONG", "BULL")
        sms_texts = [str(c) for c in calls]
        assert any("AAPL" in t for t in sms_texts)

    def test_bull_signal_suppressed_when_regime_short(self, mocker):
        calls = self._run_with_signal(mocker, "SHORT", "BULL")
        sms_texts = [str(c) for c in calls]
        assert not any("AAPL" in t and "BULL" in t for t in sms_texts)

    def test_bear_signal_suppressed_when_regime_long(self, mocker):
        calls = self._run_with_signal(mocker, "LONG", "BEAR")
        sms_texts = [str(c) for c in calls]
        assert not any("AAPL" in t and "BEAR" in t for t in sms_texts)

    def test_signal_suppressed_in_no_position_regime(self, mocker):
        calls = self._run_with_signal(mocker, "NO_POSITION", "BULL")
        sms_texts = [str(c) for c in calls]
        assert not any("AAPL" in t and "BULL" in t for t in sms_texts)

    def test_signal_passes_in_neutral_regime(self, mocker):
        calls = self._run_with_signal(mocker, "NEUTRAL", "BULL")
        sms_texts = [str(c) for c in calls]
        assert any("AAPL" in t for t in sms_texts)


class TestRunLiveHoldAnnotation:
    def test_hold_annotation_appended_to_signal_sms(self, mocker):
        today = date(2026, 5, 29)
        now_past_or = _past_or_close_time(today, or_bars=2)

        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_bars",
            return_value={"AAPL": pd.DataFrame(), "QQQ": pd.DataFrame()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_daily_bars",
            return_value={},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._now_et",
            return_value=now_past_or,
        )
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.time.sleep")
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.compute_or_ma_signals",
            return_value=[{"ticker": "AAPL", "direction": "BULL",
                           "signal_bar_time": "09:40", "date": str(today),
                           "close": 101.0, "or_mid": 100.0, "overlapping_mas": ["MA20"],
                           "or_high": 102.0, "or_low": 99.0, "or_range": 3.0,
                           "ma20_5m": 100.0, "ma50_5m": 99.0, "ma200_5m": 98.0,
                           "collection_vol": 1000000, "vol_20day_avg": 800000,
                           "daily_ma20": 100.0, "daily_ma50": 99.0, "daily_ma200": 98.0,
                           "prev_close": 100.5, "qqq_vol_ratio": 1.1, "qqq_regime": "Bullish"}],
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._compute_hold_history",
            return_value=None,
        )
        regime = _state("LONG", "+15m", "AM Pop-Fade")
        mocker.patch.object(RegimeEngine, "compute_and_add_metrics", return_value=None)
        mocker.patch.object(RegimeEngine, "get_current_regime", return_value=regime)
        mock_notify = mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._notify"
        )

        client = _make_market_data_client(today)
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                run_live(
                    ["AAPL"],
                    or_bars=2,
                    market_data_client=client,
                    dry_run=False,
                    enable_regime_engine=True,
                    regime_data_dir=tmpdir,
                    _stop_after_iterations=1,
                )
            except StopIteration:
                pass

        all_sms = " ".join(str(c) for c in mock_notify.call_args_list)
        assert "Hold: +15m" in all_sms
        assert "AM Pop-Fade" in all_sms


class TestRunLivePresessionRegimeSms:
    def test_regime_state_included_in_presession_sms(self, mocker):
        today = date(2026, 5, 29)
        presession_time = ET.localize(
            datetime.combine(today, datetime.strptime("09:25", "%H:%M").time())
        )

        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_bars",
            return_value={"AAPL": pd.DataFrame(), "QQQ": pd.DataFrame()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.fetch_daily_bars",
            return_value={},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._now_et",
            return_value=presession_time,
        )
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener.time.sleep")
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._rank_tickers_by_eod_win_rate",
            return_value=[],
        )
        regime = _state("SHORT", "+15m", "Persistent Bear", "rolling_confirmed")
        mocker.patch.object(RegimeEngine, "compute_and_add_metrics", return_value=None)
        mocker.patch.object(RegimeEngine, "get_current_regime", return_value=regime)
        mocker.patch.object(RegimeEngine, "summary_str", return_value="Regime: SHORT | Hold: +15m [Persistent Bear]")
        mock_notify = mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener._notify"
        )

        client = _make_market_data_client(today)
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                run_live(
                    ["AAPL"],
                    market_data_client=client,
                    dry_run=False,
                    enable_regime_engine=True,
                    regime_data_dir=tmpdir,
                    _stop_after_iterations=1,
                )
            except StopIteration:
                pass

        all_sms = " ".join(str(c) for c in mock_notify.call_args_list)
        assert "SHORT" in all_sms
        assert "+15m" in all_sms
