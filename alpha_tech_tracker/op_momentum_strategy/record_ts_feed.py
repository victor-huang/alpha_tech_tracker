import logging
import threading
from datetime import datetime, timezone

import pytz

from alpha_tech_tracker.op_momentum_strategy.bar_recorder import BarRecorder
from alpha_tech_tracker.trade_api.tradestation.bar_stream import TradeStationBarStream

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class TsBarRecorder:
    """
    Records TradeStation 1-min and 5-min bar streams to CSV files.

    Runs two parallel TradeStationBarStream instances (one per interval)
    and writes each closed bar to BarRecorder with feed="tradestation".

    On start(), any bars from 9:30 AM ET to the current time are backfilled
    via the REST historical API before the live stream begins, so the CSV
    always starts from the opening range regardless of when the engine starts.

    Usage:
        recorder = TsBarRecorder(ts_client, tickers, session_template="Default")
        recorder.start()
        ...
        recorder.stop()
    """

    def __init__(self, ts_client, tickers: list, session_template: str = "Default"):
        self._ts_client = ts_client
        self._tickers = tickers
        self._session_template = session_template
        self._bar_recorder = BarRecorder(feed="tradestation")
        self._stream_1min = TradeStationBarStream(ts_client, interval=1, unit="Minute")
        self._stream_5min = TradeStationBarStream(ts_client, interval=5, unit="Minute")
        self._lock = threading.Lock()

    def _backfill_session(self):
        """Fetch today's bars from 9:30 ET to now via REST and write to CSV.

        Skipped when called before market open (nothing to backfill).
        """
        now_et = datetime.now(ET)
        session_date = now_et.date()
        market_open_et = ET.localize(
            datetime.combine(session_date, datetime.min.time()).replace(hour=9, minute=30)
        )
        if now_et <= market_open_et:
            return

        start_utc = market_open_et.astimezone(timezone.utc)
        end_utc = now_et.astimezone(timezone.utc)

        logger.info(
            "TsBarRecorder: backfilling %s bars from 09:30 ET to %s ET for %d tickers",
            "1-min + 5-min",
            now_et.strftime("%H:%M"),
            len(self._tickers),
        )
        for ticker in self._tickers:
            for interval, record_fn in [
                (1, self._bar_recorder.record_1min),
                (5, self._bar_recorder.record_5min),
            ]:
                try:
                    bars = self._ts_client.get_historical_bars(
                        ticker, start_utc, end_utc, interval=interval
                    )
                    for bar in bars:
                        record_fn(ticker, bar, session_date)
                    logger.info(
                        "TsBarRecorder backfill %-6s %dmin: %d bars",
                        ticker, interval, len(bars),
                    )
                except Exception:
                    logger.exception(
                        "TsBarRecorder backfill failed for %s %dmin", ticker, interval
                    )

    def _on_1min_bar(self, bar):
        with self._lock:
            session_date = bar.timestamp.date()
        self._bar_recorder.record_1min(bar.symbol, bar, session_date)
        logger.debug("TS 1min: %s %s O=%.2f C=%.2f", bar.symbol, bar.timestamp, bar.open, bar.close)

    def _on_5min_bar(self, bar):
        with self._lock:
            session_date = bar.timestamp.date()
        self._bar_recorder.record_5min(bar.symbol, bar, session_date)
        logger.debug("TS 5min: %s %s O=%.2f C=%.2f", bar.symbol, bar.timestamp, bar.open, bar.close)

    def start(self):
        logger.info(
            "TsBarRecorder: starting TS feed for %d tickers (1-min + 5-min)",
            len(self._tickers),
        )
        self._backfill_session()
        self._stream_1min.subscribe_bars(self._on_1min_bar, *self._tickers)
        self._stream_5min.subscribe_bars(self._on_5min_bar, *self._tickers)
        self._stream_1min.start_async()
        self._stream_5min.start_async()

    def stop(self):
        logger.info("TsBarRecorder: stopping TS feed")
        self._stream_1min.stop()
        self._stream_5min.stop()
        self._bar_recorder.close()
