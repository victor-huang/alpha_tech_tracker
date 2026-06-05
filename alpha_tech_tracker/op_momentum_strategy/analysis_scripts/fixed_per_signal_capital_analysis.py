"""
Validate the $10k-per-signal capital allocation idea.

Current model:  $10k total pool, split equally across n entered positions
                → slot = $10k / n_entered  (renormalized — fewer signals = bigger slots)

Proposed model: $10k fixed per signal slot, n signals → n × $10k deployed
                → more signals on a day = more total capital deployed (up to top_n × $10k)

Analysis:
  1. Extract per-signal return% from existing no-stop replay logs
  2. Compute current vs proposed daily P&L
  3. Bucket by signal count to see if high-signal days earn the extra exposure
  4. Annual + cumulative comparison
  5. Max drawdown and Sharpe under both models
"""

import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from math import sqrt

BASE_LOG_DIR = "/Users/victorhuang/work/alpha_tech_tracker/logs"
YEARS = list(range(2018, 2027))
SIGNAL_CAP = 10_000.0   # proposed: $10k per signal slot
TOP_N = 8               # max signals cap (signals > top_n are already filtered by engine)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_CAP_RET = re.compile(
    r"Capital returned \[M1\] (\w+) \(dd=(True|False) reentry=(True|False)\): "
    r"slot=([\d.]+) cap_pnl=([+-]?[\d.]+)"
)
_BUFFERED = re.compile(r"Signal collection window \[M1\] closed: ranking (\d+) buffered signal")
_DAILY_CAP = re.compile(r"cap: ([+-]?\$[\d,]+\.?\d*)\s*\(([+-]?[\d.]+)%\)")


def parse_log(path: str) -> dict:
    """
    Returns:
        date         str
        primary      list of {ticker, slot, cap_pnl, ret_pct}  — dd=False reentry=False
        dd           list of {ticker, slot, cap_pnl}            — dd=True
        reentry      list of {ticker, slot, cap_pnl}            — reentry=True
        buffered     int   (signals fired before selector filter)
        current_pnl  float (engine's reported cap P&L)
    """
    day = os.path.basename(path).replace(".log", "")
    primary, dd_legs, reentry_legs = [], [], []
    buffered = 0
    current_pnl = None

    with open(path) as f:
        for line in f:
            m = _BUFFERED.search(line)
            if m:
                buffered = int(m.group(1))

            m = _CAP_RET.search(line)
            if m:
                ticker = m.group(1)
                is_dd = m.group(2) == "True"
                is_re = m.group(3) == "True"
                slot = float(m.group(4))
                cap_pnl = float(m.group(5))
                ret_pct = cap_pnl / slot if slot > 0 else 0.0
                entry = {"ticker": ticker, "slot": slot, "cap_pnl": cap_pnl, "ret_pct": ret_pct}
                if is_dd:
                    dd_legs.append(entry)
                elif is_re:
                    reentry_legs.append(entry)
                else:
                    primary.append(entry)

            m = _DAILY_CAP.search(line)
            if m:
                current_pnl = float(m.group(1).replace("$", "").replace(",", ""))

    return {
        "date": day,
        "primary": primary,
        "dd": dd_legs,
        "reentry": reentry_legs,
        "buffered": buffered,
        "current_pnl": current_pnl,
    }


def proposed_pnl(day_data: dict) -> float:
    """
    $10k per primary signal slot.
    DD legs scale proportionally with the primary slot they belong to.
    Reentry legs use freed capital — treated same as current (no change).

    For DD: dd_proposed = dd_cap_pnl / dd_slot * primary_slot_new
    We approximate by rescaling each DD leg's P&L by the ratio
    (SIGNAL_CAP / primary_slot) where primary_slot is the slot of its
    corresponding primary.  Since we only have 1 primary per window in
    most days, use the first (highest-rank) primary's slot as the base.
    """
    primaries = day_data["primary"]
    if not primaries:
        return 0.0

    total = 0.0

    # Primary signals: each gets $10k
    scale_factors = {}
    for p in primaries:
        old_slot = p["slot"]
        new_pnl = p["ret_pct"] * SIGNAL_CAP
        total += new_pnl
        scale_factors[p["ticker"]] = SIGNAL_CAP / old_slot if old_slot > 0 else 1.0

    # DD legs: scale by the ratio the primary slot changed.
    # Use average scale factor as approximation (DD winner isn't always identifiable
    # from the log without more context).
    if scale_factors:
        avg_scale = sum(scale_factors.values()) / len(scale_factors)
    else:
        avg_scale = 1.0

    for d in day_data["dd"]:
        total += d["cap_pnl"] * avg_scale

    # Reentry legs: these reuse returned capital — unchanged in proposed model.
    for r in day_data["reentry"]:
        total += r["cap_pnl"]

    return total


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run():
    all_days = []   # list of {date, year, n_primary, current_pnl, proposed_pnl}

    for year in YEARS:
        log_dir = os.path.join(BASE_LOG_DIR, f"replay_{year}_stock_m1_winrate_nostop")
        if not os.path.isdir(log_dir):
            continue
        for fname in sorted(os.listdir(log_dir)):
            if not re.match(r"\d{4}-\d{2}-\d{2}\.log$", fname):
                continue
            path = os.path.join(log_dir, fname)
            data = parse_log(path)
            if data["current_pnl"] is None:
                continue
            prop = proposed_pnl(data)
            all_days.append({
                "date": data["date"],
                "year": int(data["date"][:4]),
                "n_primary": len(data["primary"]),
                "buffered": data["buffered"],
                "current_pnl": data["current_pnl"],
                "proposed_pnl": prop,
            })

    if not all_days:
        print("No log data found.")
        return

    # ── 1. Signal-count buckets ──────────────────────────────────────────────
    print("=" * 70)
    print("SIGNAL COUNT vs AVERAGE DAILY RETURN")
    print("(primary entered positions per day, after selector filter)")
    print("=" * 70)
    print(f"{'Signals':>8}  {'Days':>6}  {'Cur AvgP&L':>12}  {'Prop AvgP&L':>13}  "
          f"{'Cur Worst':>10}  {'Prop Worst':>11}  {'Hit%':>6}")
    print("-" * 70)

    buckets = defaultdict(list)
    for d in all_days:
        buckets[d["n_primary"]].append(d)

    for n in sorted(buckets.keys()):
        days = buckets[n]
        cur_avg = sum(x["current_pnl"] for x in days) / len(days)
        prop_avg = sum(x["proposed_pnl"] for x in days) / len(days)
        cur_worst = min(x["current_pnl"] for x in days)
        prop_worst = min(x["proposed_pnl"] for x in days)
        hit_pct = 100.0 * sum(1 for x in days if x["current_pnl"] > 0) / len(days)
        print(f"{n:>8}  {len(days):>6}  {cur_avg:>+12.2f}  {prop_avg:>+13.2f}  "
              f"{cur_worst:>+10.2f}  {prop_worst:>+11.2f}  {hit_pct:>5.1f}%")

    print()

    # ── 2. Annual summary ────────────────────────────────────────────────────
    print("=" * 70)
    print("ANNUAL SUMMARY: CURRENT ($10k pool) vs PROPOSED ($10k/signal)")
    print("=" * 70)
    print(f"{'Year':>6}  {'Cur P&L':>10}  {'Prop P&L':>10}  "
          f"{'Cur Ret%':>9}  {'Prop Ret%':>10}  {'Cur Sharpe':>11}  {'Prop Sharpe':>12}")
    print("-" * 70)

    grand_cur = grand_prop = 0.0
    for year in YEARS:
        ydays = [d for d in all_days if d["year"] == year]
        if not ydays:
            continue
        cur_total = sum(d["current_pnl"] for d in ydays)
        prop_total = sum(d["proposed_pnl"] for d in ydays)

        cur_rets = [d["current_pnl"] / SIGNAL_CAP for d in ydays]
        prop_rets = [d["proposed_pnl"] / SIGNAL_CAP for d in ydays]

        def sharpe(rets):
            n = len(rets)
            if n < 2:
                return 0.0
            mean = sum(rets) / n
            var = sum((r - mean) ** 2 for r in rets) / (n - 1)
            std = var ** 0.5
            return (mean / std * sqrt(252)) if std > 0 else 0.0

        cur_sharpe = sharpe(cur_rets)
        prop_sharpe = sharpe(prop_rets)
        label = f"{year}" if year < 2026 else "2026 YTD"
        print(f"{label:>8}  {cur_total:>+10.0f}  {prop_total:>+10.0f}  "
              f"{cur_total/SIGNAL_CAP*100:>+8.1f}%  {prop_total/SIGNAL_CAP*100:>+9.1f}%  "
              f"{cur_sharpe:>11.2f}  {prop_sharpe:>12.2f}")
        grand_cur += cur_total
        grand_prop += prop_total

    print("-" * 70)
    print(f"{'TOTAL':>8}  {grand_cur:>+10.0f}  {grand_prop:>+10.0f}  "
          f"{grand_cur/SIGNAL_CAP*100:>+8.1f}%  {grand_prop/SIGNAL_CAP*100:>+9.1f}%")
    print()

    # ── 3. Drawdown comparison ───────────────────────────────────────────────
    print("=" * 70)
    print("MAX DRAWDOWN: WORST SINGLE DAY / WORST ROLLING WEEK")
    print("=" * 70)
    print(f"{'Year':>8}  {'Cur Day':>10}  {'Prop Day':>10}  {'Cur Week':>10}  {'Prop Week':>10}")
    print("-" * 70)

    for year in YEARS:
        ydays = sorted([d for d in all_days if d["year"] == year], key=lambda x: x["date"])
        if not ydays:
            continue
        cur_worst_day = min(d["current_pnl"] for d in ydays)
        prop_worst_day = min(d["proposed_pnl"] for d in ydays)

        # rolling 5-trading-day window
        cur_worst_wk = prop_worst_wk = 0.0
        for i in range(len(ydays)):
            window = ydays[i:i+5]
            cur_wk = sum(d["current_pnl"] for d in window)
            prop_wk = sum(d["proposed_pnl"] for d in window)
            cur_worst_wk = min(cur_worst_wk, cur_wk)
            prop_worst_wk = min(prop_worst_wk, prop_wk)

        label = f"{year}" if year < 2026 else "2026 YTD"
        print(f"{label:>8}  {cur_worst_day:>+10.0f}  {prop_worst_day:>+10.0f}  "
              f"{cur_worst_wk:>+10.0f}  {prop_worst_wk:>+10.0f}")

    print()

    # ── 4. Capital exposure distribution ────────────────────────────────────
    print("=" * 70)
    print("CAPITAL DEPLOYED PER DAY (proposed $10k/signal)")
    print("=" * 70)
    exposure_buckets = defaultdict(int)
    for d in all_days:
        deployed = d["n_primary"] * SIGNAL_CAP
        bracket = int(deployed / SIGNAL_CAP)  # 0,1,2,...8
        exposure_buckets[bracket] += 1

    total_days = len(all_days)
    print(f"{'Slots deployed':>16}  {'Capital':>12}  {'Days':>6}  {'% of days':>10}")
    print("-" * 50)
    for n in sorted(exposure_buckets.keys()):
        days_count = exposure_buckets[n]
        print(f"{n:>16}  ${n*SIGNAL_CAP:>10,.0f}  {days_count:>6}  {100*days_count/total_days:>9.1f}%")
    print()

    # ── 5. High-signal vs low-signal day correlation ─────────────────────────
    print("=" * 70)
    print("HIGH-SIGNAL DAYS: are they worth the extra exposure?")
    print("(comparing days with 1 signal vs 3+ signals vs 6+ signals)")
    print("=" * 70)
    for threshold, label in [(1, "exactly 1 signal"), (3, "3+ signals"), (6, "6+ signals")]:
        if threshold == 1:
            subset = [d for d in all_days if d["n_primary"] == 1]
        else:
            subset = [d for d in all_days if d["n_primary"] >= threshold]
        if not subset:
            continue
        avg_cur = sum(d["current_pnl"] for d in subset) / len(subset)
        avg_prop = sum(d["proposed_pnl"] for d in subset) / len(subset)
        win_rate = 100.0 * sum(1 for d in subset if d["current_pnl"] > 0) / len(subset)
        worst_prop = min(d["proposed_pnl"] for d in subset)
        print(f"  {label} ({len(subset)} days, {win_rate:.0f}% win rate):")
        print(f"    Avg P&L  current=${avg_cur:+.2f}  proposed=${avg_prop:+.2f}")
        print(f"    Worst day proposed: ${worst_prop:+.2f}")
    print()


if __name__ == "__main__":
    run()
