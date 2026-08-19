"""Fetch broker-truth realized P&L for a live trading account (Alpaca or TradeStation).

The engine's own DAILY TRADE SUMMARY can silently drop legs whose closing fill price
wasn't captured by the FILL_ESC path (e.g. a native broker stop, or a step3 market-order
race — see `bugs/BUGS.md` for the 2026-08-13/08-17/08-18 incidents). This script instead
reconstructs realized P&L directly from the broker's own fill/activity records, which are
authoritative regardless of what the engine logged.

Methodology: sum signed cash flow per fill (buy/buy_to_cover = cash out, sell/sell_short =
cash in), bucketed by the ET calendar date of the fill. This only equals P&L for days the
account ends flat in that symbol (true for this strategy — everything closes same-day) and
ignores non-trading cash flows (deposits/withdrawals), which the account activity filters
already exclude.

Note: Alpaca's `/v2/account/portfolio/history` looked like the obvious tool for this but has
a ~1-day settlement lag that silently omits the most recent trading day — use the
activity-based reconstruction here instead for anything but a full-month lookback.

Usage:
  # Alpaca (stock engine) — reads config.json next to this script by default
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_broker_pnl \
    --broker alpaca --start 2026-08-01 --end 2026-08-31

  # TradeStation (options engine) — point --config at that repo's config.json
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_broker_pnl \
    --broker tradestation --config /home/ec2-user/alpha_tech_tracker/alpha_tech_tracker/op_momentum_strategy/config.json \
    --start 2026-08-01 --end 2026-08-31 --group-by week

  # Monthly rollup
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_broker_pnl \
    --broker alpaca --start 2026-01-01 --end 2026-08-31 --group-by month
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

_ET = timezone(timedelta(hours=-4))  # EDT (UTC-4); adjust to -5 for EST
_DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "config.json")


def _parse_iso(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating non-6-digit fractional seconds.

    Python 3.8's datetime.fromisoformat requires exactly 0, 3, or 6 fractional
    digits; both Alpaca and TradeStation sometimes send other lengths (e.g. ".55").
    """
    raw = raw.replace("Z", "+00:00")
    if "." in raw:
        head, rest = raw.split(".", 1)
        sep = "+" if "+" in rest else "-"
        frac, tz = rest.split(sep, 1)
        raw = f"{head}.{(frac + '000000')[:6]}{sep}{tz}"
    return datetime.fromisoformat(raw)


# ---------------------------------------------------------------------------
# Alpaca
# ---------------------------------------------------------------------------

def _fetch_alpaca_activities(api_key: str, secret_key: str, activity_type: str, after: str) -> list:
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
    out = []
    while True:
        resp = requests.get(
            f"https://api.alpaca.markets/v2/account/activities/{activity_type}",
            headers=headers,
            params={"after": after, "direction": "asc", "page_size": 100},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        after = batch[-1]["id"]
    return out


def fetch_alpaca_daily_pnl(config: dict, start: date, end: date) -> dict:
    """Return {date_str: {"pnl": float, "fees": float, "symbols": set, "flat": bool}}."""
    alp = config["alpaca"]
    since = (datetime.combine(start, datetime.min.time(), tzinfo=_ET) - timedelta(seconds=1))
    since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    fills = _fetch_alpaca_activities(alp["api_key"], alp["secret_key"], "FILL", since_str)
    fees = _fetch_alpaca_activities(alp["api_key"], alp["secret_key"], "FEE", since_str)

    pnl = defaultdict(float)
    fee_total = defaultdict(float)
    buy_qty = defaultdict(float)
    sell_qty = defaultdict(float)
    symbols = defaultdict(set)

    for a in fills:
        dt = _parse_iso(a["transaction_time"]).astimezone(_ET)
        if not (start <= dt.date() <= end):
            continue
        d = dt.strftime("%Y-%m-%d")
        qty = float(a.get("qty") or 0)
        price = float(a.get("price") or 0)
        cash_flow = qty * price
        symbols[d].add(a.get("symbol"))
        side = a.get("side")
        if side in ("buy", "buy_to_cover"):
            pnl[d] -= cash_flow
            buy_qty[d] += qty
        elif side in ("sell", "sell_short"):
            pnl[d] += cash_flow
            sell_qty[d] += qty

    for a in fees:
        raw = a.get("date") or a.get("transaction_time")
        dt = _parse_iso(raw) if "T" in raw else datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=_ET)
        dt = dt.astimezone(_ET)
        if not (start <= dt.date() <= end):
            continue
        fee_total[dt.strftime("%Y-%m-%d")] += float(a.get("net_amount") or 0)

    days = sorted(set(pnl) | set(fee_total))
    return {
        d: {
            "pnl": pnl[d] + fee_total[d],
            "fees": fee_total[d],
            "symbols": symbols[d],
            "flat": buy_qty[d] == sell_qty[d],
        }
        for d in days
    }


# ---------------------------------------------------------------------------
# TradeStation
# ---------------------------------------------------------------------------

def _parse_ts_dt(raw: str):
    if not raw:
        return None
    is_utc = raw.endswith("Z")
    stripped = raw.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(stripped, fmt)
            return dt.replace(tzinfo=timezone.utc).astimezone(_ET) if is_utc else dt.replace(tzinfo=_ET)
        except ValueError:
            continue
    return None


def fetch_tradestation_daily_pnl(config: dict, start: date, end: date) -> dict:
    """Return {date_str: {"pnl": float, "symbols": set, "flat": bool}}.

    TradeStation's `historicalorders` endpoint excludes same-day fills, so today's
    orders (if `end` includes today) are fetched separately from `/orders` and merged.
    """
    from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient

    ts_creds = config.get("tradestation_credentials", {})
    os.environ.setdefault("TS_CLIENT_ID", ts_creds.get("client_id", ""))
    os.environ.setdefault("TS_CLIENT_SECRET", ts_creds.get("client_secret", ""))

    ts_cfg = config.get("tradestation", {})
    client = TradeStationAPIClient(
        environment=ts_cfg.get("environment", "live"),
        selected_account_key=ts_cfg.get("account_key"),
    )
    client.restore_session(config["tradestation_session"])
    account_key = client._get_account_key()

    since_str = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_orders = {}
    resp = client._session.get(
        client._v3_base_url + f"/brokerage/accounts/{account_key}/historicalorders",
        params={"since": since_str, "pageSize": 600},
    )
    data = resp.json()
    for o in (data if isinstance(data, list) else data.get("Orders", [])):
        all_orders[o.get("OrderID")] = o

    resp2 = client._session.get(
        client._v3_base_url + f"/brokerage/accounts/{account_key}/orders",
        params={"pageSize": 600},
    )
    data2 = resp2.json()
    for o in (data2 if isinstance(data2, list) else data2.get("Orders", [])):
        all_orders[o.get("OrderID")] = o

    pnl = defaultdict(float)
    buy_qty = defaultdict(float)
    sell_qty = defaultdict(float)
    symbols = defaultdict(set)

    for o in all_orders.values():
        if o.get("Status") not in ("FLL", "FLP"):
            continue
        fill_time = _parse_ts_dt(o.get("ClosedDateTime") or o.get("FilledDateTime")) or _parse_ts_dt(o.get("OpenedDateTime"))
        if fill_time is None or not (start <= fill_time.date() <= end):
            continue
        d = fill_time.strftime("%Y-%m-%d")
        for leg in o.get("Legs", []):
            symbol = (leg.get("Symbol") or "").replace(" ", "")
            side = leg.get("BuyOrSell", "")
            try:
                qty = float(leg.get("ExecQuantity") or leg.get("QuantityOrdered"))
                price = float(leg.get("ExecutionPrice") or leg.get("ExecPrice"))
            except (TypeError, ValueError):
                continue
            if qty <= 0 or price <= 0:
                continue
            cash_flow = qty * price
            symbols[d].add(symbol)
            if side in ("Buy", "BuyToCover"):
                pnl[d] -= cash_flow
                buy_qty[d] += qty
            elif side in ("Sell", "SellShort"):
                pnl[d] += cash_flow
                sell_qty[d] += qty

    days = sorted(pnl.keys())
    return {
        d: {"pnl": pnl[d], "symbols": symbols[d], "flat": buy_qty[d] == sell_qty[d]}
        for d in days
    }


# ---------------------------------------------------------------------------
# Aggregation / reporting
# ---------------------------------------------------------------------------

def _bucket_key(day_str: str, group_by: str) -> str:
    d = date.fromisoformat(day_str)
    if group_by == "day":
        return day_str
    if group_by == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if group_by == "month":
        return d.strftime("%Y-%m")
    raise ValueError(f"Unknown group_by: {group_by}")


def print_report(daily: dict, group_by: str, label: str):
    buckets = defaultdict(float)
    for day_str, row in sorted(daily.items()):
        buckets[_bucket_key(day_str, group_by)] += row["pnl"]

    print(f"\n{label} — grouped by {group_by}")
    print(f"{'Period':<12} {'P&L':>14}")
    total = 0.0
    for key, pnl in buckets.items():
        print(f"{key:<12} {pnl:>14,.2f}")
        total += pnl
    print("-" * 27)
    print(f"{'TOTAL':<12} {total:>14,.2f}")

    non_flat = [d for d, row in daily.items() if not row["flat"]]
    if non_flat:
        print(f"\nWARNING: non-flat end-of-day detected on {non_flat} — daily P&L for "
              "these days does not fully capture realized P&L (a position carried over).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broker", required=True, choices=["alpaca", "tradestation"])
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="Path to config.json (defaults to the copy next to this script)")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--group-by", default="day", choices=["day", "week", "month"])
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if args.broker == "alpaca":
        daily = fetch_alpaca_daily_pnl(config, start, end)
        label = "Alpaca account (stock engine)"
    else:
        daily = fetch_tradestation_daily_pnl(config, start, end)
        label = "TradeStation account (options engine)"

    if not daily:
        print(f"No fills found for {args.broker} between {start} and {end}.")
        return

    print_report(daily, args.group_by, label)


if __name__ == "__main__":
    main()
