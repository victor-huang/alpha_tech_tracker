"""
Sweep --stale-cut-mins and --stale-cut-threshold for 2025 and 2026 YTD.
Base config: --top 2 --weights 60 40 --window M1 09:30 1 --window A1 12:00 3
             --stop-pct 0.6 --feed sip --reversal

Uses ProcessPoolExecutor for true multi-core parallelism (avoids GIL on CPU-bound work).
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

from alpaca.data.enums import DataFeed

STALE_CUT_MINS_VALUES   = [20, 25, 30, 35, 40, 45, 50, 55, 60]
STALE_CUT_THRESH_VALUES = [0.25, 0.50, 0.75, 1.00]

PERIODS = [
    ("2025",     date(2025, 1, 1),  date(2025, 12, 31)),
    ("2026 YTD", date(2026, 1, 1),  date(2026, 5, 15)),
]

WINDOWS = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 1},
    {"label": "A1", "opening_start": "12:00", "opening_bars": 3},
]

N = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0


def _run_one(args):
    """Top-level function (required for ProcessPoolExecutor pickling)."""
    period_label, eval_start, eval_end, mins, thresh = args

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS,
        _apply_capital_flow,
        _parse_weights,
        run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    trade_rows, _, _ = run_selector_backtest(
        n=N,
        tickers=DEFAULT_TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOWS,
        stop_pct=0.60,
        stale_cut_mins=mins,
        stale_cut_threshold=thresh,
        enable_reversal=True,
        feed=DataFeed.SIP,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, WINDOWS, INITIAL_CAPITAL, weights, N)
    active = [r for r in trade_rows if not r.get("skipped")]
    total_pnl = sum(r.get("cap_pnl", 0.0) for r in active)
    n_trades  = len(active)
    n_wins    = sum(1 for r in active if r.get("pnl", 0) > 0)
    wr        = n_wins / n_trades * 100 if n_trades else 0.0
    return total_pnl, n_trades, wr


def main():
    tasks = []
    for plabel, pstart, pend in PERIODS:
        tasks.append((plabel, pstart, pend, 0, 0.0))  # baseline
        for mins, thresh in product(STALE_CUT_MINS_VALUES, STALE_CUT_THRESH_VALUES):
            tasks.append((plabel, pstart, pend, mins, thresh))

    total = len(tasks)
    print(f"Running {total} tasks across {total} combos with ProcessPoolExecutor (8 workers)...\n", flush=True)

    results = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_one, task): task for task in tasks}
        for fut in as_completed(futures):
            plabel, pstart, pend, mins, thresh = futures[fut]
            try:
                results[(plabel, mins, thresh)] = fut.result()
            except Exception as exc:
                results[(plabel, mins, thresh)] = (float("nan"), 0, 0.0)
                print(f"  ERROR ({plabel}, {mins}, {thresh}): {exc}", flush=True)
            completed += 1
            if completed % 8 == 0:
                print(f"  {completed}/{total} done...", flush=True)

    print(f"  {completed}/{total} done.\n", flush=True)

    # ── Print results ──────────────────────────────────────────────────────
    for plabel, pstart, pend in PERIODS:
        base_pnl, base_trades, base_wr = results.get((plabel, 0, 0.0), (0, 0, 0.0))
        print("=" * 80)
        print(f"  {plabel}  |  baseline (no stale-cut): ${base_pnl:+,.2f}  |  {base_trades} trades  |  WR {base_wr:.1f}%")
        print("=" * 80)
        print(f"  {'mins':>5}  {'thresh':>7}  {'P&L':>11}  {'vs base':>10}  {'Trades':>7}  {'WR':>6}")
        print("  " + "─" * 55)

        rows = []
        for mins in STALE_CUT_MINS_VALUES:
            for thresh in STALE_CUT_THRESH_VALUES:
                pnl, trades, wr = results.get((plabel, mins, thresh), (float("nan"), 0, 0.0))
                rows.append((mins, thresh, pnl, pnl - base_pnl, trades, wr))

        rows.sort(key=lambda x: x[2], reverse=True)

        for mins, thresh, pnl, delta, trades, wr in rows:
            marker = " ◄ current" if (mins == 45 and abs(thresh - 0.75) < 0.001) else ""
            print(
                f"  {mins:>5}  {thresh:>7.2f}  ${pnl:>+10,.2f}  ${delta:>+9,.2f}  {trades:>7}  {wr:>5.1f}%{marker}"
            )
        print()


if __name__ == "__main__":
    main()
