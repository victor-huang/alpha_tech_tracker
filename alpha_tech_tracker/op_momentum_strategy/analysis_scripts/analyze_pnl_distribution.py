import sys
import re
from collections import defaultdict

"""
Analyzes P&L distribution from op_momentum_selector_backtest.py output.

Usage:
    python op_momentum_selector_backtest.py [backtest args] | python analyze_pnl_distribution.py

Example:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
      python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \\
        --top 2 --weights 60 40 \\
        --window M1 09:30 3 --window A1 10:00 3 --window A2 11:45 2 \\
        --window A3 13:15 1 --window A4 15:15 1 \\
        --morning-split 100 --doubledown --doubledown-start 10 \\
        --reversal --bullish-reentry --bearish-reentry \\
        --start 2026-01-01 --end 2026-05-08 --feed sip \\
      | python alpha_tech_tracker/op_momentum_strategy/analyze_pnl_distribution.py
"""

# Multi-window trade row:
#   2026-01-02   M1    1     SNDK   BULLISH    3.36  09:45 11:20   258.14  263.96  +$5.82  +2.25%  WIN     trailing_stop_ma20
trade_re = re.compile(
    r'\s+(\d{4}-\d{2}-\d{2})\s+(\w+)\s+\d+\s+\S+\s+\S+\s+[\d.]+'
    r'\s+(\d+:\d+)\s+(\S+)'
    r'\s+[\d.]+\s+[\d.]+'
    r'\s+([+-])\$([\d.]+)'
    r'\s+([+-][\d.]+)%\s+(WIN|LOSS)\s+(\S+)'
)

# Reentry sub-row ([REV], [BRE], [BRU], [DD]) — only matches rows with a complete P&L:
#                                   [REV]            13:20 16:00   268.12  274.73  +$6.61  +2.47%  WIN     end_of_day
rev_re = re.compile(
    r'\s+\[(\w+)\]'
    r'\s+(\d+:\d+)\s+(\S+)'
    r'\s+[\d.]+\s+[\d.]+'
    r'\s+([+-])\$([\d.]+)'
    r'\s+([+-][\d.]+)%\s+(WIN|LOSS)\s+(\S+)'
)

# TOTAL line from the monthly cap P&L block:
#   TOTAL            43  22W/21L         +$1884.54   +18.85%  $11,884.54
total_re = re.compile(
    r'^\s+TOTAL\s+\d+\s+\d+W/\d+L\s+([+-])\$([\d.]+)\s+([+-][\d.]+)%'
)


def _parse_hhmm(t):
    if not t or ':' not in t or t == '—':
        return None
    try:
        h, m = t.split(':')
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _duration_mins(t_in, t_out):
    a = _parse_hhmm(t_in)
    b = _parse_hhmm(t_out)
    return b - a if a is not None and b is not None else None


data = sys.stdin.read()
lines = data.split('\n')

# Each trade: dict with pnl_pct, duration_mins (may be None), window, exit_reason
trades = []
windows = defaultdict(list)
exit_reasons = defaultdict(list)

# Parsed from the strategy TOTAL line
portfolio_cap_pnl = None
portfolio_return_pct = None

current_window = None
for line in lines:
    m = trade_re.search(line)
    if m:
        current_window = m.group(2)
        pnl_usd = (1 if m.group(5) == '+' else -1) * float(m.group(6))
        pct = float(m.group(7))
        dur = _duration_mins(m.group(3), m.group(4))
        trades.append({"pnl_pct": pct, "pnl_usd": pnl_usd, "duration_mins": dur, "window": current_window, "exit_reason": m.group(9)})
        windows[current_window].append(pct)
        exit_reasons[m.group(9)].append(pct)
        continue
    m = rev_re.search(line)
    if m:
        pnl_usd = (1 if m.group(4) == '+' else -1) * float(m.group(5))
        pct = float(m.group(6))
        dur = _duration_mins(m.group(2), m.group(3))
        win = current_window or "?"
        trades.append({"pnl_pct": pct, "pnl_usd": pnl_usd, "duration_mins": dur, "window": win, "exit_reason": m.group(8)})
        windows[win].append(pct)
        exit_reasons[m.group(8)].append(pct)
        continue
    m = total_re.match(line)
    # Take the first TOTAL match (strategy block; QQQ block has a different format)
    if m and portfolio_cap_pnl is None:
        sign = 1 if m.group(1) == '+' else -1
        portfolio_cap_pnl = sign * float(m.group(2))
        portfolio_return_pct = float(m.group(3))

if not trades:
    print("No trades found in input.")
    sys.exit(1)

pnl_pcts = [t["pnl_pct"] for t in trades]
total_n = len(trades)
overall_avg = sum(pnl_pcts) / total_n
overall_wins = sum(1 for x in pnl_pcts if x > 0)

# ── P&L distribution ────────────────────────────────────────────────────────

buckets = [
    ('<=-2.0%',       lambda x: x <= -2.0),
    ('-2.0 to -1.0%', lambda x: -2.0 < x <= -1.0),
    ('-1.0 to -0.5%', lambda x: -1.0 < x <= -0.5),
    ('-0.5 to -0.3%', lambda x: -0.5 < x <= -0.3),
    ('-0.3 to  0.0%', lambda x: -0.3 < x < 0.0),
    ('=0.0%',         lambda x: x == 0.0),
    ('+0.0 to +0.3%', lambda x: 0.0 < x <= 0.3),
    ('+0.3 to +0.5%', lambda x: 0.3 < x <= 0.5),
    ('+0.5 to +1.0%', lambda x: 0.5 < x <= 1.0),
    ('+1.0 to +2.0%', lambda x: 1.0 < x <= 2.0),
    ('>+2.0%',        lambda x: x > 2.0),
]
noise_labels = {'-0.3 to  0.0%', '=0.0%', '+0.0 to +0.3%'}

print(f"\nTotal trades : {total_n}")
print(f"Overall avg  : {overall_avg:+.3f}% / trade   (win rate: {overall_wins / total_n * 100:.0f}%)")
if portfolio_cap_pnl is not None:
    sign = '+' if portfolio_cap_pnl >= 0 else ''
    print(f"Portfolio    : {sign}${portfolio_cap_pnl:,.2f}  ({portfolio_return_pct:+.2f}% on $10k)")

print(f"\n{'Bucket':<22} {'Count':>6} {'%Total':>7}  {'AvgPnL%':>8}  {'WinRate':>8}")
print('-' * 57)
noise_count = 0
for label, fn in buckets:
    matches = [x for x in pnl_pcts if fn(x)]
    if not matches:
        continue
    pct_total = len(matches) / total_n * 100
    avg = sum(matches) / len(matches)
    wins = sum(1 for x in matches if x > 0)
    wr = wins / len(matches) * 100
    flag = ' <-- NOISE' if label in noise_labels else ''
    print(f"  {label:<20} {len(matches):>6} {pct_total:>6.1f}%  {avg:>+8.3f}%  {wr:>6.0f}%{flag}")
    if label in noise_labels:
        noise_count += len(matches)

print(f"\n  Total noise trades (±0.3%): {noise_count} ({noise_count / total_n * 100:.1f}%)")

# ── P&L distribution by duration bucket ─────────────────────────────────────

dur_groups = [
    ("Short trades (0–5 min)",   lambda t: t["duration_mins"] is not None and t["duration_mins"] <= 5),
    ("Short trades (6–10 min)",  lambda t: t["duration_mins"] is not None and 5 < t["duration_mins"] <= 10),
    ("Longer trades (>10 min)",  lambda t: t["duration_mins"] is None or t["duration_mins"] > 10),
]

for group_label, group_fn in dur_groups:
    group = [t for t in trades if group_fn(t)]
    if not group:
        continue
    g_pcts = [t["pnl_pct"] for t in group]
    g_usd  = [t["pnl_usd"] for t in group]
    g_n = len(group)
    g_avg = sum(g_pcts) / g_n
    g_total_usd = sum(g_usd)
    g_wins = sum(1 for x in g_pcts if x > 0)
    durs = [t["duration_mins"] for t in group if t["duration_mins"] is not None]
    dur_note = f"  avg dur {sum(durs)/len(durs):.1f} min" if durs else ""
    usd_sign = '+' if g_total_usd >= 0 else ''

    print(f"\n\n── {group_label} ({g_n} trades, {g_n/total_n*100:.1f}% of total){dur_note} ────────────")
    print(f"   avg EV: {g_avg:+.3f}%/trade   win rate: {g_wins}/{g_n} = {g_wins/g_n*100:.0f}%   total P&L: {usd_sign}${g_total_usd:,.2f}")
    print(f"\n   {'Bucket':<22} {'Count':>6} {'%Group':>7}  {'AvgPnL%':>8}  {'WinRate':>8}")
    print('   ' + '-' * 54)
    for label, fn in buckets:
        matches = [x for x in g_pcts if fn(x)]
        if not matches:
            continue
        pct_g = len(matches) / g_n * 100
        avg = sum(matches) / len(matches)
        wins = sum(1 for x in matches if x > 0)
        wr = wins / len(matches) * 100
        flag = ' <-- NOISE' if label in noise_labels else ''
        print(f"     {label:<20} {len(matches):>6} {pct_g:>6.1f}%  {avg:>+8.3f}%  {wr:>6.0f}%{flag}")

# ── By Window ────────────────────────────────────────────────────────────────

print("\n\nBy Window:")
for win, pcts in sorted(windows.items()):
    noise = [x for x in pcts if -0.3 <= x <= 0.3]
    wins = [x for x in pcts if x > 0]
    avg = sum(pcts) / len(pcts)
    print(
        f"  {win}: {len(pcts)} trades"
        f" | noise(±0.3%): {len(noise)} ({len(noise) / len(pcts) * 100:.0f}%)"
        f" | win rate: {len(wins) / len(pcts) * 100:.0f}%"
        f" | avg EV: {avg:+.3f}%/trade"
    )

# ── By Exit Reason ───────────────────────────────────────────────────────────

print("\n\nBy Exit Reason:")
for reason, pcts in sorted(exit_reasons.items(), key=lambda x: -len(x[1])):
    noise = [x for x in pcts if -0.3 <= x <= 0.3]
    wins = [x for x in pcts if x > 0]
    avg = sum(pcts) / len(pcts)
    print(
        f"  {reason:<25} {len(pcts):>5} trades"
        f" | noise: {len(noise):>4} ({len(noise) / len(pcts) * 100:.0f}%)"
        f" | win rate: {len(wins) / len(pcts) * 100:.0f}%"
        f" | avg: {avg:+.3f}%"
    )

# ── Short-duration small-P&L trade analysis ──────────────────────────────────

SMALL_PCT = 0.3   # ±% threshold
SHORT_MIN = 15    # minutes threshold

small_all   = [t for t in trades if abs(t["pnl_pct"]) <= SMALL_PCT]
small_short = [t for t in small_all if t["duration_mins"] is not None and t["duration_mins"] <= SHORT_MIN]
small_long  = [t for t in small_all if t["duration_mins"] is None or t["duration_mins"] > SHORT_MIN]
large_trades = [t for t in trades if abs(t["pnl_pct"]) > SMALL_PCT]


def _stats(subset):
    pcts = [t["pnl_pct"] for t in subset]
    if not pcts:
        return 0, 0.0, 0, 0
    avg = sum(pcts) / len(pcts)
    wins = sum(1 for x in pcts if x > 0)
    losses = sum(1 for x in pcts if x <= 0)
    return len(pcts), avg, wins, losses


n_all, avg_all, w_all, l_all = _stats(small_all)
n_sh,  avg_sh,  w_sh,  l_sh  = _stats(small_short)
n_lg,  avg_lg,  w_lg,  l_lg  = _stats(small_long)
n_big, avg_big, w_big, l_big = _stats(large_trades)

# Hypothetical avg EV if the small-short trades were excluded
remaining = [t for t in trades if not (abs(t["pnl_pct"]) <= SMALL_PCT
             and t["duration_mins"] is not None and t["duration_mins"] <= SHORT_MIN)]
remaining_avg = sum(t["pnl_pct"] for t in remaining) / len(remaining) if remaining else 0.0

print(f"\n\n{'─' * 70}")
print(f"  SHORT-DURATION SMALL-P&L TRADE ANALYSIS")
print(f"  Thresholds: |P&L%| ≤ {SMALL_PCT}%  AND  duration ≤ {SHORT_MIN} min")
print(f"{'─' * 70}")

print(f"\n  Overall avg EV: {overall_avg:+.3f}%/trade  ({overall_wins}/{total_n} wins = {overall_wins / total_n * 100:.0f}% win rate)")

print(f"\n  ── All ±{SMALL_PCT}% trades (any duration) ──────────────────────────")
print(f"  Count    : {n_all:>4}  ({n_all / total_n * 100:.1f}% of {total_n} total trades)")
if n_all:
    print(f"  Win rate : {w_all}/{n_all} = {w_all / n_all * 100:.0f}%")
    print(f"  Avg EV   : {avg_all:+.3f}%/trade  (vs {overall_avg:+.3f}% overall)")

print(f"\n  ── ±{SMALL_PCT}% AND ≤{SHORT_MIN} min  (short quick trades) ────────────────")
print(f"  Count    : {n_sh:>4}  ({n_sh / total_n * 100:.1f}% of {total_n} total trades)")
if n_sh:
    durs = [t["duration_mins"] for t in small_short]
    print(f"  Win rate : {w_sh}/{n_sh} = {w_sh / n_sh * 100:.0f}%")
    print(f"  Avg EV   : {avg_sh:+.3f}%/trade  (vs {overall_avg:+.3f}% overall)")
    print(f"  Avg dur  : {sum(durs) / len(durs):.1f} min  (range {min(durs)}–{max(durs)} min)")
    print(f"  If excluded, remaining avg EV: {remaining_avg:+.3f}%/trade over {len(remaining)} trades")

print(f"\n  ── ±{SMALL_PCT}% AND >{SHORT_MIN} min  (slow drifters) ──────────────────")
print(f"  Count    : {n_lg:>4}  ({n_lg / total_n * 100:.1f}% of {total_n} total trades)")
if n_lg:
    print(f"  Win rate : {w_lg}/{n_lg} = {w_lg / n_lg * 100:.0f}%")
    print(f"  Avg EV   : {avg_lg:+.3f}%/trade")

print(f"\n  ── >±{SMALL_PCT}% trades  (real movers) ─────────────────────────────")
print(f"  Count    : {n_big:>4}  ({n_big / total_n * 100:.1f}% of {total_n} total trades)")
if n_big:
    print(f"  Win rate : {w_big}/{n_big} = {w_big / n_big * 100:.0f}%")
    print(f"  Avg EV   : {avg_big:+.3f}%/trade  ← where the edge actually lives")

# Duration breakdown of all small trades
if small_all:
    dur_buckets = [("≤5 min",   lambda d: d is not None and d <= 5),
                   ("6–10 min", lambda d: d is not None and 5 < d <= 10),
                   ("11–15 min",lambda d: d is not None and 10 < d <= 15),
                   (">15 min",  lambda d: d is not None and d > 15),
                   ("unknown",  lambda d: d is None)]
    print(f"\n  Duration breakdown of all ±{SMALL_PCT}% trades:")
    for label, fn in dur_buckets:
        bucket = [t for t in small_all if fn(t["duration_mins"])]
        if bucket:
            avp = sum(t["pnl_pct"] for t in bucket) / len(bucket)
            wr = sum(1 for t in bucket if t["pnl_pct"] > 0) / len(bucket) * 100
            print(f"    {label:<12}: {len(bucket):>4} trades  avg {avp:>+.3f}%  win rate {wr:.0f}%")

print(f"\n  ── Executability Note ────────────────────────────────────────────")
print(f"  Options bid-ask spreads typically consume 0.5–2%+ of the option price.")
print(f"  Trades within ±{SMALL_PCT}% over ≤{SHORT_MIN} min are within spread noise:")
print(f"  a backtest +0.1% win often becomes a live −0.5% loss after slippage.")
print(f"  The {n_sh} short-quick trades avg {avg_sh:+.3f}%/trade in backtest; in live they")
est_live_drag = 0.4  # rough round-trip spread cost
print(f"  likely average ~{avg_sh - est_live_drag:+.2f}% after ~{est_live_drag:.1f}% round-trip spread.")
print(f"  The real edge comes from the {n_big} large-move trades (+{SMALL_PCT}%) that avg {avg_big:+.3f}%.")
print(f"{'─' * 70}")

# ── Large-mover P&L breakdown ────────────────────────────────────────────────

if n_big and portfolio_cap_pnl is not None and overall_avg != 0:
    # Calibration: K maps (avg_ev × n_trades) → portfolio_return_pct
    # This holds exactly under equal capital per trade; it's an approximation otherwise.
    K = portfolio_return_pct / (overall_avg * total_n)
    est_large_return = K * avg_big * n_big
    est_noise_drag   = K * avg_all * n_all  # noise trades' contribution under same assumption

    large_wins_pcts  = [t["pnl_pct"] for t in large_trades if t["pnl_pct"] > 0]
    large_loss_pcts  = [t["pnl_pct"] for t in large_trades if t["pnl_pct"] <= 0]
    avg_win  = sum(large_wins_pcts) / len(large_wins_pcts) if large_wins_pcts else 0.0
    avg_loss = sum(large_loss_pcts) / len(large_loss_pcts) if large_loss_pcts else 0.0

    large_by_window = defaultdict(list)
    large_by_exit   = defaultdict(list)
    for t in large_trades:
        large_by_window[t["window"]].append(t["pnl_pct"])
        large_by_exit[t["exit_reason"]].append(t["pnl_pct"])

    print(f"\n\n{'━' * 70}")
    print(f"  LARGE-MOVER TRADES ONLY  (|P&L%| > {SMALL_PCT}%)")
    print(f"{'━' * 70}")
    print(f"\n  Count    : {n_big} trades  ({n_big / total_n * 100:.1f}% of {total_n} total)")
    print(f"  Win rate : {w_big}/{n_big} = {w_big / n_big * 100:.0f}%")
    print(f"  Avg EV   : {avg_big:+.3f}%/trade")
    print(f"  Avg win  : {avg_win:+.3f}%   Avg loss: {avg_loss:+.3f}%")

    print(f"\n  Estimated portfolio return (large movers only): ~{est_large_return:+.1f}%")
    print(f"  Actual portfolio return    (all trades):          {portfolio_return_pct:+.2f}%")
    print(f"  Estimated noise drag:                            ~{est_noise_drag:+.1f}%")
    print(f"  (Estimate assumes equal capital per trade — actual varies by rank/window)")

    print(f"\n  By Window (large movers only):")
    for win, pcts in sorted(large_by_window.items()):
        wins = sum(1 for x in pcts if x > 0)
        avg = sum(pcts) / len(pcts)
        print(
            f"    {win}: {len(pcts):>4} trades"
            f" | win rate: {wins / len(pcts) * 100:.0f}%"
            f" | avg EV: {avg:+.3f}%/trade"
        )

    print(f"\n  By Exit Reason (large movers only):")
    for reason, pcts in sorted(large_by_exit.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for x in pcts if x > 0)
        avg = sum(pcts) / len(pcts)
        print(
            f"    {reason:<25} {len(pcts):>4} trades"
            f" | win rate: {wins / len(pcts) * 100:.0f}%"
            f" | avg: {avg:+.3f}%"
        )
    print(f"{'━' * 70}")
