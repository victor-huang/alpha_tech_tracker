import argparse
import os
import pandas as pd
import pytz
import yfinance as yf
from datetime import date, datetime, timedelta

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


TICKERS = ["NVDA", "CRWD", "COIN", "JNJ", "XOM", "CAT"]
SUCCESS_BARS = 3  # "long enough" = held correct side for >= 3 bars (15 min)
YFINANCE_MAX_DAYS = 60  # yfinance hard limit for 5-minute data


def fetch_yfinance_bars(tickers: list, start_date: date, end_date: date) -> dict:
    # yfinance only supports 5-min data for the last 60 days — historical ranges will fail
    result = {}
    for ticker in tickers:
        df = yf.download(
            ticker,
            start=start_date - timedelta(days=30),  # buffer for MA warmup
            end=end_date,
            interval="5m",
            auto_adjust=True,
            progress=False,
        )
        df.columns = df.columns.droplevel(1)
        df.index = df.index.tz_convert("America/New_York")
        result[ticker] = df
    return result


def fetch_alpaca_bars(
    tickers: list, start_date: date, end_date, allow_intraday: bool = False
) -> dict:
    key_id = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    client = StockHistoricalDataClient(key_id, secret_key)

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(tz=et)
    today_et = now_et.date()
    end_date_only = end_date.date() if isinstance(end_date, datetime) else end_date
    if not allow_intraday and end_date_only >= today_et:
        market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        if market_open_et <= now_et < market_close_et:
            raise ValueError(
                f"end_date {end_date} includes today but market hasn't closed yet "
                f"(current ET time: {now_et.strftime('%H:%M')}). "
                f"Re-run after 16:00 ET."
            )

    # MA200 on 5-min bars = 200 bars × 5 min = ~2.6 trading days; 5 calendar days is enough.
    fetch_start = datetime.combine(start_date - timedelta(days=5), datetime.min.time())
    if isinstance(end_date, datetime):
        fetch_end = end_date
    else:
        fetch_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    request = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
        start=fetch_start,
        end=fetch_end,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)

    result = {}
    for ticker in tickers:
        if ticker in bars.df.index.get_level_values(0):
            df = bars.df.xs(ticker, level=0).copy()
            df.index = df.index.tz_convert("America/New_York")
            df.columns = [c.capitalize() for c in df.columns]
            # Keep only regular market hours (9:30 AM – 4:00 PM ET)
            df = df.between_time("09:30", "16:00")
            result[ticker] = df
        else:
            result[ticker] = pd.DataFrame()
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="op_momentum_guide backtest")
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Number of calendar days to backtest (default: 14)",
    )
    parser.add_argument(
        "--opening-bars",
        type=int,
        default=3,
        help="Number of 5-min bars in the opening period (default: 3 = 15 min, 4 = 20 min)",
    )
    parser.add_argument(
        "--bearish-ma200",
        action="store_true",
        default=False,
        help="Require price < MA200 for bearish signal (use in bearish market regime, default: off)",
    )
    parser.add_argument(
        "--source",
        choices=["alpaca", "yfinance"],
        default="alpaca",
        help="Market data source (default: alpaca). yfinance is limited to 60 days.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override TICKERS list, e.g. --tickers NVDA CRWD COIN",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date for backtest window, YYYY-MM-DD (overrides --days)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date for backtest window, YYYY-MM-DD (default: today, requires --start)",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=0.15,
        help="Hard stop as a fraction of OR range from the favorable end (default: 0.15). "
        "Bull: exit if price drops below OR_high - stop_pct * OR_range. "
        "Bear: exit if price rises above OR_low + stop_pct * OR_range.",
    )
    parser.add_argument(
        "--trailing-ma",
        choices=["ma20", "ma50", "both"],
        default="ma20",
        help="Trailing MA stop to use once MA is above hard stop (default: ma20). "
        "ma20: use MA20 only. ma50: use MA50 only. both: use MA20 then MA50.",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=None,
        help="Per-trade max loss as a fraction of entry price (e.g. 0.02 = 2%%). "
        "Exit immediately if loss exceeds this threshold. Default: disabled.",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=False,
        help="Once hard stop is armed, use MA20 as the trailing exit instead of hard_stop_price. "
        "Lets winners run further but increases loss size on reversals. Default: off.",
    )
    return parser.parse_args()


def compute_signals_with_backtest(
    df: pd.DataFrame,
    opening_bars: int,
    bearish_ma200: bool = False,
    stop_pct: float = 0.40,
    opening_start_time: str = "09:30",
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
) -> pd.DataFrame:
    from datetime import time as dtime

    opening_start_t = datetime.strptime(opening_start_time, "%H:%M").time()

    df = df.copy()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    rows = []
    for date_, day_df in df.groupby(df.index.date):
        # Bars from opening_start onward define the opening range and post-open window.
        # All day bars (from 09:30) remain in df for accurate MA calculations.
        day_from_start = day_df[day_df.index.time >= opening_start_t]
        opening = day_from_start.head(opening_bars)
        if len(opening) < opening_bars:
            continue

        or_high = opening["High"].max()
        or_low = opening["Low"].min()
        or_range = or_high - or_low
        midpoint = (or_high + or_low) / 2
        bottom_30_threshold = or_low + 0.20 * or_range

        last_bar = opening.iloc[-1]
        close = last_bar["Close"]
        ma20 = last_bar["MA20"]
        ma200 = last_bar["MA200"]

        if pd.isna(ma20) or pd.isna(ma200):
            continue

        bearish_ma_ok = close < ma20 and (close < ma200 if bearish_ma200 else True)

        if close > midpoint and close > ma20 and close > ma200:
            signal = "BULLISH"
        elif close <= bottom_30_threshold and bearish_ma_ok:
            signal = "BEARISH"
        else:
            continue

        # Hard stop: bull exits if price drops back below the stop level after first crossing above it.
        # Bear exits if price rises back above the stop level after first crossing below it.
        # If price never crosses the stop level (no breakout confirmation), fall back to 20% from favorable end of OR range.
        # Bull fallback: OR_high - 20% × OR_range (80th percentile). Bear fallback: OR_low + 20% × OR_range (20th percentile).
        bull_hard_stop = or_high - stop_pct * or_range
        bear_hard_stop = or_low + stop_pct * or_range
        hard_stop_price = bull_hard_stop if signal == "BULLISH" else bear_hard_stop
        bull_fallback = or_high - 0.20 * or_range
        bear_fallback = or_low + 0.20 * or_range
        fallback_price = bull_fallback if signal == "BULLISH" else bear_fallback

        post_open = day_from_start.iloc[opening_bars:]
        bars_held = 0
        max_favorable_move = 0.0
        exit_price = fallback_price
        exit_reason = "fallback_20pct"
        hard_stop_armed = False

        for _, bar in post_open.iterrows():
            bar_ma20 = bar["MA20"]
            bar_ma50 = bar["MA50"]
            bar_close = bar["Close"]

            if signal == "BULLISH":
                if not hard_stop_armed and bar_close > hard_stop_price:
                    hard_stop_armed = True
                move = bar_close - midpoint
            else:
                if not hard_stop_armed and bar_close < hard_stop_price:
                    hard_stop_armed = True
                move = midpoint - bar_close

            # Max loss guard — highest priority exit
            if max_loss_pct is not None:
                loss_pct = (
                    (close - bar_close) / close
                    if signal == "BULLISH"
                    else (bar_close - close) / close
                )
                if loss_pct >= max_loss_pct:
                    exit_price = bar_close
                    exit_reason = "max_loss"
                    break

            if signal == "BULLISH":
                fallback_hit = not hard_stop_armed and bar_close <= fallback_price
                if hard_stop_armed and armed_ma20_exit:
                    # Armed MA20 mode: MA20 replaces hard_stop as the trailing exit
                    if trailing_ma in ("ma20", "both") and not pd.isna(bar_ma20):
                        ma20_trailing_stop_hit = bar_close < bar_ma20
                        ma20_exit_price, ma20_exit_reason = (
                            bar_close,
                            "trailing_stop_ma20",
                        )
                    else:
                        ma20_trailing_stop_hit = bar_close <= hard_stop_price
                        ma20_exit_price, ma20_exit_reason = hard_stop_price, "hard_stop"
                else:
                    hard_stop_hit = hard_stop_armed and bar_close <= hard_stop_price
                    ma20_trailing_stop_hit = (
                        not hard_stop_hit
                        and trailing_ma in ("ma20", "both")
                        and not pd.isna(bar_ma20)
                        and bar_ma20 > hard_stop_price
                        and bar_close < bar_ma20
                    )
                    ma20_exit_price, ma20_exit_reason = (
                        (hard_stop_price, "hard_stop")
                        if hard_stop_hit
                        else (bar_close, "trailing_stop_ma20")
                    )
                    ma20_trailing_stop_hit = ma20_trailing_stop_hit or hard_stop_hit
                trailing_stop_hit = (
                    trailing_ma in ("ma50", "both")
                    and not pd.isna(bar_ma50)
                    and bar_ma50 > hard_stop_price
                    and bar_close < bar_ma50
                )
            else:
                fallback_hit = not hard_stop_armed and bar_close >= fallback_price
                if hard_stop_armed and armed_ma20_exit:
                    if trailing_ma in ("ma20", "both") and not pd.isna(bar_ma20):
                        ma20_trailing_stop_hit = bar_close > bar_ma20
                        ma20_exit_price, ma20_exit_reason = (
                            bar_close,
                            "trailing_stop_ma20",
                        )
                    else:
                        ma20_trailing_stop_hit = bar_close >= hard_stop_price
                        ma20_exit_price, ma20_exit_reason = hard_stop_price, "hard_stop"
                else:
                    hard_stop_hit = hard_stop_armed and bar_close >= hard_stop_price
                    ma20_trailing_stop_hit = (
                        not hard_stop_hit
                        and trailing_ma in ("ma20", "both")
                        and not pd.isna(bar_ma20)
                        and bar_ma20 < or_low
                        and bar_close > bar_ma20
                    )
                    ma20_exit_price, ma20_exit_reason = (
                        (hard_stop_price, "hard_stop")
                        if hard_stop_hit
                        else (bar_close, "trailing_stop_ma20")
                    )
                    ma20_trailing_stop_hit = ma20_trailing_stop_hit or hard_stop_hit
                trailing_stop_hit = (
                    trailing_ma in ("ma50", "both")
                    and not pd.isna(bar_ma50)
                    and bar_ma50 < or_low
                    and bar_close > bar_ma50
                )

            if fallback_hit:
                if signal == "BULLISH":
                    exit_price = (
                        fallback_price if bar["High"] >= fallback_price else bar_close
                    )
                else:
                    exit_price = fallback_price
                exit_reason = "fallback_20pct"
                break
            elif ma20_trailing_stop_hit:
                exit_price = ma20_exit_price
                exit_reason = ma20_exit_reason
                break
            elif trailing_stop_hit:
                exit_price = bar_close
                exit_reason = "trailing_stop_ma50"
                break
            else:
                bars_held += 1
                max_favorable_move = max(max_favorable_move, move)
                if signal == "BULLISH":
                    exit_price = max(bar_close, midpoint)
                else:
                    exit_price = min(bar_close, midpoint)
                exit_reason = "end_of_day"

        if signal == "BULLISH":
            pnl = exit_price - close
        else:
            pnl = close - exit_price

        rows.append(
            {
                "date": date_,
                "signal": signal,
                "or_high": round(or_high, 2),
                "or_low": round(or_low, 2),
                "midpoint": round(midpoint, 2),
                "entry_price": round(close, 2),
                "exit_price": round(exit_price, 2),
                "pnl": round(pnl, 2),
                "exit_reason": exit_reason,
                "ma20": round(ma20, 2),
                "ma200": round(ma200, 2),
                "bars_held": bars_held,
                "mins_held": bars_held * 5,
                "max_favorable_move": round(max_favorable_move, 2),
                "held_to_close": exit_reason == "end_of_day",
                "total_post_bars": len(post_open),
                "success": pnl > 0,
            }
        )

    return pd.DataFrame(rows)


def print_successful_days(ticker: str, results: pd.DataFrame, backtest_days: int):
    wins = results[results["success"]].reset_index(drop=True)

    print(f"\n{'=' * 96}")
    print(
        f"  {ticker}  |  Successful signal days  |  Last {backtest_days} calendar days"
    )
    print(f"{'=' * 96}")
    print(
        f"  {'Date':<12} {'Signal':<9} {'Mid':>7} {'Entry':>7} {'Exit':>7} "
        f"{'P&L':>8} {'MinsHeld':>9} {'MaxMove':>9}  Exit Reason"
    )
    print(f"  {'-' * 94}")

    if wins.empty:
        print("  No successful signals in this period.")
        return

    for _, r in wins.iterrows():
        pnl_str = (
            f"+${abs(r['pnl']):.2f}" if r["pnl"] >= 0 else f"-${abs(r['pnl']):.2f}"
        )
        print(
            f"  {str(r['date']):<12} {r['signal']:<9} "
            f"{r['midpoint']:>7.2f} {r['entry_price']:>7.2f} {r['exit_price']:>7.2f} "
            f"{pnl_str:>8} {r['mins_held']:>9} "
            f"${r['max_favorable_move']:>8.2f}  {r['exit_reason']}"
        )


def print_stats(ticker: str, results: pd.DataFrame):
    if results.empty:
        print(f"\n  {ticker} — No signals fired in this period.")
        return

    total = len(results)
    successes = int(results["success"].sum())
    failures = total - successes
    rate = successes / total * 100

    bull = results[results["signal"] == "BULLISH"]
    bear = results[results["signal"] == "BEARISH"]

    avg_mins_success = (
        results[results["success"]]["bars_held"].mean() * 5 if successes else 0
    )
    avg_move = (
        results[results["success"]]["max_favorable_move"].mean() if successes else 0
    )
    held_all_day = int(results["held_to_close"].sum())
    total_pnl = results["pnl"].sum()
    win_pnl = results[results["success"]]["pnl"].sum()
    loss_pnl = results[~results["success"]]["pnl"].sum()

    print(f"\n  {ticker} — Stats")
    print(f"  {'─' * 52}")
    print(f"  Signals fired      : {total}  (bull={len(bull)}, bear={len(bear)})")
    print(
        f"  Success / Fail     : {successes} / {failures}  →  {rate:.0f}% success rate"
    )
    print(f"  Held all day       : {held_all_day} / {total}")
    print(f"  Avg mins held (W)  : {avg_mins_success:.0f} min")
    print(f"  Avg max move (W)   : ${avg_move:.2f} from midpoint")
    print(f"  Win P&L            : +${win_pnl:.2f}")
    print(f"  Loss P&L           : -${abs(loss_pnl):.2f}")
    print(f"  Net P&L            : {'+' if total_pnl >= 0 else ''}${total_pnl:.2f}")
    if not bull.empty:
        print(
            f"  Bullish success    : {int(bull['success'].sum())}/{len(bull)} = {bull['success'].mean() * 100:.0f}%"
        )
    if not bear.empty:
        print(
            f"  Bearish success    : {int(bear['success'].sum())}/{len(bear)} = {bear['success'].mean() * 100:.0f}%"
        )


def print_daily_pnl(all_results: dict, backtest_days: int):
    # Combine all tickers, pivot by date
    frames = []
    for ticker, df in all_results.items():
        if df.empty:
            continue
        tmp = df[
            ["date", "signal", "entry_price", "exit_price", "pnl", "success"]
        ].copy()
        tmp["ticker"] = ticker
        frames.append(tmp)

    if not frames:
        return

    combined = pd.concat(frames, ignore_index=True)
    all_dates = sorted(combined["date"].unique())

    print(f"\n{'=' * 82}")
    print(
        f"  DAILY P&L REPORT  |  Last {backtest_days} calendar days  |  1 share per signal"
    )
    print(f"{'=' * 82}")

    grand_total = 0.0
    for d in all_dates:
        day = combined[combined["date"] == d]
        wins = day[day["success"]]
        losses = day[~day["success"]]
        win_count = len(wins)
        loss_count = len(losses)
        day_pnl = day["pnl"].sum()
        grand_total += day_pnl

        pnl_str = f"+${day_pnl:.2f}" if day_pnl >= 0 else f"-${abs(day_pnl):.2f}"
        print(
            f"\n  {d}  |  signals={len(day)}  wins={win_count}  losses={loss_count}  "
            f"day P&L: {pnl_str}"
        )
        print(f"  {'─' * 78}")
        print(
            f"  {'Ticker':<7} {'Signal':<9} {'Entry':>8} {'Exit':>8} {'P&L':>9}  Result"
        )
        print(f"  {'─' * 78}")

        for _, r in day.iterrows():
            result = "WIN " if r["success"] else "LOSS"
            pnl_str_row = (
                f"+${abs(r['pnl']):.2f}" if r["pnl"] >= 0 else f"-${abs(r['pnl']):.2f}"
            )
            print(
                f"  {r['ticker']:<7} {r['signal']:<9} "
                f"{r['entry_price']:>8.2f} {r['exit_price']:>8.2f} "
                f"{pnl_str_row:>9}  {result}"
            )

    grand_str = (
        f"+${grand_total:.2f}" if grand_total >= 0 else f"-${abs(grand_total):.2f}"
    )
    print(f"\n{'=' * 82}")
    print(f"  TOTAL P&L ({backtest_days}-day window, 1 share per signal): {grand_str}")
    print(f"{'=' * 82}")


def print_pnl_distribution(all_results: dict, backtest_days: int, trading_dates: list):
    tickers = [t for t, df in all_results.items() if not df.empty]
    if not tickers:
        return

    frames = []
    for ticker, df in all_results.items():
        if df.empty:
            continue
        tmp = df[["date", "pnl", "signal", "success"]].copy()
        tmp["ticker"] = ticker
        frames.append(tmp)

    combined = pd.concat(frames, ignore_index=True)
    all_dates = sorted(trading_dates)

    col_w = 14
    ticker_col_w = 10

    header = f"  {'Date':<12}"
    for t in tickers:
        header += f"  {t:>{col_w}}"
    header += f"  {'DayTotal':>{col_w}}  Tickers W/L"
    divider = "  " + "─" * (12 + (col_w + 2) * (len(tickers) + 1) + 16)

    print(f"\n{'=' * len(divider)}")
    print(
        f"  P&L DISTRIBUTION — Last {backtest_days} calendar days  |  MA20/MA50 trailing stop"
    )
    print(f"{'=' * len(divider)}")
    print(header)
    print(divider)

    ticker_totals = {t: 0.0 for t in tickers}
    ticker_wins = {t: 0 for t in tickers}
    ticker_trades = {t: 0 for t in tickers}
    grand_total = 0.0

    for d in all_dates:
        day = combined[combined["date"] == d]
        row = f"  {str(d):<12}"
        day_total = 0.0
        win_count = 0
        loss_count = 0

        for t in tickers:
            trade = day[day["ticker"] == t]
            if trade.empty:
                row += f"  {'—':>{col_w}}"
            else:
                pnl = trade["pnl"].values[0]
                success = trade["success"].values[0]
                day_total += pnl
                ticker_totals[t] += pnl
                ticker_trades[t] += 1
                if success:
                    ticker_wins[t] += 1
                    win_count += 1
                    tag = f"W +${pnl:.2f}" if pnl >= 0 else f"W -${abs(pnl):.2f}"
                else:
                    loss_count += 1
                    tag = f"L -${abs(pnl):.2f}" if pnl < 0 else f"L +${pnl:.2f}"
                row += f"  {tag:>{col_w}}"

        grand_total += day_total
        if win_count == 0 and loss_count == 0:
            row += f"  {'no signal':>{col_w}}  —"
        else:
            day_str = (
                f"+${day_total:.2f}" if day_total >= 0 else f"-${abs(day_total):.2f}"
            )
            row += f"  {day_str:>{col_w}}  {win_count}W / {loss_count}L"
        print(row)

    print(divider)

    # totals row
    total_row = f"  {'TOTAL':<12}"
    for t in tickers:
        v = ticker_totals[t]
        tag = f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"
        total_row += f"  {tag:>{col_w}}"
    grand_str = (
        f"+${grand_total:.2f}" if grand_total >= 0 else f"-${abs(grand_total):.2f}"
    )
    total_row += f"  {grand_str:>{col_w}}"
    print(total_row)

    # win rate row
    rate_row = f"  {'WIN RATE':<12}"
    for t in tickers:
        n = ticker_trades[t]
        w = ticker_wins[t]
        rate_row += f"  {f'{w}/{n} = {w / n * 100:.0f}%' if n else '—':>{col_w}}"
    rate_row += f"  {'':>{col_w}}"
    print(rate_row)

    print(f"{'=' * len(divider)}\n")


def print_monthly_breakdown(all_results: dict, opening_bars: int):
    frames = []
    for ticker, df in all_results.items():
        if df.empty:
            continue
        tmp = df[["date", "pnl", "success", "bars_held"]].copy()
        tmp["ticker"] = ticker
        tmp["month"] = pd.to_datetime(tmp["date"]).dt.to_period("M")
        frames.append(tmp)

    if not frames:
        return

    combined = pd.concat(frames, ignore_index=True)
    tickers = list(all_results.keys())
    months = sorted(combined["month"].unique())

    print(f"\n{'=' * 70}")
    print(f"  MONTHLY BREAKDOWN — op_momentum_guide  |  {opening_bars * 5}-min opening")
    print(f"{'=' * 70}")
    print(
        f"  {'Month':<10} {'Ticker':<8} {'Signals':>8} {'Wins':>6} {'Fails':>6} {'Rate':>7} {'NetP&L':>9}"
    )
    print(f"  {'─' * 68}")

    for month in months:
        month_data = combined[combined["month"] == month]
        month_net = 0.0
        first = True
        for ticker in tickers:
            rows = month_data[month_data["ticker"] == ticker]
            if rows.empty:
                continue
            total = len(rows)
            wins = int(rows["success"].sum())
            fails = total - wins
            rate = wins / total * 100
            net = rows["pnl"].sum()
            month_net += net
            net_str = f"+${net:.2f}" if net >= 0 else f"-${abs(net):.2f}"
            month_label = str(month) if first else ""
            print(
                f"  {month_label:<10} {ticker:<8} {total:>8} {wins:>6} {fails:>6} {rate:>6.0f}%  {net_str:>9}"
            )
            first = False

        net_str = f"+${month_net:.2f}" if month_net >= 0 else f"-${abs(month_net):.2f}"
        print(f"  {'':10} {'─' * 58}")
        print(
            f"  {'':10} {'Month total':<8} {'':>8} {'':>6} {'':>6} {'':>7}  {net_str:>9}"
        )
        print()

    grand = combined["pnl"].sum()
    grand_str = f"+${grand:.2f}" if grand >= 0 else f"-${abs(grand):.2f}"
    print(f"  {'─' * 68}")
    print(
        f"  {'TOTAL':<10} {'all':<8} {len(combined):>8} {int(combined['success'].sum()):>6} "
        f"{len(combined) - int(combined['success'].sum()):>6} "
        f"{combined['success'].mean() * 100:>6.0f}%  {grand_str:>9}"
    )
    print(f"{'=' * 70}")


def print_summary(all_results: dict, backtest_days: int, opening_bars: int):
    print(f"\n{'=' * 96}")
    print(
        f"  SUMMARY — op_momentum_guide  |  Last {backtest_days} days  |  {opening_bars * 5}-min opening"
    )
    print(f"{'=' * 96}")
    print(
        f"  {'Ticker':<8} {'Signals':>8} {'Wins':>6} {'Fails':>6} {'Rate':>7} "
        f"{'AvgMins(W)':>11} {'AvgWin%':>8} {'AvgLoss%':>9} {'EV/Trade':>9} {'WinP&L':>9} {'LossP&L':>9} {'NetP&L':>9}"
    )
    print(f"  {'─' * 94}")

    total_net = 0.0
    all_win_pcts = []
    all_loss_pcts = []
    for ticker, results in all_results.items():
        if results.empty:
            print(f"  {ticker:<8} {'no signals':>8}")
            continue
        total = len(results)
        wins = int(results["success"].sum())
        fails = total - wins
        win_rate = wins / total
        loss_rate = fails / total
        avg_mins = results[results["success"]]["bars_held"].mean() * 5 if wins else 0

        win_rows = results[results["success"]]
        loss_rows = results[~results["success"]]

        win_pct_series = win_rows["pnl"] / win_rows["entry_price"] * 100
        avg_win_pct = win_pct_series.mean() if wins else 0
        all_win_pcts.extend(win_pct_series.tolist())

        loss_pct_series = loss_rows["pnl"].abs() / loss_rows["entry_price"] * 100
        avg_loss_pct = loss_pct_series.mean() if fails else 0
        all_loss_pcts.extend(loss_pct_series.tolist())

        ev = win_rate * avg_win_pct - loss_rate * avg_loss_pct

        win_pnl = win_rows["pnl"].sum()
        loss_pnl = loss_rows["pnl"].sum()
        net_pnl = results["pnl"].sum()
        total_net += net_pnl

        ev_str = f"+{ev:.3f}%" if ev >= 0 else f"{ev:.3f}%"
        net_str = f"+${net_pnl:.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):.2f}"
        win_str = f"+${win_pnl:.2f}" if win_pnl >= 0 else f"-${abs(win_pnl):.2f}"
        loss_str = f"-${abs(loss_pnl):.2f}"
        print(
            f"  {ticker:<8} {total:>8} {wins:>6} {fails:>6} {win_rate * 100:>6.0f}%"
            f" {avg_mins:>10.0f}m  {avg_win_pct:>7.2f}%  {avg_loss_pct:>8.2f}%  {ev_str:>9}"
            f"  {win_str:>9}  {loss_str:>9}  {net_str:>9}"
        )

    print(f"  {'─' * 94}")
    total_str = f"+${total_net:.2f}" if total_net >= 0 else f"-${abs(total_net):.2f}"
    overall_avg_win_pct = sum(all_win_pcts) / len(all_win_pcts) if all_win_pcts else 0
    overall_avg_loss_pct = (
        sum(all_loss_pcts) / len(all_loss_pcts) if all_loss_pcts else 0
    )
    total_wins = sum(len(r[r["success"]]) for r in all_results.values() if not r.empty)
    total_sigs = sum(len(r) for r in all_results.values() if not r.empty)
    overall_win_rate = total_wins / total_sigs if total_sigs else 0
    overall_ev = (
        overall_win_rate * overall_avg_win_pct
        - (1 - overall_win_rate) * overall_avg_loss_pct
    )
    overall_ev_str = f"+{overall_ev:.3f}%" if overall_ev >= 0 else f"{overall_ev:.3f}%"
    print(
        f"  {'TOTAL':<8} {'':>8} {'':>6} {'':>6} {'':>7} {'':>11}"
        f"  {overall_avg_win_pct:>7.2f}%  {overall_avg_loss_pct:>8.2f}%  {overall_ev_str:>9}"
        f"  {'':>9}  {'':>9} {total_str:>9}"
    )
    print(f"{'=' * 96}")


def fetch_bars(
    tickers: list,
    start_date: date,
    end_date,
    source: str = "alpaca",
    allow_intraday: bool = False,
) -> dict:
    if source == "yfinance":
        return fetch_yfinance_bars(tickers, start_date, end_date)
    return fetch_alpaca_bars(
        tickers, start_date, end_date, allow_intraday=allow_intraday
    )


def fetch_daily_bars(
    tickers: list, start_date: date, end_date: date, source: str = "alpaca"
) -> dict:
    """Fetch 1-day bars for the given tickers. Returns {ticker: DataFrame} with date index."""
    if source == "yfinance":
        result = {}
        for ticker in tickers:
            df = yf.download(
                ticker,
                start=start_date,
                end=end_date + timedelta(days=1),
                interval="1d",
                auto_adjust=True,
                progress=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.index = pd.to_datetime(df.index).date
            result[ticker] = df
        return result

    key_id = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    client = StockHistoricalDataClient(key_id, secret_key)
    request = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Day),
        start=datetime.combine(start_date, datetime.min.time()),
        end=datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    result = {}
    for ticker in tickers:
        if ticker in bars.df.index.get_level_values(0):
            df = bars.df.xs(ticker, level=0).copy()
            df.index = [pd.Timestamp(t).date() for t in df.index]
            df.columns = [c.capitalize() for c in df.columns]
            result[ticker] = df
        else:
            result[ticker] = pd.DataFrame()
    return result


def run_backtest(
    tickers: list,
    start_date: date,
    end_date: date,
    opening_bars: int = 3,
    bearish_ma200: bool = False,
    stop_pct: float = 0.15,
    source: str = "alpaca",
    ticker_dfs: dict = None,
    opening_start_time: str = "09:30",
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
) -> dict:
    if ticker_dfs is None:
        ticker_dfs = fetch_bars(tickers, start_date, end_date, source=source)
    all_results = {}
    for ticker in tickers:
        df = ticker_dfs.get(ticker, pd.DataFrame())
        if df.empty:
            all_results[ticker] = pd.DataFrame()
            continue
        results = compute_signals_with_backtest(
            df,
            opening_bars,
            bearish_ma200,
            stop_pct,
            opening_start_time,
            trailing_ma,
            max_loss_pct=max_loss_pct,
            armed_ma20_exit=armed_ma20_exit,
        )
        if not results.empty:
            results = results[results["date"] >= start_date].reset_index(drop=True)
        all_results[ticker] = results
    return all_results


if __name__ == "__main__":
    args = parse_args()
    source = args.source
    opening_bars = args.opening_bars
    bearish_ma200 = args.bearish_ma200
    stop_pct = args.stop_pct
    tickers = args.tickers if args.tickers else TICKERS

    if args.start:
        cutoff = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end) if args.end else date.today()
    else:
        end_date = date.today()
        if source == "yfinance" and args.days > YFINANCE_MAX_DAYS:
            print(
                f"Warning: yfinance only supports up to {YFINANCE_MAX_DAYS} days for 5-min data. Capping at {YFINANCE_MAX_DAYS}."
            )
            args.days = YFINANCE_MAX_DAYS
        cutoff = end_date - timedelta(days=args.days)

    backtest_days = (end_date - cutoff).days
    period_label = f"{cutoff} → {end_date}  ({backtest_days} calendar days)"

    trailing_ma = args.trailing_ma
    max_loss_pct = args.max_loss_pct
    armed_ma20_exit = args.armed_ma20_exit
    bearish_filter = "MA20 + MA200" if bearish_ma200 else "MA20 only"
    trailing_ma_label = {
        "ma20": "MA20 only",
        "ma50": "MA50 only",
        "both": "MA20 then MA50",
    }[trailing_ma]
    print(f"\nop_momentum_guide backtest — {period_label} ({source})")
    print(f"Tickers           : {', '.join(tickers)}")
    print(
        f"Opening period    : first {opening_bars * 5} min ({opening_bars} x 5-min bars)"
    )
    print(
        f"Exit rule         : trailing stop ({trailing_ma_label}, when MA > hard stop)  |  hard stop at {stop_pct * 100:.0f}% from favorable end of OR"
    )
    print(
        f"  → Bull hard stop: OR_high - {stop_pct * 100:.0f}% × OR_range  |  Bear hard stop: OR_low + {stop_pct * 100:.0f}% × OR_range"
    )
    print(
        f"Bearish filter    : {bearish_filter}  (use --bearish-ma200 to add MA200 requirement)"
    )

    print(f"\nFetching {len(tickers)} tickers from {source} ({cutoff} → {end_date})...")

    if source == "alpaca":
        ticker_dfs = fetch_alpaca_bars(tickers, cutoff, end_date)
    else:
        ticker_dfs = fetch_yfinance_bars(tickers, cutoff, end_date)

    all_results = {}
    trading_dates = set()

    for ticker in tickers:
        df = ticker_dfs.get(ticker, pd.DataFrame())
        if df.empty:
            print(f"\n  {ticker}: no data returned from {source}")
            all_results[ticker] = pd.DataFrame()
            continue

        # collect all trading days within the backtest window
        for d in df.index.date:
            if d >= cutoff:
                trading_dates.add(d)

        results = compute_signals_with_backtest(
            df,
            opening_bars,
            bearish_ma200,
            stop_pct,
            trailing_ma=trailing_ma,
            max_loss_pct=max_loss_pct,
            armed_ma20_exit=armed_ma20_exit,
        )
        if not results.empty:
            results = results[results["date"] >= cutoff].reset_index(drop=True)

        all_results[ticker] = results
        print_successful_days(ticker, results, backtest_days)
        print_stats(ticker, results)

    print_daily_pnl(all_results, backtest_days)
    print_pnl_distribution(all_results, backtest_days, trading_dates)
    print_monthly_breakdown(all_results, opening_bars)
    print_summary(all_results, backtest_days, opening_bars)
