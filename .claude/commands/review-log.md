---
description: 'SCP today''s options and stock trading logs from EC2, run daily bug analysis on both, and run fill quality analysis on options and stock fills'
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

## Step 4 — Fill quality analysis (options engine only)

Run `fetch_ts_orders` for the same date to pull all TradeStation fills and enrich them with Alpaca market data, log-sourced bid/ask, intrinsic values, and hourly average time value:

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders \
  --date ${LOG_DATE} \
  --log-file ${LOCAL_OPTION_LOG}
```

The CSV is written to `logs/fills/${LOG_DATE}/options_fills_${LOG_DATE}.csv`. Read it and flag the following:

### 4a. Escalation cost

For each fill with `opt_log_step` = 2 or 3:
- Report the symbol, side, step reached, and `fill_vs_log_mid`
- Step 2/3 means the initial fair-price limit wasn't competitive and the engine chased the ask
- Flag any step-3 fill that also has `fill_vs_log_mid > 0` (paid above mid after escalation)

### 4b. Fills vs intrinsic

For each fill where `intrinsic_value` is populated:

**Entries bought above intrinsic (normal but monitor):**
- `time_value_paid > $1.00`: flag as elevated time premium — report `time_value_paid` and `hourly_avg_time_value` for context

**Entries bought below intrinsic (favorable):**
- `time_value_paid < 0`: note as a favorable dislocation capture — no action needed

**Exits sold below intrinsic (concerning):**
- `time_value_paid < -$0.10` on a SELL: the engine sold an option for less than its exercise value — report the symbol, fill price, intrinsic, and the shortfall. Check whether the exit went through the `FILL_ESC` path or an EOD/timeout path (missing `opt_log_bid` indicates the latter)

### 4c. Fill vs mid at order time

For fills where `opt_log_mid` is populated:
- **Entries**: flag `fill_vs_log_mid > +$0.50` — paid well above mid, escalation likely chased a fast-moving option
- **Exits**: flag `fill_vs_log_mid < -$0.50` — sold well below mid, spread friction or thin market

### 4d. Wide spreads

For fills where `opt_log_spread_pct` is populated:
- Flag any fill with `opt_log_spread_pct > 15%` — inherently expensive to trade regardless of execution quality; note whether the fill was at or below mid (fair_price algorithm handling)
- Flag `opt_log_spread_pct > 10%` for entries specifically — entering a wide-spread option means the round-trip cost is high

### 4e. Missing log quotes

Count fills where `opt_log_bid` is empty. These exits went through the `position_monitor` EOD/timeout path rather than `order_executor`'s FILL_ESC loop — no quote was logged at order time. Report which fills are blind and whether any of them also show `time_value_paid < -$0.10` (sold below intrinsic with no quote context).

### 4f. Time value vs hourly average

For fills where `hourly_avg_time_value` is populated:
- **Entries**: flag `time_value_vs_hourly_avg > +$1.00` — entered when the option was trading at a significant premium relative to its own hour (momentum spike pricing)
- **Exits**: flag `time_value_vs_hourly_avg < -$1.00` — exited when the option's time value had collapsed relative to the hour's baseline (hard stop into a liquidity hole)

## Step 5 — Stock fill quality analysis

Run `fetch_alpaca_orders` for the same date to pull all Alpaca stock fills and enrich them with bar data, historical NBBO quotes, and log-sourced bid/ask from FILL_ESC lines:

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.fetch_alpaca_orders \
  --date ${LOG_DATE} \
  --log-file ${LOCAL_STOCK_LOG} \
  --live
```

The CSV is written to `logs/fills/${LOG_DATE}/stocks_fills_${LOG_DATE}.csv`. Read it and flag the following:

### 5a. Escalation cost

For each fill with `log_step` = 2 or 3:
- Report the ticker, side, step reached, wide-spread flag, and `fill_vs_log_mid`
- Step 2 = engine chased the ask (wide spread or step-1 timeout); step 3 = market order fallback
- Flag any step-3 fill — market orders have no price protection
- Flag any step-2 fill where `fill_vs_nbbo_mid > +$0.50` (paid well above mid after escalation)

### 5b. Wide spread entries

For fills where `log_wide_spread = True` on an entry:
- Report the ticker, bid/ask spread implied by `log_bid`/`log_ask`, and `fill_vs_nbbo_mid`
- SNDK routinely has $20–30 wide spreads — step 2 (aggressive at ask) is expected; flag only if fill came in above the ask
- For other tickers, a wide spread entry means high round-trip cost; note whether the fill was at or below NBBO mid (good execution despite spread)

### 5c. Fill vs NBBO mid at fill time

For fills where `nbbo_mid` is populated:
- **Entries**: flag `fill_vs_nbbo_mid > +$1.00` — paid well above mid; stock moved against us between order placement and fill
- **Exits**: flag `fill_vs_nbbo_mid < -$1.00` — sold well below mid; stop triggered into a falling market or thin liquidity

### 5d. Slippage vs limit

For fills where `slippage_bps` is populated:
- **Entries**: positive slippage = filled worse than limit (paid above for buys, received below for shorts)
- **Exits**: positive slippage = filled worse than limit (received below for sells, paid above for covers)
- Flag any fill with `|slippage_bps| > 100` — significant deviation from the intended limit

### 5e. Missing log quotes

Count fills where `log_bid` is empty. These went through EOD market exit or manual close — no FILL_ESC quote was logged. Report which fills are blind and note whether any also show `fill_vs_nbbo_mid < -$1.00` (sold well below mid with no quote context).

### 5f. Fill inside bar

Report any `fill_inside_bar = False`. These mean the fill price is outside the 1-min OHLC range at fill time — could indicate a stale bar lookup or an off-exchange fill. Single-cent mismatches at bar boundaries are rounding artifacts; larger gaps warrant investigation.

## Step 6 — Report

Present findings as a numbered list grouped by severity, with **[OPTIONS]** / **[STOCK]** labels:

**Functional bugs** (wrong behaviour, money impact, missed trades)
**Fill quality issues** (escalation cost, below-intrinsic exits, wide spreads)
**Cosmetic / messaging bugs** (wrong labels, confusing notifications)
**Data issues** (missing bars, sparse tickers)
**Informational** (reconnects, expected warnings)

For each issue include: log source, severity, line number(s), what the log says, what it should say/do.

End with:
- Options engine P&L for the day
- Stock engine P&L for the day
- Combined daily P&L
- Options fill quality summary: total fills, step 2/3 count, below-intrinsic exits, widest spread seen
- Stock fill quality summary: total fills, step 2/3 count, market-order (step 3) count, worst `fill_vs_nbbo_mid` entry and exit, blind fills (no log quote)
- Whether any functional bugs or fill quality issues require immediate code fixes
