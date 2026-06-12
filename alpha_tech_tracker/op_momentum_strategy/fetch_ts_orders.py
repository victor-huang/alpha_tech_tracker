"""Fetch filled orders from TradeStation for a given date and save fill-quality CSVs.

Produces two CSV files per run:
  fills_{date}/options_fills_{date}.csv  — one row per option fill (entry or exit)
  fills_{date}/stocks_fills_{date}.csv   — one row per stock fill

Option rows include Alpaca historical 1-min bar data and nearest trade print for the
option contract at fill time, enabling calibration of fill quality vs market mid.

Usage:
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders --date 2026-04-24
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders --date 2026-04-24 --out-dir logs/fills
"""

import argparse
import csv
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-4))  # EDT (UTC-4); adjust to -5 for EST


def _now_et() -> datetime:
    return datetime.now(tz=_ET)


def _parse_ts_datetime(raw: str) -> datetime:
    """Parse an ISO datetime string from TS into a timezone-aware datetime (ET).

    TS timestamps are UTC (trailing 'Z').  Stripping 'Z' and attaching ET would
    produce a time that is 4 hours wrong.  Correct: parse as UTC, convert to ET.
    """
    if not raw:
        return None
    is_utc = raw.endswith("Z")
    raw_stripped = raw.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw_stripped, fmt)
            if is_utc:
                return dt.replace(tzinfo=timezone.utc).astimezone(_ET)
            return dt.replace(tzinfo=_ET)
        except ValueError:
            continue
    return None


def _ticker_from_symbol(symbol: str) -> str:
    """Extract the underlying ticker from an OCC symbol or plain equity symbol."""
    m = re.match(r"^([A-Z]+)\d{6}[CP]\d{8}$", symbol)
    if m:
        return m.group(1)
    return symbol.strip()


def _is_option(symbol: str) -> bool:
    return bool(re.match(r"^[A-Z]+\d{6}[CP]\d{8}$", symbol))


def _fetch_all_orders(client, target_date: date) -> list:
    """Fetch all orders for target_date using the TS historical orders endpoint.

    Falls back to today's order endpoint if the date matches today.
    """
    account_key = client._get_account_key()
    since_dt = datetime(target_date.year, target_date.month, target_date.day,
                        tzinfo=timezone.utc)
    since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info("Fetching orders for %s (account %s)...", target_date, account_key)

    # TradeStation v3 historical orders endpoint
    url = client._v3_base_url + f"/brokerage/accounts/{account_key}/historicalorders"
    params = {"since": since_str, "pageSize": 600}
    resp = client._session.get(url, params=params)

    if resp.status_code == 404:
        logger.info("Historical orders endpoint returned 404 — falling back to /orders")
        url = client._v3_base_url + f"/brokerage/accounts/{account_key}/orders"
        resp = client._session.get(url, params={"pageSize": 600})
        data = resp.json()
        orders = data if isinstance(data, list) else data.get("Orders", [])
        logger.info("Retrieved %d raw orders", len(orders))
        return orders

    data = resp.json()
    orders = data if isinstance(data, list) else data.get("Orders", [])

    if not orders:
        # Historical endpoint returned empty — try today's /orders endpoint as fallback
        # (historicalorders excludes same-day orders on TS)
        logger.info("Historical orders endpoint returned empty — falling back to /orders")
        url = client._v3_base_url + f"/brokerage/accounts/{account_key}/orders"
        resp2 = client._session.get(url, params={"pageSize": 600})
        data2 = resp2.json()
        orders = data2 if isinstance(data2, list) else data2.get("Orders", [])

    logger.info("Retrieved %d raw orders", len(orders))
    return orders


def _parse_orders(raw_orders: list, target_date: date) -> list:
    """Parse raw TS order dicts into a normalised list of filled-order records."""
    records = []
    for raw in raw_orders:
        status = raw.get("Status", "")
        if status not in ("FLL", "FLP"):
            continue

        opened_raw = raw.get("OpenedDateTime", "")
        closed_raw = raw.get("ClosedDateTime", "") or raw.get("FilledDateTime", "")
        fill_time = _parse_ts_datetime(closed_raw) or _parse_ts_datetime(opened_raw)

        if fill_time and fill_time.date() != target_date:
            continue

        legs = raw.get("Legs", [])
        if not legs:
            continue
        leg = legs[0]

        raw_symbol = leg.get("Symbol", "")
        # Strip spaces: TradeStation pads short tickers with spaces
        symbol = raw_symbol.replace(" ", "")
        # Convert display name (e.g. "TSLA 260417C392.5") to OCC if needed
        if " " in raw_symbol and not re.match(r"^[A-Z]+\d{6}[CP]\d{8}$", symbol):
            try:
                from alpha_tech_tracker.trade_api.tradestation.client import _ts_search_name_to_occ
                symbol = _ts_search_name_to_occ(raw_symbol)
            except Exception:
                symbol = raw_symbol.strip()

        qty = float(leg.get("ExecQuantity") or leg.get("QuantityOrdered") or 0)
        fill_price_raw = raw.get("FilledPrice") or raw.get("AverageFillPrice")
        fill_price = float(fill_price_raw) if fill_price_raw else None

        limit_raw = raw.get("LimitPrice")
        limit_price = float(limit_raw) if limit_raw else None

        trade_action = leg.get("BuyOrSell", "").upper()  # Buy / Sell
        ts_action = (leg.get("OpenOrClose", "") or "").upper()  # Open / Close
        # Reconstruct entry/exit label
        if "BUY" in trade_action and "OPEN" in ts_action:
            side = "ENTRY"
        elif "SELL" in trade_action and "CLOSE" in ts_action:
            side = "EXIT"
        elif "BUY" in trade_action and "CLOSE" in ts_action:
            side = "EXIT"  # buy-to-close (short)
        elif "SELL" in trade_action and "OPEN" in ts_action:
            side = "ENTRY"  # sell-to-open (bearish)
        else:
            side = trade_action  # fallback

        records.append({
            "order_id": str(raw.get("OrderID", "")),
            "side": side,
            "trade_action": leg.get("BuyOrSell", ""),
            "ticker": _ticker_from_symbol(symbol),
            "symbol": symbol,
            "asset_type": "option" if _is_option(symbol) else "stock",
            "qty": qty,
            "fill_price": fill_price,
            "fill_time": fill_time,
            "limit_price": limit_price,
            "slippage_vs_limit": (
                round(fill_price - limit_price, 4)
                if fill_price is not None and limit_price is not None else None
            ),
        })

    records.sort(key=lambda r: (r["fill_time"] or datetime.min.replace(tzinfo=_ET)))
    logger.info("Parsed %d filled records", len(records))
    return records


def _build_alpaca_stock_client():
    """Instantiate an Alpaca StockHistoricalDataClient from env vars."""
    from alpaca.data.historical import StockHistoricalDataClient
    api_key = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_KEY_ID")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        logger.warning("ALPACA_API_KEY / ALPACA_SECRET_KEY not set — stock bar data unavailable")
        return None
    return StockHistoricalDataClient(api_key, secret_key)


def _fetch_stock_quote_at_time(alpaca_stock_client, ticker: str, fill_time: datetime) -> dict:
    """Fetch a 1-min Alpaca bar enclosing fill_time to get stock price context."""
    if alpaca_stock_client is None or fill_time is None:
        return {}
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        start = fill_time - timedelta(minutes=2)
        end = fill_time + timedelta(minutes=2)
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            start=start,
            end=end,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        )
        bars_resp = alpaca_stock_client.get_stock_bars(req)
        bars = list(bars_resp.data.get(ticker, []))
        if not bars:
            return {}
        matching = [b for b in bars if b.timestamp <= fill_time]
        bar = matching[-1] if matching else bars[0]
        mid = (bar.high + bar.low) / 2
        return {
            "stock_open": round(float(bar.open), 4),
            "stock_close": round(float(bar.close), 4),
            "stock_high": round(float(bar.high), 4),
            "stock_low": round(float(bar.low), 4),
            "stock_mid_hl": round(float(mid), 4),
            "stock_bar_time": bar.timestamp.astimezone(_ET).strftime("%H:%M"),
        }
    except Exception as exc:
        logger.warning("Could not fetch stock bar for %s at %s: %s", ticker, fill_time, exc)
        return {}


def _build_alpaca_option_client():
    """Instantiate an Alpaca OptionHistoricalDataClient from env vars."""
    from alpaca.data.historical import OptionHistoricalDataClient
    api_key = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_KEY_ID")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        logger.warning(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY not set — option bar data unavailable"
        )
        return None
    return OptionHistoricalDataClient(api_key, secret_key)


def _fetch_option_data_at_time(alpaca_opt_client, occ_symbol: str, fill_time: datetime) -> dict:
    """Fetch Alpaca historical option bar and nearest trade for calibration.

    Uses a 3-minute window around fill_time to get:
      - 1-min OHLCV bar enclosing the fill (open/high/low/close/vwap)
      - nearest actual trade print to the fill time (price + offset in seconds)

    These are used to assess fill quality: was our fill inside the bar range?
    How close to VWAP? How close to the nearest market print?
    """
    if alpaca_opt_client is None or fill_time is None:
        return {}

    from alpaca.data.requests import OptionBarsRequest, OptionTradesRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    start = fill_time - timedelta(minutes=2)
    end = fill_time + timedelta(minutes=2)
    result = {}

    # --- 1-min bar ---
    try:
        req = OptionBarsRequest(
            symbol_or_symbols=occ_symbol,
            start=start,
            end=end,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        )
        bars_resp = alpaca_opt_client.get_option_bars(req)
        bars = list(bars_resp.data.get(occ_symbol, []))

        # Find bar whose timestamp is closest before fill_time
        matching = [b for b in bars if b.timestamp <= fill_time]
        bar = matching[-1] if matching else (bars[0] if bars else None)

        if bar is not None:
            result.update({
                "opt_bar_open":  round(float(bar.open), 4),
                "opt_bar_high":  round(float(bar.high), 4),
                "opt_bar_low":   round(float(bar.low), 4),
                "opt_bar_close": round(float(bar.close), 4),
                "opt_bar_vwap":  round(float(bar.vwap), 4) if bar.vwap else None,
                "opt_bar_time":  bar.timestamp.strftime("%H:%M"),
            })
    except Exception as exc:
        logger.warning("Alpaca option bars failed for %s: %s", occ_symbol, exc)

    # --- nearest trade print ---
    try:
        req = OptionTradesRequest(
            symbol_or_symbols=occ_symbol,
            start=start,
            end=end,
            limit=50,
        )
        trades_resp = alpaca_opt_client.get_option_trades(req)
        trades = list(trades_resp.data.get(occ_symbol, []))

        if trades:
            nearest = min(
                trades,
                key=lambda t: abs((t.timestamp - fill_time).total_seconds()),
            )
            offset_s = (nearest.timestamp - fill_time).total_seconds()
            result.update({
                "opt_nearest_trade_price": round(float(nearest.price), 4),
                "opt_nearest_trade_size":  int(nearest.size),
                "opt_nearest_trade_offset_s": round(offset_s, 1),
            })
    except Exception as exc:
        logger.warning("Alpaca option trades failed for %s: %s", occ_symbol, exc)

    return result


def _fetch_hourly_avg_time_value(
    alpaca_opt_client,
    alpaca_stock_client,
    occ_symbol: str,
    ticker: str,
    fill_time: datetime,
    stock_bar_cache: dict,
) -> Optional[float]:
    """Compute the average option time value over a ±30-min window around fill_time.

    For each 1-min option bar in the window, pairs it with the closest stock bar
    to derive intrinsic value, then averages (option_close - intrinsic) across all bars.
    stock_bar_cache is a dict keyed by (ticker, window_start) to avoid redundant calls.
    Returns None if fewer than 3 paired bars are found.
    """
    if alpaca_opt_client is None or alpaca_stock_client is None or fill_time is None:
        return None

    from alpaca.data.requests import OptionBarsRequest, StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import _parse_occ_symbol

    parsed = _parse_occ_symbol(occ_symbol)
    if not parsed:
        return None
    strike = float(parsed["strike"])
    option_type = parsed["option_type"]

    window_start = fill_time - timedelta(minutes=30)
    window_end = fill_time + timedelta(minutes=30)

    # Fetch option 1-min bars for the window
    try:
        req = OptionBarsRequest(
            symbol_or_symbols=occ_symbol,
            start=window_start,
            end=window_end,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        )
        opt_bars = list(alpaca_opt_client.get_option_bars(req).data.get(occ_symbol, []))
    except Exception as exc:
        logger.warning("Hourly opt bars failed for %s: %s", occ_symbol, exc)
        return None

    if not opt_bars:
        return None

    # Fetch stock 1-min bars, cached per (ticker, window_start)
    cache_key = (ticker, window_start)
    if cache_key not in stock_bar_cache:
        try:
            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                start=window_start,
                end=window_end,
                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            )
            stock_bar_cache[cache_key] = list(
                alpaca_stock_client.get_stock_bars(req).data.get(ticker, [])
            )
        except Exception as exc:
            logger.warning("Hourly stock bars failed for %s: %s", ticker, exc)
            stock_bar_cache[cache_key] = []

    stock_bars = stock_bar_cache[cache_key]
    if not stock_bars:
        return None

    # Build a sorted list of (timestamp, close) for stock bars for fast lookup
    stock_by_ts = sorted((b.timestamp, float(b.close)) for b in stock_bars)

    def _nearest_stock_close(opt_ts: datetime) -> Optional[float]:
        best = min(stock_by_ts, key=lambda x: abs((x[0] - opt_ts).total_seconds()))
        if abs((best[0] - opt_ts).total_seconds()) > 120:
            return None
        return best[1]

    time_values = []
    for bar in opt_bars:
        stock_close = _nearest_stock_close(bar.timestamp)
        if stock_close is None:
            continue
        if option_type == "call":
            intrinsic = max(0.0, stock_close - strike)
        else:
            intrinsic = max(0.0, strike - stock_close)
        tv = float(bar.close) - intrinsic
        if tv >= 0:
            time_values.append(tv)

    if len(time_values) < 3:
        return None
    return round(sum(time_values) / len(time_values), 4)


def _parse_quotes_from_log(log_path: str, records: list) -> dict:
    """Scan the options trade log for FILL_ESC bid/ask/mid/fair at order-placement time.

    Indexes every `FILL_ESC ... SYMBOL: bid=X ask=Y mid=Z fair=W` line by
    (symbol, log_utc_timestamp).  For each record, returns the most recent quote
    logged for that symbol within 5 minutes before the fill.

    Returns dict: order_id → {bid, ask, mid, fair, spread_pct, step}
    """
    if not log_path or not os.path.exists(log_path):
        return {}

    re_ts = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    re_step = re.compile(
        r"FILL_ESC (?:loop )?step(\d+) (?:BUY_OPEN|SELL_CLOSE) (\S+): "
        r"bid=([\d.]+) ask=([\d.]+) mid=([\d.]+) fair=([\d.]+|n/a)"
    )
    # Step3 floor case: bid < fair_price — no ask/mid/fair fields; still counts as step3
    re_step3_floor = re.compile(
        r"FILL_ESC step3 (?:BUY_OPEN|SELL_CLOSE) (\S+): bid=[\d.]+ is below fair_price"
    )

    symbol_quotes = {}  # symbol → [(log_dt_utc, quote_dict)]
    with open(log_path) as f:
        for line in f:
            tm = re_ts.match(line)
            if not tm:
                continue
            sm = re_step.search(line)
            if sm:
                step, symbol, bid, ask, mid, fair = sm.groups()
                bid, ask, mid = float(bid), float(ask), float(mid)
                fair = None if fair == "n/a" else float(fair)
                log_dt = datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                spread_pct = round((ask - bid) / mid * 100, 2) if mid else None
                symbol_quotes.setdefault(symbol, []).append((log_dt, {
                    "opt_log_bid": bid,
                    "opt_log_ask": ask,
                    "opt_log_mid": mid,
                    "opt_log_fair": fair,
                    "opt_log_spread_pct": spread_pct,
                    "opt_log_step": int(step),
                }))
                continue
            fm = re_step3_floor.search(line)
            if fm:
                symbol = fm.group(1)
                if symbol in symbol_quotes and symbol_quotes[symbol]:
                    # Patch the most recent quote entry to reflect step3 escalation
                    symbol_quotes[symbol][-1][1]["opt_log_step"] = 3

    result = {}
    for rec in records:
        symbol = rec.get("symbol", "")
        if symbol not in symbol_quotes:
            continue
        fill_time_utc = rec["fill_time"].astimezone(timezone.utc)
        candidates = [
            (dt, q) for dt, q in symbol_quotes[symbol]
            if dt <= fill_time_utc and (fill_time_utc - dt).total_seconds() <= 300
        ]
        if candidates:
            _, best_q = max(candidates, key=lambda x: x[0])
            result[rec["order_id"]] = best_q

    logger.info("Log quote lookup: matched %d / %d records", len(result), len(records))
    return result


def _compute_intrinsic(symbol: str, stock_price: float) -> Optional[float]:
    """Return intrinsic value for an OCC option symbol given the underlying stock price."""
    from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import _parse_occ_symbol
    parsed = _parse_occ_symbol(symbol)
    if not parsed:
        return None
    strike = float(parsed["strike"])
    if parsed["option_type"] == "call":
        return max(0.0, round(stock_price - strike, 4))
    return max(0.0, round(strike - stock_price, 4))


def _enrich_records(alpaca_stock_client, alpaca_opt_client, records: list,
                    log_quotes: dict) -> list:
    """Add stock price, Alpaca option bar/trade, log bid/ask, and hourly avg time value."""
    stock_bar_cache = {}
    enriched = []
    for rec in records:
        row = dict(rec)
        stock_ctx = _fetch_stock_quote_at_time(alpaca_stock_client, rec["ticker"], rec["fill_time"])
        row.update(stock_ctx)

        if rec["asset_type"] == "option":
            opt_ctx = _fetch_option_data_at_time(
                alpaca_opt_client, rec["symbol"], rec["fill_time"]
            )
            row.update(opt_ctx)

            # Log-sourced bid/ask/mid/fair at order-placement time
            log_q = log_quotes.get(rec["order_id"], {})
            row.update(log_q)

            fill = rec["fill_price"]
            if fill is not None:
                if opt_ctx.get("opt_bar_vwap"):
                    row["fill_vs_vwap"] = round(fill - opt_ctx["opt_bar_vwap"], 4)
                    row["fill_vs_vwap_pct"] = round(
                        (fill - opt_ctx["opt_bar_vwap"]) / opt_ctx["opt_bar_vwap"] * 100, 3
                    )
                if opt_ctx.get("opt_nearest_trade_price"):
                    row["fill_vs_trade"] = round(
                        fill - opt_ctx["opt_nearest_trade_price"], 4
                    )
                if opt_ctx.get("opt_bar_low") and opt_ctx.get("opt_bar_high"):
                    row["fill_inside_bar"] = (
                        opt_ctx["opt_bar_low"] <= fill <= opt_ctx["opt_bar_high"]
                    )
                if log_q.get("opt_log_mid"):
                    row["fill_vs_log_mid"] = round(fill - log_q["opt_log_mid"], 4)

                stock_mid = stock_ctx.get("stock_mid_hl")
                if stock_mid is not None:
                    intrinsic = _compute_intrinsic(rec["symbol"], stock_mid)
                    if intrinsic is not None:
                        row["intrinsic_value"] = intrinsic
                        row["time_value_paid"] = round(fill - intrinsic, 4)

                        avg_tv = _fetch_hourly_avg_time_value(
                            alpaca_opt_client, alpaca_stock_client,
                            rec["symbol"], rec["ticker"],
                            rec["fill_time"], stock_bar_cache,
                        )
                        if avg_tv is not None:
                            row["hourly_avg_time_value"] = avg_tv
                            row["time_value_vs_hourly_avg"] = round(
                                row["time_value_paid"] - avg_tv, 4
                            )

        enriched.append(row)
    return enriched


_OPTION_COLS = [
    "fill_time", "side", "ticker", "symbol", "qty",
    "fill_price", "limit_price", "slippage_vs_limit",
    "intrinsic_value", "time_value_paid",
    "hourly_avg_time_value", "time_value_vs_hourly_avg",
    "opt_log_bid", "opt_log_ask", "opt_log_mid", "opt_log_fair",
    "opt_log_spread_pct", "fill_vs_log_mid", "opt_log_step",
    "opt_bar_open", "opt_bar_high", "opt_bar_low", "opt_bar_close", "opt_bar_vwap",
    "fill_vs_vwap", "fill_vs_vwap_pct", "fill_inside_bar",
    "opt_nearest_trade_price", "opt_nearest_trade_size", "opt_nearest_trade_offset_s",
    "fill_vs_trade",
    "stock_open", "stock_close", "stock_mid_hl",
    "opt_bar_time", "stock_bar_time", "order_id", "trade_action",
]

_STOCK_COLS = [
    "fill_time", "side", "ticker", "qty",
    "fill_price", "limit_price", "slippage_vs_limit",
    "stock_open", "stock_close", "stock_high", "stock_low", "stock_mid_hl",
    "stock_bar_time", "order_id", "trade_action",
]


def _write_csv(path: Path, rows: list, cols: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if isinstance(out.get("fill_time"), datetime):
                out["fill_time"] = out["fill_time"].strftime("%H:%M:%S")
            writer.writerows([out])
    logger.info("Saved %d rows → %s", len(rows), path)


def _print_table(title: str, rows: list, cols: list):
    if not rows:
        print(f"\n{title}: (none)\n")
        return
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")
    header = "  ".join(f"{c:<20}" for c in cols[:8])
    print("  " + header)
    print("  " + "-" * (len(header) + 2))
    for row in rows:
        def _fmt(v):
            if isinstance(v, datetime):
                return v.strftime("%H:%M:%S")
            if v is None:
                return "-"
            return str(v)
        line = "  ".join(f"{_fmt(row.get(c, '-')):<20}" for c in cols[:8])
        print("  " + line)
    print()


def main():
    parser = argparse.ArgumentParser(description="Fetch TS fills and save calibration CSVs")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--out-dir", default="logs/fills", help="Output directory")
    parser.add_argument("--account", default=None, help="Override TradeStation account ID (e.g. 12041669)")
    parser.add_argument("--log-file", default=None,
                        help="Options trade log for bid/ask enrichment "
                             "(default: logs/op_momentum_option_YYYY-MM-DD.log)")
    args = parser.parse_args()

    target_date = (
        date.fromisoformat(args.date) if args.date
        else _now_et().date()
    )
    out_dir = Path(args.out_dir) / str(target_date)

    from alpha_tech_tracker.op_momentum_strategy.config import (
        _load_config,
        build_execution_client,
    )
    _load_config()
    client = build_execution_client(broker="tradestation")
    if args.account:
        client._account_key = args.account
        logger.info("Using account override: %s", args.account)
    logger.info("Connected to TradeStation")

    alpaca_opt_client = _build_alpaca_option_client()
    if alpaca_opt_client:
        logger.info("Alpaca OptionHistoricalDataClient ready for option bar/trade lookups")

    alpaca_stock_client = _build_alpaca_stock_client()
    if alpaca_stock_client:
        logger.info("Alpaca StockHistoricalDataClient ready for stock bar lookups")

    log_file = args.log_file or f"logs/op_momentum_option_{target_date}.log"

    raw_orders = _fetch_all_orders(client, target_date)
    records = _parse_orders(raw_orders, target_date)
    log_quotes = _parse_quotes_from_log(log_file, records)
    records = _enrich_records(alpaca_stock_client, alpaca_opt_client, records, log_quotes)

    options = [r for r in records if r["asset_type"] == "option"]
    stocks = [r for r in records if r["asset_type"] == "stock"]

    _print_table(f"OPTION FILLS — {target_date}", options, _OPTION_COLS)
    _print_table(f"STOCK FILLS  — {target_date}", stocks, _STOCK_COLS)

    _write_csv(out_dir / f"options_fills_{target_date}.csv", options, _OPTION_COLS)
    _write_csv(out_dir / f"stocks_fills_{target_date}.csv", stocks, _STOCK_COLS)

    print(f"\nOutput saved to: {out_dir}/")
    print(f"  Options: {len(options)} fills")
    print(f"  Stocks:  {len(stocks)} fills")


if __name__ == "__main__":
    main()
