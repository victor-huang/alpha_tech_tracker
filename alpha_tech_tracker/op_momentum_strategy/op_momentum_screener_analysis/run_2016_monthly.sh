#!/bin/bash
# 2016 monthly screener runs — batches of 3 to stay within Alpaca rate limits
# Data availability: Alpaca confirmed to have 2016 data via test run
# SPOT excluded (IPO Apr 2018); same 10-ticker list as 2017
# 2016 key events: Jan China crash/oil crash, Jun Brexit, Nov Trump election surprise

set -e
PROJECT_ROOT="/Users/victorhuang/work/alpha_tech_tracker"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

TICKERS="META SNPS MU LLY MRVL QCOM CHTR TSLA AVGO AMD"

MONTHS=(2016-01 2016-02 2016-03 2016-04 2016-05 2016-06 2016-07 2016-08 2016-09 2016-10 2016-11 2016-12)
STARTS=(2016-01-04 2016-02-01 2016-03-01 2016-04-01 2016-05-02 2016-06-01 2016-07-01 2016-08-01 2016-09-01 2016-10-03 2016-11-01 2016-12-01)
ENDS=(  2016-01-29 2016-02-29 2016-03-31 2016-04-29 2016-05-31 2016-06-30 2016-07-29 2016-08-31 2016-09-30 2016-10-31 2016-11-30 2016-12-30)

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

echo "All 2016 months complete."
