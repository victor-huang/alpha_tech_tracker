"""Phase 7 of research/docs/historical_data_2005_2019_plan.md: check the historical dataset before trusting it.

Usage (from the repo root):

    python -m alpha_tech_tracker.research.historical.validate overlap
    python -m alpha_tech_tracker.research.historical.validate panels <old 2018 dir> <new 2018 dir>

- overlap: WIKI vs Alpaca daily returns for every symbol in both, 2016-01-04 -> 2018-03-27. A symbol disagrees
  when more than BAD_DAY_SHARE of its days differ by more than RETURN_TOLERANCE. Also spot-checks dead tickers.
- panels: an uptrend_formation year run on Alpaca (stocks listed today) vs the same year on the historical
  dataset: universe by tier, names added and dropped, tier agreement, and the forward test side by side.
"""
import argparse
import os
from typing import Dict

import pandas as pd

from alpha_tech_tracker.research.historical import normalize as nz

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "market_data", "historical")
OVERLAP_START, OVERLAP_END = pd.Timestamp("2016-01-04"), pd.Timestamp("2018-03-27")
RETURN_TOLERANCE = 0.005
BAD_DAY_SHARE = 0.01
SPOT_CHECKS = {"SHLD": "bankrupt 2018-10", "CELG": "acquired 2019-11", "MON": "acquired 2018-06",
               "TWX": "acquired 2018-06", "DELL~2013": "taken private 2013-10"}


def return_agreement(wiki: pd.DataFrame, alpaca: pd.DataFrame, tolerance: float = RETURN_TOLERANCE) -> pd.DataFrame:
    """Per symbol: shared days and the share of them whose daily returns differ by more than tolerance."""
    def returns(rows):
        wide = rows.pivot_table(index="day", columns="symbol", values="close")
        return wide.pct_change(fill_method=None)

    w, a = returns(wiki), returns(alpaca)
    symbols = w.columns.intersection(a.columns)
    days = w.index.intersection(a.index)
    w, a = w.loc[days, symbols], a.loc[days, symbols]
    both = w.notna() & a.notna()
    bad = ((w - a).abs() > tolerance) & both
    out = pd.DataFrame({"days": both.sum(), "bad_days": bad.sum()})
    out["bad_share"] = out["bad_days"] / out["days"].where(out["days"] > 0)
    return out.sort_values("bad_share", ascending=False)


def overlap_report(data_dir: str) -> Dict[str, pd.DataFrame]:
    wiki = nz._real_trades(nz.wiki_rows(os.path.join(data_dir, "raw", "wiki", "WIKI_PRICES.zip"), OVERLAP_END))
    wiki = wiki[wiki["day"] >= OVERLAP_START]
    alpaca = nz._real_trades(nz.alpaca_rows(os.path.join(data_dir, "prices", "alpaca")))
    alpaca = alpaca[(alpaca["day"] >= OVERLAP_START) & (alpaca["day"] <= OVERLAP_END)]
    return {"agreement": return_agreement(wiki, alpaca)}


def spot_checks(data_dir: str) -> pd.DataFrame:
    rows = nz.load_years(os.path.join(data_dir, "daily"), 2003, 2020)
    out = []
    for security, event in SPOT_CHECKS.items():
        s = rows[rows["symbol"] == security].sort_values("day")
        out.append({"security": security, "event": event, "first_day": s["day"].min(), "last_day": s["day"].max(),
                    "last_close": s["close"].iloc[-1] if len(s) else None, "bars": len(s)})
    return pd.DataFrame(out)


def compare_panels(old: pd.DataFrame, new: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    old_tiers = old.drop_duplicates("symbol").set_index("symbol")["tier"]
    new_tiers = new.drop_duplicates("symbol").set_index("symbol")["tier"]
    shared = old_tiers.index.intersection(new_tiers.index)
    universe = pd.DataFrame({"old": old_tiers.value_counts(), "new": new_tiers.value_counts(),
                             "added": new_tiers.drop(shared).value_counts(),
                             "dropped": old_tiers.drop(shared).value_counts()}).fillna(0).astype(int)
    agreement = pd.crosstab(old_tiers[shared].rename("old_tier"), new_tiers[shared].rename("new_tier"))
    return {"universe": universe, "tier_agreement": agreement,
            "added": new_tiers.drop(shared).rename("tier").reset_index(),
            "dropped": old_tiers.drop(shared).rename("tier").reset_index()}


def compare_forward_tests(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    keys = ["rule", "tier"]
    cols = ["flagged_per_checkpoint", "hit_rate", "lift", "vol_matched_lift"]
    return old[keys + cols].merge(new[keys + cols], on=keys, suffixes=("_old", "_new"))


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="check", required=True)
    o = sub.add_parser("overlap")
    o.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    pp = sub.add_parser("panels")
    pp.add_argument("old_dir")
    pp.add_argument("new_dir")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    pd.set_option("display.width", 200)
    if args.check == "overlap":
        agreement = overlap_report(args.data_dir)["agreement"]
        disagree = agreement[agreement["bad_share"] > BAD_DAY_SHARE]
        print(f"{len(agreement)} symbols in both; {len(disagree)} disagree on more than {BAD_DAY_SHARE:.0%} of days")
        print(f"median share of days off by more than {RETURN_TOLERANCE:.1%}: {agreement['bad_share'].median():.4f}")
        print(disagree.head(25).to_string())
        agreement.to_csv(os.path.join(args.data_dir, "overlap_agreement.csv"))
        print(spot_checks(args.data_dir).to_string(index=False))
        return
    old = pd.read_pickle(os.path.join(args.old_dir, "panel.pkl"))
    new = pd.read_pickle(os.path.join(args.new_dir, "panel.pkl"))
    result = compare_panels(old, new)
    print("universe by tier\n", result["universe"].to_string())
    print("\ntier agreement (rows old, columns new)\n", result["tier_agreement"].to_string())
    print("\nadded, first 40:", result["added"].head(40).values.tolist())
    print("\ndropped, first 40:", result["dropped"].head(40).values.tolist())
    fwd = compare_forward_tests(pd.read_csv(os.path.join(args.old_dir, "forward_test.csv")),
                                pd.read_csv(os.path.join(args.new_dir, "forward_test.csv")))
    print("\nforward test\n", fwd.to_string(index=False))


if __name__ == "__main__":
    run(parse_args())
