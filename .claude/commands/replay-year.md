---
description: 'Run full-year trade engine replay (stock, M1 09:30/3 + A1 10:00/3 + A2 13:15/1 + A3 15:15/1, parallel of 10) and report weekly P&L and total'
---

# Full-Year Stock Replay (4-window)

Run the op-momentum trade engine replay for every trading day in a given year, save per-day logs, and print a full P&L report.

## Step 1 — Parse arguments

Parse `$ARGUMENTS` for:

- **YEAR** — required integer (e.g. `2024`)
- **--trade-type** — optional. `stock` (default) or `options`. Log dir changes accordingly.
- **--force** — optional. Re-run days that already have a saved log.
- **--summary** — optional. Skip replay, just print P&L summary from existing logs.

If YEAR is missing, ask the user before proceeding.

Set:
- `SCRIPT` = `/Users/victorhuang/work/alpha_tech_tracker/run_replay_stock_4win.sh`
- `LOG_DIR` = `/Users/victorhuang/work/alpha_tech_tracker/logs/replay_${YEAR}_stock_4win`

Report the resolved parameters before running.

## Step 2 — Run the replay

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate && \
  bash ${SCRIPT} --year ${YEAR} [--trade-type stock|options] [--force] [--summary]
```

The script runs 10 days in parallel per batch. It will:
1. Skip days that already have a log (unless `--force`)
2. Print `OK` / `ERR` per day as each batch completes
3. Print the full weekly + total P&L summary when done

If any days show `ERR`, re-run them individually:
```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate && \
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --log-level DEBUG --trade-type stock \
  --window M1 09:30 3 --window A1 10:00 3 --window A2 13:15 1 --window A3 15:15 1 \
  --morning-split 100 --bearish-reentry --bullish-reentry --reversal \
  --rank-weighted-sizing 60 40 --doubledown --doubledown-start 10 \
  --top 2 --capital 10000 --mock-trade-execution --feed sip \
  --replay-date YYYY-MM-DD \
  > ${LOG_DIR}/YYYY-MM-DD.log 2>&1
```

## Step 3 — Report results

Present results clearly:

1. **Configuration** — year, log directory, days complete
2. **Weekly P&L table** — all weeks with daily breakdown
3. **Total** — total capital P&L and % return on $10k

Also note any losing weeks or standout days.
