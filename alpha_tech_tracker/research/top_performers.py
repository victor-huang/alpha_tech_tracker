"""Rank the best-performing US stocks per month, quarter or year, split by market-cap tier.

Usage (from the repo root, with ALPACA_API_KEY / ALPACA_SECRET_KEY set):

    # most recently completed month / quarter / year
    python -m alpha_tech_tracker.research.top_performers --period month
    python -m alpha_tech_tracker.research.top_performers --period quarter
    python -m alpha_tech_tracker.research.top_performers --period year

    # a range of periods, plus the in-progress one (MTD / QTD / YTD)
    python -m alpha_tech_tracker.research.top_performers --period year --start 2020-01-01 --include-current

Returns are split- and dividend-adjusted, from the last close before the period to the last close in it.
Tier = market value on the last trading day before the period: unadjusted close x shares outstanding.
Rows carry data-quality flags (ticker reuse, bankruptcy splices, share-count jumps) for manual review.
"""
import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "top_performers_output")
DEFAULT_CACHE_DIR = os.path.join(REPO_ROOT, "market_data", "top_performers")
LISTED_EXCHANGES = ("NYSE", "NASDAQ", "AMEX", "ARCA", "BATS")
NON_OPERATING_NAME_RE = re.compile(
    r"\b(ETF|ETN|Fund|ProShares|Direxion|Grayscale|2X|3X|Leveraged|Inverse|Bull|Bear|iShares|SPDR|"
    r"Notes|Warrants?|Rights|Units?|Acquisition Corp|Preferred)\b",
    re.I,
)
BAR_BATCH_SIZE = 200
SIP_DELAY = timedelta(minutes=16)
BAR_FETCH_ATTEMPTS = 2
BAR_RETRY_SECONDS = 5
PARTITION_OVERLAP_DAYS = 14
SHARES_CACHE_TTL_DAYS = 20
SHARES_WINDOW_BEFORE_DAYS = 120
SHARES_WINDOW_AFTER_DAYS = 60
MAX_TRADING_GAP_DAYS = 10
SHARE_JUMP_RATIO = 3.0
DAILY_JUMP_UP = 3.0
DAILY_JUMP_DOWN = -0.8
RATIO_CHANGE_MOVE = 0.4
RATIO_CHANGE_MAX_VOLUME_RATIO = 1.5


@dataclass(frozen=True)
class Tier:
    name: str
    low: float
    high: float


TIERS = (
    Tier("Large", 10e9, float("inf")),
    Tier("Mid", 2e9, 10e9),
    Tier("Small", 300e6, 2e9),
)


@dataclass(frozen=True)
class PeriodWindow:
    label: str
    start: date
    end: date
    is_complete: bool


def period_windows(period: str, first: date, last: date, today: date, include_current: bool) -> List[PeriodWindow]:
    """Calendar periods whose start falls in [first, last]; the in-progress one only when include_current."""
    windows = []
    cursor = _period_start(period, first)
    while cursor <= last:
        nxt = _next_period_start(period, cursor)
        end = nxt - timedelta(days=1)
        complete = end < today
        if complete or (include_current and cursor <= today):
            windows.append(PeriodWindow(_period_label(period, cursor), cursor, min(end, today), complete))
        cursor = nxt
    return windows


def _period_start(period: str, d: date) -> date:
    if period == "month":
        return date(d.year, d.month, 1)
    if period == "quarter":
        return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    if period == "year":
        return date(d.year, 1, 1)
    raise ValueError(f"unknown period {period}")


def _next_period_start(period: str, start: date) -> date:
    months = {"month": 1, "quarter": 3, "year": 12}[period]
    total = start.month - 1 + months
    return date(start.year + total // 12, total % 12 + 1, 1)


def _period_label(period: str, start: date) -> str:
    if period == "month":
        return start.strftime("%Y-%m")
    if period == "quarter":
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    return str(start.year)


def default_range(period: str, today: date) -> Tuple[date, date]:
    """The most recently completed period."""
    current = _period_start(period, today)
    previous = _period_start(period, current - timedelta(days=1))
    return previous, previous


def tier_for(market_cap: Optional[float]) -> Optional[str]:
    if market_cap is None:
        return None
    for tier in TIERS:
        if tier.low <= market_cap < tier.high:
            return tier.name
    return None


def compute_period_returns(
    close: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    window: PeriodWindow,
    min_price: float,
    min_dollar_volume: float,
    min_coverage: float,
) -> pd.DataFrame:
    """Per-symbol return for one window, after price / liquidity / coverage filters, best first."""
    before = close[close.index < pd.Timestamp(window.start)]
    inside = close[(close.index >= pd.Timestamp(window.start)) & (close.index <= pd.Timestamp(window.end))]
    if before.empty or inside.empty:
        return pd.DataFrame(columns=["symbol", "ret", "base_date", "base_close", "median_dollar_volume"])
    base = before.ffill().iloc[-1]
    final = inside.ffill().iloc[-1]
    ret = final / base - 1
    inside_dv = dollar_volume.reindex(inside.index)
    median_dv = inside_dv.median()
    coverage = inside.notna().sum() / len(inside)
    keep = (
        ret.notna()
        & (base >= min_price)
        & (median_dv.reindex(ret.index).fillna(0) >= min_dollar_volume)
        & (coverage >= min_coverage)
    )
    out = pd.DataFrame({
        "symbol": ret.index[keep],
        "ret": ret[keep].values,
        "base_date": before.index[-1].date(),
        "base_close": base[keep].values,
        "median_dollar_volume": median_dv.reindex(ret.index)[keep].values,
    })
    return out.sort_values("ret", ascending=False).reset_index(drop=True)


def market_cap_at(shares: Optional[pd.Series], day: date, raw_close: Optional[float]) -> Optional[float]:
    """Median reported share count around `day` times the unadjusted close."""
    if shares is None or shares.empty or raw_close is None:
        return None
    t = pd.Timestamp(day)
    window = shares[(shares.index >= t - pd.Timedelta(days=SHARES_WINDOW_BEFORE_DAYS))
                    & (shares.index <= t + pd.Timedelta(days=SHARES_WINDOW_AFTER_DAYS))]
    if window.empty:
        earlier = shares[shares.index <= t]
        window = earlier.iloc[-3:] if not earlier.empty else shares.iloc[:3]
    return float(window.median()) * raw_close


def quality_flags(prices: pd.Series, shares: Optional[pd.Series], window: PeriodWindow,
                  dollar_volume: Optional[pd.Series] = None) -> List[str]:
    """Signals that the return may be an artifact rather than a real move; flagged rows need a manual check."""
    flags = []
    t0 = pd.Timestamp(window.start) - pd.Timedelta(days=10)
    t1 = pd.Timestamp(window.end)
    span = prices[(prices.index >= t0) & (prices.index <= t1)].dropna()
    if len(span) > 1:
        if span.index.to_series().diff().dt.days.max() > MAX_TRADING_GAP_DAYS:
            flags.append("trading_gap")
        daily = span.pct_change().dropna()
        if (daily > DAILY_JUMP_UP).any() or (daily < DAILY_JUMP_DOWN).any():
            flags.append("price_jump")
        if dollar_volume is not None and _has_quiet_jump(prices, dollar_volume, daily.index):
            flags.append("ratio_change")
    if shares is not None and not shares.empty:
        around = shares[(shares.index >= t0 - pd.Timedelta(days=SHARES_WINDOW_BEFORE_DAYS)) & (shares.index <= t1)]
        if len(around) > 1 and around.min() > 0 and around.max() / around.min() > SHARE_JUMP_RATIO:
            flags.append("share_count_jump")
    return flags


def _has_quiet_jump(prices: pd.Series, dollar_volume: pd.Series, days: pd.Index) -> bool:
    """A large one-day move on no volume spike: an ADR-ratio change or unadjusted split, not real trading."""
    share_volume = (dollar_volume / prices).reindex(prices.index)
    baseline = share_volume.rolling(20, min_periods=10).mean().shift(1)
    move = prices.pct_change(fill_method=None)
    for day in days:
        if abs(move.get(day, 0)) >= RATIO_CHANGE_MOVE and share_volume.get(day, np.nan) < \
                RATIO_CHANGE_MAX_VOLUME_RATIO * baseline.get(day, np.nan):
            return True
    return False


class SharesCache:
    """Disk-backed cache of yfinance share-count history, with backoff on rate limits."""

    def __init__(self, path: str, fetcher: Optional[Callable[[str], Optional[pd.Series]]] = None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 5):
        self.path = path
        self.fetcher = fetcher or _fetch_shares_from_yfinance
        self.sleep = sleep
        self.max_retries = max_retries
        self._data = self._load()

    def _load(self) -> Dict[str, dict]:
        if os.path.exists(self.path):
            with open(self.path) as fh:
                return json.load(fh)
        return {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(self._data, fh)

    def get(self, symbol: str, today: date) -> Optional[pd.Series]:
        entry = self._data.get(symbol)
        if entry and (today - date.fromisoformat(entry["fetched"])).days <= SHARES_CACHE_TTL_DAYS:
            return _series_from_entry(entry)
        series = self._fetch_with_retry(symbol)
        if series is _RATE_LIMITED:
            return _series_from_entry(entry) if entry else None
        self._data[symbol] = {
            "fetched": today.isoformat(),
            "shares": {} if series is None else {d.date().isoformat(): int(v) for d, v in series.items()},
        }
        return series

    def _fetch_with_retry(self, symbol: str):
        for attempt in range(self.max_retries):
            try:
                return self.fetcher(symbol)
            except Exception as exc:  # yfinance raises several error types for throttling
                if not _is_rate_limit(exc):
                    return None
                self.sleep(30 * (attempt + 1))
        return _RATE_LIMITED


_RATE_LIMITED = object()


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return "RateLimit" in text or "Too Many Requests" in text


def _series_from_entry(entry: dict) -> Optional[pd.Series]:
    if not entry["shares"]:
        return None
    s = pd.Series(entry["shares"], dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _fetch_shares_from_yfinance(symbol: str) -> Optional[pd.Series]:
    s = yf.Ticker(symbol).get_shares_full(start="2015-01-01")
    if s is None or len(s) == 0:
        return None
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s = s[~s.index.duplicated(keep="last")]
    return s.astype("float64").sort_index()


class AlpacaData:
    def __init__(self):
        key, secret = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
        self.trading = TradingClient(key, secret, paper=True, raw_data=True)
        self.data = StockHistoricalDataClient(key, secret)

    def listed_stocks(self) -> pd.DataFrame:
        assets = self.trading.get_all_assets(GetAssetsRequest(asset_class=AssetClass.US_EQUITY,
                                                              status=AssetStatus.ACTIVE))
        rows = [
            {"symbol": a["symbol"], "name": a["name"], "exchange": a["exchange"]}
            for a in assets
            if a["exchange"] in LISTED_EXCHANGES and a["tradable"] and "." not in a["symbol"]
            and "/" not in a["symbol"] and not NON_OPERATING_NAME_RE.search(a["name"] or "")
        ]
        return pd.DataFrame(rows).set_index("symbol")

    def daily_bars(self, symbols: List[str], start: date, end: date) -> pd.DataFrame:
        """Adjusted daily bars as long rows: symbol, timestamp, close, volume."""
        frames = []
        for i in range(0, len(symbols), BAR_BATCH_SIZE):
            req = StockBarsRequest(symbol_or_symbols=symbols[i:i + BAR_BATCH_SIZE], timeframe=TimeFrame.Day,
                                   start=datetime.combine(start, datetime.min.time()),
                                   end=sip_request_end(end, datetime.utcnow()),
                                   adjustment=Adjustment.ALL, feed=DataFeed.SIP)
            frames.append(self._fetch_batch(req, i))
        if not frames:
            return pd.DataFrame(columns=["symbol", "timestamp", "close", "volume"])
        return pd.concat(frames, ignore_index=True)

    def _fetch_batch(self, req: StockBarsRequest, i: int) -> pd.DataFrame:
        """One bar request, retried once; a batch that still fails raises instead of silently dropping its symbols."""
        for attempt in range(BAR_FETCH_ATTEMPTS):
            try:
                return self.data.get_stock_bars(req).df[["close", "volume"]].reset_index()
            except Exception as exc:
                print(f"bars batch {i} failed (attempt {attempt + 1}): {exc}", flush=True)
                if attempt + 1 == BAR_FETCH_ATTEMPTS:
                    raise RuntimeError(f"bars batch {i} failed after {BAR_FETCH_ATTEMPTS} attempts") from exc
                time.sleep(BAR_RETRY_SECONDS)

    def raw_closes(self, symbols: List[str], day: date) -> Dict[str, float]:
        out = {}
        for i in range(0, len(symbols), BAR_BATCH_SIZE):
            req = StockBarsRequest(symbol_or_symbols=symbols[i:i + BAR_BATCH_SIZE], timeframe=TimeFrame.Day,
                                   start=datetime.combine(day - timedelta(days=6), datetime.min.time()),
                                   end=datetime.combine(day + timedelta(days=1), datetime.min.time()),
                                   adjustment=Adjustment.RAW, feed=DataFeed.SIP)
            df = self.data.get_stock_bars(req).df.reset_index()
            for symbol, g in df.groupby("symbol"):
                out[symbol] = float(g.sort_values("timestamp")["close"].iloc[-1])
        return out


def sip_request_end(end: date, utc_now: datetime) -> datetime:
    """Exclusive request end (naive UTC) for daily bars through `end`, held back SIP_DELAY from now: the free
    subscription rejects any request that reaches into the most recent SIP data."""
    return min(datetime.combine(end + timedelta(days=1), datetime.min.time()), utc_now - SIP_DELAY)


def pivot_bars(bars: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Long bars -> wide (day x symbol) adjusted close and dollar volume."""
    if bars.empty:
        empty = pd.DataFrame(index=pd.DatetimeIndex([], name="day"))
        return empty, empty.copy()
    bars = bars.copy()
    bars["day"] = pd.to_datetime(pd.to_datetime(bars["timestamp"]).dt.tz_convert("America/New_York").dt.date)
    bars["dollar_volume"] = bars["close"] * bars["volume"]
    close = bars.pivot_table(index="day", columns="symbol", values="close")
    dollar_volume = bars.pivot_table(index="day", columns="symbol", values="dollar_volume")
    return close, dollar_volume


@dataclass
class BarPartition:
    month: date
    fetched_on: date
    symbols: List[str]
    close: pd.DataFrame
    dollar_volume: pd.DataFrame


class DailyBarCache:
    """Month-partitioned disk cache of adjusted daily bars.

    A partition holds one calendar month plus PARTITION_OVERLAP_DAYS before it, fetched in one request,
    so it is internally consistent. Adjusted history is rewritten by every later split or dividend, so
    partitions fetched on different days are chain-linked per symbol on that overlap when loaded.
    """

    def __init__(self, root: str, fetch_bars: Callable[[List[str], date, date], pd.DataFrame]):
        self.root = root
        self.fetch_bars = fetch_bars

    def load(self, symbols: List[str], start: date, end: date, today: date) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Wide close / dollar volume covering [start - overlap, end], consistently adjusted as of the newest data."""
        symbols = list(dict.fromkeys(symbols))
        months = _months_between(start, end)
        partitions = [self._partition(m, symbols, today) for m in months]
        close, dollar_volume = _stitch(partitions)
        wanted = [s for s in symbols if s in close.columns]
        return close[wanted], dollar_volume[wanted]

    def seed(self, bars: pd.DataFrame, fetched_on: date, symbols: List[str]) -> List[date]:
        """Split one consistent bulk download into partitions (skips months the bulk data cannot fully cover)."""
        close, dollar_volume = pivot_bars(bars)
        first_day, last_day = close.index.min().date(), close.index.max().date()
        written = []
        for month in _months_between(first_day, last_day):
            lo = month - timedelta(days=PARTITION_OVERLAP_DAYS)
            if lo < first_day:
                continue
            hi = pd.Timestamp(_month_end(month))
            mask = (close.index >= pd.Timestamp(lo)) & (close.index <= hi)
            self._save(BarPartition(month, fetched_on, list(symbols), close[mask], dollar_volume[mask]))
            written.append(month)
        return written

    def _partition(self, month: date, symbols: List[str], today: date) -> BarPartition:
        cached = self._read(month)
        if cached is None or not _is_fresh(cached, today):
            part = self._download(month, symbols, today)
        else:
            missing = sorted(set(symbols) - set(cached.symbols))
            if not missing:
                return cached
            extra = self._download(month, missing, today)
            part = BarPartition(
                cached.month, cached.fetched_on, sorted(set(cached.symbols) | set(missing)),
                cached.close.join(extra.close, how="outer"),
                cached.dollar_volume.join(extra.dollar_volume, how="outer"),
            )
        self._save(part)
        return part

    def _download(self, month: date, symbols: List[str], today: date) -> BarPartition:
        lo = month - timedelta(days=PARTITION_OVERLAP_DAYS)
        hi = min(_month_end(month), today)
        print(f"downloading {month:%Y-%m} for {len(symbols)} symbols", flush=True)
        close, dollar_volume = pivot_bars(self.fetch_bars(symbols, lo, hi))
        if close.empty:
            raise RuntimeError(f"no bars returned for {month:%Y-%m}; not caching an empty partition")
        return BarPartition(month, today, list(symbols), close, dollar_volume)

    def _path(self, month: date) -> str:
        return os.path.join(self.root, "daily_bars", f"{month:%Y-%m}.pkl")

    def _read(self, month: date) -> Optional[BarPartition]:
        path = self._path(month)
        return BarPartition(**pd.read_pickle(path)) if os.path.exists(path) else None

    def _save(self, part: BarPartition) -> None:
        os.makedirs(os.path.dirname(self._path(part.month)), exist_ok=True)
        pd.to_pickle(vars(part), self._path(part.month))


def _is_fresh(part: BarPartition, today: date) -> bool:
    """A month fetched after it ended is final; an in-progress month is only good for the day it was fetched."""
    return part.fetched_on > _month_end(part.month) or part.fetched_on >= today


def _month_end(month: date) -> date:
    return _next_period_start("month", month) - timedelta(days=1)


def _months_between(start: date, end: date) -> List[date]:
    months, cursor = [], date(start.year, start.month, 1)
    while cursor <= end:
        months.append(cursor)
        cursor = _next_period_start("month", cursor)
    return months


def _stitch(partitions: List[BarPartition]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Join partitions newest-first, rescaling each older one onto the newer one's adjustment basis."""
    closes, volumes = [], []
    newer = None
    for i in range(len(partitions) - 1, -1, -1):
        part = partitions[i]
        close = part.close if newer is None else part.close * _link_factors(part.close, newer)
        newer = close
        dollar_volume = part.dollar_volume
        if i > 0:
            close = close[close.index >= pd.Timestamp(part.month)]
            dollar_volume = dollar_volume[dollar_volume.index >= pd.Timestamp(part.month)]
        closes.append(close)
        volumes.append(dollar_volume)
    return pd.concat(closes[::-1]).sort_index(), pd.concat(volumes[::-1]).sort_index()


def _link_factors(older: pd.DataFrame, newer: pd.DataFrame) -> pd.Series:
    """Per-symbol ratio newer/older on their latest shared day; 1.0 where they share none."""
    days = older.index.intersection(newer.index)
    symbols = older.columns.intersection(newer.columns)
    if len(days) == 0 or len(symbols) == 0:
        return pd.Series(1.0, index=older.columns)
    ratio = (newer.loc[days, symbols] / older.loc[days, symbols]).ffill().iloc[-1]
    return ratio.reindex(older.columns).fillna(1.0)


def pick_top_by_tier(
    ranked: pd.DataFrame,
    window: PeriodWindow,
    top_n: int,
    shares_for: Callable[[str], Optional[pd.Series]],
    raw_closes_for: Callable[[List[str], date], Dict[str, float]],
    close: pd.DataFrame,
    names: pd.Series,
    dollar_volume: Optional[pd.DataFrame] = None,
    scan_batch: int = 120,
    max_scan: int = 3000,
) -> List[dict]:
    """Walk the ranked list best-first, sizing each stock, until every tier holds top_n."""
    picked = {tier.name: [] for tier in TIERS}
    pos = 0
    while pos < min(len(ranked), max_scan) and any(len(v) < top_n for v in picked.values()):
        chunk = ranked.iloc[pos:pos + scan_batch]
        pos += scan_batch
        base_day = chunk["base_date"].iloc[0]
        raws = raw_closes_for(chunk["symbol"].tolist(), base_day)
        for row in chunk.itertuples():
            shares = shares_for(row.symbol)
            mcap = market_cap_at(shares, base_day, raws.get(row.symbol))
            tier = tier_for(mcap)
            if tier is None or len(picked[tier]) >= top_n:
                continue
            picked[tier].append({
                "period": window.label,
                "complete": window.is_complete,
                "tier": tier,
                "rank": len(picked[tier]) + 1,
                "symbol": row.symbol,
                "name": names.get(row.symbol, ""),
                "return_pct": round(row.ret * 100, 1),
                "start_mcap_b": round(mcap / 1e9, 2),
                "median_dollar_volume_m": round(row.median_dollar_volume / 1e6, 1),
                "flags": ",".join(quality_flags(
                    close[row.symbol], shares, window,
                    None if dollar_volume is None else dollar_volume.get(row.symbol))),
            })
    return [r for tier in TIERS for r in picked[tier.name]]


def render_markdown(rows: pd.DataFrame, period: str, top_n: int) -> str:
    lines = [f"# Top {top_n} US stocks by {period}, per market-cap tier", ""]
    tier_heads = {"Large": "Large (>= $10B)", "Mid": "Mid ($2B-$10B)", "Small": "Small ($300M-$2B)"}
    for label, group in rows.groupby("period", sort=True):
        status = "" if group["complete"].all() else " (in progress)"
        lines += [f"## {label}{status}", "", "| # | " + " | ".join(tier_heads[t.name] for t in TIERS) + " |",
                  "| --- |" + " --- |" * len(TIERS)]
        for rank in range(1, top_n + 1):
            cells = []
            for tier in TIERS:
                hit = group[(group["tier"] == tier.name) & (group["rank"] == rank)]
                if hit.empty:
                    cells.append("")
                    continue
                r = hit.iloc[0]
                flag = f" [!{r['flags']}]" if r["flags"] else ""
                cells.append(f"{r['symbol']} {r['return_pct']:+.0f}% ({r['start_mcap_b']:.1f}B){flag}")
            lines.append(f"| {rank} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += ["Cells: ticker, period return, start-of-period market value. "
              "[!flags] = check by hand: trading_gap (ticker reuse), price_jump (bankruptcy/merger splice or a "
              "real one-day move), ratio_change (big move without a volume spike: ADR-ratio change or "
              "unadjusted split), share_count_jump (SPAC merger, restructuring, wrong share history).", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> str:
    today = args.today or date.today()
    if args.start:
        first, last = args.start, args.end or today
    else:
        first, last = default_range(args.period, today)
    windows = period_windows(args.period, first, last, today, args.include_current)
    if not windows:
        raise SystemExit("no complete periods in range; pass --include-current for the in-progress one")

    alpaca = AlpacaData()
    stocks = alpaca.listed_stocks()
    print(f"{len(stocks)} listed stocks; periods: {[w.label for w in windows]}", flush=True)
    bar_cache = DailyBarCache(args.cache_dir, alpaca.daily_bars)
    close, dollar_volume = bar_cache.load(stocks.index.tolist(), windows[0].start, windows[-1].end, today)

    shares_cache = SharesCache(os.path.join(args.cache_dir, "shares.json"))
    rows = []
    try:
        for window in windows:
            ranked = compute_period_returns(close, dollar_volume, window, args.min_price,
                                            args.min_dollar_volume, args.min_coverage)
            picked = pick_top_by_tier(ranked, window, args.top, lambda s: shares_cache.get(s, today),
                                      alpaca.raw_closes, close, stocks["name"], dollar_volume)
            print(f"{window.label}: {len(ranked)} eligible, picked {len(picked)}", flush=True)
            rows += picked
            shares_cache.save()
    finally:
        shares_cache.save()

    result = pd.DataFrame(rows)
    stem = f"{args.period}_{windows[0].label}_to_{windows[-1].label}"
    os.makedirs(args.out_dir, exist_ok=True)
    csv_path = os.path.join(args.out_dir, f"{stem}.csv")
    md_path = os.path.join(args.out_dir, f"{stem}.md")
    result.to_csv(csv_path, index=False)
    with open(md_path, "w") as fh:
        fh.write(render_markdown(result, args.period, args.top))
    print(f"wrote {csv_path}\nwrote {md_path}")
    return md_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--period", choices=["month", "quarter", "year"], required=True)
    p.add_argument("--start", type=date.fromisoformat, help="first period to include (any date inside it)")
    p.add_argument("--end", type=date.fromisoformat, help="last period to include (default: today)")
    p.add_argument("--include-current", action="store_true", help="add the in-progress period (MTD/QTD/YTD)")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--min-price", type=float, default=2.0)
    p.add_argument("--min-dollar-volume", type=float, default=2e6, help="median daily $ volume in the period")
    p.add_argument("--min-coverage", type=float, default=0.9, help="share of the period's days with a bar")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="monthly bar partitions + share-count cache")
    p.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)
    return p.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
