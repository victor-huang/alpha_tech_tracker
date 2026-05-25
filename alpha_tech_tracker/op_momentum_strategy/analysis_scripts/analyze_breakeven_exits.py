"""
For each short-duration (<=15 min) losing trade in live fills, check whether
the price returned to the entry fill price within [entry_time, exit_time + 5 min]
using 5-min bar data.

Fill times are Eastern Time (UTC-4 in April). Bar timestamps are UTC.
"""

import os
import json
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone


FILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "fills")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "market_data", "cache")

SHORT_DURATION_MINS = 15
EXTEND_MINS = 5
ET_OFFSET_HOURS = 4  # April 2026: EDT = UTC-4


# ---------- helpers ----------------------------------------------------------

def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get(row, *candidates):
    for c in candidates:
        v = row.get(c, "").strip()
        if v:
            return v
    return ""


def _parse_fill_time(t_str, date_str):
    """Parse HH:MM:SS fill time + date string into UTC datetime."""
    if not t_str:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(f"{date_str} {t_str.strip()}", f"%Y-%m-%d {fmt}")
            # fill times are ET (UTC-4); convert to UTC
            return t + timedelta(hours=ET_OFFSET_HOURS)
        except ValueError:
            continue
    return None


def _parse_bar_ts(ts_str):
    """Parse bar index string '2026-04-14T13:30:00.000Z' into UTC datetime."""
    ts_str = ts_str.replace(".000Z", "+00:00").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str).replace(tzinfo=None)
    except ValueError:
        return None


# ---------- load fills -------------------------------------------------------

def load_short_losing_trades():
    trades = []
    for date_dir in sorted(os.listdir(FILLS_DIR)):
        date_path = os.path.join(FILLS_DIR, date_dir)
        if not os.path.isdir(date_path):
            continue
        fname = f"stocks_fills_{date_dir}.csv"
        fpath = os.path.join(date_path, fname)
        if not os.path.exists(fpath):
            continue

        rows = []
        with open(fpath, newline="") as f:
            for row in csv.DictReader(f):
                row["_date"] = date_dir
                rows.append(row)

        by_ticker = defaultdict(list)
        for row in rows:
            by_ticker[row.get("ticker", "").strip()].append(row)

        for ticker, group in by_ticker.items():
            entries = [r for r in group if r.get("side", "").upper() == "ENTRY"]
            exits   = [r for r in group if r.get("side", "").upper() == "EXIT"]

            for entry, exit_ in zip(entries, exits):
                t_in_str  = _get(entry, "fill_time")
                t_out_str = _get(exit_, "fill_time")
                t_in_utc  = _parse_fill_time(t_in_str, date_dir)
                t_out_utc = _parse_fill_time(t_out_str, date_dir)
                if t_in_utc is None or t_out_utc is None:
                    continue

                duration = (t_out_utc - t_in_utc).total_seconds() / 60
                if not (0 < duration <= SHORT_DURATION_MINS):
                    continue

                entry_price = _safe_float(_get(entry, "fill_price"))
                exit_price  = _safe_float(_get(exit_, "fill_price"))
                if entry_price is None or exit_price is None:
                    continue

                action = _get(entry, "trade_action").upper()
                is_short = "SHORT" in action
                if is_short:
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                else:
                    pnl_pct = (exit_price - entry_price) / entry_price * 100

                if pnl_pct >= 0:
                    continue  # only care about losing trades

                trades.append({
                    "date": date_dir,
                    "ticker": ticker,
                    "t_in_utc": t_in_utc,
                    "t_out_utc": t_out_utc,
                    "duration_mins": duration,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "is_short": is_short,
                    "action": action,
                })

    return trades


# ---------- load bar data ----------------------------------------------------

_bar_cache = {}


def _load_bars(ticker):
    """Return list of (utc_datetime, open, high, low, close) sorted by time."""
    if ticker in _bar_cache:
        return _bar_cache[ticker]

    # prefer the widest file ending >= 2026-05-01
    candidates = [
        f for f in os.listdir(CACHE_DIR)
        if f.startswith(f"alpaca_sip_5min_{ticker}_") and f.endswith(".json")
    ]

    def end_date(fname):
        parts = fname.replace(".json", "").split("_")
        return parts[-1]

    candidates = [f for f in candidates if end_date(f) >= "2026-04-30"]
    if not candidates:
        _bar_cache[ticker] = []
        return []

    chosen = sorted(candidates, key=end_date)[-1]
    fpath = os.path.join(CACHE_DIR, chosen)

    with open(fpath) as f:
        d = json.load(f)

    cols = d["columns"]  # ['Open', 'High', 'Low', 'Close', 'Volume', ...]
    idx_o = cols.index("Open")
    idx_h = cols.index("High")
    idx_l = cols.index("Low")
    idx_c = cols.index("Close")

    bars = []
    for ts_str, row in zip(d["index"], d["data"]):
        dt = _parse_bar_ts(ts_str)
        if dt is None:
            continue
        bars.append((dt, row[idx_o], row[idx_h], row[idx_l], row[idx_c]))

    bars.sort(key=lambda x: x[0])
    _bar_cache[ticker] = bars
    return bars


def bars_in_window(ticker, start_utc, end_utc):
    """Return bars that START at or after entry fill time up to window end.

    Only forward-looking bars are included: a bar starting before the entry
    fill is excluded because its high may reflect pre-entry prices.
    """
    all_bars = _load_bars(ticker)
    return [b for b in all_bars if start_utc <= b[0] <= end_utc]


# ---------- check break-even -------------------------------------------------

def check_breakeven(trade):
    """
    For a losing trade, check whether price touched entry_price in the window
    [entry_time, exit_time + EXTEND_MINS].

    Returns dict with:
      - had_opportunity: bool
      - first_be_bar_dt: UTC datetime of first bar where BE was achievable (or None)
      - mins_to_be: minutes from entry to that bar (or None)
      - bars_checked: number of bars inspected
    """
    ticker = trade["ticker"]
    entry_price = trade["entry_price"]
    is_short = trade["is_short"]
    window_end = trade["t_out_utc"] + timedelta(minutes=EXTEND_MINS)

    window_bars = bars_in_window(ticker, trade["t_in_utc"], window_end)

    first_be = None
    for bar in window_bars:
        bar_dt, o, h, l, c = bar
        if is_short:
            # short: break-even if low <= entry_price (could buy back at entry)
            if l <= entry_price:
                first_be = bar_dt
                break
        else:
            # long: break-even if high >= entry_price (could sell at entry)
            if h >= entry_price:
                first_be = bar_dt
                break

    mins_to_be = None
    if first_be is not None:
        mins_to_be = (first_be - trade["t_in_utc"]).total_seconds() / 60

    return {
        "had_opportunity": first_be is not None,
        "first_be_bar_dt": first_be,
        "mins_to_be": mins_to_be,
        "bars_checked": len(window_bars),
    }


# ---------- main -------------------------------------------------------------

def main():
    trades = load_short_losing_trades()
    print(f"Short losing trades to analyze: {len(trades)}")

    results = []
    no_data = []
    for t in trades:
        be = check_breakeven(t)
        if be["bars_checked"] == 0:
            no_data.append(t)
            continue
        results.append({**t, **be})

    if no_data:
        print(f"  (skipped {len(no_data)} trades — no bar data found)")

    have_opp   = [r for r in results if r["had_opportunity"]]
    no_opp     = [r for r in results if not r["had_opportunity"]]
    pct_opp    = len(have_opp) / len(results) * 100 if results else 0

    print(f"\n{'='*65}")
    print(f" BREAK-EVEN EXIT OPPORTUNITY ANALYSIS")
    print(f" Window: [entry_fill, actual_exit + {EXTEND_MINS} min]")
    print(f"{'='*65}")
    print(f"  Trades analyzed:              {len(results)}")
    print(f"  Had BE opportunity:           {len(have_opp)}  ({pct_opp:.1f}%)")
    print(f"  No BE opportunity:            {len(no_opp)}  ({100-pct_opp:.1f}%)")

    if have_opp:
        mins = [r["mins_to_be"] for r in have_opp if r["mins_to_be"] is not None]
        avg_mins = sum(mins) / len(mins) if mins else None
        fast = [m for m in mins if m <= 5]
        print(f"\n  Of trades with BE opportunity:")
        print(f"    Avg time to first BE bar:   {avg_mins:.1f} min" if avg_mins else "    Avg time: n/a")
        print(f"    Reached BE within 5 min:    {len(fast)} ({len(fast)/len(have_opp)*100:.1f}%)")

        # avg P&L that WOULD have been saved
        saved_pnl = [r["pnl_pct"] for r in have_opp]
        avg_saved = sum(saved_pnl) / len(saved_pnl)
        all_pnls  = [r["pnl_pct"] for r in results]
        avg_all   = sum(all_pnls) / len(all_pnls)
        print(f"\n    Avg P&L of these trades:    {avg_saved:+.3f}% (would become 0%)")
        print(f"    Avg P&L of no-opp trades:   {sum(r['pnl_pct'] for r in no_opp)/len(no_opp):+.3f}%" if no_opp else "")
        print(f"    Overall avg P&L (all):      {avg_all:+.3f}%")
        new_avg = sum(r["pnl_pct"] for r in no_opp) / len(results) if no_opp else 0
        print(f"    Avg P&L if BE exits used:   {new_avg:+.3f}%  (vs {avg_all:+.3f}%)")

    # per-ticker summary
    print(f"\n  {'Ticker':<8} {'N':>4}  {'BE_opp':>7}  {'BE%':>6}  {'AvgMins':>8}  {'AvgPnL_w/opp':>13}  {'AvgPnL_no_opp':>14}")
    print(f"  {'-'*70}")
    by_ticker = defaultdict(list)
    for r in results:
        by_ticker[r["ticker"]].append(r)
    for ticker, ts in sorted(by_ticker.items()):
        n = len(ts)
        opp = [r for r in ts if r["had_opportunity"]]
        no  = [r for r in ts if not r["had_opportunity"]]
        be_pct = len(opp) / n * 100
        mins_list = [r["mins_to_be"] for r in opp if r["mins_to_be"] is not None]
        avg_m = sum(mins_list) / len(mins_list) if mins_list else None
        avg_pnl_opp = sum(r["pnl_pct"] for r in opp) / len(opp) if opp else None
        avg_pnl_no  = sum(r["pnl_pct"] for r in no)  / len(no)  if no  else None
        m_str     = f"{avg_m:>7.1f}m"    if avg_m is not None     else f"{'—':>8}"
        opp_str   = f"{avg_pnl_opp:>+12.3f}%" if avg_pnl_opp is not None else f"{'—':>13}"
        no_str    = f"{avg_pnl_no:>+13.3f}%"  if avg_pnl_no is not None  else f"{'—':>14}"
        print(f"  {ticker:<8} {n:>4}  {len(opp):>6}  {be_pct:>5.0f}%  {m_str}  {opp_str}  {no_str}")

    # print individual trades with no opportunity (the real unavoidable losses)
    print(f"\n  Trades with NO break-even opportunity (unavoidable losses):")
    print(f"  {'Date':<12} {'Ticker':<8} {'Dur':>5}  {'Entry':>8}  {'Exit':>8}  {'P&L%':>7}  Dir")
    print(f"  {'-'*60}")
    for r in sorted(no_opp, key=lambda x: x["pnl_pct"]):
        t_in_et = r["t_in_utc"] - timedelta(hours=ET_OFFSET_HOURS)
        direction = "SHORT" if r["is_short"] else "LONG"
        print(
            f"  {r['date']:<12} {r['ticker']:<8} {r['duration_mins']:>4.0f}m"
            f"  {r['entry_price']:>8.2f}  {r['exit_price']:>8.2f}"
            f"  {r['pnl_pct']:>+6.3f}%  {direction}"
        )


if __name__ == "__main__":
    main()
