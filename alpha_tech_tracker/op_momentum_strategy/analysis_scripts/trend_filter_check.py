"""Trend filter check: the monitor's opt-in trend filters (trend_filters.py, Finding 40) applied to setup report trades.

For every trades.csv given (wave_risk_reward_setup_report output; each one a window), the trades at the report's fixed
exits of the filtered setups are split into kept / dropped by the filter decided at the session's previous daily
close, and compared per trade:

  pullback     pullback long, pullback long C1: kept on a higher 10-session high
  overnight    overnight always, overnight ma200: kept while QQQ is above its 200-day MA and up over 10 sessions

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.trend_filter_check \\
    backtest_result/wave_setups/2022-01-03_2022-06-30/trades.csv backtest_result/wave_setups/2023-01-03_2023-07-31/trades.csv
"""

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import daily_frames
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import REPORT_EXITS
from alpha_tech_tracker.op_momentum_strategy.trend_filters import (
    MARKET_TICKER,
    PULLBACK_SETUPS,
    TREND_FILTERS,
    market_trend,
    session_flags,
    ticker_trend,
)

FILTERED_SETUPS = {"pullback": PULLBACK_SETUPS, "overnight": ("overnight always", "overnight ma200")}


def load_report_trades(path):
    """A setup report's trades at the fixed exits: DataFrame(ticker, setup, day, pct)."""
    trades = pd.read_csv(path)
    trades = trades[[REPORT_EXITS.get(s) == x for s, x in zip(trades["setup"], trades["exit"])]]
    return pd.DataFrame({"ticker": trades["ticker"].values, "setup": trades["setup"].values,
                         "day": [date.fromisoformat(t[:10]) for t in trades["entry_time"]],
                         "pct": trades["net_pct"].astype(float).values})


def mark_kept(trades, daily, filters):
    """trades with `filter` (the filter that applies, or None) and `kept` (whether it lets the trade through)."""
    trades = trades.copy()
    trades["filter"] = None
    for name in filters:
        trades.loc[trades["setup"].isin(FILTERED_SETUPS[name]), "filter"] = name
    sessions = sorted(set(trades["day"]))
    night = session_flags(market_trend(daily[MARKET_TICKER]), sessions, "overnight_ok")
    higher_high = {}
    kept = []
    for ticker, day, name in zip(trades["ticker"], trades["day"], trades["filter"]):
        if name == "overnight":
            kept.append(night[day])
        elif name == "pullback":
            if ticker not in higher_high:
                higher_high[ticker] = (session_flags(ticker_trend(daily[ticker]), sessions, "pullback_ok")
                                       if ticker in daily else {})
            kept.append(higher_high[ticker].get(day, False))
        else:
            kept.append(True)
    trades["kept"] = kept
    return trades


def compare(trades):
    """Per filtered setup: trades, % per trade and sum for all / kept / dropped."""
    rows = []
    for setup, group in trades[trades["filter"].notna()].groupby("setup"):
        row = {"setup": setup}
        for label, part in (("all", group), ("kept", group[group["kept"]]), ("dropped", group[~group["kept"]])):
            row[f"{label} n"] = len(part)
            row[f"{label} %/trade"] = part["pct"].mean() if len(part) else float("nan")
            row[f"{label} sum %"] = part["pct"].sum()
        rows.append(row)
    return pd.DataFrame(rows).set_index("setup") if rows else pd.DataFrame()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trades", nargs="+", help="Setup report trades.csv files, one per window")
    parser.add_argument("--filters", nargs="+", choices=TREND_FILTERS, default=list(TREND_FILTERS))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    pd.set_option("display.width", 250)
    marked = []
    for path in args.trades:
        trades = load_report_trades(path)
        if trades.empty:
            print(f"{path}: no trades")
            continue
        daily = daily_frames(sorted(set(trades["ticker"])) + [MARKET_TICKER], min(trades["day"]), max(trades["day"]))
        window = mark_kept(trades, daily, args.filters).assign(window=Path(path).parent.name)
        marked.append(window)
        print(f"\n=== {Path(path).parent.name} ({min(trades['day'])} to {max(trades['day'])})")
        print(compare(window).to_string(float_format=lambda v: f"{v:+.2f}"))
    if len(marked) > 1:
        print("\n=== all windows")
        print(compare(pd.concat(marked)).to_string(float_format=lambda v: f"{v:+.2f}"))


if __name__ == "__main__":
    main()
