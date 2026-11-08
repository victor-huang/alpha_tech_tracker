"""Industry labels (Nasdaq screener) and industry-group strength features for the checkpoint panels.

Labels are today's classification applied to all past checkpoints; there is no point-in-time history.
"""
import os
from datetime import date, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd
import requests

NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
INDUSTRY_TTL_DAYS = 30
MIN_GROUP_MEMBERS = 5
TOP_GROUP_SHARE = 0.2
STRONG_BREADTH = 0.6
GROUP_FACTORS = ["group_top20_120d", "group_top20_60d", "group_breadth_60", "group_bottom20_120d",
                 "leader_in_top_group"]


def fetch_nasdaq_industries() -> pd.DataFrame:
    response = requests.get(NASDAQ_SCREENER_URL, params={"tableonly": "true", "download": "true"},
                            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=60)
    response.raise_for_status()
    rows = pd.DataFrame(response.json()["data"]["rows"])
    return normalize_industries(rows)


def normalize_industries(rows: pd.DataFrame) -> pd.DataFrame:
    """symbol (Alpaca style, BRK.B not BRK/B), sector, industry; blank labels dropped."""
    out = rows[["symbol", "sector", "industry"]].copy()
    out["symbol"] = out["symbol"].str.strip().str.replace("/", ".", regex=False).str.replace("^", ".", regex=False)
    out = out[(out["industry"].str.strip() != "") & out["industry"].notna()]
    return out.drop_duplicates("symbol").reset_index(drop=True)


class IndustryCache:
    """CSV cache of the industry table, refreshed when older than INDUSTRY_TTL_DAYS."""

    def __init__(self, path: str, fetcher: Callable[[], pd.DataFrame] = fetch_nasdaq_industries):
        self.path = path
        self.fetcher = fetcher

    def load(self, today: date) -> pd.DataFrame:
        cached = self._read()
        if cached is not None and _fetched_on(self.path) > today - timedelta(days=INDUSTRY_TTL_DAYS):
            return cached
        table = self.fetcher()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        table.to_csv(self.path, index=False)
        return table

    def _read(self) -> Optional[pd.DataFrame]:
        if not os.path.exists(self.path):
            return None
        return pd.read_csv(self.path, keep_default_na=False)


def _fetched_on(path: str) -> date:
    return date.fromtimestamp(os.path.getmtime(path))


def add_group_strength(panel: pd.DataFrame, industries: pd.DataFrame) -> pd.DataFrame:
    """Per (checkpoint, industry): median 60/120-day return, its percentile among industries and breadth
    (share of members in an uptrend); plus 0/1 factor columns (NaN where the stock has no usable group)."""
    p = panel.merge(industries[["symbol", "industry"]], on="symbol", how="left")
    p["trend_ok"] = (p["close"] > p["ma50"]) & (p["ma50"] > p["ma200"]) & p["ma200_rising"].astype(bool)
    grouped = p[p["industry"].notna()].groupby(["checkpoint", "industry"])
    groups = grouped.agg(group_members=("symbol", "size"), group_ret_120d=("ret_120d", "median"),
                         group_ret_60d=("ret_60d", "median"), group_breadth=("trend_ok", "mean")).reset_index()
    groups = groups[groups["group_members"] >= MIN_GROUP_MEMBERS]
    by_cp = groups.groupby("checkpoint")
    groups["group_rank_120d"] = by_cp["group_ret_120d"].rank(pct=True)
    groups["group_rank_60d"] = by_cp["group_ret_60d"].rank(pct=True)
    p = p.merge(groups, on=["checkpoint", "industry"], how="left")

    known = p["group_rank_120d"].notna()
    flags = {
        "group_top20_120d": p["group_rank_120d"] > 1 - TOP_GROUP_SHARE,
        "group_top20_60d": p["group_rank_60d"] > 1 - TOP_GROUP_SHARE,
        "group_breadth_60": p["group_breadth"] >= STRONG_BREADTH,
        "group_bottom20_120d": p["group_rank_120d"] <= TOP_GROUP_SHARE,
        "leader_in_top_group": (p["group_rank_120d"] > 1 - TOP_GROUP_SHARE) & (p["ret_120d"] > p["group_ret_120d"])
        & p["trend_ok"],
    }
    for name, flag in flags.items():
        p[name] = np.where(known, flag.astype(float), np.nan)
    return p.drop(columns="trend_ok")
