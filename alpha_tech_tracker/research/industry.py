"""Industry per symbol (SEC SIC code) and a per-industry cap on ranked lists.

The SIC code comes from SEC's per-company submissions JSON (data.sec.gov/submissions/CIK##########.json), fetched
once per symbol and cached as a CSV; symbols SEC does not list are cached with an empty code and never capped.
Requests need the SEC_USER_AGENT environment variable, as in sec_fundamentals.

The code is the company's current classification, not point in time; a company rarely changes industry.
"""
import os
import time
from typing import Callable, Dict, Iterable, Tuple

import pandas as pd

from alpha_tech_tracker.research.sec_fundamentals import _get, fetch_ticker_ciks, sec_user_agent

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
REQUEST_INTERVAL_SECONDS = 0.15
COLUMNS = ["symbol", "sic", "sic_description"]


def fetch_sic(cik: int, user_agent: str) -> Tuple[str, str]:
    submissions = _get(SUBMISSIONS_URL.format(cik=cik), user_agent).json()
    return str(submissions.get("sic") or ""), submissions.get("sicDescription") or ""


class IndustryCache:
    """symbol -> SIC code and description, fetching only symbols not cached yet."""

    def __init__(self, root: str, user_agent_for: Callable[[], str] = sec_user_agent,
                 ticker_ciks: Callable[[str], Dict[str, int]] = fetch_ticker_ciks,
                 fetch: Callable[[int, str], Tuple[str, str]] = fetch_sic,
                 pause: float = REQUEST_INTERVAL_SECONDS):
        self.root = root
        self.user_agent_for = user_agent_for
        self.ticker_ciks = ticker_ciks
        self.fetch = fetch
        self.pause = pause

    @property
    def path(self) -> str:
        return os.path.join(self.root, "industry.csv")

    def load(self, symbols: Iterable[str]) -> pd.DataFrame:
        cached = pd.read_csv(self.path, dtype=str, keep_default_na=False) if os.path.exists(self.path) \
            else pd.DataFrame(columns=COLUMNS)
        missing = sorted(set(symbols) - set(cached["symbol"]))
        if missing:
            agent = self.user_agent_for()
            ciks = self.ticker_ciks(agent)
            rows = []
            for symbol in missing:
                sic, description = ("", "")
                if symbol in ciks:
                    sic, description = self.fetch(ciks[symbol], agent)
                    time.sleep(self.pause)
                rows.append({"symbol": symbol, "sic": sic, "sic_description": description})
            cached = pd.concat([cached, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
            os.makedirs(self.root, exist_ok=True)
            cached.sort_values("symbol").to_csv(self.path, index=False)
        return cached.set_index("symbol")


def industry_of(table: pd.DataFrame, digits: int = 4) -> Dict[str, str]:
    """symbol -> the first `digits` of its SIC code (4 = industry, 3 = industry group, 2 = major group)."""
    return {s: sic[:digits] for s, sic in table["sic"].items() if sic}


def cap_per_industry(ranked: pd.DataFrame, industry: Dict[str, str], per_industry: int = 1) -> pd.DataFrame:
    """Ranked rows with any name beyond the first `per_industry` of its industry (in rank order, per checkpoint and
    tier) removed, re-ranked 1..k. Names without an industry are never removed."""
    rows = ranked.sort_values(["checkpoint", "tier", "rank"])
    group = rows["symbol"].map(industry)
    seen = rows.assign(_industry=group).groupby(["checkpoint", "tier", "_industry"]).cumcount()
    kept = rows[group.isna() | (seen < per_industry)].copy()
    kept["rank"] = kept.groupby(["checkpoint", "tier"]).cumcount() + 1.0
    return kept
