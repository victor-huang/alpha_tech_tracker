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

Already fixed in the codebase — `reconnect()` resets both `_stream_started_at = _now_et()` and
`_last_bar_received_at = None`. The 2026-04-28 large elapsed log (17927s) was from the first-ever
watchdog trigger since startup (correct behavior); subsequent ticks after reconnect use the reset
timestamp. Five tests in `TestWsWatchdog` cover this behavior.

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

## ~~G34 — `print_status()` closed-position block shows `x0` contracts~~ ✓ Fixed

**File:** `position_monitor.py` `print_status()`
**Severity:** Low — misleading intraday status prints; no money impact

`print_status()` used `p.contracts` for both qty string and the `_pnl()` multiplier. After a
live close `p.contracts` reaches 0, so every closed position showed `x0` and `+$0.00` for the
rest of the trading day.

Observed 2026-04-28: every `POSITION STATUS` print showed `EXPE … x0 … +$0.00` and
`RH … x0 … +$0.00` even though both were fully closed and profitable.

**Fix (commit 76fb295):** Extracted `_effective_contracts()` to module level (was a local inside
`print_summary()`). Applied it to `qty_str` and to the `_pnl()` contracts multiplier in the
`print_status()` closed-position block.

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

---

## G41 — Post-RECOVER count-based slot check allows re-entry when DD already consumed all capital

**File:** `trade_engine.py` `_recover_session()` / `_drain_pending_signals_for_window()`
**Severity:** High — live engine can deploy up to 2× the window budget after a TS stream reconnect

After a TradeStation stream RECOVER, `_recover_session()` reconstructs open positions from the
broker. When a DD add-on is active, only the surviving primary position is visible to the broker
(the loser has already exited); position count is therefore **1**, not 2. The max-positions gate
(`open_position_count < max_positions`) sees 1 < 2 and treats the window as having a free slot.
If the catchup bar injection replays the opening-range signals, the engine enters up to 2 new
positions using fresh budget — even though the DD add-on already consumed all window capital.

**Observed 2026-05-04 (stock log, M1 window):**
- 09:45 ET: CRWV primary $12k (rank-0) + SNDK $8k (rank-1) entered. M1 fully deployed.
- 09:51 ET: SNDK exits. DD fires → CRWV add-on $7,962. M1 still ~$20k. Position count: **1**.
- 11:43 ET: TS stream drops. Engine RECOVERs, re-runs OR catchup.
- 11:44 ET: Catchup sees 1 open M1 position, 1 free slot. Enters CVNA $12k + AMD $8k.
- Result: M1 deployed $39,890 against a $20k budget.

**Root cause:** `_rebuild_window_returned()` uses `pos.slot_capital` for the recovered position
but has no knowledge of DD add-on capital that was already consumed (the add-on position itself
is gone). The effective remaining budget is therefore overstated by the add-on amount (~$8k),
and the count-based gate is not a safe backup because DD drops count from 2 → 1.

**Fix:** `_rebuild_window_returned()` must account for DD add-on capital. One approach:
persist a `window_dd_deployed` field on `_window_state` that is checkpointed to disk and
restored on RECOVER — so the remaining-budget calculation is:
`remaining = initial_budget - recovered_slot_capital - window_dd_deployed`.
Alternatively, check `remaining_budget <= 0` as an explicit gate in
`_drain_pending_signals_for_window` before entering any post-RECOVER position.

---

## ~~G42 — Step3 market-order fallback credited a fill that never happened~~ ✓ Fixed

**File:** `order_executor.py` `place_stock_order()` step3 / `trade_engine.py` `_poll_entry_fill()`
**Severity:** High — phantom position tracked with garbage P&L, false trade alert sent, capital slot stuck

Two compounding defects, both in the step3 (final market-order) fallback path:

1. `_poll_entry_fill()` accepted `filled_avg_price=0.0` as a confirmed fill since `0.0 is not
   None` — a market order can briefly report `status="filled"` with a zero price before the
   broker populates the real one.
2. `place_stock_order()`'s step3 blindly credited `total_filled_qty` with the full requested
   share count regardless of whether the market order actually filled, and `_enter_position`
   trusts `total_filled_qty` over the separately-polled real fill status.

**Observed 2026-08-13 (options log, AMD/CRWD):** both entries escalated to step3, got a bogus
$0.00 fill logged as confirmed, and were silently dropped from the DAILY TRADE SUMMARY when
QTY-sync couldn't reconcile them (~$15,500 capital, P&L unknown).

**Observed 2026-08-17 (options log, RDDT DD add-on) — worse manifestation, defect #2 only
(fix #1 was already live):** step3 market order was declared "canceled with 0 fills — entry
failed," but `Tracking position` was logged on the very next line anyway, because
`total_filled_qty` (blindly credited) didn't match the correctly-polled 0 fill. The phantom
position persisted ~3 hours with garbage unrealized P&L (-$6,100 to -$6,266) and a false
"[DD] ADD-ON RDDT" Telegram alert, before a hard-stop fired a real BUY_COVER that happened to
net out the real share count by coincidence. The DAILY TRADE SUMMARY still shows a fake
~$6,267 "loss" for that leg — see `guides/LIVE_PNL_CALCULATION_GUIDE.md` for the broker-truth
reconciliation.

**Fix (commits `580667b`, `e88bdd9`):** `_poll_entry_fill()` now requires a positive fill price
before accepting a fill as confirmed. `place_stock_order()`'s step3 now polls `order_status` up
to 3 times after the market order and credits `total_filled_qty` with only what the broker
actually confirms, instead of assuming a full fill.

---

## G43 — QTY-sync reconciliation drops P&L when closing fill price can't be located

**File:** `position_monitor.py` (QTY SYNC reconciliation path)
**Severity:** High — real P&L silently missing from DAILY TRADE SUMMARY, confirmed recurring

When the periodic broker-qty reconciliation finds a position closed at the broker (native stop,
or a fill racing the engine's own poll) and can't locate the closing fill price, it logs
`"fill price not found — P&L not recorded"` and drops the leg entirely rather than recording it
with an estimated price or flagging it prominently.

**Observed 2026-08-18:** 6 occurrences across both engines in one day — CRDO (stock engine, 4
separate partial reconciliations across all 3 windows) and RDDT/CRWD (options engine). CRDO
alone shorted 153 shares across the day; the DAILY TRADE SUMMARY only shows 65 shares worth of
`manual_close` rows — the bulk of that day's real P&L is unaccounted for in the summary (real
broker P&L was ultimately recovered via `guides/LIVE_PNL_CALCULATION_GUIDE.md`'s
activity-based reconstruction: +$453.30 for CRDO that day, vs. the log's reported +$303.00 /
+$679.43 capital-based estimate — neither matched).

**Fix (not yet implemented):** either backfill the closing price from broker order/activity
history at reconciliation time (the same technique `fetch_broker_pnl.py` uses), or at minimum
surface these drops prominently in the DAILY TRADE SUMMARY (not just a buried WARNING log line)
so P&L totals are never silently understated.
