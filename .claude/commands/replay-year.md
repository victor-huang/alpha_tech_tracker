---
description: 'Run full-year trade engine replay (options, M1+A1+A2, parallel of 8) and report weekly/monthly P&L, streaks, top-10 days'
---

# Full-Year Replay

Run the op-momentum trade engine replay for every trading day in a given year (or date range), save per-day logs, and print a full stats report.

## Step 1 — Parse arguments

Parse `$ARGUMENTS` for these values:

- **YEAR** — required integer (e.g. `2025`). Alternatively accept `--start YYYY-MM-DD --end YYYY-MM-DD` for a custom range.
- **--live-data-dir PATH** — optional. Path to the BarRecorder CSV directory (e.g. `alpha_tech_tracker/op_momentum_strategy/live_trade_market_data`). When provided, each replay day will load intraday bars from recorded CSVs instead of the Alpaca cache.
- **--live-data-feed FEED** — optional, only meaningful when `--live-data-dir` is set. Either `iex` or `tradestation`. Default: `iex`.
- **--force** — optional flag. If set, re-run days that already have a saved log file.

Accepted formats:
- `2025` → YEAR=2025, no live data
- `2025 --live-data-dir alpha_tech_tracker/op_momentum_strategy/live_trade_market_data` → YEAR=2025, live CSV mode
- `2025 --live-data-dir /path/to/dir --live-data-feed tradestation` → YEAR=2025, TradeStation CSV mode
- `--start 2025-06-01 --end 2025-09-30` → custom range, no live data
- `--start 2025-06-01 --end 2025-09-30 --live-data-dir /path/to/dir` → custom range, live CSV mode

If YEAR is missing and no `--start/--end` given, ask the user before proceeding.

Set:
- `PYTHONPATH` = `/Users/victorhuang/work/alpha_tech_tracker`
- `PYTHON` = `/Users/victorhuang/.pyenv/versions/alpha_tech_tracker/bin/python`
- `SCRIPT` = `/Users/victorhuang/work/alpha_tech_tracker/run_replay_year.py`
- `LOG_BASE` = `/Users/victorhuang/work/alpha_tech_tracker/logs`

Report the resolved parameters before running.

## Step 2 — Build the command

For a full-year run:
```
YEAR_ARG="--year ${YEAR}"
```

For a custom date range:
```
YEAR_ARG="--start ${START} --end ${END}"
```

Live-data flags (append only when `--live-data-dir` was provided):
```
LIVE_ARGS="--live-data-dir ${LIVE_DATA_DIR} --live-data-feed ${LIVE_DATA_FEED}"
```

Force flag (append only when `--force` was provided):
```
FORCE_ARG="--force"
```

Full command:
```bash
PYTHONPATH=${PYTHONPATH} ${PYTHON} ${SCRIPT} \
  ${YEAR_ARG} \
  [${LIVE_ARGS}] \
  [${FORCE_ARG}]
```

## Step 3 — Determine expected log directory

The script saves logs to:
- `--year N` → `${LOG_BASE}/replay_${YEAR}/`
- `--start/--end` → `${LOG_BASE}/replay_${START}_${END}/`

Note this path — you will report it to the user at the end.

## Step 4 — Run the replay

Run the command from Step 2. The script:

1. **Phase 1 (sequential)** — runs one warmup day per calendar month first (sequentially) to populate the bar cache before parallel runs start. Prints `skip ... [cached]` for days that already have logs.
2. **Phase 2 (parallel of 8)** — runs all remaining trading days in parallel. Progress is printed live: `[N/M] YYYY-MM-DD  +$X,XXX.XX (+XX.XX%)`.
3. **After completion** — automatically prints the full stats report and saves it to `${LOG_DIR}/RESULTS.txt`.

Expected runtime:
- Full year with warm cache: ~15–25 min (all days served from cache in seconds each)
- Full year cold (first run for that year): ~45–90 min

Wait for the script to finish — do **not** interrupt it. If it exits with a non-zero code, report the last 30 lines of output and stop.

## Step 5 — Report results

Once the script completes, read and display the saved results file:

```bash
cat ${LOG_DIR}/RESULTS.txt
```

Present the results to the user with these sections clearly labeled:

1. **Configuration summary** — year/range, live-data mode, log directory
2. **Weekly P&L table** — all weeks (from RESULTS.txt)
3. **Monthly P&L table** — all months
4. **Top-10 best days** — date, P&L, pct
5. **Top-10 worst days** — date, P&L, pct
6. **Longest winning streak** — dates + streak P&L
7. **Longest losing streak** — dates + streak P&L
8. **Totals** — total P&L, trading days, win/loss count, win rate

Also report:
- Path to the RESULTS.txt file
- Path to the per-day log directory
- Any days that show `$0.00` P&L (no-trade days) — list them separately for awareness
