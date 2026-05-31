"""
Sweep --stop-pct around the current value of 0.4 for May 2026 and Apr+May 2026.

Hard stop fires when price moves adversely by stop_pct × OR_range from the breakout edge.
Currently set to 0.4 (40% of OR range). This sweep tests 0.10 – 0.80 in steps of 0.05.

Config: bull-regime base (CHTR excluded, 3 bars, all other params fixed).

Run from project root:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/sweep_stop_pct.py
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

import numpy as np

STOP_PCT_VALUES = [round(v, 2) for v in np.arange(0.10, 0.85, 0.05)]

PERIODS = [
    ("May-2026",     date(2026, 5, 1),  date(2026, 5, 29)),
    ("Apr+May-2026", date(2026, 4, 1),  date(2026, 5, 29)),
]

INITIAL_CAPITAL = 10_000.0
TICKERS = [
    "APP", "SHOP", "CVNA", "AMD", "META", "EXPE", "JPM", "TSLA",
    "MU", "CRDO", "PLTR", "COIN", "CLS", "MSTR", "CRWV", "MRVL",
]
SCORE_WEIGHTS = {
    "score_entry_weight":        0.60,
    "score_avg_win_weight":      0.00,
    "score_win_rate_weight":     0.10,
    "score_ev_trend_weight":     0.10,
    "score_rel_strength_weight": 0.15,
}
WINDOW = [{"label": "M1", "opening_start": "09:30", "opening_bars": 3}]


def _run_one(task):
    period_label, eval_start, eval_end, stop_pct = task

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        _apply_capital_flow,
        _parse_weights,
        run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    trade_rows, _skip_log, _trading_days = run_selector_backtest(
        n=1,
        tickers=TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOW,
        stop_pct=stop_pct,
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
        **SCORE_WEIGHTS,
    )
    weights = _parse_weights([100], 1)
    _apply_capital_flow(trade_rows, WINDOW, INITIAL_CAPITAL, weights, 1)

    active = [r for r in trade_rows if not r.get("skipped")]
    if not active:
        return {
            "period": period_label, "stop_pct": stop_pct,
            "n_days": 0, "wins": 0, "losses": 0,
            "cap_pnl": 0.0, "ret_pct": 0.0, "avg_pnl_pct": 0.0,
            "win_rate": 0.0, "hard_stops": 0,
        }

    import pandas as pd
    df = pd.DataFrame(active)
    primary = df[df["rank"] == 1]
    cap_pnl = df["cap_pnl"].sum()
    wins = int((primary["pnl_pct"] > 0).sum())
    losses = int((primary["pnl_pct"] <= 0).sum())
    n_days = primary["date"].nunique()
    avg_pnl_pct = primary["pnl_pct"].mean()
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0
    hard_stops = int((primary["exit_reason"] == "hard_stop").sum())

    return {
        "period": period_label, "stop_pct": stop_pct,
        "n_days": n_days, "wins": wins, "losses": losses,
        "cap_pnl": cap_pnl, "ret_pct": cap_pnl / INITIAL_CAPITAL * 100,
        "avg_pnl_pct": avg_pnl_pct, "win_rate": win_rate,
        "hard_stops": hard_stops,
    }


def main():
    tasks = [
        (period_label, eval_start, eval_end, stop_pct)
        for (period_label, eval_start, eval_end), stop_pct
        in product(PERIODS, STOP_PCT_VALUES)
    ]

    print(f"Running {len(tasks)} combinations ({len(STOP_PCT_VALUES)} stop values × {len(PERIODS)} periods)...")
    print(f"Stop values: {STOP_PCT_VALUES}\n")

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
                    f"[{completed:>2}/{len(tasks)}] {r['period']:<14} "
                    f"stop={r['stop_pct']:.2f}  "
                    f"{r['ret_pct']:>+7.2f}%  {r['wins']}W/{r['losses']}L  "
                    f"wr={r['win_rate']:.0%}  hs={r['hard_stops']}  avg={r['avg_pnl_pct']:>+.3f}%"
                )
            except Exception as exc:
                t = futures[future]
                print(f"  ERROR {t}: {exc}")

    import pandas as pd
    df = pd.DataFrame(results)

    for period_label, _, _ in PERIODS:
        sub = df[df["period"] == period_label].sort_values("stop_pct")
        baseline = sub[sub["stop_pct"] == 0.40]["ret_pct"].iloc[0] if not sub[sub["stop_pct"] == 0.40].empty else 0.0

        print(f"\n{'='*80}")
        print(f"  PERIOD: {period_label}  (baseline = stop_pct 0.40)")
        print(f"{'='*80}")
        print(f"  {'stop':>5}  {'ret%':>8}  {'vs 0.40':>9}  {'W/L':<9}  {'WR':>5}  {'HS':>4}  {'avg%':>8}")
        print(f"  {'-'*70}")
        for _, row in sub.iterrows():
            delta = row["ret_pct"] - baseline
            delta_str = f"{delta:>+.2f}pp" if row["stop_pct"] != 0.40 else "baseline"
            wl = f"{int(row['wins'])}W/{int(row['losses'])}L"
            marker = " ◄" if row["ret_pct"] == sub["ret_pct"].max() else ""
            print(
                f"  {row['stop_pct']:>5.2f}  {row['ret_pct']:>+8.2f}%  {delta_str:>9}  {wl:<9}  "
                f"{row['win_rate']:>4.0%}  {int(row['hard_stops']):>4}  {row['avg_pnl_pct']:>+8.3f}%{marker}"
            )

    # Best stop per period
    print(f"\n{'='*80}")
    print("  SUMMARY — Best stop_pct per period")
    print(f"{'='*80}")
    for period_label, _, _ in PERIODS:
        sub = df[df["period"] == period_label]
        best = sub.loc[sub["ret_pct"].idxmax()]
        print(
            f"  {period_label:<14}: stop={best['stop_pct']:.2f}  "
            f"{best['ret_pct']:>+.2f}%  {int(best['wins'])}W/{int(best['losses'])}L  "
            f"wr={best['win_rate']:.0%}  hard_stops={int(best['hard_stops'])}"
        )

    # Cross-period: find stop that maximises sum of returns
    pivot = df.pivot(index="stop_pct", columns="period", values="ret_pct")
    pivot["sum"] = pivot.sum(axis=1)
    pivot["min"] = pivot[[p for p in pivot.columns if p != "sum"]].min(axis=1)
    pivot = pivot.sort_values("sum", ascending=False)
    print(f"\n  Cross-period combined return (sum across periods):")
    print(f"  {'stop':>5}  {'sum':>8}  {'min':>8}  " + "  ".join(f"{p:>14}" for p in PERIODS))
    for stop_pct, row in pivot.head(10).iterrows():
        period_vals = "  ".join(f"{row[p[0]]:>+14.2f}%" for p in PERIODS)
        print(f"  {stop_pct:>5.2f}  {row['sum']:>+8.2f}%  {row['min']:>+8.2f}%  {period_vals}")


if __name__ == "__main__":
    main()
