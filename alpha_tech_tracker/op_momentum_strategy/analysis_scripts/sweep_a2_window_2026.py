"""Sweep A2 window (10:15–15:15, bars 1–10) added to M1 09:30/1/stop-0.6 base config."""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

A2_TIMES = [
    "10:15", "10:30", "10:45",
    "11:00", "11:15", "11:30", "11:45",
    "12:00", "12:15", "12:30", "12:45",
    "13:00", "13:15", "13:30", "13:45",
    "14:00", "14:15", "14:30", "14:45",
    "15:00", "15:15",
]
A2_BARS = ["1", "2", "3", "4", "5", "6", "8", "10"]

MAX_WORKERS = 20
PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"

BASE_CMD = [
    "--top", "2", "--weights", "60", "40",
    "--window", "M1", "09:30", "1",
    "--morning-split", "100",
    "--start", "2026-01-01", "--end", "2026-05-15",
    "--feed", "sip", "--reversal",
    "--stop-pct", "0.6",
]


def run_backtest(extra_args):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
    ] + BASE_CMD + extra_args
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result.stdout


def parse_window_row(out, label):
    pattern = (
        rf"{label}\s+\S+\s+\S+\s+\S+\s+"
        r"(\d+)\s+"
        r"(\d+)W/(\d+)L\s+"
        r"(\d+)%\s+"
        r"([+-]\d+\.\d+)%\s+"
        r"([+-]?\$[\d,]+\.?\d*)\s+"
        r"([+-]\d+\.?\d*)%\s+"
        r"(\d+)\s+"
        r"(\d+)%\s+"
        r"(\d+)%"
    )
    m = re.search(pattern, out)
    if not m:
        return None
    trades = int(m.group(1))
    wins = int(m.group(2))
    wr = int(m.group(4))
    ev = float(m.group(5))
    cap_pnl = float(m.group(6).replace("$", "").replace(",", ""))
    ret_pct = float(m.group(7))
    short_n = int(m.group(8))
    short_pct = int(m.group(9))
    shwr = int(m.group(10))
    return dict(trades=trades, wins=wins, wr=wr, ev=ev,
                cap_pnl=cap_pnl, ret_pct=ret_pct,
                short_n=short_n, short_pct=short_pct, shwr=shwr)


def parse_total_pct(out):
    m = re.search(r"Total return \(%\)\s*:\s*([+-]?\d+\.?\d*)%", out)
    return float(m.group(1)) if m else None


def run_baseline():
    out = run_backtest([])
    total_pct = parse_total_pct(out)
    trades_m = re.search(r"TOTAL\s+(\d+)\s+(\d+)W/(\d+)L", out)
    trades = int(trades_m.group(1)) if trades_m else None
    wr = round(int(trades_m.group(2)) / int(trades_m.group(1)) * 100) if trades_m else None
    short_m = re.search(r"Short trades\s*:\s*(\d+)", out)
    short_n = int(short_m.group(1)) if short_m and trades else None
    short_pct = round(short_n / trades * 100) if (short_n and trades) else None
    return dict(trades=trades, wr=wr, short_n=short_n, short_pct=short_pct), total_pct


def run_one(t, b):
    out = run_backtest(["--window", "A2", t, b])
    total_pct = parse_total_pct(out)
    a2 = parse_window_row(out, "A2")
    return (t, b, a2, total_pct)


def main():
    print("Running M1-only baseline...", flush=True)
    baseline_m1, baseline_pct = run_baseline()
    print(f"  Baseline M1: {baseline_pct:+.2f}%  "
          f"(trades={baseline_m1['trades']} WR={baseline_m1['wr']}% "
          f"short={baseline_m1['short_pct']}%)\n", flush=True)

    combos = list(product(A2_TIMES, A2_BARS))
    total = len(combos)
    print(f"Sweeping {total} A2 combos with {MAX_WORKERS} parallel workers...\n", flush=True)

    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(run_one, t, b): (t, b) for t, b in combos}
        for fut in as_completed(futures):
            done += 1
            t, b, a2, total_pct = fut.result()
            results.append((t, b, a2, total_pct))
            incr = (total_pct - baseline_pct) if total_pct and baseline_pct else 0
            a2_pnl = f"{a2['cap_pnl']:+.0f}" if a2 else "ERR"
            a2_sh = f"{a2['short_pct']}%" if a2 else "-"
            print(f"  [{done:3d}/{total}] A2 {t}/{b}b  total={total_pct:+.2f}%  "
                  f"incr={incr:+.2f}pp  a2_pnl={a2_pnl}  a2_short={a2_sh}", flush=True)

    results.sort(key=lambda r: r[2]["cap_pnl"] if r[2] else -99999, reverse=True)

    print("\n" + "=" * 115)
    print(f"  Baseline M1-only: {baseline_pct:+.2f}%  "
          f"(M1 trades={baseline_m1['trades']} WR={baseline_m1['wr']}% short={baseline_m1['short_pct']}%)")
    print("=" * 115)
    print(f"{'Rank':>4}  {'A2 Time':>7}  {'Bars':>4}  "
          f"{'A2 P&L$':>8}  {'A2 Ret%':>7}  {'A2 EV%':>7}  {'A2 Trades':>9}  {'A2 WR%':>6}  "
          f"{'A2 Sh%':>6}  {'A2 ShWR':>7}  "
          f"{'Total%':>7}  {'Incr pp':>8}")
    print("-" * 115)
    for rank, (t, b, a2, total_pct) in enumerate(results, 1):
        if a2 is None:
            print(f"  {rank:3d}  {t:>7}  {b:>4}  ERR")
            continue
        incr = (total_pct - baseline_pct) if total_pct and baseline_pct else 0
        print(
            f"  {rank:3d}  {t:>7}  {b:>4}  "
            f"{a2['cap_pnl']:>+8.0f}  {a2['ret_pct']:>+7.2f}%  {a2['ev']:>+7.3f}%  "
            f"{a2['trades']:>9}  {a2['wr']:>6}%  "
            f"{a2['short_pct']:>6}%  {a2['shwr']:>7}%  "
            f"{total_pct:>+7.2f}%  {incr:>+8.2f}pp"
        )
    print("=" * 115)


if __name__ == "__main__":
    main()
