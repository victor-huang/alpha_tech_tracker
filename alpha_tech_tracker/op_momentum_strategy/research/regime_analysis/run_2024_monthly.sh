#!/usr/bin/env bash
# Run MA open-range screener for each month in 2024 (Jan–Dec) in parallel.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"

MONTHS=(2024-01 2024-02 2024-03 2024-04 2024-05 2024-06 2024-07 2024-08 2024-09 2024-10 2024-11 2024-12)
STARTS=(2024-01-02 2024-02-01 2024-03-01 2024-04-01 2024-05-01 2024-06-03 2024-07-01 2024-08-01 2024-09-03 2024-10-01 2024-11-01 2024-12-02)
ENDS=(  2024-01-31 2024-02-29 2024-03-28 2024-04-30 2024-05-31 2024-06-28 2024-07-31 2024-08-30 2024-09-30 2024-10-31 2024-11-29 2024-12-31)

PIDS=()

echo "Launching ${#MONTHS[@]} parallel monthly runs..."

for i in "${!MONTHS[@]}"; do
  MONTH="${MONTHS[$i]}"
  START="${STARTS[$i]}"
  END="${ENDS[$i]}"
  LOG="$SCRIPT_DIR/${MONTH}.log"
  PYTHONPATH="$PROJECT_ROOT" python -m \
    alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
    --tickers $TICKERS \
    --start "$START" \
    --end   "$END" \
    --min-vol-ratio 1 \
    > "$LOG" 2>&1 &
  PIDS+=($!)
  echo "  started $MONTH  ($START → $END)  pid $!"
done

echo ""
echo "Waiting for all ${#PIDS[@]} processes..."

FAILED=0
for i in "${!PIDS[@]}"; do
  PID="${PIDS[$i]}"
  MONTH="${MONTHS[$i]}"
  if wait "$PID"; then
    echo "  done    $MONTH"
  else
    echo "  FAILED  $MONTH"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
if [[ $FAILED -gt 0 ]]; then
  echo "$FAILED run(s) failed. Check the individual .log files."
  exit 1
fi

echo "All 12 monthly runs complete."
echo "Logs: $SCRIPT_DIR/2024-MM.log"
