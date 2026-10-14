"""Reversal candles at wave lows and highs, bar by bar, for the wave setup monitor's alerts.

Replays 5-min bars through the wave model the way `wave_risk_reward.analyze_bars` builds it (waves end at each
session close; minimum wave size = DEFAULT_MIN_WAVE_BAR_RANGES x the trailing 78-bar average range %) and checks
each closed bar for a candidate low or high, using only that bar and the bars before it:

  bottom candidate  the current wave is down, it has fallen at least CANDIDATE_MOVE_BARS average bars (trailing
                    78-bar mean high - low) from its high to this bar's low, and this bar's low is within
                    CANDIDATE_NEAR_BARS average bar of the wave's lowest low so far
  top candidate     the mirror

On a candidate it checks the reversal patterns that marked real wave extremes most often in
research/ticker_characteristic (7 tickers, 2025 and 2026; about 27-31% of candidates are at the real extreme):

  piercing   piercing line at a bottom, dark cloud cover at a top (previous bar + this bar)
  push       push reversal (previous bar + this bar)
  long_tail  a long tail on a candidate bar, confirmed by the next bar closing beyond it (one bar late)

These say where a wave may be turning, not that a trade pays: they have not been backtested for P&L.
"""

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    BAR_INTERVAL,
    BARS_PER_SESSION,
    DEFAULT_MIN_WAVE_BAR_RANGES,
)
from alpha_tech_tracker.technical_analysis import confirmed_long_tail_reversal, piercing_reversal, push_reversal
from alpha_tech_tracker.wave import Wave

PATTERNS = ("piercing", "push", "long_tail")
CANDIDATE_MOVE_BARS = 3
CANDIDATE_NEAR_BARS = 1
MIN_AVERAGE_BARS = 20
FIRST_CANDIDATE_BAR = 2  # the session's third bar (09:40), as in the study
PATTERN_NAMES = {("piercing", "bottom"): "piercing", ("piercing", "top"): "dark cloud",
                 ("push", "bottom"): "push", ("push", "top"): "push",
                 ("long_tail", "bottom"): "long tail + confirm", ("long_tail", "top"): "long tail + confirm"}


@dataclass
class ReversalSignal:
    ticker: str
    time: datetime
    side: str
    pattern: str
    price: float
    extreme: float
    move_bars: float

    @property
    def key(self):
        return f"{self.ticker}|reversal {self.pattern} {self.side}|{self.time.isoformat()}"


def reversal_message(signals):
    """One alert for the signals a bar fired on one side (same ticker, time and side)."""
    first = signals[0]
    wave, extreme = ("down", "low") if first.side == "bottom" else ("up", "high")
    names = " + ".join(PATTERN_NAMES[(s.pattern, s.side)] for s in signals)
    return (f"{extreme.upper()}? {first.ticker} | {names} | ~{first.price:.2f} ({first.time:%H:%M} bar close) | "
            f"wave {wave} {first.move_bars:.1f} avg bars, {extreme} {first.extreme:.2f}")


def _candle(bar):
    return (bar["close"], bar["open"], bar["high"], bar["low"])


class ReversalWatch:
    """One ticker's wave replay; `update(time, bar)` per closed 5-min bar returns the ReversalSignals it fires."""

    def __init__(self, ticker, patterns=PATTERNS):
        self.ticker = ticker
        self.patterns = set(patterns)
        self.wave = None
        self.run_low = self.run_high = None
        self.ranges = deque(maxlen=BARS_PER_SESSION)
        self.range_pcts = deque(maxlen=BARS_PER_SESSION)
        self.previous = None
        self.last_time = None
        self.session_bar = 0

    @classmethod
    def from_bars(cls, ticker, frame, patterns=PATTERNS):
        """A watch warmed up on `frame` (sorted bars: open, high, low, close); the replay fires nothing.

        Waves reset at each session open and the averages look back BARS_PER_SESSION bars, so only the last
        session and the sessions holding the BARS_PER_SESSION bars before it are replayed.
        """
        watch = cls(ticker, patterns)
        prices = frame[["open", "high", "low", "close"]]
        frame = frame[((prices > 0) & (prices < float("inf"))).all(axis=1)]
        if frame.empty:
            return watch
        dates = frame.index.date
        before_last_session = int((dates < dates[-1]).sum())
        start = max(0, before_last_session - BARS_PER_SESSION)
        start = int((dates < dates[start]).sum())
        for stamp, row in frame.iloc[start:].iterrows():
            watch.update(stamp, {k: float(row[k]) for k in ("open", "high", "low", "close")})
        return watch

    def update(self, time, bar):
        if self.last_time is not None and time <= self.last_time:
            return []
        bar = {k: float(bar[k]) for k in ("open", "high", "low", "close")}
        if not all(math.isfinite(v) and v > 0 for v in bar.values()):
            return []
        self.last_time = time
        average_bar = sum(self.ranges) / len(self.ranges) if len(self.ranges) >= MIN_AVERAGE_BARS else None
        bar_range = bar["high"] - bar["low"]
        self.ranges.append(bar_range)
        self.range_pcts.append(bar_range / bar["close"])
        self.session_bar = 0 if self._count(time, bar) else self.session_bar + 1

        current = {"time": time, "bar": bar, "sides": []}
        if self.session_bar >= FIRST_CANDIDATE_BAR and average_bar:
            current["sides"] = self._candidate_sides(bar, average_bar)
        current["average_bar"] = average_bar
        previous = self.previous if self.previous and self.previous["time"].date() == time.date() else None
        self.previous = current
        return self._signals(previous, current) if previous else []

    def _count(self, time, bar):
        min_wave_change = DEFAULT_MIN_WAVE_BAR_RANGES * sum(self.range_pcts) / len(self.range_pcts)
        if self.wave is None or time.date() != self.wave.df.index[-1].date():
            self.wave = Wave(time, bar, minimum_wave_price_change=min_wave_change)
            self.run_low, self.run_high = bar["low"], bar["high"]
            return True
        self.wave.minimum_wave_price_change = min_wave_change
        new_wave = self.wave.count(time, bar, time_increment=BAR_INTERVAL)
        if new_wave:
            self.wave = new_wave
            self.run_low, self.run_high = float(new_wave.df["low"].min()), float(new_wave.df["high"].max())
        else:
            self.run_low, self.run_high = min(self.run_low, bar["low"]), max(self.run_high, bar["high"])
        return False

    def _candidate_sides(self, bar, average_bar):
        sides = []
        direction = self.wave.direction()
        if (direction == "down" and self.wave.high - bar["low"] >= CANDIDATE_MOVE_BARS * average_bar
                and bar["low"] <= self.run_low + CANDIDATE_NEAR_BARS * average_bar):
            sides.append(("bottom", (self.wave.high - bar["low"]) / average_bar, self.run_low))
        if (direction == "up" and bar["high"] - self.wave.low >= CANDIDATE_MOVE_BARS * average_bar
                and bar["high"] >= self.run_high - CANDIDATE_NEAR_BARS * average_bar):
            sides.append(("top", (bar["high"] - self.wave.low) / average_bar, self.run_high))
        return sides

    def _signals(self, previous, current):
        fired = []
        bar = current["bar"]
        pair = [_candle(previous["bar"]), _candle(bar)]
        for side, move_bars, extreme in current["sides"]:
            trend = "up" if side == "bottom" else "down"
            minimum = current["average_bar"] / bar["close"]
            if "piercing" in self.patterns and piercing_reversal(pair, trend=trend, daily_movement_minimum=minimum):
                fired.append(self._signal(current, side, "piercing", move_bars, extreme))
            if "push" in self.patterns and push_reversal(pair, trend=trend, daily_movement_minimum=minimum):
                fired.append(self._signal(current, side, "push", move_bars, extreme))
        if "long_tail" in self.patterns:
            for side, move_bars, extreme in previous["sides"]:
                trend = "up" if side == "bottom" else "down"
                minimum = previous["average_bar"] / previous["bar"]["close"]
                if confirmed_long_tail_reversal(pair, trend=trend, daily_movement_minimum=minimum):
                    fired.append(self._signal(current, side, "long_tail", move_bars, extreme))
        return fired

    def _signal(self, current, side, pattern, move_bars, extreme):
        return ReversalSignal(ticker=self.ticker, time=current["time"], side=side, pattern=pattern,
                              price=current["bar"]["close"], extreme=extreme, move_bars=move_bars)
