# OpMomentumTradeEngine — Implementation Design

## Overview

`op_momentum_trade_engine.py` is the live trading counterpart to `op_momentum_backtest.py`.
It translates the opening-range momentum strategy into real intraday option trades using
Alpaca's paper/live trading API.

**Account:** $25,000
**Daily active symbols:** 2 (selected each morning by 30-day return ranking)
**Instrument:** Weekly-expiry options
**Signal window:** First 3 × 5-min bars (9:30–9:45 AM ET)

---

## File Location

```
alpha_tech_tracker/op_momentum_strategy/op_momentum_trade_engine.py
```

---

## Configuration Constants

| Constant | Value | Notes |
|---|---|---|
| `TICKERS` | `["NVDA","CRWD","COIN","JNJ","XOM","CAT"]` | Candidate universe |
| `ACCOUNT_BUDGET` | `25_000` | USD |
| `MAX_ACTIVE_SYMBOLS` | `2` | Top N tickers to trade per day |
| `OPENING_BARS` | `3` | 5-min bars = 15-min opening range |
| `STOP_PCT` | `0.15` | Hard stop fraction of OR range |
| `STRIKE_CALL_OFFSET` | `0.90` | Bull call strike = price × 0.90 |
| `STRIKE_PUT_OFFSET` | `1.10` | Bear put strike = price × 1.10 |
| `CAPITAL_PER_SYMBOL` | `0.45` | 45% of account per symbol (10% cash buffer) |
| `EOD_EXIT_TIME` | `"15:55"` | Force-close all positions (ET) |
| `MA_WARMUP_DAYS` | `30` | Calendar days of historical bars to pre-warm MAs |
| `BEARISH_MA200` | `False` | Optional stricter bearish filter |

---

## Components

### 1. `TickerSelector`

**When:** Called once before market open (or at startup).

**What it does:**
1. Fetches 30 calendar days of daily bars for all `TICKERS` via `StockHistoricalDataClient`.
2. Computes 30-day return: `(latest_close - oldest_close) / oldest_close`.
3. Sorts descending, returns the top `MAX_ACTIVE_SYMBOLS` tickers.

**Key method:**
```python
def select(self) -> list[str]:
    # returns e.g. ["NVDA", "CRWD"]
```

---

### 2. `OptionContractSelector`

**When:** Called once per ticker immediately after signal fires.

**Inputs:** `ticker`, `signal` (`"BULLISH"` | `"BEARISH"`), `stock_price`

**What it does:**
1. Determines target strike:
   - BULLISH → `target = floor(stock_price * STRIKE_CALL_OFFSET / increment) * increment`
   - BEARISH → `target = ceil(stock_price * STRIKE_PUT_OFFSET / increment) * increment`
   - Strike increment: `$1` if price < $50, `$5` if $50–$200, `$10` if > $200
2. Computes weekly expiration = next Friday on or after today.
3. Calls `AlpacaAPIClient.get_options_contracts()` with:
   - `expiration_date = next_friday`
   - `type = "call"` (bullish) or `"put"` (bearish)
   - `strike_price_gte = target - increment`, `strike_price_lte = target + increment`
4. From returned contracts, picks the one whose strike is closest to target.
5. Returns the full OCC symbol (e.g. `"NVDA250328C00820000"`).

**Key method:**
```python
def select(self, ticker: str, signal: str, stock_price: float) -> str:
    # returns OCC option symbol string
```

---

### 3. `PositionSizer`

**When:** Called once per ticker after option contract is selected.

**Inputs:** `option_symbol`, `alpaca_client`

**What it does:**
1. Fetches live bid/ask for the option via `OptionLatestQuoteRequest`.
2. Computes mid price = `(bid + ask) / 2`.
3. Computes budget = `account_options_buying_power * CAPITAL_PER_SYMBOL`.
4. Computes `contracts = max(1, floor(budget / (mid_price * 100)))`.
5. Returns `(contracts, mid_price)`.

**Key method:**
```python
def compute(self, option_symbol: str) -> tuple[int, float]:
    # returns (num_contracts, limit_price)
```

---

### 4. `LiveSignalEngine`

**When:** Runs from 9:30 AM until signal fires (or 9:45 AM passes with no signal).

**State machine per ticker:**
```
WAITING → COLLECTING_OPENING (bars 1–3) → SIGNAL_FIRED | NO_SIGNAL
```

**What it does:**
1. At startup, fetches historical 5-min bars (last `MA_WARMUP_DAYS` calendar days) to
   pre-warm a rolling DataFrame for MA20, MA50, MA200 computation.
2. Subscribes to live `StockDataStream` bar updates for the active tickers.
3. Each incoming 5-min bar:
   - Appended to the rolling DataFrame.
   - Re-computes MA20, MA50, MA200.
   - During the opening period (first `OPENING_BARS` bars of the session), accumulates
     OR high/low.
4. After the `OPENING_BARS`-th bar closes, applies signal conditions:
   - **BULLISH:** `close > midpoint AND close > MA20 AND close > MA200`
   - **BEARISH:** `close <= OR_low + 0.20 * OR_range AND close < MA20`
   - **NEUTRAL:** no trade
5. Emits a `SignalEvent` dataclass for BULLISH/BEARISH only.

**`SignalEvent` fields:**
```python
@dataclass
class SignalEvent:
    ticker: str
    signal: str          # "BULLISH" | "BEARISH"
    entry_price: float   # closing price of last opening bar
    stock_price: float   # same as entry_price (used for strike calc)
    or_high: float
    or_low: float
    or_range: float
    ma50_at_signal: float
```

---

### 5. `PositionMonitor`

**When:** Runs from signal entry until position is closed (or 3:55 PM ET).

**State per position:**
```python
@dataclass
class ActivePosition:
    ticker: str
    signal: str
    option_symbol: str
    entry_order_id: str
    contracts: int
    entry_price: float     # stock price at signal
    or_high: float
    or_low: float
    or_range: float
    hard_stop_price: float
    hard_stop_armed: bool
    is_closed: bool
```

**On each new 5-min bar for the position's ticker:**
- Updates MA50 from the rolling DataFrame.
- BULLISH stop logic:
  - Arm if `close > hard_stop_price` (i.e. confirmed breakout above OR high minus buffer)
  - Exit if armed AND `close <= hard_stop_price` → reason: `"hard_stop"`
  - Exit if `close < MA50` → reason: `"trailing_stop_ma50"`
- BEARISH stop logic:
  - Arm if `close < hard_stop_price`
  - Exit if armed AND `close >= hard_stop_price` → reason: `"hard_stop"`
  - Exit if `close > MA50` → reason: `"trailing_stop_ma50"`
- At `EOD_EXIT_TIME`: exit all open positions → reason: `"end_of_day"`

**On exit:**
- Calls `AlpacaAPIClient.place_option_order()` with `order_action="SELL_CLOSE"`,
  limit price at bid (aggressive fill).
- Logs: ticker, signal, entry/exit stock price, option symbol, contracts, exit reason.

---

### 6. `OpMomentumTradeEngine` — Orchestrator

**Injects:** `AlpacaAPIClient`, `TickerSelector`, `LiveSignalEngine`, `PositionMonitor`

**Daily flow:**

```
9:00 AM  TickerSelector.select()
           → active_tickers = ["NVDA", "CRWD"]
           → pre-warm historical bars

9:30 AM  LiveSignalEngine starts collecting bars
           WebSocket stream subscribes to active_tickers

9:45 AM  (after 3rd bar closes)
           For each ticker with BULLISH/BEARISH signal:
             1. OptionContractSelector.select(ticker, signal, stock_price)
             2. PositionSizer.compute(option_symbol)
             3. AlpacaAPIClient.place_option_order(... BUY_OPEN ...)
             4. PositionMonitor.add_position(...)

9:45–3:55  Each new 5-min bar → PositionMonitor.on_bar(ticker, bar)
             → exits if stop conditions met

3:55 PM  PositionMonitor.close_all() → force-close remaining positions

4:00 PM  Print daily P&L summary, stop stream
```

**Key method:**
```python
def run(self):
    # blocks until EOD shutdown
```

---

## Data Flow Diagram

```
StockHistoricalDataClient
  └── [pre-warm 30d of 5-min bars] ──→ LiveSignalEngine (MA warmup)
  └── [30d daily bars]             ──→ TickerSelector (ranking)

StockDataStream (WebSocket)
  └── live 5-min bars ──→ LiveSignalEngine
                       └──→ PositionMonitor (MA50 tracking)

LiveSignalEngine
  └── SignalEvent ──→ OpMomentumTradeEngine
                       ├── OptionContractSelector (find contract)
                       ├── PositionSizer (qty + price)
                       └── AlpacaAPIClient.place_option_order (BUY_OPEN)

PositionMonitor
  └── stop triggered ──→ AlpacaAPIClient.place_option_order (SELL_CLOSE)
```

---

## Options Strike Selection Logic

| Condition | Type | Strike formula |
|---|---|---|
| BULLISH | CALL | `floor(price × 0.90 / incr) × incr` |
| BEARISH | PUT | `ceil(price × 1.10 / incr) × incr` |

Strike increment by price range:
- `price < $50` → `$1` increments
- `$50 ≤ price ≤ $200` → `$5` increments
- `price > $200` → `$10` increments

Weekly expiration = next Friday (or this Friday if today is Mon–Thu and Friday hasn't passed).
If queried on Friday after close, use next Friday.

---

## Position Sizing Example

```
Account: $25,000
options_buying_power = $25,000
Budget per symbol = $25,000 × 0.45 = $11,250

NVDA @ $820, BULLISH
→ CALL strike = floor(820 × 0.90 / 10) × 10 = $730
→ Option mid price = $8.50
→ contracts = floor($11,250 / ($8.50 × 100)) = floor(13.23) = 13
→ Total cost = 13 × $8.50 × 100 = $11,050
```

---

## Stop Logic Summary (mirrors backtest)

| Scenario | Hard Stop Price | Trailing Stop | EOD |
|---|---|---|---|
| BULLISH | `OR_high - STOP_PCT × OR_range` | Close < MA50 | 3:55 PM |
| BEARISH | `OR_low + STOP_PCT × OR_range` | Close > MA50 | 3:55 PM |

Hard stop is **armed** only after price first crosses the stop threshold in the favorable
direction (confirms breakout). If never armed, a fallback 20% level is used instead
(matching the backtest's `fallback_20pct` path).

---

## Dependencies

All already installed in the project:
- `alpaca-py` — `TradingClient`, `StockHistoricalDataClient`, `StockDataStream`,
  `OptionHistoricalDataClient`
- `pandas`
- `pytz`

Reused modules:
- `alpha_tech_tracker.trade_api.alpaca_client.client.AlpacaAPIClient`
- `alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest.fetch_alpaca_bars`

---

## Running the Engine

```bash
# Paper trading (default)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine

# Live trading
PYTHONPATH=... ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine --live
```

---

## Out of Scope (v1)

- Persistent crash recovery / Redis state checkpointing
- SMS/Slack notifications (can be wired in via `sms.py`)
- Multi-day P&L tracking / performance dashboard
- Partial fills handling (assumes orders fill fully)
