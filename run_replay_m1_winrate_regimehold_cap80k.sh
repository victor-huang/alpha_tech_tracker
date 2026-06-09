#!/bin/bash
# run_replay_m1_winrate_regimehold_cap80k.sh
# Config: M1 09:30/3 | win-rate selector | regime-engine | regime-hold
#         stop-pct 0 | trailing-ma none | top 8 | $80k capital
#
# Parallelism: one process per calendar month; days within a month run sequentially.
# Up to MAX_PARALLEL months run concurrently.
#
# Usage:
#   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026
#   ./run_replay_m1_winrate_regimehold_cap80k.sh --start 2026-03-01 --end 2026-06-30
#   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026 --summary
#   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026 --force
#   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026 --fixed-signal-alloc --compact-summary
#   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2016 --fixed-signal-alloc --warmup

set -euo pipefail

PYTHONPATH_DIR="/Users/victorhuang/work/alpha_tech_tracker"
BASE_LOG_DIR="/Users/victorhuang/work/alpha_tech_tracker/logs"
MAX_PARALLEL=18
SUMMARY_ONLY=false
COMPACT_SUMMARY=false
FORCE=false
YEAR=""
START=""
END=""
FEED="sip"
CAPITAL=80000
EXTEND_COLLECTION_BARS=2
STOP_PCT=0
FIXED_SIGNAL_ALLOC=false
REVERSAL=false
DOUBLEDOWN=false
DIRECTION_AWARE=false
WARMUP=false   # run only the first trading day of each month (2 parallel streams)

while [ $# -gt 0 ]; do
  case "$1" in
    --year)                   YEAR="$2"; START="${2}-01-01"; END="${2}-12-31"; shift 2 ;;
    --start)                  START="$2";                   shift 2 ;;
    --end)                    END="$2";                     shift 2 ;;
    --feed)                   FEED="$2";                    shift 2 ;;
    --extend-collection-bars) EXTEND_COLLECTION_BARS="$2";  shift 2 ;;
    --stop-pct)               STOP_PCT="$2";                shift 2 ;;
    --fixed-signal-alloc)     FIXED_SIGNAL_ALLOC=true;      shift ;;
    --reversal)               REVERSAL=true;                shift ;;
    --doubledown)             DOUBLEDOWN=true;              shift ;;
    --direction-aware-scoring) DIRECTION_AWARE=true;        shift ;;
    --summary)                SUMMARY_ONLY=true;            shift ;;
    --compact-summary)        COMPACT_SUMMARY=true;         shift ;;
    --force)                  FORCE=true;                   shift ;;
    --warmup)                 WARMUP=true;                  shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$START" ] || [ -z "$END" ]; then
  echo "Usage: $0 --year YYYY | --start YYYY-MM-DD --end YYYY-MM-DD"
  echo "       [--summary] [--compact-summary] [--force] [--feed sip|iex]"
  echo "       [--extend-collection-bars N] [--stop-pct N]"
  echo "       [--fixed-signal-alloc] [--reversal] [--doubledown]"
  echo "       [--direction-aware-scoring] [--warmup]"
  exit 1
fi

# Derive YEAR label for log dir when --start/--end used directly
if [ -z "$YEAR" ]; then
  START_YR="${START:0:4}"
  END_YR="${END:0:4}"
  if [ "$START_YR" = "$END_YR" ]; then
    YEAR="$START_YR"
  else
    YEAR="${START_YR}_${END_YR}"
  fi
fi

TICKERS="SNDK META SNOW PLTR MU LLY LUNR CRWD QCOM OKLO TSLA AVGO ARM AMD DDOG RDDT IONQ HOOD RKLB CLSK"

TICKER_HASH=$(python3 -c "import hashlib; print(hashlib.md5(' '.join(sorted('$TICKERS'.split())).encode()).hexdigest()[:8])")

LOG_SUFFIX=""
[ "$EXTEND_COLLECTION_BARS" -ne 2 ] && LOG_SUFFIX="${LOG_SUFFIX}_ecb${EXTEND_COLLECTION_BARS}"
[ "$(echo "$STOP_PCT > 0" | bc -l)" = "1" ] && LOG_SUFFIX="${LOG_SUFFIX}_stop$(echo "$STOP_PCT" | tr '.' 'p')"
$FIXED_SIGNAL_ALLOC && LOG_SUFFIX="${LOG_SUFFIX}_fixedalloc"
$REVERSAL          && LOG_SUFFIX="${LOG_SUFFIX}_reversal"
$DOUBLEDOWN        && LOG_SUFFIX="${LOG_SUFFIX}_dd"
$DIRECTION_AWARE   && LOG_SUFFIX="${LOG_SUFFIX}_diraware"
LOG_DIR="$BASE_LOG_DIR/replay_${YEAR}_stock_m1_winrate_regimehold_cap80k${LOG_SUFFIX}_t${TICKER_HASH}"

# ---------------------------------------------------------------------------
# Generate trading days for START..END via Python (NYSE holidays 2015-2026)
# ---------------------------------------------------------------------------
generate_trading_days() {
  python3 -c "
from datetime import date, timedelta

today = date.today()

holidays = {
    date(2015,1,1), date(2015,1,19), date(2015,2,16),
    date(2015,4,3), date(2015,5,25), date(2015,7,3),
    date(2015,9,7), date(2015,11,26), date(2015,12,25),
    date(2016,1,1), date(2016,1,18), date(2016,2,15),
    date(2016,3,25), date(2016,5,30), date(2016,7,4),
    date(2016,9,5), date(2016,11,24), date(2016,12,26),
    date(2017,1,2), date(2017,1,16), date(2017,2,20),
    date(2017,4,14), date(2017,5,29), date(2017,7,4),
    date(2017,9,4), date(2017,11,23), date(2017,12,25),
    date(2018,1,1), date(2018,1,15), date(2018,2,19),
    date(2018,3,30), date(2018,5,28), date(2018,7,4),
    date(2018,9,3), date(2018,11,22), date(2018,12,25),
    date(2019,1,1), date(2019,1,21), date(2019,2,18),
    date(2019,4,19), date(2019,5,27), date(2019,7,4),
    date(2019,9,2), date(2019,11,28), date(2019,12,25),
    date(2020,1,1), date(2020,1,20), date(2020,2,17),
    date(2020,4,10), date(2020,5,25), date(2020,7,3),
    date(2020,9,7), date(2020,11,26), date(2020,12,25),
    date(2021,1,1), date(2021,1,18), date(2021,2,15),
    date(2021,4,2), date(2021,5,31), date(2021,7,5),
    date(2021,9,6), date(2021,11,25), date(2021,12,24),
    date(2022,1,17), date(2022,2,21), date(2022,4,15),
    date(2022,5,30), date(2022,6,19), date(2022,7,4),
    date(2022,9,5), date(2022,11,24), date(2022,12,26),
    date(2023,1,2), date(2023,1,16), date(2023,2,20),
    date(2023,4,7), date(2023,5,29), date(2023,6,19),
    date(2023,7,4), date(2023,9,4), date(2023,11,23), date(2023,12,25),
    date(2024,1,1), date(2024,1,15), date(2024,2,19),
    date(2024,3,29), date(2024,5,27), date(2024,6,19),
    date(2024,7,4), date(2024,9,2), date(2024,11,28), date(2024,12,25),
    date(2025,1,1), date(2025,1,20), date(2025,2,17),
    date(2025,4,18), date(2025,5,26), date(2025,6,19),
    date(2025,7,4), date(2025,9,1), date(2025,11,27), date(2025,12,25),
    date(2026,1,1), date(2026,1,19), date(2026,2,16),
    date(2026,4,3), date(2026,5,25), date(2026,6,19),
    date(2026,7,3), date(2026,9,7), date(2026,11,26), date(2026,12,25),
}

start = date.fromisoformat('$START')
end   = date.fromisoformat('$END')
if end > today:
    end = today

d = start
while d <= end:
    if d.weekday() < 5 and d not in holidays:
        print(str(d))
    d += timedelta(days=1)
"
}

# ---------------------------------------------------------------------------
# Replay a single date (writes to LOG_DIR/DATE.log)
# ---------------------------------------------------------------------------
replay_one() {
  local DATE="$1"
  local LOG="$LOG_DIR/$DATE.log"
  PYTHONPATH="$PYTHONPATH_DIR" \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    --log-level DEBUG \
    --trade-type stock \
    --tickers $TICKERS \
    --selector win-rate \
    --enable-regime-engine \
    --window M1 09:30 3 \
    --morning-split 100 \
    --top 8 --capital $CAPITAL \
    --stop-pct $STOP_PCT \
    --trailing-ma none \
    --regime-hold \
    $([ "$EXTEND_COLLECTION_BARS" -ne 2 ] && echo "--extend-collection-bars $EXTEND_COLLECTION_BARS") \
    $($REVERSAL       && echo "--bearish-reentry --bullish-reentry --reversal") \
    $($DOUBLEDOWN     && echo "--doubledown --doubledown-start 10") \
    $($FIXED_SIGNAL_ALLOC && echo "--fixed-signal-alloc") \
    $($DIRECTION_AWARE && echo "--direction-aware-scoring") \
    --mock-trade-execution \
    --feed "$FEED" \
    --replay-date "$DATE" > "$LOG" 2>&1
}

# ---------------------------------------------------------------------------
# Replay one calendar month: all days run sequentially in a single process
# ---------------------------------------------------------------------------
replay_month() {
  local MKEY="$1"   # e.g. "2019-03"
  shift
  local DATES=("$@")
  echo "  [${MKEY}] starting ${#DATES[@]} days"
  for DATE in "${DATES[@]}"; do
    if $FORCE || [ ! -f "$LOG_DIR/$DATE.log" ]; then
      if replay_one "$DATE"; then
        echo "  [${MKEY}] OK  $DATE"
      else
        echo "  [${MKEY}] ERR $DATE"
      fi
    else
      echo "  [${MKEY}] skip $DATE (cached)"
    fi
  done
  echo "  [${MKEY}] done"
}

# ---------------------------------------------------------------------------
# P&L summary: monthly + yearly breakdown
# ---------------------------------------------------------------------------
print_summary() {
  python3 - "$LOG_DIR" "$YEAR" "$CAPITAL" "$COMPACT_SUMMARY" <<'PYEOF'
import math, os, re, sys
from datetime import date, timedelta

log_dir = sys.argv[1]
year    = sys.argv[2]
capital = float(sys.argv[3])
compact = len(sys.argv) > 4 and sys.argv[4] == 'true'

results  = {}
deployed = {}
for fname in sorted(os.listdir(log_dir)):
    if not re.match(r'\d{4}-\d{2}-\d{2}\.log$', fname):
        continue
    d_str = fname.replace('.log', '')
    with open(os.path.join(log_dir, fname)) as f:
        for line in f:
            m = re.search(r'cap:\s*([+-]?\$[\d,.]+)', line)
            if m:
                results[d_str] = float(m.group(1).replace('$','').replace(',',''))
            md = re.search(r'\$(\d[\d,]*)\s+deployed', line)
            if md:
                deployed[d_str] = float(md.group(1).replace(',',''))

if not results:
    print("No completed logs found.")
    sys.exit(0)

weeks  = {}
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
print(f"=== {year} Stock Replay — M1 win-rate | regime-hold | no-stop | top8 | ${capital:,.0f} ===")
print()

if not compact:
    print("── WEEKLY ──────────────────────────────────────────────────────")
total_days = 0
for key in sorted(weeks.keys()):
    w = weeks[key]
    n = len(w["days"])
    if not compact:
        sign = "+" if w["pnl"] >= 0 else ""
        print(f"  Week of {key}  ({n}d)   {sign}${w['pnl']:>9,.2f}")
        for d_str, pnl in w["days"]:
            day_name = date.fromisoformat(d_str).strftime("%a")
            sign2 = "+" if pnl >= 0 else ""
            print(f"      {d_str} {day_name}   {sign2}${pnl:>8,.2f}")
    total_days += n

print()
print("── MONTHLY ─────────────────────────────────────────────────────")
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
year_total = 0.0
for mkey in sorted(months.keys()):
    mp = months[mkey]
    sign = "+" if mp >= 0 else ""
    m_idx = int(mkey.split('-')[1]) - 1
    print(f"  {month_names[m_idx]} {mkey.split('-')[0]}   {sign}${mp:>9,.2f}")
    year_total += mp

print()
print("── YEARLY ──────────────────────────────────────────────────────")
sign = "+" if year_total >= 0 else ""
total_dep = sum(deployed.get(d, 0.0) for d in results)
avg_dep = total_dep / total_days if total_days else 0.0
ret_on_deployed = year_total / avg_dep * 100 if avg_dep > 0 else 0.0
ret_sign = "+" if ret_on_deployed >= 0 else ""
print(f"  {year} TOTAL   {total_days} days   {sign}${year_total:,.2f}   committed: {sign}{year_total/capital*100:.1f}%")
print(f"  Return on avg capital deployed : {ret_sign}{ret_on_deployed:.1f}%  (avg ${avg_dep:,.0f}/day deployed)")
print(f"  Logs complete: {len(results)} / {total_days} trading days")

days_with_dep = [(results[d], deployed[d]) for d in results if deployed.get(d, 0.0) > 0]
util = total_dep / (total_days * capital) if total_days else 0.0
pnl_per_dollar = year_total / total_dep if total_dep > 0 else 0.0
mean_rodc_str = "n/a"
dw_sharpe_str = "n/a"
if days_with_dep:
    rodcs = [p / d for p, d in days_with_dep]
    mean_rodc_str = f"{sum(rodcs) / len(rodcs) * 100:+.3f}%"
    if len(days_with_dep) >= 2:
        deps = [d for _, d in days_with_dep]
        avg_dep = sum(deps) / len(deps)
        w = [d / avg_dep for d in deps]
        w_sum = sum(w)
        w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
        w_var = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
        w_std = math.sqrt(w_var) if w_var > 0 else 0.0
        if w_std > 0:
            dw_sharpe_str = f"{w_mean / w_std * math.sqrt(252):.2f}"
pnl_sign = "+" if pnl_per_dollar >= 0 else ""
print()
print("── DEPLOYMENT METRICS ──────────────────────────────────────────")
print(f"  Total deployed       : ${total_dep:,.0f}")
print(f"  Capital utilization  : {util*100:.1f}%  (avg daily / ${capital:,.0f})")
print(f"  P&L per $ deployed   : {pnl_sign}{pnl_per_dollar:.4f}  (cumulative)")
print(f"  Mean daily RODC      : {mean_rodc_str}  (avg per-day return on deployed)")
print(f"  DW-Sharpe            : {dw_sharpe_str}")
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

echo ""
RUN_LABEL=" | stop=${STOP_PCT}"
[ "$EXTEND_COLLECTION_BARS" -ne 2 ] && RUN_LABEL="${RUN_LABEL} | ecb=${EXTEND_COLLECTION_BARS}"
$FIXED_SIGNAL_ALLOC && RUN_LABEL="${RUN_LABEL} | fixed-signal-alloc"
$REVERSAL           && RUN_LABEL="${RUN_LABEL} | reversal+reentry"
$DOUBLEDOWN         && RUN_LABEL="${RUN_LABEL} | doubledown"
$DIRECTION_AWARE    && RUN_LABEL="${RUN_LABEL} | dir-aware"
$WARMUP             && RUN_LABEL="${RUN_LABEL} | warmup"
echo "=== $YEAR replay — M1 win-rate | regime-hold | top8 | \$${CAPITAL}${RUN_LABEL} ==="
echo "    Total trading days : ${#ALL_DATES[@]}"
echo "    Max parallel months: $MAX_PARALLEL"
echo "    Log dir            : $LOG_DIR"
echo ""

# ---------------------------------------------------------------------------
# Warmup mode: run first trading day of each month in two parallel streams
# ---------------------------------------------------------------------------
if $WARMUP; then
  # Collect first day of each month (dates already sorted)
  FIRST_DAYS=()
  PREV_MONTH=""
  for D in "${ALL_DATES[@]}"; do
    M="${D:0:7}"
    if [ "$M" != "$PREV_MONTH" ]; then
      FIRST_DAYS+=("$D")
      PREV_MONTH="$M"
    fi
  done

  N=${#FIRST_DAYS[@]}
  HALF=$(( N / 2 ))
  FORWARD=("${FIRST_DAYS[@]:0:$HALF}")
  # Reverse the second half
  BACKWARD=()
  for (( i=N-1; i>=HALF; i-- )); do
    BACKWARD+=("${FIRST_DAYS[$i]}")
  done

  echo "=== WARMUP: first trading day per month ==="
  for D in "${FORWARD[@]}";  do printf "  fwd %s\n" "$D"; done
  for D in "${BACKWARD[@]}"; do printf "  bwd %s\n" "$D"; done
  echo ""

  (
    for D in "${FORWARD[@]}"; do
      if $FORCE || [ ! -f "$LOG_DIR/$D.log" ]; then
        echo "  [fwd] running $D"
        replay_one "$D" && echo "  [fwd] OK $D" || echo "  [fwd] ERR $D"
      else
        echo "  [fwd] skip $D (cached)"
      fi
    done
  ) &
  FWD_PID=$!

  (
    for D in "${BACKWARD[@]}"; do
      if $FORCE || [ ! -f "$LOG_DIR/$D.log" ]; then
        echo "  [bwd] running $D"
        replay_one "$D" && echo "  [bwd] OK $D" || echo "  [bwd] ERR $D"
      else
        echo "  [bwd] skip $D (cached)"
      fi
    done
  ) &
  BWD_PID=$!

  wait $FWD_PID
  wait $BWD_PID
  echo ""
  echo "=== WARMUP complete — run without --warmup to replay remaining days ==="
  exit 0
fi

# ---------------------------------------------------------------------------
# Group trading days by calendar month using a temp dir (bash 3 compatible)
# ---------------------------------------------------------------------------
MONTHS_TMPDIR=$(mktemp -d)
trap 'rm -rf "$MONTHS_TMPDIR"' EXIT

for DATE in "${ALL_DATES[@]}"; do
  MKEY="${DATE:0:7}"
  echo "$DATE" >> "$MONTHS_TMPDIR/$MKEY.txt"
done

MONTH_FILES=($(ls "$MONTHS_TMPDIR"/*.txt 2>/dev/null | sort))
TOTAL_MONTHS=${#MONTH_FILES[@]}

echo "    Calendar months    : $TOTAL_MONTHS"
echo ""

# ---------------------------------------------------------------------------
# Run up to MAX_PARALLEL months concurrently; days within each month sequential
# ---------------------------------------------------------------------------
i=0
while [ $i -lt $TOTAL_MONTHS ]; do
  batch=("${MONTH_FILES[@]:$i:$MAX_PARALLEL}")
  last_idx=$(( ${#batch[@]} - 1 ))
  FIRST_MKEY=$(basename "${batch[0]}" .txt)
  LAST_MKEY=$(basename "${batch[$last_idx]}" .txt)
  echo "--- Month batch $((i / MAX_PARALLEL + 1)): ${FIRST_MKEY} → ${LAST_MKEY} (${#batch[@]} months) ---"

  PIDS=()
  for MFILE in "${batch[@]}"; do
    MKEY=$(basename "$MFILE" .txt)
    DAYS=($(cat "$MFILE"))
    replay_month "$MKEY" "${DAYS[@]}" &
    PIDS+=($!)
  done

  for j in "${!PIDS[@]}"; do
    wait "${PIDS[$j]}" || true
  done

  i=$(( i + ${#batch[@]} ))
  echo ""
done

echo "=== All replays complete ==="
echo ""
print_summary
