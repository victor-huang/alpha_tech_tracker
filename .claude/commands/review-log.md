---
description: 'SCP today''s options and stock trading logs from EC2, then run daily bug analysis on both'
---

# Daily Log Review

## Step 1 — Determine the log date

The target date is today unless the user specified a date in $ARGUMENTS (accept formats: `YYYY-MM-DD`, `MM-DD`, or natural language like "yesterday").

- If $ARGUMENTS is empty, use today's date in ET (America/New_York).
- Resolve the date and set LOG_DATE = YYYY-MM-DD.
- Set EC2_HOST = `ec2-user@ec2-3-133-120-51.us-east-2.compute.amazonaws.com`
- Set EC2_KEY = `~/.ssh/trade-sys.pem`
- Set REMOTE_LOG_FILE = `op_momentum_${LOG_DATE}.log`
- Set LOCAL_OPTION_LOG = `logs/op_momentum_option_${LOG_DATE}.log`
- Set LOCAL_STOCK_LOG = `logs/op_momentum_stock_${LOG_DATE}.log`

Report the resolved date before proceeding.

## Step 2 — SCP both logs from EC2

### 2a. Options engine log

```bash
scp -i ${EC2_KEY} \
  ${EC2_HOST}:/home/ec2-user/alpha_tech_tracker/logs/${REMOTE_LOG_FILE} \
  ${LOCAL_OPTION_LOG}
```

### 2b. Stock engine log

```bash
scp -i ${EC2_KEY} \
  ${EC2_HOST}:/home/ec2-user/alpha_tech_tracker_stock_engine/logs/${REMOTE_LOG_FILE} \
  ${LOCAL_STOCK_LOG}
```

For each SCP:
- Always overwrite the local file (always fetch latest — the file may have grown since last download).
- If scp fails (file not found on server, connection error, etc.), report the error clearly and skip analysis for that log. Continue with the other if it succeeded.
- Report the file size after each download.

## Step 3 — Run daily bug analysis

Analyse both log files for bugs, incorrect behaviour, and anomalies. The system is an intraday options and stock momentum trading engine running on a 16-ticker pool. Label each finding with **[OPTIONS]** or **[STOCK]** to indicate which log it came from.

Work through each log in this order:

### 3a. Errors and exceptions
Search for `ERROR`, `Exception`, `Traceback`, `WARNING`. For each occurrence report:
- Log source, line number, and timestamp
- What failed and why (read the full traceback)
- Whether it caused a missed trade or silent data loss

### 3b. Signal and entry review
- List every `SIGNAL` that fired per window (M1, A1, A2)
- List every `Entering position` — confirm it matches a prior signal
- Check that BEARISH stock entries say `SELL SHORT` (not `BUY`) in SMS/Telegram notifications
- Check that BULLISH entries say `BUY`
- Flag any signal that was buffered but never entered (skipped due to negative EV, no budget, or error)

### 3c. Order execution
- Find any `Failed to place` errors
- Check for `ask=0` or `bid=0` in `STOCK FILL_ESC step1` lines — these cause step2 to submit a $0 limit price
- Check for `insufficient options buying power` — confirms 40310000 abort fired correctly
- Confirm each entry eventually gets a `Tracking position` line
- Flag any position that was entered but never tracked (entry order placed, no Tracking line)

### 3d. Exit review
- For each exit, confirm the reason is one of: `hard_stop`, `trailing_stop_ma20`, `fallback_20pct`, `end_of_day`
- Check that BEARISH exits say `SELL` (cover short) in notifications
- Check that end_of_day exits happened at or after 15:55 ET

### 3e. P&L verification
Read the DAILY TRADE SUMMARY at the end of each log. For each row:
- Check no row shows `—` for EntryFill or ExitFill (indicates fill not confirmed before summary printed)
- Verify P&L sign and direction:
  - BULLISH: P&L = (exit − entry) × qty × 100 for options, (exit − entry) × shares for stock
  - BEARISH: P&L = (entry − exit) × qty × 100 for options, (entry − exit) × shares for stock
- Verify the daily total is the sum of individual rows
- Report the daily P&L and capital deployed for each engine

### 3f. Data quality
- Report any `No catchup data for` warnings — note the ticker and window
- Check for tickers receiving bars with abnormally long gaps (>30 min between consecutive bars during regular hours)
- Note any WebSocket reconnection events

## Step 4 — Report

Present findings as a numbered list grouped by severity, with **[OPTIONS]** / **[STOCK]** labels:

**Functional bugs** (wrong behaviour, money impact, missed trades)
**Cosmetic / messaging bugs** (wrong labels, confusing notifications)
**Data issues** (missing bars, sparse tickers)
**Informational** (reconnects, expected warnings)

For each issue include: log source, severity, line number(s), what the log says, what it should say/do.

End with:
- Options engine P&L for the day
- Stock engine P&L for the day
- Combined daily P&L
- Whether any functional bugs require immediate code fixes
