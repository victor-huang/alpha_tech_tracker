"""Shared loaders for the QQQ-gap research (historical 2005-2019, Alpaca cache 2017-2026)."""
import glob
import os
import pickle
from datetime import date
from functools import lru_cache

import pandas as pd

HIST = "/Users/victorhuang/work/alpha_tech_tracker_hist"
MAIN = "/Users/victorhuang/work/alpha_tech_tracker"
HIST_PANELS = f"{HIST}/alpha_tech_tracker/research/top_performers_output/uptrend_formation_historical"
ALPACA_PANELS = f"{MAIN}/alpha_tech_tracker/research/top_performers_output/uptrend_formation"
BOOKS = f"{HIST_PANELS}/top_n_by_year"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
HIST_YEARS = list(range(2005, 2020))
ALPACA_YEARS = list(range(2020, 2027))
os.makedirs(OUT, exist_ok=True)


def source_for(year: int) -> str:
    return "historical" if year <= 2019 else "alpaca"


def panel(year: int) -> pd.DataFrame:
    root = HIST_PANELS if source_for(year) == "historical" else ALPACA_PANELS
    return pd.read_pickle(f"{root}/{year}/panel.pkl")


@lru_cache(maxsize=None)
def _hist_year(year: int) -> pd.DataFrame:
    return pd.read_pickle(f"{HIST}/market_data/historical/daily/{year}.pkl")


def close(year: int) -> pd.DataFrame:
    """Wide adjusted closes from 13 months before `year` to the end of January after it."""
    if source_for(year) == "historical":
        rows = pd.concat([_hist_year(y) for y in (year - 1, year, year + 1) if 2003 <= y <= 2020])
        rows = rows[(rows["day"] >= pd.Timestamp(year - 1, 1, 1)) & (rows["day"] <= pd.Timestamp(year + 1, 1, 31))]
        return rows.pivot(index="day", columns="symbol", values="close").sort_index()
    frames = []
    for path in sorted(glob.glob(f"{MAIN}/market_data/top_performers/daily_bars/*.pkl")):
        month = os.path.basename(path)[:7]
        if f"{year - 1}-01" <= month <= f"{year + 1}-01":
            with open(path, "rb") as f:
                frames.append(pickle.load(f)["close"])
    c = pd.concat(frames)
    c = c[~c.index.duplicated(keep="last")].sort_index()
    return c[(c.index >= pd.Timestamp(year - 1, 1, 1)) & (c.index <= pd.Timestamp(year + 1, 1, 31))]


def year_return(c: pd.DataFrame, year: int) -> pd.Series:
    """Buy at the first close of the year (the books' first checkpoint), sell at the last close of the year (or the
    last trade if it stopped)."""
    base = c[c.index >= pd.Timestamp(year, 1, 1)].iloc[0]
    end = c[c.index <= pd.Timestamp(year, 12, 31)].ffill().iloc[-1]
    return end / base - 1


def books(year: int) -> dict:
    out = {}
    for n in (3, 5, 10):
        path = f"{BOOKS}/top{n}_{year}.pkl"
        if os.path.exists(path):
            with open(path, "rb") as f:
                out[n] = pickle.load(f)
    path = f"{BOOKS}/large_top3_{year}.pkl"
    if os.path.exists(path):
        with open(path, "rb") as f:
            out["large_top3"] = pickle.load(f)
    return out


@lru_cache(maxsize=None)
def sectors() -> pd.Series:
    t = pd.read_csv(f"{HIST}/market_data/historical_cache/industries.csv", keep_default_na=False, na_values=[""])
    return t.set_index("symbol")["sector"]


def sector_of(symbol: str) -> str:
    return sectors().get(symbol.split("~")[0], "Unknown") or "Unknown"


@lru_cache(maxsize=None)
def _listings() -> pd.DataFrame:
    return pd.read_pickle(f"{HIST}/market_data/historical/listings.pkl")


def exchanges_on(day: pd.Timestamp) -> pd.Series:
    """symbol -> exchange of the listing live on `day` (Tiingo first, then Alpha Vantage, then any)."""
    l = _listings()
    live = l[(l["start"].isna() | (l["start"] <= day)) & (l["end"].isna() | (l["end"] >= day))]
    order = {"tiingo": 0, "alphavantage": 1}
    live = live.assign(rank=live["source"].map(order).fillna(2)).sort_values("rank")
    return live.drop_duplicates("symbol").set_index("symbol")["exchange"]


def market_caps(symbols, year: int) -> pd.Series:
    """Market cap on the last trading day before `year` (historical years only), as the tiers compute it."""
    from alpha_tech_tracker.research.historical.data import HistoricalData, HistoricalShares
    from alpha_tech_tracker.research.top_performers import market_cap_at

    c = close(year)
    base_day = c.index[c.index < pd.Timestamp(year, 1, 1)][-1]
    raws = HistoricalData().raw_closes(list(symbols), base_day.date())
    shares = HistoricalShares()
    caps = {s: market_cap_at(shares.get(s, date(2020, 6, 30)), base_day.date(), raws.get(s)) for s in symbols}
    return pd.Series(caps, dtype=float).dropna()
