import logging
import pytest
from unittest.mock import patch

from alpha_tech_tracker.op_momentum_strategy.position_monitor import (
    PositionMonitor,
    _QUICK_EXIT_MAX_SECONDS,
    _quick_exit_entry_price,
)

from conftest import (
    _D,
    _build_history_df,
    _make_active_position,
    _make_alpaca_client,
    _make_closed_position,
    _make_closed_stock_position,
    _make_option_quote,
    _make_signal_engine_with_history,
    _make_stock_position,
    _set_latest_bar,
)

import pandas as pd


class TestPositionMonitor:
    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def test_bullish_hard_stop_arms_then_triggers(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-1"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-2"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-4"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-5"}
        client.order_status.return_value = {
            "status": "filled",
            "filled_avg_price": 5.25,
        }
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ml-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ml-2"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ame-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ame-2"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-ame-3"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

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

    def test_no_exit_on_entry_bar_even_when_fallback_condition_is_met(self):
        """
        Regression: a position whose close is above midpoint but below fallback_price
        must not exit on the same bar that triggered entry.

        Scenario (mirrors the SHOP 2026-03-31 bug):
          OR high=120, low=100, range=20
          midpoint=110, fallback=116, hard_stop=117
          entry close=112 (above midpoint → BULLISH, but also ≤ fallback)
        """
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

        pos = _make_active_position(
            signal="BULLISH",
            or_high=_D("120"),
            or_low=_D("100"),
            hard_stop_price=_D("117"),   # 120 - 0.15*20
            fallback_price=_D("116"),    # 120 - 0.20*20
        )

        from datetime import datetime
        import pytz
        ET = pytz.timezone("America/New_York")
        entry_bar_ts = ET.localize(datetime(2026, 3, 31, 13, 15))
        pos.entry_bar_time = entry_bar_ts

        closes = [112.0]
        df = _build_history_df(closes, ma20=108.0, ma50=105.0, ma200=100.0)
        # Set the last bar's index to match entry_bar_ts
        df.index = [entry_bar_ts]
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        # on_bar with the entry bar itself — must NOT exit
        monitor.on_bar("NVDA")
        assert pos.is_closed is False

    def test_exits_on_bar_after_entry_when_fallback_condition_met(self):
        """After the entry bar, fallback_20pct should fire normally."""
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

        pos = _make_active_position(
            signal="BULLISH",
            or_high=_D("120"),
            or_low=_D("100"),
            hard_stop_price=_D("117"),
            fallback_price=_D("116"),
        )

        from datetime import datetime
        import pytz
        ET = pytz.timezone("America/New_York")
        entry_bar_ts = ET.localize(datetime(2026, 3, 31, 13, 15))
        pos.entry_bar_time = entry_bar_ts

        closes = [112.0]
        df = _build_history_df(closes, ma20=108.0, ma50=105.0, ma200=100.0)
        df.index = [entry_bar_ts]
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(pos)

        # Next bar (different timestamp, same fallback condition) → should exit
        _set_latest_bar(engine, "NVDA", close=112.0, ma50=105.0, ma20=108.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "fallback_20pct"


class TestPrintSummaryPnl:
    def test_bullish_call_profit_when_exit_above_entry(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BULLISH", entry_mid=13.86, exit_mid=14.21)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "+$35.00" in caplog.text

    def test_bullish_call_loss_when_exit_below_entry(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BULLISH", entry_mid=14.21, exit_mid=13.86)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "-$35.00" in caplog.text

    def test_bearish_put_profit_when_exit_above_entry(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BEARISH", entry_mid=13.72, exit_mid=21.35)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "+$763.00" in caplog.text

    def test_bearish_put_loss_when_exit_below_entry(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BEARISH", entry_mid=21.35, exit_mid=13.72)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "-$763.00" in caplog.text


class TestStockClosePosition:
    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def test_stock_close_calls_place_stock_order_not_option_order(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "stk-close-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=30)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        monitor.close_all(reason="end_of_day")

        client.place_stock_order.assert_called_once()
        client.place_option_order.assert_not_called()
        assert pos.is_closed is True
        assert pos.exit_reason == "end_of_day"

    def test_stock_simulate_sets_exit_mid_from_bar_close_in_replay_mode(self):
        client = _make_alpaca_client()

        pos = _make_stock_position(signal="BULLISH", shares=20)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode", return_value=True):
            monitor.close_all(reason="end_of_day")

        # replay: exit mid uses the signal engine's latest bar close, not a live API quote
        assert pos.simulated_exit_mid == _D("104.00")
        client.get_stock_quote.assert_not_called()
        client.place_stock_order.assert_not_called()

    def test_stock_simulate_sets_exit_mid_from_live_quote_in_mock_live_mode(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 98.0, "ask": 102.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }

        pos = _make_stock_position(signal="BULLISH", shares=20)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode", return_value=False):
            monitor.close_all(reason="end_of_day")

        # live mock: exit mid uses the live quote mid
        assert pos.simulated_exit_mid == _D("100.00")
        client.get_stock_quote.assert_called_once()
        client.place_stock_order.assert_not_called()

    def test_stock_stop_triggers_via_evaluate_stop(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "stk-stop-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(
            signal="BULLISH",
            hard_stop_price=_D("103.5"),
            fallback_price=_D("103.0"),
            shares=10,
        )
        pos.hard_stop_armed = True

        closes = [103.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        client.place_stock_order.assert_called_once()

    def test_alpaca_feed_forwarded_to_get_stock_quote_on_close(self):
        from alpaca.data.enums import DataFeed
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "stk-feed-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=10)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, alpaca_feed=DataFeed.IEX)
        monitor.add_position(pos)

        monitor.close_all(reason="trailing_stop")

        call_args = client.get_stock_quote.call_args
        assert call_args.kwargs.get("feed") == DataFeed.IEX

    def test_alpaca_feed_forwarded_to_get_stock_quote_first_call_on_close(self):
        from alpaca.data.enums import DataFeed
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "stk-feed-2"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=10)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, alpaca_feed=DataFeed.IEX)
        monitor.add_position(pos)

        monitor.close_all(reason="trailing_stop")

        first_call = client.get_stock_quote.call_args_list[0]
        assert first_call.kwargs.get("feed") == DataFeed.IEX

    def test_alpaca_feed_forwarded_to_get_stock_quote_in_print_status(self):
        from alpaca.data.enums import DataFeed
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.entry_fill_price = _D("100.00")
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, alpaca_feed=DataFeed.IEX)
        monitor.add_position(pos)

        monitor.print_status()

        call_args = client.get_stock_quote.call_args
        assert call_args.kwargs.get("feed") == DataFeed.IEX


    def test_latest_bar_close_passed_as_signal_price_on_close(self):
        client = _make_alpaca_client()
        client.place_stock_order.return_value = {"order_id": "stk-sig-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=10)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        _set_latest_bar(engine, "NVDA", close=103.75, ma50=90.0)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_stock_order"
        ) as mock_place:
            mock_place.return_value = {"order_id": "stk-sig-1"}
            monitor.close_all(reason="trailing_stop")

        mock_place.assert_called_once()
        _, kwargs = mock_place.call_args
        assert kwargs.get("signal_price") == 103.75

    def test_signal_price_none_when_no_latest_bar_on_close(self):
        client = _make_alpaca_client()
        client.place_stock_order.return_value = {"order_id": "stk-sig-2"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=10)
        df = _build_history_df([], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_stock_order"
        ) as mock_place:
            mock_place.return_value = {"order_id": "stk-sig-2"}
            monitor.close_all(reason="trailing_stop")

        mock_place.assert_called_once()
        _, kwargs = mock_place.call_args
        assert kwargs.get("signal_price") is None

    def test_close_all_with_callback_that_calls_get_all_positions_does_not_deadlock(self):
        # Regression test: close_all previously held self._lock while calling
        # _close_position, which triggered close_callback → get_all_positions →
        # self._lock → permanent deadlock. The second position (MSTR equivalent)
        # would never be closed.
        import threading

        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "stk-dd-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)

        closed_tickers = []

        def close_callback(pos):
            # Simulates _flush_session_state calling get_all_positions — this
            # re-acquires self._lock and deadlocks if close_all still holds it.
            monitor.get_all_positions()
            closed_tickers.append(pos.ticker)

        monitor = PositionMonitor(client, engine, close_callback=close_callback)

        pos1 = _make_stock_position(signal="BULLISH", shares=10)
        pos1.ticker = "APP"
        pos2 = _make_stock_position(signal="BULLISH", shares=15)
        pos2.ticker = "MSTR"
        monitor.add_position(pos1)
        monitor.add_position(pos2)

        done = threading.Event()

        def run():
            monitor.close_all(reason="end_of_day")
            done.set()

        t = threading.Thread(target=run)
        t.start()
        completed = done.wait(timeout=5.0)

        assert completed, "close_all deadlocked — second position was never closed"
        assert pos1.is_closed is True
        assert pos2.is_closed is True
        assert set(closed_tickers) == {"APP", "MSTR"}


class TestCloseOrderRetry:
    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def test_on_bar_retries_failed_stock_close_within_same_bar(self, caplog):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
        }}
        client.place_stock_order.side_effect = [Exception("network error"), {"order_id": "retry-1"}]
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.hard_stop_armed = True
        df = _build_history_df([102.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            with caplog.at_level(logging.WARNING):
                _set_latest_bar(engine, "NVDA", close=102.0, ma50=90.0)
                monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.close_order_failed is False
        assert pos.exit_order_id == "retry-1"
        assert client.place_stock_order.call_count == 2
        assert any("Retrying failed close order" in r.message for r in caplog.records)

    def test_on_bar_retries_failed_option_close_within_same_bar(self, caplog):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)
        client.place_option_order.side_effect = [Exception("timeout"), {"order_id": "retry-opt-1"}]
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.25}

        pos = _make_active_position(signal="BULLISH")
        pos.hard_stop_armed = True
        df = _build_history_df([102.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            with caplog.at_level(logging.WARNING):
                _set_latest_bar(engine, "NVDA", close=102.0, ma50=90.0)
                monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.close_order_failed is False
        assert pos.exit_order_id == "retry-opt-1"
        assert client.place_option_order.call_count == 2
        assert any("Retrying failed close order" in r.message for r in caplog.records)

    def test_close_callback_not_called_again_on_retry(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
        }}
        client.place_stock_order.side_effect = [Exception("network error"), {"order_id": "retry-2"}]
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.hard_stop_armed = True
        df = _build_history_df([102.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)

        callback_calls = []
        monitor = PositionMonitor(client, engine, close_callback=lambda p: callback_calls.append(p))
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=102.0, ma50=90.0)
            monitor.on_bar("NVDA")
            _set_latest_bar(engine, "NVDA", close=102.5, ma50=90.0)
            monitor.on_bar("NVDA")

        assert len(callback_calls) == 1


class TestStockPrintSummaryPnl:
    def test_stock_profit_uses_shares_not_contracts_multiplier(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_stock_position("BULLISH", entry_mid=100.0, exit_mid=102.0, shares=10)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        # P&L = (102 - 100) * 10 shares = +$20 (not * 100)
        assert "+$20.00" in caplog.text

    def test_stock_loss_uses_shares_not_contracts_multiplier(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_stock_position("BULLISH", entry_mid=102.0, exit_mid=100.0, shares=10)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "-$20.00" in caplog.text

    def test_stock_summary_shows_shares_label_not_option_symbol(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_stock_position("BULLISH", entry_mid=100.0, exit_mid=101.0, shares=5)
        )

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "[stock]" in caplog.text
        assert "5sh" in caplog.text


class TestMockOptionExitPricing:
    # strike $90 call — ITM when stock=$100 (intrinsic=$10)
    _CALL_SYM = "NVDA260328C00090000"
    # strike $110 put — ITM when stock=$100 (intrinsic=$10)
    _PUT_SYM = "NVDA260328P00110000"

    def _make_option_pos(self, signal, option_symbol, entry_stock_price, entry_mid):
        pos = _make_active_position(signal=signal)
        pos.option_symbol = option_symbol
        pos.entry_stock_price = _D(str(entry_stock_price))
        pos.simulated_entry_mid = _D(str(entry_mid))
        return pos

    def _run_eod_close(self, pos, exit_stock_price):
        client = _make_alpaca_client()
        df = _build_history_df([100.0], ma20=95.0, ma50=95.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(pos)
        _set_latest_bar(engine, "NVDA", close=exit_stock_price, ma50=95.0)
        monitor.close_all(reason="end_of_day")
        return client

    def test_call_exit_skips_api_quote_in_mock_mode(self):
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        client = self._run_eod_close(pos, exit_stock_price=102.0)

        client.get_option_quote_by_occ.assert_not_called()

    def test_call_exit_price_increases_when_stock_rises(self):
        # entry: stock=$100, strike=$90 → entry_iv=$10, entry_tp=$2.00
        # exit: stock=$102, bars_held=0 < 12 → no time decay
        # exit_iv=$12, exit_tp=$2.00, exit_price=$14.00
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        self._run_eod_close(pos, exit_stock_price=102.0)

        assert pos.simulated_exit_mid == _D("14.00")

    def test_call_exit_price_decreases_when_stock_falls(self):
        # exit: stock=$98, bars_held=0 < 12 → no time decay
        # exit_iv=$8, exit_tp=$2.00, exit_price=$10.00
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        self._run_eod_close(pos, exit_stock_price=98.0)

        assert pos.simulated_exit_mid == _D("10.00")

    def test_put_exit_price_increases_when_stock_falls(self):
        # entry: stock=$100, strike=$110 → put_iv=$10, entry_tp=$2.00
        # exit: stock=$98, bars_held=0 < 12 → no time decay
        # put_iv=$12, exit_tp=$2.00, exit_price=$14.00
        pos = self._make_option_pos("BEARISH", self._PUT_SYM, 100, "12.00")
        self._run_eod_close(pos, exit_stock_price=98.0)

        assert pos.simulated_exit_mid == _D("14.00")

    def test_no_time_decay_for_quick_exit_when_stock_flat(self):
        # bars_held=0 < 12 → time_decay=1.0; stock flat so only intrinsic matters
        # exit_iv=$10, exit_tp=$2.00 (no decay), exit_price=$12.00
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        self._run_eod_close(pos, exit_stock_price=100.0)

        assert pos.simulated_exit_mid == _D("12.00")

    def test_no_time_decay_when_held_longer_than_one_hour(self):
        # bars_held=12 ≥ 12 → time_decay=1.0 (disabled); stock flat
        # exit_iv=$10, exit_tp=$2×1.0=$2.00, exit_price=$12.00
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        pos.bars_held = 12
        self._run_eod_close(pos, exit_stock_price=100.0)

        assert pos.simulated_exit_mid == _D("12.00")


class TestOptionExitSkipsFairPriceInMockMode:
    """Regression: option_price_monitor.get_fair_price() must not be called during
    mock/simulate exits — it has no live option feed in replay mode and returns 0,
    which previously caused simulated_exit_mid=0 for all options trades."""

    _CALL_SYM = "NVDA260328C00090000"

    def _make_monitor_with_opm(self, exit_stock_price=100.0):
        from unittest.mock import Mock
        client = _make_alpaca_client()
        df = _build_history_df([100.0], ma20=95.0, ma50=95.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        opm = Mock()
        opm.get_fair_price.return_value = _D("0")
        monitor._option_price_monitor = opm
        pos = _make_active_position(signal="BULLISH")
        pos.option_symbol = self._CALL_SYM
        pos.entry_stock_price = _D("100")
        pos.simulated_entry_mid = _D("12.00")
        monitor.add_position(pos)
        _set_latest_bar(engine, "NVDA", close=exit_stock_price, ma50=95.0)
        monitor.close_all(reason="end_of_day")
        return monitor, opm, pos

    def test_get_fair_price_not_called_at_exit_in_mock_mode(self):
        _, opm, _ = self._make_monitor_with_opm()
        opm.get_fair_price.assert_not_called()

    def test_simulated_exit_mid_is_nonzero_when_opm_attached(self):
        _, _, pos = self._make_monitor_with_opm(exit_stock_price=102.0)
        assert pos.simulated_exit_mid > _D("0")

    def test_simulated_exit_mid_reflects_stock_move_not_opm_zero(self):
        # stock rises $2 → call exit price should be higher than entry
        _, _, pos = self._make_monitor_with_opm(exit_stock_price=102.0)
        assert pos.simulated_exit_mid > pos.simulated_entry_mid


class TestReentryWatcher:
    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def _make_bearish_pos(self, bars_held=0):
        pos = _make_active_position(
            signal="BEARISH",
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=_D("96.5"),
            fallback_price=_D("97.0"),
        )
        pos.bars_held = bars_held
        return pos

    def _make_bullish_pos(self, bars_held=0):
        pos = _make_active_position(
            signal="BULLISH",
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=_D("103.5"),
            fallback_price=_D("103.0"),
        )
        pos.bars_held = bars_held
        return pos

    def _make_monitor(self, client=None, **kwargs):
        if client is None:
            client = _make_alpaca_client()
            client.place_option_order.return_value = {"order_id": "close-x"}
            client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
            client.get_option_quote_by_occ.return_value = _make_option_quote(bid=4.0, ask=5.0)
        df = _build_history_df([100.0], ma20=98.0, ma50=97.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        return PositionMonitor(client, engine, mock_trade_execution=True, **kwargs), client, engine

    def test_bars_held_increments_while_position_is_open(self):
        monitor, client, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=106.5, ma50=97.0)
        monitor.on_bar("NVDA")

        assert pos.bars_held == 2
        assert pos.is_closed is False

    def test_bars_held_not_double_counted_on_repeated_poll_same_bar(self):
        monitor, client, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0)
        monitor.on_bar("NVDA")
        # Poll again without advancing the bar — same timestamp returned
        monitor.on_bar("NVDA")

        assert pos.bars_held == 1

    def test_bars_held_increments_on_new_bar_after_repeated_poll(self):
        monitor, client, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0)
        monitor.on_bar("NVDA")
        # Repeated poll on bar 1
        monitor.on_bar("NVDA")
        # New bar arrives
        _set_latest_bar(engine, "NVDA", close=106.5, ma50=97.0)
        monitor.on_bar("NVDA")

        assert pos.bars_held == 2

    def test_reversal_watcher_created_on_bearish_hard_stop_within_max_bars(self):
        monitor, _, engine = self._make_monitor(enable_reversal=True, reversal_max_bars=3)
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert len(monitor._reentry_watchers) == 1
        assert monitor._reentry_watchers[0].reentry_type == "reversal"
        assert monitor._reentry_watchers[0].ticker == "NVDA"

    def test_reversal_watcher_not_created_when_bars_held_exceeds_max(self):
        monitor, _, engine = self._make_monitor(enable_reversal=True, reversal_max_bars=3)
        pos = self._make_bearish_pos(bars_held=4)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert len(monitor._reentry_watchers) == 0

    def test_reversal_watcher_not_created_on_trailing_ma_exit(self):
        monitor, _, engine = self._make_monitor(enable_reversal=True, reversal_max_bars=3)
        pos = self._make_bearish_pos(bars_held=1)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        # MA20=88 < or_low=95, close=90 > MA20 but below hard_stop=96.5 → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=90.0, ma50=110.0, ma20=88.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"
        assert len(monitor._reentry_watchers) == 0

    def test_reversal_fires_when_price_crosses_or_high(self):
        fired = []
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=3,
            re_entry_callback=lambda w, price: fired.append((w, price)),
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")
        assert len(monitor._reentry_watchers) == 1

        # Price crosses above OR high (105)
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=110.0)
        monitor.on_bar("NVDA")

        # Allow the callback thread to complete
        import time
        time.sleep(0.05)

        assert len(monitor._reentry_watchers) == 0
        assert len(fired) == 1
        w, trigger = fired[0]
        assert w.reentry_type == "reversal"
        assert trigger == _D("106.0")

    def test_reversal_and_bearish_reentry_both_created_when_both_eligible(self):
        """Both watcher types are created simultaneously; first trigger wins."""
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=3,
            enable_bearish_reentry=True, bearish_reentry_max_bars=3,
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        types = {w.reentry_type for w in monitor._reentry_watchers}
        assert types == {"reversal", "bearish_reentry"}

    def test_reversal_wins_when_both_watchers_trigger_on_same_bar(self):
        """When reversal and BRE both fire on the same bar, only reversal is returned."""
        fired = []
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=3,
            enable_bearish_reentry=True, bearish_reentry_max_bars=3,
            re_entry_callback=lambda w, close: fired.append(w),
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        # Trigger the hard stop to create both watchers.
        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")
        assert {w.reentry_type for w in monitor._reentry_watchers} == {"reversal", "bearish_reentry"}

        # Bar where BOTH triggers fire simultaneously: close < or_low=95 AND close > or_high=105
        # is impossible, so simulate by using a price that crosses or_high (reversal trigger)
        # while we manually also patch or_low to be above close (BRE trigger).
        for w in monitor._reentry_watchers:
            if w.reentry_type == "bearish_reentry":
                w.or_low = _D("120")  # force BRE to also see close=110 < or_low=120

        _set_latest_bar(engine, "NVDA", close=110.0, ma50=110.0)
        monitor.on_bar("NVDA")

        assert len(fired) == 1
        assert fired[0].reentry_type == "reversal"
        assert len(monitor._reentry_watchers) == 0

    def test_bre_fires_when_reversal_watcher_present_but_reversal_never_triggers(self):
        """BRE fires on a later bar when the reversal trigger never appeared first."""
        fired = []
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=3,
            enable_bearish_reentry=True, bearish_reentry_max_bars=3,
            re_entry_callback=lambda w, close: fired.append(w),
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        # Hard stop fires, creating both watchers.
        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        # Price falls below or_low=95 → BRE fires; reversal (needs close > or_high=105) did not.
        _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0)
        monitor.on_bar("NVDA")

        assert len(fired) == 1
        assert fired[0].reentry_type == "bearish_reentry"
        assert len(monitor._reentry_watchers) == 0

    def test_bearish_reentry_watcher_created_when_reversal_disabled(self):
        monitor, _, engine = self._make_monitor(
            enable_reversal=False,
            enable_bearish_reentry=True, bearish_reentry_max_bars=3,
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        assert len(monitor._reentry_watchers) == 1
        assert monitor._reentry_watchers[0].reentry_type == "bearish_reentry"

    def test_bearish_reentry_fires_when_price_crosses_or_low(self):
        fired = []
        monitor, _, engine = self._make_monitor(
            enable_bearish_reentry=True, bearish_reentry_max_bars=3,
            re_entry_callback=lambda w, price: fired.append((w, price)),
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        # Price crosses below OR low (95)
        _set_latest_bar(engine, "NVDA", close=94.5, ma50=110.0)
        monitor.on_bar("NVDA")

        import time
        time.sleep(0.05)

        assert len(monitor._reentry_watchers) == 0
        assert len(fired) == 1
        w, trigger = fired[0]
        assert w.reentry_type == "bearish_reentry"
        assert trigger == _D("94.5")

    def test_bullish_reentry_watcher_created_on_bullish_hard_stop(self):
        monitor, _, engine = self._make_monitor(
            enable_bullish_reentry=True, bullish_reentry_max_bars=5,
        )
        pos = self._make_bullish_pos(bars_held=3)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        # close ≤ hard_stop (103.5) while armed → hard_stop exit
        _set_latest_bar(engine, "NVDA", close=103.0, ma50=97.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert len(monitor._reentry_watchers) == 1
        assert monitor._reentry_watchers[0].reentry_type == "bullish_reentry"

    def test_watchers_cleared_on_close_all(self):
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=3,
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")
        assert len(monitor._reentry_watchers) == 1

        monitor.close_all(reason="end_of_day")

        assert len(monitor._reentry_watchers) == 0

    def test_trailing_arm_price_gates_ma_trailing_stop_for_reentry(self):
        """
        A re-entry position with trailing_arm_price set should NOT exit via trailing MA
        until price reaches the arm threshold.
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        pos.hard_stop_price = _D("98")   # midpoint as hard stop
        pos.fallback_price = _D("98")
        pos.hard_stop_armed = True
        # Arm threshold: entry + or_range = 105 + 10 = 115
        pos.trailing_arm_price = _D("115")
        monitor.add_position(pos)

        # close=106, MA20=108 > close → would trigger trailing stop if unguarded
        # but trailing_arm_price=115 not yet reached → no exit
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, ma20=108.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is False

        # close reaches arm threshold → now MA trailing stop can fire
        _set_latest_bar(engine, "NVDA", close=115.5, ma50=100.0, ma20=116.0)
        monitor.on_bar("NVDA")
        # close=115.5 < MA20=116 with arm price reached → trailing exit
        _set_latest_bar(engine, "NVDA", close=115.0, ma50=100.0, ma20=116.5)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True

    def test_trailing_arm_price_latches_for_bullish_reentry_after_price_retreats(self):
        """
        Regression: once trailing_arm_price is reached, the MA trailing stop must
        remain armed even when price subsequently falls back below the threshold.

        Bug: _trailing_armed() was re-evaluated from the current bar's close each
        call, so a retreat below trailing_arm_price silently disarmed the stop.
        Fix: trailing_arm_reached flag latches to True on first crossing.

        Sequence:
          Bar 1: close=116 >= arm_threshold=115 → latch fires, but close >= MA20=117 → no exit
          Bar 2: close=113 < arm_threshold=115 (would have disarmed before fix)
                 but latch is set → close=113 < MA20=114 → trailing_stop_ma20 exits
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        pos.hard_stop_price = _D("98")
        pos.fallback_price = _D("98")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("115")
        monitor.add_position(pos)

        # Bar 1: arm threshold reached (116 >= 115), close=116 > MA20=115 → no exit yet
        _set_latest_bar(engine, "NVDA", close=116.0, ma50=100.0, ma20=115.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False
        assert pos.trailing_arm_reached is True

        # Bar 2: price retreats below arm threshold (113 < 115) — latch must hold
        # close=113 < MA20=114 → trailing_stop_ma20 should fire
        _set_latest_bar(engine, "NVDA", close=113.0, ma50=100.0, ma20=114.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_trailing_arm_price_latches_for_bearish_reentry_after_price_retreats(self):
        """
        Bearish mirror of the latch regression: once price falls to the bearish arm
        threshold, the MA trailing stop stays armed even if price bounces back above it.

        Sequence:
          Bar 1: close=84 <= arm_threshold=85 → latch fires; MA20=96 > or_low=95
                 so trailing gate fails → no exit yet
          Bar 2: close=88 > arm_threshold=85 (would disarm before fix)
                 but latch holds → MA20=86 < or_low=95, close=88 > MA20 → exit
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("102")
        pos.fallback_price = _D("102")
        pos.hard_stop_armed = True
        # Bearish arm: price must fall to entry - or_range = 95 - 10 = 85
        pos.trailing_arm_price = _D("85")
        monitor.add_position(pos)

        # Bar 1: arm threshold reached, but MA20=96 > or_low=95 → gate fails → no exit
        _set_latest_bar(engine, "NVDA", close=84.0, ma50=110.0, ma20=96.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False
        assert pos.trailing_arm_reached is True

        # Bar 2: price bounces above arm threshold — latch must hold
        # MA20=86 < or_low=95 → gate passes; close=88 > MA20=86 → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=88.0, ma50=110.0, ma20=86.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_watcher_from_different_exit_survives_sibling_trigger(self):
        """
        Watchers from different primary exits (different primary_exit_bar_time) on
        the same ticker must not be removed when one sibling fires.

        Scenario (mirrors Jan 5 live-engine behaviour):
          - M1 BEARISH stops out at bar_time=T1 → creates reversal+BRE watchers (exit_time=T1)
          - A1 BEARISH stops out at bar_time=T2 → creates reversal+BRE watchers (exit_time=T2)
          - A1 reversal fires → only T2 siblings are removed; M1 BRE (exit_time=T1) survives
          - M1 BRE fires on a later bar → callback invoked for M1 BRE
        """
        from datetime import datetime
        fired = []
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=10,
            enable_bearish_reentry=True, bearish_reentry_max_bars=10,
            re_entry_callback=lambda w, close: fired.append(w),
        )

        t1 = datetime(2026, 1, 5, 9, 50)
        t2 = datetime(2026, 1, 5, 13, 20)
        t3 = datetime(2026, 1, 5, 13, 25)
        t4 = datetime(2026, 1, 5, 14, 30)

        from alpha_tech_tracker.op_momentum_strategy.models import ReentryWatcher
        from decimal import Decimal as D

        # Manually inject two pairs of watchers with different exit times.
        # M1 has a higher OR high (110) so it does NOT fire at close=106.
        # A1 has OR high=105 so its reversal fires at close=106.
        # M1 BRE (or_low=95) must survive and fire later at close=94.
        m1_reversal = ReentryWatcher(
            ticker="NVDA", reentry_type="reversal", primary_signal="BEARISH",
            or_high=D("110"), or_low=D("95"), or_range=D("15"), midpoint=D("102"),
            window_label="M1", rank=1, window_budget=None, primary_exit_bar_time=t1,
        )
        m1_bre = ReentryWatcher(
            ticker="NVDA", reentry_type="bearish_reentry", primary_signal="BEARISH",
            or_high=D("110"), or_low=D("95"), or_range=D("15"), midpoint=D("102"),
            window_label="M1", rank=1, window_budget=None, primary_exit_bar_time=t1,
        )
        a1_reversal = ReentryWatcher(
            ticker="NVDA", reentry_type="reversal", primary_signal="BEARISH",
            or_high=D("105"), or_low=D("95"), or_range=D("10"), midpoint=D("100"),
            window_label="A1", rank=1, window_budget=None, primary_exit_bar_time=t2,
        )
        a1_bre = ReentryWatcher(
            ticker="NVDA", reentry_type="bearish_reentry", primary_signal="BEARISH",
            or_high=D("105"), or_low=D("95"), or_range=D("10"), midpoint=D("100"),
            window_label="A1", rank=1, window_budget=None, primary_exit_bar_time=t2,
        )
        monitor._reentry_watchers = [m1_reversal, m1_bre, a1_reversal, a1_bre]

        # Bar at t3: close=106 > or_high=105 → A1 reversal fires; M1 BRE should survive.
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._now_et",
            return_value=t3,
        ):
            _set_latest_bar(engine, "NVDA", close=106.0, ma50=110.0)
            monitor.on_bar("NVDA")

        import time
        time.sleep(0.05)

        assert len(fired) == 1
        assert fired[0].reentry_type == "reversal"
        assert fired[0].window_label == "A1"

        # M1 BRE must still be in the watcher list.
        remaining = {(w.window_label, w.reentry_type) for w in monitor._reentry_watchers}
        assert ("M1", "bearish_reentry") in remaining
        assert ("M1", "reversal") in remaining

        # Bar at t4: close=94 < or_low=95 → M1 BRE fires.
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._now_et",
            return_value=t4,
        ):
            _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0)
            monitor.on_bar("NVDA")

        time.sleep(0.05)

        assert len(fired) == 2
        second_fired = [w for w in fired if w.reentry_type != "reversal" or w.window_label != "A1"]
        assert any(w.reentry_type == "bearish_reentry" and w.window_label == "M1" for w in second_fired)
        assert len(monitor._reentry_watchers) == 0


class TestPrintSummaryRefreshFills:
    """Issue 1: print_summary() must refresh fill prices before rendering in live mode."""

    def _make_monitor_with_closed_pos(self, entry_fill=None, exit_fill=None):
        client = _make_alpaca_client()
        client.order_status.side_effect = [
            {"filled_avg_price": entry_fill, "status": "filled"},
            {"filled_avg_price": exit_fill, "status": "filled"},
        ]
        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BEARISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.entry_order_id = "entry-ord-1"
        pos.exit_order_id = "exit-ord-1"
        monitor._positions.append(pos)
        return monitor, pos

    def test_print_summary_calls_refresh_fill_prices_in_live_mode(self, caplog):
        monitor, pos = self._make_monitor_with_closed_pos(
            entry_fill=8.50, exit_fill=4.20
        )
        with caplog.at_level(logging.INFO):
            monitor.print_summary()
        assert "8.50" in caplog.text
        assert "4.20" in caplog.text

    def test_print_summary_skips_refresh_in_simulate_mode(self, capsys):
        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        client = _make_alpaca_client()
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BEARISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.simulated_entry_mid = _D("8.50")
        pos.simulated_exit_mid = _D("4.20")
        monitor._positions.append(pos)

        monitor.print_summary()
        client.order_status.assert_not_called()


class TestExitSmsPrices:
    """Issue 2: exit SMS must include the option mid price."""

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def test_exit_sms_includes_mid_price_on_intraday_stop(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "close-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=4.90, ask=5.10)

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0"))
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify") as mock_notify:
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        sell_msg = mock_notify.call_args[0][0]
        assert "SELL" in sell_msg
        assert "5.00" in sell_msg

    def test_exit_sms_includes_mid_price_on_eod_close(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-1"}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=6.00, ask=6.40)

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify") as mock_notify:
            monitor.close_all(reason="end_of_day")

        sell_msg = mock_notify.call_args[0][0]
        assert "SELL" in sell_msg
        assert "6.20" in sell_msg


class TestEodMarketOrder:
    """Issue 4: EOD close must place a direct market order, not fill escalation."""

    def test_eod_option_close_places_market_order(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-market-1"}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor.close_all(reason="end_of_day")

        call_kwargs = client.place_option_order.call_args[1]
        assert call_kwargs["price_type"] == "MARKET"
        assert call_kwargs["_option_symbol_override"] == "NVDA260328C00900000"

    def test_eod_stock_close_places_market_order(self):
        client = _make_alpaca_client()
        client.place_stock_order.return_value = {"order_id": "eod-stk-1"}

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_stock_position(signal="BULLISH", shares=20)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor.close_all(reason="end_of_day")

        call_kwargs = client.place_stock_order.call_args[1]
        assert call_kwargs["order_type"] == "MARKET"
        assert call_kwargs["symbol"] == "NVDA"

    def test_intraday_stop_still_uses_fill_escalation(self):
        """Non-EOD exits must still go through _place_with_fill_escalation."""
        client = _make_alpaca_client()
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH", hard_stop_price=_D("103.5"), fallback_price=_D("103.0"))
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._place_with_fill_escalation",
            return_value={"order_id": "esc-1"},
        ) as mock_esc, \
             patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        mock_esc.assert_called_once()

    def test_close_all_does_not_hold_lock_during_api_calls(self):
        """close_all() must not hold the lock during API calls so on_bar can proceed."""
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-2"}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos1 = _make_active_position(signal="BULLISH")
        pos2 = _make_active_position(signal="BEARISH")
        monitor.add_position(pos1)
        monitor.add_position(pos2)

        lock_held_during_api_call = []

        original_get_quote = client.get_option_quote_by_occ.side_effect

        def spy_get_quote(*args, **kwargs):
            lock_held_during_api_call.append(monitor._lock.locked())
            return _make_option_quote(bid=5.0, ask=5.5)

        client.get_option_quote_by_occ.side_effect = spy_get_quote

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor.close_all(reason="end_of_day")

        assert pos1.is_closed is True
        assert pos2.is_closed is True
        assert len(lock_held_during_api_call) >= 1
        assert not any(lock_held_during_api_call), "lock must not be held during API calls"


class TestStockExitSms:
    """Unified SMS behavior for stock close: same format and price in both mock and live modes."""

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def test_mock_replay_exit_sms_has_simulate_prefix_and_mid_before_reason(self):
        client = _make_alpaca_client()
        pos = _make_stock_position(signal="BULLISH", shares=15)
        closes = [107.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode", return_value=True), \
             patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify") as mock_notify:
            monitor.close_all(reason="end_of_day")

        msg = mock_notify.call_args[0][0]
        assert msg.startswith("[SIMULATE]")
        assert "107.00" in msg
        assert msg.index("107.00") < msg.index("reason=")

    def test_mock_live_exit_sms_has_simulate_prefix_and_quote_mid(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 98.0, "ask": 102.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        pos = _make_stock_position(signal="BULLISH", shares=15)
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode", return_value=False), \
             patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify") as mock_notify:
            monitor.close_all(reason="end_of_day")

        msg = mock_notify.call_args[0][0]
        assert msg.startswith("[SIMULATE]")
        assert "100.00" in msg
        assert msg.index("100.00") < msg.index("reason=")

    def test_live_exit_sms_has_no_simulate_prefix_and_includes_quote_mid(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 198.0, "ask": 202.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "live-stk-1"}
        pos = _make_stock_position(signal="BULLISH", shares=10)
        closes = [200.0]
        df = _build_history_df(closes, ma20=190.0, ma50=190.0, ma200=185.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode", return_value=False), \
             patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify") as mock_notify:
            monitor.close_all(reason="end_of_day")

        msg = mock_notify.call_args[0][0]
        assert "[SIMULATE]" not in msg
        assert "200.00" in msg
        assert msg.index("200.00") < msg.index("reason=")

    def test_live_exit_sms_sent_before_order_is_placed(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "live-stk-2"}
        pos = _make_stock_position(signal="BULLISH", shares=10)
        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        monitor.add_position(pos)

        call_order = []

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode", return_value=False), \
             patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify",
                   side_effect=lambda msg: call_order.append("notify")) as mock_notify:
            original_place = client.place_stock_order
            def spy_place(**kwargs):
                call_order.append("order")
                return original_place(**kwargs)
            client.place_stock_order = spy_place
            monitor.close_all(reason="end_of_day")

        assert call_order[0] == "notify"
        assert "order" in call_order


class TestQuickExitEntryPrice:
    """
    _quick_exit_entry_price returns entry_fill_price (float) when the position was
    opened recently (< _QUICK_EXIT_MAX_SECONDS), and None otherwise.
    """

    _MODULE = "alpha_tech_tracker.op_momentum_strategy.position_monitor"

    def _make_pos(self, entry_fill_price=None, entry_time=None):
        pos = _make_active_position()
        pos.entry_fill_price = _D(str(entry_fill_price)) if entry_fill_price is not None else None
        pos.entry_time = entry_time
        return pos

    def _now(self):
        from datetime import datetime
        import pytz
        return datetime.now(pytz.timezone("America/New_York"))

    def test_returns_entry_fill_price_when_held_under_threshold(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=300))
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos)
        assert result == 5.0

    def test_returns_none_when_held_over_threshold(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=_QUICK_EXIT_MAX_SECONDS + 1))
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos)
        assert result is None

    def test_returns_none_when_entry_fill_price_missing(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=None, entry_time=now - timedelta(seconds=60))
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos)
        assert result is None

    def test_returns_none_when_entry_time_missing(self):
        pos = self._make_pos(entry_fill_price=5.0, entry_time=None)
        result = _quick_exit_entry_price(pos)
        assert result is None

    def test_returns_none_exactly_at_threshold(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=_QUICK_EXIT_MAX_SECONDS))
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos)
        assert result is None


class TestPollExitFillPrice:
    """_poll_exit_fill_price sets pos.exit_fill_price from order_status before _close_callback fires."""

    def _make_monitor(self, client):
        df = _build_history_df([100.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        return PositionMonitor(client, engine)

    def test_sets_exit_fill_price_when_order_status_returns_fill(self):
        client = _make_alpaca_client()
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 102.50}
        monitor = self._make_monitor(client)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.exit_order_id = "exit-poll-1"
        monitor._poll_exit_fill_price(pos)

        assert pos.exit_fill_price == _D("102.50")

    def test_retries_when_fill_price_is_initially_none(self):
        client = _make_alpaca_client()
        client.order_status.side_effect = [
            {"status": "open", "filled_avg_price": None},
            {"status": "filled", "filled_avg_price": 98.75},
        ]
        monitor = self._make_monitor(client)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.exit_order_id = "exit-poll-2"
        monitor._poll_exit_fill_price(pos, interval=0.0)

        assert pos.exit_fill_price == _D("98.75")
        assert client.order_status.call_count == 2

    def test_returns_immediately_on_invalid_fill_price_without_sleeping(self):
        client = _make_alpaca_client()
        client.order_status.return_value = {"status": "filled", "filled_avg_price": "not-a-number"}
        sleep_calls = []
        monitor = self._make_monitor(client)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor.time") as mock_time:
            pos = _make_stock_position(signal="BULLISH", shares=10)
            pos.exit_order_id = "exit-poll-3"
            monitor._poll_exit_fill_price(pos)

        mock_time.sleep.assert_not_called()
        assert pos.exit_fill_price is None

    def test_does_not_poll_when_no_exit_order_id(self):
        client = _make_alpaca_client()
        monitor = self._make_monitor(client)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.exit_order_id = None
        monitor._poll_exit_fill_price(pos)

        client.order_status.assert_not_called()
        assert pos.exit_fill_price is None

    def test_exit_fill_price_set_before_close_callback_fires(self):
        """close_callback receives pos with exit_fill_price already populated."""
        client = _make_alpaca_client()
        client.place_stock_order.return_value = {"order_id": "exit-cb-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 105.0}
        client.get_stock_quote.return_value = {
            "QuoteResponse": {"QuoteData": [{"All": {"bid": 104.0, "ask": 106.0, "bid_size": 1, "ask_size": 1, "last": None}}]}
        }

        fill_at_callback = []

        def on_close(pos):
            fill_at_callback.append(pos.exit_fill_price)

        df = _build_history_df([106.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, close_callback=on_close)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=87.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert len(fill_at_callback) == 1
        assert fill_at_callback[0] == _D("105.0")
