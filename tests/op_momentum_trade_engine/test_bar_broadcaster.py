import json
import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.bar_broadcaster import (
    BarBroadcaster,
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


def _read_lines(sock: socket.socket, count: int, timeout: float = 2.0) -> list:
    """Read up to `count` newline-terminated JSON lines from sock."""
    lines = []
    reader = sock.makefile("r", encoding="utf-8")
    sock.settimeout(timeout)
    while len(lines) < count:
        try:
            line = reader.readline()
        except socket.timeout:
            break
        if not line:
            break
        line = line.strip()
        if line:
            lines.append(json.loads(line))
    return lines


@pytest.fixture
def tmp_socket_path():
    # macOS unix socket path limit is 104 bytes; pytest tmp_path exceeds it
    path = tempfile.mktemp(dir="/tmp", prefix="ts_bc_", suffix=".sock")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class TestBarBroadcasterFanOut:
    def test_fan_out_to_multiple_clients(self, tmp_socket_path):
        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)

        thread = threading.Thread(target=broadcaster.start, daemon=True)
        thread.start()
        time.sleep(0.1)

        client_a = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_a.connect(tmp_socket_path)
        client_b = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_b.connect(tmp_socket_path)
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("AMD"))
        time.sleep(0.1)

        msgs_a = _read_lines(client_a, 1)
        msgs_b = _read_lines(client_b, 1)

        broadcaster.stop()
        client_a.close()
        client_b.close()

        assert len(msgs_a) == 1
        assert msgs_a[0]["symbol"] == "AMD"
        assert msgs_a[0]["type"] == "bar"
        assert len(msgs_b) == 1
        assert msgs_b[0]["symbol"] == "AMD"

    def test_bar_message_contains_all_fields(self, tmp_socket_path):
        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)

        thread = threading.Thread(target=broadcaster.start, daemon=True)
        thread.start()
        time.sleep(0.1)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(tmp_socket_path)
        time.sleep(0.1)

        bar = _make_bar("AMD", close=123.45)
        broadcaster._on_bar(bar)
        time.sleep(0.1)

        msgs = _read_lines(client, 1)
        broadcaster.stop()
        client.close()

        assert len(msgs) == 1
        msg = msgs[0]
        assert msg["type"] == "bar"
        assert msg["symbol"] == "AMD"
        assert msg["close"] == 123.45
        assert msg["open"] == 100.0
        assert msg["volume"] == 1000.0
        assert "timestamp" in msg


class TestBarBroadcasterDisconnectedClient:
    def test_disconnected_client_removed_on_next_broadcast(self, tmp_socket_path):
        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)

        thread = threading.Thread(target=broadcaster.start, daemon=True)
        thread.start()
        time.sleep(0.1)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(tmp_socket_path)
        time.sleep(0.1)

        assert len(broadcaster._clients) == 1

        client.close()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("AMD"))
        time.sleep(0.1)

        broadcaster.stop()

        assert len(broadcaster._clients) == 0

    def test_surviving_client_still_receives_after_peer_disconnects(self, tmp_socket_path):
        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)

        thread = threading.Thread(target=broadcaster.start, daemon=True)
        thread.start()
        time.sleep(0.1)

        client_a = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_a.connect(tmp_socket_path)
        client_b = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_b.connect(tmp_socket_path)
        time.sleep(0.1)

        client_a.close()
        time.sleep(0.1)

        broadcaster._on_bar(_make_bar("AMD", close=200.0))
        time.sleep(0.1)

        msgs = _read_lines(client_b, 1)
        broadcaster.stop()
        client_b.close()

        assert len(msgs) == 1
        assert msgs[0]["close"] == 200.0


class TestBarBroadcasterHeartbeat:
    def test_heartbeat_message_type(self, tmp_socket_path):
        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)

        thread = threading.Thread(target=broadcaster.start, daemon=True)
        thread.start()
        time.sleep(0.1)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(tmp_socket_path)
        time.sleep(0.1)

        broadcaster._broadcast(broadcaster._heartbeat_line())
        time.sleep(0.1)

        msgs = _read_lines(client, 1)
        broadcaster.stop()
        client.close()

        assert len(msgs) == 1
        assert msgs[0]["type"] == "heartbeat"
        assert "ts" in msgs[0]


class TestBarBroadcasterSocketSetup:
    def test_stale_socket_file_removed_on_start(self, tmp_socket_path):
        # Pre-create a file at the socket path to simulate a stale socket
        with open(tmp_socket_path, "w") as f:
            f.write("stale")

        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)

        with patch.object(broadcaster, "_stream") as mock_stream, \
             patch("alpha_tech_tracker.op_momentum_strategy.bar_broadcaster.TradeStationBarStream") as MockStream:
            mock_instance = MagicMock()
            MockStream.return_value = mock_instance
            mock_instance.run.side_effect = lambda: broadcaster._stop_event.set()
            broadcaster.start()

        # Socket file should have been replaced (not failed on existing file)
        # The test passes if start() didn't raise on the pre-existing file

    def test_no_clients_on_init(self, tmp_socket_path):
        broadcaster = BarBroadcaster(_make_ts_client(), ["AMD"], socket_path=tmp_socket_path)
        assert broadcaster._clients == []
