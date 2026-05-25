"""
Sweep --reversal-max-bars X for 2025 and 2026 YTD.
Base: --top 2 --weights 60 40 --window M1 09:30 1 --window A1 12:00 3
      --stop-pct 0.6 --stale-cut-mins 45 --stale-cut-threshold 0.75 --reversal --feed sip
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

MAX_BARS_VALUES = list(range(1, 19))  # 1 through 18

PERIODS = [
    ("2025",     date(2025, 1, 1), date(2025, 12, 31)),
    ("2026 YTD", date(2026, 1, 1), date(2026, 5, 15)),
]

WINDOWS = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 1},
    {"label": "A1", "opening_start": "12:00", "opening_bars": 3},
]
N = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0


def _run_one(args):
    plabel, eval_start, eval_end, reversal_max_bars = args

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS, _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    trade_rows, _, _ = run_selector_backtest(
        n=N,
        tickers=DEFAULT_TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOWS,
        stop_pct=0.60,
        stale_cut_mins=45,
        stale_cut_threshold=0.75,
        enable_reversal=True,
        reversal_max_bars_held=reversal_max_bars,
        feed=DataFeed.SIP,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, WINDOWS, INITIAL_CAPITAL, weights, N)

    active   = [r for r in trade_rows if not r.get("skipped")]
    total_n  = len(active)
    total_wins = sum(1 for r in active if r.get("pnl", 0) > 0)
    total_wr = total_wins / total_n * 100 if total_n else 0.0
    total_pnl = sum(r.get("cap_pnl", 0.0) for r in active)

    return total_pnl, total_n, total_wr


def main():
    tasks = [
        (plabel, pstart, pend, mb)
        for plabel, pstart, pend in PERIODS
        for mb in MAX_BARS_VALUES
    ]
    total = len(tasks)
    print(f"Running {total} tasks (ProcessPoolExecutor, 8 workers)...\n", flush=True)

    results = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_one, t): t for t in tasks}
        for fut in as_completed(futures):
            t = futures[fut]
            plabel, _, _, mb = t
            try:
                results[(plabel, mb)] = fut.result()
            except Exception as exc:
                results[(plabel, mb)] = (float("nan"), 0, 0.0)
                print(f"  ERROR {t}: {exc}", flush=True)
            completed += 1
            if completed % 4 == 0:
                print(f"  {completed}/{total} done...", flush=True)

    print(f"  {completed}/{total} done.\n", flush=True)

    for plabel, pstart, pend in PERIODS:
        print("=" * 60)
        print(f"  {plabel}  |  base: --reversal --reversal-max-bars X  (current default = 3)")
        print("=" * 60)
        print(f"  {'MaxBars':>7}  {'Total P&L':>11}  {'Trades':>7}  {'WR':>6}")
        print("  " + "─" * 42)

        rows = []
        for mb in MAX_BARS_VALUES:
            rows.append((mb,) + results.get((plabel, mb), (float("nan"), 0, 0.0)))

        best_pnl = max((r[1] for r in rows if r[1] == r[1]), default=0)

        for mb, total_pnl, total_n, total_wr in rows:
            marker = "  ◄ current" if mb == 3 else ("  ◄ best" if total_pnl == best_pnl and mb != 3 else "")
            print(f"  {mb:>7}  ${total_pnl:>+10,.2f}  {total_n:>7}  {total_wr:>5.1f}%{marker}")
        print()


if __name__ == "__main__":
    main()
