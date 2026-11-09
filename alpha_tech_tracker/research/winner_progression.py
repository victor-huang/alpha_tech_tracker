"""Checkpoint-by-checkpoint view of one year's top-10 winners against the recommended top-15 lists.

For every winner and checkpoint: year-to-date gain, share of the year's log gain already made, the list rank and
why the stock was not held (trend filter leg that failed, exclusion factor, or ranked below 15), plus the feature
values behind the ranking. A comparison table sets the winners' features against the stocks the list did hold at
the same checkpoints.

An episodes table lists every stretch a winner was held: entry checkpoint and YTD gain, exit checkpoint, why it
left (the first failing rule at the next checkpoint) and the gap before it came back.

Rules: "current" (the recommended lists), "mom120" (raw 120-day return + clean for every tier), "breakout" (current
lists with fresh gap / 52-week-high breakouts admitted and ranked first) or "breakout_hold" (Large breakouts keep
priority for 60 days while above the 50-day average) or "breakout+hold_ma_rising" (breakouts plus holding a name while
its 8/20/50-day averages all rise), "prefer_ma_rising" / "require_ma_rising" (rising 8/20/50-day averages move a
stock to the front of the top 30, or are required to be eligible), or "base_ok+breakout" (base-building rebounds
under the 200-day average are eligible too, and fresh breakouts rank first). The breakout5 rules give at most 5
slots to breakouts, strongest first (event-day return x volume ratio); breakout5_hold keeps them for 60 days while
above the 50-day average.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.winner_progression --years 2026 --rule mom120
"""
import argparse
import os
from typing import List

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.selection_filters import VARIANTS, parse_args, prepare_inputs, rank_variant
from alpha_tech_tracker.research.uptrend_formation import DEFAULT_WINNERS_CSV
from alpha_tech_tracker.research.winner_capture import LISTS, year_bounds

RULES = {"current": LISTS, "mom120": {tier: "trend+mom120+clean" for tier in LISTS},
         "breakout": {"Large": "trend+riskadj120+clean+breakout", "Mid": LISTS["Mid"],
                      "Small": "trend+composite+no_dilution+prefer_gross_profit+breakout"},
         "breakout_hold": dict(LISTS, Large="trend+riskadj120+clean+breakout_hold"),
         "breakout+hold_ma_rising": dict(LISTS, Large="trend+riskadj120+clean+breakout+hold_ma_rising",
                                         Small="trend+composite+no_dilution+prefer_gross_profit+hold_ma_rising"),
         "prefer_ma_rising": dict(LISTS, Large="trend+riskadj120+clean+prefer_ma_rising",
                                  Small="trend+composite+no_dilution+prefer_gross_profit+prefer_ma_rising"),
         "require_ma_rising": dict(LISTS, Large="trend+riskadj120+clean+require_ma_rising",
                                   Small="trend+composite+no_dilution+prefer_gross_profit+require_ma_rising"),
         "breakout5": {"Large": "trend+riskadj120+clean+breakout5", "Mid": LISTS["Mid"],
                       "Small": "trend+composite+no_dilution+prefer_gross_profit+breakout5"},
         "breakout5_hold": {"Large": "trend+riskadj120+clean+breakout5_hold", "Mid": LISTS["Mid"],
                            "Small": "trend+composite+no_dilution+prefer_gross_profit+breakout5_hold"},
         "mom120+breakout5_hold": {"Large": "trend+mom120+clean+breakout5_hold", "Mid": LISTS["Mid"],
                                   "Small": "trend+mom120+clean+breakout5_hold"},
         "gap3_high2": dict(LISTS, Large="trend+riskadj120+clean+gap3_high2"),
         "gap3_high2_hold": dict(LISTS, Large="trend+riskadj120+clean+gap3_high2_hold"),
         "mom120+gap3_high2_hold": dict(LISTS, Large="trend+mom120+clean+gap3_high2_hold"),
         "base_ok+breakout": dict(LISTS, Large="trend+riskadj120+clean+base_ok+breakout",
                                  Small="trend+composite+no_dilution+prefer_gross_profit+base_ok+breakout")}
TOP = 15
FEATURES = ["ret_20d", "ret_60d", "ret_120d", "vol_60d", "risk_adj_120", "composite", "off_52w_high",
            "up_day_share_20d", "max_1d_gain_20d", "volume_surge", "dollar_volume_20d", "jump_held_60d",
            "jump_faded_60d", "drop_60d", "turnaround", "rev_yoy", "share_change", "cash_burn", "gp_top30",
            "group_top20_120d"]


def block_reason(row: pd.Series, exclude: List[str], require: List[str]) -> str:
    """Why a stock was not in the top 15 at a checkpoint (first failing rule)."""
    if pd.isna(row.get("close")):
        return "not in tier"
    if row.get("rank", np.nan) <= TOP:
        return "held"
    if not row["close"] > row["ma50"]:
        return "trend: below ma50"
    if not row["ma50"] > row["ma200"]:
        return "trend: ma50 below ma200"
    if not bool(row["ma200_rising"]):
        return "trend: ma200 falling"
    for factor in exclude:
        if row.get(factor) == 1:
            return f"excluded: {factor}"
    for factor in require:
        if row.get(factor) != 1:
            return f"missing: {factor}"
    if pd.isna(row.get("rank")):
        return "no score"
    return "held" if row["rank"] <= TOP else "ranked below 15"


def cell(row: pd.Series) -> str:
    """Compact grid code: H held, rank number when eligible, T trend fail, X excluded, . not in tier."""
    reason = row["reason"]
    if reason == "held":
        return f"H{int(row['rank'])}"
    if reason == "ranked below 15":
        return str(int(row["rank"]))
    if reason.startswith("trend"):
        return "T"
    if reason.startswith(("excluded", "missing")):
        return "X"
    return "."


def progression(panel: pd.DataFrame, ranked: pd.DataFrame, winners: pd.DataFrame, close: pd.DataFrame,
                variant_exclude: List[str], variant_require: List[str]) -> pd.DataFrame:
    rows = []
    checkpoints = sorted(panel["checkpoint"].unique())
    by_key = panel.set_index(["checkpoint", "symbol"])
    rank_of = ranked.set_index(["checkpoint", "symbol"])["rank"]
    for w in winners.itertuples():
        start, end = year_bounds(close[w.symbol], w.year) if w.symbol in close else (np.nan, np.nan)
        year_log = np.log(end / start) if start > 0 and end > 0 else np.nan
        for cp in checkpoints:
            key = (cp, w.symbol)
            in_tier = key in by_key.index and by_key.loc[key, "tier"] == w.tier
            row = by_key.loc[key].to_dict() if in_tier else {}
            row.update({"checkpoint": cp, "symbol": w.symbol, "tier": w.tier, "year_return_pct": w.return_pct,
                        "rank": rank_of.get(key, np.nan) if in_tier else np.nan})
            price = close.loc[cp, w.symbol] if w.symbol in close else np.nan
            row["ytd"] = price / start - 1 if start > 0 else np.nan
            row["gain_done"] = np.log(price / start) / year_log if year_log and year_log > 0 else np.nan
            row["reason"] = block_reason(pd.Series(row), variant_exclude, variant_require) if in_tier \
                else "not in tier"
            rows.append(row)
    out = pd.DataFrame(rows)
    out["cell"] = out.apply(cell, axis=1)
    return out


def feature_comparison(panel: pd.DataFrame, ranked: pd.DataFrame, prog: pd.DataFrame) -> pd.DataFrame:
    """Median features: winners while not held during their run (before 75% of the year's gain), winners while
    held, and the list's own top-15 picks over the same checkpoints."""
    running = prog[(prog["gain_done"] < 0.75) & (prog["reason"] != "not in tier")]
    picks = ranked[ranked["rank"] <= TOP].merge(panel, on=["checkpoint", "tier", "symbol"])
    picks = picks[picks["checkpoint"].isin(running["checkpoint"]) & picks["tier"].isin(running["tier"])]
    groups = {"winner_not_held": running[running["reason"] != "held"], "winner_held": running[running["reason"] == "held"],
              "top15_picks": picks}
    rows = []
    for tier in sorted(running["tier"].unique()):
        for name, g in groups.items():
            g = g[g["tier"] == tier]
            rows.append({"tier": tier, "group": name, "rows": len(g),
                         **{f: pd.to_numeric(g[f], errors="coerce").median() for f in FEATURES if f in g}})
    return pd.DataFrame(rows)


def episodes(prog: pd.DataFrame) -> pd.DataFrame:
    """One row per holding stretch of each winner: entry / exit checkpoints, YTD gain at entry and exit, the gain
    while held, why it left, its rank at the exit checkpoint and checkpoints until it was held again."""
    rows = []
    for symbol, g in prog.sort_values("checkpoint").groupby("symbol", sort=False):
        g = g.reset_index(drop=True)
        held = (g["reason"] == "held").values
        starts = [i for i in range(len(g)) if held[i] and (i == 0 or not held[i - 1])]
        for n, i in enumerate(starts):
            j = i
            while j + 1 < len(g) and held[j + 1]:
                j += 1
            after = g.iloc[j + 1] if j + 1 < len(g) else None
            back = next((k for k in starts if k > j), None)
            entry_ytd, exit_ytd = g.loc[i, "ytd"], (after["ytd"] if after is not None else g.loc[j, "ytd"])
            rows.append({
                "tier": g.loc[i, "tier"], "symbol": symbol, "year_return_pct": g.loc[i, "year_return_pct"],
                "episode": n + 1, "entry": g.loc[i, "checkpoint"], "entry_rank": g.loc[i, "rank"],
                "entry_ytd": entry_ytd, "exit": after["checkpoint"] if after is not None else pd.NaT,
                "checkpoints_held": j - i + 1, "exit_ytd": exit_ytd,
                "gain_while_held": (1 + exit_ytd) / (1 + entry_ytd) - 1,
                "exit_reason": after["reason"] if after is not None else "still held",
                "exit_rank": after["rank"] if after is not None else np.nan,
                "checkpoints_until_back": (back - j - 1) if back is not None else np.nan,
            })
    return pd.DataFrame(rows)


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel, close = inputs.panel, inputs.close
    year = max(args.years)
    winners = pd.read_csv(DEFAULT_WINNERS_CSV)
    winners = winners[winners["year"] == year]
    lists = RULES[args.rule]
    out_dir = os.path.join(args.out_dir, "winner_progression", str(year), args.rule)
    os.makedirs(out_dir, exist_ok=True)
    parts, grids = [], []
    for tier, name in lists.items():
        variant = VARIANTS[name]
        ranked = rank_variant(panel, variant, TOP)
        prog = progression(panel, ranked[ranked["tier"] == tier], winners[winners["tier"] == tier], close,
                           list(variant.exclude), list(variant.require)).assign(list=name)
        parts.append((prog, ranked))
        grid = prog.pivot(index="symbol", columns="checkpoint", values="cell")
        grid.columns = [c.strftime("%m-%d") for c in grid.columns]
        ytd = prog.pivot(index="symbol", columns="checkpoint", values="ytd")
        grid["year_pct"] = prog.groupby("symbol")["year_return_pct"].first()
        grid["first_held"] = prog[prog["reason"] == "held"].groupby("symbol")["checkpoint"].min().dt.strftime(
            "%m-%d")
        grid["ytd_at_first_held"] = [ytd.loc[s, pd.Timestamp(f"{year}-{d}")] if isinstance(d, str) else np.nan
                                     for s, d in zip(grid.index, grid["first_held"])]
        grids.append(grid.assign(tier=tier).sort_values("year_pct", ascending=False))
    prog_all = pd.concat([p for p, _ in parts], ignore_index=True)
    keep = ["tier", "list", "symbol", "checkpoint", "year_return_pct", "ytd", "gain_done", "rank", "reason", "cell",
            "close", "ma50", "ma200", "ma200_rising"] + [f for f in FEATURES if f in prog_all]
    prog_all[keep].to_csv(os.path.join(out_dir, "progression.csv"), index=False)
    episodes(prog_all).to_csv(os.path.join(out_dir, "episodes.csv"), index=False)
    pd.concat(grids).to_csv(os.path.join(out_dir, "grid.csv"))
    comparison = pd.concat([feature_comparison(panel, r, p) for p, r in parts], ignore_index=True)
    comparison.round(4).to_csv(os.path.join(out_dir, "feature_comparison.csv"), index=False)
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--rule", choices=sorted(RULES), default="current")
    known, rest = pre.parse_known_args(argv)
    args = parse_args(rest)
    args.rule = known.rule
    run(args)


if __name__ == "__main__":
    main()
