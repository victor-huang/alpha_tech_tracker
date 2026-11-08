"""Point-in-time quarterly sales and net income from SEC XBRL company facts, and growth-acceleration factors.

Earnings growth uses net income rather than EPS: first-filed EPS mixes pre- and post-split share counts (NVDA's
2024 10-for-1 split turns a derived Q4 EPS negative), while net income is unaffected by splits.

Data: the nightly bulk file companyfacts.zip (all filers) plus company_tickers.json for ticker -> CIK. SEC asks
every client to identify itself, so requests use the SEC_USER_AGENT environment variable
("Your Name your.email@example.com"); nothing is fetched without it.

Only US-GAAP filers are covered (10-Q / 10-K). Foreign private issuers filing 20-F / 6-K (many ADRs) have no
quarterly XBRL and get no score.

Point in time: each quarter keeps its first-filed value and the date it was filed; a checkpoint only sees
quarters filed strictly before it. Q4 is the annual value minus the three reported quarters of that fiscal year,
known from the 10-K filing date.
"""
import io
import json
import os
import time
import zipfile
from datetime import date, timedelta
from typing import Callable, Dict, Iterable

import numpy as np
import pandas as pd
import requests

COMPANY_FACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
USER_AGENT_ENV = "SEC_USER_AGENT"
FUNDAMENTALS_TTL_DAYS = 30

CONCEPTS = {
    "revenue": (["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
                 "RevenuesNetOfInterestExpense"], "USD"),
    "net_income": (["NetIncomeLoss", "ProfitLoss"], "USD"),
}
QUARTER_DAYS = (80, 100)
YEAR_DAYS = (350, 380)
YEAR_AGO_TOLERANCE_DAYS = 25
MAX_REPORT_AGE_DAYS = 200
SALES_GROWTH = 0.25
EARNINGS_GROWTH = 0.25
SALES_ACCEL = 0.05
COMBO_GROWTH = 0.20
SALES_DECEL = -0.10
MARGIN_EXPANSION = 0.01
FUNDAMENTAL_FACTORS = ["sales_growth_25", "sales_accel", "sales_accel_2q", "earnings_growth_25", "earnings_accel",
                       "margin_expansion", "growth_accel_combo", "sales_decel"]


def sec_user_agent() -> str:
    agent = os.environ.get(USER_AGENT_ENV, "").strip()
    if "@" not in agent:
        raise RuntimeError(f"set {USER_AGENT_ENV} to 'Your Name your.email@example.com' (SEC fair-access policy)")
    return agent


def _get(url: str, user_agent: str, stream: bool = False, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        response = requests.get(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
                                timeout=120, stream=stream)
        if response.status_code not in (429, 503):
            response.raise_for_status()
            return response
        time.sleep(2 ** attempt * 5)
    response.raise_for_status()
    return response


def fetch_ticker_ciks(user_agent: str) -> Dict[str, int]:
    """Ticker (Alpaca style, BRK.B) -> CIK, from SEC's current ticker list."""
    rows = _get(COMPANY_TICKERS_URL, user_agent).json().values()
    return {r["ticker"].upper().replace("-", "."): int(r["cik_str"]) for r in rows}


def download_company_facts(path: str, user_agent: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial = path + ".part"
    with _get(COMPANY_FACTS_URL, user_agent, stream=True) as response, open(partial, "wb") as out:
        for chunk in response.iter_content(chunk_size=1 << 20):
            out.write(chunk)
    os.replace(partial, path)


def concept_facts(facts: dict, metric: str) -> pd.DataFrame:
    """Duration facts for one metric across its candidate concepts (earlier concepts win the same period)."""
    names, unit = CONCEPTS[metric]
    gaap = facts.get("facts", {}).get("us-gaap", {})
    frames = []
    for priority, name in enumerate(names):
        rows = gaap.get(name, {}).get("units", {}).get(unit, [])
        rows = [r for r in rows if "start" in r and r.get("form", "").startswith(("10-Q", "10-K"))]
        if rows:
            frames.append(pd.DataFrame(rows)[["start", "end", "val", "filed"]].assign(priority=priority))
    if not frames:
        return pd.DataFrame(columns=["start", "end", "val", "filed"])
    df = pd.concat(frames, ignore_index=True)
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col])
    df = df.sort_values(["start", "end", "priority", "filed"])
    return df.groupby(["start", "end"], as_index=False).first()[["start", "end", "val", "filed"]]


def quarterly_values(facts: pd.DataFrame) -> pd.DataFrame:
    """One row per fiscal quarter: end, val and the date it became known (Q4 derived from the annual value)."""
    if facts.empty:
        return pd.DataFrame(columns=["end", "val", "known"])
    days = (facts["end"] - facts["start"]).dt.days
    quarters = facts[days.between(*QUARTER_DAYS)].rename(columns={"filed": "known"})
    annual = facts[days.between(*YEAR_DAYS)]
    derived = []
    for row in annual.itertuples():
        inside = quarters[(quarters["start"] >= row.start - timedelta(days=5)) & (quarters["end"] < row.end)
                          & (quarters["end"] > row.start)]
        if len(inside) == 3 and not (quarters["end"] - row.end).abs().dt.days.le(5).any():
            derived.append({"start": inside["end"].max() + timedelta(days=1), "end": row.end,
                            "val": row.val - inside["val"].sum(), "known": max(row.filed, inside["known"].max())})
    out = pd.concat([quarters, pd.DataFrame(derived)], ignore_index=True) if derived else quarters
    return out.sort_values("end").drop_duplicates("end", keep="first")[["end", "val", "known"]].reset_index(drop=True)


def company_quarters(facts: dict) -> pd.DataFrame:
    """Quarterly revenue / net_income for one company: columns metric, end, val, known."""
    parts = [quarterly_values(concept_facts(facts, m)).assign(metric=m) for m in CONCEPTS]
    return pd.concat(parts, ignore_index=True)


def extract_quarters(zip_path: str, ciks: Dict[str, int]) -> pd.DataFrame:
    """Quarterly rows (symbol, metric, end, val, known) for the requested tickers, read from companyfacts.zip."""
    wanted = {}
    for symbol, cik in ciks.items():
        wanted.setdefault(f"CIK{cik:010d}.json", []).append(symbol)
    rows = []
    with zipfile.ZipFile(zip_path) as archive:
        members = set(archive.namelist())
        for member, symbols in wanted.items():
            if member not in members:
                continue
            with archive.open(member) as fh:
                facts = json.load(io.TextIOWrapper(fh, encoding="utf-8"))
            quarters = company_quarters(facts)
            for symbol in symbols:
                rows.append(quarters.assign(symbol=symbol))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["metric", "end", "val", "known", "symbol"])


class FundamentalsCache:
    """Compact pickle of extracted quarters, rebuilt from a fresh companyfacts.zip when older than the TTL or
    missing requested symbols (symbols SEC does not list are remembered so they are not retried)."""

    def __init__(self, root: str, user_agent_for: Callable[[], str] = sec_user_agent,
                 download: Callable[[str, str], None] = download_company_facts,
                 ticker_ciks: Callable[[str], Dict[str, int]] = fetch_ticker_ciks,
                 extract: Callable[[str, Dict[str, int]], pd.DataFrame] = extract_quarters, keep_zip: bool = False):
        self.root = root
        self.user_agent_for = user_agent_for
        self.download = download
        self.ticker_ciks = ticker_ciks
        self.extract = extract
        self.keep_zip = keep_zip

    @property
    def path(self) -> str:
        return os.path.join(self.root, "sec_quarters.pkl")

    def load(self, symbols: Iterable[str], today: date) -> pd.DataFrame:
        symbols = sorted(set(symbols))
        cached = pd.read_pickle(self.path) if os.path.exists(self.path) else None
        if cached is not None and cached["fetched_on"] > today - timedelta(days=FUNDAMENTALS_TTL_DAYS) \
                and not set(symbols) - set(cached["covered"]):
            return cached["quarters"]
        agent = self.user_agent_for()
        ciks = self.ticker_ciks(agent)
        zip_path = os.path.join(self.root, "companyfacts.zip")
        if not os.path.exists(zip_path) or date.fromtimestamp(os.path.getmtime(zip_path)) < today - timedelta(
                days=FUNDAMENTALS_TTL_DAYS):
            print("downloading SEC companyfacts.zip", flush=True)
            self.download(zip_path, agent)
        quarters = self.extract(zip_path, {s: ciks[s] for s in symbols if s in ciks})
        os.makedirs(self.root, exist_ok=True)
        pd.to_pickle({"fetched_on": today, "covered": symbols, "quarters": quarters}, self.path)
        if not self.keep_zip:
            os.remove(zip_path)
        return quarters


def growth_table(quarters: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, quarter end): year-over-year growth of sales and net income (from a positive base), the
    previous quarter's growth, net margin vs a year ago, and the date the quarter became known."""
    quarters = quarters[quarters["metric"].isin(list(CONCEPTS))]
    wide = quarters.pivot_table(index=["symbol", "end"], columns="metric", values="val", aggfunc="first")
    known = quarters.groupby(["symbol", "end"])["known"].max()
    wide = wide.join(known).reset_index().sort_values(["symbol", "end"])
    for metric in CONCEPTS:
        if metric not in wide:
            wide[metric] = np.nan
    out = []
    for symbol, g in wide.groupby("symbol", sort=False):
        g = g.reset_index(drop=True)
        year_ago = _year_ago_index(g["end"])
        prev = _previous_quarter_index(g["end"])
        rev, rev_ly = g["revenue"], _take(g["revenue"], year_ago)
        income, income_ly = g["net_income"], _take(g["net_income"], year_ago)
        margin = income / rev.where(rev > 0)
        g["rev_yoy"] = (rev / rev_ly.where(rev_ly > 0) - 1)
        g["ni_yoy"] = income / income_ly.where(income_ly > 0) - 1
        g["margin_change"] = margin - _take(margin, year_ago)
        g["rev_yoy_prev"] = _take(g["rev_yoy"], prev)
        g["ni_yoy_prev"] = _take(g["ni_yoy"], prev)
        g["rev_accel"] = g["rev_yoy"] - g["rev_yoy_prev"]
        g["rev_accel_prev"] = _take(g["rev_accel"], prev)
        out.append(g)
    return pd.concat(out, ignore_index=True) if out else wide


def _year_ago_index(ends: pd.Series) -> pd.Series:
    return _match(ends, 365)


def _previous_quarter_index(ends: pd.Series) -> pd.Series:
    return _match(ends, 91)


def _match(ends: pd.Series, offset_days: int) -> pd.Series:
    """Row index of the quarter ending about `offset_days` before each row (-1 when there is none)."""
    values = ends.values.astype("datetime64[D]").astype(np.int64)
    target = values - offset_days
    pos = np.searchsorted(values, target)
    best = np.full(len(values), -1)
    for i, (t, p) in enumerate(zip(target, pos)):
        for j in (p - 1, p):
            if 0 <= j < len(values) and abs(values[j] - t) <= YEAR_AGO_TOLERANCE_DAYS and j != i:
                if best[i] == -1 or abs(values[j] - t) < abs(values[best[i]] - t):
                    best[i] = j
    return pd.Series(best, index=ends.index)


def _take(series: pd.Series, index: pd.Series) -> pd.Series:
    values = series.values.astype(float)
    taken = np.where(index.values >= 0, values[np.clip(index.values, 0, None)], np.nan)
    return pd.Series(taken, index=series.index)


def add_fundamental_factors(panel: pd.DataFrame, quarters: pd.DataFrame) -> pd.DataFrame:
    """Latest quarter filed strictly before each checkpoint (and ending within MAX_REPORT_AGE_DAYS); 0/1 factor
    columns, NaN where the stock has no usable report."""
    growth = growth_table(quarters).dropna(subset=["known"]).sort_values("known")
    growth = growth.rename(columns={"end": "quarter_end"})
    keys = panel[["checkpoint", "symbol"]].drop_duplicates().sort_values("checkpoint")
    keys["lookup"] = keys["checkpoint"] - pd.Timedelta(days=1)
    asof = pd.merge_asof(keys, growth, left_on="lookup", right_on="known", by="symbol", direction="backward")
    stale = (asof["checkpoint"] - asof["quarter_end"]).dt.days > MAX_REPORT_AGE_DAYS
    asof.loc[stale, ["rev_yoy", "ni_yoy", "margin_change", "rev_yoy_prev", "ni_yoy_prev", "rev_accel",
                     "rev_accel_prev"]] = np.nan

    def flag(condition: pd.Series, *needed: str) -> np.ndarray:
        known = asof[list(needed)].notna().all(axis=1)
        return np.where(known, condition.astype(float), np.nan)

    a = asof
    asof["sales_growth_25"] = flag(a["rev_yoy"] >= SALES_GROWTH, "rev_yoy")
    asof["sales_accel"] = flag((a["rev_yoy"] > 0) & (a["rev_accel"] >= SALES_ACCEL), "rev_accel")
    asof["sales_accel_2q"] = flag((a["rev_yoy"] > 0) & (a["rev_accel"] > 0) & (a["rev_accel_prev"] > 0),
                                  "rev_accel", "rev_accel_prev")
    asof["earnings_growth_25"] = flag(a["ni_yoy"] >= EARNINGS_GROWTH, "ni_yoy")
    asof["earnings_accel"] = flag((a["ni_yoy"] > 0) & (a["ni_yoy"] > a["ni_yoy_prev"]), "ni_yoy", "ni_yoy_prev")
    asof["margin_expansion"] = flag(a["margin_change"] >= MARGIN_EXPANSION, "margin_change")
    asof["growth_accel_combo"] = flag((a["rev_yoy"] >= COMBO_GROWTH) & (a["rev_accel"] > 0)
                                      & (a["ni_yoy"] >= COMBO_GROWTH), "rev_accel", "ni_yoy")
    asof["sales_decel"] = flag(a["rev_accel"] <= SALES_DECEL, "rev_accel")
    cols = ["checkpoint", "symbol", "rev_yoy", "rev_accel", "ni_yoy"] + FUNDAMENTAL_FACTORS
    return panel.merge(asof[cols], on=["checkpoint", "symbol"], how="left")


def coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """Share of panel rows per tier and year with a usable sales growth figure."""
    p = panel.assign(year=panel["checkpoint"].dt.year, has=panel["rev_yoy"].notna())
    return p.groupby(["tier", "year"])["has"].mean().unstack("year").round(2)

