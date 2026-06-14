"""
Temp script: plot cumulative P&L curves per hold window for a single ticker.

Each line = one hold window (+15m, +30m, +1h, +2h, +5h, EOD).
Each day adds the forward return from the OR-close bar at that hold duration.
A healthy ticker shows all lines trending up with minor dips.

Usage:
    python /tmp/plot_ticker_hold_curves.py --ticker AMD --start 2026-05-01 --end 2026-06-03
    python /tmp/plot_ticker_hold_curves.py --ticker TSLA --start 2026-01-01 --end 2026-06-03
"""
import argparse
import sys
from datetime import date, datetime, timedelta

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd



from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _add_ma_columns,
    _forward_pct,
    _DEFAULT_OR_BARS,
    _DEFAULT_OR_START,
)

_HOLD_WINDOWS = [15, 30, 60, 120, 300, "EOD"]
_HOLD_LABELS = {15: "+15m", 30: "+30m", 60: "+1h", 120: "+2h", 300: "+5h", "EOD": "EOD"}
# _forward_pct uses None as the EOD sentinel; we store results under "EOD" to avoid
# pandas converting None column keys to NaN.
_HOLD_TO_MINS = {15: 15, 30: 30, 60: 60, 120: 120, 300: 300, "EOD": None}
_WARMUP_DAYS = 45


def build_daily_returns(df_5m, trading_days, or_start, or_bars):
    """Return DataFrame[date × hold_window] of raw forward returns from OR-close bar."""
    or_close_time = (
        datetime.strptime(or_start, "%H:%M") + timedelta(minutes=(or_bars - 1) * 5)
    ).time()

    records = {}
    for day in trading_days:
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

    return pd.DataFrame.from_dict(records, orient="index")


def main():
    parser = argparse.ArgumentParser(description="Cumulative P&L curves per hold window for a ticker")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--or-bars", type=int, default=_DEFAULT_OR_BARS)
    parser.add_argument("--or-start", default=_DEFAULT_OR_START)
    parser.add_argument("--out", default=None, help="Save chart to file path")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    warmup_start = start_date - timedelta(days=_WARMUP_DAYS)

    print(f"Fetching 5-min bars for {args.ticker} ({warmup_start} → {end_date})...")
    bars_raw = fetch_bars([args.ticker], warmup_start, end_date, source="alpaca")
    if args.ticker not in bars_raw or bars_raw[args.ticker].empty:
        print(f"No data for {args.ticker}")
        return
    df_5m = _add_ma_columns(bars_raw[args.ticker])

    trading_days = sorted({
        d for d in df_5m.index.date
        if start_date <= d <= end_date
    })
    print(f"Computing daily returns across {len(trading_days)} trading days...")

    returns_df = build_daily_returns(df_5m, trading_days, args.or_start, args.or_bars)
    if returns_df.empty:
        print("No data to plot.")
        return

    returns_df.index = pd.to_datetime(returns_df.index)
    cumulative_df = returns_df.cumsum()

    # ── Plot ─────────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]

    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    for i, hold_mins in enumerate(_HOLD_WINDOWS):
        if hold_mins not in cumulative_df.columns:
            continue
        series = cumulative_df[hold_mins].dropna()
        label = _HOLD_LABELS[hold_mins]
        ax.plot(series.index, series.values, label=label, linewidth=2, color=colors[i])

    ax.axhline(0, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.set_title(
        f"{args.ticker} — Cumulative OR-close return by hold window\n"
        f"{args.start} to {args.end}  |  OR: {args.or_start}/{args.or_bars}b  |  Unconditional entry every day",
        fontsize=12,
    )
    ax.set_ylabel("Cumulative return (%)")
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    plt.setp(ax.get_xticklabels(), rotation=45)

    # Daily bar chart of EOD returns (bottom panel)
    ax2 = axes[1]
    if "EOD" in returns_df.columns:
        eod = returns_df["EOD"].dropna()
        bar_colors = ["#2ca02c" if v >= 0 else "#d62728" for v in eod.values]
        x_pos = range(len(eod))
        ax2.bar(x_pos, eod.values, color=bar_colors, width=0.7, alpha=0.8)
        ax2.axhline(0, color="black", linewidth=0.6)
        ax2.set_ylabel("Daily EOD %")
        ax2.set_title("Daily EOD return", fontsize=9)
        tick_step = max(1, len(eod) // 10)
        ax2.set_xticks(list(x_pos)[::tick_step])
        ax2.set_xticklabels(
            [d.strftime("%m/%d") for d in eod.index[::tick_step]], rotation=45
        )
        ax2.set_xlim(-0.5, len(eod) - 0.5)
        ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    if args.out:
        plt.savefig(args.out, dpi=150)
        print(f"Saved to {args.out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
