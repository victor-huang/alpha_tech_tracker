---
description: 'SCP live market data from EC2 (stock or options engine), TGZ + untar locally, then 3-way replay comparison: live CSV vs API cache vs backtest'
---

# Replay Comparison — Live CSV vs API Cache vs Backtest

Compare three sources for the same trading date to understand P&L and trade differences.

## Step 1 — Resolve the date, feed, and engine

Parse `$ARGUMENTS` for three values:
- **DATE** — required, format `YYYY-MM-DD`. If omitted, ask the user — do not guess.
- **FEED** — optional, either `iex` or `sip`. Default: `iex`.
- **ENGINE** — optional, either `stock` or `options`. Default: `stock`.

Accepted argument formats:
- `2026-04-13` → DATE=2026-04-13, FEED=iex, ENGINE=stock
- `2026-04-13 sip` → DATE=2026-04-13, FEED=sip, ENGINE=stock
- `2026-04-13 --feed sip` → DATE=2026-04-13, FEED=sip, ENGINE=stock
- `2026-04-13 options` → DATE=2026-04-13, FEED=iex, ENGINE=options
- `2026-04-13 --engine options` → DATE=2026-04-13, FEED=iex, ENGINE=options
- `2026-04-13 sip options` → DATE=2026-04-13, FEED=sip, ENGINE=options

Set:
- `DATE` = YYYY-MM-DD
- `FEED` = `iex` (or `sip` if specified)
- `ENGINE` = `stock` or `options`
- `EC2_HOST` = `ec2-user@ec2-3-133-120-51.us-east-2.compute.amazonaws.com`
- `EC2_KEY` = `~/.ssh/trade-sys.pem`
- If ENGINE=stock:
  - `EC2_LIVE_DATA_ROOT` = `/home/ec2-user/alpha_tech_tracker_stock_engine/alpha_tech_tracker/op_momentum_strategy/live_trade_market_data`
- If ENGINE=options:
  - `EC2_LIVE_DATA_ROOT` = `/home/ec2-user/alpha_tech_tracker/alpha_tech_tracker/op_momentum_strategy/live_trade_market_data`
- `LOCAL_LIVE_DATA_ROOT` = `alpha_tech_tracker/op_momentum_strategy/live_trade_market_data`
- `TGZ_FILE` = `live_trade_market_data_${ENGINE}_${DATE}.tgz`
- `LOG_DIR` = `logs/replay`
- `LOG_LIVE` = `${LOG_DIR}/compare_live_${ENGINE}_${DATE}.log`
- `LOG_API` = `${LOG_DIR}/compare_api_${ENGINE}_${DATE}.log`

Report the resolved DATE, FEED, and ENGINE before proceeding.

## Step 2 — Create TGZ on EC2 (date folder only)

SSH into EC2 and create a compressed archive of **only the `${DATE}` subdirectory** — not the entire `live_trade_market_data` root. This keeps the archive small (one day of CSVs).

First verify the date directory exists on EC2:

```bash
ssh -i ${EC2_KEY} ${EC2_HOST} \
  "ls ${EC2_LIVE_DATA_ROOT}/${DATE}/*.csv 2>/dev/null | wc -l"
```

If the output is `0`, report that the date directory is missing or empty on EC2 and stop.

Then create the archive:

```bash
ssh -i ${EC2_KEY} ${EC2_HOST} \
  "tar -czf /tmp/${TGZ_FILE} -C ${EC2_LIVE_DATA_ROOT} ${DATE} && echo OK"
```

- The `-C ${EC2_LIVE_DATA_ROOT} ${DATE}` ensures only the single date folder is archived, not parent directories.
- If the ssh command fails, report the error and stop.
- On success the command prints `OK`.

## Step 3 — SCP the TGZ to local

Transfer the archive from EC2 to the current working directory:

```bash
scp -i ${EC2_KEY} ${EC2_HOST}:/tmp/${TGZ_FILE} ./${TGZ_FILE}
```

- If the local `${TGZ_FILE}` already exists, overwrite it (idempotent).
- Report the local archive size after transfer completes.

## Step 4 — Untar the archive to the local live data directory

Extract the archive into the same local directory used by `--live-data-dir`:

```bash
mkdir -p ${LOCAL_LIVE_DATA_ROOT}
tar -xzf ${TGZ_FILE} -C ${LOCAL_LIVE_DATA_ROOT}
```

Verify the extraction:

```bash
ls ${LOCAL_LIVE_DATA_ROOT}/${DATE}/*.csv | wc -l
```

- Report the number of CSV files extracted.
- If zero files, report clearly and stop — replay with `--live-data-dir` cannot run.

## Step 5 — Verify the archive contents

Run a listing to confirm the archive contains the expected files:

```bash
tar -tzf ${TGZ_FILE} | head -20
echo "Total entries: $(tar -tzf ${TGZ_FILE} | wc -l)"
```

Report how many files are listed and confirm the date directory is at the correct path inside the archive.

## Step 6 — Define the shared engine config

The standard stock-trading replay config used for all three runs. **Do not change these flags between runs** — any flag difference will corrupt the comparison.

```
BASE_FLAGS="
  --trade-type stock
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
  --reversal --bearish-reentry --bullish-reentry
  --doubledown
  --top 2 --capital 10000
  --rank-weighted-sizing 60 40 --feed ${FEED}
  --mock-trade-execution --log-level DEBUG
"
```

The backtest equivalent (translated flags — `--weights` instead of `--rank-weighted-sizing`, no `--trade-type`/`--mock-trade-execution`/`--log-level`):

```
BACKTEST_FLAGS="
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
  --reversal --bearish-reentry --bullish-reentry
  --doubledown
  --top 2 --capital 10000
  --weights 60 40 --feed ${FEED}
  --show-execution-log
"
```

## Step 7 — Run A: Replay with live CSV data (`--live-data-dir`)

Run the trade engine replay using bars recorded by `BarRecorder` during the actual session:

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date ${DATE} \
  --live-data-dir ${LOCAL_LIVE_DATA_ROOT} \
  --log-file ${LOG_LIVE} \
  ${BASE_FLAGS}
```

Wait for it to complete (runs synchronously). If it errors, report the full error and stop.

## Step 8 — Run B: Replay with API/cache data (no live dir)

Run the same config without `--live-data-dir` so the engine fetches from Alpaca historical API / local cache:

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date ${DATE} \
  --log-file ${LOG_API} \
  ${BASE_FLAGS}
```

Wait for it to complete. If it errors, report the full error and stop.

## Step 9 — Run C: Selector backtest for the same single date

Run the selector backtest constrained to just `${DATE}`:

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start ${DATE} --end ${DATE} \
  ${BACKTEST_FLAGS} 2>&1
```

Capture the full stdout. If it errors, report the full error and stop.

## Step 10 — Extract trade summaries

For Run A and Run B, extract all capital-returned lines and DAILY TRADE SUMMARY from each log:

```bash
grep "Capital returned\|SIGNAL\|Selecting.*from buffer\|SIMULATE BUY\|SIMULATE SELL\|EXIT.*reason\|Daily P&L\|cap:" ${LOG_LIVE}
grep "Capital returned\|SIGNAL\|Selecting.*from buffer\|SIMULATE BUY\|SIMULATE SELL\|EXIT.*reason\|Daily P&L\|cap:" ${LOG_API}
```

For Run C (backtest), use the captured stdout — find the per-date execution log rows and the capital simulation summary.

Extract for each run:
- Total daily cap P&L
- Number of trades (primary + re-entries)
- Per-trade: Window, Ticker, Signal type, Entry price, Exit price, P&L, Exit reason
- A2 signal pool: which tickers fired and their directions

## Step 11 — Compare and analyze

Present the three results in a side-by-side table:

### Summary Table

| Metric | Run A (Live CSV) | Run B (API Cache) | Run C (Backtest) |
|---|---|---|---|
| Daily cap P&L | | | |
| Trade count | | | |
| Capital deployed | | | |

### Per-Trade Diff Table

For each unique (window, ticker, signal_type) combination that appears in any run, show whether it was present in all three, and what differed (entry price, exit price, exit reason, P&L).

Group by window (M1 / A1 / A2) for readability. For re-entries (BRE, BUE, reversal), show parent trade → re-entry chain.

## Step 12 — Root cause analysis

For each divergence found in Step 10, investigate in this order:

### 11a. Ticker selection differences

- Extract `Selecting ... from buffer` and `SIGNAL [WINDOW]` lines for the diverging window from both replay logs.
- Report the full signal pool (all tickers that fired) for each run — not just the selected top-2.
- If the pools differ, the bar OHLC for the 15:00 (or other) bar differs between sources.

### 11b. Signal direction differences (Bullish vs Bearish)

- For any ticker that fired in one source but not the other, extract its `SIGNAL` log line and report:
  - `or_high`, `or_low`, `close` values
  - Whether close is above/below OR midpoint
  - Whether close is above/below MA20
- Even small OHLC differences at bar edges (e.g. a ±$0.10 close difference on a $944 stock) can flip whether the condition is met.

### 11c. Exit timing differences

- If the same trade appears in multiple runs but exits at different times, check whether the hard stop threshold or trailing MA crossed at different bars.
- Report: entry price, stop threshold (= OR edge ± stop_pct × OR range), exit bar close, MA20 at exit bar.

### 11d. Backtest vs replay structural differences

Common reasons for backtest vs replay divergence with stock trading:

- **Stock vs options P&L basis**: With `--trade-type stock`, both replay and backtest trade shares — P&L is now directly comparable in dollar terms (unlike the options case where replay used MockOptionPricer leverage).
- **BRE/BUE timing**: Backtest processes bars in a full-day batch; replay fires bar-by-bar. A re-entry that triggers mid-bar in batch may enter 1 bar later in replay.
- **Capital recycling timing**: A same-bar exit+re-entry in batch may be sequenced differently bar-by-bar.
- **Score staleness**: Backtest runs a fresh 60-day rolling lookback per date; replay uses the pre-market selector scores fetched at engine startup. If the lookback window differs, scores and top-N picks differ.
- **Double-down timing**: DD fires after the first exit frees capital; bar-by-bar timing may differ by 1 bar vs batch.

Report which structural differences apply for each divergence observed.

## Step 13 — Report

Present a final summary with:

1. **Three-way P&L comparison** — one-line summary of each run's result
2. **Key divergences** — bulleted list of each trade that differed and why (window, ticker, what changed)
3. **Root cause classification** — group divergences by type:
   - Bar construction difference (live WebSocket OHLC vs API historical OHLC)
   - Ticker selection (different signal pool → different top-N)
   - Signal direction flip (close near OR midpoint or MA20 threshold)
   - Exit timing (stop or MA threshold crossed on different bar)
   - Structural backtest vs replay difference (BRE/BUE timing, capital recycling, score staleness)
4. **Faithfulness ranking** — which source is most representative of actual live engine behavior and why (expected: Live CSV > API Cache > Backtest for fidelity to real execution)
5. **Output files** — report paths to `${LOG_LIVE}`, `${LOG_API}`, `${TGZ_FILE}`
