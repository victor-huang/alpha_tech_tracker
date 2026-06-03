#!/usr/bin/env bash
# Run MA open-range screener for each month in 2025 (Jan–Dec) in parallel.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"

MONTHS=(2025-01 2025-02 2025-03 2025-04 2025-05 2025-06 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12)
STARTS=(2025-01-02 2025-02-03 2025-03-03 2025-04-01 2025-05-01 2025-06-02 2025-07-01 2025-08-01 2025-09-02 2025-10-01 2025-11-03 2025-12-01)
ENDS=(  2025-01-31 2025-02-28 2025-03-31 2025-04-30 2025-05-30 2025-06-30 2025-07-31 2025-08-29 2025-09-30 2025-10-31 2025-11-28 2025-12-31)

PIDS=()

echo "Launching ${#MONTHS[@]} parallel monthly runs..."

for i in "${!MONTHS[@]}"; do
  MONTH="${MONTHS[$i]}"
  START="${STARTS[$i]}"
  END="${ENDS[$i]}"
  LOG="$SCRIPT_DIR/${MONTH}_v2.log"
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
echo "Logs: $SCRIPT_DIR/2025-MM.log"
