"""QQQ MA20 regime-dependent config test on Q1 2025.

For each Q1 2025 trading day:
- If prior day's QQQ close > prior day's QQQ MA20 -> "trending" -> bars=7 stop=1.0
- Else -> "choppy" -> bars=3 stop=0.8

Groups consecutive same-regime days into segments, runs backtest per segment, sums P&L.

The +1 shift on regime indicator avoids lookahead: we use yesterday's close vs
yesterday's MA20 to decide today's config — that information is available before
today's 9:30 open.
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

PYTHONPATH = "/Users/victorhuang/work/alpha_tech_tracker"
QQQ_CACHE = f"{PYTHONPATH}/market_data/cache/alpaca_1day_QQQ_2020-09-29_2025-12-31.json"
MAX_WORKERS = 10

CONFIG_TRENDING = {"bars": 7, "stop": "1.0"}
CONFIG_CHOPPY = {"bars": 3, "stop": "0.8"}

Q1_START = "2025-01-01"
Q1_END = "2025-03-31"


def _load_qqq_with_regime() -> pd.DataFrame:
    with open(QQQ_CACHE) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw["data"], columns=raw["columns"], index=pd.to_datetime(raw["index"]))
    df["ma20"] = df["Close"].rolling(20).mean()
    df["regime"] = df["Close"].gt(df["ma20"]).map({True: "trending", False: "choppy"})
    df["regime_for_next_day"] = df["regime"].shift(1)
    return df


def _segments_for_q1(df: pd.DataFrame):
    q1 = df.loc[Q1_START:Q1_END].dropna(subset=["regime_for_next_day"]).copy()
    q1["group"] = (q1["regime_for_next_day"] != q1["regime_for_next_day"].shift()).cumsum()
    segments = []
    for _, sub in q1.groupby("group"):
        segments.append({
            "start": sub.index[0].strftime("%Y-%m-%d"),
            "end": sub.index[-1].strftime("%Y-%m-%d"),
            "regime": sub["regime_for_next_day"].iloc[0],
            "days": len(sub),
        })
    return segments


def _run_backtest(start: str, end: str, bars: int, stop: str):
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    cmd = [
        sys.executable,
        "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py",
        "--top", "2",
        "--window", "M1", "09:30", str(bars),
        "--bearish-reentry", "--bullish-reentry", "--reversal",
        "--stop-pct", stop,
        "--feed", "sip",
        "--min-hold-bars", "1",
        "--start", start, "--end", end,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = result.stdout
    m = re.search(r"TOTAL\s+\d+\s+\d+W/\d+L\s+([+-]?\$[\d,]+\.\d+)", out)
    if m:
        return float(m.group(1).replace("$", "").replace(",", ""))
    return None


def _run_segment(seg):
    cfg = CONFIG_TRENDING if seg["regime"] == "trending" else CONFIG_CHOPPY
    pnl = _run_backtest(seg["start"], seg["end"], cfg["bars"], cfg["stop"])
    return {**seg, "config": f"bars={cfg['bars']} stop={cfg['stop']}", "pnl": pnl}


def main():
    df = _load_qqq_with_regime()
    segments = _segments_for_q1(df)

    print(f"Q1 2025 regime segments ({len(segments)} total):")
    for s in segments:
        print(f"  {s['start']} → {s['end']}  ({s['days']:>2}d)  {s['regime']}")

    print(f"\nRunning {len(segments)} backtests with up to {MAX_WORKERS} workers...\n")
    results = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_run_segment, s): s for s in segments}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            pnl_s = f"${r['pnl']:+,.0f}" if r["pnl"] is not None else "ERR"
            print(f"  {r['start']} → {r['end']}  {r['regime']:<9} {r['config']:<22} {pnl_s}", flush=True)

    results.sort(key=lambda r: r["start"])
    total = sum(r["pnl"] for r in results if r["pnl"] is not None)
    trend_pnl = sum(r["pnl"] for r in results if r["regime"] == "trending" and r["pnl"] is not None)
    chop_pnl = sum(r["pnl"] for r in results if r["regime"] == "choppy" and r["pnl"] is not None)
    n_trend = sum(r["days"] for r in results if r["regime"] == "trending")
    n_chop = sum(r["days"] for r in results if r["regime"] == "choppy")

    print("\n" + "=" * 80)
    print("QQQ MA20 REGIME-SWITCHING — Q1 2025 SUMMARY")
    print("=" * 80)
    print(f"  Trending days: {n_trend:>3}  P&L: ${trend_pnl:+,.0f}  (config: bars=7 stop=1.0)")
    print(f"  Choppy days:   {n_chop:>3}  P&L: ${chop_pnl:+,.0f}  (config: bars=3 stop=0.8)")
    print(f"  TOTAL Q1 2025: ${total:+,.0f}")
    print("=" * 80)
    print("\nFor comparison:")
    print(f"  Walk-fwd (6mo, drifts to bars=7-10): +$211")
    print(f"  bars=3 stop=0.8 (forced):            -$679")
    print(f"  Q1 oracle (bars=2 stop=0.3 monthly): +$1,869")


if __name__ == "__main__":
    main()
