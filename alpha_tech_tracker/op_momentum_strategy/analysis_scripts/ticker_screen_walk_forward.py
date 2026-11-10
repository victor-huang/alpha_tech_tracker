"""Ticker screen walk-forward: replay ticker_screen month by month over a year, with no hindsight (Finding 42).

At each month's first session the screen runs on the daily bars before it (top --top-volume by 126-session median
dollar volume, price >= --min-price, 60-session average range >= --min-range %), the passers are ranked by their last
--lookback sessions of core setups (drive long + overnight long on the nights the overnight trend filter allows, 5
bps) and the top --picks are held for the month, --capital split --picks ways a trade, not compounded.

Per-ticker trades are cached under --cache-dir (one CSV per ticker and window), so reruns and other settings are
quick. The universe is today's listed stocks plus, with --include-delisted, Alpaca's inactive ones (names delisted
since; some may lack data). The price floor uses the raw (unadjusted) close known at the time, not today's
split-adjusted one. The ranking leaves out the overnight hold entered on the last session before the month (it exits
at the month's first open, after the pick).

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen_walk_forward --years 2022 2025
"""

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpaca.data.enums import Adjustment

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen import (
    CORE_LEGS,
    daily_stats,
    delisted_stocks,
    fetch_assets,
    fetch_daily,
    legs_job,
    screen,
    stock_universe,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars
from alpha_tech_tracker.op_momentum_strategy.trend_filters import MARKET_TICKER, market_trend, session_flags

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "backtest_result" / "ticker_screen_walk_forward"
MIN_TRADES = 10
LEGS_MARGIN_SESSIONS = 5


def by_date(daily):
    """{ticker: daily bars} with plain date indexes."""
    return {t: f.set_axis([pd.Timestamp(i).date() for i in f.index], axis=0) for t, f in daily.items()}


def month_starts(sessions, year):
    """The first session of each month of the year."""
    starts = {}
    for day in sessions:
        if day.year == year:
            starts.setdefault(day.month, day)
    return [starts[m] for m in sorted(starts)]


def passers_by_month(daily, starts, top_volume, min_range, min_price, raw=None):
    """{month start: [screen passers on the bars before it]}; with `raw` (unadjusted daily bars) the price floor uses the
    raw close then, not the split-adjusted one."""
    out = {}
    for start in starts:
        stats = daily_stats({t: f[f.index < start] for t, f in daily.items()})
        if raw is not None:
            stats["close"] = [_last_close(raw.get(t), start) for t in stats.index]
        out[start] = screen(stats, top_volume, min_range, min_price).index.tolist()
    return out


def _last_close(frame, before):
    if frame is None:
        return float("nan")
    closes = frame[frame.index < before]["Close"]
    return float(closes.iloc[-1]) if len(closes) else float("nan")


def ranking_trades(core, past):
    """The trades the ranking may see: the past sessions' trades, less the overnight holds entered on the last one."""
    seen = core.day.isin(past)
    if past:
        seen &= ~((core.leg == "overnight long") & (core.day == past[-1]))
    return core[seen]


def cache_path(cache_dir, ticker, start, end):
    return cache_dir / f"{ticker}_{start}_{end}.csv"


def cached_legs(tickers, start, end, cache_dir, workers):
    """Core-leg trades per ticker over start..end, from the cache or computed (and cached)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    missing = [t for t in tickers if not cache_path(cache_dir, t, start, end).exists()]
    if missing:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for ticker, legs in zip(missing, pool.map(legs_job, [(t, start, end) for t in missing])):
                legs[legs.leg.isin(CORE_LEGS)].to_csv(cache_path(cache_dir, ticker, start, end), index=False)
    paths = [cache_path(cache_dir, t, start, end) for t in tickers]
    frames = [pd.read_csv(p) for p in paths if os.path.getsize(p) > 1]
    legs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ticker", "day", "leg", "pct"])
    legs["day"] = [date.fromisoformat(str(d)[:10]) for d in legs.day]
    return legs


def core_trades(legs, night_ok):
    """Drive long trades, and overnight long trades on the nights the trend filter allows."""
    night = (legs.leg == "overnight long") & legs.day.map(night_ok).fillna(False).astype(bool)
    return legs[(legs.leg == "drive long") | night][["ticker", "day", "leg", "pct"]]


def walk(core, passers, sessions, starts, picks, lookback, capital):
    """(month trades with a dollars column, {month start: picks}) for the monthly re-pick."""
    parts, chosen = [], {}
    ends = starts[1:] + [sessions[-1] + timedelta(days=1)]
    for start, stop in zip(starts, ends):
        past = [d for d in sessions if d < start][-lookback:]
        seen = ranking_trades(core, past)
        trailing = seen[seen.ticker.isin(passers[start])].groupby("ticker").pct.agg(["sum", "size"])
        trailing = trailing[trailing["size"] >= MIN_TRADES].sort_values("sum", ascending=False)
        chosen[start] = trailing.index[:picks].tolist()
        month = core[core.ticker.isin(chosen[start]) & (core.day >= start) & (core.day < stop)]
        parts.append(month.assign(month=start.strftime("%Y-%m"), dollars=month.pct / 100 * capital / picks))
    return pd.concat(parts, ignore_index=True), chosen


def summary(trades):
    """Trades, won %, per trade %, P&L $, max drawdown $ of the daily P&L, months positive."""
    if trades.empty:
        return {"trades": 0, "won %": 0.0, "per trade %": 0.0, "P&L $": 0, "max DD $": 0, "months +": 0}
    equity = trades.groupby("day").dollars.sum().sort_index().cumsum()
    months = trades.groupby("month").dollars.sum()
    return {"trades": len(trades), "won %": round(100 * (trades.pct > 0).mean(), 1),
            "per trade %": round(trades.pct.mean(), 3), "P&L $": round(trades.dollars.sum()),
            "max DD $": round((equity - equity.cummax()).min()), "months +": int((months > 0).sum())}


def run_year(year, universe, args):
    end = clamp_end_for_sip(min(date(year, 12, 31), args.end or date.today()), DataFeed.SIP)
    qqq = fetch_daily_bars([MARKET_TICKER], date(year - 2, 1, 1), end)[MARKET_TICKER]
    sessions = sorted(qqq.index)
    starts = month_starts(sessions, year)
    daily = by_date(fetch_daily(universe, date(year - 1, 5, 1), end))
    raw = by_date(fetch_daily(universe, date(year - 1, 5, 1), end, Adjustment.RAW))
    passers = passers_by_month(daily, starts, args.top_volume, args.min_range, args.min_price, raw)
    candidates = sorted({t for names in passers.values() for t in names})
    legs_start = [d for d in sessions if d < starts[0]][-(args.lookback + LEGS_MARGIN_SESSIONS)]
    print(f"{year}: {len(universe)} stocks, {len(candidates)} pass the screen in some month; trades {legs_start}..{end}")
    legs = cached_legs(candidates, legs_start, end, Path(args.cache_dir), args.workers)
    night_ok = session_flags(market_trend(pd.DataFrame({"close": qqq["Close"].astype(float)}, index=qqq.index)),
                             sorted(set(legs.day)), "overnight_ok")
    year_sessions = [d for d in sessions if d >= legs_start]
    return walk(core_trades(legs, night_ok), passers, year_sessions, starts, args.picks, args.lookback, args.capital)


def screen_universe(include_delisted):
    """Today's listed stocks, plus the delisted ones when include_delisted."""
    listed = stock_universe(fetch_assets())
    return listed + delisted_stocks(fetch_assets("inactive"), listed) if include_delisted else listed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--end", type=date.fromisoformat, help="Last session (default: today); keeps the trade cache's "
                                                                "window stable across days")
    parser.add_argument("--include-delisted", action="store_true",
                        help="Add Alpaca's inactive (delisted) NYSE / Nasdaq stocks to the universe")
    parser.add_argument("--top-volume", type=int, default=150)
    parser.add_argument("--min-range", type=float, default=4.0)
    parser.add_argument("--min-price", type=float, default=10.0)
    parser.add_argument("--lookback", type=int, default=63)
    parser.add_argument("--picks", type=int, default=5)
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    universe = screen_universe(args.include_delisted)
    pd.set_option("display.width", 250)
    totals = {}
    for year in args.years:
        trades, chosen = run_year(year, universe, args)
        by_ticker = trades.groupby(["month", "ticker"]).pct.sum()
        print(f"\n=== {year}: top {args.picks} of the top {args.top_volume} by $ volume with a {args.min_range:g}%+ range, "
              f"{args.lookback}-session lookback, ${args.capital:,.0f}")
        for start, names in chosen.items():
            month = start.strftime("%Y-%m")
            dollars = trades[trades.month == month].dollars.sum()
            print(f"{month}: ${dollars:+,.0f} | " + ", ".join(f"{t} {by_ticker.get((month, t), 0):+.1f}%" for t in names))
        totals[year] = summary(trades)
    print("\n=== summary")
    print(pd.DataFrame(totals).T.to_string())


if __name__ == "__main__":
    main()
