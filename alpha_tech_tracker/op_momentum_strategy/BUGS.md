# Bug Tracker — op_momentum_strategy

Open bugs in the live trading engine. Fixed bugs are kept with a ~~strikethrough~~ ✓ Fixed marker.

Severity legend: **High** = money impact or missed trades | **Medium** = delayed exit or misleading logs | **Low** = display/cosmetic only

---

## G2 — Fallback exit checks `close`, backtest checks intrabar `high`

**File:** `position_monitor.py` lines 108, 135
**Severity:** Medium — live fallback exits fire later/at a worse price than backtest

Backtest exits at bar close when the bar's `high` (BULLISH) or `low` (BEARISH) touched the
fallback level. Live engine only triggers when `close` itself crosses the level — meaning bars
that trade through the level intrabar but close on the safe side are missed entirely.

**Fix:** Change the condition to check `high` (BULLISH) / `low` (BEARISH) against `fallback_price`;
exit at bar close — matching backtest behavior.

---

## ~~G31 — Partial tranche fill P&L lost when MISS triggers retry~~ ✓ Fixed

**File:** `position_monitor.py` `_close_option_position()`
**Severity:** High — P&L underreported by tranche-1 contracts whenever a tranche-2 MISS triggers a retry

`_close_option_position` previously set `pos.closed_contracts = pos.contracts` before calling
`place_option_order_in_tranches`. On retry, `pos.contracts` had already been decremented to the
remaining count (1), so the assignment overwrote the tranche-1 fill count (2) with 1. The final
`effective_contracts` was 1 and P&L was calculated for 1 contract only.

Observed 2026-04-28: EXPE 3 contracts. Final summary showed qty=1 and P&L=+$210 instead of qty=3 and P&L=+$630.

**Fix (commit cd50fe5):** Removed the upfront `pos.closed_contracts = pos.contracts` assignment.
Added `pos.closed_contracts += filled` after the tranche call so each retry accumulates its fill
into the running total rather than resetting it.

---

## G32 — Watchdog logs misleadingly large elapsed time after reconnect

**File:** `signal_engine.py` `reconnect()`
**Severity:** Medium — misleading log; reconnect fires correctly but elapsed-time figure shows engine uptime not gap since last bar

`reconnect()` resets `_last_bar_received_at = None` but does not update `_stream_started_at`.
After reconnect the watchdog falls back to `_stream_started_at` (engine startup time) when
computing elapsed, producing logs like "no bar received for 17927s" — the full engine uptime —
instead of the actual gap since the reconnect.

Observed 2026-04-28: both engines logged ~17927s / 17627s at 13:30 ET, matching seconds since
startup, not since the reconnect.

**Fix:** In `signal_engine.reconnect()`, reset `_stream_started_at = _now_et()` after clearing
`_last_bar_received_at`.

---

## G33 — FILL_ESC step3 fair-price floor not decayed on retry attempts

**File:** `order_executor.py` `fill_esc_place_option_order()`
**Severity:** Medium — close order stuck for 2+ minutes when fair_price is materially above bid, extending risk exposure

Step3 floors the sell limit at `max(bid, fair_price)`. When `bid << fair_price` (e.g. bid=$18.80,
fair=$20.05), the limit sits $1.25 above market and cannot fill. `_retry_close_position` calls
`_close_position` again — which recomputes the same `fair_price` from the stale cache —
repeating the same stuck limit for every retry cycle.

Observed 2026-04-28: EXPE retry ran steps 1–8 (~2 min) all at the fair-price floor while bid
sat at 18.70–18.80. Position only filled because the market recovered.

**Fix:** Pass a `retry_attempt` counter to `fill_esc_place_option_order`. Decay the floor
progressively (e.g. shrink by 25% of bid-gap per retry), floored at the market bid:

```python
gap = fair - bid
floor = fair - retry_attempt * 0.25 * gap
step3_price = max(bid, floor)
```

---

## G34 — `print_status()` closed-position block shows `x0` contracts

**File:** `position_monitor.py` line 1360
**Severity:** Low — misleading intraday status prints; no money impact

`print_status()` formats closed-position quantity as `f"x{p.contracts}"`. `p.contracts` tracks
remaining unfilled contracts and reaches 0 when fully closed. `print_summary()` correctly uses
`_effective_contracts(p)` (returns `closed_contracts` when non-zero), but `print_status()` does
not.

Additionally `p.exit_fill_price` may still be `None` during async fill polling, so `_pnl()`
returns `None` → the P&L column shows `+$0.00` for all closed positions in every interim status
print.

Observed 2026-04-28: every `POSITION STATUS` print showed `EXPE … x0 … +$0.00` and
`RH … x0 … +$0.00` even though both were fully closed and profitable.

**Fix:** In `print_status()` closed-position block, use `_effective_contracts(p)` for quantity:

```python
# before
qty_str = f"x{p.contracts}"

# after
qty_str = f"x{_effective_contracts(p)}"
```

---

## ~~G36 — `ask=0` stale stock quote causes mid-price to halve~~ ✓ Fixed

**File:** `models.py` `_stock_bid_ask()`
**Severity:** High — exit limit placed at ~50% of fair value; escalation steps all start from wrong baseline, causing MISS and market-order fallback

When the WebSocket delivers a snapshot with `ask=0` (staleness artifact), `mid = (bid + 0) / 2 = bid / 2`.
FILL_ESC step1 places a limit at this price, which is far below market and will never fill.

Observed 2026-04-29 stock log: `EXIT STOCK QUOTE FN: bid=620.0 ask=0.0 mid=310.00` — $310 mid
on a ~$630 stock.

**Fix (commit cb1a6c3):** Guard `ask == 0` in `_stock_bid_ask()`. When ask is zero, return `bid`
for both values so callers compute `mid = bid` instead of `bid / 2`.

---

## ~~G37 — BRE/BRU re-entry positions missing EntryFill/ExitFill in DAILY TRADE SUMMARY~~ ✓ Fixed

**File:** `position_monitor.py` `_close_stock_position()`
**Severity:** Medium — daily P&L total understated; re-entry trade rows show `—` for all fill prices and P&L

Stock PRE-CLOSE SYNC path returned early without fetching the exit fill price when
a position had been manually closed at the broker. `print_summary()` then called
`_position_pnl(pos, entry, None)` → returned `None` → all display columns including
`entry_str` were replaced with `"—"`.

The options path (`_close_option_position`) already called `_fetch_manual_close_fill_price()`
before the early return; the stock path was missing the same call.

Observed 2026-04-29 stock log DAILY TRADE SUMMARY:
- `COIN [Bearish Cont.] 67sh  10:11 → 15:55  hard_stop   — / — = —`
- `APP [Bearish Cont.]  18sh  10:12 → 14:56  hard_stop   — / — = —`
- `FN [Bearish Cont.]    1sh  12:32 → 14:04  trailing_stop_ma20  — / — = —`

**Fix (commit 519f342):** In `_close_stock_position` manual-close early-return path,
call `_fetch_manual_close_fill_price(pos)` and assign result to `pos.exit_fill_price`
before returning — matching the existing options path.

---

## ~~G38 — DD + re-entry watcher double-spend of freed slot capital~~ ✓ Fixed

**File:** `trade_engine.py` `_check_doubledown_for_window()`
**Severity:** High — intra-window capital deployed twice from the same freed slot

When a position closes via hard_stop or fallback, two things happen simultaneously:
1. A BRE/reversal watcher is created storing `window_budget` = the original full window budget
2. When DD fires at its check time, it claims the freed slot capital for the survivor add-on

If the watcher fires *after* DD, `_enter_reentry` computes `slot_capital = watcher.window_budget × rank_weight` using the stale original budget — the same freed capital DD already redeployed.

Observed 2026-04-29: CRDO (rank=1) closed via fallback in A2 → BRE watcher created → DD fired
and consumed CRDO's freed ~$7,968 for SNDK add-on → CRDO BRE watcher fired and deployed another
$7,943. Peak simultaneous: $27,275 against a $19,933 budget ($7,342 overrun).

**Fix (commit 24ba321):** In `_check_doubledown_for_window`, after confirming DD will fire
(`freed_capital > 0`), cancel all re-entry watchers in the same window whose ticker matches a
stopout position — before deducting from `_window_returned` or entering the DD position.
