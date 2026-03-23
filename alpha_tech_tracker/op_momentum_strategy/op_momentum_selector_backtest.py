import argparse
import pandas as pd
from datetime import date, timedelta

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    compute_signals_with_backtest,
    fetch_bars,
    fetch_daily_bars,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    DEFAULT_TICKERS,
    OPENING_BARS,
    ROLLING_LOOKBACK_DAYS,
    STOP_PCT,
    compute_ticker_stats,
    score_ticker,
)


def _signal_dict_from_row(row) -> dict:
    or_range = row["or_high"] - row["or_low"]
    mid = row["midpoint"]
    entry = row["entry_price"]
    entry_vs_mid_pct = abs(entry - mid) / mid * 100 if mid != 0 else 0.0
    or_range_pct = or_range / entry * 100 if entry != 0 else 0.0
    return {
        "signal": row["signal"],
        "entry_vs_mid_pct": entry_vs_mid_pct,
        "or_range_pct": or_range_pct,
    }


def run_selector_backtest(
    n: int,
    tickers: list,
    eval_start: date,
    eval_end: date,
    lookback_days: int = ROLLING_LOOKBACK_DAYS,
    opening_bars: int = OPENING_BARS,
    bearish_ma200: bool = False,
    stop_pct: float = STOP_PCT,
    source: str = "alpaca",
) -> tuple:
    """
    Walk each trading day in [eval_start, eval_end], apply rolling selector
    scoring to pick top-N tickers, and record actual trade outcomes.

    Returns (trade_rows, full_results, trading_days) where:
      - trade_rows: list of dicts, one per selected trade
      - full_results: {ticker: results_df} across the full fetch window
      - trading_days: sorted list of date objects in the eval window
    """
    # fetch_alpaca_bars already adds 30 days internally for MA warmup;
    # we only need to go back lookback_days to cover the rolling stats window.
    fetch_start = eval_start - timedelta(days=lookback_days)
    print(f"Fetching bars for {len(tickers)} tickers ({eval_start} → {eval_end})...")
    all_bars = fetch_bars(tickers, fetch_start, eval_end, source=source)

    print("Pre-computing backtest signals and outcomes...")
    full_results = {}
    for ticker in tickers:
        df = all_bars.get(ticker, pd.DataFrame())
        if df.empty:
            full_results[ticker] = pd.DataFrame()
            continue
        full_results[ticker] = compute_signals_with_backtest(
            df, opening_bars, bearish_ma200, stop_pct
        )

    trading_days = sorted(
        {
            d
            for df in all_bars.values()
            if not df.empty
            for d in df.index.date
            if eval_start <= d <= eval_end
        }
    )

    trade_rows = []
    for d in trading_days:
        lookback_start = d - timedelta(days=lookback_days)

        rolling_stats = {}
        for ticker in tickers:
            results = full_results.get(ticker, pd.DataFrame())
            if results.empty:
                rolling_stats[ticker] = compute_ticker_stats(pd.DataFrame())
                continue
            window = results[
                (results["date"] >= lookback_start) & (results["date"] < d)
            ]
            rolling_stats[ticker] = compute_ticker_stats(window)

        scored = []
        for ticker in tickers:
            results = full_results.get(ticker, pd.DataFrame())
            if results.empty:
                continue
            today_rows = results[results["date"] == d]
            if today_rows.empty:
                continue
            row = today_rows.iloc[0]
            sig = _signal_dict_from_row(row)
            stats = rolling_stats[ticker]
            s = score_ticker(sig, stats)
            if s == 0.0:
                continue
            scored.append(
                {
                    "ticker": ticker,
                    "score": round(s, 3),
                    "signal": row["signal"],
                    "entry_price": row["entry_price"],
                    "exit_price": row["exit_price"],
                    "midpoint": row["midpoint"],
                    "pnl": row["pnl"],
                    "success": bool(row["success"]),
                    "exit_reason": row["exit_reason"],
                    "entry_vs_mid_pct": round(sig["entry_vs_mid_pct"], 3),
                    "or_range_pct": round(sig["or_range_pct"], 3),
                    "rolling_ev": round(stats["ev_trade"], 3),
                    "rolling_win_rate": round(stats["win_rate"], 3),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        for rank, pick in enumerate(scored[:n], 1):
            pnl_pct = pick["pnl"] / pick["entry_price"] * 100
            trade_rows.append(
                {"date": d, "rank": rank, "pnl_pct": round(pnl_pct, 3), **pick}
            )

    return trade_rows, full_results, trading_days


def _collect_baseline(
    full_results: dict, eval_start: date, eval_end: date
) -> pd.DataFrame:
    frames = []
    for ticker, df in full_results.items():
        if df.empty:
            continue
        window = df[(df["date"] >= eval_start) & (df["date"] <= eval_end)].copy()
        if window.empty:
            continue
        window["ticker"] = ticker
        frames.append(window)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


INITIAL_CAPITAL = 10_000.0


def _print_daily_table(
    trade_rows: list, n: int, initial_capital: float = INITIAL_CAPITAL
):
    capital_per_pick = initial_capital / n
    sep = "\u2501" * 90
    print(f"\n{sep}")
    print(
        f"  {'Date':<12} {'Rank':<5} {'Ticker':<6} {'Signal':<9} {'Score':>5}  "
        f"{'Entry':>7} {'Exit':>7} {'P&L$':>7} {'P&L%':>7}  {'Result':<6}  Exit Reason"
    )
    print(sep)

    current_date = None
    day_pnl = 0.0
    day_pnl_pcts = []
    day_wins = 0
    day_losses = 0
    running_total = 0.0
    day_cap_pnl = 0.0
    portfolio = initial_capital

    for row in trade_rows:
        if row["date"] != current_date:
            if current_date is not None:
                portfolio += day_cap_pnl
                _print_day_summary(
                    day_wins,
                    day_losses,
                    day_pnl,
                    day_pnl_pcts,
                    running_total,
                    day_cap_pnl,
                    initial_capital,
                    portfolio,
                )
            current_date = row["date"]
            day_pnl = 0.0
            day_pnl_pcts = []
            day_wins = 0
            day_losses = 0
            day_cap_pnl = 0.0

        pnl = row["pnl"]
        pnl_pct = row["pnl_pct"]
        result = "WIN" if row["success"] else "LOSS"
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        pnl_pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"

        print(
            f"  {str(row['date']):<12} {row['rank']:<5} {row['ticker']:<6} "
            f"{row['signal']:<9} {row['score']:>5.2f}  "
            f"{row['entry_price']:>7.2f} {row['exit_price']:>7.2f} "
            f"{pnl_str:>7} {pnl_pct_str:>7}  {result:<6}  {row['exit_reason']}"
        )

        day_pnl += pnl
        day_pnl_pcts.append(pnl_pct)
        running_total += pnl
        day_cap_pnl += (capital_per_pick / row["entry_price"]) * pnl
        if row["success"]:
            day_wins += 1
        else:
            day_losses += 1

    if current_date is not None:
        portfolio += day_cap_pnl
        _print_day_summary(
            day_wins,
            day_losses,
            day_pnl,
            day_pnl_pcts,
            running_total,
            day_cap_pnl,
            initial_capital,
            portfolio,
        )

    print(sep)


def _print_day_summary(
    wins,
    losses,
    day_pnl,
    day_pnl_pcts,
    running_total,
    day_cap_pnl,
    initial_capital,
    portfolio,
):
    total = wins + losses
    if total == 0:
        return
    pnl_str = f"+${day_pnl:.2f}" if day_pnl >= 0 else f"-${abs(day_pnl):.2f}"
    avg_pct = sum(day_pnl_pcts) / len(day_pnl_pcts)
    avg_pct_str = f"+{avg_pct:.2f}%" if avg_pct >= 0 else f"{avg_pct:.2f}%"
    running_str = (
        f"+${running_total:.2f}"
        if running_total >= 0
        else f"-${abs(running_total):.2f}"
    )
    cap_pnl_str = (
        f"+${day_cap_pnl:.2f}" if day_cap_pnl >= 0 else f"-${abs(day_cap_pnl):.2f}"
    )
    day_ret_pct = day_cap_pnl / initial_capital * 100
    day_ret_str = f"+{day_ret_pct:.2f}%" if day_ret_pct >= 0 else f"{day_ret_pct:.2f}%"
    print(
        f"  {'':12} {'':5} {'':6} {'':9} {'':5}  "
        f"{'':>7} {'':>7} {pnl_str:>7} {avg_pct_str:>7}  "
        f"{wins}W/{losses}L  │  cap: {cap_pnl_str} ({day_ret_str})  portfolio: ${portfolio:.2f}"
    )
    print(f"  {'─' * 88}")


def _stats_from_trades(trade_rows: list) -> dict:
    total = len(trade_rows)
    if total == 0:
        return None
    wins = sum(1 for r in trade_rows if r["success"])
    losses = total - wins
    win_rate = wins / total
    win_pct_vals = [r["pnl_pct"] for r in trade_rows if r["success"]]
    loss_pct_vals = [abs(r["pnl_pct"]) for r in trade_rows if not r["success"]]
    avg_win_pct = sum(win_pct_vals) / len(win_pct_vals) if win_pct_vals else 0.0
    avg_loss_pct = sum(loss_pct_vals) / len(loss_pct_vals) if loss_pct_vals else 0.0
    ev = win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct
    net_pnl = sum(r["pnl"] for r in trade_rows)
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ev": ev,
        "net_pnl": net_pnl,
    }


def _print_stats_block(label: str, stats: dict):
    if stats is None:
        print(f"  {label}: no trades")
        return
    net_str = (
        f"+${stats['net_pnl']:.2f}"
        if stats["net_pnl"] >= 0
        else f"-${abs(stats['net_pnl']):.2f}"
    )
    ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
    print(f"\n  {label}")
    print(f"  {'─' * 48}")
    print(
        f"  Trades          : {stats['total']}  ({stats['wins']}W / {stats['losses']}L)"
    )
    print(f"  Win rate        : {stats['win_rate'] * 100:.0f}%")
    print(f"  Avg win  %      : +{stats['avg_win_pct']:.2f}%  per trade")
    print(f"  Avg loss %      : -{stats['avg_loss_pct']:.2f}%  per trade")
    print(f"  EV / trade      : {ev_str}")
    print(f"  Net P&L (1 sh)  : {net_str}")


def _capital_stats_from_trades(
    trade_rows: list, n: int, initial_capital: float
) -> dict:
    capital_per_pick = initial_capital / n
    total_cap_pnl = 0.0
    days_with_picks = set()
    daily_cap_pnls = {}
    for row in trade_rows:
        cap_pnl = (capital_per_pick / row["entry_price"]) * row["pnl"]
        total_cap_pnl += cap_pnl
        d = row["date"]
        days_with_picks.add(d)
        daily_cap_pnls[d] = daily_cap_pnls.get(d, 0.0) + cap_pnl

    daily_returns = list(daily_cap_pnls.values())
    avg_daily_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    return {
        "initial_capital": initial_capital,
        "capital_per_pick": capital_per_pick,
        "n": n,
        "total_cap_pnl": total_cap_pnl,
        "total_return_pct": total_cap_pnl / initial_capital * 100,
        "final_portfolio": initial_capital + total_cap_pnl,
        "days_with_picks": len(days_with_picks),
        "avg_daily_ret": avg_daily_ret,
        "avg_daily_ret_pct": avg_daily_ret / initial_capital * 100,
    }


def _print_capital_stats_block(stats: dict):
    cap_pnl_str = (
        f"+${stats['total_cap_pnl']:.2f}"
        if stats["total_cap_pnl"] >= 0
        else f"-${abs(stats['total_cap_pnl']):.2f}"
    )
    ret_pct_str = (
        f"+{stats['total_return_pct']:.2f}%"
        if stats["total_return_pct"] >= 0
        else f"{stats['total_return_pct']:.2f}%"
    )
    avg_str = (
        f"+${stats['avg_daily_ret']:.2f}"
        if stats["avg_daily_ret"] >= 0
        else f"-${abs(stats['avg_daily_ret']):.2f}"
    )
    avg_pct_str = (
        f"+{stats['avg_daily_ret_pct']:.2f}%"
        if stats["avg_daily_ret_pct"] >= 0
        else f"{stats['avg_daily_ret_pct']:.2f}%"
    )
    print(
        f"\n  CAPITAL SIMULATION  (${stats['initial_capital']:,.0f} initial | ${stats['capital_per_pick']:,.0f}/slot × {stats['n']} slots)"
    )
    print(f"  {'─' * 48}")
    print(f"  Total return ($)    : {cap_pnl_str}")
    print(f"  Total return (%)    : {ret_pct_str}")
    print(f"  Final portfolio     : ${stats['final_portfolio']:,.2f}")
    print(f"  Days with picks     : {stats['days_with_picks']}")
    print(f"  Avg daily return    : {avg_str}  ({avg_pct_str})")


def _period_capital_groups(
    trade_rows: list, n: int, initial_capital: float, key_fn
) -> dict:
    capital_per_pick = initial_capital / n
    groups = {}
    for row in trade_rows:
        key = key_fn(row["date"])
        if key not in groups:
            groups[key] = {"picks": 0, "wins": 0, "losses": 0, "cap_pnl": 0.0}
        groups[key]["picks"] += 1
        groups[key]["cap_pnl"] += (capital_per_pick / row["entry_price"]) * row["pnl"]
        if row["success"]:
            groups[key]["wins"] += 1
        else:
            groups[key]["losses"] += 1
    return groups


def _print_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 72
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(
        f"  {'Period':<12} {'Picks':>6}  {'W/L':<11} {'Cap P&L$':>10}  {'Return%':>8}  Portfolio"
    )
    print(f"  {'─' * 68}")

    portfolio = initial_capital
    total_picks = total_wins = total_losses = 0
    total_cap_pnl = 0.0

    for key in sorted(groups):
        g = groups[key]
        portfolio += g["cap_pnl"]
        total_picks += g["picks"]
        total_wins += g["wins"]
        total_losses += g["losses"]
        total_cap_pnl += g["cap_pnl"]

        wl = f"{g['wins']}W/{g['losses']}L"
        pnl_s = (
            f"+${g['cap_pnl']:.2f}"
            if g["cap_pnl"] >= 0
            else f"-${abs(g['cap_pnl']):.2f}"
        )
        ret = g["cap_pnl"] / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(
            f"  {key:<12} {g['picks']:>6}  {wl:<11} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}"
        )

    print(f"  {'─' * 68}")
    total_pnl_s = (
        f"+${total_cap_pnl:.2f}"
        if total_cap_pnl >= 0
        else f"-${abs(total_cap_pnl):.2f}"
    )
    total_ret = total_cap_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_picks:>6}  {total_wins}W/{total_losses}L{'':<7} {total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_cap_pnl:,.2f}"
    )
    print(sep)


def _bnh_period_groups(daily_closes: pd.Series, initial_capital: float, key_fn) -> dict:
    """Compute buy-and-hold period groups from a Series of {date: close_price}."""
    if daily_closes.empty:
        return {}
    shares = initial_capital / daily_closes.iloc[0]
    groups = {}
    for d, close in daily_closes.items():
        key = key_fn(d)
        if key not in groups:
            groups[key] = {"last_close": close}
        groups[key]["last_close"] = close

    prev_value = initial_capital
    for key in sorted(groups):
        end_value = shares * groups[key]["last_close"]
        groups[key]["pnl"] = end_value - prev_value
        prev_value = end_value
    return groups


def _print_bnh_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 60
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(f"  {'Period':<12} {'P&L$':>10}  {'Return%':>8}  Portfolio")
    print(f"  {'─' * 54}")

    portfolio = initial_capital
    total_pnl = 0.0
    for key in sorted(groups):
        pnl = groups[key]["pnl"]
        portfolio += pnl
        total_pnl += pnl
        pnl_s = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ret = pnl / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(f"  {key:<12} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}")

    print(f"  {'─' * 54}")
    total_pnl_s = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    total_ret = total_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_pnl:,.2f}"
    )
    print(sep)


def _print_summary(
    trade_rows: list,
    baseline_df: pd.DataFrame,
    n: int,
    eval_start: date,
    eval_end: date,
    lookback_days: int,
    stop_pct: float,
    initial_capital: float = INITIAL_CAPITAL,
    qqq_closes: pd.Series = None,
):
    sep = "\u2501" * 70
    print(f"\n{sep}")
    print(f"  SUMMARY — Selector Backtest")
    print(
        f"  {eval_start} → {eval_end}  |  top-{n}  |  {lookback_days}d rolling  |  stop-pct {stop_pct}"
    )
    print(sep)

    _print_stats_block(
        f"SELECTED  (top-{n} per day, scoring + EV gate)",
        _stats_from_trades(trade_rows),
    )

    if not baseline_df.empty:
        baseline_rows = [
            {
                "pnl": r["pnl"],
                "pnl_pct": r["pnl"] / r["entry_price"] * 100,
                "success": bool(r["success"]),
            }
            for r in baseline_df.to_dict("records")
        ]
        _print_stats_block(
            "BASELINE  (all signals, no selection)", _stats_from_trades(baseline_rows)
        )

    if trade_rows:
        _print_capital_stats_block(
            _capital_stats_from_trades(trade_rows, n, initial_capital)
        )

        def _week_key(d):
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"

        def _month_key(d):
            return f"{d.year}-{d.month:02d}"

        _print_period_table(
            f"WEEKLY BREAKDOWN  (${initial_capital:,.0f} initial | ${initial_capital / n:,.0f}/slot × {n} slots)",
            _period_capital_groups(trade_rows, n, initial_capital, _week_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"WEEKLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _week_key),
                initial_capital,
            )

        _print_period_table(
            f"MONTHLY BREAKDOWN  (${initial_capital:,.0f} initial | ${initial_capital / n:,.0f}/slot × {n} slots)",
            _period_capital_groups(trade_rows, n, initial_capital, _month_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"MONTHLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _month_key),
                initial_capital,
            )

    print(f"\n{sep}\n")


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Backtest the op_momentum selector algorithm"
    )
    parser.add_argument(
        "--start", type=str, required=True, help="Eval start date YYYY-MM-DD"
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Eval end date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--top", type=int, default=3, help="Top-N picks per day (default: 3)"
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None, help="Override default ticker list"
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=ROLLING_LOOKBACK_DAYS,
        help=f"Rolling lookback in calendar days (default: {ROLLING_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=STOP_PCT,
        help=f"Hard stop as fraction of OR range (default: {STOP_PCT})",
    )
    parser.add_argument(
        "--source",
        choices=["alpaca", "yfinance"],
        default="alpaca",
        help="Market data source (default: alpaca)",
    )
    parser.add_argument(
        "--bearish-ma200",
        action="store_true",
        default=False,
        help="Require price < MA200 for bearish signal",
    )
    parser.add_argument(
        "--opening-bars",
        type=int,
        default=OPENING_BARS,
        help=f"Number of 5-min bars in opening period (default: {OPENING_BARS})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    tickers = args.tickers if args.tickers else DEFAULT_TICKERS
    eval_start = date.fromisoformat(args.start)
    eval_end = date.fromisoformat(args.end) if args.end else date.today()

    print(f"\nSelector Backtest")
    print(f"  Eval window  : {eval_start} → {eval_end}")
    print(f"  Top-N        : {args.top}")
    print(f"  Tickers      : {', '.join(tickers)}")
    print(f"  Lookback     : {args.lookback}d rolling")
    print(f"  Stop pct     : {args.stop_pct}")
    print(f"  Source       : {args.source}")

    trade_rows, full_results, trading_days = run_selector_backtest(
        n=args.top,
        tickers=tickers,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_days=args.lookback,
        opening_bars=args.opening_bars,
        bearish_ma200=args.bearish_ma200,
        stop_pct=args.stop_pct,
        source=args.source,
    )

    baseline_df = _collect_baseline(full_results, eval_start, eval_end)

    print("Fetching QQQ daily bars for comparison...")
    qqq_df = fetch_daily_bars(["QQQ"], eval_start, eval_end, source=args.source).get(
        "QQQ", pd.DataFrame()
    )
    qqq_closes = qqq_df["Close"] if not qqq_df.empty else pd.Series(dtype=float)

    _print_daily_table(trade_rows, n=args.top)
    _print_summary(
        trade_rows,
        baseline_df,
        n=args.top,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_days=args.lookback,
        stop_pct=args.stop_pct,
        initial_capital=INITIAL_CAPITAL,
        qqq_closes=qqq_closes,
    )
