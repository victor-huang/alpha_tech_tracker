#!/usr/bin/env python3
"""
Run trade engine replay for all trading days in a given year (or date range).
Strategy:
  1. Run one representative day per month sequentially to warm the bar cache.
  2. Run all remaining days in parallel (default 8 workers).
  3. Save per-day logs, then print daily / weekly / monthly P&L, streaks, top-10.

Usage:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
      python run_replay_year.py --year 2024 [--force]

    python run_replay_year.py --start 2025-01-01 --end 2025-06-30 [--force]

  --force   re-run dates that already have a saved log
"""

import argparse
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
LOG_BASE = "/Users/victorhuang/work/alpha_tech_tracker/logs"

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

# NYSE holidays by year (add new years as needed)
_HOLIDAYS = {
    2024: {
        date(2024, 1, 1),   # New Year's Day
        date(2024, 1, 15),  # MLK Day
        date(2024, 2, 19),  # Presidents' Day
        date(2024, 3, 29),  # Good Friday
        date(2024, 5, 27),  # Memorial Day
        date(2024, 6, 19),  # Juneteenth
        date(2024, 7, 4),   # Independence Day
        date(2024, 9, 2),   # Labor Day
        date(2024, 11, 28), # Thanksgiving
        date(2024, 12, 25), # Christmas
    },
    2025: {
        date(2025, 1, 1),   # New Year's Day
        date(2025, 1, 20),  # MLK Day
        date(2025, 2, 17),  # Presidents' Day
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 26),  # Memorial Day
        date(2025, 6, 19),  # Juneteenth
        date(2025, 7, 4),   # Independence Day
        date(2025, 9, 1),   # Labor Day
        date(2025, 11, 27), # Thanksgiving
        date(2025, 12, 25), # Christmas
    },
    2026: {
        date(2026, 1, 1),   # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents' Day
        date(2026, 4, 3),   # Good Friday
    },
}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _holidays(year: int) -> set:
    return _HOLIDAYS.get(year, set())


def trading_days(start: date, end: date) -> list:
    days, d = [], start
    holidays = _holidays(start.year) | _holidays(end.year)
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            days.append(d)
        d += timedelta(days=1)
    return days


def iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _warmup_day_for_month(days_in_month: list) -> date:
    """Pick the last trading day of the month as the cache-warm representative."""
    return days_in_month[-1]


# ── P&L parsing ─────────────────────────────────────────────────────────────────

_CAP_PAT = re.compile(r"cap:\s*[+-]\$([0-9,]+\.[0-9]+)\s*\(([+-][0-9.]+)%\)")
_DAILY_PAT = re.compile(r"Daily P&L:\s*([+-])\$([0-9,]+\.[0-9]+)")


def _parse_pnl(output: str):
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

def run_replay(d: date, log_dir: str, force: bool = False):
    log_path = os.path.join(log_dir, f"replay_{d.isoformat()}.log")
    if not force and os.path.exists(log_path):
        with open(log_path) as f:
            content = f.read()
        cap_pnl, cap_pct = _parse_pnl(content)
        return d, cap_pnl, cap_pct, log_path, True

    cmd = BASE_CMD + ["--replay-date", d.isoformat()]
    full_env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    result = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
    combined = result.stdout + result.stderr

    with open(log_path, "w") as f:
        f.write(combined)

    cap_pnl, cap_pct = _parse_pnl(combined)
    return d, cap_pnl, cap_pct, log_path, False


# ── Stats ────────────────────────────────────────────────────────────────────────

def _streaks(days, results):
    best_win, best_loss = [], []
    cur_win, cur_loss = [], []
    for d in days:
        pnl = results[d][0]
        if pnl > 0:
            cur_win.append(d)
            if cur_loss:
                if len(cur_loss) > len(best_loss):
                    best_loss = cur_loss[:]
                cur_loss = []
        elif pnl < 0:
            cur_loss.append(d)
            if cur_win:
                if len(cur_win) > len(best_win):
                    best_win = cur_win[:]
                cur_win = []
        else:
            if len(cur_win) > len(best_win):
                best_win = cur_win[:]
            if len(cur_loss) > len(best_loss):
                best_loss = cur_loss[:]
            cur_win, cur_loss = [], []
    if len(cur_win) > len(best_win):
        best_win = cur_win[:]
    if len(cur_loss) > len(best_loss):
        best_loss = cur_loss[:]
    return best_win, best_loss


def print_and_save_results(results: dict, log_dir: str, label: str):
    days = sorted(results)

    lines = []
    def p(s=""):
        print(s)
        lines.append(s)

    p(f"Replay config: options | M1+A1+A2 | bearish/bullish-reentry | reversal | "
      f"doubledown | rank-weighted 60/40 | top-2 | $10k")
    p(f"Period: {label}  |  {len(days)} trading days")

    # ── Daily ────────────────────────────────────────────────────────────────
    p("\n" + "=" * 72)
    p("DAILY P&L")
    p("=" * 72)
    for d in days:
        pnl, pct = results[d]
        sign = "+" if pnl >= 0 else ""
        pct_str = f"  {'+' if pct and pct >= 0 else ''}{pct:.2f}%" if pct else ""
        p(f"  {d}  {sign}${pnl:8,.2f}{pct_str}")

    # ── Weekly ───────────────────────────────────────────────────────────────
    weeks = defaultdict(float)
    week_dates = defaultdict(list)
    for d in days:
        w = iso_week(d)
        weeks[w] += results[d][0]
        week_dates[w].append(d)

    p("\n" + "=" * 72)
    p("WEEKLY P&L")
    p("=" * 72)
    for w in sorted(weeks):
        pnl = weeks[w]
        sign = "+" if pnl >= 0 else ""
        first, last = week_dates[w][0], week_dates[w][-1]
        marker = "  ◀ LOSS" if pnl < 0 else ""
        p(f"  {w}  ({first} → {last})  {sign}${pnl:8,.2f}{marker}")

    # ── Monthly ──────────────────────────────────────────────────────────────
    months = defaultdict(float)
    for d in days:
        months[d.strftime("%Y-%m")] += results[d][0]

    p("\n" + "=" * 72)
    p("MONTHLY P&L")
    p("=" * 72)
    for m in sorted(months):
        pnl = months[m]
        sign = "+" if pnl >= 0 else ""
        p(f"  {m}  {sign}${pnl:8,.2f}")

    # ── Top-10 ───────────────────────────────────────────────────────────────
    sorted_days = sorted(results.items(), key=lambda x: x[1][0])
    worst_10 = sorted_days[:10]
    best_10 = sorted_days[-10:][::-1]

    p("\n" + "=" * 72)
    p("TOP-10 BEST DAYS")
    p("=" * 72)
    for rank, (d, (pnl, pct)) in enumerate(best_10, 1):
        sign = "+" if pnl >= 0 else ""
        pct_str = f"  ({'+' if pct and pct >= 0 else ''}{pct:.2f}%)" if pct else ""
        p(f"  #{rank:2d}  {d}  {sign}${pnl:8,.2f}{pct_str}")

    p("\n" + "=" * 72)
    p("TOP-10 WORST DAYS")
    p("=" * 72)
    for rank, (d, (pnl, pct)) in enumerate(worst_10, 1):
        sign = "+" if pnl >= 0 else ""
        pct_str = f"  ({pct:.2f}%)" if pct else ""
        p(f"  #{rank:2d}  {d}  {sign}${pnl:8,.2f}{pct_str}")

    # ── Streaks ───────────────────────────────────────────────────────────────
    best_win, best_loss = _streaks(days, results)

    p("\n" + "=" * 72)
    p(f"LONGEST WINNING STREAK: {len(best_win)} days")
    p("=" * 72)
    for d in best_win:
        pnl, pct = results[d]
        pct_str = f"  (+{pct:.2f}%)" if pct else ""
        p(f"  {d}  +${pnl:8,.2f}{pct_str}")
    if best_win:
        p(f"  Streak P&L: +${sum(results[d][0] for d in best_win):,.2f}")

    p("\n" + "=" * 72)
    p(f"LONGEST LOSING STREAK:  {len(best_loss)} days")
    p("=" * 72)
    for d in best_loss:
        pnl, pct = results[d]
        pct_str = f"  ({pct:.2f}%)" if pct else ""
        p(f"  {d}   ${pnl:8,.2f}{pct_str}")
    if best_loss:
        p(f"  Streak P&L: ${sum(results[d][0] for d in best_loss):,.2f}")

    # ── Totals ────────────────────────────────────────────────────────────────
    total = sum(v[0] for v in results.values())
    win_days = sum(1 for v in results.values() if v[0] > 0)
    loss_days = sum(1 for v in results.values() if v[0] < 0)

    p("\n" + "=" * 72)
    p("TOTALS")
    p("=" * 72)
    sign = "+" if total >= 0 else ""
    p(f"  Total P&L    : {sign}${total:,.2f}  ({sign}{total / 10000 * 100:.2f}% on $10k)")
    p(f"  Trading days : {len(results)}  (win: {win_days}  loss: {loss_days})")
    if win_days + loss_days > 0:
        p(f"  Win rate     : {win_days / (win_days + loss_days) * 100:.1f}%")
    p(f"  Logs saved to: {log_dir}/")
    p("=" * 72)

    # Save results to file
    result_file = os.path.join(log_dir, "RESULTS.txt")
    with open(result_file, "w") as f:
        f.write("\n".join(lines))
    print(f"\nResults saved to: {result_file}")


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Full calendar year to replay")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Re-run even if log exists")
    args = parser.parse_args()

    if args.year:
        start = date(args.year, 1, 1)
        end = date(args.year, 12, 31)
        log_dir = os.path.join(LOG_BASE, f"replay_{args.year}")
        label = str(args.year)
    elif args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        log_dir = os.path.join(LOG_BASE, f"replay_{start}_{end}")
        label = f"{start} → {end}"
    else:
        parser.error("Provide --year or --start + --end")

    os.makedirs(log_dir, exist_ok=True)
    days = trading_days(start, end)

    print(f"Replay config: options | M1+A1+A2 | bearish/bullish-reentry | reversal | "
          f"doubledown | rank-weighted 60/40 | top-2 | $10k")
    print(f"Period: {label}  |  {len(days)} trading days  |  logs → {log_dir}")

    # Partition into warmup (one per month) and remainder
    by_month = defaultdict(list)
    for d in days:
        by_month[(d.year, d.month)].append(d)

    warmup_days = [_warmup_day_for_month(v) for v in sorted(by_month.values())]
    warmup_set = set(warmup_days)
    remaining = [d for d in days if d not in warmup_set]

    # Skip warmup days that already have logs (unless --force)
    warmup_todo = [d for d in warmup_days if args.force or not os.path.exists(
        os.path.join(log_dir, f"replay_{d.isoformat()}.log"))]

    print(f"\n── Phase 1: cache warmup ({len(warmup_days)} days, 1 per month, sequential) ──")
    results = {}

    for d in warmup_days:
        if d not in [x for x in warmup_todo] and not args.force:
            log_path = os.path.join(log_dir, f"replay_{d.isoformat()}.log")
            if os.path.exists(log_path):
                with open(log_path) as f:
                    content = f.read()
                pnl, pct = _parse_pnl(content)
                results[d] = (pnl, pct)
                sign = "+" if pnl >= 0 else ""
                print(f"  skip {d}  {sign}${pnl:,.2f} [cached]", flush=True)
                continue
        d2, pnl, pct, _, cached = run_replay(d, log_dir, args.force)
        results[d2] = (pnl, pct)
        sign = "+" if pnl >= 0 else ""
        tag = " [cached]" if cached else ""
        print(f"  done {d}  {sign}${pnl:,.2f}{tag}", flush=True)

    print(f"\n── Phase 2: {len(remaining)} remaining days ({PARALLELISM} parallel) ──")
    completed = 0
    with ThreadPoolExecutor(max_workers=PARALLELISM) as pool:
        futures = {pool.submit(run_replay, d, log_dir, args.force): d for d in remaining}
        for fut in as_completed(futures):
            d, pnl, pct, _, cached = fut.result()
            results[d] = (pnl, pct)
            completed += 1
            sign = "+" if pnl >= 0 else ""
            pct_str = f" ({'+' if pct and pct >= 0 else ''}{pct:.2f}%)" if pct else ""
            tag = " [cached]" if cached else ""
            print(f"  [{completed:3d}/{len(remaining)}] {d}  {sign}${pnl:8,.2f}{pct_str}{tag}",
                  flush=True)

    print_and_save_results(results, log_dir, label)


if __name__ == "__main__":
    main()
