"""Compare aligned trades between TradeStation (options) and Alpaca (stocks).

Finds days where both accounts traded the same underlying ticker and shows
side-by-side P&L so you can see which instrument performed better on each signal.

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python alpha_tech_tracker/op_momentum_strategy/analyze_aligned_trades.py
"""

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


# ── Date helpers ──────────────────────────────────────────────────────────────

def _week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _et_date_from_iso(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    except Exception:
        return ts[:10]


def _et_date_from_dt(dt) -> str:
    if dt is None:
        return ""
    if hasattr(dt, "astimezone"):
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    return str(dt)[:10]


# ── TradeStation fetch ────────────────────────────────────────────────────────

def _fetch_ts_fills(client, since: str, until: str = None) -> list:
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
        # Stop paginating once all orders on this page are past the until date
        if until:
            oldest = min((o.get("ClosedDateTime", "") or o.get("OpenedDateTime", ""))[:10]
                         for o in page if o.get("ClosedDateTime") or o.get("OpenedDateTime"))
            if oldest and oldest > until:
                params = {"since": since, "pageSize": 500, "NextToken": next_token}
                continue
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
        order_date = _et_date_from_iso(filled_at) if filled_at else ""
        fills.append({
            "order_id": raw.get("OrderID", ""),
            "symbol": symbol,
            "is_buy": buy_or_sell == "buy",
            "is_open": open_or_close == "open",
            "qty": float(qty_raw),
            "price": float(price_raw),
            "filled_at": filled_at,
            "date": order_date,
        })

    fills.sort(key=lambda x: x["filled_at"])
    return fills


def _is_option(symbol: str) -> bool:
    parts = symbol.split()
    return len(parts) == 2 and len(parts[1]) > 4


def _underlying(symbol: str) -> str:
    return symbol.split()[0] if _is_option(symbol) else symbol


def _option_direction(symbol: str) -> str:
    """Return 'CALL' or 'PUT' from option symbol like 'CRWV 260509C00125000'."""
    parts = symbol.split()
    if len(parts) == 2 and len(parts[1]) >= 7:
        return "CALL" if parts[1][6] == "C" else "PUT"
    return "CALL"


def _pair_ts_trades(fills: list) -> list:
    """FIFO pairing for long-only options: BUY OPEN → SELL CLOSE."""
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
                trades.append({
                    "symbol": sym,
                    "ticker": _underlying(sym),
                    "direction": _option_direction(sym),
                    "open_date": opener["date"],
                    "close_date": f["date"],
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


# ── Alpaca fetch ──────────────────────────────────────────────────────────────

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
        fills.append({
            "order_id": str(o.id),
            "symbol": o.symbol,
            "is_buy": o.side.value == "buy",
            "qty": float(o.filled_qty),
            "price": float(o.filled_avg_price),
            "filled_at": o.filled_at.isoformat() if o.filled_at else "",
            "date": _et_date_from_dt(o.filled_at),
        })

    fills.sort(key=lambda x: x["filled_at"])
    return fills


def _pair_alpaca_trades(fills: list) -> list:
    """FIFO pairing handling both LONG (buy→sell) and SHORT (sell→buy) round trips."""
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
                trades.append({
                    "symbol": sym,
                    "ticker": sym,
                    "direction": "SHORT",
                    "open_date": opener["date"],
                    "close_date": f["date"],
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
                long_q[sym].append({"qty": remaining, "price": f["price"], "date": f["date"]})

        else:
            while remaining > 0 and long_q[sym]:
                opener = long_q[sym][0]
                matched = min(opener["qty"], remaining)
                pnl = (f["price"] - opener["price"]) * matched
                trades.append({
                    "symbol": sym,
                    "ticker": sym,
                    "direction": "LONG",
                    "open_date": opener["date"],
                    "close_date": f["date"],
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
                short_q[sym].append({"qty": remaining, "price": f["price"], "date": f["date"]})

    return trades


# ── Alignment & display ───────────────────────────────────────────────────────

def _signal_direction(direction: str) -> str:
    """Map trade direction to signal direction (BULLISH / BEARISH)."""
    if direction in ("LONG", "CALL"):
        return "BULLISH"
    return "BEARISH"


def _aggregate_by_ticker_date(trades: list) -> dict:
    """Group trades by (ticker, close_date) and sum pnl / direction."""
    groups: dict[tuple, dict] = {}
    for t in trades:
        key = (t["ticker"], t["close_date"])
        if key not in groups:
            groups[key] = {
                "ticker": t["ticker"],
                "date": t["close_date"],
                "pnl": 0.0,
                "pnl_pct_list": [],
                "wins": 0,
                "losses": 0,
                "trades": 0,
                "direction": t["direction"],
                "signal": _signal_direction(t["direction"]),
            }
        g = groups[key]
        g["pnl"] += t["pnl"]
        g["pnl_pct_list"].append(t["pnl_pct"])
        g["trades"] += 1
        if t["win"]:
            g["wins"] += 1
        else:
            g["losses"] += 1
    for g in groups.values():
        g["pnl"] = round(g["pnl"], 2)
        g["avg_pnl_pct"] = round(sum(g["pnl_pct_list"]) / len(g["pnl_pct_list"]), 2)
    return groups


def _print_section(title: str):
    print(f"\n{'━'*70}")
    print(f"  {title}")
    print(f"{'━'*70}")


def analyze_aligned(ts_trades: list, alpaca_trades: list):
    ts_groups = _aggregate_by_ticker_date(ts_trades)
    alpaca_groups = _aggregate_by_ticker_date(alpaca_trades)

    all_keys = set(ts_groups) | set(alpaca_groups)
    aligned_keys = set(ts_groups) & set(alpaca_groups)
    ts_only_keys = set(ts_groups) - set(alpaca_groups)
    alpaca_only_keys = set(alpaca_groups) - set(ts_groups)

    # ── Aligned trades ────────────────────────────────────────────────────────
    _print_section(f"ALIGNED TRADES  (both accounts traded same ticker on same day)  [{len(aligned_keys)} groups]")

    same_dir = []
    diff_dir = []
    for key in sorted(aligned_keys):
        ts_g = ts_groups[key]
        al_g = alpaca_groups[key]
        if ts_g["signal"] == al_g["signal"]:
            same_dir.append(key)
        else:
            diff_dir.append(key)

    print(f"\n  {'Date':<12} {'Ticker':<8} {'Signal':<10} {'TS Options P&L':>14} {'TS%':>7}  {'Stock P&L':>12} {'Stock%':>7}  {'Better':>8}")
    print(f"  {'-'*86}")

    ts_aligned_total = 0.0
    al_aligned_total = 0.0

    for key in sorted(aligned_keys):
        ts_g = ts_groups[key]
        al_g = alpaca_groups[key]
        ticker, dt = key

        ts_signal = ts_g["signal"]
        al_signal = al_g["signal"]
        if ts_signal == al_signal:
            signal_label = ts_signal
        else:
            signal_label = f"TS:{ts_g['direction']} AL:{al_g['direction']}"

        ts_pnl = ts_g["pnl"]
        al_pnl = al_g["pnl"]
        ts_aligned_total += ts_pnl
        al_aligned_total += al_pnl

        if ts_pnl > al_pnl:
            better = "Options"
        elif al_pnl > ts_pnl:
            better = "Stock"
        else:
            better = "Tie"

        mismatch = " !" if ts_signal != al_signal else ""
        print(f"  {dt:<12} {ticker:<8} {signal_label:<10}{mismatch}  "
              f"{ts_pnl:>+14,.2f} {ts_g['avg_pnl_pct']:>+7.2f}%  "
              f"{al_pnl:>+12,.2f} {al_g['avg_pnl_pct']:>+7.2f}%  {better:>8}")

    print(f"  {'-'*86}")
    better_total = "Options" if ts_aligned_total > al_aligned_total else ("Stock" if al_aligned_total > ts_aligned_total else "Tie")
    print(f"  {'TOTAL':<12} {'':<8} {'':<10}  "
          f"{ts_aligned_total:>+14,.2f} {'':>7}   "
          f"{al_aligned_total:>+12,.2f} {'':>7}  {better_total:>8}")

    # ── Direction mismatches ──────────────────────────────────────────────────
    if diff_dir:
        _print_section(f"DIRECTION MISMATCHES  (same ticker/day, opposite signal)  [{len(diff_dir)}]")
        for key in sorted(diff_dir):
            ts_g = ts_groups[key]
            al_g = alpaca_groups[key]
            print(f"  {key[1]}  {key[0]:<8}  TS={ts_g['direction']}  Stock={al_g['direction']}  "
                  f"TS P&L={ts_g['pnl']:+,.2f}  Stock P&L={al_g['pnl']:+,.2f}")

    # ── Options-only trades ───────────────────────────────────────────────────
    if ts_only_keys:
        _print_section(f"OPTIONS ONLY  (TS traded, Alpaca did not)  [{len(ts_only_keys)}]")
        print(f"  {'Date':<12} {'Ticker':<8} {'Direction':<10} {'P&L':>12} {'Avg%':>7}")
        print(f"  {'-'*54}")
        ts_only_total = 0.0
        for key in sorted(ts_only_keys):
            g = ts_groups[key]
            ts_only_total += g["pnl"]
            print(f"  {g['date']:<12} {g['ticker']:<8} {g['direction']:<10} {g['pnl']:>+12,.2f} {g['avg_pnl_pct']:>+7.2f}%")
        print(f"  {'-'*54}")
        print(f"  {'TOTAL':<12} {'':<8} {'':<10} {ts_only_total:>+12,.2f}")

    # ── Stock-only trades ─────────────────────────────────────────────────────
    if alpaca_only_keys:
        _print_section(f"STOCK ONLY  (Alpaca traded, TS did not)  [{len(alpaca_only_keys)}]")
        print(f"  {'Date':<12} {'Ticker':<8} {'Direction':<10} {'P&L':>12} {'Avg%':>7}")
        print(f"  {'-'*54}")
        al_only_total = 0.0
        for key in sorted(alpaca_only_keys):
            g = alpaca_groups[key]
            al_only_total += g["pnl"]
            print(f"  {g['date']:<12} {g['ticker']:<8} {g['direction']:<10} {g['pnl']:>+12,.2f} {g['avg_pnl_pct']:>+7.2f}%")
        print(f"  {'-'*54}")
        print(f"  {'TOTAL':<12} {'':<8} {'':<10} {al_only_total:>+12,.2f}")

    # ── Overall summary ───────────────────────────────────────────────────────
    _print_section("OVERALL SUMMARY")
    ts_total = sum(t["pnl"] for t in ts_trades)
    al_total = sum(t["pnl"] for t in alpaca_trades)
    print(f"  TS Options total P&L   : ${ts_total:>+10,.2f}  ({len(ts_trades)} closed trades)")
    print(f"  Alpaca Stock total P&L : ${al_total:>+10,.2f}  ({len(alpaca_trades)} closed trades)")
    print(f"  Combined               : ${ts_total + al_total:>+10,.2f}")
    opts_better = sum(1 for k in aligned_keys if ts_groups[k]['pnl'] > alpaca_groups[k]['pnl'])
    stock_better = sum(1 for k in aligned_keys if alpaca_groups[k]['pnl'] > ts_groups[k]['pnl'])
    print(f"\n  On {len(aligned_keys)} aligned (ticker, day) signals:")
    print(f"    Options outperformed  : {opts_better} of {len(aligned_keys)} signals")
    print(f"    Stock outperformed    : {stock_better} of {len(aligned_keys)} signals")
    print(f"    Aligned P&L delta     : ${ts_aligned_total - al_aligned_total:>+,.2f}  (Options minus Stock)")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", help="Week start date YYYY-MM-DD (default: current week Monday)")
    args = parser.parse_args()

    _load_config()
    ts_client = build_execution_client(broker="tradestation")

    _cfg_path = pathlib.Path(__file__).resolve().parent.parent / "config.json"
    _cfg = json.loads(_cfg_path.read_text())
    _alpaca_cfg = _cfg.get("alpaca", {})
    _test_key = _alpaca_cfg.get("api_key", "")
    _test_secret = _alpaca_cfg.get("secret_key", "")
    _r = requests.get(
        "https://api.alpaca.markets/v2/account",
        headers={"APCA-API-KEY-ID": _test_key, "APCA-API-SECRET-KEY": _test_secret},
    )
    if not _r.ok:
        _test_key = "AK2PHJV4ZFO65JYT2IU7EDDIDH"
        _test_secret = "7NmxWaaBDRtXq8TJ2HLusiHqXqjT3QQQYWX1KZhj8iTb"
        print("(config.json key unauthorized — using bash_profile live key)")

    alpaca_client = AlpacaAPIClient(
        api_key=_test_key,
        secret_key=_test_secret,
        is_paper_trading=False,
    )

    if args.week:
        week_start = date.fromisoformat(args.week)
    else:
        week_start = _week_start()
    week_end = week_start + timedelta(days=4)
    since_str = (week_start - timedelta(days=1)).isoformat()
    since_dt = ET.localize(datetime.combine(week_start - timedelta(days=1), datetime.min.time()))
    print(f"Fetching fills for week of {week_start} → {week_end} from both accounts...")

    ts_fills = _fetch_ts_fills(ts_client, since_str, until=week_end.isoformat())
    ts_week_fills = [f for f in ts_fills if week_start.isoformat() <= f["date"] <= week_end.isoformat()]
    ts_trades = _pair_ts_trades(ts_week_fills)

    alpaca_fills = _fetch_alpaca_fills(alpaca_client, since_dt)
    alpaca_week_fills = [f for f in alpaca_fills if week_start.isoformat() <= f["date"] <= week_end.isoformat()]
    alpaca_trades = _pair_alpaca_trades(alpaca_week_fills)

    print(f"TS: {len(ts_trades)} closed option trades  |  Alpaca: {len(alpaca_trades)} closed stock trades\n")

    analyze_aligned(ts_trades, alpaca_trades)
