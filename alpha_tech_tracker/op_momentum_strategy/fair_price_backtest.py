"""
fair_price_backtest.py

Reconstructs OptionPriceMonitor cache from historical 1-min option bars and
trade ticks, then measures get_fair_price efficiency by checking whether
actual trades in the next 15 minutes fill at or above the computed fair price.

Snapshot reconstruction:  every 1 minute (bid/ask from bar low/high, best_time_value
                           from last trade within 30 min)
Cache update + fair price: every 5 minutes (matching live monitor cadence)
Fill simulation:           scan actual trade ticks in the next 15 minutes

Usage:
    python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \\
        --tickers TSLA NVDA META --date 2026-04-10

    # Use TimePremiumContractSelector instead of the default ITM offset
    python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \\
        --tickers TSLA --date 2026-04-10 --option-selector time-premium
"""
import argparse
import bisect
import csv
import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP

import pytz

from alpaca.data.enums import DataFeed
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest, OptionTradesRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from .contract_selector import ITMOptionContractSelector, TimePremiumContractSelector
from .models import _D
from .option_price_monitor import (
    OptionPriceMonitor,
    _LIQUID_SPREAD_THRESHOLD,
    _RECENT_TRADE_MAX_AGE_SECONDS,
    _parse_occ_symbol,
)

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
UTC = pytz.utc

_SNAPSHOT_INTERVAL_MIN = 1   # bar resolution
_CACHE_UPDATE_INTERVAL_MIN = 5  # how often to add to cache + call get_fair_price
_FILL_LOOKAHEAD_MIN = 15
_CACHE_MAXLEN = 6
_DEFAULT_OUTPUT_DIR = "back_test_result/fair_price_backtest"

# Bar lookback: normal = 5 min; sparse = 60 min (deep ITM, intrinsic dominates)
_BAR_LOOKBACK_NORMAL_MIN = 5
_BAR_LOOKBACK_SPARSE_MIN = 60
_SPARSE_BAR_THRESHOLD = 30  # bars/day below this triggers wide lookback

_DETAIL_FIELDS = [
    "date", "ticker", "option_type", "option_symbol", "timestamp",
    "stock_price", "bid", "ask", "mid", "intrinsic",
    "spread_pct", "cache_size", "median_tv",
    "fair_price", "branch",
    "improvement_vs_bid", "improvement_vs_mid",
    "fill_found", "fill_price", "minutes_to_fill",
]

_SUMMARY_FIELDS = [
    "date", "ticker", "option_type", "occ_symbol", "branch",
    "count", "fill_rate_pct",
    "avg_improvement_vs_bid", "avg_improvement_vs_mid",
    "avg_minutes_to_fill",
]


# ---------------------------------------------------------------------------
# Historical mock client
# ---------------------------------------------------------------------------

class _HistoricalOptionClient:
    """
    Minimal mock ExecutionClient that serves historical bar/trade data.
    Only get_option_quote_by_occ and get_option_latest_trade_by_occ are used
    by OptionPriceMonitor.get_fair_price — all other methods are unused stubs.

    Bar low/high are used as bid/ask proxies (trade-based, not quote-based).
    This is an approximation; real bid/ask history is not available via
    Alpaca's SDK at this time.
    """

    def __init__(self, bar_lookback_minutes: int = _BAR_LOOKBACK_NORMAL_MIN):
        self._bars = {}     # {occ_symbol: {datetime_minute_et: bar}}
        self._trades = {}   # {occ_symbol: [trade, ...] sorted by timestamp}
        self._current_ts = None
        self._bar_lookback_minutes = bar_lookback_minutes

    def set_current_ts(self, ts: datetime):
        self._current_ts = ts

    def register_bars(self, occ_symbol: str, bars: list):
        by_minute = {}
        for bar in bars:
            ts_et = bar.timestamp.astimezone(ET).replace(second=0, microsecond=0)
            by_minute[ts_et] = bar
        self._bars[occ_symbol] = by_minute

    def register_trades(self, occ_symbol: str, trades: list):
        self._trades[occ_symbol] = sorted(trades, key=lambda t: t.timestamp)

    def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
        bar = self._lookup_bar(occ_symbol, self._current_ts)
        if bar is None:
            raise RuntimeError(f"No bar data for {occ_symbol} at {self._current_ts}")
        mid = float(bar.vwap) if bar.vwap else (float(bar.high) + float(bar.low)) / 2
        return {"bid": float(bar.low), "ask": float(bar.high), "mid": mid}

    def get_option_latest_trade_by_occ(self, occ_symbol: str):
        trades = self._trades.get(occ_symbol)
        if not trades:
            return None
        cutoff = self._current_ts.astimezone(UTC)
        # Binary search for rightmost trade at or before cutoff
        keys = [t.timestamp.astimezone(UTC) for t in trades]
        idx = bisect.bisect_right(keys, cutoff) - 1
        if idx < 0:
            return None
        return {"price": float(trades[idx].price), "timestamp": trades[idx].timestamp}

    def _lookup_bar(self, occ_symbol: str, ts: datetime):
        bars = self._bars.get(occ_symbol, {})
        if not bars:
            return None
        ts_min = ts.astimezone(ET).replace(second=0, microsecond=0)
        for delta in range(self._bar_lookback_minutes + 1):
            candidate = ts_min - timedelta(minutes=delta)
            if candidate in bars:
                return bars[candidate]
        return None

    # Unused stubs required so OptionPriceMonitor constructor doesn't fail
    # when it builds the default TradeEngineStrikeSelector internally.
    def get_stock_quote(self, *a, **kw):
        raise NotImplementedError

    def get_option_quotes_by_occ_batch(self, *a, **kw):
        raise NotImplementedError

    def get_options_contracts(self, *a, **kw):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _market_window(trade_date):
    open_et = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 9, 30))
    close_et = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 16, 0))
    return open_et, close_et


def _fetch_stock_bars(ticker: str, trade_date, stock_client: StockHistoricalDataClient) -> dict:
    """Returns {datetime_minute_et: mid_price_decimal}."""
    open_et, close_et = _market_window(trade_date)
    req = StockBarsRequest(
        symbol_or_symbols=[ticker],
        start=open_et,
        end=close_et,
        timeframe=TimeFrame.Minute,
        feed=DataFeed.SIP,
    )
    bars = stock_client.get_stock_bars(req)
    result = {}
    for bar in bars.data.get(ticker, []):
        ts_et = bar.timestamp.astimezone(ET).replace(second=0, microsecond=0)
        result[ts_et] = _D(str((bar.high + bar.low) / 2))
    return result


def _fetch_option_bars(occ_symbol: str, trade_date, option_client: OptionHistoricalDataClient) -> list:
    open_et, close_et = _market_window(trade_date)
    req = OptionBarsRequest(
        symbol_or_symbols=[occ_symbol],
        start=open_et,
        end=close_et,
        timeframe=TimeFrame.Minute,
    )
    bars_map = option_client.get_option_bars(req)
    return list(bars_map.data.get(occ_symbol, []))


def _fetch_option_trades(occ_symbol: str, trade_date, option_client: OptionHistoricalDataClient) -> list:
    open_et, close_et = _market_window(trade_date)
    # Extend window slightly to cover fill lookahead past 4 PM
    end_extended = close_et + timedelta(minutes=_FILL_LOOKAHEAD_MIN)
    req = OptionTradesRequest(
        symbol_or_symbols=[occ_symbol],
        start=open_et,
        end=end_extended,
    )
    trades_map = option_client.get_option_trades(req)
    return list(trades_map.data.get(occ_symbol, []))


# ---------------------------------------------------------------------------
# Snapshot reconstruction
# ---------------------------------------------------------------------------

def _build_stock_price_lookup(stock_bars: dict, ts: datetime):
    """Return stock mid at ts, falling back up to 5 minutes."""
    ts_min = ts.astimezone(ET).replace(second=0, microsecond=0)
    for delta in range(6):
        candidate = ts_min - timedelta(minutes=delta)
        if candidate in stock_bars:
            return stock_bars[candidate]
    return None


def _build_snapshot(ts, occ_symbol, option_type, strike, hist_client, stock_bars):
    """Build one snapshot dict at the given timestamp. Returns None if data unavailable."""
    stock_price = _build_stock_price_lookup(stock_bars, ts)
    if stock_price is None:
        return None

    try:
        q = hist_client.get_option_quote_by_occ(occ_symbol)
    except RuntimeError:
        return None

    bid = _D(str(q["bid"]))
    ask = _D(str(q["ask"]))
    mid = (bid + ask) / _D("2")
    if mid <= _D("0") or ask < bid:
        return None

    if option_type == "call":
        intrinsic = max(_D("0"), stock_price - strike)
    else:
        intrinsic = max(_D("0"), strike - stock_price)

    mid_time_value = mid - intrinsic

    # Trade-based time value
    trade_data = hist_client.get_option_latest_trade_by_occ(occ_symbol)
    best_time_value = float(mid_time_value)
    if trade_data is not None:
        age = (ts.astimezone(UTC) - trade_data["timestamp"].astimezone(UTC)).total_seconds()
        if age <= _RECENT_TRADE_MAX_AGE_SECONDS:
            best_time_value = float(
                max(_D("0"), _D(str(trade_data["price"])) - intrinsic)
            )

    spread_pct = (ask - bid) / mid * _D("100")

    return {
        "ts": ts,
        "stock_price": stock_price,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "intrinsic": intrinsic,
        "spread_pct": spread_pct,
        "mid_time_value": float(mid_time_value),
        "best_time_value": best_time_value,
    }


# ---------------------------------------------------------------------------
# Fair price replay helpers
# ---------------------------------------------------------------------------

def _derive_branch(spread_pct, bid, intrinsic, cache):
    if spread_pct <= _LIQUID_SPREAD_THRESHOLD and bid >= intrinsic:
        return "liquid"
    if not cache:
        return "no_cache"
    return "stale_bid" if bid < intrinsic else "wide_spread"


def _compute_median_tv(cache):
    if not cache:
        return None
    values = sorted(max(_D("0"), _D(str(s["best_time_value"]))) for s in cache)
    n = len(values)
    if n % 2 == 1:
        return values[n // 2]
    return (values[n // 2 - 1] + values[n // 2]) / _D("2")


# ---------------------------------------------------------------------------
# Fill simulation
# ---------------------------------------------------------------------------

def _simulate_fill(fair_price, trades: list, from_ts: datetime, lookahead_min: int):
    """
    Scan trade ticks in (from_ts, from_ts + lookahead_min].
    Returns (fill_found, fill_price, minutes_to_fill).
    """
    if not trades:
        return False, None, None

    end_ts = from_ts.astimezone(UTC) + timedelta(minutes=lookahead_min)
    start_ts = from_ts.astimezone(UTC)

    keys = [t.timestamp.astimezone(UTC) for t in trades]
    start_idx = bisect.bisect_right(keys, start_ts)

    for i in range(start_idx, len(trades)):
        t = trades[i]
        t_utc = t.timestamp.astimezone(UTC)
        if t_utc > end_ts:
            break
        if _D(str(t.price)) >= fair_price:
            elapsed = (t_utc - start_ts).total_seconds() / 60
            return True, float(t.price), round(elapsed, 1)

    return False, None, None


# ---------------------------------------------------------------------------
# Per-contract runner
# ---------------------------------------------------------------------------

def _run_contract(
    ticker, trade_date, occ_symbol, option_type,
    hist_client, stock_bars, trades, is_sparse=False,
):
    """
    Walk market hours at 1-min resolution. Update cache and call get_fair_price
    every 5 minutes. Returns list of detail row dicts.
    """
    parsed = _parse_occ_symbol(occ_symbol)
    if not parsed:
        logger.warning("Could not parse OCC symbol %s — skipping", occ_symbol)
        return []

    strike = parsed["strike"]
    open_et, close_et = _market_window(trade_date)

    # Build monitor with mock client; no contract_selector needed (never called)
    monitor = OptionPriceMonitor(
        client=hist_client,
        tickers=[ticker],
        output_dir="/tmp/fair_price_backtest_unused",
        contract_selector=_NullContractSelector(),
    )

    cache = deque(maxlen=_CACHE_MAXLEN)
    detail_rows = []

    ts = open_et
    while ts < close_et:
        hist_client.set_current_ts(ts)
        snap = _build_snapshot(ts, occ_symbol, option_type, strike, hist_client, stock_bars)

        elapsed_min = int((ts - open_et).total_seconds() // 60)
        is_cache_tick = elapsed_min > 0 and elapsed_min % _CACHE_UPDATE_INTERVAL_MIN == 0

        if snap is not None and is_cache_tick:
            cache.append(snap)

            # Pre-populate the monitor cache with current state
            monitor._cache[occ_symbol] = deque(list(cache), maxlen=_CACHE_MAXLEN)

            fair_price = monitor.get_fair_price(
                ticker, occ_symbol, option_type, snap["stock_price"]
            )
            if fair_price <= _D("0"):
                ts += timedelta(minutes=_SNAPSHOT_INTERVAL_MIN)
                continue

            bid = snap["bid"]
            ask = snap["ask"]
            mid = snap["mid"]
            intrinsic = snap["intrinsic"]
            spread_pct = snap["spread_pct"]

            branch = _derive_branch(spread_pct, bid, intrinsic, list(cache))
            if is_sparse:
                branch = f"illiquid_{branch}"
            median_tv = _compute_median_tv(list(cache))

            fill_found, fill_price, min_to_fill = _simulate_fill(
                fair_price, trades, ts, _FILL_LOOKAHEAD_MIN
            )

            detail_rows.append({
                "date": trade_date.isoformat(),
                "ticker": ticker,
                "option_type": option_type,
                "option_symbol": occ_symbol,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "stock_price": float(snap["stock_price"].quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
                "bid": float(bid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
                "ask": float(ask.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
                "mid": float(mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
                "intrinsic": float(intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
                "spread_pct": float(spread_pct.quantize(_D("0.1"), rounding=ROUND_HALF_UP)),
                "cache_size": len(cache),
                "median_tv": float(median_tv.quantize(_D("0.01"), rounding=ROUND_HALF_UP)) if median_tv is not None else None,
                "fair_price": float(fair_price),
                "branch": branch,
                "improvement_vs_bid": round(float(fair_price - bid), 2),
                "improvement_vs_mid": round(float(fair_price - mid), 2),
                "fill_found": fill_found,
                "fill_price": fill_price,
                "minutes_to_fill": min_to_fill,
            })

        ts += timedelta(minutes=_SNAPSHOT_INTERVAL_MIN)

    logger.info(
        "%s %s %s: %d fair_price calls, %d fills (%.0f%%)",
        trade_date, ticker, option_type,
        len(detail_rows),
        sum(1 for r in detail_rows if r["fill_found"]),
        100 * sum(1 for r in detail_rows if r["fill_found"]) / len(detail_rows) if detail_rows else 0,
    )
    return detail_rows


class _NullContractSelector:
    """Placeholder contract selector — never called in backtest context."""
    def select_contracts(self, ticker, stock_price):
        return []


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------

def _compute_summary(detail_rows, trade_date, attempted_contracts):
    groups = defaultdict(list)
    for row in detail_rows:
        key = (row["ticker"], row["option_type"], row["branch"])
        groups[key].append(row)

    summary_rows = []
    for (ticker, option_type, branch), rows in sorted(groups.items()):
        fills = [r for r in rows if r["fill_found"]]
        avg_min_to_fill = (
            round(sum(r["minutes_to_fill"] for r in fills) / len(fills), 1)
            if fills else None
        )
        summary_rows.append({
            "date": trade_date.isoformat(),
            "ticker": ticker,
            "option_type": option_type,
            "occ_symbol": rows[0]["option_symbol"],
            "branch": branch,
            "count": len(rows),
            "fill_rate_pct": round(100 * len(fills) / len(rows), 1),
            "avg_improvement_vs_bid": round(sum(r["improvement_vs_bid"] for r in rows) / len(rows), 3),
            "avg_improvement_vs_mid": round(sum(r["improvement_vs_mid"] for r in rows) / len(rows), 3),
            "avg_minutes_to_fill": avg_min_to_fill,
        })

    # Add zero rows for contracts that were attempted but produced no detail rows
    seen = {(r["ticker"], r["option_type"]) for r in detail_rows}
    for ticker, option_type, occ_symbol, bar_count in sorted(attempted_contracts):
        if (ticker, option_type) not in seen:
            branch = "no_bars" if bar_count == 0 else f"sparse_bars ({bar_count})"
            summary_rows.append({
                "date": trade_date.isoformat(),
                "ticker": ticker,
                "option_type": option_type,
                "occ_symbol": occ_symbol,
                "branch": branch,
                "count": 0,
                "fill_rate_pct": None,
                "avg_improvement_vs_bid": None,
                "avg_improvement_vs_mid": None,
                "avg_minutes_to_fill": None,
            })

    return sorted(summary_rows, key=lambda r: (r["ticker"], r["option_type"], r["branch"]))


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_backtest(
    tickers,
    trade_date,
    option_selector="standard",
    time_premium_pct_cap=0.01,
    lookahead_min=_FILL_LOOKAHEAD_MIN,
    output_dir=_DEFAULT_OUTPUT_DIR,
):
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")

    stock_client = StockHistoricalDataClient(api_key, secret_key)
    option_client = OptionHistoricalDataClient(api_key, secret_key)

    all_detail_rows = []
    attempted_contracts = []  # (ticker, option_type, occ_symbol, bar_count)

    for ticker in tickers:
        logger.info("Processing %s on %s", ticker, trade_date)

        stock_bars = _fetch_stock_bars(ticker, trade_date, stock_client)
        if not stock_bars:
            logger.warning("%s: no stock bars found for %s — skipping", ticker, trade_date)
            continue

        # Use opening stock price to select contracts
        open_et = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 9, 30))
        stock_open_price = _build_stock_price_lookup(stock_bars, open_et)
        if stock_open_price is None:
            logger.warning("%s: no opening stock price — skipping", ticker)
            continue

        from .config import build_execution_client
        exec_client = build_execution_client(is_paper=True)
        if option_selector == "time-premium":
            selector = TimePremiumContractSelector(exec_client, time_premium_pct_cap=time_premium_pct_cap)
        else:
            selector = ITMOptionContractSelector(exec_client)

        for signal, option_type in [("BULLISH", "call"), ("BEARISH", "put")]:
            try:
                occ_symbol = selector.select(ticker, signal, float(stock_open_price))
            except Exception as e:
                logger.warning("%s %s: contract selection failed — %s", ticker, option_type, e)
                continue

            logger.info("%s %s: selected contract %s", ticker, option_type, occ_symbol)

            bars = _fetch_option_bars(occ_symbol, trade_date, option_client)
            trades = _fetch_option_trades(occ_symbol, trade_date, option_client)
            attempted_contracts.append((ticker, option_type, occ_symbol, len(bars)))

            if not bars:
                logger.warning("%s %s %s: no option bars — skipping", ticker, option_type, occ_symbol)
                continue

            is_sparse = len(bars) < _SPARSE_BAR_THRESHOLD
            lookback = _BAR_LOOKBACK_SPARSE_MIN if is_sparse else _BAR_LOOKBACK_NORMAL_MIN
            if is_sparse:
                logger.info(
                    "%s %s: sparse bars (%d) — using %d-min lookback",
                    ticker, option_type, len(bars), lookback,
                )
            hist_client = _HistoricalOptionClient(bar_lookback_minutes=lookback)
            hist_client.register_bars(occ_symbol, bars)
            hist_client.register_trades(occ_symbol, trades)

            rows = _run_contract(
                ticker, trade_date, occ_symbol, option_type,
                hist_client, stock_bars, trades, is_sparse=is_sparse,
            )
            all_detail_rows.extend(rows)

    if not all_detail_rows and not attempted_contracts:
        logger.warning("No data produced — check tickers and date")
        return

    summary_rows = _compute_summary(all_detail_rows, trade_date, attempted_contracts)
    _write_outputs(all_detail_rows, summary_rows, trade_date, output_dir)


def _write_outputs(detail_rows, summary_rows, trade_date, output_dir):
    date_str = trade_date.isoformat()
    day_dir = os.path.join(output_dir, date_str)
    os.makedirs(day_dir, exist_ok=True)

    detail_path = os.path.join(day_dir, "detail.csv")
    with open(detail_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(detail_rows)

    summary_path = os.path.join(day_dir, "summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)

    logger.info("Wrote %d detail rows → %s", len(detail_rows), detail_path)
    logger.info("Wrote %d summary rows → %s", len(summary_rows), summary_path)

    # Print summary to stdout
    print(f"\n=== Fair Price Backtest — {date_str} ===\n")
    print(f"{'Ticker':<8} {'Type':<6} {'OCC Symbol':<26} {'Branch':<22} {'N':>4} {'Fill%':>6} {'vs_bid':>7} {'vs_mid':>7} {'min_fill':>9}")
    print("-" * 100)
    for r in summary_rows:
        if r["count"] == 0:
            print(f"{r['ticker']:<8} {r['option_type']:<6} {r['occ_symbol']:<26} {r['branch']:<22} {'0':>4} {'—':>6} {'—':>7} {'—':>7} {'—':>9}")
            continue
        min_fill = f"{r['avg_minutes_to_fill']:.1f}" if r["avg_minutes_to_fill"] is not None else "—"
        print(
            f"{r['ticker']:<8} {r['option_type']:<6} {r['occ_symbol']:<26} {r['branch']:<22} "
            f"{r['count']:>4} {r['fill_rate_pct']:>6.1f} "
            f"{r['avg_improvement_vs_bid']:>+7.3f} {r['avg_improvement_vs_mid']:>+7.3f} "
            f"{min_fill:>9}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Backtest get_fair_price efficiency against historical option data"
    )
    parser.add_argument("--tickers", nargs="+", required=True, help="Tickers to analyse")
    parser.add_argument("--date", required=True, help="Trading date (YYYY-MM-DD)")
    parser.add_argument(
        "--option-selector",
        default="standard",
        choices=["standard", "time-premium"],
        help="Contract selector: 'standard' = ITMOptionContractSelector (default), "
             "'time-premium' = TimePremiumContractSelector",
    )
    parser.add_argument(
        "--time-premium-pct-cap",
        type=float,
        default=0.01,
        help="Time premium cap fraction (only used with --option-selector time-premium, default 0.01)",
    )
    parser.add_argument(
        "--lookahead",
        type=int,
        default=_FILL_LOOKAHEAD_MIN,
        help=f"Fill lookahead window in minutes (default {_FILL_LOOKAHEAD_MIN})",
    )
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    from datetime import date as _date

    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_backtest(
        tickers=args.tickers,
        trade_date=_date.fromisoformat(args.date),
        option_selector=args.option_selector,
        time_premium_pct_cap=args.time_premium_pct_cap,
        lookahead_min=args.lookahead,
        output_dir=args.output_dir,
    )
