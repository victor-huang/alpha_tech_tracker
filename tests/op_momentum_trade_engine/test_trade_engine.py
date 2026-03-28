from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.config import (
    MAX_ACTIVE_SYMBOLS,
    RANK_WEIGHTS,
)
from alpha_tech_tracker.op_momentum_strategy.trade_engine import (
    OpMomentumTradeEngine,
    TickerSelector,
)

from conftest import _D, _make_alpaca_client

ET = pytz.timezone("America/New_York")

_SELECT_TOP_N_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.select_top_n"
_FETCH_BARS_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.fetch_bars"
_OPTION_CONTRACT_SELECTOR_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.OptionContractSelector.select"
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
        future_deadline = datetime.now(ET) + timedelta(minutes=5)
        engine._signal_collection_deadline = future_deadline

        event = _make_signal_event("NVDA")
        engine._on_signal(event)

        assert "NVDA" in engine._pending_signals
        assert engine._open_position_count == 0

    def test_on_signal_overwrites_earlier_signal_for_same_ticker(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) + timedelta(minutes=5)

        engine._on_signal(_make_signal_event("AMD", entry=100.0))
        engine._on_signal(_make_signal_event("AMD", entry=102.0))

        assert len(engine._pending_signals) == 1
        assert float(engine._pending_signals["AMD"].entry_price) == 102.0

    def test_on_signal_skips_when_max_positions_reached_after_deadline(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(minutes=1)
        engine._open_position_count = MAX_ACTIVE_SYMBOLS

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._on_signal(_make_signal_event("NVDA"))
            mock_enter.assert_not_called()

    def test_on_signal_calls_enter_position_after_deadline_when_slot_available(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(minutes=1)
        engine._open_position_count = 0

        with patch.object(engine, "_enter_position") as mock_enter:
            event = _make_signal_event("NVDA")
            engine._on_signal(event)
            mock_enter.assert_called_once_with(event, rank=0)

        assert engine._open_position_count == 1


class TestSignalSelectionLoop:
    def test_no_action_when_no_signals_buffered(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(seconds=1)

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop()
            mock_enter.assert_not_called()

    def test_skips_tickers_with_no_rolling_stats(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(seconds=1)
        engine._pending_signals = {"NVDA": _make_signal_event("NVDA")}
        engine._rolling_stats = {}

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop()
            mock_enter.assert_not_called()

    def test_skips_tickers_with_negative_ev(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(seconds=1)
        engine._pending_signals = {"NVDA": _make_signal_event("NVDA")}
        engine._rolling_stats = {
            "NVDA": {"ev_trade": -0.1, "win_rate": 0.4, "avg_win_pct": 1.0}
        }

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop()
            mock_enter.assert_not_called()

    def test_enters_top_n_scored_signals(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(seconds=1)
        engine._pending_signals = {
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
        ):
            engine._signal_selection_loop()

        assert len(entered_tickers) == MAX_ACTIVE_SYMBOLS

    def test_respects_max_active_symbols_limit(self):
        engine = _make_engine_with_mock_client()
        engine._signal_collection_deadline = datetime.now(ET) - timedelta(seconds=1)
        engine._open_position_count = MAX_ACTIVE_SYMBOLS
        engine._pending_signals = {"NVDA": _make_signal_event("NVDA")}
        engine._rolling_stats = {
            "NVDA": {"ev_trade": 1.0, "win_rate": 0.6, "avg_win_pct": 3.0}
        }

        with patch.object(engine, "_enter_position") as mock_enter:
            engine._signal_selection_loop()
            mock_enter.assert_not_called()


class TestRankWeightedSizing:
    def test_rank_weighted_sizing_off_passes_full_weight_to_sizer(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, rank_weighted_sizing=False
        )
        engine._monitor = Mock()
        engine._open_position_count = 1

        with (
            patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"),
            patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))) as compute_mock,
            patch(
                _PLACE_ENTRY_PATH,
                return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")},
            ),
        ):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D("1")

    def test_rank_weighted_sizing_on_passes_first_weight_for_rank_zero(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, rank_weighted_sizing=True
        )
        engine._monitor = Mock()
        engine._open_position_count = 1

        with (
            patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"),
            patch(_POSITION_SIZER_PATH, return_value=(3, _D("8.50"))) as compute_mock,
            patch(
                _PLACE_ENTRY_PATH,
                return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")},
            ),
        ):
            engine._enter_position(_make_signal_event("NVDA"), rank=0)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D(str(RANK_WEIGHTS[0]))

    def test_rank_weighted_sizing_on_passes_second_weight_for_rank_one(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, rank_weighted_sizing=True
        )
        engine._monitor = Mock()
        engine._open_position_count = 1

        with (
            patch(_OPTION_CONTRACT_SELECTOR_PATH, return_value="NVDA260328C00730000"),
            patch(_POSITION_SIZER_PATH, return_value=(2, _D("8.50"))) as compute_mock,
            patch(
                _PLACE_ENTRY_PATH,
                return_value={"order_id": "sim-1", "simulated_fill_mid": _D("8.50")},
            ),
        ):
            engine._enter_position(_make_signal_event("NVDA"), rank=1)

        call_args, _ = compute_mock.call_args
        assert call_args[1] == _D(str(RANK_WEIGHTS[1]))
