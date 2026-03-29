#!/usr/bin/env python3
"""
P&L Audit Script for m1_m2_a1_a2_compound_2026 backtest results.

Verifies:
1. Per-trade cap P&L calculation
2. Capital carried over between windows within each day
3. Day-to-day compounding (portfolio carry-over)
4. Weekly and monthly P&L aggregation
5. Spot-checks entry/exit prices against Alpaca real bar data

Usage (run from project root):
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker pyenv exec python alpha_tech_tracker/op_momentum_strategy/audit_pnl.py
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker pyenv exec python alpha_tech_tracker/op_momentum_strategy/audit_pnl.py --verify-prices
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker pyenv exec python alpha_tech_tracker/op_momentum_strategy/audit_pnl.py --date 2026-01-02
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

LOG_PATH = "backtest_result/multiple_trading_windows/m1_m2_a1_a2_compound_2026.txt"

INITIAL_CAPITAL = 10_000.0
MORNING_SPLIT = [0.60, 0.40]  # M1 = 60%, M2 = 40%
WEIGHTS = [0.50, 0.30, 0.20]  # rank-1/2/3 slots
FIRST_GROUP = ["M1", "M2"]
SEQUENTIAL = ["A1", "A2"]
MIN_CAPITAL = 100.0
TOLERANCE = 0.02  # $0.02 rounding tolerance for float comparisons

# ─── Parsing ─────────────────────────────────────────────────────────────────

_TRADE_RE = re.compile(
    r"^\s+(\d{4}-\d{2}-\d{2})\s+(M1|M2|A1|A2)\s+(\d+)\s+(\w+)\s+(BULLISH|BEARISH)\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([+-])\$([\d.]+)\s+([+-][\d.]+)%\s+"
    r"(WIN|LOSS)\s+(\S+)"
)

_SUMMARY_RE = re.compile(
    r"^\s+[+-]\$[\d.]+\s+[+-][\d.]+%\s+(\d+)W/(\d+)L"
    r"\s+│\s+cap:\s+([+-])\$([\d.]+)\s+\([+-][\d.]+%\)\s+portfolio:\s+\$([\d,]+\.\d+)"
)


def parse_log(path: str):
    """
    Returns:
        days_trades : {date: [trade_dict, ...]}  ordered within each day
        day_summary : {date: {logged_cap_pnl, logged_portfolio}}
    """
    days_trades = defaultdict(list)
    day_summary = {}
    current_date = None

    with open(path) as fh:
        for line in fh:
            m = _TRADE_RE.match(line)
            if m:
                (
                    d_str,
                    window,
                    rank,
                    ticker,
                    signal,
                    score,
                    entry,
                    exit_p,
                    pnl_sign,
                    pnl_abs,
                    pnl_pct_str,
                    result,
                    exit_reason,
                ) = m.groups()
                d = date.fromisoformat(d_str)
                current_date = d
                pnl = float(pnl_abs) * (1 if pnl_sign == "+" else -1)
                days_trades[d].append(
                    {
                        "date": d,
                        "window": window,
                        "rank": int(rank),
                        "ticker": ticker,
                        "signal": signal,
                        "entry_price": float(entry),
                        "exit_price": float(exit_p),
                        "pnl": pnl,
                        "success": result == "WIN",
                        "exit_reason": exit_reason,
                    }
                )
                continue

            s = _SUMMARY_RE.match(line)
            if s and current_date is not None:
                wins, losses, cap_sign, cap_abs, port_str = s.groups()
                cap_pnl = float(cap_abs) * (1 if cap_sign == "+" else -1)
                portfolio = float(port_str.replace(",", ""))
                day_summary[current_date] = {
                    "logged_wins": int(wins),
                    "logged_losses": int(losses),
                    "logged_cap_pnl": cap_pnl,
                    "logged_portfolio": portfolio,
                }

    return days_trades, day_summary


# ─── Capital recalculation ────────────────────────────────────────────────────


def recalculate_day(trades: list, portfolio: float) -> dict:
    """
    Independently reproduce capital P&L for one day.

    Returns dict with:
        first_group_pnl, seq_pnl, total_cap_pnl,
        per_trade: [{...calc fields...}],
        window_caps: {window_label: allocated_capital},
        errors: [str]
    """
    by_window = defaultdict(list)
    for t in trades:
        by_window[t["window"]].append(t)

    errors = []
    per_trade_details = {}  # (window, rank) -> dict
    window_caps = {}

    # ── First group (simultaneous) ──
    first_group_pnl = 0.0
    for i, label in enumerate(FIRST_GROUP):
        win_capital = portfolio * MORNING_SPLIT[i]
        window_caps[label] = win_capital
        skipped = win_capital < MIN_CAPITAL
        for t in by_window[label]:
            if skipped:
                calc_cap = 0.0
            else:
                slot = win_capital * WEIGHTS[t["rank"] - 1]
                calc_cap = (slot / t["entry_price"]) * t["pnl"]
                first_group_pnl += calc_cap
            per_trade_details[(label, t["rank"])] = {
                "ticker": t["ticker"],
                "window_capital": win_capital,
                "slot_capital": win_capital * WEIGHTS[t["rank"] - 1],
                "shares": win_capital * WEIGHTS[t["rank"] - 1] / t["entry_price"],
                "calc_cap_pnl": round(calc_cap, 4),
            }

    # ── Sequential windows ──
    available = portfolio + first_group_pnl
    seq_pnl = 0.0
    for label in SEQUENTIAL:
        window_caps[label] = available
        skipped = available < MIN_CAPITAL
        win_pnl = 0.0
        for t in by_window[label]:
            if skipped:
                calc_cap = 0.0
            else:
                slot = available * WEIGHTS[t["rank"] - 1]
                calc_cap = (slot / t["entry_price"]) * t["pnl"]
                win_pnl += calc_cap
            per_trade_details[(label, t["rank"])] = {
                "ticker": t["ticker"],
                "window_capital": available,
                "slot_capital": available * WEIGHTS[t["rank"] - 1],
                "shares": available * WEIGHTS[t["rank"] - 1] / t["entry_price"],
                "calc_cap_pnl": round(calc_cap, 4),
            }
        if not skipped:
            available += win_pnl
            seq_pnl += win_pnl

    total_cap_pnl = first_group_pnl + seq_pnl

    return {
        "first_group_pnl": first_group_pnl,
        "seq_pnl": seq_pnl,
        "total_cap_pnl": total_cap_pnl,
        "per_trade": per_trade_details,
        "window_caps": window_caps,
        "errors": errors,
    }


# ─── Alpaca price spot-check ──────────────────────────────────────────────────


def fetch_alpaca_bars_for_date(ticker: str, d: date):
    """Fetch 5-min bars from Alpaca (via cached fetch_bars) for a specific date."""
    try:
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
            fetch_bars,
        )
    except ImportError as e:
        return None, f"import error: {e}"

    fetch_start = d - timedelta(days=5)
    fetch_end = d
    try:
        all_bars = fetch_bars([ticker], fetch_start, fetch_end, source="alpaca")
    except Exception as e:
        return None, f"fetch error: {e}"

    df = all_bars.get(ticker)
    if df is None or df.empty:
        return None, "no data"

    day_bars = df[df.index.date == d]
    if day_bars.empty:
        return None, "no bars on this date"
    return day_bars, None


def spot_check_price(trade: dict) -> dict:
    """
    For a given trade, fetch actual 5-min bars from Alpaca and check whether
    the logged entry/exit prices exist within the day's bar range.
    """
    d = trade["date"]
    ticker = trade["ticker"]
    entry = trade["entry_price"]
    exit_p = trade["exit_price"]

    bars, err = fetch_alpaca_bars_for_date(ticker, d)
    if err:
        return {"ok": None, "note": err}

    day_low = bars["Low"].min()
    day_high = bars["High"].max()

    entry_in_range = day_low <= entry <= day_high
    exit_in_range = day_low <= exit_p <= day_high

    return {
        "ok": entry_in_range and exit_in_range,
        "day_low": round(day_low, 4),
        "day_high": round(day_high, 4),
        "entry_in_range": entry_in_range,
        "exit_in_range": exit_in_range,
        "n_bars": len(bars),
    }


# ─── ISO week helper ──────────────────────────────────────────────────────────


def iso_week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ─── Main audit ───────────────────────────────────────────────────────────────


def run_audit(
    focus_date: date = None,
    verify_prices: bool = False,
    max_price_checks: int = 10,
    verbose: bool = False,
):
    print(f"Loading log: {LOG_PATH}")
    days_trades, day_summary = parse_log(LOG_PATH)
    trading_days = sorted(days_trades)
    print(
        f"Parsed {len(trading_days)} trading days, "
        f"{sum(len(v) for v in days_trades.values())} trades total.\n"
    )

    # ── Day-by-day audit ──
    portfolio = INITIAL_CAPITAL
    pnl_errors = []
    port_errors = []

    weekly_cap = defaultdict(float)
    weekly_wins = defaultdict(int)
    weekly_losses = defaultdict(int)
    weekly_portfolio_end = {}

    monthly_cap = defaultdict(float)
    monthly_wins = defaultdict(int)
    monthly_losses = defaultdict(int)
    monthly_portfolio_end = {}

    price_checks_done = 0

    print("=" * 90)
    print(
        f"  {'Date':<12}  {'Logged cap P&L':>15}  {'Calc cap P&L':>14}  "
        f"{'Diff':>8}  {'Logged port':>13}  {'Calc port':>12}  {'OK?':>4}"
    )
    print("=" * 90)

    for d in trading_days:
        trades = days_trades[d]
        logged = day_summary.get(d, {})
        show = focus_date is None or d == focus_date

        calc = recalculate_day(trades, portfolio)
        calc_portfolio = portfolio + calc["total_cap_pnl"]

        logged_cap = logged.get("logged_cap_pnl", float("nan"))
        logged_port = logged.get("logged_portfolio", float("nan"))

        cap_diff = calc["total_cap_pnl"] - logged_cap
        port_diff = calc_portfolio - logged_port

        cap_ok = abs(cap_diff) <= TOLERANCE
        port_ok = abs(port_diff) <= TOLERANCE
        ok_flag = "✓" if (cap_ok and port_ok) else "✗ MISMATCH"

        if show:
            print(
                f"  {str(d):<12}  {logged_cap:>+15.2f}  {calc['total_cap_pnl']:>+14.2f}  "
                f"{cap_diff:>+8.4f}  {logged_port:>13,.2f}  {calc_portfolio:>12,.2f}  {ok_flag}"
            )

        if not cap_ok:
            pnl_errors.append((d, logged_cap, calc["total_cap_pnl"], cap_diff))
        if not port_ok:
            port_errors.append((d, logged_port, calc_portfolio, port_diff))

        if show and (verbose or focus_date):
            print(f"\n  -- Capital flow detail for {d} --")
            print(f"     Portfolio start       : ${portfolio:,.2f}")
            for label in FIRST_GROUP + SEQUENTIAL:
                wc = calc["window_caps"].get(label)
                if wc is not None:
                    print(f"     {label} window capital  : ${wc:,.2f}")
            print(f"     M1+M2 first_group_pnl: ${calc['first_group_pnl']:+,.4f}")
            print(f"     A1+A2 seq_pnl        : ${calc['seq_pnl']:+,.4f}")
            print(f"     Total cap P&L        : ${calc['total_cap_pnl']:+,.4f}")
            print()
            print(
                f"     {'Win':5} {'Rk':3}  {'Ticker':6}  {'Entry':8}  "
                f"{'Exit':8}  {'Pnl/sh':8}  {'Slot $':10}  {'Shares':8}  {'Cap P&L':10}"
            )
            for t in trades:
                key = (t["window"], t["rank"])
                td = calc["per_trade"].get(key, {})
                pnl_sign = "+" if t["pnl"] >= 0 else ""
                print(
                    f"     {t['window']:5} {t['rank']:3}  {t['ticker']:6}  "
                    f"{t['entry_price']:8.2f}  {t['exit_price']:8.2f}  "
                    f"{pnl_sign}{t['pnl']:7.2f}  "
                    f"${td.get('slot_capital', 0):9,.2f}  "
                    f"{td.get('shares', 0):8.3f}  "
                    f"{td.get('calc_cap_pnl', 0):+10.4f}"
                )
            print()

        # ── Price spot-checks ──
        if show and verify_prices and price_checks_done < max_price_checks:
            for t in trades[:2]:  # check first 2 trades each day
                if price_checks_done >= max_price_checks:
                    break
                check = spot_check_price(t)
                status = (
                    "OK"
                    if check.get("ok")
                    else ("WARN" if check.get("ok") is False else "N/A")
                )
                if check.get("ok") is False:
                    print(
                        f"  [PRICE-CHECK] {d} {t['window']} {t['ticker']}  "
                        f"entry={t['entry_price']} exit={t['exit_price']}  "
                        f"day_range=[{check.get('day_low')}, {check.get('day_high')}]  "
                        f"entry_ok={check.get('entry_in_range')}  "
                        f"exit_ok={check.get('exit_in_range')}  → {status}"
                    )
                price_checks_done += 1

        # ── Aggregate weekly / monthly ──
        wk = iso_week_label(d)
        weekly_cap[wk] += calc["total_cap_pnl"]
        weekly_wins[wk] += logged.get("logged_wins", 0)
        weekly_losses[wk] += logged.get("logged_losses", 0)
        weekly_portfolio_end[wk] = calc_portfolio

        mo = d.strftime("%Y-%m")
        monthly_cap[mo] += calc["total_cap_pnl"]
        monthly_wins[mo] += logged.get("logged_wins", 0)
        monthly_losses[mo] += logged.get("logged_losses", 0)
        monthly_portfolio_end[mo] = calc_portfolio

        portfolio = calc_portfolio

    print("=" * 90)

    # ── Error summary ──
    print(f"\n{'=' * 50}")
    if not pnl_errors and not port_errors:
        print(
            "  ✓ All daily cap P&L and portfolio values match (within $0.02 tolerance)."
        )
    else:
        if pnl_errors:
            print(f"  ✗ {len(pnl_errors)} day(s) with cap P&L mismatch:")
            for d, logged, calc_v, diff in pnl_errors:
                print(
                    f"     {d}: logged {logged:+.4f}  calc {calc_v:+.4f}  diff {diff:+.4f}"
                )
        if port_errors:
            print(f"  ✗ {len(port_errors)} day(s) with portfolio mismatch:")
            for d, logged, calc_v, diff in port_errors:
                print(
                    f"     {d}: logged {logged:,.4f}  calc {calc_v:,.4f}  diff {diff:+.4f}"
                )
    print(f"{'=' * 50}")

    if focus_date:
        return  # skip summaries for single-day focus

    # ── Weekly breakdown (reproduced) ──
    print(f"\n{'=' * 74}")
    print(f"  REPRODUCED WEEKLY BREAKDOWN  (from log trades + independent calc)")
    print(f"{'=' * 74}")
    print(f"  {'Week':<10}  {'W/L':>10}  {'Calc Cap P&L':>14}  {'Portfolio End':>15}")
    print(f"  {'-' * 68}")
    cumulative = INITIAL_CAPITAL
    for wk in sorted(weekly_cap):
        w = weekly_wins[wk]
        l = weekly_losses[wk]
        cpnl = weekly_cap[wk]
        port = weekly_portfolio_end[wk]
        print(f"  {wk:<10}  {w}W/{l}L{'':<4}  {cpnl:>+14.2f}  {port:>15,.2f}")
    total_calc = sum(weekly_cap.values())
    final_port = (
        list(weekly_portfolio_end.values())[-1]
        if weekly_portfolio_end
        else INITIAL_CAPITAL
    )
    print(f"  {'-' * 68}")
    print(
        f"  {'TOTAL':<10}  {sum(weekly_wins.values())}W/{sum(weekly_losses.values())}L{'':<4}  "
        f"{total_calc:>+14.2f}  {final_port:>15,.2f}"
    )

    # Compare to logged weekly totals
    print(f"\n  Logged weekly (from log file summary section):")
    print(f"  2026-W01: +$235.66  2026-W02: +$1,147.18  2026-W03: +$747.18")
    print(f"  2026-W04: +$22.25   2026-W05: +$679.18    2026-W06: +$834.88")
    print(f"  2026-W07: +$1,277.54 2026-W08: +$663.25   2026-W09: +$496.58")
    print(f"  2026-W10: +$885.45  2026-W11: +$146.13    2026-W12: -$11.25")
    print(f"  2026-W13: +$1,044.56")

    # ── Monthly breakdown (reproduced) ──
    print(f"\n{'=' * 74}")
    print(f"  REPRODUCED MONTHLY BREAKDOWN  (from log trades + independent calc)")
    print(f"{'=' * 74}")
    print(f"  {'Month':<10}  {'W/L':>12}  {'Calc Cap P&L':>14}  {'Portfolio End':>15}")
    print(f"  {'-' * 68}")
    for mo in sorted(monthly_cap):
        w = monthly_wins[mo]
        l = monthly_losses[mo]
        cpnl = monthly_cap[mo]
        port = monthly_portfolio_end[mo]
        print(f"  {mo:<10}  {w}W/{l}L{'':<5}  {cpnl:>+14.2f}  {port:>15,.2f}")
    print(f"  {'-' * 68}")
    total_calc = sum(monthly_cap.values())
    print(
        f"  {'TOTAL':<10}  {sum(monthly_wins.values())}W/{sum(monthly_losses.values())}{'':<5}  "
        f"{total_calc:>+14.2f}  {final_port:>15,.2f}"
    )

    print(f"\n  Logged monthly (from log file summary section):")
    print(f"  2026-01: +$2,831.44  (+28.31%)  →  $12,831.44")
    print(f"  2026-02: +$3,272.25  (+32.72%)  →  $16,103.69")
    print(f"  2026-03: +$2,064.89  (+20.65%)  →  $18,168.58")

    print(f"\n  Final portfolio (calc): ${final_port:,.2f}")
    print(f"  Final portfolio (log):  $18,168.58")
    print(f"  Difference:             ${final_port - 18168.58:+.4f}")


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Audit backtest P&L calculations.")
    parser.add_argument(
        "--date",
        help="Focus on a single date (YYYY-MM-DD) and show full trade detail.",
    )
    parser.add_argument(
        "--verify-prices",
        action="store_true",
        help="Spot-check entry/exit prices against real Alpaca bar data.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-trade capital detail for every day.",
    )
    args = parser.parse_args()

    focus = date.fromisoformat(args.date) if args.date else None
    run_audit(
        focus_date=focus,
        verify_prices=args.verify_prices,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
