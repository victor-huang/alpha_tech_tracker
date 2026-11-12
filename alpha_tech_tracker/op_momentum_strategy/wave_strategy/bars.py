"""1-min -> 5-min bar aggregation."""

from datetime import timedelta

from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import BAR_MINUTES, period_start

FLUSH_GRACE_SECONDS = 20


class FiveMinAggregator:
    """Combines 1-min bars into 5-min bars and hands each finished one to `on_bar(ticker, bar)`.

    A period is finished when its fifth minute arrives, when a later minute arrives, or
    FLUSH_GRACE_SECONDS after it ends (flush_due). `bar` is a dict: time (period start), open,
    high, low, close, minutes (1-min bars it was built from).
    """

    def __init__(self, on_bar):
        self._on_bar = on_bar
        self._buffers = {}

    def add(self, ticker, timestamp, open_, high, low, close):
        start = period_start(timestamp)
        buffer = self._buffers.get(ticker)
        if buffer and buffer["time"] != start:
            if start < buffer["time"]:
                return
            self._emit(ticker)
            buffer = None
        if buffer is None:
            buffer = self._buffers[ticker] = {"time": start, "open": open_, "high": high, "low": low,
                                              "close": close, "minutes": 0}
        buffer["high"] = max(buffer["high"], high)
        buffer["low"] = min(buffer["low"], low)
        buffer["close"] = close
        buffer["minutes"] += 1
        if timestamp.minute % BAR_MINUTES == BAR_MINUTES - 1:
            self._emit(ticker)

    def flush_due(self, now):
        for ticker in [t for t, b in self._buffers.items()
                       if b["time"] + timedelta(minutes=BAR_MINUTES, seconds=FLUSH_GRACE_SECONDS) <= now]:
            self._emit(ticker)

    def _emit(self, ticker):
        bar = self._buffers.pop(ticker, None)
        if bar:
            self._on_bar(ticker, bar)
