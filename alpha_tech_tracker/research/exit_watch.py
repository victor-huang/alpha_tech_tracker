"""Daily trailing-stop check for the recommended paper lists.

Reads the latest paper_lists CSV and, for each held name on a list with a trailing-stop exit, replays the backtest's
stop from its entry checkpoint: the peak close since entry, reset when a name that was stopped out is bought back at a
later checkpoint. A name whose close is that far under its peak should be sold now and stays out until the next
checkpoint's list. Bars are fetched fresh (not from the month cache) so an after-close run sees today's close.

Usage (repo root; Alpaca keys set; run after the close):
    PYTHONPATH=. python -m alpha_tech_tracker.research.exit_watch
"""
import argparse
import glob
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

from alpha_tech_tracker.research.ranking_exits import EXIT_RULES
from alpha_tech_tracker.research.selection_filters import PANEL_DIR
from alpha_tech_tracker.research.top_performers import AlpacaData, pivot_bars
from alpha_tech_tracker.research.uptrend_formation import checkpoint_days

CHECKPOINT_STEP = 10
CALENDAR_SYMBOL = "SPY"


def trail_status(close: pd.Series, entry: pd.Timestamp, checkpoints: List[pd.Timestamp],
                 trail: float) -> Dict[str, object]:
    """The backtest's trailing stop replayed on one name's daily closes from its entry checkpoint."""
    c = close[close.index >= entry].dropna()
    rebuy_days = set(checkpoints)
    peak = c.iloc[0]
    stopped_on: Optional[pd.Timestamp] = None
    for day, price in c.iloc[1:].items():
        if stopped_on is not None:
            if day in rebuy_days:
                peak, stopped_on = price, None
            continue
        peak = max(peak, price)
        if price / peak - 1 <= -trail:
            stopped_on = day
    last = c.iloc[-1]
    return {"close": last, "peak": peak, "from_peak": last / peak - 1, "stop_price": peak * (1 - trail),
            "stopped_on": stopped_on.date() if stopped_on is not None else None}


def latest_lists(out_dir: str) -> pd.DataFrame:
    paths = sorted(glob.glob(os.path.join(out_dir, "paper_lists", "*.csv")))
    if not paths:
        raise FileNotFoundError("no paper_lists output; run alpha_tech_tracker.research.paper_lists first")
    return pd.read_csv(paths[-1], parse_dates=["checkpoint", "entry"])


def watch_table(lists: pd.DataFrame, close: pd.DataFrame, checkpoints: List[pd.Timestamp]) -> pd.DataFrame:
    held = lists[(lists["status"] != "dropped") & lists["exit_rule"].map(lambda r: EXIT_RULES[r].trail is not None)]
    rows = []
    for row in held.itertuples():
        trail = EXIT_RULES[row.exit_rule].trail
        status = trail_status(close[row.symbol], row.entry, checkpoints, trail)
        rows.append({"list": row.list, "symbol": row.symbol, "entry": row.entry.date(), "trail": trail, **status})
    out = pd.DataFrame(rows)
    out["action"] = out["stopped_on"].map(lambda d: "SELL (stopped)" if d is not None else "hold")
    return out


def run(args: argparse.Namespace) -> None:
    lists = latest_lists(args.out_dir)
    symbols = sorted(set(lists.loc[lists["status"] != "dropped", "symbol"])) + [CALENDAR_SYMBOL]
    start = lists["entry"].min().date() - timedelta(days=7)
    close, _ = pivot_bars(AlpacaData().daily_bars(symbols, start, args.today))
    days = close[CALENDAR_SYMBOL].dropna().index
    checkpoints = [d for year in sorted(set(days.year)) for d in checkpoint_days(days, year, CHECKPOINT_STEP)]

    table = watch_table(lists, close, checkpoints)
    print(f"list checkpoint {lists['checkpoint'].iloc[0].date()}, closes through {days[-1].date()}")
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        for name, g in table.groupby("list", sort=False):
            print(f"\n{name} (trailing stop {g['trail'].iloc[0]:.0%})")
            print(g.drop(columns=["list", "trail"]).sort_values("from_peak").round(3).to_string(index=False))
    sells = table[table["action"] != "hold"]
    print(f"\n{len(sells)} to sell: {', '.join(sells['symbol']) or 'none'}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", default=PANEL_DIR)
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
