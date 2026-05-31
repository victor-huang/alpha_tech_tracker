"""
Bull-regime parameter sweep — May 2026.

Motivated by oracle analysis showing three root causes:
  1. CHTR overfitting (3-day losing streak at rank #1)
  2. Top-1 rank miss (MU was rank 2/5 on the two biggest oracle days)
  3. EV-gate exclusions (9 days; 60d lookback includes April bear)
  4. Pool-vote skip (2 days; fewer than 4 tickers with positive rolling EV)

Sweep dimensions:
  --top             : 1, 2
  --lookback        : 30, 45, 60  (shorter = more responsive to bull recovery)
  --min-pool-vote   : 0, 2, 4
  CHTR inclusion    : in, out     (exclude CHTR to remove overfit streak)

Each combo is evaluated over:
  A) May 2026 only   (2026-05-01 → 2026-05-29)  — primary target
  B) Apr+May 2026    (2026-04-01 → 2026-05-29)  — overfitting check

All other flags are pinned to the base config:
  --window M1 09:30 3 --min-hold-bars 1 --ma-momentum-gate
  --feed sip --qqq-or-weight 0.40 --normalize-or-by-adr --stop-pct 0.4
  --reversal --bearish-reentry --bullish-reentry
  --score-entry-weight 0.60 --score-avg-win-weight 0.00
  --score-win-rate-weight 0.10 --score-ev-trend-weight 0.10
  --score-rel-strength-weight 0.15

Run from project root:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/sweep_bull_regime_may2026.py
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

from alpaca.data.enums import DataFeed

# ── Sweep grid ───────────────────────────────────────────────────────────────
TOP_VALUES         = [1, 2]
LOOKBACK_VALUES    = [30, 45, 60]
MIN_POOL_VOTE_VALUES = [0, 2, 4]
CHTR_VARIANTS      = [True, False]   # True = include CHTR, False = exclude

PERIODS = [
    ("May-2026",     date(2026, 5, 1),  date(2026, 5, 29)),
    ("Apr+May-2026", date(2026, 4, 1),  date(2026, 5, 29)),
]

# ── Pinned base config ────────────────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
WINDOWS = [{"label": "M1", "opening_start": "09:30", "opening_bars": 3}]
STOP_PCT = 0.4
SCORE_WEIGHTS = {
    "score_entry_weight":       0.60,
    "score_avg_win_weight":     0.00,
    "score_win_rate_weight":    0.10,
    "score_ev_trend_weight":    0.10,
    "score_rel_strength_weight": 0.15,
}


def _run_one(task):
    period_label, eval_start, eval_end, top, lookback, min_pool_vote, include_chtr = task

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        _apply_capital_flow,
        _parse_weights,
        run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    tickers = list(DEFAULT_TICKERS)
    if not include_chtr and "CHTR" in tickers:
        tickers.remove("CHTR")

    trade_rows, _skip_log, _trading_days = run_selector_backtest(
        n=top,
        tickers=tickers,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOWS,
        stop_pct=STOP_PCT,
        min_hold_bars=1,
        ma_momentum_gate=True,
        feed=DataFeed.SIP,
        source="alpaca",
        qqq_or_weight=0.40,
        normalize_or_by_adr=True,
        enable_reversal=True,
        enable_bearish_reentry=True,
        enable_bullish_reentry=True,
        lookback_days=lookback,
        min_pool_vote_to_trade=min_pool_vote,
        **SCORE_WEIGHTS,
    )
    weights = _parse_weights([100], top) if top == 1 else _parse_weights([60, 40], top)
    _apply_capital_flow(trade_rows, WINDOWS, INITIAL_CAPITAL, weights, top)

    active = [r for r in trade_rows if not r.get("skipped")]
    if not active:
        return {
            "period": period_label,
            "top": top,
            "lookback": lookback,
            "min_pool_vote": min_pool_vote,
            "include_chtr": include_chtr,
            "n_trades": 0,
            "n_days": 0,
            "wins": 0,
            "losses": 0,
            "cap_pnl": 0.0,
            "ret_pct": 0.0,
            "avg_pnl_pct": 0.0,
        }

    import pandas as pd
    df = pd.DataFrame(active)
    primary = df[df["rank"] == 1]
    cap_pnl = df["cap_pnl"].sum()
    wins = int((primary["pnl_pct"] > 0).sum())
    losses = int((primary["pnl_pct"] <= 0).sum())
    n_days = primary["date"].nunique()
    avg_pnl_pct = primary["pnl_pct"].mean()

    return {
        "period": period_label,
        "top": top,
        "lookback": lookback,
        "min_pool_vote": min_pool_vote,
        "include_chtr": include_chtr,
        "n_trades": len(primary),
        "n_days": n_days,
        "wins": wins,
        "losses": losses,
        "cap_pnl": cap_pnl,
        "ret_pct": cap_pnl / INITIAL_CAPITAL * 100,
        "avg_pnl_pct": avg_pnl_pct,
    }


def main():
    tasks = []
    for period_label, eval_start, eval_end in PERIODS:
        for top, lookback, min_pool_vote, include_chtr in product(
            TOP_VALUES, LOOKBACK_VALUES, MIN_POOL_VOTE_VALUES, CHTR_VARIANTS
        ):
            tasks.append((period_label, eval_start, eval_end, top, lookback, min_pool_vote, include_chtr))

    print(f"Running {len(tasks)} combinations across {len(PERIODS)} periods...")
    print(f"Workers: 8 parallel processes\n")

    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_run_one, t): t for t in tasks}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                r = future.result()
                results.append(r)
                chtr_str = "CHTR+in" if r["include_chtr"] else "CHTR-out"
                print(
                    f"[{completed:>3}/{len(tasks)}] {r['period']:<14} "
                    f"top={r['top']} lb={r['lookback']:>2} vote={r['min_pool_vote']} {chtr_str:<9}  "
                    f"{r['ret_pct']:>+7.2f}%  {r['wins']}W/{r['losses']}L  "
                    f"avg={r['avg_pnl_pct']:>+.3f}%"
                )
            except Exception as exc:
                t = futures[future]
                print(f"  ERROR {t}: {exc}")

    import pandas as pd

    df = pd.DataFrame(results)

    for period_label in [p[0] for p in PERIODS]:
        sub = df[df["period"] == period_label].copy()
        sub = sub.sort_values("ret_pct", ascending=False)

        print(f"\n{'='*90}")
        print(f"  PERIOD: {period_label}  — ranked by total return")
        print(f"{'='*90}")
        print(f"  {'top':<4} {'lb':<4} {'vote':<5} {'CHTR':<9} {'ret%':>7}  {'W/L':<8}  {'avg_pnl%':>9}  {'days':>5}")
        print(f"  {'-'*75}")
        for _, row in sub.head(20).iterrows():
            chtr_str = "in" if row["include_chtr"] else "out"
            wl = f"{int(row['wins'])}W/{int(row['losses'])}L"
            print(
                f"  {int(row['top']):<4} {int(row['lookback']):<4} {int(row['min_pool_vote']):<5} {chtr_str:<9} "
                f"{row['ret_pct']:>+7.2f}%  {wl:<8}  {row['avg_pnl_pct']:>+9.3f}%  {int(row['n_days']):>5}"
            )

        # Impact of each dimension (averaged over others)
        print(f"\n  --- Dimension impact (avg ret%) ---")
        for col, vals in [
            ("top", TOP_VALUES),
            ("lookback", LOOKBACK_VALUES),
            ("min_pool_vote", MIN_POOL_VOTE_VALUES),
            ("include_chtr", CHTR_VARIANTS),
        ]:
            print(f"  {col}:")
            for v in vals:
                avg = sub[sub[col] == v]["ret_pct"].mean()
                label = str(v) if col != "include_chtr" else ("CHTR+in" if v else "CHTR-out")
                print(f"    {label:<12} avg={avg:>+7.2f}%")

    # Cross-period consistency: highlight configs that rank top-10 in BOTH periods
    if len(PERIODS) == 2:
        p1_label, p2_label = PERIODS[0][0], PERIODS[1][0]
        p1 = df[df["period"] == p1_label].copy()
        p2 = df[df["period"] == p2_label].copy()
        keys = ["top", "lookback", "min_pool_vote", "include_chtr"]
        p1["rank_p1"] = p1["ret_pct"].rank(ascending=False)
        p2["rank_p2"] = p2["ret_pct"].rank(ascending=False)
        merged = p1.merge(p2, on=keys, suffixes=("_p1", "_p2"))
        merged["rank_sum"] = merged["rank_p1"] + merged["rank_p2"]
        merged = merged.sort_values("rank_sum")
        print(f"\n{'='*90}")
        print(f"  CROSS-PERIOD CONSISTENCY (best in both {p1_label} and {p2_label})")
        print(f"{'='*90}")
        print(f"  {'top':<4} {'lb':<4} {'vote':<5} {'CHTR':<9} {'May ret%':>9}  {'Apr+May ret%':>13}  rank_sum")
        print(f"  {'-'*65}")
        for _, row in merged.head(10).iterrows():
            chtr_str = "in" if row["include_chtr"] else "out"
            print(
                f"  {int(row['top']):<4} {int(row['lookback']):<4} {int(row['min_pool_vote']):<5} {chtr_str:<9} "
                f"{row['ret_pct_p1']:>+9.2f}%  {row['ret_pct_p2']:>+13.2f}%  "
                f"#{int(row['rank_p1'])} + #{int(row['rank_p2'])} = {int(row['rank_sum'])}"
            )


if __name__ == "__main__":
    main()
