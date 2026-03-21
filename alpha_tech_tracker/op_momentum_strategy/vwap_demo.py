import pandas as pd
import yfinance as yf
import mplfinance as mpf


TICKERS = ["AAPL", "NVDA", "MSFT"]
INTERVAL = "5m"
PERIOD = "5d"


def vwap_anchored_to_open(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_vol = typical_price * df["Volume"]
    dates = df.index.date
    return tp_vol.groupby(dates).cumsum() / df["Volume"].groupby(dates).cumsum()


def fetch_intraday(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period=PERIOD, interval=INTERVAL, auto_adjust=True, progress=False)
    df.columns = df.columns.droplevel(1)
    df["VWAP"] = vwap_anchored_to_open(df)
    return df


def print_opening_range(ticker: str, df: pd.DataFrame):
    print(f"\n{'='*60}")
    print(f"  {ticker} — First 30 min (6 x 5-min bars) per day")
    print(f"{'='*60}")

    for date, group in df.groupby(df.index.date):
        opening_bars = group.head(6)
        orb_high = opening_bars["High"].max()
        orb_low = opening_bars["Low"].min()
        print(f"\n  Date: {date}  |  ORB High: {orb_high:.2f}  |  ORB Low: {orb_low:.2f}")
        print(f"  {'Time':<22} {'Open':>7} {'High':>7} {'Low':>7} {'Close':>7} {'Volume':>10} {'VWAP':>8}")
        print(f"  {'-'*72}")
        for ts, row in opening_bars.iterrows():
            print(
                f"  {str(ts):<22} "
                f"{row['Open']:>7.2f} "
                f"{row['High']:>7.2f} "
                f"{row['Low']:>7.2f} "
                f"{row['Close']:>7.2f} "
                f"{int(row['Volume']):>10,} "
                f"{row['VWAP']:>8.2f}"
            )


def plot_latest_day(ticker: str, df: pd.DataFrame):
    latest_date = df.index.date[-1]
    day_df = df[df.index.date == latest_date].copy()

    add_vwap = mpf.make_addplot(day_df["VWAP"], color="orange", width=1.5, label="VWAP")

    mpf.plot(
        day_df,
        type="candle",
        volume=True,
        addplot=add_vwap,
        title=f"{ticker} — {latest_date}  |  Candlesticks + VWAP Anchored to Open",
        style="charles",
        figsize=(14, 7),
        savefig=f"{ticker}_vwap_{latest_date}.png",
    )
    print(f"\n  Chart saved: {ticker}_vwap_{latest_date}.png")


if __name__ == "__main__":
    for ticker in TICKERS:
        print(f"\nFetching {ticker}...")
        df = fetch_intraday(ticker)
        print_opening_range(ticker, df)
        plot_latest_day(ticker, df)
