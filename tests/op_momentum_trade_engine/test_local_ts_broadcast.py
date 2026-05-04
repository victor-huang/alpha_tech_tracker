import json
import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from alpha_tech_tracker.op_momentum_strategy.bar_broadcaster import BarBroadcaster
from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
    LocalTSBroadcastMarketDataClient,
)
from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar


def _make_ts_client():
    client = MagicMock()
    client._session = MagicMock()
    client._environment = "live"
    return client


def _make_bar(symbol="AMD", close=100.5):
    return _TSBar(
        symbol=symbol,
        timestamp=datetime(2026, 5, 2, 13, 31, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=close,
        volume=1000.0,
    )


@pytest.fixture
def tmp_socket_path():
    path = tempfile.mktemp(dir="/tmp", prefix="ts_bc_test_", suffix=".sock")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
def broadcaster(tmp_socket_path):
    bc = BarBroadcaster(_make_ts_client(), ["AMD", "TSLA"], socket_path=tmp_socket_path)
    thread = threading.Thread(target=bc.start, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield bc
    bc.stop()


class TestRoundTrip:
    def test_bar_reaches_subscriber_callback(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("AMD", close=150.0))
        time.sleep(0.1)

        client.stop()

        assert len(received) == 1
        assert received[0].symbol == "AMD"
        assert received[0].close == 150.0

    def test_all_bar_fields_populated(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("AMD", close=123.45))
        time.sleep(0.1)

        client.stop()

        assert len(received) == 1
        bar = received[0]
        assert bar.open == 100.0
        assert bar.high == 101.0
        assert bar.low == 99.0
        assert bar.close == 123.45
        assert bar.volume == 1000.0
        assert isinstance(bar.timestamp, datetime)

    def test_multiple_bars_all_delivered(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("AMD", close=100.0))
        broadcaster._on_bar(_make_bar("AMD", close=101.0))
        broadcaster._on_bar(_make_bar("AMD", close=102.0))
        time.sleep(0.1)

        client.stop()

        assert len(received) == 3
        assert [b.close for b in received] == [100.0, 101.0, 102.0]


class TestTickerFiltering:
    def test_bar_for_unsubscribed_ticker_not_delivered(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("TSLA", close=200.0))
        time.sleep(0.1)

        client.stop()

        assert received == []

    def test_only_subscribed_ticker_delivered_when_both_broadcast(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("TSLA", close=200.0))
        broadcaster._on_bar(_make_bar("AMD", close=150.0))
        time.sleep(0.1)

        client.stop()

        assert len(received) == 1
        assert received[0].symbol == "AMD"


class TestHeartbeat:
    def test_heartbeat_does_not_fire_callback(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._broadcast(broadcaster._heartbeat_line())
        time.sleep(0.1)

        client.stop()

        assert received == []

    def test_heartbeat_updates_last_message_timestamp(self, broadcaster, tmp_socket_path):
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(lambda b: None, "AMD")
        client.start()
        time.sleep(0.1)

        assert client.seconds_since_last_message() == float("inf")

        broadcaster._broadcast(broadcaster._heartbeat_line())
        time.sleep(0.1)

        client.stop()

        assert client.seconds_since_last_message() < 5.0


class TestMalformedMessages:
    def _send_raw(self, sock_path: str, line: str):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.sendall((line + "\n").encode())
        return s

    def test_malformed_json_skipped_reader_continues(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._broadcast("not-valid-json\n")
        broadcaster._on_bar(_make_bar("AMD", close=99.0))
        time.sleep(0.1)

        client.stop()

        assert len(received) == 1
        assert received[0].close == 99.0

    def test_unknown_message_type_skipped(self, broadcaster, tmp_socket_path):
        received = []
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        broadcaster._broadcast(json.dumps({"type": "unknown", "data": "whatever"}) + "\n")
        broadcaster._on_bar(_make_bar("AMD", close=88.0))
        time.sleep(0.1)

        client.stop()

        assert len(received) == 1
        assert received[0].close == 88.0
