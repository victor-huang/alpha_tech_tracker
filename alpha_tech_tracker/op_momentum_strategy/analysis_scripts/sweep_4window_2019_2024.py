"""Backtest 4-window config M1=3 A1=3 A2=3 A3=3 stop=0.9 across years 2019-2024 in parallel."""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"
YEARS = [2019, 2020, 2021, 2022, 2023, 2024]


def _run_year(year: int):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
        "--top", "2",
        "--window", "M1", "09:30", "3",
        "--window", "A1", "10:00", "3",
        "--window", "A2", "10:30", "3",
        "--window", "A3", "11:00", "3",
        "--bearish-reentry", "--bullish-reentry", "--reversal",
        "--feed", "sip",
        "--min-hold-bars", "1",
        "--stop-pct", "0.9",
        "--start", f"{year}-01-01", "--end", f"{year}-12-31",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = result.stdout

    pnl = ret = trades = wins = losses = None
    qqq_ret = None

    matches = re.findall(r"TOTAL\s+(\d+)\s+(\d+)W/(\d+)L\s+([+-]?\$[\d,]+\.\d+)\s+([+-]?\d+\.\d+)%", out)
    if matches:
        trades, wins, losses, pnl_s, ret_s = matches[0]
        pnl = float(pnl_s.replace("$", "").replace(",", ""))
        ret = float(ret_s)
        trades = int(trades); wins = int(wins); losses = int(losses)

    # QQQ b&h appears in a later TOTAL line with just P&L + return
    qqq_matches = re.findall(r"TOTAL\s+([+-]?\$[\d,]+\.\d+)\s+([+-]?\d+\.\d+)%", out)
    if qqq_matches:
        # Last one is typically QQQ b&h total
        qqq_ret = float(qqq_matches[-1][1])

    return {
        "year": year, "pnl": pnl, "return_pct": ret,
        "trades": trades, "wins": wins, "losses": losses,
        "wr": (wins / trades * 100) if trades else None,
        "qqq_return_pct": qqq_ret,
        "stderr": result.stderr[-200:] if pnl is None else None,
    }


def main():
    print(f"Backtesting M1=3 A1=3 A2=3 A3=3 stop=0.9 for years {YEARS} in parallel...\n", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=len(YEARS)) as ex:
        futures = {ex.submit(_run_year, y): y for y in YEARS}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if r["pnl"] is not None:
                print(f"  {r['year']}: ${r['pnl']:+,.0f} ({r['return_pct']:+.2f}%) | {r['trades']}tr {r['wr']:.1f}%WR | QQQ {r['qqq_return_pct']:+.2f}%", flush=True)
            else:
                print(f"  {r['year']}: ERR — {r['stderr']}", flush=True)

    results.sort(key=lambda r: r["year"])
    print("\n" + "=" * 90)
    print("YEARLY SUMMARY — M1=3 A1=3 A2=3 A3=3 stop=0.9")
    print("=" * 90)
    print(f"  {'Year':<6} {'P&L':>12} {'Return':>9} {'Trades':>7} {'WR%':>6} {'QQQ B&H':>9}  vs QQQ")
    tot_pnl = 0.0
    for r in results:
        if r["pnl"] is None:
            print(f"  {r['year']:<6} ERR")
            continue
        delta = r["return_pct"] - r["qqq_return_pct"]
        tot_pnl += r["pnl"]
        print(f"  {r['year']:<6} ${r['pnl']:>+11,.0f} {r['return_pct']:>+8.2f}% {r['trades']:>7} {r['wr']:>5.1f}% {r['qqq_return_pct']:>+8.2f}% {delta:>+6.2f}pp")
    print("-" * 90)
    print(f"  {'TOTAL':<6} ${tot_pnl:>+11,.0f}  (6-year sum, no compounding)")
    print("=" * 90)


if __name__ == "__main__":
    main()
