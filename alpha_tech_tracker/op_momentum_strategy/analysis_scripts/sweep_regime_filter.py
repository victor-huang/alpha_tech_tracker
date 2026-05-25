"""
Sweep --regime-filter --regime-ma N for 2025 and 2026 YTD.
Base: --top 2 --weights 60 40 --window M1 09:30 1 --window A1 12:00 3
      --stop-pct 0.6 --stale-cut-mins 45 --stale-cut-threshold 0.75 --reversal --feed sip
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

REGIME_MA_VALUES = [3, 5, 8, 10, 13, 15, 20, 30, 50]

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
    plabel, eval_start, eval_end, regime_filter, regime_ma = args

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
        regime_filter=regime_filter,
        regime_ma=regime_ma,
        feed=DataFeed.SIP,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, WINDOWS, INITIAL_CAPITAL, weights, N)

    active   = [r for r in trade_rows if not r.get("skipped")]
    pnl      = sum(r.get("cap_pnl", 0.0) for r in active)
    n_trades = len(active)
    n_wins   = sum(1 for r in active if r.get("pnl", 0) > 0)
    wr       = n_wins / n_trades * 100 if n_trades else 0.0
    return pnl, n_trades, wr


def main():
    # baseline (no filter) + one task per regime_ma per period
    tasks = []
    for plabel, pstart, pend in PERIODS:
        tasks.append((plabel, pstart, pend, False, 0))       # baseline
        for ma in REGIME_MA_VALUES:
            tasks.append((plabel, pstart, pend, True, ma))

    total = len(tasks)
    print(f"Running {total} tasks (ProcessPoolExecutor, 8 workers)...\n", flush=True)

    results = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_one, t): t for t in tasks}
        for fut in as_completed(futures):
            t = futures[fut]
            plabel, _, _, regime_filter, ma = t
            key = (plabel, ma if regime_filter else "base")
            try:
                results[key] = fut.result()
            except Exception as exc:
                results[key] = (float("nan"), 0, 0.0)
                print(f"  ERROR {key}: {exc}", flush=True)
            completed += 1
            if completed % 4 == 0:
                print(f"  {completed}/{total} done...", flush=True)

    print(f"  {completed}/{total} done.\n", flush=True)

    for plabel, pstart, pend in PERIODS:
        base_pnl, base_trades, base_wr = results.get((plabel, "base"), (0, 0, 0.0))
        print("=" * 72)
        print(f"  {plabel}  |  baseline (no filter): ${base_pnl:+,.2f}  |  {base_trades} trades  |  WR {base_wr:.1f}%")
        print("=" * 72)
        print(f"  {'MA':>4}  {'P&L':>11}  {'vs base':>10}  {'Trades':>7}  {'WR':>6}  {'Skipped':>8}")
        print("  " + "─" * 55)
        for ma in REGIME_MA_VALUES:
            pnl, trades, wr = results.get((plabel, ma), (float("nan"), 0, 0.0))
            delta   = pnl - base_pnl
            skipped = base_trades - trades
            print(f"  {ma:>4}  ${pnl:>+10,.2f}  ${delta:>+9,.2f}  {trades:>7}  {wr:>5.1f}%  {skipped:>8}")
        print()


if __name__ == "__main__":
    main()
