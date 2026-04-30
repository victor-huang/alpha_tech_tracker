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

### ~~G17 — No cap P&L reporting in replay summary~~ ✓ Fixed

**Files:** `trade_engine.py`, `position_monitor.py`, `op_momentum_trade_engine.py`
**Severity:** Medium — no way to compare replay session returns to backtest percentages

The backtest prints `cap: +$X (+Y%)  portfolio: $Z` per day using fractional-share
P&L: `cap_pnl = (slot_capital / entry_price) × pnl_per_share`, where
`slot_capital = window_budget × (1/top_n)`.  The trade engine's `print_summary` only
showed raw dollar P&L and `% on $ deployed`.

**Fix:**
- Added `--capital` CLI flag (`replay_capital` on the engine) that sets the session
  starting capital used for both `window_budget` and the cap-% denominator.
- `_get_window_budget` returns `replay_capital × capital_fraction` in replay mode,
  so all windows (including sequential) receive a deterministic budget.
- `_enter_stock_position` computes `slot_capital = window_budget × (1/top_n)` (equal
  weight) or `window_budget × RANK_WEIGHTS[rank]` (rank-weighted), stored on each
  `ActivePosition`.
- `PositionMonitor.print_summary` gained a `%P&L` column per trade and a
  `cap: +$X (+Y%)` footer line matching the backtest's format.
- `PositionMonitor.__init__` gained `initial_capital` (used as the cap-% denominator).

---

### ~~G18 — Sequential windows use flat initial capital instead of prior window's return~~ ✓ Fixed

**Files:** `trade_engine.py`, `position_monitor.py`
**Severity:** Medium — A1/A2 `slot_capital` wrong; cap P&L diverges from backtest

The backtest's `_apply_capital_flow()` gives sequential windows all returned capital
from the prior window:
```
available_for_A1 = initial_capital + M1_cap_pnl
available_for_A2 = available_for_A1 + A1_cap_pnl
```
The trade engine assigned `replay_capital` (flat) as the budget for every window,
ignoring actual M1/A1 P&L.  In live mode, sequential windows queried the account
balance at drain time rather than constraining to prior-window proceeds.

**Fix:**
- Added `close_callback: Callable` to `PositionMonitor.__init__`; fires after each
  position closes (after the exit price is set).
- `OpMomentumTradeEngine` accumulates returned capital per window in
  `_window_returned: dict` via `_on_position_closed(pos)`:
  `returned = slot_capital + cap_pnl` for primary positions.
- `_get_window_budget` for sequential windows reads `_window_returned[prior_label]`
  plus the `slot_capital` of still-open primary positions in the prior window
  (estimated at cost basis), giving the full prior-window budget at drain time.
- Fallback (no prior-window positions at all): uses `replay_capital` (replay) or
  live account balance (live mode) — unchanged from previous behaviour.
- `_window_returned` resets at the start of each `run()` / `run_replay()` call.

---

### ~~G19 — Re-entry positions double-count capital in sequential window budget~~ ✓ Fixed

**File:** `trade_engine.py` `_on_position_closed()`
**Severity:** High — A1/A2 window budgets inflated when M1/A1 had re-entry trades

`_on_position_closed` added `slot_capital + cap_pnl` to `_window_returned` for
*every* closed position, including re-entries.  But re-entries share a capital slot
with their primary trade; they do not deploy new capital.

**Example** — top_n=2, one primary stops out and triggers a reversal:

| Position | Returned (buggy) | Returned (correct) |
|---|---|---|
| Primary 1 (slot=$5000, loss=-$250) | $4750 | $4750 |
| Reversal 1 (slot=$5000, gain=+$294) | $5294 | $294 (cap_pnl only) |
| Primary 2 (slot=$5000, gain=+$375) | $5375 | $5375 |
| **Total `_window_returned["M1"]`** | **$15419** | **$10419** |
| Backtest `available` | $10419 | $10419 ✓ |

The inflated budget caused A1/A2 positions to receive oversized `slot_capital`,
inflating their cap P&L in the summary.

**Fix:**
- In `_on_position_closed`, re-entry positions (`trailing_arm_price is not None`)
  add only `cap_pnl` (no principal) to `_window_returned`.
- In `_get_window_budget`'s still-open estimate, re-entry positions are excluded
  from the slot_capital sum for the same reason.

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

---

## Production Readiness Gaps (2026-04-11 review)

The gaps below were identified by a full read of `trade_engine.py`, `position_monitor.py`,
`order_executor.py`, `signal_engine.py`, and `config.py` against the strategy's confirmed
best parameters.

---

### ~~G20 — Entry fill price never populated during the session (quick-exit broken)~~ ✓ Fixed

**File:** `position_monitor.py:42-56`, `_monitor_loop` in `trade_engine.py`
**Severity:** High — quick-exit protection is silently disabled in live mode

`_quick_exit_entry_price()` returns `None` when `pos.entry_fill_price is None`.
`entry_fill_price` starts `None` and is only populated by `_refresh_fill_prices()`,
which runs exclusively in the EOD polling phase (`eod_triggered` block in
`_monitor_loop`). During normal trading hours `entry_fill_price` is always `None`,
so every call to `_quick_exit_entry_price()` returns `None` — the step-0 "try
entry price first" protection never fires in live mode.

**Fix:** After `_place_entry()` / `place_stock_order()` returns the order dict,
poll `client.order_status(order_id)` in a short retry loop (e.g., 3 × 5s) and
set `pos.entry_fill_price` before handing the position off to the monitor.

---

### ~~G21 — `bars_held` inflates from polling — breaks reversal/re-entry bar gate~~ ✓ Fixed

**File:** `position_monitor.py` `_evaluate_stop()` / `on_bar()`
**Severity:** Medium (only affects `--enable-reversal` / `--enable-bearish-reentry`)

`_monitor_loop` calls `on_bar()` for all tickers every 30 seconds, but
`get_latest_bar()` returns the same bar until a new 5-min bar arrives. Each poll
increments `pos.bars_held` when no exit fires. A position stopped out after 1 real
bar has `bars_held ≈ 10` (10 polls × 30s ≈ 5 min). With the default
`reversal_max_bars=3`, positions held for 1–3 real bars may not get a reversal
watcher because `bars_held` already exceeds 3 by the time the exit fires.

**Fix:** Added `last_evaluated_bar_time: Optional[datetime] = None` to `ActivePosition`.
In `_evaluate_stop`, skip the increment if `bar_time == pos.last_evaluated_bar_time`;
otherwise update `last_evaluated_bar_time` and increment `bars_held`. Repeated 30s
polls of the same 5-min bar are no-ops.

---

### G22 — `MAX_ACTIVE_SYMBOLS = 2` in config.py conflicts with best-parameter top-3

**File:** `config.py:24`
**Severity:** Medium — running without `--top 3` silently uses top-2, a worse config

All 5-year backtests are validated at top-3 (+56pp over top-5). `OpMomentumTradeEngine`
defaults `top_n` to `MAX_ACTIVE_SYMBOLS = 2`. A live session started without
`--top 3` quietly runs with 2 slots, deploying less capital per day.

**Decision: Won't Fix** — `MAX_ACTIVE_SYMBOLS = 2` is intentional for live trading. Top-2
has been tested and produces good results; the extra capital concentration reduces the
number of simultaneous positions to manage and is the current live operating standard.
Always pass `--top 3` explicitly if running the top-3 backtest configuration.

---

### ~~G23 — No position reconciliation on startup (crash recovery)~~ ✓ Fixed

**File:** `trade_engine.py` `run()`
**Severity:** High — crash-restart leaves open broker positions unmonitored

On startup `run()` fetches account buying power but never queries the broker for
existing open positions. If the engine crashes mid-session and restarts, any
already-filled entries are invisible to the new `PositionMonitor` and will go
unmonitored until the market closes (no stop, no EOD close from the engine).

**Fix:** Added `_recover_session()` called at the top of `run()`. It calls
`client.get_open_positions()`, reconstructs `ActivePosition` objects for any open
positions, adds them to the `PositionMonitor`, and logs a loud `WARNING` for each
reconciled position. `_rebuild_window_returned()` accumulates the cost basis into
`_window_returned` so sequential window budgets remain correct after a restart.

---

### ~~G24 — No account-level daily max-loss circuit breaker~~ ✓ Fixed

**Severity:** Medium — per-trade `max_loss_pct` does not protect the account overall

`--max-loss-pct` caps loss on individual positions. If multiple positions each hit
max-loss back-to-back in a bad market, the engine keeps opening new trades. A daily
P&L floor (e.g., halt if account drops 3% from opening balance) is standard practice
for live algo trading and would prevent runaway losses on volatile days.

**Fix:** Added `--daily-max-loss USD` CLI flag (maps to `DAILY_MAX_LOSS_USD` config constant).
`_daily_realized_pnl` accumulates closed-position P&L in `_rebuild_window_returned()`
(covers both live close and crash-recovery paths). `_is_circuit_breaker_tripped()` returns
`True` when `_daily_realized_pnl <= -daily_max_loss_usd`. The breaker gates both
`_on_signal_for_window` (immediate signal) and `_drain_pending_signals_for_window`
(buffered signals). P&L resets to zero at the start of each `run()` / `run_replay()` call.

---

### ~~G25 — No WebSocket reconnect watchdog~~ ✓ Fixed

**File:** `signal_engine.py` `start()` / `trade_engine.py` `_monitor_loop`
**Severity:** Medium — stream drop is silent; engine continues polling stale bars

If `StockDataStream` drops and the SDK's internal reconnect fails (or the thread
dies from an unhandled exception in `_handle_bar`), `get_latest_bar()` keeps
returning the last known bar. The monitor loop continues evaluating stops against
stale data; no new signals fire; no alert is raised.

**Fix:** Added `--ws-reconnect-timeout SECONDS` CLI flag (default 600s, maps to
`WS_RECONNECT_TIMEOUT_SECONDS`). `_handle_bar()` now updates `_last_bar_received_at`;
`start()` sets `_stream_started_at`. `_check_ws_health(now)` in `_monitor_loop`
compares `now` against the later of the two timestamps; if the gap exceeds the timeout
it calls `signal_engine.reconnect()`. `reconnect()` stops the old stream, creates a new
`StockDataStream`, resubscribes, starts a new daemon thread, resets `_last_bar_received_at`
to `None`, and preserves `_history` so no re-warmup is needed.

---

### ~~G26 — `print()` in `run()` bypasses log file~~ ✓ Fixed

**File:** `trade_engine.py`
**Severity:** Low — pre-market output missing from `logs/op_momentum_YYYY-MM-DD.log`

Three `print(f"...")` calls in `run()` and `run_replay()` write to stdout only.
In daemon mode (no terminal) these lines are silently dropped.

**Fix:** Replaced all four `print()` calls in `run()` and `run_replay()` with `logger.info()`.

---

### ~~G27 — No market holiday detection~~ ✓ Fixed

**Severity:** Low — engine idles silently on holidays

If started on a US market holiday, the engine subscribes to the WebSocket and waits
for OR bars that never arrive. The TickerSelector falls back to the prior trading day,
so picks are computed, but no signals ever fire. No alert is sent.

**Fix:** Added weekend (`weekday() >= 5`) and NYSE holiday checks at the top of `run()`
using the existing `_is_nyse_holiday()` from `contract_selector.py` (backed by
`_NYSEHolidayCalendar` with 7 NYSE rules). When a non-trading day is detected, the engine
logs a `WARNING` and returns immediately. The guard is skipped when
`_mock_trade_execution` is `True` so replay and test mode are unaffected.

---

### ~~G28 — Replay uses options P&L; backtest uses stock-price surrogate~~ ✓ Fixed

**File:** `op_momentum_trade_engine.py` → `_parse_args_and_run()`
**Severity:** High — options P&L is 5–10× the backtest equivalent; replay results were not comparable

The live engine defaulted to `trade_type="options"` for all runs including replay. In
replay mode the engine should match the backtest, which uses stock price movement as a
surrogate (no options chain lookup). Running with `trade_type="options"` amplified every
trade's P&L by the contract leverage factor, making replay totals incomparable to backtest.

**Fix (2026-04-26):** After the `is_replay` flag is set (determined by `--replay-date`
or `--replay-start`/`--replay-end`), `args.trade_type` is forced to `"stock"` — mirroring
how `mock_trade_execution` is forced for replay. Live mode is unaffected.

```python
is_replay = bool(args.replay_date) or bool(args.replay_start and args.replay_end)
mock_trade_execution = args.mock_trade_execution or is_replay
if is_replay:
    args.trade_type = "stock"
```

---

### ~~G29 — BRE/BRU/REV sub-trade timing ignored in sequential window capital flow~~ ✓ Fixed

**Files:** `op_momentum_backtest.py`, `op_momentum_selector_backtest.py`
**Severity:** Medium — sequential window (A1/A2) over-allocated capital on days where a sub-trade ran past the drain time

`_apply_capital_flow()` computed each slot's return time using only `bars_held` from the
primary trade. A BRE/BRU/REV sub-trade that fires *after* the primary exits — and runs
into the afternoon — kept the slot locked in the replay engine, but the backtest saw only
the primary exit time and incorrectly freed the slot before the sequential window opened.

**Example (4/23, COIN BEARISH → BRE):**
- Primary exits at 9:45 (bars_held=0, fallback). BRE enters at 9:50 and exits at 11:25.
- At A1 drain (10:05), the replay correctly withheld COIN's $4,000 slot.
- Backtest previously gave A1 the full $10k budget because COIN's exit_time (9:45) was
  before the drain.

**Fix (2026-04-26):**
1. `op_momentum_backtest.py`: added `"entry_idx"` to BRE, BRU, and REV row dicts so the
   lag between primary exit and sub-trade entry is available downstream.
2. `op_momentum_selector_backtest.py`: compute `slot_exit_bars` per trade row as
   `max(primary_bars_held, br_exit_bars, bru_exit_bars, rev_exit_bars)` where
   `sub_exit = primary_bars + 1 + entry_idx + 1 + sub_bars_held`.
3. `_apply_capital_flow()`: uses `slot_exit_bars` instead of `bars_held` for the
   exit_time calculation.

**Result:** BT total for 4/23 moved from -$153 to -$159 (closer to replay -$136). COIN's
slot is now correctly deducted from A1's budget.

---

### ~~G35 — Sequential window enters positions when budget is zero~~ ✓ Fixed

**File:** `trade_engine.py` `_drain_pending_signals_for_window()`
**Severity:** High — real cash deployed with $0 tracked slot capital

When all M1 capital is locked in open BRE re-entries, `_get_window_budget` returns $0
for A1. `PositionSizer.compute()` has a `max(1, int(budget / mid / 100))` floor that
forces 1 contract regardless, causing positions to be entered with `slot_capital=0`.

Observed 2026-04-29: A1 entered FN ($8,020) and CLS ($3,210) with `budget=0.0`; each
also spawned BRE watchers that re-entered again. Total over-deployment: ~$11k from $0
tracked budget.

**Fix:** In `_drain_pending_signals_for_window`, return early if `window_budget is not
None and window_budget <= 0`.

---

### G30 — FN bar-boundary ambiguity at sequential window drain (Won't Fix)

**Files:** `op_momentum_selector_backtest.py` → `_apply_capital_flow()`
**Severity:** Low — manifests only when a primary trade exits on the same bar the sequential window opens; ~$4k impact on 4/23 A1 budget

The backtest uses a bar's **open time** as the exit timestamp
(`exit_time = prior_drain + bars_held × 5`). A sequential window's drain equals
`opening_start + opening_bars × 5`. When a primary trade's exit_time exactly equals the
drain time (i.e., the bar closes at the same moment the window opens), the backtest treats
the slot as returned — but the replay engine closes the position at bar *close*, which is
simultaneous with the window firing and is treated as still-open.

**Example (4/23, FN, A1 at 10:00/1 bar):**
- M1 drain = 9:45 (585 min). FN exit_time = 585 + 3×5 = 600 (10:00).
- A1 drain = 10:00 + 1×5 = 605 (10:05). Condition 600 ≤ 605 → True.
- Backtest: FN slot returned before A1 fires → A1 budget includes FN's $6k slot.
- Replay: FN exits at bar close = 10:05, simultaneous with A1 firing → slot withheld.
- Result: A1 window_capital = $5,979 (BT) vs $1,965 (RP), ~$4k gap.

**Why accepted as-is:** 5-minute bar granularity makes sub-bar exit timing ambiguous. The
backtest interpretation (capital free once the stop fires within the bar) is arguably more
correct for recycling purposes. Fixing it would require sub-bar exit timestamps not
currently tracked. The ambiguity only manifests when a sequential window opens within one
bar of a primary exit — most pronounced for early windows (A1 at 10:00 with M1 3-bar OR)
and negligible for standard afternoon windows (A1 at 13:15, A2 at 15:00).
