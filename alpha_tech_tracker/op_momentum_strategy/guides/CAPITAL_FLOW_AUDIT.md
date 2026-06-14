# Capital Flow & Concurrency Audit

**Date:** 2026-04-18  
**Scope:** Multi-window sequential capital flow (M1 → A1 → A2) in `trade_engine.py`; lock correctness under async order execution

---

## Thread Model (live mode)

Six concurrent threads share capital state:

| Thread | What it does |
|---|---|
| Signal engine | WebSocket callbacks → `_on_signal_for_window()` |
| Per-window drain (one per window) | Loops until deadline → `_drain_pending_signals_for_window()` |
| Entry threads (N daemon threads) | Spawned by drain → `_enter_position()` |
| Monitor thread | Every 30s → `on_bar()` → `close_callback` → `_on_position_closed()` |
| DD timer | `threading.Timer` → `_check_doubledown_for_window()` |
| Main thread | Blocks on `monitor_thread.join()` |

## Lock Inventory

| Lock | Protects |
|---|---|
| `_signal_lock` | `_window_state` (pending_signals, open_position_count) |
| `_returned_lock` | `_window_returned`, `_window_primary_deployed`, `_window_closed_primary_deployed` |
| `_pnl_lock` | `_daily_realized_pnl` |
| `_monitor._lock` | `_positions`, `_reentry_watchers` |

---

## Finding 1 — No Deadlock Risk ✓

All four locks are acquired sequentially, never nested. Key proof points:

- `_get_window_budget`: acquires `_returned_lock` → releases → acquires `_monitor._lock`
- `_rebuild_window_returned`: acquires `_returned_lock` → releases → acquires `_pnl_lock`
- `_check_doubledown_for_window`: acquires `_monitor._lock` → releases → acquires `_returned_lock` → releases → acquires `_signal_lock`
- `_enter_position`: acquires `_returned_lock` briefly → releases → calls `monitor.add_position()` → acquires `_monitor._lock`
- `PositionMonitor.on_bar` / `close_all`: `close_callback` is called **outside** `_monitor._lock` — the lock is released before the callback fires

No AB-BA lock ordering inversion anywhere in the call graph.

---

## Finding 2 — Sequential Capital Flow is Correct ✓

The A1 budget formula in `_get_window_budget`:

```
A1_budget = prior_returned           (closed M1 positions, principal + P&L)
           + open_primary_capital    (still-open M1 positions at cost basis)
           - open_reentry_capital    (re-entries that already redeployed their slot)
           + undeployed              (prior_budget − prior_deployed, unused M1 slots)
```

Key cases verified correct:

| Scenario | Result |
|---|---|
| All M1 closed before A1 drains | `prior_returned` = full M1 principal + P&L; `open_primary_capital` = 0 ✓ |
| Some M1 positions still open at 1:20 PM | `open_primary_capital` adds cost basis so capital is accounted for ✓ |
| M1 had a re-entry (reversal/BRE/BUE) | Re-entry's `slot_capital` subtracted — primary exit returned principal, re-entry redeployed it ✓ |
| M1 had only 1 signal but budgeted for 2 | Undeployed slot flows forward via `prior_budget − prior_deployed` ✓ |
| Multi-session restart (checkpoint inflation) | Normalization: `effective = prior_returned − closed_deployed + initial_capital` ✓ |

---

## Finding 3 — Race Condition: TOCTOU Gap in `_get_window_budget` (low risk)

**Location:** `trade_engine.py` → `_get_window_budget()`

`_window_returned` and `_monitor._positions` are read under different locks with a small gap:

```python
with self._returned_lock:
    prior_returned = self._window_returned.get(prior_label, _D("0"))  # snapshot T1
# lock released — gap here

with self._monitor._lock:
    for pos in self._monitor._positions:    # snapshot T2
        if pos.is_closed: continue
        open_primary_capital += pos.slot_capital
```

**Safe direction (no double-count):** `pos.is_closed = True` is always set before `close_callback` is called (before `_window_returned` is updated). So if T1 sees returned capital, `is_closed` is already True by T2 and the position is correctly excluded from `open_primary_capital`.

**Unsafe direction (capital missed):** If a position closes in the gap between T1 and T2:
- T1 reads `_window_returned` before the close — returned capital not yet included
- Position closes → `pos.is_closed = True` → callback → `_window_returned` updated
- T2 sees `pos.is_closed = True` → skips from `open_primary_capital`

Result: budget misses the returned capital entirely for that position.

**Practical risk:** M1 positions close hours before A1 drains. The race window is microseconds wide and requires a position to close at exactly 1:20 PM. Low probability but real.

**Suggested fix:** Read both values under a single atomic snapshot — either snapshot `_monitor._positions` while holding `_returned_lock`, or read `_window_returned` while holding `_monitor._lock`.

---

## Finding 4 — Bug: DD Failed Entry Leaks `_window_returned` (medium severity)

**Location:** `trade_engine.py` → `_check_doubledown_for_window()`

`_window_returned` is decremented before the DD entry attempt, but is not restored if entry fails:

```python
# Subtract freed capital pre-emptively
with self._returned_lock:
    self._window_returned[label] = max(_D("0"), current - freed_capital)

# ...

success = self._enter_position(...)
if not success:
    with self._signal_lock:
        self._window_state[label]["open_position_count"] -= 1
    # BUG: _window_returned is NOT restored — A1/A2 budget will be understated
```

**Impact:** If a DD entry fails (contract selection error, order rejection), `_window_returned["M1"]` is permanently reduced by `freed_capital`. No DD position was entered, but the capital appears consumed. A1's budget is understated by that amount.

**Fix:**

```python
success = self._enter_position(...)
if not success:
    with self._signal_lock:
        self._window_state[label]["open_position_count"] -= 1
    with self._returned_lock:
        self._window_returned[label] = (
            self._window_returned.get(label, _D("0")) + freed_capital
        )
        logger.warning(
            "DD [%s] entry failed — restoring %.2f to _window_returned",
            label, float(freed_capital),
        )
```

**Status: Open** — tracked as BUG-012 in `BUGS.md`

---

## Finding 5 — `_window_state["budget"]` Not Lock-Protected (low, cosmetic)

**Location:** `trade_engine.py` → `_drain_pending_signals_for_window()` and `_get_window_budget()`

All other `_window_state` fields are accessed under `_signal_lock`, but `["budget"]` is not:

```python
# Written without lock (in drain):
self._window_state[label]["budget"] = window_budget

# Read without lock (in budget computation):
prior_budget = self._window_state.get(prior_label, {}).get("budget")
```

Safe in practice because M1 drain (write) completes hours before A1 budget computation (read), with no concurrent writers. But inconsistent with the rest of `_window_state` access.

**Suggested fix:** Move the write inside a `_signal_lock` block, and read it under `_signal_lock` in `_get_window_budget`.

**Status: Open** (low priority)

---

## Finding 6 — Entry Threads Not Joined Before DD Check (low, edge case)

**Location:** `trade_engine.py` → `_drain_pending_signals_for_window()`

Entry threads are started but not joined before `_schedule_dd_check_for_window` fires:

```python
for t in threads:
    t.start()
self._schedule_dd_check_for_window(win)  # fires immediately; entries may still be running
```

DD fires at OR close + `doubledown_start_min` (default 5 min). Fill escalation takes up to ~2 min in the worst case (steps 1–4). If a position is still in `_poll_entry_fill` when DD checks, it hasn't been added to `_monitor._positions` yet and won't be counted as a survivor.

**Impact:** DD may incorrectly see "no survivors" and skip, or fire against the wrong survivor. Low probability with 5-minute delay.

**Mitigations:**
- Increase `--doubledown-start 10` if escalation frequently hits step 3+
- Or join entry threads with a timeout before scheduling DD

**Status: Open** (low priority)

---

## Summary

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Deadlock risk | ✅ None | — |
| 2 | Sequential capital flow correctness | ✅ Correct | — |
| 3 | TOCTOU gap in `_get_window_budget` | Low (theoretical) | Open |
| 4 | DD failed entry leaks `_window_returned` | **Medium** | Open — BUG-012 |
| 5 | `_window_state["budget"]` unprotected | Low (cosmetic) | Open |
| 6 | Entry threads not joined before DD check | Low (edge case) | Open |
