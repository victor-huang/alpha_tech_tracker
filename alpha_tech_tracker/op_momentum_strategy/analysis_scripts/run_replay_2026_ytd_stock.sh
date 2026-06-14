#!/usr/bin/env bash
# run_replay_2026_ytd_stock.sh
# Replay 2026-01-02 → 2026-05-29 with the parity-tuned stock params.
#
# Usage: ./run_replay_2026_ytd_stock.sh [--force]
#   --force   re-run dates that already have a log
#
# Logs go to: logs/replay_2026_ytd_stock/YYYY-MM-DD.log
# Summary:    logs/replay_2026_ytd_stock/summary.txt  (after all days complete)

set -euo pipefail

FORCE=0
for arg in "$@"; do [[ "$arg" == "--force" ]] && FORCE=1; done

LOG_DIR="logs/replay_2026_ytd_stock"
mkdir -p "$LOG_DIR"

MAX_PARALLEL=12   # tune down if the machine gets hot; SIP cache fetches are serial per-day

# US market holidays Jan–May 2026
HOLIDAYS="2026-01-01 2026-01-20 2026-02-17 2026-04-03 2026-05-25"

TRADING_DAYS=($(python3 -c "
from datetime import date, timedelta
holidays = {date.fromisoformat(d) for d in '$HOLIDAYS'.split()}
d = date(2026, 1, 2)
end = date(2026, 5, 29)
days = []
while d <= end:
    if d.weekday() < 5 and d not in holidays:
        days.append(str(d))
    d += timedelta(days=1)
print(' '.join(days))
"))

echo "=== 2026 YTD stock replay: ${#TRADING_DAYS[@]} trading days ==="
echo "    logs → $LOG_DIR"
echo ""

replay_one() {
  local DATE="$1"
  local LOG="$LOG_DIR/$DATE.log"
  source ~/.pyenv/versions/alpha_tech_tracker/bin/activate 2>/dev/null || true
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    --log-level INFO \
    --trade-type stock \
    --top 1 \
    --window M1 09:30 3 \
    --window A1 10:00 5 \
    --window A2 12:15 10 \
    --window A3 14:15 5 \
    --reversal \
    --stop-pct 0.40 \
    --morning-split 100 \
    --bullish-reentry \
    --bearish-reentry \
    --score-entry-weight 0.60 \
    --score-avg-win-weight 0.00 \
    --score-win-rate-weight 0.10 \
    --score-ev-trend-weight 0.10 \
    --score-rel-strength-weight 0.15 \
    --ma-momentum-gate \
    --normalize-or-by-adr \
    --qqq-or-weight 0.3 \
    --dynamic-ev-gate \
    --adaptive-lookback \
    --direction-split-ev \
    --capital 10000 \
    --mock-trade-execution \
    --replay-date "$DATE" \
    --feed sip > "$LOG" 2>&1
}

# Build TODO list
TODO=()
for DATE in "${TRADING_DAYS[@]}"; do
  LOG="$LOG_DIR/$DATE.log"
  if [[ $FORCE -eq 1 ]] || [[ ! -f "$LOG" ]]; then
    TODO+=("$DATE")
  else
    echo "  skip $DATE (already done)"
  fi
done

if [[ ${#TODO[@]} -eq 0 ]]; then
  echo "All dates already complete. Run with --force to re-run."
else
  # Warm cache: run last day alone first so the 60-day lookback bar fetch
  # populates the cache; all other days will hit the cache in parallel.
  LAST="${TODO[$((${#TODO[@]} - 1))]}"
  echo "--- Cache warm: $LAST ---"
  replay_one "$LAST" && echo "    OK  $LAST" || echo "    ERR $LAST"
  echo ""

  # Remove last from TODO
  LAST_IDX=$((${#TODO[@]} - 1))
  TODO=("${TODO[@]:0:$LAST_IDX}")

  if [[ ${#TODO[@]} -gt 0 ]]; then
    echo "--- Running ${#TODO[@]} remaining days (max $MAX_PARALLEL parallel) ---"
    i=0
    while [[ $i -lt ${#TODO[@]} ]]; do
      batch=("${TODO[@]:$i:$MAX_PARALLEL}")
      echo "  batch: ${batch[0]} → ${batch[$((${#batch[@]}-1))]} (${#batch[@]} days)"
      PIDS=()
      for DATE in "${batch[@]}"; do
        replay_one "$DATE" &
        PIDS+=($!)
      done
      for j in "${!PIDS[@]}"; do
        wait "${PIDS[$j]}" \
          && echo "    OK  ${batch[$j]}" \
          || echo "    ERR ${batch[$j]}"
      done
      i=$((i + ${#batch[@]}))
    done
  fi
fi

echo ""
echo "--- Summary ---"
python3 - <<'PY'
import os, re
from pathlib import Path

log_dir = Path("logs/replay_2026_ytd_stock")
total_pnl = 0.0
trades = 0
wins = 0
days_with_trades = 0
days_no_trades = 0
errors = []

for log in sorted(log_dir.glob("2026-*.log")):
    text = log.read_text()
    day_pnl = 0.0
    day_trades = 0
    for m in re.finditer(r"Daily realized P&L updated: ([-\d.]+)", text):
        day_pnl = float(m.group(1))
    for m in re.finditer(r"EXIT \w+ \w+ reason=\w+", text):
        day_trades += 1
        line = m.group(0)
    for m in re.finditer(r"added ([-\d.]+) from", text):
        val = float(m.group(1))
        if val > 0:
            wins += 1
        trades += 1
    if day_trades > 0:
        days_with_trades += 1
        total_pnl += day_pnl
    else:
        days_no_trades += 1
    if "Error" in text or "Traceback" in text:
        errors.append(log.name)

wr = wins / trades * 100 if trades else 0
print(f"Days with trades : {days_with_trades}")
print(f"Days no trades   : {days_no_trades}")
print(f"Total P&L        : ${total_pnl:+.2f}")
print(f"Return on $10k   : {total_pnl / 10000 * 100:+.2f}%")
print(f"Trades / W/L     : {trades} / {wins}W {trades-wins}L  ({wr:.1f}% WR)")
if errors:
    print(f"Errors in        : {errors}")
PY

echo ""
echo "=== Done. Full logs in $LOG_DIR ==="
