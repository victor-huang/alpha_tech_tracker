"""Pull this week's filled stock orders from Alpaca and analyze P&L / win rate.

Uses the live trading account (is_paper_trading=False).

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python alpha_tech_tracker/op_momentum_strategy/analyze_weekly_stock_trades.py
"""

import os
import pytz
from collections import defaultdict
from datetime import date, datetime, timedelta

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from alpha_tech_tracker.op_momentum_strategy.config import _load_config, build_execution_client
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

ET = pytz.timezone("America/New_York")


def _week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())  # Monday


def _et_date(dt) -> str:
    if dt is None:
        return ""
    if hasattr(dt, "astimezone"):
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    return str(dt)[:10]


def _fetch_all_fills(client: AlpacaAPIClient, since: datetime) -> list:
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
            "date": _et_date(o.filled_at),
        })

    fills.sort(key=lambda x: x["filled_at"])
    return fills


def _pair_trades(fills: list) -> list:
    """
    Match fills into completed round trips, handling both longs and shorts.

    Long  round trip: BUY (open) → SELL (close).  P&L = (sell - buy) * qty
    Short round trip: SELL (open) → BUY  (close). P&L = (sell - buy) * qty  (same formula)

    Position direction is tracked per symbol. A BUY against a net-short position
    closes a short; a SELL against a net-long position closes a long. Sells/buys
    that arrive with no opposing open position start a new short/long respectively.
    """
    # per-symbol FIFO queues: list of {"qty", "price", "date"}
    long_q: dict[str, list] = defaultdict(list)
    short_q: dict[str, list] = defaultdict(list)
    net: dict[str, float] = defaultdict(float)
    trades = []

    for f in fills:
        sym = f["symbol"]
        remaining = f["qty"]

        if f["is_buy"]:
            # First: close any open shorts
            while remaining > 0 and short_q[sym]:
                opener = short_q[sym][0]
                matched = min(opener["qty"], remaining)
                pnl = (opener["price"] - f["price"]) * matched  # short P&L
                trades.append({
                    "symbol": sym,
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
                net[sym] += matched
                if opener["qty"] <= 0:
                    short_q[sym].pop(0)
            # Remaining qty opens a new long
            if remaining > 0:
                long_q[sym].append({"qty": remaining, "price": f["price"], "date": f["date"]})
                net[sym] += remaining

        else:  # sell
            # First: close any open longs
            while remaining > 0 and long_q[sym]:
                opener = long_q[sym][0]
                matched = min(opener["qty"], remaining)
                pnl = (f["price"] - opener["price"]) * matched  # long P&L
                trades.append({
                    "symbol": sym,
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
                net[sym] -= matched
                if opener["qty"] <= 0:
                    long_q[sym].pop(0)
            # Remaining qty opens a new short
            if remaining > 0:
                short_q[sym].append({"qty": remaining, "price": f["price"], "date": f["date"]})
                net[sym] -= remaining

    return trades


def _print_section(title: str):
    print(f"\n{'━'*60}")
    print(f"  {title}")
    print(f"{'━'*60}")


def analyze(trades: list, fills: list):
    if not trades:
        print("\nNo closed stock trades found this week.")
        _print_open_positions(fills)
        return

    total_pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = len(wins) / len(trades) * 100

    _print_section(f"WEEKLY SUMMARY  ({trades[0]['open_date']} → {trades[-1]['close_date']})")
    print(f"  Closed trades : {len(trades)}")
    print(f"  Win / Loss    : {len(wins)}W / {len(losses)}L  ({win_rate:.0f}% win rate)")
    print(f"  Total P&L     : ${total_pnl:+,.2f}")
    if wins:
        avg_win_pnl = sum(t["pnl"] for t in wins) / len(wins)
        avg_win_pct = sum(t["pnl_pct"] for t in wins) / len(wins)
        print(f"  Avg win       : ${avg_win_pnl:+,.2f}  ({avg_win_pct:+.2f}%)")
    if losses:
        avg_loss_pnl = sum(t["pnl"] for t in losses) / len(losses)
        avg_loss_pct = sum(t["pnl_pct"] for t in losses) / len(losses)
        print(f"  Avg loss      : ${avg_loss_pnl:+,.2f}  ({avg_loss_pct:+.2f}%)")

    # --- By day ---
    _print_section("BY DAY")
    by_day: dict[str, list] = defaultdict(list)
    for t in trades:
        by_day[t["close_date"]].append(t)
    print(f"  {'Date':<12} {'Trades':>6}  {'W/L':>7}  {'P&L':>10}")
    print(f"  {'-'*44}")
    for d in sorted(by_day):
        day_trades = by_day[d]
        day_pnl = sum(t["pnl"] for t in day_trades)
        day_wins = sum(1 for t in day_trades if t["win"])
        day_losses = len(day_trades) - day_wins
        print(f"  {d:<12} {len(day_trades):>6}  {day_wins}W/{day_losses}L  {day_pnl:>+10,.2f}")

    # --- By ticker ---
    _print_section("BY TICKER")
    by_ticker: dict[str, list] = defaultdict(list)
    for t in trades:
        by_ticker[t["symbol"]].append(t)
    ticker_rows = []
    for ticker, ts in by_ticker.items():
        t_pnl = sum(x["pnl"] for x in ts)
        t_wins = sum(1 for x in ts if x["win"])
        ticker_rows.append((t_pnl, ticker, ts, t_wins))
    ticker_rows.sort(reverse=True)

    print(f"  {'Ticker':<8} {'Trades':>6}  {'W/L':>7}  {'P&L':>10}  {'Avg%':>7}")
    print(f"  {'-'*50}")
    for t_pnl, ticker, ts, t_wins in ticker_rows:
        t_losses = len(ts) - t_wins
        avg_pct = sum(x["pnl_pct"] for x in ts) / len(ts)
        print(f"  {ticker:<8} {len(ts):>6}  {t_wins}W/{t_losses}L  {t_pnl:>+10,.2f}  {avg_pct:>+7.2f}%")

    # --- All trades ---
    _print_section("ALL CLOSED TRADES")
    print(f"  {'Date':<10}  {'Symbol':<8}  {'Qty':>8}  {'Open':>8}  {'Close':>8}  {'P&L':>10}  {'%':>7}  Result")
    print(f"  {'-'*80}")
    for t in sorted(trades, key=lambda x: (x["close_date"], x["symbol"])):
        result = "WIN " if t["win"] else "LOSS"
        print(f"  {t['close_date']:<10}  {t['symbol']:<8}  {t['qty']:>8.0f}  "
              f"{t['open_price']:>8.2f}  {t['close_price']:>8.2f}  "
              f"{t['pnl']:>+10.2f}  {t['pnl_pct']:>+7.2f}%  {result}")

    # --- Insights ---
    _print_section("INSIGHTS")
    if total_pnl >= 0:
        print(f"  ✓ Week is profitable: ${total_pnl:+,.2f}")
    else:
        print(f"  ✗ Week is down: ${total_pnl:+,.2f}")

    if wins:
        best = max(wins, key=lambda t: t["pnl"])
        print(f"  Best trade    : {best['symbol']} on {best['close_date']}  ${best['pnl']:+,.2f} ({best['pnl_pct']:+.2f}%)")
    if losses:
        worst = min(losses, key=lambda t: t["pnl"])
        print(f"  Worst trade   : {worst['symbol']} on {worst['close_date']}  ${worst['pnl']:+,.2f} ({worst['pnl_pct']:+.2f}%)")

    best_tickers = [(p, t) for p, t, _, _ in ticker_rows if p > 0]
    worst_tickers = [(p, t) for p, t, _, _ in ticker_rows if p < 0]
    if best_tickers:
        print(f"  Top tickers   : {', '.join(t for _, t in best_tickers[:3])}")
    if worst_tickers:
        print(f"  Weak tickers  : {', '.join(t for _, t in worst_tickers[:3])}")

    if wins and losses:
        avg_win_pct = sum(t["pnl_pct"] for t in wins) / len(wins)
        avg_loss_pct = sum(t["pnl_pct"] for t in losses) / len(losses)
        rr = abs(avg_win_pct / avg_loss_pct) if avg_loss_pct != 0 else float("inf")
        print(f"  Reward/Risk   : {rr:.2f}x  (avg win {avg_win_pct:+.2f}% / avg loss {avg_loss_pct:+.2f}%)")
        if rr < 1.0:
            print("  ⚠  Reward/risk < 1 — wins need to be larger or losses smaller")

    _print_open_positions(fills)
    print()


def _print_open_positions(fills: list):
    long_q: dict[str, list] = defaultdict(list)
    short_q: dict[str, list] = defaultdict(list)

    for f in fills:
        sym = f["symbol"]
        remaining = f["qty"]
        if f["is_buy"]:
            while remaining > 0 and short_q[sym]:
                opener = short_q[sym][0]
                matched = min(opener["qty"], remaining)
                opener["qty"] -= matched
                remaining -= matched
                if opener["qty"] <= 0:
                    short_q[sym].pop(0)
            if remaining > 0:
                long_q[sym].append({"qty": remaining, "price": f["price"]})
        else:
            while remaining > 0 and long_q[sym]:
                opener = long_q[sym][0]
                matched = min(opener["qty"], remaining)
                opener["qty"] -= matched
                remaining -= matched
                if opener["qty"] <= 0:
                    long_q[sym].pop(0)
            if remaining > 0:
                short_q[sym].append({"qty": remaining, "price": f["price"]})

    open_positions = []
    for sym, lots in long_q.items():
        for lot in lots:
            if lot["qty"] > 0:
                open_positions.append((sym, "LONG", lot["qty"], lot["price"]))
    for sym, lots in short_q.items():
        for lot in lots:
            if lot["qty"] > 0:
                open_positions.append((sym, "SHORT", lot["qty"], lot["price"]))

    if open_positions:
        print(f"\n  Open positions ({len(open_positions)}):")
        for sym, direction, qty, price in open_positions:
            print(f"    {sym:<8}  {direction}  qty={qty:.0f}  avg_entry={price:.2f}")


if __name__ == "__main__":
    import json, pathlib
    # Try config.json first; fall back to bash_profile live key if config key is unauthorized
    _cfg_path = pathlib.Path(__file__).resolve().parent.parent / "config.json"
    _cfg = json.loads(_cfg_path.read_text())
    _alpaca_cfg = _cfg.get("alpaca", {})

    # Verify the config key works; if not, use the live key from env/bash_profile
    import requests as _req
    _test_key = _alpaca_cfg.get("api_key", "")
    _test_secret = _alpaca_cfg.get("secret_key", "")
    _r = _req.get(
        "https://api.alpaca.markets/v2/account",
        headers={"APCA-API-KEY-ID": _test_key, "APCA-API-SECRET-KEY": _test_secret},
    )
    if not _r.ok:
        # config.json key is stale — fall back to the live key exported in bash_profile
        _test_key = os.environ.get("ALPACA_API_KEY", "")
        _test_secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not _test_key or not _test_secret:
            raise SystemExit(
                "config.json key unauthorized and ALPACA_API_KEY / ALPACA_SECRET_KEY "
                "are not set. Export them (e.g. from ~/.bash_profile) and retry."
            )
        print("(config.json key unauthorized — using ALPACA_* from the environment)")

    client = AlpacaAPIClient(
        api_key=_test_key,
        secret_key=_test_secret,
        is_paper_trading=False,
    )

    week_start = _week_start()
    since_dt = ET.localize(datetime.combine(week_start - timedelta(days=1), datetime.min.time()))
    print(f"Fetching Alpaca stock fills since {week_start} (Mon)...")

    fills = _fetch_all_fills(client, since_dt)
    # Filter to this week only
    week_fills = [f for f in fills if f["date"] >= week_start.isoformat()]
    print(f"Found {len(week_fills)} fills this week ({len(fills)} total fetched).")

    trades = _pair_trades(week_fills)
    analyze(trades, week_fills)
