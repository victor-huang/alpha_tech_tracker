"""
5-year annual validation for top-8 stale-cut configs + baseline + current (45/0.75).
Base: --top 2 --weights 60 40 --window M1 09:30 1 --window A1 12:00 3
      --stop-pct 0.6 --feed sip --reversal

Top 8 selected by combined (2025 delta + 2026 YTD delta):
  50/0.25 +$2,241 | 50/1.00 +$2,120 | 50/0.50 +$1,807 | 60/1.00 +$1,261
  60/0.75 +$1,138 | 60/0.50 +$1,135 | 50/0.75  +$881  | 55/1.00  +$789
Plus: baseline (0/0.00) and current (45/0.75)
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

CONFIGS = [
    ("baseline",  0,  0.00),
    ("50/0.25",  50,  0.25),
    ("50/1.00",  50,  1.00),
    ("50/0.50",  50,  0.50),
    ("60/1.00",  60,  1.00),
    ("60/0.75",  60,  0.75),
    ("60/0.50",  60,  0.50),
    ("50/0.75",  50,  0.75),
    ("55/1.00",  55,  1.00),
    ("45/0.75",  45,  0.75),   # current
]

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
YEAR_ENDS = {2026: date(2026, 5, 15)}

WINDOWS = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 1},
    {"label": "A1", "opening_start": "12:00", "opening_bars": 3},
]

N = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0


def _run_one(args):
    label, mins, thresh, year = args

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS,
        _apply_capital_flow,
        _parse_weights,
        run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed
    from datetime import date as _date

    year_ends = {2026: _date(2026, 5, 15)}
    eval_start = _date(year, 1, 1)
    eval_end   = year_ends.get(year, _date(year, 12, 31))

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
    return sum(r.get("cap_pnl", 0.0) for r in active)


def main():
    tasks = [
        (label, mins, thresh, year)
        for label, mins, thresh in CONFIGS
        for year in YEARS
    ]
    total = len(tasks)
    print(f"Running {total} tasks with ProcessPoolExecutor (8 workers)...\n", flush=True)

    results = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_one, task): task for task in tasks}
        for fut in as_completed(futures):
            label, mins, thresh, year = futures[fut]
            try:
                results[(label, year)] = fut.result()
            except Exception as exc:
                results[(label, year)] = float("nan")
                print(f"  ERROR ({label}, {year}): {exc}", flush=True)
            completed += 1
            if completed % 8 == 0:
                print(f"  {completed}/{total} done...", flush=True)

    print(f"  {completed}/{total} done.\n", flush=True)

    # ── Results table ──────────────────────────────────────────────────────
    year_labels = [str(y) if y != 2026 else "2026YTD" for y in YEARS]
    col_w = 11
    header = f"  {'Config':<12}" + "".join(f"{lbl:>{col_w}}" for lbl in year_labels) + f"{'TOTAL':>{col_w}}"
    sep = "  " + "─" * (12 + col_w * (len(YEARS) + 1))

    print("=" * len(header))
    print("  STALE-CUT ANNUAL P&L  (M1 09:30/1 + A1 12:00/3, top-2, 60/40, reversal)")
    print("=" * len(header))
    print(header)
    print(sep)

    # Sort by 6-year total, keep baseline first
    base_label = "baseline"
    non_base = [(lbl, m, t) for lbl, m, t in CONFIGS if lbl != base_label]
    sorted_configs = sorted(
        non_base,
        key=lambda x: sum(results.get((x[0], y), 0.0) for y in YEARS),
        reverse=True,
    )
    ordered = [(base_label, 0, 0.00)] + sorted_configs

    for label, mins, thresh in ordered:
        row_total = sum(results.get((label, y), 0.0) for y in YEARS)
        row = f"  {label:<12}"
        for y in YEARS:
            p = results.get((label, y), float("nan"))
            row += f"  {'+' if p >= 0 else ''}${p:>6,.0f}"
        marker = "  ◄ current" if label == "45/0.75" else ""
        row += f"  {'+' if row_total >= 0 else ''}${row_total:>6,.0f}{marker}"
        print(row)

    print(sep)

    # ── vs-baseline delta table ────────────────────────────────────────────
    print()
    base_by_year = {y: results.get((base_label, y), 0.0) for y in YEARS}
    print(f"  Delta vs baseline:")
    print(header.replace("Config", "Config  ").replace("TOTAL", " TOTAL"))
    print(sep)
    for label, mins, thresh in sorted_configs:
        deltas = [results.get((label, y), 0.0) - base_by_year[y] for y in YEARS]
        total_delta = sum(deltas)
        row = f"  {label:<12}"
        for d in deltas:
            row += f"  {'+' if d >= 0 else ''}${d:>6,.0f}"
        marker = "  ◄ current" if label == "45/0.75" else ""
        row += f"  {'+' if total_delta >= 0 else ''}${total_delta:>6,.0f}{marker}"
        print(row)
    print()


if __name__ == "__main__":
    main()
