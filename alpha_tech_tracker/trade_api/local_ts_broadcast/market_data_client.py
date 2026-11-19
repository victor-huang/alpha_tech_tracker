import json
import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from alpha_tech_tracker.trade_api.market_data_client import MarketDataClient
from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
    TradeStationMarketDataClient,
)

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/tmp/ts_bar_feed.sock"
_CONNECT_RETRY_INTERVAL = 2   # seconds between connection attempts
_CONNECT_MAX_WAIT = 60        # seconds to wait for broadcaster before giving up


@dataclass
class _BroadcastBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_json(cls, d: dict) -> "_BroadcastBar":
        return cls(
            symbol=d["symbol"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=float(d["volume"]),
        )


class LocalTSBroadcastMarketDataClient(MarketDataClient):
    """
    MarketDataClient that reads bars from a local BarBroadcaster Unix domain socket
    instead of connecting to TradeStation directly.

    warmup() and fetch_bars() still call the TS REST API via ts_client.
    Live bar delivery comes from the broadcaster over the socket.

    Each ticker's bars go to the callback on that ticker's own thread, as with the direct TS stream (one
    stream thread per ticker). The socket carries every ticker, so calling back from the reader thread would
    hold a ticker's bar until slow callbacks for the tickers ahead of it return.
    """

    def __init__(self, ts_client, socket_path: str = DEFAULT_SOCKET_PATH):
        self._ts_client = ts_client
        self._socket_path = socket_path
        self._callback = None
        self._tickers: list = []
        self._sock = None
        self._reader_thread = None
        self._stop_event = threading.Event()
        self._last_message_at: float = 0.0
        self._queues: dict = {}
        self._workers: dict = {}
        self._sock_lock = threading.Lock()

    def warmup(self, tickers: list, start_dt, end_dt) -> dict:
        return TradeStationMarketDataClient(self._ts_client).warmup(tickers, start_dt, end_dt)

    def fetch_bars(self, tickers: list, start_dt, end_dt) -> dict:
        return TradeStationMarketDataClient(self._ts_client).fetch_bars(tickers, start_dt, end_dt)

    def subscribe_bars(self, callback, *tickers):
        self._callback = callback
        self._tickers = list(tickers)

    def start(self):
        self._stop_event.clear()
        self._start_workers()
        self._connect()

    def _start_workers(self):
        for ticker in self._tickers:
            worker = self._workers.get(ticker)
            if worker is not None and worker.is_alive():
                continue
            self._queues[ticker] = queue.Queue()
            self._workers[ticker] = threading.Thread(
                target=self._deliver_loop,
                args=(ticker, self._queues[ticker]),
                name=f"local-ts-broadcast-{ticker}",
                daemon=True,
            )
            self._workers[ticker].start()

    def _deliver_loop(self, ticker, bars):
        while True:
            bar = bars.get()
            if bar is None:
                return
            try:
                if self._callback:
                    self._callback(bar)
            except Exception:
                logger.exception("LocalTSBroadcast: callback error [%s]", ticker)

    def _connect(self):
        self._sock = self._connect_with_retry()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="local-ts-broadcast-reader",
            daemon=True,
        )
        self._reader_thread.start()
        logger.info(
            "LocalTSBroadcast: connected to %s, subscribed to %s",
            self._socket_path,
            self._tickers,
        )

    def _connect_with_retry(self) -> socket.socket:
        deadline = time.monotonic() + _CONNECT_MAX_WAIT
        attempt = 0
        while True:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self._socket_path)
                if attempt > 0:
                    logger.info(
                        "LocalTSBroadcast: connected to broadcaster after %d attempt(s)",
                        attempt + 1,
                    )
                return sock
            except OSError:
                attempt += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f"LocalTSBroadcast: broadcaster not available at {self._socket_path} "
                        f"after {_CONNECT_MAX_WAIT}s — start bar_broadcaster first"
                    )
                wait = min(_CONNECT_RETRY_INTERVAL, remaining)
                logger.warning(
                    "LocalTSBroadcast: broadcaster not ready, retrying in %.0fs "
                    "(%.0fs remaining)",
                    wait,
                    remaining,
                )
                time.sleep(wait)

    def _reader_loop(self):
        """Read until stopped. When the broadcaster closes the connection (it restarts with the engines), connect
        again by itself every _CONNECT_RETRY_INTERVAL seconds: outside market hours no watchdog would notice."""
        sock = self._sock
        while sock is not None and not self._stop_event.is_set():
            closed = self._read(sock)
            if not closed or self._stop_event.is_set():
                return
            logger.warning("LocalTSBroadcast: connection closed by broadcaster; reconnecting")
            sock = self._reconnect_socket()

    def _read(self, sock):
        """Hand the socket's bars to the ticker threads. True when the broadcaster closed the connection."""
        try:
            reader = sock.makefile("r", encoding="utf-8")
            while not self._stop_event.is_set():
                try:
                    line = reader.readline()
                except OSError:
                    return False
                if not line:
                    return True
                self._handle_line(line)
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("LocalTSBroadcast: reader loop error")
        return False

    def _handle_line(self, line):
        line = line.strip()
        if not line:
            return
        self._last_message_at = time.monotonic()
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            logger.warning("LocalTSBroadcast: malformed message: %s", line[:120])
            return
        if msg.get("type") == "heartbeat":
            logger.debug("LocalTSBroadcast: heartbeat received")
            return
        if msg.get("type") != "bar" or msg.get("symbol") not in self._tickers:
            return
        try:
            bar = _BroadcastBar.from_json(msg)
        except (KeyError, ValueError):
            logger.warning("LocalTSBroadcast: malformed bar message: %s", msg)
            return
        self._queues[bar.symbol].put(bar)

    def _reconnect_socket(self):
        attempts = 0
        while not self._stop_event.wait(_CONNECT_RETRY_INTERVAL):
            attempts += 1
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(self._socket_path)
            except OSError:
                sock.close()
                if attempts == 1 or attempts % 30 == 0:
                    logger.warning("LocalTSBroadcast: broadcaster not back yet (%d attempts)", attempts)
                continue
            with self._sock_lock:
                if self._stop_event.is_set():
                    sock.close()
                    return None
                self._sock = sock
            logger.info("LocalTSBroadcast: reconnected to %s after %d attempt(s)", self._socket_path, attempts)
            return sock
        return None

    def reconnect(self):
        """Reconnect the socket; the ticker threads keep their queued bars and carry on."""
        logger.warning("LocalTSBroadcast: reconnecting to broadcaster")
        self._disconnect()
        self._stop_event.clear()
        self._start_workers()
        self._connect()

    def stop(self):
        """Disconnect and end the ticker threads, dropping bars not yet delivered. A callback already running
        finishes on its own; stop() does not wait for it (the caller may hold a lock the callback needs)."""
        self._disconnect()
        for bars in self._queues.values():
            while True:
                try:
                    bars.get_nowait()
                except queue.Empty:
                    break
            bars.put(None)
        self._queues = {}
        self._workers = {}

    def _disconnect(self):
        self._stop_event.set()
        with self._sock_lock:
            sock, self._sock = self._sock, None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3)
        self._reader_thread = None

    def seconds_since_last_message(self) -> float:
        """Seconds since last bar or heartbeat received. Used by the engine watchdog."""
        if self._last_message_at == 0.0:
            return float("inf")
        return time.monotonic() - self._last_message_at
