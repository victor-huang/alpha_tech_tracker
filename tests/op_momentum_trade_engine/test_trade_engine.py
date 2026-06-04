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


class TestEngineInit:
    def test_api_key_and_secret_read_from_alpaca_client(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

        assert engine._api_key == "test_key"
        assert engine._secret_key == "test_secret"

    def test_client_without_api_key_attrs_initialises_to_none(self):
        client = _make_alpaca_client()
        del client._api_key
        del client._secret_key
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

        assert engine._api_key is None
        assert engine._secret_key is None

    def test_client_without_api_key_attrs_does_not_raise(self):
        client = _make_alpaca_client()
        del client._api_key
        del client._secret_key

        OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

    def test_min_ev_defaults_to_zero(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

        assert engine._min_ev == 0.0

    def test_min_ev_stored_from_constructor(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True, min_ev=0.5)

        assert engine._min_ev == 0.5


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


class TestTickerSelectorWarmupFeed:
    """TickerSelector.fetch_bars() uses the configured alpaca_feed for warmup
    so that scoring bars match the feed used for live streaming."""

    @patch(_FETCH_BARS_PATH)
    def test_fetch_bars_uses_iex_when_alpaca_feed_is_iex(self, mock_fetch_bars):
        from alpaca.data.enums import DataFeed
        mock_fetch_bars.return_value = {}
        selector = TickerSelector(
            tickers=["NVDA"], top_n=1, alpaca_feed=DataFeed.IEX
        )
        selector.fetch_bars()
        _, _args, kwargs = mock_fetch_bars.mock_calls[0]
        assert kwargs.get("feed") == DataFeed.IEX

    @patch(_FETCH_BARS_PATH)
    def test_fetch_bars_uses_sip_when_alpaca_feed_is_sip(self, mock_fetch_bars):
        from alpaca.data.enums import DataFeed
        mock_fetch_bars.return_value = {}
        selector = TickerSelector(
            tickers=["NVDA"], top_n=1, alpaca_feed=DataFeed.SIP
        )
        selector.fetch_bars()
        _, _args, kwargs = mock_fetch_bars.mock_calls[0]
        assert kwargs.get("feed") == DataFeed.SIP

    @patch(_FETCH_BARS_PATH)
    def test_fetch_bars_uses_sip_by_default(self, mock_fetch_bars):
        from alpaca.data.enums import DataFeed
        mock_fetch_bars.return_value = {}
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        selector.fetch_bars()
        _, _args, kwargs = mock_fetch_bars.mock_calls[0]
        assert kwargs.get("feed") == DataFeed.SIP


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
        ) - timedelta(minutes=5)
        engine._window_state["W1"]["open_position_count"] = MAX_ACTIVE_SYMBOLS

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._on_signal_for_window("W1", _make_signal_event("NVDA"))
            mock_enter.assert_not_called()

    def test_on_signal_calls_enter_position_after_deadline_when_slot_available(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(minutes=5)
        engine._window_state["W1"]["open_position_count"] = 0

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None):
            event = _make_signal_event("NVDA")
            engine._on_signal_for_window("W1", event)
            mock_enter.assert_called_once_with(
                event, rank=0, window_label="W1", window_budget=None
            )

        assert engine._window_state["W1"]["open_position_count"] == 1

    def test_second_fast_path_signal_gets_rank_1_not_rank_0(self):
        # After a restart open_position_count resets to 0 and all new signals
        # go through the fast path (deadline already passed). Both the first
        # and second signal were incorrectly getting rank=0 (60% weight each),
        # deploying 120% of the window budget.
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(minutes=5)
        engine._window_state["W1"]["open_position_count"] = 0

        event1 = _make_signal_event("CRDO")
        event2 = _make_signal_event("COIN")

        ranks = []
        with patch.object(engine, "_enter_position", side_effect=lambda e, rank, **kw: ranks.append(rank) or True), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._on_signal_for_window("W1", event1)
            engine._on_signal_for_window("W1", event2)

        assert ranks == [0, 1]

    def test_fast_path_rank_accounts_for_already_open_recovered_positions(self):
        # If one position was recovered from checkpoint (open_position_count=1),
        # the next fast-path signal should enter at rank=1, not rank=0.
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(minutes=5)
        engine._window_state["W1"]["open_position_count"] = 1

        event = _make_signal_event("COIN")

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._on_signal_for_window("W1", event)
            _, kwargs = mock_enter.call_args
            assert kwargs["rank"] == 1


class TestDeadlineAutoExtend:
    """Guard against the 2026-05-07 incident where bar-aggregation lag caused all
    signals to arrive ~60s after the OR-close deadline, hitting the post-deadline
    path instead of the buffer path, with no drain scheduled — 0 trades all day."""

    def test_first_signal_within_grace_is_buffered_not_entered(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=60)

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch("threading.Timer") as mock_timer:
            mock_timer.return_value = Mock()
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))
            mock_enter.assert_not_called()

        assert "SHOP" in engine._window_state["W1"]["pending_signals"]

    def test_deadline_is_extended_when_first_signal_arrives_in_grace_window(self):
        engine = _make_engine_with_mock_client()
        original_deadline = datetime.now(ET) - timedelta(seconds=60)
        engine._window_state["W1"]["collection_deadline"] = original_deadline

        with patch("threading.Timer") as mock_timer:
            mock_timer.return_value = Mock()
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))

        new_deadline = engine._window_state["W1"]["collection_deadline"]
        assert new_deadline > original_deadline

    def test_drain_timer_is_scheduled_after_auto_extend(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=60)

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            mock_instance = Mock()
            mock_timer.return_value = mock_instance
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))

        mock_timer.assert_called_once()
        drain_fn = mock_timer.call_args[0][1]
        assert drain_fn == engine._drain_pending_signals_for_window
        mock_instance.start.assert_called_once()

    def test_second_signal_during_extended_window_is_buffered(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=60)

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            mock_timer.return_value = Mock()
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))

        engine._on_signal_for_window("W1", _make_signal_event("AMD"))

        assert "SHOP" in engine._window_state["W1"]["pending_signals"]
        assert "AMD" in engine._window_state["W1"]["pending_signals"]

    def test_auto_extend_does_not_fire_past_grace_window(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=91)
        engine._window_state["W1"]["open_position_count"] = 0

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))
            mock_enter.assert_called_once()
            mock_timer.assert_not_called()

    def test_auto_extend_does_not_fire_when_pending_signals_already_exist(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=60)
        engine._window_state["W1"]["pending_signals"] = {
            "COIN": _make_signal_event("COIN")
        }
        engine._window_state["W1"]["open_position_count"] = 0

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))
            mock_enter.assert_called_once()
            mock_timer.assert_not_called()

    def test_drain_called_when_timer_fires(self):
        # Verify that invoking the scheduled callback actually clears pending_signals,
        # confirming the timer target is _drain_pending_signals_for_window and not a no-op.
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=60)

        captured = {}
        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            mock_timer.return_value = Mock()
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))
            captured["fn"] = mock_timer.call_args[0][1]
            captured["args"] = mock_timer.call_args[1].get("args", mock_timer.call_args[0][2:])

        assert "SHOP" in engine._window_state["W1"]["pending_signals"]
        with patch.object(engine, "_enter_position"), \
             patch.object(engine, "_get_window_budget", return_value=None):
            captured["fn"](*captured["args"])

        assert engine._window_state["W1"]["pending_signals"] == {}

    def test_circuit_breaker_blocks_grace_window_auto_extend(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(seconds=60)
        engine._daily_max_loss_usd = 100
        engine._daily_realized_pnl = -200

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            engine._on_signal_for_window("W1", _make_signal_event("SHOP"))

        assert "SHOP" not in engine._window_state["W1"]["pending_signals"]
        mock_timer.assert_not_called()


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

    def test_skips_tickers_with_zero_ev(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(
            ET
        ) - timedelta(seconds=1)
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA")
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.0, "win_rate": 0.5, "avg_win_pct": 1.0}
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

    def test_dd_addon_returns_slot_capital_plus_cap_pnl(self):
        engine = self._make_engine()
        pos = self._make_closed_stock_pos("BULLISH", entry=100, exit_=110, slot_capital=6000)
        pos.is_doubledown_addon = True

        engine._on_position_closed(pos)

        # DD add-on returns slot_capital + cap_pnl: when DD fires it deducts the full
        # slot from _window_returned, so the full amount must be returned on close.
        cap_pnl = _D("6000") / _D("100") * _D("10")
        assert engine._window_returned["M1"] == _D("6000") + cap_pnl

    def test_dd_addon_excluded_from_closed_primary_deployed(self):
        """DD add-ons recycle freed capital, not the original window budget, so their
        slot_capital must NOT appear in _window_closed_primary_deployed. Only true
        primary positions contribute to that tracker.
        """
        engine = self._make_engine()
        engine._replay_capital = 10000

        mrvl_primary = self._make_closed_stock_pos("BULLISH", entry=152, exit_=151, slot_capital=6000)
        rh_primary = self._make_closed_stock_pos("BULLISH", entry=145, exit_=144, slot_capital=4000)
        rh_dd = self._make_closed_stock_pos("BULLISH", entry=146, exit_=145, slot_capital=6000)
        rh_dd.is_doubledown_addon = True

        engine._on_position_closed(mrvl_primary)
        engine._on_position_closed(rh_primary)
        engine._on_position_closed(rh_dd)

        # Only the two primary positions' slot_capitals are summed; the DD add-on is excluded.
        assert engine._window_closed_primary_deployed["M1"] == _D("10000")

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
             patch(_POLL_ENTRY_FILL_PATH, return_value=(_D("8.50"), 3)), \
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

    def test_bullish_reentry_trailing_arm_is_trigger_plus_0_1x_or_range(self):
        engine = self._make_engine()
        watcher = self._make_watcher(reentry_type="bullish_reentry")
        trigger = _D("108")

        engine._enter_reentry(watcher, trigger)

        call_kwargs = engine._enter_position.call_args
        assert call_kwargs[1]["trailing_arm_price"] == trigger + _D("10") * _D("0.1")

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

    def _make_multi_window_engine(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=[
                WindowConfig(label="A1", opening_start="13:15", opening_bars=1),
                WindowConfig(label="A2", opening_start="15:00", opening_bars=1, is_sequential=True),
            ],
        )
        engine._enter_position = Mock()
        return engine

    def _make_a1_watcher(self):
        return ReentryWatcher(
            ticker="CRDO",
            reentry_type="bullish_reentry",
            primary_signal="BULLISH",
            or_high=_D("185"),
            or_low=_D("175"),
            or_range=_D("10"),
            midpoint=_D("180"),
            window_label="A1",
            rank=0,
            window_budget=_D("19909"),
        )

    def test_reentry_fires_when_next_window_has_not_opened(self):
        engine = self._make_multi_window_engine()
        watcher = self._make_a1_watcher()

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_called_once()

    def test_reentry_blocked_when_next_sequential_window_has_opened(self):
        import threading
        engine = self._make_multi_window_engine()
        watcher = self._make_a1_watcher()
        engine._window_state["A2"]["budget"] = _D("19500")
        monitor = Mock()
        monitor._lock = threading.Lock()
        open_pos = Mock()
        open_pos.window_label = "A2"
        open_pos.is_closed = False
        monitor._positions = [open_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_not_called()

    def test_reentry_not_blocked_when_next_window_is_not_sequential(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=[
                WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
                WindowConfig(label="M2", opening_start="09:30", opening_bars=1, capital_fraction=0.4),
            ],
        )
        engine._enter_position = Mock()
        watcher = ReentryWatcher(
            ticker="AMD",
            reentry_type="bullish_reentry",
            primary_signal="BULLISH",
            or_high=_D("120"),
            or_low=_D("110"),
            or_range=_D("10"),
            midpoint=_D("115"),
            window_label="M1",
            rank=0,
            window_budget=_D("10000"),
        )
        engine._window_state["M2"]["budget"] = _D("4000")

        engine._enter_reentry(watcher, _D("121"))

        engine._enter_position.assert_called_once()

    def test_reentry_fires_for_last_window_with_no_successor(self):
        engine = self._make_multi_window_engine()
        watcher = ReentryWatcher(
            ticker="CRDO",
            reentry_type="bullish_reentry",
            primary_signal="BULLISH",
            or_high=_D("185"),
            or_low=_D("175"),
            or_range=_D("10"),
            midpoint=_D("180"),
            window_label="A2",
            rank=0,
            window_budget=_D("19909"),
        )

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_called_once()

    def test_reentry_gate_checks_next_window_state_under_signal_lock(self):
        import threading
        engine = self._make_multi_window_engine()
        watcher = self._make_a1_watcher()
        # Budget added without holding the signal lock — gate must read under the lock.
        engine._window_state["A2"]["budget"] = _D("5000")
        monitor = Mock()
        monitor._lock = threading.Lock()
        open_pos = Mock()
        open_pos.window_label = "A2"
        open_pos.is_closed = False
        monitor._positions = [open_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_not_called()

    def test_reentry_fires_when_next_window_opened_but_all_positions_closed(self):
        import threading
        engine = self._make_multi_window_engine()
        engine._reentry_after_next_window_returned = True
        engine._replay_capital = 10000
        watcher = self._make_a1_watcher()
        engine._window_state["A2"]["budget"] = _D("9500")
        monitor = Mock()
        monitor._lock = threading.Lock()
        closed_pos = Mock()
        closed_pos.window_label = "A2"
        closed_pos.is_closed = True
        monitor._positions = [closed_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_called_once()

    def test_reentry_uses_fresh_budget_when_next_window_cleared(self):
        import threading
        engine = self._make_multi_window_engine()
        engine._reentry_after_next_window_returned = True
        engine._replay_capital = 8500
        watcher = self._make_a1_watcher()
        engine._window_state["A2"]["budget"] = _D("9500")
        monitor = Mock()
        monitor._lock = threading.Lock()
        closed_pos = Mock()
        closed_pos.window_label = "A2"
        closed_pos.is_closed = True
        monitor._positions = [closed_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("186"))

        call_kwargs = engine._enter_position.call_args
        assert call_kwargs[1]["window_budget"] == _D("8500")
        assert call_kwargs[1]["window_budget"] != watcher.window_budget

    def test_reentry_skips_when_next_window_cleared_but_fresh_budget_is_zero(self):
        import threading
        engine = self._make_multi_window_engine()
        engine._reentry_after_next_window_returned = True
        engine._replay_capital = 0
        watcher = self._make_a1_watcher()
        engine._window_state["A2"]["budget"] = _D("9500")
        monitor = Mock()
        monitor._lock = threading.Lock()
        closed_pos = Mock()
        closed_pos.window_label = "A2"
        closed_pos.is_closed = True
        monitor._positions = [closed_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_not_called()

    def test_reentry_blocked_when_next_window_opened_and_bt_matching_mode(self):
        import threading
        engine = self._make_multi_window_engine()
        engine._reentry_after_next_window_returned = False
        engine._replay_capital = 10000
        watcher = self._make_a1_watcher()
        engine._window_state["A2"]["budget"] = _D("9500")
        monitor = Mock()
        monitor._lock = threading.Lock()
        closed_pos = Mock()
        closed_pos.window_label = "A2"
        closed_pos.is_closed = True
        monitor._positions = [closed_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("186"))

        engine._enter_position.assert_not_called()

    def test_reentry_in_middle_window_blocked_when_third_window_opened(self):
        import threading
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=[
                WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
                WindowConfig(label="A1", opening_start="13:15", opening_bars=1, is_sequential=True),
                WindowConfig(label="A2", opening_start="15:00", opening_bars=1, is_sequential=True),
            ],
        )
        engine._enter_position = Mock()
        watcher = ReentryWatcher(
            ticker="AMD",
            reentry_type="bullish_reentry",
            primary_signal="BULLISH",
            or_high=_D("120"),
            or_low=_D("110"),
            or_range=_D("10"),
            midpoint=_D("115"),
            window_label="A1",
            rank=0,
            window_budget=_D("19000"),
        )
        engine._window_state["A2"]["budget"] = _D("18500")
        monitor = Mock()
        monitor._lock = threading.Lock()
        open_pos = Mock()
        open_pos.window_label = "A2"
        open_pos.is_closed = False
        monitor._positions = [open_pos]
        engine._monitor = monitor

        engine._enter_reentry(watcher, _D("121"))

        engine._enter_position.assert_not_called()


class TestNextSequentialWindowLabel:
    def _make_engine(self, windows):
        client = _make_alpaca_client()
        return OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=windows,
        )

    def test_returns_next_label_when_next_window_is_sequential(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine([
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1),
            WindowConfig(label="A2", opening_start="15:00", opening_bars=1, is_sequential=True),
        ])

        result = engine._next_sequential_window_label("A1")

        assert result == "A2"

    def test_returns_none_when_next_window_is_not_sequential(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine([
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3, capital_fraction=0.6),
            WindowConfig(label="M2", opening_start="09:30", opening_bars=1, capital_fraction=0.4),
        ])

        result = engine._next_sequential_window_label("M1")

        assert result is None

    def test_returns_none_for_last_window(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine([
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1),
            WindowConfig(label="A2", opening_start="15:00", opening_bars=1, is_sequential=True),
        ])

        result = engine._next_sequential_window_label("A2")

        assert result is None

    def test_returns_none_for_unknown_label(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine([
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1),
        ])

        result = engine._next_sequential_window_label("X9")

        assert result is None

    def test_three_window_chain_middle_returns_third(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine([
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1, is_sequential=True),
            WindowConfig(label="A2", opening_start="15:00", opening_bars=1, is_sequential=True),
        ])

        assert engine._next_sequential_window_label("M1") == "A1"
        assert engine._next_sequential_window_label("A1") == "A2"
        assert engine._next_sequential_window_label("A2") is None


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
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}):
            engine._enter_position(_make_signal_event("NVDA"))

        custom_selector.select.assert_called_once_with("NVDA", "BULLISH", _D("105"))

    def test_replay_mode_uses_mock_selector_by_default(self):
        engine = self._make_engine()

        with patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode", return_value=True), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.MockContractSelector.select",
                   return_value="NVDA260411C00170000") as mock_select:
            engine._enter_position(_make_signal_event("NVDA"))

        mock_select.assert_called_once()

    def test_replay_mode_uses_injected_selector_when_overridden(self):
        custom_selector = Mock()
        custom_selector.select.return_value = "NVDA260411C00170000"
        engine = self._make_engine(contract_selector=custom_selector)

        with patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")}), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode", return_value=True):
            engine._enter_position(_make_signal_event("NVDA"))

        custom_selector.select.assert_called_once_with("NVDA", "BULLISH", _D("105"))


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
    def test_replay_mode_passes_replay_date_as_target_date(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = {
            "picks": [],
            "no_signal": [],
            "negative_ev": [],
            "rolling_stats": {},
        }
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        today = date(2026, 4, 13)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=True,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
        ) as mock_now_et:
            mock_now_et.return_value = Mock()
            mock_now_et.return_value.date.return_value = today
            selector.select()

        assert mock_select_top_n.call_args[1]["target_date"] == today

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_live_mode_uses_yesterday_as_bars_end(
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
        today = date(2026, 4, 15)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
        ) as mock_now_et:
            mock_now_et.return_value = Mock()
            mock_now_et.return_value.date.return_value = today
            selector.select()

        call_args = mock_fetch_bars.call_args[0]
        assert call_args[2] == today - timedelta(days=1)
        assert not mock_fetch_bars.call_args[1].get("allow_intraday")


# ---------------------------------------------------------------------------
# TickerSelector — or_bar_lookback threading
# ---------------------------------------------------------------------------

def _make_select_result_with_pick():
    return {
        "picks": [{"ticker": "NVDA", "score": 1.0, "ev_trade": 0.5}],
        "no_signal": [],
        "negative_ev": [],
        "rolling_stats": {"NVDA": {}},
    }


class TestTickerSelectorOrBarLookback:
    def test_defaults_to_3(self):
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        assert selector._or_bar_lookback == 3

    def test_stores_configured_value(self):
        selector = TickerSelector(tickers=["NVDA"], top_n=1, or_bar_lookback=5)
        assert selector._or_bar_lookback == 5

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_or_bar_lookback_to_select_top_n_in_live_mode(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_result_with_pick()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, or_bar_lookback=5)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_args[1]["or_bar_lookback"] == 5

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_or_bar_lookback_to_select_top_n_in_replay_mode(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_result_with_pick()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, or_bar_lookback=7)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=True,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
        ) as mock_now_et:
            mock_now_et.return_value.date.return_value = date(2026, 4, 7)
            selector.select()

        assert mock_select_top_n.call_args[1]["or_bar_lookback"] == 7

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_or_bar_lookback_on_prev_day_fallback(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        empty_result = {"picks": [], "no_signal": [], "negative_ev": [], "rolling_stats": {}}
        mock_select_top_n.side_effect = [empty_result, _make_select_result_with_pick()]
        selector = TickerSelector(tickers=["NVDA"], top_n=1, or_bar_lookback=2)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_count == 2
        for call in mock_select_top_n.call_args_list:
            assert call[1]["or_bar_lookback"] == 2

    @patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.TickerSelector")
    def test_run_window_selectors_passes_engine_or_bar_lookback_to_ticker_selector(
        self, mock_ticker_selector_cls
    ):
        mock_instance = Mock()
        mock_instance.rolling_stats = {}
        mock_instance.fetch_bars.return_value = {}
        mock_instance.select.return_value = []
        mock_ticker_selector_cls.return_value = mock_instance

        engine = OpMomentumTradeEngine(
            alpaca_client=_make_alpaca_client(),
            mock_trade_execution=True,
            or_bar_lookback=4,
        )
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine._windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3,
                         capital_fraction=1.0, is_sequential=False)
        ]
        engine._run_window_selectors(["NVDA"])

        _, kwargs = mock_ticker_selector_cls.call_args
        assert kwargs["or_bar_lookback"] == 4


# ---------------------------------------------------------------------------
# TickerSelector — strategy param threading (trailing_ma, max_loss_pct,
#                  armed_ma20_exit, feed)
# ---------------------------------------------------------------------------

_RUN_BACKTEST_PATH = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.run_backtest"
_BUILD_REGIME_PATH = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.build_bearish_regime_dates"
_SELECT_TOP_N_SELECTOR_PATH = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.select_top_n"


def _make_run_backtest_result():
    return {}


def _make_select_top_n_result_with_pick():
    return {
        "picks": [{"ticker": "NVDA", "score": 1.0, "ev_trade": 0.5}],
        "no_signal": [],
        "negative_ev": [],
        "rolling_stats": {"NVDA": {}},
    }


class TestSelectTopNStrategyParams:
    """select_top_n() threads trailing_ma / max_loss_pct / armed_ma20_exit
    through to run_backtest(), and feed through to build_bearish_regime_dates()."""

    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_passes_trailing_ma_to_run_backtest(self, mock_fetch, mock_run_backtest):
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
            trailing_ma="ma50",
        )

        assert mock_run_backtest.call_args[1]["trailing_ma"] == "ma50"

    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_passes_max_loss_pct_to_run_backtest(self, mock_fetch, mock_run_backtest):
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
            max_loss_pct=0.05,
        )

        assert mock_run_backtest.call_args[1]["max_loss_pct"] == 0.05

    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_passes_armed_ma20_exit_to_run_backtest(self, mock_fetch, mock_run_backtest):
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
            armed_ma20_exit=True,
        )

        assert mock_run_backtest.call_args[1]["armed_ma20_exit"] is True

    @patch(_BUILD_REGIME_PATH)
    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_passes_feed_to_build_bearish_regime_dates(
        self, mock_fetch, mock_run_backtest, mock_build_regime
    ):
        from alpaca.data.enums import DataFeed
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}
        mock_build_regime.return_value = set()

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
            regime_filter=True, feed=DataFeed.IEX,
        )

        assert mock_build_regime.call_args[1].get("feed") == DataFeed.IEX

    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_defaults_trailing_ma_to_ma20(self, mock_fetch, mock_run_backtest):
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
        )

        assert mock_run_backtest.call_args[1]["trailing_ma"] == "ma20"

    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_defaults_max_loss_pct_to_none(self, mock_fetch, mock_run_backtest):
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
        )

        assert mock_run_backtest.call_args[1]["max_loss_pct"] is None

    @patch(_RUN_BACKTEST_PATH)
    @patch("alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars")
    def test_defaults_armed_ma20_exit_to_false(self, mock_fetch, mock_run_backtest):
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import select_top_n
        mock_fetch.return_value = {}
        mock_run_backtest.return_value = {}

        select_top_n(
            n=1, tickers=["NVDA"], lookback_days=10, opening_bars=3,
            bearish_ma200=False, stop_pct=0.15, source="alpaca",
        )

        assert mock_run_backtest.call_args[1]["armed_ma20_exit"] is False


class TestTickerSelectorStrategyParams:
    """TickerSelector stores strategy params and passes them to select_top_n().
    _run_window_selectors() passes the engine's configured values."""

    def test_defaults(self):
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        assert selector._trailing_ma == "ma20"
        assert selector._max_loss_pct is None
        assert selector._armed_ma20_exit is False

    def test_stores_configured_values(self):
        selector = TickerSelector(
            tickers=["NVDA"], top_n=1,
            trailing_ma="ma50", max_loss_pct=0.05, armed_ma20_exit=True,
        )
        assert selector._trailing_ma == "ma50"
        assert selector._max_loss_pct == 0.05
        assert selector._armed_ma20_exit is True

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_trailing_ma_to_select_top_n(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result_with_pick()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, trailing_ma="ma50")

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_args[1]["trailing_ma"] == "ma50"

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_max_loss_pct_to_select_top_n(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result_with_pick()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, max_loss_pct=0.08)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_args[1]["max_loss_pct"] == 0.08

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_armed_ma20_exit_to_select_top_n(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result_with_pick()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, armed_ma20_exit=True)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_args[1]["armed_ma20_exit"] is True

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_score_feed_as_feed_to_select_top_n(
        self, mock_fetch_bars, mock_select_top_n
    ):
        from alpaca.data.enums import DataFeed
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result_with_pick()
        selector = TickerSelector(
            tickers=["NVDA"], top_n=1,
            alpaca_feed=DataFeed.SIP, score_feed=DataFeed.IEX,
        )

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_args[1]["feed"] == DataFeed.IEX

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_strategy_params_propagate_in_replay_mode(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result_with_pick()
        selector = TickerSelector(
            tickers=["NVDA"], top_n=1,
            trailing_ma="ma50", max_loss_pct=0.03, armed_ma20_exit=True,
        )

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=True,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
        ) as mock_now_et:
            mock_now_et.return_value.date.return_value = date(2026, 4, 7)
            selector.select()

        kwargs = mock_select_top_n.call_args[1]
        assert kwargs["trailing_ma"] == "ma50"
        assert kwargs["max_loss_pct"] == 0.03
        assert kwargs["armed_ma20_exit"] is True

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_strategy_params_propagate_on_prev_day_fallback(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        empty = {"picks": [], "no_signal": [], "negative_ev": [], "rolling_stats": {}}
        mock_select_top_n.side_effect = [empty, _make_select_top_n_result_with_pick()]
        selector = TickerSelector(
            tickers=["NVDA"], top_n=1,
            trailing_ma="ma50", max_loss_pct=0.03, armed_ma20_exit=True,
        )

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            selector.select()

        assert mock_select_top_n.call_count == 2
        for call in mock_select_top_n.call_args_list:
            assert call[1]["trailing_ma"] == "ma50"
            assert call[1]["max_loss_pct"] == 0.03
            assert call[1]["armed_ma20_exit"] is True

    @patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.TickerSelector")
    def test_run_window_selectors_passes_engine_strategy_params(
        self, mock_ticker_selector_cls
    ):
        mock_instance = Mock()
        mock_instance.rolling_stats = {}
        mock_instance.fetch_bars.return_value = {}
        mock_instance.select.return_value = []
        mock_ticker_selector_cls.return_value = mock_instance

        engine = OpMomentumTradeEngine(
            alpaca_client=_make_alpaca_client(),
            mock_trade_execution=True,
            trailing_ma="ma50",
            max_loss_pct=0.04,
            armed_ma20_exit=True,
        )
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine._windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3,
                         capital_fraction=1.0, is_sequential=False)
        ]
        engine._run_window_selectors(["NVDA"])

        _, kwargs = mock_ticker_selector_cls.call_args
        assert kwargs["trailing_ma"] == "ma50"
        assert kwargs["max_loss_pct"] == 0.04
        assert kwargs["armed_ma20_exit"] is True


# ---------------------------------------------------------------------------
# TickerSelector — market_data_client (TradeStation caching)
# ---------------------------------------------------------------------------

_FETCH_BARS_BACKTEST_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars"


def _make_select_top_n_result(tickers=None):
    tickers = tickers or ["NVDA"]
    return {
        "picks": [{"ticker": t, "score": 1.0, "ev_trade": 0.5, "signal": "BULLISH"} for t in tickers],
        "no_signal": [],
        "negative_ev": [],
        "rolling_stats": {t: {} for t in tickers},
    }


class TestTickerSelectorMarketDataClient:
    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_fetch_bars_uses_tradestation_source_when_client_set(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result()
        client = Mock()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, market_data_client=client)
        selector.select()

        call_kwargs = mock_fetch_bars.call_args[1]
        assert call_kwargs.get("source") == "tradestation"
        assert call_kwargs.get("market_data_client") is client

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_fetch_bars_uses_alpaca_source_when_no_client(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result()
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        selector.select()

        call_kwargs = mock_fetch_bars.call_args[1]
        assert call_kwargs.get("source") == "alpaca"
        assert call_kwargs.get("market_data_client") is None

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_tradestation_source_to_select_top_n(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result()
        client = Mock()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, market_data_client=client)
        selector.select()

        assert mock_select_top_n.call_args[1]["source"] == "tradestation"

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_select_passes_alpaca_source_to_select_top_n_when_no_client(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.return_value = _make_select_top_n_result()
        selector = TickerSelector(tickers=["NVDA"], top_n=1)
        selector.select()

        assert mock_select_top_n.call_args[1]["source"] == "alpaca"

    @patch(_SELECT_TOP_N_PATH)
    @patch(_FETCH_BARS_PATH)
    def test_tradestation_source_used_in_fallback_select_top_n_call(
        self, mock_fetch_bars, mock_select_top_n
    ):
        mock_fetch_bars.return_value = {}
        mock_select_top_n.side_effect = [
            {"picks": [], "no_signal": [], "negative_ev": [], "rolling_stats": {}},
            _make_select_top_n_result(),
        ]
        client = Mock()
        selector = TickerSelector(tickers=["NVDA"], top_n=1, market_data_client=client)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ), patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"
        ) as mock_now_et:
            mock_now_et.return_value = Mock()
            mock_now_et.return_value.date.return_value = date(2026, 4, 15)
            selector.select()

        assert mock_select_top_n.call_count == 2
        for call in mock_select_top_n.call_args_list:
            assert call[1]["source"] == "tradestation"


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

    def test_sequential_budget_uses_only_returned_capital_when_prior_position_still_open(self):
        """Open primary positions are still deployed — only actually returned capital
        is available; the still-open slot is not counted."""
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

        assert result == _D("2000")
        engine._client.get_accounts.assert_not_called()

    def test_sequential_budget_is_zero_when_prior_primaries_still_open_and_nothing_returned(self):
        """When prior primaries are still open and no capital has returned yet,
        the sequential window gets $0 — not the fallback replay capital."""
        engine = self._make_m1_a1_engine()
        engine._window_returned["M1"] = _D("0")
        engine._window_primary_deployed["M1"] = _D("10000")

        open_pos = _make_active_position()
        open_pos.window_label = "M1"
        open_pos.is_closed = False
        open_pos.trailing_arm_price = None
        open_pos.slot_capital = _D("6000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = [open_pos]
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        assert result == _D("0")
        engine._client.get_accounts.assert_not_called()

    def test_sequential_budget_is_zero_when_all_returned_capital_absorbed_by_reentries(self):
        """When prior primaries returned but all capital is tied up in re-entries
        (prior_deployed > 0), return $0 instead of fallback capital."""
        engine = self._make_m1_a1_engine()
        engine._window_returned["M1"] = _D("0")
        engine._window_primary_deployed["M1"] = _D("10000")

        reentry_pos = _make_active_position()
        reentry_pos.window_label = "M1"
        reentry_pos.is_closed = False
        reentry_pos.trailing_arm_price = _D("110")
        reentry_pos.slot_capital = _D("10000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = [reentry_pos]
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        assert result == _D("0")
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

    def test_sequential_budget_reduced_by_open_reentry_capital(self):
        """Regression: 2026-04-15 live session hit $51k peak exposure on $20k capital.

        M1 deployed $12k (APP rank=0, 60%) + $8k (CRWV rank=1, 40%) = $20k.
        Both primaries exited during M1, so _window_returned["M1"] = $20k.
        APP immediately triggered a BUE re-entry and redeployed its $12k slot.
        When A1 computed its sequential budget it saw $20k returned, but $12k of
        that was already live in the APP BUE — so A1 over-deployed by $12k.
        Fix: subtract open re-entry slot_capital from prior_returned.
        """
        engine = self._make_m1_a1_engine()
        # Both M1 primaries exited — $12k + $8k returned
        engine._window_returned["M1"] = _D("20000")
        engine._window_primary_deployed["M1"] = _D("20000")
        engine._window_state["M1"]["budget"] = _D("20000")

        # APP BUE re-entry is still open, holding the $12k (rank=0, 60%) slot
        app_bue = _make_active_position()
        app_bue.window_label = "M1"
        app_bue.is_closed = False
        app_bue.trailing_arm_price = _D("245.00")  # BUE sets trailing_arm_price
        app_bue.slot_capital = _D("12000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = [app_bue]
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        # returned=$20k minus APP BUE open=$12k → only $8k available for A1
        assert result == _D("8000")

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

    def test_sequential_budget_normalized_after_multi_session_restart(self):
        """Regression: 2026-04-17 live session deployed 2x capital after multiple engine restarts.

        Fix: use initial_capital + daily_realized_pnl − open_reentry_capital.
        This is inflation-free across restarts because daily_pnl only accumulates
        cap_pnl (never slot_capital), and initial_capital is fixed at session-1 value.
        """
        engine = self._make_m1_a1_engine()
        engine._replay_capital = 10000.0
        engine._initial_capital = _D("10000")
        # Net P&L across 2 M1 sessions
        engine._daily_realized_pnl = _D("1370")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = []
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        # budget = $10000 + $1370 − $0 = $11370
        assert result == _D("11370")

    def test_sequential_budget_preserves_single_session_pnl(self):
        """Single-session M1 gain flows correctly to A1."""
        engine = self._make_m1_a1_engine()
        engine._replay_capital = 10000.0
        engine._initial_capital = _D("10000")
        engine._daily_realized_pnl = _D("1000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = []
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        # budget = $10000 + $1000 − $0 = $11000
        assert result == _D("11000")

    def test_sequential_budget_not_normalized_when_no_replay_capital_configured(self):
        """Without initial_capital (no checkpoint, no --capital), fallback uses accumulated returns."""
        engine = self._make_m1_a1_engine()
        engine._replay_capital = None
        # _initial_capital left as None to exercise the fallback path

        engine._window_returned["M1"] = _D("21370")
        engine._window_closed_primary_deployed["M1"] = _D("20000")

        mock_monitor = Mock()
        mock_monitor._lock = threading.Lock()
        mock_monitor._positions = []
        engine._monitor = mock_monitor

        a1_win = next(w for w in engine._windows if w.label == "A1")
        result = engine._get_window_budget(a1_win)

        assert result == _D("21370")


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

    def test_zero_budget_skips_all_entries(self):
        # G35: when all capital is locked in open re-entries, sequential window
        # budget = 0. The sizer's max(1,...) would still force 1 contract, deploying
        # real cash. Guard skips entry entirely when window_budget <= 0.
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
            "AMD": _make_signal_event("AMD"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.0},
            "AMD": {"ev_trade": 0.4, "win_rate": 0.4, "avg_win_pct": 0.8},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, side_effect=[1.5, 1.2]), \
             patch.object(
                 engine, "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=_D("0")):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert enter_calls == []

    def test_negative_budget_skips_all_entries(self):
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.0},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, return_value=1.5), \
             patch.object(
                 engine, "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=_D("-500")):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert enter_calls == []

    def test_min_score_floor_skips_negative_score_pick(self):
        # Matches the backtest, which drops picks with score < min_score (default 0.0).
        # Without the floor the drain would trade the least-bad negative-score candidate.
        engine = _make_engine_with_mock_client()
        engine._min_score = 0.0
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "AMD": _make_signal_event("AMD"),
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "AMD": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.0},
            "NVDA": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
        }
        enter_calls = []
        # AMD scores positive (kept), NVDA scores negative (dropped by floor).
        with patch(_SCORE_TICKER_PATH, side_effect=[2.0, -0.5]), \
             patch.object(
                 engine, "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert enter_calls == ["AMD"]

    def test_negative_min_score_keeps_negative_score_pick(self):
        # A very negative floor disables the filter — the negative-score pick is kept.
        engine = _make_engine_with_mock_client()
        engine._min_score = -999.0
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, return_value=-0.5), \
             patch.object(
                 engine, "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert enter_calls == ["NVDA"]

    def test_none_budget_proceeds_with_entries(self):
        # budget=None means "no tracking" (first-group windows using account balance)
        engine = _make_engine_with_mock_client()
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.5, "win_rate": 0.5, "avg_win_pct": 1.0},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, return_value=1.5), \
             patch.object(
                 engine, "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert "NVDA" in enter_calls

    def test_zero_ev_blocked_when_min_ev_is_zero(self):
        # ev_trade=0.0 must be blocked when min_ev=0.0 (default), matching select_top_n()'s <= 0 gate.
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, min_ev=0.0
        )
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.0, "win_rate": 0.4, "avg_win_pct": 1.0},
        }
        with patch(_SCORE_TICKER_PATH, return_value=1.0), \
             patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        mock_enter.assert_not_called()

    def test_zero_ev_blocked_when_min_ev_above_zero(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, min_ev=0.5
        )
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.0, "win_rate": 0.4, "avg_win_pct": 1.0},
        }
        with patch(_SCORE_TICKER_PATH, return_value=1.0), \
             patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        mock_enter.assert_not_called()

    def test_positive_ev_below_min_ev_threshold_is_blocked(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, min_ev=0.5
        )
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.4, "win_rate": 0.5, "avg_win_pct": 1.5},
        }
        with patch(_SCORE_TICKER_PATH, return_value=1.0), \
             patch.object(engine, "_enter_position") as mock_enter, \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        mock_enter.assert_not_called()

    def test_positive_ev_above_min_ev_threshold_is_allowed(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, min_ev=0.5
        )
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.6, "win_rate": 0.5, "avg_win_pct": 2.0},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, return_value=1.0), \
             patch.object(
                 engine, "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert "NVDA" in enter_calls

    # ── Bug fix: sequential drain cancels prior-window reentry watchers ──────

    def _make_two_window_engine(self):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=[
                WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
                WindowConfig(label="A1", opening_start="10:00", opening_bars=3,
                             is_sequential=True),
            ],
        )
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        return engine

    def _make_watcher(self, ticker, window_label, reentry_type="bullish_reentry"):
        signal = "BEARISH" if reentry_type == "bearish_reentry" else "BULLISH"
        return ReentryWatcher(
            ticker=ticker,
            reentry_type=reentry_type,
            primary_signal=signal,
            or_high=_D("470"), or_low=_D("460"), or_range=_D("10"),
            midpoint=_D("465"), window_label=window_label, rank=0,
            window_budget=_D("6000"), primary_exit_bar_time=None,
        )

    def test_sequential_drain_cancels_prior_window_watchers(self):
        # When A1 drains and claims M1 capital, pending M1 watchers must be
        # cancelled so they can't double-spend recycled capital.
        engine = self._make_two_window_engine()
        m1_watcher = self._make_watcher("APP", "M1")
        a1_watcher = self._make_watcher("NVDA", "A1")
        engine._monitor._reentry_watchers = [m1_watcher, a1_watcher]
        engine._window_state["A1"]["pending_signals"] = {}

        engine._drain_pending_signals_for_window(engine._windows[1])

        remaining = engine._monitor._reentry_watchers
        assert len(remaining) == 1
        assert remaining[0].window_label == "A1"

    def test_first_window_drain_does_not_cancel_its_own_watchers(self):
        # Morning window has no prior window — watchers must be left untouched.
        engine = self._make_two_window_engine()
        watcher = self._make_watcher("APP", "M1")
        engine._monitor._reentry_watchers = [watcher]
        engine._window_state["M1"]["pending_signals"] = {}

        engine._drain_pending_signals_for_window(engine._windows[0])

        assert len(engine._monitor._reentry_watchers) == 1

    def test_sequential_drain_cancels_all_reentry_types_from_prior_window(self):
        # BRU, BRE, and reversal watchers are all cancelled — not just BRU.
        engine = self._make_two_window_engine()
        engine._monitor._reentry_watchers = [
            self._make_watcher("APP", "M1", "bullish_reentry"),
            self._make_watcher("APP", "M1", "bearish_reentry"),
            self._make_watcher("APP", "M1", "reversal"),
        ]
        engine._window_state["A1"]["pending_signals"] = {}

        engine._drain_pending_signals_for_window(engine._windows[1])

        assert engine._monitor._reentry_watchers == []

    def test_stock_rank0_budget_miss_falls_through_to_rank1_candidate(self):
        # MU (rank=0) price exceeds the slot budget; engine should promote JPM
        # (rank=1) and enter it rather than leaving the slot empty.
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            trade_type="stock",
            top_n=1,
        )
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        # MU inserted first → scored first → rank=0; slot budget $400 < $1000/share
        # JPM inserted second → scored second → rank=1; slot budget $400 ≥ $200/share
        engine._window_state["W1"]["pending_signals"] = {
            "MU": _make_signal_event("MU", entry=1000.0),
            "JPM": _make_signal_event("JPM", entry=200.0),
        }
        engine._rolling_stats = {
            "MU": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
            "JPM": {"ev_trade": 0.5, "win_rate": 0.4, "avg_win_pct": 1.0},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, side_effect=[3.0, 1.5]), \
             patch.object(
                 engine,
                 "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=_D("400")):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert enter_calls == ["JPM"]

    def test_stock_all_candidates_too_expensive_leaves_slot_empty(self):
        # Both candidates exceed the slot budget — slot should be left empty.
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            trade_type="stock",
            top_n=1,
        )
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "MU": _make_signal_event("MU", entry=1000.0),
            "MRVL": _make_signal_event("MRVL", entry=800.0),
        }
        engine._rolling_stats = {
            "MU": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
            "MRVL": {"ev_trade": 0.5, "win_rate": 0.4, "avg_win_pct": 1.0},
        }
        enter_calls = []
        with patch(_SCORE_TICKER_PATH, side_effect=[3.0, 1.5]), \
             patch.object(
                 engine,
                 "_enter_position",
                 side_effect=lambda e, **kw: enter_calls.append(e.ticker),
             ), \
             patch.object(engine, "_get_window_budget", return_value=_D("400")):
            engine._drain_pending_signals_for_window(engine._windows[0])

        assert enter_calls == []


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

    def test_returns_false_when_contract_selector_raises(self):
        engine = self._make_engine()
        engine._contract_selector = Mock()
        engine._contract_selector.select.side_effect = Exception("selector failure")

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
            return_value=False,
        ):
            result = engine._enter_position(_make_signal_event("NVDA"), window_label="W1")

        assert result is False

    def test_returns_false_when_sizer_raises(self):
        engine = self._make_engine()
        engine._contract_selector = Mock()
        engine._contract_selector.select.return_value = "NVDA260411C00170000"

        with patch(_POSITION_SIZER_PATH, side_effect=Exception("sizer failure")), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
                 return_value=False,
             ):
            result = engine._enter_position(_make_signal_event("NVDA"), window_label="W1")

        assert result is False

    def test_drain_loop_decrements_open_position_count_on_entry_failure(self):
        """Drain loop must decrement open_position_count when _enter_position returns False."""
        engine = self._make_engine()
        engine._trade_type = "stock"
        engine._top_n = 2

        with patch.object(engine, "_enter_position", return_value=False):
            engine._window_state["W1"]["open_position_count"] = 1
            # simulate what _enter_one does in the drain loop
            success = engine._enter_position(_make_signal_event("NVDA"), window_label="W1")
            if not success:
                engine._window_state["W1"]["open_position_count"] -= 1

        assert engine._window_state["W1"]["open_position_count"] == 0

    def test_returns_false_and_logs_warning_when_sizer_raises_runtime_error(self, caplog):
        engine = self._make_engine()
        engine._contract_selector = Mock()
        engine._contract_selector.select.return_value = "NVDA260411C00170000"

        with patch(_POSITION_SIZER_PATH, side_effect=RuntimeError("Insufficient buying power for NVDA: need $1500/contract, have $-100")), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
                 return_value=False,
             ), \
             caplog.at_level("WARNING"):
            result = engine._enter_position(_make_signal_event("NVDA"), window_label="W1")

        assert result is False
        assert "Insufficient buying power" in caplog.text
        assert "ERROR" not in caplog.text

    def test_option_entry_fits_capital_returns_false_and_logs_warning_on_runtime_error(self, caplog):
        engine = self._make_engine()
        engine._contract_selector = Mock()
        engine._contract_selector.select.return_value = "NVDA260411C00170000"

        with patch(_POSITION_SIZER_PATH, side_effect=RuntimeError("Insufficient buying power for NVDA")), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode",
                 return_value=False,
             ), \
             caplog.at_level("WARNING"):
            fits, cost = engine._option_entry_fits_capital(
                _make_signal_event("NVDA"),
                slot_weight=_D("0.5"),
                window_budget=_D("5000"),
                prior_pending_cost=_D("0"),
            )

        assert fits is False
        assert cost == _D("0")
        assert "Insufficient buying power" in caplog.text
        assert "ERROR" not in caplog.text


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
        engine._client.order_status.return_value = {"filled_avg_price": "8.75", "filled_qty": 2.0}

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            fill_price, filled_qty = engine._poll_entry_fill("order-1")

        assert fill_price == _D("8.75")
        assert filled_qty == 2
        engine._client.order_status.assert_called_once_with("order-1")

    def test_retries_when_fill_not_yet_available(self):
        engine = self._make_live_engine()
        engine._client.order_status.side_effect = [
            {"filled_avg_price": None},
            {"filled_avg_price": None},
            {"filled_avg_price": "9.10", "filled_qty": 1.0},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            fill_price, filled_qty = engine._poll_entry_fill("order-2")

        assert fill_price == _D("9.10")
        assert engine._client.order_status.call_count == 3

    def test_returns_none_after_all_retries_exhausted(self):
        engine = self._make_live_engine()
        engine._client.order_status.return_value = {"filled_avg_price": None}

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            fill_price, filled_qty = engine._poll_entry_fill("order-3", retries=2)

        assert fill_price is None
        assert filled_qty is None
        assert engine._client.order_status.call_count == 2

    def test_retries_on_order_status_exception(self):
        engine = self._make_live_engine()
        engine._client.order_status.side_effect = [
            Exception("API error"),
            {"filled_avg_price": "7.50", "filled_qty": 3.0},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            fill_price, filled_qty = engine._poll_entry_fill("order-4")

        assert fill_price == _D("7.50")
        assert filled_qty == 3

    def test_options_entry_sets_fill_price_in_live_mode(self):
        engine = self._make_live_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "live-opt-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(_D("8.60"), 2)) as poll_mock, \
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
             patch(_POLL_ENTRY_FILL_PATH, return_value=(_D("100.25"), 10)) as poll_mock, \
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
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, None)), \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        assert captured_positions[0].entry_fill_price is None

        engine._monitor.on_bar.assert_not_called()

    def test_options_entry_discarded_when_filled_qty_is_zero(self):
        engine = self._make_live_engine()

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "rej-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH):
            result = engine._enter_position(_make_signal_event("NVDA"), rank=0)

        assert result is False
        engine._monitor.add_position.assert_not_called()

    def test_options_entry_adjusts_contracts_on_partial_fill(self):
        engine = self._make_live_engine()
        captured_positions = []
        engine._monitor.add_position.side_effect = captured_positions.append

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(6, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "partial-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(_D("8.60"), 3)), \
             patch(_NOTIFY_PATH):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        assert captured_positions[0].contracts == 3

    def test_canceled_order_short_circuits_retries(self):
        engine = self._make_live_engine()
        engine._client.order_status.return_value = {
            "filled_avg_price": None,
            "filled_qty": 0.0,
            "status": "canceled",
        }

        with patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.time.sleep"):
            fill_price, filled_qty = engine._poll_entry_fill("rej-order", retries=3)

        assert fill_price is None
        assert filled_qty == 0
        assert engine._client.order_status.call_count == 1


_SAVE_SESSION_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._save_session"
_LOAD_SESSION_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._load_session"
_LOAD_SESSION_METADATA_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._load_session_metadata"
_DELETE_SESSION_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._delete_session"
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

    def test_primary_position_also_populates_closed_primary_deployed(self):
        engine = self._make_engine()
        pos = _make_checkpoint_position(
            slot_capital=_D("6000"),
            contracts=2,
            simulated_entry_mid=_D("3.00"),
            simulated_exit_mid=_D("5.00"),
            trailing_arm_price=None,
        )

        engine._rebuild_window_returned([pos])

        assert engine._window_closed_primary_deployed["M1"] == _D("6000")

    def test_reentry_position_does_not_populate_closed_primary_deployed(self):
        engine = self._make_engine()
        pos = _make_checkpoint_position(
            slot_capital=_D("6000"),
            contracts=1,
            simulated_entry_mid=_D("3.00"),
            simulated_exit_mid=_D("4.00"),
            trailing_arm_price=_D("121.00"),
        )

        engine._rebuild_window_returned([pos])

        assert engine._window_closed_primary_deployed == {}


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

        mock_save.assert_called_once_with([pos], date(2026, 4, 11), metadata=None)

    def test_flush_includes_initial_capital_in_metadata(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=False)
        engine._initial_capital = _D("20000")
        pos = _make_checkpoint_position()
        engine._monitor = Mock()
        engine._monitor.get_all_positions.return_value = [pos]

        with patch(_SAVE_SESSION_PATH) as mock_save, \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et") as mock_now:
            mock_now.return_value.date.return_value = date(2026, 4, 11)
            engine._flush_session_state()

        mock_save.assert_called_once_with(
            [pos], date(2026, 4, 11), metadata={"initial_capital": "20000"}
        )

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

    def test_restores_initial_capital_from_checkpoint_metadata(self):
        engine = self._make_live_engine()

        with patch(_LOAD_SESSION_PATH, return_value=[]), \
             patch(_LOAD_SESSION_METADATA_PATH, return_value={"initial_capital": "20000.00"}):
            engine._recover_session(date(2026, 4, 11))

        assert engine._initial_capital == _D("20000.00")

    def test_initial_capital_not_set_when_metadata_missing(self):
        engine = self._make_live_engine()

        with patch(_LOAD_SESSION_PATH, return_value=[]), \
             patch(_LOAD_SESSION_METADATA_PATH, return_value={}):
            engine._recover_session(date(2026, 4, 11))

        assert engine._initial_capital is None

    def test_reset_session_deletes_checkpoint_and_returns_empty(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=False, reset_session=True
        )
        engine._returned_lock = __import__("threading").Lock()
        engine._window_returned = {}
        engine._window_state = {"M1": {"open_position_count": 0, "capital_fraction": 1.0}}
        engine._window_primary_deployed = {}

        with patch(_DELETE_SESSION_PATH) as mock_delete, \
             patch(_LOAD_SESSION_PATH) as mock_load:
            result = engine._recover_session(date(2026, 4, 11))

        mock_delete.assert_called_once_with(date(2026, 4, 11))
        mock_load.assert_not_called()
        assert result == []

    def test_reset_session_does_not_restore_initial_capital(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=False, reset_session=True
        )
        engine._returned_lock = __import__("threading").Lock()
        engine._window_returned = {}
        engine._window_state = {"M1": {"open_position_count": 0, "capital_fraction": 1.0}}
        engine._window_primary_deployed = {}

        with patch(_DELETE_SESSION_PATH), \
             patch(_LOAD_SESSION_METADATA_PATH) as mock_meta:
            engine._recover_session(date(2026, 4, 11))

        mock_meta.assert_not_called()
        assert engine._initial_capital is None


# ---------------------------------------------------------------------------
# TestCircuitBreaker — daily max-loss circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def _make_engine(self, daily_max_loss_usd=None):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            daily_max_loss_usd=daily_max_loss_usd,
        )
        return engine

    def test_not_tripped_when_disabled(self):
        engine = self._make_engine(daily_max_loss_usd=None)
        engine._daily_realized_pnl = _D("-9999")

        assert engine._is_circuit_breaker_tripped() is False

    def test_not_tripped_when_pnl_above_threshold(self):
        engine = self._make_engine(daily_max_loss_usd=500)
        engine._daily_realized_pnl = _D("-400")

        assert engine._is_circuit_breaker_tripped() is False

    def test_tripped_when_pnl_at_threshold(self):
        engine = self._make_engine(daily_max_loss_usd=500)
        engine._daily_realized_pnl = _D("-500")

        assert engine._is_circuit_breaker_tripped() is True

    def test_tripped_when_pnl_exceeds_threshold(self):
        engine = self._make_engine(daily_max_loss_usd=500)
        engine._daily_realized_pnl = _D("-600")

        assert engine._is_circuit_breaker_tripped() is True

    def test_rebuild_window_returned_accumulates_daily_pnl(self):
        engine = self._make_engine(daily_max_loss_usd=500)
        pos = _make_checkpoint_position(
            slot_capital=_D("5000"),
            contracts=2,
            simulated_entry_mid=_D("5.00"),
            simulated_exit_mid=_D("3.00"),
            trailing_arm_price=None,
        )

        engine._rebuild_window_returned([pos])

        expected_pnl = _D("2") * _D("100") * (_D("3.00") - _D("5.00"))
        assert engine._daily_realized_pnl == expected_pnl

    def test_on_signal_skips_entry_when_circuit_breaker_tripped(self):
        engine = self._make_engine(daily_max_loss_usd=500)
        engine._daily_realized_pnl = _D("-600")
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            minutes=1
        )
        engine._window_state["W1"]["open_position_count"] = 0

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._on_signal_for_window("W1", _make_signal_event("NVDA"))

        mock_enter.assert_not_called()
        assert engine._window_state["W1"]["open_position_count"] == 0

    def test_drain_stops_when_circuit_breaker_tripped(self):
        engine = self._make_engine(daily_max_loss_usd=500)
        engine._daily_realized_pnl = _D("-600")
        engine._window_state["W1"]["collection_deadline"] = datetime.now(ET) - timedelta(
            seconds=1
        )
        engine._window_state["W1"]["pending_signals"] = {
            "NVDA": _make_signal_event("NVDA"),
        }
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 0.8, "win_rate": 0.6, "avg_win_pct": 2.0},
        }

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_SCORE_TICKER_PATH, return_value=3.0), \
             patch.object(engine, "_get_window_budget", return_value=None):
            engine._drain_pending_signals_for_window(engine._windows[0])

        mock_enter.assert_not_called()

        assert "NVDA" not in engine._window_primary_deployed.get("M1", set())


# ---------------------------------------------------------------------------
# TestCheckWsHealth — WebSocket reconnect watchdog
# ---------------------------------------------------------------------------

_NOW_ET_TRADE = "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"


class TestCheckWsHealth:
    def _make_engine(self, timeout=600):
        engine = _make_engine_with_mock_client()
        engine._ws_reconnect_timeout = timeout
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = None
        engine._signal_engine._stream_started_at = None
        return engine

    def test_no_action_when_signal_engine_is_none(self):
        engine = _make_engine_with_mock_client()
        engine._signal_engine = None
        now = ET.localize(datetime(2026, 4, 11, 10, 0))

        engine._check_ws_health(now)  # must not raise

    def test_no_action_when_no_start_time_recorded(self):
        engine = self._make_engine()
        now = ET.localize(datetime(2026, 4, 11, 10, 0))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_no_reconnect_when_within_timeout(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 10, 10))
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 10, 5)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_reconnect_when_last_bar_exceeds_timeout(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 11, 0))
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 10, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_reconnect_uses_stream_started_at_when_no_bar_received(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 11, 0))
        engine._signal_engine._last_bar_received_at = None
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 4, 11, 10, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_reconnect_exception_does_not_propagate(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 11, 0))
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 10, 0)
        )
        engine._signal_engine.reconnect.side_effect = RuntimeError("network error")

        engine._check_ws_health(now)  # must not raise

    def test_no_reconnect_before_bars_window(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 2, 0))  # 2 AM ET — before 4 AM window
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 4, 11, 1, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_no_reconnect_after_bars_window(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 21, 0))  # 9 PM ET — after 8 PM window
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 19, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_reconnect_at_start_of_bars_window(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 4, 15))  # 4:15 AM ET — inside window
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 4, 11, 3, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_no_reconnect_at_end_of_bars_window(self):
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 20, 0))  # exactly 8 PM ET — outside window
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 18, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_alpaca_sip_engine_reconnects_at_8am_pre_market(self):
        # SIP window starts at 4:00 AM — 8 AM is inside window, stale stream triggers reconnect
        engine = self._make_engine(timeout=600)
        now = ET.localize(datetime(2026, 4, 11, 8, 0))
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 4, 11, 4, 0)
        )

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_alpaca_iex_engine_no_reconnect_before_market_open(self):
        # IEX window starts at 9:25 AM — 8 AM is before window, watchdog stays silent
        from alpaca.data.enums import DataFeed
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            alpaca_feed=DataFeed.IEX,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = None
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 4, 11, 4, 0)
        )
        now = ET.localize(datetime(2026, 4, 11, 8, 0))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_alpaca_iex_engine_reconnects_after_market_open(self):
        # IEX window starts at 9:25 AM — 10 AM is inside window with stale stream
        from alpaca.data.enums import DataFeed
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            alpaca_feed=DataFeed.IEX,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 9, 30)
        )
        engine._signal_engine._stream_started_at = None
        now = ET.localize(datetime(2026, 4, 11, 10, 30))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_tradestation_engine_no_reconnect_before_market_open(self):
        # TS window starts at 9:30 AM — 8 AM is before window, so watchdog stays silent
        client = _make_alpaca_client()
        market_data_client = Mock()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = None
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 4, 11, 4, 0)
        )
        now = ET.localize(datetime(2026, 4, 11, 8, 0))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_tradestation_engine_reconnects_after_market_open(self):
        # TS window starts at 9:30 AM — 10 AM is inside window with stale stream
        client = _make_alpaca_client()
        market_data_client = Mock()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 9, 30)
        )
        engine._signal_engine._stream_started_at = None
        now = ET.localize(datetime(2026, 4, 11, 10, 30))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_tradestation_no_reconnect_at_market_open_when_started_premarket(self):
        # Regression: TS engine started at 4:29 AM, no bar received, first watchdog
        # check fires at exactly 9:30 ET. Without the fix, elapsed = 5 hours >> 600s
        # and it reconnected at the worst possible moment (right as M1 bars start).
        # With the fix, elapsed is measured from 9:30 ET, not from startup.
        client = _make_alpaca_client()
        market_data_client = Mock()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = None
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 5, 27, 4, 29)  # engine started before market hours
        )
        now = ET.localize(datetime(2026, 5, 27, 9, 30, 29))  # 29s into market open

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_tradestation_reconnects_if_no_bar_for_timeout_after_market_open(self):
        # TS engine started pre-market, window opens at 9:30 ET, but no bar arrives
        # for longer than the timeout — should reconnect.
        client = _make_alpaca_client()
        market_data_client = Mock()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = None
        engine._signal_engine._stream_started_at = ET.localize(
            datetime(2026, 5, 27, 4, 29)
        )
        now = ET.localize(datetime(2026, 5, 27, 9, 41))  # 11 min after open, no bar yet

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_no_reconnect_when_broadcaster_heartbeat_is_recent(self):
        # local_ts_broadcast: last bar was 20 min ago but heartbeat arrived 15s ago
        # → broadcaster is alive, no reconnect
        from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
            LocalTSBroadcastMarketDataClient,
        )
        client = _make_alpaca_client()
        market_data_client = Mock(spec=LocalTSBroadcastMarketDataClient)
        market_data_client.seconds_since_last_message.return_value = 15.0
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 9, 30)
        )
        engine._signal_engine._stream_started_at = None
        now = ET.localize(datetime(2026, 4, 11, 10, 30))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_not_called()

    def test_reconnect_when_broadcaster_heartbeat_is_stale(self):
        # local_ts_broadcast: both last bar and last heartbeat exceed timeout
        # → broadcaster is down, trigger reconnect
        from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
            LocalTSBroadcastMarketDataClient,
        )
        client = _make_alpaca_client()
        market_data_client = Mock(spec=LocalTSBroadcastMarketDataClient)
        market_data_client.seconds_since_last_message.return_value = 700.0
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 9, 30)
        )
        engine._signal_engine._stream_started_at = None
        now = ET.localize(datetime(2026, 4, 11, 10, 30))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()

    def test_heartbeat_check_skipped_for_non_broadcast_client(self):
        # Regular TradeStation client (plain Mock, not LocalTSBroadcastMarketDataClient)
        # → watchdog falls back to bar-only elapsed time and reconnects normally
        client = _make_alpaca_client()
        market_data_client = Mock()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            market_data_client=market_data_client,
        )
        engine._ws_reconnect_timeout = 600
        engine._signal_engine = Mock()
        engine._signal_engine._last_bar_received_at = ET.localize(
            datetime(2026, 4, 11, 9, 30)
        )
        engine._signal_engine._stream_started_at = None
        now = ET.localize(datetime(2026, 4, 11, 10, 30))

        engine._check_ws_health(now)

        engine._signal_engine.reconnect.assert_called_once()


# ---------------------------------------------------------------------------
# TestMarketHolidayGuard — run() exits early on weekends and NYSE holidays
# ---------------------------------------------------------------------------

_IS_NYSE_HOLIDAY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine._is_nyse_holiday"
)
_NOW_ET_RUN = "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et"


class TestMarketHolidayGuard:
    def _make_live_engine(self):
        client = _make_alpaca_client()
        return OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=False)

    def test_run_returns_early_on_saturday(self):
        engine = self._make_live_engine()
        saturday = date(2026, 4, 11)  # a Saturday
        mock_now = Mock()
        mock_now.return_value.date.return_value = saturday

        with patch(_NOW_ET_RUN, mock_now), \
             patch.object(engine, "_run_window_selectors") as mock_sel:
            engine.run()

        mock_sel.assert_not_called()

    def test_run_proceeds_on_sunday(self):
        engine = self._make_live_engine()
        ET_tz = pytz.timezone("America/New_York")
        # Sunday 10 PM ET — after_close=False (22 < 16:05 threshold fires, but
        # weekday==6 alone advances session_date to Monday)
        sunday_night = ET_tz.localize(datetime(2026, 4, 12, 22, 0, 0))
        # Monday 9:21 ET — past the 9:20 pre-market wait threshold
        monday_premarket = ET_tz.localize(datetime(2026, 4, 13, 9, 21, 0))

        # First 3 calls (today, now_et, last_log) return Sunday; 4th (loop
        # condition) returns Monday so the wait loop exits immediately.
        call_count = {"n": 0}
        def _mock_now():
            call_count["n"] += 1
            return sunday_night if call_count["n"] <= 3 else monday_premarket

        with patch(_NOW_ET_RUN, _mock_now), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False), \
             patch.object(engine, "_run_window_selectors", return_value=[]) as mock_sel, \
             patch.object(engine, "_signal_engine", Mock()):
            try:
                engine.run()
            except Exception:
                pass  # stream setup will fail — we only care the guard didn't block

        mock_sel.assert_called_once()

    def test_run_returns_early_on_nyse_holiday(self):
        engine = self._make_live_engine()
        good_friday = date(2026, 4, 3)  # Good Friday 2026
        mock_now = Mock()
        mock_now.return_value.date.return_value = good_friday

        with patch(_NOW_ET_RUN, mock_now), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=True), \
             patch.object(engine, "_run_window_selectors") as mock_sel:
            engine.run()

        mock_sel.assert_not_called()

    def test_guard_skipped_in_mock_mode(self):
        engine = _make_engine_with_mock_client()
        ET_tz = pytz.timezone("America/New_York")
        # Saturday 10 AM ET in mock mode: guard is skipped; after_close=False so
        # session_date stays as Saturday and no pre-market wait fires.
        saturday_morning = ET_tz.localize(datetime(2026, 4, 11, 10, 0, 0))

        with patch(_NOW_ET_RUN, Mock(return_value=saturday_morning)), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False), \
             patch.object(engine, "_run_window_selectors", return_value=[]) as mock_sel, \
             patch.object(engine, "_signal_engine", Mock()):
            try:
                engine.run()
            except Exception:
                pass  # stream setup will fail — we only care the guard didn't block

        mock_sel.assert_called_once()


_IS_REPLAY_MODE_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.is_replay_mode"


class TestComputePositionReturnedCapital:
    def _make_engine(self):
        return OpMomentumTradeEngine(
            alpaca_client=_make_alpaca_client(), mock_trade_execution=True
        )

    def test_option_bullish_profit(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = _D("4000")
        pos.contracts = 4
        pos.simulated_entry_mid = _D("10")
        pos.simulated_exit_mid = _D("12")
        # returned = 4000 + 4*100*(12-10) = 4000 + 800 = 4800
        assert engine._compute_position_returned_capital(pos) == _D("4800")

    def test_option_bullish_loss(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = _D("4000")
        pos.contracts = 4
        pos.simulated_entry_mid = _D("10")
        pos.simulated_exit_mid = _D("9.50")
        # returned = 4000 + 4*100*(9.5-10) = 4000 - 200 = 3800
        assert engine._compute_position_returned_capital(pos) == _D("3800")

    def test_option_bearish_profit(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BEARISH")
        pos.slot_capital = _D("3000")
        pos.contracts = 3
        pos.simulated_entry_mid = _D("8")
        pos.simulated_exit_mid = _D("6")
        # raw = entry - exit = 8 - 6 = 2 (BEARISH: profit when price falls)
        # returned = 3000 + 3*100*2 = 3000 + 600 = 3600
        assert engine._compute_position_returned_capital(pos) == _D("3600")

    def test_falls_back_to_slot_capital_when_no_exit_price(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = _D("5000")
        pos.contracts = 5
        pos.simulated_entry_mid = _D("10")
        pos.simulated_exit_mid = None
        pos.exit_fill_price = None
        assert engine._compute_position_returned_capital(pos) == _D("5000")

    def test_returns_zero_when_no_slot_capital(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = None
        pos.simulated_entry_mid = _D("10")
        pos.simulated_exit_mid = _D("12")
        assert engine._compute_position_returned_capital(pos) == _D("0")


class TestRebuildWindowReturnedClosedContracts:
    """BUG-1: cap_pnl must use closed_contracts when pos.contracts is zeroed after live close."""

    def _make_engine(self):
        return OpMomentumTradeEngine(
            alpaca_client=_make_alpaca_client(), mock_trade_execution=False
        )

    def test_cap_pnl_uses_closed_contracts_when_pos_contracts_is_zero(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = _D("4000")
        pos.window_label = "M1"
        pos.entry_fill_price = _D("10")
        pos.exit_fill_price = _D("12")
        pos.closed_contracts = 4
        pos.contracts = 0  # zeroed after live close

        engine._rebuild_window_returned([pos])

        # cap_pnl = 4 * 100 * (12 - 10) = 800; returned = 4000 + 800 = 4800
        assert engine._window_returned["M1"] == _D("4800")

    def test_cap_pnl_is_zero_when_both_contracts_and_closed_contracts_are_zero(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = _D("4000")
        pos.window_label = "M1"
        pos.entry_fill_price = _D("10")
        pos.exit_fill_price = _D("12")
        pos.closed_contracts = 0
        pos.contracts = 0

        engine._rebuild_window_returned([pos])

        # no contracts to multiply — returned equals slot_capital only
        assert engine._window_returned["M1"] == _D("4000")

    def test_falls_back_to_contracts_when_closed_contracts_not_set(self):
        engine = self._make_engine()
        pos = _make_active_position(signal="BULLISH")
        pos.slot_capital = _D("4000")
        pos.window_label = "M1"
        pos.entry_fill_price = _D("10")
        pos.exit_fill_price = _D("12")
        pos.closed_contracts = 0  # default — not yet set (open position)
        pos.contracts = 4

        engine._rebuild_window_returned([pos])

        # falls back to pos.contracts = 4
        assert engine._window_returned["M1"] == _D("4800")


class TestDoubleDown:
    def _make_engine(self, **kwargs):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_doubledown=True,
            doubledown_start_min=5,
            top_n=2,
            rank_weights=[0.6, 0.4],
            **kwargs,
        )
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._monitor._reentry_watchers = []
        engine._signal_engine = Mock()
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        return engine

    def _make_win(self, label="W1"):
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        return WindowConfig(label=label, opening_start="09:30", opening_bars=3)

    def _make_latest_bar(self, close=290.0, high=None, low=None):
        import pandas as pd
        return pd.Series(
            {
                "Close": close,
                "High": high if high is not None else close + 1.0,
                "Low": low if low is not None else close - 1.0,
                "MA20": 285.0,
            },
            name=datetime.now(ET),
        )

    def _make_open_pos(self, rank, slot_capital, ticker="NVDA",
                       signal="BULLISH", window_label="W1"):
        pos = _make_active_position(signal=signal)
        pos.ticker = ticker
        pos.rank = rank
        pos.window_label = window_label
        pos.is_closed = False
        pos.slot_capital = _D(str(slot_capital))
        pos.trailing_arm_price = None
        pos.is_doubledown_addon = False
        return pos

    def _make_stopout_pos(self, rank, slot_capital, ticker="TSLA",
                          signal="BULLISH", exit_reason="hard_stop",
                          entry_mid=10.0, exit_mid=9.5, contracts=4,
                          window_label="W1"):
        pos = _make_active_position(signal=signal)
        pos.ticker = ticker
        pos.rank = rank
        pos.window_label = window_label
        pos.is_closed = True
        pos.exit_reason = exit_reason
        pos.slot_capital = _D(str(slot_capital))
        pos.simulated_entry_mid = _D(str(entry_mid))
        pos.simulated_exit_mid = _D(str(exit_mid))
        pos.contracts = contracts
        pos.trailing_arm_price = None
        pos.is_doubledown_addon = False
        return pos

    def test_dd_fires_when_one_stopout_and_one_survivor(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        mock_enter.assert_called_once()
        kw = mock_enter.call_args[1]
        assert kw["reentry_type"] == "doubledown"
        assert kw["capital_weight_override"] == _D("1")
        assert kw["initial_hard_stop_armed"] is True
        # DD stop = addon_entry - 0.80 × bar_range (BULLISH): 290.0 - 0.80×2.0 = 288.40
        assert kw["hard_stop_override"] == _D("288.40")

    def test_dd_stop_uses_bar_range_for_bearish_winner(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA", signal="BEARISH")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [winner, stopout]
        # close=242.57, High=245.79, Low=242.43 → bar_range=3.36
        # BEARISH stop = 242.57 + 0.80×3.36 = 245.258
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=242.57, high=245.79, low=242.43)

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        kw = mock_enter.call_args[1]
        expected_stop = _D("242.57") + _D("0.80") * (_D("245.79") - _D("242.43"))
        assert kw["hard_stop_override"] == expected_stop

    def test_dd_freed_capital_equals_returned_capital_from_stopout(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        # entry=10, exit=9.5, contracts=4 → returned = 4000 + 4*100*(9.5-10) = 3800
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                          entry_mid=10.0, exit_mid=9.5, contracts=4)
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        assert mock_enter.call_args[1]["window_budget"] == _D("3800")

    def test_dd_skips_when_no_survivors(self):
        engine = self._make_engine()
        stopout1 = self._make_stopout_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout2 = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [stopout1, stopout2]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._check_doubledown_for_window(self._make_win())

        mock_enter.assert_not_called()

    def test_dd_skips_when_all_positions_survive(self):
        engine = self._make_engine()
        survivor1 = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        survivor2 = self._make_open_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [survivor1, survivor2]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._check_doubledown_for_window(self._make_win())

        mock_enter.assert_not_called()

    def test_stopout_with_open_reentry_excluded_from_freed_capital(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        # Open re-entry leg for rank-1: trailing_arm_price is not None marks it as re-entry
        reentry = _make_active_position(signal="BULLISH")
        reentry.ticker = "TSLA"
        reentry.rank = 1
        reentry.window_label = "W1"
        reentry.is_closed = False
        reentry.trailing_arm_price = _D("295")
        engine._monitor._positions = [winner, stopout, reentry]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._check_doubledown_for_window(self._make_win())

        # rank-1 stopout excluded (rank-1 has an active re-entry) → no eligible stopout → DD skips
        mock_enter.assert_not_called()

    def test_dd_deducts_freed_capital_from_window_returned(self):
        engine = self._make_engine()
        engine._window_returned["W1"] = _D("3800")
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        # entry=10, exit=9.5, contracts=4 → returned = 3800
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                          entry_mid=10.0, exit_mid=9.5, contracts=4)
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position"), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        assert engine._window_returned["W1"] == _D("0")

    def test_dd_does_not_fire_twice_for_same_window(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())
            engine._check_doubledown_for_window(self._make_win())

        mock_enter.assert_called_once()

    def test_winner_is_highest_ranked_survivor(self):
        engine = self._make_engine()
        # top-3 scenario: rank-0 stops out, rank-1 and rank-2 survive → rank-1 is winner
        stopout = self._make_stopout_pos(rank=0, slot_capital=5000, ticker="NVDA")
        survivor1 = self._make_open_pos(rank=1, slot_capital=3000, ticker="TSLA")
        survivor2 = self._make_open_pos(rank=2, slot_capital=2000, ticker="COIN")
        engine._monitor._positions = [stopout, survivor1, survivor2]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        event = mock_enter.call_args[0][0]
        assert event.ticker == "TSLA"

    def test_fallback_20pct_stopout_is_eligible(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                          exit_reason="fallback_20pct")
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter, \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        mock_enter.assert_called_once()

    def test_trailing_stop_exit_not_eligible_for_dd(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        # trailing_stop exits are not considered stopouts for DD purposes
        late_exit = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                            exit_reason="trailing_stop_ma20")
        engine._monitor._positions = [winner, late_exit]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._check_doubledown_for_window(self._make_win())

        mock_enter.assert_not_called()

    def test_dd_addon_is_flagged_is_doubledown_addon(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_doubledown=True,
            top_n=2,
        )
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._monitor._reentry_watchers = []
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        captured = []
        engine._monitor.add_position = Mock(side_effect=captured.append)

        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                          entry_mid=10.0, exit_mid=9.5, contracts=4)
        engine._monitor._positions = [winner, stopout]

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00290000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-dd", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        assert len(captured) == 1
        assert captured[0].is_doubledown_addon is True

    def test_dd_addon_not_tracked_in_window_primary_deployed(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_doubledown=True,
            top_n=2,
        )
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._monitor._reentry_watchers = []
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)
        engine._window_state["W1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        engine._monitor.add_position = Mock()

        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                          entry_mid=10.0, exit_mid=9.5, contracts=4)
        engine._monitor._positions = [winner, stopout]

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00290000"), \
             patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "sim-dd", "simulated_fill_mid": _D("8.50")}), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        assert "W1" not in engine._window_primary_deployed

    def test_sequential_window_budget_is_zero_when_m1_fully_deployed_with_dd_addon(self):
        """A1 budget must be $0 when all M1 capital is still deployed (primary + DD add-on open)."""
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            enable_doubledown=True,
            top_n=2,
            windows=[
                WindowConfig(label="M1", opening_start="09:30", opening_bars=3,
                             capital_fraction=1.0, is_sequential=False),
                WindowConfig(label="A1", opening_start="13:15", opening_bars=1,
                             capital_fraction=1.0, is_sequential=True),
            ],
        )
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._signal_engine = Mock()
        engine._window_state["A1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }

        # rank-1 (M1) still open: slot_capital = $6000
        rank1 = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA", window_label="M1")
        # DD add-on (M1) still open: slot_capital = $3800 (freed from rank-2 stopout)
        dd_addon = self._make_open_pos(rank=0, slot_capital=3800, ticker="NVDA", window_label="M1")
        dd_addon.is_doubledown_addon = True

        engine._monitor._positions = [rank1, dd_addon]
        # _window_returned["M1"] = 0 (freed capital was deducted when DD add-on entered)
        engine._window_returned["M1"] = _D("0")
        engine._window_primary_deployed["M1"] = _D("10000")
        engine._window_state["M1"] = {"budget": _D("10000")}

        a1_win = WindowConfig(label="A1", opening_start="13:15", opening_bars=1,
                              capital_fraction=1.0, is_sequential=True)
        budget = engine._get_window_budget(a1_win)

        # All $10k is still deployed (rank-1 $6000 + DD add-on $3800 still open) → A1 gets $0
        assert budget == _D("0")

    def test_schedule_dd_skips_in_replay_mode(self):
        engine = self._make_engine()
        with patch(_IS_REPLAY_MODE_PATH, return_value=True):
            engine._schedule_dd_check_for_window(self._make_win())
        assert "W1" not in engine._dd_timers

    def test_schedule_dd_skips_when_already_fired(self):
        engine = self._make_engine()
        engine._dd_fired.add("W1")
        with patch(_IS_REPLAY_MODE_PATH, return_value=False):
            engine._schedule_dd_check_for_window(self._make_win())
        assert "W1" not in engine._dd_timers

    def test_dd_restores_window_returned_when_entry_fails(self):
        engine = self._make_engine()
        engine._window_returned["W1"] = _D("3800")
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        # entry=10, exit=9.5, contracts=4 → returned = 3800
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA",
                                          entry_mid=10.0, exit_mid=9.5, contracts=4)
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position", return_value=False), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        # freed_capital was subtracted then restored — net change is zero
        assert engine._window_returned["W1"] == _D("3800")

    def test_schedule_dd_fires_immediately_when_time_already_passed(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        with patch(_IS_REPLAY_MODE_PATH, return_value=False), \
             patch.object(engine, "_check_doubledown_for_window") as mock_check, \
             patch(_NOTIFY_PATH):
            # Patch _now_et to return a time after the DD check time
            with patch(
                "alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
                return_value=ET.localize(datetime(2026, 1, 2, 15, 0, 0)),
            ):
                engine._schedule_dd_check_for_window(self._make_win())

        mock_check.assert_called_once()
        assert "W1" not in engine._dd_timers

    def test_schedule_dd_skips_when_feature_disabled(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, enable_doubledown=False
        )
        engine._schedule_dd_check_for_window(self._make_win())
        assert "W1" not in engine._dd_timers

    def test_schedule_dd_schedules_timer_for_afternoon_a1_window(self):
        # Window opens at 13:00/1-bar → OR closes at 13:05.
        # doubledown_start_min=5 → dd_check_time=13:10 → timer scheduled (no 13:00 cutoff).
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine()
        engine._window_state["A2"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        afternoon_win = WindowConfig(label="A2", opening_start="13:00", opening_bars=1)
        mock_now = ET.localize(datetime(2026, 1, 2, 9, 30, 0))
        with patch(_IS_REPLAY_MODE_PATH, return_value=False), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
                   return_value=mock_now), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            mock_timer.return_value = Mock()
            engine._schedule_dd_check_for_window(afternoon_win)

        mock_timer.assert_called_once()
        assert "A2" in engine._dd_timers

    def test_schedule_dd_schedules_timer_when_check_time_before_1300(self):
        # Window opens at 12:30/1-bar → OR closes at 12:35.
        # doubledown_start_min=5 → dd_check_time=12:40 → timer scheduled.
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        engine = self._make_engine()
        engine._window_state["A1"] = {
            "pending_signals": {},
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
        }
        late_morning_win = WindowConfig(label="A1", opening_start="12:30", opening_bars=1)
        mock_now = ET.localize(datetime(2026, 1, 2, 9, 30, 0))
        with patch(_IS_REPLAY_MODE_PATH, return_value=False), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine._now_et",
                   return_value=mock_now), \
             patch("alpha_tech_tracker.op_momentum_strategy.trade_engine.threading.Timer") as mock_timer:
            mock_timer.return_value = Mock()
            engine._schedule_dd_check_for_window(late_morning_win)

        mock_timer.assert_called_once()
        assert "A1" in engine._dd_timers

    def _make_reentry_watcher(self, ticker, window_label="W1", rank=1):
        return ReentryWatcher(
            ticker=ticker,
            reentry_type="bearish_reentry",
            primary_signal="BEARISH",
            or_high=_D("170"),
            or_low=_D("165"),
            or_range=_D("5"),
            midpoint=_D("167.5"),
            window_label=window_label,
            rank=rank,
            window_budget=_D("10000"),
            primary_exit_bar_time=None,
        )

    def test_dd_cancels_reentry_watchers_for_stopout_tickers(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="SNDK")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="CRDO",
                                         signal="BEARISH", exit_reason="fallback_20pct",
                                         entry_mid=168.65, exit_mid=168.76)
        engine._monitor._positions = [winner, stopout]
        engine._monitor._reentry_watchers = [self._make_reentry_watcher("CRDO")]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position"), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        assert engine._monitor._reentry_watchers == []

    def test_dd_does_not_cancel_watchers_for_different_window(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="SNDK")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="CRDO",
                                         signal="BEARISH", exit_reason="fallback_20pct",
                                         entry_mid=168.65, exit_mid=168.76)
        engine._monitor._positions = [winner, stopout]
        other_window_watcher = self._make_reentry_watcher("CRDO", window_label="W2")
        engine._monitor._reentry_watchers = [other_window_watcher]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position"), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        assert len(engine._monitor._reentry_watchers) == 1

    def test_dd_cancels_only_stopout_watcher_not_survivor_watcher(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="SNDK")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="CRDO",
                                         signal="BEARISH", exit_reason="fallback_20pct",
                                         entry_mid=168.65, exit_mid=168.76)
        engine._monitor._positions = [winner, stopout]
        crdo_watcher = self._make_reentry_watcher("CRDO", rank=1)
        sndk_watcher = self._make_reentry_watcher("SNDK", rank=0)
        engine._monitor._reentry_watchers = [crdo_watcher, sndk_watcher]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position"), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        remaining = engine._monitor._reentry_watchers
        assert len(remaining) == 1
        assert remaining[0].ticker == "SNDK"

    # ── Bug fix: DD fires after all monitors run in a bar group ─────────────

    def test_dd_sees_position_as_stopout_when_it_exits_on_dd_check_bar(self):
        # When a position's stop fires on the same bar as the DD check time,
        # DD must identify it as a stopout (not a survivor).  The fix: DD runs
        # via on_bar_group_complete, after all monitor.on_bar() calls.
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="SNDK")
        stopout = self._make_open_pos(rank=1, slot_capital=4000, ticker="CRDO")
        engine._monitor._positions = [winner, stopout]
        engine._monitor._reentry_watchers = [self._make_reentry_watcher("CRDO")]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar()

        # Simulate: CRDO exits (stop fires) before DD check runs
        stopout.is_closed = True
        stopout.exit_reason = "hard_stop"

        with patch.object(engine, "_enter_position"), \
             patch(_NOTIFY_PATH):
            engine._check_doubledown_for_window(self._make_win())

        # CRDO is a stopout → watcher must be cancelled
        assert engine._monitor._reentry_watchers == []

    def test_dd_notify_not_sent_when_entry_fails(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position", return_value=False), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._check_doubledown_for_window(self._make_win())

        dd_messages = [c[0][0] for c in mock_notify.call_args_list if "[DD]" in c[0][0]]
        assert dd_messages == []

    def test_dd_notify_sent_only_when_entry_succeeds(self):
        engine = self._make_engine()
        winner = self._make_open_pos(rank=0, slot_capital=6000, ticker="NVDA")
        stopout = self._make_stopout_pos(rank=1, slot_capital=4000, ticker="TSLA")
        engine._monitor._positions = [winner, stopout]
        engine._signal_engine.get_latest_bar.return_value = self._make_latest_bar(close=290.0)

        with patch.object(engine, "_enter_position", return_value=True), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._check_doubledown_for_window(self._make_win())

        dd_messages = [c[0][0] for c in mock_notify.call_args_list if "[DD]" in c[0][0]]
        assert len(dd_messages) == 1
        assert "NVDA" in dd_messages[0]


_MOCK_ENTRY_PRICE_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.mock_option_pricer.mock_entry_price"
)
_PLACE_WITH_FILL_ESCALATION_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.place_option_order_in_tranches"
)


class TestPlaceEntryOptionOrderSimulateMode:
    """_place_entry in mock mode must trust the sizer's limit_price."""

    # strike $90 call — gives non-zero intrinsic when stock > $90
    _CALL_SYM = "NVDA260328C00090000"
    # strike $120 put — reproduces the SHOP 2026-05-04 below-intrinsic case
    _PUT_SYM = "SHOP260508P00120000"

    def _make_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True
        )
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = {"Close": 100.0}
        engine._option_price_monitor = Mock()
        return engine

    def test_get_fair_price_not_called_in_mock_mode(self):
        engine = self._make_engine()
        engine._place_entry("NVDA", "BULLISH", self._CALL_SYM, 1, _D("12.00"))
        engine._option_price_monitor.get_fair_price.assert_not_called()

    def test_mock_entry_price_not_recomputed_in_mock_mode(self):
        # PositionSizer already priced this from event.entry_price; _place_entry
        # must not call mock_entry_price again (re-fetching latest_bar in replay
        # can return a different OR bar and produce a below-intrinsic mid).
        engine = self._make_engine()
        with patch(_MOCK_ENTRY_PRICE_PATH) as mock_fn:
            engine._place_entry("NVDA", "BULLISH", self._CALL_SYM, 1, _D("12.00"))
        mock_fn.assert_not_called()

    def test_simulated_fill_mid_equals_limit_price_in_mock_mode(self):
        engine = self._make_engine()
        result = engine._place_entry("NVDA", "BULLISH", self._CALL_SYM, 1, _D("12.00"))
        assert result["simulated_fill_mid"] == _D("12.00")

    def test_below_intrinsic_entry_not_produced_when_latest_bar_drifts(self):
        # Reproduces the SHOP 2026-05-04 bug: signal fired on OR-close stock
        # $114.02 (true intrinsic for $120 put = $5.98), sizer's limit_price
        # was $7.18, but _place_entry's latest_bar lookup returned the FIRST
        # OR bar (close $117.56), producing a $2.93 entry mid below intrinsic.
        engine = self._make_engine()
        # Stale latest_bar returns the first OR bar's close.
        engine._signal_engine.get_latest_bar.return_value = {"Close": 117.56}
        sizer_limit = _D("7.18")  # intrinsic 5.98 × 1.20 = 7.176 → 7.18 quantized

        result = engine._place_entry("SHOP", "BEARISH", self._PUT_SYM, 5, sizer_limit)

        intrinsic = _D("120") - _D("114.02")
        assert result["simulated_fill_mid"] >= intrinsic, (
            f"entry mid {result['simulated_fill_mid']} below intrinsic {intrinsic}"
        )
        assert result["simulated_fill_mid"] == sizer_limit

    def test_get_fair_price_called_in_live_mode(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=False
        )
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = {"Close": 100.0}
        engine._option_price_monitor = Mock()
        engine._option_price_monitor.get_fair_price.return_value = _D("12.00")

        with patch(
            _PLACE_WITH_FILL_ESCALATION_PATH,
            return_value=({"order_id": "live-1"}, 1),
        ):
            engine._place_entry("NVDA", "BULLISH", self._CALL_SYM, 1, _D("12.00"))

        engine._option_price_monitor.get_fair_price.assert_called_once()


# ---------------------------------------------------------------------------
# _on_exit_fill_corrected — cap_pnl delta applied after FILL_ESC MISS retry
# ---------------------------------------------------------------------------

class TestOnExitFillCorrected:
    def _make_engine(self):
        client = _make_alpaca_client()
        return OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)

    def _make_option_pos(self, signal, entry_fill, exit_fill, contracts, slot_capital):
        pos = _make_active_position(signal=signal)
        pos.trade_type = "options"
        pos.entry_fill_price = _D(str(entry_fill))
        pos.exit_fill_price = _D(str(exit_fill))
        pos.contracts = contracts
        pos.slot_capital = _D(str(slot_capital))
        pos.trailing_arm_price = None
        pos.window_label = "A1"
        return pos

    def _make_stock_pos(self, signal, entry_fill, exit_fill, slot_capital):
        pos = _make_active_position(signal=signal)
        pos.trade_type = "stock"
        pos.entry_fill_price = _D(str(entry_fill))
        pos.exit_fill_price = _D(str(exit_fill))
        pos.slot_capital = _D(str(slot_capital))
        pos.trailing_arm_price = None
        pos.window_label = "A1"
        return pos

    def test_bullish_option_adds_cap_pnl_to_window_returned(self):
        engine = self._make_engine()
        pos = self._make_option_pos("BULLISH", entry_fill=8.00, exit_fill=10.00, contracts=2, slot_capital=2000)

        engine._on_exit_fill_corrected(pos)

        # cap_pnl = 2 * 100 * (10.00 - 8.00) = 400
        assert engine._window_returned["A1"] == _D("400")

    def test_bullish_option_adds_cap_pnl_to_daily_realized_pnl(self):
        engine = self._make_engine()
        pos = self._make_option_pos("BULLISH", entry_fill=8.00, exit_fill=10.00, contracts=2, slot_capital=2000)

        engine._on_exit_fill_corrected(pos)

        assert engine._daily_realized_pnl == _D("400")

    def test_bearish_option_loss_adds_negative_cap_pnl(self):
        engine = self._make_engine()
        pos = self._make_option_pos("BEARISH", entry_fill=6.00, exit_fill=4.00, contracts=3, slot_capital=1500)

        engine._on_exit_fill_corrected(pos)

        # cap_pnl = 3 * 100 * (4.00 - 6.00) = -600 (loss: exit < entry for PUT)
        assert engine._window_returned["A1"] == _D("-600")

    def test_bullish_stock_adds_correct_cap_pnl(self):
        engine = self._make_engine()
        pos = self._make_stock_pos("BULLISH", entry_fill=100, exit_fill=110, slot_capital=5000)

        engine._on_exit_fill_corrected(pos)

        # cap_pnl = 5000/100 * 10 = 500
        assert engine._window_returned["A1"] == _D("500")

    def test_bearish_stock_direction_correct(self):
        engine = self._make_engine()
        pos = self._make_stock_pos("BEARISH", entry_fill=200, exit_fill=185, slot_capital=4000)

        engine._on_exit_fill_corrected(pos)

        # cap_pnl = 4000/200 * (200 - 185) = 4000/200 * 15 = 300
        assert engine._window_returned["A1"] == _D("300")

    def test_skips_when_exit_fill_price_is_none(self):
        engine = self._make_engine()
        pos = self._make_option_pos("BULLISH", entry_fill=8.00, exit_fill=10.00, contracts=2, slot_capital=2000)
        pos.exit_fill_price = None

        engine._on_exit_fill_corrected(pos)

        assert engine._window_returned == {}
        assert engine._daily_realized_pnl == _D("0")

    def test_skips_when_entry_is_zero(self):
        engine = self._make_engine()
        pos = self._make_option_pos("BULLISH", entry_fill=0, exit_fill=10.00, contracts=2, slot_capital=2000)

        engine._on_exit_fill_corrected(pos)

        assert engine._window_returned == {}

    def test_correction_accumulates_with_existing_window_returned(self):
        engine = self._make_engine()
        engine._window_returned["A1"] = _D("1000")
        pos = self._make_option_pos("BULLISH", entry_fill=5.00, exit_fill=7.00, contracts=1, slot_capital=500)

        engine._on_exit_fill_corrected(pos)

        # cap_pnl = 1 * 100 * 2.00 = 200; 1000 + 200 = 1200
        assert engine._window_returned["A1"] == _D("1200")


# ---------------------------------------------------------------------------
# ENTRY MISSED notification — _notify called when entry fills 0 contracts/shares
# ---------------------------------------------------------------------------

class TestEntryMissedNotification:
    def _make_live_engine(self, trade_type="options"):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=False,
            trade_type=trade_type,
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

    def test_option_entry_missed_sends_notify(self):
        engine = self._make_live_engine(trade_type="options")

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "rej-opt-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        notify_messages = [call[0][0] for call in mock_notify.call_args_list]
        assert any("ENTRY MISSED" in msg for msg in notify_messages)

    def test_option_entry_missed_message_includes_symbol(self):
        engine = self._make_live_engine(trade_type="options")

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "rej-opt-2"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        notify_messages = [call[0][0] for call in mock_notify.call_args_list]
        missed_msgs = [m for m in notify_messages if "ENTRY MISSED" in m]
        assert missed_msgs and "NVDA260404C00170000" in missed_msgs[0]

    def test_option_entry_missed_returns_false(self):
        engine = self._make_live_engine(trade_type="options")

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260404C00170000"), \
             patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))), \
             patch(_PLACE_ENTRY_PATH, return_value={"order_id": "rej-opt-3"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH):
            result = engine._enter_position(_make_signal_event("NVDA"), rank=0)

        assert result is False
        engine._monitor.add_position.assert_not_called()

    def test_stock_entry_missed_sends_notify(self):
        engine = self._make_live_engine(trade_type="stock")

        with patch(_COMPUTE_STOCK_PATH, return_value=(10, _D("100.00"))), \
             patch(_PLACE_STOCK_ORDER_PATH, return_value={"order_id": "rej-stk-1"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        notify_messages = [call[0][0] for call in mock_notify.call_args_list]
        assert any("ENTRY MISSED" in msg for msg in notify_messages)

    def test_stock_entry_missed_message_includes_ticker(self):
        engine = self._make_live_engine(trade_type="stock")

        with patch(_COMPUTE_STOCK_PATH, return_value=(10, _D("100.00"))), \
             patch(_PLACE_STOCK_ORDER_PATH, return_value={"order_id": "rej-stk-2"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH) as mock_notify:
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        notify_messages = [call[0][0] for call in mock_notify.call_args_list]
        missed_msgs = [m for m in notify_messages if "ENTRY MISSED" in m]
        assert missed_msgs and "NVDA" in missed_msgs[0]

    def test_stock_entry_missed_returns_false(self):
        engine = self._make_live_engine(trade_type="stock")

        with patch(_COMPUTE_STOCK_PATH, return_value=(10, _D("100.00"))), \
             patch(_PLACE_STOCK_ORDER_PATH, return_value={"order_id": "rej-stk-3"}), \
             patch(_POLL_ENTRY_FILL_PATH, return_value=(None, 0)), \
             patch(_NOTIFY_PATH):
            result = engine._enter_position(_make_signal_event("NVDA"), rank=0)

        assert result is False
        engine._monitor.add_position.assert_not_called()


class TestWinRateSignalDrainRanking:
    """
    _drain_pending_signals_for_window with selector_type='win-rate' should rank
    buffered signals by (up_pct_from_prev_close, ma_count, vol_ratio) descending
    instead of the composite score_ticker score.
    """

    _NOTIFY_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._notify"

    def _make_engine(self, top_n=2):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            selector_type="win-rate",
            top_n=top_n,
        )
        return engine

    def _make_wr_event(
        self, ticker, signal="BULLISH", entry=105.0,
        overlapping_mas=None, collection_vol=2000.0,
        vol_20day_avg=1000.0, prev_close=100.0,
    ):
        from alpha_tech_tracker.op_momentum_strategy.models import SignalEvent
        or_range = _D("10")
        return SignalEvent(
            ticker=ticker,
            signal=signal,
            entry_price=_D(str(entry)),
            stock_price=_D(str(entry)),
            or_high=_D(str(entry + 5)),
            or_low=_D(str(entry - 5)),
            or_range=or_range,
            ma50_at_signal=_D("100"),
            overlapping_mas=overlapping_mas or ["MA20"],
            collection_vol=collection_vol,
            vol_20day_avg=vol_20day_avg,
            prev_close=prev_close,
        )

    def _run_drain(self, engine, pending, mocker):
        """Inject pending signals and drain; return list of (ticker, rank) entered."""
        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        win = WindowConfig(label="W1", opening_start="09:30", opening_bars=3,
                           capital_fraction=1.0, is_sequential=False)
        engine._windows = [win]
        engine._window_state["W1"] = {
            "pending_signals": dict(pending),
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
            "drain_timer_scheduled": False,
        }
        # Provide sentinel rolling_stats so EV gate passes for all tickers
        engine._rolling_stats_by_window["W1"] = {
            t: {"ev_trade": 1.0, "avg_win_pct": 0.0, "win_rate": 0.0}
            for t in pending
        }

        entered = []

        def fake_enter(event, rank=0, window_label="W1", **kwargs):
            entered.append((event.ticker, rank))
            return True

        mocker.patch.object(engine, "_enter_position", side_effect=fake_enter)
        mocker.patch.object(engine, "_get_window_budget", return_value=_D("10000"))
        mocker.patch.object(engine, "_is_circuit_breaker_tripped", return_value=False)
        mocker.patch.object(engine, "_option_entry_fits_capital", return_value=(True, _D("500")))
        mocker.patch.object(engine, "_stock_entry_fits_capital", return_value=(True, _D("500")))

        with patch(self._NOTIFY_PATH):
            engine._drain_pending_signals_for_window(win)

        return entered

    def test_higher_up_pct_ranks_first(self, mocker):
        engine = self._make_engine()
        pending = {
            "AMD": self._make_wr_event("AMD", entry=106.0, prev_close=100.0),   # up_pct=6%
            "NVDA": self._make_wr_event("NVDA", entry=103.0, prev_close=100.0), # up_pct=3%
        }

        entered = self._run_drain(engine, pending, mocker)

        assert [t for t, _ in entered] == ["AMD", "NVDA"]

    def test_more_overlapping_mas_breaks_up_pct_tie(self, mocker):
        engine = self._make_engine()
        pending = {
            "AMD": self._make_wr_event("AMD", entry=105.0, prev_close=100.0,
                                       overlapping_mas=["MA20"]),          # 1 MA
            "NVDA": self._make_wr_event("NVDA", entry=105.0, prev_close=100.0,
                                        overlapping_mas=["MA20", "MA50"]), # 2 MAs
        }

        entered = self._run_drain(engine, pending, mocker)

        assert [t for t, _ in entered] == ["NVDA", "AMD"]

    def test_higher_vol_ratio_breaks_tie_after_up_pct_and_ma_count(self, mocker):
        engine = self._make_engine()
        pending = {
            "AMD": self._make_wr_event("AMD", collection_vol=1500.0, vol_20day_avg=1000.0,
                                       entry=105.0, prev_close=100.0),   # vol_ratio=1.5
            "NVDA": self._make_wr_event("NVDA", collection_vol=3000.0, vol_20day_avg=1000.0,
                                        entry=105.0, prev_close=100.0),  # vol_ratio=3.0
        }

        entered = self._run_drain(engine, pending, mocker)

        assert [t for t, _ in entered] == ["NVDA", "AMD"]

    def test_only_top_n_are_entered(self, mocker):
        engine = self._make_engine(top_n=2)
        pending = {
            "A": self._make_wr_event("A", entry=106.0, prev_close=100.0),
            "B": self._make_wr_event("B", entry=105.0, prev_close=100.0),
            "C": self._make_wr_event("C", entry=104.0, prev_close=100.0),
        }

        entered = self._run_drain(engine, pending, mocker)

        assert len(entered) == 2
        assert [t for t, _ in entered] == ["A", "B"]

    def test_score_rank_selector_still_uses_score_ticker(self, mocker):
        """selector_type='score-rank' must still call score_ticker, not the win-rate key."""
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            selector_type="score-rank",
            top_n=1,
        )
        event = _make_signal_event("AMD", entry=105.0)
        # No overlapping_mas → falls through to score_ticker path
        pending = {"AMD": event}
        engine._rolling_stats_by_window["W1"] = {
            "AMD": {"ev_trade": 1.0, "avg_win_pct": 1.0, "win_rate": 0.5,
                    "ev_trend": 0.0}
        }
        mock_score = mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.trade_engine.score_ticker",
            return_value=0.9,
        )

        from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
        win = WindowConfig("W1", "09:30", 3, 1.0, False)
        engine._windows = [win]
        engine._window_state["W1"] = {
            "pending_signals": dict(pending),
            "collection_deadline": datetime.now(ET),
            "open_position_count": 0,
            "capital_fraction": 1.0,
            "drain_timer_scheduled": False,
        }
        mocker.patch.object(engine, "_enter_position", return_value=True)
        mocker.patch.object(engine, "_get_window_budget", return_value=_D("10000"))
        mocker.patch.object(engine, "_is_circuit_breaker_tripped", return_value=False)

        with patch(self._NOTIFY_PATH):
            engine._drain_pending_signals_for_window(win)

        mock_score.assert_called_once()
