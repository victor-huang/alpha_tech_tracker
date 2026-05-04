import argparse
import pandas as pd
import pytz
from datetime import date, datetime, timedelta

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    build_bearish_regime_dates,
    fetch_bars,
    run_backtest,
    compute_signals_with_backtest,
)


_ET = pytz.timezone("America/New_York")


def _safe_bars_end(target_date: date):
    """
    Returns the safe end boundary for intraday bar fetches to avoid Alpaca's
    'recent SIP data' restriction.

    - Historical date (before today): return date + 1 (safe, already in the past).
    - Today, pre-market (before 9:30 AM ET): return target_date so the request
      ends at yesterday's close.
    - Today, market open or later: return the current datetime in ET so the
      request ends right now rather than at midnight UTC tonight (which is still
      in the future and triggers the 403).
    """
    now_et = datetime.now(_ET)
    if target_date < now_et.date():
        return target_date + timedelta(days=1)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if now_et >= market_open:
        return now_et
    return target_date


# DEFAULT_TICKERS = ["SNDK", "APP", "SHOP", "CVNA", "AMD", "META", "EXPE", "FANG"]
# v2 pool: added PLTR, COIN, NVDA — 5yr backtest 2021-2025: +330% vs +319% original
# GS and REGN: $2.50/signal over 90 days from 3/26/2026, during down trend
# removed UI 2026-03-31: Alpaca returns only sparse extended-hours bars, no reliable morning session data
# removed ISSC, added RH 2026-04-01: swap gains +19pp over 5 years; RH has cleaner OR breakouts
# removed FANG (structurally weak, +1-2% in Q1/Q2 2025 and Q1 2026), NVDA (fading trend, +0.6% Q4 2024),
# TSLA (peaked Q2/Q3 2025, declining to +6.5% Q1 2026) — replaced with CLS, MSTR, CRWV, MRVL (2026-04-12)
DEFAULT_TICKERS = [
    "SNDK",
    "APP",
    "SHOP",
    "CVNA",
    "AMD",
    "META",
    "EXPE",
    "JPM",
    "TSLA",
    "MU",
    "CRDO", # replaced ANAB 2026-04-10: sparse live data; CRDO has min 72 bars/day, 3.65% OR
    "PLTR",
    "COIN",
    "CLS",  # replaced FANG 2026-04-12: CLS +12-39% per quarter vs FANG structurally weak
    "MSTR", # replaced NVDA 2026-04-12: MSTR consistent +8-56%, NVDA fading (+0.6% Q4 2024)
    "CRWV", # replaced TSLA 2026-04-12: CRWV accelerating (+24% Q4 2025, +37% Q1 2026); TSLA peaked
    "MRVL", # added 2026-04-12: high-variance but strong peaks (+40% Q2 2025, +28% Q1 2026)
]

# AT pool (2026-04-12): removed ANAB, RH, FN, EXPE, FANG (sparse bars / low trade count
# from March 2026 data); added RKLB, ASTS, HOOD (Russell 2000 active), MSTR, NFLX (large-cap).
# CRWD → MSTR swap: MSTR wins 5/7 years vs CRWD (+4.5pp over 7 years); BTC-correlated beta driver.
ACTIVELY_TRADE_TICKERS = [
    "SNDK",
    "APP",
    "SHOP",
    "CVNA",
    "AMD",
    "META",
    "MU",
    "PLTR",
    "COIN",
    "NVDA",
    "TSLA",
    "RKLB",
    "ASTS",
    "HOOD",
    "MSTR",
    "NFLX",
]
ROLLING_LOOKBACK_DAYS = 60
OPENING_BARS = 3
OPENING_START_TIME = "09:30"
STOP_PCT = 0.15


def compute_ticker_stats(results_df: pd.DataFrame) -> dict:
    if results_df.empty:
        return {
            "signals": 0,
            "win_rate": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "ev_trade": 0.0,
            "avg_entry_vs_mid_pct": 0.0,
        }

    total = len(results_df)
    wins = results_df[results_df["success"]]
    losses = results_df[~results_df["success"]]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total
    loss_rate = loss_count / total

    avg_win_pct = (wins["pnl"] / wins["entry_price"] * 100).mean() if win_count else 0.0
    avg_loss_pct = (
        (losses["pnl"].abs() / losses["entry_price"] * 100).mean()
        if loss_count
        else 0.0
    )
    ev_trade = win_rate * avg_win_pct - loss_rate * avg_loss_pct

    if win_count:
        avg_entry_vs_mid_pct = (
            (wins["entry_price"] - wins["midpoint"]).abs() / wins["midpoint"] * 100
        ).mean()
    else:
        avg_entry_vs_mid_pct = 0.0

    return {
        "signals": total,
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ev_trade": ev_trade,
        "avg_entry_vs_mid_pct": avg_entry_vs_mid_pct,
    }


def compute_today_signals(
    ticker_dfs: dict,
    opening_bars: int,
    bearish_ma200: bool,
    stop_pct: float,
    target_date: date = None,
    opening_start_time: str = OPENING_START_TIME,
    or_bar_lookback: int = 3,
    bearish_regime_dates: set = None,
) -> dict:
    if target_date is None:
        target_date = datetime.now(_ET).date()

    opening_start_t = datetime.strptime(opening_start_time, "%H:%M").time()

    signals = {}
    for ticker, df in ticker_dfs.items():
        if df.empty:
            continue

        results = compute_signals_with_backtest(
            df, opening_bars, bearish_ma200, stop_pct,
            opening_start_time=opening_start_time,
            bearish_regime_dates=bearish_regime_dates,
        )
        if results.empty:
            continue

        today_rows = results[results["date"] == target_date]
        if today_rows.empty:
            continue

        _false = pd.Series(False, index=today_rows.index)
        primary_rows = today_rows[
            (today_rows.get("is_reversal", _false) != True)  # noqa: E712
            & (today_rows.get("is_bearish_reentry", _false) != True)  # noqa: E712
            & (today_rows.get("is_bullish_reentry", _false) != True)  # noqa: E712
        ]
        if primary_rows.empty:
            continue
        row = primary_rows.iloc[0]
        entry = row["entry_price"]
        mid = row["midpoint"]
        or_high = row["or_high"]
        or_low = row["or_low"]
        or_range = or_high - or_low
        entry_vs_mid_pct = abs(entry - mid) / mid * 100 if mid != 0 else 0.0

        if or_bar_lookback > 0:
            day_df_full = df[df.index.date == target_date]
            pre_opening = day_df_full[day_df_full.index.time < opening_start_t].tail(or_bar_lookback)
            if len(pre_opening) > 0:
                avg_recent_bar_range = (pre_opening["High"] - pre_opening["Low"]).mean()
                if or_range < avg_recent_bar_range / 4:
                    or_range = avg_recent_bar_range

        or_range_pct = or_range / entry * 100 if entry != 0 else 0.0

        # Pull MA50 from the bar data at the opening period close on target_date
        day_df = df[df.index.date == target_date]
        ma50 = float("nan")
        if not day_df.empty and "MA50" in day_df.columns:
            opening_close = (
                day_df.iloc[opening_bars - 1]
                if len(day_df) >= opening_bars
                else day_df.iloc[-1]
            )
            ma50 = opening_close["MA50"]
        else:
            # Compute MA50 if not present
            df_copy = df.copy()
            df_copy["MA50"] = df_copy["Close"].rolling(50).mean()
            day_df_copy = df_copy[df_copy.index.date == target_date]
            if not day_df_copy.empty:
                opening_close = (
                    day_df_copy.iloc[opening_bars - 1]
                    if len(day_df_copy) >= opening_bars
                    else day_df_copy.iloc[-1]
                )
                ma50 = opening_close["MA50"]

        signals[ticker] = {
            "signal": row["signal"],
            "or_high": float(or_high),
            "or_low": float(or_low),
            "or_range": float(or_range),
            "midpoint": float(mid),
            "entry_price": float(entry),
            "entry_vs_mid_pct": float(entry_vs_mid_pct),
            "or_range_pct": float(or_range_pct),
            "ma20": float(row["ma20"]),
            "ma50": float(ma50) if not pd.isna(ma50) else float("nan"),
            "ma200": float(row["ma200"]),
        }

    return signals


def score_ticker(signal_dict: dict, ticker_stats: dict) -> float:
    if ticker_stats["ev_trade"] <= 0:
        return 0.0
    return (
        signal_dict["entry_vs_mid_pct"] * 0.50
        + ticker_stats["avg_win_pct"] * 0.30
        + signal_dict["or_range_pct"] * 0.20
    )


def select_top_n(
    n: int,
    tickers: list,
    lookback_days: int,
    opening_bars: int,
    bearish_ma200: bool,
    stop_pct: float,
    source: str,
    target_date: date = None,
    ticker_dfs: dict = None,
    opening_start_time: str = OPENING_START_TIME,
    or_bar_lookback: int = 3,
    regime_filter: bool = False,
    regime_ma: int = 8,
    close_top_pct: float = None,
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
    feed: DataFeed = None,
) -> list:
    if target_date is None:
        target_date = datetime.now(_ET).date()

    lookback_start = target_date - timedelta(days=lookback_days)

    if ticker_dfs is None:
        # Single fetch covering both the rolling lookback and MA warmup windows.
        # MA warmup needs 30 days; use min() so a longer lookback_days still works.
        ma_warmup_start = target_date - timedelta(days=30)
        fetch_start = min(lookback_start, ma_warmup_start)
        ticker_dfs = fetch_bars(
            tickers,
            fetch_start,
            _safe_bars_end(target_date),
            source=source,
        )

    all_results = run_backtest(
        tickers=tickers,
        start_date=lookback_start,
        end_date=target_date,
        opening_bars=opening_bars,
        bearish_ma200=bearish_ma200,
        stop_pct=stop_pct,
        source=source,
        ticker_dfs=ticker_dfs,
        opening_start_time=opening_start_time,
        or_bar_lookback=or_bar_lookback,
        regime_filter=regime_filter,
        regime_ma=regime_ma,
        close_top_pct=close_top_pct,
        trailing_ma=trailing_ma,
        max_loss_pct=max_loss_pct,
        armed_ma20_exit=armed_ma20_exit,
    )

    rolling_stats = {
        ticker: compute_ticker_stats(
            df[df["date"] < target_date] if not df.empty else df
        )
        for ticker, df in all_results.items()
    }

    _bearish_regime_dates = (
        build_bearish_regime_dates(lookback_start, target_date, source, regime_ma, feed=feed)
        if regime_filter
        else None
    )
    today_signals = compute_today_signals(
        ticker_dfs, opening_bars, bearish_ma200, stop_pct, target_date,
        opening_start_time=opening_start_time,
        or_bar_lookback=or_bar_lookback,
        bearish_regime_dates=_bearish_regime_dates,
    )

    scored = []
    no_signal = []
    negative_ev = []

    for ticker in tickers:
        if ticker not in today_signals:
            no_signal.append(ticker)
            continue

        sig = today_signals[ticker]
        stats = rolling_stats.get(ticker, compute_ticker_stats(pd.DataFrame()))

        if stats["ev_trade"] <= 0:
            negative_ev.append(ticker)
            continue

        s = score_ticker(sig, stats)
        scored.append(
            {
                "ticker": ticker,
                "signal": sig["signal"],
                "score": round(s, 3),
                "entry_vs_mid_pct": round(sig["entry_vs_mid_pct"], 3),
                "or_range_pct": round(sig["or_range_pct"], 3),
                "ev_trade": round(stats["ev_trade"], 3),
                "win_rate": round(stats["win_rate"], 3),
                "avg_win_pct": round(stats["avg_win_pct"], 3),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:n]

    return {
        "picks": top,
        "no_signal": no_signal,
        "negative_ev": negative_ev,
        "rolling_stats": rolling_stats,
    }


def _parse_args():
    parser = argparse.ArgumentParser(
        description="op_momentum live top-N stock selector"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of top tickers to select (default: 3)",
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None, help="Override default ticker list"
    )
    parser.add_argument(
        "--ticker-set",
        choices=["V3", "AT"],
        default=None,
        help="Named ticker set: V3 (default pool) or AT (ACTIVELY_TRADE_TICKERS)",
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
        "--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)"
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
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET (default: {OPENING_START_TIME})",
    )
    parser.add_argument(
        "--or-bar-lookback",
        type=int,
        default=3,
        dest="or_bar_lookback",
        help="If OR range < 1/4 of avg High-Low of last N bars before the window, use that avg as the effective OR range for scoring. Default: 3.",
    )
    return parser.parse_args()


def _print_table(
    picks: list,
    target_date: date,
    opening_bars: int,
    lookback_days: int,
    stop_pct: float,
):
    sep = "\u2501" * 78
    opening_mins = opening_bars * 5
    print(
        f"\nTop {len(picks)} picks for {target_date}  "
        f"({opening_mins}-min opening, stop-pct {stop_pct}, {lookback_days}-day rolling stats)"
    )
    print(sep)
    print(
        f"{'Rank':>4}  {'Ticker':<7} {'Signal':<9} {'Score':>6}  "
        f"{'Entry%vMid':>10}  {'OR Range%':>9}  {'EV/Trade':>9}  {'WinRate':>8}  {'AvgWin%':>8}"
    )
    print(sep)

    if not picks:
        print("  No tickers with a signal and positive EV today.")
    else:
        for i, p in enumerate(picks, 1):
            ev_str = (
                f"+{p['ev_trade']:.3f}%"
                if p["ev_trade"] >= 0
                else f"{p['ev_trade']:.3f}%"
            )
            print(
                f"{i:>4}   {p['ticker']:<7} {p['signal']:<9} {p['score']:>6.3f}  "
                f"{p['entry_vs_mid_pct']:>9.2f}%  {p['or_range_pct']:>8.2f}%  "
                f"{ev_str:>9}  {p['win_rate'] * 100:>7.0f}%  {p['avg_win_pct']:>7.2f}%"
            )

    print(sep)


if __name__ == "__main__":
    args = _parse_args()
    _TICKER_SETS = {"V3": DEFAULT_TICKERS, "AT": ACTIVELY_TRADE_TICKERS}
    tickers = args.tickers or _TICKER_SETS.get(args.ticker_set, DEFAULT_TICKERS)
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    print(f"Fetching data and computing signals for {target_date}...")

    result = select_top_n(
        n=args.top,
        tickers=tickers,
        lookback_days=args.lookback,
        opening_bars=args.opening_bars,
        bearish_ma200=args.bearish_ma200,
        stop_pct=args.stop_pct,
        source=args.source,
        target_date=target_date,
        opening_start_time=args.opening_start,
        or_bar_lookback=args.or_bar_lookback,
    )

    picks = result["picks"]
    no_signal = result["no_signal"]
    negative_ev = result["negative_ev"]

    _print_table(picks, target_date, args.opening_bars, args.lookback, args.stop_pct)

    if no_signal:
        no_sig_str = ", ".join(f"{t} (no signal fired)" for t in no_signal)
        print(f"No signal today: {no_sig_str}")
    if negative_ev:
        print(f"Excluded (negative EV): {', '.join(negative_ev)}")
    if not no_signal and not negative_ev:
        print("No excluded tickers.")
