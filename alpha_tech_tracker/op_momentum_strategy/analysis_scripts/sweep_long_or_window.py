"""
Sweep long opening-range window configs across multiple years (standalone, no M1).
Tests start times 09:30 / 09:45 / 10:10 / 10:20 x bar counts 6 / 8 / 10 / 12.
Base: --top 2 --weights 60 40 --stop-pct 0.6
      --stale-cut-mins 45 --stale-cut-threshold 0.75 --reversal --feed sip
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

START_TIMES     = ["09:30", "09:45", "10:10", "10:20"]
BAR_COUNTS      = [6, 8, 10, 12]
PERIODS         = [
    ("2024", date(2024, 1, 1), date(2024, 12, 31)),
    ("2023", date(2023, 1, 1), date(2023, 12, 31)),
]
N               = 2
WEIGHTS_INPUT   = [60, 40]
INITIAL_CAPITAL = 10_000.0


def _entry_time(opening_start: str, opening_bars: int) -> str:
    h, m = map(int, opening_start.split(":"))
    total = h * 60 + m + opening_bars * 5
    return f"{total // 60:02d}:{total % 60:02d}"


def _run_one(args):
    plabel, eval_start, eval_end, opening_start, opening_bars = args

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS, _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    windows = [{"label": "LOR", "opening_start": opening_start, "opening_bars": opening_bars}]

    trade_rows, _, _ = run_selector_backtest(
        n=N,
        tickers=DEFAULT_TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=windows,
        stop_pct=0.60,
        stale_cut_mins=45,
        stale_cut_threshold=0.75,
        enable_reversal=True,
        feed=DataFeed.SIP,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, windows, INITIAL_CAPITAL, weights, N)

    active   = [r for r in trade_rows if not r.get("skipped")]
    n_trades = len(active)
    n_wins   = sum(1 for r in active if r.get("pnl", 0) > 0)
    wr       = n_wins / n_trades * 100 if n_trades else 0.0
    pnl      = sum(r.get("cap_pnl", 0.0) for r in active)
    return pnl, n_trades, wr


def main():
    tasks = [
        (plabel, pstart, pend, start, bars)
        for plabel, pstart, pend in PERIODS
        for start, bars in product(START_TIMES, BAR_COUNTS)
    ]
    total = len(tasks)
    print(f"Running {total} tasks (ProcessPoolExecutor, 8 workers)...\n", flush=True)

    results = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_one, t): t for t in tasks}
        for fut in as_completed(futures):
            plabel, _, _, opening_start, opening_bars = futures[fut]
            try:
                results[(plabel, opening_start, opening_bars)] = fut.result()
            except Exception as exc:
                results[(plabel, opening_start, opening_bars)] = (float("nan"), 0, 0.0)
                print(f"  ERROR {futures[fut]}: {exc}", flush=True)
            completed += 1
            if completed % 8 == 0:
                print(f"  {completed}/{total} done...", flush=True)

    print(f"  {completed}/{total} done.\n", flush=True)

    for plabel, pstart, pend in PERIODS:
        period_results = {
            (s, b): results.get((plabel, s, b), (float("nan"), 0, 0.0))
            for s, b in product(START_TIMES, BAR_COUNTS)
        }
        best_pnl = max((v[0] for v in period_results.values() if v[0] == v[0]), default=0)

        print("=" * 66)
        print(f"  LONG OR WINDOW SWEEP  —  {plabel}  ({pstart} → {pend})")
        print("  Standalone window (no M1), top-2, 60/40, reversal, stale 45/0.75")
        print("=" * 66)
        print(f"  {'Start':<6}  {'Bars':>5}  {'Entry':>6}  {'P&L':>11}  {'Trades':>7}  {'WR':>6}")
        print("  " + "─" * 52)

        for start in START_TIMES:
            for bars in BAR_COUNTS:
                pnl, n_trades, wr = period_results[(start, bars)]
                entry = _entry_time(start, bars)
                marker = "  ◄ best" if pnl == best_pnl else ""
                print(f"  {start:<6}  {bars:>5}  {entry:>6}  ${pnl:>+10,.2f}  {n_trades:>7}  {wr:>5.1f}%{marker}")
            print()


if __name__ == "__main__":
    main()
