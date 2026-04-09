# Broker Abstraction — Phase 1: Initial Refactor

**Goal:** Decouple the live trading engine from `AlpacaAPIClient` so that the execution
broker can be swapped (ETrade, IBKR, etc.) without touching strategy logic. Alpaca
remains the sole provider for market data (WebSocket streaming, historical bars, backtest).
No behavior changes. All existing tests must pass unchanged after the refactor.

---

## Problem Summary

The live engine is hard-wired to `AlpacaAPIClient` in three ways:

### 1. Concrete type used in 6 execution modules

Every module in the strategy layer accepts `AlpacaAPIClient` directly, making it
impossible to substitute another broker without changing all call sites:

| File | Line(s) | Usage |
|---|---|---|
| `trade_engine.py` | 226 | `alpaca_client: AlpacaAPIClient` |
| `position_monitor.py` | 66 | `alpaca_client: AlpacaAPIClient` |
| `order_executor.py` | 22, 260 | `client: AlpacaAPIClient` |
| `option_price_monitor.py` | 72, 120 | `client: AlpacaAPIClient` |
| `contract_selector.py` | 81, 134, 231 | `alpaca_client: AlpacaAPIClient` |
| `position_sizer.py` | 18 | `alpaca_client: AlpacaAPIClient` |

### 2. Private SDK object leaked in 8 places across 6 files

`client._option_data_client.get_option_latest_quote(OptionLatestQuoteRequest(...))` is
called directly, bypassing any interface. A non-Alpaca broker has no `_option_data_client`
attribute — this code breaks immediately on substitution:

| File | Lines |
|---|---|
| `order_executor.py` | 44 |
| `position_monitor.py` | 526, 623 |
| `trade_engine.py` | 973 |
| `option_price_monitor.py` | 202, 285 |
| `contract_selector.py` | 328 |
| `position_sizer.py` | 40 |

### 3. Monkey-patch in `order_executor.py`

`order_executor.py` mutates `AlpacaAPIClient.place_option_order` at module import time
(lines 173–256) to add `_option_symbol_override`. This couples the module loader to the
concrete Alpaca class and makes it impossible to run tests or import the module without
side-effecting `AlpacaAPIClient`.

---

## What Stays on Alpaca (Not Touched)

- `op_momentum_backtest.py` — `fetch_bars()`, `_stitch_cache()`, bar data
- `signal_engine.py` — `LiveSignalEngine` WebSocket streaming
- `bar_recorder.py` — bar CSV recording
- `op_momentum_selector.py`, `op_momentum_selector_backtest.py` — backtest pipeline
- `replay.py` — `BarReplayDriver`, `LiveBarsSource`

---

## Step-by-Step Implementation

### Step 1 — Create `trade_api/execution_client.py` (abstract interface)

Create a new file `alpha_tech_tracker/trade_api/execution_client.py` with an abstract
base class. All strategy-layer code will depend only on this type going forward.

```python
# trade_api/execution_client.py
from abc import ABC, abstractmethod


class ExecutionClient(ABC):
    """
    Abstract interface for broker execution: account management, quotes, and order
    placement. Strategies depend only on this type. Alpaca, ETrade, and IBKR each
    provide a concrete subclass.

    Option symbols are always OCC format (e.g. "TSLA250420C00240000") at this
    interface boundary. Each concrete adapter converts to broker-native format
    internally.
    """

    @abstractmethod
    def get_accounts(self) -> dict:
        """
        Return account state.
        Required keys: buying_power (float), portfolio_value (float),
                       cash (float), account_id (str).
        """

    @abstractmethod
    def get_stock_quote(self, symbols) -> dict:
        """
        Return latest bid/ask for one or more stock symbols.
        Single symbol: returns the same nested dict shape as AlpacaAPIClient today
          {"QuoteResponse": {"QuoteData": [{"All": {"bid": ..., "ask": ...}}]}}
        Multiple symbols: dict keyed by symbol, same inner shape.
        """

    @abstractmethod
    def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
        """
        Return latest bid/ask for a single option by its OCC symbol.
        Returns: {"bid": float, "ask": float, "mid": float}
        Raises on error (caller decides fallback).
        """

    @abstractmethod
    def get_options_contracts(
        self,
        underlying_symbol: str,
        expiration_date=None,
        expiration_date_gte=None,
        expiration_date_lte=None,
        option_type=None,
        strike_price_gte=None,
        strike_price_lte=None,
        limit: int = 100,
    ) -> list:
        """
        Return available option contracts matching the filters.
        Each item: {symbol, underlying_symbol, expiration_date, strike_price,
                    option_type, contract_size}
        """

    @abstractmethod
    def place_option_order(
        self,
        option_symbol: str,
        order_action: str,
        quantity: int,
        price_type: str,
        price: float = None,
    ) -> dict:
        """
        Place an option order.
        option_symbol: OCC symbol, e.g. "TSLA250420C00240000"
        order_action:  "BUY_OPEN" | "SELL_CLOSE"
        price_type:    "LIMIT" | "MARKET"
        price:         required for LIMIT; None for MARKET
        Returns: {order_id, status, filled_qty, filled_avg_price, limit_price, ...}
        """

    @abstractmethod
    def place_stock_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str,
        limit_price: float = None,
        time_in_force: str = "DAY",
    ) -> dict:
        """
        Place a stock order.
        side: "BUY" | "SELL"
        order_type: "LIMIT" | "MARKET"
        Returns: {order_id, status, filled_qty, filled_avg_price, ...}
        """

    @abstractmethod
    def order_status(self, order_id: str) -> dict:
        """
        Return current order state.
        Required keys: order_id, status, filled_qty, filled_avg_price.
        status values: "filled" | "partially_filled" | "open" | "canceled" | "expired"
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        """
        Cancel a pending order.
        Returns: {order_id, status: "cancelled", message}
        """
```

No tests needed for this file — it is a pure interface with no logic.

---

### Step 2 — Add `get_option_quote_by_occ` to `AlpacaAPIClient` and inherit `ExecutionClient`

Edit `alpha_tech_tracker/trade_api/alpaca_client/client.py`:

**2a.** Add import at the top:
```python
from alpha_tech_tracker.trade_api.execution_client import ExecutionClient
```

**2b.** Change class declaration:
```python
class AlpacaAPIClient(ExecutionClient):
```

**2c.** Add the new method (place it next to `get_option_quote`):
```python
def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
    from alpaca.data.requests import OptionLatestQuoteRequest
    quotes = self._option_data_client.get_option_latest_quote(
        OptionLatestQuoteRequest(symbol_or_symbols=[occ_symbol])
    )
    q = quotes[occ_symbol]
    bid = float(q.bid_price)
    ask = float(q.ask_price)
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "mid": mid}
```

**2d.** Update `place_option_order` signature to absorb `_option_symbol_override`
as a first-class named parameter so the monkey-patch in `order_executor.py` can
be deleted:
```python
def place_option_order(
    self,
    symbol,
    option_key=None,
    price=None,
    order_id=None,
    preview_order=None,
    price_type="LIMIT",
    option_type="CALL",
    order_action="BUY_OPEN",
    quantity=1,
    _option_symbol_override=None,   # ← add this parameter
):
    if _option_symbol_override:
        option_symbol = _option_symbol_override
    else:
        option_symbol = self._build_option_symbol(symbol, option_key, option_type)
    # ... rest of existing body unchanged
```

> Note: the `ExecutionClient.place_option_order` interface has a cleaner signature
> (OCC symbol as first arg). `AlpacaAPIClient` keeps its legacy signature for now
> to avoid breaking all call sites in one shot. The interface method is satisfied
> via a thin adapter in the concrete class — that cleanup is Phase 2.

---

### Step 3 — Replace all `_option_data_client` accesses

For each occurrence below, replace the three-line Alpaca SDK call with a single call
to `client.get_option_quote_by_occ(occ_symbol)` and unpack the returned dict.

**Pattern being replaced:**
```python
quote_resp = client._option_data_client.get_option_latest_quote(
    OptionLatestQuoteRequest(symbol_or_symbols=[occ_symbol])
)
q = quote_resp[occ_symbol]
bid = _D(q.bid_price)
ask = _D(q.ask_price)
mid = (bid + ask) / _D("2")
```

**Replacement:**
```python
q = client.get_option_quote_by_occ(occ_symbol)
bid = _D(str(q["bid"]))
ask = _D(str(q["ask"]))
mid = _D(str(q["mid"]))
```

**File-by-file changes:**

#### `order_executor.py` — line 44 (inside `_fetch_mid_bid_ask`)
The inner function currently reaches into `client._option_data_client`. Replace the
three lines with `get_option_quote_by_occ`. Also remove the `OptionLatestQuoteRequest`
import from this file (it will no longer be needed here).

#### `position_monitor.py` — lines 526 and 623
Two separate `try` blocks fetch a quote using `self._client._option_data_client`.
Replace both with `self._client.get_option_quote_by_occ(pos.option_symbol)`.
Remove the `OptionLatestQuoteRequest` import from this file.

#### `trade_engine.py` — line 973
Replace the SDK call with `self._client.get_option_quote_by_occ(option_symbol)`.
Remove the `OptionLatestQuoteRequest` import if it is no longer used elsewhere in
the file.

#### `option_price_monitor.py` — lines 202 and 285
Both are in snapshot-collection loops. Replace with
`self._client.get_option_quote_by_occ(spec.symbol)`.
Remove the `OptionLatestQuoteRequest` import from this file.

#### `contract_selector.py` — line 328
Inside `TimePremiumContractSelector`. Replace the SDK call with
`self._client.get_option_quote_by_occ(contract["symbol"])`.
Remove the `OptionLatestQuoteRequest` import from this file.

#### `position_sizer.py` — line 40
Replace with `q = self._client.get_option_quote_by_occ(option_symbol)`.
Remove the `OptionLatestQuoteRequest` import from this file.

After all six files are updated, the `alpaca.data.requests.OptionLatestQuoteRequest`
import will only remain in `alpaca_client/client.py` (inside `get_option_quote_by_occ`)
and in `signal_engine.py` (market data path — untouched).

---

### Step 4 — Remove the monkey-patch from `order_executor.py`

Lines 170–256 of `order_executor.py` currently:
1. Save `_original_place_option_order = AlpacaAPIClient.place_option_order`
2. Define `_patched_place_option_order` (identical logic with `_option_symbol_override` added)
3. Apply `AlpacaAPIClient.place_option_order = _patched_place_option_order`

Since Step 2d added `_option_symbol_override` as a real parameter to
`AlpacaAPIClient.place_option_order`, delete all three parts (the save, the
redefinition, and the assignment). Also remove the now-unused direct imports of
`OrderSide`, `TimeInForce`, `LimitOrderRequest`, `MarketOrderRequest` from
`alpaca.trading.*` that were only needed by the patched function.

After deletion, `_place_with_fill_escalation` uses `client.place_option_order(...)` with
`_option_symbol_override=option_symbol` — this now calls the real method directly.

---

### Step 5 — Update type hints in all 6 strategy modules

Change every `AlpacaAPIClient` type annotation in strategy-layer code to
`ExecutionClient`. This is annotation-only — no logic changes.

| File | Parameter to change |
|---|---|
| `trade_engine.py:226` | `alpaca_client: AlpacaAPIClient` → `alpaca_client: ExecutionClient` |
| `position_monitor.py:66` | `alpaca_client: AlpacaAPIClient` → `alpaca_client: ExecutionClient` |
| `order_executor.py:22` | `client: AlpacaAPIClient` → `client: ExecutionClient` |
| `order_executor.py:260` | `client: AlpacaAPIClient` → `client: ExecutionClient` |
| `option_price_monitor.py:72` | `client: AlpacaAPIClient` → `client: ExecutionClient` |
| `option_price_monitor.py:120` | `client: AlpacaAPIClient` → `client: ExecutionClient` |
| `contract_selector.py:81` | `client: AlpacaAPIClient` → `client: ExecutionClient` |
| `contract_selector.py:134` | `alpaca_client: AlpacaAPIClient` → `alpaca_client: ExecutionClient` |
| `contract_selector.py:231` | `client: AlpacaAPIClient` → `client: ExecutionClient` |
| `position_sizer.py:18` | `alpaca_client: AlpacaAPIClient` → `alpaca_client: ExecutionClient` |

For each file:
- Replace the `from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient`
  import with `from alpha_tech_tracker.trade_api.execution_client import ExecutionClient`
- Update the type annotation

> Exception: `op_momentum_trade_engine.py` and `option_fair_price_tester.py` instantiate
> `AlpacaAPIClient` directly — they keep the import. They pass the instance as
> `ExecutionClient` to downstream consumers, which is valid since `AlpacaAPIClient`
> is now a subclass.

---

### Step 6 — Run `autoflake` on all modified files

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

autoflake -i --remove-all-unused-imports \
  alpha_tech_tracker/trade_api/alpaca_client/client.py \
  alpha_tech_tracker/trade_api/execution_client.py \
  alpha_tech_tracker/op_momentum_strategy/order_executor.py \
  alpha_tech_tracker/op_momentum_strategy/position_monitor.py \
  alpha_tech_tracker/op_momentum_strategy/trade_engine.py \
  alpha_tech_tracker/op_momentum_strategy/option_price_monitor.py \
  alpha_tech_tracker/op_momentum_strategy/contract_selector.py \
  alpha_tech_tracker/op_momentum_strategy/position_sizer.py
```

---

## Verification

### Part A — Existing test suite (zero regression)

All existing tests must pass without modification. Tests mock `AlpacaAPIClient`
via `MagicMock` — they will continue to work because the mocks satisfy the duck-typed
interface. The `._option_data_client` mock attribute (set up in `conftest.py`) is no
longer accessed by strategy code, so those setups become inert (not a problem).

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

python -m pytest tests/op_momentum_trade_engine/ -v
```

Expected: same pass count as before the refactor.

### Part B — Historical replay

Verify the replay path runs end-to-end using a known past date. The replay exercises
the live engine code path (signals → position entry → monitoring → exit) using saved
bar data, so it will catch any wiring breakage immediately.

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# Use a date that has known saved bar data in market_data/cache/
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-03-17 \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100
```

Look for:
- Engine starts without import errors
- Opening range computed correctly
- Signal(s) fire (or no signal — either is fine as long as there's no exception)
- Engine exits cleanly at EOD

### Part C — Live engine startup (mock execution)

Verify the engine boots, connects to Alpaca WebSocket for market data, and runs
the pre-market ticker selector. Use `--mock-trade-execution` so no real orders
are placed.

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# Run outside market hours — engine will wait for bars but should boot cleanly
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100
```

Let it run for ~30 seconds and Ctrl-C. Look for:
- No `ImportError` or `AttributeError` on startup
- `AlpacaAPIClient` created and passed through without error
- `TickerSelector` pre-market run completes (may use previous-day fallback)
- No mention of `_option_data_client` in any traceback

---

## Files Changed Summary

| File | Change Type |
|---|---|
| `trade_api/execution_client.py` | **New** — abstract interface |
| `trade_api/alpaca_client/client.py` | Add `ExecutionClient` parent, add `get_option_quote_by_occ`, add `_option_symbol_override` param |
| `op_momentum_strategy/order_executor.py` | Remove monkey-patch block, replace `_option_data_client` access, update type hint |
| `op_momentum_strategy/position_monitor.py` | Replace 2× `_option_data_client` access, update type hint |
| `op_momentum_strategy/trade_engine.py` | Replace 1× `_option_data_client` access, update type hint |
| `op_momentum_strategy/option_price_monitor.py` | Replace 2× `_option_data_client` access, update type hint |
| `op_momentum_strategy/contract_selector.py` | Replace 1× `_option_data_client` access, update type hints (3×) |
| `op_momentum_strategy/position_sizer.py` | Replace 1× `_option_data_client` access, update type hint |

**Files NOT changed:** `signal_engine.py`, `bar_recorder.py`, `replay.py`,
`op_momentum_backtest.py`, `op_momentum_selector.py`, `op_momentum_selector_backtest.py`,
`op_momentum_trade_engine.py`, `option_fair_price_tester.py`, all test files.

---

## What Phase 2 Will Add (not in scope here)

- `IBKRExecutionClient(ExecutionClient)` — IBKR Client Portal Gateway adapter
- `ETradeExecutionClient(ExecutionClient)` — wrapping existing `EtradeAPIClient`
- `--broker alpaca|etrade|ibkr` CLI flag in `op_momentum_trade_engine.py`
- Alpaca market data client (WebSocket + historical) remains independent of broker choice
