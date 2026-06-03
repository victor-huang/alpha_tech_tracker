import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_HOLD_WINDOWS = ["+15m", "+30m", "+1h", "+2h", "+3h", "+5h", "EOD"]

# Seasonal defaults: (direction, hold_window or None)
_SEASONAL = {
    1:  ("LONG",        "EOD"),
    2:  ("NEUTRAL",     "+30m"),
    3:  ("NO_POSITION", None),
    4:  ("NEUTRAL",     "+1h"),
    5:  ("LONG",        "+1h"),
    6:  ("NEUTRAL",     "+1h"),
    7:  ("NEUTRAL",     "EOD"),
    8:  ("NEUTRAL",     "+15m"),
    9:  ("SHORT",       "+15m"),
    10: ("LONG",        "EOD"),
    11: ("NEUTRAL",     None),
    12: ("SHORT",       "+1h"),
}

_SEASONAL_NOTES = {
    3:  "NO_POSITION — wait for day-3 confirmation before trading",
    11: "NEUTRAL — wait for week-1 EV check before applying rolling regime",
}


def _today_month() -> int:
    return date.today().month


@dataclass
class DailyRegimeMetrics:
    date: date
    signal_count: int
    eod_wr: float
    avg_gain: float
    avg_win: float
    avg_loss: float
    hold_curve: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "signal_count": self.signal_count,
            "eod_wr": self.eod_wr,
            "avg_gain": self.avg_gain,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "hold_curve": self.hold_curve,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DailyRegimeMetrics":
        return cls(
            date=date.fromisoformat(d["date"]),
            signal_count=d["signal_count"],
            eod_wr=d["eod_wr"],
            avg_gain=d["avg_gain"],
            avg_win=d["avg_win"],
            avg_loss=d["avg_loss"],
            hold_curve=d.get("hold_curve", {}),
        )


@dataclass
class RegimeState:
    direction: str    # "LONG" | "SHORT" | "NEUTRAL" | "NO_POSITION"
    hold_window: str  # "+15m" | "+30m" | "+1h" | "+2h" | "+3h" | "+5h" | "EOD" | ""
    regime_type: str  # e.g. "Rising Bull", "AM Pop-Fade", "Seasonal Default", ...
    source: str       # "seasonal" | "rolling_confirmed" | "transition"
    notes: str        # human-readable for logging / SMS


class RegimeEngine:
    def __init__(self, data_dir: str = "market_data/regime_state"):
        self._data_dir = data_dir
        self._history: List[DailyRegimeMetrics] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _json_path(self, year: int) -> str:
        os.makedirs(self._data_dir, exist_ok=True)
        return os.path.join(self._data_dir, f"regime_metrics_{year}.json")

    def _load(self) -> None:
        """Load the last 10 records across the two most recent year files."""
        records: List[DailyRegimeMetrics] = []
        current_year = date.today().year
        for year in (current_year - 1, current_year):
            path = self._json_path(year)
            if not os.path.exists(path):
                continue
            try:
                with open(path) as f:
                    for d in json.load(f):
                        records.append(DailyRegimeMetrics.from_dict(d))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load regime metrics from %s: %s", path, exc)
        records.sort(key=lambda m: m.date)
        self._history = records[-10:]

    def add_daily_result(self, metrics: DailyRegimeMetrics) -> None:
        """Append to in-memory history and persist to JSON. Skips duplicate dates."""
        existing_dates = {m.date for m in self._history}
        if metrics.date in existing_dates:
            logger.debug("Skipping duplicate date %s in regime history", metrics.date)
            return

        self._history.append(metrics)
        self._history.sort(key=lambda m: m.date)
        if len(self._history) > 10:
            self._history = self._history[-10:]

        path = self._json_path(metrics.date.year)
        existing: List[dict] = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, KeyError):
                existing = []

        existing_json_dates = {r["date"] for r in existing}
        if metrics.date.isoformat() not in existing_json_dates:
            existing.append(metrics.to_dict())
            with open(path, "w") as f:
                json.dump(existing, f, indent=2)

    # ------------------------------------------------------------------
    # Layer 1 — Seasonal prior
    # ------------------------------------------------------------------

    def _seasonal_prior(self, month: int) -> RegimeState:
        direction, hold_window = _SEASONAL[month]
        note = _SEASONAL_NOTES.get(month, f"Seasonal default for month {month}")
        return RegimeState(
            direction=direction,
            hold_window=hold_window or "",
            regime_type="Seasonal Default",
            source="seasonal",
            notes=note,
        )

    # ------------------------------------------------------------------
    # Layer 2 — Five-day rolling check
    # ------------------------------------------------------------------

    def _rolling_check(self, history: List[DailyRegimeMetrics]) -> Optional[RegimeState]:
        """Return a RegimeState if ≥3 days of history match a known pattern, else None."""
        if len(history) < 3:
            return None

        recent = history[-5:]

        # Specific patterns first — each can overlap with Rising Bull curve shape

        # High-WR Trap: WR looks good but avg_gain ≤ 0 — override apparent bull signal
        if self._all_match(recent, self._is_high_wr_trap):
            return RegimeState("LONG", "+15m", "High-WR Trap", "rolling_confirmed",
                               "EOD WR ≥ 55% but avg_gain ≤ 0 — exit early")

        # Persistent Bear: EOD WR < 40% AND hold curve declining
        if self._all_match(recent, self._is_persistent_bear):
            return RegimeState("SHORT", "EOD", "Persistent Bear", "rolling_confirmed",
                               "EOD WR < 40% and hold curve declining across all windows")

        # U-Curve: AM negative, midday bear, EOD recovery
        if self._all_match(recent, self._is_u_curve):
            return RegimeState("LONG", "+3h", "U-Curve", "rolling_confirmed",
                               "AM negative, midday bear, EOD recovery — enter after +3h")

        # Low-WR Positive EV: EOD WR < 50%, avg_win ≥ 1.5 × |avg_loss|
        if self._all_match(recent, self._is_low_wr_positive_ev):
            return RegimeState("LONG", "+5h", "Low-WR Positive EV", "rolling_confirmed",
                               "Low WR but avg_win ≥ 1.5× |avg_loss| — hold long for EV")

        # AM Pop-Fade: +15m positive, drops ≥15pp by +30m
        if self._all_match(recent, self._is_am_pop_fade):
            return RegimeState("LONG", "+15m", "AM Pop-Fade", "rolling_confirmed",
                               "+15m win rate high, drops ≥15pp by +30m — fade pattern")

        # Rising Bull: generic fallback — hold curve rises +15m→+3h→EOD
        if self._all_match(recent, self._is_rising_bull):
            return RegimeState("LONG", "EOD", "Rising Bull", "rolling_confirmed",
                               "Hold curve rising from AM to EOD across all recent days")

        return None

    def _all_match(self, days, predicate) -> bool:
        return len(days) >= 3 and all(predicate(d) for d in days)

    def _is_rising_bull(self, m: DailyRegimeMetrics) -> bool:
        c = m.hold_curve
        return (
            c.get("+15m", 0) < c.get("+3h", 0)
            and c.get("+3h", 0) < c.get("EOD", 0)
        )

    def _is_am_pop_fade(self, m: DailyRegimeMetrics) -> bool:
        c = m.hold_curve
        am = c.get("+15m", 0)
        half = c.get("+30m", 0)
        return am > 0.50 and (am - half) >= 0.15

    def _is_persistent_bear(self, m: DailyRegimeMetrics) -> bool:
        c = m.hold_curve
        return (
            m.eod_wr < 0.40
            and c.get("+15m", 1) > c.get("+30m", 1)
            and c.get("+30m", 1) > c.get("EOD", 1)
        )

    def _is_high_wr_trap(self, m: DailyRegimeMetrics) -> bool:
        return m.eod_wr >= 0.55 and m.avg_gain <= 0

    def _is_low_wr_positive_ev(self, m: DailyRegimeMetrics) -> bool:
        return m.eod_wr < 0.50 and m.avg_win >= 1.5 * abs(m.avg_loss)

    def _is_u_curve(self, m: DailyRegimeMetrics) -> bool:
        c = m.hold_curve
        am = c.get("+15m", 1)
        mid = c.get("+1h", 1)
        eod = c.get("EOD", 0)
        # AM below 50%, dips in midday, recovers by EOD
        return am < 0.50 and mid < am and eod > mid and eod > 0.55

    # ------------------------------------------------------------------
    # Layer 3 — Transition detection
    # ------------------------------------------------------------------

    def _transition_check(self, history: List[DailyRegimeMetrics]) -> Optional[RegimeState]:
        if len(history) < 2:
            return None

        recent = history[-10:]

        # Bear → Bull: any single day EOD WR ≥ 70% after ≥5 consecutive days < 40%
        if self._detect_bear_to_bull(recent):
            return RegimeState("LONG", "EOD", "Transition: Bear→Bull", "transition",
                               "EOD WR ≥ 70% after ≥5 consecutive bear days — LONG from next session")

        # Bull → Bear: 3 consecutive days < 40% + declining curve + loss/win > 0.80
        if self._detect_bull_to_bear(recent):
            return RegimeState("SHORT", "EOD", "Transition: Bull→Bear", "transition",
                               "3 consecutive low-WR days with declining curve and high loss ratio — SHORT")

        return None

    def _detect_bear_to_bull(self, recent: List[DailyRegimeMetrics]) -> bool:
        if len(recent) < 6:
            return False
        last = recent[-1]
        if last.eod_wr < 0.70:
            return False
        # Count consecutive bear days immediately before the last day
        bear_streak = 0
        for m in reversed(recent[:-1]):
            if m.eod_wr < 0.40:
                bear_streak += 1
            else:
                break
        return bear_streak >= 5

    def _detect_bull_to_bear(self, recent: List[DailyRegimeMetrics]) -> bool:
        if len(recent) < 3:
            return False
        last3 = recent[-3:]
        # ① 3 consecutive days EOD WR < 40%
        if not all(m.eod_wr < 0.40 for m in last3):
            return False
        # ② Hold curve declining at every window for all 3 days
        if not all(self._curve_fully_declining(m) for m in last3):
            return False
        # ③ avg_loss / avg_win ratio > 0.80 (use most recent day)
        last = last3[-1]
        if last.avg_win == 0:
            return False
        return abs(last.avg_loss) / last.avg_win > 0.80

    def _curve_fully_declining(self, m: DailyRegimeMetrics) -> bool:
        c = m.hold_curve
        return (
            c.get("+15m", 1) > c.get("+1h", 1)
            and c.get("+1h", 1) > c.get("EOD", 1)
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_current_regime(self, presession_top2_wr: float = None) -> RegimeState:
        """
        Apply layers 1–3 in order. Layer 3 (transition) has highest priority.
        presession_top2_wr is Layer 4 input used only in screener run_live().
        """
        month = _today_month()

        seasonal = self._seasonal_prior(month)
        rolling = self._rolling_check(self._history)
        transition = self._transition_check(self._history)

        if transition is not None:
            return transition
        if rolling is not None:
            return rolling
        return seasonal

    def summary_str(self) -> str:
        regime = self.get_current_regime()
        hold = f" | Hold: {regime.hold_window}" if regime.hold_window else ""
        return f"Regime: {regime.direction}{hold} [{regime.regime_type}] — {regime.notes}"
