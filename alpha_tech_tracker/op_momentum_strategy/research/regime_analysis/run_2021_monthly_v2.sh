#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"
MONTHS=(2021-01 2021-02 2021-03 2021-04 2021-05 2021-06 2021-07 2021-08 2021-09 2021-10 2021-11 2021-12)
STARTS=(2021-01-04 2021-02-01 2021-03-01 2021-04-01 2021-05-03 2021-06-01 2021-07-01 2021-08-02 2021-09-01 2021-10-01 2021-11-01 2021-12-01)
ENDS=(  2021-01-29 2021-02-26 2021-03-31 2021-04-30 2021-05-28 2021-06-30 2021-07-30 2021-08-31 2021-09-30 2021-10-29 2021-11-30 2021-12-31)
PIDS=()
for i in "${!MONTHS[@]}"; do
  MONTH="${MONTHS[$i]}"; START="${STARTS[$i]}"; END="${ENDS[$i]}"
  PYTHONPATH="$PROJECT_ROOT" python -m \
    alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
    --tickers $TICKERS --start "$START" --end "$END" --min-vol-ratio 1 \
    > "$SCRIPT_DIR/${MONTH}_v2.log" 2>&1 &
  PIDS+=($!); echo "  started $MONTH pid $!"
done
FAILED=0
for i in "${!PIDS[@]}"; do
  if wait "${PIDS[$i]}"; then echo "  done    ${MONTHS[$i]}"
  else echo "  FAILED  ${MONTHS[$i]}"; FAILED=$((FAILED+1)); fi
done
[[ $FAILED -gt 0 ]] && { echo "$FAILED failed"; exit 1; }
echo "All done."
