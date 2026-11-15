"""Phase 2 of research/docs/historical_data_2005_2019_plan.md: what was listed when, and which source has its prices.

Usage (from the repo root, after the Phase 1 downloads):

    python -m alpha_tech_tracker.research.historical.securities

Writes to market_data/historical/:
- wiki_runs.pkl: one row per run of real trading (volume > 0) in WIKI up to WIKI_LAST_DAY (Alpaca takes over on
  2016-01-01, so WIKI's stale tickers and stray 2018 rows never matter). A ticker splits into two runs only when it
  looks like a different company: no trade for over REUSE_GAP_DAYS, or over GAP_DAYS with the adjusted price off by
  more than PRICE_BREAK x (DELL: 2013-10 at $13.85, junk rows in 2015 at $31.30). Shorter, price-continuous holes
  stay one run. Earlier runs of a ticker get `symbol~YYYY` (YYYY = the run's last year); the latest keeps the symbol.
- listings.pkl: one row per (symbol, listing) from Tiingo, Alpha Vantage and Alpaca, with name, exchange, asset type
  and dates where the source has them. Only plain-letter symbols (no preferreds, warrants or units).
- coverage.csv: per year (2005-2015, WIKI's span), how many operating stocks were listed (Tiingo dates, plus Alpha
  Vantage listings Tiingo lacks), how many have WIKI prices, and the rest split into still listed (fill from
  yfinance) and gone (no free source).

All sources key history by the ticker's latest owner, so names come from the listing whose dates overlap the run,
falling back to Alpaca's last-known name.
"""
import argparse
import glob
import json
import os
import re
from typing import Dict, Optional

import pandas as pd

from alpha_tech_tracker.research.top_performers import NON_OPERATING_NAME_RE

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "market_data", "historical")
GAP_DAYS = 30
REUSE_GAP_DAYS = 365
PRICE_BREAK = 2.0
WIKI_FIRST_DAY = pd.Timestamp("2003-01-01")
WIKI_LAST_DAY = pd.Timestamp("2015-12-31")
SYMBOL_RE = r"^[A-Z]{1,5}$"
# Tickers such as NA, NAN and NULL are real symbols; only empty cells and Alpha Vantage's "null" mean missing.
TEXT_SAFE = {"keep_default_na": False, "na_values": ["", "null"]}
WINDOW_START = pd.Timestamp("2004-09-01")
WINDOW_END = pd.Timestamp("2019-12-31")
WIKI_CHUNK_ROWS = 3_000_000
EXCHANGE_ALIASES = {"NYSE MKT": "AMEX", "NYSE AMERICAN": "AMEX", "NYSE ARCA": "ARCA", "NYSEARCA": "ARCA",
                    "NASDAQ GLOBAL SELECT": "NASDAQ", "NASDAQ GLOBAL MARKET": "NASDAQ", "NASDAQ CAPITAL MARKET": "NASDAQ"}
LISTED_EXCHANGES = ("NYSE", "NASDAQ", "AMEX", "ARCA", "BATS")
NAME_SUFFIX_RE = re.compile(r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|LP|LLC|HOLDINGS?|"
                            r"GROUP|THE|NEW|DE|DEL)\b")
NON_ALNUM_RE = re.compile(r"[^A-Z0-9 ]")
STILL_LISTED_FROM = pd.Timestamp("2026-01-01")


def normalize_exchange(exchange) -> Optional[str]:
    if not isinstance(exchange, str) or not exchange.strip():
        return None
    upper = exchange.strip().upper()
    return EXCHANGE_ALIASES.get(upper, upper)


def normalize_name(name) -> str:
    """Upper case, punctuation and corporate suffixes stripped, so 'Apple Inc.' and 'APPLE INC' match."""
    if not isinstance(name, str):
        return ""
    cleaned = NON_ALNUM_RE.sub(" ", name.upper())
    return " ".join(NAME_SUFFIX_RE.sub(" ", cleaned).split())


def trading_runs(days: pd.DataFrame, gap_days: int = GAP_DAYS, reuse_gap_days: int = REUSE_GAP_DAYS,
                 price_break: float = PRICE_BREAK) -> pd.DataFrame:
    """Rows (symbol, day, close) of real trades -> one row per run of one company: symbol, first_day, last_day, days.
    A new run starts after a gap over reuse_gap_days, or over gap_days with the close moved more than price_break x."""
    if days.empty:
        return pd.DataFrame(columns=["symbol", "first_day", "last_day", "days"])
    d = days.sort_values(["symbol", "day"]).reset_index(drop=True)
    new_symbol = d["symbol"].ne(d["symbol"].shift())
    gap = d["day"].diff().dt.days
    ratio = d["close"] / d["close"].shift()
    price_jump = (ratio > price_break) | (ratio < 1 / price_break)
    new_company = (gap > reuse_gap_days) | ((gap > gap_days) & price_jump)
    run_id = (new_symbol | new_company).cumsum()
    runs = d.groupby(run_id).agg(symbol=("symbol", "first"), first_day=("day", "min"), last_day=("day", "max"),
                                 days=("day", "size"))
    return runs.reset_index(drop=True)


def label_reused(runs: pd.DataFrame) -> pd.DataFrame:
    """Add `security`: the latest run per symbol keeps the symbol, earlier ones get symbol~<last year>."""
    out = runs.sort_values(["symbol", "first_day"]).reset_index(drop=True)
    latest = out.groupby("symbol")["first_day"].transform("max").eq(out["first_day"])
    out["security"] = out["symbol"].where(latest, out["symbol"] + "~" + out["last_day"].dt.year.astype(str))
    return out


def wiki_trading_days(zip_path: str) -> pd.DataFrame:
    frames = []
    for chunk in pd.read_csv(zip_path, usecols=["ticker", "date", "volume", "adj_close"], chunksize=WIKI_CHUNK_ROWS,
                             **TEXT_SAFE):
        day = pd.to_datetime(chunk["date"])
        real = (chunk["volume"] > 0) & (day >= WIKI_FIRST_DAY) & (day <= WIKI_LAST_DAY)
        frames.append(pd.DataFrame({"symbol": chunk.loc[real, "ticker"].str.upper(), "day": day[real],
                                    "close": chunk.loc[real, "adj_close"]}))
    return pd.concat(frames, ignore_index=True)


def plain_symbols(listings: pd.DataFrame) -> pd.DataFrame:
    return listings[listings["symbol"].str.match(SYMBOL_RE, na=False)].reset_index(drop=True)


def tiingo_listings(zip_path: str) -> pd.DataFrame:
    t = pd.read_csv(zip_path, **TEXT_SAFE)
    t = t[(t["assetType"] == "Stock") & (t["priceCurrency"] == "USD")].dropna(subset=["startDate", "endDate"])
    return pd.DataFrame({
        "symbol": t["ticker"].str.upper(), "name": None, "exchange": t["exchange"].map(normalize_exchange),
        "asset_type": "Stock", "start": pd.to_datetime(t["startDate"]), "end": pd.to_datetime(t["endDate"]),
        "status": None, "source": "tiingo",
    })


def alphavantage_listings(folder: str) -> pd.DataFrame:
    frames = [pd.read_csv(path, **TEXT_SAFE) for path in sorted(glob.glob(os.path.join(folder, "*.csv")))]
    if not frames:
        return pd.DataFrame(columns=["symbol", "name", "exchange", "asset_type", "start", "end", "status", "source"])
    a = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["symbol", "ipoDate", "delistingDate"])
    return pd.DataFrame({
        "symbol": a["symbol"].astype(str).str.upper(), "name": a["name"], "exchange": a["exchange"].map(normalize_exchange),
        "asset_type": a["assetType"], "start": pd.to_datetime(a["ipoDate"], errors="coerce"),
        "end": pd.to_datetime(a["delistingDate"], errors="coerce"), "status": a["status"].str.lower(),
        "source": "alphavantage",
    })


def alpaca_listings(csv_path: str) -> pd.DataFrame:
    a = pd.read_csv(csv_path, **TEXT_SAFE)
    return pd.DataFrame({
        "symbol": a["symbol"].str.upper(), "name": a["name"], "exchange": a["exchange"].map(normalize_exchange),
        "asset_type": "Stock", "start": pd.NaT, "end": pd.NaT, "status": a["status"].str.lower(), "source": "alpaca",
    })


def sec_ticker_ciks(json_path: str) -> Dict[str, int]:
    with open(json_path) as fh:
        rows = json.load(fh).values()
    return {r["ticker"].upper(): int(r["cik_str"]) for r in rows}


def sec_name_ciks(lookup_path: str) -> Dict[str, int]:
    """Normalized company name -> CIK from cik-lookup-data.txt ('NAME:CIK:' lines); names that map to more than one
    CIK are left out, so a match is never a guess between companies."""
    names, ciks = [], []
    with open(lookup_path, encoding="latin-1") as fh:
        for line in fh:
            parts = line.rstrip("\n").rsplit(":", 2)
            if len(parts) == 3 and parts[1].isdigit():
                names.append(normalize_name(parts[0]))
                ciks.append(int(parts[1]))
    table = pd.DataFrame({"name": names, "cik": ciks})
    table = table[table["name"] != ""].drop_duplicates()
    unique = table.groupby("name")["cik"].transform("nunique").eq(1)
    return dict(table[unique].drop_duplicates("name").itertuples(index=False, name=None))


def name_for_run(run, listings_by_symbol: Dict[str, pd.DataFrame]) -> Optional[str]:
    """The name of the listing with this symbol whose dates overlap the run most; otherwise Alpaca's last-known
    name, but only for the run that is still the ticker's latest (an earlier run belongs to a former owner)."""
    rows = listings_by_symbol.get(run.symbol)
    if rows is None:
        return None
    dated = rows.dropna(subset=["name", "start"])
    if not dated.empty:
        end = dated["end"].fillna(STILL_LISTED_FROM)
        overlap = (end.clip(upper=run.last_day) - dated["start"].clip(lower=run.first_day)).dt.days
        if overlap.max() > 0:
            return dated.loc[overlap.idxmax(), "name"]
    if run.security != run.symbol:
        return None
    named = rows.dropna(subset=["name"])
    return named["name"].iloc[0] if not named.empty else None


def is_operating(name) -> bool:
    return not (isinstance(name, str) and NON_OPERATING_NAME_RE.search(name))


def attach_names(runs: pd.DataFrame, listings: pd.DataFrame) -> pd.DataFrame:
    by_symbol = {s: g for s, g in listings.groupby("symbol")}
    out = runs.copy()
    out["name"] = [name_for_run(r, by_symbol) for r in out.itertuples()]
    out["operating"] = out["name"].map(is_operating)
    return out


def attach_ciks(frame: pd.DataFrame, ticker_ciks: Dict[str, int], name_ciks: Dict[str, int]) -> pd.DataFrame:
    """CIK by current ticker for each symbol's latest security, else by exact normalized name."""
    out = frame.copy()
    by_ticker = out["symbol"].map(ticker_ciks).where(out["security"] == out["symbol"])
    by_name = out["name"].map(normalize_name).map(name_ciks)
    out["cik"] = by_ticker.fillna(by_name).astype("Int64")
    return out


def listed_on(listings: pd.DataFrame, day: pd.Timestamp) -> pd.Index:
    """Symbols of operating stocks on a listed exchange whose dates span `day`: Tiingo's, plus Alpha Vantage's for
    symbols Tiingo lacks (Alpha Vantage's own dates overcount, so it never overrides Tiingo)."""
    tiingo_symbols = set(listings.loc[listings["source"] == "tiingo", "symbol"])
    extra = (listings["source"] == "alphavantage") & ~listings["symbol"].isin(tiingo_symbols)
    dated = listings[(listings["source"] == "tiingo") | extra].dropna(subset=["start"])
    dated = dated[dated["exchange"].isin(LISTED_EXCHANGES) & dated["name"].map(is_operating)
                  & dated["asset_type"].eq("Stock")]
    alive = (dated["start"] <= day) & (dated["end"].fillna(STILL_LISTED_FROM) >= day)
    return pd.Index(dated.loc[alive, "symbol"].unique())


def coverage_by_year(runs: pd.DataFrame, listings: pd.DataFrame, still_listed: set,
                     years=range(2005, 2016)) -> pd.DataFrame:
    """Jan 2 snapshot per year: listed operating stocks, how many have WIKI prices, and how the rest split."""
    rows = []
    for year in years:
        day = pd.Timestamp(year, 1, 2)
        listed = set(listed_on(listings, day))
        in_wiki = set(runs.loc[(runs["first_day"] <= day) & (runs["last_day"] >= day), "symbol"])
        missing = listed - in_wiki
        rows.append({"year": year, "listed": len(listed), "wiki": len(listed & in_wiki),
                     "wiki_only": len(in_wiki - listed), "missing_still_listed": len(missing & still_listed),
                     "missing_gone": len(missing - still_listed)})
    return pd.DataFrame(rows)


def build(data_dir: str) -> Dict[str, pd.DataFrame]:
    raw = os.path.join(data_dir, "raw")
    alpaca = alpaca_listings(os.path.join(raw, "alpaca", "assets.csv"))
    listings = plain_symbols(pd.concat([
        alphavantage_listings(os.path.join(raw, "alphavantage")),
        tiingo_listings(os.path.join(raw, "tiingo", "supported_tickers.zip")),
        alpaca,
    ], ignore_index=True))
    # Tiingo has no names; borrow the symbol's Alpha Vantage / Alpaca name so the fund filter can see it.
    fallback_names = listings.dropna(subset=["name"]).drop_duplicates("symbol").set_index("symbol")["name"]
    listings["name"] = listings["name"].fillna(listings["symbol"].map(fallback_names))

    runs = label_reused(trading_runs(wiki_trading_days(os.path.join(raw, "wiki", "WIKI_PRICES.zip"))))
    runs = attach_names(runs, listings)
    runs = attach_ciks(runs, sec_ticker_ciks(os.path.join(raw, "sec", "company_tickers.json")),
                       sec_name_ciks(os.path.join(raw, "sec", "cik-lookup-data.txt")))

    still_listed = set(alpaca.loc[alpaca["status"] == "active", "symbol"])
    coverage = coverage_by_year(runs[runs["operating"]], listings, still_listed)
    return {"wiki_runs": runs, "listings": listings, "coverage": coverage}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    out = build(args.data_dir)
    out["wiki_runs"].to_pickle(os.path.join(args.data_dir, "wiki_runs.pkl"))
    out["listings"].to_pickle(os.path.join(args.data_dir, "listings.pkl"))
    out["coverage"].to_csv(os.path.join(args.data_dir, "coverage.csv"), index=False)
    runs = out["wiki_runs"]
    print(f"wiki runs {len(runs)} over {runs['symbol'].nunique()} tickers; reused {(runs['security'] != runs['symbol']).sum()}; "
          f"named {runs['name'].notna().mean():.0%}; with CIK {runs['cik'].notna().mean():.0%}; "
          f"non-operating {(~runs['operating']).sum()}")
    print(out["coverage"].to_string(index=False))


if __name__ == "__main__":
    run(parse_args())
