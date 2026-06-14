#!/bin/bash
# 2019 monthly screener runs — batches of 3 to stay within Alpaca rate limits
# Note: SNDK/APP/SNOW/RDDT/PLTR/ARM/CRWD(partial)/DDOG(partial) may have no data pre-IPO

set -e
PROJECT_ROOT="/Users/victorhuang/work/alpha_tech_tracker"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

TICKERS="APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"

MONTHS=(2019-01 2019-02 2019-03 2019-04 2019-05 2019-06 2019-07 2019-08 2019-09 2019-10 2019-11 2019-12)
STARTS=(2019-01-02 2019-02-01 2019-03-01 2019-04-01 2019-05-01 2019-06-03 2019-07-01 2019-08-01 2019-09-03 2019-10-01 2019-11-01 2019-12-02)
ENDS=(  2019-01-31 2019-02-28 2019-03-29 2019-04-30 2019-05-31 2019-06-28 2019-07-31 2019-08-30 2019-09-30 2019-10-31 2019-11-29 2019-12-31)

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

echo "All 2019 months complete."
