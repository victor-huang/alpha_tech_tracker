import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _add_ma_columns,
    _forward_pct,
    _rank_tickers_by_eod_win_rate,  # noqa: F401 — re-exported for trade_engine.py
    compute_or_ma_signals,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

logger = logging.getLogger(__name__)

# Minutes per hold window, None = EOD
_HIST_HOLD_MIN = [15, 30, 60, 120, 180, 300, None]

# Mapping from hold_min to hold label used in hold_curve dict
_HOLD_WINDOW_LABELS: Dict[Optional[int], str] = {
    15: "+15m",
    30: "+30m",
    60: "+1h",
    120: "+2h",
    180: "+3h",
    300: "+5h",
    None: "EOD",
}

# Seasonal defaults: (direction, hold_window or None)
_SEASONAL = {
    1:  ("LONG",        "EOD"),
    2:  ("NEUTRAL",     "+30m"),
    3:  ("NO_POSITION", None),
    4:  ("NEUTRAL",     "+1h"),
    5:  ("LONG",        "EOD"),
    6:  ("NEUTRAL",     "+1h"),
    7:  ("NEUTRAL",     "EOD"),
    8:  ("NEUTRAL",     "+15m"),
    9:  ("SHORT",       "+30m"),
    10: ("LONG",        "EOD"),
    11: ("NEUTRAL",     None),
    12: ("SHORT",       "+2h"),
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

        # Rolling Long: EOD WR ≥ 60% + positive EV — genuine bull regime
        if self._all_match(recent, self._is_rolling_long):
            if self._all_match(recent, self._is_rising_bull):
                return RegimeState("LONG", "+5h", "Rolling Long + Rising Bull", "rolling_confirmed",
                                   "EOD WR ≥ 60% + positive EV + rising hold curve — maximize hold to +5h")
            return RegimeState("LONG", "EOD", "Rolling Long", "rolling_confirmed",
                               "EOD WR ≥ 60% + positive EV — LONG regime, hold to EOD")

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

    def _is_rolling_long(self, m: DailyRegimeMetrics) -> bool:
        return m.eod_wr >= 0.60 and m.avg_gain > 0

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

    # ------------------------------------------------------------------
    # Layer 4 — Pre-session top-2 independence rule
    # ------------------------------------------------------------------

    def _apply_presession_override(
        self, regime: RegimeState, presession_top2_wr: float
    ) -> RegimeState:
        """Positive divergence: pre-session top-2 EOD WR ≥ 60% overrides fade/bear/neutral."""
        if presession_top2_wr < 0.60:
            return regime
        if regime.direction == "LONG":
            return regime
        return RegimeState(
            "LONG", "EOD", "Pre-Session Override", "transition",
            f"Pre-session top-2 EOD WR {presession_top2_wr:.1%} ≥ 60% overrides "
            f"{regime.direction} [{regime.regime_type}] — LONG EOD",
        )

    def _curve_fully_declining(self, m: DailyRegimeMetrics) -> bool:
        c = m.hold_curve
        return (
            c.get("+15m", 1) > c.get("+1h", 1)
            and c.get("+1h", 1) > c.get("EOD", 1)
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_current_regime(
        self,
        presession_top2_wr: float = None,
        as_of_date: date = None,
    ) -> RegimeState:
        """
        Apply layers 1–3 in order. Layer 3 (transition) has highest priority.
        presession_top2_wr is Layer 4 input used only in screener run_live().
        as_of_date overrides today's date for month-based seasonal prior — pass
        the replay clock date in replay mode so the correct seasonal prior is used.
        """
        month = as_of_date.month if as_of_date is not None else _today_month()

        seasonal = self._seasonal_prior(month)
        rolling = self._rolling_check(self._history)
        transition = self._transition_check(self._history)

        if transition is not None:
            regime = transition
        elif rolling is not None:
            regime = rolling
        else:
            regime = seasonal

        if presession_top2_wr is not None:
            regime = self._apply_presession_override(regime, presession_top2_wr)

        return regime

    def summary_str(self, as_of_date: date = None) -> str:
        regime = self.get_current_regime(as_of_date=as_of_date)
        hold = f" | Hold: {regime.hold_window}" if regime.hold_window else ""
        return f"Regime: {regime.direction}{hold} [{regime.regime_type}] — {regime.notes}"

    # ------------------------------------------------------------------
    # Phase 2 — daily metrics computation
    # ------------------------------------------------------------------

    def compute_and_add_metrics(
        self,
        warmup_bars: dict,
        target_date: date,
        or_start: str,
        or_bars: int,
        collection_bars: int,
        source: str = "alpaca",
        feed: DataFeed = DataFeed.SIP,
    ) -> Optional[DailyRegimeMetrics]:
        """
        Compute DailyRegimeMetrics for target_date using warmup_bars.

        Returns cached record immediately if target_date already in history.
        Returns None if fewer than 3 signals fired on target_date.
        QQQ is resolved from warmup_bars["QQQ"] if present, otherwise fetched
        internally using fetch_bars(["QQQ"], ...).
        """
        cached = next((m for m in self._history if m.date == target_date), None)
        if cached is not None:
            logger.debug("Regime metrics cache hit for %s", target_date)
            return cached

        # Resolve QQQ bars
        if "QQQ" in warmup_bars:
            qqq_bars = warmup_bars["QQQ"]
        else:
            logger.info("QQQ not in warmup_bars — fetching internally for %s", target_date)
            dates_list = [
                df.index.min().date() for df in warmup_bars.values()
                if df is not None and not df.empty and hasattr(df.index, "date")
            ]
            fetch_start = min(dates_list) if dates_list else target_date - timedelta(days=45)
            qqq_raw = fetch_bars(["QQQ"], fetch_start, target_date, source=source, feed=feed)
            qqq_raw_df = qqq_raw.get("QQQ", pd.DataFrame())
            qqq_bars = _add_ma_columns(qqq_raw_df) if not qqq_raw_df.empty else pd.DataFrame()

        # Build ticker bars with MA columns; exclude QQQ from signal scan
        ticker_bars = {}
        for t, df in warmup_bars.items():
            if t == "QQQ" or df is None or df.empty:
                continue
            ticker_bars[t] = _add_ma_columns(df)

        signals = compute_or_ma_signals(
            ticker_bars,
            qqq_bars,
            or_start,
            or_bars,
            target_date,
            collection_bars=collection_bars,
        )

        if len(signals) < 3:
            logger.info(
                "Only %d signals on %s — insufficient for regime metrics (need ≥3)",
                len(signals), target_date,
            )
            return None

        # Aggregate forward returns per hold window
        hold_returns: Dict[Optional[int], List[float]] = {h: [] for h in _HIST_HOLD_MIN}
        for sig in signals:
            ticker = sig["ticker"]
            signal_time = datetime.strptime(sig["signal_bar_time"], "%H:%M").time()
            signal_date = date.fromisoformat(sig["date"])
            day_df = ticker_bars.get(ticker)
            if day_df is None or day_df.empty:
                continue
            day_only = day_df[day_df.index.date == signal_date] if hasattr(day_df.index, "date") else day_df
            for hold_min in _HIST_HOLD_MIN:
                ret = _forward_pct(day_only, signal_time, signal_date, hold_min)
                if ret is not None:
                    hold_returns[hold_min].append(ret)

        eod_rets = hold_returns[None]
        if not eod_rets:
            return None

        wins = [r for r in eod_rets if r > 0]
        losses = [r for r in eod_rets if r <= 0]
        eod_wr = len(wins) / len(eod_rets)
        avg_gain = sum(eod_rets) / len(eod_rets)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        hold_curve = {
            _HOLD_WINDOW_LABELS[h]: len([r for r in hold_returns[h] if r > 0]) / len(hold_returns[h])
            for h in _HIST_HOLD_MIN
            if hold_returns[h]
        }

        metrics = DailyRegimeMetrics(
            date=target_date,
            signal_count=len(signals),
            eod_wr=eod_wr,
            avg_gain=avg_gain,
            avg_win=avg_win,
            avg_loss=avg_loss,
            hold_curve=hold_curve,
        )
        self.add_daily_result(metrics)
        return metrics
