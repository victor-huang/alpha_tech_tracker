import csv
import logging
import os
from datetime import date

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

_DEFAULT_BASE_DIR = os.path.join(os.path.dirname(__file__), "live_trade_market_data")


class BarRecorder:
    """
    Appends 1-min and 5-min bars to CSV files as they arrive during live trading.

    Files are stored at:
        live_trade_market_data/{date}/{feed}_{ticker}_1min.csv
        live_trade_market_data/{date}/{feed}_{ticker}_5min.csv

    Timestamps are written in ET (America/New_York).
    """

    def __init__(self, base_dir: str = _DEFAULT_BASE_DIR, feed: str = "sip"):
        self._base_dir = base_dir
        self._feed = feed
        self._files: dict = {}
        self._writers: dict = {}

    def _get_writer(self, ticker: str, timeframe: str, session_date: date):
        key = (ticker, timeframe)
        if key not in self._writers:
            date_dir = os.path.join(self._base_dir, str(session_date))
            os.makedirs(date_dir, exist_ok=True)
            path = os.path.join(date_dir, f"{self._feed}_{ticker}_{timeframe}.csv")
            is_new = not os.path.exists(path)
            f = open(path, "a", newline="")
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            self._files[key] = f
            self._writers[key] = writer
            logger.info("BarRecorder: opened %s", path)
        return self._writers[key]

    def record_1min(self, ticker: str, bar, session_date: date):
        try:
            ts = bar.timestamp.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")
            writer = self._get_writer(ticker, "1min", session_date)
            writer.writerow([ts, bar.open, bar.high, bar.low, bar.close, int(bar.volume)])
            self._files[(ticker, "1min")].flush()
        except Exception:
            logger.exception("BarRecorder: failed to record 1-min bar for %s", ticker)

    def record_5min(self, ticker: str, bar, session_date: date):
        try:
            ts = bar.timestamp.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")
            writer = self._get_writer(ticker, "5min", session_date)
            writer.writerow([ts, bar.open, bar.high, bar.low, bar.close, int(bar.volume)])
            self._files[(ticker, "5min")].flush()
        except Exception:
            logger.exception("BarRecorder: failed to record 5-min bar for %s", ticker)

    def close(self):
        for f in self._files.values():
            try:
                f.close()
            except Exception:
                pass
        self._files.clear()
        self._writers.clear()
