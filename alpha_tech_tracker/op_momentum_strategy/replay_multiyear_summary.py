#!/usr/bin/env python3
"""
Multi-year options replay P&L summary.

Usage:
  python replay_multiyear_summary.py [--years 2021 2022 ...] [--trade-type options|stock]

Produces:
  - Per-year monthly + annual breakdown
  - Cross-year weekly table
  - Top-5 best / worst weeks
  - Longest winning / losing week streaks
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

BASE_LOG_DIR = "/Users/victorhuang/work/alpha_tech_tracker/logs"
CAPITAL = 10_000.0


def load_year(year: int, trade_type: str) -> dict[str, float]:
    """Return {date_str: pnl} from replay log dir for one year."""
    log_dir = os.path.join(BASE_LOG_DIR, f"replay_{year}_{trade_type}_4win")
    results: dict[str, float] = {}
    if not os.path.isdir(log_dir):
        return results
    for fname in sorted(os.listdir(log_dir)):
        if not re.match(r"\d{4}-\d{2}-\d{2}\.log$", fname):
            continue
        d_str = fname.replace(".log", "")
        with open(os.path.join(log_dir, fname)) as f:
            for line in f:
                m = re.search(r"cap:\s*([+-]?\$[\d,.]+)", line)
                if m:
                    results[d_str] = float(m.group(1).replace("$", "").replace(",", ""))
    return results


def week_key(d: date) -> str:
    """ISO week Monday date string."""
    return str(d - timedelta(days=d.weekday()))


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def sign_str(v: float) -> str:
    return "+" if v >= 0 else ""


def pnl_str(v: float, width: int = 10) -> str:
    s = f"{sign_str(v)}${v:,.2f}"
    return s.rjust(width)


def pct_str(v: float, capital: float = CAPITAL) -> str:
    p = v / capital * 100
    return f"{sign_str(p)}{p:.1f}%"


# ─────────────────────────────────────────────────────────────────────────────
# Section printers
# ─────────────────────────────────────────────────────────────────────────────

def print_yearly_summary(all_data: dict[int, dict[str, float]]) -> None:
    print()
    print("=" * 65)
    print("  YEARLY SUMMARY")
    print("=" * 65)
    grand_total = 0.0
    for year in sorted(all_data):
        data = all_data[year]
        if not data:
            print(f"  {year}:  NO DATA")
            continue
        total = sum(data.values())
        days = len(data)
        wins = sum(1 for v in data.values() if v > 0)
        wr = wins / days * 100 if days else 0
        grand_total += total
        print(
            f"  {year}:  {pnl_str(total, 12)}  {pct_str(total):>8}  "
            f"({days} days, {wr:.0f}% WR)"
        )
    print(f"  {'─'*55}")
    print(f"  5-YR TOTAL:  {pnl_str(grand_total, 12)}  {pct_str(grand_total):>8}")
    print()


def print_monthly_breakdown(all_data: dict[int, dict[str, float]]) -> None:
    print()
    print("=" * 65)
    print("  MONTHLY BREAKDOWN")
    print("=" * 65)
    for year in sorted(all_data):
        data = all_data[year]
        if not data:
            continue
        months: dict[str, float] = defaultdict(float)
        for d_str, pnl in data.items():
            months[month_key(date.fromisoformat(d_str))] += pnl
        print(f"\n  {year}")
        year_total = 0.0
        for mk in sorted(months):
            v = months[mk]
            year_total += v
            month_name = date.fromisoformat(mk + "-01").strftime("%b")
            print(f"    {month_name}  {pnl_str(v, 10)}  {pct_str(v):>7}")
        print(f"    {'─'*30}")
        print(f"    Total  {pnl_str(year_total, 10)}  {pct_str(year_total):>7}")
    print()


def print_weekly_table(all_data: dict[int, dict[str, float]]) -> None:
    """Compact weekly table: one row per week, columns per day."""
    print()
    print("=" * 75)
    print("  WEEKLY P&L TABLE (Mon–Fri)")
    print("=" * 75)

    # Build per-week, per-day data
    week_days: dict[str, dict[str, float]] = defaultdict(dict)
    for year in sorted(all_data):
        for d_str, pnl in all_data[year].items():
            d = date.fromisoformat(d_str)
            week_days[week_key(d)][d_str] = pnl

    cur_year = None
    for wk in sorted(week_days):
        year = int(wk[:4])
        if year != cur_year:
            cur_year = year
            print(f"\n  ── {year} ──")
            print(f"  {'Week of':<14} {'Mon':>9} {'Tue':>9} {'Wed':>9} {'Thu':>9} {'Fri':>9}  {'Week':>10}")

        days = week_days[wk]
        total = sum(days.values())
        cells = []
        mon = date.fromisoformat(wk)
        for i in range(5):
            d_str = str(mon + timedelta(days=i))
            if d_str in days:
                cells.append(pnl_str(days[d_str], 9))
            else:
                cells.append(" " * 9)
        print(f"  {wk:<14} {'  '.join(cells)}  {pnl_str(total, 10)}")
    print()


def compute_week_totals(all_data: dict[int, dict[str, float]]) -> list[tuple[str, float]]:
    """Return sorted list of (week_key, week_pnl) across all years."""
    weeks: dict[str, float] = defaultdict(float)
    for data in all_data.values():
        for d_str, pnl in data.items():
            d = date.fromisoformat(d_str)
            weeks[week_key(d)] += pnl
    return sorted(weeks.items())


def print_top5_weeks(all_data: dict[int, dict[str, float]]) -> None:
    week_totals = compute_week_totals(all_data)
    by_pnl = sorted(week_totals, key=lambda x: x[1])

    print()
    print("=" * 55)
    print("  TOP-5 BEST WEEKS")
    print("=" * 55)
    for wk, pnl in reversed(by_pnl[-5:]):
        print(f"  {wk}   {pnl_str(pnl, 12)}  {pct_str(pnl):>8}")

    print()
    print("=" * 55)
    print("  TOP-5 WORST WEEKS")
    print("=" * 55)
    for wk, pnl in by_pnl[:5]:
        print(f"  {wk}   {pnl_str(pnl, 12)}  {pct_str(pnl):>8}")
    print()


def print_streaks(all_data: dict[int, dict[str, float]]) -> None:
    week_totals = compute_week_totals(all_data)

    best_win_streak = best_win_start = best_win_end = None
    best_loss_streak = best_loss_start = best_loss_end = None
    cur_win = 0
    cur_loss = 0
    win_start = loss_start = None

    for wk, pnl in week_totals:
        if pnl >= 0:
            if cur_win == 0:
                win_start = wk
            cur_win += 1
            if best_win_streak is None or cur_win > best_win_streak:
                best_win_streak = cur_win
                best_win_start = win_start
                best_win_end = wk
            cur_loss = 0
            loss_start = None
        else:
            if cur_loss == 0:
                loss_start = wk
            cur_loss += 1
            if best_loss_streak is None or cur_loss > best_loss_streak:
                best_loss_streak = cur_loss
                best_loss_start = loss_start
                best_loss_end = wk
            cur_win = 0
            win_start = None

    print()
    print("=" * 55)
    print("  WEEK STREAKS")
    print("=" * 55)
    if best_win_streak:
        print(f"  Longest winning streak : {best_win_streak} weeks")
        print(f"    From {best_win_start}  to  {best_win_end}")
    if best_loss_streak:
        print(f"  Longest losing  streak : {best_loss_streak} weeks")
        print(f"    From {best_loss_start}  to  {best_loss_end}")
    print()


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-year replay summary")
    parser.add_argument(
        "--years", nargs="+", type=int, default=[2021, 2022, 2023, 2024, 2025],
        help="Years to include (default: 2021-2025)"
    )
    parser.add_argument(
        "--trade-type", default="options", choices=["options", "stock"],
        help="Trade type (default: options)"
    )
    parser.add_argument(
        "--weekly-table", action="store_true", default=False,
        help="Print full week-by-week table (verbose)"
    )
    args = parser.parse_args()

    all_data: dict[int, dict[str, float]] = {}
    for year in sorted(args.years):
        data = load_year(year, args.trade_type)
        all_data[year] = data
        status = f"{len(data)} days" if data else "NO DATA"
        print(f"  Loaded {year}: {status}", file=sys.stderr)

    print(f"\n  Config: {args.trade_type.upper()} replay  |  $10k capital  |  SIP feed")
    print(f"  Years : {', '.join(str(y) for y in sorted(args.years))}")

    print_yearly_summary(all_data)
    print_monthly_breakdown(all_data)
    if args.weekly_table:
        print_weekly_table(all_data)
    print_top5_weeks(all_data)
    print_streaks(all_data)


if __name__ == "__main__":
    main()
