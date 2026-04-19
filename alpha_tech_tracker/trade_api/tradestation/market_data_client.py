import logging
from datetime import timezone

import pandas as pd
import pytz

from alpha_tech_tracker.trade_api.market_data_client import MarketDataClient
from alpha_tech_tracker.trade_api.tradestation.bar_stream import TradeStationBarStream

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def _ts_bars_to_df(bars: list) -> pd.DataFrame:
    """Convert a list of _TSBar objects to a DataFrame with ET index, market hours clipped."""
    if not bars:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    rows = []
    for b in bars:
        ts_et = b.timestamp.astimezone(ET)
        rows.append({
            "timestamp": ts_et,
            "Open": b.open,
            "High": b.high,
            "Low": b.low,
            "Close": b.close,
            "Volume": b.volume,
        })
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index = pd.DatetimeIndex(df.index)
    # Clip to market hours only
    df = df.between_time("09:30", "16:00")
    return df


class TradeStationMarketDataClient(MarketDataClient):
    """
    MarketDataClient implementation backed by TradeStation's bar stream and REST API.

    Streaming uses TradeStationBarStream (HTTP chunked, one thread per ticker).
    Callbacks are synchronous — no async bridge needed.
    """

    def __init__(self, ts_client):
        """
        Args:
            ts_client: TradeStationAPIClient with an active session.
        """
        self._ts_client = ts_client
        self._callback = None
        self._tickers: list = []
        self._stream: TradeStationBarStream = None

    def warmup(self, tickers: list, start_dt, end_dt) -> dict:
        logger.info(
            "TradeStation warmup: fetching 1-min bars for %d tickers: %s to %s",
            len(tickers),
            start_dt.strftime("%Y-%m-%d %H:%M ET"),
            end_dt.strftime("%Y-%m-%d %H:%M ET"),
        )
        result = {}
        # Convert ET bounds to UTC for TradeStation REST API
        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)
        for ticker in tickers:
            try:
                bars = self._ts_client.get_historical_bars(
                    ticker, start_utc, end_utc, interval=5, unit="Minute"
                )
                df = _ts_bars_to_df(bars)
                result[ticker] = df
                last_close = df["Close"].iloc[-1] if not df.empty else float("nan")
                logger.info(
                    "TS warmup %-6s — %d bars, last close=%.2f",
                    ticker, len(df), last_close,
                )
            except Exception:
                logger.exception("TS warmup failed for %s", ticker)
                result[ticker] = pd.DataFrame(
                    columns=["Open", "High", "Low", "Close", "Volume"]
                )
        return result

    def fetch_bars(self, tickers: list, start_dt, end_dt) -> dict:
        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)
        result = {}
        for ticker in tickers:
            try:
                bars = self._ts_client.get_historical_bars(
                    ticker, start_utc, end_utc, interval=5, unit="Minute"
                )
                result[ticker] = _ts_bars_to_df(bars)
            except Exception:
                logger.exception("TS fetch_bars failed for %s", ticker)
                result[ticker] = pd.DataFrame(
                    columns=["Open", "High", "Low", "Close", "Volume"]
                )
        return result

    def subscribe_bars(self, callback, *tickers):
        self._callback = callback
        self._tickers = list(tickers)

    def start(self):
        self._stream = TradeStationBarStream(self._ts_client, interval=1, unit="Minute")
        self._stream.subscribe_bars(self._callback, *self._tickers)
        logger.info(
            "TradeStation: starting live 1-min stream for %s", self._tickers
        )
        self._stream.start_async()

    def reconnect(self):
        logger.warning("TradeStation: reconnecting stream")
        self.stop()
        self.start()
        logger.info("TradeStation: stream reconnected for %s", self._tickers)

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream = None
