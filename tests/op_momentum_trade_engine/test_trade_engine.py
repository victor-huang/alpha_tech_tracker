from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.config import (
    MAX_ACTIVE_SYMBOLS,
    RANK_WEIGHTS,
)
from alpha_tech_tracker.op_momentum_strategy.models import ReentryWatcher
from alpha_tech_tracker.op_momentum_strategy.trade_engine import (
    OpMomentumTradeEngine,
    TickerSelector,
)

from conftest import _D, _make_alpaca_client

ET = pytz.timezone("America/New_York")

_SELECT_TOP_N_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.select_top_n"
_FETCH_BARS_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars"
_OPTION_CONTRACT_SELECTOR_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.TimePremiumContractSelector.select"
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

    def test_rank_weighted_sizing_off_passes_full_weight_to_sizer(self):
        engine = self._make_engine(rank_weighted_sizing=False)

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))) as compute_mock, \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D("1")

    def test_rank_weighted_sizing_on_passes_first_weight_for_rank_zero(self):
        engine = self._make_engine(rank_weighted_sizing=True)

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))) as compute_mock, \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D(str(RANK_WEIGHTS[0]))

    def test_rank_weighted_sizing_on_passes_second_weight_for_rank_one(self):
        engine = self._make_engine(rank_weighted_sizing=True)

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))) as compute_mock, \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"), rank=1)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D(str(RANK_WEIGHTS[1]))


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

    def test_get_window_budget_returns_none_for_sequential_window(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="13:15", opening_bars=1, is_sequential=True
            ),
        ]
        engine = self._make_engine_with_windows(windows)
        a1_win = next(w for w in engine._windows if w.label == "A1")

        result = engine._get_window_budget(a1_win)

        assert result is None
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
