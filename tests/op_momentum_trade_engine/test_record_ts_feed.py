from datetime import datetime
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.op_momentum_strategy.record_ts_feed import TsBarRecorder
from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar


def _make_ts_client():
    client = MagicMock()
    client._session = MagicMock()
    client._environment = "live"
    return client


def _make_bar(symbol="TSLA", ts="2026-04-16T14:30:00Z"):
    return _TSBar(
        symbol=symbol,
        timestamp=datetime.fromisoformat(ts.replace("Z", "+00:00")),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=500.0,
    )


class TestTsBarRecorderInit:
    def test_creates_two_stream_instances(self):
        client = _make_ts_client()
        with patch("alpha_tech_tracker.op_momentum_strategy.record_ts_feed.TradeStationBarStream") as MockStream:
            MockStream.return_value = MagicMock()
            TsBarRecorder(client, ["TSLA", "META"])

        assert MockStream.call_count == 2
        calls = MockStream.call_args_list
        intervals = {c[1]["interval"] for c in calls}
        assert intervals == {1, 5}

    def test_bar_recorder_feed_is_tradestation(self):
        client = _make_ts_client()
        with patch("alpha_tech_tracker.op_momentum_strategy.record_ts_feed.BarRecorder") as MockBarRecorder:
            MockBarRecorder.return_value = MagicMock()
            TsBarRecorder(client, ["TSLA"])

        MockBarRecorder.assert_called_once_with(feed="tradestation")


class TestTsBarRecorderStart:
    def test_start_subscribes_and_starts_both_streams(self):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, ["TSLA", "META"])
        recorder._stream_1min = MagicMock()
        recorder._stream_5min = MagicMock()

        recorder.start()

        recorder._stream_1min.subscribe_bars.assert_called_once_with(
            recorder._on_1min_bar, "TSLA", "META"
        )
        recorder._stream_5min.subscribe_bars.assert_called_once_with(
            recorder._on_5min_bar, "TSLA", "META"
        )
        recorder._stream_1min.start_async.assert_called_once()
        recorder._stream_5min.start_async.assert_called_once()


class TestTsBarRecorderStop:
    def test_stop_stops_both_streams_and_closes_recorder(self):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, ["TSLA"])
        recorder._stream_1min = MagicMock()
        recorder._stream_5min = MagicMock()
        recorder._bar_recorder = MagicMock()

        recorder.stop()

        recorder._stream_1min.stop.assert_called_once()
        recorder._stream_5min.stop.assert_called_once()
        recorder._bar_recorder.close.assert_called_once()


class TestTsBarRecorderCallbacks:
    def test_on_1min_bar_calls_record_1min_with_bar_date(self):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, ["TSLA"])
        recorder._bar_recorder = MagicMock()
        bar = _make_bar(ts="2026-04-16T14:30:00Z")

        recorder._on_1min_bar(bar)

        from datetime import date
        recorder._bar_recorder.record_1min.assert_called_once_with(
            "TSLA", bar, date(2026, 4, 16)
        )

    def test_on_5min_bar_calls_record_5min_with_bar_date(self):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, ["TSLA"])
        recorder._bar_recorder = MagicMock()
        bar = _make_bar(symbol="META", ts="2026-04-16T15:00:00Z")

        recorder._on_5min_bar(bar)

        from datetime import date
        recorder._bar_recorder.record_5min.assert_called_once_with(
            "META", bar, date(2026, 4, 16)
        )

    def test_1min_and_5min_callbacks_are_distinct(self):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, ["TSLA"])
        recorder._bar_recorder = MagicMock()
        bar = _make_bar()

        recorder._on_1min_bar(bar)
        recorder._on_5min_bar(bar)

        assert recorder._bar_recorder.record_1min.call_count == 1
        assert recorder._bar_recorder.record_5min.call_count == 1


