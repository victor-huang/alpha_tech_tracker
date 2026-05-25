"""
Compare baseline vs --bearish-ma200 for 2025 and 2026 YTD.
Base: --top 2 --weights 60 40 --window M1 09:30 1 --window A1 12:00 3
      --stop-pct 0.6 --stale-cut-mins 45 --stale-cut-threshold 0.75 --reversal --feed sip
"""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

PERIODS = [
    ("2025",     date(2025, 1, 1), date(2025, 12, 31)),
    ("2026 YTD", date(2026, 1, 1), date(2026, 5, 15)),
]

WINDOWS = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 1},
    {"label": "A1", "opening_start": "12:00", "opening_bars": 3},
]
N = 2
WEIGHTS_INPUT = [60, 40]
INITIAL_CAPITAL = 10_000.0


def _run_one(args):
    plabel, eval_start, eval_end, bearish_ma200 = args

    from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
        DEFAULT_TICKERS, _apply_capital_flow, _parse_weights, run_selector_backtest,
    )
    from alpaca.data.enums import DataFeed

    trade_rows, _, _ = run_selector_backtest(
        n=N,
        tickers=DEFAULT_TICKERS,
        eval_start=eval_start,
        eval_end=eval_end,
        windows=WINDOWS,
        stop_pct=0.60,
        stale_cut_mins=45,
        stale_cut_threshold=0.75,
        enable_reversal=True,
        bearish_ma200=bearish_ma200,
        feed=DataFeed.SIP,
    )
    weights = _parse_weights(WEIGHTS_INPUT, N)
    _apply_capital_flow(trade_rows, WINDOWS, INITIAL_CAPITAL, weights, N)
    return trade_rows


def _stats(rows, label):
    active = [r for r in rows if not r.get("skipped")]
    bull   = [r for r in active if r.get("signal") == "BULLISH"]
    bear   = [r for r in active if r.get("signal") == "BEARISH"]

    def _row_stats(subset):
        n    = len(subset)
        wins = sum(1 for r in subset if r.get("pnl", 0) > 0)
        pnl  = sum(r.get("cap_pnl", 0.0) for r in subset)
        wr   = wins / n * 100 if n else 0.0
        return n, wins, wr, pnl

    tn, tw, twr, tpnl = _row_stats(active)
    bn, bw, bwr, bpnl = _row_stats(bull)
    en, ew, ewr, epnl = _row_stats(bear)

    print(f"\n  {label}")
    print(f"  {'─'*62}")
    print(f"  {'':12}  {'Trades':>7}  {'Wins':>6}  {'WR':>6}  {'Cap P&L':>11}")
    print(f"  {'─'*62}")
    print(f"  {'ALL':<12}  {tn:>7}  {tw:>6}  {twr:>5.1f}%  ${tpnl:>+10,.2f}")
    print(f"  {'BULLISH':<12}  {bn:>7}  {bw:>6}  {bwr:>5.1f}%  ${bpnl:>+10,.2f}")
    print(f"  {'BEARISH':<12}  {en:>7}  {ew:>6}  {ewr:>5.1f}%  ${epnl:>+10,.2f}")

    return tpnl, tn, bear


def main():
    tasks = [
        (plabel, pstart, pend, flag)
        for plabel, pstart, pend in PERIODS
        for flag in [False, True]
    ]

    print(f"Running {len(tasks)} tasks...\n", flush=True)

    results = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_run_one, t): t for t in tasks}
        for fut in as_completed(futures):
            t = futures[fut]
            plabel, _, _, flag = t
            try:
                results[(plabel, flag)] = fut.result()
            except Exception as exc:
                print(f"  ERROR {t}: {exc}", flush=True)
                results[(plabel, flag)] = []

    for plabel, pstart, pend in PERIODS:
        base_rows = results.get((plabel, False), [])
        filt_rows = results.get((plabel, True),  [])

        print(f"\n{'='*64}")
        print(f"  {plabel}")
        print(f"{'='*64}")

        base_pnl, base_n, base_bear = _stats(base_rows, "Baseline (no --bearish-ma200)")
        filt_pnl, filt_n, filt_bear = _stats(filt_rows, "With --bearish-ma200")

        skipped = base_n - filt_n
        delta   = filt_pnl - base_pnl
        print(f"\n  Delta: ${delta:+,.2f}  |  Skipped {skipped} trades")

        # Show the bearish trades that were filtered out
        base_bear_keys = {(r["date"], r["ticker"], r.get("window")): r for r in base_bear}
        filt_bear_keys = {(r["date"], r["ticker"], r.get("window")): r for r in filt_bear}
        dropped = {k: v for k, v in base_bear_keys.items() if k not in filt_bear_keys}

        if dropped:
            wins_d  = sum(1 for r in dropped.values() if r.get("pnl", 0) > 0)
            pnl_d   = sum(r.get("cap_pnl", 0.0) for r in dropped.values())
            wr_d    = wins_d / len(dropped) * 100
            print(f"\n  Filtered-out BEARISH trades: {len(dropped)}  WR {wr_d:.0f}%  P&L ${pnl_d:+,.2f}")
            print(f"  {'Date':<12}  {'Ticker':<6}  {'Win':<5}  {'P&L':>9}  {'Exit reason'}")
            print(f"  {'─'*55}")
            for (d, ticker, win), r in sorted(dropped.items()):
                w = "WIN" if r.get("pnl", 0) > 0 else "loss"
                print(f"  {str(d):<12}  {ticker:<6}  {w:<5}  ${r.get('cap_pnl',0):>+8,.2f}  {r.get('exit_reason','')}")


if __name__ == "__main__":
    main()
