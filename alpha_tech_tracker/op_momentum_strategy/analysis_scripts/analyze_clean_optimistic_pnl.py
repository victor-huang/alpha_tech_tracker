"""
analyze_clean_optimistic_pnl.py

Decomposes the optimistic-mode P&L into:
  - Selection benefit (real): what the optimistic selector's picks would have
    produced under realistic 5-min bar-close fills (same as live engine)
  - Fill artifact (noise): the inflation from filling stop/fallback exits at
    the stop level instead of the bar close

Pipeline:
  1. Run OPTIMISTIC selector backtest (exit_at_bar_close=False).  This gives
     the inflated trade rows where the SELECTOR has chosen "better" tickers.
  2. For each primary or sub-trade leg whose exit_reason is hard_stop or
     fallback_20pct, look up the 5-min exit bar's CLOSE price and substitute
     it for the optimistic stop-level fill.
  3. Recompute cap_pnl per trade.  Sum per year.

Output: per-year decomposition of:
  - Default 5-min P&L         (= live engine today)
  - Clean optimistic P&L      (= optimistic picks, realistic fills) ← the "real" upper bound
  - Raw optimistic P&L         (= optimistic picks + optimistic fills) ← what the inflated backtest shows

Selection benefit  = Clean opt − Default
Fill artifact noise = Raw opt − Clean opt
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    INITIAL_CAPITAL,
    _apply_capital_flow,
    _parse_weights,
    run_selector_backtest,
)

WINDOWS = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 3, "group": "first", "split_pct": 1.0},
    {"label": "A1", "opening_start": "10:00", "opening_bars": 3, "group": "sequential", "split_pct": 1.0},
    {"label": "A2", "opening_start": "11:45", "opening_bars": 2, "group": "sequential", "split_pct": 1.0},
    {"label": "A3", "opening_start": "13:15", "opening_bars": 1, "group": "sequential", "split_pct": 1.0},
    {"label": "A4", "opening_start": "15:15", "opening_bars": 2, "group": "sequential", "split_pct": 1.0},
]

DST_2018 = [(date(2018, 3, 11), date(2018, 11, 4)),
            (date(2019, 3, 10), date(2019, 11, 3)),
            (date(2020, 3, 8),  date(2020, 11, 1)),
            (date(2021, 3, 14), date(2021, 11, 7)),
            (date(2022, 3, 13), date(2022, 11, 6)),
            (date(2023, 3, 12), date(2023, 11, 5)),
            (date(2024, 3, 10), date(2024, 11, 3))]


def _et_offset(d: date) -> int:
    for start, end in DST_2018:
        if start <= d < end:
            return -4
    return -5


def _et_min_to_utc(d: date, et_min: int) -> datetime:
    off = _et_offset(d)
    h, m = divmod(et_min, 60)
    return datetime(d.year, d.month, d.day, h - off, m, tzinfo=timezone.utc)


SUB_LEGS = [("rev", "BULLISH"), ("br", "BEARISH"), ("bru", "BULLISH")]


def _primary_exit_bar_close_lookup(row, bars_by_ticker):
    """Return the 5-min exit bar close for the primary trade, or None if not found."""
    ticker = row["ticker"]
    df = bars_by_ticker.get(ticker)
    if df is None or df.empty:
        return None
    or_close = row["or_close_min"]
    exit_min_end = or_close + (row["bars_held"] + 1) * 5
    bar_start_utc = _et_min_to_utc(row["date"], exit_min_end - 5)
    try:
        bar = df.loc[df.index == bar_start_utc]
        if bar.empty:
            return None
        return float(bar["Close"].iloc[0])
    except Exception:
        return None


def _sub_exit_bar_close_lookup(row, prefix, bars_by_ticker):
    ticker = row["ticker"]
    df = bars_by_ticker.get(ticker)
    if df is None or df.empty:
        return None
    or_close = row["or_close_min"]
    primary_bars = row.get("bars_held", 0)
    entry_idx = row.get(f"{prefix}_entry_idx", 0)
    sub_bars = row.get(f"{prefix}_bars_held", 0)
    sub_entry_min = or_close + (primary_bars + entry_idx + 2) * 5
    sub_exit_min_end = sub_entry_min + (sub_bars + 1) * 5
    bar_start_utc = _et_min_to_utc(row["date"], sub_exit_min_end - 5)
    try:
        bar = df.loc[df.index == bar_start_utc]
        if bar.empty:
            return None
        return float(bar["Close"].iloc[0])
    except Exception:
        return None


def _pnl(entry, exit_, sig):
    return (exit_ - entry) if sig == "BULLISH" else (entry - exit_)


def _row_cap_pnl_realistic(row, bars_by_ticker, noise_log=None):
    """Recompute cap_pnl using realistic (5-min bar close) fills on stop/fallback exits.
    If noise_log is provided, append per-trade noise details for each stop/fallback leg.
    """
    slot_cap = row.get("slot_capital", 0.0)
    if not slot_cap:
        return 0.0
    entry = row["entry_price"]
    sig = row["signal"]

    # Primary leg
    if row["exit_reason"] in ("hard_stop", "fallback_20pct"):
        new_exit = _primary_exit_bar_close_lookup(row, bars_by_ticker)
        primary_exit = new_exit if new_exit is not None else row["exit_price"]
        if noise_log is not None:
            opt_exit = row["exit_price"]
            opt_pnl = _pnl(entry, opt_exit, sig)
            opt_cap = (slot_cap / entry) * opt_pnl
            real_cap = (slot_cap / entry) * _pnl(entry, primary_exit, sig)
            noise_log.append({
                "date": str(row["date"]), "win": row["window"], "ticker": row["ticker"],
                "sig": sig, "leg": "primary", "reason": row["exit_reason"],
                "entry": entry, "real_exit": primary_exit, "opt_exit": opt_exit,
                "noise_per_share": opt_exit - primary_exit if sig == "BULLISH" else primary_exit - opt_exit,
                "noise_cap": opt_cap - real_cap,
                "bars_held": row.get("bars_held", 0),
            })
    else:
        primary_exit = row["exit_price"]
    primary_pnl = _pnl(entry, primary_exit, sig)
    cap_pnl = (slot_cap / entry) * primary_pnl

    # Sub-trade legs
    for prefix, sub_sig in SUB_LEGS:
        ep = row.get(f"{prefix}_entry_price", 0) or 0
        if not ep:
            continue
        if row.get(f"{prefix}_exit_reason", "") in ("hard_stop", "fallback_20pct"):
            new_sub_exit = _sub_exit_bar_close_lookup(row, prefix, bars_by_ticker)
            sub_exit = new_sub_exit if new_sub_exit is not None else row[f"{prefix}_exit_price"]
        else:
            sub_exit = row[f"{prefix}_exit_price"]
        sub_pnl = _pnl(ep, sub_exit, sub_sig)
        cap_pnl += (slot_cap / ep) * sub_pnl

    return cap_pnl


def run_year(start_str: str, end_str: str, min_hold_bars: int = 1):
    eval_start = date.fromisoformat(start_str)
    eval_end = date.fromisoformat(end_str)
    n = 2
    weights = _parse_weights(None, n)

    print(f"\n=== {eval_start.year} ({eval_start} → {eval_end}) ===")

    # Default mode
    print(" Running default-mode backtest...")
    default_rows, _, _ = run_selector_backtest(
        n=n, tickers=list(DEFAULT_TICKERS),
        eval_start=eval_start, eval_end=eval_end,
        windows=WINDOWS, feed=DataFeed.SIP, source="alpaca",
        enable_reversal=True, enable_bearish_reentry=True, enable_bullish_reentry=True,
        min_hold_bars=min_hold_bars, exit_at_bar_close=True,
    )
    _apply_capital_flow(default_rows, WINDOWS, INITIAL_CAPITAL, weights, n,
                        morning_split=[1.0], compound=False, enable_doubledown=False)

    # Optimistic mode
    print(" Running optimistic-mode backtest...")
    opt_rows, _, _ = run_selector_backtest(
        n=n, tickers=list(DEFAULT_TICKERS),
        eval_start=eval_start, eval_end=eval_end,
        windows=WINDOWS, feed=DataFeed.SIP, source="alpaca",
        enable_reversal=True, enable_bearish_reentry=True, enable_bullish_reentry=True,
        min_hold_bars=min_hold_bars, exit_at_bar_close=False,
    )
    _apply_capital_flow(opt_rows, WINDOWS, INITIAL_CAPITAL, weights, n,
                        morning_split=[1.0], compound=False, enable_doubledown=False)

    # Fetch 5-min bars for all optimistic picks (cached)
    tickers_used = sorted({r["ticker"] for r in opt_rows if not r.get("skipped")})
    print(f" Fetching 5-min bars for {len(tickers_used)} tickers...")
    bars = fetch_bars(tickers_used, eval_start, eval_end, source="alpaca", feed=DataFeed.SIP)

    # Compute clean-optimistic cap P&L
    print(" Re-filling optimistic trades with realistic fills...")
    default_pnl = sum(r.get("cap_pnl", 0) for r in default_rows if not r.get("skipped"))
    raw_opt_pnl = sum(r.get("cap_pnl", 0) for r in opt_rows if not r.get("skipped"))
    noise_log = []
    clean_opt_pnl = sum(
        _row_cap_pnl_realistic(r, bars, noise_log=noise_log)
        for r in opt_rows if not r.get("skipped")
    )

    selection_benefit = clean_opt_pnl - default_pnl
    fill_artifact = raw_opt_pnl - clean_opt_pnl

    print(f"  Default 5-min P&L     : {default_pnl:>+12.2f}")
    print(f"  Clean optimistic P&L  : {clean_opt_pnl:>+12.2f}  (= optimistic picks, realistic fills)")
    print(f"  Raw optimistic P&L    : {raw_opt_pnl:>+12.2f}  (= optimistic picks + optimistic fills)")
    print(f"  --- decomposition ---")
    print(f"  Selection benefit     : {selection_benefit:>+12.2f}  (clean opt − default)")
    print(f"  Fill artifact (noise) : {fill_artifact:>+12.2f}  (raw opt − clean opt)")
    # Per-trade noise size stats
    noise_caps = [e["noise_cap"] for e in noise_log]
    pos = [v for v in noise_caps if v > 0]
    neg = [v for v in noise_caps if v < 0]
    if noise_caps:
        import statistics
        print(f"  Per-trade noise (primary stop/fallback legs only):")
        print(f"    N={len(noise_caps)}  positive={len(pos)}  negative={len(neg)}  zero={len(noise_caps)-len(pos)-len(neg)}")
        print(f"    mean={statistics.mean(noise_caps):+.2f}  median={statistics.median(noise_caps):+.2f}  "
              f"max={max(noise_caps):+.2f}  min={min(noise_caps):+.2f}")
    return {
        "year": eval_start.year,
        "default_pnl": default_pnl,
        "clean_opt_pnl": clean_opt_pnl,
        "raw_opt_pnl": raw_opt_pnl,
        "selection_benefit": selection_benefit,
        "fill_artifact": fill_artifact,
        "n_noise_trades": len(noise_caps),
        "mean_noise": statistics.mean(noise_caps) if noise_caps else 0,
        "median_noise": statistics.median(noise_caps) if noise_caps else 0,
        "max_noise": max(noise_caps) if noise_caps else 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-hold-bars", type=int, default=1)
    args = parser.parse_args()
    print(f"\n*** Running with min_hold_bars={args.min_hold_bars} ***\n")
    years = [
        ("2018-01-02", "2018-12-31"),
        ("2019-01-02", "2019-12-31"),
        ("2020-01-02", "2020-12-31"),
        ("2021-01-04", "2021-12-31"),
        ("2022-01-03", "2022-12-30"),
        ("2023-01-03", "2023-12-29"),
        ("2024-01-02", "2024-12-31"),
    ]
    results = []
    for s, e in years:
        try:
            results.append(run_year(s, e, min_hold_bars=args.min_hold_bars))
        except Exception as exc:
            print(f" ERROR for {s}: {exc}")
            raise

    print("\n" + "━" * 100)
    print(f"  {'Year':<6} {'Default $':>12} {'Clean Opt $':>13} {'Raw Opt $':>12} "
          f"{'Selection $':>13} {'Fill artifact $':>17}")
    print("━" * 100)
    totals = defaultdict(float)
    for r in results:
        print(f"  {r['year']:<6} {r['default_pnl']:>+12.2f} {r['clean_opt_pnl']:>+13.2f} "
              f"{r['raw_opt_pnl']:>+12.2f} {r['selection_benefit']:>+13.2f} "
              f"{r['fill_artifact']:>+17.2f}")
        for k in ("default_pnl", "clean_opt_pnl", "raw_opt_pnl",
                  "selection_benefit", "fill_artifact"):
            totals[k] += r[k]
    print("━" * 100)
    print(f"  {'7-yr':<6} {totals['default_pnl']:>+12.2f} {totals['clean_opt_pnl']:>+13.2f} "
          f"{totals['raw_opt_pnl']:>+12.2f} {totals['selection_benefit']:>+13.2f} "
          f"{totals['fill_artifact']:>+17.2f}")
    print("━" * 100)

    # Per-year noise size summary
    print(f"\n  Per-year primary-trade noise stats (only primary legs with hard_stop/fallback exits):")
    print(f"  {'Year':<6} {'N trades':>9} {'Mean $':>10} {'Median $':>10} {'Max $':>10}")
    for r in results:
        print(f"  {r['year']:<6} {r['n_noise_trades']:>9} "
              f"{r['mean_noise']:>+10.2f} {r['median_noise']:>+10.2f} {r['max_noise']:>+10.2f}")


if __name__ == "__main__":
    main()
