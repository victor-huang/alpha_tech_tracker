"""
Direction-aware win-rate selector helpers.

Implements Rules 1–8 from DEV_PLAN_DIRECTION_AWARE_WINRATE_SELECTOR.md:
  - Rule 1: 90-calendar-day rolling lookback
  - Rule 2: min 10 directional trades required; below threshold → None (no proxy fallback)
  - Rule 3: direction_score = WR * (1 + avg_win_pct * 2)
  - Rule 4: floor threshold 45%
  - Rule 5: suppress when both sides < 45% for 45 consecutive trading days
  - Rule 6: recover when either side >= 50% for 20 consecutive trading days
  - Rule 7: fall back to overall WR when < 3 valid direction-specific scores in pool
  - Rule 8: new-ticker grace period via min_trades threshold
"""
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd


def compute_directional_stats(
    df: pd.DataFrame,
    target_date: date,
    lookback_days: int = 90,
    min_trades: int = 10,
    min_total_trades: int = 20,
) -> dict:
    """
    Compute direction-specific win-rate stats from a signals history DataFrame.

    Args:
        df: DataFrame with columns [date, signal, success, pnl, entry_price].
            signal is "BULLISH" or "BEARISH"; success is bool; pnl and entry_price are floats.
        target_date: The date we are computing stats for (acts as the lookback anchor).
        lookback_days: Calendar days to look back from target_date.
        min_trades: Minimum directional trades needed for a valid direction-specific score.
            Returns None for any direction with fewer than min_trades signals.
        min_total_trades: Unused; retained for API compatibility.

    Returns:
        {"bull": stats_dict | None, "bear": stats_dict | None}

        stats_dict keys:
          wr         – directional win rate (float, 0–1)
          avg_win_pct – average % P&L of winning trades in that direction (float)
          n          – number of directional trades in the window
          is_proxy   – always False (proxy fallback removed)
    """
    if df.empty:
        return {"bull": None, "bear": None}

    cutoff = target_date - timedelta(days=lookback_days)
    window = df[df["date"] >= cutoff]

    if window.empty:
        return {"bull": None, "bear": None}

    n_total = len(window)

    success = window["success"].to_numpy(dtype=bool)
    pnl = window["pnl"].to_numpy(dtype=float)
    entry = window["entry_price"].to_numpy(dtype=float)
    signal = window["signal"].to_numpy()

    bull_mask = signal == "BULLISH"
    bear_mask = signal == "BEARISH"

    n_bull = int(bull_mask.sum())
    n_bear = int(bear_mask.sum())

    def _dir_stats(mask, n_dir):
        s = success[mask]
        p = pnl[mask]
        e = entry[mask]
        wins = int(s.sum())
        wr = wins / n_dir
        win_p = p[s]
        win_e = e[s]
        avg_win_pct = float((win_p / win_e * 100).mean()) if len(win_p) > 0 else 0.0
        return {"wr": float(wr), "avg_win_pct": avg_win_pct, "n": n_dir, "is_proxy": False}

    def _resolve(n_dir, mask):
        if n_dir >= min_trades:
            return _dir_stats(mask, n_dir)
        return None

    return {"bull": _resolve(n_bull, bull_mask), "bear": _resolve(n_bear, bear_mask)}


def direction_score(wr: float, avg_win_pct: float) -> float:
    """
    Composite direction score: WR * (1 + avg_win_pct * 2).

    Rewards both high win rate and high magnitude of wins.
    avg_win_pct is expressed as a percentage (e.g. 1.0 for 1%).
    """
    return wr * (1 + avg_win_pct * 2)


def rank_tickers_direction_aware(
    ticker_stats: Dict[str, dict],
    direction: str,
    min_pool_valid: int = 3,
    fallback_overall_wr: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, float]]:
    """
    Rank tickers by direction-specific score for the given regime direction.

    Args:
        ticker_stats: {ticker: {"bull": stats_dict|None, "bear": stats_dict|None}}
        direction: "LONG" or "SHORT"
        min_pool_valid: Fall back to overall WR ranking when fewer than this many
                        tickers have valid direction-specific scores (Rule 7).
        fallback_overall_wr: {ticker: overall_wr} used when pool fallback triggers.

    Returns:
        Sorted list of (ticker, score) highest first.
    """
    if direction == "LONG":
        side = "bull"
    elif direction == "SHORT":
        side = "bear"
    else:
        raise ValueError(f"rank_tickers_direction_aware: unexpected direction {direction!r}; "
                         "caller should fall back to overall WR for CAUTION/NEUTRAL")

    scored = []
    for ticker, stats in ticker_stats.items():
        dir_stat = stats.get(side)
        if dir_stat is not None:
            score = direction_score(dir_stat["wr"], dir_stat["avg_win_pct"])
            scored.append((ticker, score))

    if len(scored) < min_pool_valid and fallback_overall_wr is not None:
        # Rule 7: not enough direction-specific scores — fall back to overall WR for full pool
        fallback = []
        for ticker, wr in fallback_overall_wr.items():
            fallback.append((ticker, wr))
        return sorted(fallback, key=lambda x: -x[1])

    return sorted(scored, key=lambda x: -x[1])


class DualSideFloorSuppressor:
    """
    Tracks per-ticker dual-side floor suppression state (Rules 4–6).

    A ticker is suppressed when both its bull and bear WR have been < 45% for
    45 consecutive trading days. It recovers direction by direction when the
    relevant WR reaches >= 50% for 20 consecutive trading days.

    Usage:
        suppressor = DualSideFloorSuppressor()
        suppressor.update(ticker, bull_wr, bear_wr, trading_date)
        suppressed = suppressor.is_suppressed(ticker, direction="LONG", as_of=today)
    """

    def __init__(
        self,
        floor_threshold: float = 0.45,
        suppression_days: int = 45,
        recovery_threshold: float = 0.50,
        recovery_days: int = 20,
    ):
        self._floor = floor_threshold
        self._sup_days = suppression_days
        self._rec_threshold = recovery_threshold
        self._rec_days = recovery_days
        # Per-ticker state
        self._state: Dict[str, dict] = {}

    def _init_ticker(self, ticker: str) -> dict:
        state = {
            "both_below_streak": 0,  # consecutive trading days both WR < floor
            "suppressed": False,
            "bull_recovery_streak": 0,
            "bear_recovery_streak": 0,
            "bull_ok": True,   # True = not suppressed for LONG
            "bear_ok": True,   # True = not suppressed for SHORT
        }
        self._state[ticker] = state
        return state

    def update(self, ticker: str, bull_wr: float, bear_wr: float, trading_date: date) -> None:
        state = self._state.get(ticker) or self._init_ticker(ticker)

        if not state["suppressed"]:
            if bull_wr < self._floor and bear_wr < self._floor:
                state["both_below_streak"] += 1
            else:
                state["both_below_streak"] = 0

            if state["both_below_streak"] >= self._sup_days:
                state["suppressed"] = True
                state["bull_ok"] = False
                state["bear_ok"] = False
        else:
            # Track bull recovery streak
            if bull_wr >= self._rec_threshold:
                state["bull_recovery_streak"] += 1
            else:
                state["bull_recovery_streak"] = 0

            if state["bull_recovery_streak"] >= self._rec_days:
                state["bull_ok"] = True

            # Track bear recovery streak
            if bear_wr >= self._rec_threshold:
                state["bear_recovery_streak"] += 1
            else:
                state["bear_recovery_streak"] = 0

            if state["bear_recovery_streak"] >= self._rec_days:
                state["bear_ok"] = True

            if state["bull_ok"] and state["bear_ok"]:
                state["suppressed"] = False
                state["both_below_streak"] = 0
                state["bull_recovery_streak"] = 0
                state["bear_recovery_streak"] = 0

    def is_suppressed(self, ticker: str, direction: str, as_of: date = None) -> bool:
        """
        Returns True if the ticker is currently suppressed for the given direction.

        direction: "LONG" checks bull_ok; "SHORT" checks bear_ok.
        as_of is accepted for API compatibility but state is fully determined by
        prior update() calls — it is not replayed for this date.
        """
        state = self._state.get(ticker)
        if state is None:
            return False
        if direction == "LONG":
            return not state["bull_ok"]
        return not state["bear_ok"]
