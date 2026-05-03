# Retrospective — April / May 2026

Combined retrospective covering the full April–May 2026 development cycle.
Includes all bugs found and fixed in both months, with a unified pitfalls checklist
and design pattern catalogue distilled from the full body of work.

Individual source docs: `RETRO_APRIL_2026.md` (detailed write-ups for April bugs 1–10),
BUGS.md (G31–G38 live engine bugs).

---

## Bugs Fixed — April 2026

### A1 — Lookahead Bias in Regime Filter

The regime filter gated same-day signals using same-day QQQ close — data not available
at 9:45 AM signal time. The entire +16pp attributed to `--regime-filter` came from this
lookahead. Fix: shift the set of bearish dates forward by +1 business day (action date,
not signal date). Result eliminated all observed edge; filter is now optional and opt-in.

**Root cause:** "Signal date" vs "action date" conflated. The date QQQ was bearish
is not the date you can act on that information.

### A2 — Reversal vs BRE Priority: Exhaustive Scan vs First-Trigger

Backtest decided reversal vs BRE by exhaustive lookahead (scan ALL bars; try reversal
first; fall back to BRE if reversal never fires). Live engine: bar-by-bar, first trigger
wins. On days where BRE fired earlier than reversal, backtest picked reversal, live
engine picked BRE — different trades, different P&L.

**Root cause:** BRE was bolted on as an `else` branch after the reversal scan existed,
without updating the priority logic to match the live engine.

**Fix:** Compare `rev_entry_idx` vs `bre_entry_idx`; smaller index wins. Cancel the
losing entry before simulating.

### A3 — Sibling Watcher Cleanup Scoped Too Broadly

`_collect_fired_watchers` removed all watchers for a ticker when any one fired. When
A1's reversal watcher fired, M1's BRE watcher (a sibling of a different primary exit)
was silently dropped and could never fire.

**Root cause:** Cleanup key was just `ticker`. Multiple windows trading the same ticker
create independent watcher groups with the same ticker but different primary exits.

**Fix:** Add `primary_exit_bar_time` to each watcher. Cleanup removes only watchers
sharing both `ticker` and `primary_exit_bar_time`.

### A4 — Trailing Arm State Not Latched

`_trailing_armed()` re-evaluated the arm threshold on every bar. If price retreated
below the arm threshold after briefly crossing it, the MA trailing stop was silently
disarmed. Backtest used a persistent `bru_trailing_armed` boolean that never resets.

**Root cause:** Stateless query instead of latched state. "Was price ever above X?" is
different from "Is price above X right now?"

**Fix:** Add `trailing_arm_reached: bool` to `ActivePosition`. Latch to True on first
crossing; never clear it.

### A5 — Cache Stitch Seed from First Piece Instead of Request Start

`_stitch_cache` seeded `covered_end` from `pieces[0][0] - 1 day` (first piece start)
instead of `start_date - 1 day` (request start). A cache file covering Jul–Dec was
accepted as covering Jan–Dec, and the stitcher wrote a corrupt "Jan–Dec" file.

**Root cause:** Coverage validation started from the first available piece, not from
the actual request boundary.

**Fix:** Seed `covered_end = start_date - timedelta(days=1)`.

### A6 — Cache Parallel Race: Partial Writes and FileNotFoundError Crashes

Concurrent backtest processes produced two failures: (1) partial JSON writes when one
process wrote while another read; (2) `FileNotFoundError` when a file was evicted
between directory scan and `open()`.

**Fix:** Atomic writes via tmp-then-rename; tolerate `FileNotFoundError` on read and
unlink.

### A7 — IEX and SIP Feeds Share the Same Cache Key

Switching from IEX to SIP still returned IEX-cached data because the cache filename
encoded only `"alpaca"` as the source, not the feed variant.

**Root cause:** Adding a new data dimension (feed) without updating the cache key.

**Fix:** Encode feed in filename: `alpaca_sip_5min_...` vs `alpaca_iex_5min_...`.

### A8 — Success Flag Mismatch After Adding Re-Entry P&L

`success` flag was computed from primary P&L only; `pnl_pct` included reversal/re-entry.
A trade that lost on primary but won on reversal (net positive) was counted as a loss,
inflating loss rate and corrupting rolling scorer stats.

**Root cause:** `success` was written before re-entry logic existed; not updated when
combined P&L was added.

**Fix:** `"success": combined_pnl_pct > 0` — must match the `pnl_pct` field in the
same row.

### A9 — Sparse Ticker: Zero OR Range Fires False BEARISH Signal

For illiquid tickers with no bars during the OR window, `or_range = 0` and
`close <= or_low + 20% × 0` is trivially true — a false BEARISH fired.

**Root cause:** No guard against `or_range == 0` before evaluating signal conditions.

**Fix:** Synthesize flat bars for silent periods; guard `or_range == 0` in signal
evaluation.

### A10 — Wrong Option Tick Size (Non-Penny-Pilot Schedule)

`_quantize_option_price` used the non-Penny-Pilot schedule ($0.05/$0.10). All pool
tickers are Penny Pilot ($0.01/$0.05). Orders were placed at suboptimal prices; some
were rejected at the exchange.

**Fix:** Use Penny Pilot schedule for all pool tickers. Document non-pilot tickers
(`CRDO`, `RH`, `FN`, `CLS`, `APP`) in `_NON_PENNY_PILOT_TICKERS`.

---

## Bugs Fixed — May 2026

### M1 — Pre-Armed Re-Entry Positions Bypassed Trailing Arm Gate

BRE positions start with `initial_hard_stop_armed=True`. `_trailing_armed()` checked
only `trailing_arm_reached` (price reaching a full OR-range below entry) — which was
never true for CVNA on 4/30 (price never fell that far). The MA trailing stop never
fired; the position held 4.5 hours to a ~$816 loss.

**Root cause:** The MA gate checked the trailing arm threshold but ignored the
pre-armed state. Multiple stop mechanisms with separate gate conditions — each gate
must handle the pre-armed case independently.

**Fix:** Add `if pos.hard_stop_armed: return True` as the first check in
`_trailing_armed()`. Pre-armed positions always have the MA stop available.

### M2 — MA Trailing Stop Threshold Wrong for BRE vs Primary Bearish

Backtest: primary BEARISH uses `ma20 < or_low`; BRE uses `ma20 < midpoint`. Initial
live engine fix applied `midpoint` to all bearish positions — diverging from backtest
for primary entries.

**Root cause:** Fix was written from the BRE case and applied universally, without
checking the backtest for each position type separately.

**Fix:** Compute `_bearish_ma_threshold` conditioned on `pos.trailing_arm_price is
not None` (BRE → midpoint; primary → or_low). Applied to both MA20 and MA50 checks.

### M3 — Mid-Price Fallback Misreported Capital Returned to Window

When broker order history lagged, `_fetch_manual_close_fill_price()` returned the
current option mid-price as a best estimate. This estimate flowed into `exit_fill_price`
and the window budget — wrong capital for the next sequential window.

**Root cause:** Estimate used in place of confirmed fill in capital-critical accounting.

**Fix:** Return `None` when no confirmed fill. Set `close_order_reconciled=True` (stops
FILL_ESC) and keep `close_order_failed=True` (retry next cycle). Capital held until
real fill confirmed.

### M4 — DD + Re-Entry Watcher Double-Spend of Freed Slot Capital (G38)

When a position stopped out, both a re-entry watcher and DD claimed the freed slot
capital. The watcher stored the original window budget; DD deployed the freed capital
for the survivor add-on. If the watcher fired after DD, it sized from the stale budget
and double-deployed the same capital. Observed 2026-04-29: $7,342 overrun.

**Root cause:** No mutual exclusion between two capital consumers for the same freed slot.

**Fix:** Cancel re-entry watchers for stopout tickers (scoped by `window_label, ticker`)
before entering the DD add-on.

### M5 — Sequential Window Capital Gate Treated "Opened" as Permanent Block

`_enter_reentry` blocked all re-entries once the next sequential window had opened, even
when that window had already returned all capital. Valid re-entry opportunities were
silently dropped.

**Root cause:** Gate tracked "opened/not-opened" — not the lifecycle phase
(deployed vs returned).

**Fix (bf80a14):** Inspect `_monitor._positions` for open positions in the next window.
If none are open, allow the re-entry with a freshly computed budget.

### M6 — Partial Fill Accumulation Reset on Retry (G31)

`_close_option_position` set `pos.closed_contracts = pos.contracts` at the start of
each call. On retry, `pos.contracts` had been decremented; the assignment overwrote the
first-tranche fill count. P&L reported for 1 contract instead of 3.

**Fix:** Remove upfront reset. Use `pos.closed_contracts += filled` — cumulative,
append-only.

### M7 — ask=0 Stale WebSocket Quote Halves Exit Mid-Price (G36)

Alpaca WebSocket delivered `ask=0` during low-liquidity periods. `mid = (bid + 0) / 2`.
Exit limit placed at ~50% of fair value, triggering MISS and market-order fallback.
Observed: `EXIT STOCK QUOTE FN: bid=620.0 ask=0.0 mid=310.00`.

**Fix:** Guard `if ask == 0: ask = bid` in `_stock_bid_ask()`.

### M8 — Log Messages Used Option Fields for Stock Positions

`_reconcile_stuck_positions()` logged `"RECONCILED None x0"` for stock positions —
`option_symbol` and `contracts` are None/0 for stocks.

**Fix:** Branch on `pos.trade_type` to use `ticker`/`shares` vs `option_symbol`/
`contracts`.

### M9 — min_ev Gate Polarity Mismatch vs Backtest (ea92432)

Live gate was `ev_trade <= 0` (blocks ev_trade=0.0). Backtest allowed ev_trade=0.0.
Also: `get(ticker, {})` returned empty dict for missing tickers, bypassing the gate
entirely and crashing `score_ticker()` with KeyError.

**Fix:** Change to `ev_trade < self._min_ev` (default 0.0); guard `if not stats: continue`.

### M10 — Fast-Path Rank Captured After Counter Increment (3fed6eb)

Fast-path signals (after collection deadline) assigned rank from `open_position_count`
after incrementing it. Second fast-path entry got rank=2 (20% weight) instead of rank=1
(40% weight).

**Fix:** Capture rank before incrementing the counter.

### M11 — Missing exit_fill_price in Stock Manual-Close Path (G37)

`_close_stock_position` returned early when a manual close was detected without first
fetching the exit fill price. The options path already called `_fetch_manual_close_fill_price()`
before returning; the stock path missed this call. Entire stock P&L rows showed `—` in
the daily summary.

**Fix:** Fetch fill price before early return in the stock manual-close path. Downstream
(681a6bc) also added the two-phase pending state for when fill is not yet in order history.

### M12 — BRU Trailing Arm at Full OR Range Instead of 0.1× (f6a9727)

BRU positions used `trailing_arm = trigger + or_range` (full range) instead of
`trigger + 0.1 × or_range`. BRU entries needed to move a full OR range before the
MA trailing stop was eligible — far too conservative. Backtest used 0.1× for BRU
(vs 1.0× for reversal).

**Fix:** Set `trailing_arm = trigger + or_range * 0.1` for BRU in `_enter_reentry()`.

---

## Development Pitfalls — Unified Checklist

### P1 — Temporal alignment: daily data gates intraday signals by +1 business day

Any filter using a daily close (index MA, sector filter, VIX) must be shifted forward
one business day before gating intraday signals. Today's close is only available for
tomorrow's trade.

**Check:** Does the filter access data that is settled only after market close? If yes,
apply `BDay(1)` shift. Validate: run with shift=0 vs shift=1 and compare P&L.

---

### P2 — Backtest/live parity for competing signal types

Any two signals that can both fire on the same day must use identical tie-breaking rules
in both backtest and live engine. "First bar wins" and "exhaustive scan" diverge whenever
more than one signal fires in a day.

**Check:** Write a test where Signal A fires on bar 3, Signal B on bar 5. Verify both
environments pick A. Swap — verify both pick B. Test same-bar tie.

---

### P3 — Per-position-type exit thresholds must match backtest exactly

Search `op_momentum_backtest.py` for every conditional in the exit path for each
position type (primary, BRE, BUE, reversal). Apply them individually in the live engine.
Never use a blanket threshold when the backtest distinguishes them.

**Check:** For the exit path you're touching, list the threshold for each position type.
Add tests verifying each independently.

---

### P4 — Pre-armed positions must satisfy all downstream gates from bar 1

When `initial_hard_stop_armed=True`, trace every gate function in the exit path and
verify it returns True immediately for a pre-armed position. Do not assume that setting
one field propagates automatically to related fields.

**Check:** Write a test: pre-armed position, price never reaches trailing arm, MA
crosses threshold. Verify exit fires on bar 1.

**Code review heuristic:** Grep for `if bar_close > threshold` (or `< threshold`) inside
monitoring loops. Each one is a candidate for this bug — ask: is this condition meant
to be permanent once first crossed? If yes, it must be a latched boolean, not a
per-bar recomputation.

---

### P5 — Capital accounting must use confirmed broker fills, never estimates

Any value that flows into `exit_fill_price`, window budget, or daily P&L must be a
confirmed broker fill. If the fill is not yet confirmed, hold capital in RECONCILE
PENDING — do not estimate.

**Check:** Can the value you're assigning be approximate or None from the broker? If
yes, add a pending path that waits for confirmation before returning capital.

---

### P6 — Competing capital consumers require explicit cancellation

When freed slot capital can be claimed by two mechanisms (re-entry watcher + DD;
watcher + next-window opener), explicitly cancel the loser BEFORE the winner fires.
Do not rely on execution ordering.

**Check:** For the freed capital event: who are all possible consumers? Is one cancelled
before the other fires?

---

### P7 — State machines need full lifecycle phases, not just opened/not-opened

"Opened" is not binary when a window can open, deploy, and return capital. Gate
conditions must distinguish opened-deployed (block) from opened-returned (allow).

**Check:** For the state you're gating on, enumerate all phases. Does the gate handle
each correctly?

---

### P8 — Cumulative fields are append-only across retries

Fields tracking progress across retries (`closed_contracts`, `filled_qty`, `closed_pnl`)
must use `+=`. Any `=` inside a retry loop resets prior progress.

**Check:** On code review: grep for `pos.<cumulative_field> =` inside loops or
functions that can be retried.

---

### P9 — Validate broker-sourced values at the system boundary

`ask=0`, `bid=0`, inverted bid>ask, and None prices are delivered during normal
operation. Guard at the ingestion function (`_stock_bid_ask`, etc.) — not in callers.

**Check:** Does the ingestion function guard zero ask, zero bid, inverted spread? Write
tests for each degenerate case.

---

### P10 — Cross-check both trade types in every notification and callback

Stock and options use different field names (`ticker`/`option_symbol`,
`shares`/`contracts`). Any log message, notification, or callback must branch on
`pos.trade_type`. After adding a feature for one type, explicitly verify the other
type's code path.

---

### P11 — Gate operator polarity must match backtest exactly

`<= 0` and `< 0` differ at exactly 0.0. After porting any gate from backtest to live
engine, confirm the exact operator with a boundary test (value == threshold).

---

### P12 — Capture rank/index before mutating the counter

Any pattern of "assign rank = counter, then counter += 1" must execute in that order.
Add a comment at the mutation site: "rank captured above before this increment."

---

### P13 — Watcher cleanup keyed too broadly (ticker alone is insufficient)

When multiple windows trade the same ticker, their watcher groups are independent.
Cleanup must key on `(ticker, primary_exit_bar_time)` — not ticker alone — to avoid
cancelling a sibling from a different window's exit.

---

### P14 — Cache key must encode every dimension that affects data content

Any new parameter that changes the data returned (feed, resolution, adjusted vs raw,
timezone) must be encoded in the cache filename. Test: fetch with param=A, verify one
cache file. Fetch with param=B, verify a different cache file.

---

### P15 — Derived stats must be reaudited when a new P&L component is added

`success`, `win_rate`, `avg_win_pct`, `avg_loss_pct` all depend on the P&L definition.
Adding re-entry/reversal P&L without updating `success` corrupts all downstream stats.
After adding any new P&L component, search for every place that reads `row["pnl"]` or
computes `success` and verify it uses the combined value.

---

### P16 — Guard signal conditions for degenerate input (zero range, zero price)

`or_range == 0`, `entry_price == 0`, `close == NaN` — any percent-based condition
relative to a zero denominator is trivially true or crashes. Guard before evaluating.
For sparse tickers: synthesize flat bars so the MA series stays continuous.

---

### P18 — Auto-formatter can silently revert critical arithmetic

The `BDay(1)` date shift in the regime filter was reverted twice by the linter, which
interpreted the set-comprehension change as a stylistic cleanup. Comparison operators
(`<=` vs `<`), decimal quantize arguments, and date offsets are all targets — they look
like constants but carry semantic weight.

**Check:** After any auto-format or lint pass, run `git diff` and inspect every line
that touches date arithmetic, comparison operators, or numeric constants. Do not
assume the formatter preserved the intent. This applies especially to:
- `BDay(n)` shifts in date filters
- `Decimal` rounding arguments
- `< 0` vs `<= 0` in gate conditions

---

### P17 — Option tick size is ticker-specific (verify Penny Pilot enrollment)

Default tick $0.05/$0.10 is WRONG for Penny Pilot tickers ($0.01/$0.05). Most large-cap
pool tickers are Penny Pilot; `CRDO`, `RH`, `FN`, `CLS`, `APP` are NOT. When adding a
new ticker: check the CBOE Penny Tick Type Report. Live rejections with `required=0.1`
also confirm non-pilot status.

---

## Good Design Patterns — Continue These

### Latch state for threshold-crossing conditions

`trailing_arm_reached: bool = False` on `ActivePosition`. Set once to True; never cleared.
The backtest mirrors this as `bru_trailing_armed`. Prevents re-disarming when price
retreats after first crossing.

**Apply to:** any condition that is "ever crossed," not "currently above."

---

### Two-phase reconciliation: PENDING → RECONCILED

`close_order_reconciled=True` stops FILL_ESC from placing more orders.
`close_order_failed=True` keeps the reconciliation thread retrying.
Capital returned only on confirmed fill.

Decouples "position is closed at broker" from "fill price is confirmed" — the right
separation when broker order history lags 1–4 minutes.

---

### Watcher scoped by (ticker, primary_exit_bar_time)

Re-entry watchers carry the exit time of the position that spawned them. Cleanup and
cancellation use both fields. Multiple windows trading the same ticker produce
independent watcher groups that don't interfere.

---

### Explicit cancellation before deployment

In `_check_doubledown_for_window`: cancel competing re-entry watchers BEFORE computing
the DD add-on size. The cancellation is visible to any concurrent watcher-scan loop.

---

### Named gate function (`_trailing_armed()`)

The arm check is a named, independently testable function rather than inlined logic
in `_evaluate_stop()`. Adding the `hard_stop_armed` short-circuit required touching
only the gate function, not the main eval flow.

---

### Atomic cache writes (tmp-then-rename)

Write to `path.tmp`, then `Path.replace(path)`. No reader sees a partial file.
Concurrent processes can't observe a torn write.

---

### Guard degenerate budget before entering positions

```python
if window_budget is None or window_budget <= _D("0"):
    return
```

One guard in `_drain_pending_signals_for_window` prevents entering positions with
a zero or negative budget (possible after a bad day where returned capital < 0).

---

### Small, isolated commits — one fix per commit

Each commit fixes one behavior. Commit message: symptom first, not implementation.
`"fix: accumulate closed_contracts additively across tranche fills"` not
`"fix: change = to +="`. Makes bisect fast; code review precise.

---

### Two-state PENDING / RECONCILED log messages

Operators monitoring the live log distinguish "confirmed closed, waiting for fill" from
"fill confirmed, capital returned." PENDING is actionable (wait, do not close manually);
RECONCILED means the trade is fully settled.

---

### Broker abstraction via ABC (`AlpacaAPIClient` / `TradeStationAPIClient`)

Engine is broker-agnostic. Market data and execution are independently configurable.
Adding a new broker requires only an implementation of the ABC — no engine changes.

---

### `--mock-trade-execution` / replay mode flag

Full engine runs against cached data without touching real broker accounts. Enables
end-to-end simulation of entry → monitoring → exit → P&L without live API risk.

---

## Summary — Cross-Cycle Recurring Themes

| Theme | April bugs | May bugs |
|---|---|---|
| **Temporal alignment / lookahead** | A1 (regime filter +1d) | — |
| **Backtest/live parity** | A2 (scan vs first-trigger), A4 (trailing arm latch) | M2 (threshold per type), M12 (BRU arm size) |
| **Cleanup/cancellation scope too broad** | A3 (ticker only) | M4 (DD double-spend) |
| **Cache key / cache assembly** | A5 (stitch seed), A6 (race), A7 (feed key) | — |
| **Derived stat not updated after new P&L** | A8 (success flag) | — |
| **Degenerate input guard** | A9 (or_range=0), A10 (tick size) | M7 (ask=0), M9 (stats=None) |
| **State machine lifecycle** | — | M5 (opened vs returned) |
| **Cumulative field reset on retry** | — | M6 (closed_contracts) |
| **Pre-armed gate not propagating** | A4 (arm latch) | M1 (hard_stop_armed gate) |
| **Capital accounting uses estimate** | — | M3 (mid-price fallback) |
| **Competing capital consumers** | — | M4 (DD + watcher) |
| **Trade-type field mismatch in logs** | — | M8 (option_symbol for stock) |
| **Gate operator polarity** | — | M9 (min_ev <= vs <) |
| **Rank captured after mutation** | — | M10 (fast-path rank) |
| **Auto-formatter silently reverts arithmetic** | A1 (BDay shift reverted 2×) | M9 (operator polarity) |

### Top 3 universal checklist items

1. **Pre-armed positions:** before shipping any new re-entry type, trace all gate
   functions for `initial_hard_stop_armed=True` from bar 1. Each gate must handle
   the pre-armed case independently.

2. **Capital accounting:** any new fill-price assignment — confirmed broker fill or
   estimate? Estimates must never reach `exit_fill_price` or window budget.

3. **Backtest/live parity per position type:** for every exit threshold and priority
   rule, read the backtest code for each position type separately. Never apply a
   blanket value when the backtest distinguishes them.
