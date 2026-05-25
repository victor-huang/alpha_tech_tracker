"""
analyze_short_trade_reentry.py

Simulates a two-branch secondary strategy applied to short trades (≤15 min holds)
produced by the op-momentum trade engine replay logs.

Strategy:
  After a trade exits early (≤15 min), watch the price for 5–20 min post-exit.

  Branch A — Price RECLAIMS exit level within 5–20 min:
    Re-enter the SAME direction at the open of the bar after confirmation.
    Hold 2 hours, flat cut. Hard stop at -1% of deployed capital.

  Branch B — Price FAILS to reclaim exit level in 5–20 min:
    Enter the OPPOSITE direction at the open of the bar 25 min after exit.
    Hold 2 hours, flat cut. Hard stop at -1% of deployed capital.

Usage:
  python analyze_short_trade_reentry.py [--log-dir PATH] [--cache-dir PATH]
                                        [--max-hold-min N] [--stop-pct F]
                                        [--watch-start N] [--watch-end N]
                                        [--no-trigger-delay N]
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_YEAR      = 2026
DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'market_data', 'cache'
)

_TICKERS_V3 = [
    'AMD', 'APP', 'CHTR', 'CLS', 'COIN', 'CRDO', 'CRWV', 'CVNA',
    'EXPE', 'JPM', 'META', 'MRVL', 'MSTR', 'MU', 'PLTR', 'SHOP', 'TSLA',
]
# 2023/2024 pool — older cache files are alpaca_5min_ (no sip_) and missing
# CHTR, CLS, JPM, MRVL, MSTR, CRWV; those tickers will be skipped with a warning.
_TICKERS_OLD = ['AMD', 'APP', 'COIN', 'CRDO', 'CVNA', 'EXPE', 'META', 'MU', 'PLTR', 'SHOP', 'TSLA']

CACHE_FILES_BY_YEAR = {
    2023: {t: f'alpaca_5min_{t}_2022-11-02_2023-12-31.json' for t in _TICKERS_OLD},
    2024: {t: f'alpaca_5min_{t}_2023-11-02_2024-12-31.json' for t in _TICKERS_OLD},
    2025: {t: f'alpaca_sip_5min_{t}_2024-11-02_2025-12-31.json' for t in _TICKERS_V3},
    2026: {t: f'alpaca_sip_5min_{t}_2026-01-01_2026-05-15.json' for t in _TICKERS_V3},
}

EDT_BY_YEAR = {
    2023: date(2023, 3, 12),
    2024: date(2024, 3, 10),
    2025: date(2025, 3, 9),
    2026: date(2026, 3, 8),
}

# Set at runtime by main() based on --year
EDT_START   = EDT_BY_YEAR[DEFAULT_YEAR]
CACHE_FILES = CACHE_FILES_BY_YEAR[DEFAULT_YEAR]

# ── Helpers ───────────────────────────────────────────────────────────────────
def et_to_utc(trade_date_str, hhmm):
    d = date.fromisoformat(trade_date_str)
    offset = -4 if d >= EDT_START else -5
    h, m = map(int, hhmm.split(':'))
    return datetime(d.year, d.month, d.day, h - offset, m, tzinfo=timezone.utc)


def add_min(hhmm, minutes):
    h, m = map(int, hhmm.split(':'))
    total = min(h * 60 + m + minutes, 15 * 60 + 55)
    return f"{total // 60:02d}:{total % 60:02d}"


def utc_to_et_hhmm(ts, trade_date_str):
    d = date.fromisoformat(trade_date_str)
    offset = -4 if d >= EDT_START else -5
    et_min = (ts.hour + offset) * 60 + ts.minute
    return f"{et_min // 60:02d}:{et_min % 60:02d}"


# ── Data loading ──────────────────────────────────────────────────────────────
def load_bar_data(cache_dir):
    bar_data = {}
    for ticker, fname in CACHE_FILES.items():
        path = os.path.join(cache_dir, fname)
        if not os.path.exists(path):
            print(f"  WARNING: cache missing for {ticker}: {path}", file=sys.stderr)
            continue
        raw  = json.load(open(path))
        cols = raw['columns']
        oi, hi, li, ci = (cols.index('Open'), cols.index('High'),
                          cols.index('Low'),  cols.index('Close'))
        bars = []
        for ts_str, row in zip(raw['index'], raw['data']):
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            bars.append((ts, row[oi], row[hi], row[li], row[ci]))
        bar_data[ticker] = bars
    return bar_data


LOG_ROW_RE = re.compile(
    r'^\s+(\S+)\s+\[(\w+)\]\s+\S+.*?\s+([\d.]+)sh\s+'
    r'(\d{2}:\d{2})\s+(\d{2}:\d{2})\s+'
    r'\$([\d.]+)\s+\$([\d.]+)\s+'
    r'([+-]?\$[\d,.]+)\s+[+-]?[\d.]+%\s+(\S+)'
)


def load_short_trades(log_dir, bar_data, max_dur=15):
    trades = []
    for fname in sorted(os.listdir(log_dir)):
        if not re.match(r'\d{4}-\d{2}-\d{2}\.log$', fname):
            continue
        d_str = fname.replace('.log', '')
        with open(os.path.join(log_dir, fname)) as f:
            for line in f:
                m = LOG_ROW_RE.match(line)
                if not m:
                    continue
                ticker, signal, qty, entry_t, exit_t, entry_px, exit_px, pnl_str, reason = m.groups()
                dur = (datetime.strptime(exit_t, '%H:%M') -
                       datetime.strptime(entry_t, '%H:%M')).seconds // 60
                if dur <= max_dur and ticker in bar_data:
                    trades.append({
                        'date':          d_str,
                        'ticker':        ticker,
                        'orig_signal':   signal.upper(),
                        'orig_entry_t':  entry_t,
                        'orig_exit_t':   exit_t,
                        'orig_entry_px': float(entry_px),
                        'orig_exit_px':  float(exit_px),
                        'qty':           float(qty),
                        'orig_dur_min':  dur,
                        'actual_pnl':    float(pnl_str.replace('$', '').replace(',', '')),
                        'exit_reason':   reason,
                    })
    return trades


# ── Trade simulator with bar-by-bar stop check ───────────────────────────────
def simulate_hold(t, entry_px, is_long, flat_cut_hhmm, all_day,
                  entry_bar_ts, stop_pct):
    """
    Simulate holding a position from entry_bar_ts to flat_cut, checking each
    bar for a -stop_pct hard stop (using bar Low for long, High for short).

    Returns (pnl, pnl_pct, mdd, mdd_pct, exit_reason, actual_exit_hhmm).
    """
    flat_cut_utc = et_to_utc(t['date'], flat_cut_hhmm)
    qty          = t['qty']
    deployed     = entry_px * qty
    stop_loss_px = entry_px * (1 - stop_pct) if is_long else entry_px * (1 + stop_pct)

    window = [(ts, o, h, l, c) for ts, o, h, l, c in all_day
              if entry_bar_ts <= ts]

    worst_unreal = 0.0
    exit_px      = None
    exit_label   = 'flat_cut'
    actual_exit  = flat_cut_hhmm

    for ts, o, h, l, c in window:
        # Check hard stop using worst intrabar price
        adverse_px = l if is_long else h
        if (is_long and adverse_px <= stop_loss_px) or \
           (not is_long and adverse_px >= stop_loss_px):
            exit_px    = stop_loss_px
            exit_label = f'stop_{stop_pct*100:.0f}pct'
            actual_exit = utc_to_et_hhmm(ts, t['date'])
            break

        # Track MDD (close-based unrealized)
        adverse_close = l if is_long else h
        unreal = (adverse_close - entry_px) * qty if is_long \
                 else (entry_px - adverse_close) * qty
        worst_unreal = min(worst_unreal, unreal)

        # Flat cut at 2-hour mark
        if ts >= flat_cut_utc:
            exit_px    = c
            actual_exit = utc_to_et_hhmm(ts, t['date'])
            break

    if exit_px is None:
        # Ran past EOD — use last bar
        last = next((c for ts, o, h, l, c in reversed(window)
                     if ts.date() == date.fromisoformat(t['date'])), entry_px)
        exit_px    = last
        exit_label = 'eod'

    pnl     = (exit_px - entry_px) * qty if is_long else (entry_px - exit_px) * qty
    pnl_pct = pnl / deployed * 100 if deployed else 0.0
    mdd_pct = worst_unreal / deployed * 100 if deployed else 0.0

    return pnl, pnl_pct, worst_unreal, mdd_pct, exit_label, actual_exit


# ── Branch routing ────────────────────────────────────────────────────────────
def route_trade(t, bar_data, watch_start_min, watch_end_min,
                no_trigger_delay_min, max_hold_min, stop_pct):
    """
    Returns a result dict for one short trade, or None if trade can't be filled.
    """
    d       = date.fromisoformat(t['date'])
    all_day = [(ts, o, h, l, c) for ts, o, h, l, c in bar_data[t['ticker']]
               if ts.date() == d]
    if not all_day:
        return None

    is_long  = t['orig_signal'] == 'BULLISH'
    exit_px  = t['orig_exit_px']

    watch_start_utc = et_to_utc(t['date'], add_min(t['orig_exit_t'], watch_start_min))
    watch_end_utc   = et_to_utc(t['date'], add_min(t['orig_exit_t'], watch_end_min))

    # Find first confirming bar in watch window
    confirm_bar = None
    for ts, o, h, l, c in all_day:
        if watch_start_utc <= ts <= watch_end_utc:
            if (is_long and c > exit_px) or (not is_long and c < exit_px):
                confirm_bar = (ts, o, h, l, c)
                break

    if confirm_bar is not None:
        # ── Branch A: same-direction re-entry ─────────────────────────────
        confirm_idx = next(i for i, (ts, *_) in enumerate(all_day)
                           if ts == confirm_bar[0])
        if confirm_idx + 1 >= len(all_day):
            return None

        entry_bar    = all_day[confirm_idx + 1]
        reentry_px   = entry_bar[1]
        reentry_hhmm = utc_to_et_hhmm(entry_bar[0], t['date'])
        flat_cut     = add_min(reentry_hhmm, max_hold_min)
        branch       = 'A'
        direction    = is_long   # same direction

    else:
        # ── Branch B: reversal after watch window expires ──────────────────
        entry_hhmm = add_min(t['orig_exit_t'], watch_end_min + no_trigger_delay_min)
        entry_utc  = et_to_utc(t['date'], entry_hhmm)
        entry_bar  = next(((ts, o, h, l, c) for ts, o, h, l, c in all_day
                           if ts >= entry_utc), None)
        if entry_bar is None:
            return None

        reentry_px   = entry_bar[1]
        reentry_hhmm = utc_to_et_hhmm(entry_bar[0], t['date'])
        flat_cut     = add_min(reentry_hhmm, max_hold_min)
        branch       = 'B'
        direction    = not is_long   # reversed

    pnl, pnl_pct, mdd, mdd_pct, stop_label, actual_exit = simulate_hold(
        t, reentry_px, direction, flat_cut, all_day, entry_bar[0], stop_pct
    )

    return {
        **t,
        'branch':        branch,
        'reentry_px':    reentry_px,
        'reentry_hhmm':  reentry_hhmm,
        'flat_cut_hhmm': flat_cut,
        'actual_exit':   actual_exit,
        'is_long':       direction,
        'pnl':           pnl,
        'pnl_pct':       pnl_pct,
        'mdd':           mdd,
        'mdd_pct':       mdd_pct,
        'stop_label':    stop_label,
    }


# ── Reporting helpers ─────────────────────────────────────────────────────────
def section(title):
    print(f"\n  ── {title} {'─' * (54 - len(title))}")


def print_branch_stats(label, results, stop_pct):
    n      = len(results)
    if n == 0:
        print(f"  {label}: no trades")
        return
    wins   = [r for r in results if r['pnl'] > 0]
    losses = [r for r in results if r['pnl'] <= 0]
    tp     = sum(r['pnl'] for r in results)
    tp_pct = sum(r['pnl_pct'] for r in results) / n
    td_pct = sum(r['mdd_pct'] for r in results) / n
    aw_pct = sum(r['pnl_pct'] for r in wins)  / len(wins)   if wins   else 0
    al_pct = sum(r['pnl_pct'] for r in losses)/ len(losses)  if losses else 0
    rr     = abs(aw_pct / al_pct) if al_pct else float('inf')
    stopped = sum(1 for r in results if 'stop' in r['stop_label'])

    print(f"\n{'='*66}")
    print(f"  {label}")
    print(f"{'='*66}")
    print(f"  Trades          : {n}")
    print(f"  Winners         : {len(wins)} ({len(wins)/n*100:.1f}%)")
    print(f"  Losers          : {len(losses)} ({len(losses)/n*100:.1f}%)")
    print(f"  Stopped out     : {stopped} ({stopped/n*100:.1f}%)")
    print(f"  Total P&L       : ${tp:>+9,.2f}   avg {tp_pct:>+6.2f}% per trade")
    print(f"  Avg win         : {aw_pct:>+7.2f}%")
    print(f"  Avg loss        : {al_pct:>+7.2f}%")
    print(f"  Win/loss ratio  : {rr:.2f}x")
    print(f"  Avg MDD         : {td_pct:>+7.2f}%")
    worst_t = min(results, key=lambda r: r['mdd_pct'])
    print(f"  Worst MDD       : {worst_t['mdd_pct']:>+7.2f}%   "
          f"({worst_t['date']} {worst_t['ticker']})")

    section("MDD % Distribution")
    mdd_defs = [
        ('0%',            0,     float('inf')),
        ('>-0.5%',     -0.5,     0),
        ('-0.5% to -1%', -1,  -0.5),
        ('-1% to -2%',   -2,    -1),
        ('-2% to -3%',   -3,    -2),
        (f'<-{stop_pct*100:.0f}%', float('-inf'), -3),
    ]
    print(f"  {'MDD bucket':<18}  {'n':>4}  {'%':>6}  {'WR':>6}  {'Avg P&L%':>10}")
    for lbl, lo, hi in mdd_defs:
        sub = [r for r in results if lo <= r['mdd_pct'] < hi]
        if not sub:
            continue
        sw = sum(1 for r in sub if r['pnl'] > 0)
        ap = sum(r['pnl_pct'] for r in sub) / len(sub)
        print(f"  {lbl:<18}  {len(sub):>4}  {len(sub)/n*100:>5.1f}%"
              f"  {sw/len(sub)*100:>5.1f}%  {ap:>+9.2f}%")

    section("P&L % Distribution")
    pnl_defs = [
        ('<-3%',         float('-inf'), -3.0),
        ('-2% to -3%',        -3.0,    -2.0),
        ('-1% to -2%',        -2.0,    -1.0),
        ('-0.5% to -1%',      -1.0,    -0.5),
        ('0% to -0.5%',       -0.5,     0.0),
        ('0% to +0.5%',        0.0,     0.5),
        ('+0.5% to +1%',       0.5,     1.0),
        ('+1% to +2%',         1.0,     2.0),
        ('+2% to +3%',         2.0,     3.0),
        ('>+3%',               3.0,     float('inf')),
    ]
    print(f"  {'P&L bucket':<20}  {'n':>4}  {'%':>6}  {'avg P&L%':>10}")
    for lbl, lo, hi in pnl_defs:
        sub = [r for r in results if lo <= r['pnl_pct'] < hi]
        if not sub:
            continue
        ap  = sum(r['pnl_pct'] for r in sub) / len(sub)
        bar = '█' * int(len(sub) / n * 35)
        print(f"  {lbl:<20}  {len(sub):>4}  {len(sub)/n*100:>5.1f}%  {ap:>+9.2f}%  {bar}")

    section("By original exit reason")
    for reason in ['fallback_20pct', 'hard_stop', 'trailing_stop_ma20']:
        sub = [r for r in results if r['exit_reason'] == reason]
        if not sub:
            continue
        sw  = [r for r in sub if r['pnl'] > 0]
        sl  = [r for r in sub if r['pnl'] <= 0]
        sp  = sum(r['pnl_pct'] for r in sub) / len(sub)
        sd  = sum(r['mdd_pct'] for r in sub) / len(sub)
        aw  = sum(r['pnl_pct'] for r in sw) / len(sw) if sw else 0
        al  = sum(r['pnl_pct'] for r in sl) / len(sl) if sl else 0
        print(f"  [{reason:<18}]  n={len(sub):>3}  WR={len(sw)/len(sub)*100:.1f}%  "
              f"avg={sp:>+.2f}%  win={aw:>+.2f}%  loss={al:>+.2f}%  mdd={sd:>+.2f}%")

    section("Entry time slot")
    time_buckets = defaultdict(lambda: {'n': 0, 'pnl_pct': 0.0, 'wins': 0})
    for r in results:
        h, m = map(int, r['reentry_hhmm'].split(':'))
        slot = f"{h:02d}:{(m // 30) * 30:02d}"
        time_buckets[slot]['n']      += 1
        time_buckets[slot]['pnl_pct'] += r['pnl_pct']
        if r['pnl'] > 0:
            time_buckets[slot]['wins'] += 1
    print(f"  {'Slot':<8}  {'n':>4}  {'WR':>6}  {'Avg P&L%':>10}")
    for slot in sorted(time_buckets):
        v  = time_buckets[slot]
        wr = v['wins'] / v['n'] * 100
        ap = v['pnl_pct'] / v['n']
        print(f"  {slot:<8}  {v['n']:>4}  {wr:>5.1f}%  {ap:>+9.2f}%")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--year',          type=int,   default=DEFAULT_YEAR,
                        help='Year to analyse (2025 or 2026, default: 2026); auto-sets log-dir and cache files')
    parser.add_argument('--log-dir',       default=None,
                        help='Override log directory (default: derived from --year)')
    parser.add_argument('--cache-dir',          default=DEFAULT_CACHE_DIR)
    parser.add_argument('--max-hold-min',  type=int,   default=120,
                        help='Minutes to hold re-entry before flat cut (default: 120)')
    parser.add_argument('--stop-pct',      type=float, default=0.01,
                        help='Hard stop as fraction of entry price (default: 0.01 = 1%%)')
    parser.add_argument('--watch-start',   type=int,   default=5,
                        help='Minutes after exit to start watching for confirmation (default: 5)')
    parser.add_argument('--watch-end',     type=int,   default=20,
                        help='Minutes after exit to end watch window (default: 20)')
    parser.add_argument('--no-trigger-delay', type=int, default=5,
                        help='Extra minutes past watch-end before Branch B entry (default: 5 → 25 min total)')
    parser.add_argument('--max-orig-dur',  type=int,   default=15,
                        help='Max original trade duration to qualify as short (default: 15)')
    args = parser.parse_args()

    # Inject year-specific globals before any helper functions use them
    global EDT_START, CACHE_FILES
    if args.year not in EDT_BY_YEAR:
        print(f"ERROR: --year {args.year} not supported. Available: {sorted(EDT_BY_YEAR)}")
        sys.exit(1)
    EDT_START   = EDT_BY_YEAR[args.year]
    CACHE_FILES = CACHE_FILES_BY_YEAR[args.year]

    default_log = os.path.join(
        os.path.dirname(__file__), '..', '..', 'logs',
        f'replay_{args.year}_M1_0930_1_A1_1030_6_stop10'
    )
    log_dir   = os.path.abspath(args.log_dir if args.log_dir else default_log)
    cache_dir = os.path.abspath(args.cache_dir)

    print(f"Year      : {args.year}")
    print(f"Log dir   : {log_dir}")
    print(f"Cache dir : {cache_dir}")
    print(f"Config    : watch {args.watch_start}–{args.watch_end} min | "
          f"B-delay +{args.no_trigger_delay} min | "
          f"hold {args.max_hold_min} min | stop {args.stop_pct*100:.1f}%")

    print("\nLoading bar cache...")
    bar_data = load_bar_data(cache_dir)
    print(f"  Loaded {len(bar_data)} tickers")

    print("\nParsing short trades from logs...")
    short_trades = load_short_trades(log_dir, bar_data, args.max_orig_dur)
    print(f"  Found {len(short_trades)} short trades (orig dur ≤{args.max_orig_dur} min)")

    print("\nRouting trades through branches...")
    branch_a, branch_b, skipped = [], [], 0
    for t in short_trades:
        result = route_trade(
            t, bar_data,
            watch_start_min=args.watch_start,
            watch_end_min=args.watch_end,
            no_trigger_delay_min=args.no_trigger_delay,
            max_hold_min=args.max_hold_min,
            stop_pct=args.stop_pct,
        )
        if result is None:
            skipped += 1
        elif result['branch'] == 'A':
            branch_a.append(result)
        else:
            branch_b.append(result)

    print(f"  Branch A (same-dir re-entry) : {len(branch_a)}")
    print(f"  Branch B (reversal)          : {len(branch_b)}")
    print(f"  Skipped (no bar data)        : {skipped}")

    print_branch_stats(
        f"Branch A — Price reclaims exit level ({args.watch_start}–{args.watch_end} min) "
        f"→ same-dir re-entry, {args.max_hold_min}-min flat, {args.stop_pct*100:.0f}% stop",
        branch_a, args.stop_pct,
    )

    print_branch_stats(
        f"Branch B — No reclaim → reverse at +{args.watch_end + args.no_trigger_delay} min, "
        f"{args.max_hold_min}-min flat, {args.stop_pct*100:.0f}% stop",
        branch_b, args.stop_pct,
    )

    # Combined summary
    all_results = branch_a + branch_b
    n   = len(all_results)
    tp  = sum(r['pnl'] for r in all_results)
    tpp = sum(r['pnl_pct'] for r in all_results) / n if n else 0
    tdp = sum(r['mdd_pct'] for r in all_results) / n if n else 0
    wr  = sum(1 for r in all_results if r['pnl'] > 0) / n * 100 if n else 0
    orig_pnl = sum(t['actual_pnl'] for t in short_trades)

    print(f"\n{'='*66}")
    print(f"  COMBINED — all {len(short_trades)} short trades recycled")
    print(f"{'='*66}")
    print(f"  Routed trades   : {n}  (A={len(branch_a)}, B={len(branch_b)})")
    print(f"  Win rate        : {wr:.1f}%")
    print(f"  Total P&L       : ${tp:>+9,.2f}   avg {tpp:>+.2f}% per trade")
    print(f"  Avg MDD/trade   : {tdp:>+.2f}%")
    print(f"  Original P&L    : ${orig_pnl:>+9,.2f}   (short trades at early exit)")
    print(f"  Net improvement : ${tp - orig_pnl:>+9,.2f}")
    print()


if __name__ == '__main__':
    main()
