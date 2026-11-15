"""Phase 4 of research/docs/historical_data_2005_2019_plan.md: one consistent daily table from WIKI, yfinance and
Alpaca.

Usage (from the repo root, after securities.py and fill_prices.py):

    python -m alpha_tech_tracker.research.historical.normalize

Writes market_data/historical/daily/<year>.pkl, long rows: symbol, day, open, high, low, close, volume, raw_close,
source. open/high/low/close/volume are split + dividend adjusted on Alpaca's (today's) basis; raw_close is the
unadjusted close for market cap.

- Sources by date: WIKI and yfinance through WIKI_LAST_DAY, Alpaca from ALPACA_FIRST_DAY. For one symbol, WIKI wins
  over yfinance; yfinance fills only days WIKI lacks (names WIKI never had, and stale WIKI tickers after their last
  WIKI day). A yfinance series that repeats a WIKI series under another ticker (Yahoo files a renamed company's
  history under its new ticker) has the duplicated days dropped.
- Rows with no volume are dropped: Alpaca pads dead tickers with flat zero-volume bars (MON, SHLD) and WIKI has
  zero-volume junk rows (DELL 2015). Days on which almost no stock traded are dropped too (WIKI's TAM has bars dated
  on market holidays).
- Alpaca files a company's history under its current ticker, and sometimes under its old one too (AmerisourceBergen
  is in both COR and ABC for 2017). Alpaca series that repeat another's (day, volume) pairs lose the repeated days
  from the shorter series.
- Older sources are rescaled onto Alpaca's basis per symbol by the ratio of adjusted closes on their shared days in
  Jan-Mar 2016 (factor 1 when there is no overlap, e.g. a company that died before 2016). When the two disagree on
  daily returns there (GOLD was Randgold in WIKI and someone else in Alpaca), they are different companies: the
  older part becomes symbol~<its last year> and is not rescaled.
- Symbols are then split into separate companies with securities.trading_runs on the joined series, so a ticker
  that changed owners across the handover becomes symbol~YYYY + symbol.
"""
import argparse
import glob
import os
from typing import Iterable, Optional, Tuple

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.historical import securities as sec

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "market_data", "historical")
WIKI_LAST_DAY = sec.WIKI_LAST_DAY
ALPACA_FIRST_DAY = pd.Timestamp("2016-01-01")
OVERLAP_END = pd.Timestamp("2016-03-31")
HANDOVER_RETURN_TOLERANCE = 0.005
HANDOVER_BAD_SHARE = 0.2
HANDOVER_MIN_DAYS = 10
FIRST_DAY = pd.Timestamp("2003-01-01")
DUPLICATE_SHARE = 0.5
DUPLICATE_MIN_DAYS = 20
RETURN_DUPLICATE_TOLERANCE = 0.0005
RETURN_DUPLICATE_SHARE = 0.8
RETURN_DUPLICATE_MIN_MOVE = 0.002
PRICE_TICK = 0.015
BENCHMARKS = ["SPY", "QQQ"]
MIN_SYMBOLS_OPEN = 100
COLUMNS = ["symbol", "day", "open", "high", "low", "close", "volume", "raw_close", "source"]
PRICE_COLUMNS = ["open", "high", "low", "close"]


def wiki_rows(zip_path: str, last_day: pd.Timestamp = OVERLAP_END) -> pd.DataFrame:
    """WIKI through March 2016 (the extra quarter is only for matching and rescaling onto Alpaca)."""
    cols = ["ticker", "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume", "close"]
    frames = []
    for chunk in pd.read_csv(zip_path, usecols=cols, chunksize=sec.WIKI_CHUNK_ROWS, **sec.TEXT_SAFE):
        day = pd.to_datetime(chunk["date"])
        keep = (day >= FIRST_DAY) & (day <= last_day)
        c = chunk[keep]
        frames.append(pd.DataFrame({
            "symbol": c["ticker"].str.upper(), "day": day[keep], "open": c["adj_open"], "high": c["adj_high"],
            "low": c["adj_low"], "close": c["adj_close"], "volume": c["adj_volume"], "raw_close": c["close"],
            "source": "wiki"}))
    return pd.concat(frames, ignore_index=True)


def yfinance_rows(raw: pd.DataFrame, alpaca: pd.DataFrame) -> pd.DataFrame:
    """yfinance long rows -> adjusted OHLC (scaled by adj_close / close) and a rebuilt raw close.

    yfinance's close is split-adjusted to today. raw = close x splits between the day and Jan 2016 (from yfinance's
    split column) x splits since Jan 2016 (Alpaca's raw close / yfinance's close on their shared January days)."""
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    y = raw.sort_values(["symbol", "day"]).reset_index(drop=True)
    scale = y["adj_close"] / y["close"]
    out = pd.DataFrame({"symbol": y["symbol"], "day": y["day"], "volume": y["volume"], "source": "yfinance"})
    for col in PRICE_COLUMNS:
        out[col] = y[col] * scale
    split = y["splits"].where(y["splits"] > 0, 1.0)
    # splits on later days, within this download: reverse cumulative product, excluding the day itself
    later = split.groupby(y["symbol"]).transform(lambda s: s[::-1].cumprod()[::-1].shift(-1, fill_value=1.0))
    since_2016 = _splits_since_handover(y, alpaca)
    out["raw_close"] = y["close"] * later * y["symbol"].map(since_2016).fillna(1.0)
    return out[COLUMNS]


def _splits_since_handover(yf_rows: pd.DataFrame, alpaca: pd.DataFrame) -> pd.Series:
    if alpaca.empty:
        return pd.Series(dtype=float)
    jan = yf_rows[(yf_rows["day"] >= ALPACA_FIRST_DAY) & (yf_rows["day"] <= OVERLAP_END)]
    a = alpaca[(alpaca["day"] >= ALPACA_FIRST_DAY) & (alpaca["day"] <= OVERLAP_END)]
    both = jan.merge(a[["symbol", "day", "raw_close"]], on=["symbol", "day"])
    return (both["raw_close"] / both["close"]).groupby(both["symbol"]).median()


def alpaca_rows(folder: str) -> pd.DataFrame:
    paths = sorted(glob.glob(os.path.join(folder, "batch_*.pkl")))
    if not paths:
        return pd.DataFrame(columns=COLUMNS)
    rows = pd.concat([pd.read_pickle(p) for p in paths], ignore_index=True)
    rows["source"] = "alpaca"
    return rows[COLUMNS]


def self_duplicate_pairs(rows: pd.DataFrame, share: float = DUPLICATE_SHARE,
                         min_days: int = DUPLICATE_MIN_DAYS) -> pd.DataFrame:
    """Within one source, (symbol, other) pairs where `symbol` is the shorter series and repeats `other`'s
    (day, volume) pairs on at least `share` of its days and at least `min_days` days: one company, two tickers."""
    empty = pd.DataFrame(columns=["symbol", "other"])
    if rows.empty:
        return empty
    key = ["day", "vol"]
    r = rows.assign(vol=rows["volume"].round())
    unique_key = r.drop_duplicates(key + ["symbol"])
    shared = unique_key[unique_key.duplicated(key, keep=False)]
    pairs = shared.merge(shared[key + ["symbol"]].rename(columns={"symbol": "other"}), on=key)
    pairs = pairs[pairs["symbol"] != pairs["other"]]
    if pairs.empty:
        return empty
    sizes = r.groupby("symbol").size()
    counts = pairs.groupby(["symbol", "other"]).size().rename("hits").reset_index()
    counts["days"] = counts["symbol"].map(sizes)
    counts["other_days"] = counts["other"].map(sizes)
    shorter = (counts["days"] < counts["other_days"]) | \
        ((counts["days"] == counts["other_days"]) & (counts["symbol"] > counts["other"]))
    dup = counts[(counts["hits"] >= share * counts["days"]) & (counts["hits"] >= min_days) & shorter]
    return dup[["symbol", "other"]].reset_index(drop=True)


def drop_self_duplicates(rows: pd.DataFrame, share: float = DUPLICATE_SHARE,
                         min_days: int = DUPLICATE_MIN_DAYS, dup: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Drop the shorter series' days that repeat its longer twin (see self_duplicate_pairs)."""
    dup = self_duplicate_pairs(rows, share, min_days) if dup is None else dup
    if dup.empty:
        return rows
    key = ["day", "vol"]
    r = rows.assign(vol=rows["volume"].round())
    twin_days = r[key + ["symbol"]].rename(columns={"symbol": "other"})
    pairs = r[key + ["symbol"]].merge(dup, on="symbol").merge(twin_days, on=key + ["other"])
    drop = pairs[["symbol", "day"]].drop_duplicates()
    print(f"dropping {len(drop)} duplicated days from {dup['symbol'].nunique()} series, e.g. "
          f"{dup[['symbol', 'other']].values.tolist()[:10]}", flush=True)
    marked = rows.merge(drop.assign(_dup=True), on=["symbol", "day"], how="left")
    return marked[marked["_dup"].isna()].drop(columns="_dup").reset_index(drop=True)


def handover_mismatches(older: pd.DataFrame, newer: pd.DataFrame, tolerance: float = HANDOVER_RETURN_TOLERANCE,
                        bad_share: float = HANDOVER_BAD_SHARE, min_days: int = HANDOVER_MIN_DAYS) -> set:
    """Symbols whose older and newer daily returns disagree on their shared days: different companies."""
    def returns(rows):
        return rows.pivot_table(index="day", columns="symbol", values="close").pct_change(fill_method=None)

    o, n = returns(older), returns(newer)
    symbols, days = o.columns.intersection(n.columns), o.index.intersection(n.index)
    o, n = o.loc[days, symbols], n.loc[days, symbols]
    both = o.notna() & n.notna()
    bad = (((o - n).abs() > tolerance) & both).sum()
    shared = both.sum()
    return set(shared.index[(shared >= min_days) & (bad > bad_share * shared)])


def split_mismatched(older: pd.DataFrame, mismatched: set) -> pd.DataFrame:
    """Relabel the older rows of mismatched symbols as symbol~<last year>, so they never join the newer series."""
    out = older.copy()
    mask = out["symbol"].isin(mismatched) & (out["day"] <= WIKI_LAST_DAY)
    last_year = out[mask].groupby("symbol")["day"].transform("max").dt.year.astype(str)
    out.loc[mask, "symbol"] = out.loc[mask, "symbol"] + "~" + last_year
    return out


def drop_duplicate_histories(yf: pd.DataFrame, wiki: pd.DataFrame, share: float = DUPLICATE_SHARE) -> pd.DataFrame:
    """Drop yfinance days that repeat a WIKI series under another ticker, matched on (day, rounded volume)."""
    if yf.empty or wiki.empty:
        return yf
    key = ["day", "vol"]
    w = wiki[wiki["volume"] > 0].assign(vol=wiki["volume"].round()).drop_duplicates(key, keep=False)
    y = yf.assign(vol=yf["volume"].round())
    hits = y[y["volume"] > 0].merge(w[key + ["symbol"]].rename(columns={"symbol": "wiki_symbol"}), on=key)
    hits = hits[hits["symbol"] != hits["wiki_symbol"]]
    counts = hits.groupby(["symbol", "wiki_symbol"]).size().rename("hits").reset_index()
    counts["days"] = counts["symbol"].map(y.groupby("symbol").size())
    dup = counts[counts["hits"] >= share * counts["days"]]
    if dup.empty:
        return yf
    wiki_days = wiki[wiki["symbol"].isin(dup["wiki_symbol"])][["symbol", "day"]]
    drop = dup[["symbol", "wiki_symbol"]].merge(wiki_days.rename(columns={"symbol": "wiki_symbol"}), on="wiki_symbol")
    marked = yf.merge(drop[["symbol", "day"]].drop_duplicates().assign(_dup=True), on=["symbol", "day"], how="left")
    print(f"dropping duplicated yfinance history: {dup[['symbol', 'wiki_symbol']].values.tolist()[:20]}", flush=True)
    return marked[marked["_dup"].isna()].drop(columns="_dup").reset_index(drop=True)


def _yearly_return_matches(rows: pd.DataFrame, tolerance: float, min_move: float,
                           prefilter: float) -> pd.DataFrame:
    """Per year, for security pairs whose daily returns look alike (cosine above `prefilter`): days where either
    moved more than `min_move`, and how many of those the two returns agree within `tolerance`, or within
    PRICE_TICK of the day's traded price when that is wider (two copies of a $7 stock rounded to the cent differ by
    more than 5 bp)."""
    out = []
    for year, part in rows.groupby(rows["day"].dt.year):
        r = part.pivot_table(index="day", columns="symbol", values="close").pct_change(fill_method=None)
        r = r.loc[:, r.notna().sum() >= 2]
        if r.shape[1] < 2:
            continue
        traded = part.pivot_table(index="day", columns="symbol", values="raw_close").reindex_like(r)
        x = r.fillna(0.0).values
        x = x / (np.linalg.norm(x, axis=0) + 1e-12)
        cosine = np.triu(x.T @ x, k=1)
        for a, b in zip(*np.where(cosine > prefilter)):
            ra, rb = r.iloc[:, a], r.iloc[:, b]
            moved = ra.notna() & rb.notna() & ((ra.abs() > min_move) | (rb.abs() > min_move))
            price = np.fmin(traded.iloc[:, a], traded.iloc[:, b])[moved]
            allowed = np.maximum(tolerance, PRICE_TICK / price.where(price > 0)).fillna(tolerance)
            out.append((r.columns[a], r.columns[b], year, int(moved.sum()),
                        int(((ra[moved] - rb[moved]).abs() < allowed).sum())))
    return pd.DataFrame(out, columns=["symbol", "other", "year", "days", "matches"])


def return_duplicate_years(rows: pd.DataFrame, tolerance: float = RETURN_DUPLICATE_TOLERANCE,
                           share: float = RETURN_DUPLICATE_SHARE, min_days: int = DUPLICATE_MIN_DAYS,
                           min_move: float = RETURN_DUPLICATE_MIN_MOVE, prefilter: float = 0.9) -> pd.DataFrame:
    """(symbol, other, year) where the two tickers carry one company, whatever the source or price basis: their
    daily returns agree within `tolerance` on at least `share` of the days either moved that year (SWHC and SWBI,
    PCLN and BKNG; TRUE before TrueCar listed in 2014, where WIKI repeats ON). Share classes of one company (GOOG
    and GOOGL, FOX and FOXA) agree on a third of those days at most."""
    matches = _yearly_return_matches(rows, tolerance, min_move, prefilter)
    if matches.empty:
        return pd.DataFrame(columns=["symbol", "other", "year"])
    dup = matches[(matches["days"] >= min_days) & (matches["matches"] >= share * matches["days"])]
    return dup[["symbol", "other", "year"]].reset_index(drop=True)


def drop_return_duplicates(rows: pd.DataFrame, dup_years: pd.DataFrame,
                           listed_from: Optional[pd.Series] = None, keep: Iterable[str] = ()) -> pd.DataFrame:
    """Per duplicate pair, drop one series' shared days in the duplicated years. The one that loses them: never a
    symbol in `keep` (benchmarks), else the one that ends first, then the one with fewer days, then the one listed
    later (`listed_from`: symbol -> first listing day), so the copy that carries on keeps its history."""
    if dup_years.empty:
        return rows
    listed_from = listed_from if listed_from is not None else pd.Series(dtype="datetime64[ns]")
    keep = set(keep)
    spans = rows.groupby("symbol")["day"].agg(["max", "size"])
    days = rows.groupby("symbol")["day"].apply(set)

    def loses_first(s):
        start = listed_from.get(s, pd.NaT)
        return (s in keep, spans.at[s, "max"], spans.at[s, "size"],
                -(start.value if pd.notna(start) else pd.Timestamp.min.value), s)

    drop = []
    for (a, b), g in dup_years.groupby(["symbol", "other"]):
        loser = min((a, b), key=loses_first) if not ({a, b} <= keep) else None
        if loser is None:
            continue
        winner = b if loser == a else a
        years = set(g["year"])
        drop += [(loser, d) for d in days[loser] & days[winner] if d.year in years]
    drop = pd.DataFrame(drop, columns=["symbol", "day"]).drop_duplicates()
    if drop.empty:
        return rows
    print(f"dropping {len(drop)} days repeating another ticker's returns from {drop['symbol'].nunique()} series, "
          f"e.g. {dup_years[['symbol', 'other']].drop_duplicates().values.tolist()[:10]}", flush=True)
    marked = rows.merge(drop.assign(_dup=True), on=["symbol", "day"], how="left")
    return marked[marked["_dup"].isna()].drop(columns="_dup").reset_index(drop=True)


def combine_pre_handover(wiki: pd.DataFrame, yf: pd.DataFrame) -> pd.DataFrame:
    """WIKI wins; yfinance adds only (symbol, day) pairs after the symbol's last WIKI day, or symbols WIKI lacks."""
    last_wiki = wiki.groupby("symbol")["day"].max()
    after = yf["day"] > yf["symbol"].map(last_wiki).fillna(pd.Timestamp.min)
    return pd.concat([wiki, yf[after]], ignore_index=True)


def rescale_to(older: pd.DataFrame, newer: pd.DataFrame) -> pd.DataFrame:
    """Scale older prices per symbol by median(newer close / older close) over their shared days."""
    shared = older[["symbol", "day", "close"]].merge(newer[["symbol", "day", "close"]], on=["symbol", "day"],
                                                     suffixes=("_old", "_new"))
    ratio = (shared["close_new"] / shared["close_old"]).groupby(shared["symbol"]).median()
    factor = older["symbol"].map(ratio).fillna(1.0)
    out = older.copy()
    for col in PRICE_COLUMNS:
        out[col] = out[col] * factor
    out["volume"] = out["volume"] / factor.where(factor > 0, 1.0)
    return out


def drop_closed_days(rows: pd.DataFrame, min_symbols: int = MIN_SYMBOLS_OPEN) -> pd.DataFrame:
    """Drop days on which fewer than min_symbols traded: the market was closed and the rows are junk (WIKI's TAM has
    48 bars dated on holidays such as 2006-01-02, which would add a day with no price for any other stock)."""
    counts = rows.groupby("day")["symbol"].transform("size")
    return rows[counts >= min_symbols]


def assign_securities(rows: pd.DataFrame) -> pd.DataFrame:
    """Relabel symbols as symbol~YYYY for earlier companies that used the ticker (see securities.trading_runs)."""
    runs = sec.label_reused(sec.trading_runs(rows[["symbol", "day", "close"]]))
    runs = runs[runs["security"] != runs["symbol"]]
    if runs.empty:
        return rows
    out = rows.copy()
    for r in runs.itertuples():
        mask = (out["symbol"] == r.symbol) & (out["day"] >= r.first_day) & (out["day"] <= r.last_day)
        out.loc[mask, "symbol"] = r.security
    return out


def build(data_dir: str, wiki: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """The combined daily rows, and the (symbol, other) ticker pairs found to be one company in Alpaca."""
    raw = os.path.join(data_dir, "raw")
    alpaca = alpaca_rows(os.path.join(data_dir, "prices", "alpaca"))
    wiki = wiki if wiki is not None else wiki_rows(os.path.join(raw, "wiki", "WIKI_PRICES.zip"))
    yf_paths = sorted(glob.glob(os.path.join(data_dir, "prices", "yfinance", "batch_*.pkl")))
    yf_raw = pd.concat([pd.read_pickle(p) for p in yf_paths], ignore_index=True) if yf_paths else pd.DataFrame()
    yf = yfinance_rows(yf_raw, alpaca)

    alpaca, wiki, yf = (_real_trades(f) for f in (alpaca, wiki, yf))
    aliases = self_duplicate_pairs(alpaca)
    alpaca = drop_self_duplicates(alpaca, dup=aliases)
    yf = drop_duplicate_histories(yf, wiki)
    pre = combine_pre_handover(wiki, yf)
    window = (alpaca["day"] >= ALPACA_FIRST_DAY) & (alpaca["day"] <= OVERLAP_END)
    mismatched = handover_mismatches(pre[pre["day"] >= ALPACA_FIRST_DAY], alpaca[window])
    print(f"{len(mismatched)} symbols are a different company before and after the handover, e.g. "
          f"{sorted(mismatched)[:15]}", flush=True)
    pre = split_mismatched(pre[~(pre["symbol"].isin(mismatched) & (pre["day"] > WIKI_LAST_DAY))], mismatched)
    pre = rescale_to(pre, alpaca)
    pre = pre[pre["day"] <= WIKI_LAST_DAY]
    post = alpaca[alpaca["day"] >= ALPACA_FIRST_DAY]
    rows = pd.concat([pre, post], ignore_index=True)
    rows = drop_closed_days(rows[rows["symbol"].str.match(sec.SYMBOL_RE, na=False)])
    rows = assign_securities(rows.sort_values(["symbol", "day"]).reset_index(drop=True))
    dup_years = return_duplicate_years(rows)
    rows = drop_return_duplicates(rows, dup_years, _tiingo_start(raw), BENCHMARKS)
    twins = dup_years[["symbol", "other"]].drop_duplicates()
    aliases = pd.concat([aliases, twins], ignore_index=True).drop_duplicates()
    return rows, aliases


def _tiingo_start(raw_dir: str) -> pd.Series:
    """symbol -> first listing day in Tiingo's ticker list (empty when it has not been downloaded)."""
    path = os.path.join(raw_dir, "tiingo", "supported_tickers.zip")
    if not os.path.exists(path):
        return pd.Series(dtype="datetime64[ns]")
    listings = sec.tiingo_listings(path).dropna(subset=["start"])
    return listings.groupby("symbol")["start"].min()


def _real_trades(rows: pd.DataFrame) -> pd.DataFrame:
    ok = (rows["volume"] > 0) & np.isfinite(rows["close"].astype(float)) & (rows["close"] > 0)
    return rows[ok].reset_index(drop=True)


def write_years(rows: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for year, part in rows.groupby(rows["day"].dt.year):
        part.reset_index(drop=True).to_pickle(os.path.join(out_dir, f"{year}.pkl"))


def load_years(daily_dir: str, first_year: int, last_year: int) -> pd.DataFrame:
    paths = [os.path.join(daily_dir, f"{y}.pkl") for y in range(first_year, last_year + 1)]
    return pd.concat([pd.read_pickle(p) for p in paths if os.path.exists(p)], ignore_index=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    rows, aliases = build(args.data_dir)
    write_years(rows, os.path.join(args.data_dir, "daily"))
    aliases.to_csv(os.path.join(args.data_dir, "aliases.csv"), index=False)
    by_year = rows.groupby([rows["day"].dt.year, "source"])["symbol"].nunique().unstack(fill_value=0)
    earlier = rows.loc[rows["symbol"].str.contains("~", regex=False), "symbol"].nunique()
    print(f"{len(rows)} rows, {rows['symbol'].nunique()} securities ({earlier} earlier owners of a reused ticker)")
    print(by_year.to_string())


if __name__ == "__main__":
    run(parse_args())
