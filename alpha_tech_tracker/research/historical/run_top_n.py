"""Run a top_n_by_year book script (top_n_books.py, large_top3_book.py, hedge_overlay.py) on the historical data.

Usage (from the repo root, after uptrend_formation --data-source historical has written the year's panel):

    python -m alpha_tech_tracker.research.historical.run_top_n <script.py> <script args...>

The scripts call selection_filters.prepare_inputs, which reads Alpaca bars and maps tickers to SEC CIKs by today's
ticker list. This swaps in HistoricalData, the historical bar cache and panels, the CIKs from securities.csv (right
for dead and reused tickers, and no call to sec.gov), SPY/QQQ as the only benchmarks (IWM is not in the data) and a
"today" at the end of the data, so the bar cache does not ask for months after it.
"""
import os
import runpy
import sys
from typing import Dict, List

import pandas as pd

from alpha_tech_tracker.research import selection_filters as sf
from alpha_tech_tracker.research.historical import securities
from alpha_tech_tracker.research.historical.data import HISTORICAL_CACHE_DIR, HistoricalData
from alpha_tech_tracker.research.historical.shares import DEFAULT_DATA_DIR
from alpha_tech_tracker.research.sec_fundamentals import FundamentalsCache

PANEL_DIR = "alpha_tech_tracker/research/top_performers_output/uptrend_formation_historical"
DATA_END = "2020-06-30"
BENCHMARKS = ["SPY", "QQQ"]


def security_ciks(data_dir: str = DEFAULT_DATA_DIR) -> Dict[str, int]:
    table = pd.read_csv(os.path.join(data_dir, "securities.csv"), **securities.TEXT_SAFE).dropna(subset=["cik"])
    return dict(zip(table["security"], table["cik"].astype(int)))


def historical_args(argv: List[str]) -> List[str]:
    return list(argv) + ["--panel-dir", PANEL_DIR, "--cache-dir", HISTORICAL_CACHE_DIR, "--today", DATA_END]


def install(ciks: Dict[str, int]) -> None:
    parse = sf.parse_args
    sf.AlpacaData = HistoricalData
    sf.BENCHMARKS = BENCHMARKS
    sf.FundamentalsCache = lambda root: FundamentalsCache(root, user_agent_for=lambda: "unused",
                                                          ticker_ciks=lambda agent: ciks)
    sf.parse_args = lambda argv=None: parse(historical_args(sys.argv[1:] if argv is None else argv))


def main() -> None:
    install(security_ciks())
    sys.argv = sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
