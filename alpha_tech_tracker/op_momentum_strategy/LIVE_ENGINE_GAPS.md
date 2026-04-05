# Live Engine Gaps

Features present in `op_momentum_backtest.py` that are missing or different
in the live trading engine (`trade_engine.py` / `position_monitor.py`).

---

## Bugs

### ~~G1 — Stale `_open_position_count` reference in `_enter_position` exception handler~~ ✓ Fixed

**File:** `trade_engine.py` line ~260
**Severity:** High — crashes on any real order placement failure

When `_place_entry()` raises an exception, the except block decrements
`self._open_position_count` which no longer exists. It should decrement
`self._window_state[window_label]["open_position_count"]`.

```python
# current (broken)
self._open_position_count -= 1

# should be
self._window_state[window_label]["open_position_count"] -= 1
```

---

## Logic Differences

### G2 — Fallback exit checks `close`, backtest checks intrabar `high`

**File:** `position_monitor.py` lines 108, 135
**Severity:** Medium — live exits will be systematically later/worse on fallback hits

Backtest logic:
```python
# exits at close if the bar's high touched the fallback level
if bar["High"] >= fallback_price:
    exit_price = bar["Close"]
```

Live logic:
```python
# only triggers if close itself crosses the level
elif not pos.hard_stop_armed and close <= pos.fallback_price:
    exit_reason = "fallback_20pct"
```

Same asymmetry applies to the BEARISH side (checks `close >= fallback_price`).

**Fix:** Change the condition to check `high` (BULLISH) / `low` (BEARISH) against
`fallback_price`, and exit at the bar close — matching backtest behavior.

---

## Missing Features

### G3 — Trade duration and peak move not tracked on `ActivePosition`

**Severity:** Low — useful for post-trade analysis and Slack notifications

Backtest tracks per-trade:
- `bars_held` / `mins_held` — how long the position was open
- `max_favorable_move` — peak profit magnitude reached during the trade

`ActivePosition` has none of these fields.

---

### G4 — No win/loss stats in daily trade summary

**Severity:** Low — nice-to-have for end-of-day Slack notification

Backtest computes and prints: win rate, EV/trade, avg win %, avg loss % across
all closed trades for the session. `PositionMonitor.print_status()` only lists
individual position rows with no aggregate stats.

---

## Config Inconsistencies

### G5 — Regime MA default mismatch

**Severity:** Medium — backtests and live runs produce different results unless
`--regime-ma` is passed explicitly

| Context | Default |
|---------|---------|
| `op_momentum_backtest.py` | `--regime-ma 5` |
| `config.py` (`REGIME_MA`) | `8` |
| All docs and findings | `8` |

**Fix:** Change the backtest default from 5 to 8 to match live config and
documented findings.

---

## Out of Scope (backtest-only, not needed in live)

- Monthly / P&L distribution reports — replay analytics only
- `--source yfinance` flag — live always uses Alpaca
- `held_to_close` / `success` flags — backtest stats only

---

## Replay vs Backtest Alignment (2026-04 audit)

The following bugs were found and fixed by replaying `2026-03-17` and comparing
the per-trade P&L line-by-line against the `op_momentum_selector_backtest.py` output
for the same date.  All nine bugs were resolved; per-share P&L now agrees exactly.

---

### ~~G6 — Look-ahead bias in rolling stats (date filter)~~ ✓ Fixed

**File:** `op_momentum_selector.py` `select_top_n()`
**Severity:** High — inflates rolling stats by including the target day's own result

The `rolling_stats` dict was built from `df[df["date"] <= target_date]`, including the
trade result for `target_date` itself — a trade that hasn't happened yet.

**Fix:** Changed filter to `df["date"] < target_date`.

---

### ~~G7 — `signal_bar_time` not captured when buffering~~ ✓ Fixed

**File:** `trade_engine.py` `_on_signal_for_window()`
**Severity:** High — first monitoring bar after the opening range was silently skipped

`entry_bar_time` was set to the bar that triggered the drain (the first post-OR bar),
not the bar the signal fired on (the last OR bar).  The position monitor skipped the
drain bar, so the very first post-OR bar was never evaluated for stops.

**Fix:** Added `signal_bar_time` field to `SignalEvent`; capture `latest_bar.name`
when buffering the signal, and use it as `entry_bar_time` in `_enter_position`.

---

### ~~G8 — `or_bar_lookback` not passed to `run_backtest` in selector~~ ✓ Fixed

**File:** `op_momentum_selector.py` `select_top_n()`
**Severity:** Medium — noisy OR days not filtered from rolling stats

`select_top_n` called `run_backtest` without forwarding `or_bar_lookback`, so days
with a tight OR relative to recent bars were counted in rolling stats even though
the backtest would have skipped them.

**Fix:** Forwarded `or_bar_lookback` to the `run_backtest` call.

---

### ~~G9 — Drain fires one bar too late in replay (buffer deadline)~~ ✓ Fixed

**File:** `trade_engine.py` `run_replay()` window-state setup
**Severity:** High — entry bar skipped entirely for every window in replay

The collection deadline was set to `or_close_et + SIGNAL_BUFFER_MINUTES`, causing
the drain to fire one bar after the OR closed.  The signal bar became the same bar
as the first monitoring bar, and the position monitor skipped it via the
`entry_bar_time` guard.

**Fix:** Set `deadline = or_close_et` in replay mode so the drain fires at the
first post-OR bar, matching the backtest's bar-by-bar evaluation order.

---

### ~~G10 — `regime_filter` not applied to rolling stats in selector~~ ✓ Fixed

**File:** `op_momentum_selector.py` `select_top_n()`
**Severity:** Medium — rolling stats differ from backtest; wrong tickers ranked

`select_top_n` called `run_backtest` without forwarding `regime_filter` / `regime_ma`,
so the rolling lookback stats were computed on unfiltered signals (bullish trades on
bearish QQQ days were included), giving different scores than the backtest.

**Fix:** Added `regime_filter` and `regime_ma` parameters to `select_top_n` and
forwarded them to the `run_backtest` call.

---

### ~~G11 — Regime dates cover only eval window in selector backtest~~ ✓ Fixed

**File:** `op_momentum_selector_backtest.py` `run_selector_backtest()`
**Severity:** Medium — rolling stats for the 60-day lookback lack regime filtering

`build_bearish_regime_dates` was called with `(eval_start, eval_end)`.  Dates in the
60-day lookback window before `eval_start` were never in `bearish_regime_dates`, so
bullish signals on bearish QQQ regime days in the lookback were counted in rolling
stats — unlike `select_top_n`, which calls `run_backtest` with the full lookback range.

**Fix:** Changed the call to `build_bearish_regime_dates(fetch_start, eval_end, ...)`.

---

### ~~G12 — Hard stop and fallback exit prices use bar close, not stop level~~ ✓ Fixed

**File:** `position_monitor.py` `_evaluate_stop()`, `_close_stock_position()`
**Severity:** Medium — simulated P&L differs from backtest for hard_stop and fallback exits

The backtest exits at the stop level (`hard_stop_price` for hard stops;
`fallback_price` for fallbacks — or bar close if the bar never reached the fallback
level on a BULLISH trade).  `_close_stock_position` always used the current bar close
as the simulated fill price.

**Fix:**
- Added `exit_stock_price_override` parameter to `_close_position` /
  `_close_stock_position`; the override is used as the simulated fill instead of
  the bar close.
- In `_evaluate_stop`, pass `pos.hard_stop_price` as override for `hard_stop` exits.
- Pass `pos.fallback_price` as override for `fallback_20pct` exits (BEARISH always;
  BULLISH when `bar_high >= fallback_price`, i.e., the bar traded through the level).
- Added `high` parameter to `_evaluate_stop` (extracted from `latest["High"]` in
  `on_bar`) to support the BULLISH fallback check.

---

### ~~G13 — Bearish stock P&L sign inverted in trade summary~~ ✓ Fixed

**File:** `position_monitor.py` `print_status()` and `print_summary()`
**Severity:** Medium — daily P&L total wrong for sessions with BEARISH stock trades

Both `_pnl` (in `print_status`) and `_position_pnl` (in `print_summary`) computed
`raw = exit - entry` for all positions.  For BEARISH stock trades (short selling),
profit comes from a falling price, so the correct formula is `entry - exit`.
Options are unaffected because both calls and puts are bought and the P&L is
always `exit_option_price - entry_option_price`.

**Fix:** Added `if pos.trade_type == "stock" and pos.signal == "BEARISH": raw = entry - exit`
branch to both helper functions.

---

### ~~G14 — Re-entry positions not armed at entry~~ ✓ Fixed

**File:** `trade_engine.py` `_enter_reentry()` → `_enter_position()`
**Severity:** High — re-entry hard stop never fires on the first post-entry bar

`ActivePosition` is created with `hard_stop_armed=False` by default.  For re-entry
positions the entry price is always on the favourable side of the stop level
(entry > midpoint for BULLISH reversal / re-entry; entry < midpoint for BEARISH),
so the stop should be armed from the moment of entry — exactly as the backtest comment
says: *"Entry is already above OR high > reversal_hard_stop, so armed at start."*

With `hard_stop_armed=False`, the monitor would only arm when close moved further
favourable *after* entry, then only exit on the *following* bar — causing the position
to survive a dip that the backtest would have stopped out.

**Fix:** Added `initial_hard_stop_armed: bool = False` to `_enter_position`,
`_enter_stock_position`, and `_enter_option_position`; `_enter_reentry` passes
`initial_hard_stop_armed=True`.

---

### ~~G15 — Re-entry callback executed asynchronously in replay~~ ✓ Fixed

**File:** `position_monitor.py` `on_bar()` / `_collect_fired_watchers()`
**Severity:** High — re-entry position created too late; early monitoring bars missed

`_check_reentry_watchers` spawned a `threading.Thread` for the re-entry callback.
In replay the main bar loop is synchronous, so the thread could execute during a
later bar — potentially several bars after the trigger.  The position was therefore
created too late, missing critical early bars (e.g., the hard-stop bar immediately
after a reversal entry).

Additionally, invoking the callback inside `self._lock` caused a deadlock risk,
since `_enter_position` calls `monitor.add_position()` which also acquires the lock.

**Fix:**
- Renamed `_check_reentry_watchers` to `_collect_fired_watchers`; it now only
  collects and removes fired watchers under the lock and returns them as a list.
- After releasing the lock, `on_bar` iterates the fired list and invokes the
  callback **synchronously** in replay mode (`is_replay_mode() == True`) or in a
  background thread in live mode.

---

### ~~G16 — Re-entry positions spawn further re-entry watchers (cascade)~~ ✓ Fixed

**File:** `position_monitor.py` `_maybe_create_reentry_watcher()`
**Severity:** Medium — extra trades not present in backtest inflate live P&L

When a re-entry position (reversal / bearish-reentry / bullish-reentry) closed, it
triggered `_maybe_create_reentry_watcher`, which could create yet another watcher.
This cascaded indefinitely — e.g., a reversal that hard-stopped would spawn a BRU
watcher, which would fire and enter another position not modelled by the backtest.

The backtest only allows one level of re-entry per primary trade.

**Fix:** Added an early return in `_maybe_create_reentry_watcher`:
```python
if pos.trailing_arm_price is not None:
    return  # re-entry positions do not spawn further watchers
```
`trailing_arm_price` is set for all re-entry positions and `None` for primary trades.
