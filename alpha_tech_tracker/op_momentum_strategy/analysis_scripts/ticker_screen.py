"""Ticker screen: the month's tickers for the wave setup monitor's core setups (ticker-tuning doc, Finding 42).

The procedure that held up over 2020, 2022, 2023, 2025 and 2026 (monthly re-pick, no hindsight):

  1. universe   active NYSE / Nasdaq stocks (no ETFs or funds), price >= --min-price
  2. liquidity  the --top-volume stocks by median daily dollar volume over the last 126 sessions (default 150)
  3. range      60-session average daily range (high - low) / close >= --min-range % (default 4)
  4. rank       the passers by their last --lookback sessions (default 63) of the core setups: drive long (green first
                bar, stop its low, held to the close) plus the overnight long (15:55 close to the next open, earnings
                nights skipped) on the nights the monitor's overnight trend filter allows (QQQ above its 200-day MA and
                up over 10 sessions), 5 bps a trade
  5. pick       the top --picks (default 5)

The monitor's drive short + re-entry is reported too (every day, and on the days its qqq-ma50-down10 gate was on);
`--rank-shorts gated|all` adds it to the ranking score (default none: the long-only ranking the findings are for).

Run it on the first trading day of each month (it uses data through --as-of, default the last completed session).
`--write-config PATH` writes a wave setup monitor config with `drive long` and `overnight always` for the picks; run the
monitor with `--trend-filters overnight`.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen
  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen --as-of 2026-10-30 \\
    --write-config logs/wave_setup_monitor_config.json
"""

import argparse
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import gated_sessions, ticker_legs
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars
from alpha_tech_tracker.op_momentum_strategy.trend_filters import MARKET_TICKER, market_trend, session_flags

VOLUME_SESSIONS = 126
RANGE_SESSIONS = 60
DAILY_CALENDAR_DAYS = 330
QQQ_CALENDAR_DAYS = 420
FETCH_BATCH = 400
EXCHANGES = ("NYSE", "NASDAQ")
FUND_NAME = re.compile(r"\bETF\b|ProShares|Direxion|iShares|SPDR|Invesco QQQ|Trust Units|\bFund\b|2X|3X|Leveraged|"
                       r"Bitcoin|Ether", re.IGNORECASE)
CORE_LEGS = ("drive long", "overnight long")
SHORT_LEG = "drive short + re-entry"
RANK_LEGS = CORE_LEGS + (SHORT_LEG,)
SHORT_GATE = "qqq-ma50-down10"
RANK_SHORTS = ("none", "gated", "all")


def is_fund(name):
    return bool(FUND_NAME.search(name or ""))


def stock_universe(assets):
    """Tradable NYSE / Nasdaq stocks (plain alphabetic symbols, no funds) from Alpaca's asset list."""
    return sorted(a["symbol"] for a in assets if a.get("tradable") and a.get("exchange") in EXCHANGES
                  and a["symbol"].isalpha() and not is_fund(a.get("name")))


def delisted_stocks(assets, listed):
    """Former NYSE / Nasdaq stocks (inactive assets, no funds) not in `listed`: for past-year tests, so the universe
    is not only today's survivors."""
    listed = set(listed)
    return sorted({a["symbol"] for a in assets if a.get("exchange") in EXCHANGES and a["symbol"].isalpha()
                   and not is_fund(a.get("name")) and a["symbol"] not in listed})


def fetch_assets(status="active"):
    key = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_KEY_ID")
    client = TradingClient(key, os.environ.get("ALPACA_SECRET_KEY"), paper=True)
    # raw response: alpaca-py's Asset model rejects exchanges it does not know yet (e.g. TXSE)
    return client.get("/assets", {"status": status, "asset_class": "us_equity"})


def daily_stats(daily):
    """{ticker: daily bars} -> DataFrame(close, dollar_vol, range_pct) over the last sessions of each."""
    rows = {}
    for ticker, frame in daily.items():
        if frame is None or len(frame) < RANGE_SESSIONS:
            continue
        close, high, low = frame["Close"].astype(float), frame["High"].astype(float), frame["Low"].astype(float)
        dollar = (close * frame["Volume"].astype(float)).tail(VOLUME_SESSIONS)
        rows[ticker] = {"close": close.iloc[-1], "dollar_vol": dollar.median(),
                        "range_pct": 100 * ((high - low) / close).tail(RANGE_SESSIONS).mean()}
    return pd.DataFrame.from_dict(rows, orient="index")


def screen(stats, top_volume, min_range, min_price):
    """The screen passers: the top_volume stocks by dollar volume (at min_price or more) with range >= min_range."""
    liquid = stats[stats.close >= min_price].sort_values("dollar_vol", ascending=False).head(top_volume)
    return liquid[liquid.range_pct >= min_range]


def core_results(legs, night_ok, short_days=(), rank_shorts="none"):
    """Per ticker over the legs: drive long and filtered overnight long trades (the core), the drive short + re-entry
    every day and on the short_days its gate was on, and the ranking score: the core sum, plus the gated (rank_shorts
    `gated`) or every-day (`all`) drive short sum."""
    drive = legs[legs.leg == "drive long"]
    night = legs[(legs.leg == "overnight long") & legs.day.map(night_ok).fillna(False).astype(bool)]
    short = legs[legs.leg == SHORT_LEG]
    gated = short[short.day.isin(set(short_days))]
    out = pd.DataFrame({
        "drive_trades": drive.groupby("ticker").size(), "drive_sum": drive.groupby("ticker").pct.sum(),
        "night_trades": night.groupby("ticker").size(), "night_sum": night.groupby("ticker").pct.sum(),
        "short_trades": short.groupby("ticker").size(), "short_sum": short.groupby("ticker").pct.sum(),
        "gated_short_trades": gated.groupby("ticker").size(), "gated_short_sum": gated.groupby("ticker").pct.sum(),
    }).fillna(0)
    out["core_sum"] = out.drive_sum + out.night_sum
    trades = out.drive_trades + out.night_trades
    out["core_per_trade"] = out.core_sum / trades.where(trades > 0)
    short_column = {"none": None, "gated": "gated_short", "all": "short"}[rank_shorts]
    out["score"] = out.core_sum + (out[f"{short_column}_sum"] if short_column else 0)
    out["score_trades"] = trades + (out[f"{short_column}_trades"] if short_column else 0)
    return out


def rank(passers, results, min_trades=10):
    """Passers joined with their results, best score first; tickers with fewer than min_trades scored trades last."""
    table = passers.join(results, how="left")
    enough = table.score_trades.fillna(0) >= min_trades
    return pd.concat([table[enough].sort_values("score", ascending=False), table[~enough]])


def monitor_config(picks, as_of, lookback_start):
    """A wave setup monitor config with drive long and overnight always for each pick."""
    return {
        "generated": date.today().isoformat(), "source": "ticker_screen", "window": f"{lookback_start}..{as_of}",
        "top_n": 2, "types": ["long", "overnight"], "min_trades": 1,
        "tickers": {t: [{"setup": "drive long", "report_total_pct": round(float(r.drive_sum), 2)},
                        {"setup": "overnight always", "report_total_pct": round(float(r.night_sum), 2)}]
                    for t, r in picks.iterrows()},
    }


def fetch_daily(tickers, start, end, adjustment=Adjustment.SPLIT):
    """{ticker: daily SIP bars (Close / High / Low / Volume), split-adjusted by default}, FETCH_BATCH symbols a request;
    not cached (fetch_daily_bars caches one file per ticker, too slow for the whole market)."""
    key = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_KEY_ID")
    client = StockHistoricalDataClient(key, os.environ.get("ALPACA_SECRET_KEY"))
    daily = {}
    for i in range(0, len(tickers), FETCH_BATCH):
        request = StockBarsRequest(symbol_or_symbols=tickers[i:i + FETCH_BATCH], timeframe=TimeFrame.Day,
                                   start=datetime.combine(start, datetime.min.time()),
                                   end=datetime.combine(end + timedelta(days=1), datetime.min.time()),
                                   feed=DataFeed.SIP, adjustment=adjustment)
        frame = client.get_stock_bars(request).df
        if frame.empty:
            continue
        for ticker, bars in frame.groupby(level=0):
            bars = bars.droplevel(0)
            bars.columns = [c.capitalize() for c in bars.columns]
            daily[ticker] = bars
    return daily


def legs_job(job):
    ticker, start, end = job
    try:
        return ticker_legs((ticker, start, end, 5.0, "always"))[0]
    except Exception as error:
        print(f"{ticker}: no trailing results ({error})")
        return pd.DataFrame(columns=["ticker", "day", "leg", "pct"])


def trailing_results(tickers, start, end, workers, rank_shorts="none"):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        legs = pd.concat(list(pool.map(legs_job, [(t, start, end) for t in tickers])), ignore_index=True)
    legs = legs[legs.leg.isin(RANK_LEGS)]
    qqq = fetch_daily_bars([MARKET_TICKER], end - timedelta(days=QQQ_CALENDAR_DAYS), end)[MARKET_TICKER]
    qqq = pd.DataFrame({"close": qqq["Close"].astype(float)}, index=qqq.index)
    night_ok = session_flags(market_trend(qqq), sorted(set(legs.day)), "overnight_ok")
    return core_results(legs, night_ok, gated_sessions(start, end, SHORT_GATE), rank_shorts)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", type=date.fromisoformat, help="Last session of data (default: the last completed one)")
    parser.add_argument("--top-volume", type=int, default=150, help="Stocks kept by dollar volume (default 150)")
    parser.add_argument("--min-range", type=float, default=4.0, help="Minimum 60-session average daily range %%")
    parser.add_argument("--min-price", type=float, default=10.0)
    parser.add_argument("--lookback", type=int, default=63, help="Sessions of core-setup results to rank on")
    parser.add_argument("--picks", type=int, default=5)
    parser.add_argument("--rank-shorts", choices=RANK_SHORTS, default="none",
                        help="Add the drive short + re-entry to the ranking score: on its gated days, or every day")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--write-config", help="Write a wave setup monitor config for the picks to this path")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    as_of = clamp_end_for_sip(args.as_of or date.today(), DataFeed.SIP)
    universe = stock_universe(fetch_assets())
    stats = daily_stats(fetch_daily(universe, as_of - timedelta(days=DAILY_CALENDAR_DAYS), as_of))
    passers = screen(stats, args.top_volume, args.min_range, args.min_price)
    print(f"{len(universe)} stocks, {len(stats)} with history; top {args.top_volume} by dollar volume with a "
          f"{args.min_range:g}%+ daily range: {len(passers)}")
    sessions = sorted(fetch_daily_bars([MARKET_TICKER], as_of - timedelta(days=120), as_of)[MARKET_TICKER].index)
    lookback_start = sessions[-args.lookback]
    results = trailing_results(passers.index.tolist(), lookback_start, as_of, args.workers, args.rank_shorts)
    table = rank(passers, results)
    pd.set_option("display.width", 250)
    columns = ["score", "core_sum", "core_per_trade", "drive_sum", "drive_trades", "night_sum", "night_trades",
               "short_sum", "short_trades", "gated_short_sum", "gated_short_trades", "range_pct", "dollar_vol", "close"]
    shown = table[columns].assign(dollar_vol=table.dollar_vol / 1e6).rename(columns={"dollar_vol": "dollar_vol_m"})
    print(f"\ncore setups {lookback_start} .. {as_of} (sum of trade %), best score first (shorts in the score: "
          f"{args.rank_shorts}; short_* = drive short + re-entry every day, gated_short_* = on its {SHORT_GATE} days):")
    print(shown.round(2).to_string())
    picks = table.head(args.picks)
    print(f"\npicks: {', '.join(picks.index)}")
    if args.write_config:
        with open(args.write_config, "w") as handle:
            json.dump(monitor_config(picks, as_of, lookback_start), handle, indent=1)
        print(f"config written to {args.write_config}; run the monitor with --trend-filters overnight")


if __name__ == "__main__":
    main()
