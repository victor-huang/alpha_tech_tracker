"""Drive fade variants: exits x stop cushions x filters known at 9:35, chosen on calibration, checked on test.

Every session's first 5-min bar gives a drive fade (short after green, long after red; see
`wave_risk_reward.py --drive-fade`). Trades are simulated with the backtest's TradeSimulator for each
exit and stop cushion, and tagged with conditions known at the signal: 5-min MA200 stretch (in average
bar ranges, measured toward the fade), daily trend (MA50, MA200, 20-day return from closes before the
day), first-bar size and the gap from the previous close. Variants with at least `--min-trades`
calibration trades are ranked on calibration; their test result is printed unchanged. Finding 19 in
the ticker-tuning doc: none held up (Sep 2025 - Oct 2026, 21 tickers).

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_drive_fade_variants \\
    --tickers AMD META MDB FN --first 2025-09-02 --calibration-end 2026-07-02 --last 2026-10-06
"""
import argparse
import itertools
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from functools import partial

import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import drive_fade_risk_reward, drive_fade_signal
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import TradeSimulator, apply_costs
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import _load_bars

EXITS = ("target", "eod", "target-trail", "giveback")
BUFFERS = (0.1, 0.5, 1.0)


def ticker_trades(ticker, first, last, cost_bps=5.0):
    """Every first-bar fade of `ticker` between `first` and `last`, per stop cushion and exit, with its conditions."""
    bars = _load_bars(ticker, first, last, DataFeed.SIP)
    bar_range = (bars["high"] - bars["low"]).rolling(78, min_periods=20).mean().shift(1)
    daily = bars.groupby(bars.index.date).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                              close=("close", "last"))
    closes = daily["close"]
    ma50, ma200 = closes.rolling(50).mean(), closes.rolling(200).mean()
    adr = ((daily["high"] - daily["low"]) / daily["close"]).rolling(20).mean()
    sim = TradeSimulator(bars)
    days = list(daily.index)
    rows = []
    for i, day in enumerate(days):
        if day < first or day > last or i < 200:
            continue
        stamp = bars.index[bars.index.date == day][0]
        bar = {k: float(bars.at[stamp, k]) for k in ("open", "high", "low", "close")}
        prev_close, ma200_5m, avg_range = closes.iloc[i - 1], bars.at[stamp, "ma_200"], bar_range.at[stamp]
        features = {
            "ticker": ticker, "day": day,
            "ma200_stretch": (bar["close"] - ma200_5m) / avg_range if avg_range and not np.isnan(ma200_5m) else np.nan,
            "above_ma50": prev_close > ma50.iloc[i - 1], "above_ma200": prev_close > ma200.iloc[i - 1],
            "ret20": prev_close / closes.iloc[i - 21] - 1,
            "first_bar_ratio": (bar["high"] - bar["low"]) / avg_range if avg_range else np.nan,
            "gap_adr": (bar["open"] / prev_close - 1) / adr.iloc[i - 1] if adr.iloc[i - 1] else np.nan,
        }
        for buffer in BUFFERS:
            fade = drive_fade_signal(bar, "both", buffer)
            if not fade:
                continue
            name, stop, target = fade
            rr = drive_fade_risk_reward("up" if name == "drive_fade_long" else "down", bar["close"], stop, target)
            if not rr:
                continue
            signal = {"time": stamp, "signal": name, "gap": False, "box_mode": "opening", "reverses": None,
                      "regime": "", "risk_reward": rr}
            for exit_mode in EXITS:
                trade = sim.run(signal, exit_mode)
                if trade:
                    rows.append({**features, "side": 1 if name == "drive_fade_long" else -1, "buffer": buffer,
                                 "exit": exit_mode, "net_pct": apply_costs(trade, cost_bps)["net_pct"]})
    return rows


FILTERS = {
    "none": lambda t: np.ones(len(t), bool),
    **{f"MA200 stretch >= {k}": (lambda k: lambda t: (t.side * -t.ma200_stretch) >= k)(k) for k in (5, 10, 20)},
    "correction (below MA50, above MA200)": lambda t: ~t.above_ma50 & t.above_ma200,
    "correction, short only": lambda t: ~t.above_ma50 & t.above_ma200 & (t.side == -1),
    "downtrend (below MA200), short only": lambda t: ~t.above_ma200 & (t.side == -1),
    "with daily trend (short below MA50, long above)": lambda t: ((t.side == -1) & ~t.above_ma50) | ((t.side == 1) & t.above_ma50),
    "against daily trend": lambda t: ((t.side == -1) & t.above_ma50) | ((t.side == 1) & ~t.above_ma50),
    "20-day return < 0, short only": lambda t: (t.ret20 < 0) & (t.side == -1),
    **{f"first bar >= {k}x avg bar": (lambda k: lambda t: t.first_bar_ratio >= k)(k) for k in (1.5, 2.0, 3.0)},
    **{f"fade a gap >= {k} ADR": (lambda k: lambda t: (t.side * -t.gap_adr) >= k)(k) for k in (0.5, 1.0)},
    "correction + MA200 stretch >= 10": lambda t: ~t.above_ma50 & t.above_ma200 & ((t.side * -t.ma200_stretch) >= 10),
    "with daily trend + MA200 stretch >= 10": lambda t: (((t.side == -1) & ~t.above_ma50) | ((t.side == 1) & t.above_ma50))
                                                       & ((t.side * -t.ma200_stretch) >= 10),
}


def evaluate(trades, calibration_end):
    """Per filter x stop x exit: trades, total %, average % and tickers positive, per period."""
    trades = trades.assign(period=np.where(trades.day <= calibration_end, "calibration", "test"))
    out = []
    for (name, flt), buffer, exit_mode in itertools.product(FILTERS.items(), BUFFERS, EXITS):
        sub = trades[(trades.buffer == buffer) & (trades.exit == exit_mode)]
        sub = sub[np.asarray(flt(sub), dtype=bool)]
        row = {"filter": name, "stop": buffer, "exit": exit_mode}
        for period in ("calibration", "test"):
            p = sub[sub.period == period]
            per = p.groupby("ticker").net_pct.sum()
            row[f"{period}_n"] = len(p)
            row[f"{period}_total%"] = p.net_pct.sum()
            row[f"{period}_avg%"] = p.net_pct.mean() if len(p) else np.nan
            row[f"{period}_tickers+"] = f"{(per > 0).sum()}/{len(per)}"
        out.append(row)
    return pd.DataFrame(out)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--first", type=date.fromisoformat, required=True, help="First session (calibration start)")
    parser.add_argument("--calibration-end", type=date.fromisoformat, required=True)
    parser.add_argument("--last", type=date.fromisoformat, required=True, help="Last session (test end)")
    parser.add_argument("--min-trades", type=int, default=150, help="Calibration trades a variant needs to be ranked")
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--csv-out", help="Write every simulated trade to this CSV")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    work = partial(ticker_trades, first=args.first, last=args.last, cost_bps=args.cost_bps)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        trades = pd.DataFrame([r for rows in pool.map(work, args.tickers) for r in rows])
    table = evaluate(trades, args.calibration_end)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 400)
    fmt = lambda v: f"{v:+.3f}" if isinstance(v, float) and abs(v) < 1 else (f"{v:+,.1f}" if isinstance(v, float) else v)
    print(f"{len(trades)} simulated fade trades ({trades.ticker.nunique()} tickers); calibration {args.first}.."
          f"{args.calibration_end}, test after, to {args.last}\n")
    print("=== Baseline (no filter)")
    print(table[table["filter"] == "none"].to_string(index=False, float_format=fmt))
    eligible = table[table["calibration_n"] >= args.min_trades].sort_values("calibration_total%", ascending=False)
    print(f"\n=== Top 15 by calibration total (>= {args.min_trades} calibration trades), with their test result")
    print(eligible.head(15).to_string(index=False, float_format=fmt))
    positive = eligible[eligible["calibration_total%"] > 0]
    print(f"\n{len(positive)} of {len(eligible)} variants positive in calibration; "
          f"{(positive['test_total%'] > 0).sum()} of them positive in test")
    print("\n=== Best variant per filter (by calibration total, >= 50 calibration trades)")
    best = table[table["calibration_n"] >= 50].sort_values("calibration_total%", ascending=False).groupby("filter").head(1)
    print(best.to_string(index=False, float_format=fmt))
    if args.csv_out:
        trades.to_csv(args.csv_out, index=False)
        print(f"\ntrades written to {args.csv_out}")


if __name__ == "__main__":
    main()
