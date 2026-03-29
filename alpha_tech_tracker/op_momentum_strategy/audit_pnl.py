#!/usr/bin/env python3
"""
P&L Audit Script — supports both compound and non-compound backtest logs.

Verifies:
1. Per-trade cap P&L calculation (shares × pnl/share)
2. Intra-day window capital flow (morning split → sequential inheritance)
3. Portfolio carry-over (compound) or daily reset (non-compound)
4. Weekly and monthly P&L dollar amounts
5. Weekly/monthly return% using the normalised formula:
       pnl / (num_trading_days × $10K)
6. Spot-checks entry/exit prices against real Alpaca bar data (optional)

Auto-detects compound/non-compound from the log header line
"Compounding  : on/off".

Usage (run from alpha_tech_tracker/op_momentum_strategy/):
    pyenv exec python audit_pnl.py
    pyenv exec python audit_pnl.py --log backtest_result/multiple_trading_windows/m1_m2_a1_a2_2026.txt
    pyenv exec python audit_pnl.py --date 2026-01-08
    pyenv exec python audit_pnl.py --verify-prices
    pyenv exec python audit_pnl.py --verbose
"""

import argparse
import re
from collections import defaultdict
from datetime import date, timedelta

DEFAULT_LOG_COMPOUND = (
    "backtest_result/multiple_trading_windows/m1_m2_a1_a2_compound_2026.txt"
)
DEFAULT_LOG_NO_COMPOUND = (
    "backtest_result/multiple_trading_windows/m1_m2_a1_a2_2026.txt"
)

INITIAL_CAPITAL = 10_000.0
WEIGHTS = [0.50, 0.30, 0.20]   # rank-1/2/3 slots
MIN_CAPITAL = 100.0
TOLERANCE = 0.02  # $0.02 rounding tolerance for float comparisons

# ─── Regex patterns ───────────────────────────────────────────────────────────

_COMPOUND_RE = re.compile(r"Compounding\s*:\s*(on|off)", re.IGNORECASE)

# Matches window header lines, e.g.:
#   [M1] 09:30 / 3 bars  (simultaneous, 60% of portfolio)  (~$6,000)
#   [A1] 13:15 / 1 bars  (sequential, inherits all returned capital)
_WINDOW_RE = re.compile(r"\[(\w+)\].*?\((simultaneous|sequential)[^)]*\)")
_WINDOW_PCT_RE = re.compile(r"(\d+)% of portfolio")

_TRADE_RE = re.compile(
    r"^\s+(\d{4}-\d{2}-\d{2})\s+(M1|M2|A1|A2)\s+(\d+)\s+(\w+)\s+(BULLISH|BEARISH)\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([+-])\$([\d.]+)\s+([+-][\d.]+)%\s+"
    r"(WIN|LOSS)\s+(\S+)"
)

_DAY_SUMMARY_RE = re.compile(
    r"^\s+[+-]\$[\d.]+\s+[+-][\d.]+%\s+(\d+)W/(\d+)L"
    r"\s+│\s+cap:\s+([+-])\$([\d.]+)\s+\([+-][\d.]+%\)\s+portfolio:\s+\$([\d,]+\.\d+)"
)

# Matches rows in the WEEKLY BREAKDOWN table (strategy section, not QQQ)
_WEEKLY_ROW_RE = re.compile(
    r"^\s+(20\d\d-W\d{2})\s+\d+\s+\d+W/\d+L\s+"
    r"([+-])\$([\d,]+\.\d+)\s+([+-][\d.]+)%\s+\$([\d,]+\.\d+)"
)

# Matches rows in the MONTHLY BREAKDOWN table (strategy section, not QQQ)
_MONTHLY_ROW_RE = re.compile(
    r"^\s+(20\d\d-\d{2})\s+\d+\s+\d+W/\d+L\s+"
    r"([+-])\$([\d,]+\.\d+)\s+([+-][\d.]+)%\s+\$([\d,]+\.\d+)"
)

# ─── Log parsing ─────────────────────────────────────────────────────────────


def parse_log(path: str):
    """
    Parse a backtest log file.

    Returns:
        days_trades   : {date: [trade_dict, ...]}
        day_summary   : {date: {logged_wins, logged_losses, logged_cap_pnl, logged_portfolio}}
        compound      : bool (True if log was run with --compound)
        logged_weekly : {week_label: {pnl, return_pct, portfolio}}
        logged_monthly: {month_label: {pnl, return_pct, portfolio}}
        first_group   : [window_label, ...]  — simultaneous windows
        morning_split : [fraction, ...]      — capital fraction for each first-group window
        sequential    : [window_label, ...]  — sequential windows
    """
    days_trades = defaultdict(list)
    day_summary = {}
    compound = None
    logged_weekly = {}
    logged_monthly = {}
    current_date = None
    first_group = []
    morning_split = []
    sequential = []

    # Track which breakdown section we are in so we don't pick up the QQQ rows
    in_strategy_weekly = False
    in_strategy_monthly = False
    in_header = True  # window lines only appear before trade data

    with open(path) as fh:
        for line in fh:
            # ── Detect compound mode from header ──
            if compound is None:
                cm = _COMPOUND_RE.search(line)
                if cm:
                    compound = cm.group(1).lower() == "on"

            # ── Detect window configuration from header ──
            if in_header:
                wm = _WINDOW_RE.search(line)
                if wm:
                    label, kind = wm.group(1), wm.group(2)
                    if kind == "simultaneous":
                        pm = _WINDOW_PCT_RE.search(line)
                        pct = float(pm.group(1)) / 100.0 if pm else 1.0
                        first_group.append(label)
                        morning_split.append(pct)
                    else:
                        sequential.append(label)

            # ── Section headers ──
            if "WEEKLY BREAKDOWN" in line and "QQQ" not in line:
                in_strategy_weekly = True
                in_strategy_monthly = False
                continue
            if "MONTHLY BREAKDOWN" in line and "QQQ" not in line:
                in_strategy_monthly = True
                in_strategy_weekly = False
                continue
            if "QQQ" in line:
                in_strategy_weekly = False
                in_strategy_monthly = False

            # ── Trade rows ──
            m = _TRADE_RE.match(line)
            if m:
                in_header = False
                (
                    d_str, window, rank, ticker, signal, score,
                    entry, exit_p, pnl_sign, pnl_abs, _pnl_pct,
                    result, exit_reason,
                ) = m.groups()
                d = date.fromisoformat(d_str)
                current_date = d
                pnl = float(pnl_abs) * (1 if pnl_sign == "+" else -1)
                days_trades[d].append({
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
                })
                continue

            # ── Daily summary row ──
            s = _DAY_SUMMARY_RE.match(line)
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
                continue

            # ── Weekly summary rows ──
            if in_strategy_weekly:
                wm = _WEEKLY_ROW_RE.match(line)
                if wm:
                    label, sign, pnl_str, ret_pct_str, port_str = wm.groups()
                    logged_weekly[label] = {
                        "pnl": float(pnl_str.replace(",", "")) * (1 if sign == "+" else -1),
                        "return_pct": float(ret_pct_str),
                        "portfolio": float(port_str.replace(",", "")),
                    }

            # ── Monthly summary rows ──
            if in_strategy_monthly:
                mm = _MONTHLY_ROW_RE.match(line)
                if mm:
                    label, sign, pnl_str, ret_pct_str, port_str = mm.groups()
                    logged_monthly[label] = {
                        "pnl": float(pnl_str.replace(",", "")) * (1 if sign == "+" else -1),
                        "return_pct": float(ret_pct_str),
                        "portfolio": float(port_str.replace(",", "")),
                    }

    return (
        days_trades, day_summary, bool(compound),
        logged_weekly, logged_monthly,
        first_group, morning_split, sequential,
    )


# ─── Capital recalculation ────────────────────────────────────────────────────


def recalculate_day(
    trades: list,
    portfolio: float,
    first_group: list,
    morning_split: list,
    sequential: list,
) -> dict:
    """
    Independently reproduce capital P&L for one day given a starting portfolio.

    For compound mode:  portfolio = prior day's ending portfolio.
    For non-compound:   portfolio = INITIAL_CAPITAL (always $10K).

    Returns dict with:
        first_group_pnl, seq_pnl, total_cap_pnl,
        per_trade: {(window, rank): {...calc fields...}},
        window_caps: {window_label: allocated_capital},
    """
    by_window = defaultdict(list)
    for t in trades:
        by_window[t["window"]].append(t)

    per_trade_details = {}
    window_caps = {}

    # ── First group (simultaneous) ──
    first_group_pnl = 0.0
    for i, label in enumerate(first_group):
        win_capital = portfolio * morning_split[i]
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
    for label in sequential:
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

    return {
        "first_group_pnl": first_group_pnl,
        "seq_pnl": seq_pnl,
        "total_cap_pnl": first_group_pnl + seq_pnl,
        "per_trade": per_trade_details,
        "window_caps": window_caps,
    }


# ─── Alpaca price spot-check ──────────────────────────────────────────────────


def fetch_alpaca_bars_for_date(ticker: str, d: date):
    """Fetch 5-min bars from Alpaca (via cached fetch_bars) for a specific date."""
    try:
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
    except ImportError as e:
        return None, f"import error: {e}"

    fetch_start = d - timedelta(days=5)
    try:
        all_bars = fetch_bars([ticker], fetch_start, d, source="alpaca")
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
    """Check whether logged entry/exit prices fall within the day's actual bar range."""
    bars, err = fetch_alpaca_bars_for_date(trade["ticker"], trade["date"])
    if err:
        return {"ok": None, "note": err}

    day_low = bars["Low"].min()
    day_high = bars["High"].max()
    entry_ok = day_low <= trade["entry_price"] <= day_high
    exit_ok = day_low <= trade["exit_price"] <= day_high

    return {
        "ok": entry_ok and exit_ok,
        "day_low": round(day_low, 4),
        "day_high": round(day_high, 4),
        "entry_in_range": entry_ok,
        "exit_in_range": exit_ok,
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────


def iso_week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _ok_flag(cap_ok: bool, port_ok: bool) -> str:
    return "✓" if (cap_ok and port_ok) else "✗ MISMATCH"


# ─── Main audit ───────────────────────────────────────────────────────────────


def run_audit(
    log_path: str,
    focus_date: date = None,
    verify_prices: bool = False,
    max_price_checks: int = 10,
    verbose: bool = False,
):
    print(f"Loading log: {log_path}")
    (
        days_trades, day_summary, compound,
        logged_weekly, logged_monthly,
        first_group, morning_split, sequential,
    ) = parse_log(log_path)
    trading_days = sorted(days_trades)
    mode_label = "COMPOUND (portfolio carries over)" if compound else "NON-COMPOUND (daily reset to $10K)"
    print(f"Mode: {mode_label}")
    split_pcts = " / ".join(f"{s*100:.0f}%" for s in morning_split)
    print(f"Windows: first_group={first_group} ({split_pcts})  sequential={sequential}")
    print(
        f"Parsed {len(trading_days)} trading days, "
        f"{sum(len(v) for v in days_trades.values())} trades total.\n"
    )

    # ── Day-by-day audit ──
    # compound:     each day starts from the prior day's ending portfolio
    # non-compound: each day's trades always use INITIAL_CAPITAL, but the
    #               running portfolio is tracked as $10K + cumulative P&L
    trade_portfolio = INITIAL_CAPITAL  # what we pass to recalculate_day
    running_portfolio = INITIAL_CAPITAL  # cumulative equity curve ($10K + sum of daily P&Ls)

    pnl_errors = []
    port_errors = []

    weekly_cap = defaultdict(float)
    weekly_wins = defaultdict(int)
    weekly_losses = defaultdict(int)
    weekly_days = defaultdict(int)
    weekly_portfolio_end = {}

    monthly_cap = defaultdict(float)
    monthly_wins = defaultdict(int)
    monthly_losses = defaultdict(int)
    monthly_days = defaultdict(int)
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

        calc = recalculate_day(trades, trade_portfolio, first_group, morning_split, sequential)
        calc_portfolio = running_portfolio + calc["total_cap_pnl"]

        logged_cap = logged.get("logged_cap_pnl", float("nan"))
        logged_port = logged.get("logged_portfolio", float("nan"))

        cap_diff = calc["total_cap_pnl"] - logged_cap
        port_diff = calc_portfolio - logged_port

        cap_ok = abs(cap_diff) <= TOLERANCE
        port_ok = abs(port_diff) <= TOLERANCE

        if show:
            print(
                f"  {str(d):<12}  {logged_cap:>+15.2f}  {calc['total_cap_pnl']:>+14.2f}  "
                f"{cap_diff:>+8.4f}  {logged_port:>13,.2f}  {calc_portfolio:>12,.2f}  "
                f"{_ok_flag(cap_ok, port_ok)}"
            )

        if not cap_ok:
            pnl_errors.append((d, logged_cap, calc["total_cap_pnl"], cap_diff))
        if not port_ok:
            port_errors.append((d, logged_port, calc_portfolio, port_diff))

        if show and (verbose or focus_date):
            _print_day_detail(d, trades, calc, trade_portfolio, first_group, sequential)

        # ── Price spot-checks ──
        if show and verify_prices and price_checks_done < max_price_checks:
            for t in trades[:2]:
                if price_checks_done >= max_price_checks:
                    break
                check = spot_check_price(t)
                if check.get("ok") is False:
                    print(
                        f"  [PRICE-CHECK] {d} {t['window']} {t['ticker']}  "
                        f"entry={t['entry_price']} exit={t['exit_price']}  "
                        f"day_range=[{check.get('day_low')}, {check.get('day_high')}]  "
                        f"entry_ok={check.get('entry_in_range')}  "
                        f"exit_ok={check.get('exit_in_range')}  → WARN"
                    )
                price_checks_done += 1

        # ── Aggregate weekly / monthly ──
        wk = iso_week_label(d)
        weekly_cap[wk] += calc["total_cap_pnl"]
        weekly_wins[wk] += logged.get("logged_wins", 0)
        weekly_losses[wk] += logged.get("logged_losses", 0)
        weekly_days[wk] += 1
        weekly_portfolio_end[wk] = calc_portfolio

        mo = d.strftime("%Y-%m")
        monthly_cap[mo] += calc["total_cap_pnl"]
        monthly_wins[mo] += logged.get("logged_wins", 0)
        monthly_losses[mo] += logged.get("logged_losses", 0)
        monthly_days[mo] += 1
        monthly_portfolio_end[mo] = calc_portfolio

        # Advance portfolios for next iteration
        if compound:
            trade_portfolio = calc_portfolio
        running_portfolio = calc_portfolio

    print("=" * 90)

    # ── Error summary ──
    print(f"\n{'=' * 55}")
    if not pnl_errors and not port_errors:
        print("  ✓ All daily cap P&L and portfolio values match (within $0.02 tolerance).")
    else:
        if pnl_errors:
            print(f"  ✗ {len(pnl_errors)} day(s) with cap P&L mismatch:")
            for d, lv, cv, diff in pnl_errors:
                print(f"     {d}: logged {lv:+.4f}  calc {cv:+.4f}  diff {diff:+.4f}")
        if port_errors:
            print(f"  ✗ {len(port_errors)} day(s) with portfolio mismatch:")
            for d, lv, cv, diff in port_errors:
                print(f"     {d}: logged {lv:,.4f}  calc {cv:,.4f}  diff {diff:+.4f}")
    print(f"{'=' * 55}")

    if focus_date:
        return

    final_port = list(weekly_portfolio_end.values())[-1] if weekly_portfolio_end else INITIAL_CAPITAL

    _print_weekly_breakdown(
        weekly_cap, weekly_wins, weekly_losses, weekly_days,
        weekly_portfolio_end, logged_weekly, compound,
    )
    _print_monthly_breakdown(
        monthly_cap, monthly_wins, monthly_losses, monthly_days,
        monthly_portfolio_end, logged_monthly, compound,
    )

    print(f"\n  Final portfolio (calc): ${final_port:,.2f}")
    if logged_weekly:
        last_logged_port = list(logged_weekly.values())[-1]["portfolio"]
        print(f"  Final portfolio (log):  ${last_logged_port:,.2f}")
        print(f"  Difference:             ${final_port - last_logged_port:+.4f}")


# ─── Print helpers ────────────────────────────────────────────────────────────


def _print_day_detail(
    d: date, trades: list, calc: dict, trade_portfolio: float,
    first_group: list, sequential: list,
):
    print(f"\n  -- Capital flow detail for {d} --")
    print(f"     Portfolio (trade base): ${trade_portfolio:,.2f}")
    for label in first_group + sequential:
        wc = calc["window_caps"].get(label)
        if wc is not None:
            print(f"     {label} window capital   : ${wc:,.2f}")
    fg_label = "+".join(first_group)
    seq_label = "+".join(sequential)
    print(f"     {fg_label} first_group_pnl : ${calc['first_group_pnl']:+,.4f}")
    print(f"     {seq_label} seq_pnl         : ${calc['seq_pnl']:+,.4f}")
    print(f"     Total cap P&L         : ${calc['total_cap_pnl']:+,.4f}")
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


def _print_weekly_breakdown(
    weekly_cap, weekly_wins, weekly_losses, weekly_days,
    weekly_portfolio_end, logged_weekly, compound,
):
    """
    Print weekly breakdown with three columns of return%:
      - Logged%   : what the log file reports  (pnl / $10K for non-compound)
      - Norm%     : normalised = pnl / (trading_days × $10K)   [user's formula]
      - Pnl match : ✓ / ✗ MISMATCH vs logged dollar amount
    """
    print(f"\n{'=' * 95}")
    print(f"  WEEKLY BREAKDOWN")
    if not compound:
        print(f"  Return% columns: Logged% = pnl/$10K  |  Norm% = pnl/(trading_days×$10K)")
    print(f"{'=' * 95}")

    if compound:
        print(
            f"  {'Week':<10}  {'W/L':>10}  {'Calc P&L$':>11}  {'Log P&L$':>10}  "
            f"{'Diff':>7}  {'Portfolio':>12}  {'Match':>7}"
        )
        print(f"  {'-' * 87}")
        for wk in sorted(weekly_cap):
            calc_pnl = weekly_cap[wk]
            log_entry = logged_weekly.get(wk, {})
            log_pnl = log_entry.get("pnl", float("nan"))
            log_port = log_entry.get("portfolio", float("nan"))
            diff = calc_pnl - log_pnl
            match = "✓" if abs(diff) <= TOLERANCE else "✗"
            w = weekly_wins[wk]
            l = weekly_losses[wk]
            port = weekly_portfolio_end[wk]
            print(
                f"  {wk:<10}  {w}W/{l}L{'':<3}  {calc_pnl:>+11.2f}  {log_pnl:>+10.2f}  "
                f"{diff:>+7.4f}  {port:>12,.2f}  {match:>7}"
            )
    else:
        print(
            f"  {'Week':<10}  {'Days':>4}  {'W/L':>10}  {'Calc P&L$':>11}  {'Log P&L$':>10}  "
            f"{'Diff':>7}  {'Logged%':>8}  {'Norm%':>7}  {'Match':>7}"
        )
        print(f"  {'-' * 95}")
        for wk in sorted(weekly_cap):
            calc_pnl = weekly_cap[wk]
            n_days = weekly_days[wk]
            log_entry = logged_weekly.get(wk, {})
            log_pnl = log_entry.get("pnl", float("nan"))
            log_ret = log_entry.get("return_pct", float("nan"))
            diff = calc_pnl - log_pnl
            match = "✓" if abs(diff) <= TOLERANCE else "✗"
            norm_pct = calc_pnl / (n_days * INITIAL_CAPITAL) * 100
            w = weekly_wins[wk]
            l = weekly_losses[wk]
            print(
                f"  {wk:<10}  {n_days:>4}  {w}W/{l}L{'':<3}  {calc_pnl:>+11.2f}  {log_pnl:>+10.2f}  "
                f"{diff:>+7.4f}  {log_ret:>+7.2f}%  {norm_pct:>+6.2f}%  {match:>7}"
            )

    total_calc = sum(weekly_cap.values())
    total_log = sum(e["pnl"] for e in logged_weekly.values()) if logged_weekly else float("nan")
    total_diff = total_calc - total_log
    total_match = "✓" if abs(total_diff) <= TOLERANCE else "✗"
    total_w = sum(weekly_wins.values())
    total_l = sum(weekly_losses.values())
    print(f"  {'-' * (87 if compound else 95)}")

    if compound:
        print(
            f"  {'TOTAL':<10}  {total_w}W/{total_l}L{'':<3}  {total_calc:>+11.2f}  {total_log:>+10.2f}  "
            f"{total_diff:>+7.4f}  {'':>12}  {total_match:>7}"
        )
    else:
        total_days = sum(weekly_days.values())
        total_norm = total_calc / (total_days * INITIAL_CAPITAL) * 100
        total_log_ret = total_calc / INITIAL_CAPITAL * 100  # matches log's formula
        print(
            f"  {'TOTAL':<10}  {total_days:>4}  {total_w}W/{total_l}L{'':<3}  {total_calc:>+11.2f}  "
            f"{total_log:>+10.2f}  {total_diff:>+7.4f}  {total_log_ret:>+7.2f}%  "
            f"{total_norm:>+6.2f}%  {total_match:>7}"
        )


def _print_monthly_breakdown(
    monthly_cap, monthly_wins, monthly_losses, monthly_days,
    monthly_portfolio_end, logged_monthly, compound,
):
    """
    Print monthly breakdown.
    Non-compound return% formula: pnl / (trading_days × $10K).
    """
    print(f"\n{'=' * 95}")
    print(f"  MONTHLY BREAKDOWN")
    if not compound:
        print(f"  Norm% = pnl / (trading_days × $10K)")
    print(f"{'=' * 95}")

    if compound:
        print(
            f"  {'Month':<10}  {'W/L':>12}  {'Calc P&L$':>11}  {'Log P&L$':>10}  "
            f"{'Diff':>7}  {'Portfolio':>12}  {'Match':>7}"
        )
        print(f"  {'-' * 87}")
        for mo in sorted(monthly_cap):
            calc_pnl = monthly_cap[mo]
            log_entry = logged_monthly.get(mo, {})
            log_pnl = log_entry.get("pnl", float("nan"))
            diff = calc_pnl - log_pnl
            match = "✓" if abs(diff) <= TOLERANCE else "✗"
            w = monthly_wins[mo]
            l = monthly_losses[mo]
            port = monthly_portfolio_end[mo]
            print(
                f"  {mo:<10}  {w}W/{l}L{'':<5}  {calc_pnl:>+11.2f}  {log_pnl:>+10.2f}  "
                f"{diff:>+7.4f}  {port:>12,.2f}  {match:>7}"
            )
    else:
        print(
            f"  {'Month':<10}  {'Days':>4}  {'W/L':>12}  {'Calc P&L$':>11}  {'Log P&L$':>10}  "
            f"{'Diff':>7}  {'Logged%':>8}  {'Norm%':>7}  {'Match':>7}"
        )
        print(f"  {'-' * 95}")
        for mo in sorted(monthly_cap):
            calc_pnl = monthly_cap[mo]
            n_days = monthly_days[mo]
            log_entry = logged_monthly.get(mo, {})
            log_pnl = log_entry.get("pnl", float("nan"))
            log_ret = log_entry.get("return_pct", float("nan"))
            diff = calc_pnl - log_pnl
            match = "✓" if abs(diff) <= TOLERANCE else "✗"
            norm_pct = calc_pnl / (n_days * INITIAL_CAPITAL) * 100
            w = monthly_wins[mo]
            l = monthly_losses[mo]
            print(
                f"  {mo:<10}  {n_days:>4}  {w}W/{l}L{'':<5}  {calc_pnl:>+11.2f}  {log_pnl:>+10.2f}  "
                f"{diff:>+7.4f}  {log_ret:>+7.2f}%  {norm_pct:>+6.2f}%  {match:>7}"
            )

    total_calc = sum(monthly_cap.values())
    total_log = sum(e["pnl"] for e in logged_monthly.values()) if logged_monthly else float("nan")
    total_diff = total_calc - total_log
    total_match = "✓" if abs(total_diff) <= TOLERANCE else "✗"
    total_w = sum(monthly_wins.values())
    total_l = sum(monthly_losses.values())
    print(f"  {'-' * (87 if compound else 95)}")

    if compound:
        print(
            f"  {'TOTAL':<10}  {total_w}W/{total_l}L{'':<5}  {total_calc:>+11.2f}  {total_log:>+10.2f}  "
            f"{total_diff:>+7.4f}  {'':>12}  {total_match:>7}"
        )
    else:
        total_days = sum(monthly_days.values())
        total_norm = total_calc / (total_days * INITIAL_CAPITAL) * 100
        total_log_ret = total_calc / INITIAL_CAPITAL * 100
        print(
            f"  {'TOTAL':<10}  {total_days:>4}  {total_w}W/{total_l}L{'':<5}  {total_calc:>+11.2f}  "
            f"{total_log:>+10.2f}  {total_diff:>+7.4f}  {total_log_ret:>+7.2f}%  "
            f"{total_norm:>+6.2f}%  {total_match:>7}"
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Audit backtest P&L calculations.")
    parser.add_argument(
        "--log",
        default=None,
        help=(
            "Path to log file (relative to this script's directory). "
            f"Defaults to the compound log ({DEFAULT_LOG_COMPOUND}) unless "
            "--no-compound is given."
        ),
    )
    parser.add_argument(
        "--no-compound",
        action="store_true",
        help=f"Use the non-compound log ({DEFAULT_LOG_NO_COMPOUND}) as default.",
    )
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

    if args.log:
        log_path = args.log
    elif args.no_compound:
        log_path = DEFAULT_LOG_NO_COMPOUND
    else:
        log_path = DEFAULT_LOG_COMPOUND

    focus = date.fromisoformat(args.date) if args.date else None
    run_audit(
        log_path=log_path,
        focus_date=focus,
        verify_prices=args.verify_prices,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
