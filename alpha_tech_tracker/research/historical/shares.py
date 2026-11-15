"""Phase 5 of research/docs/historical_data_2005_2019_plan.md: reported share counts per security from SEC filings.

Usage (from the repo root, after normalize.py):

    python -m alpha_tech_tracker.research.historical.shares

Writes market_data/historical/shares.json ({security: {date: shares}}, dated by period end, as yfinance's share
history is) and market_data/historical/securities.csv (security, name, cik, first_day, last_day).

CIK per security: the SEC's current ticker list when the security is the ticker's current owner (an active Alpaca
asset with that symbol), otherwise an exact normalized-name match against cik-lookup-data.txt, otherwise the CIK of a
ticker Alpaca shows as the same company (aliases.csv from normalize.py: FB and META, CTL and LUMN).
Before a company's first XBRL filing (2009-2011) there is no count; top_performers.market_cap_at then uses its
first reported counts (the back-fill chosen for tiers before 2009).
"""
import argparse
import json
import os
import zipfile
from typing import Dict, List, Optional

import pandas as pd

from alpha_tech_tracker.research.historical import normalize as nz
from alpha_tech_tracker.research.historical import securities as sec
from alpha_tech_tracker.research.sec_fundamentals import _metric_values

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "market_data", "historical")
DEFAULT_COMPANY_FACTS = os.path.join(REPO_ROOT, "market_data", "top_performers", "sec", "companyfacts.zip")
MIN_SHARES = 100_000
STILL_TRADING_FROM = pd.Timestamp("2020-06-01")


def security_table(rows: pd.DataFrame, listings: pd.DataFrame, runs: pd.DataFrame,
                   aliases: Optional[Dict[str, List[str]]] = None) -> pd.DataFrame:
    """One row per security: first/last day, base symbol and name.

    Name: the Alpha Vantage listing whose dates overlap the security's trading most, else the current Alpaca name of
    a ticker Alpaca shows as the same company (FB -> META: Alpha Vantage and Alpaca file Facebook under META even in
    2016), else its WIKI run's name, else (only while it still trades at the end of the data) its own Alpaca name.
    Alpaca's name belongs to the ticker's current owner, which for a renamed or dead company is whoever reused the
    ticker (FB is now a ProShares ETF)."""
    spans = rows.groupby("symbol")["day"].agg(first_day="min", last_day="max").reset_index()
    spans = spans.rename(columns={"symbol": "security"})
    spans["symbol"] = spans["security"].str.split("~").str[0]
    dated = listings[(listings["source"] == "alphavantage")].dropna(subset=["name", "start"])
    dated_by_symbol = {sym: g for sym, g in dated.groupby("symbol")}
    run_name = runs.dropna(subset=["name"]).drop_duplicates("security").set_index("security")["name"]
    alpaca = listings[listings["source"] == "alpaca"].dropna(subset=["name"]).drop_duplicates("symbol")
    alpaca_name = alpaca.set_index("symbol")["name"]
    active = set(alpaca.loc[alpaca["status"] == "active", "symbol"])
    aliases = aliases or {}
    still_trading = spans["last_day"] >= STILL_TRADING_FROM
    names = []
    for r in spans.itertuples():
        name = sec.name_for_run(r, dated_by_symbol) if r.symbol in dated_by_symbol else None
        if name is None:
            name = next((alpaca_name[o] for o in aliases.get(r.security, []) if o in active and o in alpaca_name),
                        None)
        if name is None:
            name = run_name.get(r.security)
        if name is None and r.security == r.symbol and still_trading[r.Index]:
            name = alpaca_name.get(r.symbol)
        names.append(name)
    spans["name"] = names
    spans["still_trading"] = still_trading
    return spans


def alias_map(aliases: pd.DataFrame) -> Dict[str, List[str]]:
    """symbol -> the other tickers Alpaca shows as the same company (both directions)."""
    out: Dict[str, List[str]] = {}
    for a, b in aliases[["symbol", "other"]].itertuples(index=False):
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    return out


def resolve_ciks(table: pd.DataFrame, active: set, ticker_ciks: Dict[str, int],
                 name_ciks: Dict[str, int], aliases: Optional[Dict[str, List[str]]] = None) -> pd.Series:
    current_owner = (table["security"] == table["symbol"]) & table["symbol"].isin(active) & table["still_trading"]
    by_ticker = table["symbol"].map(ticker_ciks).where(current_owner)
    by_name = table["name"].map(sec.normalize_name).map(name_ciks)
    aliases = aliases or {}

    def by_alias(security: str):
        for other in aliases.get(security, []):
            if other in active and other in ticker_ciks:
                return ticker_ciks[other]
        return None

    alias_cik = table["security"].map(by_alias)
    return by_ticker.fillna(by_name).fillna(alias_cik).astype("Int64")


def share_history(facts: dict) -> Optional[pd.Series]:
    """Reported counts by period end. Counts under MIN_SHARES are dropped: companies with several share classes
    report per class, and companyfacts.zip leaves those facts out, so what remains can be one small class (SPG's
    8,000 class B shares) or a placeholder (Fox's 1)."""
    values = _metric_values(facts, "shares")
    values = values[values["val"] >= MIN_SHARES]
    if values.empty:
        return None
    s = values.sort_values("known").drop_duplicates("end", keep="first").set_index("end")["val"].astype("float64")
    return s.sort_index()


def read_share_histories(zip_path: str, ciks: pd.Series) -> Dict[str, pd.Series]:
    """security -> share count series, for every security with a CIK found in companyfacts.zip."""
    out = {}
    by_cik = ciks.dropna().astype(int)
    with zipfile.ZipFile(zip_path) as archive:
        members = set(archive.namelist())
        cache: Dict[int, Optional[pd.Series]] = {}
        for security, cik in by_cik.items():
            if cik not in cache:
                member = f"CIK{cik:010d}.json"
                cache[cik] = share_history(json.loads(archive.read(member))) if member in members else None
            if cache[cik] is not None:
                out[security] = cache[cik]
    return out


def to_json(histories: Dict[str, pd.Series]) -> Dict[str, Dict[str, int]]:
    return {s: {d.date().isoformat(): int(v) for d, v in series.items()} for s, series in histories.items()}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--company-facts", default=DEFAULT_COMPANY_FACTS)
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    raw = os.path.join(args.data_dir, "raw")
    rows = nz.load_years(os.path.join(args.data_dir, "daily"), 2003, 2020)[["symbol", "day"]]
    listings = pd.read_pickle(os.path.join(args.data_dir, "listings.pkl"))
    runs = pd.read_pickle(os.path.join(args.data_dir, "wiki_runs.pkl"))
    aliases = pd.read_csv(os.path.join(args.data_dir, "aliases.csv"), **sec.TEXT_SAFE)
    table = security_table(rows, listings, runs, alias_map(aliases))
    alpaca = listings[listings["source"] == "alpaca"]
    table["cik"] = resolve_ciks(table, set(alpaca.loc[alpaca["status"] == "active", "symbol"]),
                                sec.sec_ticker_ciks(os.path.join(raw, "sec", "company_tickers.json")),
                                sec.sec_name_ciks(os.path.join(raw, "sec", "cik-lookup-data.txt")),
                                alias_map(aliases))
    table.to_csv(os.path.join(args.data_dir, "securities.csv"), index=False)
    histories = read_share_histories(args.company_facts, table.set_index("security")["cik"])
    with open(os.path.join(args.data_dir, "shares.json"), "w") as fh:
        json.dump(to_json(histories), fh)
    print(f"{len(table)} securities, {table['name'].notna().mean():.0%} named, {table['cik'].notna().mean():.0%} "
          f"with CIK, {len(histories)} with share counts")


if __name__ == "__main__":
    run(parse_args())
