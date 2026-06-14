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
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from alpaca.data.enums import DataFeed
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _DEFAULT_OR_BARS,
    _DEFAULT_OR_START,
    _rank_tickers_by_eod_win_rate,
)

_LOOKBACK_WIN_RATE = 20
_TREND_SHORT = 10
_WARMUP_EXTRA = 10
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

def compute_lifecycle(ticker_bars, trading_days, top_n, or_start, or_bars, lookback_wr):
    """
    For each trading day in `trading_days`, rank the pool and record which tickers
    were in the top-N. Returns per-ticker state as of the last day.

    ticker_bars : {ticker: df_5m}  (must cover at least lookback_wr+len(trading_days) days)
    trading_days: list of date objects, chronological, representing the window to evaluate
    """
    daily_rank = {}  # date -> [ordered ticker list]

    for target in trading_days:
        ranked = _rank_tickers_by_eod_win_rate(
            ticker_bars, target, or_start, or_bars, lookback_wr
        )
        daily_rank[target] = [t for t, _ in ranked]

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

        # Win rates on today and trend
        hist_today = None
        hist_prior = None
        if ticker in ticker_bars and not ticker_bars[ticker].empty:
            from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
                _compute_hold_history,
            )
            hist_today = _compute_hold_history(ticker_bars[ticker], today, or_start, or_bars, lookback_wr)
            # Prior window: 10 days ago
            trend_anchor = all_days[max(0, len(all_days) - _TREND_SHORT - 1)]
            hist_prior = _compute_hold_history(ticker_bars[ticker], trend_anchor, or_start, or_bars, lookback_wr)

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


def print_dashboard(ticker_states, log_stats, top_n, today, compact):
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
            f"  {'Ticker':<7} {'Rank':>5} {'15mWR':>6} {'EOD_WR':>7} {'Med%':>6} "
            f"{'Trend':>7} {'Streak':>8}  {'Phase':<14}  {'Detail'}"
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
    return p.parse_args()


def main():
    args = parse_args()
    tickers = [t.upper() for t in args.tickers]

    today = date.today()
    # We need lookback + wr_lookback + warmup days of bars
    total_cal_days = int((args.lookback + args.wr_lookback + _WARMUP_EXTRA) * 1.5)
    fetch_start = today - timedelta(days=total_cal_days)
    fetch_end = today

    print(f"\nFetching 5-min bars ({fetch_start} → {fetch_end}) for {len(tickers)} tickers ...")
    feed = DataFeed(args.feed.lower()) if args.feed else None
    # allow_intraday=True lets fetch_bars include today's partial bars when market is open
    ticker_bars = fetch_bars(
        tickers, fetch_start, fetch_end, source="alpaca", feed=feed, allow_intraday=True
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

    ticker_states, daily_rank = compute_lifecycle(
        ticker_bars, eval_days, args.top,
        args.or_start, args.or_bars, args.wr_lookback,
    )

    # Optional log stats
    log_stats = {}
    if args.log_dir and os.path.isdir(args.log_dir):
        # Last 10 trading days
        log_days = eval_days[-10:]
        log_stats = _load_log_stats(args.log_dir, set(tickers), log_days)

    if args.timeline:
        print_streak_timeline(ticker_states, daily_rank, args.top, tickers, today_eval)

    print_dashboard(ticker_states, log_stats, args.top, today_eval, args.compact)


if __name__ == "__main__":
    main()
