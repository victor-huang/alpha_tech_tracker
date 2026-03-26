# OpMomentumTradeEngine — Implementation Design

## Overview

`op_momentum_trade_engine.py` is the live trading counterpart to `op_momentum_backtest.py`.
It translates the opening-range momentum strategy into real intraday option trades using
Alpaca's paper/live trading API.

**Account:** $25,000
**Daily active symbols:** up to 2 (selected each morning by composite score ranking)
**Instrument:** Weekly-expiry options
**Signal window:** First 3 × 5-min bars (9:30–9:45 AM ET, configurable)

---

## File Location

```
alpha_tech_tracker/op_momentum_strategy/op_momentum_trade_engine.py
```

---

## Configuration Constants

| Constant | Default | Notes |
|---|---|---|
| `TICKERS` | `DEFAULT_TICKERS` | Candidate universe (from selector module) |
| `ACCOUNT_BUDGET` | `25_000` | USD fallback if API returns no buying power |
| `MAX_ACTIVE_SYMBOLS` | `2` | Max concurrent positions per day |
| `OPENING_BARS` | `3` | 5-min bars = 15-min opening range |
| `OPENING_START_TIME` | `"09:30"` | Opening window start (ET) |
| `STOP_PCT` | `0.15` | Hard stop as fraction of OR range |
| `STRIKE_CALL_OFFSET` | `0.90` | Bull call strike = price × 0.90 |
| `STRIKE_PUT_OFFSET` | `1.10` | Bear put strike = price × 1.10 |
| `CAPITAL_PER_SYMBOL` | `0.45` | 45% of buying power per symbol |
| `EOD_EXIT_TIME` | `"15:55"` | Force-close all positions (ET) |
| `MA_WARMUP_DAYS` | `7` | Calendar days of 5-min bars to pre-warm MAs |
| `ROLLING_LOOKBACK_DAYS` | `30` | Days for ticker selection rolling stats |
| `BEARISH_MA200` | `False` | Require close < MA200 for BEARISH signals |
| `SIGNAL_BUFFER_MINUTES` | `2` | Collection window after OR closes |
| `TRAILING_MA` | `"ma20"` | MA to use for trailing stop: `ma20`, `ma50`, `both` |
| `MAX_LOSS_PCT` | `None` | Per-trade max stock loss % (e.g. `0.02` = 2%). Disabled by default |
| `ARMED_MA20_EXIT` | `False` | Use MA20 as trailing exit once hard stop is armed |
| `REGIME_FILTER` | `False` | Suppress BULLISH signals on QQQ bearish days |
| `REGIME_MA` | `5` | N-day MA period for QQQ regime filter |
| `RANK_WEIGHTED_SIZING` | `False` | Weight position size by ticker rank |
| `RANK_WEIGHTS` | `[0.50, 0.30, 0.20]` | Capital weights for rank-0, rank-1, rank-2 tickers |

---

## Components

### 1. `TickerSelector`

**When:** Called once before market open (or at startup).

**What it does:**
1. Fetches bars for all `TICKERS` via the backtest `fetch_bars` helper.
2. Runs `select_top_n()` (composite score: 60-day rolling EV gate + today's opening-range
   signal + composite score).
3. If today's opening range hasn't closed yet, falls back to the most recent trading day
   with complete data so the engine still has a ranked list to watch.
4. Returns the top `MAX_ACTIVE_SYMBOLS` tickers and caches their rolling stats (used later
   for signal ranking).

---

### 2. `OptionContractSelector`

**When:** Called once per ticker immediately after signal fires.

**What it does:**
1. Determines target strike:
   - BULLISH → `floor(price × 0.90 / increment) × increment` (ITM call)
   - BEARISH → `ceil(price × 1.10 / increment) × increment` (ITM put)
   - Strike increment: `$1` if price < $50, `$5` if $50–$200, `$10` if > $200
2. Searches contracts in a ±20% range around current price; picks closest to target strike.
3. Returns the full OCC symbol (e.g. `"NVDA250328C00820000"`).

---

### 3. `PositionSizer`

**When:** Called once per ticker after option contract is selected.

**Signature:**
```python
def compute(self, option_symbol: str, capital_weight: Decimal = Decimal("1")) -> tuple:
    # returns (num_contracts, limit_price)
```

**What it does:**
1. Fetches live bid/ask for the option.
2. Computes budget = `buying_power × CAPITAL_PER_SYMBOL × capital_weight`.
3. Computes `contracts = max(1, floor(budget / (mid_price × 100)))`.
4. Returns `(contracts, mid_price)`.

The `capital_weight` parameter is set by `_enter_position` based on ticker rank when
`--rank-weighted-sizing` is enabled (see below).

---

### 4. `LiveSignalEngine`

**When:** Runs from startup until 3:55 PM ET.

**What it does:**
1. Pre-warms a rolling 5-min DataFrame (last `MA_WARMUP_DAYS` calendar days) for each
   ticker to seed MA20, MA50, MA200 calculations.
2. If `--regime-filter` is on, builds the set of QQQ bearish dates from historical data
   after warmup.
3. Subscribes to a live 1-min `StockDataStream`, aggregates bars into 5-min periods.
4. After the opening range closes (`OPENING_BARS` × 5 min bars), evaluates signal
   conditions:
   - **BULLISH:** `close > midpoint AND close > MA20 AND close > MA200`
   - **BEARISH:** `close ≤ OR_low + 0.20 × OR_range AND close < MA20`
   - **NEUTRAL:** no trade
5. If `regime_filter` is enabled, suppresses BULLISH signals on days when QQQ is below
   its `regime_ma`-day MA.
6. Fires the `on_signal` callback with a `SignalEvent`.
7. Continues appending bars and updating MAs for `PositionMonitor` use.
8. Includes a historical catch-up path for tickers that missed opening bars due to stream
   gaps.

---

### 5. `PositionMonitor`

**When:** Monitors open positions from entry through 3:55 PM EOD.

**Stop evaluation order (per bar, highest priority first):**

1. **Max loss guard** (`--max-loss-pct`): exit immediately if underlying stock has moved
   against the position by more than the threshold, regardless of other conditions.

2. **Armed MA20 exit** (`--armed-ma20-exit`): once hard stop is armed, use MA20 as the
   trailing exit instead of the hard stop price. Falls back to hard stop price if MA20 is
   unavailable.

3. **Hard stop** (always on): armed after price first crosses the stop threshold in the
   favorable direction. Once armed, exit if price reverts through it.

4. **Fallback 20%** (pre-arming only): if the hard stop is never armed, exit at the 20%
   OR level.

5. **Trailing MA stop** (`--trailing-ma`): exit when the MA crosses into the unfavorable
   zone *and* the activation gate is met (MA must be in favorable territory to avoid false
   triggers early in the day). Available modes: `ma20`, `ma50`, `both`.

6. **EOD** (`EOD_EXIT_TIME`): force-close all remaining positions.

**Stop prices:**

| Signal | Hard stop price | Fallback price |
|---|---|---|
| BULLISH | `OR_high - STOP_PCT × OR_range` | `OR_high - 0.20 × OR_range` |
| BEARISH | `OR_low + STOP_PCT × OR_range` | `OR_low + 0.20 × OR_range` |

---

### 6. Signal Collection Window & Ranking

After the opening range closes, the engine waits `SIGNAL_BUFFER_MINUTES` (2 min) to
collect signals from all watched tickers before entering. During this window, signals are
buffered in `_pending_signals`.

When the deadline passes, buffered signals are ranked by the same composite score used by
the selector (EV × signal strength). Only tickers with positive EV are eligible. The top
`MAX_ACTIVE_SYMBOLS` signals are entered in ranked order.

Signals that arrive after the deadline (from tickers that fired later) bypass the buffer
and are entered immediately if a slot is available.

---

### 7. Rank-Weighted Position Sizing (`--rank-weighted-sizing`)

When enabled, position size is scaled by the ticker's rank in the signal selection order:

| Rank | Weight | Effective budget (45% account) |
|---|---|---|
| 0 (top scorer) | 50% | 45% × 0.50 = 22.5% of buying power |
| 1 | 30% | 45% × 0.30 = 13.5% of buying power |
| 2+ | 20% | 45% × 0.20 = 9.0% of buying power |

When disabled (default), all positions use weight = 1.0 (full 45% budget each).

---

### 8. Fill Escalation (`_place_with_fill_escalation`)

For both entry and exit orders, the engine uses a three-step fill escalation:

1. **Step 1:** Limit order at mid price. Wait 60 seconds.
2. **Step 2 (if unfilled):** Cancel, re-place at ask (buy) or bid (sell). Wait 60 seconds.
3. **Step 3 (if still unfilled):** Cancel, place market order.

---

### 9. SMS Notifications (`_send_sms`)

Sends SMS alerts before each trade via ClickSend. Configured in `config.json`:

```json
{
  "clicksend": {
    "enabled": true,
    "username": "your@email.com",
    "api_key": "YOUR_API_KEY",
    "to_number": "+1XXXXXXXXXX"
  }
}
```

SMS is sent before each BUY entry and SELL exit (both simulate and live modes). If the
config is missing or `enabled` is false, SMS is silently skipped — a failure never blocks
order placement.

---

### 10. `OpMomentumTradeEngine` — Orchestrator

**Daily flow:**

```
Startup     _load_config() — load alpaca + clicksend credentials
            TickerSelector.select() — rank tickers, cache rolling_stats
            LiveSignalEngine.start() — warmup bars, build regime dates, start stream

9:30 AM     Opening range begins (OPENING_BARS × 5-min bars)
            Signal collection window opens at OR close + SIGNAL_BUFFER_MINUTES

Collection  Buffered signals ranked by composite score
window      Top MAX_ACTIVE_SYMBOLS entered via _enter_position(event, rank=i)
closes      → OptionContractSelector.select(...)
            → PositionSizer.compute(symbol, capital_weight)
            → _place_entry(...) with fill escalation
            → PositionMonitor.add_position(...)

9:45–3:55   _monitor_loop() polls PositionMonitor every 30s
            Each tick: evaluate stops, close if triggered
            Status printed every 5 minutes

3:55 PM     close_all(reason="end_of_day")
4:00 PM     print_summary() — daily P&L table
            signal_engine.stop()
```

---

## CLI Reference

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  <action> [options]
```

### Actions

| Action | Description |
|---|---|
| `run` | Run in foreground (logs to stdout) |
| `start` | Start as background daemon (logs to file) |
| `stop` | Stop the running daemon |
| `status` | Show whether daemon is running and its PID |
| `restart` | Stop then start the daemon |

### Options

| Flag | Default | Description |
|---|---|---|
| `--live` | off | Use live trading account (default: paper) |
| `--simulate` | off | Simulate fills at mid price, no orders placed |
| `--tickers NVDA CRWD …` | universe | Override ticker watchlist |
| `--stop-pct FLOAT` | `0.15` | Hard stop as fraction of OR range |
| `--trailing-ma {ma20,ma50,both}` | `ma20` | MA to use for trailing stop |
| `--max-loss-pct FLOAT` | disabled | Per-trade max stock loss % (e.g. `0.02`) |
| `--armed-ma20-exit` | off | Use MA20 as trailing exit once hard stop armed |
| `--regime-filter` | off | Suppress BULLISH signals on QQQ bearish days |
| `--regime-ma INT` | `5` | N-day MA for QQQ regime filter |
| `--rank-weighted-sizing` | off | Weight positions by rank (50/30/20%) |
| `--opening-start HH:MM` | `09:30` | Opening window start time (ET) |
| `--log-level {DEBUG,INFO,…}` | `INFO` | Log verbosity |
| `--log-file PATH` | `logs/op_momentum.log` | Log file path (daemon mode) |
| `--pid-file PATH` | `~/.op_momentum_daemon.pid` | PID file path |

### Examples

```bash
# Simulate in foreground with live market data
PYTHONPATH=/path/to/repo \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --simulate

# Simulate with rank-weighted sizing and regime filter
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --simulate --rank-weighted-sizing --regime-filter

# Live paper trading with MA20 trailing stop and 2% max loss guard
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --trailing-ma ma20 --max-loss-pct 0.02

# Live paper trading with armed MA20 exit (switch to MA20 trail after arming)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --armed-ma20-exit

# Start as daemon (background), live paper trading
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  start --simulate

# Stop daemon
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine stop

# Check daemon status
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine status

# Watch specific tickers (override universe)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --simulate --tickers NVDA TSLA AAPL
```

---

## Configuration File

Located at `alpha_tech_tracker/op_momentum_strategy/config.json`:

```json
{
  "alpaca": {
    "api_key": "YOUR_ALPACA_API_KEY",
    "secret_key": "YOUR_ALPACA_SECRET_KEY"
  },
  "clicksend": {
    "enabled": false,
    "username": "your@email.com",
    "api_key": "YOUR_CLICKSEND_API_KEY",
    "to_number": "+1XXXXXXXXXX"
  }
}
```

Environment variables `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` take precedence over the
config file. ClickSend is disabled by default; set `"enabled": true` to activate SMS.

---

## Position Sizing Examples

**Without rank-weighted sizing (default):**
```
Account buying power: $25,000
Budget = $25,000 × 0.45 = $11,250 per symbol

NVDA CALL, mid = $8.50
→ contracts = floor($11,250 / ($8.50 × 100)) = 13
→ Total cost = $11,050
```

**With rank-weighted sizing (`--rank-weighted-sizing`):**
```
Rank 0 (top scorer): budget = $11,250 × 0.50 = $5,625
  NVDA CALL, mid = $8.50 → 6 contracts ($5,100)

Rank 1: budget = $11,250 × 0.30 = $3,375
  CRWD PUT, mid = $5.00 → 6 contracts ($3,000)
```

---

## Stop Logic Reference

| Stop type | Condition (BULLISH) | Condition (BEARISH) |
|---|---|---|
| `max_loss` | stock loss ≥ `max_loss_pct` × entry | stock gain ≥ `max_loss_pct` × entry |
| `hard_stop` | armed AND close ≤ hard_stop_price | armed AND close ≥ hard_stop_price |
| `armed_ma20` | armed AND `--armed-ma20-exit` AND close < MA20 | armed AND close > MA20 |
| `fallback_20pct` | not armed AND close ≤ fallback_price | not armed AND close ≥ fallback_price |
| `trailing_stop_ma20` | MA20 > hard_stop AND close < MA20 | MA20 < OR_low AND close > MA20 |
| `trailing_stop_ma50` | MA50 > hard_stop AND close < MA50 | MA50 < OR_low AND close > MA50 |
| `end_of_day` | 3:55 PM ET | 3:55 PM ET |

Priority order (first match wins): `max_loss` → `armed_ma20` or `hard_stop` → `fallback_20pct` → `trailing_stop_ma*`

---

## Dependencies

- `alpaca-py` — `TradingClient`, `StockHistoricalDataClient`, `StockDataStream`
- `clicksend-client` — SMS notifications
- `pandas`, `pytz`

Reused modules:
- `alpha_tech_tracker.trade_api.alpaca_client.client.AlpacaAPIClient`
- `alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest` — `fetch_bars`, `build_bearish_regime_dates`
- `alpha_tech_tracker.op_momentum_strategy.op_momentum_selector` — `score_ticker`, `select_top_n`
