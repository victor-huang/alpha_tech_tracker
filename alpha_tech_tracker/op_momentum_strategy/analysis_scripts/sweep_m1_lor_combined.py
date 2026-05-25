"""
Combined sweep: M1 (09:30/1) + LOR second window.
LOR bar collection starts at 10:00 / 10:20 / 10:30, entry >= 10:20.
Sequential capital (no morning-split) — M1 capital flows into LOR.
Base: --top 2 --weights 60 40 --stop-pct 0.6
      --stale-cut-mins 45 --stale-cut-threshold 0.75 --reversal --feed sip
Period: 2026 YTD (2026-01-01 → 2026-05-15)
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

M1_WINDOW    = {"label": "M1", "opening_start": "09:30", "opening_bars": 1}

# Top 10 candidates from 2026 YTD sweep, sorted by total P&L
TOP10_CONFIGS = [
    ("10:00", 10),  # entry 10:50  +$1,449 vs M1
    ("10:30", 12),  # entry 11:30  +$1,350
    ("10:30",  8),  # entry 11:10  +$1,306
    ("10:30",  4),  # entry 10:50  +$1,230
    ("10:20",  6),  # entry 10:50  +$1,089
    ("10:20", 10),  # entry 11:10  +$1,002
    ("10:00",  6),  # entry 10:30  +$  995
    ("10:30",  6),  # entry 11:00  +$  977
    ("10:00",  4),  # entry 10:20  +$  866
    ("10:20", 12),  # entry 11:20  +$  722
]

EVAL_START   = date(2025, 1, 1)
EVAL_END     = date(2025, 12, 31)
N            = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0


def _entry_time(opening_start: str, opening_bars: int) -> str:
    h, m = map(int, opening_start.split(":"))
    total = h * 60 + m + opening_bars * 5
    return f"{total // 60:02d}:{total % 60:02d}"


def _run_one(args):
    lor_start, lor_bars = args

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS, _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed
    from datetime import date as _date

    windows = [
        {"label": "M1",  "opening_start": "09:30", "opening_bars": 1},
        {"label": "LOR", "opening_start": lor_start, "opening_bars": lor_bars},
    ]

    trade_rows, _, _ = run_selector_backtest(
        n=N,
        tickers=DEFAULT_TICKERS,
        eval_start=EVAL_START,
        eval_end=EVAL_END,
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
    m1_rows  = [r for r in active if r.get("window") == "M1"]
    lor_rows = [r for r in active if r.get("window") == "LOR"]

    def _stats(rows):
        n    = len(rows)
        wins = sum(1 for r in rows if r.get("pnl", 0) > 0)
        pnl  = sum(r.get("cap_pnl", 0.0) for r in rows)
        wr   = wins / n * 100 if n else 0.0
        return n, wr, pnl

    return _stats(active) + _stats(m1_rows) + _stats(lor_rows)


def _run_baseline(_):
    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS, _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed
    from datetime import date as _date

    windows = [{"label": "M1", "opening_start": "09:30", "opening_bars": 1}]
    trade_rows, _, _ = run_selector_backtest(
        n=N, tickers=DEFAULT_TICKERS,
        eval_start=EVAL_START, eval_end=EVAL_END,
        windows=windows, stop_pct=0.60,
        stale_cut_mins=45, stale_cut_threshold=0.75,
        enable_reversal=True, feed=DataFeed.SIP,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, windows, INITIAL_CAPITAL, weights, N)
    active = [r for r in trade_rows if not r.get("skipped")]
    n = len(active)
    wins = sum(1 for r in active if r.get("pnl", 0) > 0)
    pnl  = sum(r.get("cap_pnl", 0.0) for r in active)
    wr   = wins / n * 100 if n else 0.0
    return (n, wr, pnl) + (n, wr, pnl) + (0, 0.0, 0.0)


def main():
    configs = TOP10_CONFIGS
    total = len(configs) + 1  # +1 for baseline
    print(f"Running {total} tasks ({len(configs)} combos + 1 baseline, 8 workers)...\n", flush=True)

    results = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_baseline, None): ("baseline", 0)}
        for cfg in configs:
            futures[pool.submit(_run_one, cfg)] = cfg

        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:
                results[key] = (0, 0.0, 0.0) * 3
                print(f"  ERROR {key}: {exc}", flush=True)
            completed += 1
            if completed % 4 == 0:
                print(f"  {completed}/{total} done...", flush=True)

    print(f"  {completed}/{total} done.\n", flush=True)

    base = results.get(("baseline", 0), (0, 0.0, 0.0, 0, 0.0, 0.0, 0, 0.0, 0.0))
    base_pnl = base[2]

    print("=" * 90)
    print("  M1 (09:35 entry) + LOR COMBINED  —  2025  (sequential capital)")
    print("=" * 90)
    print(f"  {'LOR Start':<10}  {'Bars':>4}  {'Entry':>6}  "
          f"{'Total P&L':>11}  {'vs M1':>9}  {'Tot WR':>7}  "
          f"{'M1 P&L':>9}  {'LOR P&L':>9}  {'LOR WR':>7}")
    print("  " + "─" * 82)

    # Print baseline first
    print(f"  {'M1 only':<10}  {'—':>4}  {'—':>6}  "
          f"  ${base_pnl:>+9,.0f}  {'—':>9}  {base[1]:>6.1f}%  "
          f"  ${base[5]:>+7,.0f}  {'—':>9}  {'—':>7}")
    print()

    # Sort by total P&L descending
    sorted_configs = sorted(
        configs,
        key=lambda c: results.get(c, (0, 0.0, 0.0, 0, 0.0, 0.0, 0, 0.0, 0.0))[2],
        reverse=True,
    )

    for cfg in sorted_configs:
        s, b = cfg
        r = results.get(cfg, (0, 0.0, 0.0, 0, 0.0, 0.0, 0, 0.0, 0.0))
        tot_n, tot_wr, tot_pnl = r[0], r[1], r[2]
        m1_pnl = r[5]
        lor_n, lor_wr, lor_pnl = r[6], r[7], r[8]
        delta = tot_pnl - base_pnl
        entry = _entry_time(s, b)
        print(f"  {s:<10}  {b:>4}  {entry:>6}  "
              f"  ${tot_pnl:>+9,.0f}  ${delta:>+8,.0f}  {tot_wr:>6.1f}%  "
              f"  ${m1_pnl:>+7,.0f}  ${lor_pnl:>+8,.0f}  {lor_wr:>6.1f}%")
    print()


if __name__ == "__main__":
    main()
