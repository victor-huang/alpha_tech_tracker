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

## Module Structure

```
alpha_tech_tracker/op_momentum_strategy/
  models.py              _D(), SignalEvent, _FiveMinBar, ActivePosition
  config.py              All constants, _load_config(), _send_sms()
  contract_selector.py   _next_friday(), _strike_increment(), OptionContractSelector
  position_sizer.py      PositionSizer
  order_executor.py      _place_with_fill_escalation(), AlpacaAPIClient monkey-patch
  signal_engine.py       LiveSignalEngine
  position_monitor.py    PositionMonitor
  trade_engine.py        TickerSelector, OpMomentumTradeEngine
  op_momentum_trade_engine.py   CLI/daemon entry point + backward-compat re-exports
```

Tests:

```
tests/op_momentum_trade_engine/
  conftest.py              Shared helpers and fixtures
  test_contract_selector.py
  test_position_sizer.py
  test_signal_engine.py
  test_position_monitor.py
  test_trade_engine.py
```

---

## Configuration Constants

| Constant | Default | Notes |
|---|---|---|
| `TICKERS` | `DEFAULT_TICKERS` | Candidate universe (from selector module) |
| `ACCOUNT_BUDGET` | `25_000` | USD fallback if API returns no buying power |
| `MAX_ACTIVE_SYMBOLS` | `2` | Max concurrent positions **per window** per day |
| `OPENING_BARS` | `3` | 5-min bars = 15-min opening range |
| `OPENING_START_TIME` | `"09:30"` | Opening window start (ET) |
| `STOP_PCT` | `0.15` | Hard stop as fraction of OR range |
| `STRIKE_CALL_OFFSET` | `0.90` | Bull call strike = price × 0.90 |
| `STRIKE_PUT_OFFSET` | `1.10` | Bear put strike = price × 1.10 |
| `CAPITAL_PER_SYMBOL` | `0.45` | 45% of window budget per symbol |
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

## Multi-Window Trading

The engine supports running multiple intraday opening-range windows per day, mirroring the
multi-window backtest in `op_momentum_selector_backtest.py`. Windows are non-overlapping
and each fires independently based on its own OR start time and bar count.

### Window Configuration (`WindowConfig`)

```python
@dataclass
class WindowConfig:
    label: str            # "M1", "A1", "A2"
    opening_start: str    # "09:30", "13:15", "15:00"
    opening_bars: int     # 3, 1, 1
    capital_fraction: float = 1.0   # fraction of account buying power (first-group only)
    is_sequential: bool = False     # True for all windows after the first group
```

### Capital Allocation Rules

**First-group windows** (simultaneous, specified via `--morning-split`):
- Each gets `buying_power × capital_fraction` as an explicit budget at signal time
- `capital_fraction` comes from `--morning-split` percentages (e.g. `100%` → `1.0`)
- The `PositionSizer` receives this explicit `window_budget` and skips the live account call

**Sequential windows** (all windows after the first group):
- `window_budget = None` → `PositionSizer` calls `get_accounts()` at signal time
- The live account balance naturally reflects any returned capital from earlier windows
  (closed positions restore buying power) and any capital still tied up in open positions
- No special capital recycling logic needed — the account is the source of truth

**Capital allocation example** ($10k account, M1 + A1 + A2, weights 50/30/20):

| Window | Type | Budget source | Rank-1 slot | Rank-2 slot | Rank-3 slot |
|---|---|---|---|---|---|
| M1 9:45 AM | first-group (100%) | `$10,000 × 100%` = $10,000 | $10k × 45% × 50% = $2,250 | × 30% = $1,350 | × 20% = $900 |
| A1 1:20 PM | sequential | live account at 1:20 PM | same formula on live balance | | |
| A2 3:05 PM | sequential | live account at 3:05 PM | same formula on live balance | | |

If M1 positions are still open when A1 fires, the live buying power is lower — A1 naturally
gets a smaller budget. No explicit force-close is needed.

### Per-Window Signal Lifecycle

Each window runs independently:
1. `LiveSignalEngine` tracks OR bars for each window simultaneously on a single stream
2. When a window's OR closes, signals are collected into a per-window buffer
3. After `SIGNAL_BUFFER_MINUTES`, the per-window selection loop ranks buffered signals
4. Up to `MAX_ACTIVE_SYMBOLS` positions are entered for that window
5. Positions exit naturally (hard stop, trailing MA, or EOD at 3:55 PM)

Positions from multiple windows are all monitored by a single `PositionMonitor`. The EOD
force-close applies globally at 3:55 PM regardless of which window opened the position.

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
def compute(
    self,
    option_symbol: str,
    capital_weight: Decimal = Decimal("1"),
    window_budget: Optional[Decimal] = None,
) -> tuple:
    # returns (num_contracts, limit_price)
```

**What it does:**
1. Fetches live bid/ask for the option.
2. Computes budget:
   - If `window_budget` is provided (first-group window): `window_budget × CAPITAL_PER_SYMBOL × capital_weight`
   - Otherwise (sequential window or default): `buying_power × CAPITAL_PER_SYMBOL × capital_weight` (reads live account)
3. Computes `contracts = max(1, floor(budget / (mid_price × 100)))`.
4. Returns `(contracts, mid_price)`.

The `capital_weight` parameter is set by `_enter_position` based on ticker rank when
`--rank-weighted-sizing` is enabled (see below). The `window_budget` parameter is set
by the engine based on the window's `capital_fraction` for first-group windows.

---

### 4. `LiveSignalEngine`

**When:** Runs from startup until 3:55 PM ET.

**Multi-window support:** Accepts a `windows` list at construction time. Each entry is a
dict `{"label", "opening_start", "opening_bars", "on_signal"}`. A single WebSocket stream
serves all windows — bars are evaluated against each window's OR independently.

**What it does:**
1. Pre-warms a rolling 5-min DataFrame (last `MA_WARMUP_DAYS` calendar days) for each
   ticker to seed MA20, MA50, MA200 calculations.
2. If `--regime-filter` is on, builds the set of QQQ bearish dates from historical data
   after warmup.
3. Subscribes to a live 1-min `StockDataStream`, aggregates bars into 5-min periods.
4. For each window, after that window's OR closes (`opening_bars` × 5 min), evaluates
   signal conditions per ticker:
   - **BULLISH:** `close > midpoint AND close > MA20 AND close > MA200`
   - **BEARISH:** `close ≤ OR_low + 0.20 × OR_range AND close < MA20`
   - **NEUTRAL:** no trade
5. If `regime_filter` is enabled, suppresses BULLISH signals on days when QQQ is below
   its `regime_ma`-day MA.
6. Fires the window's `on_signal` callback with a `SignalEvent`.
7. Continues appending bars and updating MAs for `PositionMonitor` use.
8. Includes a per-window historical catch-up path for tickers that missed opening bars.

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

**Single-window daily flow (default, backward-compatible):**

```
Startup     _load_config() — load alpaca + clicksend credentials
            TickerSelector.select() — rank tickers, cache rolling_stats
            LiveSignalEngine.start() — warmup bars, build regime dates, start stream

9:30 AM     Opening range begins (OPENING_BARS × 5-min bars)
            Signal collection window opens at OR close + SIGNAL_BUFFER_MINUTES

Collection  Buffered signals ranked by composite score
window      Top MAX_ACTIVE_SYMBOLS entered via _enter_position(event, rank=i)
closes      → OptionContractSelector.select(...)
            → PositionSizer.compute(symbol, capital_weight, window_budget)
            → _place_entry(...) with fill escalation
            → PositionMonitor.add_position(...)

9:45–3:55   _monitor_loop() polls PositionMonitor every 30s
            Each tick: evaluate stops, close if triggered
            Status printed every 5 minutes

3:55 PM     close_all(reason="end_of_day")
4:00 PM     print_summary() — daily P&L table
            signal_engine.stop()
```

**Multi-window daily flow (M1 + A1 + A2 example):**

```
Startup     TickerSelector.select() using first window's opening_start
            LiveSignalEngine.start() — registers ALL windows on one stream
            Per-window signal_selection_loop threads started (one per window)
            Single _monitor_loop thread started (monitors all positions)

9:30 AM     M1 OR begins
9:45 AM     M1 OR closes; M1 signal collection window opens
9:47 AM     M1 collection deadline — rank signals, enter top-N
            window_budget = account_buying_power × capital_fraction (first-group)
            PositionSizer uses window_budget instead of live account read
            M1 positions entered, monitored until natural exit

1:15 PM     A1 OR begins (one 5-min bar from 1:15 to 1:20)
1:20 PM     A1 OR closes; A1 signal collection window opens
1:22 PM     A1 collection deadline — rank signals, enter top-N
            window_budget = None → PositionSizer reads live account balance
            Account reflects M1 outcome (closed positions restored buying power;
            any still-open M1 positions reduce available buying power naturally)

3:00 PM     A2 OR begins (one 5-min bar from 3:00 to 3:05)
3:05 PM     A2 OR closes; A2 signal collection window opens
3:07 PM     A2 collection deadline — rank signals, enter top-N (same as A1)

3:55 PM     close_all(reason="end_of_day") for ALL windows' positions
4:00 PM     print_summary()
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
| `--opening-start HH:MM` | `09:30` | Opening window start time (single-window mode) |
| `--window LABEL START BARS` | — | Define a named trading window (repeatable) |
| `--morning-split PCT …` | — | Capital split % for simultaneous first-group windows |
| `--log-level {DEBUG,INFO,…}` | `INFO` | Log verbosity |
| `--log-file PATH` | `logs/op_momentum.log` | Log file path (daemon mode) |
| `--pid-file PATH` | `~/.op_momentum_daemon.pid` | PID file path |

`--window` and `--morning-split` mirror the selector backtest CLI exactly. When `--window`
is not specified, the engine falls back to single-window mode using `--opening-start` and
the `OPENING_BARS` config constant (backward-compatible).

`--morning-split` determines which windows are "first-group" (simultaneous) and which are
sequential. The number of values given determines the first-group size; remaining windows
are sequential. Each sequential window reads the live account balance at its signal time.

### Examples

```bash
# Single-window (default, backward-compatible)
PYTHONPATH=/path/to/repo \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --mock-trade-execution --regime-filter --regime-ma 8 --rank-weighted-sizing

# Conservative multi-window: M1 + A1 + A2 (recommended live config)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --mock-trade-execution --regime-filter --regime-ma 8 --rank-weighted-sizing \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# Aggressive multi-window: M2 + A1 + A2
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --mock-trade-execution --regime-filter --regime-ma 8 --rank-weighted-sizing \
  --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# Two parallel morning windows (60/40 split) + afternoon
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --mock-trade-execution \
  --window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 \
  --morning-split 60 40

# Start as daemon
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  start --regime-filter --regime-ma 8 --rank-weighted-sizing \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# Stop daemon
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine stop

# Watch specific tickers (override universe)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  run --mock-trade-execution --tickers NVDA COIN PLTR
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

## Mock Trade Execution (`--mock-trade-execution`)

When `--mock-trade-execution` is set, no real orders are placed. Fills are simulated in
place using formulas that approximate real option pricing without live market data.

### Mock Option Pricer (`mock_option_pricer.py`)

Used in replay and paper-trading mode to produce meaningful P&L from option trades
without calling the historical option quote API (which returns stale/same-day prices in
replay).

#### Entry price — `mock_entry_price(stock_price, option_symbol, option_type)`

```
intrinsic = max(0, stock - strike)      # call
          = max(0, strike - stock)      # put
price     = intrinsic × (1 + 0.20)     # 20% time premium on top of intrinsic
```

OTM options (intrinsic = 0) floor to `$0.01` before the multiplier so position sizing
still works (avoids division by zero in contract count).

Result is quantized to exchange tick size: `$0.05` below `$3.00`, `$0.10` at or above.

**Example:** stock=$100, strike=$90 call → intrinsic=$10, price=$10×1.20=**$12.00**

#### Exit price — `mock_exit_price(exit_stock_price, option_symbol, option_type, entry_price, entry_stock_price)`

```
entry_intrinsic = max(0, entry_stock - strike)
entry_time_prem = max(0, entry_price  - entry_intrinsic)

exit_intrinsic  = max(0, exit_stock  - strike)
exit_time_prem  = entry_time_prem × 1.0         # no time decay (_TIME_DECAY = 1)

exit_price      = exit_intrinsic + exit_time_prem
```

Reconstructs the time premium actually paid at entry (fully retained at exit), then adds
the new intrinsic at exit. This means:
- Stock gain/loss flows through the intrinsic dollar-for-dollar
- Time premium is preserved in full — exit P&L reflects only the stock price move

**Example:** entry stock=$100, strike=$90, entry_price=$12
- entry_intrinsic=$10, entry_tp=$2.00
- exit stock=$102 → exit_intrinsic=$12, exit_tp=$2×1.0=$2.00
- exit_price=**$14.00**

#### Integration points

| Stage | File | Behaviour |
|---|---|---|
| Position sizing | `position_sizer.py` `compute()` | When `mock_stock_price` is provided, calls `mock_entry_price()` instead of fetching a live option quote |
| Entry fill | `trade_engine.py` `_place_entry()` | Uses `mock_entry_price()` at the signal-bar close; sets `pos.simulated_entry_mid` |
| Exit fill | `position_monitor.py` `_close_option_position()` | Uses `mock_exit_price()` with the triggering bar's close; sets `pos.simulated_exit_mid` |

The option type (`call`/`put`) is inferred automatically from the OCC symbol (`C` or `P`).

#### Replay result differences: stock vs options

Option P&L in replay mode will often differ from the stock P&L for the same trade.
This is expected and correct — the main cause is **option tick-size quantization**:

- Stock fills are priced to the cent (e.g. $695.61 vs $695.65 = $0.04/share).
- Option prices are quantized: `$0.05` ticks below $3, `$0.10` ticks at $3 and above.
- A stock move smaller than the option tick size rounds to `$0.00` per contract.

**Example:** SNDK stock loses $0.04/share (6 shares × $0.04 = −$0.24). The same move
raises the call's intrinsic by $0.04, but $0.04 < $0.10 minimum tick → option exit
price rounds to the same value as entry → **$0.00 option P&L** (1 contract × 100 × $0).

Other contributing factors:
- Options price intrinsic on a fixed strike; delta is always < 1 for near-ATM strikes.
- Contracts are integer-valued, so capital is never fully deployed (fractional contracts
  are dropped), leading to small systematic underuse of the position budget.

---

## Dependencies

- `alpaca-py` — `TradingClient`, `StockHistoricalDataClient`, `StockDataStream`
- `clicksend-client` — SMS notifications
- `pandas`, `pytz`

Reused modules:
- `alpha_tech_tracker.trade_api.alpaca_client.client.AlpacaAPIClient`
- `alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest` — `fetch_bars`, `build_bearish_regime_dates`
- `alpha_tech_tracker.op_momentum_strategy.op_momentum_selector` — `score_ticker`, `select_top_n`

Internal modules (see Module Structure above):
- `models`, `config`, `contract_selector`, `position_sizer`, `order_executor`,
  `signal_engine`, `position_monitor`, `trade_engine`
