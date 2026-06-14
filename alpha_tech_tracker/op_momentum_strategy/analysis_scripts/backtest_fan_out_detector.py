"""
Backtest the fan-out curve early detection signals on 2026 data.

For each calendar month:
  - Detection window: first 5 trading days
  - Validation window: remaining trading days

Signals computed on detection window:
  1. Cumulative EOD slope (linear regression)
  2. R² of that fit
  3. Fan-out ratio: EOD_cumul / +1h_cumul
  4. EOD win rate over detection window
  5. Max drawdown of cumulative EOD curve

A ticker is flagged if it passes configurable thresholds on all signals.
Reports: detected vs undetected avg EOD return in validation window.
"""
import sys
import argparse
from datetime import date, datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd



from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _add_ma_columns,
    _forward_pct,
    _DEFAULT_OR_BARS,
    _DEFAULT_OR_START,
)

_HOLD_WINDOWS = [15, 30, 60, 120, 300, "EOD"]
_HOLD_TO_MINS = {15: 15, 30: 30, 60: 60, 120: 120, 300: 300, "EOD": None}
_WARMUP_DAYS = 45


def _daily_returns(df_5m, days, or_start, or_bars):
    """Return dict {day: {hold_key: pct}} for the given days."""
    or_close_time = (
        datetime.strptime(or_start, "%H:%M") + timedelta(minutes=(or_bars - 1) * 5)
    ).time()
    records = {}
    for day in days:
        day_df = df_5m[df_5m.index.date == day]
        if day_df.empty:
            continue
        row = {}
        for hold_key in _HOLD_WINDOWS:
            pct = _forward_pct(day_df, or_close_time, day, _HOLD_TO_MINS[hold_key])
            if pct is not None:
                row[hold_key] = pct
        if row:
            records[day] = row
    return records


def _compute_signals(daily_rets):
    """
    Compute detection signals from a dict of {day: {hold_key: pct}}.
    Returns a dict of signal values, or None if insufficient data.
    """
    days = sorted(daily_rets.keys())
    if len(days) < 3:
        return None

    eod_vals = [daily_rets[d]["EOD"] for d in days if "EOD" in daily_rets[d]]
    h1_vals  = [daily_rets[d][60]    for d in days if 60    in daily_rets[d]]
    if len(eod_vals) < 3:
        return None

    eod_cumul = np.cumsum(eod_vals)
    h1_cumul  = np.cumsum(h1_vals) if h1_vals else None

    # 1 & 2: slope + R² of cumulative EOD
    x = np.arange(len(eod_cumul), dtype=float)
    slope, intercept = np.polyfit(x, eod_cumul, 1)
    fitted = slope * x + intercept
    ss_res = np.sum((eod_cumul - fitted) ** 2)
    ss_tot = np.sum((eod_cumul - eod_cumul.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # 3: fan-out ratio
    eod_total = eod_cumul[-1]
    if h1_cumul is not None and len(h1_cumul) > 0:
        h1_total = h1_cumul[-1]
        fan_out = eod_total / h1_total if abs(h1_total) > 0.01 else (10.0 if eod_total > 0 else -10.0)
    else:
        fan_out = None

    # 4: EOD win rate
    win_rate = sum(1 for v in eod_vals if v > 0) / len(eod_vals)

    # 5: max drawdown of cumulative EOD
    peak = eod_cumul[0]
    max_dd = 0.0
    for v in eod_cumul:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    return {
        "eod_total": eod_total,
        "slope": slope,
        "r2": r2,
        "fan_out": fan_out,
        "win_rate": win_rate,
        "max_dd": max_dd,
        "n_days": len(eod_vals),
    }


def _passes(sig, slope_min, r2_min, fan_out_min, win_rate_min, max_dd_max):
    if sig is None:
        return False
    if sig["slope"] < slope_min:
        return False
    if sig["r2"] < r2_min:
        return False
    if sig["fan_out"] is not None and sig["fan_out"] < fan_out_min:
        return False
    if sig["win_rate"] < win_rate_min:
        return False
    if sig["max_dd"] > max_dd_max:
        return False
    return True


def run_backtest(tickers, start_date, end_date, or_start, or_bars,
                 detect_days, slope_min, r2_min, fan_out_min, win_rate_min, max_dd_max):

    warmup_start = start_date - timedelta(days=_WARMUP_DAYS)
    print(f"Fetching 5-min bars ({warmup_start} → {end_date}) [alpaca]...")
    bars_raw = fetch_bars(tickers, warmup_start, end_date, source="alpaca")
    ticker_bars = {t: _add_ma_columns(df) for t, df in bars_raw.items() if not df.empty}

    all_trading_days = sorted({
        d for df in ticker_bars.values()
        for d in df.index.date
        if start_date <= d <= end_date
    })

    # Group trading days by calendar month
    months = defaultdict(list)
    for d in all_trading_days:
        months[(d.year, d.month)].append(d)

    print(f"\nThresholds: slope≥{slope_min}  R²≥{r2_min}  fan-out≥{fan_out_min}  "
          f"win-rate≥{win_rate_min:.0%}  max-dd≤{max_dd_max}%")
    print(f"Detection window: first {detect_days} trading days of each month\n")

    all_detected_val   = []
    all_undetected_val = []
    month_rows = []

    for (yr, mo), days in sorted(months.items()):
        if len(days) < detect_days + 3:
            continue
        detect_days_list = days[:detect_days]
        val_days_list    = days[detect_days:]
        month_label = f"{yr}-{mo:02d}"

        detected = []
        undetected = []

        for ticker, df in ticker_bars.items():
            det_rets = _daily_returns(df, detect_days_list, or_start, or_bars)
            sig = _compute_signals(det_rets)
            val_rets = _daily_returns(df, val_days_list, or_start, or_bars)
            val_eod = sum(r.get("EOD", 0) for r in val_rets.values())
            val_wr  = (sum(1 for r in val_rets.values() if r.get("EOD", 0) > 0) /
                       len(val_rets) if val_rets else None)

            row = {
                "month": month_label,
                "ticker": ticker,
                "detected": _passes(sig, slope_min, r2_min, fan_out_min, win_rate_min, max_dd_max),
                "det_slope":    round(sig["slope"], 3)    if sig else None,
                "det_r2":       round(sig["r2"], 2)       if sig else None,
                "det_fan_out":  round(sig["fan_out"], 2)  if sig and sig["fan_out"] is not None else None,
                "det_win_rate": round(sig["win_rate"], 2) if sig else None,
                "det_max_dd":   round(sig["max_dd"], 2)   if sig else None,
                "det_eod_total":round(sig["eod_total"], 2)if sig else None,
                "val_eod_total": round(val_eod, 2),
                "val_win_rate":  round(val_wr, 2) if val_wr is not None else None,
            }
            month_rows.append(row)

            if row["detected"]:
                detected.append((ticker, val_eod, val_wr))
                all_detected_val.append(val_eod)
            else:
                undetected.append((ticker, val_eod, val_wr))
                all_undetected_val.append(val_eod)

        # Per-month summary
        print(f"{'─'*70}")
        print(f"{month_label}  |  detect={detect_days_list[0]}→{detect_days_list[-1]}  "
              f"val={val_days_list[0]}→{val_days_list[-1]}  ({len(val_days_list)} days)")
        print(f"  DETECTED ({len(detected)}):")
        for t, v, w in sorted(detected, key=lambda x: -x[1]):
            wr_str = f"{w:.0%}" if w is not None else "?"
            print(f"    {t:<8} val EOD cumul: {v:>+6.2f}%  win rate: {wr_str}")
        if not detected:
            print("    (none)")
        print(f"  NOT DETECTED ({len(undetected)}) — top 5 by val EOD:")
        for t, v, w in sorted(undetected, key=lambda x: -x[1])[:5]:
            wr_str = f"{w:.0%}" if w is not None else "?"
            print(f"    {t:<8} val EOD cumul: {v:>+6.2f}%  win rate: {wr_str}")

    # Overall summary
    print(f"\n{'='*70}")
    print(f"OVERALL SUMMARY  ({start_date} → {end_date})")
    print(f"{'='*70}")
    n_det   = len(all_detected_val)
    n_undet = len(all_undetected_val)
    avg_det   = sum(all_detected_val)   / n_det   if n_det   else 0
    avg_undet = sum(all_undetected_val) / n_undet if n_undet else 0
    det_wr   = sum(1 for v in all_detected_val   if v > 0) / n_det   if n_det   else 0
    undet_wr = sum(1 for v in all_undetected_val if v > 0) / n_undet if n_undet else 0
    print(f"  Detected     : {n_det:>3} ticker-months  avg val EOD: {avg_det:>+6.2f}%  win rate: {det_wr:.0%}")
    print(f"  Not detected : {n_undet:>3} ticker-months  avg val EOD: {avg_undet:>+6.2f}%  win rate: {undet_wr:.0%}")
    print(f"  Edge         : {avg_det - avg_undet:>+6.2f}% avg EOD per ticker-month")

    # Per-month aggregation table
    df = pd.DataFrame(month_rows)
    print(f"\n{'─'*70}")
    print("Per-month avg validation EOD — detected vs not detected:")
    print(f"  {'Month':<10} {'Det avg':>9} {'Undet avg':>11} {'Edge':>8} {'N det':>7} {'N undet':>9}")
    print(f"  {'-'*55}")
    for month_label, grp in df.groupby("month"):
        det_grp   = grp[grp["detected"]]
        undet_grp = grp[~grp["detected"]]
        d_avg = det_grp["val_eod_total"].mean() if not det_grp.empty else float("nan")
        u_avg = undet_grp["val_eod_total"].mean() if not undet_grp.empty else float("nan")
        edge  = d_avg - u_avg
        print(f"  {month_label:<10} {d_avg:>+8.2f}%  {u_avg:>+9.2f}%  {edge:>+7.2f}%  "
              f"{len(det_grp):>5}  {len(undet_grp):>7}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--start",   default="2026-01-01")
    parser.add_argument("--end",     default="2026-06-03")
    parser.add_argument("--or-bars",      type=int,   default=_DEFAULT_OR_BARS)
    parser.add_argument("--or-start",               default=_DEFAULT_OR_START)
    parser.add_argument("--detect-days",  type=int,   default=5)
    parser.add_argument("--slope-min",    type=float, default=0.3)
    parser.add_argument("--r2-min",       type=float, default=0.6)
    parser.add_argument("--fan-out-min",  type=float, default=1.5)
    parser.add_argument("--win-rate-min", type=float, default=0.6)
    parser.add_argument("--max-dd-max",   type=float, default=3.0)
    args = parser.parse_args()

    run_backtest(
        tickers=args.tickers,
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        or_start=args.or_start,
        or_bars=args.or_bars,
        detect_days=args.detect_days,
        slope_min=args.slope_min,
        r2_min=args.r2_min,
        fan_out_min=args.fan_out_min,
        win_rate_min=args.win_rate_min,
        max_dd_max=args.max_dd_max,
    )


if __name__ == "__main__":
    main()
