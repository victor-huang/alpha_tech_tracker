"""
End-to-end full-day simulation tests.

Each test drives the engine against a static fixture file, mocking only
3rd-party API calls (Alpaca). The fixture captures the "golden path" expected
outcomes so that any future change to signal logic, sizing, stop conditions,
or P&L calculation will immediately surface as a test failure.

Data flow under test:
  LiveSignalEngine._process_five_min_bar()  (opening bars injected directly)
    → SignalEvent captured via on_signal callback
  OpMomentumTradeEngine._enter_position()   (called without threading)
    → OptionContractSelector selects contract  (mock get_options_contracts)
    → PositionSizer computes qty/price        (mock get_accounts + quote)
    → _place_entry in mock mode              (mock quote → simulated fill)
    → ActivePosition added to PositionMonitor
  PositionMonitor.on_bar()                  (monitoring bars injected via _set_latest_bar)
    → _evaluate_stop fires exit condition
    → _close_position in mock mode           (mock quote → simulated exit mid)

Assertions cover: signal direction, OR levels, stop prices, contract selection,
position sizing (contracts), entry/exit simulated fills, exit reason, and P&L.
"""

import asyncio
import json
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _D, _FiveMinBar, SignalEvent
from alpha_tech_tracker.op_momentum_strategy.position_monitor import PositionMonitor
from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine

from conftest import (
    _build_history_df,
    _make_alpaca_client,
    _make_option_quote,
    _make_signal_engine_with_history,
    _set_latest_bar,
)

ET = pytz.timezone("America/New_York")

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_TODAY_PATH = "alpha_tech_tracker.op_momentum_strategy.contract_selector._today"
_HIST_CLIENT_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient"
)
_NOTIFY_TRADE_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine._notify"
_NOTIFY_MONITOR_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.position_monitor._notify"
)


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def _make_five_min_bar(ticker: str, bar_dict: dict, session_date: date) -> _FiveMinBar:
    import pytz

    ET = pytz.timezone("America/New_York")
    h, m = bar_dict["time"].split(":")
    ts = ET.localize(
        datetime.combine(session_date, datetime.min.time()).replace(
            hour=int(h), minute=int(m)
        )
    )
    return _FiveMinBar(
        symbol=ticker,
        timestamp=ts,
        open=bar_dict["open"],
        high=bar_dict["high"],
        low=bar_dict["low"],
        close=bar_dict["close"],
        volume=bar_dict["volume"],
    )


def _build_history_from_fixture(fx: dict) -> object:
    h = fx["history"]
    n = h["num_bars"]
    return _build_history_df(
        closes=[h["close"]] * n,
        ma20=[h["ma20"]] * n,
        ma50=[h["ma50"]] * n,
        ma200=[h["ma200"]] * n,
    )


def _wire_engine_and_monitor(client, signal_engine):
    engine = OpMomentumTradeEngine(
        alpaca_client=client,
        mock_trade_execution=True,
    )
    engine._signal_engine = signal_engine
    monitor = PositionMonitor(client, signal_engine, mock_trade_execution=True)
    engine._monitor = monitor
    return engine, monitor


class TestFullDaySimulationNvdaBullish:
    @pytest.fixture(autouse=True)
    def patch_notify(self):
        with patch(_NOTIFY_TRADE_PATH), patch(_NOTIFY_MONITOR_PATH):
            yield

    def _run_scenario(self, fixture_name: str):
        fx = _load_fixture(fixture_name)
        ticker = fx["ticker"]
        session_date = date.fromisoformat(fx["session_date"])
        expected = fx["expected"]
        mock_api = fx["mock_api"]
        option_symbol = expected["option_symbol"]

        # --- Signal engine with pre-warmed history ---
        history_df = _build_history_from_fixture(fx)
        signal_engine = _make_signal_engine_with_history(ticker, history_df)

        captured: list = []
        signal_engine._windows[0]["on_signal"] = captured.append

        # --- Feed opening bars directly (bypass WebSocket) ---
        for bar_dict in fx["opening_bars"]:
            bar = _make_five_min_bar(ticker, bar_dict, session_date)
            signal_engine._process_five_min_bar(bar)

        assert len(captured) == 1, "Expected exactly one signal"
        event: SignalEvent = captured[0]

        # --- Mock Alpaca client responses ---
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = mock_api["option_contracts"]
        client.get_accounts.return_value = {
            "buying_power": mock_api["account_buying_power"]
        }

        entry_q = _make_option_quote(
            mock_api["entry_quote"]["bid"], mock_api["entry_quote"]["ask"]
        )
        exit_q = _make_option_quote(
            mock_api["exit_quote"]["bid"], mock_api["exit_quote"]["ask"]
        )
        client._option_data_client.get_option_latest_quote.side_effect = [
            {option_symbol: entry_q},  # TimePremiumContractSelector batch fetch
            {option_symbol: entry_q},  # PositionSizer.compute()
            {option_symbol: entry_q},  # _place_entry() re-fetches for exact mid
            {option_symbol: exit_q},   # _close_position() exit mid
        ]

        engine, monitor = _wire_engine_and_monitor(client, signal_engine)

        # --- Enter position ---
        with patch(_TODAY_PATH, return_value=session_date):
            engine._enter_position(event, rank=0)

        assert len(monitor._positions) == 1
        pos = monitor._positions[0]

        # --- Feed monitoring bars, stop after expected exit fires ---
        for mon_bar in fx["monitoring_bars"]:
            _set_latest_bar(
                signal_engine,
                ticker,
                close=mon_bar["close"],
                ma50=mon_bar["ma50"],
                ma20=mon_bar["ma20"],
            )
            monitor.on_bar(ticker)
            if mon_bar["expected_exit"] is not None:
                break

        return event, pos, expected

    def test_signal_is_bullish(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert event.signal == expected["signal"]
        assert pos.signal == expected["signal"]

    def test_opening_range_levels(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.or_high == _D(expected["or_high"])
        assert pos.or_low == _D(expected["or_low"])

    def test_stop_prices_computed_from_or(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.hard_stop_price == _D(expected["hard_stop_price"])
        assert pos.fallback_price == _D(expected["fallback_price"])

    def test_contract_selection(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.option_symbol == expected["option_symbol"]

    def test_position_sizing(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.contracts == expected["contracts"]

    def test_entry_simulated_fill(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.simulated_entry_mid == _D(expected["entry_mid"])

    def test_position_closed_by_trailing_ma20(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.is_closed
        assert pos.exit_reason == expected["exit_reason"]

    def test_exit_simulated_fill(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        assert pos.simulated_exit_mid == _D(expected["exit_mid"])

    def test_pnl_matches_fixture(self):
        event, pos, expected = self._run_scenario("full_day_nvda_bullish.json")
        pnl = (
            (pos.simulated_exit_mid - pos.simulated_entry_mid)
            * Decimal(pos.contracts)
            * Decimal("100")
        )
        assert pnl == _D(expected["pnl"])


class TestLivePipingSimulation:
    """
    Feeds raw historical 1-minute bars through the engine's real async _handle_bar
    path in a background asyncio thread — no mocking of internal logic — to verify
    that 5-min bar aggregation and signal detection work exactly as in live trading.
    """

    def test_one_min_bars_produce_bullish_signal(self):
        fx = _load_fixture("one_min_bars_nvda_bullish.json")
        ticker = fx["ticker"]

        history_df = _build_history_from_fixture(fx)
        signal_engine = _make_signal_engine_with_history(ticker, history_df)

        captured = []
        signal_received = threading.Event()

        def on_signal(event):
            captured.append(event)
            signal_received.set()

        signal_engine._windows[0]["on_signal"] = on_signal

        today = datetime.now(ET).date()
        market_open = ET.localize(
            datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
        )

        one_min_bars = []
        for b in fx["one_min_bars"]:
            bar = Mock()
            bar.symbol = ticker
            bar.timestamp = market_open + timedelta(minutes=b["minute_offset"])
            bar.open = b["open"]
            bar.high = b["high"]
            bar.low = b["low"]
            bar.close = b["close"]
            bar.volume = b["volume"]
            one_min_bars.append(bar)

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()

        with patch(_HIST_CLIENT_PATH) as mock_hdc:
            mock_hdc.return_value.get_stock_bars.side_effect = Exception(
                "no catchup data"
            )

            for bar in one_min_bars:
                asyncio.run_coroutine_threadsafe(
                    signal_engine._handle_bar(bar), loop
                ).result(timeout=5)

            signal_received.wait(timeout=5)

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)

        assert len(captured) == 1
        event = captured[0]
        assert event.signal == fx["expected"]["signal"]
        assert event.or_high == _D(fx["expected"]["or_high"])
        assert event.or_low == _D(fx["expected"]["or_low"])


class TestLivePipingFullDay:
    """
    End-to-end test that starts from raw 1-minute bars (real async _handle_bar threading),
    flows through signal detection, trade entry, position monitoring, and exit — with only
    3rd-party Alpaca API calls mocked.
    """

    FIXTURE = "one_min_bars_nvda_bullish.json"

    @pytest.fixture(autouse=True)
    def patch_notify(self):
        with patch(_NOTIFY_TRADE_PATH), patch(_NOTIFY_MONITOR_PATH):
            yield

    def _run_scenario(self, fixture_name: str):
        fx = _load_fixture(fixture_name)
        ticker = fx["ticker"]
        expected = fx["expected"]
        mock_api = fx["mock_api"]
        option_symbol = expected["option_symbol"]

        history_df = _build_history_from_fixture(fx)
        signal_engine = _make_signal_engine_with_history(ticker, history_df)

        captured = []
        signal_received = threading.Event()

        def on_signal(event):
            captured.append(event)
            signal_received.set()

        signal_engine._windows[0]["on_signal"] = on_signal

        today = datetime.now(ET).date()
        market_open = ET.localize(
            datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
        )

        one_min_bars = []
        for b in fx["one_min_bars"]:
            bar = Mock()
            bar.symbol = ticker
            bar.timestamp = market_open + timedelta(minutes=b["minute_offset"])
            bar.open = b["open"]
            bar.high = b["high"]
            bar.low = b["low"]
            bar.close = b["close"]
            bar.volume = b["volume"]
            one_min_bars.append(bar)

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()

        with patch(_HIST_CLIENT_PATH) as mock_hdc:
            mock_hdc.return_value.get_stock_bars.side_effect = Exception(
                "no catchup data"
            )
            for bar in one_min_bars:
                asyncio.run_coroutine_threadsafe(
                    signal_engine._handle_bar(bar), loop
                ).result(timeout=5)
            signal_received.wait(timeout=5)

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)

        assert len(captured) == 1, "Expected exactly one signal from 1-min bar feed"
        event: SignalEvent = captured[0]

        client = _make_alpaca_client()
        client.get_options_contracts.return_value = mock_api["option_contracts"]
        client.get_accounts.return_value = {
            "buying_power": mock_api["account_buying_power"]
        }

        entry_q = _make_option_quote(
            mock_api["entry_quote"]["bid"], mock_api["entry_quote"]["ask"]
        )
        exit_q = _make_option_quote(
            mock_api["exit_quote"]["bid"], mock_api["exit_quote"]["ask"]
        )
        client._option_data_client.get_option_latest_quote.side_effect = [
            {option_symbol: entry_q},  # TimePremiumContractSelector batch fetch
            {option_symbol: entry_q},
            {option_symbol: entry_q},
            {option_symbol: exit_q},
        ]

        engine, monitor = _wire_engine_and_monitor(client, signal_engine)
        engine._enter_position(event, rank=0)

        assert len(monitor._positions) == 1
        pos = monitor._positions[0]

        for mon_bar in fx["monitoring_bars"]:
            _set_latest_bar(
                signal_engine,
                ticker,
                close=mon_bar["close"],
                ma50=mon_bar["ma50"],
                ma20=mon_bar["ma20"],
            )
            monitor.on_bar(ticker)
            if mon_bar["expected_exit"] is not None:
                break

        return event, pos, expected

    def test_signal_is_bullish(self):
        event, pos, expected = self._run_scenario(self.FIXTURE)
        assert event.signal == expected["signal"]
        assert pos.signal == expected["signal"]

    def test_opening_range_levels(self):
        event, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.or_high == _D(expected["or_high"])
        assert pos.or_low == _D(expected["or_low"])

    def test_stop_prices_computed_from_or(self):
        event, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.hard_stop_price == _D(expected["hard_stop_price"])
        assert pos.fallback_price == _D(expected["fallback_price"])

    def test_contract_selection(self):
        _, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.option_symbol == expected["option_symbol"]

    def test_position_sizing(self):
        _, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.contracts == expected["contracts"]

    def test_entry_simulated_fill(self):
        _, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.simulated_entry_mid == _D(expected["entry_mid"])

    def test_position_closed_by_trailing_ma20(self):
        _, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.is_closed
        assert pos.exit_reason == expected["exit_reason"]

    def test_exit_simulated_fill(self):
        _, pos, expected = self._run_scenario(self.FIXTURE)
        assert pos.simulated_exit_mid == _D(expected["exit_mid"])

    def test_pnl_matches_fixture(self):
        _, pos, expected = self._run_scenario(self.FIXTURE)
        pnl = (
            (pos.simulated_exit_mid - pos.simulated_entry_mid)
            * Decimal(pos.contracts)
            * Decimal("100")
        )
        assert pnl == _D(expected["pnl"])
