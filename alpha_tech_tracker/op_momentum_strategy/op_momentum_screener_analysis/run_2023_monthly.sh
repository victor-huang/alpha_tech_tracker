#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"
MONTHS=(2023-01 2023-02 2023-03 2023-04 2023-05 2023-06 2023-07 2023-08 2023-09 2023-10 2023-11 2023-12)
STARTS=(2023-01-03 2023-02-01 2023-03-01 2023-04-03 2023-05-01 2023-06-01 2023-07-03 2023-08-01 2023-09-01 2023-10-02 2023-11-01 2023-12-01)
ENDS=(  2023-01-31 2023-02-28 2023-03-31 2023-04-28 2023-05-31 2023-06-30 2023-07-31 2023-08-31 2023-09-29 2023-10-31 2023-11-30 2023-12-29)
PIDS=()
echo "Launching ${#MONTHS[@]} parallel monthly runs..."
for i in "${!MONTHS[@]}"; do
  MONTH="${MONTHS[$i]}"; START="${STARTS[$i]}"; END="${ENDS[$i]}"
  LOG="$SCRIPT_DIR/${MONTH}.log"
  PYTHONPATH="$PROJECT_ROOT" python -m \
    alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
    --tickers $TICKERS --start "$START" --end "$END" --min-vol-ratio 1 \
    > "$LOG" 2>&1 &
  PIDS+=($!); echo "  started $MONTH  pid $!"
done
echo ""; echo "Waiting..."
FAILED=0
for i in "${!PIDS[@]}"; do
  if wait "${PIDS[$i]}"; then echo "  done    ${MONTHS[$i]}"
  else echo "  FAILED  ${MONTHS[$i]}"; FAILED=$((FAILED+1)); fi
done
[[ $FAILED -gt 0 ]] && { echo "$FAILED failed"; exit 1; }
echo "All done."
