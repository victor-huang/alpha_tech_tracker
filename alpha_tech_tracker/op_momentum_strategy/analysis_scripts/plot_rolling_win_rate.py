"""
Temp script: plot rolling 20-day win rate per ticker over a date range.

Usage (from project root, with virtualenv active):
    python /tmp/plot_rolling_win_rate.py \
        --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
        --start 2026-05-01 --end 2026-06-03 \
        --hold EOD
"""
import argparse
import sys
from datetime import date, timedelta

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd



from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _add_ma_columns,
    _compute_hold_history,
    _DEFAULT_OR_BARS,
    _DEFAULT_OR_START,
)

_HOLD_KEY_MAP = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "5h": 300,
    "EOD": None,
}

_5MIN_WARMUP_DAYS = 45


def build_rolling_win_rates(ticker_bars_5m, trading_days, or_start, or_bars, hold_mins):
    """Return DataFrame[date × ticker] of rolling 20-day win rates for the given hold window."""
    records = {}
    for day in trading_days:
        row = {}
        for ticker, df in ticker_bars_5m.items():
            hist = _compute_hold_history(df, day, or_start, or_bars, lookback=20)
            if hist and hold_mins in hist["win_rates"]:
                row[ticker] = hist["win_rates"][hold_mins]
        records[day] = row
    return pd.DataFrame.from_dict(records, orient="index")


def main():
    parser = argparse.ArgumentParser(description="Plot rolling 20-day win rate per ticker")
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--hold", default="EOD", choices=list(_HOLD_KEY_MAP.keys()),
        help="Hold window to plot (default: EOD)"
    )
    parser.add_argument("--or-bars", type=int, default=_DEFAULT_OR_BARS)
    parser.add_argument("--or-start", default=_DEFAULT_OR_START)
    parser.add_argument("--out", default=None, help="Save chart to file instead of showing it")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    hold_mins = _HOLD_KEY_MAP[args.hold]
    hold_label = args.hold

    warmup_start = start_date - timedelta(days=_5MIN_WARMUP_DAYS)
    print(f"Fetching 5-min bars ({warmup_start} → {end_date}) [alpaca]...")
    bars_raw = fetch_bars(args.tickers, warmup_start, end_date, source="alpaca")
    ticker_bars_5m = {t: _add_ma_columns(df) for t, df in bars_raw.items() if not df.empty}

    trading_days = sorted({
        d for df in ticker_bars_5m.values()
        for d in df.index.date
        if start_date <= d <= end_date
    })
    print(f"Computing rolling win rates across {len(trading_days)} trading days…")

    wr_df = build_rolling_win_rates(ticker_bars_5m, trading_days, args.or_start, args.or_bars, hold_mins)
    if wr_df.empty:
        print("No data to plot.")
        return

    wr_df.index = pd.to_datetime(wr_df.index)

    fig, ax = plt.subplots(figsize=(16, 7))
    for ticker in sorted(wr_df.columns):
        series = wr_df[ticker].dropna()
        if not series.empty:
            ax.plot(series.index, series.values, label=ticker, linewidth=1.5)

    ax.axhline(50, color="black", linestyle="--", linewidth=0.8, alpha=0.5, label="50%")
    ax.set_title(
        f"Rolling 20-day win rate — {hold_label} hold  |  {args.start} to {args.end}",
        fontsize=13,
    )
    ax.set_ylabel("Win rate (%)")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    plt.xticks(rotation=45)
    ax.legend(fontsize=8, ncol=4, loc="lower left")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    if args.out:
        plt.savefig(args.out, dpi=150)
        print(f"Saved to {args.out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
