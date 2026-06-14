#!/bin/bash
# 2017 monthly screener runs — batches of 3 to stay within Alpaca rate limits
# SPOT excluded (IPO April 2018); all other 2018 tickers available in 2017
# 2017 was the low-vol "Trump rally" year: S&P +19%, Nasdaq +28%, VIX at historic lows

set -e
PROJECT_ROOT="/Users/victorhuang/work/alpha_tech_tracker"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

TICKERS="META SNPS MU LLY MRVL QCOM CHTR TSLA AVGO AMD"

MONTHS=(2017-01 2017-02 2017-03 2017-04 2017-05 2017-06 2017-07 2017-08 2017-09 2017-10 2017-11 2017-12)
STARTS=(2017-01-03 2017-02-01 2017-03-01 2017-04-03 2017-05-01 2017-06-01 2017-07-03 2017-08-01 2017-09-01 2017-10-02 2017-11-01 2017-12-01)
ENDS=(  2017-01-31 2017-02-28 2017-03-31 2017-04-28 2017-05-31 2017-06-30 2017-07-31 2017-08-31 2017-09-29 2017-10-31 2017-11-30 2017-12-29)

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

echo "All 2017 months complete."
