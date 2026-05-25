"""
Annual sweep of top-10 A1 configs across 2021-2025.
Base config: --top 2 --weights 60 40 --window M1 09:30 1 --stop-pct 0.6
             --feed sip --stale-cut-mins 45 --stale-cut-threshold 0.75 --reversal
"""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    DEFAULT_TICKERS,
    _apply_capital_flow,
    _parse_weights,
    run_selector_backtest,
)

TOP_10_A1_CONFIGS = [
    {"label": "11:30/2", "opening_start": "11:30", "opening_bars": 2},
    {"label": "13:00/1", "opening_start": "13:00", "opening_bars": 1},
    {"label": "12:00/3", "opening_start": "12:00", "opening_bars": 3},
    {"label": "11:00/2", "opening_start": "11:00", "opening_bars": 2},
    {"label": "14:15/2", "opening_start": "14:15", "opening_bars": 2},
    {"label": "14:15/1", "opening_start": "14:15", "opening_bars": 1},
    {"label": "11:00/1", "opening_start": "11:00", "opening_bars": 1},
    {"label": "14:15/3", "opening_start": "14:15", "opening_bars": 3},
    {"label": "14:00/2", "opening_start": "14:00", "opening_bars": 2},
    {"label": "13:30/2", "opening_start": "13:30", "opening_bars": 2},
]

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
YEAR_ENDS = {2026: date(2026, 5, 15)}
N = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0
FEED = DataFeed.SIP


def _run_one(a1_label: str, a1_start: str, a1_bars: int, year: int):
    eval_start = date(year, 1, 1)
    eval_end = YEAR_ENDS.get(year, date(year, 12, 31))

    windows = [
        {"label": "M1", "opening_start": "09:30", "opening_bars": 1},
        {"label": a1_label, "opening_start": a1_start, "opening_bars": a1_bars},
    ]

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
        feed=FEED,
    )

    weights = _parse_weights(WEIGHTS_INPUT, N)
    resolved_windows = windows

    _apply_capital_flow(
        trade_rows,
        resolved_windows,
        INITIAL_CAPITAL,
        weights,
        N,
    )

    active = [r for r in trade_rows if not r.get("skipped")]
    total_pnl = sum(r.get("cap_pnl", 0.0) for r in active)
    return total_pnl


def main():
    tasks = []
    for cfg in TOP_10_A1_CONFIGS:
        for year in YEARS:
            tasks.append((cfg["label"], cfg["opening_start"], cfg["opening_bars"], year))

    print(f"Running {len(tasks)} tasks with 20 workers...\n", flush=True)

    results = {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_run_one, label, start, bars, year): (label, year)
            for label, start, bars, year in tasks
        }
        completed = 0
        for fut in as_completed(futures):
            label, year = futures[fut]
            try:
                pnl = fut.result()
            except Exception as exc:
                pnl = float("nan")
                print(f"  ERROR {label} {year}: {exc}", flush=True)
            results[(label, year)] = pnl
            completed += 1
            if completed % 10 == 0:
                print(f"  {completed}/{len(tasks)} done...", flush=True)

    print(f"\n  {completed}/{len(tasks)} done.\n", flush=True)

    # ── Print results table ────────────────────────────────────────────────
    col_w = 10
    year_labels = [str(y) if y != 2026 else "2026 YTD" for y in YEARS]
    header = f"  {'Config':<12}" + "".join(f"{lbl:>{col_w}}" for lbl in year_labels) + f"{'TOTAL':>{col_w}}"
    sep = "  " + "─" * (12 + col_w * (len(YEARS) + 1))
    print("=" * len(header))
    print("  A1 CONFIG ANNUAL P&L  (M1 09:30/1 base, top-2, 60/40, reversal, sip)")
    print("=" * len(header))
    print(header)
    print(sep)

    totals_by_year = {y: 0.0 for y in YEARS}
    rows_for_sort = []
    for cfg in TOP_10_A1_CONFIGS:
        label = cfg["label"]
        row_total = sum(results.get((label, y), 0.0) for y in YEARS)
        rows_for_sort.append((label, row_total))

    for label, row_total in rows_for_sort:
        row = f"  {label:<12}"
        for y in YEARS:
            pnl = results.get((label, y), float("nan"))
            totals_by_year[y] += pnl
            sign = "+" if pnl >= 0 else ""
            row += f"  {sign}${pnl:>6,.0f}"
        sign = "+" if row_total >= 0 else ""
        row += f"  {sign}${row_total:>6,.0f}"
        print(row)

    print(sep)
    footer = f"  {'ALL CONFIGS':<12}"
    grand_total = 0.0
    for y in YEARS:
        t = totals_by_year[y]
        grand_total += t
        sign = "+" if t >= 0 else ""
        footer += f"  {sign}${t:>6,.0f}"
    sign = "+" if grand_total >= 0 else ""
    footer += f"  {sign}${grand_total:>6,.0f}"
    print(footer)
    print()

    # ── Win / loss years per config ──────────────────────────────────────
    print(f"  {'Config':<12}  {'Win yrs':>8}  {'Lose yrs':>9}  {'Best yr':>9}  {'Worst yr':>10}  {'5yr Total':>10}")
    print(sep)
    for label, row_total in rows_for_sort:
        year_pnls = [(y, results.get((label, y), 0.0)) for y in YEARS]
        wins = sum(1 for _, p in year_pnls if p > 0)
        losses = sum(1 for _, p in year_pnls if p <= 0)
        best_y, best_p = max(year_pnls, key=lambda x: x[1])
        worst_y, worst_p = min(year_pnls, key=lambda x: x[1])
        print(
            f"  {label:<12}  {wins:>8}  {losses:>9}"
            f"  {best_y}({'+' if best_p >= 0 else ''}${best_p:,.0f})"
            f"  {worst_y}({'+' if worst_p >= 0 else ''}${worst_p:,.0f})"
            f"  {'+'if row_total >= 0 else ''}${row_total:,.0f}"
        )


if __name__ == "__main__":
    main()
