# Stock Trading Support — Implementation Plan

## Overview

Add stock trading as an alternative to options trading in the live trade engine.
A new `--trade-type {options,stock}` CLI flag selects the mode at startup.

The strategy logic is **unchanged** — OR breakout signals, MA trailing stops, hard stops,
fallback stops, and EOD closure all operate on stock price and require no modification.
Only the entry and exit mechanics differ: contract selection + option order vs. shares + stock order.

---

## New CLI Flag

```bash
--trade-type {options,stock}   # default: options (backwards compatible)
```

Example usage:

```bash
# Run with stock trading
python op_momentum_trade_engine.py run --trade-type stock --regime-filter --regime-ma 8

# Run with options trading (existing behavior, unchanged)
python op_momentum_trade_engine.py run --trade-type options --regime-filter --regime-ma 8
```

---

## Files to Change

### 1. `models.py` — Tiny

Add two fields to `ActivePosition`:

| Field | Type | Description |
|---|---|---|
| `trade_type` | `str` | `"options"` or `"stock"` |
| `shares` | `int` | Number of shares (stock mode only; 0 for options) |

`option_symbol` and `contracts` remain on the model but are `None`/`0` for stock trades.

---

### 2. `position_sizer.py` — Small

Add a new `compute_stock()` method alongside the existing `compute()` (options):

```python
def compute_stock(self, ticker, stock_price, capital_weight=1.0, window_budget=None) -> (int, Decimal):
    """
    Returns (shares, limit_price) for a stock entry.
    Budget logic is identical to compute() — same capital_weight and window_budget handling.
    shares = int(budget / stock_price)
    limit_price = current ask price from stock quote
    """
```

Key differences from `compute()`:
- No options multiplier (× 100)
- Uses stock bid/ask quote instead of option quote
- Returns `shares` (int) instead of `contracts` (int)

---

### 3. `order_executor.py` — Small

Add a new `place_stock_order()` function alongside `_place_with_fill_escalation()`:

```python
def place_stock_order(client, ticker, shares, order_action, mock=False) -> dict:
    """
    Places a stock buy or sell order with the same 3-step fill escalation as options:
      Step 1 (0–60s):   limit order at mid price
      Step 2 (60–120s): cancel unfilled → re-place at ask (buy) or bid (sell)
      Step 3 (120s+):   cancel unfilled → market order
    order_action: "BUY_OPEN" or "SELL_CLOSE"
    Returns same dict shape as _place_with_fill_escalation:
      {order_id, status, filled_qty, filled_avg_price}
    """
```

Uses `client.place_stock_order()` which already exists on `AlpacaAPIClient`.

---

### 4. `position_monitor.py` — Small

**`_evaluate_stop()` — no changes.** All stop conditions are computed from stock price, which is
the same for both trade types. The existing logic is correct as-is.

**`_close_position()` — add trade_type branch:**

```python
def _close_position(self, pos, reason):
    if pos.trade_type == "stock":
        # fetch stock quote for P&L notification
        # place_stock_order(client, pos.ticker, pos.shares, "SELL_CLOSE")
        # record exit_order_id, exit_fill_price
    else:
        # existing option close logic — unchanged
```

`close_all()` (EOD) requires no changes — it calls `_close_position()` which handles the branch.

---

### 5. `op_momentum_trade_engine.py` — Medium

**`_enter_position()` — add trade_type branch:**

Current options flow:
```
signal → contract_selector.select() → position_sizer.compute() → place_option_order → ActivePosition
```

New branched flow:
```python
if self._trade_type == "stock":
    shares, limit_price = self._sizer.compute_stock(ticker, stock_price, ...)
    order = place_stock_order(client, ticker, shares, "BUY_OPEN")
    pos = ActivePosition(trade_type="stock", shares=shares, option_symbol=None, contracts=0, ...)
else:
    # existing options flow — unchanged
    option_symbol = self._contract_selector.select(ticker, signal, stock_price)
    contracts, limit_price = self._sizer.compute(option_symbol, ...)
    order = _place_with_fill_escalation(...)
    pos = ActivePosition(trade_type="options", contracts=contracts, ...)
```

**`_parse_args()` — add `--trade-type` argument** and pass through to engine constructor.

**`print_status()` / `print_summary()` in `PositionMonitor`** — display shares instead of
contracts when `trade_type == "stock"`.

---

## What Does NOT Change

| Component | Reason |
|---|---|
| `signal_engine.py` | Signals are stock-price based — identical for both modes |
| `contract_selector.py` | Skipped entirely in stock mode |
| `position_monitor._evaluate_stop()` | All stop conditions use stock price — unchanged |
| Stop logic (hard stop, fallback, trailing MA, max loss) | Identical for both modes |
| EOD close (`close_all()`) | Delegates to `_close_position()` which handles the branch |
| Multi-window, regime filter, ranking, scoring | Unaffected |
| Mock trading mode | Works the same for both trade types |

---

## Change Summary

| File | Size | What Changes |
|---|---|---|
| `models.py` | Tiny | Add `trade_type: str`, `shares: int` to `ActivePosition` |
| `position_sizer.py` | Small | Add `compute_stock()` method |
| `order_executor.py` | Small | Add `place_stock_order()` function |
| `position_monitor.py` | Small | Branch on `trade_type` in `_close_position()` only |
| `op_momentum_trade_engine.py` | Medium | Branch in `_enter_position()`, add `--trade-type` CLI arg |

---

## Implementation Order

1. `models.py` — add fields (no logic, unblocks everything else)
2. `position_sizer.py` — add `compute_stock()`
3. `order_executor.py` — add `place_stock_order()`
4. `position_monitor.py` — branch in `_close_position()`
5. `op_momentum_trade_engine.py` — branch in `_enter_position()`, wire CLI flag

---

## Testing Approach

Use `--mock-trade-execution` to validate stock mode without placing real orders:

```bash
python op_momentum_trade_engine.py run \
  --trade-type stock \
  --mock-trade-execution \
  --regime-filter --regime-ma 8
```

Verify:
- Entry logs show shares (not contracts/option symbol)
- Stop conditions fire correctly on stock price movements
- EOD close logs show stock sell orders
- P&L calculation uses shares × price delta (not option premium)
