"""List afternoon window trades (A2 ~1:20 PM, A3 ~3:20 PM) that stopped out
quickly (within 15 minutes), from both TS options and Alpaca stocks.

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python alpha_tech_tracker/op_momentum_strategy/analyze_afternoon_stops.py [--weeks N]
"""

import argparse
import json
import pathlib
import pytz
import requests
from collections import defaultdict
from datetime import date, datetime, timedelta

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from alpha_tech_tracker.op_momentum_strategy.config import _load_config, build_execution_client
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

ET = pytz.timezone("America/New_York")

# Afternoon window entry time boundaries (ET hour)
A2_START_HOUR = 13   # ~1:20 PM entry
A2_END_HOUR   = 15
A3_START_HOUR = 15   # ~3:20 PM entry
A3_END_HOUR   = 16

QUICK_STOP_MINUTES = 15


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dt(ts: str) -> datetime:
    """Parse ISO timestamp to UTC-aware datetime."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _et_str(dt: datetime) -> str:
    if dt is None:
        return ""
    return dt.astimezone(ET).strftime("%Y-%m-%d %H:%M")


def _et_date(dt) -> str:
    if dt is None:
        return ""
    if hasattr(dt, "astimezone"):
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    return str(dt)[:10]


def _et_date_from_iso(ts: str) -> str:
    dt = _parse_dt(ts)
    return dt.astimezone(ET).strftime("%Y-%m-%d") if dt else ts[:10]


def _window_label(dt: datetime) -> str:
    """Return A2, A3, or None based on ET entry time."""
    if dt is None:
        return None
    et = dt.astimezone(ET)
    h = et.hour
    if A2_START_HOUR <= h < A2_END_HOUR:
        return "A2"
    if A3_START_HOUR <= h < A3_END_HOUR:
        return "A3"
    return None


def _duration_min(open_ts: str, close_ts: str) -> float:
    """Return duration between two ISO timestamps in minutes, or None."""
    t1 = _parse_dt(open_ts)
    t2 = _parse_dt(close_ts)
    if t1 and t2:
        return (t2 - t1).total_seconds() / 60
    return None


# ── TradeStation ──────────────────────────────────────────────────────────────

def _fetch_ts_fills(client, since: str) -> list:
    account_key = client._get_account_key()

    hist = []
    params = {"since": since, "pageSize": 500}
    while True:
        resp = client._session.get(
            client._v3_base_url + f"/brokerage/accounts/{account_key}/historicalorders",
            params=params,
        )
        data = client._parse(resp)
        page = data if isinstance(data, list) else data.get("Orders", [])
        hist.extend(page)
        next_token = data.get("NextToken") if isinstance(data, dict) else None
        if not next_token or not page:
            break
        oldest = min(
            (o.get("ClosedDateTime", "") or o.get("OpenedDateTime", ""))[:10]
            for o in page if o.get("ClosedDateTime") or o.get("OpenedDateTime")
        )
        if oldest and oldest < since:
            break
        params = {"since": since, "pageSize": 500, "NextToken": next_token}

    resp2 = client._session.get(
        client._v3_base_url + f"/brokerage/accounts/{account_key}/orders",
        params={"pageSize": 500},
    )
    data2 = client._parse(resp2)
    today_orders = data2 if isinstance(data2, list) else data2.get("Orders", [])

    seen_ids = {o.get("OrderID") for o in hist}
    combined = hist + [o for o in today_orders if o.get("OrderID") not in seen_ids]

    fills = []
    for raw in combined:
        if raw.get("Status") not in ("FLL", "FLP"):
            continue
        price_raw = raw.get("FilledPrice") or raw.get("AverageFillPrice")
        if not price_raw:
            continue
        leg = (raw.get("Legs") or [{}])[0]
        symbol = leg.get("Symbol") or raw.get("Symbol", "")
        buy_or_sell = leg.get("BuyOrSell", "").lower()
        open_or_close = leg.get("OpenOrClose", "").lower()
        qty_raw = leg.get("ExecQuantity") or raw.get("ExecuteQuantity") or 0
        filled_at = raw.get("ClosedDateTime") or raw.get("OpenedDateTime") or raw.get("TimeStamp", "")
        fills.append({
            "order_id": raw.get("OrderID", ""),
            "symbol": symbol,
            "is_buy": buy_or_sell == "buy",
            "is_open": open_or_close == "open",
            "qty": float(qty_raw),
            "price": float(price_raw),
            "filled_at": filled_at,
            "date": _et_date_from_iso(filled_at) if filled_at else "",
        })

    fills.sort(key=lambda x: x["filled_at"])
    return fills


def _is_option(symbol: str) -> bool:
    parts = symbol.split()
    return len(parts) == 2 and len(parts[1]) > 4


def _underlying(symbol: str) -> str:
    return symbol.split()[0] if _is_option(symbol) else symbol


def _option_direction(symbol: str) -> str:
    parts = symbol.split()
    if len(parts) == 2 and len(parts[1]) >= 7:
        return "CALL" if parts[1][6] == "C" else "PUT"
    return "CALL"


def _pair_ts_trades(fills: list) -> list:
    open_lots: dict[str, list] = defaultdict(list)
    trades = []

    for f in fills:
        sym = f["symbol"]
        if not _is_option(sym):
            continue
        if f["is_buy"] and f["is_open"]:
            open_lots[sym].append(dict(f))
        elif not f["is_buy"] and not f["is_open"]:
            qty_to_close = f["qty"]
            while qty_to_close > 0 and open_lots[sym]:
                opener = open_lots[sym][0]
                matched = min(opener["qty"], qty_to_close)
                pnl = (f["price"] - opener["price"]) * matched * 100
                open_dt = _parse_dt(opener["filled_at"])
                trades.append({
                    "source": "TS Options",
                    "symbol": sym,
                    "ticker": _underlying(sym),
                    "direction": _option_direction(sym),
                    "open_date": opener["date"],
                    "close_date": f["date"],
                    "open_filled_at": opener["filled_at"],
                    "close_filled_at": f["filled_at"],
                    "open_et": _et_str(_parse_dt(opener["filled_at"])),
                    "close_et": _et_str(_parse_dt(f["filled_at"])),
                    "window": _window_label(open_dt),
                    "duration_min": _duration_min(opener["filled_at"], f["filled_at"]),
                    "open_price": opener["price"],
                    "close_price": f["price"],
                    "qty": matched,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((f["price"] - opener["price"]) / opener["price"] * 100, 2),
                    "win": pnl > 0,
                })
                opener["qty"] -= matched
                qty_to_close -= matched
                if opener["qty"] <= 0:
                    open_lots[sym].pop(0)

    return trades


# ── Alpaca ────────────────────────────────────────────────────────────────────

def _fetch_alpaca_fills(client: AlpacaAPIClient, since: datetime) -> list:
    request = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        after=since,
        limit=500,
    )
    orders = client._trading_client.get_orders(request)

    fills = []
    for o in orders:
        if o.filled_avg_price is None or o.filled_qty is None:
            continue
        filled_at = o.filled_at.isoformat() if o.filled_at else ""
        fills.append({
            "order_id": str(o.id),
            "symbol": o.symbol,
            "is_buy": o.side.value == "buy",
            "qty": float(o.filled_qty),
            "price": float(o.filled_avg_price),
            "filled_at": filled_at,
            "date": _et_date(o.filled_at),
        })

    fills.sort(key=lambda x: x["filled_at"])
    return fills


def _pair_alpaca_trades(fills: list) -> list:
    long_q: dict[str, list] = defaultdict(list)
    short_q: dict[str, list] = defaultdict(list)
    trades = []

    for f in fills:
        sym = f["symbol"]
        remaining = f["qty"]

        if f["is_buy"]:
            while remaining > 0 and short_q[sym]:
                opener = short_q[sym][0]
                matched = min(opener["qty"], remaining)
                pnl = (opener["price"] - f["price"]) * matched
                open_dt = _parse_dt(opener["filled_at"])
                trades.append({
                    "source": "Alpaca Stock",
                    "symbol": sym,
                    "ticker": sym,
                    "direction": "SHORT",
                    "open_date": opener["date"],
                    "close_date": f["date"],
                    "open_filled_at": opener["filled_at"],
                    "close_filled_at": f["filled_at"],
                    "open_et": _et_str(open_dt),
                    "close_et": _et_str(_parse_dt(f["filled_at"])),
                    "window": _window_label(open_dt),
                    "duration_min": _duration_min(opener["filled_at"], f["filled_at"]),
                    "open_price": opener["price"],
                    "close_price": f["price"],
                    "qty": matched,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((opener["price"] - f["price"]) / opener["price"] * 100, 2),
                    "win": pnl > 0,
                })
                opener["qty"] -= matched
                remaining -= matched
                if opener["qty"] <= 0:
                    short_q[sym].pop(0)
            if remaining > 0:
                long_q[sym].append({"qty": remaining, "price": f["price"],
                                    "date": f["date"], "filled_at": f["filled_at"]})

        else:
            while remaining > 0 and long_q[sym]:
                opener = long_q[sym][0]
                matched = min(opener["qty"], remaining)
                pnl = (f["price"] - opener["price"]) * matched
                open_dt = _parse_dt(opener["filled_at"])
                trades.append({
                    "source": "Alpaca Stock",
                    "symbol": sym,
                    "ticker": sym,
                    "direction": "LONG",
                    "open_date": opener["date"],
                    "close_date": f["date"],
                    "open_filled_at": opener["filled_at"],
                    "close_filled_at": f["filled_at"],
                    "open_et": _et_str(open_dt),
                    "close_et": _et_str(_parse_dt(f["filled_at"])),
                    "window": _window_label(open_dt),
                    "duration_min": _duration_min(opener["filled_at"], f["filled_at"]),
                    "open_price": opener["price"],
                    "close_price": f["price"],
                    "qty": matched,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((f["price"] - opener["price"]) / opener["price"] * 100, 2),
                    "win": pnl > 0,
                })
                opener["qty"] -= matched
                remaining -= matched
                if opener["qty"] <= 0:
                    long_q[sym].pop(0)
            if remaining > 0:
                short_q[sym].append({"qty": remaining, "price": f["price"],
                                     "date": f["date"], "filled_at": f["filled_at"]})

    return trades


# ── Display ───────────────────────────────────────────────────────────────────

def _print_section(title: str):
    print(f"\n{'━'*80}")
    print(f"  {title}")
    print(f"{'━'*80}")


def analyze_afternoon_stops(all_trades: list):
    afternoon = [t for t in all_trades if t["window"] in ("A2", "A3")]

    if not afternoon:
        print("\nNo afternoon window trades found.")
        return

    quick = [t for t in afternoon if t["duration_min"] is not None
             and t["duration_min"] <= QUICK_STOP_MINUTES and not t["win"]]
    slow  = [t for t in afternoon if t not in quick]

    _print_section(f"ALL AFTERNOON TRADES  (A2=1:15 PM window, A3=3:15 PM window)  [{len(afternoon)} trades]")
    print(f"\n  {'Source':<14} {'Date':<12} {'W':<4} {'Ticker':<8} {'Dir':<6} "
          f"{'Open ET':<17} {'Close ET':<17} {'Min':>5}  {'P&L':>9}  {'%':>7}")
    print(f"  {'-'*100}")

    for t in sorted(afternoon, key=lambda x: x["open_filled_at"]):
        dur = f"{t['duration_min']:.0f}" if t["duration_min"] is not None else "?"
        flag = " ◄ QUICK STOP" if t in quick else ""
        result = "W" if t["win"] else "L"
        print(f"  {t['source']:<14} {t['open_date']:<12} {result:<4} {t['ticker']:<8} "
              f"{t['direction']:<6} {t['open_et']:<17} {t['close_et']:<17} {dur:>5}"
              f"  {t['pnl']:>+9.2f}  {t['pnl_pct']:>+7.2f}%{flag}")

    _print_section(f"QUICK STOPS  (≤{QUICK_STOP_MINUTES} min, losing)  [{len(quick)} trades]")
    if not quick:
        print("  None found.")
    else:
        total_pnl = sum(t["pnl"] for t in quick)
        print(f"\n  {'Source':<14} {'Date':<12} {'Ticker':<8} {'Dir':<6} "
              f"{'Open ET':<17} {'Close ET':<17} {'Min':>5}  {'P&L':>9}  {'%':>7}")
        print(f"  {'-'*97}")
        for t in sorted(quick, key=lambda x: x["open_filled_at"]):
            dur = f"{t['duration_min']:.0f}"
            print(f"  {t['source']:<14} {t['open_date']:<12} {t['ticker']:<8} "
                  f"{t['direction']:<6} {t['open_et']:<17} {t['close_et']:<17} {dur:>5}"
                  f"  {t['pnl']:>+9.2f}  {t['pnl_pct']:>+7.2f}%")
        print(f"  {'-'*97}")
        print(f"  Total quick-stop P&L: ${total_pnl:+,.2f}  over {len(quick)} trades")

    _print_section("SUMMARY BY WINDOW")
    for win_label in ("A2", "A3"):
        wt = [t for t in afternoon if t["window"] == win_label]
        if not wt:
            continue
        wq = [t for t in wt if t in quick]
        total = sum(t["pnl"] for t in wt)
        wins_n = sum(1 for t in wt if t["win"])
        print(f"\n  {win_label}: {len(wt)} trades  {wins_n}W/{len(wt)-wins_n}L  "
              f"total P&L ${total:+,.2f}   quick stops: {len(wq)}"
              f"  (${sum(t['pnl'] for t in wq):+,.2f})")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=2,
                        help="How many weeks back to fetch (default: 2)")
    args = parser.parse_args()

    _load_config()
    ts_client = build_execution_client(broker="tradestation")

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    since_date = week_start - timedelta(weeks=args.weeks - 1)
    since_str = (since_date - timedelta(days=1)).isoformat()

    print(f"Fetching TS option fills since {since_date} ({args.weeks} weeks)...")

    ts_fills = _fetch_ts_fills(ts_client, since_str)
    ts_week_fills = [f for f in ts_fills if f["date"] >= since_date.isoformat()]
    ts_trades = _pair_ts_trades(ts_week_fills)
    print(f"TS: {len(ts_trades)} closed option trades")

    analyze_afternoon_stops(ts_trades)
