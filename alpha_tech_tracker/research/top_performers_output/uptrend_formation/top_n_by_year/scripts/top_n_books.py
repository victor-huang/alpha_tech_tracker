"""Top-5 books for 2026 (Large / Mid / Small recommended rules) with a trade log, daily equity and monthly P&L."""
import pickle
import sys
from typing import Callable, Dict, List

import pandas as pd

from alpha_tech_tracker.research.mid_reclaim import (
    FRESH_FIRST,
    PAPER_SETTING,
    TIER as MID_TIER,
    attach_features,
    order_candidates,
    reclaim_features,
    reclaim_list,
)
from alpha_tech_tracker.research.recommended_rules import RECOMMENDED, prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import parse_args, prepare_inputs, rank_variant
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX

N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
YEAR = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
COST = 1e-3
OUT = sys.argv[1]


def simulate(pick: Callable, close: pd.DataFrame, checkpoints: List[pd.Timestamp], stop: float):
    c = close.ffill()
    price = c.values
    col = {s: i for i, s in enumerate(c.columns)}
    starts = list(c.index.get_indexer(checkpoints))
    ends = starts[1:] + [len(c.index) - 1]
    positions: Dict[str, float] = {}
    peaks: Dict[str, float] = {}
    opened: Dict[str, dict] = {}
    held_before: set = set()
    cash, equity, trades = 1.0, {}, []

    def close_trade(s, day, reason):
        t = opened.pop(s)
        t.update(exit=c.index[day], exit_price=price[day, col[s]], reason=reason)
        t["ret"] = t["exit_price"] / t["entry_price"] - 1
        trades.append(t)

    for cp, start, end in zip(checkpoints, starts, ends):
        start_value = cash + sum(positions.values())
        held = pick(cp, list(positions), held_before)
        for s in [s for s in positions if s not in held]:
            close_trade(s, start, "dropped")
        target = {s: 1.0 / len(held) for s in held} if held else {}
        current = {s: v / start_value for s, v in positions.items()}
        turnover = sum(abs(target.get(s, 0.0) - current.get(s, 0.0)) for s in set(target) | set(current))
        value = start_value * (1 - COST * turnover)
        positions = {s: value * w for s, w in target.items()}
        cash = value - sum(positions.values())
        for s in held:
            if s not in opened:
                opened[s] = {"symbol": s, "checkpoint": cp, "entry": cp, "entry_price": price[start, col[s]]}
        peaks = {s: peaks[s] if s in current else price[start, col[s]] for s in held}
        held_before.update(held)
        equity[c.index[start]] = cash + sum(positions.values())
        for day in range(start + 1, end + 1):
            for s in list(positions):
                j = col[s]
                positions[s] *= price[day, j] / price[day - 1, j]
                peaks[s] = max(peaks[s], price[day, j])
                if price[day, j] <= peaks[s] * (1 - stop):
                    cash += positions.pop(s) * (1 - COST)
                    peaks.pop(s)
                    close_trade(s, day, f"stop {stop:.0%}")
            equity[c.index[day]] = cash + sum(positions.values())
    for s in list(opened):
        close_trade(s, len(c.index) - 1, "open")
    return pd.Series(equity), pd.DataFrame(trades)


def ranked_picker(ranked: pd.DataFrame):
    by_cp = {cp: g.sort_values("rank") for cp, g in ranked.groupby("checkpoint")}

    def pick(cp, positions, held_before):
        g = by_cp.get(cp)
        if g is None:
            return []
        rank_of = dict(zip(g["symbol"], g["rank"]))
        held = sorted([s for s in positions if rank_of.get(s, 1e9) <= N], key=rank_of.get)[:N]
        for s in g["symbol"]:
            if len(held) >= N:
                break
            if s not in held:
                held.append(s)
        return held
    return pick


def mid_picker(lists):
    def pick(cp, positions, held_before):
        listed = lists.get(cp, [])
        keep = [s for s in positions if s in listed]
        buys = [s for s in order_candidates(listed, held_before, FRESH_FIRST) if s not in keep][:max(N - len(keep), 0)]
        return keep + buys
    return pick


def monthly(equity: pd.Series) -> pd.Series:
    m = equity.resample("M").last()
    return m.pct_change().fillna(m.iloc[0] / 1.0 - 1)


def main():
    inputs = prepare_inputs(parse_args(["--years", str(YEAR)]))
    end = f"{YEAR}-12-31"
    inputs = inputs._replace(close=inputs.close.loc[:end], dollar_volume=inputs.dollar_volume.loc[:end])
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    checkpoints = list(inputs.checkpoints)
    out = {"checkpoints": checkpoints, "n": N, "year": YEAR}
    for tier, (_, variant, exit_rule) in RECOMMENDED.items():
        ranked = rank_variant(panel, variant, 15)
        ranked = ranked[ranked["tier"] == tier]
        symbols = sorted(set(ranked["symbol"]))
        eq, trades = simulate(ranked_picker(ranked), inputs.close[symbols], checkpoints,
                              float(exit_rule.replace("trail", "")) / 100)
        out[tier] = (eq, trades.assign(tier=tier))
    mid_symbols = sorted(set(inputs.panel.loc[inputs.panel["tier"] == MID_TIER, "symbol"]) & set(inputs.close.columns))
    mclose = inputs.close[mid_symbols]
    lists = reclaim_list(attach_features(inputs.panel, reclaim_features(mclose, inputs.dollar_volume[mid_symbols])),
                         PAPER_SETTING)
    eq, trades = simulate(mid_picker(lists), mclose, checkpoints, 0.15)
    out["Mid"] = (eq, trades.assign(tier="Mid"))
    qqq = inputs.close[REGIME_INDEX]
    out["QQQ"] = qqq[qqq.index >= checkpoints[0]] / qqq[qqq.index >= checkpoints[0]].iloc[0]

    table = pd.DataFrame({t: monthly(out[t][0]) for t in ("Large", "Mid", "Small")})
    table["QQQ"] = monthly(out["QQQ"])
    table.index = table.index.strftime("%Y-%m")
    table.loc[f"{YEAR} total"] = [out[t][0].iloc[-1] - 1 for t in ("Large", "Mid", "Small")] + [out["QQQ"].iloc[-1] - 1]
    out["monthly"] = table
    print((table * 100).round(1).to_string())
    for t in ("Large", "Mid", "Small"):
        tr = out[t][1]
        print(f"{t}: {len(tr)} trades, {tr['symbol'].nunique()} names, win rate {(tr['ret'] > 0).mean():.0%}, "
              f"avg {tr['ret'].mean():.1%}, data through {out[t][0].index[-1].date()}")
    with open(OUT, "wb") as f:
        pickle.dump(out, f)


if __name__ == "__main__":
    main()
