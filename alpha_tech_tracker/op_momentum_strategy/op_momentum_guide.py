import pandas as pd
import yfinance as yf


TICKERS = ["APP", "NVDA", "MSFT", "QQQ"]
INTERVAL = "5m"
# 60d needed to build enough history for the 200-period MA (200 x 5min ≈ 16 trading days)
PERIOD = "60d"
# 3 bars = 15 min, 4 bars = 20 min
OPENING_BARS = 3


def compute_op_momentum_guide(df: pd.DataFrame, opening_bars: int = OPENING_BARS) -> pd.DataFrame:
    df = df.copy()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    rows = []
    for date, day_df in df.groupby(df.index.date):
        opening = day_df.head(opening_bars)
        if len(opening) < opening_bars:
            continue

        or_high = opening["High"].max()
        or_low = opening["Low"].min()
        or_range = or_high - or_low
        midpoint = (or_high + or_low) / 2
        bottom_10_threshold = or_low + 0.10 * or_range

        last_bar = opening.iloc[-1]
        close = last_bar["Close"]
        ma20 = last_bar["MA20"]
        ma200 = last_bar["MA200"]

        price_pct_in_range = ((close - or_low) / or_range * 100) if or_range > 0 else 50.0

        if pd.isna(ma20) or pd.isna(ma200):
            signal = "NO_DATA"
        elif close > midpoint and close > ma20 and close > ma200:
            signal = "BULLISH"
        elif close <= bottom_10_threshold and close < ma20 and close < ma200:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        rows.append({
            "date": date,
            "or_high": round(or_high, 2),
            "or_low": round(or_low, 2),
            "midpoint": round(midpoint, 2),
            "bottom_10_threshold": round(bottom_10_threshold, 2),
            "close": round(close, 2),
            "price_pct_in_range": round(price_pct_in_range, 1),
            "ma20": round(ma20, 2) if not pd.isna(ma20) else None,
            "ma200": round(ma200, 2) if not pd.isna(ma200) else None,
            "signal": signal,
        })

    return pd.DataFrame(rows)


def signal_badge(signal: str) -> str:
    return {"BULLISH": "▲ BULLISH", "BEARISH": "▼ BEARISH", "NEUTRAL": "— NEUTRAL"}.get(signal, signal)


def print_report(ticker: str, results: pd.DataFrame):
    period_label = f"{OPENING_BARS * 5}-min"
    print(f"\n{'='*76}")
    print(f"  {ticker}  |  op_momentum_guide  |  Opening period: {period_label}")
    print(f"{'='*76}")
    print(
        f"  {'Date':<12} {'OR Hi':>7} {'OR Lo':>7} {'Mid':>7} {'Bot10%':>7} "
        f"{'Close':>7} {'%Rng':>6} {'MA20':>8} {'MA200':>8}  Signal"
    )
    print(f"  {'-'*74}")

    for _, row in results.iterrows():
        ma20_str = f"{row['ma20']:>8.2f}" if row["ma20"] else "     n/a"
        ma200_str = f"{row['ma200']:>8.2f}" if row["ma200"] else "     n/a"
        print(
            f"  {str(row['date']):<12} "
            f"{row['or_high']:>7.2f} "
            f"{row['or_low']:>7.2f} "
            f"{row['midpoint']:>7.2f} "
            f"{row['bottom_10_threshold']:>7.2f} "
            f"{row['close']:>7.2f} "
            f"{row['price_pct_in_range']:>5.1f}% "
            f"{ma20_str} "
            f"{ma200_str}  "
            f"{signal_badge(row['signal'])}"
        )


def print_summary(all_results: dict):
    tickers = list(all_results.keys())
    latest_date = max(
        all_results[t]["date"].max() for t in tickers
        if not all_results[t].empty
    )

    print(f"\n{'='*50}")
    print(f"  op_momentum_guide — Summary for {latest_date}")
    print(f"{'='*50}")
    for ticker in tickers:
        df = all_results[ticker]
        today = df[df["date"] == latest_date]
        if today.empty:
            print(f"  {ticker:<6}  no data")
            continue
        row = today.iloc[0]
        print(f"  {ticker:<6}  {signal_badge(row['signal']):<14}  "
              f"close=${row['close']:.2f}  "
              f"{row['price_pct_in_range']:.1f}% of range  "
              f"MA20=${row['ma20']:.2f}  MA200=${row['ma200']:.2f}")
    print(f"{'='*50}")


if __name__ == "__main__":
    all_results = {}

    for ticker in TICKERS:
        print(f"Fetching {ticker} ({PERIOD} of {INTERVAL} bars)...")
        df = yf.download(ticker, period=PERIOD, interval=INTERVAL, auto_adjust=True, progress=False)
        df.columns = df.columns.droplevel(1)

        results = compute_op_momentum_guide(df)
        all_results[ticker] = results
        print_report(ticker, results.tail(5))  # show last 5 trading days

    print_summary(all_results)
