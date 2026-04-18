# Implementation Retrospective — Live Trade Engine

Lessons learned and watchouts from building `trade_engine.py` / `position_monitor.py`
and validating them against `op_momentum_backtest.py`. Organized by theme.

---

## 1. Lookahead Asymmetry

The backtest has full-day lookahead. The live engine does not. Every place the backtest
makes a decision by scanning all remaining bars is a potential divergence point.

**Known cases:**

### Reversal/BRE priority
The backtest scans exhaustively for the reversal trigger first; only if no reversal
trigger appears in the entire remaining day does it consider BRE. In the live engine,
reversal and BRE are mutually exclusive at watcher-creation time: reversal watcher is
created when `bars_held ≤ reversal_max_bars`, and BRE is blocked. If the reversal
never fires, the BRE opportunity is also missed.

This causes a persistent +~$16 divergence on any day where a BEARISH primary stops
out early, reversal never fires, but BRE would have.

**Watchout:** Do not attempt to fix this by creating both watchers simultaneously.
Doing so creates a larger regression: BRE fires first on dates where price drops below
OR low before rising above OR high, but the backtest uses reversal (via lookahead).
Tested 2026-04-05 — broke 2026-02-11 (-$81) and 2026-02-24 (-$75). Reverted.

**What to do instead:** Accept as structural. If the gap matters for live trading,
consider changing the backtest to use chronological priority (fire whatever fires first)
rather than exhaustive reversal priority. That would make both systems agree — but
changes the backtest's historical returns.

---

## 2. Intraday Bar Timing vs. Backtest Bar Counting

The backtest counts bars by index within a day (`opening.iloc[:n]`). The live engine
processes bars at their actual wallclock timestamps and applies a collection deadline.

**Consequence for sparse tickers (ANAB):** ANAB has few trades per session. Its first
three 5-min bars may span 10:30–10:45 AM instead of 9:30–9:45 AM. Backtest treats
these as valid OR bars; live engine's deadline fires at 9:50 AM and skips ANAB
entirely, substituting a lower-ranked ticker.

**Watchout:** When validating replay vs. backtest for sparse tickers, expect systematic
divergence on any day where the ticker's OR formation is delayed. This is not a bug —
it accurately represents real-time behavior. The pre-market selector will show ANAB as
the top pick, but execution will differ.

**Downstream effect:** The substituted ticker often has a reversal leg. If the reversal
loses, the A1/A2 cap P&L can be -$7 to -$15 worse than backtest on those days.

---

## 3. Capital Flow: Realized vs. Unrealized

The backtest's sequential window budget (`available = portfolio + first_group_pnl`)
includes unrealized P&L of still-open M1 positions at the time A1 starts.

The live engine computes A1 budget at drain time by summing:
- Capital returned by closed M1 positions (at cost + realized P&L)
- Slot capital of still-open M1 positions (at cost, no unrealized gain)
- Undeployed M1 capital (M1 budget minus M1 deployed)

**Consequence:** When a large M1 winner (e.g., SHOP +$320) is still running at A1
drain, A1 gets ~$300 less budget than the backtest assumed. This reduces A1 and A2
slot capitals and their cap P&Ls proportionally. Expect a persistent -$1 to -$5 drag
on each sequential window on strong M1 days.

**Watchout:** This is structural. The live engine cannot know SHOP's unrealized gain
at A1 drain time with certainty (mark-to-market requires a quote). Accepting the
at-cost estimate is the right tradeoff.

---

## 4. Re-entry Position Lifecycle Rules

Re-entry positions (reversal, BRE, BRU) share a capital slot with their primary. They
do not deploy new capital. Violating this causes inflated A1/A2 budgets.

### Capital accounting (G19, fixed)
`_on_position_closed` must add only `cap_pnl` (not `slot_capital + cap_pnl`) to
`_window_returned` for re-entry positions. Re-entries are identified by
`pos.trailing_arm_price is not None`. Getting this wrong inflates sequential budgets
by 50–100% (e.g., `_window_returned["M1"]` was $15,419 instead of $10,419).

### No cascading (G16, fixed)
Re-entry positions must not spawn further watchers. Add a guard:
```python
if pos.trailing_arm_price is not None:
    return  # re-entries don't chain
```
Without this, a reversal that hard-stops spawns a BRU watcher, which fires and enters
yet another position — not in the backtest model.

### Hard stop armed at entry (G14, fixed)
Re-entry entries are always on the favorable side of the midpoint stop. The stop must
be armed immediately (`initial_hard_stop_armed=True`). If left unarmed, the position
survives a dip that the backtest would stop out, inflating P&L.

---

## 5. Replay Threading

In replay mode, bar processing is synchronous — one bar at a time, no real-time
sleep. Any async operation inside the bar loop runs at an indeterminate future bar.

**Re-entry callback threading (G15, fixed):** The original implementation spawned a
`threading.Thread` for the re-entry callback inside `_collect_fired_watchers`. In
replay, the thread might execute during bar N+3 instead of bar N, causing the
re-entry position to miss the critical first monitoring bars (including the immediate
hard-stop check).

**Rule:** In replay mode (`is_replay_mode() == True`), all callbacks that affect
position state must be invoked synchronously. Use threading only in live mode.

**Deadlock risk:** Never invoke a callback that calls `monitor.add_position()` while
holding `self._lock`. Collect fired watchers under the lock, then invoke callbacks
after releasing it.

---

## 6. Stop Price vs. Bar Close

The backtest exits at the stop level, not the bar close.

| Exit type | Backtest price | Original live price |
|-----------|---------------|---------------------|
| `hard_stop` | `pos.hard_stop_price` | bar close (wrong) |
| `fallback_20pct` (BEARISH) | `pos.fallback_price` | bar close (wrong) |
| `fallback_20pct` (BULLISH) | `pos.fallback_price` if bar high ≥ level, else bar close | bar close (wrong) |
| `trailing_stop_ma20` | bar close | bar close ✓ |
| `end_of_day` | bar close | bar close ✓ |

**Fix (G12):** Added `exit_stock_price_override` to `_close_position` /
`_close_stock_position`. Pass `pos.hard_stop_price` for hard stops and
`pos.fallback_price` for fallbacks (with the BULLISH high-check).

**Watchout:** Forgetting the override makes per-trade P&L agree only on trailing/EOD
exits. Hard-stop and fallback exits will show larger-than-backtest losses (exiting at
close instead of stop level) and make replay-vs-backtest comparison misleading.

---

## 7. Signal Deadline Off-by-One

The collection deadline comparison uses `now <= deadline` (not `now < deadline`).

Sparse tickers (ANAB) sometimes fire their signal at exactly the OR close timestamp
(`now == deadline`). Using strict `<` caused these signals to bypass the ranked drain
(they arrived "after" the deadline) and enter at rank=0 with no competition.

**Symptom:** Sparse ticker enters as rank=1 (slot=50% of budget) on dates where it
should be rank=2 (slot=30%); or it gets selected when it should be behind a higher-EV
ticker that fired slightly earlier.

**Fix (B2):** `if now <= state["collection_deadline"]` in `_on_signal_for_window`.

---

## 8. Rolling Stats Look-ahead Bias

The 60-day rolling stats must use `date < target_date` (not `date <= target_date`).

Including the current day's result inflates EV/WR because it counts a trade that
hasn't happened yet. On winning days the bias inflates scores; on losing days it
deflates them. This causes wrong ticker rankings and selection.

**Fix (G6):** `df[df["date"] < target_date]` in `select_top_n()`.

**Watchout:** Easy to re-introduce when adding new stat computations. Any filtered
slice used for "historical performance" must exclude the current date.

---

## 9. Regime Filter Coverage in Rolling Stats

When computing rolling stats for dates in the 60-day lookback before `eval_start`,
`bearish_regime_dates` must cover those lookback dates too.

Original code called `build_bearish_regime_dates(eval_start, eval_end)`. Dates in the
lookback window (60 days before `eval_start`) weren't in the set, so bullish signals
on bearish QQQ days in the lookback were counted — different behavior from the live
selector, which calls `run_backtest` with the full lookback range.

**Fix (G11):** Call `build_bearish_regime_dates(fetch_start, eval_end)` where
`fetch_start = eval_start - lookback_days`.

**Watchout:** Any time you add a new feature that filters trades (regime, OR-range
threshold, min EV), verify that the same filter is applied consistently in both the
rolling-stats computation AND the trade selection logic.

---

## 10. `signal_bar_time` Must Be the OR Close Bar, Not the Drain Bar

When a signal is buffered (not immediately entered), the bar that drains the buffer
(first post-OR bar) is different from the bar the signal fired on (last OR bar).

`entry_bar_time` must be set to the signal bar — the last OR bar — so the position
monitor knows which bar the position was entered on. If set to the drain bar, the
monitor skips the drain bar when evaluating stops, causing the first monitoring bar
after OR to be missed entirely.

**Fix (G7):** Capture `latest_bar.name` as `signal_bar_time` when the signal is
buffered; use it in `_enter_position`.

---

## 11. Regime MA Default Must Match Across All Entry Points

The regime MA default in `op_momentum_backtest.py` was 5; `config.py` and all
findings use 8. Always pass `--regime-ma 8` explicitly; do not rely on defaults.

If you add any new CLI or function that wraps the backtest, ensure `regime_ma=8`
is forwarded or defaulted explicitly — do not inherit the module-level default.

---

## Quick Validation Checklist

When making changes to position lifecycle or capital flow:

1. Run replay for 2026-02-03, 2026-02-11, 2026-02-26, 2026-04-01 and compare to
   backtest. The three ✓ dates should stay within $2. 2026-02-03 (+$13.79) and
   2026-02-24 (-$11.75) are structural baselines — changes should not make them worse.

2. Run the full test suite:
   ```bash
   PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
     python -m pytest tests/op_momentum_trade_engine/ -v
   ```
   All 277 tests must pass.

3. Check `_window_returned["M1"]` at EOD. For top-2 with M1 budget $10,000:
   - Primary deployed: $8,000 (two slots: $5,000 + $3,000)
   - Expected: `returned ≈ $8,000 + cap_pnl`
   - If returned > $15,000 → re-entry capital double-counted (G19 regression)
   - If A1 budget > $12,000 → same problem

4. For dates with BRE/reversal activity, verify the re-entry fires in only ONE
   direction (not both) and `is_reentry=True` in the log.
