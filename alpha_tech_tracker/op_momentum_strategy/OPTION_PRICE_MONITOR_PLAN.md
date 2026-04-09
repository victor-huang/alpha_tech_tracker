# Option Price Monitor — Implementation Plan

## Overview

A new module that serves two roles:

1. **Background collector** — runs every 5 minutes during market hours, captures option pricing stats (intrinsic value, time value, spread %, daily theta) for all tickers in the selection list, and writes them to CSV for analysis.
2. **Pricing advisor** — called on-demand by the trade engine at entry and exit to return a fair limit price within the bid/ask range, using intrinsic value as a floor and recent snapshot history to estimate a reasonable time premium when the spread is wide or the bid is stale.

Both roles share the same in-memory snapshot cache. The trade engine can use the advisor alone (no CSV writing) or run both together.

---

## Motivation

### Problem with raw bid/ask

When an option is less liquid, the bid/ask spread can be wide or the bid can fall below intrinsic value (a stale quote). In those cases, using raw mid as the limit price is either overpaying or, worse, placing a limit below the option's guaranteed floor.

### Example

```
TSLA stock at $300
Weekly CALL, strike $280

bid = $19   ← BELOW intrinsic ($20) — stale quote
ask = $28
mid = $23.50

intrinsic_value = 300 - 280 = $20
bid_time_value  = 19 - 20 = -$1   ← arbitrage signal, quote is unreliable
ask_time_value  = 28 - 20 = +$8
mid_time_value  = 23.50 - 20 = +$3.50

A better entry limit = intrinsic ($20) + reasonable_time_premium (~$3.50)
                     = ~$23.50, clamped within [$19, $28]
```

---

## Contract Selection Architecture

### Design Principle

The monitor works with a **list of `ContractSpec` objects per ticker**, not a single symbol. Today that list contains the CALL and PUT that the live trade engine would pick (same strike logic). In the future, the list can include multiple strikes by swapping in a different selector — no other code changes.

### Data Model

```python
@dataclass
class ContractSpec:
    symbol: str       # full OCC symbol, e.g. "TSLA260410C00280000"
    option_type: str  # "call" or "put"
```

### Default Selector: `TradeEngineStrikeSelector`

Reuses `ITMOptionContractSelector` (the same class used in the live trade engine) to pick the strike:

```python
class TradeEngineStrikeSelector:
    def __init__(self, client: AlpacaAPIClient)
    def select_contracts(self, ticker, stock_price) -> list[ContractSpec]:
        # calls ITMOptionContractSelector.select(ticker, "BULLISH", stock_price) → CALL
        # calls ITMOptionContractSelector.select(ticker, "BEARISH", stock_price) → PUT
        # returns [ContractSpec(call_symbol, "call"), ContractSpec(put_symbol, "put")]
```

### Expiry Selection: Nearest Weekly, Fallback Monthly

Inside `ITMOptionContractSelector`, the existing `_next_friday()` and `_end_of_next_month()` helpers are extracted into a shared `_nearest_liquid_expiry(ticker, stock_price, option_type)` function. Both `ITMOptionContractSelector` and `TradeEngineStrikeSelector` call this function so the expiry logic is never duplicated.

```
1. Compute next Friday (or this Friday if today ≤ Wednesday)
2. Check if Alpaca lists any options for that expiry on this ticker
3. If yes  → use weekly
4. If no   → walk forward week by week, up to 4 weeks
5. Still none → fall back to nearest monthly (3rd Friday)
```

### Future: Multiple Strikes

Adding more strikes requires only a new selector class — the monitor, trade engine, and CSV schema are unchanged:

```python
class MultiStrikeSelector:
    def select_contracts(self, ticker, stock_price) -> list[ContractSpec]:
        # e.g. ATM call, one strike OTM call, ATM put, one strike OTM put
        ...

monitor = OptionPriceMonitor(
    client=client,
    tickers=tickers,
    contract_selector=MultiStrikeSelector(client),
)
```

---

## Fair Price Estimation Algorithm

Called by `get_fair_price()` at trade entry and exit:

```
inputs: bid, ask, stock_price, strike, option_type, days_to_expiry

step 1 — intrinsic floor
  intrinsic = max(0, stock_price - strike)  # call
            = max(0, strike - stock_price)  # put

step 2 — spread quality
  mid        = (bid + ask) / 2
  spread_pct = (ask - bid) / mid * 100

step 3 — choose fair price
  if spread_pct ≤ 15% and bid ≥ intrinsic:
      fair = mid                           # liquid quote, use it directly

  elif bid < intrinsic:
      fair = intrinsic + median_time_value_from_cache(option_symbol)
      # bid is stale; intrinsic is the guaranteed floor

  elif spread_pct > 15%:
      fair = intrinsic + median_time_value_from_cache(option_symbol)
      # wide spread; use history to estimate time premium
      # if cache is empty: fair = intrinsic + 0.20 * (ask - bid)

step 4 — clamp to bid/ask range
  fair = clamp(fair, bid, ask)             # never recommend outside quoted range
```

`median_time_value_from_cache` uses the last 30 minutes of 5-min snapshots for that option symbol (up to 6 data points).

---

## Class Structure

```python
class OptionPriceMonitor:
    def __init__(
        self,
        client: AlpacaAPIClient,
        tickers: list,
        output_dir: str = "market_data/options_price_data",
        contract_selector=None,       # defaults to TradeEngineStrikeSelector(client)
        interval_seconds: int = 300,
    )

    # Background collection (optional — can use pricing advisor standalone)
    def start()                       # starts daemon thread, non-blocking
    def stop()                        # signals thread to exit cleanly

    # On-demand pricing — called by trade engine at entry and exit
    def get_fair_price(
        self,
        ticker: str,
        option_symbol: str,
        option_type: str,
        stock_price: Decimal,
    ) -> Decimal

    # Internal
    def _collection_loop()
    def _snapshot_ticker(ticker: str)                        # both call + put
    def _fetch_stats(ticker, spec: ContractSpec, stock_price) -> dict
    def _write_row(ticker: str, spec: ContractSpec, row: dict)
    def _update_cache(option_symbol: str, row: dict)
    def _median_time_value(option_symbol: str) -> Decimal
```

### In-Memory Cache

```python
# {option_symbol: deque of stat dicts, maxlen=6}  (6 × 5 min = 30 min window)
_cache: dict[str, deque]
```

---

## CSV Output

### File Layout

```
market_data/options_price_data/
  2026-04-01/
    TSLA_call.csv
    TSLA_put.csv
    NVDA_call.csv
    NVDA_put.csv
    ...
```

One file per ticker per option type per trading day. Rows appended every 5 minutes.

### Schema

| Column | Description |
|---|---|
| `timestamp` | ET timestamp of snapshot |
| `ticker` | e.g. `TSLA` |
| `option_type` | `call` or `put` |
| `option_symbol` | full OCC symbol |
| `strike` | strike price |
| `expiry` | expiration date |
| `expiry_type` | `weekly` or `monthly` |
| `days_to_expiry` | calendar days remaining |
| `stock_price` | stock mid at snapshot time |
| `bid` | option bid |
| `ask` | option ask |
| `mid` | `(bid + ask) / 2` |
| `intrinsic_value` | `max(0, stock - strike)` for call; `max(0, strike - stock)` for put |
| `bid_time_value` | `bid - intrinsic` (negative = stale/illiquid bid) |
| `ask_time_value` | `ask - intrinsic` |
| `mid_time_value` | `mid - intrinsic` |
| `spread_pct` | `(ask - bid) / mid * 100` |
| `daily_theta_approx` | `mid_time_value / days_to_expiry` |

---

## Integration with Trade Engine

### `trade_engine.py`

```python
# __init__: accept optional monitor
def __init__(self, ..., option_price_monitor=None):
    self._option_price_monitor = option_price_monitor

# _place_entry: use fair price if monitor available
if self._option_price_monitor:
    limit_price = self._option_price_monitor.get_fair_price(
        ticker, option_symbol, option_type, stock_price
    )

# run(): start and stop alongside signal engine
if self._option_price_monitor:
    self._option_price_monitor.start()
...
if self._option_price_monitor:
    self._option_price_monitor.stop()
```

### `position_monitor.py`

```python
# _close_option_position: use fair price for exit limit
if self._option_price_monitor:
    limit_price = self._option_price_monitor.get_fair_price(
        pos.ticker, pos.option_symbol, option_type, current_stock_price
    )
```

### `op_momentum_trade_engine.py`

New CLI flag:
```bash
--collect-option-prices    # enables background CSV collection + fair pricing advisor
```

When set, the engine instantiates `OptionPriceMonitor` and passes it to `OpMomentumTradeEngine`.

---

## Standalone CLI

Can run independently without the trade engine for data collection only:

```bash
# Collect for full default ticker pool
python alpha_tech_tracker/op_momentum_strategy/option_price_monitor.py

# Specific tickers
python alpha_tech_tracker/op_momentum_strategy/option_price_monitor.py \
  --tickers TSLA NVDA COIN

# Custom interval and output dir
python alpha_tech_tracker/op_momentum_strategy/option_price_monitor.py \
  --tickers TSLA NVDA \
  --interval 300 \
  --output-dir market_data/options_price_data
```

---

## Files to Create/Change

| File | Change |
|---|---|
| `option_price_monitor.py` | **New** — `ContractSpec`, `TradeEngineStrikeSelector`, `OptionPriceMonitor` |
| `contract_selector.py` | Extract `_nearest_liquid_expiry()` as a module-level function shared with `TradeEngineStrikeSelector` |
| `trade_engine.py` | Accept optional `option_price_monitor` param; call `get_fair_price()` at entry; start/stop monitor in `run()` |
| `position_monitor.py` | Call `get_fair_price()` in `_close_option_position()` |
| `op_momentum_trade_engine.py` | Add `--collect-option-prices` CLI flag; wire `OptionPriceMonitor` to engine |

---

## Implementation Order

1. `contract_selector.py` — extract `_nearest_liquid_expiry()` (unblocks everything else)
2. `option_price_monitor.py` — `ContractSpec`, `TradeEngineStrikeSelector`, full `OptionPriceMonitor`
3. `trade_engine.py` — wire in `option_price_monitor` param and `get_fair_price()` at entry
4. `position_monitor.py` — `get_fair_price()` at exit
5. `op_momentum_trade_engine.py` — CLI flag

---

## What This Enables Post-Collection

Once a few days of data are in `market_data/options_price_data/`:

| Analysis | How |
|---|---|
| Best time of day to enter | Plot `mid_time_value` by timestamp — find when options are cheapest |
| Tickers with chronic stale bids | Count rows where `bid_time_value < 0` per ticker |
| Overpaying for time premium | Compare entry `mid_time_value` from live trades vs snapshot baseline |
| Liquidity threshold calibration | Histogram of `spread_pct` per ticker — set per-ticker thresholds |
| Daily theta by ticker | Compare `daily_theta_approx` — avoid high-theta options for longer holds |
