"""
analyze_short_trade_be_hold.py

For 2026 short-duration trades (≤15 min), simulates holding 5–10 extra minutes
and exiting at break-even (original entry price) if it is touched.

Three scenarios per trade:
  baseline   — original P&L as logged
  hold_5     — if BE touched within 5 min of original exit, exit at entry_px;
               else exit at 1-min bar close 5 min after original exit
  hold_10    — same as hold_5 but 10-min window

Break-even definition:
  BEARISH short: any 1-min bar LOW  ≤ entry_px within the hold window
  BULLISH long:  any 1-min bar HIGH ≥ entry_px within the hold window

Feasibility:
  Reports hit-rate (% of trades where BE is reachable), max adverse excursion
  at hold end for misses, and net P&L impact vs baseline.
"""

import argparse
import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from collections import defaultdict
from pathlib import Path

PYTHONPATH_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR   = PYTHONPATH_ROOT / "market_data" / "cache"
LOG_DIR     = PYTHONPATH_ROOT / "logs" / "replay_2026_M1_0930_1_A1_1030_6_stop10"
EDT_START   = date(2026, 3, 8)
MAX_DUR_MIN = 15
MARKET_CLOSE_ET = time(16, 0)

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


def utc_to_et_hhmm(ts, trade_date_str):
    off = et_offset(date.fromisoformat(trade_date_str))
    return f"{ts.hour + off:02d}:{ts.minute:02d}"


# ── 1-min cache ───────────────────────────────────────────────────────────────

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


def _1min_cache_path(ticker, start, end):
    return CACHE_DIR / f"alpaca_sip_1min_{ticker}_{start}_{end}.json"


def fetch_1min_bars(tickers, start_str, end_str):
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


# ── Break-even hold simulation ────────────────────────────────────────────────

def _et_time(hhmm):
    h, m = map(int, hhmm.split(':'))
    return time(h, m)


def simulate_be_hold(t, bars_1min, max_hold_min=10):
    """
    For a trade t, check whether break-even is reachable within max_hold_min
    minutes after original exit using 1-min bars.

    Returns a dict with:
      be_min         — minutes after original exit when BE is first hit (None = not hit)
      be_hit_5       — True if BE hit within 5 min
      be_hit_10      — True if BE hit within 10 min (or max_hold_min)
      hold_5_pnl     — P&L if we hold 5 min: exit at entry_px if BE hit, else bar close
      hold_10_pnl    — P&L if we hold max_hold_min: same logic
      hold_5_px      — exit price used in hold_5 scenario
      hold_10_px     — exit price used in hold_10 scenario
      max_adverse_5  — worst unrealized loss during 0–5 min hold (for shorts: highest high)
      max_adverse_10 — worst unrealized loss during 0–max_hold_min hold
    """
    is_short = t["signal"] == "BEARISH"
    entry_px = t["entry_px"]
    qty      = t["qty"]
    d        = date.fromisoformat(t["date"])

    exit_utc = et_to_utc(t["date"], t["exit_t"])

    # market close in UTC
    off = et_offset(d)
    market_close_utc = datetime(d.year, d.month, d.day,
                                16 - off, 0, tzinfo=timezone.utc)

    # collect 1-min bars from exit_t to exit_t + max_hold_min (or market close)
    hold_bars = []
    for delta_min in range(1, max_hold_min + 1):
        bar_ts = exit_utc + timedelta(minutes=delta_min)
        if bar_ts > market_close_utc:
            break
        if bar_ts in bars_1min:
            hold_bars.append((delta_min, bars_1min[bar_ts]))

    be_min     = None
    max_adv_5  = 0.0  # worst excursion (positive = adverse, in $ per share)
    max_adv_10 = 0.0

    for delta_min, bar in hold_bars:
        # check break-even touch
        if be_min is None:
            if is_short and bar["low"] <= entry_px:
                be_min = delta_min
            elif not is_short and bar["high"] >= entry_px:
                be_min = delta_min

        # track max adverse excursion (per-share, positive = bad for the trade)
        if is_short:
            adverse = bar["high"] - entry_px  # short: price going UP is adverse
        else:
            adverse = entry_px - bar["low"]   # long: price going DOWN is adverse

        if delta_min <= 5:
            max_adv_5  = max(max_adv_5,  adverse)
        max_adv_10 = max(max_adv_10, adverse)

    be_hit_5  = be_min is not None and be_min <= 5
    be_hit_10 = be_min is not None and be_min <= max_hold_min

    def _pnl_at(hold_mins, be_hit):
        if be_hit:
            exit_px = entry_px
        else:
            # find the closest bar at or after exit_utc + hold_mins
            target = exit_utc + timedelta(minutes=hold_mins)
            exit_px = None
            for ts in sorted(bars_1min):
                if ts >= target and ts.date() == d:
                    exit_px = bars_1min[ts]["close"]
                    break
            if exit_px is None and hold_bars:
                exit_px = hold_bars[-1][1]["close"]
            if exit_px is None:
                return None, None

        if is_short:
            pnl = (entry_px - exit_px) * qty
        else:
            pnl = (exit_px - entry_px) * qty
        return pnl, exit_px

    hold_5_pnl, hold_5_px   = _pnl_at(5,           be_hit_5)
    hold_10_pnl, hold_10_px = _pnl_at(max_hold_min, be_hit_10)

    return {
        "be_min":         be_min,
        "be_hit_5":       be_hit_5,
        "be_hit_10":      be_hit_10,
        "hold_5_pnl":     hold_5_pnl,
        "hold_10_pnl":    hold_10_pnl,
        "hold_5_px":      hold_5_px,
        "hold_10_px":     hold_10_px,
        "max_adverse_5":  max_adv_5,
        "max_adverse_10": max_adv_10,
    }


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _bucket(dur):
    b = (dur // 5) * 5
    return f"{b:02d}-{b+5:02d}min"


def _summarize(rows, label_key, label_fn=None):
    buckets = defaultdict(lambda: {
        "n": 0, "base": 0.0, "h5": 0.0, "h10": 0.0,
        "be5": 0, "be10": 0, "skipped": 0,
    })
    for r in rows:
        k = label_fn(r) if label_fn else r[label_key]
        b = buckets[k]
        if r["hold_5_pnl"] is None:
            b["skipped"] += 1
            continue
        b["n"]    += 1
        b["base"] += r["orig_pnl"]
        b["h5"]   += r["hold_5_pnl"]
        b["h10"]  += r["hold_10_pnl"]
        if r["be_hit_5"]:
            b["be5"] += 1
        if r["be_hit_10"]:
            b["be10"] += 1
    return buckets


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log-dir",     default=str(LOG_DIR))
    parser.add_argument("--cache-dir",   default=str(CACHE_DIR))
    parser.add_argument("--start",       default="2026-01-01")
    parser.add_argument("--end",         default="2026-05-16")
    parser.add_argument("--max-hold",    type=int, default=10,
                        help="Max hold extension in minutes (default 10)")
    parser.add_argument("--losers-only", action="store_true",
                        help="Only analyse losing trades (orig_pnl < 0)")
    args = parser.parse_args()

    print("Loading short trades from replay logs...")
    trades = load_short_trades(args.log_dir)
    print(f"  {len(trades)} trades total (orig dur ≤{MAX_DUR_MIN} min)")

    if args.losers_only:
        trades = [t for t in trades if t["orig_pnl"] < 0]
        print(f"  {len(trades)} losing trades")

    tickers = sorted({t["ticker"] for t in trades})
    print(f"\nLoading 1-min SIP bars for {len(tickers)} tickers...")
    bars_by_ticker = fetch_1min_bars(tickers, args.start, args.end)

    print("\nSimulating break-even hold scenarios...")
    results = []
    skipped = 0

    for t in trades:
        if t["ticker"] not in bars_by_ticker:
            skipped += 1
            continue
        bars_day = {ts: v for ts, v in bars_by_ticker[t["ticker"]].items()
                    if ts.date() == date.fromisoformat(t["date"])}
        if not bars_day:
            skipped += 1
            continue

        r = simulate_be_hold(t, bars_day, max_hold_min=args.max_hold)
        results.append({**t, **r})

    n = len(results)
    print(f"  Simulated: {n}  Skipped: {skipped}")

    # ── Totals ────────────────────────────────────────────────────────────────
    valid = [r for r in results if r["hold_5_pnl"] is not None]
    n_v   = len(valid)

    base_total = sum(r["orig_pnl"]    for r in valid)
    h5_total   = sum(r["hold_5_pnl"]  for r in valid)
    h10_total  = sum(r["hold_10_pnl"] for r in valid)
    be5_n      = sum(1 for r in valid if r["be_hit_5"])
    be10_n     = sum(1 for r in valid if r["be_hit_10"])

    losers     = [r for r in valid if r["orig_pnl"] < 0]
    n_l        = len(losers)
    l_base     = sum(r["orig_pnl"]    for r in losers)
    l_h5       = sum(r["hold_5_pnl"]  for r in losers)
    l_h10      = sum(r["hold_10_pnl"] for r in losers)
    l_be5_n    = sum(1 for r in losers if r["be_hit_5"])
    l_be10_n   = sum(1 for r in losers if r["be_hit_10"])

    def pct(a, b): return f"{a/b*100:.1f}%" if b else "n/a"
    def sgn(v):    return f"${v:>+9,.2f}"

    print(f"\n{'='*68}")
    print(f"  2026 Short Trades — Break-Even Hold Analysis ({args.max_hold}-min max)")
    print(f"{'='*68}")
    print(f"  Trades analysed : {n_v}")
    print(f"  Losers          : {n_l}  ({pct(n_l, n_v)} of total)")

    print(f"\n  ── ALL trades (winners + losers) ──────────────────────────────")
    print(f"  Baseline P&L    : {sgn(base_total)}")
    print(f"  Hold +5min P&L  : {sgn(h5_total)}  (Δ {sgn(h5_total  - base_total)})")
    print(f"  Hold+10min P&L  : {sgn(h10_total)}  (Δ {sgn(h10_total - base_total)})")
    print(f"  BE hit ≤5 min   : {be5_n:>4}  ({pct(be5_n, n_v)})")
    print(f"  BE hit ≤{args.max_hold} min  : {be10_n:>4}  ({pct(be10_n, n_v)})")

    print(f"\n  ── LOSERS only ─────────────────────────────────────────────────")
    print(f"  Baseline P&L    : {sgn(l_base)}")
    print(f"  Hold +5min P&L  : {sgn(l_h5)}  (Δ {sgn(l_h5  - l_base)})")
    print(f"  Hold+10min P&L  : {sgn(l_h10)}  (Δ {sgn(l_h10 - l_base)})")
    print(f"  BE hit ≤5 min   : {l_be5_n:>4}  ({pct(l_be5_n, n_l)})  → P&L ≈ $0 (covered at entry)")
    print(f"  BE hit ≤{args.max_hold} min  : {l_be10_n:>4}  ({pct(l_be10_n, n_l)})")
    not_be10 = n_l - l_be10_n
    l_miss   = [r for r in losers if not r["be_hit_10"] and r["hold_10_pnl"] is not None]
    if l_miss:
        miss_base  = sum(r["orig_pnl"]    for r in l_miss)
        miss_h10   = sum(r["hold_10_pnl"] for r in l_miss)
        avg_adv    = sum(r["max_adverse_10"] for r in l_miss) / len(l_miss)
        print(f"  BE NOT hit ({not_be10}) :")
        print(f"    baseline P&L    : {sgn(miss_base)}")
        print(f"    hold-{args.max_hold} forced P&L: {sgn(miss_h10)}  (Δ {sgn(miss_h10 - miss_base)})")
        print(f"    avg max adverse : ${avg_adv:>+.4f}/sh  (per-share worst excursion during hold)")

    # ── Distribution of BE timing ─────────────────────────────────────────────
    print(f"\n  ── BE hit timing (losers only) ─────────────────────────────────")
    print(f"  {'Minute':<10}  {'#':>5}  {'Cumulative':>12}  {'Cum %':>8}")
    cumulative = 0
    timing = defaultdict(int)
    for r in losers:
        if r["be_min"] is not None:
            timing[r["be_min"]] += 1
    for m in range(1, args.max_hold + 1):
        cumulative += timing[m]
        print(f"  +{m:<9}  {timing[m]:>5}  {cumulative:>12}  {pct(cumulative, n_l):>8}")

    # ── By exit reason ────────────────────────────────────────────────────────
    print(f"\n  ── By exit reason (losers only) ────────────────────────────────")
    print(f"  {'Reason':<22}  {'n':>4}  {'BE≤5':>5}  {'BE≤10':>6}  {'BaseP&L':>9}  {'Hold5Δ':>9}  {'Hold10Δ':>9}")
    by_reason = _summarize(losers, "exit_reason")
    for k in sorted(by_reason):
        v = by_reason[k]
        if v["n"] == 0:
            continue
        print(f"  {k:<22}  {v['n']:>4}  "
              f"{pct(v['be5'], v['n']):>5}  {pct(v['be10'], v['n']):>6}  "
              f"{v['base']:>+9,.0f}  {v['h5']-v['base']:>+9,.0f}  {v['h10']-v['base']:>+9,.0f}")

    # ── By duration bucket ────────────────────────────────────────────────────
    print(f"\n  ── By trade duration (losers only) ─────────────────────────────")
    print(f"  {'Duration':<12}  {'n':>4}  {'BE≤5':>5}  {'BE≤10':>6}  {'BaseP&L':>9}  {'Hold5Δ':>9}  {'Hold10Δ':>9}")
    by_dur = _summarize(losers, "dur_min", label_fn=lambda r: _bucket(r["dur_min"]))
    for k in sorted(by_dur):
        v = by_dur[k]
        if v["n"] == 0:
            continue
        print(f"  {k:<12}  {v['n']:>4}  "
              f"{pct(v['be5'], v['n']):>5}  {pct(v['be10'], v['n']):>6}  "
              f"{v['base']:>+9,.0f}  {v['h5']-v['base']:>+9,.0f}  {v['h10']-v['base']:>+9,.0f}")

    # ── By signal direction ───────────────────────────────────────────────────
    print(f"\n  ── By signal direction (losers only) ───────────────────────────")
    print(f"  {'Signal':<10}  {'n':>4}  {'BE≤5':>5}  {'BE≤10':>6}  {'BaseP&L':>9}  {'Hold5Δ':>9}  {'Hold10Δ':>9}")
    by_sig = _summarize(losers, "signal")
    for k in sorted(by_sig):
        v = by_sig[k]
        if v["n"] == 0:
            continue
        print(f"  {k:<10}  {v['n']:>4}  "
              f"{pct(v['be5'], v['n']):>5}  {pct(v['be10'], v['n']):>6}  "
              f"{v['base']:>+9,.0f}  {v['h5']-v['base']:>+9,.0f}  {v['h10']-v['base']:>+9,.0f}")

    # ── P&L delta distribution ────────────────────────────────────────────────
    deltas_10 = [r["hold_10_pnl"] - r["orig_pnl"] for r in losers
                 if r["hold_10_pnl"] is not None]
    if deltas_10:
        improved = sum(1 for d in deltas_10 if d > 0.50)
        neutral  = sum(1 for d in deltas_10 if abs(d) <= 0.50)
        worsened = sum(1 for d in deltas_10 if d < -0.50)
        print(f"\n  ── Per-trade hold-{args.max_hold} Δ vs baseline (losers only) ──────────")
        print(f"  Improved (>+$0.50) : {improved:>4}  ({pct(improved, n_l)})")
        print(f"  Neutral  (±$0.50)  : {neutral:>4}  ({pct(neutral, n_l)})")
        print(f"  Worsened (<-$0.50) : {worsened:>4}  ({pct(worsened, n_l)})")
        print(f"  Best Δ             : ${max(deltas_10):>+,.2f}")
        print(f"  Worst Δ            : ${min(deltas_10):>+,.2f}")
    print()


if __name__ == "__main__":
    main()
