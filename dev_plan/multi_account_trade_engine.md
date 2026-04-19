# Multi-Account Trade Engine — Discovery & Planning

**Created:** 2026-04-19
**Branch:** `open_market_momentum_stategy`
**Goal:** Understand what refactoring is needed to run a single engine instance that trades
stocks in one account and options in another (or any combination of N accounts × trade types).

---

## Background

The current engine supports one execution client per process. Running two accounts today
requires two separate processes (separate working directories, each with its own `config.json`).
That works but creates redundant market data streams and no shared capital coordination.

This document records the discovery investigation into what a single-process multi-account
design would look like.

---

## Current Architecture — Key Constraints

### 1. `trade_type` is engine-wide, not per-window

`self._trade_type` is set once at `OpMomentumTradeEngine.__init__` and shared across all
windows. `WindowConfig` has no `trade_type` field.

**Impact:** One engine instance can only trade one asset type. It is impossible today to
configure M1 as options and A1 as stocks within a single process.

---

### 2. Single execution client — 27 call sites

`self._client` is stored at engine init and flows to every subcomponent. Specific locations:

| File | Lines | What it does |
|---|---|---|
| `trade_engine.py` | 274 | Stored as `self._client` |
| `trade_engine.py` | 452, 603 | `PositionSizer` instantiated with `self._client` |
| `trade_engine.py` | 715, 1116 | `order_status()` — fill detection |
| `trade_engine.py` | 1157, 1265, 1829 | `get_accounts()` — window budget, sequential flow, EOD balance |
| `trade_engine.py` | 1496 | Option quote fetch for entry |
| `position_monitor.py` | 120 | Stored as `self._client` for all exits |
| `position_monitor.py` | 547, 647, 968 | `get_stock_quote()` — stop price checks |
| `position_monitor.py` | 598, 775 | Exit order placement |
| `position_monitor.py` | 682, 832, 850, 899, 906 | Exit escalation and fill monitoring |
| `position_sizer.py` | 31, 40, 57, 110 | Buying power and option quote fetches |
| `contract_selector.py` | 94 | `get_options_contracts()` — strike selection |
| `option_price_monitor.py` | 128 | Quote collection for fair-price advisor |

**Impact:** All order placement, all exit routing, all contract selection, and all buying power
queries go through one client unconditionally. There is no mechanism to dispatch to account B
for options while account A handles stocks.

---

### 3. Account/buying power queries are account-blind

`PositionSizer.compute()` and `compute_stock()` call `client.get_accounts()` with no account
ID selector. The call returns the balance of whichever account the client is authenticated to.

There are 5 distinct `get_accounts()` calls across the engine:
- `position_sizer.py:31` — slot capital computation
- `trade_engine.py:1157` — M1 initial budget
- `trade_engine.py:1265` — sequential window budget (A1, A2)
- `trade_engine.py:1829` — live buying power log at startup

**Impact:** If two windows pull from different accounts simultaneously, each would read the
wrong balance and both would over-deploy capital.

---

### 4. `ActivePosition` has no account context

Fields that currently exist: `window_label`, `trade_type`, `rank`, `window_budget`,
`slot_capital`, `ticker`, `option_symbol`, `contracts`, `shares`, etc.

Fields that are absent:
- `account_id`
- `broker`
- Any reference to the client that should handle its exit

**Impact:** When `PositionMonitor._close_position()` fires, it uses `self._client` for every
position regardless of which account the position was entered in. In a multi-account setup
this would route exits to the wrong broker/account.

---

### 5. Shared state dict key collisions

Three engine-level dictionaries are keyed only by window label:

| Dict | Collision risk |
|---|---|
| `_window_state` | Signal from account A's window overwrites account B's same-label window |
| `_window_returned` | P&L from different accounts accumulates into one bucket, corrupting sequential capital flow |
| `_window_primary_deployed` | Capital deployed across accounts conflated, breaking un-deployed calculation |

All three are protected by `_signal_lock`, but locks cannot prevent key collisions — two
accounts sharing a window label would silently corrupt each other's state.

---

## Options Considered

### Option A — `ExecutionSlot` abstraction (recommended for coordinated capital)

Introduce a lightweight config object:

```python
@dataclass
class ExecutionSlot:
    account_id: str           # unique key; used to rekey state dicts
    client: ExecutionClient   # broker-specific client for this account
    trade_type: str           # "stock" | "option"
    window_label: str | None  # restrict slot to one window, or None = all windows
```

Engine holds `slots: list[ExecutionSlot]` instead of a single `self._client`. At entry time,
`_enter_position()` resolves the matching slot for `(window_label, trade_type)` and uses that
slot's client. `ActivePosition` gains an `execution_slot` reference so `PositionMonitor` knows
exactly which client to call for exits.

State dicts rekeyed from `window_label` → `(account_id, window_label)` to prevent collisions.

**Example configuration:**
```
slots=[
    ExecutionSlot(account_id="alpaca-stocks",  client=alpaca_client,  trade_type="stock",  window_label="M1"),
    ExecutionSlot(account_id="ts-options",     client=ts_client,      trade_type="option", window_label="M1"),
    ExecutionSlot(account_id="alpaca-stocks2", client=alpaca_client2, trade_type="stock",  window_label="A1"),
]
```

**Scope:**
| File | Nature of change |
|---|---|
| `models.py` | Add `account_id`, `execution_slot` to `ActivePosition`; add `execution_slot` to `WindowConfig` |
| `trade_engine.py` | Replace `self._client` with slot registry; slot resolution at entry; rekey state dicts |
| `position_monitor.py` | Route all 13 exit call sites through `pos.execution_slot.client` |
| `position_sizer.py` | Accept slot, query `slot.client.get_accounts()` for account-specific buying power |
| `contract_selector.py` | Accept slot client instead of engine client |
| `option_price_monitor.py` | Multi-slot quote collection |
| `op_momentum_trade_engine.py` | CLI: `--slot` flag or YAML config for slot list; `build_slots()` helper |
| `config.py` | `build_execution_slot()` helper |
| Tests | Multi-slot scenario tests |

**Estimated scope:** 600–800 new/modified lines across 8 files.
**Risk:** Moderate — touches the hottest execution paths.
**Benefit:** Extensible to N accounts; backward compatible (default to single slot).

---

### Option B — Multi-client dict (simpler but messier)

Replace `self._client` with `self._clients: dict[str, ExecutionClient]` keyed by account ID.
Pass a lookup function to all subcomponents. No new abstraction layer — just threading the
dict through every call site.

**Scope:** Similar to Option A but without the clean encapsulation. Harder to reason about,
higher chance of missed call sites.

---

### Option C — Separate engine processes (zero refactor, recommended for independent accounts)

Run one engine process per account in separate working directories. Each has its own
`config.json`, `--market-data-source`, `--execution-broker`, and `--trade-type`.

```
~/alpha_engine_stocks/    config.json → execution_broker: alpaca,       trade_type: stock
~/alpha_engine_options/   config.json → execution_broker: tradestation, trade_type: option
```

**Scope:** 0 refactoring. Already supported today.
**Risk:** Near zero.
**Limitations:**
- Redundant market data connections (two WebSocket streams for the same tickers)
- No shared capital coordination — morning options P&L cannot feed afternoon stocks budget
- Operational overhead of managing N daemon processes

---

## Decision Framework

| Question | Answer → |
|---|---|
| Do accounts need shared capital flow (M1 options P&L seeds A1 stocks budget)? | Yes → Option A |
| Are accounts fully independent (each deploys its own fixed budget)? | No coordination needed → Option C |
| Is reducing market data connections important (one stream, multiple accounts)? | Yes → Option A |
| Is implementation risk a primary concern right now? | Yes → Option C first, A later |

---

## Recommended Path

**Short term:** Use Option C (separate processes). It works today with zero risk. The
`--market-data-source` and `--execution-broker` flags added in this branch make it clean
to configure per-process.

**Medium term:** Implement Option A if coordinated capital or consolidated observability
(single log, single Telegram feed, one EOD summary) becomes important. The `ExecutionSlot`
design is a natural extension of the existing `ExecutionClient` abstraction.

**If implementing Option A**, the `ExecutionSlot` should be the unit tested at the
integration level — verify that entries route to the right client, exits route through the
position's own slot, and state dict rekeying eliminates cross-account contamination.
