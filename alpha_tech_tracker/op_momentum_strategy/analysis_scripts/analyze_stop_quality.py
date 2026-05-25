"""For each losing afternoon option trade, fetch 5-min stock bars and determine:
  - Did price continue against the trade direction after stop? → stop was helpful
  - Did price recover back in the trade direction?           → stop was too tight

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python alpha_tech_tracker/op_momentum_strategy/analyze_stop_quality.py [--weeks N]
"""

import argparse
import json
import pathlib
import pytz
import requests
from collections import defaultdict
from datetime import date, datetime, timedelta

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.enums import QueryOrderStatus

from alpha_tech_tracker.op_momentum_strategy.config import _load_config, build_execution_client

ET = pytz.timezone("America/New_York")

A2_START_HOUR = 13
A2_END_HOUR   = 15
A3_START_HOUR = 15
A3_END_HOUR   = 16
QUICK_STOP_MINUTES = 15
# How far after exit to look for recovery/continuation
LOOKFORWARD_BARS = 6   # 6 × 5 min = 30 min
# Threshold: price must move this % to be classified as clear continuation/recovery
MOVE_THRESHOLD_PCT = 0.15


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dt(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _et_str(dt: datetime) -> str:
    return dt.astimezone(ET).strftime("%H:%M") if dt else ""


def _et_date_from_iso(ts: str) -> str:
    dt = _parse_dt(ts)
    return dt.astimezone(ET).strftime("%Y-%m-%d") if dt else ts[:10]


def _window_label(dt: datetime) -> str:
    if dt is None:
        return None
    h = dt.astimezone(ET).hour
    if A2_START_HOUR <= h < A2_END_HOUR:
        return "A2"
    if A3_START_HOUR <= h < A3_END_HOUR:
        return "A3"
    return None


def _duration_min(open_ts: str, close_ts: str) -> float:
    t1 = _parse_dt(open_ts)
    t2 = _parse_dt(close_ts)
    return (t2 - t1).total_seconds() / 60 if t1 and t2 else None


# ── TradeStation fetch (same as analyze_afternoon_stops) ──────────────────────

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
                    "ticker": _underlying(sym),
                    "direction": _option_direction(sym),
                    "open_date": opener["date"],
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


# ── Bar fetching ──────────────────────────────────────────────────────────────

def _fetch_bars_for_date(bar_client: StockHistoricalDataClient,
                          tickers: list, dt: date) -> dict:
    """Fetch all 5-min bars for a list of tickers on a given date. Returns
    dict[ticker] -> list of (timestamp_et, open, high, low, close)."""
    start = ET.localize(datetime.combine(dt, datetime.min.time()).replace(hour=13, minute=0))
    end   = ET.localize(datetime.combine(dt, datetime.min.time()).replace(hour=16, minute=5))
    req = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed="sip",
    )
    raw = bar_client.get_stock_bars(req)
    result = {}
    for ticker in tickers:
        bars_list = raw.data.get(ticker, [])
        result[ticker] = [
            (b.timestamp.astimezone(ET), b.open, b.high, b.low, b.close)
            for b in bars_list
        ]
    return result


def _bars_after(bars: list, after_dt: datetime, n: int) -> list:
    """Return up to n bars whose timestamp is >= after_dt."""
    return [b for b in bars if b[0] >= after_dt][:n]


# ── Stop quality analysis ─────────────────────────────────────────────────────

def _classify(direction: str, entry_px: float, exit_px: float,
               post_bars: list) -> tuple:
    """
    Returns (verdict, post_move_pct, note).

    verdict:
      'HELPED'    — price continued against trade after stop; avoiding further loss
      'TOO TIGHT' — price recovered in trade direction after stop
      'NEUTRAL'   — small move either way, inconclusive
      'NO DATA'   — not enough bars after exit
    """
    if not post_bars:
        return "NO DATA", None, ""

    # Use close of bar LOOKFORWARD_BARS bars after exit (or last available)
    post_close = post_bars[-1][4]
    post_move_pct = (post_close - exit_px) / exit_px * 100

    bullish = direction == "CALL"

    # For CALL (bullish): positive post_move = recovery (too tight), negative = continuation (helped)
    # For PUT  (bearish): negative post_move = recovery (too tight), positive = continuation (helped)
    if bullish:
        if post_move_pct <= -MOVE_THRESHOLD_PCT:
            verdict = "HELPED"
            note = f"stock fell {post_move_pct:+.2f}% after stop"
        elif post_move_pct >= MOVE_THRESHOLD_PCT:
            verdict = "TOO TIGHT"
            note = f"stock rose {post_move_pct:+.2f}% after stop"
        else:
            verdict = "NEUTRAL"
            note = f"stock moved {post_move_pct:+.2f}% after stop"
    else:
        if post_move_pct >= MOVE_THRESHOLD_PCT:
            verdict = "HELPED"
            note = f"stock rose {post_move_pct:+.2f}% after stop"
        elif post_move_pct <= -MOVE_THRESHOLD_PCT:
            verdict = "TOO TIGHT"
            note = f"stock fell {post_move_pct:+.2f}% after stop"
        else:
            verdict = "NEUTRAL"
            note = f"stock moved {post_move_pct:+.2f}% after stop"

    return verdict, post_move_pct, note


def _print_section(title: str):
    print(f"\n{'━'*88}")
    print(f"  {title}")
    print(f"{'━'*88}")


def analyze_stop_quality(losing_trades: list, bar_client: StockHistoricalDataClient):
    # Group by date to batch bar fetches
    by_date: dict[str, list] = defaultdict(list)
    for t in losing_trades:
        by_date[t["open_date"]].append(t)

    results = []
    for dt_str, day_trades in sorted(by_date.items()):
        dt = date.fromisoformat(dt_str)
        tickers = list({t["ticker"] for t in day_trades})
        bars_by_ticker = _fetch_bars_for_date(bar_client, tickers, dt)

        for t in day_trades:
            ticker = t["ticker"]
            bars = bars_by_ticker.get(ticker, [])
            close_dt = _parse_dt(t["close_filled_at"])
            if close_dt:
                post_bars = _bars_after(bars, close_dt, LOOKFORWARD_BARS)
            else:
                post_bars = []

            # Stock price at exit: use the bar that contains the exit time
            exit_bar = next((b for b in bars if b[0] >= _parse_dt(t["open_filled_at"])), None)
            exit_stock_px = exit_bar[4] if exit_bar else None

            if exit_stock_px and post_bars:
                verdict, post_move_pct, note = _classify(
                    t["direction"], exit_stock_px, exit_stock_px, post_bars
                )
                # Recompute using actual exit bar close
                post_close = post_bars[-1][4]
                post_move_pct = round((post_close - exit_stock_px) / exit_stock_px * 100, 3)
                verdict, _, note = _classify(t["direction"], exit_stock_px, exit_stock_px, post_bars)
            else:
                verdict, post_move_pct, note = "NO DATA", None, ""

            results.append({**t, "verdict": verdict, "post_move_pct": post_move_pct, "note": note})

    return results


def _print_results(results: list):
    helped    = [r for r in results if r["verdict"] == "HELPED"]
    too_tight = [r for r in results if r["verdict"] == "TOO TIGHT"]
    neutral   = [r for r in results if r["verdict"] == "NEUTRAL"]
    no_data   = [r for r in results if r["verdict"] == "NO DATA"]

    total = len(results)
    _print_section(f"STOP QUALITY ANALYSIS — {total} losing afternoon trades")
    print(f"\n  HELPED    (stop avoided further loss) : {len(helped):>3}  ({len(helped)/total*100:.0f}%)")
    print(f"  TOO TIGHT (price recovered after stop): {len(too_tight):>3}  ({len(too_tight)/total*100:.0f}%)")
    print(f"  NEUTRAL   (small move, inconclusive)  : {len(neutral):>3}  ({len(neutral)/total*100:.0f}%)")
    if no_data:
        print(f"  NO DATA                               : {len(no_data):>3}")

    _print_section("DETAIL — ALL TRADES")
    hdr = f"  {'Date':<12} {'W':<2} {'Ticker':<6} {'Dir':<5} {'Open ET':<7} {'Close ET':<8} {'Min':>4}  {'Opt%':>6}  {'Stk30m%':>8}  Verdict"
    print(hdr)
    print(f"  {'-'*90}")

    for r in sorted(results, key=lambda x: x["open_filled_at"]):
        dur  = f"{r['duration_min']:.0f}" if r["duration_min"] is not None else "?"
        pm   = f"{r['post_move_pct']:+.2f}%" if r["post_move_pct"] is not None else "  n/a "
        flag = " ◄" if r["verdict"] == "TOO TIGHT" else ""
        print(f"  {r['open_date']:<12} {r['window']:<2} {r['ticker']:<6} {r['direction']:<5} "
              f"{r['open_et']:<7} {r['close_et']:<8} {dur:>4}  "
              f"{r['pnl_pct']:>+6.2f}%  {pm:>8}  {r['verdict']}{flag}")

    _print_section("TOO TIGHT — trades where the stop cut a winner short")
    if not too_tight:
        print("  None found.")
    else:
        tt_pnl   = sum(r["pnl"] for r in too_tight)
        pnl_lost = sum(abs(r["pnl"]) for r in too_tight)
        print(f"\n  {'Date':<12} {'W':<2} {'Ticker':<6} {'Dir':<5} {'Open ET':<7} {'Min':>4}  "
              f"{'Opt P&L':>9}  {'Stk after':>10}  Note")
        print(f"  {'-'*85}")
        for r in sorted(too_tight, key=lambda x: x["open_filled_at"]):
            dur = f"{r['duration_min']:.0f}" if r["duration_min"] is not None else "?"
            pm  = f"{r['post_move_pct']:+.3f}%" if r["post_move_pct"] is not None else "n/a"
            print(f"  {r['open_date']:<12} {r['window']:<2} {r['ticker']:<6} {r['direction']:<5} "
                  f"{r['open_et']:<7} {dur:>4}  "
                  f"{r['pnl']:>+9.2f}  {pm:>10}  {r['note']}")
        print(f"\n  {len(too_tight)} trades  /  Stop-out cost: ${pnl_lost:,.2f}  "
              f"(could have recovered if held longer)")

    _print_section("SUMMARY BY WINDOW")
    for win_label in ("A2", "A3"):
        wt = [r for r in results if r["window"] == win_label]
        if not wt:
            continue
        wh = [r for r in wt if r["verdict"] == "HELPED"]
        wtt = [r for r in wt if r["verdict"] == "TOO TIGHT"]
        wn = [r for r in wt if r["verdict"] == "NEUTRAL"]
        print(f"\n  {win_label}: {len(wt)} losses  |  "
              f"Helped={len(wh)} ({len(wh)/len(wt)*100:.0f}%)  "
              f"TooTight={len(wtt)} ({len(wtt)/len(wt)*100:.0f}%)  "
              f"Neutral={len(wn)} ({len(wn)/len(wt)*100:.0f}%)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=2)
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
    all_trades = _pair_ts_trades(ts_week_fills)

    afternoon_losses = [
        t for t in all_trades
        if t["window"] in ("A2", "A3") and not t["win"]
    ]
    print(f"Found {len(afternoon_losses)} losing afternoon trades. Fetching bar data...")

    bar_client = StockHistoricalDataClient(
        api_key="AK2PHJV4ZFO65JYT2IU7EDDIDH",
        secret_key="7NmxWaaBDRtXq8TJ2HLusiHqXqjT3QQQYWX1KZhj8iTb",
    )

    results = analyze_stop_quality(afternoon_losses, bar_client)
    _print_results(results)
