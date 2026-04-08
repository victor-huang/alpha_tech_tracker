import threading
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _FiveMinBar
from alpha_tech_tracker.op_momentum_strategy.replay import (
    BarReplayDriver,
    _now_et,
    clear_replay_clock,
    set_replay_clock,
)

ET = pytz.timezone("America/New_York")


def _et(h, m, d=date(2026, 3, 17)):
    return ET.localize(datetime.combine(d, datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()))


def _bar(ticker, h, m, close=100.0, d=date(2026, 3, 17)):
    ts = _et(h, m, d)
    return _FiveMinBar(symbol=ticker, timestamp=ts, open=close, high=close + 1, low=close - 1, close=close, volume=1000)


class TestReplayClock:
    def teardown_method(self, _):
        clear_replay_clock()

    def test_now_et_returns_wall_clock_when_no_clock_set(self):
        clear_replay_clock()
        before = datetime.now(ET)
        result = _now_et()
        after = datetime.now(ET)
        assert before <= result <= after

    def test_set_replay_clock_overrides_now_et(self):
        fixed = _et(9, 45)
        set_replay_clock(lambda: fixed)
        assert _now_et() == fixed

    def test_clear_replay_clock_restores_wall_clock(self):
        set_replay_clock(lambda: _et(9, 45))
        clear_replay_clock()
        before = datetime.now(ET)
        result = _now_et()
        after = datetime.now(ET)
        assert before <= result <= after

    def test_clock_can_be_updated_between_calls(self):
        set_replay_clock(lambda: _et(9, 30))
        assert _now_et().hour == 9 and _now_et().minute == 30
        set_replay_clock(lambda: _et(10, 0))
        assert _now_et().hour == 10 and _now_et().minute == 0

    def test_clock_is_thread_safe(self):
        results = []
        fixed = _et(14, 0)
        set_replay_clock(lambda: fixed)

        def reader():
            for _ in range(50):
                results.append(_now_et())

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r == fixed for r in results)


class TestBarReplayDriverTimeline:
    def test_build_timeline_single_ticker_in_order(self):
        bars = {
            "NVDA": [_bar("NVDA", 9, 35), _bar("NVDA", 9, 30), _bar("NVDA", 9, 40)],
        }
        driver = BarReplayDriver(tickers=["NVDA"], replay_date=date(2026, 3, 17), signal_engine=MagicMock())
        timeline = driver._build_timeline(bars)
        timestamps = [b.timestamp for b in timeline]
        assert timestamps == sorted(timestamps)

    def test_build_timeline_merges_multiple_tickers_by_timestamp(self):
        d = date(2026, 3, 17)
        bars = {
            "NVDA": [_bar("NVDA", 9, 30), _bar("NVDA", 9, 40)],
            "TSLA": [_bar("TSLA", 9, 35), _bar("TSLA", 9, 45)],
        }
        driver = BarReplayDriver(tickers=["NVDA", "TSLA"], replay_date=d, signal_engine=MagicMock())
        timeline = driver._build_timeline(bars)
        timestamps = [b.timestamp for b in timeline]
        assert timestamps == sorted(timestamps)
        assert len(timeline) == 4

    def test_build_timeline_empty_ticker_excluded(self):
        bars = {"NVDA": [_bar("NVDA", 9, 30)], "TSLA": []}
        driver = BarReplayDriver(tickers=["NVDA", "TSLA"], replay_date=date(2026, 3, 17), signal_engine=MagicMock())
        timeline = driver._build_timeline(bars)
        assert len(timeline) == 1
        assert timeline[0].symbol == "NVDA"

    def test_build_timeline_excludes_bars_at_or_after_eod_exit_time(self):
        bars = {
            "NVDA": [
                _bar("NVDA", 15, 50),
                _bar("NVDA", 15, 55),  # EOD_EXIT_TIME — should be excluded
                _bar("NVDA", 16, 0),   # after close — should be excluded
            ],
        }
        driver = BarReplayDriver(tickers=["NVDA"], replay_date=date(2026, 3, 17), signal_engine=MagicMock())
        timeline = driver._build_timeline(bars)
        assert len(timeline) == 1
        assert timeline[0].timestamp.hour == 15
        assert timeline[0].timestamp.minute == 50


class TestBarReplayDriverRun:
    def teardown_method(self, _):
        clear_replay_clock()

    def _make_driver(self, bars_by_ticker, on_bar=None):
        signal_engine = MagicMock()
        replay_date = date(2026, 3, 17)
        driver = BarReplayDriver(
            tickers=list(bars_by_ticker.keys()),
            replay_date=replay_date,
            signal_engine=signal_engine,
            on_bar_injected=on_bar,
        )
        with patch.object(driver, "_fetch_session_bars", return_value=bars_by_ticker):
            driver.run()
        return driver, signal_engine

    def test_run_injects_each_bar_into_signal_engine(self):
        b1 = _bar("NVDA", 9, 30)
        b2 = _bar("NVDA", 9, 35)
        driver, engine = self._make_driver({"NVDA": [b1, b2]})
        assert engine._process_five_min_bar.call_count == 2
        engine._process_five_min_bar.assert_any_call(b1)
        engine._process_five_min_bar.assert_any_call(b2)

    def test_run_advances_clock_per_bar(self):
        clocks_seen = []
        b1 = _bar("NVDA", 9, 30)
        b2 = _bar("NVDA", 9, 35)

        signal_engine = MagicMock()
        signal_engine._process_five_min_bar.side_effect = lambda b: clocks_seen.append(_now_et())

        driver = BarReplayDriver(
            tickers=["NVDA"],
            replay_date=date(2026, 3, 17),
            signal_engine=signal_engine,
        )
        with patch.object(driver, "_fetch_session_bars", return_value={"NVDA": [b1, b2]}):
            driver.run()

        assert clocks_seen[0] == b1.timestamp
        assert clocks_seen[1] == b2.timestamp

    def test_run_calls_on_bar_injected_after_each_bar(self):
        tickers_seen = []
        b1 = _bar("NVDA", 9, 30)
        b2 = _bar("TSLA", 9, 35)
        driver, _ = self._make_driver({"NVDA": [b1], "TSLA": [b2]}, on_bar=tickers_seen.append)
        assert set(tickers_seen) == {"NVDA", "TSLA"}

    def test_run_clears_clock_after_completion(self):
        driver, _ = self._make_driver({"NVDA": [_bar("NVDA", 9, 30)]})
        before = datetime.now(ET)
        result = _now_et()
        after = datetime.now(ET)
        assert before <= result <= after

    def test_run_injects_bars_in_timestamp_order(self):
        injected = []
        b_late = _bar("NVDA", 9, 40)
        b_early = _bar("NVDA", 9, 30)

        signal_engine = MagicMock()
        signal_engine._process_five_min_bar.side_effect = injected.append

        driver = BarReplayDriver(
            tickers=["NVDA"],
            replay_date=date(2026, 3, 17),
            signal_engine=signal_engine,
        )
        with patch.object(driver, "_fetch_session_bars", return_value={"NVDA": [b_late, b_early]}):
            driver.run()

        assert injected[0].timestamp < injected[1].timestamp


class TestBarReplayDriverFetch:
    def test_fetch_session_bars_filters_to_replay_date_only(self):
        replay_date = date(2026, 3, 17)
        prev_day = replay_date - timedelta(days=1)

        idx_prev = pd.DatetimeIndex([ET.localize(datetime.combine(prev_day, datetime.strptime("15:55", "%H:%M").time()))])
        idx_today = pd.DatetimeIndex([
            ET.localize(datetime.combine(replay_date, datetime.strptime("09:30", "%H:%M").time())),
            ET.localize(datetime.combine(replay_date, datetime.strptime("09:35", "%H:%M").time())),
        ])
        df = pd.DataFrame(
            {"Open": [99, 100, 101], "High": [100, 101, 102], "Low": [98, 99, 100], "Close": [100, 101, 102], "Volume": [1000, 1000, 1000]},
            index=idx_prev.append(idx_today),
        )

        driver = BarReplayDriver(tickers=["NVDA"], replay_date=replay_date, signal_engine=MagicMock())
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.replay.fetch_bars",
            return_value={"NVDA": df},
        ):
            result = driver._fetch_session_bars()

        assert len(result["NVDA"]) == 2
        assert all(b.timestamp.date() == replay_date for b in result["NVDA"])

    def test_fetch_session_bars_returns_empty_list_for_missing_ticker(self):
        replay_date = date(2026, 3, 17)
        driver = BarReplayDriver(tickers=["NVDA"], replay_date=replay_date, signal_engine=MagicMock())
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.replay.fetch_bars",
            return_value={"NVDA": pd.DataFrame()},
        ):
            result = driver._fetch_session_bars()
        assert result["NVDA"] == []


class TestReplayClockIntegrationWithEngine:
    """Verify _now_et() is honoured in trade_engine signal buffering logic."""

    def teardown_method(self, _):
        clear_replay_clock()

    def test_on_signal_buffers_when_clock_is_before_deadline(self):
        from alpha_tech_tracker.op_momentum_strategy.models import SignalEvent
        from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine
        from conftest import _D, _make_alpaca_client

        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)
        engine._monitor = MagicMock()
        engine._signal_engine = MagicMock()

        deadline = _et(9, 47)
        engine._window_state["W1"]["collection_deadline"] = deadline

        # Set clock to before deadline — signal should be buffered
        set_replay_clock(lambda: _et(9, 40))

        event = SignalEvent(
            ticker="NVDA", signal="BULLISH",
            entry_price=_D("105"), stock_price=_D("105"),
            or_high=_D("107"), or_low=_D("97"), or_range=_D("10"),
            ma50_at_signal=_D("100"),
        )
        engine._on_signal_for_window("W1", event)

        assert "NVDA" in engine._window_state["W1"]["pending_signals"]

    def test_on_signal_enters_directly_when_clock_is_past_deadline(self):
        from alpha_tech_tracker.op_momentum_strategy.models import SignalEvent
        from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine
        from conftest import _D, _make_alpaca_client

        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(alpaca_client=client, mock_trade_execution=True)
        engine._monitor = MagicMock()
        engine._signal_engine = MagicMock()
        engine._signal_engine.get_latest_bar.return_value = None
        engine._enter_position = MagicMock()

        deadline = _et(9, 47)
        engine._window_state["W1"]["collection_deadline"] = deadline

        # Set clock past deadline — signal should go direct to _enter_position
        set_replay_clock(lambda: _et(9, 55))

        event = SignalEvent(
            ticker="NVDA", signal="BULLISH",
            entry_price=_D("105"), stock_price=_D("105"),
            or_high=_D("107"), or_low=_D("97"), or_range=_D("10"),
            ma50_at_signal=_D("100"),
        )
        engine._on_signal_for_window("W1", event)

        engine._enter_position.assert_called_once()
        assert "NVDA" not in engine._window_state["W1"]["pending_signals"]
