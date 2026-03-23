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
    ActivePosition,
    LiveSignalEngine,
    OptionContractSelector,
    PositionMonitor,
    PositionSizer,
    TickerSelector,
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
            strike_price_gte="720",
            strike_price_lte="740",
            limit=20,
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
        assert call_args.kwargs["strike_price_lte"] == "115"
        assert call_args.kwargs["strike_price_gte"] == "105"
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


class TestTickerSelector:
    @patch(_SELECT_TOP_N_PATH)
    def test_returns_top_n_tickers_by_composite_score(self, mock_select_top_n):
        mock_select_top_n.return_value = {
            "picks": [
                {"ticker": "NVDA", "signal": "BULLISH", "score": 4.2, "ev_trade": 0.8},
                {"ticker": "CRWD", "signal": "BEARISH", "score": 3.1, "ev_trade": 0.5},
            ],
            "no_signal": ["COIN"],
            "negative_ev": [],
        }

        selector = TickerSelector(tickers=["NVDA", "CRWD", "COIN"], top_n=2)
        result = selector.select()

        assert result == ["NVDA", "CRWD"]
        mock_select_top_n.assert_called_once()

    @patch(_SELECT_TOP_N_PATH)
    def test_falls_back_to_previous_day_when_today_has_no_picks(
        self, mock_select_top_n
    ):
        mock_select_top_n.side_effect = [
            {"picks": [], "no_signal": ["NVDA", "CRWD"], "negative_ev": []},
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
            },
        ]

        selector = TickerSelector(tickers=["NVDA", "CRWD"], top_n=2)
        result = selector.select()

        assert result == ["NVDA"]
        assert mock_select_top_n.call_count == 2


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


# ---------------------------------------------------------------------------
# TestPositionMonitor — stop evaluation logic
# ---------------------------------------------------------------------------


class TestPositionMonitor:
    def test_bullish_hard_stop_arms_then_triggers(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-1"}
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

    def test_bullish_trailing_stop_triggers_below_ma50(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-2"}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0")
        )
        pos.hard_stop_armed = True

        closes = [104.0]
        df = _build_history_df(closes, ma20=95.0, ma50=105.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # close 104 < MA50 105 → trailing stop
        _set_latest_bar(engine, "NVDA", close=104.0, ma50=105.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma50"

    def test_bullish_fallback_triggers_when_not_yet_armed(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-3"}
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

    def test_bearish_trailing_stop_triggers_above_ma50(self):
        # Bearish trailing stop: close CROSSES ABOVE MA50 (trend reversing up)
        # hard_stop_price=96.5 (high), armed=True; close=93 < 96.5 → hard_stop does NOT fire
        # MA50=92 < close=93 → close > MA50 → trailing stop fires
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-5"}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

        pos = _make_active_position(
            signal="BEARISH",
            or_high=_D("100"),
            or_low=_D("90"),
            hard_stop_price=_D("96.5"),  # high; close=93 < 96.5 → armed check fails
            fallback_price=_D("98"),
        )
        pos.hard_stop_armed = True

        closes = [93.0]
        df = _build_history_df(closes, ma20=110.0, ma50=92.0, ma200=115.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # armed AND close=93 >= hard_stop=96.5 → False (no hard_stop exit)
        # close=93 > MA50=92 → trailing stop fires
        _set_latest_bar(engine, "NVDA", close=93.0, ma50=92.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma50"

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


def _set_latest_bar(engine, ticker, close, ma50):
    """Overwrite the last row of history to simulate a new bar."""
    df = engine._history[ticker].copy()
    df.iloc[-1, df.columns.get_loc("Close")] = float(close)
    df.iloc[-1, df.columns.get_loc("MA50")] = float(ma50)
    engine._history[ticker] = df


def _make_option_quote(bid, ask):
    q = Mock()
    q.bid_price = bid
    q.ask_price = ask
    return q
