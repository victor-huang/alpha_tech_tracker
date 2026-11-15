"""Phase 3 of research/docs/historical_data_2005_2019_plan.md: download the prices WIKI does not have.

Usage (from the repo root, after securities.py, with ALPACA_API_KEY / ALPACA_SECRET_KEY exported):

    python -m alpha_tech_tracker.research.historical.fill_prices yfinance
    python -m alpha_tech_tracker.research.historical.fill_prices alpaca
    python -m alpha_tech_tracker.research.historical.fill_prices yfinance alpaca --limit-batches 1   # smoke test

- yfinance, 2003-01 -> 2016-01: names listed in 2003-2015 that WIKI lacks and that still trade today, WIKI tickers
  that went stale while still trading, and the benchmarks (WIKI has no ETFs). yfinance only has names still listed.
- alpaca, 2016-01 -> 2020-06: every plain-letter operating stock Alpaca has on a listed exchange (active or inactive) plus every symbol
  listed in 2016-2019 per Tiingo / Alpha Vantage, since Alpaca's inactive list misses some dead tickers (TWX, MON).
  Each batch is fetched twice, split + dividend adjusted and raw, for returns and market cap, one calendar month
  per request: a request that spans a change in Alpaca's identifier for a stock silently returns only the part
  after the change (TRP for 2016-2020 starts 2019-05-09; TRP for 2017 alone has all 251 days).

Raw downloads go to market_data/historical/prices/<source>/batch_<NNNN>.pkl as long rows; a batch file that exists
is skipped, so an interrupted run resumes. The batch lists are saved alongside so a rerun uses the same batches.
"""
import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import pandas as pd
import yfinance as yf
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from alpha_tech_tracker.research.historical import securities as sec

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "market_data", "historical")
BENCHMARKS = ["SPY", "QQQ"]
YF_START, YF_END = "2003-01-01", "2016-02-01"
ALPACA_START, ALPACA_END = datetime(2016, 1, 1), datetime(2020, 6, 30)
LISTED_SINCE = pd.Timestamp("2003-01-01")
ALPACA_LISTED_FROM = pd.Timestamp("2016-01-01")
ALPACA_LISTED_TO = pd.Timestamp("2019-12-31")
STALE_BEFORE = pd.Timestamp("2015-12-01")
YF_BATCH, ALPACA_BATCH = 50, 200
YF_PAUSE_SECONDS = 2
RETRIES = 3
BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


def listed_between(listings: pd.DataFrame, first: pd.Timestamp, last: pd.Timestamp) -> set:
    """Symbols listed on any Jan 2 / Jul 2 snapshot in [first, last]."""
    symbols = set()
    for year in range(first.year, last.year + 1):
        for month in (1, 7):
            day = pd.Timestamp(year, month, 2)
            if first <= day <= last:
                symbols |= set(sec.listed_on(listings, day))
    return symbols


def yfinance_symbols(listings: pd.DataFrame, runs: pd.DataFrame) -> List[str]:
    alpaca = listings[listings["source"] == "alpaca"]
    active = set(alpaca.loc[alpaca["status"] == "active", "symbol"])
    missing = listed_between(listings, LISTED_SINCE, sec.WIKI_LAST_DAY) - set(runs["symbol"])
    latest = runs[runs["security"] == runs["symbol"]]
    stale = set(latest.loc[latest["last_day"] < STALE_BEFORE, "symbol"])
    return sorted(s for s in ((missing | stale) & active) | set(BENCHMARKS) if re.match(sec.SYMBOL_RE, s))


def alpaca_symbols(listings: pd.DataFrame, runs: pd.DataFrame) -> List[str]:
    alpaca = listings[listings["source"] == "alpaca"]
    on_exchange = alpaca["exchange"].isin(sec.LISTED_EXCHANGES) & alpaca["name"].map(sec.is_operating)
    known = set(alpaca.loc[on_exchange, "symbol"])
    listed = listed_between(listings, ALPACA_LISTED_FROM, ALPACA_LISTED_TO)
    wiki_alive = set(runs.loc[runs["last_day"] >= pd.Timestamp("2015-01-01"), "symbol"])
    return sorted(s for s in known | listed | wiki_alive | set(BENCHMARKS) if re.match(sec.SYMBOL_RE, s))


def month_windows(start: datetime, end: datetime) -> List[tuple]:
    """[(month start, last moment of that month or end)] covering start..end."""
    windows, cursor = [], start
    while cursor <= end:
        nxt = datetime(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        windows.append((cursor, min(nxt - timedelta(seconds=1), end)))
        cursor = nxt
    return windows


def batches(symbols: List[str], size: int) -> List[List[str]]:
    return [symbols[i:i + size] for i in range(0, len(symbols), size)]


def yfinance_long(frame: pd.DataFrame, symbols: List[str]) -> pd.DataFrame:
    """yf.download(group_by='ticker', actions=True) wide frame -> long rows: symbol, day, open, high, low, close
    (split-adjusted), adj_close, volume, dividends, splits."""
    rows = []
    for symbol in symbols:
        if symbol not in frame.columns.get_level_values(0):
            continue
        part = frame[symbol].dropna(subset=["Close"])
        if part.empty:
            continue
        rows.append(pd.DataFrame({
            "symbol": symbol, "day": pd.to_datetime(part.index).tz_localize(None).normalize(),
            "open": part["Open"].values, "high": part["High"].values, "low": part["Low"].values,
            "close": part["Close"].values, "adj_close": part["Adj Close"].values, "volume": part["Volume"].values,
            "dividends": part.get("Dividends", pd.Series(0.0, index=part.index)).values,
            "splits": part.get("Stock Splits", pd.Series(0.0, index=part.index)).values,
        }))
    if not rows:
        return pd.DataFrame(columns=["symbol", "day", "open", "high", "low", "close", "adj_close", "volume",
                                     "dividends", "splits"])
    return pd.concat(rows, ignore_index=True)


def fetch_yfinance_batch(symbols: List[str]) -> pd.DataFrame:
    frame = yf.download(symbols, start=YF_START, end=YF_END, group_by="ticker", auto_adjust=False, actions=True,
                        threads=True, progress=False)
    if not isinstance(frame.columns, pd.MultiIndex):
        frame = pd.concat({symbols[0]: frame}, axis=1)
    return yfinance_long(frame, symbols)


class AlpacaBars:
    def __init__(self):
        self.client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])

    def _bars(self, symbols: List[str], adjustment: Adjustment) -> pd.DataFrame:
        frames = []
        for start, end in month_windows(ALPACA_START, ALPACA_END):
            req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start, end=end,
                                   adjustment=adjustment, feed=DataFeed.SIP)
            df = self.client.get_stock_bars(req).df
            if not df.empty:
                frames.append(df.reset_index()[["symbol", "timestamp"] + BAR_COLUMNS])
        if not frames:
            return pd.DataFrame(columns=["symbol", "timestamp"] + BAR_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def fetch_batch(self, symbols: List[str]) -> pd.DataFrame:
        """Adjusted OHLCV with the raw close alongside: symbol, day, open, high, low, close, volume, raw_close."""
        adjusted = self._bars(symbols, Adjustment.ALL)
        raw = self._bars(symbols, Adjustment.RAW)[["symbol", "timestamp", "close"]].rename(columns={"close": "raw_close"})
        out = adjusted.merge(raw, on=["symbol", "timestamp"], how="left")
        out["day"] = pd.to_datetime(pd.to_datetime(out["timestamp"], utc=True)
                                    .dt.tz_convert("America/New_York").dt.date)
        return out.drop(columns="timestamp")[["symbol", "day"] + BAR_COLUMNS + ["raw_close"]]


def run_batches(symbols: List[str], size: int, out_dir: str, fetch: Callable[[List[str]], pd.DataFrame],
                limit: Optional[int] = None, pause: float = 0.0,
                sleep: Callable[[float], None] = time.sleep) -> Dict[str, int]:
    """Fetch each batch not yet on disk; the batch list is saved first so a rerun keeps the same batches."""
    os.makedirs(out_dir, exist_ok=True)
    plan_path = os.path.join(out_dir, "batches.json")
    if os.path.exists(plan_path):
        with open(plan_path) as fh:
            planned = json.load(fh)
    else:
        planned = batches(symbols, size)
        with open(plan_path, "w") as fh:
            json.dump(planned, fh)
    done = fetched = 0
    for i, batch in enumerate(planned):
        path = os.path.join(out_dir, f"batch_{i:04d}.pkl")
        if os.path.exists(path):
            done += 1
            continue
        if limit is not None and fetched >= limit:
            break
        rows = _fetch_with_retry(fetch, batch, sleep)
        rows.to_pickle(path)
        fetched += 1
        print(f"{os.path.basename(out_dir)} batch {i + 1}/{len(planned)}: {rows['symbol'].nunique()} of "
              f"{len(batch)} symbols, {len(rows)} rows", flush=True)
        sleep(pause)
    return {"batches": len(planned), "already_done": done, "fetched": fetched}


def _fetch_with_retry(fetch: Callable[[List[str]], pd.DataFrame], batch: List[str],
                      sleep: Callable[[float], None]) -> pd.DataFrame:
    for attempt in range(RETRIES):
        try:
            return fetch(batch)
        except Exception as exc:  # yfinance and alpaca-py raise many error types for throttling and timeouts
            if attempt + 1 == RETRIES:
                raise
            print(f"batch failed (attempt {attempt + 1}): {exc}", flush=True)
            sleep(30 * (attempt + 1))


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sources", nargs="+", choices=["yfinance", "alpaca"])
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--limit-batches", type=int, help="fetch at most this many new batches per source")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    listings = pd.read_pickle(os.path.join(args.data_dir, "listings.pkl"))
    runs = pd.read_pickle(os.path.join(args.data_dir, "wiki_runs.pkl"))
    prices = os.path.join(args.data_dir, "prices")
    if "yfinance" in args.sources:
        symbols = yfinance_symbols(listings, runs)
        print(f"yfinance: {len(symbols)} symbols", flush=True)
        print(run_batches(symbols, YF_BATCH, os.path.join(prices, "yfinance"), fetch_yfinance_batch,
                          args.limit_batches, YF_PAUSE_SECONDS))
    if "alpaca" in args.sources:
        symbols = alpaca_symbols(listings, runs)
        print(f"alpaca: {len(symbols)} symbols", flush=True)
        print(run_batches(symbols, ALPACA_BATCH, os.path.join(prices, "alpaca"), AlpacaBars().fetch_batch,
                          args.limit_batches))


if __name__ == "__main__":
    run(parse_args())
