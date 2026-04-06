import pytest
from unittest.mock import patch

from alpha_tech_tracker.op_momentum_strategy.position_monitor import PositionMonitor

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
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

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
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00900000": _make_option_quote(bid=5.0, ask=5.5)
        }

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
    def test_bullish_call_profit_when_exit_above_entry(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BULLISH", entry_mid=13.86, exit_mid=14.21)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        assert "+$35.00" in captured

    def test_bullish_call_loss_when_exit_below_entry(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BULLISH", entry_mid=14.21, exit_mid=13.86)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        assert "-$35.00" in captured

    def test_bearish_put_profit_when_exit_above_entry(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BEARISH", entry_mid=13.72, exit_mid=21.35)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        assert "+$763.00" in captured

    def test_bearish_put_loss_when_exit_below_entry(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_position("BEARISH", entry_mid=21.35, exit_mid=13.72)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        assert "-$763.00" in captured


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


class TestStockPrintSummaryPnl:
    def test_stock_profit_uses_shares_not_contracts_multiplier(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_stock_position("BULLISH", entry_mid=100.0, exit_mid=102.0, shares=10)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        # P&L = (102 - 100) * 10 shares = +$20 (not * 100)
        assert "+$20.00" in captured

    def test_stock_loss_uses_shares_not_contracts_multiplier(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_stock_position("BULLISH", entry_mid=102.0, exit_mid=100.0, shares=10)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        assert "-$20.00" in captured

    def test_stock_summary_shows_shares_label_not_option_symbol(self, capsys):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor.add_position(
            _make_closed_stock_position("BULLISH", entry_mid=100.0, exit_mid=101.0, shares=5)
        )

        monitor.print_summary()

        captured = capsys.readouterr().out
        assert "[stock]" in captured
        assert "5sh" in captured


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

        client._option_data_client.get_option_latest_quote.assert_not_called()

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

    def test_minimal_time_decay_for_quick_exit_when_stock_flat(self):
        # stock flat → exit_iv=$10, tp=$2×0.9998=$1.9996 → quantizes to $2.00 → exit=$12.00
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        self._run_eod_close(pos, exit_stock_price=100.0)

        assert pos.simulated_exit_mid == _D("12.00")

    def test_minimal_time_decay_when_held_longer_than_one_hour(self):
        # bars_held=12; stock flat → same as quick exit: $2×0.9998 rounds to $2.00
        pos = self._make_option_pos("BULLISH", self._CALL_SYM, 100, "12.00")
        pos.bars_held = 12
        self._run_eod_close(pos, exit_stock_price=100.0)

        assert pos.simulated_exit_mid == _D("12.00")


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
            client._option_data_client.get_option_latest_quote.return_value = {
                "NVDA260328C00900000": _make_option_quote(bid=4.0, ask=5.0)
            }
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

    def test_reversal_suppresses_bearish_reentry_for_same_position(self):
        monitor, _, engine = self._make_monitor(
            enable_reversal=True, reversal_max_bars=3,
            enable_bearish_reentry=True, bearish_reentry_max_bars=3,
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        assert len(monitor._reentry_watchers) == 1
        assert monitor._reentry_watchers[0].reentry_type == "reversal"

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
        assert pos.exit_reason == "trailing_stop_ma20"
