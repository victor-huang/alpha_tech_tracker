"""Phase 6 of research/docs/historical_data_2005_2019_plan.md: the historical dataset behind the same interface the
research scripts use for Alpaca (top_performers.AlpacaData) and yfinance share counts (top_performers.SharesCache).

    data = HistoricalData()
    data.listed_stocks()                       # every security in the dataset, dead ones included
    data.daily_bars(symbols, start, end)       # long rows: symbol, timestamp (UTC), close, volume (adjusted)
    data.raw_closes(symbols, day)              # {symbol: unadjusted close on or before day}
    HistoricalShares().get(symbol, today)      # SEC share counts; never fetches

The point-in-time universe follows from the bars: a security only has bars while it traded, so
uptrend_formation.start_of_year_universe only sees what was trading before the year started.
"""
import json
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

from alpha_tech_tracker.research.historical import normalize as nz
from alpha_tech_tracker.research.historical import securities as sec
from alpha_tech_tracker.research.historical.shares import alias_map

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "market_data", "historical")
HISTORICAL_CACHE_DIR = os.path.join(REPO_ROOT, "market_data", "historical_cache")
YFINANCE_SHARES_PATH = os.path.join(REPO_ROOT, "market_data", "top_performers", "shares.json")
STILL_TRADING_FROM = pd.Timestamp("2020-06-01")
RAW_CLOSE_LOOKBACK_DAYS = 6


class HistoricalData:
    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_dir = data_dir
        self._years: Dict[int, pd.DataFrame] = {}

    def _year(self, year: int) -> pd.DataFrame:
        if year not in self._years:
            path = os.path.join(self.data_dir, "daily", f"{year}.pkl")
            if os.path.exists(path):
                self._years[year] = pd.read_pickle(path)
            else:
                self._years[year] = pd.DataFrame(columns=nz.COLUMNS).astype({"day": "datetime64[ns]"})
        return self._years[year]

    def _rows(self, symbols: List[str], start: date, end: date) -> pd.DataFrame:
        frames = [self._year(y) for y in range(start.year, end.year + 1)]
        rows = pd.concat(frames, ignore_index=True)
        keep = rows["symbol"].isin(set(symbols)) & (rows["day"] >= pd.Timestamp(start)) & \
            (rows["day"] <= pd.Timestamp(end))
        return rows[keep]

    def listed_stocks(self) -> pd.DataFrame:
        table = pd.read_csv(os.path.join(self.data_dir, "securities.csv"), **sec.TEXT_SAFE)
        table = table[table["name"].map(sec.is_operating)]
        listings = pd.read_pickle(os.path.join(self.data_dir, "listings.pkl"))
        exchange = listings.dropna(subset=["exchange"]).drop_duplicates("symbol").set_index("symbol")["exchange"]
        return pd.DataFrame({"name": table["name"].values, "exchange": table["symbol"].map(exchange).values},
                            index=pd.Index(table["security"].values, name="symbol"))

    def daily_bars(self, symbols: List[str], start: date, end: date) -> pd.DataFrame:
        """Adjusted daily bars as long rows: symbol, timestamp, close, volume (the AlpacaData.daily_bars shape)."""
        rows = self._rows(symbols, start, end).reset_index(drop=True)
        return pd.DataFrame({"symbol": rows["symbol"],
                             "timestamp": rows["day"].dt.tz_localize("America/New_York").dt.tz_convert("UTC"),
                             "close": rows["close"], "volume": rows["volume"]})

    def raw_closes(self, symbols: List[str], day: date) -> Dict[str, float]:
        rows = self._rows(symbols, day - timedelta(days=RAW_CLOSE_LOOKBACK_DAYS), day)
        last = rows.sort_values("day").groupby("symbol")["raw_close"].last()
        return {s: float(v) for s, v in last.items()}


class HistoricalShares:
    """SharesCache stand-in; get() never fetches and save() writes nothing.

    Companies still trading at the end of the dataset use the yfinance history already in the top_performers cache
    (read-only; under their own ticker or one Alpaca shows as the same company, e.g. FB -> META) from its first date
    (~2015) on, which is what the Alpaca-based runs use, and SEC counts (shares.json) before it. Companies that died
    use SEC counts only: for them the yfinance entry would belong to the ticker's current owner. SEC counts miss
    foreign filers (20-F) and are unreliable for multi-class companies, so yfinance wins wherever it has data."""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR, yfinance_path: str = YFINANCE_SHARES_PATH):
        with open(os.path.join(data_dir, "shares.json")) as fh:
            self._sec = json.load(fh)
        self._yf: Dict[str, Dict[str, int]] = {}
        if os.path.exists(yfinance_path):
            table = pd.read_csv(os.path.join(data_dir, "securities.csv"), **sec.TEXT_SAFE)
            trading = set(table.loc[pd.to_datetime(table["last_day"]) >= STILL_TRADING_FROM, "security"])
            alias_path = os.path.join(data_dir, "aliases.csv")
            aliases = alias_map(pd.read_csv(alias_path, **sec.TEXT_SAFE)) if os.path.exists(alias_path) else {}
            with open(yfinance_path) as fh:
                cached = {s: e["shares"] for s, e in json.load(fh).items() if e.get("shares")}
            for security in trading:
                for key in [security] + aliases.get(security, []):
                    if key in cached:
                        self._yf[security] = cached[key]
                        break

    def get(self, symbol: str, today: Optional[date] = None) -> Optional[pd.Series]:
        sec_counts, yf_counts = _series(self._sec.get(symbol)), _series(self._yf.get(symbol))
        if yf_counts is None:
            return sec_counts
        if sec_counts is None:
            return yf_counts
        return pd.concat([sec_counts[sec_counts.index < yf_counts.index.min()], yf_counts])

    def save(self) -> None:
        pass


def _series(entry: Optional[Dict[str, int]]) -> Optional[pd.Series]:
    if not entry:
        return None
    s = pd.Series(entry, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()
