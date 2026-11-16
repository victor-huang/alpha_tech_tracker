"""Paper-tracking lists at the latest biweekly checkpoint: the recommended Large and Small rules
(recommended_rules.RECOMMENDED), the previous Large rule for comparison, and the concentrated Large top 3 ranked by
the 180-day score alone (concentration.py), plus the short-hedge basket (short_hedge.py): the 15 weakest liquid Large
names, status "short" while QQQ closes below both its 50- and 200-day averages (short 50% of the Large book until the
next checkpoint), otherwise "off". Also the Mid reclaim + growth list (mid_reclaim.py): fresh 200-day reclaims with 25%+
sales growth, never-held names bought first, 15% trailing stop, sold when they leave the list. Also the doubler switch
(docs/qqq_gap_before_2018.md on the historical-data branch): hold the Large book while at least 1.5% of the Large tier is
up 100%+ over 250 days, otherwise hold the start-of-year top 7 NASDAQ companies (equal weight) or QQQ. The market
cash rule (cash_rule.py) is printed as the default signal for holding cash instead; exit_watch checks it daily.

Each list is the backtest book (its top N, no buffer, no market gate) at the latest checkpoint, with names new since the
previous checkpoint, names dropped, and the checkpoint each held name was bought at (`entry`, used by exit_watch for
the trailing stop). Checkpoints are every 10 trading days from the first trading day of the year, so a list only
changes on a checkpoint day; `--refresh` rebuilds the year's checkpoint panel first.

Usage (repo root; Alpaca keys set, and SEC_USER_AGENT when the 30-day SEC refresh is due):
    PYTHONPATH=. python -m alpha_tech_tracker.research.paper_lists
    PYTHONPATH=. python -m alpha_tech_tracker.research.paper_lists --refresh
"""
import argparse
import os
from datetime import date
from typing import Dict, List, Tuple

import pandas as pd

from alpha_tech_tracker.research import cash_rule, uptrend_formation
from alpha_tech_tracker.research.concentration import LISTS as CONCENTRATED
from alpha_tech_tracker.research.mid_reclaim import (
    PAPER_SETTING,
    STOP,
    TIER,
    attach_features,
    reclaim_features,
    reclaim_list,
    run_reclaim_book,
)
from alpha_tech_tracker.research.recommended_rules import RECOMMENDED, prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import (
    PANEL_DIR,
    VARIANTS,
    Variant,
    period_returns,
    prepare_inputs,
    rank_variant,
    run_portfolio,
)
from alpha_tech_tracker.research.short_hedge import HEDGE_FRACTION, downtrend, weakest
from alpha_tech_tracker.research.top_performers import DEFAULT_CACHE_DIR
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX
from alpha_tech_tracker.research.winner_capture import LISTS

TOP = 15
DETAIL_COLUMNS = ["close", "ret_60d", "ret_120d", "ret_180d", "off_52w_high", "gap_10d", "high_breakout_10d"]
HEDGE_LIST = "large_short_hedge"
MID_LIST = "mid_reclaim_growth"
MID_EXIT_RULE = "trail15"
SWITCH_LIST = "large_switch_top7"
DOUBLER_RETURN = 1.0
DOUBLER_SHARE_MIN = 0.015
# The 7 largest US NASDAQ companies on the last close before each year; refresh every January
TOP7_BY_YEAR = {2026: ["NVDA", "AAPL", "GOOGL", "MSFT", "AMZN", "META", "AVGO"]}


def paper_rules() -> Dict[str, Tuple[str, Variant, str, int]]:
    """List name -> (tier, variant, exit rule name, names held)."""
    top3 = CONCENTRATED["large_score_only"]
    return {
        "large_recommended": ("Large", RECOMMENDED["Large"][1], RECOMMENDED["Large"][2], TOP),
        "large_previous": ("Large", VARIANTS[LISTS["Large"]], "none", TOP),
        "large_top3": ("Large", top3.variant, top3.exit_rule, 3),
        "small_recommended": ("Small", RECOMMENDED["Small"][1], RECOMMENDED["Small"][2], TOP),
    }


def entry_checkpoints(book: pd.DataFrame) -> Dict[str, pd.Timestamp]:
    """For each name held at the book's last checkpoint, the first checkpoint of its current unbroken holding."""
    held_sets = [set(h) for h in book["held"]]
    entries = {}
    for symbol in held_sets[-1]:
        i = len(held_sets) - 1
        while i > 0 and symbol in held_sets[i - 1]:
            i -= 1
        entries[symbol] = book.index[i]
    return entries


def latest_list(book: pd.DataFrame, ranked: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Names held at the book's last checkpoint with their rank, entry checkpoint and details, plus names held at the
    previous checkpoint that were dropped (status "dropped")."""
    last = book.index[-1]
    held = book["held"].iloc[-1]
    before = book["held"].iloc[-2] if len(book) > 1 else []
    at = panel[panel["checkpoint"] == last].set_index("symbol")
    rank_of = ranked[ranked["checkpoint"] == last].set_index("symbol")["rank"]
    entries = entry_checkpoints(book)
    rows = [{"symbol": s, "status": "held" if s in before else "new"} for s in held]
    rows += [{"symbol": s, "status": "dropped"} for s in before if s not in held]
    out = pd.DataFrame(rows, columns=["symbol", "status"])
    out.insert(0, "checkpoint", last.date())
    out["rank"] = out["symbol"].map(rank_of)
    out["entry"] = out["symbol"].map(lambda s: entries[s].date() if s in entries else None)
    details = at.reindex(out["symbol"], columns=DETAIL_COLUMNS).reset_index(drop=True)
    return pd.concat([out, details], axis=1)


def hedge_list(panel: pd.DataFrame, index_close: pd.Series, checkpoints: List[pd.Timestamp]) -> pd.DataFrame:
    """The short-hedge basket at the last checkpoint (short_hedge.weakest), status "short" while QQQ closes below
    both its 50- and 200-day averages, otherwise "off"."""
    last = checkpoints[-1]
    on = downtrend(index_close, checkpoints)
    basket = weakest(panel)
    basket = basket[basket["checkpoint"] == last]
    out = pd.DataFrame({"checkpoint": last.date(), "symbol": basket["symbol"].values,
                        "status": "short" if on[last] else "off", "rank": basket["rank"].values, "entry": None})
    at = panel[panel["checkpoint"] == last].set_index("symbol")
    details = at.reindex(out["symbol"], columns=DETAIL_COLUMNS).reset_index(drop=True)
    return pd.concat([out, details], axis=1)


def doubler_share(panel: pd.DataFrame, checkpoint: pd.Timestamp) -> Tuple[float, int, int]:
    """Share of the Large tier up DOUBLER_RETURN or more over 250 days at `checkpoint`, with the count and tier size."""
    tier = panel[(panel["checkpoint"] == checkpoint) & (panel["tier"] == "Large")]["ret_250d"].dropna()
    count = int((tier >= DOUBLER_RETURN).sum())
    return (count / len(tier) if len(tier) else 0.0), count, len(tier)


def switch_list(panel: pd.DataFrame, checkpoint: pd.Timestamp) -> pd.DataFrame:
    """The doubler switch's off-side basket: the year's top 7, status "hold" when the doubler share is below
    DOUBLER_SHARE_MIN (hold them instead of the Large book), "off" when the Large book is on, "missing" when the
    year's top 7 is not set."""
    share, _, _ = doubler_share(panel, checkpoint)
    members = TOP7_BY_YEAR.get(checkpoint.year, [])
    status = "missing" if not members else ("off" if share >= DOUBLER_SHARE_MIN else "hold")
    out = pd.DataFrame({"checkpoint": checkpoint.date(), "symbol": members, "status": status,
                        "rank": range(1, len(members) + 1), "entry": None})
    at = panel[panel["checkpoint"] == checkpoint].drop_duplicates("symbol").set_index("symbol")
    details = at.reindex(out["symbol"], columns=DETAIL_COLUMNS).reset_index(drop=True)
    return pd.concat([out, details], axis=1)


def ranked_from_lists(lists: Dict[pd.Timestamp, List[str]]) -> pd.DataFrame:
    """Checkpoint, symbol and rank (1 = first in the list's order) for every listed name."""
    rows = [{"checkpoint": cp, "symbol": s, "rank": i + 1} for cp, names in lists.items() for i, s in enumerate(names)]
    return pd.DataFrame(rows, columns=["checkpoint", "symbol", "rank"])


def mid_list(lists: Dict[pd.Timestamp, List[str]], close: pd.DataFrame, checkpoints: List[pd.Timestamp],
             panel: pd.DataFrame) -> pd.DataFrame:
    """The Mid reclaim + growth book at the last checkpoint, replayed day by day with its trailing stop so the
    never-held-first order sees every earlier purchase; rank is the volume-surge order on the list."""
    book = run_reclaim_book(lists, close, checkpoints, PAPER_SETTING.ranking, stop=STOP, cost=0.0)
    return latest_list(book, ranked_from_lists(lists), panel)


def mid_inputs(inputs) -> Tuple[Dict[pd.Timestamp, List[str]], pd.DataFrame]:
    symbols = sorted(set(inputs.panel.loc[inputs.panel["tier"] == TIER, "symbol"]) & set(inputs.close.columns))
    close = inputs.close[symbols]
    features = reclaim_features(close, inputs.dollar_volume[symbols])
    return reclaim_list(attach_features(inputs.panel, features), PAPER_SETTING), close


def run(args: argparse.Namespace) -> None:
    if args.refresh:
        uptrend_formation.main(["--year", str(args.today.year), "--today", args.today.isoformat()])
    args.years = [args.today.year - 1, args.today.year]
    inputs = prepare_inputs(args)
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    returns = period_returns(inputs.close, inputs.checkpoints)

    out_dir = os.path.join(args.out_dir, "paper_lists")
    os.makedirs(out_dir, exist_ok=True)
    lists = []
    for name, (tier, variant, exit_rule, n) in paper_rules().items():
        ranked = rank_variant(panel, variant, TOP)
        ranked = ranked[ranked["tier"] == tier]
        book = run_portfolio(ranked, returns, inputs.regime, n, n, False, 0.0, variant.take_all)
        lists.append(latest_list(book, ranked, panel).assign(list=name, exit_rule=exit_rule))
    mid_lists, mid_close = mid_inputs(inputs)
    lists.append(mid_list(mid_lists, mid_close, list(inputs.checkpoints), panel)
                 .assign(list=MID_LIST, exit_rule=MID_EXIT_RULE))
    hedge = hedge_list(panel, inputs.close[REGIME_INDEX], list(inputs.checkpoints))
    lists.append(hedge.assign(list=HEDGE_LIST, exit_rule="none"))
    last = inputs.checkpoints[-1]
    lists.append(switch_list(panel, last).assign(list=SWITCH_LIST, exit_rule="none"))
    table = pd.concat(lists, ignore_index=True)
    checkpoint = table["checkpoint"].iloc[0]
    path = os.path.join(out_dir, f"{checkpoint}.csv")
    table.round(4).to_csv(path, index=False)

    qqq = inputs.close[cash_rule.INDEX].dropna()
    qqq_volume = inputs.dollar_volume[cash_rule.INDEX].reindex(qqq.index) / qqq
    print(cash_rule.status_line(cash_rule.cash_rule(qqq, qqq_volume)))
    regime = "above" if inputs.regime.iloc[-1] else "below"
    hedge_state = hedge["status"].iloc[0] if len(hedge) else "off"
    print(f"checkpoint {checkpoint} (QQQ {regime} its 200-day average; short hedge {hedge_state}, "
          f"{HEDGE_FRACTION:.0%} of the Large book when on)")
    share, count, size = doubler_share(panel, last)
    side = "Large book" if share >= DOUBLER_SHARE_MIN else "top 7 / QQQ"
    print(f"doubler switch: {count} of {size} Large names up {DOUBLER_RETURN:.0%}+ over 250 days = {share:.1%} "
          f"(threshold {DOUBLER_SHARE_MIN:.1%}) -> hold the {side}")
    if last.year not in TOP7_BY_YEAR:
        print(f"WARNING: TOP7_BY_YEAR has no {last.year} list; set it to the year's 7 largest US NASDAQ companies")
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        for name, g in table.groupby("list", sort=False):
            print(f"\n{name} (exit: {g['exit_rule'].iloc[0]})")
            print(g.drop(columns=["checkpoint", "list", "exit_rule"]).round(3).to_string(index=False))
    print(f"\nwrote {path}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh", action="store_true", help="rebuild this year's checkpoint panel first")
    p.add_argument("--panel-dir", default=PANEL_DIR)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    p.add_argument("--out-dir", default=PANEL_DIR)
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
