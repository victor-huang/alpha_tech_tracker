import logging
import threading
from datetime import datetime, timedelta

import pandas as pd
import pytz

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from alpha_tech_tracker.trade_api.market_data_client import MarketDataClient

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def _alpaca_bars_to_df_dict(all_df: pd.DataFrame, tickers: list) -> dict:
    """
    Convert a multi-symbol Alpaca bars DataFrame (MultiIndex symbol/timestamp)
    into dict[symbol -> DataFrame] with ET-localized index, market hours clipped,
    columns capitalised (Open/High/Low/Close/Volume).
    """
    result = {}
    empty_cols = ["Open", "High", "Low", "Close", "Volume"]
    for ticker in tickers:
        try:
            df = all_df.xs(ticker, level=0).copy()
            df.index = df.index.tz_convert(ET)
            df = df.between_time("09:30", "16:00")
            df.columns = [c.capitalize() for c in df.columns]
            result[ticker] = df
        except KeyError:
            result[ticker] = pd.DataFrame(columns=empty_cols)
    return result


class AlpacaMarketDataClient(MarketDataClient):
    """
    MarketDataClient implementation backed by the Alpaca SDK.

    Streaming uses StockDataStream (WebSocket). The Alpaca SDK requires async
    bar handlers; this class bridges that by registering an internal async handler
    that calls the sync callback provided via subscribe_bars().
    """

    def __init__(self, api_key: str, secret_key: str, feed: DataFeed = DataFeed.IEX):
        self._api_key = api_key
        self._secret_key = secret_key
        self._feed = feed
        self._callback = None
        self._stream: StockDataStream = None
        self._tickers: list = []
        self._stream_started_at = None
        self._thread = None

    def warmup(self, tickers: list, start_dt, end_dt) -> dict:
        hist_client = StockHistoricalDataClient(self._api_key, self._secret_key)
        logger.info(
            "Alpaca warmup: fetching 5-min bars for %d tickers: %s to %s",
            len(tickers),
            start_dt.strftime("%Y-%m-%d %H:%M ET"),
            end_dt.strftime("%Y-%m-%d %H:%M ET"),
        )
        request = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
            start=start_dt,
            end=end_dt,
            feed=self._feed,
        )
        bars = hist_client.get_stock_bars(request)
        logger.info("Alpaca warmup fetch complete")
        return _alpaca_bars_to_df_dict(bars.df, tickers)

    def fetch_bars(self, tickers: list, start_dt, end_dt) -> dict:
        hist_client = StockHistoricalDataClient(self._api_key, self._secret_key)
        request = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
            start=start_dt,
            end=end_dt,
            feed=self._feed,
        )
        try:
            bars = hist_client.get_stock_bars(request)
            all_df = bars.df
            # Alpaca returns flat DatetimeIndex when only one ticker is requested.
            if not isinstance(all_df.index, pd.MultiIndex) and len(tickers) == 1:
                all_df = pd.concat({tickers[0]: all_df}, names=["symbol", "timestamp"])
            return _alpaca_bars_to_df_dict(all_df, tickers)
        except Exception:
            logger.exception("Alpaca fetch_bars failed for %s", tickers)
            empty_cols = ["Open", "High", "Low", "Close", "Volume"]
            return {t: pd.DataFrame(columns=empty_cols) for t in tickers}

    def subscribe_bars(self, callback, *tickers):
        self._callback = callback
        self._tickers = list(tickers)

    def start(self):
        self._stream = StockDataStream(
            self._api_key,
            self._secret_key,
            feed=self._feed,
            websocket_params={"ping_interval": 20, "ping_timeout": 40},
        )

        callback = self._callback

        async def _handler(bar):
            if callback:
                callback(bar)

        self._stream.subscribe_bars(_handler, *self._tickers)
        logger.info("Alpaca: starting live stream for %s", self._tickers)
        self._thread = threading.Thread(target=self._stream.run, daemon=True)
        self._thread.start()
        self._stream_started_at = datetime.now(ET)

    def reconnect(self):
        logger.warning("Alpaca: reconnecting stream")
        self.stop()
        self._stream = StockDataStream(
            self._api_key,
            self._secret_key,
            feed=self._feed,
            websocket_params={"ping_interval": 20, "ping_timeout": 40},
        )

        callback = self._callback

        async def _handler(bar):
            if callback:
                callback(bar)

        self._stream.subscribe_bars(_handler, *self._tickers)
        self._thread = threading.Thread(target=self._stream.run, daemon=True)
        self._thread.start()
        self._stream_started_at = datetime.now(ET)
        logger.info("Alpaca: stream reconnected for %s", self._tickers)

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
            except AttributeError:
                pass

    @staticmethod
    def warmup_date_range(warmup_days: int):
        """
        Compute (start_dt, end_dt) for warmup relative to now in ET.
        Returns tz-aware datetimes. Rolls back on weekends.
        """
        now_et = datetime.now(ET)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_et >= market_open:
            end_dt = now_et
        else:
            prev = now_et.date() - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            end_dt = ET.localize(
                datetime.combine(prev, datetime.strptime("16:00", "%H:%M").time())
            )
        start_dt = end_dt - timedelta(days=warmup_days)
        return start_dt, end_dt
