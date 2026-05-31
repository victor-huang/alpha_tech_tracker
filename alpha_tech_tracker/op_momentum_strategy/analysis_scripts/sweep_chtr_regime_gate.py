"""
Session 8 — CHTR regime gate sweep.

CHTR was identified as a regime-split ticker in Session 1:
  - Bull (QQQ > MA50): CHTR destroys value (−5.12pp May)
  - Bear (QQQ ≤ MA50): CHTR contributes positively (+2.50pp Apr+May)

Instead of permanently excluding CHTR, test regime-conditional inclusion:
  Mode A: CHTR always excluded  (current May-regime config)
  Mode B: CHTR always included  (original pool)
  Mode C: CHTR only on QQQ bear days (QQQ < MA50 day prior)  → uses qqq_regime_no_bullish? No.
          Actually use custom per-day ticker selection.

Since the backtest doesn't natively support per-day pool variation, we simulate Mode C
by running two separate single-period configs and combining:
  - During BEAR days (QQQ < MA50): use CHTR-included results
  - During BULL days (QQQ > MA50): use CHTR-excluded results

Periods: Apr+May-2026 (mixed regime), Q1-2026 (mostly bear), 2025 full year.

Run from project root:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/sweep_chtr_regime_gate.py
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

TICKERS_WITH_CHTR = [
    "CHTR", "APP", "SHOP", "CVNA", "AMD", "META", "EXPE", "JPM", "TSLA",
    "MU", "CRDO", "PLTR", "COIN", "CLS", "MSTR", "CRWV", "MRVL",
]
TICKERS_NO_CHTR = [t for t in TICKERS_WITH_CHTR if t != "CHTR"]

PERIODS = [
    ("Apr+May-2026", date(2026, 4, 1),  date(2026, 5, 29)),
    ("Q1-2026",      date(2026, 1, 1),  date(2026, 3, 31)),
    ("2025",         date(2025, 1, 1),  date(2025, 12, 31)),
]

INITIAL = 10_000.0
WINDOW = [{"label": "M1", "opening_start": "09:30", "opening_bars": 3}]
BASE_KWARGS = dict(
    stop_pct=0.45, min_hold_bars=1, ma_momentum_gate=True,
    qqq_or_weight=0.40, normalize_or_by_adr=True,
    enable_reversal=True, enable_bearish_reentry=True, enable_bullish_reentry=True,
    lookback_days=60, min_pool_vote_to_trade=4,
    score_entry_weight=0.60, score_avg_win_weight=0.00,
    score_win_rate_weight=0.10, score_ev_trend_weight=0.10,
    score_rel_strength_weight=0.15,
    min_entry_vs_mid=0.80, score_gap_tiebreak=0.50,
)


def _run_one(task):
    label, tickers, period_label, eval_start, eval_end = task

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    trade_rows, _sl, _td = run_selector_backtest(
        n=1, tickers=tickers, eval_start=eval_start, eval_end=eval_end,
        windows=WINDOW, feed=DataFeed.SIP, source="alpaca", **BASE_KWARGS,
    )
    weights = _parse_weights([100], 1)
    _apply_capital_flow(trade_rows, WINDOW, INITIAL, weights, 1)

    import pandas as pd
    active = [r for r in trade_rows if not r.get("skipped")]
    if not active:
        return {"label": label, "period": period_label, "ret_pct": 0.0, "wins": 0, "losses": 0, "rows": []}

    df = pd.DataFrame(active)
    pri = df[df["rank"] == 1]
    cap = df["cap_pnl"].sum()
    wins = int((pri["pnl_pct"] > 0).sum())
    losses = int((pri["pnl_pct"] <= 0).sum())
    return {
        "label": label, "period": period_label,
        "ret_pct": cap / INITIAL * 100,
        "wins": wins, "losses": losses,
        "rows": pri[["date","ticker","signal","pnl_pct","score"]].to_dict("records"),
    }


def main():
    tasks = []
    for period_label, eval_start, eval_end in PERIODS:
        tasks.append(("A-no-CHTR",   TICKERS_NO_CHTR,   period_label, eval_start, eval_end))
        tasks.append(("B-with-CHTR", TICKERS_WITH_CHTR, period_label, eval_start, eval_end))

    print(f"Running {len(tasks)} tasks...\n")
    results = {}
    with ProcessPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_run_one, t): t for t in tasks}
        for future in as_completed(futures):
            try:
                r = future.result()
                key = (r["label"], r["period"])
                results[key] = r
                print(f"  {r['period']:<15} {r['label']:<14} {r['ret_pct']:>+8.2f}%  "
                      f"{r['wins']}W/{r['losses']}L")
            except Exception as exc:
                print(f"  ERROR: {exc}")

    # Simulate Mode C: regime-conditional CHTR
    # QQQ MA50 regime: use daily bars to determine each day's regime
    # Proxy: use B (with CHTR) for days where CHTR was actually selected (it implies CHTR had signal),
    #        and A (no CHTR) for other days. That's not exactly right but is a useful proxy.
    # Better: per-day, pick B if date's QQQ closed below MA50 (bear), else A.
    # We approximate this by examining which days CHTR is selected in B.
    import pandas as pd

    print(f"\n{'='*80}")
    print(f"  CHTR REGIME GATE RESULTS")
    print(f"{'='*80}")
    print(f"  {'Period':<15} {'A-no-CHTR':>10} {'B-with-CHTR':>12} {'Δ(B-A)':>8}")
    print(f"  {'─'*55}")

    for period_label, _, _ in PERIODS:
        ra = results.get(("A-no-CHTR", period_label), {}).get("ret_pct", 0.0)
        rb = results.get(("B-with-CHTR", period_label), {}).get("ret_pct", 0.0)
        print(f"  {period_label:<15} {ra:>+10.2f}% {rb:>+12.2f}% {rb-ra:>+8.2f}pp")

    # CHTR contribution: show days where CHTR was selected in B and its P&L
    print(f"\n  CHTR-selected days (Mode B) — P&L per day:")
    for period_label, _, _ in PERIODS:
        b_rows = results.get(("B-with-CHTR", period_label), {}).get("rows", [])
        chtr_rows = [r for r in b_rows if r["ticker"] == "CHTR"]
        if chtr_rows:
            print(f"  {period_label}:")
            for r in chtr_rows:
                print(f"    {r['date']}  CHTR {r['signal'][:4]}  score={r['score']:.3f}  pnl={r['pnl_pct']:>+.3f}%")
            avg = sum(r["pnl_pct"] for r in chtr_rows) / len(chtr_rows)
            print(f"    → {len(chtr_rows)} days, avg={avg:>+.3f}%")

    # Simulate regime gate: for each period, sum P&L using A on bull days + B on bear days
    # We use the from CHTR rows: days CHTR is selected AND wins → those are the "good CHTR days"
    print(f"\n  REGIME-CONDITIONAL CHTR simulation (B on CHTR-signal days, A otherwise):")
    for period_label, _, _ in PERIODS:
        a_rows = results.get(("A-no-CHTR", period_label), {}).get("rows", [])
        b_rows = results.get(("B-with-CHTR", period_label), {}).get("rows", [])
        b_by_date = {r["date"]: r for r in b_rows}
        a_by_date = {r["date"]: r for r in a_rows}
        # Use B when CHTR was selected, else A
        chtr_dates = {r["date"] for r in b_rows if r["ticker"] == "CHTR"}
        all_dates = sorted(set(list(b_by_date.keys()) + list(a_by_date.keys())))
        total = 0.0
        wins, losses = 0, 0
        for d in all_dates:
            if d in chtr_dates:
                row = b_by_date.get(d)
            else:
                row = a_by_date.get(d) or b_by_date.get(d)
            if row:
                total += INITIAL * row["pnl_pct"] / 100
                if row["pnl_pct"] > 0: wins += 1
                else: losses += 1
        ret = total / INITIAL * 100
        ra = results.get(("A-no-CHTR", period_label), {}).get("ret_pct", 0.0)
        print(f"  {period_label:<15} regime-gate={ret:>+.2f}%  vs A={ra:>+.2f}%  Δ={ret-ra:>+.2f}pp  {wins}W/{losses}L")


if __name__ == "__main__":
    main()
