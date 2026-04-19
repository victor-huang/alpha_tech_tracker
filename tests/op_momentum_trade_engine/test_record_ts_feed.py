from datetime import datetime
from unittest.mock import MagicMock, patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.record_ts_feed import TsBarRecorder
from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar

ET = pytz.timezone("America/New_York")


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
        recorder._backfill_session = MagicMock()

        recorder.start()

        recorder._stream_1min.subscribe_bars.assert_called_once_with(
            recorder._on_1min_bar, "TSLA", "META"
        )
        recorder._stream_5min.subscribe_bars.assert_called_once_with(
            recorder._on_5min_bar, "TSLA", "META"
        )
        recorder._stream_1min.start_async.assert_called_once()
        recorder._stream_5min.start_async.assert_called_once()

    def test_start_calls_backfill_before_stream_subscription(self):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, ["TSLA"])
        recorder._stream_1min = MagicMock()
        recorder._stream_5min = MagicMock()
        call_order = []
        recorder._backfill_session = MagicMock(side_effect=lambda: call_order.append("backfill"))
        recorder._stream_1min.subscribe_bars.side_effect = lambda *a: call_order.append("subscribe_1min")

        recorder.start()

        assert call_order[0] == "backfill"
        assert "subscribe_1min" in call_order
        assert call_order.index("backfill") < call_order.index("subscribe_1min")


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


class TestBackfillSession:
    def _make_recorder(self, tickers=None):
        client = _make_ts_client()
        recorder = TsBarRecorder(client, tickers or ["TSLA"])
        recorder._bar_recorder = MagicMock()
        return recorder

    def _market_time(self, hour, minute):
        """Return an ET-aware datetime for today at the given hour:minute."""
        now_et = datetime.now(ET)
        return ET.localize(
            datetime(now_et.year, now_et.month, now_et.day, hour, minute)
        )

    def test_skips_when_called_before_market_open(self):
        recorder = self._make_recorder()
        before_open = self._market_time(9, 0)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = before_open
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        recorder._ts_client.get_historical_bars.assert_not_called()

    def test_skips_when_called_exactly_at_market_open(self):
        recorder = self._make_recorder()
        at_open = self._market_time(9, 30)

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = at_open
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        recorder._ts_client.get_historical_bars.assert_not_called()

    def test_fetches_1min_and_5min_bars_for_each_ticker(self):
        recorder = self._make_recorder(tickers=["TSLA", "META"])
        during_session = self._market_time(10, 30)
        recorder._ts_client.get_historical_bars.return_value = []

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = during_session
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        assert recorder._ts_client.get_historical_bars.call_count == 4  # 2 tickers × 2 intervals

    def test_fetches_both_intervals_per_ticker(self):
        recorder = self._make_recorder(tickers=["TSLA"])
        during_session = self._market_time(10, 30)
        recorder._ts_client.get_historical_bars.return_value = []

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = during_session
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        calls = recorder._ts_client.get_historical_bars.call_args_list
        intervals_used = {c[1]["interval"] if c[1] else c[0][3] for c in calls}
        assert 1 in intervals_used
        assert 5 in intervals_used

    def test_writes_returned_bars_to_1min_recorder(self):
        recorder = self._make_recorder(tickers=["TSLA"])
        during_session = self._market_time(10, 0)
        bar1 = _make_bar(ts="2026-04-16T13:35:00Z")
        bar2 = _make_bar(ts="2026-04-16T13:40:00Z")

        def get_historical_bars(ticker, start, end, interval):
            if interval == 1:
                return [bar1, bar2]
            return []

        recorder._ts_client.get_historical_bars.side_effect = get_historical_bars

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = during_session
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        assert recorder._bar_recorder.record_1min.call_count == 2

    def test_writes_returned_bars_to_5min_recorder(self):
        recorder = self._make_recorder(tickers=["TSLA"])
        during_session = self._market_time(10, 0)
        bar = _make_bar(ts="2026-04-16T13:35:00Z")

        def get_historical_bars(ticker, start, end, interval):
            if interval == 5:
                return [bar]
            return []

        recorder._ts_client.get_historical_bars.side_effect = get_historical_bars

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = during_session
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        recorder._bar_recorder.record_5min.assert_called_once()

    def test_continues_other_tickers_when_one_fetch_fails(self):
        recorder = self._make_recorder(tickers=["TSLA", "META"])
        during_session = self._market_time(10, 0)

        def get_historical_bars(ticker, start, end, interval):
            if ticker == "TSLA":
                raise RuntimeError("network error")
            return []

        recorder._ts_client.get_historical_bars.side_effect = get_historical_bars

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.record_ts_feed.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = during_session
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            recorder._backfill_session()

        meta_calls = [
            c for c in recorder._ts_client.get_historical_bars.call_args_list
            if c[0][0] == "META"
        ]
        assert len(meta_calls) == 2  # 1min + 5min for META still attempted

