"""
Rank Russell 2000 candidate tickers by average daily dollar volume for 2026 YTD.
Outputs top-N sorted by avg daily dollar volume using Alpaca daily bars.
"""

import os
import sys
from datetime import date

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")
from alpha_tech_tracker.op_momentum_strategy.config import _load_config

_load_config()

# Broad Russell 2000 candidate pool — high-activity small/mid-cap names
# Curated from R2000 components known for high intraday volume and momentum
RUSSELL_2000_CANDIDATES = [
    # AI / Robotics / Autonomous
    "IONQ", "SOUN", "ACHR", "JOBY", "RKLB", "OKLO", "LUNR", "SERV",
    # Crypto / Mining
    "MARA", "RIOT", "CLSK", "CIFR", "HUT", "BTBT",
    # Fintech / Lending
    "UPST", "AFRM", "DAVE", "OPEN",
    # Energy / EV
    "PLUG", "ENVX", "WOLF", "BLNK", "CHPT",
    # Consumer / Retail
    "HIMS", "CAVA", "DUOL", "RKT",
    # Semi / Hardware
    "SMCI", "ACMR", "AMBA",
    # Biotech / Health
    "EXAS", "PRVA", "ARWR", "FATE",
    # Other high-beta R2000 names
    "RDDT", "PONY", "LABD", "LABU", "SPWR", "VNET",
    "BITI", "SMAR", "DKNG", "PENN", "RXRX", "MTTR",
    "PSNY", "OPEN", "CLOV", "MVST", "KORE", "SOFI",
    "NKLA", "WKHS", "GOEV", "RIDE", "MVIS",
    "SPCE", "ASTR", "MNTS", "VORB",
    # Additional momentum names that may be in R2000
    "ASTS", "RCAT", "UAVS", "PTGX", "TPVG",
    "HOOD", "NU", "STEP", "LNTH", "XPOF",
    "PGNY", "QLYS", "YEXT", "PRCT", "SEMR",
    "TASK", "BRZE", "ALTR", "JAMF", "NCNO",
]

TOP_N = 20
START = date(2026, 1, 2)
END = date(2026, 6, 3)


def main():
    client = StockHistoricalDataClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
    )

    tickers = sorted(set(RUSSELL_2000_CANDIDATES))
    print(f"Fetching daily bars for {len(tickers)} tickers ({START} to {END})...")

    req = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame.Day,
        start=START,
        end=END,
        feed=DataFeed.SIP,
    )
    bars_df = client.get_stock_bars(req).df

    if bars_df.empty:
        print("No data returned.")
        return

    bars_df = bars_df.reset_index()
    bars_df["dollar_volume"] = bars_df["close"] * bars_df["volume"]

    summary = (
        bars_df.groupby("symbol")
        .agg(
            avg_dollar_volume=("dollar_volume", "mean"),
            avg_volume=("volume", "mean"),
            avg_close=("close", "mean"),
            trading_days=("close", "count"),
        )
        .sort_values("avg_dollar_volume", ascending=False)
    )

    summary = summary[summary["trading_days"] >= 50]

    print(f"\nTop {TOP_N} Russell 2000 candidates by avg daily dollar volume (2026 YTD)\n")
    print(f"{'Rank':<5} {'Ticker':<8} {'Avg Daily $Vol':>16} {'Avg Volume':>14} {'Avg Close':>12} {'Days':>6}")
    print("-" * 65)
    for i, (symbol, row) in enumerate(summary.head(TOP_N).iterrows(), 1):
        dvol = row["avg_dollar_volume"]
        if dvol >= 1e9:
            dvol_str = f"${dvol/1e9:.1f}B"
        elif dvol >= 1e6:
            dvol_str = f"${dvol/1e6:.1f}M"
        else:
            dvol_str = f"${dvol/1e3:.0f}K"
        print(
            f"{i:<5} {symbol:<8} {dvol_str:>16} {row['avg_volume']:>14,.0f}"
            f" {row['avg_close']:>12,.0f} {int(row['trading_days']):>6}"
        )

    top_tickers = list(summary.head(TOP_N).index)
    print(f"\nTop {TOP_N} tickers (space-separated):")
    print(" ".join(top_tickers))


if __name__ == "__main__":
    main()
