"""Down-market short setups for the wave setup monitor (alerts only), switched on for a session by a market gate.

Tested on nine down markets 2020-2026 with the gate on (ticker-tuning doc, Finding 37), two shorts held up and are
the defaults (DEFAULT_SHORT_SETUPS): drive (7 of 9 windows) and overnight (7 of 9, largest in crashes, largest risk
when the gate is wrong). retest is opt-in: once a same-bar look-ahead in the study was fixed it made money in only 5
of 9 windows and lost overall.

  retest     a short limit at the retest of the last confirmed rally high: once the wave model (RETEST_SETTING:
             3-bar waves, 23.6% retrace, 3 average bars) confirms a turn down, a sell limit RETEST_OFFSET x ADR
             below that wave's high, from the next bar, only while the previous close is below it; RETEST_WINDOW,
             at most RETEST_MAX_PER_DAY a day; stop RETEST_BUFFER x ADR above the high, lowered to each new
             confirmed rally high; covered at the close
  drive      drive short: a red first 5-min bar is shorted at its close, stop its high, covered at the close; after
             a stop-out, one re-entry on the first close back below that high (before REENTRY_LATEST), no stop
  overnight  short the close, cover at the next open; nights into an earnings release are skipped

Gate (decided on the previous daily close, for the whole session): `qqq-ma50` = QQQ closed below its 50-day MA;
`always`; `off`. The gate is a function of the daily closes so a better market indicator can replace it.
"""

from collections import deque
from datetime import time

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import BAR_INTERVAL, BARS_PER_SESSION
from alpha_tech_tracker.wave import Wave

SHORT_SETUPS = ("retest", "drive", "overnight")
DEFAULT_SHORT_SETUPS = ("drive", "overnight")
SETUP_NAMES = {"retest": "short retest", "drive": "short drive", "drive re-entry": "short drive re-entry",
               "overnight": "short overnight"}
GATES = ("qqq-ma50", "always", "off")
GATE_TICKER = "QQQ"
GATE_MA = 50
RETEST_SETTING = (3, 0.236, 3.0)
RETEST_OFFSET = 0.05
RETEST_BUFFER = 0.2
RETEST_WINDOW = (time(10, 0), time(15, 0))
RETEST_MAX_PER_DAY = 2
REENTRY_LATEST = time(15, 0)
ADR_SESSIONS = 20


def gate_status(gate, closes):
    """(on, text) for a session from the gate ticker's daily closes before it."""
    if gate == "always":
        return True, "short setups on (gate: always)"
    if gate == "off":
        return False, "short setups off (gate: off)"
    if len(closes) < GATE_MA:
        return False, f"short setups off: {GATE_TICKER} has {len(closes)} daily closes, the gate needs {GATE_MA}"
    last, ma = closes[-1], sum(closes[-GATE_MA:]) / GATE_MA
    state = "on" if last < ma else "off"
    relation = "below" if last < ma else "above"
    return last < ma, f"short setups {state}: {GATE_TICKER} closed {last:.2f}, {relation} its {GATE_MA}-day MA {ma:.2f}"


class RallyTracker:
    """Bar-by-bar wave replay (waves reset at each session open) reporting confirmed turns down and the rally high."""

    def __init__(self, min_length, bounce, min_ranges):
        self.min_length, self.bounce, self.min_ranges = min_length, bounce, min_ranges
        self.range_pcts = deque(maxlen=BARS_PER_SESSION)
        self.wave = None

    def update(self, stamp, bar):
        """The confirmed rally's high (its highest wick) when this bar confirms a turn down, else None."""
        self.range_pcts.append((bar["high"] - bar["low"]) / bar["close"])
        min_change = self.min_ranges * sum(self.range_pcts) / len(self.range_pcts)
        if self.wave is None or stamp.date() != self.wave.df.index[-1].date():
            self.wave = self._new_wave(stamp, bar, min_change)
            return None
        self.wave.minimum_wave_price_change = min_change
        before = self.wave.direction()
        new_wave = self.wave.count(stamp, bar, time_increment=BAR_INTERVAL)
        if not new_wave:
            return None
        new_wave.minimum_wave_length, new_wave.bounce_threshold = self.min_length, self.bounce
        peak = float(self.wave.df["high"].max()) if before == "up" else None
        self.wave = new_wave
        return peak

    def _new_wave(self, stamp, bar, min_change):
        wave = Wave(stamp, bar, minimum_wave_price_change=min_change)
        wave.minimum_wave_length, wave.bounce_threshold = self.min_length, self.bounce
        return wave


class RetestShort:
    """One ticker's retest-short signals: `update(stamp, bar, adr, in_position, last_bar)` per closed 5-min bar returns
    events — {"kind": "trail", "peak"}, {"kind": "entry", "fill", "stop", "stopped"}, {"kind": "arm", "level", "stop"}.
    The caller owns the position (stop checks, the close); this class owns the rally highs and the daily entry count.
    """

    def __init__(self, ticker, setting=RETEST_SETTING):
        self.ticker = ticker
        self.tracker = RallyTracker(*setting)
        self.last_peak = None
        self.previous_close = None
        self.session = None
        self.entries = 0
        self.armed = None
        self.last_time = None

    def update(self, stamp, bar, adr, in_position, last_bar=False):
        if self.last_time is not None and stamp <= self.last_time:
            return []
        self.last_time = stamp
        if stamp.date() != self.session:
            self.session, self.entries, self.last_peak, self.previous_close, self.armed = stamp.date(), 0, None, None, None
        known_peak, previous_close = self.last_peak, self.previous_close
        self.previous_close = bar["close"]
        events = []
        peak = self.tracker.update(stamp, bar)
        if peak is not None:
            self.last_peak = peak
            if in_position:
                events.append({"kind": "trail", "peak": peak})
        if not in_position and not last_bar:
            entry = self._entry(stamp, bar, adr, known_peak, previous_close)
            if entry:
                events.append(entry)
                in_position = not entry["stopped"]
        arm = None if in_position or last_bar else self._arm(stamp, bar, adr)
        if arm and (self.armed is None or abs(arm["level"] - self.armed) > 1e-9):
            events.append(arm)
        self.armed = arm["level"] if arm else None
        return events

    def _in_window(self, stamp):
        return RETEST_WINDOW[0] <= stamp.time() < RETEST_WINDOW[1] and self.entries < RETEST_MAX_PER_DAY

    def _entry(self, stamp, bar, adr, peak, previous_close):
        if peak is None or previous_close is None or not adr or not self._in_window(stamp):
            return None
        level = peak - RETEST_OFFSET * adr
        if not previous_close < level or bar["high"] < level:
            return None
        fill, stop = max(bar["open"], level), peak + RETEST_BUFFER * adr
        if fill >= stop:
            return None
        self.entries += 1
        return {"kind": "entry", "fill": fill, "stop": stop, "stopped": bar["high"] >= stop}

    def _arm(self, stamp, bar, adr):
        """The sell limit standing for the next bar, if any (the trader places it after this bar's close)."""
        if self.last_peak is None or not adr or self.entries >= RETEST_MAX_PER_DAY:
            return None
        next_bar = (stamp + BAR_INTERVAL).time()
        if not RETEST_WINDOW[0] <= next_bar < RETEST_WINDOW[1]:
            return None
        level = self.last_peak - RETEST_OFFSET * adr
        if not bar["close"] < level:
            return None
        return {"kind": "arm", "level": level, "stop": self.last_peak + RETEST_BUFFER * adr}


def next_session_adr(bars, session, sessions=ADR_SESSIONS):
    """The ADR for `session` from the bars of the sessions before it."""
    days = sorted(d for d in set(bars.index.date) if d < session)[-sessions:]
    if len(days) < sessions:
        return None
    ranges = [float(bars[bars.index.date == d]["high"].max() - bars[bars.index.date == d]["low"].min()) for d in days]
    return sum(ranges) / len(ranges)
