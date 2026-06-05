"""
Build a 20-ticker basket from 2024 dollar-volume rankings:
  - FANG fixed: META AMZN NFLX GOOGL  (4)
  - Top-6 QQQ by 2024 avg daily $vol, excluding FANG  (6)  → 10 total
  - Top-10 Russell 2000 by 2024 avg daily $vol, non-crypto  (10) → 20 total
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

START = date(2024, 1, 2)
END = date(2024, 12, 31)
MIN_DAYS = 200

FANG = ["META", "AMZN", "NFLX", "GOOGL"]

QQQ_CANDIDATES = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMD", "PLTR", "AVGO", "QCOM",
    "MU", "INTC", "MRVL", "ORCL", "AMAT", "LRCX", "KLAC",
    "CRWD", "PANW", "SNPS", "CDNS", "ADSK",
    "APP", "DDOG", "SNOW", "MNDY", "ZS", "OKTA", "TEAM",
    "ABNB", "BKNG", "CPRT", "CTAS", "FAST",
    "ON", "SMCI", "ARM",
]

# Russell 2000 non-crypto candidates
R2000_NONCRYPTO = [
    # AI / Robotics / Space
    "IONQ", "SOUN", "ACHR", "JOBY", "RKLB", "OKLO", "LUNR", "SERV",
    # Fintech / Lending
    "UPST", "AFRM", "DAVE", "HOOD", "SOFI", "RKT",
    # Consumer / Health
    "HIMS", "CAVA", "DUOL", "DKNG", "PENN",
    # Semi / Hardware
    "ACMR", "AMBA", "ENVX", "WOLF",
    # Growth / SaaS
    "RXRX", "BRZE", "ALTR", "JAMF", "NCNO", "QLYS", "YEXT",
    "TASK", "SEMR", "PRCT", "PGNY",
    # Other high-beta R2000
    "SMCI", "RDDT", "NU", "PONY", "ASTS",
    "MTTR", "SPCE", "ASTR", "NKLA",
    "STEP", "LNTH", "XPOF",
]


def fetch_summary(client, tickers, label):
    print(f"  Fetching {len(tickers)} {label} tickers...")
    req = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame.Day,
        start=START,
        end=END,
        feed=DataFeed.SIP,
    )
    df = client.get_stock_bars(req).df
    if df.empty:
        return {}
    df = df.reset_index()
    df["dollar_volume"] = df["close"] * df["volume"]
    summary = (
        df.groupby("symbol")
        .agg(
            avg_dollar_volume=("dollar_volume", "mean"),
            avg_volume=("volume", "mean"),
            avg_close=("close", "mean"),
            trading_days=("close", "count"),
        )
        .sort_values("avg_dollar_volume", ascending=False)
    )
    return summary[summary["trading_days"] >= MIN_DAYS]


def print_table(summary, top_n, label, exclude=None):
    exclude = set(exclude or [])
    rows = [(sym, row) for sym, row in summary.iterrows() if sym not in exclude]
    print(f"\n── {label} (top {top_n}) ─────────────────────────────────────────")
    print(f"{'Rank':<5} {'Ticker':<8} {'Avg Daily $Vol':>16} {'Avg Volume':>14} {'Avg Close':>12}")
    print("-" * 60)
    picked = []
    for i, (sym, row) in enumerate(rows[:top_n], 1):
        dvol = row["avg_dollar_volume"]
        dvol_str = f"${dvol/1e9:.1f}B" if dvol >= 1e9 else f"${dvol/1e6:.1f}M"
        print(f"{i:<5} {sym:<8} {dvol_str:>16} {row['avg_volume']:>14,.0f} {row['avg_close']:>12,.0f}")
        picked.append(sym)
    return picked


def main():
    client = StockHistoricalDataClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
    )

    print(f"\nRanking 2024 tickers by avg daily dollar volume ({START} to {END})\n")

    qqq_summary = fetch_summary(client, QQQ_CANDIDATES, "QQQ non-FANG")
    r2000_summary = fetch_summary(client, R2000_NONCRYPTO, "R2000 non-crypto")

    # FANG is fixed
    print(f"\n── FANG (fixed) ─────────────────────────────────────────────")
    for t in FANG:
        print(f"       {t}")

    # Top-6 QQQ excluding FANG
    qqq_picks = print_table(qqq_summary, 6, "QQQ non-FANG", exclude=FANG)

    # Top-10 R2000 non-crypto (also exclude any that overlap)
    overlap = set(FANG) | set(qqq_picks)
    r2000_picks = print_table(r2000_summary, 10, "R2000 non-crypto", exclude=overlap)

    basket = FANG + qqq_picks + r2000_picks
    print(f"\n{'='*60}")
    print(f"FINAL BASKET (20 tickers) — hot in 2024")
    print(f"{'='*60}")
    print(f"  FANG (4):          {' '.join(FANG)}")
    print(f"  QQQ top-6 (6):     {' '.join(qqq_picks)}")
    print(f"  R2000 top-10 (10): {' '.join(r2000_picks)}")
    print(f"\n  All 20: {' '.join(basket)}")


if __name__ == "__main__":
    main()
