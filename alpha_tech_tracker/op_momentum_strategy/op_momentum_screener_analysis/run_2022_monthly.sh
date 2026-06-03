#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"
MONTHS=(2022-01 2022-02 2022-03 2022-04 2022-05 2022-06 2022-07 2022-08 2022-09 2022-10 2022-11 2022-12)
STARTS=(2022-01-03 2022-02-01 2022-03-01 2022-04-01 2022-05-02 2022-06-01 2022-07-01 2022-08-01 2022-09-01 2022-10-03 2022-11-01 2022-12-01)
ENDS=(  2022-01-31 2022-02-28 2022-03-31 2022-04-29 2022-05-31 2022-06-30 2022-07-29 2022-08-31 2022-09-30 2022-10-31 2022-11-30 2022-12-30)
PIDS=()
echo "Launching ${#MONTHS[@]} parallel monthly runs..."
for i in "${!MONTHS[@]}"; do
  MONTH="${MONTHS[$i]}"; START="${STARTS[$i]}"; END="${ENDS[$i]}"
  PYTHONPATH="$PROJECT_ROOT" python -m \
    alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
    --tickers $TICKERS --start "$START" --end "$END" --min-vol-ratio 1 \
    > "$SCRIPT_DIR/${MONTH}.log" 2>&1 &
  PIDS+=($!); echo "  started $MONTH pid $!"
done
echo ""; echo "Waiting..."
FAILED=0
for i in "${!PIDS[@]}"; do
  if wait "${PIDS[$i]}"; then echo "  done    ${MONTHS[$i]}"
  else echo "  FAILED  ${MONTHS[$i]}"; FAILED=$((FAILED+1)); fi
done
[[ $FAILED -gt 0 ]] && { echo "$FAILED failed"; exit 1; }
echo "All done."
