import logging
import pytest
from unittest.mock import MagicMock, patch

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


class TestAddPosition:
    def test_options_position_logs_opt_and_contracts(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine)
        pos = _make_active_position(signal="BULLISH", contracts=3)

        with caplog.at_level(logging.INFO):
            monitor.add_position(pos)

        assert "opt=NVDA260328C00900000" in caplog.text
        assert "contracts=3" in caplog.text
        assert "[stock]" not in caplog.text

    def test_stock_position_logs_shares_not_opt(self, caplog):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine)
        pos = _make_stock_position(signal="BULLISH", shares=47)

        with caplog.at_level(logging.INFO):
            monitor.add_position(pos)

        assert "[stock]" in caplog.text
        assert "shares=47" in caplog.text
        assert "opt=" not in caplog.text
        assert "contracts=" not in caplog.text


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


class TestTrailingMaSwitchPeriod:
    """Live engine fast-MA trailing-stop upgrade.

    Setup: BULLISH primary, OR=[95,105], midpoint=100, or_range=10, hard_stop=103.5.
    after-arm threshold = or_range = 10, so close=110 latches use_ma_fast.
    Then close drops below the supplied fast MA → fast-MA trailing exit.
    MA20 is pinned below hard_stop (98) so MA20 trailing can never fire alone.
    """

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    @staticmethod
    def _setup(client, period=8, switch="after-arm", switch_factor=1.0):
        client.place_option_order.return_value = {"order_id": "close-fast"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.25}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)

        pos = _make_active_position(
            signal="BULLISH", or_high=_D("105"), or_low=_D("95"),
            hard_stop_price=_D("103.5"), fallback_price=_D("103.0"),
        )
        df = _build_history_df([100.0, 100.0], ma20=98.0, ma50=98.0, ma200=95.0)
        df[f"MA{period}"] = [99.0, 99.0]
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(
            client, engine,
            trailing_ma_switch=switch,
            trailing_ma_switch_factor=switch_factor,
            trailing_ma_switch_period=period,
        )
        monitor.add_position(pos)
        return pos, engine, monitor

    @staticmethod
    def _push_bar(engine, ticker, close, ma_fast, period):
        _set_latest_bar(engine, ticker, close=close, ma50=98.0, ma20=98.0)
        engine._history[ticker].iloc[-1, engine._history[ticker].columns.get_loc(f"MA{period}")] = ma_fast

    def test_use_ma_fast_latches_when_move_reaches_or_range(self):
        pos, engine, monitor = self._setup(_make_alpaca_client())
        # close=110 → move = 110 - midpoint(100) = 10 ≥ or_range=10 → latch
        self._push_bar(engine, "NVDA", close=110.0, ma_fast=109.0, period=8)
        monitor.on_bar("NVDA")
        assert pos.use_ma_fast is True
        assert pos.is_closed is False  # close > MA8, no exit yet

    def test_default_period_8_emits_trailing_stop_ma8_reason(self):
        pos, engine, monitor = self._setup(_make_alpaca_client(), period=8)
        self._push_bar(engine, "NVDA", close=110.0, ma_fast=109.0, period=8)  # latch
        monitor.on_bar("NVDA")
        self._push_bar(engine, "NVDA", close=108.5, ma_fast=109.0, period=8)  # close < MA8
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma8"

    def test_period_5_emits_trailing_stop_ma5_reason(self):
        pos, engine, monitor = self._setup(_make_alpaca_client(), period=5)
        self._push_bar(engine, "NVDA", close=110.0, ma_fast=109.0, period=5)
        monitor.on_bar("NVDA")
        self._push_bar(engine, "NVDA", close=108.5, ma_fast=109.0, period=5)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma5"

    def test_switch_none_does_not_latch_or_use_fast_ma(self):
        pos, engine, monitor = self._setup(_make_alpaca_client(), switch="none")
        self._push_bar(engine, "NVDA", close=110.0, ma_fast=109.0, period=8)
        monitor.on_bar("NVDA")
        assert pos.use_ma_fast is False
        # Even with close=108.5 < MA8=109, MA20=98 < hard_stop=103.5 → no MA20 trailing
        self._push_bar(engine, "NVDA", close=108.5, ma_fast=109.0, period=8)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False

    def test_use_ma_fast_remains_latched_after_pullback(self):
        # Move drops below threshold after latch — must NOT un-latch.
        pos, engine, monitor = self._setup(_make_alpaca_client())
        self._push_bar(engine, "NVDA", close=110.0, ma_fast=109.0, period=8)  # latch
        monitor.on_bar("NVDA")
        assert pos.use_ma_fast is True
        # close drops to 105 (move=5, well below threshold=10) but latch must hold
        self._push_bar(engine, "NVDA", close=105.0, ma_fast=109.0, period=8)
        monitor.on_bar("NVDA")
        assert pos.use_ma_fast is True
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma8"


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

    def test_live_summary_qty_uses_closed_contracts_when_contracts_zeroed(self, caplog):
        # BUG-1: after live close, pos.contracts becomes 0; summary must use closed_contracts
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.entry_fill_price = _D("10.00")
        pos.exit_fill_price = _D("12.00")
        pos.closed_contracts = 3
        pos.contracts = 0  # zeroed by _close_option_position
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "  3" in caplog.text

    def test_live_summary_pnl_uses_closed_contracts_for_dollar_amount(self, caplog):
        # BUG-1: P&L = (12 - 10) * 3 contracts * 100 = +$600, not $0
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.entry_fill_price = _D("10.00")
        pos.exit_fill_price = _D("12.00")
        pos.closed_contracts = 3
        pos.contracts = 0
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "+$600.00" in caplog.text

    def test_live_summary_pnl_loss_uses_closed_contracts(self, caplog):
        # BUG-1: P&L = (8 - 10) * 2 contracts * 100 = -$400, not $0
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.entry_fill_price = _D("10.00")
        pos.exit_fill_price = _D("8.00")
        pos.closed_contracts = 2
        pos.contracts = 0
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "-$400.00" in caplog.text

    def test_negative_zero_pnl_formats_as_positive_zero(self, caplog):
        # BUG-3: a near-zero loss rounds to -0.00 in Decimal; must display "+$0.00" not "+$-0.00"
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        pos = _make_closed_position("BULLISH", entry_mid=10.001, exit_mid=10.000)
        pos.contracts = 1
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "+$-" not in caplog.text


class TestStockBidAsk:
    """_stock_bid_ask() — G36: ask=0 stale quote must not halve the mid."""

    def _make_quote(self, bid, ask):
        return {"QuoteResponse": {"QuoteData": [{"All": {"bid": bid, "ask": ask}}]}}

    def test_normal_quote_returns_bid_and_ask(self):
        from alpha_tech_tracker.op_momentum_strategy.models import _stock_bid_ask
        bid, ask = _stock_bid_ask(self._make_quote(619.50, 620.10))
        assert bid == 619.50
        assert ask == 620.10

    def test_ask_zero_falls_back_to_bid(self):
        # G36: WebSocket delivers ask=0 snapshot; mid must use bid, not bid/2.
        from alpha_tech_tracker.op_momentum_strategy.models import _stock_bid_ask
        bid, ask = _stock_bid_ask(self._make_quote(620.0, 0.0))
        assert bid == 620.0
        assert ask == 620.0

    def test_ask_zero_mid_equals_bid_not_half(self):
        from alpha_tech_tracker.op_momentum_strategy.models import _stock_bid_ask
        from decimal import Decimal
        bid_f, ask_f = _stock_bid_ask(self._make_quote(620.0, 0.0))
        mid = (Decimal(str(bid_f)) + Decimal(str(ask_f))) / Decimal("2")
        assert mid == Decimal("620.0")


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

    def test_manual_close_detection_sets_exit_fill_price_from_broker(self):
        # G37: when PRE-CLOSE SYNC finds the position gone at broker,
        # _fetch_manual_close_fill_price must be called and its return value
        # stored on pos.exit_fill_price so print_summary() can show P&L.
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "buy", "filled_avg_price": 105.50,
             "filled_qty": 15.0, "filled_at": None},
        ]

        pos = _make_stock_position(signal="BEARISH", shares=15)
        pos.entry_order_id = None
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        monitor.add_position(pos)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode",
            return_value=False,
        ):
            monitor.close_all(reason="end_of_day")

        assert pos.exit_fill_price == _D("105.50")
        client.place_stock_order.assert_not_called()

    def test_manual_close_detection_leaves_exit_fill_price_none_when_fetch_fails(self):
        # G37: if _fetch_manual_close_fill_price returns None (no order found, no quote),
        # exit_fill_price must remain None — not silently set to 0 or mid.
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.get_open_positions.return_value = {}
        client.get_filled_orders.side_effect = RuntimeError("API down")

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.entry_order_id = None
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        monitor.add_position(pos)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode",
            return_value=False,
        ):
            monitor.close_all(reason="hard_stop")

        assert pos.exit_fill_price is None
        client.place_stock_order.assert_not_called()


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
        # Step-1 failure is now caught inside the escalation function and the next
        # attempt proceeds immediately — "placement failed" is logged there.
        assert any("placement failed" in r.message for r in caplog.records)

    def test_on_bar_retries_failed_option_close_within_same_bar(self, caplog):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)
        client.place_option_order.side_effect = [Exception("timeout"), {"order_id": "retry-opt-1"}]
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.25}

        pos = _make_active_position(signal="BULLISH", contracts=1)
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
        # Step-1 failure is now caught inside the escalation function and step-2
        # proceeds immediately — "placement failed" is logged there.
        assert any("placement failed" in r.message for r in caplog.records)

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
        assert "5.00sh" in caplog.text


class TestPrintStatusQtySyncCloses:
    def _make_monitor(self):
        client = _make_alpaca_client()
        engine = _make_signal_engine_with_history("NVDA", pd.DataFrame())
        return PositionMonitor(client, engine, mock_trade_execution=False)

    def _make_qty_sync_close(self, ticker="CRWV", entry_fill=10.27, exit_fill=9.15, contracts=2):
        pos = _make_active_position(signal="BEARISH", contracts=contracts)
        pos.ticker = ticker
        pos.is_closed = True
        pos.exit_reason = "manual_close"
        pos.entry_fill_price = _D(str(entry_fill))
        pos.exit_fill_price = _D(str(exit_fill))
        pos.entry_time = None
        pos.exit_time = None
        return pos

    def test_print_status_includes_qty_sync_close_in_closed_positions(self, caplog):
        monitor = self._make_monitor()
        engine_close = _make_active_position(signal="BEARISH", contracts=1)
        engine_close.ticker = "CRWV"
        engine_close.is_closed = True
        engine_close.exit_reason = "hard_stop"
        engine_close.entry_fill_price = _D("10.27")
        engine_close.exit_fill_price = _D("8.60")
        monitor.add_position(engine_close)
        monitor._qty_sync_closes.append(self._make_qty_sync_close())

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert caplog.text.count("CRWV") >= 2

    def test_print_status_running_pnl_includes_qty_sync_close_pnl(self, caplog):
        monitor = self._make_monitor()
        engine_close = _make_active_position(signal="BEARISH", contracts=1)
        engine_close.ticker = "CRWV"
        engine_close.is_closed = True
        engine_close.exit_reason = "hard_stop"
        engine_close.entry_fill_price = _D("10.27")
        engine_close.exit_fill_price = _D("8.60")
        monitor.add_position(engine_close)
        monitor._qty_sync_closes.append(self._make_qty_sync_close())

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        # engine close: (10.27 - 8.60) * 1 * 100 = +167
        # qty sync close: (10.27 - 9.15) * 2 * 100 = +224
        # combined running P&L = +$391 (both are BEARISH profit)
        assert "391" in caplog.text

    def test_print_status_without_qty_sync_closes_shows_only_engine_pnl(self, caplog):
        monitor = self._make_monitor()
        engine_close = _make_active_position(signal="BEARISH", contracts=1)
        engine_close.ticker = "CRWV"
        engine_close.is_closed = True
        engine_close.exit_reason = "hard_stop"
        engine_close.entry_fill_price = _D("10.27")
        engine_close.exit_fill_price = _D("8.60")
        monitor.add_position(engine_close)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "167" in caplog.text
        assert "391" not in caplog.text


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
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode",
            lambda: True,
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

    def test_zero_volume_bar_does_not_increment_bars_held_by_default(self):
        monitor, client, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, volume=100)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, volume=0)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, volume=0)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=106.5, ma50=97.0, volume=200)
        monitor.on_bar("NVDA")

        assert pos.bars_held == 2

    def test_zero_volume_bar_increments_bars_held_when_count_flat_bars_enabled(self):
        monitor, client, engine = self._make_monitor(count_flat_bars_in_held=True)
        pos = self._make_bullish_pos()
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, volume=100)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, volume=0)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=106.5, ma50=97.0, volume=200)
        monitor.on_bar("NVDA")

        assert pos.bars_held == 3

    def test_bre_watcher_created_after_hard_stop_when_flat_bars_skipped(self):
        monitor, _, engine = self._make_monitor(
            enable_bearish_reentry=True, bearish_reentry_max_bars=3
        )
        # BEARISH position: hard_stop at 96.5, armed already; stop triggers when close > 96.5
        pos = self._make_bearish_pos(bars_held=0)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        # 1 real bar, 2 flat bars — bars_held stays at 1 (flat bars skipped)
        _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0, volume=80)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0, volume=0)
        monitor.on_bar("NVDA")
        _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0, volume=0)
        monitor.on_bar("NVDA")
        # hard stop triggers on this bar (close 96.5 == hard_stop_price boundary; use 97.0 > 96.5)
        # bars_held is 1 at stop time (flat bars not counted) ≤ max_bars=3 → watcher created
        _set_latest_bar(engine, "NVDA", close=97.0, ma50=110.0, volume=250)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert len(monitor._reentry_watchers) == 1

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

        # Price crosses below OR low (95) and below MA20 (default 98.0) → BRE fires.
        _set_latest_bar(engine, "NVDA", close=94.5, ma50=110.0)
        monitor.on_bar("NVDA")

        assert len(monitor._reentry_watchers) == 0
        assert len(fired) == 1
        w, trigger = fired[0]
        assert w.reentry_type == "bearish_reentry"
        assert trigger == _D("94.5")

    def test_bearish_reentry_blocked_when_close_above_ma20(self):
        # close < or_low=95 but close > MA20 — price dipped below OR but is still above MA20,
        # meaning the downtrend is not confirmed. BRE must not fire (CVNA Apr-30 style false re-entry).
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

        # close=94.0 < or_low=95 but MA20=93.0 → close > MA20 → BRE blocked.
        _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0, ma20=93.0)
        monitor.on_bar("NVDA")

        assert len(fired) == 0
        assert len(monitor._reentry_watchers) == 1

    def test_bearish_reentry_fires_only_when_close_below_both_or_low_and_ma20(self):
        # Verifies the MA20 guard lifts once price falls below MA20 as well.
        fired = []
        monitor, _, engine = self._make_monitor(
            enable_bearish_reentry=True, bearish_reentry_max_bars=5,
            re_entry_callback=lambda w, price: fired.append((w, price)),
        )
        pos = self._make_bearish_pos(bars_held=2)
        pos.hard_stop_armed = True
        monitor.add_position(pos)

        _set_latest_bar(engine, "NVDA", close=96.5, ma50=110.0)
        monitor.on_bar("NVDA")

        # close=94.0 < or_low=95 but MA20=93.0 → close > MA20 → still blocked.
        _set_latest_bar(engine, "NVDA", close=94.0, ma50=110.0, ma20=93.0)
        monitor.on_bar("NVDA")
        assert len(fired) == 0

        # close=92.0 < or_low=95 AND close < MA20=93.5 → BRE fires.
        _set_latest_bar(engine, "NVDA", close=92.0, ma50=110.0, ma20=93.5)
        monitor.on_bar("NVDA")
        assert len(fired) == 1
        assert fired[0][0].reentry_type == "bearish_reentry"

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

    def test_reversal_trailing_does_not_fire_before_arm_price_reached(self):
        """
        Reversal positions gate the MA trailing stop on trailing_arm_price (entry + or_range),
        matching the backtest's rev_trailing_armed gate. The trailing stop must not fire until
        price reaches the arm threshold, even though hard_stop_armed=True from bar 1.
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        pos.hard_stop_price = _D("98")
        pos.fallback_price = _D("98")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("115")
        pos.reentry_type = "reversal"
        monitor.add_position(pos)

        # close=106 < MA20=108 but arm threshold (115) not yet reached → no exit
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, ma20=108.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is False

    def test_reversal_trailing_fires_after_arm_price_reached(self):
        """Once price reaches trailing_arm_price, subsequent MA cross triggers the stop."""
        monitor, _, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        pos.hard_stop_price = _D("98")
        pos.fallback_price = _D("98")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("115")
        pos.reentry_type = "reversal"
        monitor.add_position(pos)

        # Bar 1: price reaches arm threshold (116 >= 115) and is above MA20 → arm latches
        _set_latest_bar(engine, "NVDA", close=116.0, ma50=97.0, ma20=112.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False
        assert pos.trailing_arm_reached is True

        # Bar 2: price drops below MA20 → trailing_stop_ma20 fires
        _set_latest_bar(engine, "NVDA", close=110.0, ma50=97.0, ma20=112.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_reversal_hard_stop_fires_before_arm_price_reached(self):
        """
        While the trailing MA stop is inactive (arm price not yet reached), the hard stop
        is the only protection. It must still fire if price drops below hard_stop_price.
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        pos.hard_stop_price = _D("98")
        pos.fallback_price = _D("98")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("115")
        pos.reentry_type = "reversal"
        monitor.add_position(pos)

        # close=97 <= hard_stop=98; arm threshold (115) not reached → hard_stop fires
        _set_latest_bar(engine, "NVDA", close=97.0, ma50=90.0, ma20=93.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"

    def test_bru_trailing_does_not_fire_before_0_1x_arm_price_reached(self):
        """
        bullish_reentry positions gate the MA trailing stop on trailing_arm_price
        (entry + 0.1 × or_range) even when hard_stop_armed=True.
        The trailing stop must not fire until the price arm is reached.
        """
        monitor, _, engine = self._make_monitor()
        pos = _make_active_position(
            signal="BULLISH",
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=_D("100"),
            fallback_price=_D("100"),
        )
        pos.entry_stock_price = _D("106")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("107")  # entry(106) + or_range(10) * 0.1
        pos.reentry_type = "bullish_reentry"
        monitor.add_position(pos)

        # close=106.5 < arm(107) and close=106.5 < MA20=108 → no exit (arm not reached)
        _set_latest_bar(engine, "NVDA", close=106.5, ma50=97.0, ma20=108.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is False

    def test_bru_trailing_fires_after_0_1x_arm_price_reached(self):
        """
        After close reaches trailing_arm_price (entry + 0.1 × or_range), the arm
        latches and the MA trailing stop becomes active for bullish_reentry positions.
        """
        monitor, _, engine = self._make_monitor()
        pos = _make_active_position(
            signal="BULLISH",
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=_D("100"),
            fallback_price=_D("100"),
        )
        pos.entry_stock_price = _D("106")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("107")  # entry(106) + or_range(10) * 0.1
        pos.reentry_type = "bullish_reentry"
        monitor.add_position(pos)

        # close=107.5 >= arm(107) → arm latches; MA20=105 < close=107.5 → no trailing yet
        _set_latest_bar(engine, "NVDA", close=107.5, ma50=97.0, ma20=105.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False
        assert pos.trailing_arm_reached is True

        # close=104 < MA20=105, MA20=105 > hard_stop(100) → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=104.0, ma50=97.0, ma20=105.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_bru_trailing_arm_not_latched_when_close_at_threshold_but_below_ma20(self):
        """
        bullish_reentry arm requires BOTH close >= arm_price AND close > MA20.
        When close reaches the price threshold but is still below MA20, the arm
        must not latch — the trailing stop should remain inactive.
        """
        monitor, _, engine = self._make_monitor()
        pos = _make_active_position(
            signal="BULLISH",
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=_D("100"),
            fallback_price=_D("100"),
        )
        pos.entry_stock_price = _D("106")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("107")  # entry(106) + or_range(10) * 0.1
        pos.reentry_type = "bullish_reentry"
        monitor.add_position(pos)

        # close=107.5 >= arm(107) but close=107.5 < MA20=110 → arm must NOT latch yet
        _set_latest_bar(engine, "NVDA", close=107.5, ma50=97.0, ma20=110.0)
        monitor.on_bar("NVDA")
        assert pos.trailing_arm_reached is False
        assert pos.is_closed is False

        # close=111 >= arm(107) AND close=111 > MA20=110 → arm now latches
        _set_latest_bar(engine, "NVDA", close=111.0, ma50=97.0, ma20=110.0)
        monitor.on_bar("NVDA")
        assert pos.trailing_arm_reached is True
        assert pos.is_closed is False

        # close=109 < MA20=110, MA20=110 > hard_stop(100) → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=109.0, ma50=97.0, ma20=110.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_pre_armed_bre_bearish_exits_via_ma20_without_reaching_trailing_arm_price(self):
        """
        BRE (bearish re-entry) position starts with hard_stop_armed=True, so the
        MA trailing stop is immediately active without requiring close to fall all
        the way to trailing_arm_price (entry - or_range).

        Mirrors the CVNA 4/30 BRE failure: entered short at 95, trailing_arm=85
        (never reached), stock rallied above MA20 while MA20 < midpoint → exit.
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("100")   # midpoint as hard stop
        pos.fallback_price = _D("100")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("85")   # entry(95) - range(10), never reached
        pos.reentry_type = "bearish_reentry"
        monitor.add_position(pos)

        # close=97 > MA20=92; MA20=92 < midpoint(100); arm threshold(85) not reached
        # hard_stop_armed=True → trailing immediately active → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=97.0, ma50=110.0, ma20=92.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_trailing_arm_price_still_gates_ma_trailing_stop_when_hard_stop_not_armed(self):
        """
        When hard_stop_armed=False, trailing_arm_price still gates the MA trailing
        stop — the fallback arm logic remains active for positions not pre-armed.
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bullish_pos()
        pos.hard_stop_price = _D("98")
        pos.fallback_price = _D("98")
        pos.hard_stop_armed = False
        pos.trailing_arm_price = _D("115")
        monitor.add_position(pos)

        # close=106 < MA20=108; arm threshold(115) not reached, hard_stop not armed → no exit
        _set_latest_bar(engine, "NVDA", close=106.0, ma50=97.0, ma20=108.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is False

    def test_bearish_ma20_trailing_stop_uses_or_midpoint_threshold(self):
        """
        BRE (trailing_arm_price set): bearish MA20 trailing stop gate uses OR midpoint,
        matching the backtest's br_eff_trail < midpoint condition.

        With or_high=105, or_low=95, midpoint=100:
        - MA20=101 (above midpoint) → gate fails → no exit
        - MA20=97 (between or_low and midpoint) → gate passes → trailing_stop_ma20
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("100")
        pos.fallback_price = _D("100")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("85")
        pos.reentry_type = "bearish_reentry"
        monitor.add_position(pos)

        # MA20=101 >= midpoint(100) → gate fails → no exit
        # close=98 is below hard_stop(100) so hard_stop does not fire either
        _set_latest_bar(engine, "NVDA", close=98.0, ma50=110.0, ma20=101.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False

        # MA20=97 < midpoint(100) and close=99 > MA20=97 → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=99.0, ma50=110.0, ma20=97.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_primary_bearish_ma20_trailing_stop_uses_or_low_threshold(self):
        """
        Primary BEARISH positions (trailing_arm_price=None) use or_low as the MA20
        gate — matching the backtest's _eff_trail < or_low condition (line 510).

        With or_high=105, or_low=95, midpoint=100:
        - MA20=97 (between or_low and midpoint) → gate fails for primary → no exit
          (would pass midpoint gate — this test catches the regression)
        - MA20=94 (below or_low) → gate passes → trailing_stop_ma20
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("102")   # above midpoint; won't fire at close=98
        pos.fallback_price = _D("97")
        pos.hard_stop_armed = True
        # trailing_arm_price=None → primary position
        monitor.add_position(pos)

        # MA20=97 is between or_low(95) and midpoint(100): primary gate (or_low) fails → no exit
        _set_latest_bar(engine, "NVDA", close=98.0, ma50=110.0, ma20=97.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False

        # MA20=94 < or_low(95) → gate passes; close=96 > MA20=94 → trailing_stop_ma20
        _set_latest_bar(engine, "NVDA", close=96.0, ma50=110.0, ma20=94.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma20"

    def test_bre_bearish_ma50_trailing_stop_uses_or_midpoint_threshold(self):
        """
        BRE positions use midpoint as the MA50 gate (same logic as MA20 for BRE).
        MA50 between or_low and midpoint triggers an exit for BRE but not for primary.

        With or_high=105, or_low=95, midpoint=100:
        - BRE (trailing_arm_price set): MA50=97 < midpoint → gate passes → exit
        """
        monitor, _, engine = self._make_monitor(trailing_ma="ma50")
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("100")
        pos.fallback_price = _D("100")
        pos.hard_stop_armed = True
        pos.trailing_arm_price = _D("85")   # BRE position
        pos.reentry_type = "bearish_reentry"
        monitor.add_position(pos)

        # MA50=97 < midpoint(100); close=98 > MA50=97 → trailing_stop_ma50
        _set_latest_bar(engine, "NVDA", close=98.0, ma50=97.0, ma20=97.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma50"

    def test_primary_bearish_ma50_trailing_stop_uses_or_low_threshold(self):
        """
        Primary BEARISH positions use or_low as the MA50 gate, matching the backtest
        condition bar_ma50 < or_low (line 525).

        MA50 between or_low and midpoint must NOT trigger an exit for primary positions.
        """
        monitor, _, engine = self._make_monitor(trailing_ma="ma50")
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("102")
        pos.fallback_price = _D("97")
        pos.hard_stop_armed = True
        # trailing_arm_price=None → primary position
        monitor.add_position(pos)

        # MA50=97 between or_low(95) and midpoint(100) → primary gate (or_low) fails → no exit
        _set_latest_bar(engine, "NVDA", close=98.0, ma50=97.0, ma20=97.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False

        # MA50=94 < or_low(95) → gate passes; close=96 > MA50=94 → trailing_stop_ma50
        _set_latest_bar(engine, "NVDA", close=96.0, ma50=94.0, ma20=97.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is True
        assert pos.exit_reason == "trailing_stop_ma50"

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
        pos.hard_stop_armed = False
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
          Bar 1: close=84 <= arm_threshold=85 → latch fires; close=84 < MA20=96
                 so trailing exit does not fire (bearish exits when close > MA20)
          Bar 2: close=88 > arm_threshold=85 (would disarm before latch fix)
                 but latch holds → MA20=86 < midpoint(100), close=88 > MA20=86 → exit
        """
        monitor, _, engine = self._make_monitor()
        pos = self._make_bearish_pos()
        pos.hard_stop_price = _D("102")
        pos.fallback_price = _D("102")
        pos.hard_stop_armed = False
        # Bearish arm: price must fall to entry - or_range = 95 - 10 = 85
        pos.trailing_arm_price = _D("85")
        monitor.add_position(pos)

        # Bar 1: arm threshold reached; close=84 < MA20=96 → no exit yet
        _set_latest_bar(engine, "NVDA", close=84.0, ma50=110.0, ma20=96.0)
        monitor.on_bar("NVDA")
        assert pos.is_closed is False
        assert pos.trailing_arm_reached is True

        # Bar 2: price bounces above arm threshold — latch must hold
        # MA20=86 < midpoint(100) → gate passes; close=88 > MA20=86 → trailing_stop_ma20
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
        client.order_status.return_value = {"status": "filled"}

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
    """EOD option close uses fill escalation (limit first, market fallback); stock EOD is still market."""

    def test_eod_option_close_uses_fill_escalation(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-1"}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)
        client.order_status.return_value = {"status": "filled"}

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"), \
             patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            monitor.close_all(reason="end_of_day")

        first_call = client.place_option_order.call_args_list[0]
        assert first_call.kwargs["price_type"] == "LIMIT"
        assert first_call.kwargs["_option_symbol_override"] == "NVDA260328C00900000"

    def test_eod_option_close_no_quick_exit_protection(self):
        # EOD close must not use entry_fill_price (step-0 quick-exit protection)
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-1"}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)
        client.order_status.return_value = {"status": "filled"}

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        pos.option_fill_price = 4.80  # entry fill price — must NOT be tried at EOD
        monitor.add_position(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"), \
             patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            monitor.close_all(reason="end_of_day")

        # First limit order should be at mid (5.25), not at entry fill price (4.80)
        first_price = client.place_option_order.call_args_list[0].kwargs["price"]
        assert first_price != 4.80

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
        """Non-EOD exits must still go through place_option_order_in_tranches."""
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
            "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_option_order_in_tranches",
            return_value=({"order_id": "esc-1"}, 3),
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
        client.order_status.return_value = {"status": "filled"}

        closes = [100.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos1 = _make_active_position(signal="BULLISH")
        pos2 = _make_active_position(signal="BEARISH")
        monitor.add_position(pos1)
        monitor.add_position(pos2)

        lock_held_during_api_call = []

        def spy_get_quote(*args, **kwargs):
            lock_held_during_api_call.append(monitor._lock.locked())
            return _make_option_quote(bid=5.0, ask=5.5)

        client.get_option_quote_by_occ.side_effect = spy_get_quote

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"), \
             patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
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
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=_QUICK_EXIT_MAX_SECONDS - 1))
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

    def test_returns_entry_fill_price_when_stock_within_tolerance(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=60))
        pos.entry_stock_price = _D("300.00")
        # 0.1% move — within 0.3% tolerance
        current_stock_price = _D("299.70")
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos, current_stock_price=current_stock_price)
        assert result == 5.0

    def test_returns_none_when_stock_moved_beyond_tolerance(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=60))
        pos.entry_stock_price = _D("300.00")
        # 0.5% move — exceeds 0.3% tolerance
        current_stock_price = _D("298.50")
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos, current_stock_price=current_stock_price)
        assert result is None

    def test_returns_fill_price_exactly_at_tolerance_boundary(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=60))
        pos.entry_stock_price = _D("300.00")
        # exactly 0.3% move — at boundary (diff_pct == tolerance), still qualifies
        current_stock_price = _D("299.10")
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos, current_stock_price=current_stock_price)
        assert result == 5.0

    def test_skips_stock_check_when_current_stock_price_not_provided(self):
        from datetime import timedelta
        now = self._now()
        pos = self._make_pos(entry_fill_price=5.0, entry_time=now - timedelta(seconds=60))
        with patch(f"{self._MODULE}._now_et", return_value=now):
            result = _quick_exit_entry_price(pos, current_stock_price=None)
        assert result == 5.0


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

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"), \
             patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            _set_latest_bar(engine, "NVDA", close=87.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert len(fill_at_callback) == 1
        assert fill_at_callback[0] == _D("105.0")

    def test_does_not_set_exit_fill_price_when_order_is_cancelled(self):
        """FILL_ESC MISS: cancelled order returns filled_avg_price=0 — must not record as fill."""
        client = _make_alpaca_client()
        client.order_status.return_value = {"status": "canceled", "filled_avg_price": 0.0}
        monitor = self._make_monitor(client)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.exit_order_id = "exit-cancelled-1"
        monitor._poll_exit_fill_price(pos)

        assert pos.exit_fill_price is None
        assert client.order_status.call_count == 1

    def test_does_not_set_exit_fill_price_when_order_is_rejected(self):
        client = _make_alpaca_client()
        client.order_status.return_value = {"status": "rejected", "filled_avg_price": 0.0}
        monitor = self._make_monitor(client)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.exit_order_id = "exit-rejected-1"
        monitor._poll_exit_fill_price(pos)

        assert pos.exit_fill_price is None

    def test_retries_when_fill_price_is_zero_but_order_not_cancelled(self):
        """fill_price=0 on open order should retry, not record as fill."""
        client = _make_alpaca_client()
        client.order_status.side_effect = [
            {"status": "open", "filled_avg_price": 0.0},
            {"status": "filled", "filled_avg_price": 99.50},
        ]
        monitor = self._make_monitor(client)

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.exit_order_id = "exit-zero-retry"
        monitor._poll_exit_fill_price(pos, interval=0.0)

        assert pos.exit_fill_price == _D("99.50")
        assert client.order_status.call_count == 2


class TestCloseRetryLimit:
    """
    Fix 3: close_order_failed retries must be capped at _MAX_CLOSE_RETRIES (3).
    After the limit is reached, subsequent on_bar() calls must not attempt
    another close so the broker API is not spammed.
    """

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def _make_monitor_and_stuck_position(self):
        client = _make_alpaca_client()
        # Both quote and order placement must fail so close_order_failed stays True
        # across retries (if place_option_order succeeded the flag would clear).
        client.get_option_quote_by_occ.side_effect = RuntimeError("quote always fails")
        client.place_option_order.side_effect = RuntimeError("order always fails")

        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)

        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        monitor._positions.append(pos)

        return monitor, client, engine, pos

    def test_retries_exactly_max_times(self):
        monitor, client, engine, pos = self._make_monitor_and_stuck_position()

        for i in range(5):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert pos.close_retry_count == 3

    def test_no_close_attempt_after_limit_reached(self):
        monitor, client, engine, pos = self._make_monitor_and_stuck_position()

        for i in range(5):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        # Each retry reaches the market-order fallback exactly once (step3 limit fails,
        # then place_option_order raises too). 3 retries → call_count == 3; bars 4-5 add 0.
        assert client.place_option_order.call_count == 3

    def test_manual_intervention_alert_sent_only_once(self):
        monitor, client, engine, pos = self._make_monitor_and_stuck_position()

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
        ) as mock_notify:
            for i in range(6):
                _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
                monitor.on_bar("NVDA")

        retry_limit_alerts = [
            c for c in mock_notify.call_args_list
            if "retries exhausted" in str(c)
        ]
        assert len(retry_limit_alerts) == 1


class TestFetchManualCloseFillPrice:
    """
    _fetch_manual_close_fill_price() returns the actual fill price of a manual close
    from broker order history. Returns None when no matching filled order is found —
    no mid fallback, so capital is not prematurely returned to the window budget.
    """

    def _make_monitor_and_pos(self, entry_time=None):
        client = _make_alpaca_client()
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        pos = _make_active_position(signal="BEARISH", contracts=6)
        if entry_time is not None:
            pos.entry_time = entry_time
        return monitor, client, pos

    def test_returns_filled_order_price_when_sell_order_found(self):
        monitor, client, pos = self._make_monitor_and_pos()
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 9.80,
             "filled_qty": 6.0, "filled_at": None},
        ]

        price = monitor._fetch_manual_close_fill_price(pos)

        assert price == _D("9.80")

    def test_skips_buy_orders_for_bearish_option(self):
        monitor, client, pos = self._make_monitor_and_pos()
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "buy", "filled_avg_price": 9.80,
             "filled_qty": 6.0, "filled_at": None},
        ]

        price = monitor._fetch_manual_close_fill_price(pos)

        assert price is None

    def test_skips_orders_filled_before_entry_time(self):
        import pytz
        from datetime import datetime
        ET = pytz.timezone("America/New_York")
        entry = ET.localize(datetime(2026, 4, 24, 9, 47))
        before_entry = ET.localize(datetime(2026, 4, 24, 9, 30))
        monitor, client, pos = self._make_monitor_and_pos(entry_time=entry)
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 7.00,
             "filled_qty": 6.0, "filled_at": before_entry},
        ]

        price = monitor._fetch_manual_close_fill_price(pos)

        assert price is None

    def test_returns_none_when_no_matching_order(self):
        monitor, client, pos = self._make_monitor_and_pos()
        client.get_filled_orders.return_value = []

        price = monitor._fetch_manual_close_fill_price(pos)

        assert price is None

    def test_returns_none_when_order_history_fetch_fails(self):
        monitor, client, pos = self._make_monitor_and_pos()
        client.get_filled_orders.side_effect = RuntimeError("API error")

        price = monitor._fetch_manual_close_fill_price(pos)

        assert price is None

    def test_stock_bearish_close_looks_for_buy_side_order(self):
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "buy", "filled_avg_price": 109.50,
             "filled_qty": 104.0, "filled_at": None},
        ]

        price = monitor._fetch_manual_close_fill_price(pos)

        assert price == _D("109.50")


class TestReconcileStuckPositions:
    """
    _reconcile_stuck_positions() checks the broker for open positions and resolves
    stuck (close_order_failed) positions that the user has manually closed.

    Two paths when broker confirms position is closed:
    - Fill confirmed in order history → RECONCILED: clears close_order_failed, fires callback.
    - Fill not yet in order history (API lag) → RECONCILE PENDING: sets close_order_reconciled
      to stop FILL_ESC retries but keeps close_order_failed=True so the next 5-min cycle retries.
    """

    def _make_monitor_with_stuck_option(self):
        client = _make_alpaca_client()
        client.get_filled_orders.return_value = []

        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        pos.close_alert_sent = True
        pos.entry_fill_price = _D("3.50")
        pos.slot_capital = _D("5000")
        monitor._positions.append(pos)
        return monitor, client, pos

    def _sell_order(self, price=5.00, qty=2.0):
        return {"order_id": "o99", "side": "sell", "filled_avg_price": price,
                "filled_qty": qty, "filled_at": None}

    def test_no_action_when_no_stuck_positions(self):
        client = _make_alpaca_client()
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        monitor._reconcile_stuck_positions()

        client.get_open_positions.assert_not_called()

    def test_no_action_when_position_still_open_at_broker(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 2.0}}

        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is True
        assert pos.exit_fill_price is None

    def test_clears_close_order_failed_when_fill_confirmed(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [self._sell_order(5.10)]

        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is False

    def test_keeps_close_order_failed_when_fill_pending(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is True

    def test_sets_exit_fill_price_from_broker_order_history(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [self._sell_order(5.10)]

        monitor._reconcile_stuck_positions()

        assert pos.exit_fill_price == _D("5.10")

    def test_does_not_set_exit_fill_price_when_fill_pending(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        monitor._reconcile_stuck_positions()

        assert pos.exit_fill_price is None

    def test_fires_exit_retry_callback_when_fill_confirmed(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [self._sell_order(5.10)]

        callback_positions = []
        monitor._exit_retry_callback = callback_positions.append

        monitor._reconcile_stuck_positions()

        assert len(callback_positions) == 1
        assert callback_positions[0] is pos

    def test_no_callback_when_fill_pending(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        callback_called = []
        monitor._exit_retry_callback = lambda p: callback_called.append(p)

        monitor._reconcile_stuck_positions()

        assert pos.exit_fill_price is None
        assert callback_called == []

    def test_sends_reconciled_notify_when_fill_confirmed(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [self._sell_order(5.10)]

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
        ) as mock_notify:
            monitor._reconcile_stuck_positions()

        assert mock_notify.call_count == 1
        assert "RECONCILED" in mock_notify.call_args[0][0]

    def test_sends_pending_notify_when_fill_not_yet_in_order_history(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
        ) as mock_notify:
            monitor._reconcile_stuck_positions()

        assert mock_notify.call_count == 1
        assert "RECONCILE PENDING" in mock_notify.call_args[0][0]

    def test_graceful_when_broker_fetch_fails(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.side_effect = RuntimeError("network error")

        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is True

    def test_sets_close_order_reconciled_when_fill_confirmed(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [self._sell_order(5.10)]

        monitor._reconcile_stuck_positions()

        assert pos.close_order_reconciled is True

    def test_sets_close_order_reconciled_when_fill_pending(self):
        monitor, client, pos = self._make_monitor_with_stuck_option()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        monitor._reconcile_stuck_positions()

        assert pos.close_order_reconciled is True

    def test_reconciled_position_skipped_by_retry_loop(self):
        """Retry loop in on_bar must not re-open close_order_failed after reconciliation."""
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.side_effect = RuntimeError("quote unavailable")
        client.place_option_order.side_effect = RuntimeError("order unavailable")
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        pos.close_order_reconciled = True
        monitor._positions.append(pos)

        _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
        monitor.on_bar("NVDA")

        assert pos.close_retry_count == 0
        client.place_option_order.assert_not_called()


class TestCloseAllEodStuckPositionSweep:
    """
    Fix 2: close_all() must force-close any position that previously failed
    to close (is_closed=True, close_order_failed=True) via a market order.
    Without this fix, those positions are skipped (they are already marked
    closed) and left open at the broker overnight.
    """

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def _make_monitor(self, client):
        closes = [104.0]
        df = _build_history_df(closes, ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        return PositionMonitor(client, engine)

    def test_stuck_position_receives_eod_market_order(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-mkt-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}

        monitor = self._make_monitor(client)

        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        monitor._positions.append(pos)

        monitor.close_all()

        market_calls = [
            c for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "MARKET"
        ]
        assert len(market_calls) == 2  # 3 contracts / tranche_size=2 → 2 tranches

    def test_normal_open_position_and_stuck_position_both_closed(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}

        monitor = self._make_monitor(client)

        open_pos = _make_active_position(signal="BEARISH")
        monitor._positions.append(open_pos)

        stuck_pos = _make_active_position(signal="BULLISH")
        stuck_pos.is_closed = True
        stuck_pos.exit_reason = "hard_stop"
        stuck_pos.close_order_failed = True
        monitor._positions.append(stuck_pos)

        monitor.close_all()

        # 2 positions × 2 tranches each (3 contracts / tranche_size=2)
        assert client.place_option_order.call_count == 4
        market_calls = [
            c for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "MARKET"
        ]
        assert len(market_calls) == 4

    def test_no_extra_close_when_no_stuck_positions(self):
        client = _make_alpaca_client()
        client.place_option_order.return_value = {"order_id": "eod-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.0}

        monitor = self._make_monitor(client)

        pos = _make_active_position(signal="BULLISH")
        monitor._positions.append(pos)

        monitor.close_all()

        assert client.place_option_order.call_count == 2  # 3 contracts / tranche_size=2 → 2 tranches


class TestGapThroughExitOverride:
    """
    Verify that exit price overrides respect bar High/Low for gap-through scenarios.

    When the exit bar gaps through the stop or fallback level — meaning the bar's
    entire range was already past the trigger — the realistic fill is the bar Open,
    not the theoretical stop level.
    """

    def _make_monitor(self, pos):
        closes = [float(pos.entry_stock_price)]
        df = _build_history_df(closes, ma20=80.0, ma50=80.0, ma200=75.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(_make_alpaca_client(), engine, mock_trade_execution=True)
        monitor.add_position(pos)
        return monitor, engine

    def test_bull_hard_stop_normal_uses_stop_price(self):
        # Bar High >= hard_stop_price: stock traded at the stop level → fill at stop
        pos = _make_stock_position(signal="BULLISH", hard_stop_price=_D("103.5"))
        pos.hard_stop_armed = True
        monitor, engine = self._make_monitor(pos)

        # close=103.0 triggers hard_stop; high=104.0 >= 103.5 → stop fill
        _set_latest_bar(engine, "NVDA", close=103.0, ma50=80.0, high=104.0, low=102.5, open_=103.8)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert pos.simulated_exit_mid == _D("103.50")

    def test_bull_hard_stop_gap_down_uses_bar_open(self):
        # Bar High < hard_stop_price: stock gapped down through stop → fill at open
        pos = _make_stock_position(signal="BULLISH", hard_stop_price=_D("103.5"))
        pos.hard_stop_armed = True
        monitor, engine = self._make_monitor(pos)

        # close=101.0 triggers hard_stop; high=103.0 < 103.5 → gap-down → open fill
        _set_latest_bar(engine, "NVDA", close=101.0, ma50=80.0, high=103.0, low=100.5, open_=103.1)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert pos.simulated_exit_mid == _D("103.10")

    def test_bear_hard_stop_normal_uses_stop_price(self):
        # Bar Low <= hard_stop_price: stock traded at the stop level → fill at stop
        pos = _make_stock_position(
            signal="BEARISH",
            or_high=_D("100"), or_low=_D("90"),
            hard_stop_price=_D("91.5"), fallback_price=_D("93"),
        )
        pos.hard_stop_armed = True
        monitor, engine = self._make_monitor(pos)

        # close=92.5 triggers hard_stop; low=91.0 <= 91.5 → stop fill
        _set_latest_bar(engine, "NVDA", close=92.5, ma50=80.0, high=93.0, low=91.0, open_=91.2)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert pos.simulated_exit_mid == _D("91.50")

    def test_bear_hard_stop_gap_up_uses_bar_open(self):
        # Bar Low > hard_stop_price: stock gapped up through stop → fill at open
        pos = _make_stock_position(
            signal="BEARISH",
            or_high=_D("100"), or_low=_D("90"),
            hard_stop_price=_D("91.5"), fallback_price=_D("93"),
        )
        pos.hard_stop_armed = True
        monitor, engine = self._make_monitor(pos)

        # close=93.0 triggers hard_stop; low=92.0 > 91.5 → gap-up → open fill
        _set_latest_bar(engine, "NVDA", close=93.0, ma50=80.0, high=93.5, low=92.0, open_=92.0)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "hard_stop"
        assert pos.simulated_exit_mid == _D("92.00")

    def test_bear_fallback_normal_uses_fallback_price(self):
        # Bar Low <= fallback_price: stock traded at the fallback level → fill at fallback
        pos = _make_stock_position(
            signal="BEARISH",
            or_high=_D("100"), or_low=_D("90"),
            hard_stop_price=_D("91.5"), fallback_price=_D("93"),
        )
        monitor, engine = self._make_monitor(pos)

        # close=93.5 >= fallback 93 triggers fallback; low=92.5 <= 93 → fallback fill
        _set_latest_bar(engine, "NVDA", close=93.5, ma50=80.0, high=94.0, low=92.5, open_=92.8)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "fallback_20pct"
        assert pos.simulated_exit_mid == _D("93.00")

    def test_bear_fallback_gap_up_uses_bar_open(self):
        # Bar Low > fallback_price: stock gapped up through fallback → fill at open
        pos = _make_stock_position(
            signal="BEARISH",
            or_high=_D("100"), or_low=_D("90"),
            hard_stop_price=_D("91.5"), fallback_price=_D("93"),
        )
        monitor, engine = self._make_monitor(pos)

        # close=95.0 >= fallback 93 triggers fallback; low=93.5 > 93 → gap-up → open fill
        _set_latest_bar(engine, "NVDA", close=95.0, ma50=80.0, high=95.5, low=93.5, open_=93.6)
        monitor.on_bar("NVDA")

        assert pos.is_closed is True
        assert pos.exit_reason == "fallback_20pct"
        assert pos.simulated_exit_mid == _D("93.60")


# ---------------------------------------------------------------------------
# exit_retry_callback — fires after FILL_ESC MISS retry confirms fill
# ---------------------------------------------------------------------------

class TestExitRetryCallback:
    """exit_retry_callback is called once when a retry close order succeeds and
    exit_fill_price is confirmed. It must NOT fire when close_callback first fires
    (exit_fill_price=None at that point) and must NOT fire if the retry still fails."""

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def _make_monitor_with_failed_stock_position(self, exit_retry_callback=None):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }
        client.place_stock_order.return_value = {"order_id": "retry-stk-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 100.0}

        df = _build_history_df([100.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(
            client, engine, exit_retry_callback=exit_retry_callback
        )

        pos = _make_stock_position(signal="BULLISH", shares=10)
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        monitor._positions.append(pos)

        return monitor, engine, pos

    def _make_monitor_with_failed_option_position(self, exit_retry_callback=None):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=5.5)
        client.place_option_order.return_value = {"order_id": "retry-opt-1"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 5.25}

        df = _build_history_df([100.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(
            client, engine, exit_retry_callback=exit_retry_callback
        )

        pos = _make_active_position(signal="BULLISH", contracts=2)
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        monitor._positions.append(pos)

        return monitor, engine, pos

    def test_callback_called_after_successful_stock_retry(self):
        callback_calls = []
        monitor, engine, pos = self._make_monitor_with_failed_stock_position(
            exit_retry_callback=callback_calls.append
        )

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert len(callback_calls) == 1
        assert callback_calls[0] is pos

    def test_callback_called_after_successful_option_retry(self):
        callback_calls = []
        monitor, engine, pos = self._make_monitor_with_failed_option_position(
            exit_retry_callback=callback_calls.append
        )

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert len(callback_calls) == 1
        assert callback_calls[0] is pos

    def test_callback_receives_position_with_exit_fill_price_set(self):
        captured = []
        monitor, engine, pos = self._make_monitor_with_failed_stock_position(
            exit_retry_callback=lambda p: captured.append(p.exit_fill_price)
        )

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert captured[0] == _D("100.0")

    def test_callback_not_called_when_retry_still_fails(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.side_effect = RuntimeError("quote unavailable")
        client.place_option_order.side_effect = RuntimeError("order rejected")

        df = _build_history_df([100.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)

        callback_calls = []
        monitor = PositionMonitor(
            client, engine, exit_retry_callback=callback_calls.append
        )

        pos = _make_active_position(signal="BULLISH", contracts=2)
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        monitor._positions.append(pos)

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert callback_calls == []

    def test_no_callback_registered_does_not_raise(self):
        monitor, engine, pos = self._make_monitor_with_failed_stock_position(
            exit_retry_callback=None
        )

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            _set_latest_bar(engine, "NVDA", close=103.0, ma50=90.0)
            monitor.on_bar("NVDA")

        assert pos.close_order_failed is False


class TestPreCloseBrokerQtySync:
    """
    _close_option_position() and _close_stock_position() query get_open_positions()
    before placing a close order in live mode. If the user manually closed some or all
    contracts/shares, the engine adjusts qty so the order matches the remaining position.
    """

    _REPLAY_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode"
    _PLACE_OPTION_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_option_order_in_tranches"
    _PLACE_STOCK_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_stock_order"
    _NOTIFY_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"

    def _make_live_monitor(self, contracts=6):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = {"bid": 8.50, "ask": 9.50, "mid": 9.00}
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BEARISH", contracts=contracts)
        pos.entry_fill_price = _D("8.00")
        return monitor, client, engine, pos

    def test_option_full_manual_close_skips_order(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 8.0}
        client.get_filled_orders.return_value = [
            {"order_id": "sell1", "side": "sell", "filled_avg_price": 9.00, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        place_order.assert_not_called()
        assert pos.close_order_failed is False

    def test_option_full_manual_close_sets_fill_price_from_order_history(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 8.0}
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 9.75,
             "filled_qty": 6.0, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.exit_fill_price == _D("9.75")

    def test_option_marks_pending_when_order_status_unknown_and_no_sell_history(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.side_effect = RuntimeError("API unavailable")
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.exit_fill_price is None
        assert pos.close_order_failed is True
        assert pos.close_order_reconciled is True

    def test_option_partial_manual_close_adjusts_contracts_before_order(self):
        monitor, client, engine, pos = self._make_live_monitor(contracts=6)
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 4.0}}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 4)) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "trailing_stop_ma20")

        _, kwargs = place_order.call_args
        assert kwargs["contracts"] == 4

    def test_option_partial_close_fires_close_callback_with_manually_closed_qty(self):
        close_cb = MagicMock()
        monitor, client, engine, pos = self._make_live_monitor(contracts=6)
        monitor._close_callback = close_cb
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 4.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "manual1", "side": "sell", "filled_avg_price": 12.50,
             "filled_qty": 2.0, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 4)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "trailing_stop_ma20")

        close_cb.assert_called_once()
        partial = close_cb.call_args[0][0]
        assert partial.contracts == 2
        assert partial.exit_fill_price == _D("12.50")
        assert partial.exit_reason == "manual_close"
        assert partial.is_closed is True

    def test_option_partial_close_stored_in_qty_sync_closes(self):
        monitor, client, engine, pos = self._make_live_monitor(contracts=6)
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 4.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "manual1", "side": "sell", "filled_avg_price": 12.50,
             "filled_qty": 2.0, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 4)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "trailing_stop_ma20")

        assert len(monitor._qty_sync_closes) == 1
        assert monitor._qty_sync_closes[0].contracts == 2

    def test_option_partial_close_no_fill_price_does_not_fire_close_callback(self):
        close_cb = MagicMock()
        monitor, client, engine, pos = self._make_live_monitor(contracts=6)
        monitor._close_callback = close_cb
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 4.0}}
        client.get_filled_orders.return_value = []
        client.order_status.return_value = {"status": "filled", "filled_avg_price": "9.00"}
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 4)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "trailing_stop_ma20")

        close_cb.assert_not_called()

    def test_option_no_adjustment_when_broker_qty_matches_engine(self):
        monitor, client, engine, pos = self._make_live_monitor(contracts=6)
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 6.0}}
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 6)) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        _, kwargs = place_order.call_args
        assert kwargs["contracts"] == 6

    def test_option_broker_fetch_failure_proceeds_with_engine_qty(self):
        monitor, client, engine, pos = self._make_live_monitor(contracts=6)
        client.get_open_positions.side_effect = RuntimeError("network error")
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 6)) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        _, kwargs = place_order.call_args
        assert kwargs["contracts"] == 6

    def test_option_sync_skipped_in_mock_mode(self):
        client = _make_alpaca_client()
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        pos = _make_active_position(signal="BEARISH", contracts=6)
        pos.simulated_entry_mid = _D("8.00")
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        client.get_open_positions.assert_not_called()

    def test_stock_full_manual_close_skips_order_fill_confirmed(self):
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "buy", "filled_avg_price": 109.50,
             "filled_qty": 104.0, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._NOTIFY_PATH):
            monitor._close_stock_position(pos, "trailing_stop_ma20")

        client.place_stock_order.assert_not_called()
        assert pos.close_order_failed is False
        assert pos.exit_fill_price == _D("109.50")

    def test_stock_full_manual_close_skips_order_fill_pending(self):
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._NOTIFY_PATH):
            monitor._close_stock_position(pos, "trailing_stop_ma20")

        client.place_stock_order.assert_not_called()
        assert pos.close_order_failed is True
        assert pos.close_order_reconciled is True
        assert pos.exit_fill_price is None

    def test_stock_partial_manual_close_adjusts_shares_before_order(self):
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        # Broker shows 50 shares remain (short position, negative qty)
        client.get_open_positions.return_value = {"NVDA": {"qty": -50.0}}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_STOCK_PATH, return_value={"order_id": "stk-order"}) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_stock_position(pos, "trailing_stop_ma20")

        assert pos.shares == 50
        _, kwargs = place_order.call_args
        assert kwargs["shares"] == 50

    def test_stock_partial_close_fires_close_callback_with_manually_closed_shares(self):
        close_cb = MagicMock()
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False, close_callback=close_cb)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        pos.entry_fill_price = _D("120.00")
        client.get_open_positions.return_value = {"NVDA": {"qty": -50.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "manual1", "side": "buy", "filled_avg_price": 115.00,
             "filled_qty": 54.0, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_STOCK_PATH, return_value={"order_id": "stk"}), \
                patch(self._NOTIFY_PATH):
            monitor._close_stock_position(pos, "hard_stop")

        close_cb.assert_called_once()
        partial = close_cb.call_args[0][0]
        assert partial.shares == 54
        assert partial.exit_fill_price == _D("115.00")
        assert partial.exit_reason == "manual_close"
        assert partial.is_closed is True

    def test_stock_partial_close_no_fill_price_does_not_fire_close_callback(self):
        close_cb = MagicMock()
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False, close_callback=close_cb)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        client.get_open_positions.return_value = {"NVDA": {"qty": -50.0}}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_STOCK_PATH, return_value={"order_id": "stk"}), \
                patch(self._NOTIFY_PATH):
            monitor._close_stock_position(pos, "hard_stop")

        close_cb.assert_not_called()
        assert pos.shares == 50

    def test_option_position_found_at_broker_proceeds_normally(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 6.0}}
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 6)) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert client.get_open_positions.call_count == 1
        _, kwargs = place_order.call_args
        assert kwargs["contracts"] == 6

    def test_option_broker_api_lag_proceeds_with_close_when_entry_confirmed(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 8.0}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 6)) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        _, kwargs = place_order.call_args
        assert kwargs["contracts"] == 6

    def test_option_broker_api_lag_uses_engine_contract_count(self):
        monitor, client, engine, pos = self._make_live_monitor(contracts=4)
        client.get_open_positions.return_value = {}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 8.0}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 4)) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "trailing_stop_ma20")

        _, kwargs = place_order.call_args
        assert kwargs["contracts"] == 4

    def test_option_not_found_manual_sell_found_after_entry_skips_close(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 8.0}
        client.get_filled_orders.return_value = [
            {"order_id": "sell1", "side": "sell", "filled_avg_price": 9.50, "filled_at": None},
        ]
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        place_order.assert_not_called()
        assert pos.close_order_failed is False

    def test_option_not_found_entry_canceled_skips_close(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.return_value = {"status": "canceled"}
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        place_order.assert_not_called()

    def test_option_not_found_order_status_failure_skips_close(self):
        monitor, client, engine, pos = self._make_live_monitor()
        client.get_open_positions.return_value = {}
        client.order_status.side_effect = RuntimeError("API unavailable")
        client.get_filled_orders.return_value = []
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH) as place_order, \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        place_order.assert_not_called()


class TestSyncOpenPositionQtys:
    """
    _sync_open_position_qtys() polls the broker every 5 min and corrects pos.contracts /
    pos.shares when the user manually partially closed a position outside the engine.
    """

    def _make_monitor_with_open_option(self, contracts=6):
        client = _make_alpaca_client()
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        pos = _make_active_position(signal="BEARISH", contracts=contracts)
        monitor._positions.append(pos)
        return monitor, client, pos

    def test_no_broker_call_when_no_open_positions(self):
        client = _make_alpaca_client()
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        pos = _make_active_position(signal="BEARISH")
        pos.is_closed = True
        monitor._positions.append(pos)

        monitor._sync_open_position_qtys()

        client.get_open_positions.assert_not_called()

    def test_partial_manual_close_updates_contracts(self):
        monitor, client, pos = self._make_monitor_with_open_option(contracts=6)
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 4.0}}
        client.get_filled_orders.return_value = []

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        assert pos.contracts == 4

    def test_sends_notify_on_partial_close(self):
        monitor, client, pos = self._make_monitor_with_open_option(contracts=6)
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 4.0}}
        client.get_filled_orders.return_value = []

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
        ) as mock_notify:
            monitor._sync_open_position_qtys()

        assert mock_notify.call_count == 1
        assert "QTY SYNC" in mock_notify.call_args[0][0]

    def test_no_change_when_broker_qty_matches_engine(self):
        monitor, client, pos = self._make_monitor_with_open_option(contracts=6)
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 6.0}}

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify") as mock_notify:
            monitor._sync_open_position_qtys()

        assert pos.contracts == 6
        mock_notify.assert_not_called()

    def test_position_absent_from_broker_leaves_contracts_unchanged(self):
        monitor, client, pos = self._make_monitor_with_open_option(contracts=6)
        client.get_open_positions.return_value = {}

        monitor._sync_open_position_qtys()

        assert pos.contracts == 6

    def test_already_closed_positions_are_skipped(self):
        monitor, client, pos = self._make_monitor_with_open_option(contracts=6)
        pos.is_closed = True
        client.get_open_positions.return_value = {pos.option_symbol: {"qty": 2.0}}

        monitor._sync_open_position_qtys()

        assert pos.contracts == 6

    def test_stock_partial_close_updates_shares(self):
        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)
        pos = _make_stock_position(signal="BEARISH", shares=104)
        monitor._positions.append(pos)
        client.get_open_positions.return_value = {"NVDA": {"qty": -50.0}}
        client.get_filled_orders.return_value = []

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        assert pos.shares == 50

    def test_broker_fetch_failure_leaves_positions_unchanged(self):
        monitor, client, pos = self._make_monitor_with_open_option(contracts=6)
        client.get_open_positions.side_effect = RuntimeError("network error")

        monitor._sync_open_position_qtys()

        assert pos.contracts == 6


# ---------------------------------------------------------------------------
# TestClosedContractsRetentionOnRetry — G31
# ---------------------------------------------------------------------------


class TestClosedContractsRetentionOnRetry:
    """
    G31: _close_option_position previously set pos.closed_contracts = pos.contracts
    on every call. After a partial tranche fill (contracts decremented), a retry call
    reset closed_contracts to the *remaining* count, discarding the tranche-1 fill count.

    Fix: closed_contracts is now accumulated additively (+= filled) so each tranche's
    fill is retained across retry calls.
    """

    _PLACE_OPTION_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_option_order_in_tranches"
    _NOTIFY_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
    _REPLAY_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode"

    def _make_monitor_with_pos(self, contracts=3):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = {"bid": 8.50, "ask": 9.50, "mid": 9.00}
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BEARISH", contracts=contracts)
        pos.entry_fill_price = _D("8.00")
        return monitor, client, pos

    def test_first_partial_close_accumulates_filled_count(self):
        # First call fills 2 of 3 → closed_contracts accumulates to 2.
        monitor, _, pos = self._make_monitor_with_pos(contracts=3)
        with \
                patch(self._REPLAY_PATH, return_value=True), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "o1"}, 2)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.closed_contracts == 2
        assert pos.contracts == 1
        assert pos.close_order_failed is True

    def test_retry_fill_adds_to_previously_accumulated_closed_contracts(self):
        # First call fills 2; retry fills remaining 1 → closed_contracts totals 3.
        # G31 bug: retry called pos.closed_contracts = pos.contracts = 1, overwriting
        # the tranche-1 fill, so effective_contracts was 1 instead of 3 and P&L was
        # understated (observed EXPE 2026-04-28: +$210 instead of +$630).
        monitor, _, pos = self._make_monitor_with_pos(contracts=3)
        with \
                patch(self._REPLAY_PATH, return_value=True), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "o1"}, 2)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.closed_contracts == 2
        assert pos.contracts == 1

        with \
                patch(self._REPLAY_PATH, return_value=True), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "o2"}, 1)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.closed_contracts == 3
        assert pos.contracts == 0
        assert pos.close_order_failed is False

    def test_miss_on_retry_does_not_reduce_previously_filled_count(self):
        # First call fills 2; retry MISSes (fills 0) → closed_contracts stays at 2.
        monitor, _, pos = self._make_monitor_with_pos(contracts=3)
        with \
                patch(self._REPLAY_PATH, return_value=True), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "o1"}, 2)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.closed_contracts == 2

        with \
                patch(self._REPLAY_PATH, return_value=True), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "o2"}, 0)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.closed_contracts == 2
        assert pos.contracts == 1



# ---------------------------------------------------------------------------
# TestPrintStatusClosedQty — G34
# ---------------------------------------------------------------------------


class TestPrintStatusClosedQty:
    """
    G34: print_status() closed-position block used p.contracts for qty and P&L multiplier.
    After a live close p.contracts reaches 0, so every closed position showed x0 and
    +$0.00. Fix: use _effective_contracts() (returns closed_contracts when > 0).
    """

    def _make_monitor(self):
        client = _make_alpaca_client()
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        return PositionMonitor(client, engine)

    def test_closed_position_qty_shows_closed_contracts_not_zero(self, caplog):
        monitor = self._make_monitor()
        pos = _make_active_position(signal="BEARISH", contracts=3)
        pos.is_closed = True
        pos.exit_reason = "trailing_stop_ma20"
        pos.contracts = 0
        pos.closed_contracts = 3
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "x3" in caplog.text

    def test_closed_position_qty_falls_back_to_contracts_when_closed_contracts_zero(self, caplog):
        # closed_contracts stays 0 when the close hasn't filled yet (mid-retry).
        # In that case _effective_contracts falls back to p.contracts.
        monitor = self._make_monitor()
        pos = _make_active_position(signal="BULLISH", contracts=2)
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.contracts = 2
        pos.closed_contracts = 0
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "x2" in caplog.text

    def test_closed_position_pnl_uses_closed_contracts(self, caplog):
        # P&L = (10 - 8) * 3 * 100 = +$600.
        monitor = self._make_monitor()
        pos = _make_active_position(signal="BULLISH", contracts=3)
        pos.is_closed = True
        pos.exit_reason = "trailing_stop_ma20"
        pos.entry_fill_price = _D("8.00")
        pos.exit_fill_price = _D("10.00")
        pos.contracts = 0
        pos.closed_contracts = 3
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "+$600.00" in caplog.text

    def test_closed_bearish_option_pnl_profit_when_exit_above_entry(self, caplog):
        # BEARISH put: bought at 8, sold at 10 → profit = (10 - 8) * 2 * 100 = +$400.
        monitor = self._make_monitor()
        pos = _make_active_position(signal="BEARISH", contracts=2)
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.entry_fill_price = _D("8.00")
        pos.exit_fill_price = _D("10.00")
        pos.contracts = 0
        pos.closed_contracts = 2
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "+$400.00" in caplog.text

    def test_closed_position_pnl_blank_when_exit_fill_price_missing(self, caplog):
        # exit_fill_price=None means fill not yet confirmed; P&L column must be blank,
        # not $0.00, so the operator knows the figure is pending.
        monitor = self._make_monitor()
        pos = _make_active_position(signal="BULLISH", contracts=2)
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.entry_fill_price = _D("9.00")
        pos.exit_fill_price = None
        pos.contracts = 0
        pos.closed_contracts = 2
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "$0.00" not in caplog.text

    def test_closed_stock_position_qty_uses_shares(self, caplog):
        # Stock positions use p.shares (unchanged by the fix); verify no regression.
        monitor = self._make_monitor()
        pos = _make_stock_position(signal="BULLISH", shares=15)
        pos.is_closed = True
        pos.exit_reason = "end_of_day"
        monitor.add_position(pos)

        with caplog.at_level(logging.INFO):
            monitor.print_status()

        assert "x15.00sh" in caplog.text


class TestReconcileTwoCycleRetry:
    """
    When the broker confirms a position is closed but the fill is not yet in order
    history (RECONCILE PENDING), the reconciliation thread must retry on the next
    5-min cycle and fire the callback only once — when the real fill is confirmed.
    """

    def _make_monitor_with_stuck_pos(self):
        client = _make_alpaca_client()
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine)

        pos = _make_active_position(signal="BULLISH")
        pos.is_closed = True
        pos.exit_reason = "hard_stop"
        pos.close_order_failed = True
        pos.entry_fill_price = _D("3.50")
        pos.slot_capital = _D("5000")
        monitor._positions.append(pos)
        return monitor, client, pos

    def test_callback_not_fired_on_pending_cycle(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()
        callback_called = []
        monitor._exit_retry_callback = callback_called.append

        monitor._reconcile_stuck_positions()

        assert callback_called == []

    def test_callback_fired_once_on_confirmed_cycle(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()
        callback_called = []
        monitor._exit_retry_callback = callback_called.append

        monitor._reconcile_stuck_positions()
        assert callback_called == []

        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 5.20, "filled_at": None},
        ]
        monitor._reconcile_stuck_positions()

        assert len(callback_called) == 1
        assert pos.exit_fill_price == _D("5.20")

    def test_fill_price_set_only_on_confirmed_cycle(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()

        monitor._reconcile_stuck_positions()
        assert pos.exit_fill_price is None

        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 5.20, "filled_at": None},
        ]
        monitor._reconcile_stuck_positions()

        assert pos.exit_fill_price == _D("5.20")

    def test_close_order_failed_cleared_on_confirmed_cycle(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()

        monitor._reconcile_stuck_positions()
        assert pos.close_order_failed is True

        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 5.20, "filled_at": None},
        ]
        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is False

    def test_pending_position_picked_up_again_by_stuck_filter(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()

        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is True
        assert pos.close_order_reconciled is True
        assert client.get_open_positions.call_count == 1

        monitor._reconcile_stuck_positions()

        assert client.get_open_positions.call_count == 2

    def test_pending_notify_includes_attempt_counter(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
        ) as mock_notify:
            monitor._reconcile_stuck_positions()

        msg = mock_notify.call_args[0][0]
        assert "RECONCILE PENDING" in msg
        assert "1/" in msg

    def test_reconcile_pending_count_increments_each_cycle(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()

        for _ in range(3):
            monitor._reconcile_stuck_positions()

        assert pos.reconcile_pending_count == 3

    def test_abandoned_after_max_attempts(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()
        max_attempts = PositionMonitor._MAX_RECONCILE_ATTEMPTS

        for _ in range(max_attempts):
            monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is False

    def test_abandoned_sends_abandoned_notify(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()
        max_attempts = PositionMonitor._MAX_RECONCILE_ATTEMPTS

        notifications = []
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify",
            side_effect=notifications.append,
        ):
            for _ in range(max_attempts):
                monitor._reconcile_stuck_positions()

        last_msg = notifications[-1]
        assert "RECONCILE ABANDONED" in last_msg

    def test_no_further_reconcile_cycles_after_abandoned(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()
        max_attempts = PositionMonitor._MAX_RECONCILE_ATTEMPTS

        for _ in range(max_attempts):
            monitor._reconcile_stuck_positions()

        call_count_at_abandon = client.get_open_positions.call_count
        monitor._reconcile_stuck_positions()

        assert client.get_open_positions.call_count == call_count_at_abandon

    def test_fill_confirmed_before_max_still_resolves(self):
        monitor, client, pos = self._make_monitor_with_stuck_pos()

        monitor._reconcile_stuck_positions()
        assert pos.close_order_failed is True

        client.get_filled_orders.return_value = [
            {"order_id": "o1", "side": "sell", "filled_avg_price": 5.20, "filled_at": None},
        ]
        monitor._reconcile_stuck_positions()

        assert pos.close_order_failed is False
        assert pos.exit_fill_price == _D("5.20")


class TestFillEscMissGuard:
    """
    When a FILL_ESC attempt times out and fires a MISS after the reconciliation thread
    has already confirmed the position closed at broker (close_order_reconciled=True),
    the MISS must NOT re-set close_order_failed=True.

    Without the guard, a concurrent in-flight FILL_ESC restores close_order_failed=True,
    triggering a redundant second reconciliation cycle with a stale mid-price estimate.
    """

    _REPLAY_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.is_replay_mode"
    _PLACE_OPTION_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor.place_option_order_in_tranches"
    _NOTIFY_PATH = "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"

    def _make_live_monitor(self):
        client = _make_alpaca_client()
        client.get_open_positions.return_value = {
            "NVDA260328C00900000": {"qty": 6.0}
        }
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BEARISH", contracts=6)
        pos.entry_fill_price = _D("8.00")
        pos.close_order_failed = False
        pos.close_order_reconciled = True
        return monitor, client, pos

    def test_miss_does_not_set_close_order_failed_when_already_reconciled(self):
        monitor, client, pos = self._make_live_monitor()
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 0)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.close_order_failed is False

    def test_miss_still_sets_close_order_failed_when_not_yet_reconciled(self):
        client = _make_alpaca_client()
        client.get_open_positions.return_value = {
            "NVDA260328C00900000": {"qty": 6.0}
        }
        df = _build_history_df([116.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=False)
        pos = _make_active_position(signal="BEARISH", contracts=6)
        pos.entry_fill_price = _D("8.00")
        pos.close_order_failed = False
        pos.close_order_reconciled = False
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 0)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        assert pos.close_order_failed is True

    def test_reconciled_position_not_picked_up_again_by_reconciliation_after_miss(self):
        monitor, client, pos = self._make_live_monitor()
        with \
                patch(self._REPLAY_PATH, return_value=False), \
                patch(self._PLACE_OPTION_PATH, return_value=({"order_id": "x"}, 0)), \
                patch(self._NOTIFY_PATH):
            monitor._close_option_position(pos, "hard_stop")

        pos.is_closed = True
        client.get_open_positions.return_value = {}
        client.get_filled_orders.return_value = []

        callback_called = []
        monitor._exit_retry_callback = callback_called.append
        monitor._reconcile_stuck_positions()

        assert callback_called == []


class TestDoubleDownCoClose:
    """DD add-on must be co-closed whenever the primary exits, for any exit reason."""

    @pytest.fixture(autouse=True)
    def patch_sleep(self, monkeypatch):
        monkeypatch.setattr(
            "alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep",
            lambda _: None,
        )

    def _make_primary(self, signal="BULLISH", hard_stop=_D("98.0"), window="M1"):
        pos = _make_stock_position(
            signal=signal,
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=hard_stop,
            fallback_price=_D("94.0"),
            shares=100,
        )
        pos.ticker = "TSLA"
        pos.window_label = window
        pos.hard_stop_armed = True
        pos.is_doubledown_addon = False
        return pos

    def _make_dd(self, signal="BULLISH", hard_stop=_D("98.0"), window="M1"):
        pos = _make_stock_position(
            signal=signal,
            or_high=_D("105"),
            or_low=_D("95"),
            hard_stop_price=hard_stop,
            fallback_price=_D("94.0"),
            shares=150,
        )
        pos.ticker = "TSLA"
        pos.window_label = window
        pos.hard_stop_armed = True
        pos.is_doubledown_addon = True
        return pos

    def _make_monitor(self, *positions):
        client = _make_alpaca_client()
        client.place_stock_order.return_value = {"order_id": "close-dd"}
        client.order_status.return_value = {"status": "filled", "filled_avg_price": 97.0}
        df = _build_history_df([100.0], ma20=98.0, ma50=98.0, ma200=95.0)
        engine = _make_signal_engine_with_history("TSLA", df)
        monitor = PositionMonitor(client, engine, mock_trade_execution=True)
        monitor._positions = list(positions)
        return monitor

    def test_dd_co_closes_when_primary_exits_via_hard_stop(self):
        primary = self._make_primary(hard_stop=_D("98.0"))
        dd = self._make_dd(hard_stop=_D("98.0"))
        monitor = self._make_monitor(primary, dd)

        _set_latest_bar(monitor._signal_engine, "TSLA", close=97.5, ma50=99.0)
        monitor.on_bar("TSLA")

        assert primary.is_closed is True
        assert primary.exit_reason == "hard_stop"
        assert dd.is_closed is True
        assert dd.exit_reason == "hard_stop"

    def test_dd_co_closes_when_primary_exits_via_trailing_stop(self):
        primary = self._make_primary(hard_stop=_D("90.0"))
        dd = self._make_dd(hard_stop=_D("90.0"))
        monitor = self._make_monitor(primary, dd)

        # MA20=103 > close=101 → trailing stop fires on primary; DD must follow
        _set_latest_bar(monitor._signal_engine, "TSLA", close=101.0, ma50=99.0, ma20=103.0)
        monitor.on_bar("TSLA")

        assert primary.is_closed is True
        assert primary.exit_reason == "trailing_stop_ma20"
        assert dd.is_closed is True
        assert dd.exit_reason == "trailing_stop_ma20"

    def test_dd_co_closes_when_primary_exits_via_fallback(self):
        primary = self._make_primary(hard_stop=_D("98.0"))
        primary.hard_stop_armed = False
        dd = self._make_dd(hard_stop=_D("98.0"))
        dd.hard_stop_armed = False
        monitor = self._make_monitor(primary, dd)

        # close=93.5 < fallback=94.0, hard stop never armed → fallback_20pct
        _set_latest_bar(monitor._signal_engine, "TSLA", close=93.5, ma50=99.0)
        monitor.on_bar("TSLA")

        assert primary.is_closed is True
        assert primary.exit_reason == "fallback_20pct"
        assert dd.is_closed is True
        assert dd.exit_reason == "fallback_20pct"

    def test_dd_co_closes_even_when_primary_has_trailing_arm_set(self):
        # Primary is a BRE (reentry_type set) with trailing_arm not yet reached; the
        # hard stop fires first. DD must co-close regardless.
        primary = self._make_primary(hard_stop=_D("102.0"))
        primary.trailing_arm_price = _D("106.0")
        primary.reentry_type = "bearish_reentry"
        dd = self._make_dd(hard_stop=_D("102.0"))
        monitor = self._make_monitor(primary, dd)

        # close=101 <= hard_stop=102 → primary hard_stop fires → DD co-closes
        _set_latest_bar(monitor._signal_engine, "TSLA", close=101.0, ma50=99.0, ma20=103.0)
        monitor.on_bar("TSLA")

        assert primary.is_closed is True
        assert dd.is_closed is True
        assert dd.exit_reason == primary.exit_reason

    def test_co_close_does_not_self_trigger_when_only_dd_is_open(self):
        dd = self._make_dd(hard_stop=_D("98.0"))
        monitor = self._make_monitor(dd)

        _set_latest_bar(monitor._signal_engine, "TSLA", close=97.5, ma50=99.0)
        monitor.on_bar("TSLA")

        closed = [p for p in monitor._positions if p.is_closed]
        assert len(closed) == 1

    def test_co_close_scoped_to_matching_window_not_other_window(self):
        primary_m1 = self._make_primary(hard_stop=_D("98.0"), window="M1")
        dd_m1 = self._make_dd(hard_stop=_D("98.0"), window="M1")
        # Give the A1 DD a stop well below the bar close so it doesn't fire on its own;
        # only the M1 primary's exit should trigger co-close, scoped to M1.
        dd_a1 = self._make_dd(hard_stop=_D("90.0"), window="A1")
        monitor = self._make_monitor(primary_m1, dd_m1, dd_a1)

        # ma20=96.0 < close=97.5 so trailing stop does not fire independently;
        # only the M1 primary's hard_stop (98.0 > close) drives the exit.
        _set_latest_bar(monitor._signal_engine, "TSLA", close=97.5, ma50=99.0, ma20=96.0)
        monitor.on_bar("TSLA")

        assert primary_m1.is_closed is True
        assert dd_m1.is_closed is True
        assert dd_a1.is_closed is False


class TestQtySyncPartialManualClose:
    """_sync_open_position_qtys: partial manual close detected via broker qty < engine qty."""

    def _make_monitor(self, pos, close_callback=None):
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history(pos.ticker, df)
        client = _make_alpaca_client()
        monitor = PositionMonitor(
            client,
            engine,
            mock_trade_execution=True,
            close_callback=close_callback,
        )
        monitor.add_position(pos)
        return monitor, client

    def _make_options_pos(self, contracts=2):
        pos = _make_active_position(contracts=contracts)
        pos.entry_fill_price = _D("22.95")
        pos.window_label = "M1"
        return pos

    def _make_stock_pos(self, shares=100):
        pos = _make_stock_position(shares=shares)
        pos.entry_fill_price = _D("200.00")
        pos.window_label = "M1"
        return pos

    def test_partial_options_close_fires_close_callback_with_manually_closed_qty(self):
        closed_positions = []
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos, close_callback=closed_positions.append)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 1},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "32.00",
                "order_id": "manual-sell-1",
                "filled_at": None,
            }
        ]

        monitor._sync_open_position_qtys()

        assert len(closed_positions) == 1
        closed = closed_positions[0]
        assert closed.contracts == 1
        assert closed.exit_fill_price == _D("32.00")
        assert closed.is_closed is True
        assert closed.exit_reason == "manual_close"

    def test_partial_options_close_reduces_remaining_contracts_on_original_pos(self):
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 1},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "32.00",
                "order_id": "manual-sell-1",
                "filled_at": None,
            }
        ]

        monitor._sync_open_position_qtys()

        assert pos.contracts == 1

    def test_partial_options_close_no_fill_price_still_reduces_contracts(self):
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 1},
        }
        client.get_filled_orders.return_value = []

        monitor._sync_open_position_qtys()

        assert pos.contracts == 1

    def test_partial_options_close_no_fill_price_does_not_fire_close_callback(self):
        closed_positions = []
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos, close_callback=closed_positions.append)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 1},
        }
        client.get_filled_orders.return_value = []

        monitor._sync_open_position_qtys()

        assert closed_positions == []

    def test_partial_options_close_no_fill_price_logs_warning(self, caplog):
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 1},
        }
        client.get_filled_orders.return_value = []

        with caplog.at_level(logging.WARNING):
            monitor._sync_open_position_qtys()

        assert "fill price unknown" in caplog.text.lower() or "fill price not found" in caplog.text.lower()

    def test_partial_options_close_closed_record_copies_entry_data(self):
        closed_positions = []
        pos = self._make_options_pos(contracts=2)
        pos.ticker = "COIN"
        pos.signal = "BULLISH"
        pos.option_symbol = "COIN260515C00180000"
        pos.entry_fill_price = _D("22.95")
        pos.window_label = "M1"
        monitor, client = self._make_monitor(pos, close_callback=closed_positions.append)

        client.get_open_positions.return_value = {
            "COIN260515C00180000": {"qty": 1},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "32.00",
                "order_id": "manual-sell-1",
                "filled_at": None,
            }
        ]

        monitor._sync_open_position_qtys()

        closed = closed_positions[0]
        assert closed.ticker == "COIN"
        assert closed.signal == "BULLISH"
        assert closed.option_symbol == "COIN260515C00180000"
        assert closed.entry_fill_price == _D("22.95")
        assert closed.window_label == "M1"

    def test_partial_stock_close_fires_close_callback_with_manually_closed_shares(self):
        closed_positions = []
        pos = self._make_stock_pos(shares=100)
        monitor, client = self._make_monitor(pos, close_callback=closed_positions.append)

        client.get_open_positions.return_value = {
            pos.ticker: {"qty": 60},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "210.50",
                "order_id": "manual-sell-stk-1",
                "filled_at": None,
            }
        ]

        monitor._sync_open_position_qtys()

        assert len(closed_positions) == 1
        closed = closed_positions[0]
        assert closed.shares == 40
        assert closed.exit_fill_price == _D("210.50")
        assert closed.is_closed is True
        assert closed.exit_reason == "manual_close"

    def test_partial_stock_close_reduces_remaining_shares_on_original_pos(self):
        pos = self._make_stock_pos(shares=100)
        monitor, client = self._make_monitor(pos)

        client.get_open_positions.return_value = {
            pos.ticker: {"qty": 60},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "210.50",
                "order_id": "manual-sell-stk-1",
                "filled_at": None,
            }
        ]

        monitor._sync_open_position_qtys()

        assert pos.shares == 60

    def test_no_callback_when_broker_qty_equals_engine_qty(self):
        closed_positions = []
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos, close_callback=closed_positions.append)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 2},
        }

        monitor._sync_open_position_qtys()

        assert closed_positions == []
        assert pos.contracts == 2

    def test_no_callback_when_symbol_absent_from_broker_open_positions(self):
        closed_positions = []
        pos = self._make_options_pos(contracts=2)
        monitor, client = self._make_monitor(pos, close_callback=closed_positions.append)

        client.get_open_positions.return_value = {}

        monitor._sync_open_position_qtys()

        assert closed_positions == []
        assert pos.contracts == 2

    def test_partial_close_stored_in_qty_sync_closes(self):
        pos = self._make_options_pos(contracts=4)
        monitor, client = self._make_monitor(pos)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 2},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "9.00",
                "order_id": "manual-sell-1",
                "filled_at": None,
            }
        ]

        monitor._sync_open_position_qtys()

        assert len(monitor._qty_sync_closes) == 1
        stored = monitor._qty_sync_closes[0]
        assert stored.contracts == 2
        assert stored.exit_fill_price == _D("9.00")
        assert stored.exit_reason == "manual_close"

    def test_partial_close_appears_in_print_summary_with_manual_close_label(self, caplog):
        pos = self._make_options_pos(contracts=4)
        monitor, client = self._make_monitor(pos)

        client.get_open_positions.return_value = {
            pos.option_symbol: {"qty": 2},
        }
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "9.00",
                "order_id": "manual-sell-1",
                "filled_at": None,
            }
        ]
        monitor._sync_open_position_qtys()

        pos.is_closed = True
        pos.exit_fill_price = _D("8.35")
        pos.exit_reason = "fallback_20pct"

        with caplog.at_level(logging.INFO):
            monitor.print_summary()

        assert "[Manual Close]" in caplog.text
        assert "manual_close" in caplog.text


class TestManualCloseOrderIdExclusion:
    """_fetch_manual_close_fill_price and _entry_confirmed_filled_no_manual_close
    must skip filled sell orders whose order_id matches pos.exit_order_id so that
    the engine's own close orders are never misidentified as manual closes.
    """

    def _make_monitor(self, pos):
        df = _build_history_df([104.0], ma20=90.0, ma50=90.0, ma200=85.0)
        engine = _make_signal_engine_with_history(pos.ticker, df)
        client = _make_alpaca_client()
        monitor = PositionMonitor(
            client,
            engine,
            mock_trade_execution=True,
        )
        monitor.add_position(pos)
        return monitor, client

    def _options_pos_with_exit_order(self, exit_order_id="engine-close-99"):
        pos = _make_active_position(contracts=2)
        pos.entry_fill_price = _D("22.95")
        pos.exit_order_id = exit_order_id
        return pos

    # --- _fetch_manual_close_fill_price ---

    def test_fetch_manual_close_skips_engine_exit_order_id_returns_none(self):
        """Only filled sell order has order_id == pos.exit_order_id → return None."""
        pos = self._options_pos_with_exit_order("engine-close-99")
        monitor, client = self._make_monitor(pos)

        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "30.00",
                "order_id": "engine-close-99",
                "filled_at": None,
            }
        ]

        assert monitor._fetch_manual_close_fill_price(pos) is None

    def test_fetch_manual_close_returns_price_when_different_order_id(self):
        """Sell order with a different order_id is a genuine manual close — return its price."""
        pos = self._options_pos_with_exit_order("engine-close-99")
        monitor, client = self._make_monitor(pos)

        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "30.00",
                "order_id": "manual-close-1",
                "filled_at": None,
            }
        ]

        assert monitor._fetch_manual_close_fill_price(pos) == _D("30.00")

    def test_fetch_manual_close_skips_engine_order_returns_second_manual_order(self):
        """Engine order skipped; following manual close order is returned."""
        pos = self._options_pos_with_exit_order("engine-close-99")
        monitor, client = self._make_monitor(pos)

        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "30.00",
                "order_id": "engine-close-99",
                "filled_at": None,
            },
            {
                "side": "sell",
                "filled_avg_price": "28.50",
                "order_id": "manual-close-1",
                "filled_at": None,
            },
        ]

        assert monitor._fetch_manual_close_fill_price(pos) == _D("28.50")

    # --- _entry_confirmed_filled_no_manual_close ---

    def test_entry_confirmed_filled_skips_engine_exit_order_returns_true(self):
        """Engine's own exit_order_id must not be treated as a manual close — return True."""
        pos = self._options_pos_with_exit_order("engine-close-99")
        monitor, client = self._make_monitor(pos)

        client.order_status.return_value = {"status": "filled"}
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "30.00",
                "order_id": "engine-close-99",
                "filled_at": None,
            }
        ]

        assert monitor._entry_confirmed_filled_no_manual_close(pos) is True

    def test_entry_confirmed_filled_detects_genuine_manual_close_returns_false(self):
        """Sell order with a different order_id is correctly identified as a manual close."""
        pos = self._options_pos_with_exit_order("engine-close-99")
        monitor, client = self._make_monitor(pos)

        client.order_status.return_value = {"status": "filled"}
        client.get_filled_orders.return_value = [
            {
                "side": "sell",
                "filled_avg_price": "30.00",
                "order_id": "manual-sell-77",
                "filled_at": None,
            }
        ]

        assert monitor._entry_confirmed_filled_no_manual_close(pos) is False


class TestFifoQtySyncMultiPosition:
    """_sync_open_position_qtys FIFO attribution when two engine positions share the same ticker.

    Scenario mirrors the 2026-05-18 MU live trade:
    - M1 (primary): 10sh BEARISH short, entered first
    - DD (add-on): 16sh BEARISH short, entered second
    - Total engine: 26sh; broker shows 13sh (13sh manually covered)
    - Alpaca applies FIFO: cover hits M1 (oldest) first, then DD

    Expected FIFO attribution:
    - M1 fully closed: 10sh @ fill price
    - DD partially closed: 3sh @ fill price
    - M1.shares → 0; DD.shares → 13
    """

    def _make_monitor_with_two_positions(self, m1_shares=10, dd_shares=16, close_callback=None):
        import pytz
        from datetime import datetime
        ET = pytz.timezone("America/New_York")

        m1 = _make_stock_position(signal="BEARISH", shares=m1_shares)
        m1.window_label = "M1"
        m1.entry_time = ET.localize(datetime(2026, 5, 18, 9, 46, 0))

        dd = _make_stock_position(signal="BEARISH", shares=dd_shares)
        dd.window_label = "DD"
        dd.is_doubledown_addon = True
        dd.entry_time = ET.localize(datetime(2026, 5, 18, 9, 55, 0))

        client = _make_alpaca_client()
        df = _build_history_df([114.0], ma20=118.0, ma50=118.0, ma200=120.0)
        engine = _make_signal_engine_with_history("NVDA", df)
        monitor = PositionMonitor(
            client, engine, mock_trade_execution=True, close_callback=close_callback
        )
        monitor._positions.extend([m1, dd])
        return monitor, client, m1, dd

    def test_fifo_m1_fully_closed_dd_partially_closed(self):
        """13sh manual cover with M1=10 + DD=16: M1 fully consumed, DD gets remaining 3sh."""
        closed = []
        monitor, client, m1, dd = self._make_monitor_with_two_positions(
            m1_shares=10, dd_shares=16, close_callback=closed.append
        )
        client.get_open_positions.return_value = {"NVDA": {"qty": -13.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "cover1", "side": "buy", "filled_avg_price": 702.80,
             "filled_qty": 13.0, "filled_at": None},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        assert m1.shares == 0
        assert dd.shares == 13

    def test_fifo_close_callback_fires_for_m1_and_dd(self):
        """Both the M1 (10sh) and DD (3sh) partial closes fire the close callback."""
        closed = []
        monitor, client, m1, dd = self._make_monitor_with_two_positions(
            m1_shares=10, dd_shares=16, close_callback=closed.append
        )
        client.get_open_positions.return_value = {"NVDA": {"qty": -13.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "cover1", "side": "buy", "filled_avg_price": 702.80,
             "filled_qty": 13.0, "filled_at": None},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        assert len(closed) == 2
        m1_close = next(p for p in closed if p.window_label == "M1")
        dd_close = next(p for p in closed if p.window_label == "DD")
        assert m1_close.shares == 10
        assert dd_close.shares == 3

    def test_fifo_fill_price_is_weighted_average_across_split_order(self):
        """One 13sh fill covers M1 (10sh) fully and DD (3sh); both get same price."""
        closed = []
        monitor, client, m1, dd = self._make_monitor_with_two_positions(
            m1_shares=10, dd_shares=16, close_callback=closed.append
        )
        client.get_open_positions.return_value = {"NVDA": {"qty": -13.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "cover1", "side": "buy", "filled_avg_price": 702.80,
             "filled_qty": 13.0, "filled_at": None},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        assert all(p.exit_fill_price == _D("702.80") for p in closed)

    def test_fifo_two_separate_orders_attributed_oldest_first(self):
        """Two fill orders: first 10sh, then 3sh. M1 (oldest) gets first order, DD gets second."""
        import pytz
        from datetime import datetime
        ET = pytz.timezone("America/New_York")
        closed = []
        monitor, client, m1, dd = self._make_monitor_with_two_positions(
            m1_shares=10, dd_shares=5, close_callback=closed.append
        )
        client.get_open_positions.return_value = {"NVDA": {"qty": -2.0}}
        client.get_filled_orders.return_value = [
            {"order_id": "cover1", "side": "buy", "filled_avg_price": 702.00,
             "filled_qty": 10.0, "filled_at": ET.localize(datetime(2026, 5, 18, 11, 0))},
            {"order_id": "cover2", "side": "buy", "filled_avg_price": 668.00,
             "filled_qty": 3.0, "filled_at": ET.localize(datetime(2026, 5, 18, 14, 44))},
        ]

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        m1_close = next(p for p in closed if p.window_label == "M1")
        dd_close = next(p for p in closed if p.window_label == "DD")
        assert m1_close.shares == 10
        assert m1_close.exit_fill_price == _D("702.00")
        assert dd_close.shares == 3
        assert dd_close.exit_fill_price == _D("668.00")
        assert m1.shares == 0
        assert dd.shares == 2

    def test_fifo_no_fill_orders_updates_shares_without_callback(self):
        """No fill orders found: shares still updated, callback not fired."""
        closed = []
        monitor, client, m1, dd = self._make_monitor_with_two_positions(
            m1_shares=10, dd_shares=16, close_callback=closed.append
        )
        client.get_open_positions.return_value = {"NVDA": {"qty": -13.0}}
        client.get_filled_orders.return_value = []

        with patch("alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"):
            monitor._sync_open_position_qtys()

        assert closed == []
        assert m1.shares == 0
        assert dd.shares == 13
