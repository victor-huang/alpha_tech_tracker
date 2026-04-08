import abc
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, time as _time
from itertools import groupby
from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _FiveMinBar
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


# ── Bar data sources ──────────────────────────────────────────────────────────


class LiveBarsSource(abc.ABC):
    """Interface for supplying intraday 5-min bars to the replay driver.

    Implement this to add new data sources (e.g. a different CSV schema,
    a local database, a remote API).  The driver calls `load()` once at
    the start of `run()` and feeds the returned bars through the signal
    engine in chronological order.
    """

    @abc.abstractmethod
    def load(
        self, tickers: List[str], replay_date: date
    ) -> "dict[str, List[_FiveMinBar]]":
        """Return {ticker: [_FiveMinBar, ...]} for the given date.

        Missing or empty tickers should map to an empty list, not raise.
        """


class CsvLiveBarsSource(LiveBarsSource):
    """Loads 5-min bars from BarRecorder CSV files.

    Expects files at: {base_dir}/{replay_date}/{ticker}_5min.csv
    CSV schema: timestamp,open,high,low,close,volume
      - timestamps are naive ET strings (e.g. "2026-04-02 09:30:00")
    """

    def __init__(self, base_dir: str):
        self._base_dir = Path(base_dir)

    def load(
        self, tickers: List[str], replay_date: date
    ) -> "dict[str, List[_FiveMinBar]]":
        date_dir = self._base_dir / str(replay_date)
        result = {}
        for ticker in tickers:
            csv_path = date_dir / f"{ticker}_5min.csv"
            if not csv_path.exists():
                logger.warning(
                    "CsvLiveBarsSource: no file for %s at %s", ticker, csv_path
                )
                result[ticker] = []
                continue
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            bars = []
            for _, row in df.iterrows():
                ts = ET.localize(row["timestamp"].to_pydatetime())
                bars.append(
                    _FiveMinBar(
                        symbol=ticker,
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
            result[ticker] = bars
            logger.info(
                "CsvLiveBarsSource: loaded %d bars for %s", len(bars), ticker
            )
        return result


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

    After `run()` returns, `last_bar_time` holds the timestamp of the final bar
    so the caller can re-pin the replay clock before running any post-session
    logic (e.g. EOD close_all).
    """

    tickers: list
    replay_date: date
    signal_engine: object  # LiveSignalEngine
    on_bar_injected: Optional[Callable[[str], None]] = None
    last_bar_time: Optional[datetime] = None
    bars_source: Optional[LiveBarsSource] = None
    exit_time: str = "14:55"

    def run(self):
        bars_by_ticker = self._fetch_session_bars()
        timeline = self._build_timeline(bars_by_ticker)

        logger.info(
            "Replay %s — %d 5-min bars across %d tickers",
            self.replay_date,
            len(timeline),
            len([t for t, b in bars_by_ticker.items() if b]),
        )

        # Group bars by timestamp so all tickers' bars at the same time are fully
        # processed by the signal engine before any drain/monitor callbacks fire.
        # This ensures that tickers with a missing bar at the OR open time (whose
        # signal fires on the OR-close bar) are still buffered before the drain.
        for ts, ts_group in groupby(timeline, key=lambda b: b.timestamp):
            group_bars = list(ts_group)
            set_replay_clock(lambda t=ts: t)
            self.last_bar_time = ts
            for bar in group_bars:
                self.signal_engine._process_five_min_bar(bar)
            if self.on_bar_injected:
                for bar in group_bars:
                    self.on_bar_injected(bar.symbol)

        clear_replay_clock()
        logger.info("Replay %s complete", self.replay_date)

    def _fetch_session_bars(self) -> dict:
        """Return {ticker: [_FiveMinBar, ...]} for `replay_date` only.

        Delegates to `bars_source.load()` when a source is provided,
        otherwise falls back to the Alpaca cache via fetch_bars.
        """
        if self.bars_source is not None:
            logger.info(
                "Replay %s — loading bars from %s",
                self.replay_date,
                type(self.bars_source).__name__,
            )
            return self.bars_source.load(self.tickers, self.replay_date)

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
        exit_h, exit_m = [int(x) for x in self.exit_time.split(":")]
        cutoff = _time(exit_h, exit_m)
        all_bars = [
            b
            for bars_list in bars_by_ticker.values()
            for b in bars_list
            if b.timestamp.time() < cutoff
        ]
        return sorted(all_bars, key=lambda b: b.timestamp)
