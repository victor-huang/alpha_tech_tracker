"""
Unit tests for OpMomentumTradeEngine components.

Each test class covers one component and uses mocker.patch to isolate
from real API calls and network dependencies.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import pytz


def _D(x) -> Decimal:
    return Decimal(str(x))


from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import (
    CAPITAL_PER_SYMBOL,
    MAX_ACTIVE_SYMBOLS,
    ActivePosition,
    LiveSignalEngine,
    OpMomentumTradeEngine,
    OptionContractSelector,
    PositionMonitor,
    PositionSizer,
    SignalEvent,
    TickerSelector,
    _FiveMinBar,
    _next_friday,
    _strike_increment,
)

ET = pytz.timezone("America/New_York")


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_alpaca_client():
    client = Mock()
    client._api_key = "test_key"
    client._secret_key = "test_secret"
    client._option_data_client = Mock()
    return client


def _make_active_position(
    signal="BULLISH",
    or_high=_D("105"),
    or_low=_D("95"),
    hard_stop_price=_D("103.5"),
    fallback_price=_D("103.0"),
):
    or_range = or_high - or_low
    return ActivePosition(
        ticker="NVDA",
        signal=signal,
        option_symbol="NVDA260328C00900000",
        entry_order_id="order-123",
        contracts=3,
        entry_stock_price=_D("104"),
        or_high=or_high,
        or_low=or_low,
        or_range=or_range,
        hard_stop_price=hard_stop_price,
        fallback_price=fallback_price,
    )


def _make_signal_engine_with_history(
    ticker: str, history_df: pd.DataFrame
) -> LiveSignalEngine:
    engine = LiveSignalEngine(
        tickers=[ticker],
        api_key="k",
        secret_key="s",
        opening_bars=3,
        on_signal=None,
    )
    engine._history[ticker] = history_df
    return engine


# ---------------------------------------------------------------------------
# TestNextFriday
# ---------------------------------------------------------------------------


class TestNextFriday:
    def test_monday_returns_same_week_friday(self):
        monday = date(2026, 3, 23)
        assert _next_friday(monday) == date(2026, 3, 27)

    def test_friday_returns_next_week_friday(self):
        friday = date(2026, 3, 27)
        assert _next_friday(friday) == date(2026, 4, 3)

    def test_saturday_returns_next_week_friday(self):
        saturday = date(2026, 3, 28)
        assert _next_friday(saturday) == date(2026, 4, 3)

    def test_thursday_returns_next_day_friday(self):
        thursday = date(2026, 3, 26)
        assert _next_friday(thursday) == date(2026, 3, 27)


# ---------------------------------------------------------------------------
# TestStrikeIncrement
# ---------------------------------------------------------------------------


class TestStrikeIncrement:
    def test_low_price_stock_uses_one_dollar_increment(self):
        assert _strike_increment(_D("30")) == _D("1")

    def test_mid_price_stock_uses_five_dollar_increment(self):
        assert _strike_increment(_D("100")) == _D("5")
        assert _strike_increment(_D("200")) == _D("5")

    def test_high_price_stock_uses_ten_dollar_increment(self):
        assert _strike_increment(_D("820")) == _D("10")
        assert _strike_increment(_D("500")) == _D("10")

    def test_boundary_at_fifty_uses_five_dollar_increment(self):
        assert _strike_increment(_D("50")) == _D("5")


# ---------------------------------------------------------------------------
# TestOptionContractSelector
# ---------------------------------------------------------------------------

_NEXT_FRIDAY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine._next_friday"
)


class TestOptionContractSelector:
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bullish_signal_selects_call_with_lower_strike(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328C00730000", "strike_price": 730.0},
            {"symbol": "NVDA260328C00740000", "strike_price": 740.0},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("NVDA", "BULLISH", 820.0)

        assert symbol == "NVDA260328C00730000"
        client.get_options_contracts.assert_called_once_with(
            underlying_symbol="NVDA",
            expiration_date=date(2026, 3, 27),
            option_type="call",
            strike_price_gte="656",
            strike_price_lte="984",
            limit=50,
        )

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bearish_signal_selects_put_with_higher_strike(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328P00910000", "strike_price": 910.0},
            {"symbol": "NVDA260328P00900000", "strike_price": 900.0},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("NVDA", "BEARISH", 820.0)

        assert symbol == "NVDA260328P00900000"

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_picks_contract_closest_to_target_strike(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "CRWD260328C00085000", "strike_price": 85.0},
            {"symbol": "CRWD260328C00090000", "strike_price": 90.0},
            {"symbol": "CRWD260328C00095000", "strike_price": 95.0},
        ]

        selector = OptionContractSelector(client)
        # stock @ 100 → target call strike = floor(90/5)*5 = 90
        symbol = selector.select("CRWD", "BULLISH", 100.0)

        assert symbol == "CRWD260328C00090000"

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_raises_when_no_contracts_found(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = []

        selector = OptionContractSelector(client)

        with pytest.raises(RuntimeError, match="No call contracts found"):
            selector.select("NVDA", "BULLISH", 820.0)

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_floating_point_safe_strike_calculation(self, _):
        """100 * 1.10 = 110.000...01 must not round up to 115."""
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "COIN260328P00110000", "strike_price": 110.0},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("COIN", "BEARISH", 100.0)

        call_args = client.get_options_contracts.call_args
        assert call_args.kwargs["strike_price_lte"] == "120"
        assert call_args.kwargs["strike_price_gte"] == "80"
        assert call_args.kwargs["limit"] == 50
        assert symbol == "COIN260328P00110000"


# ---------------------------------------------------------------------------
# TestPositionSizer
# ---------------------------------------------------------------------------


class TestPositionSizer:
    def test_computes_contract_count_from_buying_power(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}

        mock_quote = Mock()
        mock_quote.bid_price = 8.00
        mock_quote.ask_price = 9.00
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00730000": mock_quote
        }

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute("NVDA260328C00730000")

        budget = _D("25000") * CAPITAL_PER_SYMBOL
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected_contracts = max(1, int(budget / (mid * _D("100"))))

        assert contracts == expected_contracts
        assert limit_price == _D("8.50")

    def test_minimum_one_contract_when_budget_is_tiny(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100.0}

        mock_quote = Mock()
        mock_quote.bid_price = 50.00
        mock_quote.ask_price = 60.00
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00730000": mock_quote
        }

        sizer = PositionSizer(client)
        contracts, _ = sizer.compute("NVDA260328C00730000")

        assert contracts == 1

    def test_returns_one_contract_and_ask_when_mid_is_zero(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}

        mock_quote = Mock()
        mock_quote.bid_price = 0.0
        mock_quote.ask_price = 0.0
        client._option_data_client.get_option_latest_quote.return_value = {
            "OPT": mock_quote
        }

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute("OPT")

        assert contracts == 1
        assert limit_price == _D("0")


# ---------------------------------------------------------------------------
# TestTickerSelector
# ---------------------------------------------------------------------------

_SELECT_TOP_N_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine.select_top_n"
)
_FETCH_BARS_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine.fetch_bars"
)


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


# ---------------------------------------------------------------------------
# TestSignalBuffer — _on_signal buffering and post-deadline behavior
# ---------------------------------------------------------------------------


def _make_signal_event(
    ticker="NVDA", signal="BULLISH", entry=105.0, or_high=107.0, or_low=97.0
):
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
    engine = OpMomentumTradeEngine(alpaca_client=client, simulate=True)
    return engine


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
            mock_enter.assert_called_once_with(event)

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
            side_effect=lambda e: entered_tickers.append(e.ticker),
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


# ---------------------------------------------------------------------------
# TestLiveSignalEngine — signal firing logic (no live stream)
# ---------------------------------------------------------------------------


class TestLiveSignalEngine:
    def _make_history_df(self, closes, ma20=None, ma50=None, ma200=None):
        """Build a minimal history DataFrame with pre-set MA values."""
        n = len(closes)
        today = datetime.now(ET).date()
        timestamps = [
            ET.localize(
                datetime.combine(today, datetime.min.time())
                + timedelta(hours=9, minutes=30 + i * 5)
            )
            for i in range(n)
        ]
        df = pd.DataFrame(
            {
                "Open": closes,
                "High": [c + 1.0 for c in closes],
                "Low": [c - 1.0 for c in closes],
                "Close": closes,
                "Volume": [1000.0] * n,
            },
            index=timestamps,
        )
        df["MA20"] = ma20 if ma20 is not None else closes[-1] - 5.0
        df["MA50"] = ma50 if ma50 is not None else closes[-1] - 3.0
        df["MA200"] = ma200 if ma200 is not None else closes[-1] - 10.0
        return df

    def test_bullish_signal_fires_when_close_above_midpoint_and_mas(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BULLISH"
        assert fired_events[0].ticker == "NVDA"

    def test_bearish_signal_fires_when_close_at_bottom_and_below_ma20(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        # OR range 95-105, bottom_30 = 95 + 0.2*10 = 97, close=96 is below bottom_30
        closes = [100.0, 98.0, 96.0]
        df = self._make_history_df(closes, ma20=105.0, ma200=110.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[101.0, 99.0, 97.0], lows=[99.0, 97.0, 95.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BEARISH"

    def test_neutral_signal_does_not_fire_callback(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        # close is at midpoint exactly — neither bullish nor bearish condition met
        closes = [100.0, 100.0, 100.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=100.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[101.0, 101.0, 101.0], lows=[99.0, 99.0, 99.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 0

    def test_no_signal_when_ma_data_not_ready(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        closes = [106.0, 107.0, 108.0]
        df = self._make_history_df(closes)
        df["MA20"] = float("nan")
        df["MA200"] = float("nan")
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[107.0, 108.0, 109.0], lows=[105.0, 106.0, 107.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 0

    def test_get_latest_bar_returns_none_when_no_history(self):
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
        )

        assert engine.get_latest_bar("NVDA") is None

    def test_get_latest_bar_returns_last_row(self):
        closes = [100.0, 102.0, 104.0]
        df = _build_history_df(closes, ma20=95.0, ma50=93.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)

        latest = engine.get_latest_bar("NVDA")

        assert latest is not None
        assert latest["Close"] == 104.0

    def test_aggregate_bars_builds_correct_ohlcv(self):
        engine = LiveSignalEngine(
            tickers=["AMD"], api_key="k", secret_key="s", opening_bars=3
        )
        period_start = ET.localize(datetime(2026, 3, 24, 9, 30))
        bars = _make_mock_bars(
            "AMD",
            highs=[101.0, 102.0, 103.0, 104.0, 105.0],
            lows=[99.0, 100.0, 101.0, 102.0, 103.0],
        )
        for i, b in enumerate(bars):
            b.open = 100.0 + i
            b.close = 100.5 + i
            b.volume = 1000.0

        result = engine._aggregate_bars("AMD", period_start, bars)

        assert result.symbol == "AMD"
        assert result.timestamp == period_start
        assert result.open == 100.0
        assert result.high == 105.0
        assert result.low == 99.0
        assert result.close == 104.5
        assert result.volume == 5000.0

    def test_process_five_min_bar_accumulates_opening_bars(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["AMD"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )
        closes = [104.0, 105.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["AMD"] = df

        bar1 = _FiveMinBar(
            "AMD",
            ET.localize(datetime(2026, 3, 24, 9, 30)),
            102.0,
            103.0,
            101.0,
            102.5,
            1000.0,
        )
        bar2 = _FiveMinBar(
            "AMD",
            ET.localize(datetime(2026, 3, 24, 9, 35)),
            103.0,
            104.0,
            102.0,
            103.5,
            1000.0,
        )

        engine._process_five_min_bar(bar1)
        assert len(engine._opening_buf["AMD"]) == 1
        assert len(fired_events) == 0

        engine._process_five_min_bar(bar2)
        assert len(engine._opening_buf["AMD"]) == 2
        assert len(fired_events) == 0

    def test_process_five_min_bar_calls_try_fire_signal_on_third_bar(self):
        engine = LiveSignalEngine(
            tickers=["AMD"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
        )
        closes = [104.0, 105.0, 106.0]
        engine._history["AMD"] = self._make_history_df(closes, ma20=100.0, ma200=90.0)

        bars = [
            _FiveMinBar(
                "AMD",
                ET.localize(datetime(2026, 3, 24, 9, 30)),
                104.0,
                105.0,
                99.0,
                104.0,
                1000.0,
            ),
            _FiveMinBar(
                "AMD",
                ET.localize(datetime(2026, 3, 24, 9, 35)),
                104.0,
                106.0,
                100.0,
                105.0,
                1000.0,
            ),
            _FiveMinBar(
                "AMD",
                ET.localize(datetime(2026, 3, 24, 9, 40)),
                105.0,
                107.0,
                103.0,
                106.0,
                1000.0,
            ),
        ]

        with patch.object(engine, "_try_fire_signal") as mock_fire:
            for b in bars:
                engine._process_five_min_bar(b)

        mock_fire.assert_called_once()
        assert mock_fire.call_args[0][0] == "AMD"
        assert engine._signal_fired["AMD"] is True

    def test_regime_filter_suppresses_bullish_signal_on_bearish_day(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
            regime_filter=True,
        )
        today = datetime.now(ET).date()
        engine._bearish_regime_dates = {today}

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 0

    def test_regime_filter_allows_bullish_signal_on_non_bearish_day(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
            regime_filter=True,
        )
        engine._bearish_regime_dates = set()  # today is not bearish

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BULLISH"

    def test_regime_filter_does_not_suppress_bearish_signal(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
            regime_filter=True,
        )
        today = datetime.now(ET).date()
        engine._bearish_regime_dates = {today}  # bearish regime active

        # OR range 95-105, bottom_30=97, close=96 → BEARISH
        closes = [100.0, 98.0, 96.0]
        df = self._make_history_df(closes, ma20=105.0, ma200=110.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[101.0, 99.0, 97.0], lows=[99.0, 97.0, 95.0]
        )
        engine._opening_buf["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BEARISH"


# ---------------------------------------------------------------------------
# TestPositionMonitor — stop evaluation logic
# ---------------------------------------------------------------------------


_SLEEP_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine.time.sleep"
)


class TestPositionMonitor:
    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine.time.sleep",
            lambda _: None,
        )

    def test_bullish_hard_stop_arms_then_triggers(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-1"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH",
            or_high=105.0,
            or_low=95.0,
            hard_stop_price=103.5,
            fallback_price=103.0,
        )

        closes = [100.0, 104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # First bar: close 104 > hard_stop 103.5 → arm but not exit
        _set_latest_bar(engine, "NVDA", close=104.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.hard_stop_armed is True
        assert pos.is_closed is False

        # Second bar: close drops to 103 ≤ hard_stop 103.5 → exit
        _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"

    def test_bullish_trailing_stop_triggers_below_ma20(self):
        # MA20=106 > hard_stop=103.5 (activation gate passes) and close=104 < MA20=106
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-2"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )
        pos.hard_stop_armed = True

        closes = [104.0]
        df = _build_history_df(closes, ma20=106.0, ma50=105.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # MA20=106 > hard_stop=103.5 → gate passes; close=104 < MA20=106 → trailing stop
        _set_latest_bar(engine, "NVDA", close=104.0, ma50=105.0, ma20=106.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_bullish_fallback_triggers_when_not_yet_armed(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-3"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )

        closes = [102.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # close 102 ≤ fallback 103, and hard stop never armed → fallback
        _set_latest_bar(engine, "NVDA", close=102.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "fallback_20pct"

    def test_bearish_hard_stop_arms_then_triggers(self):
        # OR: 90-100, range=10
        # hard_stop (bear) = 91.5  (arms when close dips BELOW this level)
        # fallback (bear)  = 93.0  (exits when close goes ABOVE this before arming)
        # Sequence:
        #   close=91.7 → not armed (91.7 > 91.5); no fallback (91.7 < 93) → nothing
        #   close=91.0 → arm      (91.0 < 91.5); 91.0 >= 91.5 is False → no exit
        #   close=92.5 → armed AND 92.5 >= 91.5 → exit "hard_stop"
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-4"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BEARISH",
            or_high=_D("100"),
            or_low=_D("90"),
            hard_stop_price=_D("91.5"),
            fallback_price=_D("93"),
        )

        closes = [95.0]
        df = _build_history_df(closes, ma20=110.0, ma50=110.0, ma200=115.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # close=91.7 > 91.5 → not armed; 91.7 < fallback 93 → no fallback
        _set_latest_bar(engine, "NVDA", close=91.7, ma50=110.0)
        monitor.on_bar("NVDA")
        assert pos.hard_stop_armed is False
        assert pos.is_closed is False

        # close=91.0 < 91.5 → arm; 91 >= 91.5 is False → no exit yet
        _set_latest_bar(engine, "NVDA", close=91.0, ma50=110.0)
        monitor.on_bar("NVDA")
        assert pos.hard_stop_armed is True
        assert pos.is_closed is False

        # close=92.5 >= 91.5 while armed → exit hard_stop
        _set_latest_bar(engine, "NVDA", close=92.5, ma50=110.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"

    def test_bearish_trailing_stop_triggers_above_ma20(self):
        # MA20=88 < or_low=90 (activation gate passes) and close=93 > MA20=88
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-5"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BEARISH",
            or_high=_D("100"),
            or_low=_D("90"),
            hard_stop_price=_D("96.5"),
            fallback_price=_D("98"),
        )
        pos.hard_stop_armed = True

        closes = [93.0]
        df = _build_history_df(closes, ma20=88.0, ma50=92.0, ma200=115.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # MA20=88 < or_low=90 → gate passes; close=93 > MA20=88 → trailing stop
        _set_latest_bar(engine, "NVDA", close=93.0, ma50=92.0, ma20=88.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_position_not_closed_while_favorable(self):
        client = _make_alpaca_client()

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )
        pos.hard_stop_armed = True

        closes = [110.0]
        df = _build_history_df(closes, ma20=90.0, ma50=100.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # close 110 > MA50 100, > hard_stop 103.5 → no exit
        _set_latest_bar(engine, "NVDA", close=110.0, ma50=100.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is False
        client.place_option_order.assert_not_called()

    def test_close_all_marks_all_open_positions_closed(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-close"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos1 = _make_active_position(signal="BULLISH")
        pos2 = _make_active_position(signal="BEARISH")
        pos2.option_symbol = "NVDA260328C00900000"

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=88.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos1)
        monitor.add_position(pos2)

        monitor.close_all(reason="end_of_day")

        assert pos1.is_closed is True
        assert pos1.exit_reason == "end_of_day"
        assert pos2.is_closed is True
        assert pos2.exit_reason == "end_of_day"

    def test_max_loss_pct_exits_bullish_position_immediately(self):
        # entry_stock_price=104, close=101 → loss = (104-101)/104 ≈ 2.88% ≥ max_loss_pct=2%
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ml-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )

        closes = [101.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, max_loss_pct=0.02)
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=101.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "max_loss"

    def test_max_loss_pct_exits_bearish_position_immediately(self):
        # BEARISH: entry_stock_price=104, close=107 → loss = (107-104)/104 ≈ 2.88% ≥ 2%
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ml-2"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BEARISH",
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=_D("96.5"),
            fallback_price=_D("97.0"),
        )

        closes = [107.0]
        df = _build_history_df(closes, ma20=110.0, ma50=110.0, ma200=115.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, max_loss_pct=0.02)
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=107.0, ma50=110.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "max_loss"

    def test_max_loss_pct_does_not_exit_when_loss_within_threshold(self):
        # entry_stock_price=104, close=103 → loss = 1/104 ≈ 0.96% < 2%
        client = _make_alpaca_client()
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("101.0"), fallback_price=_D("102.0")
        )

        closes = [103.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, max_loss_pct=0.02)
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is False

    def test_armed_ma20_exit_bullish_trails_ma20_once_armed(self):
        # hard_stop=103.5
        # bar 1: close=106 > 103.5 → arm; MA20=104 < close=106 → close < MA20 is False → no exit
        # bar 2: close=105 < MA20=108 → exit trailing_stop_ma20
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ame-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )

        closes = [106.0, 105.0]
        df = _build_history_df(closes, ma20=104.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, armed_ma20_exit=True)
        monitor.add_position(pos)

        # Bar 1: arm; MA20=104 < close=106 → close not below MA20 → no exit
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=90.0, ma20=104.0)
        monitor.on_bar("NVDA")
        assert pos.hard_stop_armed is True
        assert pos.is_closed is False

        # Bar 2: armed + close=105 < MA20=108 → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=105.0, ma50=90.0, ma20=108.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_armed_ma20_exit_bearish_trails_ma20_once_armed(self):
        # OR: 90-100; hard_stop=96.5
        # bar 1: close=93 < 96.5 → arm; MA20=95 > close=93 → close > MA20 is False → no exit
        # bar 2: close=95 > MA20=88 → exit trailing_stop_ma20
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ame-2"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BEARISH",
            or_high=_D("100"),
            or_low=_D("90"),
            hard_stop_price=_D("96.5"),
            fallback_price=_D("98.0"),
        )

        closes = [93.0, 95.0]
        df = _build_history_df(closes, ma20=95.0, ma50=110.0, ma200=115.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, armed_ma20_exit=True)
        monitor.add_position(pos)

        # Bar 1: arm; MA20=95 > close=93 → close not above MA20 → no exit
        _set_latest_bar(engine, "NVDA", close=93.0, ma50=110.0, ma20=95.0)
        monitor.on_bar("NVDA")
        assert pos.hard_stop_armed is True
        assert pos.is_closed is False

        # Bar 2: armed + close=95 > MA20=88 → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=95.0, ma50=110.0, ma20=88.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_armed_ma20_exit_falls_back_to_hard_stop_when_ma20_unavailable(self):
        # armed + no MA20 → hard stop is used as exit
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ame-3"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )
        pos.hard_stop_armed = True

        closes = [103.0]
        df = _build_history_df(closes, ma20=float("nan"), ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, armed_ma20_exit=True)
        monitor.add_position(pos)

        # No MA20 available + armed + close=103 ≤ hard_stop=103.5 → hard_stop
        _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"

    def test_already_closed_position_is_not_closed_again(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-close"}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=88.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        monitor.close_all(reason="end_of_day")

        client.place_option_order.assert_not_called()
        assert pos.exit_reason == "hard_stop"


# ---------------------------------------------------------------------------
# Private helpers for building test fixtures
# ---------------------------------------------------------------------------


def _make_mock_bars(ticker, highs, lows):
    bars = []
    for h, l in zip(highs, lows):
        bar = Mock()
        bar.symbol = ticker
        bar.high = h
        bar.low = l
        bar.open = (h + l) / 2.0
        bar.close = (h + l) / 2.0
        bar.volume = 1000.0
        bar.timestamp = datetime.now(ET)
        bars.append(bar)
    return bars


def _build_history_df(closes, ma20, ma50, ma200):
    today = datetime.now(ET).date()
    timestamps = [
        ET.localize(
            datetime.combine(today, datetime.min.time())
            + timedelta(hours=9, minutes=30 + i * 5)
        )
        for i in range(len(closes))
    ]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1000.0] * len(closes),
            "MA20": ma20,
            "MA50": ma50,
            "MA200": ma200,
        },
        index=timestamps,
    )
    return df


def _set_latest_bar(engine, ticker, close, ma50, ma20=None):
    """Overwrite the last row of history to simulate a new bar."""
    df = engine._history[ticker].copy()
    df.iloc[-1, df.columns.get_loc("Close")] = float(close)
    df.iloc[-1, df.columns.get_loc("MA50")] = float(ma50)
    if ma20 is not None:
        df.iloc[-1, df.columns.get_loc("MA20")] = float(ma20)
    engine._history[ticker] = df


def _make_option_quote(bid, ask):
    q = Mock()
    q.bid_price = bid
    q.ask_price = ask
    return q
