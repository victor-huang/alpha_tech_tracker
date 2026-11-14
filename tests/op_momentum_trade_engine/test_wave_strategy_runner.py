import csv
import json
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy import wave_strategy_runner as runner_module
from alpha_tech_tracker.op_momentum_strategy.position_sizer import InsufficientBuyingPowerError
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.intents import (
    BAR_CLOSE,
    ENTER,
    EXIT,
    MOC,
    MOVE_STOP,
    STOP,
    Intent,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import ET
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.specs import build_setup_spec
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.trades import LiveTrade
from alpha_tech_tracker.op_momentum_strategy.wave_strategy_runner import WaveStrategyRunner

SESSION = date(2026, 10, 6)


def _ts(text):
    return ET.localize(datetime.strptime(text, "%Y-%m-%d %H:%M"))


class _Clock:
    def __init__(self, text):
        self.value = _ts(text)

    def __call__(self):
        return self.value


def _bars(closes_by_time):
    index = pd.DatetimeIndex([_ts(t) for t in closes_by_time])
    closes = list(closes_by_time.values())
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes}, index=index)


def _runner(tmp_path, mocker, tickers=("AMD",), **kwargs):
    notes = []
    runner = WaveStrategyRunner(
        {t: [build_setup_spec("drive long")] for t in tickers}, mocker.Mock(), state_file=tmp_path / "state.json",
        trades_dir=tmp_path, notify=notes.append, now=_Clock("2026-10-06 09:35"), releases_loader=lambda t: [],
        daily_closes_loader=lambda tickers, session: {}, trend_daily_loader=lambda tickers, session: {},
        short_setups=[], **kwargs)
    runner.strategy.start_session(SESSION, {t: _bars({"2026-10-06 09:30": 100.0}) for t in tickers})
    return runner, notes


def _trade(ticker="AMD", setup="drive long", side=1, entry=100.0, stop=99.0, exit_mode="eod"):
    return LiveTrade(ticker=ticker, setup=setup, exit_mode=exit_mode, entry_time=_ts("2026-10-06 09:30"), side=side,
                     entry=entry, stop=stop, risk=None if stop is None else abs(entry - stop))


def _enter(runner, trade, order=BAR_CLOSE):
    action = "BUY" if trade.side == 1 else "SHORT"
    runner._on_intent(Intent(ENTER, f"{action} {trade.ticker}", action, trade, trade.ticker, trade.setup,
                             trade.entry, order))


def _exit(runner, trade, price, order=STOP):
    action = "SOLD" if trade.side == 1 else "COVERED"
    runner._on_intent(Intent(EXIT, f"{action} {trade.ticker}", action, trade, trade.ticker, trade.setup, price, order))


def _live_runner(tmp_path, mocker, **kwargs):
    mocker.patch.object(runner_module, "place_stock_order", return_value={"order_id": "o1", "filled_avg_price": 100.0})
    return _runner(tmp_path, mocker, mock=False, execution_client=mocker.Mock(), **kwargs)


def _close_outcomes(mocker, runner, outcomes):
    """Patch the broker close: each call takes the next outcome (True fills at 99, False fails, an exception raises)."""
    def close(pos, reason, exit_stock_price_override=None):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        pos.close_order_failed = not outcome
        if outcome:
            pos.exit_fill_price = Decimal("99.0")

    return mocker.patch.object(runner.position_monitor, "_close_stock_position", side_effect=close)


def _rows(tmp_path):
    with open(tmp_path / f"wave_strategy_engine_trades_{SESSION}.csv", newline="") as handle:
        return list(csv.DictReader(handle))


class TestEntries:
    def test_mock_entry_fills_at_the_strategys_price_with_a_slot_sized_position(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker, balance=20000, slots=10)

        _enter(runner, _trade(entry=480.5))

        pos = runner.open_positions()[0]
        assert (pos.signal, pos.shares, pos.entry_stock_price, pos.hard_stop_price) == (
            "BULLISH", 4, Decimal("480.5"), Decimal("99.0"))
        assert _rows(tmp_path)[0]["price"] == "480.5000"

    def test_a_short_entry_opens_a_bearish_position(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)

        _enter(runner, _trade(setup="short drive", side=-1, stop=101.0))

        assert runner.open_positions()[0].signal == "BEARISH"

    def test_skips_when_every_slot_is_taken(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker, tickers=("AMD", "APP", "MU"), balance=20000, slots=2)
        for ticker in ("AMD", "APP"):
            _enter(runner, _trade(ticker=ticker))
        for pos in runner.open_positions():
            pos.entry_stock_price = Decimal("1")  # leaves the balance free, so only the slot count can block

        _enter(runner, _trade(ticker="MU"))

        assert [p.ticker for p in runner.open_positions()] == ["AMD", "APP"]

    def test_skips_when_the_free_balance_is_short_of_a_slot(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker, tickers=("AMD", "APP"), balance=2000, slots=2)
        _enter(runner, _trade(ticker="AMD", entry=10.0))
        runner.open_positions()[0].entry_stock_price = Decimal("19.0")  # 100 shares now cost 1,900 of the 2,000

        _enter(runner, _trade(ticker="APP"))

        assert [p.ticker for p in runner.open_positions()] == ["AMD"]

    def test_skips_a_ticker_priced_above_the_slot(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker, balance=1000, slots=2)

        _enter(runner, _trade(entry=600.0))

        assert runner.open_positions() == []

    def test_overnight_entries_are_not_traded(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)

        _enter(runner, _trade(setup="overnight always", stop=None, exit_mode="next open"), order=MOC)

        assert runner.open_positions() == []

    def test_live_entry_places_the_order_and_records_the_fill(self, tmp_path, mocker):
        place = mocker.patch.object(runner_module, "place_stock_order",
                                    return_value={"order_id": "o1", "filled_avg_price": 100.07})
        runner, _ = _runner(tmp_path, mocker, mock=False, execution_client=mocker.Mock())

        _enter(runner, _trade(setup="short drive", side=-1, stop=101.0))

        assert place.call_args.args[1:4] == ("AMD", 20, "SELL_SHORT")
        assert runner.open_positions()[0].entry_fill_price == Decimal("100.07")

    def test_skips_when_the_broker_reports_too_little_buying_power(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)
        mocker.patch.object(runner.sizer, "compute_stock", side_effect=InsufficientBuyingPowerError("$500 free"))

        _enter(runner, _trade())

        assert runner.positions == {}

    def test_a_sizing_error_is_alerted_and_not_traded(self, tmp_path, mocker):
        runner, notes = _runner(tmp_path, mocker)
        mocker.patch.object(runner.sizer, "compute_stock", side_effect=ConnectionError("broker down"))

        _enter(runner, _trade())

        assert runner.positions == {}
        assert "ENTRY FAILED AMD" in notes[-1]

    def test_live_mode_needs_an_execution_client(self, tmp_path, mocker):
        with pytest.raises(ValueError):
            _runner(tmp_path, mocker, mock=False)


class TestExits:
    def test_mock_exit_closes_at_the_strategys_price_with_its_pnl(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)

        _exit(runner, trade, 98.995)

        pos = next(iter(runner.positions.values()))
        assert (pos.is_closed, pos.exit_reason, pos.simulated_exit_mid) == (True, "wave_stop", Decimal("98.995"))
        assert _rows(tmp_path)[-1]["pnl"] == "-20.10"

    def test_a_short_exits_with_the_pnl_of_a_short(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)
        trade = _trade(setup="short drive", side=-1, stop=101.0)
        _enter(runner, trade)

        _exit(runner, trade, 98.0, order=MOC)

        assert _rows(tmp_path)[-1]["pnl"] == "40.00"
        assert next(iter(runner.positions.values())).exit_reason == "wave_close"

    def test_exit_without_a_position_is_ignored(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker, balance=1000, slots=2)
        trade = _trade(entry=600.0)
        _enter(runner, trade)

        _exit(runner, trade, 590.0)

        assert runner.positions == {}

    def test_move_stop_updates_the_positions_stop(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)

        runner._on_intent(Intent(MOVE_STOP, "RAISE STOP AMD", "RAISE STOP", trade, "AMD", "drive long", 99.5))

        assert runner.open_positions()[0].hard_stop_price == Decimal("99.5")


class TestFailedCloses:
    def test_a_failed_close_is_flagged_alerted_and_recorded(self, tmp_path, mocker):
        runner, notes = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        _close_outcomes(mocker, runner, [False])

        _exit(runner, trade, 99.0)

        pos = next(iter(runner.positions.values()))
        assert (pos.is_closed, pos.close_order_failed) == (True, True)
        assert "CLOSE FAILED AMD" in notes[-1]
        assert _rows(tmp_path)[-1]["order"] == "FAILED"

    def test_an_exception_while_closing_does_not_escape(self, tmp_path, mocker):
        runner, _ = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        _close_outcomes(mocker, runner, [ConnectionError("timeout")])

        _exit(runner, trade, 99.0)

        assert next(iter(runner.positions.values())).close_order_failed is True

    def test_the_tickers_next_bar_retries_the_close(self, tmp_path, mocker):
        runner, _ = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        _close_outcomes(mocker, runner, [False, True])
        _exit(runner, trade, 99.0)

        runner._retry_failed_closes("AMD")

        pos = next(iter(runner.positions.values()))
        assert pos.close_order_failed is False
        assert (_rows(tmp_path)[-1]["order"], _rows(tmp_path)[-1]["pnl"]) == ("RETRY", "-20.00")

    def test_another_tickers_bar_does_not_retry(self, tmp_path, mocker):
        runner, _ = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        close = _close_outcomes(mocker, runner, [False])
        _exit(runner, trade, 99.0)

        runner._retry_failed_closes("APP")

        assert close.call_count == 1

    def test_retries_stop_after_the_limit_with_one_alert(self, tmp_path, mocker):
        runner, notes = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        close = _close_outcomes(mocker, runner, [False] * 4)
        _exit(runner, trade, 99.0)

        for _ in range(runner_module.MAX_CLOSE_RETRIES + 2):
            runner._retry_failed_closes("AMD")

        assert close.call_count == 1 + runner_module.MAX_CLOSE_RETRIES
        assert sum("retries failed" in n for n in notes) == 1

    def test_the_end_of_the_session_tries_a_market_close_past_the_limit(self, tmp_path, mocker):
        runner, _ = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        close = _close_outcomes(mocker, runner, [False] * 4 + [True])
        _exit(runner, trade, 99.0)
        for _ in range(runner_module.MAX_CLOSE_RETRIES):
            runner._retry_failed_closes("AMD")

        runner.finish(session_over=True)

        assert close.call_args.args[1] == "end_of_day"
        assert next(iter(runner.positions.values())).close_order_failed is False

    def test_a_failed_close_survives_a_restart(self, tmp_path, mocker):
        first, _ = _live_runner(tmp_path, mocker)
        trade = _trade()
        _enter(first, trade)
        first.strategy.trades.append(trade)
        _close_outcomes(mocker, first, [False])
        _exit(first, trade, 99.0)
        first.finish(session_over=False)
        second, _ = _live_runner(tmp_path, mocker)

        second._load_state()

        pos = next(iter(second.positions.values()))
        assert (pos.close_order_failed, pos.close_retry_count) == (True, 0)


class TestFinish:
    def test_the_end_of_the_session_closes_what_is_still_open_at_the_last_close(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)
        _enter(runner, _trade())

        runner.finish(session_over=True)

        pos = next(iter(runner.positions.values()))
        assert (pos.is_closed, pos.exit_reason, pos.simulated_exit_mid) == (True, "end_of_day", Decimal("100.0"))

    def test_a_stop_before_the_end_keeps_positions_open_in_the_state(self, tmp_path, mocker):
        runner, _ = _runner(tmp_path, mocker)
        _enter(runner, _trade())

        runner.finish(session_over=False)

        saved = json.loads((tmp_path / "state.json").read_text())["positions"]
        assert [p["is_closed"] for p in saved.values()] == [False]

    def test_the_summary_reports_the_sessions_pnl(self, tmp_path, mocker):
        runner, notes = _runner(tmp_path, mocker)
        trade = _trade()
        _enter(runner, trade)
        runner.now.value = _ts("2026-10-06 10:00")
        _exit(runner, trade, 101.0)

        runner.finish(session_over=True)

        assert notes[-1] == "[wave engine] 2026-10-06 wave engine: 1 trades closed, $+20.00"


class TestRestart:
    def test_a_same_session_restart_restores_the_open_positions(self, tmp_path, mocker):
        first, _ = _runner(tmp_path, mocker)
        trade = _trade()
        _enter(first, trade)
        first.strategy.trades.append(trade)
        first.finish(session_over=False)
        second, _ = _runner(tmp_path, mocker)

        second._load_state()

        assert [p.ticker for p in second.open_positions()] == ["AMD"]
        assert [p.ticker for p in second.position_monitor.get_all_positions()] == ["AMD"]

    def test_positions_left_open_by_an_earlier_session_are_alerted_not_restored(self, tmp_path, mocker):
        first, _ = _runner(tmp_path, mocker)
        _enter(first, _trade())
        first.finish(session_over=False)
        state = json.loads((tmp_path / "state.json").read_text())
        state["session"] = "2026-10-05"
        (tmp_path / "state.json").write_text(json.dumps(state))
        second, notes = _runner(tmp_path, mocker)

        second._load_state()

        assert second.positions == {}
        assert "still open" in notes[-1] and "AMD x20" in notes[-1]
