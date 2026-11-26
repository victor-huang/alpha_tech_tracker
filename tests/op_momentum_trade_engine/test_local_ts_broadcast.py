import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Real Unix-domain socket fan-out between a BarBroadcaster and LocalTSBroadcastMarketDataClient. Excluded from the
# default suite (`-m "not integration"`); run with `pytest -m integration` or by passing the file path.
pytestmark = pytest.mark.integration

from alpha_tech_tracker.op_momentum_strategy.bar_broadcaster import BarBroadcaster
from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
    LocalTSBroadcastMarketDataClient,
)
from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar

WAIT_SECONDS = 2.0


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


def _wait_for(condition, timeout=WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


class _IdleStream:
    """Stands in for the TradeStation stream: the tests push bars through the broadcaster themselves."""

    def __init__(self, *args, **kwargs):
        self._stopped = threading.Event()

    def subscribe_bars(self, callback, *tickers):
        pass

    def run(self):
        self._stopped.wait()

    def stop(self):
        self._stopped.set()


@pytest.fixture
def tmp_socket_path():
    path = tempfile.mktemp(dir="/tmp", prefix="ts_bc_test_", suffix=".sock")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
def broadcaster(tmp_socket_path, mocker):
    mocker.patch("alpha_tech_tracker.op_momentum_strategy.bar_broadcaster.TradeStationBarStream", _IdleStream)
    bc = BarBroadcaster(_make_ts_client(), ["AMD", "TSLA"], socket_path=tmp_socket_path)
    thread = threading.Thread(target=bc.start, daemon=True)
    thread.start()
    assert _wait_for(lambda: os.path.exists(tmp_socket_path))
    yield bc
    bc.stop()
    thread.join(timeout=WAIT_SECONDS)


@pytest.fixture
def connect(broadcaster, tmp_socket_path):
    """Start a client subscribed to AMD and wait until the broadcaster has accepted it."""
    clients = []

    def _connect(callback):
        client = LocalTSBroadcastMarketDataClient(MagicMock(), socket_path=tmp_socket_path)
        client.subscribe_bars(callback, "AMD")
        client.start()
        clients.append(client)
        assert _wait_for(lambda: len(broadcaster._clients) == len(clients))
        return client

    yield _connect
    for client in clients:
        client.stop()


class TestRoundTrip:
    def test_bar_reaches_subscriber_callback(self, broadcaster, connect):
        received = []
        connect(received.append)

        broadcaster._on_bar(_make_bar("AMD", close=150.0))

        assert _wait_for(lambda: len(received) == 1)
        assert (received[0].symbol, received[0].close) == ("AMD", 150.0)

    def test_all_bar_fields_populated(self, broadcaster, connect):
        received = []
        connect(received.append)

        broadcaster._on_bar(_make_bar("AMD", close=123.45))

        assert _wait_for(lambda: len(received) == 1)
        bar = received[0]
        assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (100.0, 101.0, 99.0, 123.45, 1000.0)
        assert isinstance(bar.timestamp, datetime)

    def test_multiple_bars_all_delivered(self, broadcaster, connect):
        received = []
        connect(received.append)

        for close in (100.0, 101.0, 102.0):
            broadcaster._on_bar(_make_bar("AMD", close=close))

        assert _wait_for(lambda: len(received) == 3)
        assert [b.close for b in received] == [100.0, 101.0, 102.0]


class TestTickerFiltering:
    def test_bar_for_unsubscribed_ticker_not_delivered(self, broadcaster, connect):
        received = []
        client = connect(received.append)

        broadcaster._on_bar(_make_bar("TSLA", close=200.0))

        assert _wait_for(lambda: client.seconds_since_last_message() < WAIT_SECONDS)
        assert received == []

    def test_only_subscribed_ticker_delivered_when_both_broadcast(self, broadcaster, connect):
        received = []
        connect(received.append)

        broadcaster._on_bar(_make_bar("TSLA", close=200.0))
        broadcaster._on_bar(_make_bar("AMD", close=150.0))

        assert _wait_for(lambda: len(received) == 1)
        assert [b.symbol for b in received] == ["AMD"]


class TestHeartbeat:
    def test_heartbeat_does_not_fire_callback(self, broadcaster, connect):
        received = []
        client = connect(received.append)

        broadcaster._broadcast(broadcaster._heartbeat_line())

        assert _wait_for(lambda: client.seconds_since_last_message() < WAIT_SECONDS)
        assert received == []

    def test_heartbeat_updates_last_message_timestamp(self, broadcaster, connect):
        client = connect(lambda b: None)
        assert client.seconds_since_last_message() == float("inf")

        broadcaster._broadcast(broadcaster._heartbeat_line())

        assert _wait_for(lambda: client.seconds_since_last_message() < 5.0)


class TestMalformedMessages:
    def test_malformed_json_skipped_reader_continues(self, broadcaster, connect):
        received = []
        connect(received.append)

        broadcaster._broadcast("not-valid-json\n")
        broadcaster._on_bar(_make_bar("AMD", close=99.0))

        assert _wait_for(lambda: len(received) == 1)
        assert received[0].close == 99.0

    def test_unknown_message_type_skipped(self, broadcaster, connect):
        received = []
        connect(received.append)

        broadcaster._broadcast(json.dumps({"type": "unknown", "data": "whatever"}) + "\n")
        broadcaster._on_bar(_make_bar("AMD", close=88.0))

        assert _wait_for(lambda: len(received) == 1)
        assert received[0].close == 88.0
