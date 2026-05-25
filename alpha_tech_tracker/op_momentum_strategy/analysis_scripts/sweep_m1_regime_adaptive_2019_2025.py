"""Backtest M1=5 stop=0.5 --regime-adaptive across 2019-2025 in parallel."""
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"
YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]


def _run_year(year: int):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
        "--top", "2",
        "--window", "M1", "09:30", "5",
        "--bearish-reentry", "--bullish-reentry", "--reversal",
        "--feed", "sip",
        "--min-hold-bars", "1",
        "--stop-pct", "0.5",
        "--regime-adaptive",
        "--start", f"{year}-01-01", "--end", f"{year}-12-31",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = result.stdout

    pnl = ret = trades = wins = qqq_ret = None
    m = re.search(r"TOTAL\s+(\d+)\s+(\d+)W/(\d+)L\s+([+-]?\$[\d,]+\.\d+)\s+([+-]?\d+\.\d+)%", out)
    if m:
        trades = int(m.group(1)); wins = int(m.group(2))
        pnl = float(m.group(4).replace("$", "").replace(",", ""))
        ret = float(m.group(5))
    qqq_matches = re.findall(r"TOTAL\s+([+-]?\$[\d,]+\.\d+)\s+([+-]?\d+\.\d+)%", out)
    if qqq_matches:
        qqq_ret = float(qqq_matches[-1][1])

    # Parse regime bucket breakdown
    buckets = []
    in_block = False
    for line in out.splitlines():
        if "Regime Adaptive" in line and "Distribution" in line:
            in_block = True
            continue
        if in_block:
            if line.strip().startswith("─"):
                continue
            if line.strip().startswith("Bucket"):
                continue
            if not line.strip():
                in_block = False
                continue
            # parse: vix_hi_ma_strong  13(14%)   25     32%     $-251
            bm = re.match(r"\s*(\S+)\s+(\d+)\((\d+)%\)\s+(\d+)\s+(\S+)\s+\$([+-]?[\d,]+)", line)
            if bm:
                buckets.append({
                    "name": bm.group(1),
                    "days": int(bm.group(2)),
                    "trades": int(bm.group(4)),
                    "wr": bm.group(5),
                    "pnl": int(bm.group(6).replace(",", "")),
                })

    return {
        "year": year, "pnl": pnl, "return_pct": ret,
        "trades": trades, "wr": (wins / trades * 100) if trades else None,
        "qqq_return_pct": qqq_ret, "buckets": buckets,
        "stderr": result.stderr[-300:] if pnl is None else None,
    }


def main():
    print(f"Backtesting M1=5 stop=0.5 --regime-adaptive for years {YEARS} in parallel...\n", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=len(YEARS)) as ex:
        futures = {ex.submit(_run_year, y): y for y in YEARS}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if r["pnl"] is not None:
                vs = r["return_pct"] - (r["qqq_return_pct"] or 0)
                print(f"  {r['year']}: ${r['pnl']:+,.0f} ({r['return_pct']:+.2f}%) | {r['trades']}tr {r['wr']:.1f}%WR | QQQ {r['qqq_return_pct']:+.2f}% (vs {vs:+.2f}pp)", flush=True)
            else:
                print(f"  {r['year']}: ERR — {r['stderr']}", flush=True)

    results.sort(key=lambda r: r["year"])
    print("\n" + "=" * 95)
    print("YEARLY SUMMARY — M1=5 stop=0.5 --regime-adaptive")
    print("=" * 95)
    print(f"  {'Year':<6} {'P&L':>12} {'Return':>9} {'Trades':>7} {'WR%':>6} {'QQQ B&H':>9}  vs QQQ")
    tot = 0.0
    for r in results:
        if r["pnl"] is None:
            print(f"  {r['year']:<6} ERR")
            continue
        delta = r["return_pct"] - (r["qqq_return_pct"] or 0)
        tot += r["pnl"]
        print(f"  {r['year']:<6} ${r['pnl']:>+11,.0f} {r['return_pct']:>+8.2f}% {r['trades']:>7} {r['wr']:>5.1f}% {r['qqq_return_pct']:>+8.2f}% {delta:>+6.2f}pp")
    print("-" * 95)
    print(f"  {'TOTAL':<6} ${tot:>+11,.0f}  (7-year sum, no compounding)")
    print("=" * 95)

    print("\nBucket breakdown by year (P&L):")
    print(f"  {'Year':<6} {'vix_hi_str':>11} {'vix_hi_wk':>11} {'vix_mid_str':>12} {'vix_mid_wk':>11}")
    for r in results:
        if not r["buckets"]:
            continue
        b = {x["name"]: x["pnl"] for x in r["buckets"]}
        print(f"  {r['year']:<6} ${b.get('vix_hi_ma_strong', 0):>+10,} ${b.get('vix_hi_ma_weak', 0):>+10,} ${b.get('vix_mid_ma_strong', 0):>+11,} ${b.get('vix_mid_ma_weak', 0):>+10,}")


if __name__ == "__main__":
    main()
