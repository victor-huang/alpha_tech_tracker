#!/usr/bin/env python3
"""
Run trade engine replay for all 2026 trading days through Apr 21.
Runs 8 dates in parallel, saves per-day logs, and prints a summary
broken down by week/month with top-10 best and worst days.

Usage:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
      python run_2026_replay.py [--force]

  --force  re-run dates that already have a log file
"""

import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

# ── Configuration ──────────────────────────────────────────────────────────────
PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"
PYTHON = "/Users/victorhuang/.pyenv/versions/alpha_tech_tracker/bin/python"
PARALLELISM = 8
LOG_DIR = "/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2026_ytd"

BASE_CMD = [
    PYTHON, "-m",
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine",
    "run",
    "--log-level", "DEBUG",
    "--trade-type", "options",
    "--window", "M1", "09:30", "3",
    "--window", "A1", "13:15", "1",
    "--window", "A2", "15:00", "1",
    "--morning-split", "100",
    "--bearish-reentry",
    "--bullish-reentry",
    "--reversal",
    "--rank-weighted-sizing", "60", "40",
    "--doubledown",
    "--top", "2",
    "--capital", "10000",
    "--mock-trade-execution",
]

# 2026 NYSE market holidays through April 21
MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
}

START_DATE = date(2026, 1, 2)
END_DATE = date(2026, 4, 21)

# ── Helpers ─────────────────────────────────────────────────────────────────────

def trading_days(start: date, end: date):
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in MARKET_HOLIDAYS_2026:
            days.append(d)
        d += timedelta(days=1)
    return days


def iso_week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ── P&L parsing ─────────────────────────────────────────────────────────────────

_CAP_PAT = re.compile(
    r"cap:\s*[+-]\$([0-9,]+\.[0-9]+)\s*\(([+-][0-9.]+)%\)"
)
_DAILY_PAT = re.compile(
    r"Daily P&L:\s*([+-])\$([0-9,]+\.[0-9]+)"
)


def _parse_pnl(output: str):
    """
    Return (cap_pnl_usd, cap_pnl_pct).
    Prefers the 'cap:' line; falls back to 'Daily P&L:'; returns (0.0, 0.0) on no trades.
    """
    cap_matches = _CAP_PAT.findall(output)
    if cap_matches:
        usd_str, pct_str = cap_matches[-1]
        usd = float(usd_str.replace(",", ""))
        pct = float(pct_str)
        last_cap_lines = [l for l in output.splitlines() if "cap:" in l]
        if last_cap_lines and "cap: -" in last_cap_lines[-1]:
            usd = -usd
        return usd, pct

    daily_matches = _DAILY_PAT.findall(output)
    if daily_matches:
        sign, usd_str = daily_matches[-1]
        usd = float(usd_str.replace(",", ""))
        if sign == "-":
            usd = -usd
        return usd, None

    return 0.0, 0.0


# ── Run one replay ───────────────────────────────────────────────────────────────

def run_replay(d: date, force: bool = False):
    """Run a single replay date; return (date, cap_pnl, cap_pct, log_path)."""
    log_path = os.path.join(LOG_DIR, f"replay_{d.isoformat()}.log")

    if not force and os.path.exists(log_path):
        with open(log_path) as f:
            content = f.read()
        cap_pnl, cap_pct = _parse_pnl(content)
        return d, cap_pnl, cap_pct, log_path, True  # cached=True

    cmd = BASE_CMD + ["--replay-date", d.isoformat()]
    full_env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    result = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
    combined = result.stdout + result.stderr

    with open(log_path, "w") as f:
        f.write(combined)

    cap_pnl, cap_pct = _parse_pnl(combined)
    return d, cap_pnl, cap_pct, log_path, False  # cached=False


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    force = "--force" in sys.argv
    os.makedirs(LOG_DIR, exist_ok=True)

    days = trading_days(START_DATE, END_DATE)
    print(f"Replay config: options | M1+A1+A2 | bearish/bullish-reentry | reversal | "
          f"doubledown | rank-weighted 60/40 | top-2 | $10k")
    print(f"Running {len(days)} trading days ({START_DATE} → {END_DATE}), "
          f"{PARALLELISM} in parallel …\n")

    results = {}  # date → (cap_pnl, cap_pct)

    with ThreadPoolExecutor(max_workers=PARALLELISM) as pool:
        futures = {pool.submit(run_replay, d, force): d for d in days}
        completed = 0
        for fut in as_completed(futures):
            d, cap_pnl, cap_pct, log_path, cached = fut.result()
            results[d] = (cap_pnl, cap_pct)
            completed += 1
            sign = "+" if cap_pnl >= 0 else ""
            pct_str = (
                f" ({'+' if cap_pct and cap_pct >= 0 else ''}{cap_pct:.2f}%)"
                if cap_pct is not None else ""
            )
            cached_tag = " [cached]" if cached else ""
            print(
                f"[{completed:3d}/{len(days)}] {d}  {sign}${cap_pnl:8,.2f}{pct_str}{cached_tag}",
                flush=True,
            )

    # ── Daily ────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("DAILY P&L")
    print("=" * 72)
    for d in sorted(results):
        cap_pnl, cap_pct = results[d]
        sign = "+" if cap_pnl >= 0 else ""
        pct_str = f"  {'+' if cap_pct and cap_pct >= 0 else ''}{cap_pct:.2f}%" if cap_pct is not None else ""
        print(f"  {d}  {sign}${cap_pnl:8,.2f}{pct_str}")

    # ── Weekly ───────────────────────────────────────────────────────────────────
    weeks: dict = defaultdict(float)
    week_dates: dict = defaultdict(list)
    for d in sorted(results):
        w = iso_week_label(d)
        weeks[w] += results[d][0]
        week_dates[w].append(d)

    print("\n" + "=" * 72)
    print("WEEKLY P&L")
    print("=" * 72)
    for w in sorted(weeks):
        pnl = weeks[w]
        sign = "+" if pnl >= 0 else ""
        first, last = week_dates[w][0], week_dates[w][-1]
        print(f"  {w}  ({first} → {last})  {sign}${pnl:8,.2f}")

    # ── Monthly ──────────────────────────────────────────────────────────────────
    months: dict = defaultdict(float)
    for d in sorted(results):
        m = d.strftime("%Y-%m")
        months[m] += results[d][0]

    print("\n" + "=" * 72)
    print("MONTHLY P&L")
    print("=" * 72)
    for m in sorted(months):
        pnl = months[m]
        sign = "+" if pnl >= 0 else ""
        print(f"  {m}  {sign}${pnl:8,.2f}")

    # ── Top-10 best / worst days ─────────────────────────────────────────────────
    sorted_days = sorted(results.items(), key=lambda x: x[1][0])
    worst_10 = sorted_days[:10]
    best_10 = sorted_days[-10:][::-1]

    print("\n" + "=" * 72)
    print("TOP-10 BEST DAYS")
    print("=" * 72)
    for rank, (d, (pnl, pct)) in enumerate(best_10, 1):
        sign = "+" if pnl >= 0 else ""
        pct_str = f"  (+{pct:.2f}%)" if pct and pct >= 0 else (f"  ({pct:.2f}%)" if pct else "")
        print(f"  #{rank:2d}  {d}  {sign}${pnl:8,.2f}{pct_str}")

    print("\n" + "=" * 72)
    print("TOP-10 WORST DAYS")
    print("=" * 72)
    for rank, (d, (pnl, pct)) in enumerate(worst_10, 1):
        sign = "+" if pnl >= 0 else ""
        pct_str = f"  ({pct:.2f}%)" if pct is not None else ""
        print(f"  #{rank:2d}  {d}  {sign}${pnl:8,.2f}{pct_str}")

    # ── Totals ───────────────────────────────────────────────────────────────────
    total = sum(v[0] for v in results.values())
    total_pct = total / 10000 * 100
    win_days = sum(1 for v in results.values() if v[0] > 0)
    loss_days = sum(1 for v in results.values() if v[0] < 0)
    zero_days = sum(1 for v in results.values() if v[0] == 0)

    print("\n" + "=" * 72)
    print("TOTALS")
    print("=" * 72)
    sign = "+" if total >= 0 else ""
    print(f"  Total P&L    : {sign}${total:,.2f}  ({sign}{total_pct:.2f}% on $10k)")
    print(f"  Trading days : {len(results)}  (win: {win_days}  loss: {loss_days}  no-trade: {zero_days})")
    if win_days + loss_days > 0:
        print(f"  Win rate     : {win_days / (win_days + loss_days) * 100:.1f}%")
    print(f"  Logs saved to: {LOG_DIR}/")
    print("=" * 72)


if __name__ == "__main__":
    main()
