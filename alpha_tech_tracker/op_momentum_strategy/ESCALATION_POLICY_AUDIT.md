# Escalation Policy Audit

**Scope:** `_place_with_fill_escalation` and `place_option_order_in_tranches` in `order_executor.py`
**Audit date:** 2026-04-19

---

## 1. Escalation Policy Overview

Every option order goes through a 4-phase fill escalation before falling back to market:

| Phase | Duration | Limit price | Trigger |
|---|---|---|---|
| **Step 0** (quick-exit) | 20 s | `entry_fill_price` | Position held < 6 min **and** stock within 0.3% of entry price |
| **Steps 1–N** (adaptive loop) | ~15 s/iteration | BUY: mid → ask; SELL: mid → max(bid, fair) | Always (step 0 optional) |
| **Step 3** (final limit) | 30 s (BUY) / 60 s (SELL) | BUY: ask; SELL: floor | After loop exhausted |
| **MARKET fallback** | Immediate | Market | All quote fetches fail |

Each phase polls for fill. Partial fills are tracked by a `_contracts_remaining` counter and `_confirmed_filled` counter. The escalation returns `(order: dict, confirmed_filled: int)`.

### Tranche wrapping

`place_option_order_in_tranches` splits large orders into batches of `tranche_size` (default 5 contracts) and calls `_place_with_fill_escalation` for each. Rules:

- If `contracts ≤ tranche_size`, calls the escalation once (no-tranche path).
- Tranches execute sequentially. On the first miss (`confirmed_filled == 0`), the loop stops.
- `entry_fill_price` is forwarded only to tranche 1.

---

## 2. Scenarios Reviewed

| # | Scenario | Covered? | Notes |
|---|---|---|---|
| 1 | Fill at step 0 (quick-exit, entry price) | ✅ | Returns immediately on first poll |
| 2 | Fill during adaptive loop (mid price) | ✅ | Partial fills accumulate correctly |
| 3 | Partial fill at step 3, remainder gone | ✅ | `confirmed_filled` tracks actual qty; `remaining` adjusted for next tranche |
| 4 | Full miss at step 3 (order cancelled, 0 filled) | ✅ | Returns `confirmed_filled=0`; tranche loop stops |
| 5 | All quote fetches fail → MARKET fallback | ✅ | Remaining contracts assumed filled; returns full count |
| 6 | Exception during placement | ✅ | Returns `{}, 0`; tranche loop stops |
| 7 | ≤ 5 contracts (no-tranche) | ✅ | Calls escalation once, returns `(order, confirmed_filled)` |
| 8 | 2 tranches, both fill | ✅ | `filled_so_far` accumulates across both |
| 9 | Tranche 1 fills, tranche 2 misses | ✅ | Loop breaks; `filled_so_far` = tranche 1 qty only |
| 10 | Tranche 1 misses immediately | ✅ | Loop breaks at first iteration; `filled_so_far = 0` |
| 11 | Tranche 1 partial fill, tranche 2 covers remainder | ✅ | `remaining` = unfilled from tranche 1; tranche 2 sized correctly |
| 12 | Close attempt, position partially filled, `close_order_failed` set | ✅ | `pos.contracts -= confirmed_filled`; retry on next bar (up to 3 retries) |
| 13 | `_poll_exit_fill_price` sees "cancelled" status | ✅ | Logs `FILL_MISS` warning; `close_order_failed` remains set for retry |

---

## 3. Bugs Found and Fixed

### Bug 1 — MISS/Fill Ambiguity

**Root cause:** `_place_with_fill_escalation` returned `order` (with `order_id` present) on a step 3 timeout/miss, identical to a successful fill return. Callers used `not order.get("order_id")` as a miss sentinel, which was never True for step 3 misses.

**Impact:** A step 3 miss was silently treated as a fill. The tranche loop continued to the next tranche even though 0 contracts were filled. `filled_so_far` was overcounted, and `pos.contracts` was decremented incorrectly, causing the position to appear closed when it was not.

**Fix:** Added a `_confirmed_filled = [0]` counter alongside `_contracts_remaining`. Every fill confirmation site increments `_confirmed_filled[0]` by the actual qty filled. The function now returns `(order, confirmed_filled: int)`. A miss returns `confirmed_filled=0`. The tranche loop breaks on `confirmed_filled == 0`.

---

### Bug 2 — Step 3 Partial Fill Overcounting

**Root cause:** At every partial fill site, `_contracts_remaining[0] -= min(filled_qty, _contracts_remaining[0])` correctly tracked the unfilled remainder — but there was no symmetric counter for what was actually filled. The final return path used `_contracts_remaining[0]` to infer the fill count, which underreported when multiple partial fills occurred across phases.

**Impact:** Multi-phase partial fills (e.g., 3 contracts filled in loop + 2 more at step 3) could return an incorrect `confirmed_filled`, causing `pos.contracts` and `filled_so_far` in the tranche loop to be wrong.

**Fix:** Same `_confirmed_filled` counter introduced in Bug 1. At every partial fill site, replaced:
```python
_contracts_remaining[0] -= min(filled_qty, _contracts_remaining[0])
```
with:
```python
partial = min(filled_qty, _contracts_remaining[0])
_confirmed_filled[0] += partial
_contracts_remaining[0] -= partial
```

---

## 4. Edge Cases — Noted, Not Fixed

### Edge Case A — EOD Timing Not Bounded

**Severity:** Medium

**Description:** The EOD close is triggered at 3:55 PM. For a position with > 5 contracts, `place_option_order_in_tranches` runs tranches sequentially. Each SELL tranche worst case:
- Adaptive loop: ~6–8 iterations × ~15 s ≈ 90–120 s
- Step 3 final limit: 60 s
- Total per tranche: ~150–180 s

With 2 tranches, the total wall-clock exposure is up to **~340–360 s (≈ 6 minutes)**. An EOD close initiated at 3:55 PM can produce active limit orders at or after 4:00 PM in after-hours — where fills are unlikely and cancellations may leave positions open overnight.

**No deadline is currently passed** into `_place_with_fill_escalation` or `place_option_order_in_tranches`.

**Proposed mitigation:** Add an optional `deadline: Optional[datetime]` parameter. Before each escalation step, check `datetime.now() >= deadline`. If past deadline, skip remaining steps and issue a direct MARKET order for the remaining contracts.

---

### Edge Case B — Step 0 Protection Missing on Tranche 2+

**Severity:** Low

**Description:** Step 0 (quick-exit at `entry_fill_price`) protects against selling below entry price when the position was entered recently (held < 6 min, stock near entry). `entry_fill_price` is forwarded only to tranche 1. Tranches 2+ start the adaptive loop at mid price without attempting `entry_fill_price` first.

For a position with > 5 contracts in a quick-exit scenario, the first 5 contracts are protected at entry price. The remaining contracts (up to 4 for a 9-contract position) start at mid — which may be below entry if the underlying moved slightly.

**Practical impact:** Rare scenario (quick-exit condition fires AND position size > 5 contracts). Maximum exposure is the spread between mid and entry price across the unprotected contracts.

**Proposed mitigation:** Pass `entry_fill_price` to all tranches when executing a quick-exit close. The per-tranche check (`held_duration < 6 min AND stock_within_0.3%`) would still gate whether step 0 actually fires, since those conditions are re-evaluated at the start of each escalation call.

---

## 5. Test Coverage Added

All scenarios above are covered by unit tests in `tests/op_momentum_trade_engine/test_order_executor.py`:

- `TestFillEscalation` — step-by-step escalation paths
- `TestPartialFillHandling` — partial fill accounting and `confirmed_filled` assertions
- `TestTrancheFilling` — no-tranche, 2-tranche fill, tranche miss, tranche 1 miss, entry_fill_price forwarding
