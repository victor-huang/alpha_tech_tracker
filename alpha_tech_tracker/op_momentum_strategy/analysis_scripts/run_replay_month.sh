#!/usr/bin/env bash
# run_replay_month.sh — replay a full month, warming cache from last day first
#
# Usage: ./run_replay_month.sh <YYYY-MM>
# Example: ./run_replay_month.sh 2025-12
#
# Strategy:
#   1. Run the last trading day alone first (warms TS intraday + warmup caches)
#   2. Run remaining days in parallel (max 25)

set -euo pipefail

MONTH="${1:-}"
if [ -z "$MONTH" ]; then
  echo "Usage: $0 <YYYY-MM>"
  exit 1
fi

LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2025"
mkdir -p "$LOG_DIR"

MAX_PARALLEL=25

replay_one() {
  local DATE="$1"
  local LOG="$LOG_DIR/$DATE.log"
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    --log-level DEBUG \
    --trade-type options \
    --collect-option-prices \
    --window M1 9:30 3 --window A1 13:15 1 --window A2 15:00 1 \
    --morning-split 100 --bearish-reentry --bullish-reentry --reversal \
    --rank-weighted-sizing 60 40 \
    --doubledown --doubledown-start 10 \
    --mock-trade-execution \
    --top 2 --capital 10000 \
    --market-data-source tradestation \
    --replay-date "$DATE" > "$LOG" 2>&1
}

# Collect all dates for this month that don't have a log yet
TODO=()
for LOG in "$LOG_DIR"/${MONTH}-*.log; do
  : # just to avoid empty glob error
done 2>/dev/null || true

# Get all dates from the log dir + generate expected ones via python
DATES=($(python3 -c "
import sys
from datetime import date, timedelta

month = sys.argv[1]
year, mo = int(month.split('-')[0]), int(month.split('-')[1])

# US market holidays 2025
holidays = {
  date(2025,1,1), date(2025,1,20), date(2025,2,17),
  date(2025,4,18), date(2025,5,26), date(2025,6,19),
  date(2025,7,4), date(2025,9,1), date(2025,11,27), date(2025,12,25),
}

d = date(year, mo, 1)
days = []
while d.month == mo:
    if d.weekday() < 5 and d not in holidays:
        days.append(str(d))
    d += timedelta(days=1)
print(' '.join(days))
" "$MONTH"))

echo "=== $MONTH: ${#DATES[@]} trading days ==="

# Build TODO list (skip already-completed logs)
TODO=()
for DATE in "${DATES[@]}"; do
  if [ ! -f "$LOG_DIR/$DATE.log" ]; then
    TODO+=("$DATE")
  else
    echo "  skip $DATE (already done)"
  fi
done

if [ ${#TODO[@]} -eq 0 ]; then
  echo "All dates already complete for $MONTH"
  exit 0
fi

# Step 1: run the last day alone to warm cache
LAST="${TODO[$((${#TODO[@]} - 1))]}"
echo ""
echo "--- Cache warm: $LAST (running alone) ---"
replay_one "$LAST"
echo "  done $LAST"

# Remove last from TODO
LAST_IDX=$((${#TODO[@]} - 1))
TODO=("${TODO[@]:0:$LAST_IDX}")

if [ ${#TODO[@]} -eq 0 ]; then
  echo "Only one date to run, done."
  exit 0
fi

# Step 2: run remaining in batches of MAX_PARALLEL
echo ""
echo "--- Running ${#TODO[@]} remaining dates (max $MAX_PARALLEL parallel) ---"

i=0
while [ $i -lt ${#TODO[@]} ]; do
  batch=("${TODO[@]:$i:$MAX_PARALLEL}")
  first="${batch[0]}"
  last="${batch[$((${#batch[@]} - 1))]}"
  echo "  batch: $first → $last (${#batch[@]} dates)"
  PIDS=()
  for DATE in "${batch[@]}"; do
    replay_one "$DATE" &
    PIDS+=($!)
  done
  for j in "${!PIDS[@]}"; do
    wait "${PIDS[$j]}" && echo "    OK  ${batch[$j]}" || echo "    ERR ${batch[$j]}"
  done
  i=$((i + ${#batch[@]}))
done

echo ""
echo "=== $MONTH complete ==="
