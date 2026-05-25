"""
Run top-10 A1 configs for 2026 YTD only, then print combined 2021-2026 table.
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

PRIOR_RESULTS = {
    "11:30/2": {2021:  6078, 2022:  8583, 2023: 13140, 2024:  5462, 2025:  9283},
    "13:00/1": {2021:  5664, 2022: 10486, 2023: 12412, 2024:  7373, 2025:  9763},
    "12:00/3": {2021:  6186, 2022:  8297, 2023: 13607, 2024:  6451, 2025:  9984},
    "11:00/2": {2021:  5715, 2022: 10352, 2023: 15717, 2024:  5706, 2025: 11234},
    "14:15/2": {2021:  5401, 2022:  9604, 2023: 10909, 2024:  4720, 2025:  8624},
    "14:15/1": {2021:  6377, 2022:  8828, 2023: 13177, 2024:  6185, 2025: 10486},
    "11:00/1": {2021:  4335, 2022: 10474, 2023: 12650, 2024:  5516, 2025: 11597},
    "14:15/3": {2021:  4109, 2022:  8826, 2023: 11042, 2024:  4216, 2025:  9721},
    "14:00/2": {2021:  6918, 2022:  6038, 2023: 13542, 2024:  8660, 2025:  9300},
    "13:30/2": {2021:  5654, 2022:  9197, 2023: 14985, 2024:  7499, 2025: 10129},
}

N = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0
FEED = DataFeed.SIP


def _run_one(a1_label, a1_start, a1_bars):
    windows = [
        {"label": "M1", "opening_start": "09:30", "opening_bars": 1},
        {"label": a1_label, "opening_start": a1_start, "opening_bars": a1_bars},
    ]
    trade_rows, _, _ = run_selector_backtest(
        n=N,
        tickers=DEFAULT_TICKERS,
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 5, 15),
        windows=windows,
        stop_pct=0.60,
        stale_cut_mins=45,
        stale_cut_threshold=0.75,
        enable_reversal=True,
        feed=FEED,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, windows, INITIAL_CAPITAL, weights, N)
    active = [r for r in trade_rows if not r.get("skipped")]
    return sum(r.get("cap_pnl", 0.0) for r in active)


def main():
    print("Running 10 configs for 2026 YTD...\n", flush=True)
    results_2026 = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_run_one, cfg["label"], cfg["opening_start"], cfg["opening_bars"]): cfg["label"]
            for cfg in TOP_10_A1_CONFIGS
        }
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                results_2026[label] = fut.result()
            except Exception as exc:
                results_2026[label] = float("nan")
                print(f"  ERROR {label}: {exc}", flush=True)
            print(f"  {label} done", flush=True)

    YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
    col_w = 11
    year_labels = ["2021", "2022", "2023", "2024", "2025", "2026 YTD", "TOTAL"]
    header = f"  {'Config':<12}" + "".join(f"{lbl:>{col_w}}" for lbl in year_labels)
    sep = "  " + "─" * (12 + col_w * len(year_labels))

    print("\n" + "=" * len(header))
    print("  A1 CONFIG ANNUAL P&L  (M1 09:30/1 base, top-2, 60/40, reversal, sip)")
    print("=" * len(header))
    print(header)
    print(sep)

    rows_for_sort = []
    for cfg in TOP_10_A1_CONFIGS:
        label = cfg["label"]
        yr_pnls = {**PRIOR_RESULTS[label], 2026: results_2026.get(label, 0.0)}
        total = sum(yr_pnls[y] for y in YEARS)
        rows_for_sort.append((label, yr_pnls, total))

    rows_for_sort.sort(key=lambda x: x[2], reverse=True)

    for label, yr_pnls, total in rows_for_sort:
        row = f"  {label:<12}"
        for y in YEARS:
            p = yr_pnls[y]
            row += f"  {'+' if p >= 0 else ''}${p:>6,.0f}"
        row += f"  {'+' if total >= 0 else ''}${total:>6,.0f}"
        print(row)

    print(sep)
    print(f"\n  {'Config':<12}  {'Win yrs':>8}  {'Lose yrs':>9}  {'Best yr':>14}  {'Worst yr':>15}  {'6yr Total':>10}")
    print("  " + "─" * 75)
    for label, yr_pnls, total in rows_for_sort:
        wins = sum(1 for y in YEARS if yr_pnls[y] > 0)
        losses = sum(1 for y in YEARS if yr_pnls[y] <= 0)
        best_y = max(YEARS, key=lambda y: yr_pnls[y])
        worst_y = min(YEARS, key=lambda y: yr_pnls[y])
        bp, wp = yr_pnls[best_y], yr_pnls[worst_y]
        best_lbl = "2026YTD" if best_y == 2026 else str(best_y)
        worst_lbl = "2026YTD" if worst_y == 2026 else str(worst_y)
        print(
            f"  {label:<12}  {wins:>8}  {losses:>9}"
            f"  {best_lbl}({'+' if bp >= 0 else ''}${bp:,.0f})"
            f"  {worst_lbl}({'+' if wp >= 0 else ''}${wp:,.0f})"
            f"  {'+' if total >= 0 else ''}${total:,.0f}"
        )


if __name__ == "__main__":
    main()
