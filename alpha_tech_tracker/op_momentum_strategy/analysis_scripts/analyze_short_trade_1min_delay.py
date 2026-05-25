"""
analyze_short_trade_1min_delay.py

For 2026 short trades (≤15 min), measures the P&L impact of a 1-min entry delay
AND a 1-min exit delay using 1-min SIP bar data from Alpaca.

Compares three scenarios:
  baseline  — original trade P&L as logged
  entry+1   — enter 1 min after original entry, exit at same original exit bar
  full+1    — enter 1 min after original entry, exit 1 min after original exit bar
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path

PYTHONPATH_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR   = PYTHONPATH_ROOT / "market_data" / "cache"
LOG_DIR     = PYTHONPATH_ROOT / "logs" / "replay_2026_M1_0930_1_A1_1030_6_stop10"
EDT_START   = date(2026, 3, 8)
MAX_DUR_MIN = 15

LOG_ROW_RE = re.compile(
    r'^\s+(\S+)\s+\[(\w+)\]\s+\S+.*?\s+([\d.]+)sh\s+'
    r'(\d{2}:\d{2})\s+(\d{2}:\d{2})\s+'
    r'\$([\d.]+)\s+\$([\d.]+)\s+'
    r'([+-]?\$[\d,.]+)\s+[+-]?[\d.]+%\s+(\S+)'
)


def et_offset(d):
    return -4 if d >= EDT_START else -5


def et_to_utc(trade_date_str, hhmm):
    d = date.fromisoformat(trade_date_str)
    off = et_offset(d)
    h, m = map(int, hhmm.split(':'))
    return datetime(d.year, d.month, d.day, h - off, m, tzinfo=timezone.utc)


def utc_to_et(ts, trade_date_str):
    off = et_offset(date.fromisoformat(trade_date_str))
    et = ts.hour + off
    return f"{et:02d}:{ts.minute:02d}"


# ── 1-min cache ───────────────────────────────────────────────────────────────

def _1min_cache_path(ticker, start, end):
    return CACHE_DIR / f"alpaca_sip_1min_{ticker}_{start}_{end}.json"


def _load_1min_cache(path):
    raw  = json.loads(path.read_text())
    cols = raw["columns"]
    oi, hi, li, ci = (cols.index("Open"), cols.index("High"),
                      cols.index("Low"),  cols.index("Close"))
    bars = {}
    for ts_str, row in zip(raw["index"], raw["data"]):
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        bars[ts] = {"open": row[oi], "high": row[hi], "low": row[li], "close": row[ci]}
    return bars


def fetch_1min_bars(tickers, start_str, end_str):
    """Fetch 1-min SIP bars from Alpaca for all tickers; cache to disk."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed

    key    = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    client = StockHistoricalDataClient(key, secret)

    result = {}
    for ticker in tickers:
        path = _1min_cache_path(ticker, start_str, end_str)
        if path.exists():
            print(f"  {ticker}: loaded from cache")
            result[ticker] = _load_1min_cache(path)
            continue

        print(f"  {ticker}: fetching from Alpaca...", end=" ", flush=True)
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Minute),
            start=datetime.fromisoformat(start_str),
            end=datetime.fromisoformat(end_str),
            feed=DataFeed.SIP,
            adjustment="raw",
        )
        bars_resp = client.get_stock_bars(req)
        df = bars_resp.df
        if ticker in df.index.get_level_values(0):
            df = df.loc[ticker]
        df.index = df.index.tz_convert("UTC")

        raw = {
            "columns": ["Open", "High", "Low", "Close", "Volume"],
            "index":   [ts.isoformat() for ts in df.index],
            "data":    [[row.open, row.high, row.low, row.close, row.volume]
                        for _, row in df.iterrows()],
        }
        path.write_text(json.dumps(raw))
        result[ticker] = _load_1min_cache(path)
        print(f"{len(df)} bars")

    return result


# ── Trade loader ──────────────────────────────────────────────────────────────

def load_short_trades(log_dir):
    trades = []
    for fname in sorted(os.listdir(log_dir)):
        if not re.match(r"\d{4}-\d{2}-\d{2}\.log$", fname):
            continue
        d_str = fname.replace(".log", "")
        with open(os.path.join(log_dir, fname)) as f:
            for line in f:
                m = LOG_ROW_RE.match(line)
                if not m:
                    continue
                ticker, signal, qty, entry_t, exit_t, entry_px, exit_px, pnl_str, reason = m.groups()
                dur = (datetime.strptime(exit_t, "%H:%M") -
                       datetime.strptime(entry_t, "%H:%M")).seconds // 60
                if dur <= MAX_DUR_MIN:
                    trades.append({
                        "date":       d_str,
                        "ticker":     ticker,
                        "signal":     signal.upper(),
                        "qty":        float(qty),
                        "entry_t":    entry_t,
                        "exit_t":     exit_t,
                        "entry_px":   float(entry_px),
                        "exit_px":    float(exit_px),
                        "orig_pnl":   float(pnl_str.replace("$", "").replace(",", "")),
                        "dur_min":    dur,
                        "exit_reason": reason,
                    })
    return trades


# ── Delay simulation ──────────────────────────────────────────────────────────

def bar_at(bars_dict, ts):
    """Return the first bar at or after ts (5-min resolution)."""
    for bt in sorted(bars_dict):
        if bt >= ts:
            return bt, bars_dict[bt]
    return None, None


def simulate_delay(t, bars_1min, entry_delay=1, exit_delay=1):
    """
    Simulate 1-min delay on entry and/or exit.
    entry_delay: minutes after original entry bar open to enter
    exit_delay:  minutes after original exit bar open to exit
    Returns dict with pnl_entry1, pnl_full1, and the actual px used.
    """
    d     = date.fromisoformat(t["date"])
    is_long = t["signal"] == "BULLISH"
    qty   = t["qty"]

    entry_utc = et_to_utc(t["date"], t["entry_t"])
    exit_utc  = et_to_utc(t["date"], t["exit_t"])

    # 1-min delay on entry: open of bar at entry_utc + 1 min
    entry1_utc = entry_utc + timedelta(minutes=entry_delay)
    exit1_utc  = exit_utc  + timedelta(minutes=exit_delay)

    entry1_bar_ts = None
    entry1_px     = None
    for ts in sorted(bars_1min):
        if ts >= entry1_utc and ts.date() == d:
            entry1_bar_ts = ts
            entry1_px = bars_1min[ts]["open"]
            break

    exit_orig_bar_ts = None
    exit_orig_px     = None
    for ts in sorted(bars_1min):
        if ts >= exit_utc and ts.date() == d:
            exit_orig_bar_ts = ts
            exit_orig_px = bars_1min[ts]["open"]
            break

    exit1_bar_ts = None
    exit1_px     = None
    for ts in sorted(bars_1min):
        if ts >= exit1_utc and ts.date() == d:
            exit1_bar_ts = ts
            exit1_px = bars_1min[ts]["open"]
            break

    results = {"entry1_px": entry1_px, "exit_orig_px": exit_orig_px, "exit1_px": exit1_px}

    # Scenario: entry+1, original exit time
    if entry1_px and exit_orig_px:
        pnl = (exit_orig_px - entry1_px) * qty if is_long else (entry1_px - exit_orig_px) * qty
        results["pnl_entry1"] = pnl
    else:
        results["pnl_entry1"] = None

    # Scenario: entry+1, exit+1
    if entry1_px and exit1_px:
        pnl = (exit1_px - entry1_px) * qty if is_long else (entry1_px - exit1_px) * qty
        results["pnl_full1"] = pnl
    else:
        results["pnl_full1"] = None

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log-dir",      default=str(LOG_DIR))
    parser.add_argument("--cache-dir",    default=str(CACHE_DIR))
    parser.add_argument("--start",        default="2026-01-01")
    parser.add_argument("--end",          default="2026-05-16")
    parser.add_argument("--entry-delay",  type=int, default=1,
                        help="Minutes after original entry bar to enter (default: 1)")
    parser.add_argument("--exit-delay",   type=int, default=1,
                        help="Minutes after original exit bar to exit (default: 1)")
    args = parser.parse_args()

    log_dir = args.log_dir

    print("Loading short trades from replay logs...")
    trades = load_short_trades(log_dir)
    print(f"  {len(trades)} short trades (orig dur ≤{MAX_DUR_MIN} min)")

    tickers = sorted({t["ticker"] for t in trades})
    print(f"\nFetching/loading 1-min SIP bars for {len(tickers)} tickers: {tickers}")
    bars_by_ticker = fetch_1min_bars(tickers, args.start, args.end)

    print("\nSimulating 1-min delay scenarios...")
    baseline_total = 0.0
    entry1_total   = 0.0
    full1_total    = 0.0
    skipped        = 0

    by_reason  = defaultdict(lambda: {"baseline": 0.0, "entry1": 0.0, "full1": 0.0, "n": 0})
    by_dur     = defaultdict(lambda: {"baseline": 0.0, "entry1": 0.0, "full1": 0.0, "n": 0})
    by_signal  = defaultdict(lambda: {"baseline": 0.0, "entry1": 0.0, "full1": 0.0, "n": 0})

    details = []
    for t in trades:
        if t["ticker"] not in bars_by_ticker:
            skipped += 1
            continue
        bars_1min = {ts: v for ts, v in bars_by_ticker[t["ticker"]].items()
                     if ts.date() == date.fromisoformat(t["date"])}
        if not bars_1min:
            skipped += 1
            continue

        r = simulate_delay(t, bars_1min, entry_delay=args.entry_delay, exit_delay=args.exit_delay)
        if r["pnl_entry1"] is None or r["pnl_full1"] is None:
            skipped += 1
            continue

        baseline_total += t["orig_pnl"]
        entry1_total   += r["pnl_entry1"]
        full1_total    += r["pnl_full1"]

        for bucket, key in [(by_reason, t["exit_reason"]),
                             (by_dur,    f"{(t['dur_min']//5)*5:02d}-{(t['dur_min']//5)*5+5:02d}min"),
                             (by_signal, t["signal"])]:
            bucket[key]["baseline"] += t["orig_pnl"]
            bucket[key]["entry1"]   += r["pnl_entry1"]
            bucket[key]["full1"]    += r["pnl_full1"]
            bucket[key]["n"]        += 1

        details.append({**t, **r})

    n = len(details)
    print(f"  Simulated: {n}  Skipped: {skipped}")

    def pct(val, ref):
        return f"{val/abs(ref)*100:+.1f}%" if ref else "n/a"

    print(f"\n{'='*62}")
    ed, xd = args.entry_delay, args.exit_delay
    print(f"  2026 Short Trade — {ed}-min Entry / {xd}-min Exit Delay Impact")
    print(f"{'='*62}")
    print(f"  Trades analysed  : {n}")
    print(f"  Baseline P&L     : ${baseline_total:>+9,.2f}  (as logged)")
    print(f"  Entry +{ed} min     : ${entry1_total:>+9,.2f}  ({pct(entry1_total - baseline_total, baseline_total)} vs baseline)")
    print(f"  Entry+{ed}/Exit+{xd}min : ${full1_total:>+9,.2f}  ({pct(full1_total - baseline_total, baseline_total)} vs baseline)")
    print(f"  Entry delay cost : ${entry1_total - baseline_total:>+9,.2f}")
    print(f"  Exit  delay cost : ${full1_total - entry1_total:>+9,.2f}")
    print(f"  Total delay cost : ${full1_total - baseline_total:>+9,.2f}")

    print(f"\n  ── By exit reason ──────────────────────────────────────")
    print(f"  {'Reason':<22}  {'n':>4}  {'baseline':>10}  {'entry+1':>10}  {'full+1':>10}  {'delta':>8}")
    for k in sorted(by_reason):
        v = by_reason[k]
        delta = v["full1"] - v["baseline"]
        print(f"  {k:<22}  {v['n']:>4}  {v['baseline']:>+10,.0f}  {v['entry1']:>+10,.0f}  {v['full1']:>+10,.0f}  {delta:>+8,.0f}")

    print(f"\n  ── By trade duration ───────────────────────────────────")
    print(f"  {'Duration':<12}  {'n':>4}  {'baseline':>10}  {'entry+1':>10}  {'full+1':>10}  {'delta':>8}")
    for k in sorted(by_dur):
        v = by_dur[k]
        delta = v["full1"] - v["baseline"]
        print(f"  {k:<12}  {v['n']:>4}  {v['baseline']:>+10,.0f}  {v['entry1']:>+10,.0f}  {v['full1']:>+10,.0f}  {delta:>+8,.0f}")

    print(f"\n  ── By signal direction ─────────────────────────────────")
    print(f"  {'Signal':<10}  {'n':>4}  {'baseline':>10}  {'entry+1':>10}  {'full+1':>10}  {'delta':>8}")
    for k in sorted(by_signal):
        v = by_signal[k]
        delta = v["full1"] - v["baseline"]
        print(f"  {k:<10}  {v['n']:>4}  {v['baseline']:>+10,.0f}  {v['entry1']:>+10,.0f}  {v['full1']:>+10,.0f}  {delta:>+8,.0f}")

    # per-trade delta distribution
    deltas = [r["pnl_full1"] - r["orig_pnl"] for r in details]
    improved = sum(1 for d in deltas if d > 0.50)
    worsened = sum(1 for d in deltas if d < -0.50)
    neutral  = n - improved - worsened
    print(f"\n  ── Per-trade delay delta distribution ──────────────────")
    print(f"  Improved (>+$0.50) : {improved:>4}  ({improved/n*100:.1f}%)")
    print(f"  Neutral  (±$0.50)  : {neutral:>4}  ({neutral/n*100:.1f}%)")
    print(f"  Worsened (<-$0.50) : {worsened:>4}  ({worsened/n*100:.1f}%)")
    print(f"  Worst single delta : ${min(deltas):>+,.2f}")
    print(f"  Best single delta  : ${max(deltas):>+,.2f}")
    print()


if __name__ == "__main__":
    main()
