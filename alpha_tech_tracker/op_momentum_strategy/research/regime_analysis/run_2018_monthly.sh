#!/bin/bash
# 2018 monthly screener runs — batches of 3 to stay within Alpaca rate limits
# Note: APP/SNOW/RDDT/PLTR/ARM/CRWD/DDOG pre-IPO (no data)
# SPOT IPO April 2018 (limited early data); META was FB but Alpaca handles historically

set -e
PROJECT_ROOT="/Users/victorhuang/work/alpha_tech_tracker"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

TICKERS="META SNPS SPOT MU LLY MRVL QCOM CHTR TSLA AVGO AMD"

MONTHS=(2018-01 2018-02 2018-03 2018-04 2018-05 2018-06 2018-07 2018-08 2018-09 2018-10 2018-11 2018-12)
STARTS=(2018-01-02 2018-02-01 2018-03-01 2018-04-02 2018-05-01 2018-06-01 2018-07-02 2018-08-01 2018-09-04 2018-10-01 2018-11-01 2018-12-03)
ENDS=(  2018-01-31 2018-02-28 2018-03-29 2018-04-30 2018-05-31 2018-06-29 2018-07-31 2018-08-31 2018-09-28 2018-10-31 2018-11-30 2018-12-31)

run_batch() {
    local indices=("$@")
    for i in "${indices[@]}"; do
        echo "Starting ${MONTHS[$i]} (${STARTS[$i]} → ${ENDS[$i]})..."
        PYTHONPATH="$PROJECT_ROOT" python -m \
            alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
            --tickers $TICKERS \
            --start "${STARTS[$i]}" --end "${ENDS[$i]}" \
            --min-vol-ratio 1 \
            > "$SCRIPT_DIR/${MONTHS[$i]}.log" 2>&1 &
    done
    wait
    echo "Batch done."
}

echo "=== Batch 1: Jan Feb Mar ==="
run_batch 0 1 2
sleep 3

echo "=== Batch 2: Apr May Jun ==="
run_batch 3 4 5
sleep 3

echo "=== Batch 3: Jul Aug Sep ==="
run_batch 6 7 8
sleep 3

echo "=== Batch 4: Oct Nov Dec ==="
run_batch 9 10 11

echo "All 2018 months complete."
