"""
Ticker lifecycle analyzer.

For a given pool of tickers, shows each ticker's current position in its selection
cycle based on the win-rate selector patterns documented in
WIN_RATE_TICKER_SELECTION_AND_LIFE_CYCLE.md.

For each ticker it computes:
  - Current 20-day EOD win rate and hold window profile
  - Win rate trend (current 20d vs prior 10d window)
  - Selection streak / absence gap over the last 60 trading days
  - Trade fire rate and P&L density (from replay logs, optional)
  - Lifecycle phase classification

Usage (from project root with virtualenv active):
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
        --tickers LUNR OKLO IONQ RKLB CLSK HOOD CRWD PLTR AMD TSLA \
        --top 8 \
        --lookback 60

    # With replay log dir to show P&L density:
    python ... --log-dir logs/replay_2026_stock_m1_winrate_regimehold_cap80k_fixedalloc_reversal_dd

    # Pipe-friendly compact output:
    python ... --compact
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from alpaca.data.enums import DataFeed
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.regime_engine import (
    DailyRegimeMetrics,
    RegimeEngine,
)
from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _DEFAULT_OR_BARS,
    _DEFAULT_OR_START,
    _precompute_or_anchor_returns,
    _rank_tickers_by_eod_win_rate,
)

_LOOKBACK_WIN_RATE = 20
_TREND_SHORT = 10
_WARMUP_EXTRA = 10

_LIFECYCLE_CACHE_DIR = (
    Path(__file__).parent.parent.parent.parent / "market_data" / "cache"
)

_PHASE_COLORS = {
    "HIBERNATING":   "\033[90m",   # dark grey
    "RE-ACTIVATING": "\033[92m",   # bright green
    "ACTIVE":        "\033[32m",   # green
    "MATURE CYCLE":  "\033[36m",   # cyan
    "QUALITY FADE":  "\033[33m",   # yellow
    "CLIFF EDGE":    "\033[91m",   # bright red
    "DORMANT":       "\033[90m",   # dark grey (never selected)
}
_RESET = "\033[0m"

_DIR_COLORS = {
    "LONG":    "\033[32m",   # green
    "SHORT":   "\033[91m",   # bright red
    "CAUTION": "\033[33m",   # yellow
    "NEUTRAL": "\033[36m",   # cyan
    "WAIT":    "\033[33m",   # yellow
}

# Regime guidance from MASTER_REGIME_SUMMARY.md — monthly direction, exit, confirmation, notes.
# regime_hold_note: how QQQ MA8 regime-hold filter changes the recommendation.
_REGIME_BY_MONTH = {
    1:  {
        "direction": "LONG",
        "exit": "EOD",
        "confirm": "Day-3 WR check",
        "note": "Flip SHORT immediately if day-3 EOD WR < 45%. 9/11 years positive; only 2022 and 2026 failed.",
        "regime_hold": "Filter handles intra-month bear days; still long-biased with regime-hold.",
    },
    2:  {
        "direction": "NEUTRAL",
        "exit": "EOD",
        "confirm": "Day-3 shape",
        "note": "Follow Jan's regime. AM-pop-fade risk: if +15m WR drops ≥15pp by +30m, exit at +15m only. Feb 2026 was short at +15m (+33.8%).",
        "regime_hold": "Filter reduces AM-pop-fade exposure. No structural change to default.",
    },
    3:  {
        "direction": "CAUTION",
        "exit": "+15m",
        "confirm": "Day-3 required",
        "note": "Most dangerous month — 7/11 years negative. NO POSITION until day-3 confirms. WR > 55% + rising curve → extend to EOD. Otherwise SHORT. Mar 2026 short EOD: +19.4%.",
        "regime_hold": "Regime-hold filter made March positive 9/10 years — caution rule is for unfiltered strategy only.",
    },
    4:  {
        "direction": "NEUTRAL",
        "exit": "EOD",
        "confirm": "First 2–3 days",
        "note": "No seasonal assumption — confirm from day 1. Highly mixed across years. Event-driven (Liberation Day 2025/2026). Apr 2025: +157%, Apr 2026: +40%.",
        "regime_hold": "With regime-hold, April is the empirically strongest month — mild bull prior with day-3 confirmation.",
    },
    5:  {
        "direction": "LONG",
        "exit": "EOD",
        "confirm": "Watch EV",
        "note": "Mild bull — 7/9 years positive. Check avg gain (EV), not just win rate. Independent of April's result.",
        "regime_hold": "No change — mild bull prior holds with or without filter.",
    },
    6:  {
        "direction": "NEUTRAL",
        "exit": "EOD",
        "confirm": "Day-3 curve",
        "note": "Follow May shape if May was rising-curve bull. Range -3.2% to +19.8% (adj). Never a deep bear. Hold curve direction by day 3 is the signal.",
        "regime_hold": "No structural change. Follow May's regime-hold direction.",
    },
    7:  {
        "direction": "NEUTRAL",
        "exit": "EOD",
        "confirm": "Curve shape",
        "note": "Follow Jun's regime. If Jun was rising-curve bull, hold EOD. Strong when broader bull in place (2016–2018 all +16–21%).",
        "regime_hold": "No change — carry prior month's regime-hold stance.",
    },
    8:  {
        "direction": "CAUTION",
        "exit": "+15m",
        "confirm": "Week-1 shape",
        "note": "Very split: strong bull (2023 +26%, 2025 +21%) vs deep bear (2022 -29%, 2024 -29%). Check AM-pop-fade. If Jul was rising-curve bull, default to EOD and monitor.",
        "regime_hold": "Least reliable rule (+14pp net, high variance). Only apply +15m default if July was also flat/negative.",
    },
    9:  {
        "direction": "SHORT",
        "exit": "+15m–+30m",
        "confirm": "—",
        "note": "7/10 years bear or fade. AM-pop-fade dominant: +15m WR looks ok then collapses by +30m. Override to LONG only if avg win > 1.5× avg loss AND hold curve rising by day 3.",
        "regime_hold": "September SHORT is largely unnecessary with regime-hold — filter makes Sep positive 7/9 years. Do NOT stack both.",
    },
    10: {
        "direction": "LONG",
        "exit": "+3h–EOD",
        "confirm": "Day-1",
        "note": "Strongest seasonal — 9/11 years positive. Both exceptions (2016 election, 2021 Omicron) have named macro overrides. Avg bull Oct: +17.3%.",
        "regime_hold": "Confirmed 9-for-9 with regime-hold — no exceptions. Most reliable month in the dataset.",
    },
    11: {
        "direction": "WAIT",
        "exit": "EOD or SHORT",
        "confirm": "Week-1 EV",
        "note": "Most unpredictable month. Check EV after week 1: EV > 0 per signal → LONG EOD; EV ≤ 0 regardless of WR → SHORT EOD. Spread: Nov 2024 +42.9% vs Nov 2021 -34.7%.",
        "regime_hold": "Regime-hold leans positive (6/9 years) but does not resolve November's unpredictability. Still use week-1 EV check.",
    },
    12: {
        "direction": "SHORT",
        "exit": "EOD",
        "confirm": "—",
        "note": "8/10 years negative. Override to LONG only with named macro catalyst (trade deal, vaccine, major policy). Dec 2019 (Phase 1) and Dec 2020 (vaccine) are only valid overrides.",
        "regime_hold": "December SHORT almost entirely neutralized by regime-hold — filter made Dec positive 8/9 years. Do NOT stack both.",
    },
}


def _print_regime_note(today, regime_state=None, n_metrics=0):
    month = today.month
    r = _REGIME_BY_MONTH.get(month)
    if not r:
        return
    month_name = today.strftime("%B %Y")
    dir_col = _DIR_COLORS.get(r["direction"], "")
    print(f"\n{'─'*92}")
    print(f"  Regime Guidance — {month_name}  (source: MASTER_REGIME_SUMMARY.md)")
    print(f"{'─'*92}")
    print(f"  Direction : {dir_col}{r['direction']}{_RESET}  |  Exit: {r['exit']}  |  Confirm: {r['confirm']}")
    print(f"  Seasonal  : {r['note']}")
    print(f"  With MA8  : {r['regime_hold']}")

    if regime_state is not None:
        rs_col = _DIR_COLORS.get(regime_state.direction, "")
        if n_metrics < 3:
            status = "PENDING (need ≥3 days)"
        elif regime_state.source == "seasonal":
            status = "SEASONAL (no rolling pattern yet)"
        else:
            status = "CONFIRMED"
        print(f"  {'─'*88}")
        print(
            f"  Live      : {rs_col}{regime_state.direction}{_RESET}"
            f"  Hold: {regime_state.hold_window or '—'}"
            f"  [{regime_state.regime_type}]"
            f"  via {regime_state.source}"
            f"  ({n_metrics}d)  {status}"
        )
        print(f"  → {regime_state.notes}")


# ---------------------------------------------------------------------------
# Daily-rank incremental cache
# ---------------------------------------------------------------------------

def _lifecycle_cache_path(tickers, or_start, or_bars, feed, wr_lookback):
    key = "|".join([
        ",".join(sorted(tickers)),
        or_start,
        str(or_bars),
        feed or "default",
        str(wr_lookback),
    ])
    h = hashlib.sha256(key.encode()).hexdigest()[:10]
    return _LIFECYCLE_CACHE_DIR / f"lifecycle_daily_rank_{h}.json"


def _load_lifecycle_cache(path):
    """Return {date: [ticker, ...]} from disk, or empty dict if missing/corrupt."""
    try:
        raw = json.loads(path.read_text())
        return {date.fromisoformat(k): v for k, v in raw.get("daily_rank", {}).items()}
    except Exception:
        return {}


def _save_lifecycle_cache(path, daily_rank):
    _LIFECYCLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"daily_rank": {d.isoformat(): tickers for d, tickers in daily_rank.items()}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Regime metrics computation from daily-rank picks
# ---------------------------------------------------------------------------

_REGIME_HOLD_MIN = [15, 30, 60, 120, 180, 300, None]
_REGIME_HOLD_LABELS = {15: "+15m", 30: "+30m", 60: "+1h", 120: "+2h", 180: "+3h", 300: "+5h", None: "EOD"}


def _build_daily_metrics_from_rank(ticker_bars, daily_rank, eval_days, or_start, or_bars, top_n):
    """
    For each day in eval_days, compute DailyRegimeMetrics from the top-N tickers
    in daily_rank.  Returns a list of DailyRegimeMetrics sorted by date.
    """
    or_start_dt = datetime.strptime(or_start, "%H:%M")
    or_close_t = (or_start_dt + timedelta(minutes=(or_bars - 1) * 5)).time()

    daily_metrics = []
    for d in eval_days:
        picks = daily_rank.get(d, [])[:top_n]
        hold_returns = {h: [] for h in _REGIME_HOLD_MIN}

        for ticker in picks:
            df = ticker_bars.get(ticker)
            if df is None or df.empty:
                continue
            day_df = df[df.index.date == d]
            if day_df.empty:
                continue

            close_col = "close" if "close" in day_df.columns else "Close"
            or_mask = day_df.index.time == or_close_t
            if not or_mask.any():
                continue
            entry_price = float(day_df[or_mask].iloc[0][close_col])
            if entry_price <= 0:
                continue

            for h in _REGIME_HOLD_MIN:
                if h is None:
                    exit_price = float(day_df.iloc[-1][close_col])
                else:
                    exit_t = (datetime.combine(d, or_close_t) + timedelta(minutes=h)).time()
                    exit_mask = day_df.index.time >= exit_t
                    if not exit_mask.any():
                        continue
                    exit_price = float(day_df[exit_mask].iloc[0][close_col])
                hold_returns[h].append((exit_price - entry_price) / entry_price)

        eod_rets = hold_returns[None]
        if not eod_rets:
            continue

        wins = [r for r in eod_rets if r > 0]
        losses = [r for r in eod_rets if r <= 0]
        hold_curve = {
            _REGIME_HOLD_LABELS[h]: len([r for r in hold_returns[h] if r > 0]) / len(hold_returns[h])
            for h in _REGIME_HOLD_MIN if hold_returns[h]
        }

        daily_metrics.append(DailyRegimeMetrics(
            date=d,
            signal_count=len(picks),
            eod_wr=len(wins) / len(eod_rets),
            avg_gain=sum(eod_rets) / len(eod_rets),
            avg_win=sum(wins) / len(wins) if wins else 0.0,
            avg_loss=sum(losses) / len(losses) if losses else 0.0,
            hold_curve=hold_curve,
        ))

    return sorted(daily_metrics, key=lambda m: m.date)


def _compute_regime_state(daily_metrics, today_eval):
    """Instantiate RegimeEngine in-memory (no disk I/O) and return current RegimeState."""
    engine = RegimeEngine.__new__(RegimeEngine)
    engine._history = daily_metrics[-10:]
    return engine.get_current_regime(as_of_date=today_eval)


# ---------------------------------------------------------------------------
# Lifecycle phase classification
# ---------------------------------------------------------------------------

def _classify_phase(streak, absence_gap, wr_eod, wr_trend_delta, fire_rate):
    """
    streak        : positive = consecutive days IN top-N, negative = days OUT
    absence_gap   : how many days since last top-N selection (0 if currently in)
    wr_eod        : current 20d EOD win rate (0-100)
    wr_trend_delta: current 20d EOD WR minus prior 10d EOD WR (points)
    fire_rate     : trades / days selected over last 10 days (0-1), or None

    Returns (phase_label, detail_str)
    """
    if streak <= 0:
        gap = abs(streak)
        if gap >= 15:
            return "HIBERNATING", f"absent {gap}d"
        return "HIBERNATING", f"absent {gap}d (short gap)"

    # Currently in streak
    # Quality fade: selected but fire rate collapsing post a recent peak
    if fire_rate is not None and fire_rate < 0.3 and streak >= 3:
        if wr_trend_delta < -5:
            return "QUALITY FADE", f"streak {streak}d fire={fire_rate:.0%} wr↓{wr_trend_delta:+.0f}pp"
        return "QUALITY FADE", f"streak {streak}d fire={fire_rate:.0%}"

    # Cliff edge: win rate dropping sharply even while selected
    if wr_trend_delta <= -15 and streak >= 3:
        return "CLIFF EDGE", f"streak {streak}d wr↓{wr_trend_delta:+.0f}pp"

    # Fresh re-activation (returned after an absence)
    if 1 <= streak <= 4 and absence_gap >= 15:
        return "RE-ACTIVATING", f"streak {streak}d (gap was {absence_gap}d)"

    if 1 <= streak <= 4:
        return "RE-ACTIVATING", f"streak {streak}d"

    if 5 <= streak <= 19:
        trend = f" wr↑{wr_trend_delta:+.0f}pp" if wr_trend_delta >= 5 else (f" wr↓{wr_trend_delta:+.0f}pp" if wr_trend_delta <= -5 else "")
        return "ACTIVE", f"streak {streak}d{trend}"

    trend = f" wr↑{wr_trend_delta:+.0f}pp" if wr_trend_delta >= 5 else (f" wr↓{wr_trend_delta:+.0f}pp" if wr_trend_delta <= -5 else "")
    return "MATURE CYCLE", f"streak {streak}d{trend}"


# ---------------------------------------------------------------------------
# Log parsing (optional P&L density)
# ---------------------------------------------------------------------------

def _load_log_stats(log_dir, tickers, trading_days):
    """
    Parse replay log dir for the last N trading days.
    Returns {ticker: {"selected": int, "trades": int, "pnl": float}} over that window.
    """
    cap_re = re.compile(r"Capital returned \[M1\] (\w+) .*?cap_pnl=([+-]?[\d.]+)")
    sel_re = re.compile(r"WinRateTickerSelector.*top-\d+: \[([^\]]+)\]")
    date_re = re.compile(r"Replay (\d{4}-\d{2}-\d{2})")

    stats = defaultdict(lambda: {"selected": 0, "trades": 0, "pnl": 0.0})
    target_dates = set(str(d) for d in trading_days)

    for fname in sorted(os.listdir(log_dir)):
        if not fname.endswith(".log"):
            continue
        dm = date_re.search(fname)
        if not dm or dm.group(1) not in target_dates:
            continue
        with open(os.path.join(log_dir, fname)) as f:
            content = f.read()
        sm = sel_re.search(content)
        if sm:
            picks = [t.strip().strip("'") for t in sm.group(1).split(",")]
            for t in picks:
                if t in tickers:
                    stats[t]["selected"] += 1
        for m in cap_re.finditer(content):
            t, pnl = m.group(1), float(m.group(2))
            if t in tickers:
                stats[t]["trades"] += 1
                stats[t]["pnl"] += pnl

    return stats


# ---------------------------------------------------------------------------
# Core: compute per-ticker state over a rolling window of trading days
# ---------------------------------------------------------------------------

def compute_lifecycle(ticker_bars, trading_days, top_n, or_start, or_bars, lookback_wr,
                      cached_daily_rank=None, ticker_anchor_returns=None):
    """
    For each trading day in `trading_days`, rank the pool and record which tickers
    were in the top-N. Returns per-ticker state as of the last day.

    ticker_bars         : {ticker: df_5m}  (must cover at least lookback_wr+len(trading_days) days)
    trading_days        : list of date objects, chronological, representing the window to evaluate
    cached_daily_rank   : pre-loaded {date: [ticker, ...]} from disk; days present are skipped
    ticker_anchor_returns: pre-computed {ticker: {date: {hold_min: pct}}} — fast dict-lookup path
    """
    daily_rank = dict(cached_daily_rank) if cached_daily_rank else {}

    missing_days = [d for d in trading_days if d not in daily_rank]
    if missing_days:
        print(f"  [lifecycle cache] computing {len(missing_days)} day(s) "
              f"(skipping {len(trading_days) - len(missing_days)} cached) ...")
        for target in missing_days:
            ranked = _rank_tickers_by_eod_win_rate(
                ticker_bars, target, or_start, or_bars, lookback_wr,
                ticker_anchor_returns=ticker_anchor_returns,
            )
            daily_rank[target] = [t for t, _ in ranked]
    else:
        print(f"  [lifecycle cache] all {len(trading_days)} days loaded from cache")

    # Per-ticker: current streak, absence gap, win rates on last day
    ticker_states = {}
    all_days = sorted(daily_rank.keys())
    today = all_days[-1]

    for ticker, df in ticker_bars.items():
        # Compute streak as of today
        streak = 0
        last_absence_gap = 0
        prev_in = None
        last_exit_day = None

        for d in all_days:
            ranked = daily_rank[d]
            in_topn = ranked.index(ticker) < top_n if ticker in ranked else False
            if in_topn:
                if prev_in is False or prev_in is None:
                    # Just entered
                    last_absence_gap = abs(streak) if streak < 0 else 0
                    streak = 1
                else:
                    streak += 1
            else:
                if prev_in is True:
                    last_exit_day = d
                    streak = -1
                elif prev_in is False or prev_in is None:
                    streak -= 1
                else:
                    streak = -1
            prev_in = in_topn

        absence_gap = last_absence_gap if streak > 0 else 0

        # Win rates on today and trend — use anchor_returns fast path when available
        hist_today = None
        hist_prior = None
        if ticker in ticker_bars and not ticker_bars[ticker].empty:
            from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
                _compute_hold_history,
            )
            anchor_returns = ticker_anchor_returns.get(ticker) if ticker_anchor_returns else None
            hist_today = _compute_hold_history(
                ticker_bars[ticker], today, or_start, or_bars, lookback_wr,
                anchor_returns=anchor_returns,
            )
            # Prior window: 10 days ago
            trend_anchor = all_days[max(0, len(all_days) - _TREND_SHORT - 1)]
            hist_prior = _compute_hold_history(
                ticker_bars[ticker], trend_anchor, or_start, or_bars, lookback_wr,
                anchor_returns=anchor_returns,
            )

        wr_eod = hist_today["win_rates"].get(None, 0) if hist_today else 0
        med_eod = hist_today["medians"].get(None, 0) if hist_today else 0
        wr_15m = hist_today["win_rates"].get(15, 0) if hist_today else 0
        wr_eod_prior = hist_prior["win_rates"].get(None, 0) if hist_prior else wr_eod
        wr_trend = wr_eod - wr_eod_prior

        # Pool rank today
        today_ranked = daily_rank[today]
        pool_rank = today_ranked.index(ticker) + 1 if ticker in today_ranked else len(today_ranked) + 1

        ticker_states[ticker] = {
            "streak": streak,
            "absence_gap": absence_gap,
            "wr_eod": wr_eod,
            "med_eod": med_eod,
            "wr_15m": wr_15m,
            "wr_trend": wr_trend,
            "pool_rank": pool_rank,
            "in_topn": pool_rank <= top_n,
            "n_days": hist_today["n"] if hist_today else 0,
        }

    return ticker_states, daily_rank


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _phase_color(phase):
    return _PHASE_COLORS.get(phase, "")


def print_dashboard(ticker_states, log_stats, top_n, today, compact, regime_state=None, n_metrics=0):
    _print_regime_note(today, regime_state=regime_state, n_metrics=n_metrics)

    # Sort: in-topN first (by pool rank), then out (by streak desc)
    in_top = sorted(
        [(t, s) for t, s in ticker_states.items() if s["in_topn"]],
        key=lambda x: x[1]["pool_rank"],
    )
    out_top = sorted(
        [(t, s) for t, s in ticker_states.items() if not s["in_topn"]],
        key=lambda x: -x[1]["wr_eod"],
    )
    ordered = in_top + out_top

    # Header
    print(f"\n{'─'*92}")
    print(f"  Ticker Lifecycle — as of {today}  |  top-{top_n} pool  |  20d EOD win rate")
    print(f"{'─'*92}")

    if not compact:
        print(
            f"  {'Ticker':<7} {'Rank':>5}  {'15mWR':>6}  {'EOD_WR':>7}  {'Med%':>6}  "
            f"{'Trend':>7}  {'Streak':>8}  {'Phase':<14}  {'Detail'}"
        )
        print(f"  {'─'*88}")

    prev_in_topn = None
    for ticker, s in ordered:
        # divider between in/out
        if not compact and prev_in_topn is True and not s["in_topn"]:
            print(f"  {'─'*88}")
        prev_in_topn = s["in_topn"]

        # Fire rate from logs
        fire_rate = None
        pnl_density = None
        if ticker in log_stats and log_stats[ticker]["selected"] > 0:
            ls = log_stats[ticker]
            fire_rate = ls["trades"] / ls["selected"] if ls["selected"] else None
            pnl_density = ls["pnl"] / ls["selected"] if ls["selected"] else None

        phase, detail = _classify_phase(
            s["streak"], s["absence_gap"], s["wr_eod"], s["wr_trend"], fire_rate
        )

        rank_str = f"#{s['pool_rank']}" if s["in_topn"] else f" {s['pool_rank']}"
        trend_str = f"{s['wr_trend']:+.0f}pp"
        col = _phase_color(phase)

        if compact:
            pnl_str = f"  pnl/sel=${pnl_density:+.0f}" if pnl_density is not None else ""
            print(f"  {col}{ticker:<7}{_RESET} {rank_str:>5}  EOD {s['wr_eod']:.0f}%  "
                  f"{col}{phase:<14}{_RESET}  {detail}{pnl_str}")
        else:
            pnl_str = f"  pnl/sel=${pnl_density:+.0f}" if pnl_density is not None else ""
            print(
                f"  {col}{ticker:<7}{_RESET} {rank_str:>5}  "
                f"{s['wr_15m']:>5.0f}%  {s['wr_eod']:>6.0f}%  {s['med_eod']:>+5.1f}%  "
                f"{trend_str:>7}  "
                f"{s['streak']:>+7}d  "
                f"{col}{phase:<14}{_RESET}  {detail}{pnl_str}"
            )

    print(f"{'─'*92}")
    print(f"  Rank ≤ {top_n} = currently in top-{top_n}  |  Trend = 20d WR minus 10d-ago WR\n")


def print_streak_timeline(ticker_states, daily_rank, top_n, tickers_focus, today):
    """Print a compact ASCII timeline of in/out selection over the evaluation window."""
    all_days = sorted(daily_rank.keys())
    # Show last 40 days max
    show_days = all_days[-40:]
    # Header: month/day labels every 5 days
    label_row = "  " + " " * 9
    for i, d in enumerate(show_days):
        if i % 5 == 0:
            label_row += str(d)[5:]  # MM-DD
        else:
            label_row += "     "
    print(label_row)

    # One row per ticker
    for ticker in tickers_focus:
        row = f"  {ticker:<7}  "
        for d in show_days:
            ranked = daily_rank[d]
            in_topn = ranked.index(ticker) < top_n if ticker in ranked else False
            row += "█" if in_topn else "·"
        state = ticker_states.get(ticker, {})
        phase, _ = _classify_phase(
            state.get("streak", 0), state.get("absence_gap", 0),
            state.get("wr_eod", 0), state.get("wr_trend", 0), None
        )
        col = _phase_color(phase)
        row += f"  {col}{phase}{_RESET}"
        print(row)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Ticker lifecycle analyzer")
    p.add_argument(
        "--tickers", nargs="+",
        default=["SNDK", "META", "SNOW", "PLTR", "MU", "LLY", "LUNR", "CRWD",
                 "QCOM", "OKLO", "TSLA", "AVGO", "ARM", "AMD", "DDOG", "RDDT",
                 "IONQ", "HOOD", "RKLB", "CLSK"],
    )
    p.add_argument("--top", type=int, default=8, help="Top-N selection size (default 8)")
    p.add_argument("--lookback", type=int, default=60,
                   help="Days of history to evaluate selection streak (default 60)")
    p.add_argument("--wr-lookback", type=int, default=20,
                   help="Win rate rolling window in days (default 20)")
    p.add_argument("--or-start", default=_DEFAULT_OR_START)
    p.add_argument("--or-bars", type=int, default=_DEFAULT_OR_BARS)
    p.add_argument("--log-dir", default=None,
                   help="Replay log dir for P&L density stats (optional)")
    p.add_argument("--compact", action="store_true", help="Compact one-line output per ticker")
    p.add_argument("--timeline", action="store_true",
                   help="Print ASCII selection timeline for each ticker")
    p.add_argument("--feed", default="sip", help="Alpaca data feed (default: sip)")
    p.add_argument("--rebuild", action="store_true",
                   help="Ignore and overwrite the daily-rank cache (re-compute all days)")
    p.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                   help="Point-in-time date to evaluate (default: today)")
    return p.parse_args()


def main():
    args = parse_args()
    tickers = [t.upper() for t in args.tickers]

    today = date.today()
    as_of = date.fromisoformat(args.as_of) if args.as_of else today
    # Roll back to Friday if as_of lands on a weekend
    fetch_end = as_of - timedelta(days=max(0, as_of.weekday() - 4))
    # Only allow partial intraday bars when evaluating today's live session
    allow_intraday = fetch_end == today

    # We need lookback + wr_lookback + warmup days of bars
    total_cal_days = int((args.lookback + args.wr_lookback + _WARMUP_EXTRA) * 1.5)
    fetch_start = fetch_end - timedelta(days=total_cal_days)

    print(f"\nFetching 5-min bars ({fetch_start} → {fetch_end}) for {len(tickers)} tickers ...")
    feed = DataFeed(args.feed.lower()) if args.feed else None
    ticker_bars = fetch_bars(
        tickers, fetch_start, fetch_end, source="alpaca", feed=feed, allow_intraday=allow_intraday
    )

    # Build list of trading days present in the data
    all_trading_days = sorted({
        d.date() for df in ticker_bars.values() if not df.empty
        for d in df.index.normalize().unique()
    })
    # Use last `lookback` days as the evaluation window
    eval_days = all_trading_days[-args.lookback:]
    if not eval_days:
        print("No trading days found in fetched data.")
        sys.exit(1)

    today_eval = eval_days[-1]
    print(f"Evaluating {len(eval_days)} trading days ending {today_eval} ...")

    # Pre-group bars by date once — eliminates O(eval_days × tickers × lookback) DataFrame scans
    ticker_day_groups = {
        t: {d: df[df.index.date == d] for d in set(df.index.date)}
        for t, df in ticker_bars.items() if not df.empty
    }
    ticker_anchor_returns = _precompute_or_anchor_returns(
        ticker_day_groups, args.or_start, args.or_bars
    )

    # Load incremental daily-rank cache (skip if --rebuild)
    cache_path = _lifecycle_cache_path(tickers, args.or_start, args.or_bars, args.feed, args.wr_lookback)
    cached_daily_rank = {} if args.rebuild else _load_lifecycle_cache(cache_path)
    if args.rebuild:
        print("  [lifecycle cache] --rebuild: ignoring existing cache")
    elif cached_daily_rank:
        print(f"  [lifecycle cache] loaded {len(cached_daily_rank)} cached day(s) from {cache_path.name}")

    ticker_states, daily_rank = compute_lifecycle(
        ticker_bars, eval_days, args.top,
        args.or_start, args.or_bars, args.wr_lookback,
        cached_daily_rank=cached_daily_rank,
        ticker_anchor_returns=ticker_anchor_returns,
    )

    # Persist updated daily_rank (only settled past days — not today if market is open)
    from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import _is_cacheable
    saveable_rank = {d: v for d, v in daily_rank.items() if _is_cacheable(d)}
    _save_lifecycle_cache(cache_path, saveable_rank)

    # Optional log stats
    log_stats = {}
    if args.log_dir and os.path.isdir(args.log_dir):
        # Last 10 trading days
        log_days = eval_days[-10:]
        log_stats = _load_log_stats(args.log_dir, set(tickers), log_days)

    # Compute live regime confirmation from top-N picks
    daily_metrics = _build_daily_metrics_from_rank(
        ticker_bars, daily_rank, eval_days, args.or_start, args.or_bars, args.top
    )
    regime_state = _compute_regime_state(daily_metrics, today_eval)

    if args.timeline:
        print_streak_timeline(ticker_states, daily_rank, args.top, tickers, today_eval)

    print_dashboard(
        ticker_states, log_stats, args.top, today_eval, args.compact,
        regime_state=regime_state, n_metrics=len(daily_metrics),
    )


if __name__ == "__main__":
    main()
