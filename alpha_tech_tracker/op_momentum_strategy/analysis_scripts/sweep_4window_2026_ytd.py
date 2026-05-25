"""4-window (M1/A1/A2/A3) bar count sweep for 2026 YTD.

Window start times fixed:
- M1: 09:30
- A1: 10:00
- A2: 10:30
- A3: 11:00

Stage 1: bar grid at stop=0.9 (doc's 2026 best stop-pct).
  M1 bars: 1-6 (entry by 10:00 A1 start)
  A1 bars: 1-6 (entry by 10:30 A2 start)
  A2 bars: 1-6 (entry by 11:00 A3 start)
  A3 bars: 1-12 (entry by 12:00)
  -> 6*6*6*12 = 2,592 combos

Stage 2: top-5 from stage 1 swept across stop-pct {0.3..1.0} -> 40 combos
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
STAGE1_STOP = "0.9"
STAGE2_STOPS = ["0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1.0"]
TOP_N_FOR_STAGE2 = 5


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


def _print_top(results, n, header):
    print(f"\n{header}")
    print(f"  {'Rank':<5} {'M1':<3} {'A1':<3} {'A2':<3} {'A3':<3} {'Stop':<5} {'P&L':>12}")
    for i, r in enumerate(results[:n], 1):
        m1, a1, a2, a3, stop, pnl = r
        ps = f"${pnl:+,.0f}" if pnl is not None else "ERR"
        print(f"  #{i:<4} {m1:<3} {a1:<3} {a2:<3} {a3:<3} {stop:<5} {ps:>12}")


def main():
    # Stage 1: bar grid at stop=0.9
    combos = list(product(range(1, 7), range(1, 7), range(1, 7), range(1, 13)))
    total = len(combos)
    print(f"=== Stage 1: {total} bar combos at stop={STAGE1_STOP} ({START_DATE} → {END_DATE}) ===", flush=True)
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_run_one, m1, a1, a2, a3, STAGE1_STOP): (m1, a1, a2, a3) for m1, a1, a2, a3 in combos}
        for fut in as_completed(futures):
            done += 1
            results.append(fut.result())
            if done % 100 == 0 or done == total:
                print(f"  [{done}/{total}]", flush=True)

    results.sort(key=lambda r: r[5] if r[5] is not None else -1e12, reverse=True)
    _print_top(results, 10, "Stage 1 top-10 (bar grid @ stop=0.9):")

    top_n = results[:TOP_N_FOR_STAGE2]
    print(f"\n=== Stage 2: top-{TOP_N_FOR_STAGE2} x {len(STAGE2_STOPS)} stops = {TOP_N_FOR_STAGE2 * len(STAGE2_STOPS)} combos ===", flush=True)
    stage2_combos = [(r[0], r[1], r[2], r[3], s) for r in top_n for s in STAGE2_STOPS]
    stage2_results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_run_one, m1, a1, a2, a3, s): (m1, a1, a2, a3, s) for m1, a1, a2, a3, s in stage2_combos}
        for fut in as_completed(futures):
            done += 1
            stage2_results.append(fut.result())
            print(f"  [{done}/{len(stage2_combos)}]", flush=True)

    stage2_results.sort(key=lambda r: r[5] if r[5] is not None else -1e12, reverse=True)
    _print_top(stage2_results, 10, "Stage 2 top-10 (with stop sweep):")

    print("\n" + "=" * 80)
    print("WINNER")
    print("=" * 80)
    if stage2_results:
        w = stage2_results[0]
        print(f"  M1={w[0]} A1={w[1]} A2={w[2]} A3={w[3]} stop={w[4]}  →  ${w[5]:+,.0f}")
    print("=" * 80)


if __name__ == "__main__":
    main()
