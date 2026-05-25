"""
Run BOTH default-mode (exit_at_bar_close=True) and optimistic-mode
(exit_at_bar_close=False) backtests for 2024, then for each trade set count
"big winners" (gain >= 0.5%) — distinguishing between:
  - genuine big winners (exit_reason NOT in {hard_stop, fallback_20pct}) —
    these gains are independent of the fill model
  - stop-fill big winners (exit_reason IN {hard_stop, fallback_20pct}) — these
    are inflated by the optimistic fill model
"""

import argparse
from collections import defaultdict
from datetime import date

from alpaca.data.enums import DataFeed

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

THRESHOLD = 0.005  # +0.5%
NON_STOP_REASONS = {"trailing_stop_ma20", "trailing_stop_ma50", "end_of_day",
                    "max_loss", "stale_cut"}


def run_mode(eval_start: date, eval_end: date, optimistic: bool):
    n = 2
    weights = _parse_weights(None, n)
    trade_rows, _, _ = run_selector_backtest(
        n=n,
        tickers=list(DEFAULT_TICKERS),
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOWS,
        feed=DataFeed.SIP,
        source="alpaca",
        enable_reversal=True,
        enable_bearish_reentry=True,
        enable_bullish_reentry=True,
        min_hold_bars=1,
        exit_at_bar_close=not optimistic,
    )
    _apply_capital_flow(
        trade_rows, WINDOWS, INITIAL_CAPITAL, weights, n,
        morning_split=[1.0], compound=False, enable_doubledown=False,
    )
    return [r for r in trade_rows if not r.get("skipped")]


def pnl_pct(entry, exit_, sig):
    return (exit_ - entry) / entry if sig == "BULLISH" else (entry - exit_) / entry


SUB_LEGS = [("rev", "BULLISH"), ("br", "BEARISH"), ("bru", "BULLISH")]


def _new_stats():
    return {
        "total_legs": 0,
        "big_winners_total": 0,
        "big_winners_non_stop": 0,
        "big_winners_stop_fill": 0,
        "cap_pnl_big_total": 0.0,
        "cap_pnl_big_non_stop": 0.0,
        "cap_pnl_big_stop_fill": 0.0,
        "primary_big_non_stop": 0,
        "sub_big_non_stop": 0,
    }


def classify(rows, threshold):
    """Count primary AND each sub-trade leg (REV/BR/BRU) separately as
    individual "trades" for big-winner accounting. Each leg gets its own
    pnl_pct, cap_pnl, and exit_reason.
    """
    stats = _new_stats()
    by_window = defaultdict(_new_stats)

    for r in rows:
        slot_cap = r.get("slot_capital", 0.0)
        if not slot_cap:
            continue
        entry_price = r["entry_price"]
        win = r["window"]

        # ── Primary leg ──
        sig = r["signal"]
        pct = pnl_pct(entry_price, r["exit_price"], sig)
        reason = r["exit_reason"]
        is_stop = reason in ("hard_stop", "fallback_20pct")
        prim_pnl = (r["exit_price"] - entry_price) if sig == "BULLISH" else (entry_price - r["exit_price"])
        prim_cap = (slot_cap / entry_price) * prim_pnl

        for s in (stats, by_window[win]):
            s["total_legs"] += 1
            if pct >= threshold:
                s["big_winners_total"] += 1
                s["cap_pnl_big_total"] += prim_cap
                if is_stop:
                    s["big_winners_stop_fill"] += 1
                    s["cap_pnl_big_stop_fill"] += prim_cap
                else:
                    s["big_winners_non_stop"] += 1
                    s["cap_pnl_big_non_stop"] += prim_cap
                    s["primary_big_non_stop"] += 1

        # ── Sub-trade legs (REV / BR / BRU) ──
        for prefix, sub_sig in SUB_LEGS:
            ep = r.get(f"{prefix}_entry_price", 0) or 0
            if not ep:
                continue
            ex = r.get(f"{prefix}_exit_price", 0)
            spct = pnl_pct(ep, ex, sub_sig)
            sreason = r.get(f"{prefix}_exit_reason", "")
            s_is_stop = sreason in ("hard_stop", "fallback_20pct")
            sub_pnl = (ex - ep) if sub_sig == "BULLISH" else (ep - ex)
            sub_cap = (slot_cap / ep) * sub_pnl

            for s in (stats, by_window[win]):
                s["total_legs"] += 1
                if spct >= threshold:
                    s["big_winners_total"] += 1
                    s["cap_pnl_big_total"] += sub_cap
                    if s_is_stop:
                        s["big_winners_stop_fill"] += 1
                        s["cap_pnl_big_stop_fill"] += sub_cap
                    else:
                        s["big_winners_non_stop"] += 1
                        s["cap_pnl_big_non_stop"] += sub_cap
                        s["sub_big_non_stop"] += 1

    return stats, by_window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2024-12-31")
    args = parser.parse_args()
    es = date.fromisoformat(args.start)
    ee = date.fromisoformat(args.end)

    print(f"\n=== Default backtest ({es} → {ee}) ===")
    default_rows = run_mode(es, ee, optimistic=False)
    print(f"Default active rows: {len(default_rows)}")

    print(f"\n=== Optimistic backtest ({es} → {ee}) ===")
    opt_rows = run_mode(es, ee, optimistic=True)
    print(f"Optimistic active rows: {len(opt_rows)}")

    d_stats, d_by_win = classify(default_rows, THRESHOLD)
    o_stats, o_by_win = classify(opt_rows, THRESHOLD)

    # Same-trade overlap: count (date, window, rank, ticker) keys shared
    def key(r):
        return (str(r["date"]), r["window"], r["rank"], r["ticker"])
    d_keys = {key(r) for r in default_rows if r.get("slot_capital")}
    o_keys = {key(r) for r in opt_rows if r.get("slot_capital")}
    shared = d_keys & o_keys
    only_default = d_keys - o_keys
    only_opt = o_keys - d_keys

    print()
    print("━" * 100)
    print(f"  Comparison: gain ≥ {THRESHOLD*100:.1f}% big-winner counts, 2024")
    print("━" * 100)
    print(f"  {'Metric':<48} {'Default':>14} {'Optimistic':>14} {'Δ (opt-def)':>14}")
    print("─" * 100)
    print(f"  {'Total trade legs (primary + REV/BR/BRU)':<48} "
          f"{d_stats['total_legs']:>14} {o_stats['total_legs']:>14} "
          f"{o_stats['total_legs']-d_stats['total_legs']:>+14}")
    print(f"  {'Big winners (any exit, ≥0.5%)':<48} "
          f"{d_stats['big_winners_total']:>14} {o_stats['big_winners_total']:>14} "
          f"{o_stats['big_winners_total']-d_stats['big_winners_total']:>+14}")
    print(f"  {'  └ genuine (non hard_stop/fallback)':<48} "
          f"{d_stats['big_winners_non_stop']:>14} {o_stats['big_winners_non_stop']:>14} "
          f"{o_stats['big_winners_non_stop']-d_stats['big_winners_non_stop']:>+14}")
    print(f"  {'  └ stop-fill (artifact-prone)':<48} "
          f"{d_stats['big_winners_stop_fill']:>14} {o_stats['big_winners_stop_fill']:>14} "
          f"{o_stats['big_winners_stop_fill']-d_stats['big_winners_stop_fill']:>+14}")
    print()
    print(f"  {'Cap $ from big winners (any exit)':<48} "
          f"{d_stats['cap_pnl_big_total']:>+14.2f} {o_stats['cap_pnl_big_total']:>+14.2f} "
          f"{o_stats['cap_pnl_big_total']-d_stats['cap_pnl_big_total']:>+14.2f}")
    print(f"  {'  └ from genuine big winners':<48} "
          f"{d_stats['cap_pnl_big_non_stop']:>+14.2f} {o_stats['cap_pnl_big_non_stop']:>+14.2f} "
          f"{o_stats['cap_pnl_big_non_stop']-d_stats['cap_pnl_big_non_stop']:>+14.2f}")
    print(f"  {'  └ from stop-fill big winners':<48} "
          f"{d_stats['cap_pnl_big_stop_fill']:>+14.2f} {o_stats['cap_pnl_big_stop_fill']:>+14.2f} "
          f"{o_stats['cap_pnl_big_stop_fill']-d_stats['cap_pnl_big_stop_fill']:>+14.2f}")
    print()
    print(f"  {'Pick overlap':<48} {len(shared):>14}")
    print(f"  {'Picks only in default':<48} {len(only_default):>14}")
    print(f"  {'Picks only in optimistic':<48} {len(only_opt):>14}")
    print("━" * 100)

    # Genuine big winners on picks UNIQUE to each mode (primary + sub-trade legs)
    def big_legs_on_unique(rows, keys):
        results = []
        for r in rows:
            if key(r) not in keys:
                continue
            slot_cap = r.get("slot_capital", 0.0)
            if not slot_cap:
                continue
            entry_price = r["entry_price"]
            # primary
            if r["exit_reason"] not in ("hard_stop", "fallback_20pct"):
                p = pnl_pct(entry_price, r["exit_price"], r["signal"])
                if p >= THRESHOLD:
                    pnl = (r["exit_price"] - entry_price) if r["signal"] == "BULLISH" else (entry_price - r["exit_price"])
                    results.append({"cap": (slot_cap / entry_price) * pnl})
            # subs
            for prefix, sub_sig in SUB_LEGS:
                ep = r.get(f"{prefix}_entry_price", 0) or 0
                if not ep:
                    continue
                if r.get(f"{prefix}_exit_reason", "") in ("hard_stop", "fallback_20pct"):
                    continue
                ex = r.get(f"{prefix}_exit_price", 0)
                sp = pnl_pct(ep, ex, sub_sig)
                if sp >= THRESHOLD:
                    sub_pnl = (ex - ep) if sub_sig == "BULLISH" else (ep - ex)
                    results.append({"cap": (slot_cap / ep) * sub_pnl})
        return results

    d_unique_big = big_legs_on_unique(default_rows, only_default)
    o_unique_big = big_legs_on_unique(opt_rows, only_opt)

    print()
    print(f"  Genuine big winners (non hard_stop/fallback, ≥0.5%) on UNIQUE picks (primary + sub-legs):")
    print(f"    Only in default-mode picks: {len(d_unique_big)} legs, "
          f"cap P&L = {sum(r['cap'] for r in d_unique_big):+,.2f}")
    print(f"    Only in optimistic-mode picks: {len(o_unique_big)} legs, "
          f"cap P&L = {sum(r['cap'] for r in o_unique_big):+,.2f}")
    print(f"    Net advantage to OPTIMISTIC picks: "
          f"{len(o_unique_big) - len(d_unique_big):+d} legs, "
          f"{sum(r['cap'] for r in o_unique_big) - sum(r['cap'] for r in d_unique_big):+,.2f}")

    print()
    print(f"  Per-window genuine big-winner counts (≥0.5%, non-stop exits):")
    print(f"  {'Win':<4} {'Default #':>10} {'Opt #':>10} {'Δ':>8}  "
          f"{'Default $':>12} {'Opt $':>12} {'Δ $':>10}")
    for w in sorted(set(d_by_win) | set(o_by_win)):
        d = d_by_win[w]
        o = o_by_win[w]
        print(
            f"  {w:<4} {d['big_winners_non_stop']:>10} {o['big_winners_non_stop']:>10} "
            f"{o['big_winners_non_stop']-d['big_winners_non_stop']:>+8} "
            f"{d['cap_pnl_big_non_stop']:>+12.2f} {o['cap_pnl_big_non_stop']:>+12.2f} "
            f"{o['cap_pnl_big_non_stop']-d['cap_pnl_big_non_stop']:>+10.2f}"
        )


if __name__ == "__main__":
    main()
