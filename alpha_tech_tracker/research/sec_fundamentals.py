"""Point-in-time quarterly fundamentals from SEC XBRL company facts: sales / earnings growth-acceleration factors
and balance-sheet quality factors (share dilution, cash burn and runway, gross profitability).

Earnings growth uses net income rather than EPS: first-filed EPS mixes pre- and post-split share counts (NVDA's
2024 10-for-1 split turns a derived Q4 EPS negative), while net income is unaffected by splits.

Data: the nightly bulk file companyfacts.zip (all filers) plus company_tickers.json for ticker -> CIK. SEC asks
every client to identify itself, so requests use the SEC_USER_AGENT environment variable
("Your Name your.email@example.com"); nothing is fetched without it.

Only US-GAAP filers are covered (10-Q / 10-K). Foreign private issuers filing 20-F / 6-K (many ADRs) have no
quarterly XBRL and get no score.

Point in time: each quarter keeps its first-filed value and the date it was filed; a checkpoint only sees
quarters filed strictly before it. Q4 is the annual value minus the three reported quarters of that fiscal year,
known from the 10-K filing date. Operating cash flow is reported year-to-date, so each quarter is the difference
between consecutive year-to-date totals. Balance-sheet values (shares, assets, cash) are instants.

Share counts are not split-adjusted: a one-year change outside SPLIT_GUARD is treated as a likely split and left
unscored, so a 3-for-2 split can still read as dilution.
"""
import io
import json
import os
import time
import zipfile
from datetime import date, timedelta
from typing import Callable, Dict, Iterable, NamedTuple, Tuple

import numpy as np
import pandas as pd
import requests

COMPANY_FACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
USER_AGENT_ENV = "SEC_USER_AGENT"
FUNDAMENTALS_TTL_DAYS = 30



class Concept(NamedTuple):
    names: Tuple[str, ...]
    unit: str = "USD"
    kind: str = "duration"


CONCEPTS = {
    "revenue": Concept(("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
                        "RevenuesNetOfInterestExpense")),
    "net_income": Concept(("NetIncomeLoss", "ProfitLoss")),
    "gross_profit": Concept(("GrossProfit",)),
    "cost_of_revenue": Concept(("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")),
    "operating_cash_flow": Concept(("NetCashProvidedByUsedInOperatingActivities",
                                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"), kind="ytd"),
    "shares": Concept(("dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"), "shares",
                      "instant"),
    "assets": Concept(("Assets",), kind="instant"),
    "cash": Concept(("CashAndCashEquivalentsAtCarryingValue",
                     "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"), kind="instant"),
}
GROWTH_METRICS = ("revenue", "net_income")
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
SHARES_YEAR_TOLERANCE_DAYS = 45
SPLIT_GUARD = (0.55, 1.8)
DILUTION = 0.10
BUYBACK = -0.02
RUNWAY_QUARTERS = 4
GROSS_PROFIT_TOP = 0.7
TTM_SPAN_DAYS = (250, 300)
QUALITY_FACTORS = ["dilution_10", "buyback_2", "cash_burn", "low_runway", "gp_top30"]


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
    """Facts for one metric across its candidate concepts (earlier concepts win the same period); instants get
    start = end. Names default to the us-gaap namespace ("dei:Name" for others)."""
    concept = CONCEPTS[metric]
    instant = concept.kind == "instant"
    frames = []
    for priority, qualified in enumerate(concept.names):
        namespace, _, name = qualified.rpartition(":")
        rows = facts.get("facts", {}).get(namespace or "us-gaap", {}).get(name, {}).get("units", {}).get(
            concept.unit, [])
        rows = [dict(r, start=r["end"]) if instant else r for r in rows
                if ("start" in r) != instant and r.get("form", "").startswith(("10-Q", "10-K"))]
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


def ytd_quarterly_values(facts: pd.DataFrame) -> pd.DataFrame:
    """Quarters from year-to-date totals: a reported 3-month value, else this YTD minus the YTD one quarter shorter
    with the same start."""
    if facts.empty:
        return pd.DataFrame(columns=["end", "val", "known"])
    days = (facts["end"] - facts["start"]).dt.days
    direct = facts[days.between(*QUARTER_DAYS)].rename(columns={"filed": "known"})
    derived = []
    for row in facts[days > QUARTER_DAYS[1]].itertuples():
        shorter = facts[((facts["start"] - row.start).abs().dt.days <= 5)
                        & (row.end - facts["end"]).dt.days.between(*QUARTER_DAYS)]
        if len(shorter):
            prior = shorter.iloc[0]
            derived.append({"end": row.end, "val": row.val - prior["val"], "known": max(row.filed, prior["filed"])})
    out = pd.concat([direct, pd.DataFrame(derived)], ignore_index=True) if derived else direct
    return out.sort_values("end").drop_duplicates("end", keep="first")[["end", "val", "known"]].reset_index(drop=True)


def _metric_values(facts: dict, metric: str) -> pd.DataFrame:
    rows = concept_facts(facts, metric)
    kind = CONCEPTS[metric].kind
    if kind == "instant":
        return rows.rename(columns={"filed": "known"})[["end", "val", "known"]]
    return ytd_quarterly_values(rows) if kind == "ytd" else quarterly_values(rows)


def company_quarters(facts: dict) -> pd.DataFrame:
    """Quarterly flows and balance-sheet instants for one company: columns metric, end, val, known."""
    parts = [_metric_values(facts, m).assign(metric=m) for m in CONCEPTS]
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
    """Compact pickle of extracted quarters, rebuilt when older than the TTL, missing requested symbols (symbols
    SEC does not list are remembered so they are not retried) or extracted before new metrics were added.

    companyfacts.zip (~1 GB) is kept next to it and reused while younger than the TTL, so adding a metric only
    re-extracts."""

    def __init__(self, root: str, user_agent_for: Callable[[], str] = sec_user_agent,
                 download: Callable[[str, str], None] = download_company_facts,
                 ticker_ciks: Callable[[str], Dict[str, int]] = fetch_ticker_ciks,
                 extract: Callable[[str, Dict[str, int]], pd.DataFrame] = extract_quarters, keep_zip: bool = True):
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
                and not set(symbols) - set(cached["covered"]) and cached.get("metrics") == sorted(CONCEPTS):
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
        pd.to_pickle({"fetched_on": today, "covered": symbols, "metrics": sorted(CONCEPTS), "quarters": quarters},
                     self.path)
        if not self.keep_zip:
            os.remove(zip_path)
        return quarters


def growth_table(quarters: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, quarter end): year-over-year growth of sales and net income (from a positive base), the
    previous quarter's growth, net margin vs a year ago, and the date the quarter became known."""
    quarters = quarters[quarters["metric"].isin(GROWTH_METRICS)]
    wide = quarters.pivot_table(index=["symbol", "end"], columns="metric", values="val", aggfunc="first")
    known = quarters.groupby(["symbol", "end"])["known"].max()
    wide = wide.join(known).reset_index().sort_values(["symbol", "end"])
    for metric in GROWTH_METRICS:
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


def _year_ago_index(ends: pd.Series, tolerance: int = YEAR_AGO_TOLERANCE_DAYS) -> pd.Series:
    return _match(ends, 365, tolerance)


def _previous_quarter_index(ends: pd.Series) -> pd.Series:
    return _match(ends, 91)


def _match(ends: pd.Series, offset_days: int, tolerance: int = YEAR_AGO_TOLERANCE_DAYS) -> pd.Series:
    """Row index of the quarter ending about `offset_days` before each row (-1 when there is none)."""
    values = ends.values.astype("datetime64[D]").astype(np.int64)
    target = values - offset_days
    pos = np.searchsorted(values, target)
    best = np.full(len(values), -1)
    for i, (t, p) in enumerate(zip(target, pos)):
        for j in (p - 1, p):
            if 0 <= j < len(values) and abs(values[j] - t) <= tolerance and j != i:
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
    return add_quality_factors(panel.merge(asof[cols], on=["checkpoint", "symbol"], how="left"), quarters)


def share_change_table(quarters: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, share-count date): one-year change in shares outstanding, NaN when it looks like a split."""
    shares = quarters[quarters["metric"] == "shares"].sort_values(["symbol", "end"])
    out = []
    for symbol, g in shares.groupby("symbol", sort=False):
        g = g.reset_index(drop=True)
        shares = g["val"].astype(float).where(g["val"].astype(float) > 0)
        ratio = shares / _take(shares, _year_ago_index(g["end"], SHARES_YEAR_TOLERANCE_DAYS))
        out.append(g.assign(share_change=(ratio - 1).where(ratio.between(*SPLIT_GUARD))))
    if not out:
        return pd.DataFrame(columns=["symbol", "end", "known", "share_change"])
    return pd.concat(out, ignore_index=True)[["symbol", "end", "known", "share_change"]]


def quality_table(quarters: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, quarter end): trailing-4-quarter gross profit over assets, trailing operating cash flow, cash,
    and the date all of it was known."""
    metrics = ["revenue", "gross_profit", "cost_of_revenue", "operating_cash_flow", "assets", "cash"]
    q = quarters[quarters["metric"].isin(metrics)]
    q = q.assign(val=q["val"].astype(float))
    columns = ["symbol", "end", "known", "gp_assets", "ocf_ttm", "cash"]
    if q.empty:
        return pd.DataFrame(columns=columns)
    wide = q.pivot_table(index=["symbol", "end"], columns="metric", values="val", aggfunc="first")
    wide = wide.reindex(columns=metrics).join(q.groupby(["symbol", "end"])["known"].max()).reset_index()
    wide = wide.sort_values(["symbol", "end"]).reset_index(drop=True)
    wide["gross"] = wide["gross_profit"].fillna(wide["revenue"] - wide["cost_of_revenue"])
    by = wide.groupby("symbol")
    span = (wide["end"] - by["end"].shift(3)).dt.days
    full_year = span.between(*TTM_SPAN_DAYS)
    wide["gross_ttm"] = by["gross"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True).where(full_year)
    wide["ocf_ttm"] = by["operating_cash_flow"].rolling(4, min_periods=4).sum().reset_index(
        level=0, drop=True).where(full_year)
    wide["known"] = pd.concat([by["known"].shift(k) for k in range(1, 4)] + [wide["known"]], axis=1).max(axis=1)
    wide["gp_assets"] = wide["gross_ttm"] / wide["assets"].where(wide["assets"] > 0)
    return wide[columns]


def _asof(panel: pd.DataFrame, table: pd.DataFrame, values) -> pd.DataFrame:
    keys = panel[["checkpoint", "symbol"]].drop_duplicates().sort_values("checkpoint")
    keys["lookup"] = keys["checkpoint"] - pd.Timedelta(days=1)
    table = table.dropna(subset=["known"]).rename(columns={"end": "as_of_end"})
    table = table.assign(known=pd.to_datetime(table["known"]), as_of_end=pd.to_datetime(table["as_of_end"]))
    table = table.sort_values("known")
    out = pd.merge_asof(keys, table, left_on="lookup", right_on="known", by="symbol", direction="backward")
    stale = (out["checkpoint"] - out["as_of_end"]).dt.days > MAX_REPORT_AGE_DAYS
    out.loc[stale, values] = np.nan
    return out[["checkpoint", "symbol"] + values]


def add_quality_factors(panel: pd.DataFrame, quarters: pd.DataFrame) -> pd.DataFrame:
    """Dilution / buyback from the share count, cash burn and runway from trailing operating cash flow and cash,
    and gross profitability in the top 30% of its checkpoint and tier."""
    p = panel.merge(_asof(panel, share_change_table(quarters), ["share_change"]), on=["checkpoint", "symbol"],
                    how="left")
    p = p.merge(_asof(panel, quality_table(quarters), ["gp_assets", "ocf_ttm", "cash"]), on=["checkpoint", "symbol"],
                how="left")
    p["share_change"] = p["share_change"].astype(float)
    for col in ("gp_assets", "ocf_ttm", "cash"):
        p[col] = p[col].astype(float)
    burning = p["ocf_ttm"] < 0
    runway = p["cash"] / (-p["ocf_ttm"] / 4)
    p["dilution_10"] = np.where(p["share_change"].notna(), (p["share_change"] >= DILUTION).astype(float), np.nan)
    p["buyback_2"] = np.where(p["share_change"].notna(), (p["share_change"] <= BUYBACK).astype(float), np.nan)
    p["cash_burn"] = np.where(p["ocf_ttm"].notna(), burning.astype(float), np.nan)
    p["low_runway"] = np.where(p["ocf_ttm"].notna() & (p["cash"].notna() | ~burning),
                               (burning & (runway < RUNWAY_QUARTERS)).astype(float), np.nan)
    gp_rank = p.groupby(["checkpoint", "tier"])["gp_assets"].rank(pct=True)
    p["gp_top30"] = np.where(gp_rank.notna(), (gp_rank >= GROSS_PROFIT_TOP).astype(float), np.nan)
    return p


def coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """Share of panel rows per tier and year with a usable sales growth figure."""
    p = panel.assign(year=panel["checkpoint"].dt.year)
    columns = {"sales_growth": "rev_yoy", "share_change": "share_change", "cash_flow": "ocf_ttm",
               "gross_profit": "gp_assets"}
    rows = {name: p[col].notna().groupby([p["tier"], p["year"]]).mean().unstack("year")
            for name, col in columns.items() if col in p}
    return pd.concat(rows, names=["field"]).round(2)

