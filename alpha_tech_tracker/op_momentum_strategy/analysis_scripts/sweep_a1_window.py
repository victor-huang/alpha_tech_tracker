import argparse
import itertools
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

PYTHON = "/Users/victorhuang/.pyenv/versions/alpha_tech_tracker/bin/python"
SCRIPT = "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py"
ENV = {**os.environ, "PYTHONPATH": "/Users/victorhuang/work/alpha_tech_tracker"}
CWD = "/Users/victorhuang/work/alpha_tech_tracker"

_parser = argparse.ArgumentParser()
_parser.add_argument("--start", default="2026-01-01")
_parser.add_argument("--end", default="2026-05-15")
_args, _ = _parser.parse_known_args()

START = _args.start
END = _args.end

# Fixed M1 config
M1_FIXED = [
    "--top", "2", "--weights", "60", "40",
    "--window", "M1", "09:30", "1",
    "--morning-split", "100",
    "--stop-pct", "0.6",
    "--stale-cut-mins", "45", "--stale-cut-threshold", "0.75",
    "--feed", "sip",
    "--start", START, "--end", END,
]

A1_TIMES = ["11:00", "11:30", "12:00", "12:30", "13:00", "13:15", "13:30", "14:00", "14:15", "14:30"]
A1_BARS = [1, 2, 3]

PARALLEL = 15


def run_baseline():
    cmd = [PYTHON, SCRIPT] + M1_FIXED
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=CWD, env=ENV)
    return result.stdout + result.stderr


def run_one(time_, bars):
    cmd = [PYTHON, SCRIPT] + M1_FIXED + ["--window", "A1", time_, str(bars)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=CWD, env=ENV)
    return time_, bars, result.stdout + result.stderr


def parse_total(out):
    # First TOTAL line from weekly breakdown:
    # TOTAL   78  29W/49L   +$1891.32   +18.91%  $11,891.32
    m = re.search(
        r"TOTAL\s+(\d+)\s+(\d+)W/(\d+)L\s+([+\-]\$[\d,]+\.\d+)\s+([+\-][\d.,]+)%\s+\$([\d,]+\.\d+)",
        out,
    )
    if not m:
        return None
    trades = int(m.group(1))
    wins = int(m.group(2))
    ret_pct = float(m.group(5).replace(",", ""))
    portfolio = float(m.group(6).replace(",", ""))
    cap_pnl = portfolio - 10000.0
    win_rate = wins / trades * 100 if trades else 0.0
    return {"trades": trades, "wins": wins, "cap_pnl": cap_pnl, "ret_pct": ret_pct, "win_rate": win_rate}


def parse_a1_row(out):
    # Per-window breakdown row for A1 (now includes Short / Sh% / ShWR columns):
    # A1   11:30   2   sequential   37  17W/20L   46%   +0.515%   +$769.32   +7.69%   10   27%    0%
    m = re.search(
        r"A1\s+(\d+:\d+)\s+(\d+)\s+sequential\s+(\d+)\s+(\d+)W/(\d+)L\s+(\d+)%\s+([+\-][\d.]+)%\s+([+\-]\$[\d,]+\.\d+)\s+([+\-][\d.]+)%\s+(\d+)\s+(\d+)%\s+(\d+)%",
        out,
    )
    if not m:
        return None
    trades = int(m.group(3))
    wins = int(m.group(4))
    win_rate = wins / trades * 100 if trades else 0.0
    ev = float(m.group(7))
    cap_pnl_str = m.group(8).replace("$", "").replace(",", "")
    cap_pnl = float(cap_pnl_str)
    ret_pct = float(m.group(9))
    short_total = int(m.group(10))
    short_pct = int(m.group(11))
    short_wr = int(m.group(12))
    return {
        "trades": trades, "wins": wins, "win_rate": win_rate,
        "ev": ev, "cap_pnl": cap_pnl, "ret_pct": ret_pct,
        "short_total": short_total, "short_pct": short_pct, "short_wr": short_wr,
    }


def print_table(results, baseline_total, title):
    print(f"\n{'=' * 122}")
    print(f"  {title}")
    print(f"  M1 baseline: ret={baseline_total['ret_pct']:+.2f}%  cap_pnl=${baseline_total['cap_pnl']:+,.2f}  trades={baseline_total['trades']}  WR={baseline_total['win_rate']:.1f}%")
    print(f"{'=' * 122}")
    hdr = (
        f"{'Rank':>4}  {'Time':>6}  {'Bars':>4}"
        f"  {'A1 Trd':>6}  {'A1 WR%':>6}  {'A1 EV%':>7}  {'A1 P&L':>10}  {'Shrt':>4}  {'Sh%':>4}  {'ShWR':>4}"
        f"  {'Tot Trd':>7}  {'Tot WR%':>7}  {'Tot Ret%':>9}  {'Tot P&L':>10}  {'Incr':>10}"
    )
    print(hdr)
    print("-" * 122)
    for rank, r in enumerate(results, 1):
        incr = r["total_cap_pnl"] - baseline_total["cap_pnl"]
        print(
            f"{rank:>4}  {r['time']:>6}  {r['bars']:>4}"
            f"  {r['a1_trades']:>6}  {r['a1_wr']:>6.1f}  {r['a1_ev']:>+7.3f}  {r['a1_cap_pnl']:>+10,.2f}"
            f"  {r['a1_short']:>4}  {r['a1_short_pct']:>3}%  {r['a1_short_wr']:>3}%"
            f"  {r['total_trades']:>7}  {r['total_wr']:>7.1f}  {r['total_ret']:>+9.2f}%  {r['total_cap_pnl']:>+10,.2f}  {incr:>+10,.2f}"
        )
    print("=" * 122)


def main():
    print(f"Running M1 baseline ({START} to {END}) ...", flush=True)
    baseline_out = run_baseline()
    baseline_total = parse_total(baseline_out)
    if not baseline_total:
        print("ERROR: could not parse baseline output")
        print(baseline_out[-2000:])
        return
    print(f"  M1 baseline → ret={baseline_total['ret_pct']:+.2f}%  cap_pnl=${baseline_total['cap_pnl']:+,.2f}\n", flush=True)

    combos = list(itertools.product(A1_TIMES, A1_BARS))
    total = len(combos)
    print(f"Running {total} A1 combos with parallelism={PARALLEL} ...\n", flush=True)

    results = []
    done = 0

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futures = {ex.submit(run_one, t, b): (t, b) for t, b in combos}
        for fut in as_completed(futures):
            t, b = futures[fut]
            time_, bars, out = fut.result()
            total_stats = parse_total(out)
            a1_stats = parse_a1_row(out)
            done += 1
            if total_stats and a1_stats:
                incr = total_stats["cap_pnl"] - baseline_total["cap_pnl"]
                results.append({
                    "time": time_,
                    "bars": bars,
                    "a1_trades": a1_stats["trades"],
                    "a1_wr": a1_stats["win_rate"],
                    "a1_ev": a1_stats["ev"],
                    "a1_cap_pnl": a1_stats["cap_pnl"],
                    "a1_short": a1_stats["short_total"],
                    "a1_short_pct": a1_stats["short_pct"],
                    "a1_short_wr": a1_stats["short_wr"],
                    "total_trades": total_stats["trades"],
                    "total_wr": total_stats["win_rate"],
                    "total_ret": total_stats["ret_pct"],
                    "total_cap_pnl": total_stats["cap_pnl"],
                })
                print(
                    f"  [{done}/{total}] A1 {time_} bars={bars}"
                    f" → A1: {a1_stats['ev']:+.3f}% EV  {a1_stats['cap_pnl']:+,.2f}"
                    f"  short={a1_stats['short_total']}({a1_stats['short_pct']}%)"
                    f"  | Total: {total_stats['ret_pct']:+.2f}%  incr={incr:+,.2f}",
                    flush=True,
                )
            else:
                print(f"  [{done}/{total}] A1 {time_} bars={bars} → PARSE ERROR", flush=True)

    # Sort by total cap P&L descending
    results.sort(key=lambda r: r["total_cap_pnl"], reverse=True)
    print_table(results, baseline_total, f"A1 WINDOW SWEEP — {START} to {END}  |  M1: 09:30/1 stop=0.60 stale=45min/0.75%")

    # Also show sorted by A1 incremental contribution
    results_by_incr = sorted(results, key=lambda r: r["a1_cap_pnl"], reverse=True)
    print(f"\nTop 5 by A1 incremental P&L:")
    for r in results_by_incr[:5]:
        incr = r["total_cap_pnl"] - baseline_total["cap_pnl"]
        print(
            f"  --window A1 {r['time']} {r['bars']}"
            f"  → A1 P&L={r['a1_cap_pnl']:+,.2f}  EV={r['a1_ev']:+.3f}%  WR={r['a1_wr']:.0f}%"
            f"  short={r['a1_short']}({r['a1_short_pct']}% ShWR={r['a1_short_wr']}%)"
            f"  | Total ret={r['total_ret']:+.2f}%  incr={incr:+,.2f}"
        )

    print(f"\nTop 5 by total return:")
    for r in results[:5]:
        incr = r["total_cap_pnl"] - baseline_total["cap_pnl"]
        print(
            f"  --window A1 {r['time']} {r['bars']}"
            f"  → A1 P&L={r['a1_cap_pnl']:+,.2f}  EV={r['a1_ev']:+.3f}%  WR={r['a1_wr']:.0f}%"
            f"  short={r['a1_short']}({r['a1_short_pct']}% ShWR={r['a1_short_wr']}%)"
            f"  | Total ret={r['total_ret']:+.2f}%  incr={incr:+,.2f}"
        )


if __name__ == "__main__":
    main()
