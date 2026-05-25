"""4-window curated sweep for 2026 YTD (~100 combos).

Anchored on M1=3 (doc's 2026 winner), explore A1/A2/A3 lengths + stop-pct.
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"
MAX_WORKERS = 20
START_DATE = "2026-01-01"
END_DATE = "2026-05-21"

M1_BARS = [3]
A1_BARS = [1, 3, 6]
A2_BARS = [1, 3, 6]
A3_BARS = [3, 6, 12]
STOPS = ["0.5", "0.7", "0.9", "1.0"]


def _run_one(m1, a1, a2, a3, stop):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
        "--top", "2",
        "--window", "M1", "09:30", str(m1),
        "--window", "A1", "10:00", str(a1),
        "--window", "A2", "10:30", str(a2),
        "--window", "A3", "11:00", str(a3),
        "--bearish-reentry", "--bullish-reentry", "--reversal",
        "--stop-pct", stop,
        "--feed", "sip",
        "--min-hold-bars", "1",
        "--start", START_DATE, "--end", END_DATE,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = result.stdout
    m = re.search(r"TOTAL\s+\d+\s+\d+W/\d+L\s+([+-]?\$[\d,]+\.\d+)", out)
    pnl = float(m.group(1).replace("$", "").replace(",", "")) if m else None
    return (m1, a1, a2, a3, stop, pnl)


def main():
    combos = list(product(M1_BARS, A1_BARS, A2_BARS, A3_BARS, STOPS))
    print(f"=== {len(combos)} combos, max {MAX_WORKERS} workers ({START_DATE} → {END_DATE}) ===", flush=True)
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_run_one, *c): c for c in combos}
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            results.append(r)
            ps = f"${r[5]:+,.0f}" if r[5] is not None else "ERR"
            print(f"  [{done:3d}/{len(combos)}] M1={r[0]} A1={r[1]} A2={r[2]} A3={r[3]} stop={r[4]} → {ps}", flush=True)

    results.sort(key=lambda r: r[5] if r[5] is not None else -1e12, reverse=True)
    print("\n" + "=" * 80)
    print("TOP 20")
    print("=" * 80)
    print(f"  {'Rank':<5} {'M1':<3} {'A1':<3} {'A2':<3} {'A3':<3} {'Stop':<5} {'P&L':>12}")
    for i, r in enumerate(results[:20], 1):
        ps = f"${r[5]:+,.0f}" if r[5] is not None else "ERR"
        print(f"  #{i:<4} {r[0]:<3} {r[1]:<3} {r[2]:<3} {r[3]:<3} {r[4]:<5} {ps:>12}")
    print("=" * 80)


if __name__ == "__main__":
    main()
