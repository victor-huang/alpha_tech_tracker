#!/usr/bin/env bash
# run_replay_2026_stock_4win.sh
# Replay all 2026 trading days (up to 2026-05-01) in parallel batches of 6.
# Config: stock, M1 09:30/3 + A1 10:00/3 + A2 13:15/1 + A3 15:15/1, reversal+reentry+DD
#
# Usage:
#   ./run_replay_2026_stock_4win.sh           # run missing dates, then print summary
#   ./run_replay_2026_stock_4win.sh --summary # print P&L summary only (no replay)
#   ./run_replay_2026_stock_4win.sh --force   # re-run all dates even if logs exist

set -euo pipefail

LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2026_stock_4win"
PYTHONPATH_DIR="/Users/victorhuang/work/alpha_tech_tracker"
MAX_PARALLEL=6
SUMMARY_ONLY=false
FORCE=false

for arg in "$@"; do
  case "$arg" in
    --summary) SUMMARY_ONLY=true ;;
    --force)   FORCE=true ;;
  esac
done

# ---------------------------------------------------------------------------
# US market holidays in scope (2026-01-01 → 2026-05-01)
# ---------------------------------------------------------------------------
HOLIDAYS=(
  "2026-01-01"  # New Year's Day
  "2026-01-19"  # MLK Day
  "2026-02-16"  # Presidents' Day
  "2026-04-03"  # Good Friday
)

is_holiday() {
  local d="$1"
  for h in "${HOLIDAYS[@]}"; do
    [ "$d" = "$h" ] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# Generate all trading days 2026-01-01 → 2026-05-01
# ---------------------------------------------------------------------------
generate_trading_days() {
  python3 -c "
from datetime import date, timedelta
holidays = {
    date(2026,1,1), date(2026,1,19), date(2026,2,16), date(2026,4,3)
}
d = date(2026, 1, 1)
end = date(2026, 5, 1)
days = []
while d <= end:
    if d.weekday() < 5 and d not in holidays:
        days.append(str(d))
    d += timedelta(days=1)
print('\n'.join(days))
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
    --window M1 09:30 3 \
    --window A1 10:00 3 \
    --window A2 13:15 1 \
    --window A3 15:15 1 \
    --morning-split 100 \
    --bearish-reentry --bullish-reentry --reversal \
    --rank-weighted-sizing 60 40 \
    --doubledown --doubledown-start 10 \
    --top 2 --capital 10000 \
    --mock-trade-execution \
    --feed sip \
    --replay-date "$DATE" > "$LOG" 2>&1
}

# ---------------------------------------------------------------------------
# P&L summary: weekly breakdown + total
# ---------------------------------------------------------------------------
print_summary() {
  python3 - "$LOG_DIR" <<'PYEOF'
import os, re, sys
from datetime import date, timedelta

log_dir = sys.argv[1]

# Parse cap P&L from each log
results = {}
for fname in sorted(os.listdir(log_dir)):
    if not re.match(r'\d{4}-\d{2}-\d{2}\.log$', fname):
        continue
    d = fname.replace('.log', '')
    fpath = os.path.join(log_dir, fname)
    pnl = None
    with open(fpath, 'r') as f:
        for line in f:
            # "  Daily P&L: +$5285.00  (+10.55%  on  $50075 deployed)  │  cap: +$5285.00 (+52.85%)"
            m = re.search(r'cap:\s*([+-]?\$[\d,.]+)', line)
            if m:
                pnl = float(m.group(1).replace('$', '').replace(',', ''))
    if pnl is not None:
        results[d] = pnl

if not results:
    print("No completed logs found.")
    sys.exit(0)

# Group by ISO week
weeks = {}
for d_str, pnl in sorted(results.items()):
    d = date.fromisoformat(d_str)
    # Monday of that week
    week_start = d - timedelta(days=d.weekday())
    week_end   = week_start + timedelta(days=4)
    key = str(week_start)
    if key not in weeks:
        weeks[key] = {"start": week_start, "end": week_end, "days": [], "pnl": 0.0}
    weeks[key]["days"].append((d_str, pnl))
    weeks[key]["pnl"] += pnl

print()
print(f"{'Week':12}  {'Days':>4}  {'Weekly P&L':>12}  {'Daily avg':>10}")
print("-" * 48)
total = 0.0
total_days = 0
for key in sorted(weeks):
    w = weeks[key]
    n = len(w["days"])
    avg = w["pnl"] / n if n else 0
    sign = "+" if w["pnl"] >= 0 else ""
    print(f"{key}  {n:>4}  {sign}${w['pnl']:>10,.2f}  {sign}${avg:>8,.2f}")
    total += w["pnl"]
    total_days += n

print("-" * 48)
sign = "+" if total >= 0 else ""
print(f"{'TOTAL':12}  {total_days:>4}  {sign}${total:>10,.2f}  {sign}${total/total_days:>8,.2f}")
print()
pct = total / 10000 * 100
print(f"Capital P&L on $10,000: {sign}${total:,.2f}  ({sign}{pct:.1f}%)")
print(f"Logs:  {len(results)} / {total_days} trading days complete")
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

# Build TODO list
ALL_DATES=()
while IFS= read -r line; do
  ALL_DATES+=("$line")
done < <(generate_trading_days)
TODO=()
for DATE in "${ALL_DATES[@]}"; do
  LOG="$LOG_DIR/$DATE.log"
  if $FORCE || [ ! -f "$LOG" ]; then
    TODO+=("$DATE")
  else
    echo "  skip $DATE (log exists)"
  fi
done

echo ""
echo "=== 2026 YTD stock replay (4-window: M1+A1+A2+A3) ==="
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

# Run in batches of MAX_PARALLEL
i=0
total=${#TODO[@]}
while [ $i -lt $total ]; do
  batch=("${TODO[@]:$i:$MAX_PARALLEL}")
  echo "--- Batch $((i/MAX_PARALLEL + 1)): ${batch[0]} → ${batch[$((${#batch[@]}-1))]} (${#batch[@]} dates) ---"
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
