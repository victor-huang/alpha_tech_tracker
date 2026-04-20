import csv
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _FiveMinBar
from alpha_tech_tracker.op_momentum_strategy.replay import (
    BarReplayDriver,
    CsvLiveBarsSource,
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

    def test_build_timeline_default_exit_includes_1555_bar(self):
        bars = {
            "NVDA": [
                _bar("NVDA", 15, 50),
                _bar("NVDA", 15, 55),  # default exit_time — now included (fix: <= cutoff)
                _bar("NVDA", 16, 0),   # after market close — still excluded
            ],
        }
        driver = BarReplayDriver(tickers=["NVDA"], replay_date=date(2026, 3, 17), signal_engine=MagicMock())
        timeline = driver._build_timeline(bars)
        assert len(timeline) == 2

    def test_build_timeline_full_day_exit_time_includes_afternoon_bars(self):
        bars = {
            "NVDA": [
                _bar("NVDA", 14, 55),
                _bar("NVDA", 15, 0),
                _bar("NVDA", 15, 50),
                _bar("NVDA", 15, 55),  # EOD_EXIT_TIME — now included (fix: <= cutoff)
            ],
        }
        driver = BarReplayDriver(
            tickers=["NVDA"],
            replay_date=date(2026, 3, 17),
            signal_engine=MagicMock(),
            exit_time="15:55",
        )
        timeline = driver._build_timeline(bars)
        assert len(timeline) == 4
        assert timeline[-1].timestamp.minute == 55

    def test_build_timeline_excludes_bar_strictly_after_exit_time(self):
        bars = {
            "NVDA": [
                _bar("NVDA", 15, 55),
                _bar("NVDA", 16, 0),   # strictly after exit_time="15:55" — excluded
            ],
        }
        driver = BarReplayDriver(
            tickers=["NVDA"],
            replay_date=date(2026, 3, 17),
            signal_engine=MagicMock(),
            exit_time="15:55",
        )
        timeline = driver._build_timeline(bars)
        assert len(timeline) == 1
        assert timeline[0].timestamp.hour == 15
        assert timeline[0].timestamp.minute == 55

    def test_build_timeline_full_day_1605_includes_1555_bar(self):
        bars = {
            "NVDA": [
                _bar("NVDA", 15, 50),
                _bar("NVDA", 15, 55),  # included when exit_time="16:05"
            ],
        }
        driver = BarReplayDriver(
            tickers=["NVDA"],
            replay_date=date(2026, 3, 17),
            signal_engine=MagicMock(),
            exit_time="16:05",
        )
        timeline = driver._build_timeline(bars)
        assert len(timeline) == 2
        assert timeline[-1].timestamp.hour == 15
        assert timeline[-1].timestamp.minute == 55


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

    def test_run_sets_last_bar_time_to_eod_bar_when_full_day(self):
        b_eod = _bar("NVDA", 15, 55)

        signal_engine = MagicMock()
        driver = BarReplayDriver(
            tickers=["NVDA"],
            replay_date=date(2026, 3, 17),
            signal_engine=signal_engine,
            exit_time="16:05",
        )
        with patch.object(driver, "_fetch_session_bars", return_value={"NVDA": [b_eod]}):
            driver.run()

        assert driver.last_bar_time == b_eod.timestamp


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

    def test_fetch_session_bars_uses_cached_fetch_bars_when_market_data_client_set(self):
        replay_date = date(2026, 3, 5)
        market_data_client = MagicMock()
        driver = BarReplayDriver(
            tickers=["APP", "CRDO"],
            replay_date=replay_date,
            signal_engine=MagicMock(),
            market_data_client=market_data_client,
        )
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.replay.fetch_bars",
            return_value={"APP": pd.DataFrame(), "CRDO": pd.DataFrame()},
        ) as mock_fetch:
            driver._fetch_session_bars()

        mock_fetch.assert_called_once_with(
            ["APP", "CRDO"],
            replay_date,
            replay_date,
            source="tradestation",
            market_data_client=market_data_client,
        )

    def test_fetch_session_bars_does_not_call_client_fetch_bars_directly(self):
        replay_date = date(2026, 3, 5)
        market_data_client = MagicMock()
        driver = BarReplayDriver(
            tickers=["APP"],
            replay_date=replay_date,
            signal_engine=MagicMock(),
            market_data_client=market_data_client,
        )
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.replay.fetch_bars",
            return_value={"APP": pd.DataFrame()},
        ):
            driver._fetch_session_bars()

        market_data_client.fetch_bars.assert_not_called()

    def test_fetch_session_bars_passes_replay_date_as_both_start_and_end(self):
        replay_date = date(2026, 4, 8)
        market_data_client = MagicMock()
        driver = BarReplayDriver(
            tickers=["FN"],
            replay_date=replay_date,
            signal_engine=MagicMock(),
            market_data_client=market_data_client,
        )
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.replay.fetch_bars",
            return_value={"FN": pd.DataFrame()},
        ) as mock_fetch:
            driver._fetch_session_bars()

        _, args, kwargs = mock_fetch.mock_calls[0]
        assert args[1] == replay_date
        assert args[2] == replay_date


def _write_5min_csv(path: Path, rows: list):
    """Write a BarRecorder-format 5-min CSV to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for row in rows:
            writer.writerow(row)


class TestCsvLiveBarsSourceTsFeed:
    """Verify CsvLiveBarsSource reads TradeStation-recorded CSVs correctly."""

    def test_loads_5min_bars_from_tradestation_csv(self, tmp_path):
        session = date(2026, 4, 16)
        csv_path = tmp_path / "2026-04-16" / "tradestation_TSLA_5min.csv"
        _write_5min_csv(csv_path, [
            ["2026-04-16 09:30:00", 100.0, 101.0, 99.0, 100.5, 500],
            ["2026-04-16 09:35:00", 100.5, 102.0, 100.0, 101.5, 600],
        ])

        source = CsvLiveBarsSource(str(tmp_path), feed="tradestation")
        result = source.load(["TSLA"], session)

        assert len(result["TSLA"]) == 2
        assert all(isinstance(b, _FiveMinBar) for b in result["TSLA"])

    def test_bar_fields_parsed_correctly(self, tmp_path):
        session = date(2026, 4, 16)
        csv_path = tmp_path / "2026-04-16" / "tradestation_TSLA_5min.csv"
        _write_5min_csv(csv_path, [
            ["2026-04-16 09:30:00", 366.75, 366.84, 362.5, 364.37, 974501],
        ])

        source = CsvLiveBarsSource(str(tmp_path), feed="tradestation")
        bar = source.load(["TSLA"], session)["TSLA"][0]

        assert bar.symbol == "TSLA"
        assert bar.open == 366.75
        assert bar.high == 366.84
        assert bar.low == 362.5
        assert bar.close == 364.37
        assert bar.volume == 974501.0

    def test_timestamp_localized_to_et(self, tmp_path):
        session = date(2026, 4, 16)
        csv_path = tmp_path / "2026-04-16" / "tradestation_TSLA_5min.csv"
        _write_5min_csv(csv_path, [
            ["2026-04-16 09:30:00", 100.0, 101.0, 99.0, 100.5, 500],
        ])

        source = CsvLiveBarsSource(str(tmp_path), feed="tradestation")
        bar = source.load(["TSLA"], session)["TSLA"][0]

        assert bar.timestamp.tzinfo is not None
        assert bar.timestamp == ET.localize(datetime(2026, 4, 16, 9, 30, 0))

    def test_multiple_tickers_loaded_independently(self, tmp_path):
        session = date(2026, 4, 16)
        for ticker in ["TSLA", "META"]:
            csv_path = tmp_path / "2026-04-16" / f"tradestation_{ticker}_5min.csv"
            _write_5min_csv(csv_path, [
                [f"2026-04-16 09:30:00", 100.0, 101.0, 99.0, 100.5, 500],
                [f"2026-04-16 09:35:00", 100.5, 102.0, 100.0, 101.5, 600],
            ])

        source = CsvLiveBarsSource(str(tmp_path), feed="tradestation")
        result = source.load(["TSLA", "META"], session)

        assert len(result["TSLA"]) == 2
        assert len(result["META"]) == 2

    def test_missing_csv_returns_empty_list(self, tmp_path):
        session = date(2026, 4, 16)
        source = CsvLiveBarsSource(str(tmp_path), feed="tradestation")
        result = source.load(["TSLA"], session)

        assert result["TSLA"] == []

    def test_bars_fed_into_replay_driver_in_order(self, tmp_path):
        session = date(2026, 4, 16)
        csv_path = tmp_path / "2026-04-16" / "tradestation_TSLA_5min.csv"
        _write_5min_csv(csv_path, [
            ["2026-04-16 09:40:00", 101.0, 102.0, 100.5, 101.5, 400],
            ["2026-04-16 09:30:00", 100.0, 101.0, 99.0, 100.5, 500],
            ["2026-04-16 09:35:00", 100.5, 102.0, 100.0, 101.5, 600],
        ])

        source = CsvLiveBarsSource(str(tmp_path), feed="tradestation")
        injected = []
        signal_engine = MagicMock()
        signal_engine._process_five_min_bar.side_effect = injected.append

        driver = BarReplayDriver(
            tickers=["TSLA"],
            replay_date=session,
            signal_engine=signal_engine,
            bars_source=source,
            exit_time="16:05",
        )
        driver.run()

        timestamps = [b.timestamp for b in injected]
        assert timestamps == sorted(timestamps)
        assert len(injected) == 3

    def test_iex_and_tradestation_files_coexist_without_interference(self, tmp_path):
        session = date(2026, 4, 16)
        for feed in ["iex", "tradestation"]:
            csv_path = tmp_path / "2026-04-16" / f"{feed}_TSLA_5min.csv"
            _write_5min_csv(csv_path, [
                ["2026-04-16 09:30:00", 100.0, 101.0, 99.0, 100.5, 500],
            ])

        iex_bars = CsvLiveBarsSource(str(tmp_path), feed="iex").load(["TSLA"], session)
        ts_bars = CsvLiveBarsSource(str(tmp_path), feed="tradestation").load(["TSLA"], session)

        assert len(iex_bars["TSLA"]) == 1
        assert len(ts_bars["TSLA"]) == 1


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
