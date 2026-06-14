#!/usr/bin/env bash
# run_phase1_qqq10_r2k10_feb_may_2026.sh
#
# Phase 1 — Ticker Set Selection Experiment
# Pool: QQQ top-10 + R2K top-10 by 2025 avg dollar volume (50/50)
#   QQQ: NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX
#   R2K: HOOD SOFI SMCI HIMS IONQ MARA RIOT ASTS RKLB JOBY
# Dates: Feb 2026 + May 2026 (initial characteristics test)
# Config: M1 09:30/3 | win-rate | regime-engine | regime-hold
#         stop-pct 0 | trailing-ma none | top 8 | $80k
#
# Usage:
#   ./run_phase1_qqq10_r2k10_feb_may_2026.sh
#   ./run_phase1_qqq10_r2k10_feb_may_2026.sh --summary
#   ./run_phase1_qqq10_r2k10_feb_may_2026.sh --force

set -euo pipefail

PYTHONPATH_DIR="/Users/victorhuang/work/alpha_tech_tracker"
LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs/replay_phase1_qqq10_r2k10_feb_may_2026"
MAX_PARALLEL=20
SUMMARY_ONLY=false
FORCE=false
CAPITAL=80000
FEED="sip"
STOP_PCT=0
EXTEND_COLLECTION_BARS=2

while [ $# -gt 0 ]; do
  case "$1" in
    --summary) SUMMARY_ONLY=true; shift ;;
    --force)   FORCE=true;        shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# QQQ top-10 (2025 actives) + R2K top-10 (2025 actives)
TICKERS="NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX HOOD SOFI SMCI HIMS IONQ MARA RIOT ASTS RKLB JOBY"

# ---------------------------------------------------------------------------
# Feb + May 2026 trading days (NYSE holidays applied)
# ---------------------------------------------------------------------------
generate_trading_days() {
  python3 -c "
from datetime import date, timedelta

holidays = {
    date(2026,1,1), date(2026,1,19), date(2026,2,16),
    date(2026,4,3), date(2026,5,25), date(2026,6,19),
    date(2026,7,3), date(2026,9,7), date(2026,11,26), date(2026,12,25),
}

today = date.today()
months = [(2026, 2), (2026, 5)]
for year, month in months:
    if month == 2:
        end_day = 28
    elif month in (4, 6, 9, 11):
        end_day = 30
    else:
        end_day = 31
    start = date(year, month, 1)
    end   = date(year, month, end_day)
    if end > today:
        end = today
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            print(str(d))
        d += timedelta(days=1)
"
}

# ---------------------------------------------------------------------------
# Replay a single date
# ---------------------------------------------------------------------------
replay_one() {
  local DATE="$1"
  local LOG="$LOG_DIR/$DATE.log"
  PYTHONPATH="$PYTHONPATH_DIR" \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    --log-level DEBUG \
    --trade-type stock \
    --tickers $TICKERS \
    --selector win-rate \
    --enable-regime-engine \
    --window M1 09:30 3 \
    --morning-split 100 \
    --top 8 --capital $CAPITAL \
    --stop-pct $STOP_PCT \
    --trailing-ma none \
    --regime-hold \
    --extend-collection-bars $EXTEND_COLLECTION_BARS \
    --mock-trade-execution \
    --feed "$FEED" \
    --replay-date "$DATE" > "$LOG" 2>&1
}

# ---------------------------------------------------------------------------
# P&L summary: per-day + monthly + total
# ---------------------------------------------------------------------------
print_summary() {
  python3 - "$LOG_DIR" "$CAPITAL" <<'PYEOF'
import math, os, re, sys
from datetime import date

log_dir = sys.argv[1]
capital = float(sys.argv[2])

results  = {}
deployed = {}
for fname in sorted(os.listdir(log_dir)):
    if not re.match(r'\d{4}-\d{2}-\d{2}\.log$', fname):
        continue
    d_str = fname.replace('.log', '')
    with open(os.path.join(log_dir, fname)) as f:
        for line in f:
            m = re.search(r'cap:\s*([+-]?\$[\d,.]+)', line)
            if m:
                results[d_str] = float(m.group(1).replace('$','').replace(',',''))
            md = re.search(r'\$(\d[\d,]*)\s+deployed', line)
            if md:
                deployed[d_str] = float(md.group(1).replace(',',''))

months = {}
for d_str, pnl in results.items():
    mkey = d_str[:7]
    months[mkey] = months.get(mkey, 0.0) + pnl

month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
print()
print("── MONTHLY ─────────────────────────────────────────────────────")
grand_total = 0.0
for mkey in sorted(months.keys()):
    mp = months[mkey]
    sign = "+" if mp >= 0 else ""
    m_idx = int(mkey.split('-')[1]) - 1
    print(f"  {month_names[m_idx]} {mkey.split('-')[0]}   {sign}${mp:>9,.2f}   ({sign}{mp/capital*100:.1f}%)")
    grand_total += mp

total_days = len(results)
total_dep  = sum(deployed.get(d, 0.0) for d in results)
avg_dep    = total_dep / total_days if total_days else 0.0
util       = total_dep / (total_days * capital) if total_days else 0.0

print()
print("── TOTAL ───────────────────────────────────────────────────────")
sign = "+" if grand_total >= 0 else ""
print(f"  Feb+May total    {total_days} days   {sign}${grand_total:,.2f}   ({sign}{grand_total/capital*100:.1f}% on ${capital:,.0f})")
print(f"  Avg deployed/day : ${avg_dep:,.0f}   Utilization: {util*100:.1f}%")

days_with_dep = [(results[d], deployed[d]) for d in results if deployed.get(d, 0.0) > 0]
if days_with_dep:
    rodcs = [p / d for p, d in days_with_dep]
    mean_rodc = sum(rodcs) / len(rodcs) * 100
    print(f"  Mean daily RODC  : {mean_rodc:+.3f}%")
    if len(days_with_dep) >= 2:
        deps = [d for _, d in days_with_dep]
        avg_d = sum(deps) / len(deps)
        w = [d / avg_d for d in deps]
        w_sum = sum(w)
        w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
        w_var  = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
        w_std  = math.sqrt(w_var) if w_var > 0 else 0.0
        if w_std > 0:
            print(f"  DW-Sharpe        : {w_mean / w_std * math.sqrt(252):.2f}")

print(f"  Logs complete    : {len(results)} / {total_days} dates")
print()
PYEOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if $SUMMARY_ONLY; then
  print_summary
  exit 0
fi

mkdir -p "$LOG_DIR"

ALL_DATES=()
while IFS= read -r line; do
  ALL_DATES+=("$line")
done < <(generate_trading_days)

TODO=()
for DATE in "${ALL_DATES[@]}"; do
  if $FORCE || [ ! -f "$LOG_DIR/$DATE.log" ]; then
    TODO+=("$DATE")
  else
    echo "  skip $DATE (log exists)"
  fi
done

echo ""
echo "=== Phase 1: QQQ-10 + R2K-10 (2025 actives) — Feb + May 2026 ==="
echo "    Pool (20): $TICKERS"
echo "    Config   : M1 win-rate | regime-hold | top8 | \$${CAPITAL} | feed=${FEED}"
echo "    Total dates : ${#ALL_DATES[@]}"
echo "    To run      : ${#TODO[@]}"
echo "    Max parallel: $MAX_PARALLEL"
echo "    Log dir     : $LOG_DIR"
echo ""

if [ ${#TODO[@]} -eq 0 ]; then
  echo "All dates already complete — printing summary."
  print_summary
  exit 0
fi

i=0
total_todo=${#TODO[@]}
while [ $i -lt $total_todo ]; do
  batch=("${TODO[@]:$i:$MAX_PARALLEL}")
  last_idx=$((${#batch[@]}-1))
  echo "--- Batch $((i/MAX_PARALLEL + 1)): ${batch[0]} → ${batch[$last_idx]} (${#batch[@]} dates) ---"
  PIDS=()
  for DATE in "${batch[@]}"; do
    replay_one "$DATE" &
    PIDS+=($!)
    echo "  started $DATE (pid $!)"
  done
  for j in "${!PIDS[@]}"; do
    if wait "${PIDS[$j]}"; then
      echo "  OK  ${batch[$j]}"
    else
      echo "  ERR ${batch[$j]} (exit $?)"
    fi
  done
  i=$((i + ${#batch[@]}))
  echo ""
done

echo "=== All replays complete ==="
echo ""
print_summary
