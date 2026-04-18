# Session Crash Recovery — Implementation Plan (G23)

On startup the engine starts fresh with no knowledge of prior open positions. If the
process crashes mid-session, any already-filled entries are invisible to the new
`PositionMonitor` and will go unmonitored until the market closes (no stop, no EOD
close from the engine).

This plan implements a two-part solution:

1. **Write** — flush a `session_YYYY-MM-DD.json` checkpoint after every position state
   change (open, close).
2. **Read** — on startup, load today's checkpoint, broker-verify each saved open
   position, re-add live ones to the monitor, and reconstruct window capital state.

Reconciliation is skipped entirely in `--mock-trade-execution` (replay) mode.

---

## Files to Create

| File | Purpose |
|---|---|
| `op_momentum_strategy/state/` | Runtime directory for session snapshots (gitignored) |
| `op_momentum_strategy/session_state.py` | Serialization + atomic file I/O (~70 lines) |
| `tests/unit/test_session_state.py` | Unit tests for the new module |

## Files to Modify

| File | Changes |
|---|---|
| `models.py` | Add `to_dict()` / `from_dict()` to `ActivePosition` |
| `position_monitor.py` | Add `get_all_positions()` method |
| `trade_engine.py` | `_flush_session_state()`, `_rebuild_window_returned()`, `_recover_session()`, call sites |
| `.gitignore` | Ignore `alpha_tech_tracker/op_momentum_strategy/state/*.json` |

---

## Step 1 — `ActivePosition` serialization (`models.py`)

Add two methods to the `ActivePosition` dataclass.

**`to_dict() -> dict`**

| Field type | Serialization |
|---|---|
| `str`, `int`, `bool` | pass through |
| `Decimal` | `str(value)` |
| `Optional[Decimal]` | `str(value)` or `None` |
| `datetime` | `dt.isoformat()` |
| `Optional[datetime]` | `dt.isoformat()` or `None` |

**`from_dict(d: dict) -> ActivePosition` (classmethod)**

Reverse mapping:
- `str` → `Decimal` via `_D()`
- ISO string → `datetime` via `datetime.fromisoformat()`
- All `Optional` fields: check for `None` before converting

---

## Step 2 — `session_state.py` (new module)

```
STATE_DIR = Path(__file__).parent / "state"

def _state_path(session_date: date) -> Path

def save(positions: list[ActivePosition], session_date: date) -> None

def load(session_date: date) -> list[ActivePosition]
```

### File format

```json
{
  "date": "2026-04-11",
  "positions": [ { "ticker": "NVDA", "signal": "BULLISH", ... }, ... ]
}
```

All positions are saved — both open and closed — so window capital can be
reconstructed from closed ones on reload.

### `save()` contract

- Writes to `state/session_YYYY-MM-DD.{pid}.tmp`, then `Path.replace()` to the final
  path — atomic on POSIX, readers always see a complete file.
- Logs and **swallows** all exceptions — a failed checkpoint write must never crash the
  trading engine.

### `load()` contract

- Returns `[]` when the file does not exist (first run of the day, or prior day's file).
- Returns `[]` on any read or parse error, logs a warning.
- Validates `data["date"] == str(session_date)` — rejects files from a prior day even
  if they exist in the same path.

---

## Step 3 — `get_all_positions()` in `position_monitor.py`

```python
def get_all_positions(self) -> list:
    with self._lock:
        return list(self._positions)  # thread-safe snapshot
```

Called by `_flush_session_state()` to collect all positions (open + closed) for the
checkpoint. Returns a copy, not the live list.

---

## Step 4 — `trade_engine.py` changes

### 4a. `_flush_session_state()`

```python
def _flush_session_state(self) -> None:
    if self._mock_trade_execution:
        return
    try:
        session_state.save(self._monitor.get_all_positions(), _now_et().date())
    except Exception:
        logger.exception("Failed to flush session state")
```

**Call sites (3 total):**

| Location | Line (approx) | Trigger |
|---|---|---|
| `_enter_option_position()` | after `self._monitor.add_position(pos)` (line 631) | new option position opened |
| `_enter_stock_position()` | after `self._monitor.add_position(pos)` (line 506) | new stock position opened |
| `_on_position_closed()` | end of method (line 747) | any position closed |

### 4b. `_rebuild_window_returned(positions)` (private helper)

Extracts the P&L accounting logic from `_on_position_closed` into a side-effect-free
helper. Used both by the refactored `_on_position_closed` (live path) and by
`_recover_session` (recovery path) without duplicating the computation.

```python
def _rebuild_window_returned(self, positions: list) -> None:
    """Add each position's returned capital into _window_returned.

    Mirrors _on_position_closed's accounting without logging side-effects.
    Safe to call with an empty list.
    """
    for pos in positions:
        if pos.slot_capital is None:
            continue
        entry = (
            pos.simulated_entry_mid
            if pos.simulated_entry_mid is not None
            else pos.entry_stock_price
        )
        exit_ = (
            pos.simulated_exit_mid
            if pos.simulated_exit_mid is not None
            else pos.exit_fill_price
        )
        if entry and entry > 0 and exit_:
            if pos.trade_type == "stock" and pos.signal == "BEARISH":
                raw = entry - exit_
            else:
                raw = exit_ - entry
            cap_pnl = (
                pos.slot_capital / entry * raw
                if pos.trade_type == "stock"
                else _D(pos.contracts) * _D("100") * raw
            )
        else:
            cap_pnl = _D("0")

        is_reentry = pos.trailing_arm_price is not None
        returned = cap_pnl if is_reentry else pos.slot_capital + cap_pnl
        with self._returned_lock:
            self._window_returned.setdefault(pos.window_label, _D("0"))
            self._window_returned[pos.window_label] += returned
```

`_on_position_closed` is then simplified to call `self._rebuild_window_returned([pos])`
instead of the inline computation, then logs as before.

### 4c. `_recover_session(session_date: date) -> list`

```python
def _recover_session(self, session_date: date) -> list:
    if self._mock_trade_execution:
        return []

    all_saved = session_state.load(session_date)
    if not all_saved:
        return []

    # Rebuild _window_returned from closed positions — no logging side-effects.
    self._rebuild_window_returned([p for p in all_saved if p.is_closed])

    # Broker-verify each saved open position.
    verified = []
    for pos in [p for p in all_saved if not p.is_closed]:
        try:
            status = self._client.order_status(pos.entry_order_id)
            if status.get("status") in ("filled", "partially_filled"):
                if pos.entry_fill_price is None:
                    fill = status.get("filled_avg_price")
                    if fill:
                        pos.entry_fill_price = _D(str(fill))
                verified.append(pos)
                logger.warning(
                    "RECOVERED position %s %s (order %s)",
                    pos.ticker,
                    pos.option_symbol or "stock",
                    pos.entry_order_id,
                )
            else:
                logger.warning(
                    "Skipping saved position %s — broker order status: %s",
                    pos.ticker,
                    status.get("status"),
                )
        except Exception:
            logger.exception(
                "Could not verify order %s for %s — skipping",
                pos.entry_order_id,
                pos.ticker,
            )

    return verified
```

### 4d. Recovery call site in `run()`

Inserted **after** `PositionMonitor` is created and **before** `signal_engine.start()`:

```python
# Reconcile open positions from a prior session crash (live mode only).
recovered = self._recover_session(today)
for pos in recovered:
    self._monitor.add_position(pos)
    label = pos.window_label
    self._window_state[label]["open_position_count"] += 1
    if pos.trailing_arm_price is None:  # primary (not re-entry)
        self._window_primary_deployed.setdefault(label, set()).add(pos.ticker)
```

---

## Recovery Startup Sequence

```
run()
  │
  ├── _window_returned = {}
  ├── _window_primary_deployed = {}
  ├── per-window _window_state initialized (open_position_count = 0)
  ├── PositionMonitor created
  ├── LiveSignalEngine created
  │
  ├── _recover_session(today)                          ← NEW
  │     ├── session_state.load("state/session_YYYY-MM-DD.json")
  │     ├── _rebuild_window_returned(closed_positions) ← capital accounting, no logs
  │     └── for each open position:
  │           order_status(entry_order_id) → verify filled
  │           logger.warning("RECOVERED ...")
  │           return verified list
  │
  ├── for pos in recovered:                            ← NEW
  │     monitor.add_position(pos)
  │     _window_state[label]["open_position_count"] += 1
  │     _window_primary_deployed[label].add(pos.ticker)  # primary only
  │
  └── signal_engine.start()  ← stream begins; monitor loop begins
```

---

## What Is Explicitly NOT Recovered

| Item | Reason |
|---|---|
| `_reentry_watchers` | Out of scope for this plan |
| `bars_held` | Reset to 0; cosmetic counter, not load-bearing for exit logic |
| `pending_signals` | OR window has already passed on restart |
| `collection_deadline` | Recomputed correctly from window config |

---

## Step 5 — Tests

### `tests/unit/test_session_state.py`

| Class | Tests |
|---|---|
| `TestActivePositionSerialization` | `test_to_dict_converts_decimal_to_str` |
| | `test_to_dict_converts_datetime_to_iso` |
| | `test_to_dict_handles_none_optionals` |
| | `test_from_dict_round_trip_preserves_all_fields` |
| `TestSessionStateSave` | `test_creates_state_dir_if_missing` |
| | `test_file_named_by_date` |
| | `test_write_is_atomic_tmp_then_rename` |
| | `test_save_swallows_exception_and_logs` |
| `TestSessionStateLoad` | `test_returns_empty_list_when_no_file` |
| | `test_returns_empty_list_for_wrong_date` |
| | `test_returns_empty_list_on_parse_error` |
| | `test_round_trip_save_and_load` |

### `tests/op_momentum_trade_engine/test_trade_engine.py` — new `TestRecoverSession` class

| Test | Verifies |
|---|---|
| `test_skips_recovery_in_mock_mode` | `session_state.load` not called when `_mock_trade_execution=True` |
| `test_returns_empty_when_no_checkpoint` | `load` returns `[]` → monitor unchanged |
| `test_adds_broker_verified_position_to_monitor` | `add_position()` called for verified position |
| `test_skips_position_when_broker_order_not_filled` | order status `"new"` → position skipped |
| `test_skips_position_when_order_status_raises` | exception → position skipped, no crash |
| `test_populates_entry_fill_price_when_none_in_checkpoint` | fill price fetched from broker |
| `test_increments_open_position_count_for_recovered_position` | `_window_state["M1"]["open_position_count"]` = 1 |
| `test_adds_primary_ticker_to_window_primary_deployed` | non-reentry → ticker in `_window_primary_deployed["M1"]` |
| `test_reentry_position_not_added_to_primary_deployed` | reentry → ticker NOT in `_window_primary_deployed` |
| `test_rebuilds_window_returned_from_closed_positions` | closed position's `slot_capital` appears in `_window_returned` |

### `tests/op_momentum_trade_engine/test_trade_engine.py` — new `TestFlushSessionState` class

| Test | Verifies |
|---|---|
| `test_flush_skipped_in_mock_mode` | `session_state.save` not called when mock mode |
| `test_flush_called_after_option_entry` | `save` called after `_enter_option_position` |
| `test_flush_called_after_stock_entry` | `save` called after `_enter_stock_position` |
| `test_flush_called_after_position_closed` | `save` called at end of `_on_position_closed` |
| `test_flush_exception_does_not_crash_engine` | `save` raises → no exception propagated |

### `tests/unit/test_op_momentum_backtest.py` (existing) — new `TestRebuildWindowReturned` class

| Test | Verifies |
|---|---|
| `test_primary_position_returns_slot_capital_plus_pnl` | slot + cap_pnl accumulated |
| `test_reentry_position_returns_pnl_only` | only cap_pnl accumulated (no slot_capital) |
| `test_skips_position_with_no_slot_capital` | `slot_capital=None` → no entry in dict |
| `test_empty_list_is_noop` | no exception, dict unchanged |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| State file from yesterday | `load()` rejects it (date mismatch) → returns `[]` → clean start |
| Position manually closed at broker during crash window | `order_status` returns non-filled status → skipped, logged |
| `order_status` raises (network error) | Exception caught, position skipped, logged |
| State directory missing on first run | `save()` creates it via `STATE_DIR.mkdir(parents=True, exist_ok=True)` |
| Checkpoint write fails (disk full) | `save()` logs exception, swallows it — engine continues unaffected |
| Multiple windows, partial crash (M1 open, A1 not yet started) | `_window_returned["M1"]` rebuilt from checkpoint; A1 budget computed normally from that |
