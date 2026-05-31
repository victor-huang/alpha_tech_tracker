"""
Sweep scoring params + EV gate threshold to improve oracle match rate.

Diagnosis (May 2026, top-5 comparison):
  - Layer 1: EV gate blocks oracle #1 on 12/17 days (25.08% P&L unreachable)
    Tickers excluded: MSTR, AMD, SHOP, META, CLS, MU, COIN, PLTR, CRDO
  - Layer 2: Ranking error on 2/17 days — CRWV dominates all score metrics over COIN/MU;
    irreducible without lookahead. Not targeted by this sweep.

Sweep dimensions:
  --min-ev          : 0.0, -0.3, -0.5, -1.0  (how far below zero to allow)
  --score-entry-weight    : 0.40, 0.50, 0.60
  --score-avg-win-weight  : 0.00, 0.20, 0.30  (currently 0.00 — rewards big winners)
  --score-rel-strength-weight : 0.15, 0.25    (cross-sectional momentum)

Win-rate and EV-trend weights held fixed at 0.10 each.

Each combo is evaluated with top=1 (we only trade #1) on May-2026 and Apr+May-2026.
Reports both P&L and oracle match rate (vs oracle_top5.csv reference).

Run from project root:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/sweep_scoring_ev_gate.py
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

MIN_EV_VALUES       = [0.0, -0.3, -0.5, -1.0]
ENTRY_WEIGHTS       = [0.40, 0.50, 0.60]
AVG_WIN_WEIGHTS     = [0.00, 0.20, 0.30]
REL_STR_WEIGHTS     = [0.15, 0.25]

PERIODS = [
    ("May-2026",     date(2026, 5, 1),  date(2026, 5, 29)),
    ("Apr+May-2026", date(2026, 4, 1),  date(2026, 5, 29)),
]

ORACLE_CSV = "logs/oracle_compare/oracle_top5.csv"
INITIAL_CAPITAL = 10_000.0
TICKERS = [
    "APP", "SHOP", "CVNA", "AMD", "META", "EXPE", "JPM", "TSLA",
    "MU", "CRDO", "PLTR", "COIN", "CLS", "MSTR", "CRWV", "MRVL",
]
WINDOW = [{"label": "M1", "opening_start": "09:30", "opening_bars": 3}]


def _load_oracle_r1(oracle_csv):
    import pandas as pd
    df = pd.read_csv(oracle_csv)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    r1 = df[df["rank"] == 1][["date", "ticker"]].set_index("date")["ticker"].to_dict()
    return r1


def _run_one(task):
    (period_label, eval_start, eval_end,
     min_ev, entry_w, avg_win_w, rel_str_w) = task

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed
    import pandas as pd

    trade_rows, _skip_log, _trading_days = run_selector_backtest(
        n=1,
        tickers=TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOW,
        stop_pct=0.45,
        min_hold_bars=1,
        ma_momentum_gate=True,
        feed=DataFeed.SIP,
        source="alpaca",
        qqq_or_weight=0.40,
        normalize_or_by_adr=True,
        enable_reversal=True,
        enable_bearish_reentry=True,
        enable_bullish_reentry=True,
        lookback_days=60,
        min_pool_vote_to_trade=4,
        min_ev=min_ev,
        score_entry_weight=entry_w,
        score_avg_win_weight=avg_win_w,
        score_win_rate_weight=0.10,
        score_ev_trend_weight=0.10,
        score_rel_strength_weight=rel_str_w,
    )
    weights = _parse_weights([100], 1)
    _apply_capital_flow(trade_rows, WINDOW, INITIAL_CAPITAL, weights, 1)

    active = [r for r in trade_rows if not r.get("skipped")]
    if not active:
        return {
            "period": period_label, "min_ev": min_ev,
            "entry_w": entry_w, "avg_win_w": avg_win_w, "rel_str_w": rel_str_w,
            "n_days": 0, "wins": 0, "losses": 0,
            "cap_pnl": 0.0, "ret_pct": 0.0, "avg_pnl_pct": 0.0,
            "win_rate": 0.0, "oracle_r1_match": 0, "oracle_r1_in_top3": 0, "n_match_days": 0,
        }

    df = pd.DataFrame(active)
    primary = df[df["rank"] == 1].copy()
    primary["date"] = pd.to_datetime(primary["date"]).dt.date

    oracle_r1 = _load_oracle_r1(ORACLE_CSV)

    r1_match = 0
    n_match_days = 0
    for _, row in primary.iterrows():
        d = row["date"]
        if d in oracle_r1:
            n_match_days += 1
            if row["ticker"] == oracle_r1[d]:
                r1_match += 1

    cap_pnl = df["cap_pnl"].sum()
    wins = int((primary["pnl_pct"] > 0).sum())
    losses = int((primary["pnl_pct"] <= 0).sum())
    n_days = primary["date"].nunique()
    avg_pnl_pct = primary["pnl_pct"].mean()
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

    return {
        "period": period_label, "min_ev": min_ev,
        "entry_w": entry_w, "avg_win_w": avg_win_w, "rel_str_w": rel_str_w,
        "n_days": n_days, "wins": wins, "losses": losses,
        "cap_pnl": cap_pnl, "ret_pct": cap_pnl / INITIAL_CAPITAL * 100,
        "avg_pnl_pct": avg_pnl_pct, "win_rate": win_rate,
        "oracle_r1_match": r1_match,
        "oracle_r1_match_pct": r1_match / n_match_days if n_match_days > 0 else 0.0,
        "n_match_days": n_match_days,
    }


def main():
    tasks = [
        (period_label, eval_start, eval_end, min_ev, entry_w, avg_win_w, rel_str_w)
        for (period_label, eval_start, eval_end),
            min_ev, entry_w, avg_win_w, rel_str_w
        in product(PERIODS, MIN_EV_VALUES, ENTRY_WEIGHTS, AVG_WIN_WEIGHTS, REL_STR_WEIGHTS)
    ]

    print(f"Running {len(tasks)} combinations across {len(PERIODS)} periods...")
    print(f"min_ev × entry_w × avg_win_w × rel_str_w = "
          f"{len(MIN_EV_VALUES)}×{len(ENTRY_WEIGHTS)}×{len(AVG_WIN_WEIGHTS)}×{len(REL_STR_WEIGHTS)} = "
          f"{len(MIN_EV_VALUES)*len(ENTRY_WEIGHTS)*len(AVG_WIN_WEIGHTS)*len(REL_STR_WEIGHTS)} per period\n")

    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_run_one, t): t for t in tasks}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                r = future.result()
                results.append(r)
                print(
                    f"[{completed:>3}/{len(tasks)}] {r['period']:<14} "
                    f"ev={r['min_ev']:>5.1f} ew={r['entry_w']:.2f} aw={r['avg_win_w']:.2f} rs={r['rel_str_w']:.2f}  "
                    f"{r['ret_pct']:>+7.2f}%  {r['wins']}W/{r['losses']}L  "
                    f"wr={r['win_rate']:.0%}  oracle_match={r.get('oracle_r1_match_pct', 0):.0%}"
                )
            except Exception as exc:
                t = futures[future]
                print(f"  ERROR {t}: {exc}")

    import pandas as pd
    df = pd.DataFrame(results)

    for period_label, _, _ in PERIODS:
        sub = df[df["period"] == period_label].copy()
        baseline = sub[
            (sub["min_ev"] == 0.0) &
            (sub["entry_w"] == 0.60) &
            (sub["avg_win_w"] == 0.00) &
            (sub["rel_str_w"] == 0.15)
        ]["ret_pct"].iloc[0] if not sub.empty else 0.0

        print(f"\n{'='*100}")
        print(f"  PERIOD: {period_label}  — top 20 by P&L  (baseline = {baseline:+.2f}%)")
        print(f"{'='*100}")
        print(f"  {'ev':>5} {'ew':>5} {'aw':>5} {'rs':>5}  {'ret%':>8}  {'vs base':>8}  {'W/L':<9} {'WR':>5}  {'oracle%':>8}")
        print(f"  {'-'*85}")
        for _, row in sub.sort_values("ret_pct", ascending=False).head(20).iterrows():
            delta = row["ret_pct"] - baseline
            wl = f"{int(row['wins'])}W/{int(row['losses'])}L"
            marker = " ◄" if row["ret_pct"] == sub["ret_pct"].max() else ""
            print(
                f"  {row['min_ev']:>5.1f} {row['entry_w']:>5.2f} {row['avg_win_w']:>5.2f} {row['rel_str_w']:>5.2f}  "
                f"{row['ret_pct']:>+8.2f}%  {delta:>+8.2f}pp  {wl:<9} "
                f"{row['win_rate']:>4.0%}  {row.get('oracle_r1_match_pct', 0):>7.0%}{marker}"
            )

        # Impact of each dimension
        print(f"\n  --- Dimension impact (avg ret%) ---")
        for col, vals in [
            ("min_ev",    MIN_EV_VALUES),
            ("entry_w",   ENTRY_WEIGHTS),
            ("avg_win_w", AVG_WIN_WEIGHTS),
            ("rel_str_w", REL_STR_WEIGHTS),
        ]:
            print(f"  {col}:")
            for v in vals:
                avg_ret = sub[sub[col] == v]["ret_pct"].mean()
                avg_match = sub[sub[col] == v]["oracle_r1_match_pct"].mean()
                print(f"    {v:<6}  avg_ret={avg_ret:>+7.2f}%  oracle_match={avg_match:.0%}")

    # Cross-period: best configs that hold in BOTH periods
    if len(PERIODS) == 2:
        keys = ["min_ev", "entry_w", "avg_win_w", "rel_str_w"]
        p1_label, p2_label = PERIODS[0][0], PERIODS[1][0]
        p1 = df[df["period"] == p1_label].copy()
        p2 = df[df["period"] == p2_label].copy()
        p1["rank_p1"] = p1["ret_pct"].rank(ascending=False)
        p2["rank_p2"] = p2["ret_pct"].rank(ascending=False)
        merged = p1.merge(p2, on=keys, suffixes=("_p1", "_p2"))
        merged["rank_sum"] = merged["rank_p1"] + merged["rank_p2"]
        merged = merged.sort_values("rank_sum")

        print(f"\n{'='*100}")
        print(f"  CROSS-PERIOD CONSISTENCY — top configs in both {p1_label} and {p2_label}")
        print(f"{'='*100}")
        print(f"  {'ev':>5} {'ew':>5} {'aw':>5} {'rs':>5}  {'May ret%':>9}  {'Apr+May%':>10}  {'oracle%(May)':>13}  rank_sum")
        print(f"  {'-'*80}")
        for _, row in merged.head(15).iterrows():
            print(
                f"  {row['min_ev']:>5.1f} {row['entry_w']:>5.2f} {row['avg_win_w']:>5.2f} {row['rel_str_w']:>5.2f}  "
                f"{row['ret_pct_p1']:>+9.2f}%  {row['ret_pct_p2']:>+10.2f}%  "
                f"{row.get('oracle_r1_match_pct_p1', 0):>12.0%}  "
                f"#{int(row['rank_p1'])} + #{int(row['rank_p2'])} = {int(row['rank_sum'])}"
            )


if __name__ == "__main__":
    main()
