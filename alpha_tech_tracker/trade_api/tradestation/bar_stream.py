import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_STREAM_URL = "https://api.tradestation.com/v3/marketdata/stream/barcharts/{symbol}"
_SIM_STREAM_URL = "https://sim-api.tradestation.com/v3/marketdata/stream/barcharts/{symbol}"


@dataclass
class _TSBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ts_dict(cls, d: dict, symbol: str, interval_minutes: int = 1) -> "_TSBar":
        """Parse a TradeStation bar dict (stream or historical) into a _TSBar.

        Handles both ISO TimeStamp strings and Epoch integer (milliseconds).

        TradeStation timestamps bars at their CLOSE time. This method normalizes
        to open-time convention (subtracting interval_minutes) so that _TSBar
        timestamps are consistent with Alpaca and the rest of the codebase.
        """
        raw_ts = d.get("TimeStamp") or d.get("Epoch")
        if isinstance(raw_ts, (int, float)):
            ts = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc)
        else:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        ts = ts - timedelta(minutes=interval_minutes)
        return cls(
            symbol=symbol,
            timestamp=ts,
            open=float(d["Open"]),
            high=float(d["High"]),
            low=float(d["Low"]),
            close=float(d["Close"]),
            volume=float(d.get("TotalVolume", 0)),
        )


class TradeStationBarStream:
    """
    Streams 1-min bars for multiple tickers via TradeStation's HTTP chunked
    streaming endpoint. One persistent connection per ticker, each in a
    daemon thread. Reconnects automatically on error.

    Usage:
        stream = TradeStationBarStream(ts_client)
        stream.subscribe_bars(on_bar, "TSLA", "META", ...)
        stream.start_async()   # starts threads and returns immediately
        ...
        stream.stop()

        # or block until stop() is called from another thread:
        stream.run()
    """

    def __init__(self, ts_client, interval: int = 1, unit: str = "Minute", barsback: int = 0):
        self._session = ts_client._session
        self._environment = ts_client._environment
        self._interval = interval
        self._unit = unit
        self._barsback = barsback
        self._tickers: list = []
        self._callback = None
        self._stop_event = threading.Event()
        self._threads: list = []

    def _stream_url(self, symbol: str) -> str:
        if self._environment == "sim":
            return _SIM_STREAM_URL.format(symbol=symbol)
        return _STREAM_URL.format(symbol=symbol)

    def subscribe_bars(self, callback, *tickers):
        self._callback = callback
        self._tickers = list(tickers)

    def _stream_ticker(self, symbol: str):
        url = self._stream_url(symbol)
        params = {"interval": self._interval, "unit": self._unit}
        if self._barsback > 0:
            params["barsback"] = self._barsback
        backoff = 5
        while not self._stop_event.is_set():
            try:
                logger.info("TS stream: connecting [%s]", symbol)
                resp = self._session.get(
                    url, params=params, stream=True, timeout=(10, 90)
                )
                resp.raise_for_status()
                backoff = 5
                for raw_line in resp.iter_lines():
                    if self._stop_event.is_set():
                        break
                    if not raw_line:
                        continue
                    try:
                        frame = json.loads(raw_line)
                    except (ValueError, TypeError):
                        continue
                    if "Heartbeat" in frame:
                        continue
                    if frame.get("BarStatus") != "Closed":
                        continue
                    try:
                        bar = _TSBar.from_ts_dict(frame, symbol, interval_minutes=self._interval)
                    except (KeyError, ValueError):
                        logger.warning(
                            "TS stream: malformed bar [%s]: %s", symbol, frame
                        )
                        continue
                    if self._callback:
                        self._callback(bar)
            except Exception:
                if not self._stop_event.is_set():
                    logger.exception(
                        "TS stream: error [%s] — reconnecting in %ds", symbol, backoff
                    )
                    self._stop_event.wait(backoff)
                    backoff = min(backoff * 2, 60)

    def start_async(self):
        """Start one daemon thread per ticker and return immediately."""
        self._stop_event.clear()
        self._threads = []
        for ticker in self._tickers:
            t = threading.Thread(
                target=self._stream_ticker,
                args=(ticker,),
                name="ts-stream-{}".format(ticker),
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def run(self):
        """Start threads and block until all finish (or stop() is called)."""
        self.start_async()
        for t in self._threads:
            t.join()

    def stop(self):
        self._stop_event.set()
