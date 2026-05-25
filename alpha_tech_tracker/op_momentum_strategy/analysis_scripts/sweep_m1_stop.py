import itertools
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

PYTHON = "/Users/victorhuang/.pyenv/versions/alpha_tech_tracker/bin/python"
SCRIPT = "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py"
ENV = {**os.environ, "PYTHONPATH": "/Users/victorhuang/work/alpha_tech_tracker"}

START = "2026-03-01"
END = "2026-05-15"

TIMES = ["09:30", "09:35"]
BARS = [1, 2, 3, 4, 5]
STOP_PCTS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]

PARALLEL = 20


def run_one(time_, bars, stop_pct):
    cmd = [
        PYTHON, SCRIPT,
        "--start", START, "--end", END,
        "--top", "2", "--weights", "60", "40",
        "--window", "M1", time_, str(bars),
        "--stop-pct", str(stop_pct),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd="/Users/victorhuang/work/alpha_tech_tracker", env=ENV
    )
    out = result.stdout + result.stderr
    return time_, bars, stop_pct, out


def parse(time_, bars, stop_pct, out):
    # Parse cap P&L TOTAL line: "  TOTAL  106  43W/63L  +$1713.82  +17.14%  $11,713.82"
    m = re.search(
        r"TOTAL\s+(\d+)\s+(\d+)W/(\d+)L\s+[+\-]\$[\d,]+\.\d+\s+([+\-][\d.,]+)%\s+\$([\d,]+\.\d+)",
        out,
    )
    if not m:
        return None

    trades = int(m.group(1))
    wins = int(m.group(2))
    losses = int(m.group(3))
    ret_pct = float(m.group(4))
    portfolio = float(m.group(5).replace(",", ""))
    cap_pnl = portfolio - 10000.0
    win_rate = wins / trades * 100 if trades else 0.0

    avg_win = _find_float(out, r"Avg win\s+%\s+:\s+([+\-][\d.]+)%")
    avg_loss = _find_float(out, r"Avg loss\s+%\s+:\s+([+\-][\d.]+)%")

    sm = re.search(r"Short trades\s+:\s+(\d+)\s+\(≤15 min\)\s+WR:\s+(\d+)%", out)
    short_total = int(sm.group(1)) if sm else 0
    short_wr = int(sm.group(2)) if sm else 0

    return {
        "time": time_,
        "bars": bars,
        "stop_pct": stop_pct,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "cap_pnl": cap_pnl,
        "ret_pct": ret_pct,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "short_total": short_total,
        "short_wr": short_wr,
    }


def _find_float(text, pattern):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else float("nan")


def main():
    combos = list(itertools.product(TIMES, BARS, STOP_PCTS))
    total = len(combos)
    print(f"Running {total} combos with parallelism={PARALLEL} ...\n", flush=True)

    results = []
    done = 0

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futures = {ex.submit(run_one, t, b, s): (t, b, s) for t, b, s in combos}
        for fut in as_completed(futures):
            t, b, s = futures[fut]
            time_, bars, stop_pct, out = fut.result()
            row = parse(time_, bars, stop_pct, out)
            done += 1
            if row:
                results.append(row)
                print(f"  [{done}/{total}] {time_} bars={bars} stop={stop_pct:.2f} → {row['ret_pct']:+.2f}%  cap_pnl=${row['cap_pnl']:+,.2f}", flush=True)
            else:
                print(f"  [{done}/{total}] {time_} bars={bars} stop={stop_pct:.2f} → PARSE ERROR", flush=True)

    results.sort(key=lambda r: r["cap_pnl"], reverse=True)

    print("\n")
    print("=" * 106)
    print(f"  SWEEP RESULTS — {START} to {END}  |  --top 2 --weights 60 40")
    print("=" * 106)
    hdr = (
        f"{'Rank':>4}  {'Time':>6}  {'Bars':>4}  {'Stop':>5}  {'Trades':>6}  {'WR%':>5}"
        f"  {'AvgW%':>6}  {'AvgL%':>6}  {'Cap P&L':>10}  {'Ret%':>7}"
        f"  {'Short':>5}  {'Sh%':>4}  {'Short/All':>9}"
    )
    print(hdr)
    print("-" * 106)
    for rank, r in enumerate(results, 1):
        short_pct = r["short_total"] / r["trades"] * 100 if r["trades"] else 0
        print(
            f"{rank:>4}  {r['time']:>6}  {r['bars']:>4}  {r['stop_pct']:>5.2f}"
            f"  {r['trades']:>6}  {r['win_rate']:>5.1f}"
            f"  {r['avg_win']:>+6.2f}  {r['avg_loss']:>+6.2f}"
            f"  {r['cap_pnl']:>+10,.2f}  {r['ret_pct']:>+7.2f}%"
            f"  {r['short_total']:>5}  {r['short_wr']:>3}%  {short_pct:>8.0f}%"
        )
    print("=" * 106)
    print(f"\nTop 5 configs:")
    for r in results[:5]:
        short_pct = r["short_total"] / r["trades"] * 100 if r["trades"] else 0
        print(
            f"  --window M1 {r['time']} {r['bars']} --stop-pct {r['stop_pct']:.2f}"
            f"  →  {r['ret_pct']:+.2f}%  WR={r['win_rate']:.0f}%  trades={r['trades']}"
            f"  short={r['short_total']} ({short_pct:.0f}%)  short-WR={r['short_wr']}%"
        )


if __name__ == "__main__":
    main()
