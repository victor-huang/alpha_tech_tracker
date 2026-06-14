#!/usr/bin/env bash
# Custom replay: M1 09:30/1 + A1 10:30/6 | stop-pct 0.1 | reversal | top2 | weights 60/40
# Date range: 2026-01-01 → 2026-05-13

set -euo pipefail

PYTHONPATH_DIR="/Users/victorhuang/work/alpha_tech_tracker"
MAX_PARALLEL=20
FORCE=false
SUMMARY_ONLY=false
YEAR=""
START_DATE=""
END_DATE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --year)    YEAR="$2";       shift 2 ;;
    --start)   START_DATE="$2"; shift 2 ;;
    --end)     END_DATE="$2";   shift 2 ;;
    --force)   FORCE=true;      shift ;;
    --summary) SUMMARY_ONLY=true; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$YEAR" ]; then
  echo "Usage: $0 --year YYYY [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--force] [--summary]"
  exit 1
fi

if [ -z "$START_DATE" ]; then START_DATE="${YEAR}-01-01"; fi
if [ -z "$END_DATE" ];   then END_DATE="${YEAR}-12-31";   fi

LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs/replay_${YEAR}_M1_0930_1_A1_1030_6_stop10"

generate_trading_days() {
  python3 -c "
from datetime import date, timedelta

holidays = {
    date(2019,1,1), date(2019,1,21), date(2019,2,18),
    date(2019,4,19), date(2019,5,27), date(2019,7,4),
    date(2019,9,2), date(2019,11,28), date(2019,12,25),
    date(2020,1,1), date(2020,1,20), date(2020,2,17),
    date(2020,4,10), date(2020,5,25), date(2020,7,3),
    date(2020,9,7), date(2020,11,26), date(2020,12,25),
    date(2021,1,1), date(2021,1,18), date(2021,2,15),
    date(2021,4,2), date(2021,5,31), date(2021,7,5),
    date(2021,9,6), date(2021,11,25), date(2021,12,24),
    date(2022,1,17), date(2022,2,21), date(2022,4,15),
    date(2022,5,30), date(2022,6,19), date(2022,7,4),
    date(2022,9,5), date(2022,11,24), date(2022,12,26),
    date(2023,1,2), date(2023,1,16), date(2023,2,20),
    date(2023,4,7), date(2023,5,29), date(2023,6,19),
    date(2023,7,4), date(2023,9,4), date(2023,11,23), date(2023,12,25),
    date(2024,1,1), date(2024,1,15), date(2024,2,19),
    date(2024,3,29), date(2024,5,27), date(2024,6,19),
    date(2024,7,4), date(2024,9,2), date(2024,11,28), date(2024,12,25),
    date(2025,1,1), date(2025,1,20), date(2025,2,17),
    date(2025,4,18), date(2025,5,26), date(2025,6,19),
    date(2025,7,4), date(2025,9,1), date(2025,11,27), date(2025,12,25),
    date(2026,1,1), date(2026,1,19), date(2026,2,16),
    date(2026,4,3), date(2026,5,25), date(2026,6,19),
    date(2026,7,3), date(2026,9,7), date(2026,11,26), date(2026,12,25),
}

start = date.fromisoformat('$START_DATE')
end   = date.fromisoformat('$END_DATE')

d = start
while d <= end:
    if d.weekday() < 5 and d not in holidays:
        print(str(d))
    d += timedelta(days=1)
"
}

replay_one() {
  local DATE="$1"
  local LOG="$LOG_DIR/$DATE.log"
  PYTHONPATH="$PYTHONPATH_DIR" \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    --log-level DEBUG \
    --trade-type stock \
    --window M1 09:30 1 \
    --window A1 10:30 6 \
    --morning-split 100 \
    --reversal \
    --rank-weighted-sizing 60 40 \
    --stop-pct 0.1 \
    --top 2 --capital 10000 \
    --mock-trade-execution \
    --feed sip \
    --replay-date "$DATE" > "$LOG" 2>&1
}

print_summary() {
  python3 - "$LOG_DIR" <<'PYEOF'
import os, re, sys
from datetime import date, timedelta

log_dir = sys.argv[1]

results = {}
for fname in sorted(os.listdir(log_dir)):
    if not re.match(r'\d{4}-\d{2}-\d{2}\.log$', fname):
        continue
    d_str = fname.replace('.log', '')
    with open(os.path.join(log_dir, fname)) as f:
        for line in f:
            m = re.search(r'cap:\s*([+-]?\$[\d,.]+)', line)
            if m:
                results[d_str] = float(m.group(1).replace('$','').replace(',',''))

if not results:
    print("No completed logs found.")
    sys.exit(0)

weeks = {}
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
    if mkey not in months:
        months[mkey] = 0.0
    months[mkey] += pnl

print()
print("=== 2026 Stock Replay — M1 09:30/1 + A1 10:30/6 ===")
print("    reversal | rank-weighted 60/40 | stop-pct 0.1 | top2 | $10k")
print()

print("── WEEKLY ──────────────────────────────────────────────────────")
total_days = 0
year_total = 0.0
for key in sorted(weeks.keys()):
    w = weeks[key]
    n = len(w["days"])
    sign = "+" if w["pnl"] >= 0 else ""
    print(f"  Week of {key}  ({n}d)   {sign}${w['pnl']:>9,.2f}")
    for d_str, pnl in w["days"]:
        day_name = date.fromisoformat(d_str).strftime("%a")
        sign2 = "+" if pnl >= 0 else ""
        print(f"      {d_str} {day_name}   {sign2}${pnl:>8,.2f}")
    total_days += n
    year_total += w["pnl"]

print()
print("── MONTHLY ─────────────────────────────────────────────────────")
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
for mkey in sorted(months.keys()):
    mp = months[mkey]
    sign = "+" if mp >= 0 else ""
    m_idx = int(mkey.split('-')[1]) - 1
    print(f"  {month_names[m_idx]} {mkey.split('-')[0]}   {sign}${mp:>9,.2f}   ({sign}{mp/10000*100:.1f}%)")

print()
print("── TOTAL ───────────────────────────────────────────────────────")
sign = "+" if year_total >= 0 else ""
year_label = log_dir.split('replay_')[1].split('_')[0] if 'replay_' in log_dir else '?'
print(f"  {year_label} TOTAL   {total_days} days   {sign}${year_total:,.2f}   ({sign}{year_total/10000*100:.1f}% on $10k)")
print(f"  Logs: {len(results)} complete")
print()
PYEOF
}

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
echo "=== $YEAR custom replay: M1 09:30/1 + A1 10:30/6 | stop 0.1 | reversal | top2 ==="
echo "    Total trading days : ${#ALL_DATES[@]}"
echo "    To run             : ${#TODO[@]}"
echo "    Max parallel       : $MAX_PARALLEL"
echo "    Log dir            : $LOG_DIR"
echo ""

if [ ${#TODO[@]} -eq 0 ]; then
  echo "All dates complete — printing summary."
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
