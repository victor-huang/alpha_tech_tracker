# Code Review — 2026-05-01 Commits

Adversarial review of four commits landed on 2026-05-01:

| SHA | Summary |
|---|---|
| `ea92432` | feat: add min_ev gate to live engine matching backtest behavior |
| `22e60ef` | feat: add penny pilot audit script and update commands |
| `681a6bc` | fix: eliminate mid-price fallback and gate re-entries on sequential window capital |
| `bf80a14` | fix: allow BRU/BRE re-entry after next window returns all capital |

---

## CONFIRMED BUGS

### BUG-1 — `_reconcile_stuck_positions` log message wrong for stock positions (`position_monitor.py`)

**Location:** `position_monitor.py`, `_reconcile_stuck_positions()`, both the RECONCILED and
RECONCILE PENDING message branches.

**Code:**
```python
msg = (
    f"RECONCILED {pos.option_symbol} x{pos.contracts}"
    f" — manually closed at broker, exit price ${float(fill_price):.2f}"
)
```

**Problem:** For stock positions, `pos.option_symbol` is `None` and `pos.contracts` is `0`.
The log message reads `"RECONCILED None x0 — ..."`, which is misleading for operators
monitoring the log. The RECONCILE PENDING branch has the same issue.

**Fix:** Branch on `pos.trade_type` to build the instrument label:
```python
instrument = f"{pos.ticker} x{pos.shares} shares" if pos.trade_type == "stock" \
             else f"{pos.option_symbol} x{pos.contracts}"
```

---

## MISSING TESTS

### FINDING-1 — `bf80a14` new re-entry path has zero test coverage

**Commit:** `bf80a14` — "allow BRU/BRE re-entry after next window returns all capital"

`_enter_reentry` was extended to inspect `_monitor._positions` when the next window has
already opened. If the next window has no open positions (capital returned), the re-entry
proceeds with a freshly computed budget. None of the four new sub-behaviors have tests:

1. Re-entry fires when next window opened but has no open positions
2. Re-entry is still blocked when next window has open positions
3. Re-entry skips when next window cleared but fresh budget is 0 or None
4. Re-entry uses the fresh budget (not the stale `watcher.window_budget`) in the call

The existing test `test_reentry_blocked_when_next_sequential_window_has_opened` relies on
`engine._monitor = None`, which means `next_has_open` stays `False` and the block now
passes through to the fresh-budget path — it passes only because `_get_window_budget`
raises an exception (mock client) and returns `None`. The test no longer validates the
"blocked because capital is deployed" behavior.

---

## DISMISSED FINDINGS

### DISMISSED-1 — TOCTOU between `next_has_open` check and `_get_window_budget` call

Between releasing `_monitor._lock` and calling `_get_window_budget`, another thread could
open a position in the next window and deploy the capital. This is a real race window but
acceptable in practice: signal processing is largely serialized, and `_get_window_budget`
will recompute from `buying_power` which would already reflect the new deployment.
No action required.

### DISMISSED-2 — `not stats` handling of empty dict (`ea92432`)

`window_rolling_stats.get(ticker)` returning `{}` is treated as "no stats" and skipped.
This matches the old behavior (`stats.get("ev_trade", 0) <= 0` → skip when ev_trade
defaults to 0 via missing key). Consistent.

---

## Implementation Plan

1. Fix BUG-1 in `position_monitor.py` — instrument label in reconciliation log messages
2. Add tests for `bf80a14` new path in `TestEnterReentry` (4 scenarios)
3. Update `test_reentry_blocked_when_next_sequential_window_has_opened` to attach a monitor
   with open positions so it validates the correct mechanism
