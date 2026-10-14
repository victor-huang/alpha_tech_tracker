"""Drive long + overnight hold on one ticker vs buying and holding it, over one or more periods.

For each period it reports P&L, return and max drawdown of buy and hold against:
  drive long only     green first 5-min bar, buy its close, hold to the session close; stop at the
                      first bar's low, or that low minus `--avg-bar-stop` x the average 5-min bar range
                      of the previous 78 bars (the wider stop, ticker-tuning doc Finding 28)
  overnight only      buy the 15:55 close, sell the next open: above the daily MA200, every night, and
                      every night including earnings nights (the setup skips those by default)
  drive long + overnight, for every stop x overnight variant above

Every trade is `--size` dollars (not compounded) with `--cost-bps` round-trip costs; drive long exits at
the close as the overnight hold enters, so both legs share one slot. Buy and hold buys `--size` at the
period's first open and sells at its last close. Drawdowns are on the summed P&L, as % of `--size`.

Bars are split-adjusted Alpaca SIP 5-min bars fetched directly (about 14 months of warm-up for the
daily MA200), ending at today at the latest; needs ALPACA_API_KEY and ALPACA_SECRET_KEY. Earnings
release dates come from earnings_calendar.py. `--since` drops every bar before a date, for a new listing
or a reused symbol (SPCX was an ETF until the company listed on 2026-06-12); the overnight MA200 filter
then needs 200 sessions after it before it can fire.

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_vs_buy_hold \\
    SNPS --period 2023-06-18:2024-04-05

  # several periods, a $5k slot, wider stop at 3 x the average bar, every row to CSV
  ... wave_setup_vs_buy_hold META --period 2024-09-19:2025-02-21 --period 2025-05-01:2025-09-29 \\
      --size 5000 --avg-bar-stop 3 --csv-out meta_vs_hold.csv
"""

import argparse
import os
from datetime import date, datetime, timedelta

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import ticker_earnings_windows
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    WaveRiskRewardParams,
    add_moving_averages,
    analyze_bars,
    regular_hours,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import TradeSimulator, apply_costs

DEFAULT_SIZE = 10000.0
DEFAULT_COST_BPS = 5.0
DEFAULT_AVG_BAR_STOP = 2.0
AVG_BAR_WINDOW = 78  # one session of 5-min bars
WARMUP_DAYS = 430  # the daily MA200 for the overnight filter, plus a margin
FIRST_BAR_STOP = "first-bar low stop"
OVERNIGHT_VARIANTS = (("above MA200", "ma200", True), ("every night", "always", True),
                      ("every night incl. earnings", "always", False))


def parse_period(text):
    """'YYYY-MM-DD:YYYY-MM-DD' -> (start, end)."""
    try:
        start, end = (date.fromisoformat(part) for part in text.split(":"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD:YYYY-MM-DD, got {text!r}")
    if end < start:
        raise argparse.ArgumentTypeError(f"period end {end} is before its start {start}")
    return start, end


def fetch_bars(ticker, start, end):
    """Regular-hours split-adjusted 5-min SIP bars with moving averages, `start`..`end` (capped at today)."""
    client = StockHistoricalDataClient(os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY"))
    request = StockBarsRequest(
        symbol_or_symbols=[ticker], timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(min(end, date.today()), datetime.min.time()),
        feed=DataFeed.SIP, adjustment=Adjustment.SPLIT,
    )
    raw = client.get_stock_bars(request).df.xs(ticker, level=0)
    raw.index = raw.index.tz_convert("America/New_York")
    return add_moving_averages(regular_hours(raw[["open", "high", "low", "close"]]))


def drive_long_trades(bars, avg_bar_stop=DEFAULT_AVG_BAR_STOP, cost_bps=DEFAULT_COST_BPS):
    """Every drive long day with both stops: rows of day, time, net_pct, stop."""
    avg_bar = (bars["high"] - bars["low"]).rolling(AVG_BAR_WINDOW, min_periods=AVG_BAR_WINDOW // 2).mean().shift(1)
    wide_label = f"{avg_bar_stop:g}x avg-bar stop"
    rows = []
    for day, session in bars.groupby(bars.index.date):
        o, l, c = (session[k].values for k in ("open", "low", "close"))
        if len(c) < 3 or not c[0] > o[0]:
            continue
        stops = [(FIRST_BAR_STOP, l[0])]
        if pd.notna(avg_bar.loc[session.index[0]]):
            stops.append((wide_label, l[0] - avg_bar_stop * avg_bar.loc[session.index[0]]))
        for label, stop in stops:
            exit_price = c[-1]
            for j in range(1, len(c)):
                if l[j] <= stop:
                    exit_price = min(o[j], stop)
                    break
            rows.append({"day": day, "time": session.index[0], "net_pct": (exit_price / c[0] - 1) * 100 - cost_bps / 100,
                         "stop": label})
    return pd.DataFrame(rows, columns=["day", "time", "net_pct", "stop"])


def overnight_trades(bars, mode, skip_earnings, earnings_windows, cost_bps=DEFAULT_COST_BPS):
    """Overnight holds from analyze_bars: rows of day, time, net_pct."""
    params = WaveRiskRewardParams(box_signals=False, overnight_hold=mode, overnight_skip_earnings=skip_earnings)
    simulator = TradeSimulator(bars)
    rows = []
    for signal in analyze_bars(bars, params, earnings_windows)["signals"]:
        trade = simulator.run(signal, "eod")
        if trade:
            rows.append({"day": signal["time"].date(), "time": signal["time"],
                         "net_pct": apply_costs(trade, cost_bps)["net_pct"]})
    return pd.DataFrame(rows, columns=["day", "time", "net_pct"])


def buy_and_hold(bars, start, end):
    """(return %, max drawdown % of daily closes) from the period's first open to its last close."""
    span = bars[(bars.index.date >= start) & (bars.index.date <= end)]
    closes = span["close"].groupby(span.index.date).last()
    return (span["close"].iloc[-1] / span["open"].iloc[0] - 1) * 100, ((closes / closes.cummax()) - 1).min() * 100


def strategy_result(trades, start, end, size=DEFAULT_SIZE):
    """P&L $, return % and max drawdown % of `size` for the trades entered in start..end."""
    window = trades[(trades["day"] >= start) & (trades["day"] <= end)].sort_values("time")
    pnl = window["net_pct"] / 100 * size
    curve = pnl.cumsum()
    drawdown = (curve - curve.cummax()).min() if len(curve) else 0.0
    return {"P&L $": pnl.sum(), "return %": 100 * pnl.sum() / size, "max DD %": 100 * drawdown / size, "trades": len(window)}


def compare(bars, periods, earnings_windows, size=DEFAULT_SIZE, cost_bps=DEFAULT_COST_BPS, avg_bar_stop=DEFAULT_AVG_BAR_STOP):
    """One row per period x strategy, buy and hold first in each period."""
    drive = drive_long_trades(bars, avg_bar_stop, cost_bps)
    overnight = {name: overnight_trades(bars, mode, skip, earnings_windows, cost_bps)
                 for name, mode, skip in OVERNIGHT_VARIANTS}
    stops = list(dict.fromkeys(drive["stop"]))
    strategies = [(f"drive long only, {stop}", [drive[drive["stop"] == stop]]) for stop in stops]
    strategies += [(f"overnight {name} only", [trades]) for name, trades in overnight.items()]
    strategies += [(f"drive long ({stop}) + overnight {name}", [drive[drive["stop"] == stop], trades])
                   for stop in stops for name, trades in overnight.items()]
    rows = []
    for start, end in periods:
        label = f"{start:%m/%d/%Y}-{end:%m/%d/%Y}"
        hold_return, hold_drawdown = buy_and_hold(bars, start, end)
        hold_pnl = size * hold_return / 100
        rows.append({"period": label, "strategy": "buy & hold", "P&L $": hold_pnl, "return %": hold_return,
                     "max DD %": hold_drawdown, "trades": 1, "vs buy & hold $": 0.0})
        for name, parts in strategies:
            result = strategy_result(pd.concat(parts), start, end, size)
            rows.append({"period": label, "strategy": name, **result, "vs buy & hold $": result["P&L $"] - hold_pnl})
    return pd.DataFrame(rows)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ticker")
    parser.add_argument("--period", dest="periods", action="append", type=parse_period, required=True,
                        help="YYYY-MM-DD:YYYY-MM-DD; repeat for several periods")
    parser.add_argument("--size", type=float, default=DEFAULT_SIZE, help=f"Dollars per trade (default: {DEFAULT_SIZE:,.0f})")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS,
                        help=f"Round-trip cost per trade in basis points (default: {DEFAULT_COST_BPS:g})")
    parser.add_argument("--avg-bar-stop", type=float, default=DEFAULT_AVG_BAR_STOP,
                        help="Wider drive long stop: first-bar low minus this many average 5-min bars"
                             f" (default: {DEFAULT_AVG_BAR_STOP:g})")
    parser.add_argument("--since", type=date.fromisoformat,
                        help="Ignore bars before this date (new listing or reused symbol), YYYY-MM-DD")
    parser.add_argument("--csv-out", help="Also write every row to this CSV")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    ticker = args.ticker.upper()
    first = min(start for start, _ in args.periods)
    last = max(end for _, end in args.periods)
    bars = fetch_bars(ticker, first - timedelta(days=WARMUP_DAYS), last + timedelta(days=5))
    if args.since:
        bars = bars[bars.index.date >= args.since]
    table = compare(bars, args.periods, ticker_earnings_windows(ticker, bars), args.size, args.cost_bps, args.avg_bar_stop)
    pd.set_option("display.width", 250)
    for label, rows in table.groupby("period", sort=False):
        print(f"\n=== {ticker} {label} (${args.size:,.0f} per trade, {args.cost_bps:g} bps)")
        print(rows.drop(columns="period").to_string(index=False, float_format=lambda v: f"{v:+,.1f}"))
    if args.csv_out:
        table.insert(0, "ticker", ticker)
        table.to_csv(args.csv_out, index=False)
        print(f"\nrows written to {args.csv_out}")


if __name__ == "__main__":
    main()
