# Live Trade Engine — Bug Tracker

Running log of bugs identified from live sessions, code review, and log analysis.

**Status key:** `Fixed` | `Open` | `Won't Fix` | `Needs Backtest`

---

## Session: 2026-04-17

---

### BUG-005 (Critical): FILL_ESC MISS Reports `exit_fill=0.0000` — Position Marked Closed with Zero P&L

**Status: Fixed** — commit in `position_monitor.py`
**Severity:** Critical — money impact, position may still be open at broker with no engine awareness

#### What happened

When all FILL_ESC steps exhaust and the final limit order is cancelled, the broker returns `filled_avg_price=0.0` for the cancelled order. `_poll_exit_fill_price()` was treating this as a valid fill, logging `"Exit fill confirmed: fill=0.0000"` and setting `pos.exit_fill_price = 0.0`. The resulting P&L was `cap_pnl = 0.00` regardless of actual position value. The position appeared closed in the engine while likely still open at the broker.

#### Root cause

`_poll_exit_fill_price()` only checked for `fill_price is None` to skip an attempt. It did not check:
1. Whether the order status was `canceled` / `rejected`
2. Whether `filled_avg_price == 0` (broker's sentinel for no fill on a cancelled order)

#### Fix

- Added `order_status_val in ("canceled", "cancelled", "rejected")` → log `FILL_MISS` warning, return immediately without setting `exit_fill_price`
- Added `fill_price_raw == 0` → treat as not-yet-filled, retry up to `max_attempts`
- Same guard added to `_refresh_fill_prices()`
- Default retry params changed to `max_attempts=3, interval=5.0` (was 5 × 2s)

#### Files

- `position_monitor.py` — `_poll_exit_fill_price()`, `_refresh_fill_prices()`
- `tests/op_momentum_trade_engine/test_position_monitor.py` — `TestPollExitFillPrice`

---

### BUG-006 (Critical): Sequential Window Budget Inflates 2× After Multi-Session Restart

**Status: Fixed** — commit in `trade_engine.py`
**Severity:** Critical — money impact, A1/A2 deployed 2× intended capital

#### What happened

On 2026-04-17 the engine was restarted twice during the session. Each restart called `_recover_session()` → `_rebuild_window_returned()`, which summed `slot_capital + cap_pnl` for ALL closed M1 positions found in the checkpoint file, including positions from previous engine instances that same day. After two restarts each having traded ~$10k in M1, `_window_returned["M1"]` inflated to ~$21k. A1 was then budgeted at $21k instead of ~$11k.

#### Root cause

`_rebuild_window_returned` did not track how much of the accumulated `_window_returned` came from prior sessions vs the current session. With no way to distinguish restart-accumulated vs single-session returns, the full stale sum was used as A1's budget.

#### Fix

Added `_window_closed_primary_deployed` dict that tracks the sum of `slot_capital` for all closed primary positions per window. `_get_window_budget` applies normalization when `closed_deployed > initial_capital`:

```
effective = prior_returned - closed_deployed + initial_capital
         = net_pnl_all_sessions + initial_capital
```

This collapses multi-session accumulated principal back to one session's worth while preserving real P&L.

Normalization only fires when `self._replay_capital is not None` (i.e., `--capital` was passed).

#### Files

- `trade_engine.py` — `_get_window_budget()`, `_rebuild_window_returned()`, `__init__` / `run()` / `run_single_date()`
- `tests/op_momentum_trade_engine/test_trade_engine.py` — `TestGetWindowBudgetCapitalFlow`, `TestRebuildWindowReturned`

---

### BUG-007 (Operational): Sequential Entry — Rank-1 Entry Blocked Rank-2 for ~65 Seconds

**Status: Fixed** — commit in `trade_engine.py`
**Severity:** Moderate — delayed entry, missed fill-escalation window for rank-2

#### What happened

`_drain_pending_signals_for_window` iterated ranked signals sequentially. Rank-0's `_enter_position()` call — including order placement, fill escalation polling (up to 65s), and fill confirmation — ran to completion before rank-1's entry started. By the time rank-1 entered, the price had moved and fill escalation was already in a less favorable step.

#### Fix

Selections are now collected upfront (incrementing `open_position_count` speculatively), then all fired concurrently as daemon threads. On failure, the count is decremented by the caller, not inside `_enter_position`. No fallback to next-ranked ticker on failure — stop-on-failure is the intended behavior.

#### Files

- `trade_engine.py` — `_drain_pending_signals_for_window()`
- `tests/op_momentum_trade_engine/test_trade_engine.py` — `TestEnterPositionFailures`

---

## Session: 2026-04-08

---

### BUG-001 (Critical): `ITMOptionContractSelector` Selected OTM Strike Due to API Pagination

**Status: Fixed** — commits `6a3a902`, `867d7df`
**Severity:** Critical — wrong contract selected, maximum intrinsic loss exposure

**Trade affected:** SNDK [Bearish] A2 — `SNDK260410P00745000` x4, −$680

#### What happened

At 15:09 ET, the engine entered SNDK BEARISH (stock at $777.01) and selected the `$745` put — $32 OTM. Target was K≈$850. Alpaca returned K=$745 in the first page of its broad ±20% range query (`$622–$932`, limit=50). K=$850 was never in the result set.

#### Fix

`ITMOptionContractSelector` now uses a narrow ±5-increment window centered on `target_strike` as the primary search. For SNDK at $777, incr=$10: narrow range=[$800, $900]. Broad fallback retained if narrow search returns nothing.

**Files:** `contract_selector.py`

---

### BUG-002 (Open): No Minimum OR Range Guard — Instant `fallback_20pct` Exits

**Status: Open**
**Severity:** High — wasted capital on degenerate entries, confirmed −$550 P&L impact

**Trades affected:** TSLA [Bullish] A1 (OR range=$0.45 on $347 stock = 0.13%), FN [Bearish] A2 (OR range=$1.12 on $611 stock = 0.18%)

#### What happened

Both positions exited on `bars_held=0`. The fallback threshold `OR_low + 0.20 × OR_range` was within normal bid/ask noise when the OR range is < 0.2% of stock price. 1-bar afternoon windows (A1 at 13:15, A2 at 15:00) are most vulnerable.

#### Fix needed

Add `MIN_OR_RANGE_PCT = 0.003` (0.3%) guard in `signal_engine.py` before emitting a signal:

```python
if or_range / close < MIN_OR_RANGE_PCT:
    logger.info("%s [%s]: skipping — OR range %.4f%% below minimum", ...)
    return
```

Validate threshold via backtest sweep over 2025. Starting value 0.3% would have blocked both bad trades without filtering legitimate signals.

**Files:** `signal_engine.py`

---

### BUG-003 (Open): Stale M1 Catchup Signals Entered 34 Minutes Past Optimal

**Status: Open**
**Severity:** Moderate — late entries at suboptimal price; both AMD and SHOP entered at 10:19 ET vs optimal ~9:45 ET

#### What happened

Engine restarted at ~10:09 ET. Catchup replayed opening bars and fired M1 signals as if the opening range just closed. By the time fill escalation completed (10:19 ET) the market had already established its direction and AMD had dropped from $232 to $228.

#### Fix needed

In `signal_engine.py`, add a wall-clock staleness check before buffering any catchup signal:

```python
MAX_CATCHUP_DELAY_MINUTES = 20

elapsed = (now_et - signal_bar_et).total_seconds() / 60
if elapsed > MAX_CATCHUP_DELAY_MINUTES:
    logger.info("%s [%s]: skipping stale catchup signal — %d min elapsed", ...)
    return
```

**Files:** `signal_engine.py`

---

### BUG-004 (Open): Bad Alpaca Pre-Market Quote Returns ~50% of Actual Stock Price

**Status: Open**
**Severity:** Low — no P&L impact (pre-computation only; actual trade used live price)

**Ticker affected:** FN at 09:33 ET — logged `stock=299.875` when actual price was ~$607

#### What happened

The background `TimePremiumContractSelector` pre-computation logged FN's stock price as $299.875 (≈ half actual). The live A2 trade at 15:07 ET used `stock_price=610.62` correctly. Bad quote was only in earliest pre-market runs.

#### Fix needed

Add a sanity check in the pre-computation: if live quote deviates > 30% from last historical close (`warmup_close`), log a warning and skip pre-computation for that ticker.

Separately, check whether FN had a corporate action around 2026-04-08 that caused Alpaca to return a split-adjusted price temporarily.

**Files:** `option_price_monitor.py`

---

## Open: Session Save / Reload Issues

Issues identified via code review of `_recover_session()` and checkpoint handling. No live incidents yet; risk is latent.

---

### BUG-008 (Open): Exit Order Not Checked on Recovery — Broker-Closed Positions Re-Added as Open

**Status: Open**
**Severity:** High — could cause duplicate exit order on an already-closed position, or miss a broker-side fill entirely

#### What happened (risk scenario)

If the engine crashes or is stopped **after an exit order is placed but before `_close_callback` fires**, the checkpoint records the position as open with a non-null `exit_order_id`. On restart, `_recover_session()` re-adds it to `open_positions` without checking whether the exit order was filled at the broker. Two failure modes:
1. Position was already closed at broker → engine re-monitors it and places a second exit order
2. Position was partially filled → engine uses stale fill price, cap_pnl is wrong

#### Fix needed

In `_recover_session()`, for each recovered position with a non-null `exit_order_id`, call `order_status(exit_order_id)` and:
- If status = `filled`: apply the fill, close the position (skip re-monitoring)
- If status = `partially_filled`: log a warning, use the partial fill price
- If status = `canceled`: treat exit as failed, re-queue for exit monitoring
- If status = `open` / `pending`: leave as open — the exit order is still live

**Files:** `trade_engine.py` — `_recover_session()`

---

### BUG-009 (Open): No State Flush on SIGTERM / Ctrl+C — Checkpoint May Be Stale

**Status: Open**
**Severity:** Moderate — on planned stops, state written at last checkpoint interval may be behind by up to 30s

#### What happened (risk scenario)

`op_momentum_trade_engine.py` sends SIGTERM to the daemon PID on `stop`. No SIGTERM handler calls `_flush_session_state()` before the process exits. The checkpoint file may be missing the last 30s of state (filled orders, new positions). On the next startup, `_recover_session()` works from a stale file.

#### Fix needed

Add a SIGTERM handler in `OpMomentumTradeEngine` that calls `_flush_session_state()` before `sys.exit(0)`:

```python
import signal

def _handle_sigterm(self, signum, frame):
    logger.info("SIGTERM received — flushing session state before exit")
    self._flush_session_state()
    sys.exit(0)

# in __init__ or run():
signal.signal(signal.SIGTERM, self._handle_sigterm)
```

**Files:** `trade_engine.py`, `op_momentum_trade_engine.py`

---

### BUG-010 (Open): `--top` Decrease Not Enforced on Restart — Extra Positions May Be Monitored

**Status: Open**
**Severity:** Low — edge case when `--top` is changed between restarts mid-session

#### Risk scenario

If the engine was running `--top 3` and entered 3 positions, then is restarted with `--top 2`, `_recover_session()` recovers all 3 open positions and sets `open_position_count = 3`. Any new drain for the same window would see `count >= top_n (2)` and block new entries — this is correct. However, all 3 existing positions continue to be monitored and would all exit normally. The capital deployed (3 × slot) exceeds the new `--top 2` budget but no harm beyond over-deployment.

No fix needed in most cases; document as known behavior. A future fix could force-exit the lowest-ranked recovered position when the recovered count exceeds `--top`.

**Status: Won't Fix** (low probability, low impact, complex fix)

---

### BUG-011 (Open): `--capital` Change on Restart Does Not Rescale Recovered `slot_capital`

**Status: Open**
**Severity:** Low-Moderate — recovered positions retain original `slot_capital`; new entries use new capital but `_get_window_budget` arithmetic mixes old and new sizing

#### Risk scenario

If `--capital 10000` was used in session 1 (2 positions, $5k each), then `--capital 5000` is used on restart, `_recover_session()` restores positions with `slot_capital=$5000` each. `_rebuild_window_returned` sums them: `_window_closed_primary_deployed["M1"] = $10k`. `_get_window_budget` uses `initial_capital=$5k` and applies normalization: `effective = 10k - 10k + 5k = $5k`. A1 gets only $5k even though the actual M1 P&L may have been +$2k. Normalization erroneously clips the P&L contribution.

#### Fix needed

Document that changing `--capital` between restarts on the same trading day is unsupported. Alternatively, store the original `--capital` in the checkpoint and warn if it differs on restart.

**Files:** `trade_engine.py` — `_recover_session()`, `_flush_session_state()`

---

## Open: Capital Flow / Concurrency Issues

From the 2026-04-18 audit (`docs/CAPITAL_FLOW_AUDIT.md`).

---

### BUG-012 (Medium): DD Failed Entry Leaks `_window_returned`

**Status: Open**
**Severity:** Medium — A1/A2 budget understated when a double-down entry fails

#### What happened (risk scenario)

In `_check_doubledown_for_window`, `_window_returned[label]` is decremented by `freed_capital` before the DD entry is attempted. If `_enter_position` returns `False` (contract error, order rejection), the decrement is never restored. The freed capital appears consumed but no position was entered.

#### Fix needed

Restore `_window_returned` on entry failure:

```python
success = self._enter_position(...)
if not success:
    with self._signal_lock:
        self._window_state[label]["open_position_count"] -= 1
    with self._returned_lock:
        self._window_returned[label] = (
            self._window_returned.get(label, _D("0")) + freed_capital
        )
```

**Files:** `trade_engine.py` — `_check_doubledown_for_window()`

---

### BUG-013 (Low): `_window_state["budget"]` Written/Read Without Lock

**Status: Fixed**
**Severity:** Low — cosmetic inconsistency; safe due to timing but contrary to pattern

All other `_window_state` fields are accessed under `_signal_lock`. The `["budget"]` key is set in `_drain_pending_signals_for_window` and read in `_get_window_budget` without the lock. Safe because M1 drain completes hours before A1 reads it, but should be made consistent.

**Fix:** Wrapped the write in `_drain_pending_signals_for_window` and the read in `_get_window_budget` in `_signal_lock` blocks.

**Files:** `trade_engine.py` — `_drain_pending_signals_for_window()`, `_get_window_budget()`

---

### BUG-014 (Low): Entry Threads Not Joined Before DD Check — Slow Fills May Miss Survivor

**Status: Open**
**Severity:** Low — DD may skip or mis-target when fill escalation is slow

Entry threads are started and `_schedule_dd_check_for_window` fires immediately (DD runs at OR close + `doubledown_start_min`). If an entry is still in `_poll_entry_fill` (step 3+ escalation, up to ~2 min) when DD checks `_monitor._positions`, the position is not yet tracked and won't be counted as a survivor.

**Mitigation:** Increase `--doubledown-start` to 10+ minutes if escalation frequently hits step 3+.

**Files:** `trade_engine.py` — `_drain_pending_signals_for_window()`, `_schedule_dd_check_for_window()`

---

## Summary Table

| ID | Bug | Session | Severity | Status |
|---|---|---|---|---|
| BUG-001 | `ITMOptionContractSelector` OTM strike via pagination | 2026-04-08 | Critical | **Fixed** |
| BUG-002 | No min OR range guard → instant `fallback_20pct` | 2026-04-08 | High | **Open** |
| BUG-003 | Stale M1 catchup signals after mid-session restart | 2026-04-08 | Moderate | **Open** |
| BUG-004 | Bad Alpaca pre-market quote for FN (stock=299.875) | 2026-04-08 | Low | **Open** |
| BUG-005 | FILL_ESC MISS sets `exit_fill=0.0000` on cancelled order | 2026-04-17 | Critical | **Fixed** |
| BUG-006 | Sequential window budget inflates 2× after multi-restart | 2026-04-17 | Critical | **Fixed** |
| BUG-007 | Sequential entry blocked rank-2 for ~65s | 2026-04-17 | Moderate | **Fixed** |
| BUG-008 | Exit order not checked on recovery — broker-closed pos re-opened | Code review | High | **Open** |
| BUG-009 | No state flush on SIGTERM — checkpoint may be stale | Code review | Moderate | **Open** |
| BUG-010 | `--top` decrease not enforced on restart | Code review | Low | **Won't Fix** |
| BUG-011 | `--capital` change on restart corrupts normalization math | Code review | Low-Moderate | **Open** |
| BUG-012 | DD failed entry leaks `_window_returned` | Capital flow audit | Medium | **Fixed** |
| BUG-013 | `_window_state["budget"]` written/read without lock | Capital flow audit | Low | **Fixed** |
| BUG-014 | Entry threads not joined before DD check — slow fills may miss survivor | Capital flow audit | Low | **Fixed** |
