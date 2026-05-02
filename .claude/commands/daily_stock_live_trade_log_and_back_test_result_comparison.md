---
description: 'SCP stock live trade log from EC2, run IEX backtest for same date, compare selection + P&L + fill quality'
---

# Daily Stock Live Trade Log vs Backtest Comparison

Compare the live stock engine results against the IEX backtest for the same date to understand selection accuracy, P&L divergence, and fill quality.

## Step 1 — Resolve the date

Parse `$ARGUMENTS` for a date (formats: `YYYY-MM-DD`, `MM-DD`, or natural language like "yesterday").

- If empty, use today's date in ET (America/New_York).
- Set `DATE` = YYYY-MM-DD.
- Set `EC2_HOST` = `ec2-user@ec2-3-133-120-51.us-east-2.compute.amazonaws.com`
- Set `EC2_KEY` = `~/.ssh/trade-sys.pem`
- Set `LOG_FILE` = `op_momentum_${DATE}.log`
- Set `LOCAL_LOG` = `logs/op_momentum_stock_${DATE}.log`

Report the resolved date before proceeding.

## Step 2 — SCP the stock log from EC2

The stock engine log lives in the `alpha_tech_tracker_stock_engine` directory (not `alpha_tech_tracker`):

```bash
scp -i ${EC2_KEY} \
  ${EC2_HOST}:/home/ec2-user/alpha_tech_tracker_stock_engine/logs/${LOG_FILE} \
  ${LOCAL_LOG}
```

- If the local file already exists and is non-empty, overwrite it (always fetch latest — the file may have grown since last download).
- If scp fails, report the error clearly and stop.
- Report the file size after download.

## Step 3 — Run the IEX backtest for the same date

Always use `--feed iex` — this is what the live engine uses and it produces matching selector scores and price data.

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate && \
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 \
  --window M1 09:30 3 --window A1 12:00 2 --window A2 13:15 1 --window A3 15:00 1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 10 \
  --start ${DATE} --end ${DATE} --feed iex 2>&1
```

Capture the full stdout. If it errors, report the full error and stop.

## Step 4 — Extract live log data

From `${LOCAL_LOG}`, extract the following in a single grep pass:

```bash
grep -n "SIGNAL\|Entering position\|Tracking position\|EXIT.*reason\|FILL_ESC\|step[12]\|step3\|market order placed\|filled\|Capital returned\|DAILY TRADE SUMMARY\|Re-entry\|DD.*firing\|No catchup data\|WebSocket watchdog\|ERROR\|ValueError" \
  ${LOCAL_LOG}
```

From this output, build the following tables for the analysis:

### 4a. Signal pool per window
List every `SIGNAL [M1]`, `SIGNAL [A1]`, `SIGNAL [A2]` that fired and was buffered, grouped by window.

### 4b. Selected entries
List every `Entering position` line: window, ticker, direction, price, rank.

### 4c. Fill escalation per trade
For each entry and exit, record:
- Order type (BUY_OPEN, SELL_SHORT, SELL_CLOSE, BUY_COVER)
- Step reached (step1 / step2 / step3 market)
- Number of step1 attempts before escalating
- Wall-clock time from first attempt to `filled` line (seconds)
- Quote at time of placement: bid, ask, spread $, spread %
- Actual fill price from DAILY TRADE SUMMARY

### 4d. DAILY TRADE SUMMARY
Read the `DAILY TRADE SUMMARY` block at the end of the log. Record every row:
- Ticker, Signal type, Qty, EntryFill, ExitFill, P&L$, P&L%, Exit reason

Also note the daily total P&L and total capital deployed.

## Step 5 — Selection comparison

Build a side-by-side table of IEX BT vs Live for all 6 slots (M1 rank-1, M1 rank-2, A1 rank-1, A1 rank-2, A2 rank-1, A2 rank-2):

| Window | BT Rank | BT Ticker | BT Direction | Live Ticker | Live Direction | Match? |
|--------|---------|-----------|--------------|-------------|----------------|--------|

Mark each slot ✓ (match) or ✗ (mismatch). For any mismatch, note which ticker the BT picked vs what the live engine selected and why scores likely differed (e.g., different bar close prices, OR range differences between IEX historical cache and live IEX stream).

## Step 6 — Per-trade P&L comparison

For trades where BT and live picked the **same ticker and direction**, compare side-by-side at the per-share level:

| Trade | BT entry | BT exit | BT P&L/sh | BT exit reason | Live entry | Live exit | Live P&L/sh | Live exit reason | Gap/sh | Gap attribution |
|-------|----------|---------|-----------|----------------|-----------|----------|-------------|-----------------|--------|----------------|

For BEARISH trades, P&L/sh = entry − exit. For BULLISH, P&L/sh = exit − entry.

Gap attribution: classify each gap as one of:
- **Fill slippage** — live fill price deviated from BT bar-close price due to escalation delay or stale quote
- **Exit timing** — same stop logic, but stock took a different path in live (BT held longer or stopped sooner)
- **Exit reason change** — e.g., BT ended end_of_day but live hit trailing_stop
- **Re-entry path** — BT took BRE/BUE/DD, live took a different branch or none

For trades only in live (not in BT due to re-entry, DD, or selection mismatch), show them separately with their live P&L.

## Step 7 — Fill quality analysis

For every trade entry and exit, produce a fill quality table:

| Trade | Side | Step reached | Attempts | Time to fill | Quote bid | Quote ask | Spread% | Mid placed | Actual fill | Slippage vs mid | Assessment |
|-------|------|-------------|----------|--------------|-----------|-----------|---------|-----------|------------|----------------|------------|

Slippage vs mid:
- For BUY: positive = paid above mid (bad), negative = paid below mid (good)
- For SELL/SELL_SHORT: positive = received above mid (good), negative = received below mid (bad)
- For BUY_COVER: positive = paid above mid (bad)

Assessment codes:
- ✅ step1, ≤5s, |slippage| < $0.20
- ⚠️ needed step2 or step1 >3 attempts, or spread >1%
- ❌ reached step3 market, or ask=0/bid=0 caused ValueError fallback, or slippage > $0.50/sh

Flag these specific conditions:
- `ask=0` or `bid=0` at step1 → broken IEX quote, orders will be rejected; step2 with nonsensical aggressive_price will eventually fill at market
- `spread > 3%` at entry → stale quote; the limit at mid may be far from actual market
- step3 market order → note the last known bid and actual fill to measure market impact

## Step 8 — Root cause attribution

Summarize the total P&L gap (BT vs Live) broken into attributed buckets:

| Cause | Approx. $ impact | Type |
|-------|-----------------|------|
| Different tickers selected (selection mismatch) | | Selector divergence |
| Same ticker, different exit timing (market path) | | Market conditions |
| Entry fill slippage (escalation delay, fast market) | | Fill quality |
| Broken IEX quote on entry/exit (ask=0, step3 market) | | Fill quality / data |
| DD vs BRE path difference | | Re-entry logic |
| Other | | |
| **Total gap** | | |

Classify the overall day: is the live result worse than BT primarily because of (a) market conditions the strategy had no edge on, (b) fill quality, or (c) selection mismatch?

## Step 9 — Issues and anomalies

Report any bugs or concerns found in the live log:

**Functional bugs** (wrong behavior, money impact)
- Broken quotes (`ask=0`, `bid=0`) causing step2 with nonsensical prices
- Step3 market order reached — flag the ticker and whether it created adverse slippage
- `ValueError: ask=0` in exit path — confirm market fallback fired correctly
- Any `ERROR` or `Exception` with a traceback

**Data issues**
- `No catchup data for` warnings — list ticker and window
- WebSocket watchdog reconnects — note time and whether it preceded the OR window

**Informational**
- Stale quotes with spread >3% — note ticker, side, and whether it affected fill price

## Step 10 — Final report

Present in this order:

### P&L Summary
Three-line table: IEX BT / Live / Gap, with win rate and trade count.

### Selection Match
One line per window: matched or diverged, and which ticker differed.

### Per-Trade Comparison Table
Full table from Step 6.

### Fill Quality Scorecard
Full table from Step 7. Highlight any ❌ fills.

### Root Cause Breakdown
Bucket table from Step 8 with narrative.

### Issues
Findings from Step 9.

End with a one-line verdict: was today's live underperformance vs BT driven by market conditions, fill quality, or selection mismatch — and which single trade had the largest impact.
