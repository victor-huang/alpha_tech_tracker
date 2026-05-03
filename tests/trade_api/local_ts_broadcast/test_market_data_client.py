import json
import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
    LocalTSBroadcastMarketDataClient,
    _BroadcastBar,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _bar_msg(symbol="AMD", ts=None) -> str:
    if ts is None:
        ts = datetime(2026, 5, 2, 9, 31, tzinfo=timezone.utc)
    return json.dumps({
        "type": "bar",
        "symbol": symbol,
        "timestamp": _iso(ts),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000.0,
    }) + "\n"


def _heartbeat_msg() -> str:
    return json.dumps({
        "type": "heartbeat",
        "ts": _iso(datetime.now(tz=timezone.utc)),
    }) + "\n"


def _make_ts_client():
    return MagicMock()


class _SocketServer:
    """Minimal Unix socket server for testing — sends lines to each client."""

    def __init__(self, socket_path: str):
        self._path = socket_path
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(socket_path)
        self._sock.listen(5)
        self._clients = []
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self):
        self._sock.settimeout(2.0)
        try:
            conn, _ = self._sock.accept()
            self._clients.append(conn)
        except socket.timeout:
            pass

    def send(self, line: str):
        for conn in self._clients:
            conn.sendall(line.encode())

    def close(self):
        for conn in self._clients:
            try:
                conn.close()
            except OSError:
                pass
        self._sock.close()


@pytest.fixture
def tmp_socket():
    # macOS unix socket path limit is 104 bytes; pytest tmp_path exceeds it
    path = tempfile.mktemp(dir="/tmp", prefix="ts_test_", suffix=".sock")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class TestBroadcastBarFromJson:
    def test_parses_all_fields(self):
        ts = datetime(2026, 5, 2, 9, 31, tzinfo=timezone.utc)
        d = {
            "symbol": "AMD",
            "timestamp": ts.isoformat(),
            "open": "100.25",
            "high": "101.00",
            "low": "100.10",
            "close": "100.80",
            "volume": "42381",
        }
        bar = _BroadcastBar.from_json(d)
        assert bar.symbol == "AMD"
        assert bar.timestamp == ts
        assert bar.open == 100.25
        assert bar.close == 100.80
        assert bar.volume == 42381.0

    def test_parses_numeric_values(self):
        ts = datetime(2026, 5, 2, 9, 31, tzinfo=timezone.utc)
        d = {
            "symbol": "META",
            "timestamp": ts.isoformat(),
            "open": 500.0,
            "high": 505.0,
            "low": 498.0,
            "close": 502.0,
            "volume": 8000.0,
        }
        bar = _BroadcastBar.from_json(d)
        assert bar.symbol == "META"
        assert bar.close == 502.0


class TestLocalTSBroadcastMarketDataClientCallback:
    def test_callback_called_for_subscribed_ticker(self, tmp_socket):
        server = _SocketServer(tmp_socket)
        time.sleep(0.05)

        received = []
        client = LocalTSBroadcastMarketDataClient(_make_ts_client(), socket_path=tmp_socket)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        server.send(_bar_msg("AMD"))
        time.sleep(0.2)

        client.stop()
        server.close()

        assert len(received) == 1
        assert received[0].symbol == "AMD"
        assert received[0].close == 100.5

    def test_callback_not_called_for_unsubscribed_ticker(self, tmp_socket):
        server = _SocketServer(tmp_socket)
        time.sleep(0.05)

        received = []
        client = LocalTSBroadcastMarketDataClient(_make_ts_client(), socket_path=tmp_socket)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        server.send(_bar_msg("META"))
        time.sleep(0.2)

        client.stop()
        server.close()

        assert received == []

    def test_heartbeat_does_not_trigger_callback(self, tmp_socket):
        server = _SocketServer(tmp_socket)
        time.sleep(0.05)

        received = []
        client = LocalTSBroadcastMarketDataClient(_make_ts_client(), socket_path=tmp_socket)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        server.send(_heartbeat_msg())
        time.sleep(0.2)

        client.stop()
        server.close()

        assert received == []

    def test_multiple_tickers_both_delivered(self, tmp_socket):
        server = _SocketServer(tmp_socket)
        time.sleep(0.05)

        received = []
        client = LocalTSBroadcastMarketDataClient(_make_ts_client(), socket_path=tmp_socket)
        client.subscribe_bars(received.append, "AMD", "META")
        client.start()
        time.sleep(0.1)

        server.send(_bar_msg("AMD"))
        server.send(_bar_msg("META"))
        time.sleep(0.2)

        client.stop()
        server.close()

        symbols = {b.symbol for b in received}
        assert symbols == {"AMD", "META"}

    def test_heartbeat_updates_last_message_timestamp(self, tmp_socket):
        server = _SocketServer(tmp_socket)
        time.sleep(0.05)

        client = LocalTSBroadcastMarketDataClient(_make_ts_client(), socket_path=tmp_socket)
        client.subscribe_bars(lambda b: None, "AMD")
        client.start()
        time.sleep(0.1)

        before = client.seconds_since_last_message()
        server.send(_heartbeat_msg())
        time.sleep(0.1)
        after = client.seconds_since_last_message()

        client.stop()
        server.close()

        assert after < before


class TestLocalTSBroadcastMarketDataClientReconnect:
    def test_reconnect_reattaches_after_server_restart(self):
        socket_path = tempfile.mktemp(dir="/tmp", prefix="ts_reconnect_", suffix=".sock")

        server = _SocketServer(socket_path)
        time.sleep(0.05)

        received = []
        client = LocalTSBroadcastMarketDataClient(_make_ts_client(), socket_path=socket_path)
        client.subscribe_bars(received.append, "AMD")
        client.start()
        time.sleep(0.1)

        server.close()
        time.sleep(0.1)

        server2 = _SocketServer(socket_path)
        time.sleep(0.05)
        client.reconnect()
        time.sleep(0.1)

        server2.send(_bar_msg("AMD"))
        time.sleep(0.2)

        client.stop()
        server2.close()

        assert len(received) == 1


class TestLocalTSBroadcastMarketDataClientWarmup:
    def test_warmup_delegates_to_ts_market_data_client(self):
        ts_client = _make_ts_client()
        client = LocalTSBroadcastMarketDataClient(ts_client)

        mock_result = {"AMD": MagicMock()}
        with patch(
            "alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client.TradeStationMarketDataClient"
        ) as MockTS:
            MockTS.return_value.warmup.return_value = mock_result
            result = client.warmup(["AMD"], MagicMock(), MagicMock())

        MockTS.assert_called_once_with(ts_client)
        assert result is mock_result

    def test_fetch_bars_delegates_to_ts_market_data_client(self):
        ts_client = _make_ts_client()
        client = LocalTSBroadcastMarketDataClient(ts_client)

        mock_result = {"AMD": MagicMock()}
        with patch(
            "alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client.TradeStationMarketDataClient"
        ) as MockTS:
            MockTS.return_value.fetch_bars.return_value = mock_result
            result = client.fetch_bars(["AMD"], MagicMock(), MagicMock())

        MockTS.assert_called_once_with(ts_client)
        assert result is mock_result

    def test_connect_raises_when_broadcaster_not_available(self):
        socket_path = "/tmp/ts_test_missing_definitely_not_there.sock"
        client = LocalTSBroadcastMarketDataClient(
            _make_ts_client(),
            socket_path=socket_path,
        )
        client.subscribe_bars(lambda b: None, "AMD")

        with patch(
            "alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client"
            "._CONNECT_MAX_WAIT",
            2,
        ):
            with pytest.raises(RuntimeError, match="broadcaster not available"):
                client.start()
