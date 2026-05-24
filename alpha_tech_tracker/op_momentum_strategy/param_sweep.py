"""
Walk-forward parameter sweep: tune on a training period, validate on a test period.

Sweeps opening_start_time × opening_bars × stop_pct, runs each combo on both
periods, and prints a ranked table sorted by training P&L. Runs combos in
parallel using multiprocessing.

Usage:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/param_sweep.py \
    --train-start 2024-12-01 --train-end 2024-12-31 \
    --test-start  2025-01-01 --test-end  2025-01-31

Optional overrides:
  --top 2 --lookback 60 --feed sip --workers 25
  --times  09:30 09:35 09:40
  --bars   1 2 3 4 5
  --stops  0.2 0.3 0.4 0.5 0.6 0.8
  --bearish-reentry --bullish-reentry --reversal --ma-momentum-gate
  --min-hold-bars N
"""

import argparse
import io
import sys
from contextlib import redirect_stdout
from datetime import date
from itertools import product
from multiprocessing import Pool

import numpy as np
from alpaca.data.enums import DataFeed

sys.path.insert(0, '/Users/victorhuang/work/alpha_tech_tracker')
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import run_selector_backtest


def _stats(trade_rows: list) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    pnl = sum(r["pnl_pct"] for r in active)
    wr = sum(1 for r in active if r["pnl_pct"] > 0) / len(active) if active else 0.0
    return {"pnl": pnl, "wr": wr, "n": len(active)}


def _run_one(task: dict) -> dict:
    """Worker function — runs one combo for both train and test periods."""
    params = task["params"]
    shared = task["shared"]
    train_start = task["train_start"]
    train_end = task["train_end"]
    test_start = task["test_start"]
    test_end = task["test_end"]
    feed = DataFeed.SIP if shared["feed"] == "sip" else DataFeed.IEX

    windows = [{"label": "M1", "opening_start": params["time"], "opening_bars": params["bars"]}]

    def _call(start, end):
        with redirect_stdout(io.StringIO()):
            rows, _, _ = run_selector_backtest(
                n=shared["top"],
                tickers=DEFAULT_TICKERS,
                eval_start=start,
                eval_end=end,
                lookback_days=shared["lookback"],
                stop_pct=params["stop"],
                source="alpaca",
                feed=feed,
                windows=windows,
                enable_reversal=shared["reversal"],
                enable_bearish_reentry=shared["bearish_reentry"],
                enable_bullish_reentry=shared["bullish_reentry"],
                min_hold_bars=shared["min_hold_bars"],
                ma_momentum_gate=shared["ma_momentum_gate"],
            )
        return rows

    train_rows = _call(train_start, train_end)
    test_rows = _call(test_start, test_end)

    label = f"{params['time']}/{params['bars']}b/s{params['stop']:.2f}"
    return {
        **params,
        "label": label,
        "train": _stats(train_rows),
        "test": _stats(test_rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--top", type=int, default=2)
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--times", nargs="+", default=["09:30", "09:35", "09:40"])
    parser.add_argument("--bars", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--stops", nargs="+", type=float, default=[0.2, 0.3, 0.4, 0.5, 0.6, 0.8])
    parser.add_argument("--reversal", action="store_true", default=False)
    parser.add_argument("--bearish-reentry", action="store_true", default=False)
    parser.add_argument("--bullish-reentry", action="store_true", default=False)
    parser.add_argument("--ma-momentum-gate", action="store_true", default=False)
    parser.add_argument("--min-hold-bars", type=int, default=0)
    args = parser.parse_args()

    train_start = date.fromisoformat(args.train_start)
    train_end = date.fromisoformat(args.train_end)
    test_start = date.fromisoformat(args.test_start)
    test_end = date.fromisoformat(args.test_end)

    shared = dict(
        top=args.top,
        lookback=args.lookback,
        feed=args.feed,
        reversal=args.reversal,
        bearish_reentry=args.bearish_reentry,
        bullish_reentry=args.bullish_reentry,
        min_hold_bars=args.min_hold_bars,
        ma_momentum_gate=args.ma_momentum_gate,
    )

    combos = list(product(args.times, args.bars, args.stops))
    total = len(combos)
    workers = min(args.workers, total)

    print(f"Sweeping {total} combos  (times={args.times} bars={args.bars} stops={args.stops})")
    print(f"Train: {train_start} → {train_end}   Test: {test_start} → {test_end}")
    print(f"Workers: {workers}\n")

    tasks = [
        dict(
            params={"time": t, "bars": b, "stop": s},
            shared=shared,
            train_start=train_start, train_end=train_end,
            test_start=test_start, test_end=test_end,
        )
        for t, b, s in combos
    ]

    results = []
    completed = 0
    with Pool(processes=workers) as pool:
        for r in pool.imap_unordered(_run_one, tasks):
            completed += 1
            print(f"  [{completed:3d}/{total}] {r['label']:<22}"
                  f"  train {r['train']['pnl']:+6.2f}% ({r['train']['n']}t {r['train']['wr']:.0%}wr)"
                  f"  test {r['test']['pnl']:+6.2f}% ({r['test']['n']}t {r['test']['wr']:.0%}wr)",
                  flush=True)
            results.append(r)

    # Sort by train P&L
    results.sort(key=lambda x: x["train"]["pnl"], reverse=True)

    print("\n" + "="*85)
    print(f"RANKED BY TRAIN P&L")
    print(f"{'Config':<22} {'Train P&L':>10} {'Train WR':>9} {'Train N':>8}  "
          f"{'Test P&L':>9} {'Test WR':>8} {'Test N':>7}")
    print("-"*85)
    for r in results:
        print(f"{r['label']:<22} {r['train']['pnl']:>+9.2f}% {r['train']['wr']:>8.0%} "
              f"{r['train']['n']:>8}  "
              f"{r['test']['pnl']:>+8.2f}% {r['test']['wr']:>7.0%} {r['test']['n']:>7}")

    results_by_test = sorted(results, key=lambda x: x["test"]["pnl"], reverse=True)
    print("\n--- Top 15 by TEST P&L ---")
    print(f"{'Config':<22} {'Train P&L':>10} {'Train WR':>9}  {'Test P&L':>9} {'Test WR':>8}  {'Train rank':>10}")
    print("-"*75)
    for r in results_by_test[:15]:
        train_rank = results.index(r) + 1
        print(f"{r['label']:<22} {r['train']['pnl']:>+9.2f}% {r['train']['wr']:>8.0%}  "
              f"{r['test']['pnl']:>+8.2f}% {r['test']['wr']:>7.0%}  #{train_rank}")

    train_pnls = [r["train"]["pnl"] for r in results]
    test_pnls = [r["test"]["pnl"] for r in results]
    corr = float(np.corrcoef(train_pnls, test_pnls)[0, 1])
    print(f"\nTrain/test P&L correlation: {corr:+.3f}")
    if corr > 0.3:
        print("  -> Moderate carry-over: top train configs tend to perform better in test period")
    elif corr > 0:
        print("  -> Weak carry-over: slight positive trend but noisy")
    else:
        print("  -> No carry-over: Dec rank does NOT predict Jan performance for this config")


if __name__ == "__main__":
    main()
