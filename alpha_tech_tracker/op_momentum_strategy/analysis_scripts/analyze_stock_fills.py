"""
Analyze live stock fill history from logs/fills/ to measure actual slippage
and cost for short-duration trades (≤15 min).

Pairs ENTRY/EXIT rows by (date, ticker) to compute trade duration,
then segments by duration bucket to show round-trip cost vs mid.
"""

import os
import csv
from collections import defaultdict
from datetime import datetime


FILLS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "logs", "fills"
)

SHORT_DURATION_MINS = 15


def _parse_time(t_str):
    """Return datetime.time or None from HH:MM:SS or HH:MM."""
    if not t_str:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(t_str.strip(), fmt).time()
        except ValueError:
            continue
    return None


def _minutes_between(t1, t2):
    """Minutes from t1 to t2 (both datetime.time). Returns None if invalid."""
    if t1 is None or t2 is None:
        return None
    return (t2.hour * 60 + t2.minute) - (t1.hour * 60 + t1.minute)


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_all_fills():
    """Return list of dicts with normalized fields from all stocks_fills CSVs."""
    all_rows = []
    for date_dir in sorted(os.listdir(FILLS_DIR)):
        date_path = os.path.join(FILLS_DIR, date_dir)
        if not os.path.isdir(date_path):
            continue
        fname = f"stocks_fills_{date_dir}.csv"
        fpath = os.path.join(date_path, fname)
        if not os.path.exists(fpath):
            continue

        with open(fpath, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["_date"] = date_dir
                all_rows.append(row)
    return all_rows


def _get_field(row, *candidates):
    """Return first non-empty field value from candidate column names."""
    for c in candidates:
        v = row.get(c, "").strip()
        if v:
            return v
    return ""


def build_trades(rows):
    """
    Match ENTRY/EXIT rows by (date, ticker) into round-trip trades.
    Returns list of trade dicts.
    """
    # group by (date, ticker), preserving order
    by_key = defaultdict(list)
    for row in rows:
        key = (row["_date"], row.get("ticker", "").strip())
        by_key[key].append(row)

    trades = []
    for (date, ticker), group in by_key.items():
        entries = [r for r in group if r.get("side", "").upper() == "ENTRY"]
        exits = [r for r in group if r.get("side", "").upper() == "EXIT"]

        # pair entries and exits in order
        pairs = list(zip(entries, exits))
        for entry, exit_ in pairs:
            t_in = _parse_time(_get_field(entry, "fill_time"))
            t_out = _parse_time(_get_field(exit_, "fill_time"))
            duration = _minutes_between(t_in, t_out)

            entry_price = _safe_float(_get_field(entry, "fill_price"))
            exit_price = _safe_float(_get_field(exit_, "fill_price"))
            pnl_pct = None
            if entry_price and exit_price and entry_price > 0:
                direction = _get_field(entry, "trade_action").upper()
                if "SHORT" in direction:
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                else:
                    pnl_pct = (exit_price - entry_price) / entry_price * 100

            # slippage: fill_vs_log_mid (newer schema) or fill_vs_stock_mid (old)
            entry_vs_mid = _safe_float(
                _get_field(entry, "fill_vs_log_mid", "fill_vs_nbbo_mid", "fill_vs_stock_mid")
            )
            exit_vs_mid = _safe_float(
                _get_field(exit_, "fill_vs_log_mid", "fill_vs_nbbo_mid", "fill_vs_stock_mid")
            )

            entry_slippage_bps = _safe_float(_get_field(entry, "slippage_bps", "slippage_vs_limit"))
            exit_slippage_bps = _safe_float(_get_field(exit_, "slippage_bps", "slippage_vs_limit"))

            nbbo_spread_entry = _safe_float(_get_field(entry, "nbbo_spread_pct"))
            nbbo_spread_exit = _safe_float(_get_field(exit_, "nbbo_spread_pct"))

            qty = _safe_float(_get_field(entry, "qty")) or 0
            dollar_pnl = None
            if entry_price and exit_price and qty:
                direction = _get_field(entry, "trade_action").upper()
                if "SHORT" in direction:
                    dollar_pnl = (entry_price - exit_price) * qty
                else:
                    dollar_pnl = (exit_price - entry_price) * qty

            trades.append({
                "date": date,
                "ticker": ticker,
                "t_in": t_in,
                "t_out": t_out,
                "duration_mins": duration,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "qty": qty,
                "pnl_pct": pnl_pct,
                "dollar_pnl": dollar_pnl,
                "entry_vs_mid": entry_vs_mid,
                "exit_vs_mid": exit_vs_mid,
                "entry_slippage_bps": entry_slippage_bps,
                "exit_slippage_bps": exit_slippage_bps,
                "nbbo_spread_entry": nbbo_spread_entry,
                "nbbo_spread_exit": nbbo_spread_exit,
                "entry_action": _get_field(entry, "trade_action"),
            })

    return trades


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None, None
    avg = sum(vals) / len(vals)
    mn = min(vals)
    mx = max(vals)
    return avg, mn, mx


def analyze(trades, label, subset):
    if not subset:
        print(f"\n{label}: no trades")
        return

    n = len(subset)
    pnls = [t["pnl_pct"] for t in subset if t["pnl_pct"] is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    durations = [t["duration_mins"] for t in subset if t["duration_mins"] is not None]
    avg_dur, _, _ = _stats(durations)

    avg_pnl, _, _ = _stats(pnls)
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0

    entry_vs_mid = [t["entry_vs_mid"] for t in subset if t["entry_vs_mid"] is not None]
    exit_vs_mid = [t["exit_vs_mid"] for t in subset if t["exit_vs_mid"] is not None]
    avg_e_mid, _, _ = _stats(entry_vs_mid)
    avg_x_mid, _, _ = _stats(exit_vs_mid)

    e_bps = [t["entry_slippage_bps"] for t in subset if t["entry_slippage_bps"] is not None]
    x_bps = [t["exit_slippage_bps"] for t in subset if t["exit_slippage_bps"] is not None]
    avg_e_bps, _, _ = _stats(e_bps)
    avg_x_bps, _, _ = _stats(x_bps)

    nbbo_sp = [t["nbbo_spread_entry"] for t in subset if t["nbbo_spread_entry"] is not None]
    avg_nbbo_sp, _, _ = _stats(nbbo_sp)

    print(f"\n{'='*60}")
    print(f" {label}  (n={n})")
    print(f"{'='*60}")
    print(f"  Avg duration:          {avg_dur:.1f} min" if avg_dur else "  Avg duration:          n/a")
    print(f"  Win rate:              {win_rate:.1f}%  ({len(wins)}W/{len(losses)}L of {len(pnls)})")
    print(f"  Avg P&L per trade:     {avg_pnl:+.3f}%" if avg_pnl is not None else "  Avg P&L per trade:     n/a")

    print(f"\n  -- Slippage vs mid ($ per share) --")
    if avg_e_mid is not None:
        print(f"  Entry fill vs mid:     {avg_e_mid:+.4f}  (n={len(entry_vs_mid)})")
    if avg_x_mid is not None:
        print(f"  Exit  fill vs mid:     {avg_x_mid:+.4f}  (n={len(exit_vs_mid)})")
    if avg_e_mid is not None and avg_x_mid is not None:
        # round-trip cost: entry above mid + exit below mid → both adverse
        # entry_vs_mid > 0 means we paid above mid (cost)
        # exit_vs_mid < 0 means we sold below mid (cost)
        rt_cost = avg_e_mid - avg_x_mid  # both contribute positively to cost
        print(f"  Round-trip cost vs mid:{rt_cost:+.4f}/share")

    if avg_e_bps is not None:
        print(f"\n  -- Slippage vs limit order (bps) --")
        print(f"  Entry slippage:        {avg_e_bps:+.1f} bps  (n={len(e_bps)})")
    if avg_x_bps is not None:
        print(f"  Exit  slippage:        {avg_x_bps:+.1f} bps  (n={len(x_bps)})")

    if avg_nbbo_sp is not None:
        print(f"\n  Avg NBBO spread:       {avg_nbbo_sp:.3f}%  (n={len(nbbo_sp)})")

    # round-trip cost as % of stock price
    # estimate using avg fill vs mid for both legs, relative to avg entry price
    entry_prices = [t["entry_price"] for t in subset if t["entry_price"]]
    avg_ep = sum(entry_prices) / len(entry_prices) if entry_prices else None
    if avg_e_mid is not None and avg_x_mid is not None and avg_ep:
        rt_cost_pct = (avg_e_mid - avg_x_mid) / avg_ep * 100
        print(f"\n  Round-trip cost % of price: {rt_cost_pct:+.3f}%")
        if avg_pnl is not None:
            net = avg_pnl - rt_cost_pct
            print(f"  Avg P&L after slip cost:    {net:+.3f}%")


def print_by_ticker(trades, subset_label, subset):
    if not subset:
        return
    by_ticker = defaultdict(list)
    for t in subset:
        by_ticker[t["ticker"]].append(t)

    print(f"\n  {subset_label} — breakdown by ticker:")
    print(f"  {'Ticker':<8} {'N':>4}  {'AvgDur':>7}  {'AvgPnL%':>9}  {'WinR%':>6}  {'E_vs_mid':>9}  {'X_vs_mid':>9}")
    print(f"  {'-'*70}")
    for ticker, ts in sorted(by_ticker.items()):
        n = len(ts)
        pnls = [t["pnl_pct"] for t in ts if t["pnl_pct"] is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else None
        wins = len([p for p in pnls if p > 0])
        wr = wins / len(pnls) * 100 if pnls else 0
        durs = [t["duration_mins"] for t in ts if t["duration_mins"] is not None]
        avg_d = sum(durs) / len(durs) if durs else None
        e_mids = [t["entry_vs_mid"] for t in ts if t["entry_vs_mid"] is not None]
        x_mids = [t["exit_vs_mid"] for t in ts if t["exit_vs_mid"] is not None]
        avg_em = sum(e_mids) / len(e_mids) if e_mids else None
        avg_xm = sum(x_mids) / len(x_mids) if x_mids else None
        print(
            f"  {ticker:<8} {n:>4}  "
            f"{avg_d:>6.1f}m  "
            f"{avg_pnl:>+8.3f}%  "
            f"{wr:>5.0f}%  "
            f"{avg_em:>+8.4f}  "
            f"{avg_xm:>+8.4f}"
            if avg_d is not None and avg_pnl is not None and avg_em is not None and avg_xm is not None
            else f"  {ticker:<8} {n:>4}  {'n/a':>7}  {'n/a':>9}  {wr:>5.0f}%  {'n/a':>9}  {'n/a':>9}"
        )


def main():
    rows = load_all_fills()
    print(f"Loaded {len(rows)} fill rows from {FILLS_DIR}")

    trades = build_trades(rows)
    valid = [t for t in trades if t["duration_mins"] is not None]
    print(f"Built {len(trades)} round-trip trades ({len(valid)} with valid duration)")

    short = [t for t in valid if 0 < t["duration_mins"] <= SHORT_DURATION_MINS]
    long_ = [t for t in valid if t["duration_mins"] > SHORT_DURATION_MINS]

    pct_short = len(short) / len(valid) * 100 if valid else 0
    print(f"\nShort trades (≤{SHORT_DURATION_MINS} min): {len(short)} ({pct_short:.1f}% of total)")
    print(f"Longer trades (>{SHORT_DURATION_MINS} min): {len(long_)} ({100-pct_short:.1f}%)")

    analyze(trades, "ALL TRADES", valid)
    analyze(trades, f"SHORT TRADES  ≤{SHORT_DURATION_MINS} min", short)
    analyze(trades, f"LONGER TRADES >{SHORT_DURATION_MINS} min", long_)

    print_by_ticker(trades, f"SHORT ≤{SHORT_DURATION_MINS} min", short)
    print_by_ticker(trades, f"LONGER >{SHORT_DURATION_MINS} min", long_)

    # P&L dollar contribution breakdown
    total_dollar = sum(t["dollar_pnl"] for t in valid if t["dollar_pnl"] is not None)
    short_dollar = sum(t["dollar_pnl"] for t in short if t["dollar_pnl"] is not None)
    long_dollar  = sum(t["dollar_pnl"] for t in long_ if t["dollar_pnl"] is not None)

    print(f"\n{'='*60}")
    print(f" P&L CONTRIBUTION BREAKDOWN")
    print(f"{'='*60}")
    print(f"  {'Bucket':<22} {'N':>4}  {'$P&L':>12}  {'% of Total P&L':>16}")
    print(f"  {'-'*58}")
    total_abs = abs(total_dollar) or 1
    for lbl, grp, dollars in [
        (f"Short  ≤{SHORT_DURATION_MINS} min", short, short_dollar),
        (f"Longer >{SHORT_DURATION_MINS} min", long_, long_dollar),
        ("ALL", valid, total_dollar),
    ]:
        n_d = len([t for t in grp if t["dollar_pnl"] is not None])
        pct = dollars / total_dollar * 100 if total_dollar else float("nan")
        print(f"  {lbl:<22} {n_d:>4}  ${dollars:>+10.2f}  {pct:>+14.1f}%")

    # P&L distribution for short trades
    print(f"\n  P&L buckets for short (≤{SHORT_DURATION_MINS} min) trades:")
    buckets = [
        ("< -1%",   lambda p: p < -1.0),
        ("-1 to -0.3%", lambda p: -1.0 <= p < -0.3),
        ("±0.3%",   lambda p: -0.3 <= p <= 0.3),
        ("+0.3 to +1%", lambda p: 0.3 < p <= 1.0),
        ("> +1%",   lambda p: p > 1.0),
    ]
    short_pnls = [(t["ticker"], t["pnl_pct"], t["duration_mins"]) for t in short if t["pnl_pct"] is not None]
    print(f"  {'Bucket':<18} {'N':>4}  {'%Total':>7}  {'AvgPnL%':>9}")
    print(f"  {'-'*45}")
    for label, fn in buckets:
        bucket_pnls = [p for _, p, _ in short_pnls if fn(p)]
        n = len(bucket_pnls)
        pct = n / len(short_pnls) * 100 if short_pnls else 0
        avg = sum(bucket_pnls) / n if n else 0
        print(f"  {label:<18} {n:>4}  {pct:>6.1f}%  {avg:>+8.3f}%")


if __name__ == "__main__":
    main()
