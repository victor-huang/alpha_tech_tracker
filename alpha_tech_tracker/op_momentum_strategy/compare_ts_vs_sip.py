"""
compare_ts_vs_sip.py — compare TradeStation recorded 5-min bars vs Alpaca SIP for the same day.

Usage:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
      python alpha_tech_tracker/op_momentum_strategy/compare_ts_vs_sip.py \
      --tickers APP META COIN \
      --start 2026-04-27 --end 2026-05-01 \
      --live-data-dir alpha_tech_tracker/op_momentum_strategy/live_trade_market_data
"""
import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytz

from alpaca.data.enums import DataFeed
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_alpaca_bars

_ET = pytz.timezone("America/New_York")
_MARKET_OPEN = "09:30"
_MARKET_CLOSE = "15:55"
_OHLC = ["open", "high", "low", "close"]


def _trading_days(start: date, end: date) -> list:
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _load_ts_csv(live_data_dir: Path, day: date, ticker: str) -> pd.DataFrame:
    path = live_data_dir / str(day) / f"tradestation_{ticker}_5min.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(_ET)
    df = df.set_index("timestamp").sort_index()
    df = df.between_time(_MARKET_OPEN, _MARKET_CLOSE)
    df = df[~df.index.duplicated(keep="last")]
    day_str = str(day)
    df = df[df.index.strftime("%Y-%m-%d") == day_str]
    df.columns = [c.lower() for c in df.columns]
    return df[_OHLC + ["volume"]]


def _compare_ticker_day(ts_df: pd.DataFrame, sip_df: pd.DataFrame, ticker: str, day: date) -> pd.DataFrame:
    """Return a row-per-bar diff DataFrame for one ticker/day."""
    sip_day = sip_df[sip_df.index.strftime("%Y-%m-%d") == str(day)].copy()
    sip_day.columns = [c.lower() for c in sip_day.columns]

    merged = ts_df[_OHLC].join(sip_day[_OHLC], lsuffix="_ts", rsuffix="_sip", how="outer")
    rows = []
    for ts_idx, row in merged.iterrows():
        for field in _OHLC:
            ts_val = row.get(f"{field}_ts")
            sip_val = row.get(f"{field}_sip")
            if pd.isna(ts_val) or pd.isna(sip_val):
                continue
            diff = ts_val - sip_val
            pct = (diff / sip_val * 100) if sip_val != 0 else float("nan")
            rows.append({
                "ticker": ticker,
                "date": str(day),
                "bar_time": ts_idx.strftime("%H:%M"),
                "field": field,
                "ts": round(ts_val, 4),
                "sip": round(sip_val, 4),
                "diff": round(diff, 4),
                "diff_pct": round(pct, 4),
            })
    return pd.DataFrame(rows)


def _print_summary(all_diffs: pd.DataFrame):
    if all_diffs.empty:
        print("No overlapping bars found.")
        return

    total = len(all_diffs)
    nonzero = (all_diffs["diff"] != 0).sum()
    print(f"\n{'='*60}")
    print(f"Total bar-field comparisons : {total:,}")
    print(f"Exact matches               : {total - nonzero:,} ({(total-nonzero)/total*100:.1f}%)")
    print(f"Differences                 : {nonzero:,} ({nonzero/total*100:.1f}%)")

    if nonzero == 0:
        print("\nTS and SIP data are identical for all bars.")
        return

    diffs = all_diffs[all_diffs["diff"] != 0]

    print(f"\n--- Diff magnitude (when non-zero) ---")
    stats = diffs["diff_pct"].abs().describe(percentiles=[0.5, 0.9, 0.99])
    for label, val in stats.items():
        print(f"  {label:>6}: {val:.4f}%")

    print(f"\n--- By ticker ---")
    by_ticker = (
        diffs.groupby("ticker")
        .agg(
            diffs=("diff", "count"),
            mean_abs_pct=("diff_pct", lambda x: x.abs().mean()),
            max_abs_pct=("diff_pct", lambda x: x.abs().max()),
        )
        .round(4)
        .sort_values("mean_abs_pct", ascending=False)
    )
    print(by_ticker.to_string())

    print(f"\n--- By field ---")
    by_field = (
        diffs.groupby("field")
        .agg(
            diffs=("diff", "count"),
            mean_abs_pct=("diff_pct", lambda x: x.abs().mean()),
            max_abs_pct=("diff_pct", lambda x: x.abs().max()),
        )
        .round(4)
    )
    print(by_field.to_string())

    print(f"\n--- Top 10 largest absolute differences ---")
    top10 = diffs.reindex(diffs["diff_pct"].abs().nlargest(10).index)
    print(top10[["ticker", "date", "bar_time", "field", "ts", "sip", "diff", "diff_pct"]].to_string(index=False))

    print(f"\n--- Bars only in TS (missing from SIP) ---")
    ts_only = all_diffs[all_diffs["sip"].isna()]
    if ts_only.empty:
        print("  None")
    else:
        print(ts_only[["ticker", "date", "bar_time", "field"]].drop_duplicates().to_string(index=False))

    print(f"\n--- Bars only in SIP (missing from TS) ---")
    sip_only = all_diffs[all_diffs["ts"].isna()]
    if sip_only.empty:
        print("  None")
    else:
        print(sip_only[["ticker", "date", "bar_time", "field"]].drop_duplicates().to_string(index=False))


def run(tickers: list, start: date, end: date, live_data_dir: Path):
    print(f"Fetching Alpaca SIP bars for {tickers} from {start} to {end}...")
    sip_data = fetch_alpaca_bars(tickers, start, end, allow_intraday=False, feed=DataFeed.SIP)

    days = _trading_days(start, end)
    all_diffs = []

    for ticker in tickers:
        sip_df = sip_data.get(ticker, pd.DataFrame())
        for day in days:
            ts_df = _load_ts_csv(live_data_dir, day, ticker)
            if ts_df.empty:
                print(f"  [{ticker} {day}] no TS CSV — skipping")
                continue
            if sip_df.empty:
                print(f"  [{ticker} {day}] no SIP data — skipping")
                continue
            diff_df = _compare_ticker_day(ts_df, sip_df, ticker, day)
            ts_bars = len(ts_df)
            sip_bars = len(sip_df[sip_df.index.strftime("%Y-%m-%d") == str(day)])
            print(f"  [{ticker} {day}] TS bars={ts_bars}  SIP bars={sip_bars}  diffs={len(diff_df)}")
            all_diffs.append(diff_df)

    if all_diffs:
        combined = pd.concat(all_diffs, ignore_index=True)
        _print_summary(combined)


def _parse_args():
    parser = argparse.ArgumentParser(description="Compare TradeStation recorded CSV vs Alpaca SIP 5-min bars")
    parser.add_argument("--tickers", nargs="+", default=["APP", "META", "COIN"])
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--live-data-dir",
        default="alpha_tech_tracker/op_momentum_strategy/live_trade_market_data",
        help="Root dir containing date subdirs with tradestation_*_5min.csv files",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        tickers=args.tickers,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        live_data_dir=Path(args.live_data_dir),
    )
