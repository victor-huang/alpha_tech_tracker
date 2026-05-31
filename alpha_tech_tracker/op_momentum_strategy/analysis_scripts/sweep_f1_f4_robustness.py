"""
Session 7 — F1+F4 gates multi-period robustness sweep.

Tests 4 configs across 5 periods to confirm F1 (entry quality gate) and
F4 (score gap tiebreaker) are robust beyond May 2026.

Configs:
  A  baseline              (no gates)
  B  F1 entry>0.80
  C  F4 gap<0.50 tiebreak
  D  F1+F4 combined        (entry>0.80 + gap<0.50)

Periods:
  May-2026       2026-05-01 → 2026-05-29   (the bull regime we tuned on)
  Apr+May-2026   2026-04-01 → 2026-05-29   (extended check)
  Q1-2026        2026-01-01 → 2026-03-31   (different regime, bear start)
  2025           2025-01-01 → 2025-12-31   (full year baseline)
  2024           2024-01-01 → 2024-12-31   (long-term check)

Run from project root:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/sweep_f1_f4_robustness.py
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

CONFIGS = [
    ("A-baseline",  0.00, 0.00),
    ("B-F1(>0.80)", 0.80, 0.00),
    ("C-F4(<0.50)", 0.00, 0.50),
    ("D-F1+F4",     0.80, 0.50),
]

PERIODS = [
    ("May-2026",     date(2026, 5, 1),  date(2026, 5, 29)),
    ("Apr+May-2026", date(2026, 4, 1),  date(2026, 5, 29)),
    ("Q1-2026",      date(2026, 1, 1),  date(2026, 3, 31)),
    ("2025",         date(2025, 1, 1),  date(2025, 12, 31)),
    ("2024",         date(2024, 1, 1),  date(2024, 12, 31)),
]

INITIAL_CAPITAL = 10_000.0
TICKERS = [
    "APP", "SHOP", "CVNA", "AMD", "META", "EXPE", "JPM", "TSLA",
    "MU", "CRDO", "PLTR", "COIN", "CLS", "MSTR", "CRWV", "MRVL",
]
WINDOW = [{"label": "M1", "opening_start": "09:30", "opening_bars": 3}]
BASE_KWARGS = dict(
    stop_pct=0.45, min_hold_bars=1, ma_momentum_gate=True,
    qqq_or_weight=0.40, normalize_or_by_adr=True,
    enable_reversal=True, enable_bearish_reentry=True, enable_bullish_reentry=True,
    lookback_days=60, min_pool_vote_to_trade=4,
    score_entry_weight=0.60, score_avg_win_weight=0.00,
    score_win_rate_weight=0.10, score_ev_trend_weight=0.10,
    score_rel_strength_weight=0.15,
)


def _run_one(task):
    config_label, min_ev_mid, gap_tb, period_label, eval_start, eval_end = task

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    trade_rows, _sl, _td = run_selector_backtest(
        n=1, tickers=TICKERS, eval_start=eval_start, eval_end=eval_end,
        windows=WINDOW, feed=DataFeed.SIP, source="alpaca",
        min_entry_vs_mid=min_ev_mid, score_gap_tiebreak=gap_tb,
        **BASE_KWARGS,
    )
    weights = _parse_weights([100], 1)
    _apply_capital_flow(trade_rows, WINDOW, INITIAL_CAPITAL, weights, 1)

    import pandas as pd
    active = [r for r in trade_rows if not r.get("skipped")]
    if not active:
        return {"config": config_label, "period": period_label,
                "ret_pct": 0.0, "wins": 0, "losses": 0, "skips": 0, "n_days": 0, "win_rate": 0.0}

    df = pd.DataFrame(active)
    pri = df[df["rank"] == 1]
    cap_pnl = df["cap_pnl"].sum()
    wins = int((pri["pnl_pct"] > 0).sum())
    losses = int((pri["pnl_pct"] <= 0).sum())
    n_days = pri["date"].nunique()
    total_days_in_period = len(pd.bdate_range(eval_start, eval_end))
    skips = total_days_in_period - n_days

    return {
        "config": config_label, "period": period_label,
        "ret_pct": cap_pnl / INITIAL_CAPITAL * 100,
        "wins": wins, "losses": losses, "skips": skips, "n_days": n_days,
        "win_rate": wins / (wins + losses) if (wins + losses) else 0.0,
    }


def main():
    tasks = [
        (cfg_label, min_ev, gap_tb, period_label, eval_start, eval_end)
        for (cfg_label, min_ev, gap_tb), (period_label, eval_start, eval_end)
        in product(CONFIGS, PERIODS)
    ]

    print(f"Running {len(tasks)} tasks ({len(CONFIGS)} configs × {len(PERIODS)} periods) — 8 workers\n")

    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_run_one, t): t for t in tasks}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                r = future.result()
                results.append(r)
                print(f"  [{completed:>2}/{len(tasks)}] {r['period']:<14} {r['config']:<14} "
                      f"{r['ret_pct']:>+8.2f}%  {r['wins']}W/{r['losses']}L/{r['skips']}sk  "
                      f"wr={r['win_rate']:.0%}")
            except Exception as exc:
                t = futures[future]
                print(f"  ERROR {t}: {exc}")

    import pandas as pd

    df = pd.DataFrame(results)
    pivot = df.pivot(index="period", columns="config", values="ret_pct")
    period_order = [p[0] for p in PERIODS]
    config_order = [c[0] for c in CONFIGS]
    pivot = pivot.reindex(index=period_order, columns=config_order)

    # Add delta columns
    pivot["B-A"] = pivot["B-F1(>0.80)"] - pivot["A-baseline"]
    pivot["C-A"] = pivot["C-F4(<0.50)"] - pivot["A-baseline"]
    pivot["D-A"] = pivot["D-F1+F4"]     - pivot["A-baseline"]

    print(f"\n{'='*90}")
    print(f"  RESULT TABLE — returns by config and period")
    print(f"{'='*90}")
    print(f"  {'Period':<15} {'A-baseline':>12} {'B-F1(>0.80)':>12} {'C-F4(<0.50)':>12} {'D-F1+F4':>10}  {'B-A':>7}  {'C-A':>7}  {'D-A':>7}")
    print(f"  {'-'*85}")
    for period in period_order:
        row = pivot.loc[period]
        print(f"  {period:<15} {row['A-baseline']:>+12.2f}% {row['B-F1(>0.80)']:>+12.2f}% "
              f"{row['C-F4(<0.50)']:>+12.2f}% {row['D-F1+F4']:>+10.2f}%  "
              f"{row['B-A']:>+7.2f}pp {row['C-A']:>+7.2f}pp {row['D-A']:>+7.2f}pp")

    print(f"\n  Win rate table:")
    wr_pivot = df.pivot(index="period", columns="config", values="win_rate").reindex(
        index=period_order, columns=config_order)
    for period in period_order:
        row = wr_pivot.loc[period]
        print(f"  {period:<15} " + "  ".join(f"{row[c]:>10.0%}" for c in config_order))

    # Summary: which configs consistently beat baseline
    print(f"\n  Periods where each gate beats baseline:")
    for col, lbl in [("B-A","F1"), ("C-A","F4"), ("D-A","F1+F4")]:
        wins_above = (pivot[col] > 0).sum()
        avg_delta = pivot[col].mean()
        min_delta = pivot[col].min()
        print(f"  {lbl}: {wins_above}/{len(period_order)} periods positive  avg={avg_delta:>+.2f}pp  worst={min_delta:>+.2f}pp")

    pivot.to_csv("/Users/victorhuang/work/alpha_tech_tracker/logs/oracle_compare/session7_f1_f4_robustness.csv")
    print("\n  Results saved to logs/oracle_compare/session7_f1_f4_robustness.csv")


if __name__ == "__main__":
    main()
