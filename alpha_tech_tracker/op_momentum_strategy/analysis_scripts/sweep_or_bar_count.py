"""
Sweep --opening-bars (OR bar count) for the M1 window.

Tests 1–6 bars (5-min to 30-min opening range) across three periods:
  - May-2026       (bull regime, primary target)
  - Apr+May-2026   (mixed regime, overfitting check)
  - 2025           (full year, long-term robustness)

Uses the recommended bull-regime config from Finding 19 (CHTR excluded).

Run from project root:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/sweep_or_bar_count.py
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from itertools import product

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

OR_BARS_VALUES = [1, 2, 3, 4, 5, 6]

PERIODS = [
    ("May-2026",     date(2026, 5, 1),  date(2026, 5, 29)),
    ("Apr+May-2026", date(2026, 4, 1),  date(2026, 5, 29)),
    ("2025",         date(2025, 1, 1),  date(2025, 12, 31)),
]

INITIAL_CAPITAL = 10_000.0

# Bull-regime base config (CHTR excluded per Finding 19)
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


def _run_one(task):
    period_label, eval_start, eval_end, or_bars = task

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        _apply_capital_flow,
        _parse_weights,
        run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    window = [{"label": "M1", "opening_start": "09:30", "opening_bars": or_bars}]

    trade_rows, _skip_log, _trading_days = run_selector_backtest(
        n=1,
        tickers=TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=window,
        stop_pct=0.4,
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
    _apply_capital_flow(trade_rows, window, INITIAL_CAPITAL, weights, 1)

    active = [r for r in trade_rows if not r.get("skipped")]
    if not active:
        return {
            "period": period_label,
            "or_bars": or_bars,
            "entry_time": f"09:{30 + or_bars * 5:02d}",
            "n_days": 0,
            "wins": 0,
            "losses": 0,
            "cap_pnl": 0.0,
            "ret_pct": 0.0,
            "avg_pnl_pct": 0.0,
            "win_rate": 0.0,
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

    return {
        "period": period_label,
        "or_bars": or_bars,
        "entry_time": f"09:{30 + or_bars * 5:02d}",
        "n_days": n_days,
        "wins": wins,
        "losses": losses,
        "cap_pnl": cap_pnl,
        "ret_pct": cap_pnl / INITIAL_CAPITAL * 100,
        "avg_pnl_pct": avg_pnl_pct,
        "win_rate": win_rate,
    }


def main():
    tasks = [
        (period_label, eval_start, eval_end, or_bars)
        for (period_label, eval_start, eval_end), or_bars
        in product(PERIODS, OR_BARS_VALUES)
    ]

    print(f"Running {len(tasks)} combinations ({len(OR_BARS_VALUES)} bar counts × {len(PERIODS)} periods)...")
    print(f"Bar counts: {OR_BARS_VALUES} → entry times 09:35 – 10:00\n")

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
                    f"bars={r['or_bars']} (entry {r['entry_time']})  "
                    f"{r['ret_pct']:>+7.2f}%  {r['wins']}W/{r['losses']}L  "
                    f"wr={r['win_rate']:.0%}  avg={r['avg_pnl_pct']:>+.3f}%"
                )
            except Exception as exc:
                t = futures[future]
                print(f"  ERROR {t}: {exc}")

    import pandas as pd
    df = pd.DataFrame(results)

    for period_label, _, _ in PERIODS:
        sub = df[df["period"] == period_label].sort_values("or_bars")
        baseline = sub[sub["or_bars"] == 3]["ret_pct"].iloc[0] if not sub[sub["or_bars"] == 3].empty else 0.0

        print(f"\n{'='*75}")
        print(f"  PERIOD: {period_label}  (baseline = 3 bars / 15-min OR)")
        print(f"{'='*75}")
        print(f"  {'bars':<6} {'entry':<7} {'ret%':>7}  {'vs 3-bar':>9}  {'W/L':<8}  {'WR':>5}  {'avg%':>8}  {'days':>5}")
        print(f"  {'-'*70}")
        for _, row in sub.iterrows():
            delta = row["ret_pct"] - baseline
            delta_str = f"{delta:>+.2f}pp" if row["or_bars"] != 3 else "baseline"
            wl = f"{int(row['wins'])}W/{int(row['losses'])}L"
            marker = " ◄" if row["ret_pct"] == sub["ret_pct"].max() else ""
            print(
                f"  {int(row['or_bars']):<6} {row['entry_time']:<7} "
                f"{row['ret_pct']:>+7.2f}%  {delta_str:>9}  {wl:<8}  "
                f"{row['win_rate']:>4.0%}  {row['avg_pnl_pct']:>+8.3f}%  "
                f"{int(row['n_days']):>5}{marker}"
            )

    # Summary: which bar count wins each period?
    print(f"\n{'='*75}")
    print("  SUMMARY — Best bar count per period")
    print(f"{'='*75}")
    for period_label, _, _ in PERIODS:
        sub = df[df["period"] == period_label]
        best = sub.loc[sub["ret_pct"].idxmax()]
        print(
            f"  {period_label:<14}: {int(best['or_bars'])} bars (entry {best['entry_time']})  "
            f"{best['ret_pct']:>+.2f}%  {int(best['wins'])}W/{int(best['losses'])}L  "
            f"wr={best['win_rate']:.0%}"
        )

    # Consistency: bar count ranked best across all periods
    agg = df.groupby("or_bars")["ret_pct"].mean().reset_index()
    agg.columns = ["or_bars", "avg_ret_pct"]
    agg = agg.sort_values("avg_ret_pct", ascending=False)
    print(f"\n  Avg return across all periods (robustness ranking):")
    for _, row in agg.iterrows():
        print(f"    {int(row['or_bars'])} bars  avg={row['avg_ret_pct']:>+.2f}%")


if __name__ == "__main__":
    main()
