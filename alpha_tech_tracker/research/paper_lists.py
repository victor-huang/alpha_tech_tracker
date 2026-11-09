"""Paper-tracking lists at the latest biweekly checkpoint: the recommended Large and Small rules
(recommended_rules.RECOMMENDED), the previous Large rule for comparison, and the concentrated Large top 3 ranked by
the 180-day score alone (concentration.py).

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
from typing import Dict, Tuple

import pandas as pd

from alpha_tech_tracker.research import uptrend_formation
from alpha_tech_tracker.research.concentration import LISTS as CONCENTRATED
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
from alpha_tech_tracker.research.top_performers import DEFAULT_CACHE_DIR
from alpha_tech_tracker.research.winner_capture import LISTS

TOP = 15
DETAIL_COLUMNS = ["close", "ret_60d", "ret_120d", "ret_180d", "off_52w_high", "gap_10d", "high_breakout_10d"]


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
    table = pd.concat(lists, ignore_index=True)
    checkpoint = table["checkpoint"].iloc[0]
    path = os.path.join(out_dir, f"{checkpoint}.csv")
    table.round(4).to_csv(path, index=False)

    regime = "above" if inputs.regime.iloc[-1] else "below"
    print(f"checkpoint {checkpoint} (QQQ {regime} its 200-day average)")
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
