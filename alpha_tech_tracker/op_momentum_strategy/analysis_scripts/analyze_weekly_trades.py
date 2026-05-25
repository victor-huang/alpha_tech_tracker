"""Pull this week's filled orders from TradeStation and analyze P&L / win rate.

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python alpha_tech_tracker/op_momentum_strategy/analyze_weekly_trades.py
"""

from collections import defaultdict
from datetime import date, timedelta

from alpha_tech_tracker.op_momentum_strategy.config import _load_config, build_execution_client


def _week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())  # Monday


def _et_date(ts: str) -> str:
    """Convert UTC ISO timestamp to ET date string YYYY-MM-DD."""
    import pytz
    from datetime import datetime
    ET = pytz.timezone("America/New_York")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    except Exception:
        return ts[:10]


def _fetch_all_fills(client, since: str) -> list:
    account_key = client._get_account_key()

    # Historical orders (completed days)
    resp = client._session.get(
        client._v3_base_url + f"/brokerage/accounts/{account_key}/historicalorders",
        params={"since": since, "pageSize": 500},
    )
    data = client._parse(resp)
    hist = data if isinstance(data, list) else data.get("Orders", [])

    # Today's orders (not yet in historicalorders)
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
        buy_or_sell = leg.get("BuyOrSell", "").lower()   # "Buy" | "Sell"
        open_or_close = leg.get("OpenOrClose", "").lower()  # "Open" | "Close"
        qty_raw = leg.get("ExecQuantity") or raw.get("ExecuteQuantity") or 0
        filled_at = raw.get("ClosedDateTime") or raw.get("OpenedDateTime") or raw.get("TimeStamp", "")
        order_date = _et_date(filled_at) if filled_at else ""
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


def _pair_trades(fills: list) -> list:
    """Match BUY opens to SELL closes by symbol, FIFO."""
    open_lots: dict[str, list] = defaultdict(list)
    trades = []

    for f in fills:
        sym = f["symbol"]
        if f["is_buy"] and f["is_open"]:
            open_lots[sym].append(dict(f))
        elif not f["is_buy"] and not f["is_open"]:
            qty_to_close = f["qty"]
            while qty_to_close > 0 and open_lots[sym]:
                opener = open_lots[sym][0]
                matched = min(opener["qty"], qty_to_close)
                pnl_per_share = (f["price"] - opener["price"]) * matched
                multiplier = 100 if _is_option(sym) else 1
                pnl = pnl_per_share * multiplier

                trades.append({
                    "symbol": sym,
                    "ticker": _underlying(sym),
                    "is_option": _is_option(sym),
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


def _print_section(title: str):
    print(f"\n{'━'*60}")
    print(f"  {title}")
    print(f"{'━'*60}")


def analyze(trades: list, fills: list):
    if not trades:
        print("\nNo closed trades found this week.")
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
        print(f"  Avg win       : ${sum(t['pnl'] for t in wins)/len(wins):+,.2f}  "
              f"({sum(t['pnl_pct'] for t in wins)/len(wins):+.2f}%)")
    if losses:
        print(f"  Avg loss      : ${sum(t['pnl'] for t in losses)/len(losses):+,.2f}  "
              f"({sum(t['pnl_pct'] for t in losses)/len(losses):+.2f}%)")

    # --- By day ---
    _print_section("BY DAY")
    by_day: dict[str, list] = defaultdict(list)
    for t in trades:
        by_day[t["close_date"]].append(t)
    print(f"  {'Date':<12} {'Trades':>6}  {'W/L':>7}  {'P&L':>10}")
    print(f"  {'-'*42}")
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
        by_ticker[t["ticker"]].append(t)
    ticker_rows = []
    for ticker, ts in by_ticker.items():
        t_pnl = sum(x["pnl"] for x in ts)
        t_wins = sum(1 for x in ts if x["win"])
        ticker_rows.append((t_pnl, ticker, ts, t_wins))
    ticker_rows.sort(reverse=True)

    print(f"  {'Ticker':<8} {'Trades':>6}  {'W/L':>7}  {'P&L':>10}  {'Avg%':>7}")
    print(f"  {'-'*48}")
    for t_pnl, ticker, ts, t_wins in ticker_rows:
        t_losses = len(ts) - t_wins
        avg_pct = sum(x["pnl_pct"] for x in ts) / len(ts)
        print(f"  {ticker:<8} {len(ts):>6}  {t_wins}W/{t_losses}L  {t_pnl:>+10,.2f}  {avg_pct:>+7.2f}%")

    # --- Options vs stock ---
    opts = [t for t in trades if t["is_option"]]
    stocks = [t for t in trades if not t["is_option"]]
    if opts and stocks:
        _print_section("OPTIONS vs STOCK")
        for label, group in [("Options", opts), ("Stock", stocks)]:
            g_pnl = sum(t["pnl"] for t in group)
            g_wins = sum(1 for t in group if t["win"])
            g_wr = g_wins / len(group) * 100
            print(f"  {label:<8}  {len(group):>3} trades  "
                  f"{g_wins}W/{len(group)-g_wins}L ({g_wr:.0f}%)  ${g_pnl:+,.2f}")

    # --- Individual trades ---
    _print_section("ALL CLOSED TRADES")
    print(f"  {'Date':<10}  {'Symbol':<24}  {'Qty':>4}  {'Open':>7}  {'Close':>7}  {'P&L':>9}  {'%':>7}  Result")
    print(f"  {'-'*88}")
    for t in sorted(trades, key=lambda x: x["close_date"]):
        result = "WIN " if t["win"] else "LOSS"
        sym_short = t["symbol"][:24]
        print(f"  {t['close_date']:<10}  {sym_short:<24}  {t['qty']:>4.0f}  "
              f"{t['open_price']:>7.2f}  {t['close_price']:>7.2f}  "
              f"{t['pnl']:>+9.2f}  {t['pnl_pct']:>+7.2f}%  {result}")

    # --- Insights ---
    _print_section("INSIGHTS")
    if total_pnl > 0:
        print(f"  ✓ Week is profitable: ${total_pnl:+,.2f}")
    else:
        print(f"  ✗ Week is down: ${total_pnl:+,.2f}")

    if wins:
        best = max(wins, key=lambda t: t["pnl"])
        print(f"  Best trade    : {best['ticker']} on {best['close_date']}  ${best['pnl']:+,.2f} ({best['pnl_pct']:+.2f}%)")
    if losses:
        worst = min(losses, key=lambda t: t["pnl"])
        print(f"  Worst trade   : {worst['ticker']} on {worst['close_date']}  ${worst['pnl']:+,.2f} ({worst['pnl_pct']:+.2f}%)")

    # Largest winners / losers by ticker
    best_tickers = [(t_pnl, ticker) for t_pnl, ticker, _, _ in ticker_rows if t_pnl > 0]
    worst_tickers = [(t_pnl, ticker) for t_pnl, ticker, _, _ in ticker_rows if t_pnl < 0]
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

    # Unclosed positions warning
    open_buys = []
    open_by_sym: dict[str, list] = defaultdict(list)
    for f in fills:
        if f["is_buy"] and f["is_open"]:
            open_by_sym[f["symbol"]].append(dict(f))
        elif not f["is_buy"] and not f["is_open"]:
            qty_to_close = f["qty"]
            while qty_to_close > 0 and open_by_sym[f["symbol"]]:
                opener = open_by_sym[f["symbol"]][0]
                matched = min(opener["qty"], qty_to_close)
                opener["qty"] -= matched
                qty_to_close -= matched
                if opener["qty"] <= 0:
                    open_by_sym[f["symbol"]].pop(0)
    for sym, lots in open_by_sym.items():
        for lot in lots:
            if lot["qty"] > 0:
                open_buys.append((sym, lot["qty"], lot["price"]))
    if open_buys:
        print(f"\n  Open positions ({len(open_buys)}):")
        for sym, qty, price in open_buys:
            print(f"    {sym}  qty={qty:.0f}  entry={price:.2f}")

    print()


if __name__ == "__main__":
    _load_config()
    client = build_execution_client(broker="tradestation")

    week_start = _week_start()
    since = (week_start - timedelta(days=1)).isoformat()  # small buffer
    print(f"Fetching fills since {since} (week of {week_start})...")

    fills = _fetch_all_fills(client, since)
    print(f"Found {len(fills)} fills total.")

    # Filter to this week only
    week_fills = [f for f in fills if f["date"] >= week_start.isoformat()]
    trades = _pair_trades(week_fills)

    analyze(trades, week_fills)
