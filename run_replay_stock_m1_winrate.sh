#!/usr/bin/env bash
# run_replay_stock_5win_winrate.sh
# Replay trades for a full year in parallel batches.
# Config: M1 09:30/3 + A1 10:00/3 + A2 11:45/2 + A3 13:15/1 + A4 15:15/1
#         reversal + reentry + DD + rank-weighted-sizing
#         --selector win-rate + --enable-regime-engine (win-rate-signal mode)
#
# Usage:
#   ./run_replay_stock_5win_winrate.sh --year 2025
#   ./run_replay_stock_5win_winrate.sh --year 2026 --summary
#   ./run_replay_stock_5win_winrate.sh --year 2025 --force

set -euo pipefail

PYTHONPATH_DIR="/Users/victorhuang/work/alpha_tech_tracker"
BASE_LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs"
MAX_PARALLEL=20
SUMMARY_ONLY=false
FORCE=false
NO_STOP=false
FIXED_ALLOC=false
YEAR=""
TRADE_TYPE="stock"
FEED="sip"
CAPITAL=10000

while [ $# -gt 0 ]; do
  case "$1" in
    --year)         YEAR="$2";       shift 2 ;;
    --trade-type)   TRADE_TYPE="$2"; shift 2 ;;
    --feed)         FEED="$2";       shift 2 ;;
    --capital)      CAPITAL="$2";    shift 2 ;;
    --summary)      SUMMARY_ONLY=true; shift ;;
    --force)        FORCE=true;      shift ;;
    --no-stop)      NO_STOP=true;    shift ;;
    --fixed-alloc)  FIXED_ALLOC=true; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$YEAR" ]; then
  echo "Usage: $0 --year YYYY [--trade-type stock|options] [--capital N] [--summary] [--force] [--no-stop] [--fixed-alloc]"
  exit 1
fi

if $FIXED_ALLOC; then
  LOG_DIR="$BASE_LOG_DIR/replay_${YEAR}_${TRADE_TYPE}_m1_winrate_fixedalloc_cap${CAPITAL}"
elif $NO_STOP; then
  LOG_DIR="$BASE_LOG_DIR/replay_${YEAR}_${TRADE_TYPE}_m1_winrate_nostop"
else
  LOG_DIR="$BASE_LOG_DIR/replay_${YEAR}_${TRADE_TYPE}_m1_winrate"
fi

# ---------------------------------------------------------------------------
# Generate trading days for YEAR via Python (NYSE holidays 2019-2026)
# ---------------------------------------------------------------------------
generate_trading_days() {
  python3 -c "
import sys
from datetime import date, timedelta

year = int('$YEAR')
today = date.today()

holidays = {
    # 2018
    date(2018,1,1), date(2018,1,15), date(2018,2,19),
    date(2018,3,30), date(2018,5,28), date(2018,7,4),
    date(2018,9,3), date(2018,11,22), date(2018,12,25),
    # 2019
    date(2019,1,1), date(2019,1,21), date(2019,2,18),
    date(2019,4,19), date(2019,5,27), date(2019,7,4),
    date(2019,9,2), date(2019,11,28), date(2019,12,25),
    # 2020
    date(2020,1,1), date(2020,1,20), date(2020,2,17),
    date(2020,4,10), date(2020,5,25), date(2020,7,3),
    date(2020,9,7), date(2020,11,26), date(2020,12,25),
    # 2021
    date(2021,1,1), date(2021,1,18), date(2021,2,15),
    date(2021,4,2), date(2021,5,31), date(2021,7,5),
    date(2021,9,6), date(2021,11,25), date(2021,12,24),
    # 2022
    date(2022,1,17), date(2022,2,21), date(2022,4,15),
    date(2022,5,30), date(2022,6,19), date(2022,7,4),
    date(2022,9,5), date(2022,11,24), date(2022,12,26),
    # 2023
    date(2023,1,2), date(2023,1,16), date(2023,2,20),
    date(2023,4,7), date(2023,5,29), date(2023,6,19),
    date(2023,7,4), date(2023,9,4), date(2023,11,23), date(2023,12,25),
    # 2024
    date(2024,1,1), date(2024,1,15), date(2024,2,19),
    date(2024,3,29), date(2024,5,27), date(2024,6,19),
    date(2024,7,4), date(2024,9,2), date(2024,11,28), date(2024,12,25),
    # 2025
    date(2025,1,1), date(2025,1,20), date(2025,2,17),
    date(2025,4,18), date(2025,5,26), date(2025,6,19),
    date(2025,7,4), date(2025,9,1), date(2025,11,27), date(2025,12,25),
    # 2026
    date(2026,1,1), date(2026,1,19), date(2026,2,16),
    date(2026,4,3), date(2026,5,25), date(2026,6,19),
    date(2026,7,3), date(2026,9,7), date(2026,11,26), date(2026,12,25),
}

start = date(year, 1, 1)
end   = date(year, 12, 31)
if end > today:
    end = today

d = start
while d <= end:
    if d.weekday() < 5 and d not in holidays:
        print(str(d))
    d += timedelta(days=1)
"
}

# Ticker pool — matches ma_open_range_momentum_screener run set
TICKERS="SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT"

# ---------------------------------------------------------------------------
# Replay a single date — win-rate selector + win-rate-signal mode
# ---------------------------------------------------------------------------
replay_one() {
  local DATE="$1"
  local LOG="$LOG_DIR/$DATE.log"
  local EXTRA_FLAGS=""
  if $NO_STOP || $FIXED_ALLOC; then
    EXTRA_FLAGS="$EXTRA_FLAGS --trailing-ma none --stop-pct 0"
  fi
  if $FIXED_ALLOC; then
    EXTRA_FLAGS="$EXTRA_FLAGS --fixed-signal-alloc"
  fi
  PYTHONPATH="$PYTHONPATH_DIR" \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    --log-level DEBUG \
    --trade-type "$TRADE_TYPE" \
    --tickers $TICKERS \
    --selector win-rate \
    --enable-regime-engine \
    --window M1 09:30 3 \
    --morning-split 100 \
    --bearish-reentry --bullish-reentry --reversal \
    --doubledown --doubledown-start 10 \
    --top 8 --capital "$CAPITAL" \
    --mock-trade-execution \
    --feed "$FEED" \
    $EXTRA_FLAGS \
    --replay-date "$DATE" > "$LOG" 2>&1
}

# ---------------------------------------------------------------------------
# P&L summary: weekly + monthly + yearly breakdown
# ---------------------------------------------------------------------------
print_summary() {
  python3 - "$LOG_DIR" "$YEAR" "$CAPITAL" <<'PYEOF'
import os, re, sys
from datetime import date, timedelta

log_dir  = sys.argv[1]
year     = sys.argv[2]
capital  = float(sys.argv[3]) if len(sys.argv) > 3 else 10000.0

results = {}
for fname in sorted(os.listdir(log_dir)):
    if not re.match(r'\d{4}-\d{2}-\d{2}\.log$', fname):
        continue
    d_str = fname.replace('.log', '')
    with open(os.path.join(log_dir, fname)) as f:
        for line in f:
            m = re.search(r'cap:\s*([+-]?\$[\d,.]+)', line)
            if m:
                results[d_str] = float(m.group(1).replace('$','').replace(',',''))

if not results:
    print("No completed logs found.")
    sys.exit(0)

# -- weekly buckets --
weeks = {}
months = {}
for d_str, pnl in sorted(results.items()):
    d = date.fromisoformat(d_str)
    week_start = d - timedelta(days=d.weekday())
    wkey = str(week_start)
    if wkey not in weeks:
        weeks[wkey] = {"days": [], "pnl": 0.0}
    weeks[wkey]["days"].append((d_str, pnl))
    weeks[wkey]["pnl"] += pnl

    mkey = d.strftime("%Y-%m")
    if mkey not in months:
        months[mkey] = 0.0
    months[mkey] += pnl

print()
no_stop_flag = "$NO_STOP"
fixed_alloc_flag = "$FIXED_ALLOC"
if fixed_alloc_flag == "true":
    stop_label = "no-stop + fixed-signal-alloc"
elif no_stop_flag == "true":
    stop_label = "no-stop"
else:
    stop_label = "stop=default"
print(f"=== {year} Stock Replay (WIN-RATE MODE) ===")
print(f"    M1 09:30/3 only  |  {stop_label}")
print(f"    selector=win-rate | regime-engine | reversal | bearish/bullish-reentry | DD@10 | rank-weighted 60/40 | top8 | $10k")
print()

# -- weekly detail --
print("── WEEKLY ──────────────────────────────────────────────────────")
total = 0.0
total_days = 0
for key in sorted(weeks.keys()):
    w = weeks[key]
    n = len(w["days"])
    sign = "+" if w["pnl"] >= 0 else ""
    print(f"  Week of {key}  ({n}d)   {sign}${w['pnl']:>9,.2f}")
    for d_str, pnl in w["days"]:
        day_name = date.fromisoformat(d_str).strftime("%a")
        sign2 = "+" if pnl >= 0 else ""
        print(f"      {d_str} {day_name}   {sign2}${pnl:>8,.2f}")
    total += w["pnl"]
    total_days += n

# -- monthly summary --
print()
print("── MONTHLY ─────────────────────────────────────────────────────")
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
year_total = 0.0
for mkey in sorted(months.keys()):
    mp = months[mkey]
    sign = "+" if mp >= 0 else ""
    m_idx = int(mkey.split('-')[1]) - 1
    print(f"  {month_names[m_idx]} {mkey.split('-')[0]}   {sign}${mp:>9,.2f}   ({sign}{mp/capital*100:.1f}%)")
    year_total += mp

# -- yearly total --
print()
print("── YEARLY ──────────────────────────────────────────────────────")
sign = "+" if year_total >= 0 else ""
print(f"  {year} TOTAL   {total_days} days   {sign}${year_total:,.2f}   ({sign}{year_total/capital*100:.1f}% on ${capital:,.0f})")
print(f"  Logs complete: {len(results)} / {total_days} trading days")
print()
PYEOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if $SUMMARY_ONLY; then
  print_summary
  exit 0
fi

mkdir -p "$LOG_DIR"

ALL_DATES=()
while IFS= read -r line; do
  ALL_DATES+=("$line")
done < <(generate_trading_days)

TODO=()
for DATE in "${ALL_DATES[@]}"; do
  if $FORCE || [ ! -f "$LOG_DIR/$DATE.log" ]; then
    TODO+=("$DATE")
  else
    echo "  skip $DATE (log exists)"
  fi
done

echo ""
echo "=== $YEAR $TRADE_TYPE replay (M1 window, WIN-RATE MODE) ==="
echo "    Total trading days : ${#ALL_DATES[@]}"
echo "    To run             : ${#TODO[@]}"
echo "    Max parallel       : $MAX_PARALLEL"
echo "    Log dir            : $LOG_DIR"
echo ""

if [ ${#TODO[@]} -eq 0 ]; then
  echo "All dates already complete — printing summary."
  print_summary
  exit 0
fi

i=0
total_todo=${#TODO[@]}
while [ $i -lt $total_todo ]; do
  batch=("${TODO[@]:$i:$MAX_PARALLEL}")
  last_idx=$((${#batch[@]}-1))
  echo "--- Batch $((i/MAX_PARALLEL + 1)): ${batch[0]} → ${batch[$last_idx]} (${#batch[@]} dates) ---"
  PIDS=()
  for DATE in "${batch[@]}"; do
    replay_one "$DATE" &
    PIDS+=($!)
    echo "  started $DATE (pid $!)"
  done
  for j in "${!PIDS[@]}"; do
    if wait "${PIDS[$j]}"; then
      echo "  OK  ${batch[$j]}"
    else
      echo "  ERR ${batch[$j]} (exit $?)"
    fi
  done
  i=$((i + ${#batch[@]}))
  echo ""
done

echo "=== All replays complete ==="
echo ""
print_summary
