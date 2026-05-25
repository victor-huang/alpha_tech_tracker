"""2-month rolling walk-forward for Q1 2025 (companion to sweep_m1_walkforward_q1_2025.py).

Step 1: Train Nov-Dec 2024 -> Test Jan 2025
Step 2: Train Dec 2024-Jan 2025 -> Test Feb 2025
Step 3: Train Jan-Feb 2025 -> Test Mar 2025

Oracle values reused from prior 6mo q1 sweep (oracle is independent of training window).
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
    {"name": "Step 1", "train": ("2024-11-01", "2024-12-31"), "test": ("2025-01-01", "2025-01-31"),
     "oracle_config": "bars=4 s=0.3", "oracle_pnl": 202.0},
    {"name": "Step 2", "train": ("2024-12-01", "2025-01-31"), "test": ("2025-02-01", "2025-02-28"),
     "oracle_config": "bars=2 s=0.3", "oracle_pnl": 889.0},
    {"name": "Step 3", "train": ("2025-01-01", "2025-02-28"), "test": ("2025-03-01", "2025-03-31"),
     "oracle_config": "bars=2 s=0.3", "oracle_pnl": 778.0},
]


def _bars_to_entry(bars: int) -> str:
    h, mm = 9, 30 + bars * 5
    h += mm // 60
    mm = mm % 60
    return f"{h:02d}:{mm:02d}"


def _run_one(start, end, bars, stop):
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
    m = re.search(r"TOTAL\s+\d+\s+\d+W/\d+L\s+([+-]?\$[\d,]+\.\d+)", out)
    return (bars, stop, float(m.group(1).replace("$", "").replace(",", ""))) if m else (bars, stop, None)


def _sweep(label, start, end):
    combos = list(product(BARS, STOPS))
    print(f"\n=== {label}: {len(combos)} combos {start} → {end} ===", flush=True)
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_run_one, start, end, b, s): (b, s) for b, s in combos}
        for fut in as_completed(futures):
            done += 1
            results.append(fut.result())
            if done % 20 == 0 or done == len(combos):
                print(f"  [{done}/{len(combos)}]", flush=True)
    results.sort(key=lambda r: r[2] if r[2] is not None else -1e12, reverse=True)
    return results


def main():
    summary = []
    for step in STEPS:
        name = step["name"]
        ts, te = step["train"]
        xs, xe = step["test"]

        train = _sweep(f"{name} training", ts, te)
        print(f"\n{name} training top-5:")
        for i, (b, s, p) in enumerate(train[:5], 1):
            ps = f"${p:+,.0f}" if p is not None else "ERR"
            print(f"  #{i} bars={b} ({_bars_to_entry(b)}) stop={s} {ps}")

        best_b, best_s, best_train = train[0]
        print(f"\n{name} selected: bars={best_b} stop={best_s} (train ${best_train:+,.0f})", flush=True)

        _, _, oos = _run_one(xs, xe, best_b, best_s)
        eff = oos / step["oracle_pnl"] if oos is not None and step["oracle_pnl"] else None
        print(f"{name} OOS ({xs[:7]}): ${oos:+,.0f} (oracle {step['oracle_config']} ${step['oracle_pnl']:+,.0f}, eff {eff:.3f})", flush=True)

        summary.append({
            "name": name, "test": xs[:7],
            "selected": f"bars={best_b} s={best_s}",
            "oos": oos, "oracle": step["oracle_config"],
            "oracle_pnl": step["oracle_pnl"], "eff": eff,
        })

    print("\n" + "=" * 95)
    print("2-MONTH WALK-FORWARD — Q1 2025 SUMMARY")
    print("=" * 95)
    print(f"  {'Step':<8} {'Test':<10} {'Selected':<22} {'OOS P&L':>12} {'Oracle':<18} {'Oracle P&L':>12} {'Eff':>7}")
    tot_oos = tot_ora = 0.0
    for r in summary:
        oos_s = f"${r['oos']:+,.0f}" if r['oos'] is not None else "ERR"
        eff_s = f"{r['eff']:.3f}" if r['eff'] is not None else "—"
        tot_oos += r['oos'] or 0
        tot_ora += r['oracle_pnl']
        print(f"  {r['name']:<8} {r['test']:<10} {r['selected']:<22} {oos_s:>12} {r['oracle']:<18} ${r['oracle_pnl']:>+11,.0f} {eff_s:>7}")
    print("-" * 95)
    et = tot_oos / tot_ora if tot_ora else 0
    print(f"  {'TOTAL':<8} {'Q1 2025':<10} {'':<22} ${tot_oos:>+11,.0f} {'':<18} ${tot_ora:>+11,.0f} {et:>7.3f}")
    print("=" * 95)
    print("\nFor comparison:")
    print(f"  6mo walk-fwd: OOS +$211, eff 0.113")
    print(f"  bars=3 s=0.8 forced: OOS -$679, eff -0.363")


if __name__ == "__main__":
    main()
