# Reduce Noise — Implementation Reference

This document records the exact code changes made to implement the three noise-reduction proposals (P1, P2, P3). All changes were subsequently reverted because all proposals were rejected (see `PROPOSLAS.md`).

---

## Files Modified

- `alpha_tech_tracker/op_momentum_strategy/op_momentum_backtest.py`
- `alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py`

---

## op_momentum_backtest.py

### 1. New parameters on `compute_signals_with_backtest`

Added three keyword arguments (all defaulting to off/baseline values):

```python
def compute_signals_with_backtest(
    df, opening_bars, bearish_ma200=False, stop_pct=0.40,
    opening_start_time="09:30", trailing_ma="ma20",
    max_loss_pct=None, armed_ma20_exit=False,
    bearish_regime_dates=None, enable_reversal=False,
    reversal_max_bars_held=3,
    min_entry_room: float = 0.0,   # P1
    fallback_pct: float = 0.20,    # P2
    entry_bar_confirm: bool = False, # P3
) -> pd.DataFrame:
```

### 2. P3 — Entry bar direction confirmation (after regime filter, before stop computation)

```python
if entry_bar_confirm:
    bar_open = last_bar.get("Open", float("nan"))
    if signal == "BULLISH" and close <= bar_open:
        continue
    elif signal == "BEARISH" and close >= bar_open:
        continue
```

### 3. P2 — Configurable fallback percentage (replaces hardcoded 0.20)

```python
# Before:
bull_fallback = or_high - 0.20 * or_range
bear_fallback = or_low + 0.20 * or_range

# After:
bull_fallback = or_high - fallback_pct * or_range
bear_fallback = or_low + fallback_pct * or_range
```

Dynamic exit reason (two places — initial assignment and inside the exit loop):

```python
# Before:
exit_reason = "fallback_20pct"

# After:
exit_reason = f"fallback_{int(fallback_pct * 100)}pct"
```

### 4. P1 — Minimum entry-to-fallback room (after fallback computation)

```python
if min_entry_room > 0.0 and close != 0:
    if signal == "BULLISH":
        entry_room = (close - fallback_price) / close * 100
    else:
        entry_room = (fallback_price - close) / close * 100
    if entry_room < min_entry_room:
        continue
```

**Formula notes:**
- BULLISH: entry is above fallback (fallback fires when price drops to fallback_price) → room = `(close - fallback_price) / close * 100`
- BEARISH: entry is below fallback (fallback fires when price rises to fallback_price) → room = `(fallback_price - close) / close * 100`
- There was an initial inversion bug (both directions swapped) that was fixed before the 5-year sweep.

### 5. Reversal eligibility fix (required by P2's dynamic exit reason)

Without this fix, any run with `fallback_pct != 0.20` would silently drop all reversal trades because the eligibility check was hardcoded to `"fallback_20pct"`.

```python
# Before:
and exit_reason in ("hard_stop", "fallback_20pct")

# After:
and (exit_reason == "hard_stop" or exit_reason.startswith("fallback_"))
```

### 6. New parameters on `run_backtest`

```python
def run_backtest(
    ...existing params...,
    min_entry_room: float = 0.0,
    fallback_pct: float = 0.20,
    entry_bar_confirm: bool = False,
) -> dict:
```

Passed through to `compute_signals_with_backtest`:

```python
results = compute_signals_with_backtest(
    df, opening_bars, ...,
    min_entry_room=min_entry_room,
    fallback_pct=fallback_pct,
    entry_bar_confirm=entry_bar_confirm,
)
```

---

## op_momentum_selector_backtest.py

### 1. New parameters on `run_selector_backtest`

```python
def run_selector_backtest(
    ...existing params...,
    min_entry_room: float = 0.0,
    fallback_pct: float = 0.20,
    entry_bar_confirm: bool = False,
) -> tuple:
```

Passed through to `compute_signals_with_backtest` call inside the window loop:

```python
results_for_window[ticker] = compute_signals_with_backtest(
    df, win["opening_bars"], ...,
    min_entry_room=min_entry_room,
    fallback_pct=fallback_pct,
    entry_bar_confirm=entry_bar_confirm,
)
```

### 2. New CLI arguments in `_parse_args()`

```python
parser.add_argument(
    "--min-entry-room",
    type=float, default=0.0, dest="min_entry_room",
    help="Skip trade if entry-to-fallback distance < threshold %% of entry. Default: 0.0 (disabled).",
)
parser.add_argument(
    "--fallback-pct",
    type=float, default=0.20, dest="fallback_pct",
    help="Fallback stop as fraction of OR range from favorable end (default: 0.20).",
)
parser.add_argument(
    "--entry-bar-confirm",
    action="store_true", default=False, dest="entry_bar_confirm",
    help="Require last OR bar to close in signal direction. Default: off.",
)
```

### 3. Config print lines and wiring in `__main__`

```python
print(f"  Min entry room: {f'{args.min_entry_room:.2f}%' if args.min_entry_room > 0 else 'disabled'}")
print(f"  Fallback pct : {args.fallback_pct:.0%} of OR range")
print(f"  Entry bar confirm: {'on' if args.entry_bar_confirm else 'off'}")
```

Wired to `run_selector_backtest`:

```python
run_selector_backtest(
    ...,
    min_entry_room=args.min_entry_room,
    fallback_pct=args.fallback_pct,
    entry_bar_confirm=args.entry_bar_confirm,
)
```

---

## Bugs Found During Implementation

### Bug 1: Entry room formula inverted (P1)

Initial implementation had both signal directions swapped:

```python
# Wrong:
if signal == "BULLISH":
    entry_room = (fallback_price - close) / close * 100   # negative for all valid BULLISH entries
else:
    entry_room = (close - fallback_price) / close * 100   # negative for all valid BEARISH entries

# Correct:
if signal == "BULLISH":
    entry_room = (close - fallback_price) / close * 100
else:
    entry_room = (fallback_price - close) / close * 100
```

Effect: the wrong formula filtered out almost all trades (both directions had negative room). Fixed before the 5-year sweep.

### Bug 2: Reversal eligibility broken by dynamic exit reason (P2)

When `fallback_pct=0.30`, exit_reason became `"fallback_30pct"` but the reversal eligibility check still looked for `"fallback_20pct"`. This silently dropped all reversal trades in P2 runs.

Fixed by changing the check to `exit_reason.startswith("fallback_")`. The fix was kept even after P2 was rejected — the reversal check is now robust regardless of `--fallback-pct` value.

**Note:** This fix was kept in the final revert only if the reversal code paths matter. Since all three proposals are reverted, the revert restores the original `"fallback_20pct"` string literal, which is correct for the default `fallback_pct=0.20` case.
