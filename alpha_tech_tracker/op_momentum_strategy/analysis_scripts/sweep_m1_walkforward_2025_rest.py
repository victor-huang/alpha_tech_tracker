"""6-month rolling walk-forward for Apr-Dec 2025 (continues sweep_m1_walkforward_q1_2025.py).

Step 4: Train Oct 2024 - Mar 2025 -> Test Apr 2025
...
Step 12: Train Jun 2025 - Nov 2025 -> Test Dec 2025
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from itertools import product

BARS = list(range(1, 11))
STOPS = ["0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1.0"]

MAX_WORKERS = 20
PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"


def _month_end(year: int, month: int) -> str:
    if month == 12:
        return f"{year}-12-31"
    next_m = datetime(year, month + 1, 1)
    from datetime import timedelta
    end = next_m - timedelta(days=1)
    return end.strftime("%Y-%m-%d")


def _months_back_start(test_year: int, test_month: int, months_back: int) -> str:
    y, m = test_year, test_month - months_back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-01"


def _build_steps():
    steps = []
    n = 4
    for ym in [(2025, 4), (2025, 5), (2025, 6), (2025, 7), (2025, 8),
               (2025, 9), (2025, 10), (2025, 11), (2025, 12)]:
        y, m = ym
        train_start = _months_back_start(y, m, 6)
        train_end = _month_end(y if m > 1 else y - 1, m - 1 if m > 1 else 12)
        test_start = f"{y:04d}-{m:02d}-01"
        test_end = _month_end(y, m)
        steps.append({"name": f"Step {n}", "train": (train_start, train_end), "test": (test_start, test_end)})
        n += 1
    return steps


STEPS = _build_steps()


def _bars_to_entry(bars: int) -> str:
    h = 9
    mm = 30 + bars * 5
    h += mm // 60
    mm = mm % 60
    return f"{h:02d}:{mm:02d}"


def _run_one(start: str, end: str, bars: int, stop: str):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
        "--top", "2",
        "--window", "M1", "09:30", str(bars),
        "--bearish-reentry", "--bullish-reentry", "--reversal",
        "--stop-pct", stop,
        "--feed", "sip",
        "--min-hold-bars", "1",
        "--start", start, "--end", end,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = result.stdout
    pnl = None
    m = re.search(r"TOTAL\s+\d+\s+\d+W/\d+L\s+([+-]?\$[\d,]+\.\d+)", out)
    if m:
        pnl = float(m.group(1).replace("$", "").replace(",", ""))
    return (bars, stop, pnl)


def _sweep(label: str, start: str, end: str):
    combos = list(product(BARS, STOPS))
    print(f"\n=== {label}: sweeping {len(combos)} combos for {start} → {end} ===", flush=True)
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_run_one, start, end, b, s): (b, s) for b, s in combos}
        for fut in as_completed(futures):
            done += 1
            row = fut.result()
            results.append(row)
            if done % 40 == 0 or done == len(combos):
                print(f"  [{done}/{len(combos)}]", flush=True)
    results.sort(key=lambda r: r[2] if r[2] is not None else -1e12, reverse=True)
    return results


def _print_top5(results, header: str):
    print(f"\n{header}")
    print(f"  {'Rank':<6} {'Bars':<5} {'Entry':<7} {'Stop':<5} {'P&L':>12}")
    for i, (b, s, pnl) in enumerate(results[:5], 1):
        pnl_s = f"${pnl:+,.0f}" if pnl is not None else "ERR"
        print(f"  #{i:<5} {b:<5} {_bars_to_entry(b):<7} {s:<5} {pnl_s:>12}")


def main():
    summary_rows = []
    for step in STEPS:
        name = step["name"]
        train_start, train_end = step["train"]
        test_start, test_end = step["test"]

        train_results = _sweep(f"{name} training", train_start, train_end)
        _print_top5(train_results, f"{name} training top-5 ({train_start} → {train_end}):")
        best_bars, best_stop, best_train_pnl = train_results[0]
        print(f"\n{name} selected: bars={best_bars} stop={best_stop} (train ${best_train_pnl:+,.0f})", flush=True)

        _, _, oos_pnl = _run_one(test_start, test_end, best_bars, best_stop)
        oos_pnl_s = f"${oos_pnl:+,.0f}" if oos_pnl is not None else "ERR"
        print(f"{name} OOS P&L ({test_start[:7]}): {oos_pnl_s}", flush=True)

        oracle_results = _sweep(f"{name} oracle", test_start, test_end)
        _print_top5(oracle_results, f"{name} oracle top-5:")
        oracle_bars, oracle_stop, oracle_pnl = oracle_results[0]
        eff = (oos_pnl / oracle_pnl) if (oos_pnl is not None and oracle_pnl and oracle_pnl != 0) else None

        summary_rows.append({
            "name": name,
            "test": test_start[:7],
            "selected": f"bars={best_bars} s={best_stop}",
            "oos_pnl": oos_pnl,
            "oracle": f"bars={oracle_bars} s={oracle_stop}",
            "oracle_pnl": oracle_pnl,
            "eff": eff,
        })

    print("\n" + "=" * 100)
    print("WALK-FORWARD SUMMARY (6-month rolling, Apr-Dec 2025)")
    print("=" * 100)
    print(f"  {'Step':<8} {'Test':<10} {'Selected':<20} {'OOS P&L':>12} {'Oracle':<20} {'Oracle P&L':>12} {'Eff':>7}")
    tot_oos = 0.0
    tot_oracle = 0.0
    for r in summary_rows:
        oos = f"${r['oos_pnl']:+,.0f}" if r['oos_pnl'] is not None else "ERR"
        ora = f"${r['oracle_pnl']:+,.0f}" if r['oracle_pnl'] is not None else "ERR"
        eff = f"{r['eff']:.3f}" if r['eff'] is not None else "—"
        tot_oos += r['oos_pnl'] or 0
        tot_oracle += r['oracle_pnl'] or 0
        print(f"  {r['name']:<8} {r['test']:<10} {r['selected']:<20} {oos:>12} {r['oracle']:<20} {ora:>12} {eff:>7}")
    print("-" * 100)
    eff_tot = tot_oos / tot_oracle if tot_oracle else 0
    print(f"  {'TOTAL':<8} {'Apr-Dec':<10} {'':<20} ${tot_oos:>+11,.0f} {'':<20} ${tot_oracle:>+11,.0f} {eff_tot:>7.3f}")
    print("=" * 100)


if __name__ == "__main__":
    main()
