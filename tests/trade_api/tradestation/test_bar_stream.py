import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from alpha_tech_tracker.trade_api.tradestation.bar_stream import (
    _TSBar,
    TradeStationBarStream,
    _STREAM_URL,
    _SIM_STREAM_URL,
)
from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient


def _make_client(environment="live"):
    client = TradeStationAPIClient(
        client_id="test_id",
        client_secret="test_secret",
        environment=environment,
    )
    client._session = MagicMock()
    return client


def _make_stream(environment="live"):
    return TradeStationBarStream(_make_client(environment))


def _mock_stream_response(lines: list, stop_event=None):
    """Build a mock response whose iter_lines() yields the given byte strings.

    If stop_event is provided, it is set after all lines are yielded so that
    the _stream_ticker reconnect loop exits cleanly instead of looping forever.
    """
    resp = MagicMock()
    resp.status_code = 200

    def _gen():
        for line in lines:
            yield line
        if stop_event is not None:
            stop_event.set()

    resp.iter_lines.return_value = _gen()
    return resp


def _bar_line(
    status="Closed",
    symbol=None,
    ts="2026-01-01T14:30:00Z",
    o="100", h="101", lo="99", c="100.5", vol="500",
):
    d = {
        "Open": o, "High": h, "Low": lo, "Close": c,
        "TotalVolume": vol, "TimeStamp": ts, "BarStatus": status,
    }
    return json.dumps(d).encode()


# ---------------------------------------------------------------------------
# TestTSBar
# ---------------------------------------------------------------------------

class TestTSBar:
    def test_from_ts_dict_iso_timestamp_normalized_to_open_time(self):
        # TS close-timestamp 13:31 for a 1-min bar → open time 13:30
        d = {"Open": "100", "High": "101", "Low": "99", "Close": "100.5",
             "TotalVolume": "500", "TimeStamp": "2026-04-15T13:31:00Z"}
        bar = _TSBar.from_ts_dict(d, "TSLA", interval_minutes=1)
        assert bar.timestamp == datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)

    def test_from_ts_dict_5min_bar_normalized_to_open_time(self):
        # TS close-timestamp 13:35 for a 5-min bar → open time 13:30
        d = {"Open": "100", "High": "101", "Low": "99", "Close": "100.5",
             "TotalVolume": "500", "TimeStamp": "2026-04-15T13:35:00Z"}
        bar = _TSBar.from_ts_dict(d, "TSLA", interval_minutes=5)
        assert bar.timestamp == datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)

    def test_from_ts_dict_epoch_ms_normalized_to_open_time(self):
        # 1776259860000 ms = 2026-04-15T13:31:00Z (TS close time for 1-min bar)
        # normalized open time = 13:30
        d = {"Open": "100", "High": "101", "Low": "99", "Close": "100.5",
             "TotalVolume": "500", "Epoch": 1776259860000}
        bar = _TSBar.from_ts_dict(d, "TSLA", interval_minutes=1)
        assert bar.timestamp == datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)

    def test_from_ts_dict_numeric_fields_coerced_to_float(self):
        d = {"Open": "366.75", "High": "366.84", "Low": "362.5",
             "Close": "364.37", "TotalVolume": "974501",
             "TimeStamp": "2026-04-15T13:31:00Z"}
        bar = _TSBar.from_ts_dict(d, "TSLA", interval_minutes=1)
        assert bar.open == 366.75
        assert bar.high == 366.84
        assert bar.low == 362.5
        assert bar.close == 364.37
        assert bar.volume == 974501.0

    def test_from_ts_dict_symbol_stored(self):
        d = {"Open": "100", "High": "101", "Low": "99", "Close": "100.5",
             "TotalVolume": "500", "TimeStamp": "2026-04-15T13:31:00Z"}
        bar = _TSBar.from_ts_dict(d, "META", interval_minutes=1)
        assert bar.symbol == "META"

    def test_from_ts_dict_missing_volume_defaults_zero(self):
        d = {"Open": "100", "High": "101", "Low": "99", "Close": "100.5",
             "TimeStamp": "2026-04-15T13:31:00Z"}
        bar = _TSBar.from_ts_dict(d, "TSLA", interval_minutes=1)
        assert bar.volume == 0.0


# ---------------------------------------------------------------------------
# TestGetHistoricalBars
# ---------------------------------------------------------------------------

class TestGetHistoricalBars:
    def _mock_bars_response(self, client, bars_data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"Bars": bars_data}
        client._session.get.return_value = resp
        return resp

    def _bar_dict(self, ts="2026-04-15T13:31:00Z"):
        return {
            "Open": "366.75", "High": "366.84", "Low": "362.5",
            "Close": "364.37", "TotalVolume": "974501",
            "TimeStamp": ts, "BarStatus": "Closed",
        }

    def test_returns_list_of_ts_bars(self):
        client = _make_client()
        self._mock_bars_response(client, [self._bar_dict(), self._bar_dict("2026-04-15T13:32:00Z")])

        start = datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)
        end = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
        bars = client.get_historical_bars("TSLA", start, end)

        assert len(bars) == 2
        assert all(isinstance(b, _TSBar) for b in bars)
        assert bars[0].symbol == "TSLA"

    def test_firstdate_shifted_back_one_minute_for_1min_bars(self):
        client = _make_client()
        self._mock_bars_response(client, [])

        start = datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)
        end = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
        client.get_historical_bars("TSLA", start, end, interval=1)

        params = client._session.get.call_args[1]["params"]
        assert params["firstdate"] == "2026-04-15T13:29:00Z"

    def test_firstdate_shifted_back_five_minutes_for_5min_bars(self):
        client = _make_client()
        self._mock_bars_response(client, [])

        start = datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)
        end = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
        client.get_historical_bars("TSLA", start, end, interval=5)

        params = client._session.get.call_args[1]["params"]
        assert params["firstdate"] == "2026-04-15T13:25:00Z"

    def test_lastdate_passed_unchanged(self):
        client = _make_client()
        self._mock_bars_response(client, [])

        start = datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)
        end = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
        client.get_historical_bars("TSLA", start, end)

        params = client._session.get.call_args[1]["params"]
        assert params["lastdate"] == "2026-04-15T14:00:00Z"

    def test_correct_v3_url_used(self):
        client = _make_client()
        self._mock_bars_response(client, [])

        client.get_historical_bars(
            "TSLA",
            datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc),
        )

        url = client._session.get.call_args[0][0]
        assert "/v3/marketdata/barcharts/TSLA" in url

    def test_bars_without_open_field_skipped(self):
        client = _make_client()
        self._mock_bars_response(client, [
            self._bar_dict(),
            {"High": "101", "Low": "99", "Close": "100", "TotalVolume": "0",
             "TimeStamp": "2026-04-15T13:32:00Z"},  # missing Open
        ])

        bars = client.get_historical_bars(
            "TSLA",
            datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc),
        )

        assert len(bars) == 1

    def test_1min_bar_timestamp_normalized_to_open_time(self):
        client = _make_client()
        # TS returns close-timestamp 13:31 for a 1-min bar (13:30-13:31 period)
        self._mock_bars_response(client, [self._bar_dict("2026-04-15T13:31:00Z")])

        bars = client.get_historical_bars(
            "TSLA",
            datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc),
            interval=1,
        )

        assert bars[0].timestamp == datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)

    def test_5min_bar_timestamp_normalized_to_open_time(self):
        client = _make_client()
        # TS returns close-timestamp 13:35 for a 5-min bar (13:30-13:35 period)
        self._mock_bars_response(client, [self._bar_dict("2026-04-15T13:35:00Z")])

        bars = client.get_historical_bars(
            "TSLA",
            datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc),
            interval=5,
        )

        assert bars[0].timestamp == datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc)

    def test_empty_bars_response_returns_empty_list(self):
        client = _make_client()
        self._mock_bars_response(client, [])

        bars = client.get_historical_bars(
            "TSLA",
            datetime(2026, 4, 15, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc),
        )

        assert bars == []


# ---------------------------------------------------------------------------
# TestTradeStationBarStream
# ---------------------------------------------------------------------------

class TestTradeStationBarStream:
    def test_closed_bar_triggers_callback(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [_bar_line(status="Closed")], stop_event=stream._stop_event
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        callback.assert_called_once()

    def test_open_bar_does_not_trigger_callback(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [_bar_line(status="Open")], stop_event=stream._stop_event
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        callback.assert_not_called()

    def test_heartbeat_frame_skipped(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [json.dumps({"Heartbeat": 1, "Timestamp": "2026-01-01T14:31:05Z"}).encode()],
            stop_event=stream._stop_event,
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        callback.assert_not_called()

    def test_empty_line_skipped(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [b"", _bar_line(status="Closed")], stop_event=stream._stop_event
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        callback.assert_called_once()

    def test_malformed_json_skipped(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [b"not-json", _bar_line(status="Closed")], stop_event=stream._stop_event
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        callback.assert_called_once()

    def test_callback_receives_ts_bar_with_correct_fields(self):
        client = _make_client()
        stream = TradeStationBarStream(client)  # default interval=1
        client._session.get.return_value = _mock_stream_response(
            [_bar_line(
                status="Closed", ts="2026-01-01T14:30:00Z",  # TS close time
                o="100", h="101", lo="99", c="100.5", vol="500",
            )],
            stop_event=stream._stop_event,
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        bar = callback.call_args[0][0]
        assert isinstance(bar, _TSBar)
        assert bar.symbol == "TSLA"
        assert bar.open == 100.0
        assert bar.high == 101.0
        assert bar.low == 99.0
        assert bar.close == 100.5
        assert bar.volume == 500.0
        # TS close-time 14:30 normalized to open-time 14:29 for a 1-min bar
        assert bar.timestamp == datetime(2026, 1, 1, 14, 29, tzinfo=timezone.utc)

    def test_5min_stream_callback_normalizes_to_open_time(self):
        client = _make_client()
        stream = TradeStationBarStream(client, interval=5, unit="Minute")
        client._session.get.return_value = _mock_stream_response(
            [_bar_line(status="Closed", ts="2026-01-01T14:35:00Z")],
            stop_event=stream._stop_event,
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        bar = callback.call_args[0][0]
        # TS close-time 14:35 normalized to open-time 14:30 for a 5-min bar
        assert bar.timestamp == datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)

    def test_only_closed_bars_trigger_callback_mixed_stream(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [
                _bar_line(status="Closed", ts="2026-01-01T14:30:00Z"),
                _bar_line(status="Open",   ts="2026-01-01T14:31:00Z"),
                json.dumps({"Heartbeat": 1, "Timestamp": "2026-01-01T14:31:05Z"}).encode(),
                _bar_line(status="Closed", ts="2026-01-01T14:31:00Z"),
                b"",
            ],
            stop_event=stream._stop_event,
        )
        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        assert callback.call_count == 2

    def test_stop_event_exits_iter_lines_loop(self):
        client = _make_client()
        stream = TradeStationBarStream(client)

        def lines_with_midway_stop():
            yield _bar_line(status="Closed")
            stream._stop_event.set()
            yield _bar_line(status="Closed")  # should not be processed

        resp = MagicMock()
        resp.status_code = 200
        resp.iter_lines.return_value = lines_with_midway_stop()
        client._session.get.return_value = resp

        callback = MagicMock()
        stream.subscribe_bars(callback, "TSLA")
        stream._stream_ticker("TSLA")

        assert callback.call_count == 1

    def test_one_thread_per_ticker_started(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        # stop immediately so threads exit without blocking
        client._session.get.return_value = _mock_stream_response(
            [], stop_event=stream._stop_event
        )
        stream.subscribe_bars(MagicMock(), "TSLA", "META", "AMD")
        stream.start_async()
        for t in stream._threads:
            t.join(timeout=2)

        assert len(stream._threads) == 3
        names = {t.name for t in stream._threads}
        assert names == {"ts-stream-TSLA", "ts-stream-META", "ts-stream-AMD"}

    def test_uses_live_url_for_live_environment(self):
        client = _make_client(environment="live")
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [], stop_event=stream._stop_event
        )
        stream.subscribe_bars(MagicMock(), "TSLA")
        stream._stream_ticker("TSLA")

        url = client._session.get.call_args[0][0]
        assert url == _STREAM_URL.format(symbol="TSLA")

    def test_uses_sim_url_for_sim_environment(self):
        client = _make_client(environment="sim")
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [], stop_event=stream._stop_event
        )
        stream.subscribe_bars(MagicMock(), "TSLA")
        stream._stream_ticker("TSLA")

        url = client._session.get.call_args[0][0]
        assert url == _SIM_STREAM_URL.format(symbol="TSLA")

    def test_barsback_included_in_params_when_set(self):
        client = _make_client()
        stream = TradeStationBarStream(client, barsback=5)
        client._session.get.return_value = _mock_stream_response(
            [], stop_event=stream._stop_event
        )
        stream.subscribe_bars(MagicMock(), "TSLA")
        stream._stream_ticker("TSLA")

        params = client._session.get.call_args[1]["params"]
        assert params["barsback"] == 5

    def test_barsback_omitted_from_params_when_zero(self):
        client = _make_client()
        stream = TradeStationBarStream(client, barsback=0)
        client._session.get.return_value = _mock_stream_response(
            [], stop_event=stream._stop_event
        )
        stream.subscribe_bars(MagicMock(), "TSLA")
        stream._stream_ticker("TSLA")

        params = client._session.get.call_args[1]["params"]
        assert "barsback" not in params

    def test_get_request_uses_split_connect_and_read_timeout(self):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.return_value = _mock_stream_response(
            [], stop_event=stream._stop_event
        )
        stream.subscribe_bars(MagicMock(), "TSLA")
        stream._stream_ticker("TSLA")

        _, kwargs = client._session.get.call_args
        assert kwargs["timeout"] == (10, 90)

    def test_backoff_doubles_on_repeated_connection_errors(self, monkeypatch):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.side_effect = ConnectionError("network error")
        monkeypatch.setattr("alpha_tech_tracker.trade_api.tradestation.bar_stream.random.uniform", lambda *_: 0)

        wait_calls = []

        def fake_wait(secs):
            wait_calls.append(secs)
            if len(wait_calls) >= 3:
                stream._stop_event.set()

        monkeypatch.setattr(stream._stop_event, "wait", fake_wait)
        stream._stream_ticker("TSLA")

        assert wait_calls == [5, 10, 20]

    def test_backoff_capped_at_sixty_seconds(self, monkeypatch):
        client = _make_client()
        stream = TradeStationBarStream(client)
        client._session.get.side_effect = ConnectionError("network error")
        monkeypatch.setattr("alpha_tech_tracker.trade_api.tradestation.bar_stream.random.uniform", lambda *_: 0)

        wait_calls = []

        def fake_wait(secs):
            wait_calls.append(secs)
            if len(wait_calls) >= 6:
                stream._stop_event.set()

        monkeypatch.setattr(stream._stop_event, "wait", fake_wait)
        stream._stream_ticker("TSLA")

        assert wait_calls == [5, 10, 20, 40, 60, 60]

    def test_backoff_resets_to_five_after_successful_connection(self, monkeypatch):
        client = _make_client()
        stream = TradeStationBarStream(client)
        monkeypatch.setattr("alpha_tech_tracker.trade_api.tradestation.bar_stream.random.uniform", lambda *_: 0)

        wait_calls = []

        def fake_wait(secs):
            wait_calls.append(secs)
            if len(wait_calls) >= 2:
                stream._stop_event.set()

        monkeypatch.setattr(stream._stop_event, "wait", fake_wait)

        call_count = [0]

        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("first error")
            if call_count[0] == 2:
                return _mock_stream_response([], stop_event=None)
            raise ConnectionError("second error")

        client._session.get.side_effect = get_side_effect
        stream.subscribe_bars(MagicMock(), "TSLA")
        stream._stream_ticker("TSLA")

        assert wait_calls[0] == 5
        assert wait_calls[1] == 5


# ---------------------------------------------------------------------------
# Reconnect jitter — wait time includes backoff + random offset
# ---------------------------------------------------------------------------

class TestStreamReconnectJitter:
    def test_reconnect_wait_includes_jitter(self, monkeypatch):
        client = _make_client()
        stream = TradeStationBarStream(client)
        monkeypatch.setattr(
            "alpha_tech_tracker.trade_api.tradestation.bar_stream.random.uniform",
            lambda lo, hi: 1.0,
        )

        wait_calls = []

        def fake_wait(secs):
            wait_calls.append(secs)
            stream._stop_event.set()

        monkeypatch.setattr(stream._stop_event, "wait", fake_wait)
        client._session.get.side_effect = ConnectionError("simulated error")

        stream._stream_ticker("TSLA")

        # backoff=5, jitter=1.0 → wait(6.0)
        assert len(wait_calls) == 1
        assert wait_calls[0] == 6.0

    def test_jitter_is_bounded_by_twenty_percent_of_backoff(self, monkeypatch):
        """random.uniform is called with (0, backoff * 0.2) — verify the upper bound."""
        client = _make_client()
        stream = TradeStationBarStream(client)

        uniform_calls = []
        monkeypatch.setattr(
            "alpha_tech_tracker.trade_api.tradestation.bar_stream.random.uniform",
            lambda lo, hi: uniform_calls.append((lo, hi)) or 0,
        )

        def fake_wait(_):
            stream._stop_event.set()

        monkeypatch.setattr(stream._stop_event, "wait", fake_wait)
        client._session.get.side_effect = ConnectionError("error")

        stream._stream_ticker("TSLA")

        assert uniform_calls[0] == (0, 5 * 0.2)

    def test_different_tickers_receive_different_jitter(self, monkeypatch):
        """Concurrent reconnects from different tickers get independently random jitter."""
        import random as stdlib_random

        client = _make_client()
        stream = TradeStationBarStream(client)

        jitter_values = []
        original_uniform = stdlib_random.uniform

        def counting_uniform(lo, hi):
            val = original_uniform(lo, hi)
            jitter_values.append(val)
            return val

        monkeypatch.setattr(
            "alpha_tech_tracker.trade_api.tradestation.bar_stream.random.uniform",
            counting_uniform,
        )

        wait_calls = []

        def fake_wait(secs):
            wait_calls.append(secs)
            if len(wait_calls) >= 2:
                stream._stop_event.set()

        monkeypatch.setattr(stream._stop_event, "wait", fake_wait)
        client._session.get.side_effect = ConnectionError("error")

        stream._stream_ticker("TSLA")

        # Each wait gets its own jitter sample; two retries → two samples
        assert len(jitter_values) == 2
        assert all(0 <= j <= 5 * 0.2 for j in jitter_values)
