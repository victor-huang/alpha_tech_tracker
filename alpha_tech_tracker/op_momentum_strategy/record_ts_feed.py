import logging
import threading

from alpha_tech_tracker.op_momentum_strategy.bar_recorder import BarRecorder
from alpha_tech_tracker.trade_api.tradestation.bar_stream import TradeStationBarStream

logger = logging.getLogger(__name__)


class TsBarRecorder:
    """
    Records TradeStation 1-min and 5-min bar streams to CSV files.

    Runs two parallel TradeStationBarStream instances (one per interval)
    and writes each closed bar to BarRecorder with feed="tradestation".

    Usage:
        recorder = TsBarRecorder(ts_client, tickers, session_template="Default")
        recorder.start()
        ...
        recorder.stop()
    """

    def __init__(self, ts_client, tickers: list, session_template: str = "Default"):
        self._tickers = tickers
        self._session_template = session_template
        self._bar_recorder = BarRecorder(feed="tradestation")
        self._stream_1min = TradeStationBarStream(ts_client, interval=1, unit="Minute")
        self._stream_5min = TradeStationBarStream(ts_client, interval=5, unit="Minute")
        self._lock = threading.Lock()

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
        self._stream_1min.subscribe_bars(self._on_1min_bar, *self._tickers)
        self._stream_5min.subscribe_bars(self._on_5min_bar, *self._tickers)
        self._stream_1min.start_async()
        self._stream_5min.start_async()

    def stop(self):
        logger.info("TsBarRecorder: stopping TS feed")
        self._stream_1min.stop()
        self._stream_5min.stop()
        self._bar_recorder.close()
