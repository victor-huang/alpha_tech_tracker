import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import SignalEvent
from alpha_tech_tracker.op_momentum_strategy.regime_engine import (
    RegimeEngine,
    RegimeState,
)
from alpha_tech_tracker.op_momentum_strategy.trade_engine import (
    OpMomentumTradeEngine,
    WinRateTickerSelector,
)

ET = pytz.timezone("America/New_York")

_D = Decimal


def _regime_state(direction="LONG", hold_window="EOD", regime_type="Rising Bull"):
    return RegimeState(
        direction=direction,
        hold_window=hold_window,
        regime_type=regime_type,
        source="rolling_confirmed",
        notes="test",
    )


def _make_client():
    client = MagicMock()
    client._api_key = "k"
    client._secret_key = "s"
    client._option_data_client = MagicMock()
    client.get_accounts.return_value = {"buying_power": 50000}
    return client


def _minimal_ticker_df(today=None):
    today = today or date(2026, 5, 29)
    ts = ET.localize(datetime.combine(today, datetime.min.time().replace(hour=9, minute=40)))
    return pd.DataFrame({"Close": [100.0], "Volume": [1_000_000]}, index=pd.DatetimeIndex([ts]))


# ─── WinRateTickerSelector ────────────────────────────────────────────────────

class TestWinRateTickerSelector:
    def test_select_long_returns_top_n(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={
                "AAPL": _minimal_ticker_df(),
                "TSLA": _minimal_ticker_df(),
                "NVDA": _minimal_ticker_df(),
            },
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._rank_tickers_by_eod_win_rate",
            return_value=[
                ("AAPL", {"win_rates": {None: 70}}),
                ("NVDA", {"win_rates": {None: 65}}),
                ("TSLA", {"win_rates": {None: 55}}),
            ],
        )
        sel = WinRateTickerSelector(tickers=["AAPL", "TSLA", "NVDA"], top_n=2)
        ticker_dfs = sel.fetch_bars()
        result = sel.select(ticker_dfs, direction="LONG")
        assert result == ["AAPL", "NVDA"]

    def test_select_short_returns_bottom_n(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={
                "AAPL": _minimal_ticker_df(),
                "TSLA": _minimal_ticker_df(),
                "NVDA": _minimal_ticker_df(),
            },
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._rank_tickers_by_eod_win_rate",
            return_value=[
                ("AAPL", {"win_rates": {None: 70}}),
                ("NVDA", {"win_rates": {None: 65}}),
                ("TSLA", {"win_rates": {None: 55}}),
            ],
        )
        sel = WinRateTickerSelector(tickers=["AAPL", "TSLA", "NVDA"], top_n=2)
        ticker_dfs = sel.fetch_bars()
        result = sel.select(ticker_dfs, direction="SHORT")
        # bottom-2 by EOD WR = TSLA (55%) and NVDA (65%)
        assert result == ["TSLA", "NVDA"]

    def test_select_default_direction_is_long(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={"AAPL": _minimal_ticker_df()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._rank_tickers_by_eod_win_rate",
            return_value=[("AAPL", {"win_rates": {None: 70}})],
        )
        sel = WinRateTickerSelector(tickers=["AAPL"], top_n=1)
        result = sel.select(sel.fetch_bars())
        assert result == ["AAPL"]

    def test_rolling_stats_populated_after_select(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={"AAPL": _minimal_ticker_df()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._rank_tickers_by_eod_win_rate",
            return_value=[("AAPL", {"win_rates": {None: 70}})],
        )
        sel = WinRateTickerSelector(tickers=["AAPL"], top_n=1)
        sel.select(sel.fetch_bars())
        assert "AAPL" in sel.rolling_stats
        assert sel.rolling_stats["AAPL"]["ev_trade"] == 1.0


# ─── Direction filter in _on_signal_for_window ───────────────────────────────

class TestDirectionFilter:
    def _make_engine_with_regime(self, regime_direction, tmpdir):
        client = _make_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_regime_engine=True,
            regime_data_dir=tmpdir,
        )
        engine._current_regime = _regime_state(regime_direction)
        # Minimal window state so _on_signal_for_window can run
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": ET.localize(datetime(2026, 5, 29, 9, 45)),
            "open_position_count": 0,
            "capital_fraction": 1.0,
            "drain_timer_scheduled": False,
        }
        return engine

    def _make_event(self, signal="BULLISH", ticker="AAPL"):
        return SignalEvent(
            ticker=ticker,
            signal=signal,
            entry_price=_D("100"),
            stock_price=_D("100"),
            or_high=_D("102"),
            or_low=_D("98"),
            or_range=_D("4"),
            ma50_at_signal=_D("99"),
        )

    def test_bullish_buffered_in_long_regime(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 40)),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._make_engine_with_regime("LONG", tmpdir)
            engine._on_signal_for_window("W1", self._make_event("BULLISH"))
        assert "AAPL" in engine._window_state["W1"]["pending_signals"]

    def test_bullish_blocked_in_short_regime(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 40)),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._make_engine_with_regime("SHORT", tmpdir)
            engine._on_signal_for_window("W1", self._make_event("BULLISH"))
        assert "AAPL" not in engine._window_state["W1"]["pending_signals"]

    def test_bearish_blocked_in_long_regime(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 40)),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._make_engine_with_regime("LONG", tmpdir)
            engine._on_signal_for_window("W1", self._make_event("BEARISH"))
        assert "AAPL" not in engine._window_state["W1"]["pending_signals"]

    def test_signal_blocked_in_no_position_regime(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 40)),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._make_engine_with_regime("NO_POSITION", tmpdir)
            engine._on_signal_for_window("W1", self._make_event("BULLISH"))
        assert "AAPL" not in engine._window_state["W1"]["pending_signals"]

    def test_bullish_passes_in_neutral_regime(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 40)),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._make_engine_with_regime("NEUTRAL", tmpdir)
            engine._on_signal_for_window("W1", self._make_event("BULLISH"))
        assert "AAPL" in engine._window_state["W1"]["pending_signals"]

    def test_no_filter_when_regime_engine_disabled(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 40)),
        )
        client = _make_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_regime_engine=False,
        )
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": ET.localize(datetime(2026, 5, 29, 9, 45)),
            "open_position_count": 0,
            "capital_fraction": 1.0,
            "drain_timer_scheduled": False,
        }
        engine._on_signal_for_window("W1", self._make_event("BULLISH"))
        assert "AAPL" in engine._window_state["W1"]["pending_signals"]


# ─── Regime engine called in _run_window_selectors ───────────────────────────

class TestRunWindowSelectorsRegime:
    def test_compute_and_add_metrics_called_when_regime_engine_enabled(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 20)),
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={"AAPL": _minimal_ticker_df()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.select_top_n",
            return_value={"picks": [{"ticker": "AAPL", "score": 1.0, "ev_trade": 1.0}],
                          "rolling_stats": {}, "dynamic_ev_gate_state": None,
                          "direction_split_ev_state": None, "scoring_context": {}},
        )
        mock_compute = mocker.patch.object(RegimeEngine, "compute_and_add_metrics", return_value=None)
        mocker.patch.object(
            RegimeEngine, "get_current_regime",
            return_value=_regime_state("LONG"),
        )
        mocker.patch.object(RegimeEngine, "summary_str", return_value="Regime: LONG | Hold: EOD [Rising Bull]")
        with tempfile.TemporaryDirectory() as tmpdir:
            client = _make_client()
            engine = OpMomentumTradeEngine(
                alpaca_client=client,
                mock_trade_execution=True,
                enable_regime_engine=True,
                regime_data_dir=tmpdir,
            )
            engine._run_window_selectors(["AAPL"])
        mock_compute.assert_called_once()

    def test_regime_engine_not_called_when_disabled(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 20)),
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={"AAPL": _minimal_ticker_df()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.select_top_n",
            return_value={"picks": [{"ticker": "AAPL", "score": 1.0, "ev_trade": 1.0}],
                          "rolling_stats": {}, "dynamic_ev_gate_state": None,
                          "direction_split_ev_state": None, "scoring_context": {}},
        )
        mock_compute = mocker.patch.object(RegimeEngine, "compute_and_add_metrics", return_value=None)
        client = _make_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_regime_engine=False,
        )
        engine._run_window_selectors(["AAPL"])
        mock_compute.assert_not_called()


# ─── Selector type switching ─────────────────────────────────────────────────

class TestSelectorType:
    def test_score_rank_uses_ticker_selector(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 20)),
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={"AAPL": _minimal_ticker_df()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.select_top_n",
            return_value={"picks": [{"ticker": "AAPL", "score": 1.0, "ev_trade": 1.0}],
                          "rolling_stats": {}, "dynamic_ev_gate_state": None,
                          "direction_split_ev_state": None, "scoring_context": {}},
        )
        from alpha_tech_tracker.op_momentum_strategy.trade_engine import TickerSelector
        spy = mocker.patch.object(TickerSelector, "select", return_value=["AAPL"])
        client = _make_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            selector_type="score-rank",
        )
        engine._run_window_selectors(["AAPL"])
        spy.assert_called_once()

    def test_win_rate_uses_win_rate_selector(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 20)),
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={"AAPL": _minimal_ticker_df()},
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._rank_tickers_by_eod_win_rate",
            return_value=[("AAPL", {"win_rates": {None: 0.65}})],
        )
        from alpha_tech_tracker.op_momentum_strategy.trade_engine import WinRateTickerSelector
        spy = mocker.patch.object(WinRateTickerSelector, "select", return_value=["AAPL"])
        client = _make_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            selector_type="win-rate",
        )
        engine._run_window_selectors(["AAPL"])
        spy.assert_called_once()

    def test_win_rate_rolling_stats_populated_for_drain(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars",
            return_value={
                "AAPL": _minimal_ticker_df(),
                "TSLA": _minimal_ticker_df(),
            },
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._rank_tickers_by_eod_win_rate",
            return_value=[
                ("AAPL", {"win_rates": {None: 0.70}}),
                ("TSLA", {"win_rates": {None: 0.55}}),
            ],
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 20)),
        )
        sel = WinRateTickerSelector(tickers=["AAPL", "TSLA"], top_n=2)
        sel.select(sel.fetch_bars(), direction="LONG")
        assert "AAPL" in sel.rolling_stats
        assert "TSLA" in sel.rolling_stats
        assert sel.rolling_stats["AAPL"]["ev_trade"] == 1.0


# ─── Timed exit wired into positions at entry ─────────────────────────────────

class TestTimedExitWiredOnEntry:
    def test_timed_exit_minutes_set_when_regime_hold_active(self, mocker):
        """_HOLD_WINDOW_MINUTES maps regime hold_window to minutes on ActivePosition."""
        from alpha_tech_tracker.op_momentum_strategy.trade_engine import _HOLD_WINDOW_MINUTES
        assert _HOLD_WINDOW_MINUTES["+15m"] == 15
        assert _HOLD_WINDOW_MINUTES["+1h"] == 60
        assert _HOLD_WINDOW_MINUTES["EOD"] is None

    def test_active_position_gets_timed_exit_from_regime(self, mocker):
        """_enter_stock_position propagates regime hold_window → ActivePosition.timed_exit_minutes."""
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 46)),
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.place_stock_order",
            return_value={"order_id": "sim-stock-AAPL", "status": "simulated"},
        )
        captured = []

        def _capture_position(pos):
            captured.append(pos)

        with tempfile.TemporaryDirectory() as tmpdir:
            client = _make_client()
            engine = OpMomentumTradeEngine(
                alpaca_client=client,
                mock_trade_execution=True,
                enable_regime_engine=True,
                regime_hold=True,
                disable_ma_stops_for_regime_hold=True,
                regime_data_dir=tmpdir,
            )
            engine._current_regime = _regime_state(direction="LONG", hold_window="+1h")
            from unittest.mock import MagicMock
            monitor = MagicMock()
            monitor.add_position.side_effect = _capture_position
            engine._monitor = monitor

            event = SignalEvent(
                ticker="AAPL",
                signal="BULLISH",
                entry_price=_D("150"),
                stock_price=_D("150"),
                or_high=_D("152"),
                or_low=_D("148"),
                or_range=_D("4"),
                ma50_at_signal=_D("149"),
            )
            engine._enter_stock_position(
                event=event,
                rank=0,
                window_label="W1",
                window_budget=_D("10000"),
                capital_weight=_D("0.5"),
                bull_hard_stop=_D("147"),
                bear_hard_stop=_D("153"),
                bull_fallback=_D("148.8"),
                bear_fallback=_D("151.2"),
                entry_bar_time=None,
            )

        assert len(captured) == 1
        pos = captured[0]
        assert pos.timed_exit_minutes == 60
        assert pos.disable_ma_stop is True

    def test_active_position_no_timed_exit_when_regime_hold_disabled(self, mocker):
        """With regime_hold=False, timed_exit_minutes is always None regardless of regime."""
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
            return_value=ET.localize(datetime(2026, 5, 29, 9, 46)),
        )
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.place_stock_order",
            return_value={"order_id": "sim-stock-AAPL", "status": "simulated"},
        )
        captured = []

        with tempfile.TemporaryDirectory() as tmpdir:
            client = _make_client()
            engine = OpMomentumTradeEngine(
                alpaca_client=client,
                mock_trade_execution=True,
                enable_regime_engine=True,
                regime_hold=False,
                regime_data_dir=tmpdir,
            )
            engine._current_regime = _regime_state(direction="LONG", hold_window="+1h")
            from unittest.mock import MagicMock
            monitor = MagicMock()
            monitor.add_position.side_effect = lambda pos: captured.append(pos)
            engine._monitor = monitor

            event = SignalEvent(
                ticker="AAPL",
                signal="BULLISH",
                entry_price=_D("150"),
                stock_price=_D("150"),
                or_high=_D("152"),
                or_low=_D("148"),
                or_range=_D("4"),
                ma50_at_signal=_D("149"),
            )
            engine._enter_stock_position(
                event=event,
                rank=0,
                window_label="W1",
                window_budget=_D("10000"),
                capital_weight=_D("0.5"),
                bull_hard_stop=_D("147"),
                bear_hard_stop=_D("153"),
                bull_fallback=_D("148.8"),
                bear_fallback=_D("151.2"),
                entry_bar_time=None,
            )

        assert len(captured) == 1
        assert captured[0].timed_exit_minutes is None
        assert captured[0].disable_ma_stop is False
