#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"
MONTHS=(2020-01 2020-02 2020-03 2020-04 2020-05 2020-06 2020-07 2020-08 2020-09 2020-10 2020-11 2020-12)
STARTS=(2020-01-02 2020-02-03 2020-03-02 2020-04-01 2020-05-01 2020-06-01 2020-07-01 2020-08-03 2020-09-01 2020-10-01 2020-11-02 2020-12-01)
ENDS=(  2020-01-31 2020-02-28 2020-03-31 2020-04-30 2020-05-29 2020-06-30 2020-07-31 2020-08-31 2020-09-30 2020-10-30 2020-11-30 2020-12-31)
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
