import argparse
import random
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, datetime, time as time_type, timedelta

from alpaca.data.enums import DataFeed
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    NO_MORE_NEW_POSITION_AFTER,
    build_bearish_regime_dates,
    build_qqq_extended_dates,
    build_qqq_or_alignment,
    compute_signals_with_backtest,
    fetch_bars,
    fetch_daily_bars,
)
from alpha_tech_tracker.op_momentum_strategy.config import EOD_EXIT_TIME
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    ACTIVELY_TRADE_TICKERS,
    DEFAULT_TICKERS,
    OPENING_BARS,
    OPENING_START_TIME,
    ROLLING_LOOKBACK_DAYS,
    STOP_PCT,
    compute_ticker_stats,
    score_ticker,
)

MIN_WINDOW_CAPITAL = 100.0
INITIAL_CAPITAL = 10_000.0
DOUBLEDOWN_START_MIN = 5  # min from OR close at which the DD check fires and addon enters

# ── Regime-adaptive config ────────────────────────────────────────────────────
REGIME_VIX_HI = 22.0
REGIME_VIX_LO = 17.0
REGIME_MA_STRONG_SCORE = 3  # min count of MA8/20/50/200 QQQ price is above at 9:40 bar

# (bars, stop_pct) per regime bucket — from 2018-2025 cross-year sweep.
# See M1_WINDOW_SWEEP_FINDINGS.md "Regime-Segmented Config Sweep" sections.
REGIME_ADAPTIVE_CONFIGS = {
    "vix_hi_ma_strong":  (4, 0.4),  # VIX≥22 + MA≥3: high confidence (2020:114d, 2022:90d)
    "vix_hi_ma_weak":    (5, 0.5),  # VIX≥22 + MA≤2: medium confidence (2022:103d)
    "vix_mid_ma_strong": (6, 0.7),  # VIX17-22 + MA≥3: medium confidence (2021:69d, 2023:55d)
    "vix_mid_ma_weak":   (6, 0.5),  # VIX17-22 + MA≤2: medium confidence (2021:67d, 2023:53d)
    "vix_lo":            (5, 0.5),  # VIX<17 (calm): low confidence — use all-weather default
}
# ─────────────────────────────────────────────────────────────────────────────

# The replay cutoff feeds bars with open-timestamp < EOD_EXIT_TIME (15:55), so the last
# bar processed is the 15:50 bar (open 15:50, closes at 15:55).  Display its open-time
# to match the live engine's exit_time convention (which stamps the bar open, not close).
_EOD_DISPLAY_TIME = (
    datetime.strptime(EOD_EXIT_TIME, "%H:%M") - timedelta(minutes=5)
).strftime("%H:%M")


def _consec_streak(close: pd.Series) -> pd.Series:
    result = np.zeros(len(close))
    vals = close.values
    streak = 0
    for i in range(1, len(vals)):
        if np.isnan(vals[i]) or np.isnan(vals[i - 1]):
            streak = 0
        elif vals[i] > vals[i - 1]:
            streak = streak + 1 if streak > 0 else 1
        elif vals[i] < vals[i - 1]:
            streak = streak - 1 if streak < 0 else -1
        else:
            streak = 0
        result[i] = streak
    return pd.Series(result, index=close.index)


def _build_daily_context(bars_5min: pd.DataFrame, frog_days: int = 60) -> dict:
    """
    Pre-computes daily features (all prior-day, no lookahead) from 5-min bars.
    Returns a dict keyed by date → {dist_52w_low_pct, consec_streak,
    prev_day_vol_ratio, daily_ma200_dist_pct, daily_ma50_dist_pct}.
    """
    if bars_5min.empty:
        return {}
    mh = bars_5min.between_time("09:30", "16:00")
    daily = mh.resample("D").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Close"])
    daily.index = daily.index.normalize().tz_localize(None)

    daily["daily_ma200"] = daily["Close"].rolling(200, min_periods=100).mean()
    daily["daily_ma200_dist_pct"] = (
        (daily["Open"] - daily["daily_ma200"]) / daily["daily_ma200"] * 100
    )

    daily["daily_ma50"] = daily["Close"].rolling(50, min_periods=20).mean()
    daily["daily_ma50_dist_pct"] = (
        (daily["Open"] - daily["daily_ma50"]) / daily["daily_ma50"] * 100
    )

    vol_20d_avg = daily["Volume"].rolling(20, min_periods=5).mean().shift(1)
    daily["prev_day_vol_ratio"] = daily["Volume"].shift(1) / vol_20d_avg

    daily["consec_streak"] = _consec_streak(daily["Close"]).shift(1)

    daily["high_52w"] = daily["High"].rolling(252, min_periods=60).max().shift(1)
    daily["low_52w"] = daily["Low"].rolling(252, min_periods=60).min().shift(1)
    daily["dist_52w_low_pct"] = (
        (daily["Open"] - daily["low_52w"]) / daily["low_52w"] * 100
    )
    daily["dist_52w_high_pct"] = (
        (daily["Open"] - daily["high_52w"]) / daily["high_52w"] * 100
    )

    daily_dir = daily["Close"].diff().apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    daily["frog_score"] = (
        daily_dir.rolling(frog_days, min_periods=frog_days // 2).mean().shift(1)
    )

    result = {}
    for ts, row in daily.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        result[d] = {
            "dist_52w_low_pct": float(row["dist_52w_low_pct"]),
            "dist_52w_high_pct": float(row["dist_52w_high_pct"]),
            "consec_streak": float(row["consec_streak"]),
            "prev_day_vol_ratio": float(row["prev_day_vol_ratio"]),
            "daily_ma200_dist_pct": float(row["daily_ma200_dist_pct"]),
            "daily_ma50_dist_pct": float(row["daily_ma50_dist_pct"]),
            "frog_score": float(row["frog_score"]) if not pd.isna(row["frog_score"]) else 0.0,
        }
    return result


def _signal_dict_from_row(row) -> dict:
    or_range = row["or_high"] - row["or_low"]
    mid = row["midpoint"]
    entry = row["entry_price"]
    entry_vs_mid_pct = abs(entry - mid) / mid * 100 if mid != 0 else 0.0
    or_range_pct = or_range / entry * 100 if entry != 0 else 0.0
    raw_ratio = row.get("or_vol_ratio", None)
    # Default to 1.0 (neutral — "exactly average volume") when ratio is unavailable,
    # e.g. during the first 5 trading days before the rolling window warms up.
    # With the default score_vol_ratio_weight=0.00 this has no effect on scoring;
    # callers that set a positive weight should be aware that missing data produces
    # a neutral 1.0 rather than 0.0 or NaN exclusion.
    or_vol_ratio = float(raw_ratio) if raw_ratio is not None and not (isinstance(raw_ratio, float) and raw_ratio != raw_ratio) else 1.0
    return {
        "signal": row["signal"],
        "entry_vs_mid_pct": entry_vs_mid_pct,
        "or_range_pct": or_range_pct,
        "or_vol_ratio": or_vol_ratio,
        "or_high": float(row["or_high"]),
        "or_low": float(row["or_low"]),
        "ma20": float(row["ma20"]),
        "ma50": float(row.get("ma50", float("nan"))),
    }


def _normalize_windows(windows, opening_start_time, opening_bars):
    """
    Accept either a list of window dicts or fall back to the legacy single-window params.
    Each window dict: {"label": str, "opening_start": str, "opening_bars": int}
    """
    if windows:
        return windows
    return [
        {
            "label": "W1",
            "opening_start": opening_start_time,
            "opening_bars": opening_bars,
        }
    ]


def _compute_cap_pnl(row: dict, slot_capital: float) -> float:
    cap_pnl = (slot_capital / row["entry_price"]) * row["pnl"]
    for ep_key, pnl_key in (
        ("rev_entry_price", "rev_pnl"),
        ("br_entry_price", "br_pnl"),
        ("bru_entry_price", "bru_pnl"),
    ):
        ep = row.get(ep_key, 0)
        if ep:
            cap_pnl += (slot_capital / ep) * row.get(pnl_key, 0)
    return cap_pnl


def _compute_dd_deployed(rows: list) -> float:
    """
    Return the amount of freed capital redeployed into the DD addon leg for this window.

    Called after slot_capital is set on each row. The DD addon is still running when
    the next sequential window starts, so this amount must be deducted from the capital
    passed forward to that window.
    """
    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
    if winner is None or winner.get("skipped"):
        return 0.0
    freed_rank_set = set(winner["dd_freed_ranks"])
    total = 0.0
    for r in rows:
        if r["rank"] not in freed_rank_set or r.get("skipped"):
            continue
        slot_cap = r.get("slot_capital", 0.0)
        if slot_cap > 0 and r.get("entry_price", 0) > 0:
            returned = slot_cap * (1.0 + r["pnl"] / r["entry_price"])
            total += max(0.0, returned)
    return total


def _apply_doubledown_window(rows: list) -> float:
    """
    Apply the double-down add-on P&L for a single window's rows.

    Requires slot_capital to be set on each row (called after _compute_cap_pnl).
    Mutates the winner row in-place (cap_pnl, dd_addon_cap_pnl, dd_freed_capital).
    Returns the addon dollar P&L added (0.0 if no DD fired).
    """
    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
    if winner is None or winner.get("skipped"):
        return 0.0

    freed_rank_set = set(winner["dd_freed_ranks"])
    total_freed = 0.0
    for r in rows:
        if r["rank"] not in freed_rank_set or r.get("skipped"):
            continue
        slot_cap = r.get("slot_capital", 0.0)
        if slot_cap > 0 and r.get("entry_price", 0) > 0:
            returned = slot_cap * (1.0 + r["pnl"] / r["entry_price"])
            total_freed += max(0.0, returned)

    if total_freed <= 0:
        return 0.0

    addon_cap_pnl = total_freed * winner.get("dd_addon_pnl_pct", 0.0)
    winner["cap_pnl"] += addon_cap_pnl
    winner["dd_addon_cap_pnl"] = addon_cap_pnl
    winner["dd_freed_capital"] = total_freed

    # Fold DD addon into composite pnl_pct / success so the primary row's quality
    # score reflects the full day's performance (primary + REV + BRE + BRU + DD).
    dd_pct = winner.get("dd_addon_pnl_pct", 0.0) * 100  # fraction → percentage
    winner["pnl_pct"] = round(winner.get("pnl_pct", 0.0) + dd_pct, 3)
    winner["success"] = winner["pnl_pct"] > 0

    return addon_cap_pnl


def _compute_primary_cap_pnl(row: dict, slot_capital: float) -> float:
    """Compute cap_pnl using only primary entry/exit, excluding BRU/BR/REV sub-trades."""
    entry_price = row.get("entry_price", 0.0)
    exit_price = row.get("exit_price", entry_price)
    if entry_price <= 0:
        return 0.0
    raw = (
        exit_price - entry_price
        if row.get("signal") == "BULLISH"
        else entry_price - exit_price
    )
    return slot_capital / entry_price * raw


def _apply_capital_flow(
    trade_rows: list,
    windows: list,
    initial_capital: float,
    weights: list,
    n: int,
    morning_split: list = None,
    min_capital: float = MIN_WINDOW_CAPITAL,
    compound: bool = False,
    enable_doubledown: bool = False,
) -> list:
    """
    Apply day-by-day capital flow across windows.

    Capital allocation rules:
      - First group (simultaneous): first len(morning_split) windows each get
        portfolio * morning_split[i] of capital deployed at the same time.
      - Sequential windows (remaining): each inherits all returned capital from
        the previous window (first_group_pnl flows into the first sequential
        window; each subsequent window gets the prior window's returned capital).
      - If a window's allocated capital < min_capital, it is skipped for that day
        and the available capital passes unchanged to the next sequential window.
      - compound=False (default): portfolio resets to initial_capital at the start
        of each day — isolates per-day strategy edge, good for strategy comparison.
      - compound=True: portfolio carries over day-to-day — reflects live account growth.

    DD capital recycling (enable_doubledown=True):
      For each sequential window Wk, available = base + pnl_acc - active_dd_capital,
      where active_dd_capital is the sum of freed capital from all preceding DDs whose
      winner has NOT yet exited by Wk's OR close time. If a DD exits before Wk starts,
      its capital naturally flows back in (no deduction). DD P&L is applied separately
      via _apply_doubledown() and does not affect sequential window sizing.

    Capital recycling between windows (timing-accurate):
      Each sequential window's available capital is computed from what has
      actually been returned by its drain time (OR close). Prior window trades
      that are still running at drain time have their slot_capital deducted;
      trades that exited before drain time contribute their cap_pnl. This
      matches live engine behaviour and correctly handles morning trades that
      hold past an afternoon window's start time.

    Mutates each trade row in-place, adding:
      - 'cap_pnl': actual dollar P&L for this trade given real capital allocation
      - 'window_capital': capital allocated to this window on this day
      - 'skipped': True if window was skipped due to insufficient capital

    Returns skip_log: list of dicts describing each window execution per day.
    """
    if morning_split is None:
        morning_split = [1.0]

    n_first = len(morning_split)
    window_labels = [w["label"] for w in windows]

    # OR close time (minutes from midnight) = drain time for each window.
    # Used both for DD leg lock-up detection and for sequential capital timing.
    drain_min: dict = {}
    for w in windows:
        h, m = map(int, w["opening_start"].split(":"))
        drain_min[w["label"]] = h * 60 + m + w["opening_bars"] * 5

    # Index trade_rows by (date, window) for fast lookup
    by_day_window = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    trading_days = sorted({row["date"] for row in trade_rows})
    skip_log = []
    portfolio = initial_capital

    for d in trading_days:
        if not compound:
            portfolio = initial_capital

        # day_dds: list of (dd_deployed, winner_exit_min) for all DDs fired today.
        # Used by sequential windows to decide how much capital is still locked in DD.
        day_dds: list = []

        # Tracks BRU P&L removed mid-loop (Phase 2 cancellations) so portfolio
        # receives the correct net P&L at end of day.
        day_pnl_correction = 0.0

        # --- First group: simultaneous windows, each gets portfolio * split[i] ---
        first_group_pnl = 0.0
        for i, label in enumerate(window_labels[:n_first]):
            win_capital = portfolio * morning_split[i]
            rows = by_day_window.get((d, label), [])
            skipped = win_capital < min_capital
            status = (
                "skipped_low_capital"
                if skipped
                else ("executed" if rows else "no_signal")
            )
            skip_log.append(
                {
                    "date": d,
                    "window": label,
                    "status": status,
                    "available_capital": round(win_capital, 2),
                    "picks": len(rows),
                }
            )
            win_pnl = 0.0
            for row in rows:
                row["window_capital"] = win_capital
                if skipped:
                    row["cap_pnl"] = 0.0
                    row["skipped"] = True
                else:
                    slot_capital = win_capital * weights[row["rank"] - 1]
                    row["slot_capital"] = slot_capital
                    if row.get("reentry_cancelled_by_dd"):
                        row["cap_pnl"] = _compute_primary_cap_pnl(row, slot_capital)
                    else:
                        row["cap_pnl"] = _compute_cap_pnl(row, slot_capital)
                    row["skipped"] = False
                    win_pnl += row["cap_pnl"]
            if enable_doubledown and not skipped:
                dd_dep = _compute_dd_deployed(rows)
                if dd_dep > 0:
                    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
                    if winner is not None:
                        exit_min = (
                            drain_min[label] + (winner["bars_held"] + 1) * 5
                        )
                        day_dds.append((dd_dep, exit_min))
            first_group_pnl += win_pnl

        # --- Sequential windows ---
        # For each sequential window, available capital is computed from what has
        # actually been returned by its drain time, matching live engine behaviour:
        #   available = portfolio
        #             + cap_pnl for each prior row that exited before this drain
        #             - slot_capital for each prior row still running at this drain
        # This correctly handles morning trades that hold past an afternoon window's
        # start time — their capital is locked and unavailable until they close.
        #
        # Sub-trade timing (BRU/BRE/REV): a sub-trade fires hours after the primary
        # exits.  Between the primary exit and the sub-trade entry the capital is
        # genuinely free.  We therefore use a three-phase model per slot:
        #   Phase 1 — primary still running at this_drain → deduct slot_capital
        #   Phase 2 — primary done, sub not started yet   → capital is free; add
        #             primary-only cap_pnl (avoids pulling in future sub P&L)
        #   Phase 3 — sub running at this_drain           → capital re-deployed;
        #             deduct slot_capital
        #   Phase 4 — everything exited before this_drain → add combined cap_pnl
        seq_pnl = 0.0
        for i_seq, label in enumerate(window_labels[n_first:]):
            this_drain = drain_min[label]

            available = portfolio
            for prior_label in window_labels[:n_first + i_seq]:
                prior_drain = drain_min[prior_label]
                for row in by_day_window.get((d, prior_label), []):
                    if row.get("skipped"):
                        continue
                    # Add-on rows (BRE/BRU/REV) reuse freed capital from the primary
                    # slot — they don't deploy additional window capital, so they must
                    # not affect the available-capital calculation.
                    if (row.get("is_reversal") or row.get("is_bearish_reentry")
                            or row.get("is_bullish_reentry")):
                        continue
                    primary_bars = row.get("bars_held", 0)
                    primary_exit_time = prior_drain + primary_bars * 5

                    if primary_exit_time > this_drain:
                        # Phase 1: primary still running — full slot locked.
                        available -= row.get("slot_capital", 0.0)
                        continue

                    # Primary has exited.  Handle cancellation shortcuts before
                    # phase logic — these rows have already had their sub-trades
                    # suppressed and their cap_pnl corrected.
                    if row.get("bru_cancelled"):
                        # Phase 2 was applied at an earlier sequential window.
                        # BRU capital was given to that window — use stored
                        # primary-only cap_pnl (BRU contribution already removed).
                        available += row["primary_only_cap_pnl"]
                        continue

                    if row.get("reentry_cancelled_by_dd"):
                        # DD fired at this row's window and cancelled its sub-trade.
                        # cap_pnl was already set to primary-only during window exec.
                        # DD capital is separately deducted via day_dds.
                        available += row.get("cap_pnl", 0.0)
                        continue

                    # Primary has exited.  Check sub-trade timing when BRU/BRE/REV
                    # fields are present.  Three phases are possible:
                    #   Phase 2 — sub exists but hasn't started at this_drain
                    #             → primary capital is free; add primary-only cap_pnl
                    #             → mark row so BRU is suppressed for all later windows
                    #   Phase 3 — sub is running at this_drain
                    #             → slot still deployed; deduct slot_capital
                    #   Phase 4 — sub finished before this_drain (or no sub)
                    #             → add full combined cap_pnl
                    # When no BRU/BRE/REV entry_price is set we fall back to the
                    # slot_exit_bars-based lock check (original pre-phase behaviour).
                    sub_active = False
                    sub_started = False
                    sub_exists = False
                    for sub_prefix, idx_key, bars_key in (
                        ("bru", "bru_entry_idx", "bru_bars_held"),
                        ("br",  "br_entry_idx",  "br_bars_held"),
                        ("rev", "rev_entry_idx", "rev_bars_held"),
                    ):
                        if not row.get(f"{sub_prefix}_entry_price"):
                            continue
                        sub_exists = True
                        sub_entry_idx = row.get(idx_key, 0)
                        sub_bars = row.get(bars_key, 0)
                        # Sub-trade scan starts one bar after the primary exits;
                        # sub fires sub_entry_idx bars into that scan, then holds
                        # sub_bars more bars.
                        sub_entry_min = prior_drain + (primary_bars + 1 + sub_entry_idx + 1) * 5
                        sub_exit_min = sub_entry_min + sub_bars * 5
                        if sub_entry_min <= this_drain:
                            sub_started = True
                        if sub_entry_min <= this_drain < sub_exit_min:
                            sub_active = True

                    if sub_active:
                        # Phase 3: sub-trade running — slot capital re-deployed.
                        available -= row.get("slot_capital", 0.0)
                    elif sub_exists and not sub_started:
                        # Phase 2: primary done, sub hasn't started yet.
                        # Capital is genuinely free — add primary-only cap_pnl.
                        # Also mark the BRU as cancelled: the sequential window
                        # has claimed this capital so the sub-trade can't fire.
                        # Matches live engine "window [M] capital deployed in [W]
                        # — skipping" behaviour.
                        primary_cap_pnl = _compute_primary_cap_pnl(
                            row, row.get("slot_capital", 0.0)
                        )
                        available += primary_cap_pnl
                        if not row.get("bru_cancelled"):
                            row["bru_cancelled"] = True
                            row["primary_only_cap_pnl"] = primary_cap_pnl
                            day_pnl_correction += row.get("cap_pnl", 0.0) - primary_cap_pnl
                            row["cap_pnl"] = primary_cap_pnl
                    elif sub_exists:
                        # Phase 4 (with sub): sub already exited — full combined cap_pnl.
                        available += row.get("cap_pnl", 0.0)
                    else:
                        # No BRU/BRE/REV fields: fall back to slot_exit_bars timing.
                        slot_exit_bars = row.get("slot_exit_bars", primary_bars)
                        slot_exit_time = prior_drain + slot_exit_bars * 5
                        if slot_exit_time > this_drain:
                            available -= row.get("slot_capital", 0.0)
                        else:
                            available += row.get("cap_pnl", 0.0)

            # Deduct capital from any DD legs still running at this window's drain.
            if enable_doubledown:
                for dd_dep, exit_min in day_dds:
                    if exit_min >= this_drain:
                        available -= dd_dep

            rows = by_day_window.get((d, label), [])
            skipped = available < min_capital
            status = (
                "skipped_low_capital"
                if skipped
                else ("executed" if rows else "no_signal")
            )
            skip_log.append(
                {
                    "date": d,
                    "window": label,
                    "status": status,
                    "available_capital": round(available, 2),
                    "picks": len(rows),
                }
            )
            win_pnl = 0.0
            for row in rows:
                row["window_capital"] = available
                if skipped:
                    row["cap_pnl"] = 0.0
                    row["skipped"] = True
                else:
                    slot_capital = available * weights[row["rank"] - 1]
                    row["slot_capital"] = slot_capital
                    if row.get("reentry_cancelled_by_dd"):
                        row["cap_pnl"] = _compute_primary_cap_pnl(row, slot_capital)
                    else:
                        row["cap_pnl"] = _compute_cap_pnl(row, slot_capital)
                    row["skipped"] = False
                    win_pnl += row["cap_pnl"]
            if enable_doubledown and not skipped:
                dd_dep = _compute_dd_deployed(rows)
                if dd_dep > 0:
                    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
                    if winner is not None:
                        exit_min = (
                            drain_min[label] + (winner["bars_held"] + 1) * 5
                        )
                        day_dds.append((dd_dep, exit_min))
            if not skipped:
                seq_pnl += win_pnl

        portfolio += first_group_pnl + seq_pnl - day_pnl_correction

    return skip_log


def _annotate_doubledown_addon(
    trade_rows: list,
    bars_by_date: dict,
    window_opening_times: dict,
    opening_bars_by_label: dict,
    doubledown_start_min: int = DOUBLEDOWN_START_MIN,
) -> None:
    """
    For each (date, window) group where rank-2+ positions stopped out before
    doubledown_start_min minutes after OR close, annotate the winner row with
    the add-on leg P&L.

    All picks in a window enter at OR close. The DD check fires at the fixed
    start time (OR close + doubledown_start_min) — not at the stopout bar.

    Add-on leg mechanics (backtested approximation):
    - Entry: close of the bar at OR close + doubledown_start_min.
    - Hard stop: entry ± 80% × (High − Low) of the check bar in the adverse
      direction — allows a small loss proportional to the bar's range.
    - Exit: winner's exit price (same trailing-stop path), or the hard stop
      price if the exit is beyond it.
    - P&L: signed return from addon_entry to effective exit (can be negative).

    At most one doubledown per window per day. All freed capital from multiple
    stopouts is combined into a single addon leg on the highest-ranked survivor.

    Mutates trade_rows in-place, adding to winner rows:
      dd_addon_pnl_pct        float  add-on return as fraction of addon entry (signed)
      dd_addon_stop_price     float  hard-stop price for the add-on leg
      dd_addon_effective_exit float  actual exit used (stop or winner exit)
      dd_addon_entry          float  add-on entry price
      dd_freed_ranks          list   ranks whose freed capital flows to the winner
    """
    stop_reasons = {"hard_stop", "fallback_20pct"}
    # 0-indexed bar index at OR close + doubledown_start_min
    dd_bars = doubledown_start_min // 5  # 5 min → 1, 15 min → 3, 50 min → 10

    by_day_window: dict = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    for (d, label), rows in by_day_window.items():
        if len(rows) < 2:
            continue

        rows_by_rank = sorted(rows, key=lambda r: r["rank"])

        # Partition into stopouts and survivors at the DD check time.
        # Any early stopout frees its capital for the winner's add-on — including
        # ranks that had a pending re-entry (BRU/BR/REV). When DD fires, the live
        # engine cancels those re-entry watchers ("DD [W]: cancelled N re-entry
        # watcher(s) for [...]"). We mark those rows so _apply_capital_flow can
        # suppress their sub-trade and use primary-only cap_pnl.
        def _is_early_stopout(r):
            return (
                r.get("exit_reason", "") in stop_reasons
                and r.get("bars_held", 999) <= dd_bars
            )

        stopouts = [r for r in rows_by_rank if _is_early_stopout(r)]
        survivors = [r for r in rows_by_rank if not _is_early_stopout(r)]

        if not stopouts or not survivors:
            continue

        # Winner = highest-ranked survivor (lowest rank number).
        # Freed capital from ALL stopouts flows to this one position.
        winner = survivors[0]

        # If the winner already exited before the addon entry bar, the addon
        # can't fire — there is no open position to add on to.
        if winner.get("bars_held", 0) < dd_bars:
            continue
        freed_ranks = [r["rank"] for r in stopouts]

        # Look up the doubledown bar close for the winner's ticker.
        opening_bars = opening_bars_by_label.get(label, 3)
        opening_start = window_opening_times.get(label)
        if opening_start is None:
            continue

        day_bars = bars_by_date.get(winner["ticker"], {}).get(d)
        if day_bars is None or day_bars.empty:
            continue

        or_close_time = (
            datetime.combine(d, opening_start) + timedelta(minutes=opening_bars * 5)
        ).time()
        post_or = day_bars[day_bars.index.time >= or_close_time]
        if len(post_or) <= dd_bars:
            continue

        addon_bar = post_or.iloc[dd_bars]
        if addon_bar.name.time() > NO_MORE_NEW_POSITION_AFTER:
            continue
        addon_entry = float(addon_bar["Close"])
        if addon_entry == 0:
            continue

        exit_price = float(winner["exit_price"])
        bar_range = float(addon_bar["High"]) - float(addon_bar["Low"])
        bars_after_addon = post_or.iloc[dd_bars + 1 : winner.get("bars_held", 0) + 1]
        if winner["signal"] == "BULLISH":
            stop_price = addon_entry - 0.80 * bar_range
            stop_breached = any(
                float(b["Low"]) < stop_price for _, b in bars_after_addon.iterrows()
            )
            effective_exit = stop_price if stop_breached else max(exit_price, stop_price)
            raw_pct = (effective_exit - addon_entry) / addon_entry
        else:
            stop_price = addon_entry + 0.80 * bar_range
            stop_breached = any(
                float(b["High"]) > stop_price for _, b in bars_after_addon.iterrows()
            )
            effective_exit = stop_price if stop_breached else min(exit_price, stop_price)
            raw_pct = (addon_entry - effective_exit) / addon_entry

        winner["dd_addon_pnl_pct"] = raw_pct
        winner["dd_addon_entry"] = addon_entry
        winner["dd_addon_stop_price"] = stop_price
        winner["dd_addon_effective_exit"] = effective_exit
        winner["dd_addon_stop_breached"] = stop_breached
        winner["dd_freed_ranks"] = freed_ranks
        winner["dd_fire_min"] = winner.get("or_close_min", 0) + dd_bars * 5

        # DD confirmed to fire. Mark stopout rows that had sub-trades — their
        # re-entries are cancelled by DD (matches live engine behaviour).
        for r in stopouts:
            if (
                r.get("bru_entry_price", 0) != 0
                or r.get("br_entry_price", 0) != 0
                or r.get("rev_entry_price", 0) != 0
            ):
                r["reentry_cancelled_by_dd"] = True


def _fetch_regime_data(fetch_start, eval_end, source, feed):
    """
    Fetch VIX daily data and QQQ 5-min bars for regime classification.

    Returns (vix_prior, qqq_5min):
      - vix_prior: pd.Series indexed by Timestamp, prior day's VIX close (shifted +1 BDay)
      - qqq_5min: pd.DataFrame of QQQ 5-min bars with rolling MA8/20/50/200 on Close
    """
    print("  [regime] Fetching VIX daily data...")
    vix_raw = yf.download(
        "^VIX",
        start=str(fetch_start),
        end=str(eval_end + timedelta(days=1)),
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if hasattr(vix_raw.columns, "get_level_values"):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    vix_series = vix_raw["Close"].dropna()
    vix_prior = vix_series.shift(1)

    print("  [regime] Fetching QQQ 5-min bars for MA alignment...")
    qqq_all = fetch_bars(["QQQ"], fetch_start, eval_end, source=source, feed=feed)
    qqq_5min = qqq_all.get("QQQ", pd.DataFrame()).sort_index()
    if not qqq_5min.empty:
        qqq_5min = qqq_5min.copy()
        qqq_5min["ma8"]   = qqq_5min["Close"].rolling(8).mean()
        qqq_5min["ma20"]  = qqq_5min["Close"].rolling(20).mean()
        qqq_5min["ma50"]  = qqq_5min["Close"].rolling(50).mean()
        qqq_5min["ma200"] = qqq_5min["Close"].rolling(200).mean()
    return vix_prior, qqq_5min


def _classify_day_regime(d, vix_prior, qqq_5min):
    """
    Classify trading day d into a regime bucket name.
    Returns None if VIX or QQQ data is unavailable (caller should use fallback).
    """
    ts = pd.Timestamp(d)
    vix_val = None
    for offset in range(1, 6):
        prev = ts - pd.tseries.offsets.BDay(offset)
        if prev in vix_prior.index:
            candidate = vix_prior[prev]
            if not np.isnan(float(candidate)):
                vix_val = float(candidate)
                break
    if vix_val is None:
        return None

    entry_ts = pd.Timestamp(
        datetime.combine(d, datetime.strptime("09:40", "%H:%M").time()),
        tz="America/New_York",
    )
    bar_row = qqq_5min.loc[qqq_5min.index == entry_ts] if not qqq_5min.empty else pd.DataFrame()
    if bar_row.empty:
        return None

    close_price = bar_row["Close"].iloc[0]
    ma_vals = [bar_row[col].iloc[0] for col in ("ma8", "ma20", "ma50", "ma200")]
    if any(np.isnan(v) for v in ma_vals):
        return None

    ma_score = sum(1 for v in ma_vals if close_price > v)

    if vix_val >= REGIME_VIX_HI:
        return "vix_hi_ma_strong" if ma_score >= REGIME_MA_STRONG_SCORE else "vix_hi_ma_weak"
    elif vix_val >= REGIME_VIX_LO:
        return "vix_mid_ma_strong" if ma_score >= REGIME_MA_STRONG_SCORE else "vix_mid_ma_weak"
    else:
        return "vix_lo"


def _build_day_config_map(trading_days, vix_prior, qqq_5min, fallback_bars, fallback_stop):
    """
    Returns dict[date, (bars, stop_pct)] for each trading day.
    Days without VIX/QQQ data fall back to (fallback_bars, fallback_stop).
    """
    config_map = {}
    fallback_key = (fallback_bars, fallback_stop)
    for d in trading_days:
        bucket = _classify_day_regime(d, vix_prior, qqq_5min)
        config_map[d] = REGIME_ADAPTIVE_CONFIGS.get(bucket, fallback_key) if bucket else fallback_key
    return config_map


def _build_qqq_scoring_regime(fetch_start: date, eval_end: date) -> dict:
    """
    Returns {date: 'bull'/'bear'} based on prior-day QQQ close vs 50d MA.
    No lookahead — shift(1) ensures today's regime uses yesterday's close/MA.
    """
    print("  [regime-scoring] Fetching QQQ daily bars for scoring regime...")
    qqq = yf.download(
        "QQQ",
        start=str(fetch_start - timedelta(days=120)),
        end=str(eval_end + timedelta(days=1)),
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if qqq.empty:
        return {}
    if isinstance(qqq.columns, pd.MultiIndex):
        qqq.columns = qqq.columns.get_level_values(0)
    close = qqq["Close"].squeeze().dropna()
    ma50 = close.rolling(50, min_periods=20).mean()
    above = (close > ma50).shift(1)
    result = {}
    for ts, val in above.items():
        d = ts.date() if hasattr(ts, "date") else ts
        if not pd.isna(val):
            result[d] = "bull" if bool(val) else "bear"
    return result


def _compute_rolling_stats(tickers, lookback_start, d, eff_primary_wr, ev_trend_days):
    rolling_stats = {}
    for ticker in tickers:
        primary_results = eff_primary_wr.get(ticker, pd.DataFrame())
        if primary_results.empty:
            rolling_stats[ticker] = compute_ticker_stats(pd.DataFrame())
            continue
        window_slice = primary_results[
            (primary_results["date"] >= lookback_start)
            & (primary_results["date"] < d)
        ]
        rolling_stats[ticker] = compute_ticker_stats(window_slice, recent_days=ev_trend_days)
    return rolling_stats


def run_selector_backtest(
    n: int,
    tickers: list,
    eval_start: date,
    eval_end: date,
    lookback_days: int = ROLLING_LOOKBACK_DAYS,
    opening_bars: int = OPENING_BARS,
    opening_start_time: str = OPENING_START_TIME,
    bearish_ma200: bool = False,
    stop_pct: float = STOP_PCT,
    source: str = "alpaca",
    trailing_ma: str = "ma20",
    trailing_ma_switch: str = "none",
    trailing_ma_switch_factor: float = 1.0,
    trailing_ma_switch_period: int = 8,
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
    regime_filter: bool = False,
    regime_ma: int = 5,
    windows: list = None,
    dedup: bool = False,
    enable_reversal: bool = False,
    reversal_max_bars_held: int = 3,
    enable_bearish_reversal: bool = False,
    bearish_reversal_max_bars_held: int = 3,
    min_or_range: float = 0.0,
    min_or_range_windows: list = None,
    min_ma200_distance: float = 0.0,
    min_ma200_distance_windows: list = None,
    min_score: float = 0.0,
    min_ev: float = 0.0,
    or_bar_lookback: int = 3,
    enable_bearish_reentry: bool = False,
    bearish_reentry_max_bars: int = 3,
    enable_bullish_reentry: bool = False,
    bullish_reentry_max_bars: int = 5,
    close_top_pct: float = None,
    feed: DataFeed = None,
    enable_doubledown: bool = False,
    doubledown_start_min: int = DOUBLEDOWN_START_MIN,
    filter_flat_or: bool = True,
    qqq_align_filter: bool = False,
    qqq_align_threshold: float = 0.50,
    qqq_extend_days: int = 0,
    qqq_extend_pct: float = 0.05,
    qqq_extend_max_dd: float = 0.0,
    min_first_bar_range_pct: float = None,
    min_first_bar_volume_mult: float = None,
    min_or_vol_ratio: float = None,
    score_entry_weight: float = 0.50,
    score_vol_ratio_weight: float = 0.00,
    score_avg_win_weight: float = 0.30,
    score_ev_trend_weight: float = 0.00,
    score_dist_52w_low_weight: float = 0.00,
    score_dist_52w_high_weight: float = 0.00,
    score_streak_weight: float = 0.00,
    score_prev_day_vol_weight: float = 0.00,
    score_ma200_dist_weight: float = 0.00,
    score_ma50_dist_weight: float = 0.00,
    regime_scoring: bool = False,
    regime_bull_entry_weight: float = None,
    regime_bull_vol_ratio_weight: float = None,
    regime_bull_avg_win_weight: float = None,
    regime_bull_ma50_dist_weight: float = None,
    regime_bear_entry_weight: float = None,
    regime_bear_vol_ratio_weight: float = None,
    regime_bear_avg_win_weight: float = None,
    regime_bear_ma50_dist_weight: float = None,
    ev_trend_days: int = 15,
    direction_split_ev_gate: bool = True,
    ds_bull_min_ev: float = 0.0,
    ds_neutral_min_ev: float = 0.0,
    ds_bear_min_ev: float = 0.0,
    oracle_picks: bool = False,
    min_hold_bars: int = 0,
    stale_cut_mins: int = 0,
    stale_cut_threshold: float = 0.0,
    exit_at_bar_close: bool = True,
    only_dates: set = None,
    regime_adaptive: bool = False,
    random_picks: bool = False,
    random_seed: int = None,
    ma_momentum_gate: bool = False,
    ma_momentum_gate_in_scoring: bool = False,
    dynamic_ev_gate: bool = True,
    dg_mode: str = "percentile",
    dg_bull_threshold: int = 10,
    dg_bear_threshold: int = 5,
    dg_bull_exclude_pct: float = 0.10,
    dg_neutral_exclude_pct: float = 0.25,
    dg_bear_exclude_pct: float = 0.40,
    dg_bull_min_wr: float = 0.30,
    dg_neutral_min_wr: float = 0.33,
    dg_bear_min_wr: float = 0.38,
    dg_bull_min_wl: float = 1.3,
    dg_neutral_min_wl: float = 1.5,
    dg_bear_min_wl: float = 1.8,
    adaptive_lookback: bool = True,
    al_bull_threshold: int = 10,
    al_bear_threshold: int = 5,
    al_bull_days: int = 20,
    al_neutral_days: int = 60,
    al_bear_days: int = 90,
    qqq_or_weight: float = 0.30,
    score_win_rate_weight: float = 0.0,
    score_trend_align_weight: float = 0.0,
    entry_weight_bull: float = None,
    entry_weight_bear: float = None,
    normalize_or_by_adr: bool = False,
    adr_days: int = 20,
    min_pool_vote_to_trade: int = 0,
    direction_regime_filter: bool = False,
    drf_bull_only_thresh: int = 10,
    drf_bear_only_thresh: int = 5,
    ev_shrink_k: float = 0.0,
    score_frog_weight: float = 0.0,
    frog_days: int = 60,
    score_rel_strength_weight: float = 0.0,
    score_dir_ev_weight: float = 0.0,
) -> tuple:
    """
    Walk each trading day in [eval_start, eval_end], apply rolling selector
    scoring to pick top-N tickers per window, and record actual trade outcomes.

    windows: list of {"label", "opening_start", "opening_bars"} dicts.
             Falls back to single window from opening_start_time/opening_bars if omitted.
    dedup:   if True, skip a ticker in later windows if already picked by an earlier window that day.
    regime_adaptive: if True, M1 window bars/stop_pct are chosen per day based on
             prior VIX close and QQQ 5-min MA alignment score (see REGIME_ADAPTIVE_CONFIGS).

    Returns (trade_rows, all_window_results, trading_days) where:
      - trade_rows: list of dicts, one per selected trade (includes "window" key)
      - all_window_results: {window_label: {ticker: results_df}}
      - trading_days: sorted list of date objects in the eval window
    """
    if random_picks and random_seed is not None:
        random.seed(random_seed)

    windows = _normalize_windows(windows, opening_start_time, opening_bars)
    n_windows = len(windows)

    fetch_start = eval_start - timedelta(days=lookback_days)
    print(f"Fetching bars for {len(tickers)} tickers ({eval_start} → {eval_end})...")
    all_bars = fetch_bars(tickers, fetch_start, eval_end, source=source, feed=feed)

    # Regime dates must cover the full fetch window (lookback + eval) so that rolling
    # stats for each day are computed on regime-filtered signals, matching the selector.
    bearish_regime_dates = (
        build_bearish_regime_dates(fetch_start, eval_end, source, regime_ma, feed=feed)
        if regime_filter
        else None
    )

    # Build per-window QQQ alignment skip sets (one pair per window opening config).
    qqq_align_by_window = {}
    if qqq_align_filter:
        built_configs = {}
        for win in windows:
            key = (win["opening_bars"], win["opening_start"])
            if key not in built_configs:
                built_configs[key] = build_qqq_or_alignment(
                    fetch_start, eval_end,
                    win["opening_bars"], win["opening_start"],
                    source, feed, qqq_align_threshold,
                )
            qqq_align_by_window[win["label"]] = built_configs[key]

        # Gate: if extend_days is set, only apply alignment filter on days where QQQ
        # has risen too much too fast. Intersection narrows the skip sets so that on
        # normal trending days the filter stays off.
        if qqq_extend_days > 0:
            extend_dates = build_qqq_extended_dates(
                fetch_start, eval_end,
                qqq_extend_days, qqq_extend_pct, qqq_extend_max_dd,
                source, feed,
            )
            for label in qqq_align_by_window:
                sb, sr = qqq_align_by_window[label]
                qqq_align_by_window[label] = (sb & extend_dates, sr & extend_dates)

    print(f"Pre-computing MA columns for {len(tickers)} tickers...")
    for ticker in tickers:
        df = all_bars.get(ticker, pd.DataFrame())
        if df.empty:
            continue
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        all_bars[ticker] = df

    # Pre-compute rolling ADR per ticker: prior-N-day average of (H-L)/Close %.
    # No lookahead: shift(1) ensures today's ADR uses yesterday's close/range.
    adr_by_ticker_date: dict = {}
    if normalize_or_by_adr:
        print(f"Pre-computing {adr_days}-day rolling ADR for {len(tickers)} tickers...")
        for ticker in tickers:
            df = all_bars.get(ticker, pd.DataFrame())
            if df.empty:
                continue
            mh = df.between_time("09:30", "16:00")
            daily = mh.resample("D").agg(
                High=("High", "max"),
                Low=("Low", "min"),
                Close=("Close", "last"),
            ).dropna(subset=["Close"])
            daily.index = daily.index.normalize().tz_localize(None)
            daily["adr_pct"] = (daily["High"] - daily["Low"]) / daily["Close"] * 100
            rolling_adr = daily["adr_pct"].rolling(adr_days, min_periods=5).mean().shift(1)
            adr_by_ticker_date[ticker] = {
                ts.date(): float(v)
                for ts, v in rolling_adr.items()
                if not pd.isna(v)
            }

    daily_context_by_ticker = {}
    needs_daily_ctx = any([score_dist_52w_low_weight, score_dist_52w_high_weight,
                           score_streak_weight, score_prev_day_vol_weight,
                           score_ma200_dist_weight, score_ma50_dist_weight, regime_scoring,
                           score_frog_weight, score_rel_strength_weight])
    if needs_daily_ctx:
        print(f"Pre-computing daily context for {len(tickers)} tickers...")
        for ticker in tickers:
            df = all_bars.get(ticker, pd.DataFrame())
            daily_context_by_ticker[ticker] = _build_daily_context(df, frog_days=frog_days)

    if score_rel_strength_weight:
        all_ctx_dates = set()
        for ctx_by_date in daily_context_by_ticker.values():
            all_ctx_dates.update(ctx_by_date.keys())
        for d in all_ctx_dates:
            vals = [
                daily_context_by_ticker[t][d]["daily_ma50_dist_pct"]
                for t in tickers
                if t in daily_context_by_ticker
                and d in daily_context_by_ticker[t]
                and not np.isnan(daily_context_by_ticker[t][d]["daily_ma50_dist_pct"])
            ]
            if not vals:
                continue
            pool_mean_ma50 = sum(vals) / len(vals)
            for t in tickers:
                if t in daily_context_by_ticker and d in daily_context_by_ticker[t]:
                    ctx = daily_context_by_ticker[t][d]
                    ma50 = ctx.get("daily_ma50_dist_pct", float("nan"))
                    ctx["rel_ma50_dist_pct"] = (ma50 - pool_mean_ma50) if not np.isnan(ma50) else float("nan")

    qqq_scoring_regime = {}
    if regime_scoring:
        qqq_scoring_regime = _build_qqq_scoring_regime(fetch_start, eval_end)
        bull_days = sum(1 for v in qqq_scoring_regime.values() if v == "bull")
        bear_days = sum(1 for v in qqq_scoring_regime.values() if v == "bear")
        print(f"  [regime-scoring] {bull_days} bull days / {bear_days} bear days in range")

    print(f"Pre-computing signals for {n_windows} window(s)...")
    all_window_results = {}
    for win in windows:
        label = win["label"]
        results_for_window = {}
        win_ma_switch = win.get("trailing_ma_switch", trailing_ma_switch)
        win_ma_switch_period = win.get("trailing_ma_switch_period", trailing_ma_switch_period)
        win_ma_switch_factor = win.get("trailing_ma_switch_factor", trailing_ma_switch_factor)
        for ticker in tickers:
            df = all_bars.get(ticker, pd.DataFrame())
            if df.empty:
                results_for_window[ticker] = pd.DataFrame()
                continue
            _qqq_sb, _qqq_sr = qqq_align_by_window.get(label, (None, None))
            results_for_window[ticker] = compute_signals_with_backtest(
                df,
                win["opening_bars"],
                bearish_ma200,
                stop_pct,
                opening_start_time=win["opening_start"],
                trailing_ma=trailing_ma,
                trailing_ma_switch=win_ma_switch,
                trailing_ma_switch_factor=win_ma_switch_factor,
                trailing_ma_switch_period=win_ma_switch_period,
                max_loss_pct=max_loss_pct,
                armed_ma20_exit=armed_ma20_exit,
                bearish_regime_dates=bearish_regime_dates,
                enable_reversal=enable_reversal,
                reversal_max_bars_held=reversal_max_bars_held,
                enable_bearish_reversal=enable_bearish_reversal,
                bearish_reversal_max_bars_held=bearish_reversal_max_bars_held,
                or_bar_lookback=or_bar_lookback,
                enable_bearish_reentry=enable_bearish_reentry,
                bearish_reentry_max_bars=bearish_reentry_max_bars,
                enable_bullish_reentry=enable_bullish_reentry,
                bullish_reentry_max_bars=bullish_reentry_max_bars,
                close_top_pct=win.get("close_top_pct", close_top_pct),
                filter_flat_or=filter_flat_or,
                qqq_align_skip_bull=_qqq_sb,
                qqq_align_skip_bear=_qqq_sr,
                min_first_bar_range_pct=min_first_bar_range_pct,
                min_first_bar_volume_mult=min_first_bar_volume_mult,
                min_or_vol_ratio=min_or_vol_ratio,
                min_hold_bars=min_hold_bars,
                stale_cut_mins=stale_cut_mins,
                stale_cut_threshold=stale_cut_threshold,
                exit_at_bar_close=exit_at_bar_close,
                ma_momentum_gate=ma_momentum_gate,
            )
        all_window_results[label] = results_for_window
        print(f"  [{label}] {win['opening_start']} / {win['opening_bars']} bars — done")

    trading_days = sorted(
        {
            d
            for df in all_bars.values()
            if not df.empty
            for d in df.index.date
            if eval_start <= d <= eval_end
        }
    )
    if only_dates:
        trading_days = [d for d in trading_days if d in only_dates]

    # Pre-group bars by date: replaces O(total_bars) index.date scan with O(1) dict lookup
    # in the or_bar_lookback scoring path, called 16 tickers × N windows × N days.
    bars_by_date = {
        ticker: {d_: g for d_, g in df.groupby(df.index.date)}
        for ticker, df in all_bars.items()
        if not df.empty
    }

    # Pre-compute QQQ opening-range return per day for scoring alignment component.
    # No lookahead: uses M1 OR bars (9:30-9:45) already formed before the 9:45 pick.
    qqq_or_by_date: dict = {}
    if qqq_or_weight != 0.0:
        _m1_win_ref = next((w for w in windows if w["label"] == "M1"), windows[0])
        _m1_h, _m1_m = map(int, _m1_win_ref["opening_start"].split(":"))
        _m1_open_t = time_type(_m1_h, _m1_m)
        _m1_n_bars = _m1_win_ref["opening_bars"]
        _qqq_fetched = fetch_bars(["QQQ"], fetch_start, eval_end, source=source, feed=feed)
        _qqq_df = _qqq_fetched.get("QQQ", pd.DataFrame())
        if not _qqq_df.empty:
            _qqq_by_date = {d_: g for d_, g in _qqq_df.groupby(_qqq_df.index.date)}
            for d_ in trading_days:
                _day_q = _qqq_by_date.get(d_, pd.DataFrame())
                if _day_q.empty:
                    continue
                _or_bars = _day_q[_day_q.index.time >= _m1_open_t].head(_m1_n_bars)
                if not _or_bars.empty:
                    _o = float(_or_bars.iloc[0]["Open"])
                    _c = float(_or_bars.iloc[-1]["Close"])
                    if _o > 0:
                        qqq_or_by_date[d_] = (_c - _o) / _o * 100
        print(f"  QQQ OR scoring: pre-computed {len(qqq_or_by_date)} days  weight={qqq_or_weight:+.3f}")

    # Pre-filter primary-only signal rows per window per ticker: eliminates re-applying
    # the three is_reversal/is_bearish_reentry/is_bullish_reentry conditions every day.
    primary_window_results = {
        label: {
            ticker: (
                df[
                    (df["is_reversal"] != True)           # noqa: E712
                    & (df["is_bearish_reentry"] != True)  # noqa: E712
                    & (df["is_bullish_reentry"] != True)  # noqa: E712
                ]
                if not df.empty
                else df
            )
            for ticker, df in results_for_window.items()
        }
        for label, results_for_window in all_window_results.items()
    }

    # Pre-group all signal rows by (window, ticker, date): replaces linear date scan
    # in today_rows lookup with O(1) dict lookup.
    results_by_date = {
        label: {
            ticker: ({d_: g for d_, g in df.groupby("date")} if not df.empty else {})
            for ticker, df in results_for_window.items()
        }
        for label, results_for_window in all_window_results.items()
    }

    # Pre-parse window opening times (avoids strptime on every trading day).
    window_opening_times = {
        win["label"]: datetime.strptime(win["opening_start"], "%H:%M").time()
        for win in windows
    }

    # ── Regime-adaptive: pre-compute M1 signals for each unique (bars, stop) ──
    day_config_map = {}      # date → (bars, stop_pct) — empty when not adaptive
    regime_primary = {}      # (bars, stop) → primary_window_results["M1"]
    regime_by_date = {}      # (bars, stop) → results_by_date["M1"]

    if regime_adaptive:
        from collections import Counter
        m1_win = next((w for w in windows if w["label"] == "M1"), windows[0])
        m1_start = m1_win["opening_start"]
        fallback_bars = m1_win["opening_bars"]
        fallback_stop = stop_pct

        vix_prior, qqq_5min = _fetch_regime_data(fetch_start, eval_end, source, feed)
        day_config_map = _build_day_config_map(
            trading_days, vix_prior, qqq_5min, fallback_bars, fallback_stop
        )

        unique_configs = set(day_config_map.values())
        print(f"  [regime] Pre-computing M1 signals for {len(unique_configs)} regime config(s)...")

        m1_win_ma_switch = m1_win.get("trailing_ma_switch", trailing_ma_switch)
        m1_win_ma_switch_period = m1_win.get("trailing_ma_switch_period", trailing_ma_switch_period)
        m1_win_ma_switch_factor = m1_win.get("trailing_ma_switch_factor", trailing_ma_switch_factor)
        _qqq_sb_m1, _qqq_sr_m1 = qqq_align_by_window.get(m1_win["label"], (None, None))

        for (r_bars, r_stop) in unique_configs:
            if (r_bars, r_stop) in regime_primary:
                continue
            print(f"    bars={r_bars} stop={r_stop}...")
            m1_results = {}
            for ticker in tickers:
                df = all_bars.get(ticker, pd.DataFrame())
                if df.empty:
                    m1_results[ticker] = pd.DataFrame()
                    continue
                m1_results[ticker] = compute_signals_with_backtest(
                    df,
                    r_bars,
                    bearish_ma200,
                    r_stop,
                    opening_start_time=m1_start,
                    trailing_ma=trailing_ma,
                    trailing_ma_switch=m1_win_ma_switch,
                    trailing_ma_switch_factor=m1_win_ma_switch_factor,
                    trailing_ma_switch_period=m1_win_ma_switch_period,
                    max_loss_pct=max_loss_pct,
                    armed_ma20_exit=armed_ma20_exit,
                    bearish_regime_dates=bearish_regime_dates,
                    enable_reversal=enable_reversal,
                    reversal_max_bars_held=reversal_max_bars_held,
                    enable_bearish_reversal=enable_bearish_reversal,
                    bearish_reversal_max_bars_held=bearish_reversal_max_bars_held,
                    or_bar_lookback=or_bar_lookback,
                    enable_bearish_reentry=enable_bearish_reentry,
                    bearish_reentry_max_bars=bearish_reentry_max_bars,
                    enable_bullish_reentry=enable_bullish_reentry,
                    bullish_reentry_max_bars=bullish_reentry_max_bars,
                    close_top_pct=m1_win.get("close_top_pct", close_top_pct),
                    filter_flat_or=filter_flat_or,
                    qqq_align_skip_bull=_qqq_sb_m1,
                    qqq_align_skip_bear=_qqq_sr_m1,
                    min_first_bar_range_pct=min_first_bar_range_pct,
                    min_first_bar_volume_mult=min_first_bar_volume_mult,
                    min_or_vol_ratio=min_or_vol_ratio,
                    min_hold_bars=min_hold_bars,
                    stale_cut_mins=stale_cut_mins,
                    stale_cut_threshold=stale_cut_threshold,
                    exit_at_bar_close=exit_at_bar_close,
                    ma_momentum_gate=ma_momentum_gate,
                )
            regime_primary[(r_bars, r_stop)] = {
                ticker: (
                    df[
                        (df["is_reversal"] != True)           # noqa: E712
                        & (df["is_bearish_reentry"] != True)  # noqa: E712
                        & (df["is_bullish_reentry"] != True)  # noqa: E712
                    ]
                    if not df.empty else df
                )
                for ticker, df in m1_results.items()
            }
            regime_by_date[(r_bars, r_stop)] = {
                ticker: ({d_: g for d_, g in df.groupby("date")} if not df.empty else {})
                for ticker, df in m1_results.items()
            }
        print("  [regime] Pre-computation done.")

        bucket_counts = Counter()
        for d_, (b_, s_) in day_config_map.items():
            bucket = next(
                (k for k, v in REGIME_ADAPTIVE_CONFIGS.items() if v == (b_, s_)),
                "fallback",
            )
            bucket_counts[bucket] += 1
        print("  [regime] Day distribution:")
        for bkt, cnt in sorted(bucket_counts.items(), key=lambda x: -x[1]):
            print(f"    {bkt:<20} {cnt:>3} days")
    # ── end regime pre-computation ─────────────────────────────────────────────

    trade_rows = []
    for d in trading_days:
        lookback_start = d - timedelta(days=lookback_days)
        picked_today = set()

        if regime_adaptive and d in day_config_map:
            day_key = day_config_map[d]
            day_regime_bucket = next(
                (k for k, v in REGIME_ADAPTIVE_CONFIGS.items() if v == day_key),
                "fallback",
            )
        else:
            day_key = None
            day_regime_bucket = None

        for win in windows:
            label = win["label"]
            full_results = all_window_results[label]

            # Select the right signal sets for this window on this day.
            if regime_adaptive and label == "M1" and day_key is not None:
                eff_primary_wr = regime_primary[day_key]
                eff_by_date    = regime_by_date[day_key]
                eff_bars       = day_key[0]
            else:
                eff_primary_wr = primary_window_results[label]
                eff_by_date    = results_by_date[label]
                eff_bars       = win["opening_bars"]

            rolling_stats = _compute_rolling_stats(
                tickers, lookback_start, d, eff_primary_wr, ev_trend_days
            )

            # Pool vote: # tickers with positive rolling EV (prior-day data only — no lookahead).
            pool_vote = sum(1 for s in rolling_stats.values() if s["ev_trade"] > 0)

            # Skip this window/day if pool health is below threshold.
            if min_pool_vote_to_trade > 0 and pool_vote < min_pool_vote_to_trade:
                continue

            # Determine dynamic EV gate thresholds for this day.
            if dynamic_ev_gate:
                if pool_vote >= dg_bull_threshold:
                    _dg_regime = "bull"
                elif pool_vote <= dg_bear_threshold:
                    _dg_regime = "bear"
                else:
                    _dg_regime = "neutral"

                if dg_mode == "percentile":
                    # Pool-relative: exclude bottom N% of positive-EV candidates by EV.
                    # Computing only over candidates (ev > min_ev) so the floor moves with
                    # actual pool performance, not dragged down by perpetually negative tickers.
                    candidate_evs = sorted(
                        s["ev_trade"] for s in rolling_stats.values() if s["ev_trade"] > min_ev
                    )
                    if _dg_regime == "bull":
                        _excl_pct = dg_bull_exclude_pct
                    elif _dg_regime == "bear":
                        _excl_pct = dg_bear_exclude_pct
                    else:
                        _excl_pct = dg_neutral_exclude_pct
                    if candidate_evs:
                        cutoff_idx = int(len(candidate_evs) * _excl_pct)
                        _dg_ev_floor = candidate_evs[cutoff_idx] if cutoff_idx < len(candidate_evs) else candidate_evs[-1]
                    else:
                        _dg_ev_floor = min_ev
                else:
                    # threshold mode: fixed absolute WR/W/L floors.
                    if _dg_regime == "bull":
                        _dg_min_wr = dg_bull_min_wr
                        _dg_min_wl = dg_bull_min_wl
                    elif _dg_regime == "bear":
                        _dg_min_wr = dg_bear_min_wr
                        _dg_min_wl = dg_bear_min_wl
                    else:
                        _dg_min_wr = dg_neutral_min_wr
                        _dg_min_wl = dg_neutral_min_wl

            # Adaptive lookback: recompute stats with regime-adjusted window.
            if adaptive_lookback:
                if pool_vote >= al_bull_threshold:
                    _al_days = al_bull_days
                elif pool_vote <= al_bear_threshold:
                    _al_days = al_bear_days
                else:
                    _al_days = al_neutral_days
                _al_lookback_start = d - timedelta(days=_al_days)
                rolling_stats = _compute_rolling_stats(
                    tickers, _al_lookback_start, d, eff_primary_wr, ev_trend_days
                )

            # Bayesian shrinkage: pull each ticker's ev_trade toward pool mean.
            if ev_shrink_k > 0:
                ev_values = [s["ev_trade"] for s in rolling_stats.values()]
                pool_ev_mean = sum(ev_values) / len(ev_values) if ev_values else 0.0
                shrunk = {}
                for t, s in rolling_stats.items():
                    n_obs = max(s["signals"], 1)
                    ev_s = (n_obs * s["ev_trade"] + ev_shrink_k * pool_ev_mean) / (n_obs + ev_shrink_k)
                    shrunk[t] = dict(s)
                    shrunk[t]["ev_trade"] = ev_s
                rolling_stats = shrunk

            if direction_split_ev_gate:
                if pool_vote >= dg_bull_threshold:
                    _ds_min_ev = ds_bull_min_ev
                elif pool_vote <= dg_bear_threshold:
                    _ds_min_ev = ds_bear_min_ev
                else:
                    _ds_min_ev = ds_neutral_min_ev

            # Adaptive entry weight: loosen in bull (breakouts reliable), tighten in bear.
            # Uses same pool_vote tiers as dynamic EV gate.
            if entry_weight_bull is not None or entry_weight_bear is not None:
                if pool_vote >= dg_bull_threshold:
                    _adaptive_entry = entry_weight_bull if entry_weight_bull is not None else score_entry_weight
                elif pool_vote <= dg_bear_threshold:
                    _adaptive_entry = entry_weight_bear if entry_weight_bear is not None else score_entry_weight
                else:
                    _adaptive_entry = score_entry_weight
            else:
                _adaptive_entry = None  # sentinel: use existing regime_scoring logic

            scored = []
            opening_start_t = window_opening_times[label]
            for ticker in tickers:
                if dedup and ticker in picked_today:
                    continue
                today_rows = eff_by_date.get(ticker, {}).get(d)
                if today_rows is None or today_rows.empty:
                    continue
                # Use primary (non-reversal) row for scoring; reversal row carries
                # the extra leg P&L that gets added to the capital sim below.
                primary_today = today_rows[
                    (today_rows["is_reversal"] != True)  # noqa: E712
                    & (today_rows["is_bearish_reentry"] != True)  # noqa: E712
                    & (today_rows["is_bullish_reentry"] != True)  # noqa: E712
                ]
                if primary_today.empty:
                    continue
                row = primary_today.iloc[0]
                rev_today = today_rows[today_rows["is_reversal"] == True]
                rev_row = rev_today.iloc[0] if not rev_today.empty else None
                br_today = today_rows[today_rows["is_bearish_reentry"] == True]
                br_row = br_today.iloc[0] if not br_today.empty else None
                bru_today = today_rows[today_rows["is_bullish_reentry"] == True]
                bru_row = bru_today.iloc[0] if not bru_today.empty else None
                sig = _signal_dict_from_row(row)
                if (
                    min_or_range_windows is None or label in min_or_range_windows
                ) and sig["or_range_pct"] < min_or_range:
                    continue
                if min_ma200_distance > 0 and (
                    min_ma200_distance_windows is None or label in min_ma200_distance_windows
                ):
                    ma200 = row.get("ma200", float("nan"))
                    entry_price = row.get("entry_price", 0.0)
                    if not pd.isna(ma200) and ma200 > 0:
                        pct_above_ma200 = (entry_price - ma200) / ma200 * 100
                        if pct_above_ma200 < min_ma200_distance:
                            continue
                if or_bar_lookback > 0:
                    day_df = bars_by_date.get(ticker, {}).get(d)
                    if day_df is not None:
                        pre_opening = day_df[day_df.index.time < opening_start_t].tail(
                            or_bar_lookback
                        )
                        if len(pre_opening) > 0:
                            avg_recent_bar_range = (
                                pre_opening["High"] - pre_opening["Low"]
                            ).mean()
                            or_range = row["or_high"] - row["or_low"]
                            if or_range < avg_recent_bar_range / 4:
                                entry = row["entry_price"]
                                sig["or_range_pct"] = (
                                    avg_recent_bar_range / entry * 100
                                    if entry != 0
                                    else 0.0
                                )
                if normalize_or_by_adr:
                    _adr = adr_by_ticker_date.get(ticker, {}).get(d)
                    if _adr and _adr > 0:
                        sig["or_range_pct"] = sig["or_range_pct"] / _adr

                stats = rolling_stats[ticker]
                if oracle_picks:
                    _primary_pnl_pct = row["pnl"] / row["entry_price"] * 100 if row["entry_price"] else 0.0
                    _rev_pnl_pct = (rev_row["pnl"] / rev_row["entry_price"] * 100) if (rev_row is not None and rev_row["entry_price"]) else 0.0
                    _br_pnl_pct = (br_row["pnl"] / br_row["entry_price"] * 100) if (br_row is not None and br_row["entry_price"]) else 0.0
                    _bru_pnl_pct = (bru_row["pnl"] / bru_row["entry_price"] * 100) if (bru_row is not None and bru_row["entry_price"]) else 0.0
                    _actual_pnl_pct = _primary_pnl_pct + _rev_pnl_pct + _br_pnl_pct + _bru_pnl_pct
                    s = 0.0
                else:
                    _actual_pnl_pct = 0.0
                    if stats["ev_trade"] < min_ev:
                        continue
                    if dynamic_ev_gate:
                        if dg_mode == "percentile":
                            if stats["ev_trade"] < _dg_ev_floor:
                                continue
                        else:
                            _wl = abs(stats["avg_win_pct"] / stats["avg_loss_pct"]) if stats["avg_loss_pct"] != 0 else 0.0
                            if stats["win_rate"] < _dg_min_wr or _wl < _dg_min_wl:
                                continue
                    if direction_split_ev_gate:
                        dir_ev = (
                            stats["ev_trade_bullish"]
                            if sig["signal"] == "BULLISH"
                            else stats["ev_trade_bearish"]
                        )
                        if dir_ev < _ds_min_ev:
                            continue
                    if direction_regime_filter:
                        if pool_vote >= drf_bull_only_thresh and sig["signal"] == "BEARISH":
                            continue
                        if pool_vote <= drf_bear_only_thresh and sig["signal"] == "BULLISH":
                            continue
                    if random_picks:
                        if stats["ev_trade"] <= 0:
                            continue
                        s = 0.0
                    else:
                        if regime_scoring:
                            regime = qqq_scoring_regime.get(d, "bull")
                            if regime == "bull":
                                eff_entry = regime_bull_entry_weight if regime_bull_entry_weight is not None else score_entry_weight
                                eff_vol   = regime_bull_vol_ratio_weight if regime_bull_vol_ratio_weight is not None else score_vol_ratio_weight
                                eff_aw    = regime_bull_avg_win_weight if regime_bull_avg_win_weight is not None else score_avg_win_weight
                                eff_ma50  = regime_bull_ma50_dist_weight if regime_bull_ma50_dist_weight is not None else score_ma50_dist_weight
                            else:
                                eff_entry = regime_bear_entry_weight if regime_bear_entry_weight is not None else score_entry_weight
                                eff_vol   = regime_bear_vol_ratio_weight if regime_bear_vol_ratio_weight is not None else score_vol_ratio_weight
                                eff_aw    = regime_bear_avg_win_weight if regime_bear_avg_win_weight is not None else score_avg_win_weight
                                eff_ma50  = regime_bear_ma50_dist_weight if regime_bear_ma50_dist_weight is not None else score_ma50_dist_weight
                        else:
                            eff_entry = score_entry_weight
                            eff_vol   = score_vol_ratio_weight
                            eff_aw    = score_avg_win_weight
                            eff_ma50  = score_ma50_dist_weight
                        # Pool-vote adaptive entry weight overrides base (not regime_scoring).
                        if _adaptive_entry is not None and not regime_scoring:
                            eff_entry = _adaptive_entry
                        s = score_ticker(
                            sig, stats,
                            eff_entry, eff_vol,
                            eff_aw, score_ev_trend_weight,
                            score_dist_52w_low_weight, score_streak_weight,
                            score_prev_day_vol_weight, score_ma200_dist_weight,
                            eff_ma50,
                            score_win_rate_weight=score_win_rate_weight,
                            score_trend_align_weight=score_trend_align_weight,
                            score_dist_52w_high_weight=score_dist_52w_high_weight,
                            score_frog_weight=score_frog_weight,
                            score_rel_strength_weight=score_rel_strength_weight,
                            score_dir_ev_weight=score_dir_ev_weight,
                            daily_context=daily_context_by_ticker.get(ticker, {}).get(d),
                            ma_momentum_gate_in_scoring=ma_momentum_gate_in_scoring,
                        )
                        if s == 0.0:
                            continue
                        if qqq_or_weight != 0.0:
                            # Positive alignment: signal direction matches QQQ OR direction.
                            # BULLISH benefits from positive QQQ OR; BEARISH from negative.
                            _qqq_or = qqq_or_by_date.get(d, 0.0)
                            _align = _qqq_or if sig["signal"] == "BULLISH" else -_qqq_or
                            s += qqq_or_weight * _align
                        if s < min_score:
                            continue
                scored.append(
                    {
                        "ticker": ticker,
                        "score": round(s, 3),
                        "actual_pnl_pct": round(_actual_pnl_pct, 3),
                        "signal": row["signal"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "or_high": float(row["or_high"]),
                        "or_low": float(row["or_low"]),
                        "midpoint": row["midpoint"],
                        "pnl": row["pnl"],
                        "success": bool(row["success"]),
                        "exit_reason": row["exit_reason"],
                        "entry_vs_mid_pct": round(sig["entry_vs_mid_pct"], 3),
                        "or_range_pct": round(sig["or_range_pct"], 3),
                        "rolling_ev": round(stats["ev_trade"], 3),
                        "rolling_win_rate": round(stats["win_rate"], 3),
                        "rev_pnl": float(rev_row["pnl"])
                        if rev_row is not None
                        else 0.0,
                        "rev_entry_price": float(rev_row["entry_price"])
                        if rev_row is not None
                        else 0.0,
                        "rev_exit_price": float(rev_row["exit_price"])
                        if rev_row is not None
                        else 0.0,
                        "rev_exit_reason": str(rev_row["exit_reason"])
                        if rev_row is not None
                        else "",
                        "rev_bars_held": int(rev_row["bars_held"])
                        if rev_row is not None
                        else 0,
                        "rev_entry_idx": int(rev_row.get("entry_idx", 0))
                        if rev_row is not None
                        else 0,
                        "br_pnl": float(br_row["pnl"]) if br_row is not None else 0.0,
                        "br_entry_price": float(br_row["entry_price"])
                        if br_row is not None
                        else 0.0,
                        "br_exit_price": float(br_row["exit_price"])
                        if br_row is not None
                        else 0.0,
                        "br_exit_reason": str(br_row["exit_reason"])
                        if br_row is not None
                        else "",
                        "br_bars_held": int(br_row["bars_held"])
                        if br_row is not None
                        else 0,
                        "br_entry_idx": int(br_row.get("entry_idx", 0))
                        if br_row is not None
                        else 0,
                        "bru_pnl": float(bru_row["pnl"])
                        if bru_row is not None
                        else 0.0,
                        "bru_entry_price": float(bru_row["entry_price"])
                        if bru_row is not None
                        else 0.0,
                        "bru_exit_price": float(bru_row["exit_price"])
                        if bru_row is not None
                        else 0.0,
                        "bru_exit_reason": str(bru_row["exit_reason"])
                        if bru_row is not None
                        else "",
                        "bru_bars_held": int(bru_row["bars_held"])
                        if bru_row is not None
                        else 0,
                        "bru_entry_idx": int(bru_row.get("entry_idx", 0))
                        if bru_row is not None
                        else 0,
                        "bars_held": int(row["bars_held"]),
                        "mins_held": int(row["mins_held"]),
                    }
                )

            if oracle_picks:
                scored.sort(key=lambda x: x["actual_pnl_pct"], reverse=True)
                picks_today = scored[:n]
            elif random_picks:
                picks_today = random.sample(scored, min(n, len(scored)))
            else:
                scored.sort(key=lambda x: x["score"], reverse=True)
                picks_today = scored[:n]
            for rank, pick in enumerate(picks_today, 1):
                picked_today.add(pick["ticker"])
                primary_pnl_pct = pick["pnl"] / pick["entry_price"] * 100
                rev_pnl_pct = (
                    pick["rev_pnl"] / pick["rev_entry_price"] * 100
                    if pick["rev_entry_price"] != 0
                    else 0.0
                )
                br_pnl_pct = (
                    pick["br_pnl"] / pick["br_entry_price"] * 100
                    if pick["br_entry_price"] != 0
                    else 0.0
                )
                bru_pnl_pct = (
                    pick["bru_pnl"] / pick["bru_entry_price"] * 100
                    if pick["bru_entry_price"] != 0
                    else 0.0
                )
                combined_pnl_pct = (
                    primary_pnl_pct + rev_pnl_pct + br_pnl_pct + bru_pnl_pct
                )
                _h, _m = map(int, win["opening_start"].split(":"))
                _or_close_min = _h * 60 + _m + eff_bars * 5
                _primary_bars = pick["bars_held"]
                # Compute how many bars from OR close until the slot is fully returned,
                # accounting for BRE/BRU/REV sub-trades that start after the primary exits.
                # Formula: sub_exit = primary_bars_held + 1 (gap to sub-trade entry scan start)
                #                     + sub_entry_idx (bars into scan before sub-trade fires)
                #                     + 1 (the entry bar itself)
                #                     + sub_bars_held (bars the sub-trade holds after entry)
                _br_exit = (
                    _primary_bars + 1 + pick.get("br_entry_idx", 0) + 1 + pick.get("br_bars_held", 0)
                    if pick.get("br_entry_price") else 0
                )
                _bru_exit = (
                    _primary_bars + 1 + pick.get("bru_entry_idx", 0) + 1 + pick.get("bru_bars_held", 0)
                    if pick.get("bru_entry_price") else 0
                )
                _rev_exit = (
                    _primary_bars + 1 + pick.get("rev_entry_idx", 0) + 1 + pick.get("rev_bars_held", 0)
                    if pick.get("rev_entry_price") else 0
                )
                _slot_exit_bars = max(_primary_bars, _br_exit, _bru_exit, _rev_exit)
                trade_rows.append(
                    {
                        "date": d,
                        "window": label,
                        "rank": rank,
                        "or_close_min": _or_close_min,
                        "regime": day_regime_bucket,
                        "pnl_pct": round(combined_pnl_pct, 3),
                        "success": combined_pnl_pct > 0,
                        # cap_pnl, window_capital, skipped filled in by _apply_capital_flow
                        "cap_pnl": 0.0,
                        "window_capital": 0.0,
                        "skipped": False,
                        "slot_exit_bars": _slot_exit_bars,
                        **{
                            k: v
                            for k, v in pick.items()
                            if k
                            not in (
                                "success",
                                "br_pnl",
                                "br_entry_price",
                                "br_exit_price",
                                "br_exit_reason",
                                "bru_pnl",
                                "bru_entry_price",
                                "bru_exit_price",
                                "bru_exit_reason",
                            )
                        },
                        "br_pnl": pick["br_pnl"],
                        "br_entry_price": pick["br_entry_price"],
                        "br_exit_price": pick["br_exit_price"],
                        "br_exit_reason": pick["br_exit_reason"],
                        "bru_pnl": pick["bru_pnl"],
                        "bru_entry_price": pick["bru_entry_price"],
                        "bru_exit_price": pick["bru_exit_price"],
                        "bru_exit_reason": pick["bru_exit_reason"],
                    }
                )

    if enable_doubledown:
        opening_bars_by_label = {win["label"]: win["opening_bars"] for win in windows}
        _annotate_doubledown_addon(
            trade_rows, bars_by_date, window_opening_times, opening_bars_by_label,
            doubledown_start_min=doubledown_start_min,
        )

    return trade_rows, all_window_results, trading_days


def _apply_doubledown(trade_rows: list) -> None:
    """
    Apply double-down add-on P&L across all windows in trade_rows.

    Called after _apply_capital_flow so that DD P&L is NOT recycled into
    sequential window (A1/A2) capital. The DD leg runs to its own natural
    exit (trailing stop or EOD) independently — A1/A2 use only the base
    primary-leg capital, not freed capital from the DD addon.
    """
    by_day_window: dict = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    for rows in by_day_window.values():
        _apply_doubledown_window(rows)


def _apply_opportunity_pool(
    trade_rows: list,
    windows: list,
    initial_pool: float,
    compound: bool = False,
    doubledown_start_min: int = DOUBLEDOWN_START_MIN,
) -> None:
    """
    Deploy the opportunity pool on DD-eligible winner rows, recycling capital
    sequentially within each day across windows.

    Requires _annotate_doubledown_addon and _apply_capital_flow to have run first.
    Mutates winner rows in-place, adding:
      opp_deployed   float  capital deployed from pool at this window's DD
      opp_cap_pnl    float  dollar P&L from the deployment (signed)
      opp_returned   float  capital returned after exit (floor 0)
    Also folds opp_cap_pnl into winner["cap_pnl"] so weekly/monthly totals pick it up.
    """
    if initial_pool <= 0:
        return

    dd_bars = doubledown_start_min // 5
    window_labels = [w["label"] for w in windows]

    or_close_min_by_label = {}
    for w in windows:
        h, m = map(int, w["opening_start"].split(":"))
        or_close_min_by_label[w["label"]] = h * 60 + m + w["opening_bars"] * 5

    by_day_window: dict = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    trading_days = sorted({row["date"] for row in trade_rows})
    pool = initial_pool

    for d in trading_days:
        if not compound:
            pool = initial_pool

        pool_exit_min = 0  # 0 = pool is free; set after each deployment

        for label in window_labels:
            or_close_min = or_close_min_by_label[label]
            dd_fire_min = or_close_min + dd_bars * 5

            if pool_exit_min > dd_fire_min:
                continue  # prior deployment still running — pool locked

            if pool <= 0:
                continue

            rows = by_day_window.get((d, label), [])
            winner = next(
                (r for r in rows if "dd_freed_ranks" in r and not r.get("skipped")),
                None,
            )
            if winner is None:
                continue

            if winner.get("bars_held", 0) < dd_bars:
                continue  # safety guard (annotation already enforces this)

            pnl_pct = winner.get("dd_addon_pnl_pct", 0.0)
            opp_cap_pnl = pool * pnl_pct
            opp_returned = max(pool + opp_cap_pnl, 0.0)

            winner["opp_deployed"] = pool
            winner["opp_cap_pnl"] = opp_cap_pnl
            winner["opp_returned"] = opp_returned
            winner["cap_pnl"] = winner.get("cap_pnl", 0.0) + opp_cap_pnl

            pool = opp_returned

            if winner.get("exit_reason") == "end_of_day":
                pool_exit_min = 960
            else:
                pool_exit_min = or_close_min + (winner["bars_held"] + 1) * 5


def _collect_baseline(
    all_window_results: dict, eval_start: date, eval_end: date
) -> pd.DataFrame:
    first_window_results = next(iter(all_window_results.values()))
    frames = []
    for ticker, df in first_window_results.items():
        if df.empty:
            continue
        window = df[(df["date"] >= eval_start) & (df["date"] <= eval_end)].copy()
        if window.empty:
            continue
        window["ticker"] = ticker
        frames.append(window)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _parse_weights(weights_input: list, n: int) -> list:
    """Return per-rank capital fractions for the top-n positions.

    When more weights than n are provided (e.g. --weights 50 30 20 with --top 2),
    the first n weights are used and the remainder is undeployed capital — matching
    the live engine's rank-indexed weight assignment.  The fractions are normalised
    relative to the *total* of all provided weights so the caller's intent (e.g.
    50%/30%/20%) is preserved; only n of them are returned.
    """
    if not weights_input:
        return [1.0 / n] * n
    total = sum(weights_input)
    fracs = [w / total for w in weights_input]
    if len(fracs) >= n:
        return fracs[:n]
    return [1.0 / n] * n


def _weights_label(weights: list, initial_capital: float) -> str:
    if len(set(round(w, 6) for w in weights)) == 1:
        return f"${initial_capital * weights[0]:,.0f}/slot × {len(weights)} slots"
    pcts = "/".join(f"{w * 100:.0f}%" for w in weights)
    return f"weighted {pcts} × {len(weights)} slots"


def _print_regime_summary(trade_rows: list, trading_days: list):
    from collections import defaultdict
    bucket_order = list(REGIME_ADAPTIVE_CONFIGS.keys()) + ["fallback", None]
    stats = defaultdict(lambda: {"days": 0, "trades": 0, "wins": 0, "pnl": 0.0})

    day_buckets = {}
    for row in trade_rows:
        if row.get("window") != "M1" or row.get("skipped"):
            continue
        d = row["date"]
        bucket = row.get("regime") or "fallback"
        day_buckets[d] = bucket
        stats[bucket]["trades"] += 1
        stats[bucket]["wins"] += 1 if row.get("success") else 0
        stats[bucket]["pnl"] += row.get("cap_pnl", 0.0)

    all_days_set = set(trading_days)
    traded_days = set(day_buckets.keys())
    untraded_days = all_days_set - traded_days
    for d in untraded_days:
        stats[None]["days"] += 1

    for d, bkt in day_buckets.items():
        stats[bkt]["days"] += 1

    n_total = len(trading_days)
    print(f"\n{'─'*70}")
    print("  Regime Adaptive — M1 Day Distribution")
    print(f"{'─'*70}")
    print(f"  {'Bucket':<22} {'Days':>5}  {'Trades':>6}  {'Win%':>6}  {'P&L':>10}")
    for bkt in bucket_order:
        s = stats.get(bkt)
        if not s or s["days"] == 0:
            continue
        label = bkt if bkt else "(no trades)"
        n_trades = s["trades"]
        wr = f"{s['wins']/n_trades*100:.0f}%" if n_trades else "  —"
        pnl_str = f"${s['pnl']:>+,.0f}"
        pct = f"({s['days']/n_total*100:.0f}%)"
        print(f"  {label:<22} {s['days']:>4}{pct:>4}  {n_trades:>6}  {wr:>6}  {pnl_str:>10}")
    print(f"{'─'*70}")


def _print_skip_log(skip_log: list, windows: list):
    if not skip_log:
        return
    sep = "\u2501" * 80
    print(f"\n{sep}")
    print(f"  WINDOW EXECUTION LOG")
    print(sep)
    print(f"  {'Date':<12} {'Window':<8} {'Status':<22} {'Capital':>10}  {'Picks':>5}")
    print(f"  {'─' * 76}")

    skipped_count = 0
    executed_count = 0
    no_signal_count = 0

    prev_date = None
    for entry in skip_log:
        d = entry["date"]
        if d != prev_date and prev_date is not None:
            print(f"  {'─' * 76}")
        prev_date = d

        status = entry["status"]
        cap = entry["available_capital"]
        picks = entry["picks"]

        if status == "skipped_low_capital":
            skipped_count += 1
            status_display = "SKIPPED (low capital)"
        elif status == "no_signal":
            no_signal_count += 1
            status_display = "no signal"
        else:
            executed_count += 1
            status_display = f"executed ({picks} picks)"

        print(
            f"  {str(d):<12} {entry['window']:<8} {status_display:<22} ${cap:>9,.2f}  {picks:>5}"
        )

    print(f"  {'─' * 76}")
    print(
        f"  Executed: {executed_count}  |  No signal: {no_signal_count}  |  Skipped (low capital): {skipped_count}"
    )
    print(sep)


_REENTRY_TYPES = [
    ("[REV]", "rev_entry_price", "rev_pnl", "rev_exit_price", "rev_exit_reason", "rev_entry_idx", "rev_bars_held"),
    ("[BRE]", "br_entry_price", "br_pnl", "br_exit_price", "br_exit_reason", "br_entry_idx", "br_bars_held"),
    ("[BRU]", "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason", "bru_entry_idx", "bru_bars_held"),
]


def _print_reentry_subrow(
    row: dict,
    label: str,
    ep_key: str,
    pnl_key: str,
    exit_price_key: str,
    exit_reason_key: str,
    entry_idx_key: str,
    bars_held_key: str,
    multi_window: bool,
    fmt_bar_time,
):
    ep = row.get(ep_key, 0)
    if not ep:
        return None
    blank_win = f"{'':5} " if multi_window else ""

    or_close = row.get("or_close_min")
    primary_bars = row.get("bars_held", 0)
    entry_idx = row.get(entry_idx_key, 0)
    sub_bars = row.get(bars_held_key, 0)
    if or_close is not None:
        sub_entry_min = or_close + (primary_bars + entry_idx + 2) * 5
        exit_reason = row.get(exit_reason_key, "")
        if exit_reason == "end_of_day":
            sub_exit_str = _EOD_DISPLAY_TIME
        else:
            sub_exit_min = sub_entry_min + (sub_bars + 1) * 5
            sub_exit_str = fmt_bar_time(sub_exit_min)
        sub_entry_str = fmt_bar_time(sub_entry_min)
    else:
        sub_entry_str = "—"
        sub_exit_str = "—"

    cancelled = row.get("reentry_cancelled_by_dd") or row.get("bru_cancelled")
    if cancelled:
        cancel_reason = "cancelled by DD" if row.get("reentry_cancelled_by_dd") else "cancelled (capital recycled)"
        print(
            f"  {'':12} {blank_win}{'':5} {'':6} "
            f"{label:<9} {'':>5}  "
            f"{sub_entry_str:>5} {'':>5}  "
            f"{ep:>7.2f} {'':>7} "
            f"{'':>7} {'':>7}  {'':6}  {cancel_reason}"
        )
        return None
    p = row[pnl_key]
    pct = p / ep * 100
    pnl_str = f"+${abs(p):.2f}" if p >= 0 else f"-${abs(p):.2f}"
    pct_str = f"+{abs(pct):.2f}%" if pct >= 0 else f"{pct:.2f}%"
    result = "WIN" if p > 0 else "LOSS"
    print(
        f"  {'':12} {blank_win}{'':5} {'':6} "
        f"{label:<9} {'':>5}  "
        f"{sub_entry_str:>5} {sub_exit_str:>5}  "
        f"{ep:>7.2f} {row[exit_price_key]:>7.2f} "
        f"{pnl_str:>7} {pct_str:>7}  {result:<6}  {row[exit_reason_key]}"
    )
    return p, pct


def _print_daily_table(
    trade_rows: list,
    n: int,
    initial_capital: float = INITIAL_CAPITAL,
    weights: list = None,
    multi_window: bool = False,
):
    def _fmt_bar_time(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _entry_exit_times(row) -> tuple:
        or_close = row.get("or_close_min")
        if or_close is None:
            return "—", "—"
        entry_str = _fmt_bar_time(or_close)
        if row.get("exit_reason") == "end_of_day":
            exit_str = _EOD_DISPLAY_TIME
        else:
            exit_str = _fmt_bar_time(or_close + (row.get("bars_held", 0) + 1) * 5)
        return entry_str, exit_str

    weights = weights or _parse_weights(None, n)
    active_rows = [r for r in trade_rows if not r.get("skipped")]
    sep = "\u2501" * 110
    win_col = f"{'Win':<5} " if multi_window else ""
    print(f"\n{sep}")
    print(
        f"  {'Date':<12} {win_col}{'Rank':<5} {'Ticker':<6} {'Signal':<9} {'Score':>5}  "
        f"{'In':>5} {'Out':>5}  {'Entry':>7} {'Exit':>7} {'P&L$':>7} {'P&L%':>7}  {'Result':<6}  Exit Reason"
    )
    print(sep)

    current_date = None
    current_window = None
    day_pnl = 0.0
    day_pnl_pcts = []
    day_wins = 0
    day_losses = 0
    running_total = 0.0
    day_cap_pnl = 0.0
    portfolio = initial_capital

    for row in active_rows:
        row_date = row["date"]
        row_window = row["window"]

        if row_date != current_date:
            if current_date is not None:
                portfolio += day_cap_pnl
                _print_day_summary(
                    day_wins,
                    day_losses,
                    day_pnl,
                    day_pnl_pcts,
                    running_total,
                    day_cap_pnl,
                    initial_capital,
                    portfolio,
                    multi_window=multi_window,
                )
            current_date = row_date
            current_window = None
            day_pnl = 0.0
            day_pnl_pcts = []
            day_wins = 0
            day_losses = 0
            day_cap_pnl = 0.0

        if multi_window and row_window != current_window:
            if current_window is not None:
                print(f"  {'·' * 108}")
            current_window = row_window

        pnl = row["pnl"]
        pnl_pct = pnl / row["entry_price"] * 100
        result = "WIN" if pnl > 0 else "LOSS"
        pnl_str = f"+${abs(pnl):.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        pnl_pct_str = f"+{abs(pnl_pct):.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
        win_str = f"{row_window:<5} " if multi_window else ""
        t_in, t_out = _entry_exit_times(row)

        print(
            f"  {str(row_date):<12} {win_str}{row['rank']:<5} {row['ticker']:<6} "
            f"{row['signal']:<9} {row['score']:>5.2f}  "
            f"{t_in:>5} {t_out:>5}  "
            f"{row['entry_price']:>7.2f} {row['exit_price']:>7.2f} "
            f"{pnl_str:>7} {pnl_pct_str:>7}  {result:<6}  {row['exit_reason']}"
        )

        day_pnl += pnl
        day_pnl_pcts.append(pnl_pct)
        running_total += pnl
        day_cap_pnl += row["cap_pnl"]
        if pnl > 0:
            day_wins += 1
        else:
            day_losses += 1

        for (
            _label,
            _ep_key,
            _pnl_key,
            _exit_price_key,
            _exit_reason_key,
            _entry_idx_key,
            _bars_held_key,
        ) in _REENTRY_TYPES:
            sub = _print_reentry_subrow(
                row,
                _label,
                _ep_key,
                _pnl_key,
                _exit_price_key,
                _exit_reason_key,
                _entry_idx_key,
                _bars_held_key,
                multi_window,
                _fmt_bar_time,
            )
            if sub is not None:
                p, pct = sub
                day_pnl += p
                day_pnl_pcts.append(pct)
                running_total += p
                if p > 0:
                    day_wins += 1
                else:
                    day_losses += 1

        dd_cap_pnl = row.get("dd_addon_cap_pnl", 0.0)
        if dd_cap_pnl != 0.0:
            freed = row.get("dd_freed_capital", 0.0)
            addon_entry = row.get("dd_addon_entry", 0.0)
            freed_ranks = row.get("dd_freed_ranks", [])
            effective_exit = row.get("dd_addon_effective_exit", float(row["exit_price"]))
            if row["signal"] == "BULLISH":
                per_share = effective_exit - addon_entry
            else:
                per_share = addon_entry - effective_exit
            pnl_pct = per_share / addon_entry * 100 if addon_entry else 0.0
            pnl_str = f"+${per_share:.2f}" if per_share >= 0 else f"-${abs(per_share):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            outcome = "WIN" if per_share >= 0 else "LOSS"
            blank_win = f"{'':5} " if multi_window else ""
            ranks_str = "/".join(f"R{r}" for r in freed_ranks)
            dd_fire_min = row.get("dd_fire_min")
            if dd_fire_min is not None:
                dd_in_str = _fmt_bar_time(dd_fire_min)
                dd_out_str = _EOD_DISPLAY_TIME if row.get("exit_reason") == "end_of_day" \
                    else _fmt_bar_time(row.get("or_close_min", 0) + (row.get("bars_held", 0) + 1) * 5)
            else:
                dd_in_str = "—"
                dd_out_str = "—"
            print(
                f"  {'':12} {blank_win}{'':5} {'':6} "
                f"{'[DD]':<9} {'':>5}  "
                f"{dd_in_str:>5} {dd_out_str:>5}  "
                f"{addon_entry:>7.2f} {effective_exit:>7.2f} "
                f"{pnl_str:>7} {pct_str:>7}  {outcome:<6}  freed ${freed:.0f} ← {ranks_str}"
            )

        opp_cap_pnl = row.get("opp_cap_pnl")
        if opp_cap_pnl is not None:
            opp_deployed = row.get("opp_deployed", 0.0)
            opp_returned = row.get("opp_returned", 0.0)
            addon_entry = row.get("dd_addon_entry", 0.0)
            effective_exit = row.get("dd_addon_effective_exit", float(row["exit_price"]))
            if row["signal"] == "BULLISH":
                per_share = effective_exit - addon_entry
            else:
                per_share = addon_entry - effective_exit
            pnl_pct = per_share / addon_entry * 100 if addon_entry else 0.0
            pnl_str = f"+${per_share:.2f}" if per_share >= 0 else f"-${abs(per_share):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            outcome = "WIN" if opp_cap_pnl >= 0 else "LOSS"
            opp_net_str = (
                f"+${abs(opp_cap_pnl):.2f}" if opp_cap_pnl >= 0 else f"-${abs(opp_cap_pnl):.2f}"
            )
            blank_win = f"{'':5} " if multi_window else ""
            dd_fire_min = row.get("dd_fire_min")
            if dd_fire_min is not None:
                opp_in_str = _fmt_bar_time(dd_fire_min)
                opp_out_str = _EOD_DISPLAY_TIME if row.get("exit_reason") == "end_of_day" \
                    else _fmt_bar_time(row.get("or_close_min", 0) + (row.get("bars_held", 0) + 1) * 5)
            else:
                opp_in_str = "—"
                opp_out_str = "—"
            print(
                f"  {'':12} {blank_win}{'':5} {'':6} "
                f"{'[OPP]':<9} {'':>5}  "
                f"{opp_in_str:>5} {opp_out_str:>5}  "
                f"{addon_entry:>7.2f} {effective_exit:>7.2f} "
                f"{pnl_str:>7} {pct_str:>7}  {outcome:<6}  "
                f"pool ${opp_deployed:,.0f} → ${opp_returned:,.0f}  ({opp_net_str})"
            )

    if current_date is not None:
        portfolio += day_cap_pnl
        _print_day_summary(
            day_wins,
            day_losses,
            day_pnl,
            day_pnl_pcts,
            running_total,
            day_cap_pnl,
            initial_capital,
            portfolio,
            multi_window=multi_window,
        )

    print(sep)


def _print_day_summary(
    wins,
    losses,
    day_pnl,
    day_pnl_pcts,
    running_total,
    day_cap_pnl,
    initial_capital,
    portfolio,
    multi_window: bool = False,
):
    total = wins + losses
    if total == 0:
        return
    pnl_str = f"+${abs(day_pnl):.2f}" if day_pnl >= 0 else f"-${abs(day_pnl):.2f}"
    avg_pct = sum(day_pnl_pcts) / len(day_pnl_pcts)
    avg_pct_str = f"+{abs(avg_pct):.2f}%" if avg_pct >= 0 else f"{avg_pct:.2f}%"
    cap_pnl_str = (
        f"+${abs(day_cap_pnl):.2f}" if day_cap_pnl >= 0 else f"-${abs(day_cap_pnl):.2f}"
    )
    day_ret_pct = day_cap_pnl / initial_capital * 100
    day_ret_str = (
        f"+{abs(day_ret_pct):.2f}%" if day_ret_pct >= 0 else f"{day_ret_pct:.2f}%"
    )
    win_pad = "      " if multi_window else ""
    print(
        f"  {'':12} {win_pad}{'':5} {'':6} {'':9} {'':5}  "
        f"{'':>5} {'':>5}  {'':>7} {'':>7} {pnl_str:>7} {avg_pct_str:>7}  "
        f"{wins}W/{losses}L  │  cap: {cap_pnl_str} ({day_ret_str})  portfolio: ${portfolio:.2f}"
    )
    print(f"  {'─' * 108}")


def _stats_from_trades(trade_rows: list) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    total = len(active)
    if total == 0:
        return None
    wins = sum(1 for r in active if r["success"])
    losses = total - wins
    win_rate = wins / total
    win_pct_vals = [r["pnl_pct"] for r in active if r["success"]]
    loss_pct_vals = [abs(r["pnl_pct"]) for r in active if not r["success"]]
    avg_win_pct = sum(win_pct_vals) / len(win_pct_vals) if win_pct_vals else 0.0
    avg_loss_pct = sum(loss_pct_vals) / len(loss_pct_vals) if loss_pct_vals else 0.0
    ev = win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct
    net_pnl = sum(r["pnl"] for r in active)

    rev_rows = [r for r in active if r.get("rev_entry_price", 0)]
    rev_total = len(rev_rows)
    rev_wins = sum(1 for r in rev_rows if r.get("rev_pnl", 0) > 0)
    rev_losses = rev_total - rev_wins

    br_rows = [r for r in active if r.get("br_entry_price", 0)]
    br_total = len(br_rows)
    br_wins = sum(1 for r in br_rows if r.get("br_pnl", 0) > 0)
    br_losses = br_total - br_wins

    bru_rows = [r for r in active if r.get("bru_entry_price", 0)]
    bru_total = len(bru_rows)
    bru_wins = sum(1 for r in bru_rows if r.get("bru_pnl", 0) > 0)
    bru_losses = bru_total - bru_wins

    dd_rows = [r for r in active if r.get("dd_addon_cap_pnl", 0.0) != 0.0]
    dd_total = len(dd_rows)
    dd_wins = sum(1 for r in dd_rows if r.get("dd_addon_cap_pnl", 0.0) > 0)
    dd_losses = dd_total - dd_wins
    dd_net_cap_pnl = sum(r.get("dd_addon_cap_pnl", 0.0) for r in dd_rows)

    opp_rows = [r for r in active if r.get("opp_cap_pnl") is not None]
    opp_total = len(opp_rows)
    opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
    opp_losses = opp_total - opp_wins
    opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)

    short_rows = [r for r in active if r.get("mins_held", 999) <= 15]
    short_total = len(short_rows)
    short_wins = sum(1 for r in short_rows if r["success"])

    vshort_rows = [r for r in active if r.get("mins_held", 999) <= 10]
    vshort_total = len(vshort_rows)
    vshort_wins = sum(1 for r in vshort_rows if r["success"])

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ev": ev,
        "net_pnl": net_pnl,
        "rev_total": rev_total,
        "rev_wins": rev_wins,
        "rev_losses": rev_losses,
        "br_total": br_total,
        "br_wins": br_wins,
        "br_losses": br_losses,
        "bru_total": bru_total,
        "bru_wins": bru_wins,
        "bru_losses": bru_losses,
        "dd_total": dd_total,
        "dd_wins": dd_wins,
        "dd_losses": dd_losses,
        "dd_net_cap_pnl": dd_net_cap_pnl,
        "opp_total": opp_total,
        "opp_wins": opp_wins,
        "opp_losses": opp_losses,
        "opp_net_cap_pnl": opp_net_cap_pnl,
        "short_total": short_total,
        "short_wins": short_wins,
        "vshort_total": vshort_total,
        "vshort_wins": vshort_wins,
    }


def _print_stats_block(label: str, stats: dict):
    if stats is None:
        print(f"  {label}: no trades")
        return
    net_str = (
        f"+${stats['net_pnl']:.2f}"
        if stats["net_pnl"] >= 0
        else f"-${abs(stats['net_pnl']):.2f}"
    )
    ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
    print(f"\n  {label}")
    print(f"  {'─' * 48}")
    print(
        f"  Trades          : {stats['total']}  ({stats['wins']}W / {stats['losses']}L)"
    )
    if stats.get("rev_total", 0):
        print(
            f"  Reversals       : {stats['rev_total']}  ({stats['rev_wins']}W / {stats['rev_losses']}L)"
        )
    if stats.get("br_total", 0):
        print(
            f"  Bearish re-entry: {stats['br_total']}  ({stats['br_wins']}W / {stats['br_losses']}L)"
        )
    if stats.get("bru_total", 0):
        print(
            f"  Bullish re-entry: {stats['bru_total']}  ({stats['bru_wins']}W / {stats['bru_losses']}L)"
        )
    if stats.get("dd_total", 0):
        dd_net = stats["dd_net_cap_pnl"]
        dd_net_str = f"+${dd_net:.2f}" if dd_net >= 0 else f"-${abs(dd_net):.2f}"
        print(
            f"  Double-down     : {stats['dd_total']}  ({stats['dd_wins']}W / {stats['dd_losses']}L)"
            f"  net cap P&L: {dd_net_str}"
        )
    if stats.get("opp_total", 0):
        opp_net = stats["opp_net_cap_pnl"]
        opp_net_str = f"+${opp_net:.2f}" if opp_net >= 0 else f"-${abs(opp_net):.2f}"
        print(
            f"  Opportunity pool: {stats['opp_total']}  ({stats['opp_wins']}W / {stats['opp_losses']}L)"
            f"  net cap P&L: {opp_net_str}"
        )
    print(f"  Win rate        : {stats['win_rate'] * 100:.0f}%")
    if stats.get("vshort_total", 0):
        vshort_wr = stats["vshort_wins"] / stats["vshort_total"] * 100
        short_wr = stats["short_wins"] / stats["short_total"] * 100 if stats.get("short_total") else 0
        print(
            f"  Short trades    : {stats['vshort_total']}  (≤10 min)  WR: {vshort_wr:.0f}%"
            f"  |  {stats['short_total']}  (≤15 min)  WR: {short_wr:.0f}%"
        )
    elif stats.get("short_total", 0):
        short_wr = stats["short_wins"] / stats["short_total"] * 100
        print(f"  Short trades    : {stats['short_total']}  (≤15 min)  WR: {short_wr:.0f}%")
    print(f"  Avg win  %      : +{stats['avg_win_pct']:.2f}%  per trade")
    print(f"  Avg loss %      : -{stats['avg_loss_pct']:.2f}%  per trade")
    print(f"  EV / trade      : {ev_str}")
    print(f"  Net P&L (1 sh)  : {net_str}")


def _capital_stats_from_trades(trade_rows: list, initial_capital: float) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    total_cap_pnl = sum(r["cap_pnl"] for r in active)
    days_with_picks = set(r["date"] for r in active)

    daily_cap_pnls = {}
    for row in active:
        d = row["date"]
        daily_cap_pnls[d] = daily_cap_pnls.get(d, 0.0) + row["cap_pnl"]

    daily_returns = list(daily_cap_pnls.values())
    avg_daily_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    return {
        "initial_capital": initial_capital,
        "total_cap_pnl": total_cap_pnl,
        "total_return_pct": total_cap_pnl / initial_capital * 100,
        "final_portfolio": initial_capital + total_cap_pnl,
        "days_with_picks": len(days_with_picks),
        "avg_daily_ret": avg_daily_ret,
        "avg_daily_ret_pct": avg_daily_ret / initial_capital * 100,
    }


def _print_capital_stats_block(stats: dict, weights_label: str = ""):
    cap_pnl_str = (
        f"+${stats['total_cap_pnl']:.2f}"
        if stats["total_cap_pnl"] >= 0
        else f"-${abs(stats['total_cap_pnl']):.2f}"
    )
    ret_pct_str = (
        f"+{stats['total_return_pct']:.2f}%"
        if stats["total_return_pct"] >= 0
        else f"{stats['total_return_pct']:.2f}%"
    )
    avg_str = (
        f"+${stats['avg_daily_ret']:.2f}"
        if stats["avg_daily_ret"] >= 0
        else f"-${abs(stats['avg_daily_ret']):.2f}"
    )
    avg_pct_str = (
        f"+{stats['avg_daily_ret_pct']:.2f}%"
        if stats["avg_daily_ret_pct"] >= 0
        else f"{stats['avg_daily_ret_pct']:.2f}%"
    )
    label = f"${stats['initial_capital']:,.0f} initial"
    if weights_label:
        label += f" | {weights_label}"
    print(f"\n  CAPITAL SIMULATION  ({label})")
    print(f"  {'─' * 48}")
    print(f"  Total return ($)    : {cap_pnl_str}")
    print(f"  Total return (%)    : {ret_pct_str}")
    print(f"  Final portfolio     : ${stats['final_portfolio']:,.2f}")
    print(f"  Days with picks     : {stats['days_with_picks']}")
    print(f"  Avg daily return    : {avg_str}  ({avg_pct_str})")


def _print_per_window_stats(
    trade_rows: list,
    windows: list,
    initial_capital: float,
    morning_split: list,
):
    n_first = len(morning_split)
    split_pct = " / ".join(f"{s * 100:.0f}%" for s in morning_split)
    sep = "\u2501" * 96
    print(f"\n{sep}")
    print(
        f"  PER-WINDOW BREAKDOWN  (first group: {split_pct} of portfolio | sequential: inherits all returned capital)"
    )
    print(sep)
    print(
        f"  {'Window':<8} {'Start':<7} {'Bars':<5} {'Group':<12} {'Trades':>7}  {'W/L':<10} "
        f"{'WinRate':>8}  {'EV/trade':>9}  {'Cap P&L':>10}  {'Return%':>8}  {'≤10m':>5}  {'Short':>6}  {'Sh%':>5}  {'ShWR':>5}"
    )
    print(f"  {'─' * 102}")

    for i, win in enumerate(windows):
        label = win["label"]
        if i < n_first:
            group = f"first({morning_split[i] * 100:.0f}%)"
        else:
            group = "sequential"
        win_rows = [
            r for r in trade_rows if r["window"] == label and not r.get("skipped")
        ]
        if not win_rows:
            print(
                f"  {label:<8} {win['opening_start']:<7} {win['opening_bars']:<5} {group:<10} {'—':>7}"
            )
            continue
        stats = _stats_from_trades(win_rows)
        cap_stats = _capital_stats_from_trades(win_rows, initial_capital)
        ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
        cap_pnl_str = (
            f"+${cap_stats['total_cap_pnl']:.2f}"
            if cap_stats["total_cap_pnl"] >= 0
            else f"-${abs(cap_stats['total_cap_pnl']):.2f}"
        )
        ret_str = (
            f"+{cap_stats['total_return_pct']:.2f}%"
            if cap_stats["total_return_pct"] >= 0
            else f"{cap_stats['total_return_pct']:.2f}%"
        )
        wl = f"{stats['wins']}W/{stats['losses']}L"
        short_total = stats.get("short_total", 0)
        short_pct = short_total / stats["total"] * 100 if stats["total"] else 0.0
        short_wr = stats["short_wins"] / short_total * 100 if short_total else 0.0
        vshort_total = stats.get("vshort_total", 0)
        print(
            f"  {label:<8} {win['opening_start']:<7} {win['opening_bars']:<5} {group:<10} "
            f"{stats['total']:>7}  {wl:<10} {stats['win_rate'] * 100:>7.0f}%  "
            f"{ev_str:>9}  {cap_pnl_str:>10}  {ret_str:>8}"
            f"  {vshort_total:>5}  {short_total:>6}  {short_pct:>4.0f}%  {short_wr:>4.0f}%"
        )
    print(sep)


def _period_capital_groups(trade_rows: list, initial_capital: float, key_fn) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    groups = {}
    for row in active:
        key = key_fn(row["date"])
        if key not in groups:
            groups[key] = {"picks": 0, "wins": 0, "losses": 0, "cap_pnl": 0.0}
        groups[key]["picks"] += 1
        groups[key]["cap_pnl"] += row["cap_pnl"]
        if row["success"]:
            groups[key]["wins"] += 1
        else:
            groups[key]["losses"] += 1
    return groups


def _print_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 72
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(
        f"  {'Period':<12} {'Picks':>6}  {'W/L':<11} {'Cap P&L$':>10}  {'Return%':>8}  Portfolio"
    )
    print(f"  {'─' * 68}")

    portfolio = initial_capital
    total_picks = total_wins = total_losses = 0
    total_cap_pnl = 0.0

    for key in sorted(groups):
        g = groups[key]
        portfolio += g["cap_pnl"]
        total_picks += g["picks"]
        total_wins += g["wins"]
        total_losses += g["losses"]
        total_cap_pnl += g["cap_pnl"]

        wl = f"{g['wins']}W/{g['losses']}L"
        pnl_s = (
            f"+${g['cap_pnl']:.2f}"
            if g["cap_pnl"] >= 0
            else f"-${abs(g['cap_pnl']):.2f}"
        )
        ret = g["cap_pnl"] / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(
            f"  {key:<12} {g['picks']:>6}  {wl:<11} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}"
        )

    print(f"  {'─' * 68}")
    total_pnl_s = (
        f"+${total_cap_pnl:.2f}"
        if total_cap_pnl >= 0
        else f"-${abs(total_cap_pnl):.2f}"
    )
    total_ret = total_cap_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_picks:>6}  {total_wins}W/{total_losses}L{'':<7} "
        f"{total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_cap_pnl:,.2f}"
    )
    print(sep)


def _bnh_period_groups(daily_closes: pd.Series, initial_capital: float, key_fn) -> dict:
    if daily_closes.empty:
        return {}
    shares = initial_capital / daily_closes.iloc[0]
    groups = {}
    for d, close in daily_closes.items():
        key = key_fn(d)
        if key not in groups:
            groups[key] = {"last_close": close}
        groups[key]["last_close"] = close

    prev_value = initial_capital
    for key in sorted(groups):
        end_value = shares * groups[key]["last_close"]
        groups[key]["pnl"] = end_value - prev_value
        prev_value = end_value
    return groups


def _print_bnh_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 60
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(f"  {'Period':<12} {'P&L$':>10}  {'Return%':>8}  Portfolio")
    print(f"  {'─' * 54}")

    portfolio = initial_capital
    total_pnl = 0.0
    for key in sorted(groups):
        pnl = groups[key]["pnl"]
        portfolio += pnl
        total_pnl += pnl
        pnl_s = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ret = pnl / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(f"  {key:<12} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}")

    print(f"  {'─' * 54}")
    total_pnl_s = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    total_ret = total_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_pnl:,.2f}"
    )
    print(sep)


def _print_summary(
    trade_rows: list,
    baseline_df: pd.DataFrame,
    n: int,
    eval_start: date,
    eval_end: date,
    lookback_days: int,
    stop_pct: float,
    windows: list,
    initial_capital: float = INITIAL_CAPITAL,
    qqq_closes: pd.Series = None,
    weights: list = None,
    morning_split: list = None,
):
    sep = "\u2501" * 70
    print(f"\n{sep}")
    print(f"  SUMMARY — Selector Backtest")
    print(
        f"  {eval_start} → {eval_end}  |  top-{n}  |  {lookback_days}d rolling  |  stop-pct {stop_pct}"
    )
    print(sep)

    _print_stats_block(
        f"SELECTED  (top-{n} per window per day, scoring + EV gate)",
        _stats_from_trades(trade_rows),
    )

    if not baseline_df.empty:
        baseline_rows = [
            {
                "pnl": r["pnl"],
                "pnl_pct": r["pnl"] / r["entry_price"] * 100,
                "success": bool(r["success"]),
                "skipped": False,
            }
            for r in baseline_df.to_dict("records")
        ]
        _print_stats_block(
            "BASELINE  (all signals, no selection, first window only)",
            _stats_from_trades(baseline_rows),
        )

    if trade_rows:
        weights = weights or _parse_weights(None, n)
        wlabel = _weights_label(weights, initial_capital)
        _print_capital_stats_block(
            _capital_stats_from_trades(trade_rows, initial_capital), wlabel
        )

        if len(windows) > 1:
            _print_per_window_stats(
                trade_rows, windows, initial_capital, morning_split or [1.0]
            )

        def _week_key(d):
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"

        def _month_key(d):
            return f"{d.year}-{d.month:02d}"

        _print_period_table(
            f"WEEKLY BREAKDOWN  (${initial_capital:,.0f} initial | {wlabel})",
            _period_capital_groups(trade_rows, initial_capital, _week_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"WEEKLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _week_key),
                initial_capital,
            )

        _print_period_table(
            f"MONTHLY BREAKDOWN  (${initial_capital:,.0f} initial | {wlabel})",
            _period_capital_groups(trade_rows, initial_capital, _month_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"MONTHLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _month_key),
                initial_capital,
            )

    print(f"\n{sep}\n")


def _print_opportunity_pool_block(
    trade_rows: list, initial_pool: float, compound: bool
):
    opp_rows = [r for r in trade_rows if not r.get("skipped") and r.get("opp_cap_pnl") is not None]
    if not opp_rows:
        return
    opp_total = len(opp_rows)
    opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
    opp_losses = opp_total - opp_wins
    win_rate = opp_wins / opp_total * 100
    opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)
    final_balance = initial_pool + opp_net_cap_pnl
    pool_return_pct = opp_net_cap_pnl / initial_pool * 100 if initial_pool else 0.0

    net_str = f"+${opp_net_cap_pnl:.2f}" if opp_net_cap_pnl >= 0 else f"-${abs(opp_net_cap_pnl):.2f}"
    ret_str = f"+{pool_return_pct:.2f}%" if pool_return_pct >= 0 else f"{pool_return_pct:.2f}%"
    compound_note = "compounded" if compound else "resets daily"

    sep = "━" * 60
    print(f"\n{sep}")
    print(f"  OPPORTUNITY POOL  (${initial_pool:,.0f} initial | {compound_note})")
    print(f"  {'─' * 56}")
    print(f"  Deployments         : {opp_total}  ({opp_wins}W / {opp_losses}L)")
    print(f"  Win rate            : {win_rate:.0f}%")
    print(f"  Net cap P&L         : {net_str}")
    print(f"  Net pool return (%) : {ret_str}")
    if compound:
        final_str = f"${final_balance:,.2f}"
        print(f"  Final pool balance  : {final_str}")
    print(sep)


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Backtest the op_momentum selector algorithm"
    )
    parser.add_argument(
        "--start", type=str, required=True, help="Eval start date YYYY-MM-DD"
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Eval end date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--top", type=int, default=3, help="Top-N picks per day (default: 3)"
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None, help="Override default ticker list"
    )
    parser.add_argument(
        "--ticker-set",
        choices=["V3", "AT"],
        default=None,
        help="Named ticker set: V3 (default pool) or AT (ACTIVELY_TRADE_TICKERS)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=ROLLING_LOOKBACK_DAYS,
        help=f"Rolling lookback in calendar days (default: {ROLLING_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=STOP_PCT,
        help=f"Hard stop as fraction of OR range (default: {STOP_PCT})",
    )
    parser.add_argument(
        "--source",
        choices=["alpaca", "yfinance"],
        default="alpaca",
        help="Market data source (default: alpaca)",
    )
    parser.add_argument(
        "--feed",
        choices=["iex", "sip"],
        default="sip",
        help="Alpaca data feed: 'sip' (consolidated, default) or 'iex' (free tier)",
    )
    parser.add_argument(
        "--bearish-ma200",
        action="store_true",
        default=False,
        help="Require price < MA200 for bearish signal",
    )
    parser.add_argument(
        "--ma-momentum-gate",
        action="store_true",
        default=False,
        dest="ma_momentum_gate",
        help=(
            "Gate signals on MA alignment. "
            "BULLISH: OR range must overlap or be above both 5-min MA20 and MA50, "
            "and the last OR bar must close above MA20 or MA50. "
            "BEARISH (mirror): OR range must overlap or be below both MAs, "
            "and the last OR bar must close below MA20."
        ),
    )
    parser.add_argument(
        "--ma-momentum-gate-in-scoring",
        action="store_true",
        default=False,
        dest="ma_momentum_gate_in_scoring",
        help=(
            "Apply the MA momentum gate at the selector scoring step (score=0 if gate fails), "
            "rather than filtering signals out of the backtest pool. "
            "Tickers that fail the gate are skipped by the top-N ranker but their signals "
            "remain visible in all_window_results. Same alignment rules as --ma-momentum-gate."
        ),
    )
    parser.add_argument(
        "--opening-bars",
        type=int,
        default=OPENING_BARS,
        help=f"Number of 5-min bars in opening period (default: {OPENING_BARS}). "
        "Used only when --window is not specified.",
    )
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET (default: {OPENING_START_TIME}). "
        "Used only when --window is not specified.",
    )
    parser.add_argument(
        "--window",
        action="append",
        nargs="+",
        metavar="PARAM",
        default=None,
        help="Define a trading window: LABEL START BARS [CLOSE_TOP_PCT] (e.g. M1 09:30 3 or A1 13:15 1 0.05). "
        "CLOSE_TOP_PCT is optional: if provided, BULLISH only when close >= OR_high - PCT*OR_range, "
        "BEARISH only when close <= OR_low + PCT*OR_range (overrides --close-top-pct for this window). "
        "Repeat to add multiple windows. When specified, overrides --opening-start/--opening-bars.",
    )
    parser.add_argument(
        "--window-ma-switch",
        action="append",
        nargs="+",
        metavar="PARAM",
        default=None,
        dest="window_ma_switch",
        help="Per-window trailing MA switch override: LABEL MODE [PERIOD] "
        "(e.g. --window-ma-switch A1 after-arm 8). "
        "MODE is one of: none, after-arm, after-target. "
        "PERIOD defaults to --trailing-ma-switch-period if omitted. "
        "Repeat to configure multiple windows.",
    )
    parser.add_argument(
        "--morning-split",
        nargs="+",
        type=float,
        default=None,
        help="Per-window split for the first (simultaneous) group as percentages, e.g. --morning-split 60 40. "
        "Must sum to ≤ 100. The number of values determines how many leading windows are simultaneous. "
        "Remaining windows run sequentially, each inheriting all returned capital. "
        "Default: single window gets 100%% of portfolio.",
    )
    parser.add_argument(
        "--min-window-capital",
        type=float,
        default=MIN_WINDOW_CAPITAL,
        help=f"Minimum capital required to execute a window (default: ${MIN_WINDOW_CAPITAL:.0f}). "
        "Windows with less available capital are skipped.",
    )
    parser.add_argument(
        "--show-execution-log",
        action="store_true",
        default=False,
        help="Print the window execution log showing which windows ran or were skipped each day. Default: off.",
    )
    parser.add_argument(
        "--csv-out",
        type=str,
        default=None,
        dest="csv_out",
        help="Write all non-skipped trade rows to a CSV file at this path.",
    )
    parser.add_argument(
        "--compound",
        action="store_true",
        default=False,
        help="Compound capital across days (portfolio carries over). "
        "Default: reset to initial capital each day for clean per-day strategy evaluation.",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        default=False,
        help="Skip a ticker in later windows if already picked by an earlier window that day.",
    )
    parser.add_argument(
        "--trailing-ma",
        choices=["ma20", "ma50", "both"],
        default="ma20",
        help="Trailing MA stop to use once MA is above hard stop (default: ma20).",
    )
    parser.add_argument(
        "--trailing-ma-switch",
        choices=["none", "after-arm", "after-target"],
        default="none",
        dest="trailing_ma_switch",
        help="Upgrade trailing stop to a faster MA once a profit threshold is reached. "
        "after-arm: upgrade when price moves 1x OR range past entry. "
        "after-target: upgrade at factor x OR range (see --trailing-ma-switch-factor). "
        "Default: none.",
    )
    parser.add_argument(
        "--trailing-ma-switch-period",
        type=int,
        default=8,
        dest="trailing_ma_switch_period",
        help="Period of the fast MA used after the switch threshold is hit (default: 8). "
        "Common choices: 5, 8, 10. Only applies when --trailing-ma-switch is not none.",
    )
    parser.add_argument(
        "--trailing-ma-switch-factor",
        type=float,
        default=1.0,
        dest="trailing_ma_switch_factor",
        help="OR-range multiplier for --trailing-ma-switch after-target (default: 1.0).",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=None,
        help="Per-trade max loss as a fraction of entry price (e.g. 0.02 = 2%%). Default: disabled.",
    )
    parser.add_argument(
        "--min-hold-bars",
        type=int,
        default=0,
        dest="min_hold_bars",
        help="Minimum bars to hold before fallback/hard-stop exits can fire (e.g. 3 = 15 min). "
        "max-loss-pct still exits immediately. Default: 0 (disabled).",
    )
    parser.add_argument(
        "--oracle-picks",
        action="store_true",
        default=False,
        dest="oracle_picks",
        help="Replace scoring with perfect-hindsight selection: pick top-N by actual realized P&L each day. "
        "No EV gate — includes all tickers with a valid signal. Shows theoretical maximum return.",
    )
    parser.add_argument(
        "--random-picks",
        action="store_true",
        default=False,
        dest="random_picks",
        help="Replace scoring with random selection from EV-positive tickers. "
        "Use as a baseline to measure how much the scoring formula contributes.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        dest="random_seed",
        help="Seed for --random-picks to make runs reproducible. Default: None (different each run).",
    )
    parser.add_argument(
        "--dynamic-ev-gate",
        action="store_true",
        default=True,
        dest="dynamic_ev_gate",
        help="Apply regime-adaptive EV filter based on daily pool vote (default: on). "
        "Mode 'percentile' (default): exclude bottom N%% of pool by EV, adapts with market. "
        "Mode 'threshold': fixed WR/W/L floors per regime tier.",
    )
    parser.add_argument(
        "--no-dynamic-ev-gate",
        action="store_false",
        dest="dynamic_ev_gate",
        help="Disable the regime-adaptive EV filter (reverts to baseline behavior).",
    )
    parser.add_argument(
        "--dg-mode",
        type=str,
        default="percentile",
        choices=["percentile", "threshold"],
        dest="dg_mode",
        help="Gate mode for --dynamic-ev-gate. 'percentile': pool-relative EV floor (recommended). "
        "'threshold': fixed absolute WR/W/L floors. Default: percentile.",
    )
    parser.add_argument("--dg-bull-threshold", type=int, default=10, dest="dg_bull_threshold",
                        help="Pool vote count at or above which bull-regime thresholds apply. Default: 10.")
    parser.add_argument("--dg-bear-threshold", type=int, default=5, dest="dg_bear_threshold",
                        help="Pool vote count at or below which bear-regime thresholds apply. Default: 5.")
    parser.add_argument("--dg-bull-exclude-pct", type=float, default=0.10, dest="dg_bull_exclude_pct",
                        help="[percentile mode] Fraction of pool to exclude from bottom in bull regime. Default: 0.10.")
    parser.add_argument("--dg-neutral-exclude-pct", type=float, default=0.25, dest="dg_neutral_exclude_pct",
                        help="[percentile mode] Fraction of pool to exclude from bottom in neutral regime. Default: 0.25.")
    parser.add_argument("--dg-bear-exclude-pct", type=float, default=0.40, dest="dg_bear_exclude_pct",
                        help="[percentile mode] Fraction of pool to exclude from bottom in bear regime. Default: 0.40.")
    parser.add_argument("--dg-bull-min-wr", type=float, default=0.30, dest="dg_bull_min_wr",
                        help="[threshold mode] Minimum win rate in bull regime. Default: 0.30.")
    parser.add_argument("--dg-neutral-min-wr", type=float, default=0.33, dest="dg_neutral_min_wr",
                        help="[threshold mode] Minimum win rate in neutral regime. Default: 0.33.")
    parser.add_argument("--dg-bear-min-wr", type=float, default=0.38, dest="dg_bear_min_wr",
                        help="[threshold mode] Minimum win rate in bear regime. Default: 0.38.")
    parser.add_argument("--dg-bull-min-wl", type=float, default=1.3, dest="dg_bull_min_wl",
                        help="[threshold mode] Minimum W/L ratio in bull regime. Default: 1.3.")
    parser.add_argument("--dg-neutral-min-wl", type=float, default=1.5, dest="dg_neutral_min_wl",
                        help="[threshold mode] Minimum W/L ratio in neutral regime. Default: 1.5.")
    parser.add_argument("--dg-bear-min-wl", type=float, default=1.8, dest="dg_bear_min_wl",
                        help="[threshold mode] Minimum W/L ratio in bear regime. Default: 1.8.")
    parser.add_argument(
        "--adaptive-lookback",
        action="store_true",
        default=True,
        dest="adaptive_lookback",
        help="Shorten lookback window in bull regimes (more responsive) and lengthen in bear regimes "
        "(require more evidence). Uses same pool-vote signal as --dynamic-ev-gate (default: on).",
    )
    parser.add_argument(
        "--no-adaptive-lookback",
        action="store_false",
        dest="adaptive_lookback",
        help="Disable adaptive lookback (uses fixed --lookback window for all regimes).",
    )
    parser.add_argument("--al-bull-threshold", type=int, default=10, dest="al_bull_threshold",
                        help="Pool vote count for bull regime in adaptive lookback. Default: 10.")
    parser.add_argument("--al-bear-threshold", type=int, default=5, dest="al_bear_threshold",
                        help="Pool vote count for bear regime in adaptive lookback. Default: 5.")
    parser.add_argument("--al-bull-days", type=int, default=20, dest="al_bull_days",
                        help="Lookback days in bull regime. Default: 20.")
    parser.add_argument("--al-neutral-days", type=int, default=60, dest="al_neutral_days",
                        help="Lookback days in neutral regime. Default: 60.")
    parser.add_argument("--al-bear-days", type=int, default=90, dest="al_bear_days",
                        help="Lookback days in bear regime. Default: 90.")
    parser.add_argument(
        "--stale-cut-mins",
        type=int,
        default=0,
        dest="stale_cut_mins",
        help="Exit flat trades at this many minutes after entry if |P&L| < --stale-cut-threshold. "
        "E.g. 30 means check at the 30-min bar. Default: 0 (disabled).",
    )
    parser.add_argument(
        "--stale-cut-threshold",
        type=float,
        default=0.0,
        dest="stale_cut_threshold",
        help="P&L threshold (as %% of entry) for stale-cut. Trade is cut if |P&L| < threshold "
        "at --stale-cut-mins. E.g. 0.25 means exit if within ±0.25%% of entry. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=False,
        help="Once hard stop is armed, use MA20 as the trailing exit. Default: off.",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        default=False,
        help="Skip BULLISH signals on days when QQQ close is below its N-day MA. Default: off.",
    )
    parser.add_argument(
        "--regime-ma",
        type=int,
        default=5,
        help="N-day MA period for QQQ regime filter (default: 5).",
    )
    parser.add_argument(
        "--qqq-align-filter",
        action="store_true",
        default=False,
        dest="qqq_align_filter",
        help="Skip entries where QQQ's OR close position contradicts the signal direction. "
        "BULLISH skipped when QQQ OR_cpos <= threshold; BEARISH skipped when QQQ OR_cpos > threshold. "
        "Uses same OR window as the individual stock — no lookahead bias. Default: off.",
    )
    parser.add_argument(
        "--qqq-align-threshold",
        type=float,
        default=0.50,
        dest="qqq_align_threshold",
        help="QQQ OR close position threshold for alignment filter (default: 0.50). "
        "BULL skipped if QQQ OR_cpos <= this value; BEAR skipped if QQQ OR_cpos > this value.",
    )
    parser.add_argument(
        "--qqq-extend-days",
        type=int,
        default=0,
        dest="qqq_extend_days",
        help="Gate the QQQ align filter to only fire when QQQ has risen too much too fast. "
        "N = rolling window of prior trading-day closes (e.g. 5). "
        "0 = disabled (filter fires on all days). Requires --qqq-align-filter.",
    )
    parser.add_argument(
        "--qqq-extend-pct",
        type=float,
        default=0.05,
        dest="qqq_extend_pct",
        help="Cumulative return threshold for the overextension gate (default: 0.05 = 5%%). "
        "Filter only activates if QQQ's N-day prior return exceeds this value.",
    )
    parser.add_argument(
        "--qqq-extend-max-dd",
        type=float,
        default=0.0,
        dest="qqq_extend_max_dd",
        help="Max single-day drawdown allowed in the N-day window (default: 0.0 = disabled). "
        "If any day in the window closed down more than this fraction, the date is not "
        "considered overextended (there was consolidation). E.g. 0.01 = 1%% pullback allowed.",
    )
    parser.add_argument(
        "--weights",
        nargs="+",
        type=int,
        default=None,
        help="Position weights per rank (e.g. --weights 50 30 20). Must match --top count.",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=INITIAL_CAPITAL,
        help=f"Initial portfolio capital in dollars (default: {INITIAL_CAPITAL:,.0f}).",
    )
    parser.add_argument(
        "--reversal",
        action="store_true",
        default=False,
        help="Enable reversal trade: if BEARISH primary stops out within N bars and "
        "price later crosses above OR high, enter a BULLISH reversal with OR-midpoint "
        "hard stop. Default: off.",
    )
    parser.add_argument(
        "--reversal-max-bars",
        type=int,
        default=3,
        dest="reversal_max_bars",
        help="Max bars_held threshold for reversal eligibility (default: 3 = within 4 bars).",
    )
    parser.add_argument(
        "--bearish-reversal",
        action="store_true",
        default=False,
        dest="bearish_reversal",
        help="Enable bearish reversal trade: if BULLISH primary stops out within N bars and "
        "price later crosses below OR low, enter a BEARISH reversal with OR-midpoint "
        "hard stop. Default: off.",
    )
    parser.add_argument(
        "--bearish-reversal-max-bars",
        type=int,
        default=3,
        dest="bearish_reversal_max_bars",
        help="Max bars_held threshold for bearish reversal eligibility (default: 3).",
    )
    parser.add_argument(
        "--min-first-bar-range",
        type=float,
        default=None,
        dest="min_first_bar_range_pct",
        help="Rule 1: skip entry if the first 5-min bar of the opening window has a "
        "high-low range smaller than this fraction of the bar midpoint "
        "(e.g. 0.015 = 1.5%%). M1 only. Default: disabled.",
    )
    parser.add_argument(
        "--min-first-bar-volume",
        type=float,
        default=None,
        dest="min_first_bar_volume_mult",
        help="Rule 4: skip M1 entry if the 09:30 bar volume < mult × (20d avg daily vol / 78). "
        "E.g. 1.5 means opening bar must be 1.5× the expected per-bar volume. Default: disabled.",
    )
    parser.add_argument(
        "--min-or-vol-ratio",
        type=float,
        default=None,
        dest="min_or_vol_ratio",
        help="Skip entry if OR-window mean volume / 20d historical OR-window mean volume < threshold. "
        "Default: disabled.",
    )
    parser.add_argument(
        "--score-entry-weight",
        type=float,
        default=0.50,
        dest="score_entry_weight",
        help="Scoring weight for entry_vs_mid_pct (default: 0.50). Must satisfy: entry + vol_ratio + 0.30 + or_range <= 1.0.",
    )
    parser.add_argument(
        "--score-vol-ratio-weight",
        type=float,
        default=0.00,
        dest="score_vol_ratio_weight",
        help="Scoring weight for or_vol_ratio (default: 0.00). Remainder after entry + vol_ratio + avg_win goes to or_range_pct.",
    )
    parser.add_argument(
        "--score-avg-win-weight",
        type=float,
        default=0.30,
        dest="score_avg_win_weight",
        help="Scoring weight for avg_win_pct (default: 0.30). Remainder after entry + vol_ratio + avg_win + ev_trend goes to or_range_pct.",
    )
    parser.add_argument(
        "--score-ev-trend-weight",
        type=float,
        default=0.00,
        dest="score_ev_trend_weight",
        help="Scoring weight for ev_trend (recent EV − full-window EV). Positive = rewards accelerating tickers. Default: 0.00.",
    )
    parser.add_argument(
        "--ev-trend-days",
        type=int,
        default=15,
        dest="ev_trend_days",
        help="Calendar days for the recent EV window in ev_trend computation (default: 15).",
    )
    parser.add_argument(
        "--score-dist-52w-low-weight",
        type=float,
        default=0.00,
        dest="score_dist_52w_low_weight",
        help="Scoring weight for 52-week low proximity. Higher weight rewards tickers closer to their 52w low. Default: 0.00.",
    )
    parser.add_argument(
        "--score-dist-52w-high-weight",
        type=float,
        default=0.00,
        dest="score_dist_52w_high_weight",
        help="Scoring weight for 52-week high proximity (George & Hwang 2004). Rewards tickers near their 52w high for both BULLISH and BEARISH signals. Default: 0.00.",
    )
    parser.add_argument(
        "--score-streak-weight",
        type=float,
        default=0.00,
        dest="score_streak_weight",
        help="Scoring weight for consecutive-day streak penalty. Penalizes tickers with long up/down streaks (overextension). Default: 0.00.",
    )
    parser.add_argument(
        "--score-prev-day-vol-weight",
        type=float,
        default=0.00,
        dest="score_prev_day_vol_weight",
        help="Scoring weight for prior-day volume ratio (vol vs 20d avg). Rewards above-average volume activity. Default: 0.00.",
    )
    parser.add_argument(
        "--score-ma200-dist-weight",
        type=float,
        default=0.00,
        dest="score_ma200_dist_weight",
        help="Scoring weight for daily MA200 distance penalty. Penalizes tickers overextended above their 200-day MA. Default: 0.00.",
    )
    parser.add_argument(
        "--score-ma50-dist-weight",
        type=float,
        default=0.00,
        dest="score_ma50_dist_weight",
        help="Direction-aware scoring weight for daily MA50 distance. Rewards above-MA50 for BULLISH signals, below-MA50 for BEARISH signals. Default: 0.00.",
    )
    parser.add_argument(
        "--regime-scoring",
        action="store_true",
        default=False,
        dest="regime_scoring",
        help="Enable regime-adaptive scoring. Applies different weight profiles on bull vs bear days "
        "(classified by prior-day QQQ close vs 50d MA). Use --bull-* and --bear-* flags to set profiles.",
    )
    # Bull regime weight overrides (QQQ prior-close > 50d MA)
    # Research defaults: add ma50 momentum signal in confirmed uptrends
    parser.add_argument("--bull-score-entry-weight",    type=float, default=None, dest="regime_bull_entry_weight",
                        help="Entry weight in bull regime. Default: 0.70 (when --regime-scoring active).")
    parser.add_argument("--bull-score-vol-ratio-weight", type=float, default=None, dest="regime_bull_vol_ratio_weight",
                        help="Vol ratio weight in bull regime. Default: 0.15.")
    parser.add_argument("--bull-score-avg-win-weight",  type=float, default=None, dest="regime_bull_avg_win_weight",
                        help="Avg-win weight in bull regime. Default: 0.00.")
    parser.add_argument("--bull-score-ma50-dist-weight", type=float, default=None, dest="regime_bull_ma50_dist_weight",
                        help="MA50 distance weight in bull regime. Default: 0.10 (reward momentum leaders).")
    # Bear regime weight overrides (QQQ prior-close <= 50d MA)
    # Research defaults: fall back to E1 (best for bear/choppy years)
    parser.add_argument("--bear-score-entry-weight",    type=float, default=None, dest="regime_bear_entry_weight",
                        help="Entry weight in bear regime. Default: 0.80 (E1 baseline).")
    parser.add_argument("--bear-score-vol-ratio-weight", type=float, default=None, dest="regime_bear_vol_ratio_weight",
                        help="Vol ratio weight in bear regime. Default: 0.15.")
    parser.add_argument("--bear-score-avg-win-weight",  type=float, default=None, dest="regime_bear_avg_win_weight",
                        help="Avg-win weight in bear regime. Default: 0.00.")
    parser.add_argument("--bear-score-ma50-dist-weight", type=float, default=None, dest="regime_bear_ma50_dist_weight",
                        help="MA50 distance weight in bear regime. Default: 0.00 (ignore MA50 in bear).")
    parser.add_argument(
        "--direction-split-ev",
        action="store_true",
        default=True,
        dest="direction_split_ev_gate",
        help="Apply EV gate per signal direction (BULLISH/BEARISH separately). "
        "Excludes tickers with negative directional EV even if combined EV is positive. Default: on.",
    )
    parser.add_argument(
        "--no-direction-split-ev",
        action="store_false",
        dest="direction_split_ev_gate",
        help="Disable direction-split EV gate (uses combined EV for both directions).",
    )
    parser.add_argument("--ds-bull-min-ev", type=float, default=0.0, dest="ds_bull_min_ev",
                        help="Min directional EV required in bull regime (pool_vote >= bull_threshold). Default: 0.0.")
    parser.add_argument("--ds-neutral-min-ev", type=float, default=0.0, dest="ds_neutral_min_ev",
                        help="Min directional EV required in neutral regime. Default: 0.0.")
    parser.add_argument("--ds-bear-min-ev", type=float, default=0.0, dest="ds_bear_min_ev",
                        help="Min directional EV required in bear regime (pool_vote <= bear_threshold). Default: 0.0.")
    parser.add_argument(
        "--qqq-or-weight",
        type=float,
        default=0.30,
        dest="qqq_or_weight",
        help="Scoring weight for QQQ opening-range alignment (9:30-9:45). "
             "Positive values boost tickers whose signal direction matches QQQ OR; penalise opposing. "
             "Default: 0.30 (confirmed optimal across 2019-2026).",
    )
    parser.add_argument("--score-trend-align-weight", type=float, default=0.0,
                        dest="score_trend_align_weight",
                        help="Weight for direction-aware consecutive-streak scoring. Positive = reward "
                             "signals aligned with prior price momentum; penalizes counter-trend picks. "
                             "Normalized to [-1,+1] via streak/5. Default: 0.0.")
    parser.add_argument("--score-win-rate-weight", type=float, default=0.0,
                        dest="score_win_rate_weight",
                        help="Scoring weight for rolling win rate. Higher values favour consistent "
                             "tickers over lottery-style high-EV picks. Default: 0.0.")
    parser.add_argument("--entry-weight-bull", type=float, default=None,
                        dest="entry_weight_bull",
                        help="entry_vs_mid_pct weight in bull regime (pool_vote >= bull_threshold). "
                             "Default: same as --score-entry-weight.")
    parser.add_argument("--entry-weight-bear", type=float, default=None,
                        dest="entry_weight_bear",
                        help="entry_vs_mid_pct weight in bear regime (pool_vote <= bear_threshold). "
                             "Reduce to de-prioritise aggressive breakouts in choppy markets. "
                             "Default: same as --score-entry-weight.")
    parser.add_argument("--normalize-or-by-adr", action="store_true", default=False,
                        dest="normalize_or_by_adr",
                        help="Normalize or_range_pct by each ticker's rolling ADR before scoring. "
                             "Makes OR magnitude comparable across different-volatility stocks. Default: off.")
    parser.add_argument("--adr-days", type=int, default=20,
                        dest="adr_days",
                        help="Lookback days for rolling ADR computation used in --normalize-or-by-adr. Default: 20.")
    parser.add_argument("--min-pool-vote", type=int, default=0,
                        dest="min_pool_vote_to_trade",
                        help="Skip trading on days where fewer than N tickers have positive rolling EV. "
                             "0 = disabled (always trade). Default: 0.")
    parser.add_argument("--direction-regime-filter", action="store_true", default=False,
                        dest="direction_regime_filter",
                        help="In bull regime (pool_vote >= drf-bull-thresh), skip BEARISH picks. "
                             "In bear regime (pool_vote <= drf-bear-thresh), skip BULLISH picks. Default: off.")
    parser.add_argument("--drf-bull-thresh", type=int, default=10, dest="drf_bull_only_thresh",
                        help="Pool vote >= this → only BULLISH picks allowed. Default: 10.")
    parser.add_argument("--drf-bear-thresh", type=int, default=5, dest="drf_bear_only_thresh",
                        help="Pool vote <= this → only BEARISH picks allowed. Default: 5.")
    parser.add_argument(
        "--ev-shrink-k",
        type=float,
        default=0.0,
        dest="ev_shrink_k",
        help="Bayesian EV shrinkage factor k. Shrinks each ticker ev_trade toward pool mean: ev_s = (n*ev + k*pool_mean)/(n+k). 0=disabled. Try 5-10. Default: 0.0.",
    )
    parser.add_argument(
        "--score-frog-weight",
        type=float,
        default=0.0,
        dest="score_frog_weight",
        help="Frog-in-the-Pan path smoothness weight. Rewards tickers with consistent directional daily moves. Direction-aware. Default: 0.0.",
    )
    parser.add_argument(
        "--frog-days",
        type=int,
        default=60,
        dest="frog_days",
        help="Lookback days for Frog-in-the-Pan smoothness score. Default: 60.",
    )
    parser.add_argument(
        "--score-dir-ev-weight",
        type=float,
        default=0.0,
        dest="score_dir_ev_weight",
        help=(
            "Direction-specific historical EV weight. Uses ev_trade_bullish for BULLISH signals "
            "and ev_trade_bearish for BEARISH signals. Rewards tickers that historically perform "
            "well specifically in the direction being scored, not just overall. "
            "Typical range 0.05-0.20. Default: 0.0."
        ),
    )
    parser.add_argument(
        "--score-rel-strength-weight",
        type=float,
        default=0.0,
        dest="score_rel_strength_weight",
        help=(
            "Cross-sectional relative MA50 strength weight. Scores each ticker's MA50 distance "
            "relative to the pool mean that day. Positive = outperforming pool. "
            "Direction-aware: rewards BULLISH for outperforming, BEARISH for underperforming. "
            "Most effective in bear/choppy years where pool spread is wide. Default: 0.0."
        ),
    )
    parser.add_argument(
        "--min-or-range",
        type=float,
        default=0.0,
        dest="min_or_range",
        help="Skip ticker if OR range %% < threshold. Filters low-range tickers with tight stops. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--min-or-range-windows",
        nargs="+",
        default=None,
        dest="min_or_range_windows",
        metavar="LABEL",
        help="Only apply --min-or-range to these window labels (e.g. --min-or-range-windows M1 M2). Default: apply to all windows.",
    )
    parser.add_argument(
        "--min-ma200-distance",
        type=float,
        default=0.0,
        dest="min_ma200_distance",
        help="Skip ticker if (entry - MA200) / MA200 %% < threshold. Filters entries too close to or below the 200-period MA. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--min-ma200-distance-windows",
        nargs="+",
        default=None,
        dest="min_ma200_distance_windows",
        metavar="LABEL",
        help="Only apply --min-ma200-distance to these window labels (e.g. --min-ma200-distance-windows A1 A2). Default: apply to all windows.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        dest="min_score",
        help="Skip ticker if score < threshold. Filters low-conviction picks. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.0,
        dest="min_ev",
        help="Skip ticker if rolling EV %% < threshold. Raises the EV gate above 0. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--or-bar-lookback",
        type=int,
        default=3,
        dest="or_bar_lookback",
        help="If OR range < 1/4 of avg High-Low of last N bars before the window, use that avg as the effective OR range for scoring. Default: 3.",
    )
    parser.add_argument(
        "--close-top-pct",
        type=float,
        default=None,
        dest="close_top_pct",
        help=(
            "Tighter signal filter: BULLISH only if close >= OR_high - PCT * OR_range; "
            "BEARISH only if close <= OR_low + PCT * OR_range. "
            "Hard stop set to OR_low (bull) or OR_high (bear), pre-armed from bar 0. "
            "Example: --close-top-pct 0.05 requires close in top/bottom 5%% of the bar. "
            "Default: off (uses standard midpoint/bottom-30 conditions)."
        ),
    )
    parser.add_argument(
        "--bearish-reentry",
        action="store_true",
        default=False,
        dest="bearish_reentry",
        help="Enable bearish re-entry: if BEARISH primary stops out within N bars and "
        "price later closes below OR_low, re-enter short with midpoint as hard stop. "
        "Only fires when reversal did not fire. Default: off.",
    )
    parser.add_argument(
        "--bearish-reentry-max-bars",
        type=int,
        default=3,
        dest="bearish_reentry_max_bars",
        help="Max bars_held for the primary BEARISH trade to be eligible for re-entry (default: 3).",
    )
    parser.add_argument(
        "--bullish-reentry",
        action="store_true",
        default=False,
        dest="bullish_reentry",
        help="Enable bullish re-entry: if BULLISH primary stops out within N bars and "
        "price later closes above OR_high, re-enter long with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--bullish-reentry-max-bars",
        type=int,
        default=5,
        dest="bullish_reentry_max_bars",
        help="Max bars_held for the primary BULLISH trade to be eligible for re-entry (default: 3).",
    )
    parser.add_argument(
        "--only-dates",
        type=str,
        default=None,
        dest="only_dates",
        help="Path to a file with YYYY-MM-DD dates (one per line). Only those trading days "
             "are evaluated; all others are skipped. Use with --start/--end spanning the full range.",
    )
    parser.add_argument(
        "--regime-adaptive",
        action="store_true",
        default=False,
        dest="regime_adaptive",
        help=(
            "Select M1 window bars and stop_pct per day based on prior VIX close and QQQ "
            "5-min MA alignment score at the 9:40 bar. Uses cross-year validated config table "
            "(see REGIME_ADAPTIVE_CONFIGS). The bars value in --window M1 is used as a fallback "
            "when VIX/QQQ data is unavailable. Incompatible with --doubledown."
        ),
    )
    parser.add_argument(
        "--doubledown",
        action="store_true",
        default=False,
        help=(
            "Enable double-down: if rank-2+ positions stop out within the doubledown window "
            "of OR close, deploy their returned capital into the highest-ranked survivor as a "
            "single add-on leg. Add-on entry = close of the doubledown bar; hard stop = "
            "entry ± 80% × bar range. Default: off."
        ),
    )
    parser.add_argument(
        "--doubledown-start",
        type=int,
        default=DOUBLEDOWN_START_MIN,
        dest="doubledown_start_min",
        help=(
            f"Minutes from OR close at which the DD check fires and the add-on leg enters. "
            f"Stopouts that occurred before this mark are eligible to free capital. "
            f"Must be a multiple of 5. Default: {DOUBLEDOWN_START_MIN}."
        ),
    )
    parser.add_argument(
        "--opportunity-capital",
        type=float,
        default=0.0,
        dest="opportunity_capital_pct",
        help=(
            "Size of the opportunity pool as a percentage of initial capital "
            "(e.g. 50 = 50%%). Pool deploys on DD signals independently of "
            "window capital and recycles sequentially within the day. "
            "Requires --doubledown. Default: 0 (disabled)."
        ),
    )
    parser.add_argument(
        "--no-exit-at-bar-close",
        dest="exit_at_bar_close",
        action="store_false",
        default=True,
        help="Exit at the intrabar stop/fallback price instead of bar close. "
        "Default: exit at bar close (matches live engine behaviour).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    _TICKER_SETS = {"V3": DEFAULT_TICKERS, "AT": ACTIVELY_TRADE_TICKERS}
    tickers = args.tickers or _TICKER_SETS.get(args.ticker_set, DEFAULT_TICKERS)
    eval_start = date.fromisoformat(args.start)
    eval_end = date.fromisoformat(args.end) if args.end else date.today()

    weights = _parse_weights(args.weights, args.top)

    if args.window:
        windows = []
        for w in args.window:
            if len(w) < 3:
                parser.error(
                    f"--window requires LABEL START BARS [CLOSE_TOP_PCT], got: {w}"
                )
            win = {"label": w[0], "opening_start": w[1], "opening_bars": int(w[2])}
            if len(w) > 3:
                win["close_top_pct"] = float(w[3])
            windows.append(win)
    else:
        windows = None

    resolved_windows = _normalize_windows(
        windows, args.opening_start, args.opening_bars
    )

    # Apply per-window MA switch overrides
    if args.window_ma_switch:
        _valid_modes = {"none", "after-arm", "after-target"}
        _win_by_label = {w["label"]: w for w in resolved_windows}
        for entry in args.window_ma_switch:
            if len(entry) < 2:
                parser.error(f"--window-ma-switch requires LABEL MODE [PERIOD], got: {entry}")
            wlabel, mode = entry[0], entry[1]
            if mode not in _valid_modes:
                parser.error(f"--window-ma-switch mode must be one of {_valid_modes}, got: {mode}")
            if wlabel not in _win_by_label:
                parser.error(f"--window-ma-switch label '{wlabel}' not found in defined windows")
            _win_by_label[wlabel]["trailing_ma_switch"] = mode
            if len(entry) > 2:
                _win_by_label[wlabel]["trailing_ma_switch_period"] = int(entry[2])
    n_windows = len(resolved_windows)

    # Parse --morning-split: convert percentages to fractions, validate
    if args.morning_split:
        raw_split = args.morning_split
        total_pct = sum(raw_split)
        if total_pct > 100.0 + 1e-6:
            raise SystemExit(
                f"--morning-split values sum to {total_pct:.1f}% which exceeds 100%."
            )
        if len(raw_split) > n_windows:
            raise SystemExit(
                f"--morning-split has {len(raw_split)} values but only {n_windows} window(s) defined."
            )
        morning_split = [v / 100.0 for v in raw_split]
    else:
        morning_split = [1.0] if n_windows == 1 else None

    n_first = len(morning_split) if morning_split else 1

    print(f"\nSelector Backtest")
    print(f"  Eval window  : {eval_start} → {eval_end}")
    print(f"  Top-N        : {args.top}")
    print(f"  Weights      : {_weights_label(weights, args.capital)}")
    print(f"  Tickers      : {', '.join(tickers)}")
    print(f"  Lookback     : {args.lookback}d rolling")
    print(f"  Windows      : {n_windows} total")
    for i, w in enumerate(resolved_windows):
        if morning_split and i < len(morning_split):
            group_desc = f"simultaneous, {morning_split[i] * 100:.0f}% of portfolio"
            cap_approx = args.capital * morning_split[i]
        else:
            group_desc = "sequential, inherits all returned capital"
            cap_approx = None
        cap_str = f"  (~${cap_approx:,.0f})" if cap_approx is not None else ""
        ctp = w.get("close_top_pct")
        ctp_str = f", top/bottom {ctp * 100:.0f}%" if ctp is not None else ""
        w_switch = w.get("trailing_ma_switch")
        w_period = w.get("trailing_ma_switch_period", args.trailing_ma_switch_period)
        ma_switch_str = f", ma-switch={w_switch}/ma{w_period}" if w_switch and w_switch != "none" else ""
        print(
            f"    [{w['label']}] {w['opening_start']} / {w['opening_bars']} bars{ctp_str}{ma_switch_str}  ({group_desc}){cap_str}"
        )
    print(f"  Min capital  : ${args.min_window_capital:.0f} per window (skip if below)")
    print(
        f"  Compounding  : {'on (portfolio carries over)' if args.compound else f'off (reset ${args.capital:,.0f} each day)'}"
    )
    print(f"  Dedup        : {'on' if args.dedup else 'off'}")
    if args.oracle_picks:
        print(f"  Picker       : ORACLE  (perfect hindsight — top-N by actual P&L, no EV gate)")
    elif args.random_picks:
        seed_str = str(args.random_seed) if args.random_seed is not None else "none (non-deterministic)"
        print(f"  Picker       : RANDOM  (seed={seed_str})")
    elif args.regime_scoring:
        bull_e  = args.regime_bull_entry_weight    if args.regime_bull_entry_weight    is not None else 0.70
        bull_vr = args.regime_bull_vol_ratio_weight if args.regime_bull_vol_ratio_weight is not None else 0.15
        bull_aw = args.regime_bull_avg_win_weight   if args.regime_bull_avg_win_weight   is not None else 0.00
        bull_m5 = args.regime_bull_ma50_dist_weight if args.regime_bull_ma50_dist_weight is not None else 0.10
        bear_e  = args.regime_bear_entry_weight    if args.regime_bear_entry_weight    is not None else 0.80
        bear_vr = args.regime_bear_vol_ratio_weight if args.regime_bear_vol_ratio_weight is not None else 0.15
        bear_aw = args.regime_bear_avg_win_weight   if args.regime_bear_avg_win_weight   is not None else 0.00
        bear_m5 = args.regime_bear_ma50_dist_weight if args.regime_bear_ma50_dist_weight is not None else 0.00
        bull_or = round(1.0 - bull_e - bull_vr - bull_aw - bull_m5, 3)
        bear_or = round(1.0 - bear_e - bear_vr - bear_aw - bear_m5, 3)
        print(f"  Picker       : REGIME-SCORED  (QQQ prior-close vs 50d MA)")
        print(f"    Bull (QQQ>MA50): entry={bull_e} avg_win={bull_aw} or_range={bull_or} vol={bull_vr} ma50={bull_m5}")
        print(f"    Bear (QQQ≤MA50): entry={bear_e} avg_win={bear_aw} or_range={bear_or} vol={bear_vr} ma50={bear_m5}")
    else:
        aw = args.score_avg_win_weight
        ev = args.score_entry_weight
        vr = args.score_vol_ratio_weight
        et = args.score_ev_trend_weight
        d52 = args.score_dist_52w_low_weight
        d52h = args.score_dist_52w_high_weight
        sk = args.score_streak_weight
        pv = args.score_prev_day_vol_weight
        m2 = args.score_ma200_dist_weight
        m5 = args.score_ma50_dist_weight
        ta = args.score_trend_align_weight
        fg = args.score_frog_weight
        rs = args.score_rel_strength_weight
        de = args.score_dir_ev_weight
        or_w = round(1.0 - ev - vr - aw - et - d52 - d52h - sk - pv - m2 - m5 - ta - fg - rs - de, 3)
        print(
            f"  Picker       : scored  (entry={ev} avg_win={aw} or_range={or_w} vol={vr} "
            f"ev_trend={et} dist_52w_low={d52} dist_52w_high={d52h} streak={sk} prev_vol={pv} ma200={m2} ma50={m5} trend_align={ta} frog={fg} rel_strength={rs} dir_ev={de})"
        )
    if args.direction_split_ev_gate:
        print(
            f"  Dir-split EV : on  bull≥{args.dg_bull_threshold} min_ev={args.ds_bull_min_ev:+.3f}"
            f"  neutral min_ev={args.ds_neutral_min_ev:+.3f}"
            f"  bear≤{args.dg_bear_threshold} min_ev={args.ds_bear_min_ev:+.3f}"
        )
    else:
        print(f"  Dir-split EV : off")
    if args.qqq_or_weight != 0.0:
        print(f"  QQQ OR score : weight={args.qqq_or_weight:+.3f}  (boosts aligned signals, penalises opposing)")
    if args.score_win_rate_weight != 0.0:
        print(f"  Win rate wt  : {args.score_win_rate_weight:+.3f}  (rewards consistent tickers)")
    if args.entry_weight_bull is not None or args.entry_weight_bear is not None:
        print(f"  Adaptive entry: bull={args.entry_weight_bull or 'default'}  bear={args.entry_weight_bear or 'default'}"
              f"  (pool_vote thresholds: bull≥{args.dg_bull_threshold} bear≤{args.dg_bear_threshold})")
    if args.normalize_or_by_adr:
        print(f"  OR/ADR norm  : on  adr_days={args.adr_days}  (or_range_pct ÷ rolling ADR)")
    if args.min_pool_vote_to_trade > 0:
        print(f"  Min pool vote: {args.min_pool_vote_to_trade}  (skip day if fewer tickers have positive EV)")
    if args.direction_regime_filter:
        print(f"  Dir regime   : on  bull≥{args.drf_bull_only_thresh}→BULLISH_only  bear≤{args.drf_bear_only_thresh}→BEARISH_only")
    if args.ev_shrink_k > 0:
        print(f"  EV shrinkage : k={args.ev_shrink_k:.1f}  (Bayesian shrink toward pool mean)")
    if args.score_frog_weight > 0:
        print(f"  Frog-in-Pan  : weight={args.score_frog_weight:.3f}  days={args.frog_days}  (path smoothness, direction-aware)")
    if args.score_rel_strength_weight > 0:
        print(f"  Rel strength : weight={args.score_rel_strength_weight:.3f}  (cross-sectional MA50 vs pool mean, direction-aware)")
    if args.score_dir_ev_weight > 0:
        print(f"  Dir EV score : weight={args.score_dir_ev_weight:.3f}  (direction-specific EV: bull→ev_bull, bear→ev_bear)")
    print(f"  Stop pct     : {args.stop_pct}")
    print(f"  Trailing MA  : {args.trailing_ma}")
    print(
        f"  Max loss pct : {f'{args.max_loss_pct * 100:.1f}%' if args.max_loss_pct else 'disabled'}"
    )
    print(
        f"  Min hold     : {f'{args.min_hold_bars} bars ({args.min_hold_bars * 5} min)' if args.min_hold_bars else 'off'}"
    )
    if args.stale_cut_mins > 0 and args.stale_cut_threshold > 0.0:
        print(f"  Stale cut    : exit at {args.stale_cut_mins} min if |P&L| < {args.stale_cut_threshold:.2f}%")
    else:
        print(f"  Stale cut    : off")
    print(f"  Armed MA20   : {'on' if args.armed_ma20_exit else 'off'}")
    print(
        f"  Regime filter: {'QQQ MA' + str(args.regime_ma) if args.regime_filter else 'off'}"
    )
    if args.qqq_align_filter:
        if args.qqq_extend_days > 0:
            extend_desc = (
                f"threshold={args.qqq_align_threshold}, "
                f"gate={args.qqq_extend_days}d>{args.qqq_extend_pct * 100:.0f}%"
            )
            if args.qqq_extend_max_dd > 0:
                extend_desc += f" max-dd={args.qqq_extend_max_dd * 100:.0f}%"
        else:
            extend_desc = f"threshold={args.qqq_align_threshold} (fires every day)"
        print(f"  QQQ align    : on ({extend_desc})")
    else:
        print(f"  QQQ align    : off")
    print(
        f"  Reversal     : {'on (max bars_held=' + str(args.reversal_max_bars) + ')' if args.reversal else 'off'}"
    )
    print(
        f"  Bearish Rev  : {'on (max bars_held=' + str(args.bearish_reversal_max_bars) + ')' if args.bearish_reversal else 'off'}"
    )
    print(
        f"  Bearish RE   : {'on (max bars_held=' + str(args.bearish_reentry_max_bars) + ')' if args.bearish_reentry else 'off'}"
    )
    print(
        f"  Bullish RE   : {'on (max bars_held=' + str(args.bullish_reentry_max_bars) + ')' if args.bullish_reentry else 'off'}"
    )
    if args.doubledown:
        print(f"  Double-down  : on (start +{args.doubledown_start_min}min, stop=80% bar-range on add-on)")
    else:
        print("  Double-down  : off")
    if args.opportunity_capital_pct > 0:
        _opp_initial = args.capital * args.opportunity_capital_pct / 100
        print(
            f"  Opp pool     : ${_opp_initial:,.0f} ({args.opportunity_capital_pct:.0f}% of initial capital)"
            + (" | compounded" if args.compound else " | resets daily")
        )
        if not args.doubledown:
            print("  WARNING: --opportunity-capital has no effect without --doubledown")
    else:
        print("  Opp pool     : disabled")
    if args.min_or_range > 0:
        wins_str = (
            ",".join(args.min_or_range_windows)
            if args.min_or_range_windows
            else "all windows"
        )
        min_or_range_desc = f"{args.min_or_range:.2f}% (windows: {wins_str})"
    else:
        min_or_range_desc = "disabled"
    print(f"  Min OR range : {min_or_range_desc}")
    if args.min_ma200_distance > 0:
        ma200_wins_str = (
            ",".join(args.min_ma200_distance_windows)
            if args.min_ma200_distance_windows
            else "all windows"
        )
        min_ma200_desc = f"{args.min_ma200_distance:.2f}% (windows: {ma200_wins_str})"
    else:
        min_ma200_desc = "disabled"
    print(f"  Min MA200 dist: {min_ma200_desc}")
    print(
        f"  Min score    : {f'{args.min_score:.3f}' if args.min_score > 0 else 'disabled'}"
    )
    print(
        f"  Min EV       : {f'{args.min_ev:.3f}%' if args.min_ev > 0 else 'disabled'}"
    )
    print(
        f"  OR bar lookback: {f'last {args.or_bar_lookback} bars' if args.or_bar_lookback > 0 else 'disabled'}"
    )
    print(
        f"  Close top pct: {f'top/bottom {args.close_top_pct * 100:.0f}% (global default, overridable per window)' if args.close_top_pct is not None else 'disabled (standard midpoint/bottom-30; per-window override via --window LABEL START BARS PCT)'}"
    )
    if args.dynamic_ev_gate:
        if args.dg_mode == "percentile":
            print(
                f"  Dyn EV gate  : on [{args.dg_mode}]"
                f"  bull≥{args.dg_bull_threshold} excl={args.dg_bull_exclude_pct:.0%}"
                f"  neutral excl={args.dg_neutral_exclude_pct:.0%}"
                f"  bear≤{args.dg_bear_threshold} excl={args.dg_bear_exclude_pct:.0%}"
            )
        else:
            print(
                f"  Dyn EV gate  : on [{args.dg_mode}]"
                f"  bull≥{args.dg_bull_threshold} (WR≥{args.dg_bull_min_wr:.0%} W/L≥{args.dg_bull_min_wl})"
                f"  neutral (WR≥{args.dg_neutral_min_wr:.0%} W/L≥{args.dg_neutral_min_wl})"
                f"  bear≤{args.dg_bear_threshold} (WR≥{args.dg_bear_min_wr:.0%} W/L≥{args.dg_bear_min_wl})"
            )
    else:
        print(f"  Dyn EV gate  : off")
    if args.adaptive_lookback:
        print(
            f"  Adapt lookback: on  bull≥{args.al_bull_threshold}→{args.al_bull_days}d"
            f"  neutral→{args.al_neutral_days}d"
            f"  bear≤{args.al_bear_threshold}→{args.al_bear_days}d"
        )
    else:
        print(f"  Adapt lookback: off")
    print(f"  Source       : {args.source}")
    alpaca_feed = DataFeed.IEX if args.feed == "iex" else DataFeed.SIP
    if args.source == "alpaca":
        print(f"  Alpaca feed  : {args.feed.upper()}")

    only_dates = None
    if args.only_dates:
        with open(args.only_dates) as _f:
            only_dates = {date.fromisoformat(ln.strip()) for ln in _f if ln.strip()}
        print(f"  Only dates   : {len(only_dates)} days loaded from {args.only_dates}")

    if args.regime_adaptive:
        if args.doubledown:
            raise SystemExit("--regime-adaptive and --doubledown cannot be used together.")
        print(f"  Regime adapt : on (VIX_LO={REGIME_VIX_LO} VIX_HI={REGIME_VIX_HI} MA_score≥{REGIME_MA_STRONG_SCORE})")

    trade_rows, all_window_results, trading_days = run_selector_backtest(
        n=args.top,
        tickers=tickers,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_days=args.lookback,
        opening_bars=args.opening_bars,
        opening_start_time=args.opening_start,
        bearish_ma200=args.bearish_ma200,
        stop_pct=args.stop_pct,
        source=args.source,
        trailing_ma=args.trailing_ma,
        trailing_ma_switch=args.trailing_ma_switch,
        trailing_ma_switch_factor=args.trailing_ma_switch_factor,
        trailing_ma_switch_period=args.trailing_ma_switch_period,
        max_loss_pct=args.max_loss_pct,
        armed_ma20_exit=args.armed_ma20_exit,
        regime_filter=args.regime_filter,
        regime_ma=args.regime_ma,
        windows=windows,
        dedup=args.dedup,
        enable_reversal=args.reversal,
        reversal_max_bars_held=args.reversal_max_bars,
        enable_bearish_reversal=args.bearish_reversal,
        bearish_reversal_max_bars_held=args.bearish_reversal_max_bars,
        enable_bearish_reentry=args.bearish_reentry,
        bearish_reentry_max_bars=args.bearish_reentry_max_bars,
        enable_bullish_reentry=args.bullish_reentry,
        bullish_reentry_max_bars=args.bullish_reentry_max_bars,
        min_or_range=args.min_or_range,
        min_or_range_windows=args.min_or_range_windows,
        min_ma200_distance=args.min_ma200_distance,
        min_ma200_distance_windows=args.min_ma200_distance_windows,
        min_score=args.min_score,
        min_ev=args.min_ev,
        or_bar_lookback=args.or_bar_lookback,
        close_top_pct=args.close_top_pct,
        feed=alpaca_feed,
        enable_doubledown=args.doubledown,
        doubledown_start_min=args.doubledown_start_min,
        qqq_align_filter=args.qqq_align_filter,
        qqq_align_threshold=args.qqq_align_threshold,
        qqq_extend_days=args.qqq_extend_days,
        qqq_extend_pct=args.qqq_extend_pct,
        qqq_extend_max_dd=args.qqq_extend_max_dd,
        min_first_bar_range_pct=args.min_first_bar_range_pct,
        min_first_bar_volume_mult=args.min_first_bar_volume_mult,
        min_or_vol_ratio=args.min_or_vol_ratio,
        score_entry_weight=args.score_entry_weight,
        score_vol_ratio_weight=args.score_vol_ratio_weight,
        score_avg_win_weight=args.score_avg_win_weight,
        score_ev_trend_weight=args.score_ev_trend_weight,
        score_dist_52w_low_weight=args.score_dist_52w_low_weight,
        score_dist_52w_high_weight=args.score_dist_52w_high_weight,
        score_streak_weight=args.score_streak_weight,
        score_prev_day_vol_weight=args.score_prev_day_vol_weight,
        score_ma200_dist_weight=args.score_ma200_dist_weight,
        score_ma50_dist_weight=args.score_ma50_dist_weight,
        regime_scoring=args.regime_scoring,
        regime_bull_entry_weight=args.regime_bull_entry_weight if args.regime_bull_entry_weight is not None else (0.70 if args.regime_scoring else None),
        regime_bull_vol_ratio_weight=args.regime_bull_vol_ratio_weight if args.regime_bull_vol_ratio_weight is not None else (0.15 if args.regime_scoring else None),
        regime_bull_avg_win_weight=args.regime_bull_avg_win_weight if args.regime_bull_avg_win_weight is not None else (0.00 if args.regime_scoring else None),
        regime_bull_ma50_dist_weight=args.regime_bull_ma50_dist_weight if args.regime_bull_ma50_dist_weight is not None else (0.10 if args.regime_scoring else None),
        regime_bear_entry_weight=args.regime_bear_entry_weight if args.regime_bear_entry_weight is not None else (0.80 if args.regime_scoring else None),
        regime_bear_vol_ratio_weight=args.regime_bear_vol_ratio_weight if args.regime_bear_vol_ratio_weight is not None else (0.15 if args.regime_scoring else None),
        regime_bear_avg_win_weight=args.regime_bear_avg_win_weight if args.regime_bear_avg_win_weight is not None else (0.00 if args.regime_scoring else None),
        regime_bear_ma50_dist_weight=args.regime_bear_ma50_dist_weight if args.regime_bear_ma50_dist_weight is not None else (0.00 if args.regime_scoring else None),
        ev_trend_days=args.ev_trend_days,
        direction_split_ev_gate=args.direction_split_ev_gate,
        ds_bull_min_ev=args.ds_bull_min_ev,
        ds_neutral_min_ev=args.ds_neutral_min_ev,
        ds_bear_min_ev=args.ds_bear_min_ev,
        oracle_picks=args.oracle_picks,
        min_hold_bars=args.min_hold_bars,
        stale_cut_mins=args.stale_cut_mins,
        stale_cut_threshold=args.stale_cut_threshold,
        exit_at_bar_close=args.exit_at_bar_close,
        only_dates=only_dates,
        regime_adaptive=args.regime_adaptive,
        random_picks=args.random_picks,
        random_seed=args.random_seed,
        ma_momentum_gate=args.ma_momentum_gate,
        ma_momentum_gate_in_scoring=args.ma_momentum_gate_in_scoring,
        dynamic_ev_gate=args.dynamic_ev_gate,
        dg_mode=args.dg_mode,
        dg_bull_threshold=args.dg_bull_threshold,
        dg_bear_threshold=args.dg_bear_threshold,
        dg_bull_exclude_pct=args.dg_bull_exclude_pct,
        dg_neutral_exclude_pct=args.dg_neutral_exclude_pct,
        dg_bear_exclude_pct=args.dg_bear_exclude_pct,
        dg_bull_min_wr=args.dg_bull_min_wr,
        dg_neutral_min_wr=args.dg_neutral_min_wr,
        dg_bear_min_wr=args.dg_bear_min_wr,
        dg_bull_min_wl=args.dg_bull_min_wl,
        dg_neutral_min_wl=args.dg_neutral_min_wl,
        dg_bear_min_wl=args.dg_bear_min_wl,
        adaptive_lookback=args.adaptive_lookback,
        al_bull_threshold=args.al_bull_threshold,
        al_bear_threshold=args.al_bear_threshold,
        al_bull_days=args.al_bull_days,
        al_neutral_days=args.al_neutral_days,
        al_bear_days=args.al_bear_days,
        qqq_or_weight=args.qqq_or_weight,
        score_win_rate_weight=args.score_win_rate_weight,
        entry_weight_bull=args.entry_weight_bull,
        entry_weight_bear=args.entry_weight_bear,
        normalize_or_by_adr=args.normalize_or_by_adr,
        adr_days=args.adr_days,
        min_pool_vote_to_trade=args.min_pool_vote_to_trade,
        score_trend_align_weight=args.score_trend_align_weight,
        direction_regime_filter=args.direction_regime_filter,
        drf_bull_only_thresh=args.drf_bull_only_thresh,
        drf_bear_only_thresh=args.drf_bear_only_thresh,
        ev_shrink_k=args.ev_shrink_k,
        score_frog_weight=args.score_frog_weight,
        frog_days=args.frog_days,
        score_rel_strength_weight=args.score_rel_strength_weight,
        score_dir_ev_weight=args.score_dir_ev_weight,
    )

    skip_log = _apply_capital_flow(
        trade_rows,
        resolved_windows,
        args.capital,
        weights,
        args.top,
        morning_split=morning_split,
        min_capital=args.min_window_capital,
        compound=args.compound,
        enable_doubledown=args.doubledown,
    )

    if args.doubledown:
        _apply_doubledown(trade_rows)

    if args.opportunity_capital_pct > 0 and args.doubledown:
        _opp_initial = args.capital * args.opportunity_capital_pct / 100
        _apply_opportunity_pool(
            trade_rows,
            resolved_windows,
            initial_pool=_opp_initial,
            compound=args.compound,
            doubledown_start_min=args.doubledown_start_min,
        )

    baseline_df = _collect_baseline(all_window_results, eval_start, eval_end)

    print("Fetching QQQ daily bars for comparison...")
    qqq_df = fetch_daily_bars(["QQQ"], eval_start, eval_end, source=args.source, feed=alpaca_feed).get(
        "QQQ", pd.DataFrame()
    )
    qqq_closes = qqq_df["Close"] if not qqq_df.empty else pd.Series(dtype=float)

    multi_window = n_windows > 1
    _print_daily_table(
        trade_rows, n=args.top, weights=weights, multi_window=multi_window
    )
    _print_summary(
        trade_rows,
        baseline_df,
        n=args.top,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_days=args.lookback,
        stop_pct=args.stop_pct,
        windows=resolved_windows,
        initial_capital=args.capital,
        qqq_closes=qqq_closes,
        weights=weights,
        morning_split=morning_split,
    )
    if args.opportunity_capital_pct > 0 and args.doubledown:
        _opp_initial = args.capital * args.opportunity_capital_pct / 100
        _print_opportunity_pool_block(trade_rows, _opp_initial, args.compound)

    if args.regime_adaptive:
        _print_regime_summary(trade_rows, trading_days)

    if args.show_execution_log:
        _print_skip_log(skip_log, resolved_windows)

    if args.csv_out:
        active = [r for r in trade_rows if not r.get("skipped")]
        pd.DataFrame(active).to_csv(args.csv_out, index=False)
        print(f"\nTrade rows written to: {args.csv_out}")
