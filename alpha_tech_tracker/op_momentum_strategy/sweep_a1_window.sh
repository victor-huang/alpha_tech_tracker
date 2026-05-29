#!/usr/bin/env bash
# Sweep A1 window start times (10:00–12:00, 15-min steps) × bar counts (1,2,3)
# Base config: M1 09:30/3 + A1 <time>/<bars>, top-1, 2026-01-01 to 2026-05-22
# Runs 22 jobs in parallel; results written to sweep_a1_window_results/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT_DIR="$SCRIPT_DIR/backtest_result/a1_window_sweep_$(date +%Y%m%d)"
mkdir -p "$OUT_DIR"

PYTHON="python"
BACKTEST="alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest"

BASE_ARGS=(
    --top 1
    --window M1 09:30 3
    --min-hold-bars 1
    --ma-momentum-gate
    --feed sip
    --qqq-or-weight 0.40
    --normalize-or-by-adr
    --stop-pct 0.4
    --reversal --bearish-reentry --bullish-reentry
    --score-entry-weight 0.60
    --score-avg-win-weight 0.00
    --score-win-rate-weight 0.10
    --score-ev-trend-weight 0.10
    --score-rel-strength-weight 0.15
    --min-pool-vote 4
    --start 2026-01-01 --end 2026-05-22
)

START_TIMES=(
    "10:00" "10:15" "10:30" "10:45"
    "11:00" "11:15" "11:30" "11:45"
    "12:00"
)
BAR_COUNTS=(1 2 3)

PARALLEL=22

run_one() {
    local start="$1"
    local bars="$2"
    local label="A1_${start//:}b${bars}"
    local logfile="$OUT_DIR/${label}.log"

    PYTHONPATH="$REPO_ROOT" $PYTHON -m "$BACKTEST" \
        "${BASE_ARGS[@]}" \
        --window A1 "$start" "$bars" \
        > "$logfile" 2>&1

    # Extract A1 line from per-window breakdown
    local a1_line
    a1_line=$(grep -E "^  A1 " "$logfile" | tail -1 || true)
    if [[ -n "$a1_line" ]]; then
        printf "%-8s  bars=%-2s  %s\n" "$start" "$bars" "$a1_line"
    else
        printf "%-8s  bars=%-2s  [no A1 output]\n" "$start" "$bars"
    fi
}

export -f run_one
export OUT_DIR REPO_ROOT PYTHON BACKTEST
export BASE_ARGS  # arrays don't export cleanly; handled via wrapper below

echo "============================================================"
echo "  A1 Window Sweep  —  $(date)"
echo "  Output dir: $OUT_DIR"
echo "  Combos: ${#START_TIMES[@]} times × ${#BAR_COUNTS[@]} bars = $((${#START_TIMES[@]} * ${#BAR_COUNTS[@]}))"
echo "  Parallelism: $PARALLEL"
echo "============================================================"
echo ""

# Build job list
JOBS=()
for t in "${START_TIMES[@]}"; do
    for b in "${BAR_COUNTS[@]}"; do
        JOBS+=("$t|$b")
    done
done

run_job() {
    local spec="$1"
    local start="${spec%%|*}"
    local bars="${spec##*|}"
    local label="A1_${start//:}b${bars}"
    local logfile="$OUT_DIR/${label}.log"

    PYTHONPATH="$REPO_ROOT" $PYTHON -m \
        alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest \
        --top 1 \
        --window M1 09:30 3 \
        --min-hold-bars 1 \
        --ma-momentum-gate \
        --feed sip \
        --qqq-or-weight 0.40 \
        --normalize-or-by-adr \
        --stop-pct 0.4 \
        --reversal --bearish-reentry --bullish-reentry \
        --score-entry-weight 0.60 \
        --score-avg-win-weight 0.00 \
        --score-win-rate-weight 0.10 \
        --score-ev-trend-weight 0.10 \
        --score-rel-strength-weight 0.15 \
        --min-pool-vote 4 \
        --start 2026-01-01 --end 2026-05-22 \
        --window A1 "$start" "$bars" \
        > "$logfile" 2>&1

    # Extract A1 stats from per-window breakdown table
    local a1_line
    a1_line=$(grep -E "^  A1 " "$logfile" | tail -1 || true)
    if [[ -n "$a1_line" ]]; then
        # Pull Return% and WinRate columns from the line
        local ret wr ev
        ret=$(echo "$a1_line" | grep -oP '[+-]\d+\.\d+%' | tail -1 || echo "?")
        wr=$(echo  "$a1_line" | grep -oP '\d+%' | head -1 || echo "?")
        ev=$(echo  "$a1_line" | grep -oP '[+-]\d+\.\d+%' | head -1 || echo "?")
        printf "start=%-6s  bars=%s  WR=%-5s  EV=%-9s  Return=%s\n" \
            "$start" "$bars" "$wr" "$ev" "$ret"
    else
        printf "start=%-6s  bars=%s  [no A1 output — check %s]\n" "$start" "$bars" "$logfile"
    fi
}

export -f run_job
export REPO_ROOT OUT_DIR

# Run in parallel batches
ACTIVE=0
PIDS=()

for spec in "${JOBS[@]}"; do
    run_job "$spec" &
    pid=$!
    PIDS+=($pid)
    ACTIVE=$((ACTIVE + 1))

    if [[ $ACTIVE -ge $PARALLEL ]]; then
        wait "${PIDS[0]}"
        PIDS=("${PIDS[@]:1}")
        ACTIVE=$((ACTIVE - 1))
    fi
done

# Wait for remaining
for pid in "${PIDS[@]}"; do
    wait "$pid"
done

echo ""
echo "============================================================"
echo "  SWEEP COMPLETE — collating results"
echo "============================================================"
echo ""

# Print sorted summary from individual log files
printf "%-8s  %-5s  %-8s  %-12s  %-10s  %-8s\n" \
    "Start" "Bars" "Trades" "W/L" "WinRate" "Return%"
printf "%s\n" "────────────────────────────────────────────────────────────────"

for t in "${START_TIMES[@]}"; do
    for b in "${BAR_COUNTS[@]}"; do
        label="A1_${t//:}b${b}"
        logfile="$OUT_DIR/${label}.log"
        a1_line=$(grep -E "^  A1 " "$logfile" | tail -1 || true)
        if [[ -n "$a1_line" ]]; then
            # columns: label start bars group trades W/L WinRate EV CapPnL Return%
            trades=$(echo "$a1_line" | awk '{print $5}')
            wl=$(echo    "$a1_line" | awk '{print $6}')
            wr=$(echo    "$a1_line" | awk '{print $7}')
            ev=$(echo    "$a1_line" | awk '{print $8}')
            ret=$(echo   "$a1_line" | awk '{print $10}')
            printf "%-8s  %-5s  %-8s  %-12s  %-8s  %-12s  EV=%-12s\n" \
                "$t" "$b" "$trades" "$wl" "$wr" "$ret" "$ev"
        else
            printf "%-8s  %-5s  [no output]\n" "$t" "$b"
        fi
    done
done

echo ""
echo "Full logs: $OUT_DIR/"
