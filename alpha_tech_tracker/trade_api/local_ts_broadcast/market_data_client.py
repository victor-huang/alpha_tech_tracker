import json
import logging
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

    def warmup(self, tickers: list, start_dt, end_dt) -> dict:
        return TradeStationMarketDataClient(self._ts_client).warmup(tickers, start_dt, end_dt)

    def fetch_bars(self, tickers: list, start_dt, end_dt) -> dict:
        return TradeStationMarketDataClient(self._ts_client).fetch_bars(tickers, start_dt, end_dt)

    def subscribe_bars(self, callback, *tickers):
        self._callback = callback
        self._tickers = list(tickers)

    def start(self):
        self._stop_event.clear()
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
        try:
            reader = self._sock.makefile("r", encoding="utf-8")
            while not self._stop_event.is_set():
                try:
                    line = reader.readline()
                except OSError:
                    break
                if not line:
                    if not self._stop_event.is_set():
                        logger.warning("LocalTSBroadcast: connection closed by broadcaster")
                    break
                line = line.strip()
                if not line:
                    continue
                self._last_message_at = time.monotonic()
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError):
                    logger.warning("LocalTSBroadcast: malformed message: %s", line[:120])
                    continue
                if msg.get("type") == "heartbeat":
                    logger.debug("LocalTSBroadcast: heartbeat received")
                    continue
                if msg.get("type") != "bar":
                    continue
                if msg.get("symbol") not in self._tickers:
                    continue
                try:
                    bar = _BroadcastBar.from_json(msg)
                except (KeyError, ValueError):
                    logger.warning("LocalTSBroadcast: malformed bar message: %s", msg)
                    continue
                if self._callback:
                    self._callback(bar)
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("LocalTSBroadcast: reader loop error")

    def reconnect(self):
        logger.warning("LocalTSBroadcast: reconnecting to broadcaster")
        self.stop()
        self.start()

    def stop(self):
        self._stop_event.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3)
        self._reader_thread = None

    def seconds_since_last_message(self) -> float:
        """Seconds since last bar or heartbeat received. Used by the engine watchdog."""
        if self._last_message_at == 0.0:
            return float("inf")
        return time.monotonic() - self._last_message_at
