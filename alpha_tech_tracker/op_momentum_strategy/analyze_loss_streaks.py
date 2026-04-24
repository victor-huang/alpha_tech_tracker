"""
Loss streak analysis for the op_momentum selector backtest.

Runs the full 6-year backtest (2021–2026 YTD), extracts daily cap P&L,
identifies all-loss weeks, computes conditional loss probabilities,
and simulates simple circuit-breaker strategies.

Usage:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
      python alpha_tech_tracker/op_momentum_strategy/analyze_loss_streaks.py
"""

import sys
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from alpaca.data.enums import DataFeed

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    DEFAULT_TICKERS,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    INITIAL_CAPITAL,
    _apply_capital_flow,
    run_selector_backtest,
)

# ── Backtest config (matches live SOA config, top-1 for single-pick clarity) ──
BACKTEST_KWARGS = dict(
    tickers=DEFAULT_TICKERS,
    lookback_days=60,
    opening_bars=3,
    opening_start_time="09:30",
    stop_pct=0.15,
    trailing_ma="ma20",
    source="alpaca",
    feed=DataFeed.IEX,
    windows=[{"label": "M1", "opening_start": "09:30", "opening_bars": 3}],
    enable_reversal=True,
    enable_bearish_reentry=True,
    enable_bullish_reentry=True,
    enable_doubledown=True,
    doubledown_start_min=5,
    n=1,
)

YEARS = [
    (date(2021, 1, 1), date(2021, 12, 31)),
    (date(2022, 1, 1), date(2022, 12, 31)),
    (date(2023, 1, 1), date(2023, 12, 31)),
    (date(2024, 1, 1), date(2024, 12, 31)),
    (date(2025, 1, 1), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 4, 23)),
]

WEIGHTS = [1.0]
MORNING_SPLIT = [1.0]


def _daily_pnl(trade_rows: list, trading_days: list) -> dict:
    """Return {date: cap_pnl} for every trading day."""
    by_date = defaultdict(float)
    for row in trade_rows:
        by_date[row["date"]] += row.get("cap_pnl", 0.0)
    # Days where no trade fired still count as 0
    for d in trading_days:
        by_date.setdefault(d, 0.0)
    return dict(sorted(by_date.items()))


def _iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _weekly_summary(daily: dict) -> dict:
    """
    Return {iso_week: {"days": [date], "pnls": [float], "wins": int, "losses": int, "total": float}}
    """
    weeks = defaultdict(lambda: {"days": [], "pnls": [], "wins": 0, "losses": 0, "total": 0.0})
    for d, pnl in sorted(daily.items()):
        w = _iso_week(d)
        weeks[w]["days"].append(d)
        weeks[w]["pnls"].append(pnl)
        if pnl > 0:
            weeks[w]["wins"] += 1
        elif pnl < 0:
            weeks[w]["losses"] += 1
        weeks[w]["total"] += pnl
    return dict(weeks)


def _run_all_years():
    all_daily = {}
    for start, end in YEARS:
        print(f"  Running {start.year}...", flush=True)
        trade_rows, _, trading_days = run_selector_backtest(
            eval_start=start, eval_end=end, **BACKTEST_KWARGS
        )
        _apply_capital_flow(
            trade_rows,
            [{"label": "M1", "opening_start": "09:30", "opening_bars": 3}],
            INITIAL_CAPITAL,
            WEIGHTS,
            n=1,
            morning_split=MORNING_SPLIT,
            compound=False,
            enable_doubledown=True,
        )
        daily = _daily_pnl(trade_rows, trading_days)
        all_daily.update(daily)
    return all_daily


def _circuit_breaker_sim(daily: dict, pause_after_k: int, pause_days: int) -> dict:
    """
    Simulate a circuit breaker: after `pause_after_k` consecutive losing days,
    skip the next `pause_days` trading days.

    Returns a modified daily dict where skipped days have cap_pnl = 0.
    """
    dates = sorted(daily.keys())
    result = dict(daily)
    consecutive_losses = 0
    pause_remaining = 0

    for d in dates:
        if pause_remaining > 0:
            result[d] = 0.0  # skipped day — no trade
            pause_remaining -= 1
            consecutive_losses = 0  # reset streak once we resume
            continue
        pnl = daily[d]
        if pnl < 0:
            consecutive_losses += 1
            if consecutive_losses >= pause_after_k:
                pause_remaining = pause_days
                consecutive_losses = 0
        else:
            consecutive_losses = 0

    return result


def _weekly_loss_cap_sim(daily: dict, max_weekly_loss_pct: float) -> dict:
    """
    Simulate a weekly loss cap: once the week's cumulative loss exceeds
    max_weekly_loss_pct × INITIAL_CAPITAL, skip remaining days of that week.
    """
    cap_threshold = INITIAL_CAPITAL * max_weekly_loss_pct
    result = dict(daily)
    weeks = defaultdict(list)
    for d in sorted(daily.keys()):
        weeks[_iso_week(d)].append(d)

    for week_days in weeks.values():
        cumulative = 0.0
        capped = False
        for d in week_days:
            if capped:
                result[d] = 0.0
                continue
            pnl = daily[d]
            cumulative += pnl
            if cumulative < -cap_threshold:
                capped = True

    return result


def _summarize(daily: dict, label: str) -> dict:
    total = sum(daily.values())
    wins = sum(1 for v in daily.values() if v > 0)
    losses = sum(1 for v in daily.values() if v < 0)
    skipped = sum(1 for v in daily.values() if v == 0)
    return {
        "label": label,
        "total": total,
        "wins": wins,
        "losses": losses,
        "skipped": skipped,
        "days": len(daily),
    }


def main():
    print("\nRunning 6-year backtest (2021–2026 YTD)...\n")
    all_daily = _run_all_years()

    dates = sorted(all_daily.keys())
    weekly = _weekly_summary(all_daily)

    # ── Section 1: All-loss week frequency ──────────────────────────────────
    print("\n" + "═" * 70)
    print("  ALL-LOSS WEEK FREQUENCY  (every trading day in the week a loss)")
    print("═" * 70)

    all_loss_weeks = {w: v for w, v in weekly.items() if v["wins"] == 0 and v["losses"] > 0}
    total_weeks = len(weekly)

    print(f"\n  Total calendar weeks with ≥1 trade : {total_weeks}")
    print(f"  All-loss weeks (0W/NL)             : {len(all_loss_weeks)}  "
          f"({len(all_loss_weeks)/total_weeks*100:.1f}%)")
    print(f"  Avg all-loss weeks per year        : {len(all_loss_weeks)/6:.1f}")
    print()
    print(f"  {'Week':<12} {'W/L':>6} {'Cap P&L':>10}  {'Following week':>14}")
    print(f"  {'─' * 56}")

    week_keys = sorted(weekly.keys())
    for i, wk in enumerate(week_keys):
        v = weekly[wk]
        if v["wins"] > 0 or v["losses"] == 0:
            continue
        wl = f"{v['wins']}W/{v['losses']}L"
        pnl = v["total"]
        pnl_str = f"+${pnl:.0f}" if pnl >= 0 else f"-${abs(pnl):.0f}"
        # Following week
        next_wk = week_keys[i + 1] if i + 1 < len(week_keys) else None
        if next_wk:
            nv = weekly[next_wk]
            nxt_str = f"+${nv['total']:.0f}" if nv["total"] >= 0 else f"-${abs(nv['total']):.0f}"
            nxt_tag = "✅ bounce" if nv["total"] > 0 else "❌ continued"
            following = f"{nxt_str} {nxt_tag}"
        else:
            following = "—"
        print(f"  {wk:<12} {wl:>6}  {pnl_str:>9}    {following}")

    # ── Section 2: Near-loss weeks (1W/NL) ──────────────────────────────────
    near_loss = {w: v for w, v in weekly.items() if v["wins"] == 1 and v["losses"] >= 3}
    print(f"\n  Near-all-loss weeks (1W/3+L)       : {len(near_loss)}  "
          f"({len(near_loss)/total_weeks*100:.1f}%)")

    # ── Section 3: Conditional loss probabilities ────────────────────────────
    print("\n" + "═" * 70)
    print("  CONDITIONAL LOSS PROBABILITY  P(lose day N | lost last K days)")
    print("═" * 70)

    pnl_seq = [all_daily[d] for d in dates]
    outcomes = [1 if p < 0 else 0 for p in pnl_seq]  # 1 = loss, 0 = win/flat

    print(f"\n  Unconditional loss rate: {sum(outcomes)/len(outcomes)*100:.1f}%\n")
    print(f"  {'Streak':<30} {'Occurrences':>12} {'Loss next day':>14} {'Prob':>8}")
    print(f"  {'─' * 68}")

    for k in range(1, 6):
        n_streaks = 0
        n_next_loss = 0
        for i in range(k, len(outcomes)):
            if all(outcomes[i - k: i]):  # k consecutive losses ending at i-1
                n_streaks += 1
                if i < len(outcomes) and outcomes[i]:
                    n_next_loss += 1
        if n_streaks > 0:
            prob = n_next_loss / n_streaks * 100
            label = f"after {k} consecutive loss{'es' if k > 1 else ''}"
            print(f"  {label:<30} {n_streaks:>12}  {n_next_loss:>13}  {prob:>7.1f}%")

    # ── Section 4: Circuit breaker simulations ──────────────────────────────
    print("\n" + "═" * 70)
    print("  CIRCUIT BREAKER SIMULATIONS  (no-compound, $10k daily reset)")
    print("═" * 70)

    baseline = _summarize(all_daily, "Baseline (no breaker)")
    scenarios = [baseline]

    for k in [2, 3]:
        for pause in [1, 2]:
            modified = _circuit_breaker_sim(all_daily, pause_after_k=k, pause_days=pause)
            label = f"Pause {pause}d after {k} consec. losses"
            scenarios.append(_summarize(modified, label))

    for max_loss in [0.02, 0.03, 0.04]:
        modified = _weekly_loss_cap_sim(all_daily, max_weekly_loss_pct=max_loss)
        label = f"Weekly loss cap {max_loss*100:.0f}% (${max_loss*INITIAL_CAPITAL:.0f})"
        scenarios.append(_summarize(modified, label))

    print(f"\n  {'Strategy':<38} {'6yr P&L':>10} {'vs BL':>8} {'W':>6} {'L':>6} {'Skip':>6}")
    print(f"  {'─' * 76}")
    bl_total = baseline["total"]
    for s in scenarios:
        delta = s["total"] - bl_total
        delta_str = f"{delta:+.0f}" if s["label"] != "Baseline (no breaker)" else "—"
        pnl_str = f"+${s['total']:.0f}" if s["total"] >= 0 else f"-${abs(s['total']):.0f}"
        print(
            f"  {s['label']:<38} {pnl_str:>10} {delta_str:>8}  "
            f"{s['wins']:>5}  {s['losses']:>5}  {s['skipped']:>5}"
        )

    # ── Section 5: Intra-week streak breakdown ──────────────────────────────
    print("\n" + "═" * 70)
    print("  INTRA-WEEK LOSS STREAK BREAKDOWN")
    print("═" * 70)
    print()

    day_counts = defaultdict(lambda: {"total": 0, "followed_by_loss": 0})
    for wk, v in weekly.items():
        pnls = v["pnls"]
        for i, p in enumerate(pnls):
            if p < 0 and i + 1 < len(pnls):
                streak_pos = i + 1  # 1-indexed position within the losing run
                day_counts[streak_pos]["total"] += 1
                if pnls[i + 1] < 0:
                    day_counts[streak_pos]["followed_by_loss"] += 1

    # Simpler view: given you've lost Mon (day 1 of week), P(lose Tue)?
    # Group by which day-in-week the losing day is (1..4 for Mon..Thu)
    from collections import Counter
    week_day_loss_counts = defaultdict(Counter)
    for wk, v in weekly.items():
        pnls = v["pnls"]
        for i, p in enumerate(pnls):
            day_in_week = i + 1  # 1-indexed
            outcome = "loss" if p < 0 else "win"
            week_day_loss_counts[day_in_week][outcome] += 1

    print(f"  {'Day in week':<14} {'Total':>7} {'Wins':>7} {'Losses':>8} {'Loss rate':>10}")
    print(f"  {'─' * 52}")
    for day_num in sorted(week_day_loss_counts.keys()):
        c = week_day_loss_counts[day_num]
        total = c["win"] + c["loss"]
        loss_rate = c["loss"] / total * 100 if total else 0
        day_label = {1: "Day 1 (Mon)", 2: "Day 2 (Tue)", 3: "Day 3 (Wed)", 4: "Day 4 (Thu)", 5: "Day 5 (Fri)"}.get(day_num, f"Day {day_num}")
        print(f"  {day_label:<14} {total:>7} {c['win']:>7} {c['loss']:>8} {loss_rate:>9.1f}%")

    print()
    print("═" * 70)
    print()


if __name__ == "__main__":
    main()
