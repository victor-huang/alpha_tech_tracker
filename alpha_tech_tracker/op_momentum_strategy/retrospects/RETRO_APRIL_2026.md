# Retrospective — April 2026

Covers bugs found and fixed across the backtest engine, live trade engine, and cache
system during the April 2026 development cycle. Each entry describes what broke, why
it broke, how it was fixed, and what to check the next time something similar is built.

---

## Bug 1 — Lookahead Bias in Regime Filter (backtest)

**Commit:** `95b39d0`

### What happened
`build_bearish_regime_dates` returned the set of calendar dates where QQQ's close was
below its N-day MA. These dates were used to suppress BULLISH signals on the *same* day.
But QQQ's daily close is not settled until after market close — it is not known at 9:45
AM when the signal fires. This introduced a 1-day lookahead: the backtest was gating
today's trade using today's information.

The entire 5-year edge attributed to `--regime-filter` (+16pp) came from this bug.
After the fix, no MA value (3–50) beat the no-filter baseline in a clean backtest.

### Root cause
The function built a set of *signal dates* (the day QQQ was bearish) but the callers
needed *action dates* (the next trading day, when the regime is actually known). There
was no comment making this distinction clear, so the off-by-one went unnoticed.

### Fix
Shift every date in the set forward by one business day (`pd.tseries.offsets.BDay(1)`).
The set now contains action dates. A bearish close on day D gates signals on D+1.

### Lesson learned
**Any external daily signal (index MA, sector filter, VIX threshold) must be shifted
+1 business day before being used to gate intraday signals.** Today's close is only
available for tomorrow's trade.

### What to double-check when building new filters
- What time of day is the filter data available? Daily close = available next morning.
- Is the set indexed by signal date or action date? Document this in the docstring.
- Run the filter with shift=0 vs shift=1 on the same backtest and compare P&L. If
  the result changes dramatically, you likely had a lookahead.
- The linter twice silently reverted the BDay shift because it saw a `set comprehension`
  change and treated it as stylistic. Always verify `git diff` after linting before
  committing anything that involves date arithmetic in a filter.

---

## Bug 2 — Reversal vs BRE Priority: Exhaustive Lookahead Instead of First-Trigger Wins

**Commit:** `f9e5923`

### What happened
When both reversal (REV) and bearish re-entry (BRE) were enabled, the backtest decided
which to simulate using exhaustive lookahead: scan *all* remaining post-stop bars for a
reversal trigger; only try BRE if reversal never fires anywhere across the entire day.
The live engine works completely differently: it processes bars one at a time and takes
whichever trigger fires first.

On any day where BRE fired on an earlier bar than reversal, the backtest picked REV and
the live engine picked BRE — different trades, different P&L.

### Root cause
The reversal scan was implemented first (before BRE existed), and BRE was bolted on as
an `else` branch: "try reversal; if that doesn't find anything, try BRE." This felt
natural in a batch script but diverged from the live engine's bar-by-bar loop.

### Fix
Run both entry scans before simulating either. Compare `rev_entry_idx` vs
`bre_entry_idx`. Whichever is smaller wins; same-bar ties go to reversal (consistent
with the live engine's priority order). Cancel the losing entry by setting its
`entry_price = None` and skip its simulation block.

### Lesson learned
**Any two competing signals that can both fire on the same day must use the same
tie-breaking rule in backtest and live engine — and the rule must be explicit.**
"First bar wins" and "exhaustive scan" produce the same answer only when at most one
signal fires per day.

### What to double-check when adding a new re-entry or competing signal type
- Does the backtest use exhaustive scan while the live engine uses bar-by-bar?
- Write a test case where Signal A fires on bar 3 and Signal B fires on bar 5. Verify
  backtest and live engine both pick A.
- Write a test case where Signal B fires on bar 3 and Signal A fires on bar 5. Verify
  both pick B.
- Check same-bar tie behavior explicitly.

---

## Bug 3 — Sibling Watcher Cleanup Too Broad (live trade engine)

**Commit:** `f399650`

### What happened
`_collect_fired_watchers` removed **all** watchers for a ticker when any one of them
fired. This accidentally deleted watchers belonging to a different window's primary exit.
Example: when A1's reversal watcher fired, M1's BRE watcher (a sibling of M1's primary
exit, not A1's) was silently dropped — it could never fire.

### Root cause
The cleanup key was just `ticker`. Two windows trading the same ticker on the same day
create independent watcher groups that share a ticker but belong to different primary
exits. The original code didn't model the concept of "which primary exit spawned this
watcher" — it assumed one watcher group per ticker per day.

### Fix
Add `primary_exit_bar_time` to each watcher. Cleanup now removes only watchers that
share both `ticker` and `primary_exit_bar_time` as the fired watcher — true siblings of
the same exit event. Watchers from a different window's exit survive untouched.

### Lesson learned
**Watcher / callback cleanup must be scoped to the exact event that spawned the
watcher, not to a broad key like ticker.** When multiple windows trade the same ticker,
their watcher groups are independent and must not interfere.

### What to double-check when adding new watcher or re-entry types
- What is the correct cleanup scope? Ticker alone is almost always too broad.
- Does your test suite cover two windows holding the same ticker simultaneously?
- Write a test: M1 and A1 both enter the same ticker. M1's watcher fires. Verify A1's
  watcher is still alive and fires correctly later.

---

## Bug 4 — Trailing Arm State Not Latched (live trade engine)

**Commit:** `33fb278`

### What happened
`_trailing_armed()` in `PositionMonitor` re-evaluated the arm threshold on every bar.
If price rose above the arm threshold on bar 5 but then retreated below it on bar 6,
the trailing MA stop was silently disarmed. The backtest used a boolean
`bru_trailing_armed` that latches to `True` on first crossing and is never cleared —
so the live engine and backtest diverged silently on any trade where price temporarily
pulled back after arming.

### Root cause
The live engine computed "is price above threshold?" dynamically instead of persisting
state. Stateless queries are easy to write but wrong for threshold-crossing logic: once
you've confirmed the threshold was crossed, that fact should be permanent.

### Fix
Add `trailing_arm_reached: bool` to `ActivePosition`. Set it to `True` on first
crossing; never clear it. `_trailing_armed()` returns `self.position.trailing_arm_reached`.

### Lesson learned
**Any threshold-crossing condition that should be permanent once met must be stored as
latched state, not recomputed from current price.** "Was price ever above X?" is
different from "Is price above X right now?"

### What to double-check when adding new arm/trigger conditions
- Is this condition "ever crossed" or "currently above"? Use latched state for the former.
- Does the backtest use a persistent boolean that matches?
- Write a test: price crosses threshold, then retreats. Verify arm remains True.
- Grep for any `if bar_close > threshold` inside a monitoring loop — each one is a
  candidate for this bug if the condition is meant to be permanent.

---

## Bug 5 — Cache Corruption via Wrong Stitch Seed (backtest data cache)

**Commit:** `f35c9ec`

### What happened
`_stitch_cache` seeded `covered_end` from `pieces[0][0] - 1 day` (the start of the
first found cache piece) instead of `start_date - 1 day` (the actual request start).
This made the gap-check between the request start and the first piece trivially pass,
even when the first piece started months after the requested start.

Result: a cache file covering Jul–Dec was accepted as covering Jan–Dec. The stitcher
saved a "Jan–Dec" file containing only Jul–Dec bars, then evicted the original Jul–Dec
file. Every subsequent request silently returned truncated data.

### Root cause
The seed variable name (`covered_end`) implied "how far we've covered so far starting
from the request start" but it was initialized from the first piece rather than from the
request. A logic error in the initialization step, made invisible by the fact that
stitching usually works when the first piece is close to the request start.

### Fix
Seed `covered_end = start_date - timedelta(days=1)` in both `_stitch_cache` and
`_partial_stitch_cache`. The gap between `start_date` and `pieces[0][0]` is now checked
with the same 7-day tolerance used for inter-piece gaps.

### Lesson learned
**Cache assembly logic must validate coverage from the actual request boundary, not from
the first found piece.** Always ask: "Does my assembled result actually cover [start,
end]?" — don't assume the first piece is close enough to start.

### What to double-check when building or modifying a cache/stitch system
- Does coverage validation start from the request start, not from the first piece?
- After a stitch, verify the output file's actual date range matches the requested range.
- Test the case where the first available piece starts significantly after the request
  start — does the system correctly fall back to an API fetch?
- Test the eviction path: after stitching and evicting originals, re-request the same
  range and verify data completeness.

---

## Bug 6 — Cache Parallel Race Conditions (backtest data cache)

**Commit:** `8a0255f`

### What happened
Running multiple backtest processes concurrently (e.g., a parameter sweep with
`ProcessPoolExecutor`) caused two failure modes:
1. **Partial writes**: one process wrote a cache JSON file while another was reading it,
   producing a truncated/corrupt JSON.
2. **FileNotFoundError crashes**: a process scanned the cache directory, found a file,
   then another process evicted it before the first could open it.

### Root cause
Cache writes were non-atomic (`open(path, 'w')` + `json.dump`). Directory scans and
subsequent file opens were not protected against concurrent deletion.

### Fix
1. **Atomic writes**: write to a `.tmp` sibling, then `Path.replace()` (single POSIX
   `rename` syscall — atomic). Readers see either the old complete file or the new
   complete file, never a partial write.
2. **Tolerate FileNotFoundError on load**: if a piece disappears between scan and open,
   return `None` and let the caller fall through to a fresh API fetch.
3. **Tolerate FileNotFoundError on unlink**: if another process already deleted the
   file, silently ignore rather than crashing.

### Lesson learned
**Any file-based cache shared across processes needs atomic writes and TOCTOU guards.**
"Check then act" (scan directory, then open file) is always a race when another process
can delete files in between.

### What to double-check when adding caching to any parallel workload
- Are all cache writes atomic? Use tmp-then-rename.
- Are all cache reads guarded against `FileNotFoundError`?
- Are all cache deletes guarded against `FileNotFoundError`?
- Does the parallel sweep have enough workers to expose the race? Test with 8+ workers.

---

## Bug 7 — IEX and SIP Feed Data Sharing the Same Cache Key

**Commit:** `6ec9b66`

### What happened
Switching from IEX to SIP feed in the backtest still hit the IEX-populated cache
because both feeds used the same cache filename format
(`alpaca_5min_{ticker}_{start}_{end}.json`). SIP data is denser and has different bar
values than IEX — silently returning IEX data for SIP requests produced subtly wrong
backtest results.

### Root cause
The cache key was built from source name (`"alpaca"`) without encoding the feed
variant. When a second dimension (feed) was added to the data source, the cache key
was not updated to include it.

### Fix
Encode the feed in the cache key: `alpaca_sip_5min_{ticker}...` vs
`alpaca_iex_5min_{ticker}...`. Switching feeds now writes to a separate file set with
no manual cleanup needed.

### Lesson learned
**Every dimension that affects data content must be encoded in the cache key.** When
you add a new parameter that changes what data is returned (feed, resolution, adjusted
vs unadjusted, timezone), the cache key must change too.

### What to double-check when adding a new data source parameter
- Does the new parameter affect the bar values returned?
- Is the parameter encoded in the cache key/filename?
- Test: fetch with param=A, verify cache file created. Fetch with param=B, verify a
  *different* cache file is created, not the same one.

---

## Bug 8 — Success Flag Mismatch in Backtest Stats

**This session** (not committed separately — fixed inline with the `pnl_pct` field)

### What happened
In `op_momentum_selector_backtest.py`, trade rows stored:
```python
"success": pick["pnl"] > 0   # primary trade P&L only
"pnl_pct": combined_pnl_pct  # primary + reversal/re-entry combined
```
The `success` flag was based on the raw primary P&L, but `pnl_pct` included reversal
and re-entry P&L. A trade where the primary lost but the reversal won (net positive)
was counted as a loss in the success flag — inflating the reported loss rate and
polluting the `avg_loss_pct` stat used by the rolling scorer.

### Root cause
`success` was written before re-entry logic was added. When re-entry P&L was added to
the row, the success flag was not updated to match.

### Fix
```python
"success": combined_pnl_pct > 0   # matches pnl_pct stored alongside it
```

### Lesson learned
**When you add a new P&L component to a trade row, audit every derived flag and stat
that was computed before the new component existed.** `success`, `win_rate`,
`avg_win_pct`, `avg_loss_pct` all depend on the correct P&L definition — adding
reversal/re-entry P&L without updating the success flag silently corrupts all of them.

### What to double-check when adding a new P&L component
- Search for every place that reads `row["pnl"]` or `pick["pnl"]` — is each one
  supposed to use combined P&L or primary-only?
- Is the `success` flag consistent with `pnl_pct` stored in the same row?
- Do `avg_win_pct` and `avg_loss_pct` compute on the same basis as `pnl_pct`?

---

## Bug 9 — Sparse Ticker: Zero OR Range Causes False BEARISH Signal (live trade engine)

**Commit:** `9b654cd`

### What happened
For illiquid tickers (e.g. FN on certain mornings), the Alpaca WebSocket delivered no
bars during the opening range window. The signal engine received an empty OR buffer,
produced `or_range = 0`, and then evaluated the BEARISH condition — which passed trivially
because `close <= or_low + 20% × 0` is always true. A false BEARISH signal fired.

### Root cause
No guard against `or_range == 0` before evaluating signal conditions. Additionally, no
mechanism to handle silent 5-min periods — a missing bar left a gap in the MA series
and the OR buffer.

### Fix
1. Synthesize flat bars (OHLC = last close, volume = 0) for any 5-min period with no
   activity, keeping the MA series and OR buffer continuous.
2. Add `or_range == 0` guard in `_try_fire_signal` — suppress both BULLISH and BEARISH
   when the opening range is degenerate.

### Lesson learned
**Always guard signal conditions against degenerate input (zero range, empty window,
NaN prices).** Percent-based conditions relative to a zero denominator produce
undefined or trivially-true results.

### What to double-check when adding a new signal or filter condition
- What happens when `or_range == 0`? When `entry_price == 0`? When `close == NaN`?
- Does the signal fire correctly on days with sparse bar delivery?
- For any `close <= low + pct × range` style condition: add `and range > 0` guard.

---

## Bug 10 — Wrong Option Tick Size (live trade engine)

**Commit:** `be164f0`

### What happened
`_quantize_option_price` used the standard non-Penny-Pilot tick schedule ($0.05 under
$3, $0.10 above). All tickers in the pool are on the CBOE Penny Pilot Program, where
the correct ticks are $0.01 under $3 and $0.05 above $3. Limit orders were placed at
suboptimal price points — up to $0.05 off per order.

### Root cause
The non-pilot schedule is the "default" mentioned in most generic documentation. The
Penny Pilot schedule requires knowing which tickers are enrolled and is easy to miss.

### Fix
Use $0.01 / $0.05 thresholds for all pool tickers. Document the rule in CLAUDE.md so
it is not quietly reverted.

### Lesson learned
**Option tick sizes are not uniform.** Before placing any limit option order, confirm
whether the underlying is on the Penny Pilot Program. Using the wrong schedule wastes
$0.01–$0.05 per order and can cause unnecessary bid rejections.

### What to double-check when adding a new ticker to the pool
- Is it on the CBOE Penny Pilot Program? (All major liquid ETFs and large-caps are.)
- Does `_quantize_option_price` use the correct tick for that ticker?
- Run a test that places a limit order near a $3.00 boundary and verify the tick.

---

## Summary — Recurring Themes

| Theme | Bugs |
|---|---|
| **Off-by-one in time / date** | Bug 1 (regime filter +1 day lookahead) |
| **Backtest/live divergence** | Bug 2 (first-trigger vs exhaustive scan), Bug 4 (trailing arm state) |
| **Cleanup scope too broad** | Bug 3 (sibling watcher keyed on ticker only) |
| **Cache key missing a dimension** | Bug 7 (IEX vs SIP same key) |
| **Cache assembly / eviction logic** | Bug 5 (stitch seed), Bug 6 (parallel race) |
| **Derived field not updated after adding new P&L component** | Bug 8 (success flag) |
| **Missing guard for degenerate input** | Bug 9 (or_range == 0) |
| **Wrong external constant** | Bug 10 (tick size schedule) |

### Top 3 things to always verify for any new feature

1. **Temporal alignment**: does every filter/signal use only data that is known at the
   time the signal fires? Daily closes, rolling MAs on daily bars, and external index
   values all need a +1 business day shift before they can gate intraday signals.

2. **Backtest/live parity**: after implementing any new exit, re-entry, or priority rule,
   write a test that exercises the exact bar sequence where backtest and live engine could
   diverge — especially any place where the backtest "scans ahead" to find an entry.

3. **Cache key completeness**: any new parameter that changes the data returned must be
   encoded in the cache key. Run two fetches with different parameter values and confirm
   they produce two different cache files.
