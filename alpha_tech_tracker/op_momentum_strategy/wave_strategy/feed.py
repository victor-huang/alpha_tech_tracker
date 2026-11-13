"""Market data for the wave strategy: warm-up history, the 1-min stream built into 5-min bars, the first-period
refetch after a (re)start, the delayed-feed / outage backfill and the stream watchdog."""

import logging
import threading
from datetime import datetime, timedelta

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import regular_hours
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.bars import FiveMinAggregator
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import (
    BAR_MINUTES,
    ET,
    MARKET_OPEN,
    _now_et,
    period_start,
    previous_trading_day,
    session_close,
)

logger = logging.getLogger(__name__)

WARMUP_CALENDAR_DAYS = 20
OUTAGE_ALERT_SECONDS = 300
STREAM_TIMEOUT_SECONDS = 120
DELAYED_DATA_MINUTES = 16  # Alpaca plans without real-time SIP only serve SIP history older than 15 min


def empty_bars():
    return pd.DataFrame(columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([], tz=ET))


class BarFeed:
    """Wraps a MarketDataClient (warmup / fetch_bars / subscribe_bars / start / stop / reconnect).

    Callbacks: `on_bar(ticker, bar)` gets each finished 5-min bar (a FiveMinAggregator dict) under `lock`;
    `on_backfill(gap_start, fetched)` gets the regular-hours bars of a backfilled gap by ticker, or None when the
    fetch failed; `alert(message)` gets the data outage / restored notices.
    """

    def __init__(self, client, on_bar, on_backfill, alert, now=_now_et, lock=None):
        self.client = client
        self.on_bar = on_bar
        self.on_backfill = on_backfill
        self.alert = alert
        self.now = now
        self.lock = lock or threading.RLock()
        self.client_lock = threading.Lock()  # history requests share the client's session with the stats thread
        self.aggregator = FiveMinAggregator(self.on_five_min_bar)
        self.tickers = []
        self.session = None
        self.close_time = None
        self.stream_started_at = None
        self.last_minute_at = None
        self.refetch_before = None
        self.backfill = None
        self.last_reconnect_at = None
        self.outage_from = None

    # --- history ---------------------------------------------------------

    def history(self, method, tickers, start, end):
        """A history request to the market data client, one at a time."""
        with self.client_lock:
            return getattr(self.client, method)(tickers, start, end)

    def session_bars(self, tickers, now):
        """Each ticker's regular-hours 5-min bars finished by `now` (see `warmup`); empty frames for missing ones."""
        history = self.warmup(tickers, now)
        bars_by_ticker = {}
        for ticker in tickers:
            frame = history.get(ticker)
            bars = regular_hours(frame) if frame is not None and not frame.empty else empty_bars()
            bars_by_ticker[ticker] = bars[bars.index + timedelta(minutes=BAR_MINUTES) <= now]
        return bars_by_ticker

    def warmup(self, tickers, now):
        """History up to now; before the open, up to the previous session's close (no recent data needed).

        If the feed refuses recent data (delayed SIP plans), warm up to DELAYED_DATA_MINUTES ago and
        backfill the gap once it can be queried (run_backfill).
        """
        if now.time() < MARKET_OPEN:
            previous = previous_trading_day(now.date())
            end = ET.localize(datetime.combine(previous, session_close(previous)))
        else:
            end = now
        start = end - timedelta(days=WARMUP_CALENDAR_DAYS)
        try:
            return self.history("warmup", tickers, start, end)
        except Exception as error:
            if "recent" not in str(error).lower():
                raise
            delayed_end = now - timedelta(minutes=DELAYED_DATA_MINUTES)
            logger.warning("Feed refuses recent data (%s); warming up to %s and backfilling the rest later",
                           error, f"{delayed_end:%H:%M}")
            self.schedule_backfill(delayed_end, now)
            return self.history("warmup", tickers, start, delayed_end)

    # --- stream ----------------------------------------------------------

    def start_session(self, session, tickers, close_time, now):
        """Streamed minutes count from the open of `session` to `close_time`; the period streaming starts in is
        refetched whole."""
        self.session = session
        self.tickers = list(tickers)
        self.close_time = close_time
        self.refetch_before = period_start(now) + timedelta(minutes=BAR_MINUTES)

    def start_stream(self):
        self.client.subscribe_bars(self.on_minute_bar, *self.tickers)
        self.client.start()
        self.stream_started_at = self.now()

    def stop(self):
        self.client.stop()

    def on_minute_bar(self, bar):
        ticker = bar.symbol
        if ticker not in self.tickers:
            return
        timestamp = bar.timestamp.astimezone(ET)
        if timestamp.date() != self.session or not (MARKET_OPEN <= timestamp.time() < self.close_time):
            return
        with self.lock:
            now = self.now()
            if self.outage_from is not None:
                self.alert(f"market data restored at {now:%H:%M} after a gap from {self.outage_from:%H:%M}; "
                           "signals and stop checks in the gap were missed, check open positions")
                self.schedule_backfill(self.outage_from, now)
                self.outage_from = None
            self.last_minute_at = now
            self.aggregator.add(ticker, timestamp, float(bar.open), float(bar.high), float(bar.low), float(bar.close))

    def on_five_min_bar(self, ticker, bar):
        with self.lock:
            if self.refetch_before is not None and bar["time"] < self.refetch_before:
                bar = self._refetch_bar(ticker, bar)
            self.on_bar(ticker, bar)

    def flush_due(self, now):
        self.aggregator.flush_due(now)

    def _refetch_bar(self, ticker, partial):
        """The first period after a (re)start only has the minutes streamed since; fetch it whole."""
        try:
            fetched = self.history("fetch_bars", [ticker], partial["time"],
                                   partial["time"] + timedelta(minutes=BAR_MINUTES))
            frame = fetched.get(ticker)
            if frame is not None and not frame.empty:
                row = regular_hours(frame).loc[partial["time"]]
                return {"time": partial["time"], "open": float(row["open"]), "high": float(row["high"]),
                        "low": float(row["low"]), "close": float(row["close"]), "minutes": BAR_MINUTES}
        except Exception:
            logger.warning("%s: refetch of the %s bar failed; using the streamed minutes", ticker,
                           f"{partial['time']:%H:%M}", exc_info=True)
        return partial

    # --- gaps ------------------------------------------------------------

    def schedule_backfill(self, gap_start, gap_end):
        if self.backfill is not None:
            gap_start, gap_end = min(gap_start, self.backfill[0]), max(gap_end, self.backfill[1])
        self.backfill = (gap_start, gap_end)

    def run_backfill(self, now):
        """Fetch a scheduled gap once it can be queried and hand its bars to `on_backfill`."""
        gap_start, gap_end = self.backfill
        if now < gap_end + timedelta(minutes=DELAYED_DATA_MINUTES):
            return
        self.backfill = None
        try:
            fetched = self.history("fetch_bars", self.tickers, gap_start, gap_end)
        except Exception:
            logger.warning("Backfill of %s-%s failed", f"{gap_start:%H:%M}", f"{gap_end:%H:%M}", exc_info=True)
            self.on_backfill(gap_start, None)
            return
        self.on_backfill(gap_start, {ticker: regular_hours(fetched[ticker]) for ticker in self.tickers
                                     if fetched.get(ticker) is not None and not fetched[ticker].empty})

    def watchdog(self, now):
        """Reconnect a silent stream, and tell the user once when market data has stopped."""
        if not (MARKET_OPEN <= now.time() < self.close_time) or self.stream_started_at is None:
            return
        session_open = ET.localize(datetime.combine(now.date(), MARKET_OPEN))
        last = self.last_minute_at or max(self.stream_started_at, session_open)
        silent = (now - last).total_seconds()
        reconnect_due = (self.last_reconnect_at is None
                         or (now - self.last_reconnect_at).total_seconds() > STREAM_TIMEOUT_SECONDS)
        if silent > STREAM_TIMEOUT_SECONDS and reconnect_due:
            logger.warning("No 1-min bar for %.0fs; reconnecting the stream", silent)
            self.last_reconnect_at = now
            try:
                self.client.reconnect()
            except Exception:
                logger.exception("Stream reconnect failed")
        if silent >= OUTAGE_ALERT_SECONDS and self.outage_from is None:
            self.outage_from = last
            self.alert(f"no market data since {last:%H:%M}; no alerts until it returns "
                       "(check the feed / data subscription, see the log)")
