"""Sweep A3 window (12:xx, bars >= 3) on top of M1 + each of 3 A1 candidates."""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

A1_CONFIGS = [
    ("10:00", "6"),
    ("10:15", "10"),
    ("10:30", "8"),
]

A3_TIMES = [
    "12:00", "12:15", "12:30", "12:45",
    "13:00", "13:15", "13:30", "13:45",
    "14:00", "14:15", "14:30", "14:45",
    "15:00", "15:15",
]
A3_BARS = ["1", "2", "3", "4", "5", "6", "8", "10"]

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


def run_baseline(a1t, a1b):
    out = run_backtest(["--window", "A1", a1t, a1b])
    return parse_total_pct(out), parse_window_row(out, "A1")


def run_one(a1t, a1b, a3t, a3b):
    out = run_backtest(["--window", "A1", a1t, a1b, "--window", "A3", a3t, a3b])
    total_pct = parse_total_pct(out)
    a3 = parse_window_row(out, "A3")
    return (a1t, a1b, a3t, a3b, total_pct, a3)


def print_table(label, baseline_pct, baseline_a1, results):
    results_sorted = sorted(results, key=lambda r: r[5]["cap_pnl"] if r[5] else -99999, reverse=True)

    print(f"\n{'=' * 115}")
    print(f"  A1 config: {label}  |  Baseline (M1+A1): {baseline_pct:+.2f}%"
          f"  (A1: trades={baseline_a1['trades']} WR={baseline_a1['wr']}%"
          f" EV={baseline_a1['ev']:+.3f}% sh={baseline_a1['short_pct']}%)")
    print(f"{'=' * 115}")
    print(f"{'Rank':>4}  {'A3 Time':>7}  {'Bars':>4}  "
          f"{'A3 P&L$':>8}  {'A3 Ret%':>7}  {'A3 EV%':>7}  {'A3 Trades':>9}  "
          f"{'A3 WR%':>6}  {'A3 Sh%':>6}  {'A3 ShWR':>7}  "
          f"{'Total%':>7}  {'Incr pp':>8}")
    print(f"{'-' * 115}")
    for rank, (a1t, a1b, a3t, a3b, total_pct, a3) in enumerate(results_sorted, 1):
        if a3 is None:
            print(f"  {rank:3d}  {a3t:>7}  {a3b:>4}  ERR")
            continue
        incr = (total_pct - baseline_pct) if total_pct and baseline_pct else 0
        print(
            f"  {rank:3d}  {a3t:>7}  {a3b:>4}  "
            f"{a3['cap_pnl']:>+8.0f}  {a3['ret_pct']:>+7.2f}%  {a3['ev']:>+7.3f}%  "
            f"{a3['trades']:>9}  {a3['wr']:>6}%  "
            f"{a3['short_pct']:>6}%  {a3['shwr']:>7}%  "
            f"{total_pct:>+7.2f}%  {incr:>+8.2f}pp"
        )
    print(f"{'=' * 115}")


def main():
    # Run baselines for all 3 A1 configs
    print("Running A1-only baselines...", flush=True)
    baselines = {}
    for a1t, a1b in A1_CONFIGS:
        pct, a1_row = run_baseline(a1t, a1b)
        baselines[(a1t, a1b)] = (pct, a1_row)
        print(f"  A1 {a1t}/{a1b}b baseline: {pct:+.2f}%  "
              f"(trades={a1_row['trades']} WR={a1_row['wr']}% sh={a1_row['short_pct']}%)", flush=True)

    # Build all combos: A1 config × A3 time × A3 bars
    combos = [(a1t, a1b, a3t, a3b)
              for (a1t, a1b) in A1_CONFIGS
              for a3t, a3b in product(A3_TIMES, A3_BARS)]
    total = len(combos)
    print(f"\nSweeping {total} M1+A1+A3 combos with {MAX_WORKERS} parallel workers...\n", flush=True)

    # Group results by A1 config
    grouped = {(a1t, a1b): [] for a1t, a1b in A1_CONFIGS}
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(run_one, *c): c for c in combos}
        for fut in as_completed(futures):
            done += 1
            row = fut.result()
            a1t, a1b = row[0], row[1]
            grouped[(a1t, a1b)].append(row)
            a3t, a3b = row[2], row[3]
            total_pct = row[4]
            a3 = row[5]
            base_pct = baselines[(a1t, a1b)][0]
            incr = (total_pct - base_pct) if total_pct and base_pct else 0
            a3_pnl = f"{a3['cap_pnl']:+.0f}" if a3 else "ERR"
            a3_sh = f"{a3['short_pct']}%" if a3 else "-"
            print(f"  [{done:3d}/{total}] A1={a1t}/{a1b}b  A3={a3t}/{a3b}b  "
                  f"total={total_pct:+.2f}%  incr={incr:+.2f}pp  "
                  f"a3_pnl={a3_pnl}  a3_short={a3_sh}", flush=True)

    for (a1t, a1b) in A1_CONFIGS:
        base_pct, base_a1 = baselines[(a1t, a1b)]
        label = f"{a1t}/{a1b}b"
        print_table(label, base_pct, base_a1, grouped[(a1t, a1b)])


if __name__ == "__main__":
    main()
