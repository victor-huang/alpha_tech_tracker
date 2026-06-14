"""
Rolling 5-day fan-out detector backtest with regime gate.

For each trading day D:
  - Gate: skip if monthly regime = CAUTION or SHORT
  - Detection window: last 5 trading days ending at D (inclusive)
  - Validation window: next N trading days after D

Compares avg forward EOD return for detected vs undetected ticker-days.
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
_WARMUP_DAYS = 60

# Monthly regime from MASTER_REGIME_SUMMARY
# LONG/MILD_BULL/NEUTRAL = run detection
# CAUTION = skip (require explicit day-3 confirmation first)
# SHORT = skip entirely
_MONTHLY_REGIME = {
    1:  "LONG",       # January
    2:  "NEUTRAL",    # February — mixed seasonal; CAUTION added for 2026 only (Feb 2026 bear)
    3:  "CAUTION",    # March — no position until day-3 confirms
    4:  "NEUTRAL",    # April
    5:  "MILD_BULL",  # May
    6:  "NEUTRAL",    # June
    7:  "NEUTRAL",    # July
    8:  "CAUTION",    # August
    9:  "SHORT",      # September
    10: "LONG",       # October
    11: "NEUTRAL",    # November
    12: "SHORT",      # December
}
_SKIP_REGIMES = {"CAUTION", "SHORT"}


def _daily_returns_for_days(df_5m, days, or_start, or_bars):
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
    days = sorted(daily_rets.keys())
    if len(days) < 3:
        return None

    eod_vals = [daily_rets[d]["EOD"] for d in days if "EOD" in daily_rets[d]]
    h1_vals  = [daily_rets[d][60]    for d in days if 60    in daily_rets[d]]
    if len(eod_vals) < 3:
        return None

    eod_cumul = np.cumsum(eod_vals)

    x = np.arange(len(eod_cumul), dtype=float)
    slope, _ = np.polyfit(x, eod_cumul, 1)
    fitted = slope * x + np.mean(eod_cumul - slope * x)
    ss_res = np.sum((eod_cumul - fitted) ** 2)
    ss_tot = np.sum((eod_cumul - eod_cumul.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    eod_total = eod_cumul[-1]
    if h1_vals and len(h1_vals) >= 3:
        h1_total = float(np.sum(h1_vals))
        fan_out = eod_total / h1_total if abs(h1_total) > 0.01 else (10.0 if eod_total > 0 else -10.0)
    else:
        fan_out = None

    win_rate = sum(1 for v in eod_vals if v > 0) / len(eod_vals)

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


def _cross_ticker_eod_win_rate(ticker_bars, days, or_start, or_bars):
    """Return fraction of (ticker, day) pairs with positive EOD return over the window."""
    wins = total = 0
    for df in ticker_bars.values():
        rets = _daily_returns_for_days(df, days, or_start, or_bars)
        for r in rets.values():
            if "EOD" in r:
                total += 1
                if r["EOD"] > 0:
                    wins += 1
    return wins / total if total > 0 else None


def run_backtest(tickers, start_date, end_date, or_start, or_bars,
                 detect_days, forward_days,
                 slope_min, r2_min, fan_out_min, win_rate_min, max_dd_max,
                 market_wr_min=0.45):

    warmup_start = start_date - timedelta(days=_WARMUP_DAYS)
    print(f"Fetching 5-min bars ({warmup_start} → {end_date}) [alpaca]...")
    bars_raw = fetch_bars(tickers, warmup_start, end_date, source="alpaca")
    ticker_bars = {t: _add_ma_columns(df) for t, df in bars_raw.items() if not df.empty}

    all_trading_days = sorted({
        d for df in ticker_bars.values()
        for d in df.index.date
        if start_date <= d <= end_date
    })

    print(f"\nThresholds: slope≥{slope_min}  R²≥{r2_min}  fan-out≥{fan_out_min}  "
          f"win-rate≥{win_rate_min:.0%}  max-dd≤{max_dd_max}%")
    print(f"Detection: weekly (Monday) rolling {detect_days}d lookback  |  Validation: next {forward_days} trading days")
    print(f"Regime gate: skip {sorted(_SKIP_REGIMES)} months")
    print(f"Market gate: cross-ticker EOD win rate ≥ {market_wr_min:.0%} over detection window\n")

    rows = []
    skipped_regime = 0

    # Index each trading day so we can find the first trading day of each week
    day_to_idx = {d: i for i, d in enumerate(all_trading_days)}

    # Build set of first trading days per (year, isoweek)
    first_of_week = set()
    seen_weeks = set()
    for d in all_trading_days:
        wk = (d.isocalendar()[0], d.isocalendar()[1])
        if wk not in seen_weeks:
            seen_weeks.add(wk)
            first_of_week.add(d)

    for i, day in enumerate(all_trading_days):
        # Only evaluate on the first trading day of each week (Monday or next open)
        if day not in first_of_week:
            continue

        # Regime gate
        regime = _MONTHLY_REGIME.get(day.month, "NEUTRAL")
        if regime in _SKIP_REGIMES:
            skipped_regime += 1
            continue

        # Need detect_days prior days + forward_days after
        if i < detect_days:
            continue
        if i + forward_days >= len(all_trading_days):
            continue

        det_window  = all_trading_days[i - detect_days: i]
        fwd_window  = all_trading_days[i + 1: i + 1 + forward_days]

        # Market momentum gate: cross-ticker EOD win rate over detection window
        market_wr = _cross_ticker_eod_win_rate(ticker_bars, det_window, or_start, or_bars)
        if market_wr is not None and market_wr < market_wr_min:
            continue

        for ticker, df in ticker_bars.items():
            det_rets = _daily_returns_for_days(df, det_window, or_start, or_bars)
            sig = _compute_signals(det_rets)
            detected = _passes(sig, slope_min, r2_min, fan_out_min, win_rate_min, max_dd_max)

            fwd_rets = _daily_returns_for_days(df, fwd_window, or_start, or_bars)
            fwd_eod = [r.get("EOD", 0) for r in fwd_rets.values()]
            fwd_total = sum(fwd_eod)
            fwd_wr = sum(1 for v in fwd_eod if v > 0) / len(fwd_eod) if fwd_eod else None

            rows.append({
                "day": day,
                "month": f"{day.year}-{day.month:02d}",
                "regime": regime,
                "ticker": ticker,
                "detected": detected,
                "fwd_eod_total": round(fwd_total, 3),
                "fwd_win_rate": round(fwd_wr, 2) if fwd_wr is not None else None,
                "det_slope":    round(sig["slope"], 3)    if sig else None,
                "det_r2":       round(sig["r2"], 2)       if sig else None,
                "det_fan_out":  round(sig["fan_out"], 2)  if sig and sig["fan_out"] is not None else None,
                "det_win_rate": round(sig["win_rate"], 2) if sig else None,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No data.")
        return

    det   = df[df["detected"]]
    undet = df[~df["detected"]]

    print(f"{'='*70}")
    print(f"OVERALL  ({start_date} → {end_date})")
    print(f"{'='*70}")
    print(f"  Total ticker-days evaluated : {len(df):>6}  (skipped {skipped_regime} regime-gated days)")
    print(f"  Detected                    : {len(det):>6}  ({len(det)/len(df)*100:.1f}%)")
    print(f"  Not detected                : {len(undet):>6}")
    print()

    def _summary(label, subset):
        if subset.empty:
            print(f"  {label}: no data")
            return
        avg   = subset["fwd_eod_total"].mean()
        med   = subset["fwd_eod_total"].median()
        wr    = (subset["fwd_eod_total"] > 0).mean()
        print(f"  {label:<16}  avg {forward_days}d EOD: {avg:>+6.2f}%  "
              f"median: {med:>+6.2f}%  win rate: {wr:.0%}  n={len(subset)}")

    _summary("DETECTED",     det)
    _summary("NOT DETECTED", undet)
    edge = det["fwd_eod_total"].mean() - undet["fwd_eod_total"].mean()
    print(f"\n  Edge: {edge:>+.2f}% avg {forward_days}d EOD per ticker-day")

    # Per-month breakdown
    print(f"\n{'─'*70}")
    print(f"{'Month':<10} {'Regime':<12} {'Det avg':>9} {'Undet avg':>11} {'Edge':>8} {'N det':>7} {'N undet':>9}")
    print(f"{'─'*70}")
    for month, grp in df.groupby("month"):
        regime = grp["regime"].iloc[0]
        d_grp = grp[grp["detected"]]
        u_grp = grp[~grp["detected"]]
        d_avg = d_grp["fwd_eod_total"].mean() if not d_grp.empty else float("nan")
        u_avg = u_grp["fwd_eod_total"].mean() if not u_grp.empty else float("nan")
        edge_m = d_avg - u_avg
        print(f"{month:<10} {regime:<12} {d_avg:>+8.2f}%  {u_avg:>+9.2f}%  "
              f"{edge_m:>+7.2f}%  {len(d_grp):>5}  {len(u_grp):>7}")

    # Weekly P&L table — one row per Monday, shows detected tickers + realized return
    position_size = 10_000
    print(f"\n{'─'*70}")
    print(f"WEEK-BY-WEEK  (assuming ${position_size:,} per detected ticker)")
    print(f"{'─'*70}")
    print(f"{'Monday':<12} {'Regime':<12} {'Detected tickers + 15d return':<45} {'Week P&L':>10}")
    print(f"{'─'*70}")

    monthly_pnl = defaultdict(float)
    monthly_det = defaultdict(int)
    for monday, grp in df[df["detected"]].groupby("day"):
        regime = grp["regime"].iloc[0]
        tickers_str = "  ".join(
            f"{r['ticker']}({r['fwd_eod_total']:+.1f}%)"
            for _, r in grp.sort_values("fwd_eod_total", ascending=False).iterrows()
        )
        week_pnl = sum(r["fwd_eod_total"] / 100 * position_size for _, r in grp.iterrows())
        mo = f"{monday.year}-{monday.month:02d}"
        monthly_pnl[mo] += week_pnl
        monthly_det[mo] += len(grp)
        print(f"{str(monday):<12} {regime:<12} {tickers_str:<45} ${week_pnl:>+9,.0f}")

    print(f"\n{'─'*70}")
    print(f"MONTHLY SUMMARY  (${position_size:,}/detected ticker, non-compounded)")
    print(f"{'─'*70}")
    print(f"{'Month':<12} {'Detections':>11} {'Monthly P&L':>13} {'Avg/detection':>15}")
    print(f"{'─'*50}")
    total_pnl = 0
    for mo in sorted(monthly_pnl):
        n = monthly_det[mo]
        pnl = monthly_pnl[mo]
        total_pnl += pnl
        print(f"{mo:<12} {n:>11}  ${pnl:>+12,.0f}  ${pnl/n:>+13,.0f}")
    print(f"{'─'*50}")
    total_det = sum(monthly_det.values())
    print(f"{'TOTAL':<12} {total_det:>11}  ${total_pnl:>+12,.0f}  ${total_pnl/total_det if total_det else 0:>+13,.0f}")

    # Per-ticker summary
    print(f"\n{'─'*70}")
    print("Per-ticker: avg forward EOD (detected days only), sorted by avg")
    print(f"{'─'*70}")
    print(f"{'Ticker':<8} {'Det days':>9} {'Avg fwd EOD':>12} {'Median':>8} {'Win rate':>10}")
    print(f"{'─'*50}")
    ticker_stats = (
        det.groupby("ticker")["fwd_eod_total"]
        .agg(["count", "mean", "median", lambda x: (x > 0).mean()])
        .rename(columns={"<lambda_0>": "wr"})
        .sort_values("mean", ascending=False)
    )
    for ticker, row in ticker_stats.iterrows():
        print(f"{ticker:<8} {int(row['count']):>9}  {row['mean']:>+10.2f}%  "
              f"{row['median']:>+7.2f}%  {row['wr']:>9.0%}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--start",   default="2026-01-01")
    parser.add_argument("--end",     default="2026-06-03")
    parser.add_argument("--or-bars",      type=int,   default=_DEFAULT_OR_BARS)
    parser.add_argument("--or-start",               default=_DEFAULT_OR_START)
    parser.add_argument("--detect-days",  type=int,   default=5)
    parser.add_argument("--forward-days", type=int,   default=5)
    parser.add_argument("--slope-min",    type=float, default=0.3)
    parser.add_argument("--r2-min",       type=float, default=0.6)
    parser.add_argument("--fan-out-min",  type=float, default=1.5)
    parser.add_argument("--win-rate-min", type=float, default=0.6)
    parser.add_argument("--max-dd-max",     type=float, default=3.0)
    parser.add_argument("--market-wr-min",  type=float, default=0.45,
                        help="Min cross-ticker EOD win rate over detection window (default 0.45)")
    args = parser.parse_args()

    run_backtest(
        tickers=args.tickers,
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        or_start=args.or_start,
        or_bars=args.or_bars,
        detect_days=args.detect_days,
        forward_days=args.forward_days,
        slope_min=args.slope_min,
        r2_min=args.r2_min,
        fan_out_min=args.fan_out_min,
        win_rate_min=args.win_rate_min,
        max_dd_max=args.max_dd_max,
        market_wr_min=args.market_wr_min,
    )


if __name__ == "__main__":
    main()
