"""Sweep M1 window time/bars/stop-pct for 2025 full year."""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

TIMES = ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "10:00"]
BARS = ["1", "2", "3", "4", "5"]
STOPS = ["0.10", "0.15", "0.20", "0.25", "0.30", "0.40", "0.50", "0.60"]

MAX_WORKERS = 20
PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"


def run_one(t, b, s):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
        "--top", "2", "--weights", "60", "40",
        "--window", "M1", t, b,
        "--start", "2025-01-01", "--end", "2025-12-31",
        "--feed", "sip", "--reversal",
        "--stop-pct", s,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = result.stdout

    ret_pct = None
    trades = None
    wins = None
    wr = None
    avg_win = None
    avg_loss = None

    m = re.search(r"Total return \(%\)\s*:\s*([+-]?\d+\.?\d*)%", out)
    if m:
        ret_pct = float(m.group(1))

    # "TOTAL  487  105W/382L  -$xxx  -xx.xx%  $xxx"
    m = re.search(r"TOTAL\s+(\d+)\s+(\d+)W/(\d+)L", out)
    if m:
        trades = int(m.group(1))
        wins = int(m.group(2))
        wr = round(wins / trades * 100, 1) if trades else 0

    m = re.search(r"Avg win\s*:\s*([+-]?\d+\.?\d*)%", out)
    if m:
        avg_win = float(m.group(1))

    m = re.search(r"Avg loss\s*:\s*([+-]?\d+\.?\d*)%", out)
    if m:
        avg_loss = float(m.group(1))

    return (t, b, s, ret_pct, trades, wr, avg_win, avg_loss)


def main():
    combos = list(product(TIMES, BARS, STOPS))
    total = len(combos)
    print(f"Running {total} combos with {MAX_WORKERS} parallel workers...\n", flush=True)

    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(run_one, t, b, s): (t, b, s) for t, b, s in combos}
        for fut in as_completed(futures):
            done += 1
            row = fut.result()
            results.append(row)
            t, b, s = row[:3]
            ret = f"{row[3]:+.2f}%" if row[3] is not None else "ERR"
            print(f"  [{done:3d}/{total}] M1 {t}/{b}b stop={s}  →  {ret}", flush=True)

    results.sort(key=lambda r: r[3] if r[3] is not None else -9999, reverse=True)

    print("\n" + "=" * 85)
    print(f"{'Rank':>4}  {'Time':>5}  {'Bars':>4}  {'Stop':>5}  {'Return%':>8}  {'Trades':>6}  {'WR%':>5}  {'AvgW%':>6}  {'AvgL%':>6}")
    print("-" * 85)
    for rank, (t, b, s, ret, trades, wr, avgw, avgl) in enumerate(results, 1):
        ret_s = f"{ret:+.2f}%" if ret is not None else "ERR"
        tr_s = str(trades) if trades is not None else "-"
        wr_s = f"{wr:.1f}" if wr is not None else "-"
        aw_s = f"{avgw:+.2f}" if avgw is not None else "-"
        al_s = f"{avgl:+.2f}" if avgl is not None else "-"
        print(f"  {rank:3d}  {t:>5}  {b:>4}  {s:>5}  {ret_s:>8}  {tr_s:>6}  {wr_s:>5}  {aw_s:>6}  {al_s:>6}")
    print("=" * 85)


if __name__ == "__main__":
    main()
