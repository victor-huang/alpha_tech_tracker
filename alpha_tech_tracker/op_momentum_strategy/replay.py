import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional

import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _FiveMinBar
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# ── Replay clock ──────────────────────────────────────────────────────────────
# Module-level singleton so signal_engine and trade_engine can both call
# _now_et() without passing a clock object around.

_clock_lock = threading.Lock()
_clock: Optional[Callable[[], datetime]] = None


def _now_et() -> datetime:
    """Return current ET time, or the injected replay clock value when replaying."""
    with _clock_lock:
        fn = _clock
    if fn is not None:
        return fn()
    return datetime.now(ET)


def is_replay_mode() -> bool:
    """Return True when a replay clock is active (i.e. run_replay() is in progress)."""
    with _clock_lock:
        return _clock is not None


def set_replay_clock(fn: Callable[[], datetime]):
    global _clock
    with _clock_lock:
        _clock = fn


def clear_replay_clock():
    global _clock
    with _clock_lock:
        _clock = None


# ── BarReplayDriver ───────────────────────────────────────────────────────────


@dataclass
class BarReplayDriver:
    """
    Fetches 5-min bars for `replay_date` from the backtest cache (or Alpaca)
    and feeds them into the live signal engine one bar at a time, advancing the
    replay clock per bar.

    `on_bar_injected(ticker)` is called after each injection so the caller can
    immediately run the position monitor for that ticker.
    """

    tickers: list
    replay_date: date
    signal_engine: object  # LiveSignalEngine
    on_bar_injected: Optional[Callable[[str], None]] = None

    def run(self):
        bars_by_ticker = self._fetch_session_bars()
        timeline = self._build_timeline(bars_by_ticker)

        logger.info(
            "Replay %s — %d 5-min bars across %d tickers",
            self.replay_date,
            len(timeline),
            len([t for t, b in bars_by_ticker.items() if b]),
        )

        for bar in timeline:
            set_replay_clock(lambda ts=bar.timestamp: ts)
            self.signal_engine._process_five_min_bar(bar)
            if self.on_bar_injected:
                self.on_bar_injected(bar.symbol)

        clear_replay_clock()
        logger.info("Replay %s complete", self.replay_date)

    def _fetch_session_bars(self) -> dict:
        """Return {ticker: [_FiveMinBar, ...]} for `replay_date` only."""
        all_bars = fetch_bars(
            self.tickers,
            self.replay_date,
            self.replay_date,
            source="alpaca",
            allow_intraday=True,
        )

        result = {}
        for ticker, df in all_bars.items():
            if df.empty:
                result[ticker] = []
                continue
            day_df = df[[ts.date() == self.replay_date for ts in df.index]]
            bars = []
            for ts, row in day_df.iterrows():
                bars.append(
                    _FiveMinBar(
                        symbol=ticker,
                        timestamp=ts,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]),
                    )
                )
            result[ticker] = bars

        return result

    def _build_timeline(self, bars_by_ticker: dict) -> list:
        all_bars = [b for bars_list in bars_by_ticker.values() for b in bars_list]
        return sorted(all_bars, key=lambda b: b.timestamp)
