import threading
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.config import (
    MAX_ACTIVE_SYMBOLS,

)
from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    ITMOptionContractSelector,
    TimePremiumContractSelector,
)
from alpha_tech_tracker.op_momentum_strategy.models import ReentryWatcher
from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import (
    _build_contract_selector,
)
from alpha_tech_tracker.op_momentum_strategy.trade_engine import (
    OpMomentumTradeEngine,
    TickerSelector,
)

from conftest import _D, _make_active_position, _make_alpaca_client

ET = pytz.timezone("America/New_York")

_SELECT_TOP_N_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.select_top_n"
_FETCH_BARS_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars"
_SCORE_TICKER_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.score_ticker"
_OPTION_CONTRACT_SELECTOR_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.ITMOptionContractSelector.select"
)
_POSITION_SIZER_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.PositionSizer.compute"
)
_PLACE_ENTRY_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.OpMomentumTradeEngine._place_entry"


def _make_signal_event(
    ticker="NVDA", signal="BULLISH", entry=105.0, or_high=107.0, or_low=97.0
):
    from alpha_tech_tracker.op_momentum_strategy.models import SignalEvent

    or_range = _D(str(or_high)) - _D(str(or_low))
    return SignalEvent(
        ticker=ticker,
        signal=signal,
        entry_price=_D(str(entry)),
        stock_price=_D(str(entry)),
        or_high=_D(str(or_high)),
        or_low=_D(str(or_low)),
        or_range=or_range,
        ma50_at_signal=_D("100"),
    )


def _make_engine_with_mock_client():
    client = _make_alpaca_client()
    engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)
    return engine


class TestTickerSelector:
    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_returns_top_n_tickers_by_composite_score(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = {
            "picks": [
                {"ticker": "NVDA", "signal": "BULLISH", "score": 4.2, "ev_trade": 0.8},
                {"ticker": "CRWD", "signal": "BEARISH", "score": 3.1, "ev_trade": 0.5},
            ],
            "no_signal": ["COIN"],
            "negative_ev": [],
            "rolling_stats": {
                "NVDA": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
                "CRWD": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.5},
            },
        }

        selector = TickerSelector(tickers=["NVDA", "CRWD", "COIN"], top_n=2)
        result = selector.select()

        assert result == ["NVDA", "CRWD"]
        assert "NVDA" in selector.rolling_stats
        mock_fetch_bars.assert_called_once()
        mock_select_top_n.assert_called_once()

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_falls_back_to_previous_day_when_today_has_no_picks(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        fallback_stats = {
            "NVDA": {"ev_trade": 0.6, "win_rate": 0.55, "avg_win_pct": 1.8}
        }
        mock_select_top_n.side_effect = [
            {
                "picks": [],
                "no_signal": ["NVDA", "CRWD"],
                "negative_ev": [],
                "rolling_stats": {},
            },
            {
                "picks": [
                    {
                        "ticker": "NVDA",
                        "signal": "BULLISH",
                        "score": 3.0,
                        "ev_trade": 0.6,
                    }
                ],
                "no_signal": ["CRWD"],
                "negative_ev": [],
                "rolling_stats": fallback_stats,
            },
        ]

        selector = TickerSelector(tickers=["NVDA", "CRWD"], top_n=2)
        result = selector.select()

        assert result == ["NVDA"]
        assert selector.rolling_stats == fallback_stats
        mock_fetch_bars.assert_called_once()
        assert mock_select_top_n.call_count == 2


class TestSignalBuffer:
    def test_on_signal_buffers_when_before_deadline(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) + timedelta(minutes=5)

        event = _make_signal_event("NVDA")
        engine._on_signal_for_window("W1", event)

        assert "NVDA" in engine._window_state["W1"]["pending_signals"]
        assert engine._window_state["W1"]["open_position_count"] == 0

    def test_on_signal_overwrites_earlier_signal_for_same_ticker(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) + timedelta(minutes=5)

        engine._on_signal_for_window("W1", _make_signal_event("AMD", entry=100.0))
        engine._on_signal_for_window("W1", _make_signal_event("AMD", entry=102.0))

        assert len(engine._window_state["W1"]["pending_signals"]) == 1
        assert (
            float(engine._window_state["W1"]["pending_signals"]["AMD"].entry_price)
            == 102.0
        )

    def test_on_signal_skips_when_max_positions_reached_after_deadline(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(minutes=1)
        engine._window_state["W1"]["open_position_count"] = MAX_ACTIVE_SYMBOLS

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._on_signal_for_window("W1", _make_signal_event("NVDA"))
            mock_enter.assert_not_called()

    def test_on_signal_calls_enter_position_after_deadline_when_slot_available(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(minutes=1)
        engine._window_state["W1"]["open_position_count"] = 0

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None):
            event = _make_signal_event("NVDA")
            engine._on_signal_for_window("W1", event)
            mock_enter.assert_called_once_with(
                event, rank=0, window_label="W1", window_budget=None
            )

        assert engine._window_state["W1"]["open_position_count"] == 1


class TestSignalSelectionLoop:
    def test_no_action_when_no_signals_buffered(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(seconds=1)

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop_for_window(engine._windows[0])
            mock_enter.assert_not_called()

    def test_skips_tickers_with_no_rolling_stats(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(seconds=1)
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA")
        }
        engine._rolling_stats = {}

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop_for_window(engine._windows[0])
            mock_enter.assert_not_called()

    def test_skips_tickers_with_negative_ev(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(seconds=1)
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA")
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": -0.1, "win_rate": 0.4, "avg_win_pct": 1.0}
        }

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop_for_window(engine._windows[0])
            mock_enter.assert_not_called()

    def test_enters_top_n_scored_signals(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(seconds=1)
        engine._window_state["W1"]["pending_signals"] = {
            "AMD": _make_signal_event("AMD", entry=105.0, or_high=107.0, or_low=97.0),
            "NVDA": _make_signal_event("NVDA", entry=106.0, or_high=108.0, or_low=96.0),
            "META": _make_signal_event("META", entry=104.0, or_high=106.0, or_low=98.0),
        }
        engine._rolling_stats = {
            "AMD": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 2.0},
            "NVDA": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 3.0},
            "META": {"ev_trade": 0.3, "win_rate": 0.45, "avg_win_pct": 1.5},
        }

        entered_tickers = []
        with patch.object(
            engine,
            "_enter_position",
            side_effect=lambda e, **kw: entered_tickers.append(e.ticker),
        ), patch.object(engine, "_get_window_budget", return_value=None):
            engine._signal_selection_loop_for_window(engine._windows[0])

        assert len(entered_tickers) == MAX_ACTIVE_SYMBOLS

    def test_respects_max_active_symbols_limit(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(seconds=1)
        engine._window_state["W1"]["open_position_count"] = MAX_ACTIVE_SYMBOLS
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA")
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 1.0, "win_rate": 0.6, "avg_win_pct": 3.0}
        }

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop_for_window(engine._windows[0])
            mock_enter.assert_not_called()


class TestRankWeightedSizing:
    def _make_engine(self, **kwargs):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True, **kwargs)
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        return engine

    def test_rank_weighted_sizing_off_passes_equal_fraction_to_sizer(self):
        engine = self._make_engine(rank_weights=None)

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))) as compute_mock, \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        # capital_weight = 1/top_n for equal sizing (default top_n=MAX_ACTIVE_SYMBOLS=2)
        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D("1") / _D(str(engine._top_n))

    def test_rank_weighted_sizing_on_passes_first_weight_for_rank_zero(self):
        engine = self._make_engine(rank_weights=[60, 40])

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))) as compute_mock, \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D("0.6")

    def test_rank_weighted_sizing_on_passes_second_weight_for_rank_one(self):
        engine = self._make_engine(rank_weights=[60, 40])

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))) as compute_mock, \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"), rank=1)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D("0.4")


class TestMultiWindowEngine:
    def _make_engine_with_windows(self, windows):
        pass

        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=windows,
        )
        return engine

    def test_window_state_initialized_for_each_window(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="13:15", opening_bars=1, is_sequential=True
            ),
        ]
        engine = self._make_engine_with_windows(windows)

        assert "M1" in engine._window_state
        assert "A1" in engine._window_state

    def test_window_state_contains_required_keys(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [WindowConfig(label="M1", opening_start="09:30", opening_bars=3)]
        engine = self._make_engine_with_windows(windows)

        state = engine._window_state["M1"]
        assert "pending_signals" in state
        assert "collection_deadline" in state
        assert "open_position_count" in state
        assert "capital_fraction" in state

    def test_single_window_defaults_to_w1_label(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

        assert "W1" in engine._window_state

    def test_get_window_budget_sequential_fallback_to_account_when_no_prior_capital(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="13:15", opening_bars=1, is_sequential=True
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        engine._client.get_accounts.return_value = {"buying_power": 15000.0}
        a1_win = next(w for w in engine._windows if w.label == "A1")

        result = engine._get_window_budget(a1_win)

        assert result == _D("15000")
        engine._client.get_accounts.assert_called_once()

    def test_get_window_budget_sequential_returns_none_when_account_query_fails(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="13:15", opening_bars=1, is_sequential=True
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        engine._client.get_accounts.side_effect = Exception("network error")
        a1_win = next(w for w in engine._windows if w.label == "A1")

        result = engine._get_window_budget(a1_win)

        assert result is None

    def test_get_window_budget_sequential_uses_prior_window_returned_capital(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="13:15", opening_bars=1, is_sequential=True
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        engine._window_returned["M1"] = _D("11500")
        a1_win = next(w for w in engine._windows if w.label == "A1")

        result = engine._get_window_budget(a1_win)

        assert result == _D("11500")
        engine._client.get_accounts.assert_not_called()

    def test_get_window_budget_returns_explicit_budget_for_first_group_window(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(
                label="M1", opening_start="09:30", opening_bars=3, capital_fraction=1.0
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        engine._client.get_accounts.return_value = {"buying_power": 20000.0}
        m1_win = engine._windows[0]

        result = engine._get_window_budget(m1_win)

        assert result == _D("20000") * _D("1.0")

    def test_get_window_budget_applies_capital_fraction(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(
                label="M1", opening_start="09:30", opening_bars=3, capital_fraction=0.6
            ),
            WindowConfig(
                label="M2", opening_start="09:30", opening_bars=1, capital_fraction=0.4
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        engine._client.get_accounts.return_value = {"buying_power": 10000.0}
        m1_win = engine._windows[0]

        result = engine._get_window_budget(m1_win)

        assert result == _D("10000") * _D("0.6")

    def test_signals_buffered_in_correct_window_state(self):
        from alpha_tech_tracker.op_momentum_strategy.models import (
            WindowConfig,
        )

        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="13:15", opening_bars=1, is_sequential=True
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        engine._window_state["M1"]["collection_deadline"] = datetime.now(
            ET
        ) + timedelta(minutes=5)
        engine._window_state["A1"]["collection_deadline"] = datetime.now(
            ET
        ) + timedelta(minutes=5)

        or_range = _D("10")
        event_m1 = _make_signal_event("NVDA")
        event_a1 = _make_signal_event("AMD")

        engine._on_signal_for_window("M1", event_m1)
        engine._on_signal_for_window("A1", event_a1)

        assert "NVDA" in engine._window_state["M1"]["pending_signals"]
        assert "AMD" not in engine._window_state["M1"]["pending_signals"]
        assert "AMD" in engine._window_state["A1"]["pending_signals"]
        assert "NVDA" not in engine._window_state["A1"]["pending_signals"]


class TestOnPositionClosed:
    def _make_engine(self):
        client = _make_alpaca_client()
        return OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

    def _make_closed_stock_pos(self, signal, entry, exit_, slot_capital, trailing_arm=None):
        pos = _make_active_position(signal=signal)
        pos.trade_type = "stock"
        pos.simulated_entry_mid = _D(str(entry))
        pos.simulated_exit_mid = _D(str(exit_))
        pos.slot_capital = _D(str(slot_capital))
        pos.trailing_arm_price = _D(str(trailing_arm)) if trailing_arm else None
        pos.window_label = "M1"
        return pos

    def test_primary_bullish_adds_slot_capital_plus_pnl(self):
        engine = self._make_engine()
        pos = self._make_closed_stock_pos("BULLISH", entry=100, exit_=110, slot_capital=5000)

        engine._on_position_closed(pos)

        # returned = 5000 + 5000/100 * 10 = 5000 + 500 = 5500
        assert engine._window_returned["M1"] == _D("5500")

    def test_primary_bearish_adds_slot_capital_plus_pnl(self):
        engine = self._make_engine()
        pos = self._make_closed_stock_pos("BEARISH", entry=200, exit_=185, slot_capital=5000)

        engine._on_position_closed(pos)

        # returned = 5000 + 5000/200 * 15 = 5000 + 375 = 5375
        assert engine._window_returned["M1"] == _D("5375")

    def test_primary_losing_trade_returns_less_than_slot_capital(self):
        engine = self._make_engine()
        pos = self._make_closed_stock_pos("BULLISH", entry=100, exit_=95, slot_capital=5000)

        engine._on_position_closed(pos)

        # returned = 5000 + 5000/100 * (-5) = 5000 - 250 = 4750
        assert engine._window_returned["M1"] == _D("4750")

    def test_reentry_adds_only_cap_pnl_not_slot_capital(self):
        engine = self._make_engine()
        pos = self._make_closed_stock_pos(
            "BULLISH", entry=102, exit_=108, slot_capital=5000, trailing_arm=115
        )

        engine._on_position_closed(pos)

        # Re-entry: returned = cap_pnl only = 5000/102 * 6 ≈ 294.12
        expected = _D(str(5000)) / _D("102") * _D("6")
        assert engine._window_returned["M1"] == expected

    def test_primary_then_reentry_matches_backtest_available(self):
        """Combined primary + re-entry window_returned = slot_capital + all cap_pnls.

        With top_n=1 and slot_capital=5000, the backtest available for the next
        sequential window = 5000 (initial) + cap_pnl_primary + cap_pnl_reentry.
        The re-entry's principal (5000) must NOT be double-counted.
        """
        engine = self._make_engine()

        # Primary stops out: slot=5000, entry=100, exit=95 → cap_pnl=-250 → returned=4750
        primary = self._make_closed_stock_pos("BULLISH", entry=100, exit_=95, slot_capital=5000)
        engine._on_position_closed(primary)

        # Reversal re-entry wins: slot=5000, entry=102, exit=108 → cap_pnl=+294.12 → returned=294.12
        reentry = self._make_closed_stock_pos(
            "BULLISH", entry=102, exit_=108, slot_capital=5000, trailing_arm=115
        )
        engine._on_position_closed(reentry)

        # Expected = slot_capital + cap_pnl_primary + cap_pnl_reentry (re-entry principal not added again)
        cap_pnl_primary = _D("5000") / _D("100") * _D("-5")
        cap_pnl_reentry = _D("5000") / _D("102") * _D("6")
        expected = _D("5000") + cap_pnl_primary + cap_pnl_reentry
        assert engine._window_returned["M1"] == expected

    def test_skips_position_with_no_slot_capital(self):
        engine = self._make_engine()
        pos = _make_active_position()
        pos.slot_capital = None

        engine._on_position_closed(pos)

        assert engine._window_returned == {}


_NOTIFY_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._notify"


class TestEntryAlert:
    def _make_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        return engine

    def test_entry_alert_includes_readable_option_symbol(self):
        engine = self._make_engine()
        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        msg = mock_notify.call_args[0][0]
        assert "NVDA" in msg
        assert "Call" in msg
        assert "170" in msg

    def test_entry_alert_includes_entry_mid(self):
        engine = self._make_engine()
        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        msg = mock_notify.call_args[0][0]
        assert "8.50" in msg

    def test_entry_alert_includes_hard_stop_price(self):
        engine = self._make_engine()
        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA", or_high=107.0, or_low=97.0), rank=0)

        # hard_stop = or_high - stop_pct(0.15) * or_range(10) = 107 - 1.5 = 105.50
        msg = mock_notify.call_args[0][0]
        assert "stop" in msg
        assert "105.50" in msg

    def test_entry_alert_prefixed_with_simulate_in_mock_mode(self):
        engine = self._make_engine()
        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        msg = mock_notify.call_args[0][0]
        assert msg.startswith("[SIMULATE]")

    def test_entry_alert_includes_rank(self):
        engine = self._make_engine()
        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)
        assert "R1" in mock_notify.call_args[0][0]

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-2", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=2)
        assert "R3" in mock_notify.call_args[0][0]

    def test_entry_alert_shows_fill_price_in_live_mode(self):
        """Issue 2: live entry SMS shows the quote mid from the sizer, before order placement."""
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=False,
        )
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        engine._monitor = Mock()
        engine._monitor.add_position = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "live-1"}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        msg = mock_notify.call_args[0][0]
        assert "8.50" in msg
        assert "[SIMULATE]" not in msg

    def test_entry_alert_strike_not_shown_as_fill_price(self):
        """Issue 3: the option strike must appear as (k=$...) so it is not confused with fill."""
        engine = self._make_engine()
        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        msg = mock_notify.call_args[0][0]
        assert "(k=$170)" in msg
        assert "@ $170" not in msg


_COMPUTE_STOCK_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.PositionSizer.compute_stock"
)
_PLACE_STOCK_ORDER_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.place_stock_order"
)


class TestStockTradeEntry:
    def _make_stock_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            trade_type="stock",
        )
        from unittest.mock import Mock
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET) - timedelta(minutes=1),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        return engine

    def test_stock_entry_skips_option_contract_selector(self):
        engine = self._make_stock_engine()
        with patch(_COMPUTE_STOCK_PATH, return_value=(20, _D("100.00"))) as compute_mock, \
             patch(_OPTION_CONTRACT_SELECTOR_PATH) as selector_mock, \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"))

        selector_mock.assert_not_called()
        compute_mock.assert_called_once()

    def test_stock_entry_creates_position_with_trade_type_stock(self):
        engine = self._make_stock_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_COMPUTE_STOCK_PATH, return_value=(20, _D("100.00"))), \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"))

        assert len(captured_positions) == 1
        pos = captured_positions[0]
        assert pos.trade_type == "stock"
        assert pos.shares == 20
        assert pos.contracts == 0
        assert pos.option_symbol == ""

    def test_stock_entry_simulated_mid_uses_bar_price_in_replay_mode(self):
        engine = self._make_stock_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_COMPUTE_STOCK_PATH, return_value=(20, _D("99.50"))), \
             patch(_NOTIFY_PATH), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode", return_value=True):
            engine._enter_position(_make_signal_event("NVDA"))

        pos = captured_positions[0]
        assert pos.simulated_entry_mid == _D("105")

    def test_stock_entry_simulated_mid_uses_live_quote_in_mock_live_mode(self):
        engine = self._make_stock_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_COMPUTE_STOCK_PATH, return_value=(20, _D("99.50"))), \
             patch(_NOTIFY_PATH), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode", return_value=False):
            engine._enter_position(_make_signal_event("NVDA"))

        pos = captured_positions[0]
        assert pos.simulated_entry_mid == _D("99.50")

    def test_stock_entry_notify_message_shows_shares_not_contracts(self):
        engine = self._make_stock_engine()
        with patch(_COMPUTE_STOCK_PATH, return_value=(15, _D("100.00"))), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        msg = mock_notify.call_args[0][0]
        assert "15 shares" in msg
        assert "[SIMULATE]" in msg
        assert "R1" in msg

    def test_bullish_stock_entry_notify_says_buy(self):
        engine = self._make_stock_engine()
        with patch(_COMPUTE_STOCK_PATH, return_value=(10, _D("100.00"))), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA", signal="BULLISH"))

        msg = mock_notify.call_args[0][0]
        assert "BUY" in msg
        assert "SELL SHORT" not in msg

    def test_bearish_stock_entry_notify_says_sell_short(self):
        engine = self._make_stock_engine()
        with patch(_COMPUTE_STOCK_PATH, return_value=(10, _D("100.00"))), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA", signal="BEARISH"))

        msg = mock_notify.call_args[0][0]
        assert "SELL SHORT" in msg
        assert msg.count("BUY") == 0

    def test_options_entry_unchanged_when_trade_type_is_options(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            trade_type="options",
        )
        from unittest.mock import Mock
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET) - timedelta(minutes=1),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }

        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-opt-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"))

        assert len(captured_positions) == 1
        pos = captured_positions[0]
        assert pos.trade_type == "options"
        assert pos.contracts == 3
        assert pos.option_symbol == "NVDA260404C00170000"


class TestEnterReentry:
    def _make_watcher(self, reentry_type="reversal"):
        return ReentryWatcher(
            ticker="NVDA",
            reentry_type=reentry_type,
            primary_signal="BEARISH",
            or_high=_D("107"),
            or_low=_D("97"),
            or_range=_D("10"),
            midpoint=_D("102"),
            window_label="W1",
            rank=1,
            window_budget=_D("3000"),
        )

    def _make_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
        )
        engine._enter_position = Mock()
        return engine

    def test_reversal_calls_enter_position_with_bullish_signal(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="reversal")
        trigger = _D("108")

        engine._enter_reentry(watcher, trigger)

        call_kwargs = engine._enter_position.call_args
        event = call_kwargs[0][0]
        assert event.signal == "BULLISH"
        assert event.ticker == "NVDA"
        assert event.entry_price == trigger

    def test_reversal_passes_midpoint_as_hard_stop_override(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="reversal")
        trigger = _D("108")

        engine._enter_reentry(watcher, trigger)

        call_kwargs = engine._enter_position.call_args
        assert call_kwargs[1]["hard_stop_override"] == _D("102")

    def test_reversal_trailing_arm_is_trigger_plus_or_range(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="reversal")
        trigger = _D("108")

        engine._enter_reentry(watcher, trigger)

        call_kwargs = engine._enter_position.call_args
        assert call_kwargs[1]["trailing_arm_price"] == trigger + _D("10")

    def test_bearish_reentry_calls_enter_position_with_bearish_signal(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="bearish_reentry")
        trigger = _D("96")

        engine._enter_reentry(watcher, trigger)

        call_kwargs = engine._enter_position.call_args
        event = call_kwargs[0][0]
        assert event.signal == "BEARISH"
        assert event.entry_price == trigger

    def test_bearish_reentry_trailing_arm_is_trigger_minus_or_range(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="bearish_reentry")
        trigger = _D("96")

        engine._enter_reentry(watcher, trigger)

        call_kwargs = engine._enter_position.call_args
        assert call_kwargs[1]["trailing_arm_price"] == trigger - _D("10")

    def test_enter_reentry_passes_watcher_rank_and_window_label(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="reversal")

        engine._enter_reentry(watcher, _D("108"))

        call_kwargs = engine._enter_position.call_args
        assert call_kwargs[1]["rank"] == 1
        assert call_kwargs[1]["window_label"] == "W1"
        assert call_kwargs[1]["window_budget"] == _D("3000")


class TestBuildContractSelector:
    def _make_args(self, option_selector="standard", time_premium_pct_cap=0.01):
        args = Mock()
        args.option_selector = option_selector
        args.time_premium_pct_cap = time_premium_pct_cap
        return args

    def test_default_returns_option_contract_selector(self):
        client = _make_alpaca_client()
        selector = _build_contract_selector(self._make_args(), client)

        assert isinstance(selector, ITMOptionContractSelector)

    def test_time_premium_returns_time_premium_contract_selector(self):
        client = _make_alpaca_client()
        selector = _build_contract_selector(self._make_args(option_selector="time-premium"), client)

        assert isinstance(selector, TimePremiumContractSelector)

    def test_time_premium_forwards_pct_cap(self):
        client = _make_alpaca_client()
        selector = _build_contract_selector(
            self._make_args(option_selector="time-premium", time_premium_pct_cap=0.02),
            client,
        )

        assert selector._time_premium_pct_cap == _D("0.02")


class TestContractSelectorInjection:
    def _make_engine(self, contract_selector=None, **kwargs):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            contract_selector=contract_selector,
            **kwargs,
        )
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET) - timedelta(minutes=1),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        return engine

    def test_defaults_to_option_contract_selector_when_none_provided(self):
        engine = self._make_engine()

        assert isinstance(engine._contract_selector, ITMOptionContractSelector)

    def test_uses_injected_selector_instance(self):
        custom_selector = Mock()
        engine = self._make_engine(contract_selector=custom_selector)

        assert engine._contract_selector is custom_selector

    def test_injected_selector_is_called_on_options_entry(self):
        custom_selector = Mock()
        custom_selector.select.return_value = "NVDA260411C00170000"
        engine = self._make_engine(contract_selector=custom_selector)

        with patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode", return_value=False):
            engine._enter_position(_make_signal_event("NVDA"))

        custom_selector.select.assert_called_once_with("NVDA", "BULLISH", _D("105"))

    def test_replay_mode_uses_mock_selector_regardless_of_injected_selector(self):
        custom_selector = Mock()
        custom_selector.select.return_value = "NVDA260411C00170000"
        engine = self._make_engine(contract_selector=custom_selector)

        with patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode", return_value=True), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.MockContractSelector.select",
                   return_value="NVDA260411C00170000") as mock_select:
            engine._enter_position(_make_signal_event("NVDA"))

        custom_selector.select.assert_not_called()
        mock_select.assert_called_once()


# ---------------------------------------------------------------------------
# TickerSelector — replay mode bars_end
# ---------------------------------------------------------------------------

class TestTickerSelectorReplayMode:
    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_replay_mode_passes_yesterday_as_bars_end(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = {
            "picks": [{"ticker": "NVDA", "score": 1.0, "ev_trade": 0.5}],
            "no_signal": [],
            "negative_ev": [],
            "rolling_stats": {"NVDA": {}},
        }
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        today = date(2026, 4, 7)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=True,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
        ) as mock_now_et:
            mock_now_et.return_value = Mock()
            mock_now_et.return_value.date.return_value = today
            selector.select()

        call_args = mock_fetch_bars.call_args[0]
        assert call_args[2] == today - timedelta(days=1)
        assert "allow_intraday" not in mock_fetch_bars.call_args[1]

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_live_mode_passes_allow_intraday_true(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = {
            "picks": [{"ticker": "NVDA", "score": 1.0, "ev_trade": 0.5}],
            "no_signal": [],
            "negative_ev": [],
            "rolling_stats": {"NVDA": {}},
        }
        selector = TickerSelector(tickers=["NVDA"], top_n=1)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._safe_bars_end",
            return_value=date(2026, 4, 7),
        ):
            selector.select()

        assert mock_fetch_bars.call_args[1].get("allow_intraday") is True


# ---------------------------------------------------------------------------
# _on_position_closed — options formula
# ---------------------------------------------------------------------------

class TestOnPositionClosedOptions:
    def _make_engine(self):
        client = _make_alpaca_client()
        return OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

    def _make_closed_option_pos(self, signal, entry, exit_, contracts, slot_capital):
        pos = _make_active_position(signal=signal)
        pos.trade_type = "options"
        pos.simulated_entry_mid = _D(str(entry))
        pos.simulated_exit_mid = _D(str(exit_))
        pos.contracts = contracts
        pos.slot_capital = _D(str(slot_capital))
        pos.trailing_arm_price = None
        pos.window_label = "M1"
        return pos

    def test_options_win_returns_slot_capital_plus_contracts_times_100_times_pnl(self):
        engine = self._make_engine()
        pos = self._make_closed_option_pos(
            "BULLISH", entry=8.50, exit_=10.00, contracts=2, slot_capital=2000
        )

        engine._on_position_closed(pos)

        # cap_pnl = 2 * 100 * (10.00 - 8.50) = 300
        # returned = 2000 + 300 = 2300
        assert engine._window_returned["M1"] == _D("2300")

    def test_options_loss_returns_slot_capital_minus_loss(self):
        engine = self._make_engine()
        pos = self._make_closed_option_pos(
            "BEARISH", entry=5.00, exit_=3.50, contracts=3, slot_capital=1500
        )

        engine._on_position_closed(pos)

        # cap_pnl = 3 * 100 * (3.50 - 5.00) = -450
        # returned = 1500 + (-450) = 1050
        assert engine._window_returned["M1"] == _D("1050")


# ---------------------------------------------------------------------------
# _get_window_budget — open prior positions + undeployed capital
# ---------------------------------------------------------------------------

class TestGetWindowBudgetCapitalFlow:
    def _make_m1_a1_engine(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        client = _make_alpaca_client()
        return OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=[
                WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
                WindowConfig(
                    label="A1",
                    opening_start="13:15",
                    opening_bars=1,
                    is_sequential=True,
                ),
            ],
        )

    def test_sequential_budget_includes_still_open_prior_position_slot_capital(self):
        engine = self._make_m1_a1_engine()
        engine._window_returned["M1"] = _D("2000")

        open_pos = _make_active_position()
        open_pos.window_label = "M1"
        open_pos.is_closed = False
        open_pos.trailing_arm_price = None
        open_pos.slot_capital = _D("3333")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = [open_pos]
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        assert result == _D("5333")
        engine._client.get_accounts.assert_not_called()

    def test_sequential_budget_excludes_reentry_open_positions(self):
        """Re-entries share the primary's capital slot — their slot_capital must
        not be double-counted when computing the sequential window budget."""
        engine = self._make_m1_a1_engine()
        engine._window_returned["M1"] = _D("0")

        reentry_pos = _make_active_position()
        reentry_pos.window_label = "M1"
        reentry_pos.is_closed = False
        reentry_pos.trailing_arm_price = _D("110")  # marks as re-entry
        reentry_pos.slot_capital = _D("5000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = [reentry_pos]
        engine._monitor = mock_monitor

        engine._client.get_accounts.return_value = {"buying_power": 12000.0}
        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        # reentry slot not counted → prior_returned stays 0 → falls back to account
        assert result == _D("12000")

    def test_sequential_budget_forwards_undeployed_capital_from_prior_window(self):
        """When M1 deploys fewer slots than its budget allows, the undeployed
        portion flows forward to the sequential window."""
        engine = self._make_m1_a1_engine()
        engine._window_returned["M1"] = _D("3200")
        engine._window_primary_deployed["M1"] = _D("3333")
        engine._window_state["M1"]["budget"] = _D("10000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = []
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        # returned=3200 + undeployed(10000 - 3333)=6667 → 9867
        assert result == _D("9867")
        engine._client.get_accounts.assert_not_called()

    def test_sequential_budget_not_inflated_when_option_slots_fully_deployed(self):
        """When all M1 option slots are filled, no phantom undeployed capital
        must flow to A1.  Prior to the bug fix, _window_primary_deployed was
        never updated for option entries, so deployed=0 caused the full M1
        window_budget to be added as undeployed — inflating A1's budget."""
        engine = self._make_m1_a1_engine()
        m1_window_budget = _D("10000")
        # Two option positions fully deployed (top_n=2, equal sizing → capital_weight=1/2)
        slot_capital = m1_window_budget / _D("2")  # 5000 each
        engine._window_returned["M1"] = slot_capital * _D("2")  # 10000 returned
        engine._window_primary_deployed["M1"] = slot_capital * _D("2")  # 10000 deployed
        engine._window_state["M1"]["budget"] = m1_window_budget

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = []
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        # returned=10000 + undeployed(10000-10000)=0 → 10000
        # Must NOT be 10000 + 10000 = 20000 (the bug value when deployed was 0)
        assert result == _D("10000")


# ---------------------------------------------------------------------------
# _drain_pending_signals_for_window — rank ordering + budget storage
# ---------------------------------------------------------------------------

class TestDrainPendingSignals:
    def test_signals_entered_in_descending_score_order(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        # AMD inserted first, NVDA second — controls score_ticker call order
        engine._window_state["W1"]["pending_signals"] = {
            "AMD": _make_signal_event("AMD"),
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "AMD": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.0},
            "NVDA": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
        }

        rank_calls = []

        with patch(_SCORE_TICKER_PATH, side_effect=[1.5, 3.0]), \
             patch.object(
                 engine,
                 "_enter_position",
                 side_effect=lambda e, **kw: rank_calls.append((e.ticker, kw["rank"])),
             ), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        # NVDA scored 3.0 → rank=0; AMD scored 1.5 → rank=1
        assert rank_calls[0] == ("NVDA", 0)
        assert rank_calls[1] == ("AMD", 1)

    def test_window_budget_stored_in_window_state_after_drain(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA")
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.0}
        }

        with patch.object(engine, "_enter_position"), \
             patch.object(engine, "_get_window_budget", return_value=_D("8000")):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert engine._window_state["W1"].get("budget") == _D("8000")


# ---------------------------------------------------------------------------
# _enter_position failure paths — open_position_count must be decremented
# ---------------------------------------------------------------------------

class TestEnterPositionFailures:
    def _make_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        return engine

    def test_open_position_count_decremented_when_contract_selector_raises(self):
        engine = self._make_engine()
        engine._contract_selector = Mock()
        engine._contract_selector.select.side_effect = Exception("selector failure")
        engine._window_state["W1"]["open_position_count"] = 1

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            engine._enter_position(_make_signal_event("NVDA"), window_label="W1")

        assert engine._window_state["W1"]["open_position_count"] == 0

    def test_open_position_count_decremented_when_sizer_raises(self):
        engine = self._make_engine()
        engine._contract_selector = Mock()
        engine._contract_selector.select.return_value = "NVDA260411C00170000"
        engine._window_state["W1"]["open_position_count"] = 1

        with patch(_POSITION_SIZER_PATH, side_effect=Exception("sizer failure")), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
                 return_value=False,
             ):
            engine._enter_position(_make_signal_event("NVDA"), window_label="W1")

        assert engine._window_state["W1"]["open_position_count"] == 0


# ---------------------------------------------------------------------------
# _window_primary_deployed — primary vs re-entry tracking
# ---------------------------------------------------------------------------

class TestWindowPrimaryDeployed:
    def _make_stock_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            trade_type="stock",
            rank_weights=None,
            top_n=3,
        )
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        return engine

    def _make_option_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            trade_type="option",
            rank_weights=None,
        )
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._contract_selector = Mock()
        engine._contract_selector.select.return_value = "NVDA260411C00170000"
        return engine

    def test_option_primary_entry_updates_window_primary_deployed(self):
        """Option entries must track deployed capital so sequential window
        budgets can compute undeployed correctly — currently broken (bug)."""
        engine = self._make_option_engine()
        engine._monitor.add_position = Mock()

        with patch(_POSITION_SIZER_PATH, return_value=(3, _D("10.00"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "o1"}), \
             patch(_NOTIFY_PATH), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
                 return_value=False,
             ):
            engine._enter_position(
                _make_signal_event("NVDA"),
                window_label="W1",
                window_budget=_D("10000"),
            )

        # slot_capital = window_budget * capital_weight
        # rank_weighted=False, top_n=2 (default) → capital_weight=1/2 → slot=5000
        expected_slot = _D("10000") / _D("2")
        assert "W1" in engine._window_primary_deployed
        assert engine._window_primary_deployed["W1"] == expected_slot

    def test_option_reentry_does_not_update_window_primary_deployed(self):
        """Re-entry option entries must not update _window_primary_deployed."""
        engine = self._make_option_engine()
        engine._monitor.add_position = Mock()

        with patch(_POSITION_SIZER_PATH, return_value=(3, _D("10.00"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "o1"}), \
             patch(_NOTIFY_PATH), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
                 return_value=False,
             ):
            engine._enter_position(
                _make_signal_event("NVDA"),
                window_label="W1",
                window_budget=_D("10000"),
                trailing_arm_price=_D("115"),
            )

        assert "W1" not in engine._window_primary_deployed

    def test_primary_entry_updates_window_primary_deployed(self):
        engine = self._make_stock_engine()
        engine._monitor.add_position = Mock()

        with patch(_COMPUTE_STOCK_PATH, return_value=(20, _D("100.00"))), \
             patch(_NOTIFY_PATH):
            engine._enter_position(
                _make_signal_event("NVDA"),
                window_label="W1",
                window_budget=_D("9000"),
            )

        # slot_capital = window_budget * capital_weight
        # rank_weighted=False, top_n=3 → capital_weight=1/3 → slot=3000
        assert "W1" in engine._window_primary_deployed
        expected_slot = _D("9000") / _D("3")
        assert engine._window_primary_deployed["W1"] == expected_slot

    def test_reentry_does_not_update_window_primary_deployed(self):
        engine = self._make_stock_engine()
        engine._monitor.add_position = Mock()

        with patch(_COMPUTE_STOCK_PATH, return_value=(20, _D("100.00"))), \
             patch(_NOTIFY_PATH):
            engine._enter_position(
                _make_signal_event("NVDA"),
                window_label="W1",
                window_budget=_D("9000"),
                trailing_arm_price=_D("115"),
            )

        assert "W1" not in engine._window_primary_deployed


class TestMonitorLoop:
    """Tests for _monitor_loop post-EOD session-end behaviour."""

    _NOW_ET = "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
    _SLEEP = "alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"

    def _make_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)
        engine._monitor = Mock()
        engine._monitor._positions = []
        return engine

    def test_close_all_called_once_at_eod_time(self):
        engine = self._make_engine()
        eod_dt = datetime(2026, 4, 9, 15, 55, 0, tzinfo=pytz.timezone("America/New_York"))
        end_dt = datetime(2026, 4, 9, 16, 5, 0, tzinfo=pytz.timezone("America/New_York"))
        times = iter([eod_dt, eod_dt, end_dt])

        with patch(self._NOW_ET, side_effect=lambda: next(times)), \
             patch(self._SLEEP):
            engine._monitor_loop([])

        engine._monitor.close_all.assert_called_once_with(reason="end_of_day")

    def test_refresh_fill_prices_called_between_eod_and_session_end(self):
        engine = self._make_engine()
        eod_dt = datetime(2026, 4, 9, 15, 55, 0, tzinfo=pytz.timezone("America/New_York"))
        mid_dt = datetime(2026, 4, 9, 16, 0, 0, tzinfo=pytz.timezone("America/New_York"))
        end_dt = datetime(2026, 4, 9, 16, 5, 0, tzinfo=pytz.timezone("America/New_York"))
        times = iter([eod_dt, eod_dt, mid_dt, end_dt])

        with patch(self._NOW_ET, side_effect=lambda: next(times)), \
             patch(self._SLEEP):
            engine._monitor_loop([])

        engine._monitor._refresh_fill_prices.assert_called()

    def test_loop_exits_at_session_end_time(self):
        engine = self._make_engine()
        eod_dt = datetime(2026, 4, 9, 15, 55, 0, tzinfo=pytz.timezone("America/New_York"))
        end_dt = datetime(2026, 4, 9, 16, 5, 0, tzinfo=pytz.timezone("America/New_York"))
        times = iter([eod_dt, eod_dt, end_dt])

        with patch(self._NOW_ET, side_effect=lambda: next(times)), \
             patch(self._SLEEP) as sleep_mock:
            engine._monitor_loop([])

        assert sleep_mock.call_count == 1

    def test_on_bar_not_called_after_eod(self):
        engine = self._make_engine()
        eod_dt = datetime(2026, 4, 9, 15, 55, 0, tzinfo=pytz.timezone("America/New_York"))
        end_dt = datetime(2026, 4, 9, 16, 5, 0, tzinfo=pytz.timezone("America/New_York"))
        times = iter([eod_dt, eod_dt, end_dt])

        with patch(self._NOW_ET, side_effect=lambda: next(times)), \
             patch(self._SLEEP):
            engine._monitor_loop(["NVDA"])


_POLL_ENTRY_FILL_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.OpMomentumTradeEngine._poll_entry_fill"
)


class TestPollEntryFill:
    def _make_live_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=False,
        )
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET) - timedelta(minutes=1),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        return engine

    def test_returns_fill_price_on_first_attempt(self):
        engine = self._make_live_engine()
        engine._client.order_status.return_value = {"filled_avg_price": "8.75"}

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            result = engine._poll_entry_fill("order-1")

        assert result == _D("8.75")
        engine._client.order_status.assert_called_once_with("order-1")

    def test_retries_when_fill_not_yet_available(self):
        engine = self._make_live_engine()
        engine._client.order_status.side_effect = [
            {"filled_avg_price": None},
            {"filled_avg_price": None},
            {"filled_avg_price": "9.10"},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            result = engine._poll_entry_fill("order-2")

        assert result == _D("9.10")
        assert engine._client.order_status.call_count == 3

    def test_returns_none_after_all_retries_exhausted(self):
        engine = self._make_live_engine()
        engine._client.order_status.return_value = {"filled_avg_price": None}

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            result = engine._poll_entry_fill("order-3", retries=2)

        assert result is None
        assert engine._client.order_status.call_count == 2

    def test_retries_on_order_status_exception(self):
        engine = self._make_live_engine()
        engine._client.order_status.side_effect = [
            Exception("API error"),
            {"filled_avg_price": "7.50"},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            result = engine._poll_entry_fill("order-4")

        assert result == _D("7.50")

    def test_options_entry_sets_fill_price_in_live_mode(self):
        engine = self._make_live_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "live-opt-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=_D("8.60")) as poll_mock, \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        poll_mock.assert_called_once_with("live-opt-1")
        assert captured_positions[0].entry_fill_price == _D("8.60")

    def test_stock_entry_sets_fill_price_in_live_mode(self):
        engine = self._make_live_engine()
        engine._trade_type = "stock"
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_COMPUTE_STOCK_PATH, return_value=(10, _D("100.00"))), \
             patch(_PLACE_STOCK_ORDER_PATH, return_value={"order_id": "live-stk-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=_D("100.25")) as poll_mock, \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        poll_mock.assert_called_once_with("live-stk-1")
        assert captured_positions[0].entry_fill_price == _D("100.25")

    def test_options_entry_skips_poll_in_mock_mode(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
        )
        engine._monitor = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET) - timedelta(minutes=1),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch(_POLL_ENTRY_FILL_PATH) as poll_mock, \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        poll_mock.assert_not_called()
        assert captured_positions[0].entry_fill_price is None

    def test_fill_price_none_when_poll_returns_none(self):
        engine = self._make_live_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "live-2"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=None), \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        assert captured_positions[0].entry_fill_price is None

        engine._monitor.on_bar.assert_not_called()


_SAVE_SESSION_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._save_session"
_LOAD_SESSION_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._load_session"
_FLUSH_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.OpMomentumTradeEngine._flush_session_state"


def _make_checkpoint_position(**overrides):
    defaults = dict(
        ticker="NVDA",
        signal="BULLISH",
        option_symbol="NVDA260418C00120000",
        entry_order_id="ord-001",
        contracts=2,
        entry_stock_price=_D("120.00"),
        or_high=_D("122.00"),
        or_low=_D("118.00"),
        or_range=_D("4.00"),
        hard_stop_price=_D("117.40"),
        fallback_price=_D("118.80"),
        trade_type="options",
        window_label="M1",
        rank=0,
        window_budget=_D("10000"),
        slot_capital=_D("5000"),
        entry_fill_price=_D("3.50"),
        hard_stop_armed=True,
    )
    defaults.update(overrides)
    from alpha_tech_tracker.op_momentum_strategy.models import ActivePosition
    return ActivePosition(**defaults)


# ---------------------------------------------------------------------------
# TestRebuildWindowReturned
# ---------------------------------------------------------------------------


class TestRebuildWindowReturned:
    def _make_engine(self):
        engine = _make_engine_with_mock_client()
        engine._returned_lock = __import__("threading").Lock()
        engine._window_returned = {}
        return engine

    def test_primary_position_returns_slot_capital_plus_pnl(self):
        engine = self._make_engine()
        pos = _make_checkpoint_position(
            slot_capital=_D("5000"),
            contracts=2,
            simulated_entry_mid=_D("3.00"),
            simulated_exit_mid=_D("5.00"),
            trailing_arm_price=None,
        )

        engine._rebuild_window_returned([pos])

        returned = engine._window_returned["M1"]
        expected = _D("5000") + _D("2") * _D("100") * (_D("5.00") - _D("3.00"))
        assert returned == expected

    def test_reentry_position_returns_pnl_only(self):
        engine = self._make_engine()
        pos = _make_checkpoint_position(
            slot_capital=_D("5000"),
            contracts=1,
            simulated_entry_mid=_D("3.00"),
            simulated_exit_mid=_D("4.00"),
            trailing_arm_price=_D("121.00"),
        )

        engine._rebuild_window_returned([pos])

        returned = engine._window_returned["M1"]
        assert returned == _D("1") * _D("100") * (_D("4.00") - _D("3.00"))

    def test_skips_position_with_no_slot_capital(self):
        engine = self._make_engine()
        pos = _make_checkpoint_position(slot_capital=None)

        engine._rebuild_window_returned([pos])

        assert engine._window_returned == {}

    def test_empty_list_is_noop(self):
        engine = self._make_engine()

        engine._rebuild_window_returned([])

        assert engine._window_returned == {}


# ---------------------------------------------------------------------------
# TestFlushSessionState
# ---------------------------------------------------------------------------


class TestFlushSessionState:
    def test_flush_skipped_in_mock_mode(self):
        engine = _make_engine_with_mock_client()
        engine._monitor = Mock()

        with patch(_SAVE_SESSION_PATH) as mock_save:
            engine._flush_session_state()

        mock_save.assert_not_called()

    def test_flush_calls_save_with_all_positions_in_live_mode(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=False)
        pos = _make_checkpoint_position()
        engine._monitor = Mock()
        engine._monitor.get_all_positions.return_value = [pos]

        with patch(_SAVE_SESSION_PATH) as mock_save, \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et") as mock_now:
            mock_now.return_value.date.return_value = date(2026, 4, 11)
            engine._flush_session_state()

        mock_save.assert_called_once_with([pos], date(2026, 4, 11))

    def test_flush_exception_does_not_propagate(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=False)
        engine._monitor = Mock()
        engine._monitor.get_all_positions.side_effect = RuntimeError("boom")

        engine._flush_session_state()  # must not raise


# ---------------------------------------------------------------------------
# TestRecoverSession
# ---------------------------------------------------------------------------


class TestRecoverSession:
    def _make_live_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=False)
        engine._returned_lock = __import__("threading").Lock()
        engine._window_returned = {}
        engine._window_state = {
            "M1": {"open_position_count": 0, "capital_fraction": 1.0}
        }
        engine._window_primary_deployed = {}
        return engine

    def test_skips_recovery_in_mock_mode(self):
        engine = _make_engine_with_mock_client()

        with patch(_LOAD_SESSION_PATH) as mock_load:
            result = engine._recover_session(date(2026, 4, 11))

        mock_load.assert_not_called()
        assert result == []

    def test_returns_empty_when_no_checkpoint(self):
        engine = self._make_live_engine()

        with patch(_LOAD_SESSION_PATH, return_value=[]):
            result = engine._recover_session(date(2026, 4, 11))

        assert result == []

    def test_adds_broker_verified_position(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False)
        engine._client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": "3.55",
        }

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            result = engine._recover_session(date(2026, 4, 11))

        assert len(result) == 1
        assert result[0].ticker == "NVDA"

    def test_skips_position_when_broker_order_not_filled(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False)
        engine._client.order_status.return_value = {"status": "new"}

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            result = engine._recover_session(date(2026, 4, 11))

        assert result == []

    def test_skips_position_when_order_status_raises(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False)
        engine._client.order_status.side_effect = RuntimeError("network error")

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            result = engine._recover_session(date(2026, 4, 11))

        assert result == []

    def test_populates_entry_fill_price_when_none_in_checkpoint(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False, entry_fill_price=None)
        engine._client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": "3.75",
        }

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            result = engine._recover_session(date(2026, 4, 11))

        assert result[0].entry_fill_price == _D("3.75")

    def test_preserves_existing_fill_price_from_checkpoint(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False, entry_fill_price=_D("3.50"))
        engine._client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": "9.99",
        }

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            result = engine._recover_session(date(2026, 4, 11))

        assert result[0].entry_fill_price == _D("3.50")

    def test_rebuilds_window_returned_from_closed_positions(self):
        engine = self._make_live_engine()
        closed = _make_checkpoint_position(
            is_closed=True,
            slot_capital=_D("5000"),
            contracts=2,
            simulated_entry_mid=_D("3.00"),
            simulated_exit_mid=_D("5.00"),
            trailing_arm_price=None,
        )

        with patch(_LOAD_SESSION_PATH, return_value=[closed]):
            engine._recover_session(date(2026, 4, 11))

        assert "M1" in engine._window_returned
        assert engine._window_returned["M1"] > _D("0")

    def test_increments_open_position_count_after_recovery(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False)
        engine._client.order_status.return_value = {"status": "filled"}
        engine._monitor = Mock()

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            recovered = engine._recover_session(date(2026, 4, 11))
        for p in recovered:
            engine._monitor.add_position(p)
            engine._window_state[p.window_label]["open_position_count"] += 1

        assert engine._window_state["M1"]["open_position_count"] == 1

    def test_primary_ticker_added_to_window_primary_deployed(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(is_closed=False, trailing_arm_price=None)
        engine._client.order_status.return_value = {"status": "filled"}
        engine._monitor = Mock()

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            recovered = engine._recover_session(date(2026, 4, 11))
        for p in recovered:
            if p.trailing_arm_price is None:
                engine._window_primary_deployed.setdefault(p.window_label, set()).add(p.ticker)

        assert "NVDA" in engine._window_primary_deployed.get("M1", set())

    def test_reentry_ticker_not_added_to_primary_deployed(self):
        engine = self._make_live_engine()
        pos = _make_checkpoint_position(
            is_closed=False,
            trailing_arm_price=_D("121.00"),
            reentry_type="reversal",
        )
        engine._client.order_status.return_value = {"status": "filled"}
        engine._monitor = Mock()

        with patch(_LOAD_SESSION_PATH, return_value=[pos]):
            recovered = engine._recover_session(date(2026, 4, 11))
        for p in recovered:
            if p.trailing_arm_price is None:
                engine._window_primary_deployed.setdefault(p.window_label, set()).add(p.ticker)

        assert "NVDA" not in engine._window_primary_deployed.get("M1", set())
