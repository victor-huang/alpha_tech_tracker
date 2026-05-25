"""6-month rolling walk-forward optimization: train on prior 6mo, test on each Q1 2025 month.

Step 1: Train Jul-Dec 2024 -> Test Jan 2025
Step 2: Train Aug 2024-Jan 2025 -> Test Feb 2025
Step 3: Train Sep 2024-Feb 2025 -> Test Mar 2025

Base config (matches M1_WALKFORWARD_TEST.md):
  --top 2 --window M1 09:30 <bars> --bearish-reentry --bullish-reentry --reversal
  --stop-pct <stop> --feed sip --min-hold-bars 1

Sweep space: bars 1-10, stop-pct {0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0} (80 combos).
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

BARS = list(range(1, 11))
STOPS = ["0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1.0"]

MAX_WORKERS = 20
PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"

STEPS = [
    {"name": "Step 1", "train": ("2024-07-01", "2024-12-31"), "test": ("2025-01-01", "2025-01-31")},
    {"name": "Step 2", "train": ("2024-08-01", "2025-01-31"), "test": ("2025-02-01", "2025-02-28")},
    {"name": "Step 3", "train": ("2024-09-01", "2025-02-28"), "test": ("2025-03-01", "2025-03-31")},
]


def _bars_to_entry(bars: int) -> str:
    h = 9
    m = 30 + bars * 5
    h += m // 60
    m = m % 60
    return f"{h:02d}:{m:02d}"


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
            b, s, pnl = row
            pnl_s = f"${pnl:+,.0f}" if pnl is not None else "ERR"
            if done % 20 == 0 or done == len(combos):
                print(f"  [{done}/{len(combos)}] last: bars={b} stop={s} {pnl_s}", flush=True)
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

        print(f"\n{name} selected config: bars={best_bars} stop={best_stop} (train P&L=${best_train_pnl:+,.0f})", flush=True)
        print(f"\n{name} running OOS on test month {test_start} → {test_end}...", flush=True)
        _, _, oos_pnl = _run_one(test_start, test_end, best_bars, best_stop)
        oos_pnl_s = f"${oos_pnl:+,.0f}" if oos_pnl is not None else "ERR"
        print(f"{name} OOS P&L: {oos_pnl_s}", flush=True)

        oracle_results = _sweep(f"{name} oracle", test_start, test_end)
        _print_top5(oracle_results, f"{name} oracle top-5 ({test_start} → {test_end}):")
        oracle_bars, oracle_stop, oracle_pnl = oracle_results[0]

        eff = (oos_pnl / oracle_pnl) if (oos_pnl is not None and oracle_pnl and oracle_pnl != 0) else None
        eff_s = f"{eff:.3f}" if eff is not None else "—"
        oracle_pnl_s = f"${oracle_pnl:+,.0f}" if oracle_pnl is not None else "ERR"

        summary_rows.append({
            "name": name,
            "test": f"{test_start[:7]}",
            "selected": f"bars={best_bars} stop={best_stop}",
            "oos_pnl": oos_pnl_s,
            "oracle": f"bars={oracle_bars} stop={oracle_stop}",
            "oracle_pnl": oracle_pnl_s,
            "efficiency": eff_s,
        })

    print("\n" + "=" * 95)
    print("WALK-FORWARD SUMMARY (6-month rolling, Q1 2025)")
    print("=" * 95)
    print(f"  {'Step':<8} {'Test':<10} {'Selected':<22} {'OOS P&L':>12} {'Oracle':<22} {'Oracle P&L':>12} {'Eff':>6}")
    for r in summary_rows:
        print(f"  {r['name']:<8} {r['test']:<10} {r['selected']:<22} {r['oos_pnl']:>12} {r['oracle']:<22} {r['oracle_pnl']:>12} {r['efficiency']:>6}")
    print("=" * 95)


if __name__ == "__main__":
    main()
