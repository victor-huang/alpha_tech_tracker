#!/usr/bin/env bash
# run_replay_2026_qqq10_r2k10.sh
#
# Full-year 2026 replay — QQQ-10 + R2K-10 ticker pool (2025 most-active)
#   QQQ: NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX
#   R2K: HOOD SOFI SMCI HIMS IONQ MARA RIOT ASTS RKLB JOBY
# Config: M1 09:30/3 | win-rate | regime-engine | regime-hold
#         stop-pct 0 | trailing-ma none | top 8 | $80k capital
#
# Usage:
#   ./run_replay_2026_qqq10_r2k10.sh
#   ./run_replay_2026_qqq10_r2k10.sh --summary
#   ./run_replay_2026_qqq10_r2k10.sh --force

set -euo pipefail

PYTHONPATH_DIR="/Users/victorhuang/work/alpha_tech_tracker"
LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2026_qqq10_r2k10_m1_winrate_regimehold_cap80k"
MAX_PARALLEL=20
SUMMARY_ONLY=false
FORCE=false
YEAR=2026
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

TICKERS="NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX HOOD SOFI SMCI HIMS IONQ MARA RIOT ASTS RKLB JOBY"

# ---------------------------------------------------------------------------
# Generate 2026 trading days
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
start = date(2026, 1, 1)
end   = date(2026, 12, 31)
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
# P&L summary: weekly + monthly + yearly
# ---------------------------------------------------------------------------
print_summary() {
  python3 - "$LOG_DIR" "$YEAR" "$CAPITAL" <<'PYEOF'
import math, os, re, sys
from datetime import date, timedelta

log_dir = sys.argv[1]
year    = sys.argv[2]
capital = float(sys.argv[3])

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

if not results:
    print("No completed logs found.")
    sys.exit(0)

weeks  = {}
months = {}
for d_str, pnl in sorted(results.items()):
    d = date.fromisoformat(d_str)
    week_start = d - timedelta(days=d.weekday())
    wkey = str(week_start)
    if wkey not in weeks:
        weeks[wkey] = {"days": [], "pnl": 0.0}
    weeks[wkey]["days"].append((d_str, pnl))
    weeks[wkey]["pnl"] += pnl
    mkey = d.strftime("%Y-%m")
    months[mkey] = months.get(mkey, 0.0) + pnl

total_days = sum(len(w["days"]) for w in weeks.values())

print()
print(f"=== {year} — QQQ-10 + R2K-10 (2025 actives) | M1 win-rate | regime-hold | top8 | ${capital:,.0f} ===")
print()

print("── WEEKLY ──────────────────────────────────────────────────────")
for key in sorted(weeks.keys()):
    w = weeks[key]
    n = len(w["days"])
    sign = "+" if w["pnl"] >= 0 else ""
    print(f"  Week of {key}  ({n}d)   {sign}${w['pnl']:>9,.2f}")
    for d_str, pnl in w["days"]:
        day_name = date.fromisoformat(d_str).strftime("%a")
        sign2 = "+" if pnl >= 0 else ""
        print(f"      {d_str} {day_name}   {sign2}${pnl:>8,.2f}")

print()
print("── MONTHLY ─────────────────────────────────────────────────────")
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
year_total = 0.0
for mkey in sorted(months.keys()):
    mp = months[mkey]
    sign = "+" if mp >= 0 else ""
    m_idx = int(mkey.split('-')[1]) - 1
    print(f"  {month_names[m_idx]} {mkey.split('-')[0]}   {sign}${mp:>9,.2f}   ({sign}{mp/capital*100:.1f}%)")
    year_total += mp

print()
print("── YEARLY ──────────────────────────────────────────────────────")
sign = "+" if year_total >= 0 else ""
total_dep = sum(deployed.get(d, 0.0) for d in results)
avg_dep = total_dep / total_days if total_days else 0.0
ret_on_deployed = year_total / avg_dep * 100 if avg_dep > 0 else 0.0
ret_sign = "+" if ret_on_deployed >= 0 else ""
print(f"  {year} TOTAL   {total_days} days   {sign}${year_total:,.2f}   ({sign}{year_total/capital*100:.1f}% on ${capital:,.0f})")
print(f"  Logs complete: {len(results)} / {total_days} trading days")

days_with_dep = [(results[d], deployed[d]) for d in results if deployed.get(d, 0.0) > 0]
util = total_dep / (total_days * capital) if total_days else 0.0
pnl_per_dollar = year_total / total_dep if total_dep > 0 else 0.0
mean_rodc_str = "n/a"
dw_sharpe_str = "n/a"
if days_with_dep:
    rodcs = [p / d for p, d in days_with_dep]
    mean_rodc_str = f"{sum(rodcs) / len(rodcs) * 100:+.3f}%"
    if len(days_with_dep) >= 2:
        deps = [d for _, d in days_with_dep]
        avg_d = sum(deps) / len(deps)
        w = [d / avg_d for d in deps]
        w_sum = sum(w)
        w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
        w_var  = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
        w_std  = math.sqrt(w_var) if w_var > 0 else 0.0
        if w_std > 0:
            dw_sharpe_str = f"{w_mean / w_std * math.sqrt(252):.2f}"
pnl_sign = "+" if pnl_per_dollar >= 0 else ""
print()
print("── DEPLOYMENT METRICS ──────────────────────────────────────────")
print(f"  Total deployed       : ${total_dep:,.0f}")
print(f"  Capital utilization  : {util*100:.1f}%  (avg daily / ${capital:,.0f})")
print(f"  P&L per $ deployed   : {pnl_sign}{pnl_per_dollar:.4f}  (cumulative)")
print(f"  Mean daily RODC      : {mean_rodc_str}")
print(f"  DW-Sharpe            : {dw_sharpe_str}")
print()
PYEOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"

if $SUMMARY_ONLY; then
  print_summary
  exit 0
fi

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
echo "=== 2026 replay — QQQ-10 + R2K-10 | M1 win-rate | regime-hold | top8 | \$${CAPITAL} ==="
echo "    Pool: $TICKERS"
echo "    Total trading days : ${#ALL_DATES[@]}"
echo "    To run             : ${#TODO[@]}"
echo "    Max parallel       : $MAX_PARALLEL"
echo "    Log dir            : $LOG_DIR"
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
