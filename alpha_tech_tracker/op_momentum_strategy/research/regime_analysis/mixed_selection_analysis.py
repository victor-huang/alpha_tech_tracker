"""
Mixed selection simulation — all years 2016-2026:
  - LONG months : top-3 qualifying signals by pre-session 20d EOD WR (highest rank)
  - SHORT months: bottom-3 qualifying signals by pre-session 20d EOD WR (lowest rank)

Also computes all-top-3 strategy P&L dynamically for comparison.
Directions for 2016/2017 determined from regime analysis docs.
"""

import re, os
from collections import defaultdict

HOLD_LABELS = ['+15m', '+30m', '+45m', '+1h', '+1h30m', '+2h', '+3h', '+4h', '+5h', '+6h', '+7h', 'EOD']
MONTHS_LBL  = {'01':'Jan','02':'Feb','03':'Mar','04':'Apr','05':'May','06':'Jun',
               '07':'Jul','08':'Aug','09':'Sep','10':'Oct','11':'Nov','12':'Dec'}

# ── Direction lookup ───────────────────────────────────────────────────────
# SHORT months: strategy direction is SHORT → bottom-3 selection for mixed sim
SHORT_MONTHS = {
    # 2016: Sep seasonal, Nov avg-gain flip, Dec seasonal
    (2016, '09'), (2016, '11'), (2016, '12'),
    # 2017: Apr WR>40% in v2 → LONG (no flip); Sep EV exception revoked → SHORT; Dec seasonal
    (2017, '09'), (2017, '12'),
    # 2018
    (2018, '09'), (2018, '12'),
    # 2019
    (2019, '12'),
    # 2020
    (2020, '09'), (2020, '12'),
    # 2021
    (2021, '09'), (2021, '11'), (2021, '12'),
    # 2022 — full bear year
    (2022, '01'), (2022, '02'), (2022, '04'), (2022, '05'), (2022, '09'), (2022, '12'),
    # 2023
    (2023, '09'), (2023, '12'),
    # 2024
    (2024, '09'), (2024, '12'),
    # 2025
    (2025, '09'), (2025, '12'),
}

# Partial-confidence credits (default 1.0)
SHORT_CREDITS = {
    (2016, '11'): 0.70,   # avg gain ≤ 0 → 70% credit
    (2017, '04'): 0.70,   # WR < 40% flip → 70% credit
    (2021, '11'): 0.70,
    (2022, '01'): 0.60,
    (2022, '04'): 0.70,
}

# LONG months that exit at +15m instead of EOD
LONG_15M_EXIT = (
    {(y, '03') for y in range(2016, 2027)} |   # March: CAUTION every year
    {(y, '08') for y in range(2016, 2026)}      # Aug: early-exit rule
)


def parse_pct(s):
    return float(re.sub(r'[%WL]', '', s))

def is_win(s):
    return s.endswith('W')

def parse_log(filepath):
    daily_ranks   = {}
    daily_signals = defaultdict(dict)
    with open(filepath) as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.search(r'Pre-session top-2.*—\s+(\d{4}-\d{2}-\d{2})', line)
        if m:
            date = m.group(1)
            ranks, j, in_table = [], i + 1, False
            while j < len(lines):
                l = lines[j].rstrip()
                if re.match(r'\s+Ticker\s+N\s+', l):
                    in_table = True
                    j += 1
                    if j < len(lines) and re.match(r'\s+-{5,}', lines[j]):
                        j += 1
                    continue
                if in_table:
                    tm = re.match(r'\s{2}([A-Z]+)\s+\d+\s+', l)
                    if tm:
                        ranks.append(tm.group(1))
                        j += 1
                        continue
                    else:
                        break
                j += 1
            daily_ranks[date] = ranks
            i += 1
            continue
        sm = re.match(
            r'^(\d{4}-\d{2}-\d{2})\s+([A-Z]+)\s+09:30/3b\s+\S+\s+[\d.]+\s+[\d.]+x\s+(.+)$',
            line
        )
        if sm:
            date, ticker, rest = sm.group(1), sm.group(2), sm.group(3).split()
            sig = {}
            for k, label in enumerate(HOLD_LABELS):
                if k < len(rest):
                    sig[label]          = parse_pct(rest[k])
                    sig[label + '_win'] = is_win(rest[k])
            daily_signals[date][ticker] = sig
        i += 1
    return daily_ranks, daily_signals


def select_and_aggregate(daily_ranks, daily_signals, is_short, top_n=3):
    selected = []
    for date in sorted(daily_signals.keys()):
        fired      = daily_signals[date]
        rank_order = daily_ranks.get(date, [])
        if is_short:
            ranked_fired = [t for t in reversed(rank_order) if t in fired]
        else:
            ranked_fired = [t for t in rank_order if t in fired]
        unranked = [t for t in fired if t not in rank_order]
        picks    = (ranked_fired + unranked)[:top_n]
        for t in picks:
            selected.append(fired[t])

    if not selected:
        return {}
    stats = {}
    for label in HOLD_LABELS:
        vals = [s[label] for s in selected if label in s]
        if not vals:
            continue
        wins = sum(1 for s in selected if s.get(label + '_win', False))
        stats[label] = {
            'count': len(vals),
            'wr':    100 * wins / len(vals),
            'sum':   sum(vals),
            'avg':   sum(vals) / len(vals),
        }
    return stats


def compute_strategy_pnl(year, mon_str, stats):
    key  = (year, mon_str)
    eod  = stats.get('EOD', {}).get('sum', 0.0)
    p15m = stats.get('+15m', {}).get('sum', 0.0)
    if key in SHORT_MONTHS:
        return -eod * SHORT_CREDITS.get(key, 1.0)
    elif key in LONG_15M_EXIT:
        return p15m
    else:
        return eod


# ── Build results ──────────────────────────────────────────────────────────
LOG_BASE = '/Users/victorhuang/work/alpha_tech_tracker/logs'

YEARS_MONTHS = {y: [f'{m:02d}' for m in range(1, 13)] for y in range(2016, 2026)}
YEARS_MONTHS[2026] = ['01', '02', '03', '04', '05']

def log_path(year, month_str):
    # All years: use v2 logs (bug-fixed screener)
    # 2023-2025: v1 was overwritten, _v2.log files also exist (identical data)
    return f'{LOG_BASE}/{year}_monthly_screener/{month_str}_v2.log'


top3_results   = {}   # (year, mon) -> stats (always top-3 selection)
mixed_results  = {}   # (year, mon) -> stats (top-3 LONG, bottom-3 SHORT)
top3_strategy  = {}   # (year, mon) -> strategy P&L from top-3
mixed_strategy = {}   # (year, mon) -> strategy P&L from mixed

for year, months in YEARS_MONTHS.items():
    for mon in months:
        month_str = f'{year}-{mon}'
        path      = log_path(year, month_str)
        if not os.path.exists(path):
            continue
        daily_ranks, daily_signals = parse_log(path)
        is_short = (year, mon) in SHORT_MONTHS

        t3_stats = select_and_aggregate(daily_ranks, daily_signals, is_short=False)
        mx_stats = select_and_aggregate(daily_ranks, daily_signals, is_short=is_short)

        if t3_stats:
            top3_results[(year, mon)]  = t3_stats
            top3_strategy[(year, mon)] = compute_strategy_pnl(year, mon, t3_stats)
        if mx_stats:
            mixed_results[(year, mon)]  = mx_stats
            mixed_strategy[(year, mon)] = compute_strategy_pnl(year, mon, mx_stats)


def direction_label(year, mon):
    key = (year, mon)
    if key in SHORT_MONTHS:
        sel = 'BOTTOM-3'
        if key in SHORT_CREDITS:
            sel += f' ({int(SHORT_CREDITS[key]*100)}% cr)'
        return f'SHORT  {sel}'
    elif key in LONG_15M_EXIT:
        return 'LONG   TOP-3   +15m'
    else:
        return 'LONG   TOP-3   EOD'


# ── Per-year detail ────────────────────────────────────────────────────────
print('=' * 115)
print('Mixed Top-3/Bottom-3 vs All-Top-3 — 2016 to 2026')
print('=' * 115)

for year in sorted(set(y for y, _ in mixed_results)):
    yr_mx = 0.0
    yr_t3 = 0.0
    print(f'\n### {year}')
    print(f'  {"Month":<7} {"Direction":<30} {"Mixed":>8} {"Top3":>8} {"Δ":>7}  '
          f'{"Mx EOD":>8} {"T3 EOD":>8} {"Mx WR":>7}')
    print(f'  {"-"*7} {"-"*30} {"-"*8} {"-"*8} {"-"*7}  {"-"*8} {"-"*8} {"-"*7}')
    months = YEARS_MONTHS.get(year, [])
    for mon in months:
        key = (year, mon)
        if key not in mixed_results:
            continue
        mx_strat = mixed_strategy.get(key, 0.0)
        t3_strat = top3_strategy.get(key, 0.0)
        delta    = mx_strat - t3_strat
        mx_eod   = mixed_results[key].get('EOD', {}).get('sum', 0.0)
        t3_eod   = top3_results[key].get('EOD', {}).get('sum', 0.0) if key in top3_results else 0.0
        mx_wr    = mixed_results[key].get('EOD', {}).get('wr', 0.0)
        flag     = ' ⚡' if abs(delta) >= 5 else ''
        print(f'  {MONTHS_LBL[mon]:<7} {direction_label(year, mon):<30} '
              f'{mx_strat:>+7.1f}% {t3_strat:>+7.1f}% {delta:>+6.1f}pp{flag}  '
              f'{mx_eod:>+7.2f}% {t3_eod:>+7.2f}% {mx_wr:>6.1f}%')
        yr_mx += mx_strat
        yr_t3  += t3_strat
    print(f'  {"YEAR TOTAL":<39} {yr_mx:>+7.1f}% {yr_t3:>+7.1f}% {yr_mx-yr_t3:>+6.1f}pp')


# ── Yearly summary ─────────────────────────────────────────────────────────
print('\n')
print('=' * 75)
print('Yearly Summary — Mixed vs All-Top-3')
print('=' * 75)
print(f'  {"Year":<6} {"Mixed Strat":>13} {"Top3 Strat":>12} {"Δ":>10} '
      f'{"Mx PureLong":>13} {"T3 PureLong":>12}')
print(f'  {"-"*6} {"-"*13} {"-"*12} {"-"*10} {"-"*13} {"-"*12}')

grand_mx = grand_t3 = grand_mx_pl = grand_t3_pl = 0.0
for year in sorted(set(y for y, _ in mixed_results)):
    months = YEARS_MONTHS.get(year, [])
    yr_mx  = sum(mixed_strategy.get((year, m), 0.0) for m in months if (year, m) in mixed_results)
    yr_t3  = sum(top3_strategy.get((year, m),  0.0) for m in months if (year, m) in top3_results)
    yr_mx_pl = sum(mixed_results[(year, m)].get('EOD', {}).get('sum', 0.0)
                   for m in months if (year, m) in mixed_results)
    yr_t3_pl = sum(top3_results[(year, m)].get('EOD', {}).get('sum', 0.0)
                   for m in months if (year, m) in top3_results)
    print(f'  {year:<6} {yr_mx:>+11.1f}% {yr_t3:>+10.1f}% {yr_mx-yr_t3:>+9.1f}pp '
          f'{yr_mx_pl:>+11.1f}% {yr_t3_pl:>+10.1f}%')
    grand_mx   += yr_mx;  grand_t3   += yr_t3
    grand_mx_pl += yr_mx_pl; grand_t3_pl += yr_t3_pl

print(f'  {"TOTAL":<6} {grand_mx:>+11.1f}% {grand_t3:>+10.1f}% '
      f'{grand_mx-grand_t3:>+9.1f}pp {grand_mx_pl:>+11.1f}% {grand_t3_pl:>+10.1f}%')


# ── SHORT-month deep dive ──────────────────────────────────────────────────
print('\n')
print('=' * 85)
print('SHORT-month deep-dive: bottom-3 vs top-3 (✓ = bottom-3 more negative EOD = better short)')
print('=' * 85)
print(f'  {"Month":<10} {"B3 EOD":>9} {"T3 EOD":>9} {"Δ EOD":>8}  '
      f'{"B3 Strat":>10} {"T3 Strat":>10} {"Δ Strat":>9}')
print(f'  {"-"*10} {"-"*9} {"-"*9} {"-"*8}  {"-"*10} {"-"*10} {"-"*9}')

for year in sorted(set(y for y, _ in mixed_results)):
    for mon in YEARS_MONTHS.get(year, []):
        key = (year, mon)
        if key not in SHORT_MONTHS or key not in mixed_results:
            continue
        b3_eod   = mixed_results[key].get('EOD', {}).get('sum', 0.0)
        t3_eod   = top3_results[key].get('EOD', {}).get('sum', 0.0) if key in top3_results else float('nan')
        b3_strat = mixed_strategy[key]
        t3_strat = top3_strategy.get(key, float('nan'))
        better   = '✓' if b3_eod < t3_eod else ' '
        print(f'  {year}-{MONTHS_LBL[mon]:<7} {b3_eod:>+8.2f}% {t3_eod:>+8.2f}% '
              f'{b3_eod-t3_eod:>+7.2f}pp{better}  '
              f'{b3_strat:>+8.1f}%  {t3_strat:>+8.1f}%  {b3_strat-t3_strat:>+7.1f}pp')
