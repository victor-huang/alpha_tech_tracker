"""Fetch filled stock orders from Alpaca for a given date and save fill-quality CSV.

Produces one CSV file per run:
  logs/fills/{date}/stocks_fills_{date}.csv  — one row per stock fill (entry or exit)

Each row is enriched with:
  - Alpaca 1-min OHLCV bar + VWAP enclosing the fill
  - Alpaca historical NBBO bid/ask at fill time
  - Log-sourced bid/ask/mid from the FILL_ESC quote line in the stock trade log
  - Derived metrics: slippage_bps, fill_vs_quote_mid, quote_spread_pct, fill_inside_bar, etc.

Usage:
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_alpaca_orders
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_alpaca_orders --date 2026-05-01
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_alpaca_orders --date 2026-05-01 --live
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


def _load_alpaca_credentials() -> tuple:
    """Return (api_key, secret_key) from config.json, falling back to env vars."""
    import json
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        alpaca = cfg.get("alpaca", {})
        api_key = alpaca.get("api_key")
        secret_key = alpaca.get("secret_key")
        if api_key and secret_key:
            return api_key, secret_key
    api_key = os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_KEY_ID")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    return api_key, secret_key


def _build_trading_client(paper: bool):
    from alpaca.trading.client import TradingClient
    api_key, secret_key = _load_alpaca_credentials()
    if not api_key or not secret_key:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
    return TradingClient(api_key, secret_key, paper=paper)


def _build_alpaca_stock_data_client():
    from alpaca.data.historical import StockHistoricalDataClient
    api_key, secret_key = _load_alpaca_credentials()
    if not api_key or not secret_key:
        logger.warning("ALPACA_API_KEY / ALPACA_SECRET_KEY not set — market data unavailable")
        return None
    return StockHistoricalDataClient(api_key, secret_key)


def _fetch_orders(trading_client, target_date: date) -> list:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    start_dt = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0,
        tzinfo=timezone.utc,
    )
    end_dt = start_dt + timedelta(days=1)

    logger.info("Fetching Alpaca orders for %s ...", target_date)
    req = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        after=start_dt,
        until=end_dt,
        limit=500,
    )
    orders = trading_client.get_orders(req)
    logger.info("Retrieved %d raw orders", len(orders))
    return orders


def _scan_log_for_actions(log_path: str) -> dict:
    """Pre-scan the stock log to build a UUID → log_action mapping.

    log_action is one of: BUY_OPEN, SELL_CLOSE, SELL_SHORT, BUY_COVER.
    Used to correctly classify ENTRY vs EXIT for bearish (short) trades.
    """
    if not log_path or not os.path.exists(log_path):
        return {}

    re_quote_action = re.compile(
        r"STOCK FILL_ESC step\d+ attempt=\d+ (BUY_OPEN|SELL_CLOSE|SELL_SHORT|BUY_COVER) (\S+):"
    )
    re_placed = re.compile(r"STOCK FILL_ESC step\d+ (?:attempt=\d+ )?order placed: id=([0-9a-f-]+)")
    re_market_placed = re.compile(r"STOCK FILL_ESC step3 market order placed: id=([0-9a-f-]+)")

    # Track the most recent action+ticker seen before each "order placed" line
    pending_action = None
    pending_ticker = None
    uuid_to_action = {}

    with open(log_path) as f:
        for line in f:
            m = re_quote_action.search(line)
            if m and "wide spread" not in line and "aggressive_price" not in line:
                pending_action = m.group(1)
                pending_ticker = m.group(2)
                continue

            m = re_placed.search(line)
            if m:
                uuid = m.group(1)
                if pending_action:
                    uuid_to_action[uuid] = (pending_action, pending_ticker)
                continue

            m = re_market_placed.search(line)
            if m:
                uuid = m.group(1)
                if pending_action:
                    uuid_to_action[uuid] = (pending_action, pending_ticker)
                continue

    return uuid_to_action


_LOG_ACTION_TO_SIDE = {
    "BUY_OPEN": "ENTRY",
    "SELL_SHORT": "ENTRY",
    "SELL_CLOSE": "EXIT",
    "BUY_COVER": "EXIT",
}


def _parse_orders(raw_orders: list, target_date: date,
                  log_actions: Optional[dict] = None) -> list:
    """Filter to filled stock orders on target_date and normalize into records.

    log_actions: dict from _scan_log_for_actions — UUID → (action, ticker).
    Used to correctly label ENTRY/EXIT for short (bearish) trades.
    """
    from alpaca.trading.enums import OrderStatus

    records = []
    for order in raw_orders:
        if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            continue

        asset_class = getattr(order, "asset_class", None)
        if asset_class is not None and str(asset_class) not in (
            "AssetClass.US_EQUITY", "us_equity"
        ):
            continue

        filled_at = order.filled_at
        if filled_at is None:
            filled_at = order.submitted_at
        if filled_at is None:
            continue

        if hasattr(filled_at, "astimezone"):
            fill_time_et = filled_at.astimezone(_ET)
        else:
            fill_time_et = datetime.fromisoformat(str(filled_at)).astimezone(_ET)

        if fill_time_et.date() != target_date:
            continue

        filled_qty = float(order.filled_qty or 0)
        if filled_qty == 0:
            continue

        fill_price = float(order.filled_avg_price) if order.filled_avg_price else None
        limit_price = float(order.limit_price) if order.limit_price else None

        order_id = str(order.id)
        side_str = str(order.side).lower()

        # Use log action if available (handles SELL_SHORT / BUY_COVER for bearish trades)
        log_action_info = (log_actions or {}).get(order_id)
        if log_action_info:
            log_action, _ = log_action_info
            side = _LOG_ACTION_TO_SIDE.get(log_action, "ENTRY" if "buy" in side_str else "EXIT")
            trade_action = log_action
        else:
            side = "ENTRY" if "buy" in side_str else "EXIT"
            trade_action = "BUY_OPEN" if "buy" in side_str else "SELL_CLOSE"

        slippage = None
        if fill_price is not None and limit_price is not None and limit_price != 0:
            # For entries (buy long or sell short), positive slippage = worse fill
            # For exits (sell close or buy cover), positive slippage = worse fill
            # Unified: slippage = (fill_price - limit_price) × direction
            if side == "ENTRY" and "buy" in side_str:
                slippage = round((fill_price - limit_price) / limit_price * 10000, 1)
            elif side == "ENTRY" and "sell" in side_str:
                # Short entry: selling, worse fill = lower price
                slippage = round((limit_price - fill_price) / limit_price * 10000, 1)
            elif side == "EXIT" and "sell" in side_str:
                # Long exit: worse fill = lower price
                slippage = round((limit_price - fill_price) / limit_price * 10000, 1)
            else:
                # Short exit (buy cover): worse fill = higher price
                slippage = round((fill_price - limit_price) / limit_price * 10000, 1)

        records.append({
            "order_id": order_id,
            "side": side,
            "trade_action": trade_action,
            "ticker": order.symbol,
            "qty": filled_qty,
            "fill_price": fill_price,
            "fill_time": fill_time_et,
            "limit_price": limit_price,
            "slippage_bps": slippage,
        })

    records.sort(key=lambda r: r["fill_time"])
    logger.info("Parsed %d filled stock records for %s", len(records), target_date)
    return records


def _parse_stock_quotes_from_log(log_path: str, records: list) -> dict:
    """Scan the stock trade log for FILL_ESC bid/ask/mid at order-placement time.

    Matches each Alpaca order UUID to the quote line that preceded its placement in
    the log. Each "order placed: id=UUID" line is paired with the immediately prior
    quote line for the same ticker (resolved via the Alpaca order's symbol).

    Returns dict: order_id → {log_bid, log_ask, log_mid, log_step, log_wide_spread,
                               log_aggressive_price}
    """
    if not log_path or not os.path.exists(log_path):
        logger.warning("Log file not found: %s", log_path)
        return {}

    re_ts = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    _ACTION = r"(BUY_OPEN|SELL_CLOSE|SELL_SHORT|BUY_COVER)"

    # Quote line: "STOCK FILL_ESC stepN attemptN ACTION TICKER: bid=X ask=Y mid=Z"
    re_quote = re.compile(
        r"STOCK FILL_ESC step(\d+) attempt=(\d+) " + _ACTION + r" (\S+): "
        r"bid=([\d.]+) ask=([\d.]+) mid=([\d.]+)"
    )
    # Wide spread skip line (step1 → step2)
    re_wide = re.compile(
        r"STOCK FILL_ESC step(\d+) attempt=(\d+) " + _ACTION + r" (\S+): "
        r"wide spread"
    )
    # Step2 aggressive_price line
    re_agg = re.compile(
        r"STOCK FILL_ESC step(\d+) attempt=(\d+) " + _ACTION + r" (\S+): "
        r"bid=([\d.]+) ask=([\d.]+) aggressive_price=([\d.]+)"
    )
    # Order placed line (no ticker in this line)
    re_placed = re.compile(
        r"STOCK FILL_ESC step(\d+) attempt=(\d+) order placed: id=([0-9a-f-]+)"
    )
    # Market order placed line (step3)
    re_market = re.compile(
        r"STOCK FILL_ESC step3 market order placed: id=([0-9a-f-]+)"
    )

    # Build ordered list of events: (line_num, timestamp, event_type, data)
    events = []
    with open(log_path) as f:
        for i, line in enumerate(f):
            tm = re_ts.match(line)
            ts_str = tm.group(1) if tm else None

            m = re_quote.search(line)
            if m and "wide spread" not in line and "aggressive_price" not in line:
                step, attempt, action, ticker, bid, ask, mid = m.groups()
                events.append((i, ts_str, "quote", {
                    "step": int(step), "attempt": int(attempt),
                    "action": action, "ticker": ticker,
                    "bid": float(bid), "ask": float(ask), "mid": float(mid),
                    "wide_spread": False, "aggressive_price": None,
                }))
                continue

            m = re_wide.search(line)
            if m:
                step, attempt, action, ticker = m.groups()
                events.append((i, ts_str, "wide_spread", {
                    "step": int(step), "attempt": int(attempt),
                    "action": action, "ticker": ticker,
                }))
                continue

            m = re_agg.search(line)
            if m:
                step, attempt, action, ticker, bid, ask, agg = m.groups()
                events.append((i, ts_str, "quote_agg", {
                    "step": int(step), "attempt": int(attempt),
                    "action": action, "ticker": ticker,
                    "bid": float(bid), "ask": float(ask), "mid": None,
                    "wide_spread": True, "aggressive_price": float(agg),
                }))
                continue

            m = re_placed.search(line)
            if m:
                step, attempt, uuid = m.groups()
                events.append((i, ts_str, "placed", {
                    "step": int(step), "attempt": int(attempt), "uuid": uuid,
                }))
                continue

            m = re_market.search(line)
            if m:
                uuid = m.group(1)
                events.append((i, ts_str, "placed_market", {
                    "step": 3, "attempt": 1, "uuid": uuid,
                }))
                continue

    # Build UUID → ticker mapping from records (Alpaca order API has the symbol)
    uuid_to_ticker = {rec["order_id"]: rec["ticker"] for rec in records}

    # For each "placed" event, find the most recent quote for (ticker, step, attempt)
    uuid_to_quote = {}
    for idx, (line_num, ts_str, etype, data) in enumerate(events):
        if etype not in ("placed", "placed_market"):
            continue
        uuid = data["uuid"]
        if uuid not in uuid_to_ticker:
            continue
        ticker = uuid_to_ticker[uuid]
        step = data["step"]
        attempt = data.get("attempt", 1)

        # Scan backwards for most recent matching quote
        for j in range(idx - 1, -1, -1):
            _, _, prev_etype, prev_data = events[j]
            if prev_etype not in ("quote", "quote_agg"):
                continue
            if prev_data["ticker"] != ticker:
                continue
            if prev_data["step"] != step or prev_data["attempt"] != attempt:
                continue
            # Found the matching quote
            q = prev_data
            # Check if a wide_spread event occurred between quote and placed for this ticker
            wide = False
            for k in range(j + 1, idx):
                _, _, k_etype, k_data = events[k]
                if k_etype == "wide_spread" and k_data["ticker"] == ticker:
                    wide = True
                    break

            uuid_to_quote[uuid] = {
                "log_bid": q["bid"],
                "log_ask": q["ask"],
                "log_mid": q.get("mid"),
                "log_aggressive_price": q.get("aggressive_price"),
                "log_step": q["step"],
                "log_wide_spread": q["wide_spread"] or wide,
            }
            break
        else:
            # Step 3 market order — no quote line
            if etype == "placed_market":
                uuid_to_quote[uuid] = {
                    "log_bid": None, "log_ask": None, "log_mid": None,
                    "log_aggressive_price": None, "log_step": 3, "log_wide_spread": True,
                }

    logger.info(
        "Log quote lookup: matched %d / %d records",
        len(uuid_to_quote), len(records),
    )
    return uuid_to_quote


def _fetch_bar_at_time(alpaca_data_client, ticker: str, fill_time: datetime) -> dict:
    """Fetch 1-min Alpaca bar enclosing fill_time for OHLCV and VWAP."""
    if alpaca_data_client is None or fill_time is None:
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
        bars_resp = alpaca_data_client.get_stock_bars(req)
        bars = list(bars_resp.data.get(ticker, []))
        if not bars:
            return {}
        matching = [b for b in bars if b.timestamp <= fill_time]
        bar = matching[-1] if matching else bars[0]
        return {
            "bar_open": round(float(bar.open), 4),
            "bar_high": round(float(bar.high), 4),
            "bar_low": round(float(bar.low), 4),
            "bar_close": round(float(bar.close), 4),
            "bar_vwap": round(float(bar.vwap), 4) if bar.vwap else None,
            "bar_volume": int(bar.volume) if bar.volume else None,
            "bar_time": bar.timestamp.astimezone(_ET).strftime("%H:%M"),
        }
    except Exception as exc:
        logger.warning("Bar fetch failed for %s at %s: %s", ticker, fill_time, exc)
        return {}


def _fetch_nbbo_at_time(alpaca_data_client, ticker: str, fill_time: datetime) -> dict:
    """Fetch Alpaca historical NBBO quote nearest to fill_time."""
    if alpaca_data_client is None or fill_time is None:
        return {}
    try:
        from alpaca.data.requests import StockQuotesRequest
        start = fill_time - timedelta(seconds=30)
        end = fill_time + timedelta(seconds=5)
        req = StockQuotesRequest(
            symbol_or_symbols=ticker,
            start=start,
            end=end,
            limit=20,
        )
        quotes_resp = alpaca_data_client.get_stock_quotes(req)
        quotes = list(quotes_resp.data.get(ticker, []))
        if not quotes:
            return {}
        nearest = min(
            quotes,
            key=lambda q: abs((q.timestamp - fill_time).total_seconds()),
        )
        bid = float(nearest.bid_price) if nearest.bid_price else None
        ask = float(nearest.ask_price) if nearest.ask_price else None
        mid = round((bid + ask) / 2, 4) if bid and ask else None
        spread_pct = (
            round((ask - bid) / mid * 100, 2) if mid and mid > 0 else None
        )
        offset_s = round((nearest.timestamp - fill_time).total_seconds(), 1)
        return {
            "nbbo_bid": bid,
            "nbbo_ask": ask,
            "nbbo_mid": mid,
            "nbbo_spread_pct": spread_pct,
            "nbbo_offset_s": offset_s,
        }
    except Exception as exc:
        logger.warning("NBBO fetch failed for %s at %s: %s", ticker, fill_time, exc)
        return {}


def _enrich_records(alpaca_data_client, records: list, log_quotes: dict) -> list:
    """Add bar data, NBBO quotes, log quotes, and derived fill-quality metrics."""
    enriched = []
    for rec in records:
        row = dict(rec)
        fill = rec["fill_price"]

        bar = _fetch_bar_at_time(alpaca_data_client, rec["ticker"], rec["fill_time"])
        row.update(bar)

        nbbo = _fetch_nbbo_at_time(alpaca_data_client, rec["ticker"], rec["fill_time"])
        row.update(nbbo)

        log_q = log_quotes.get(rec["order_id"], {})
        row.update(log_q)

        if fill is not None:
            # Fill vs NBBO mid
            nbbo_mid = nbbo.get("nbbo_mid")
            if nbbo_mid:
                row["fill_vs_nbbo_mid"] = round(fill - nbbo_mid, 4)
                row["fill_vs_nbbo_mid_bps"] = round(
                    (fill - nbbo_mid) / nbbo_mid * 10000, 1
                )

            # Fill vs log mid (from FILL_ESC quote line)
            log_mid = log_q.get("log_mid")
            if log_mid:
                row["fill_vs_log_mid"] = round(fill - log_mid, 4)

            # Fill vs bar VWAP
            vwap = bar.get("bar_vwap")
            if vwap:
                row["fill_vs_vwap"] = round(fill - vwap, 4)
                row["fill_vs_vwap_bps"] = round(
                    (fill - vwap) / vwap * 10000, 1
                )

            # Fill inside bar range
            if bar.get("bar_low") and bar.get("bar_high"):
                row["fill_inside_bar"] = bar["bar_low"] <= fill <= bar["bar_high"]

        enriched.append(row)
    return enriched


_STOCK_COLS = [
    "fill_time", "side", "ticker", "qty",
    "fill_price", "limit_price", "slippage_bps",
    "log_step", "log_wide_spread",
    "log_bid", "log_ask", "log_mid", "log_aggressive_price",
    "fill_vs_log_mid",
    "nbbo_bid", "nbbo_ask", "nbbo_mid", "nbbo_spread_pct", "nbbo_offset_s",
    "fill_vs_nbbo_mid", "fill_vs_nbbo_mid_bps",
    "bar_open", "bar_high", "bar_low", "bar_close", "bar_vwap", "bar_volume",
    "fill_vs_vwap", "fill_vs_vwap_bps", "fill_inside_bar",
    "bar_time", "order_id", "trade_action",
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
    display_cols = [
        "fill_time", "side", "ticker", "qty",
        "fill_price", "slippage_bps", "log_step",
        "fill_vs_log_mid", "fill_vs_nbbo_mid", "fill_inside_bar",
    ]
    print(f"\n{'=' * 90}")
    print(f"  {title}")
    print(f"{'=' * 90}")
    header = "  ".join(f"{c:<20}" for c in display_cols)
    print("  " + header)
    print("  " + "-" * (len(header) + 2))
    for row in rows:
        def _fmt(v):
            if isinstance(v, datetime):
                return v.strftime("%H:%M:%S")
            if v is None:
                return "-"
            if isinstance(v, bool):
                return "Y" if v else "N"
            return str(v)
        line = "  ".join(f"{_fmt(row.get(c, '-')):<20}" for c in display_cols)
        print("  " + line)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Alpaca stock fills and save fill-quality CSV"
    )
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today ET)")
    parser.add_argument("--out-dir", default="logs/fills", help="Output directory root")
    parser.add_argument("--log-file", default=None,
                        help="Stock trade log for bid/ask enrichment "
                             "(default: logs/op_momentum_stock_YYYY-MM-DD.log)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--paper", dest="paper", action="store_true", default=True,
                       help="Use paper trading account (default)")
    group.add_argument("--live", dest="paper", action="store_false",
                       help="Use live trading account")
    args = parser.parse_args()

    target_date = (
        date.fromisoformat(args.date) if args.date
        else _now_et().date()
    )
    out_dir = Path(args.out_dir) / str(target_date)
    log_file = args.log_file or f"logs/op_momentum_stock_{target_date}.log"
    account_type = "paper" if args.paper else "live"

    logger.info("Fetching %s account orders for %s", account_type, target_date)

    from alpha_tech_tracker.op_momentum_strategy.config import _load_config
    _load_config()

    trading_client = _build_trading_client(paper=args.paper)
    alpaca_data_client = _build_alpaca_stock_data_client()

    raw_orders = _fetch_orders(trading_client, target_date)

    log_actions = _scan_log_for_actions(log_file)
    logger.info("Scanned log for actions: %d UUID→action mappings", len(log_actions))

    records = _parse_orders(raw_orders, target_date, log_actions=log_actions)

    if not records:
        print(f"No filled stock orders found for {target_date}.")
        return

    log_quotes = _parse_stock_quotes_from_log(log_file, records)
    records = _enrich_records(alpaca_data_client, records, log_quotes)

    _print_table(f"STOCK FILLS — {target_date} ({account_type})", records, _STOCK_COLS)

    out_path = out_dir / f"stocks_fills_{target_date}.csv"
    _write_csv(out_path, records, _STOCK_COLS)

    print(f"\nOutput: {out_path}")
    print(f"  Fills: {len(records)}")

    # Summary stats
    entries = [r for r in records if r["side"] == "ENTRY"]
    exits = [r for r in records if r["side"] == "EXIT"]
    step2_plus = [r for r in records if (r.get("log_step") or 0) >= 2]
    wide_spread = [r for r in records if r.get("log_wide_spread")]
    print(f"  Entries: {len(entries)}  Exits: {len(exits)}")
    print(f"  Step 2+ fills: {len(step2_plus)}")
    print(f"  Wide spread detected: {len(wide_spread)}")


if __name__ == "__main__":
    main()
