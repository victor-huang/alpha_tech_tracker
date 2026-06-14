# Auto-Switch Profit Protection (MA8 Trailing Exit)

## Summary

Once a trade moves far enough in the winning direction, automatically tighten the trailing
exit from MA20 to MA8. The goal is to lock in more of the gain on strong momentum moves
without sacrificing early-hold flexibility — MA20 is used during the first phase so the
trade isn't shaken out too early, and MA8 takes over once the profit target is reached.

**Hypothesis**: on days where the trade runs far enough to trigger the upgrade, the stock
has demonstrated strong momentum. A tighter trailing stop captures a larger fraction of the
peak gain before the inevitable pullback. On days where the target is never reached, behavior
is identical to the current MA20-only exit.

No backtest results yet — this doc captures the design so implementation can proceed and
be measured.

---

## Background: Current Trailing Exit Logic

After the opening range closes, each position is protected by a two-phase exit:

1. **Hard stop** — fires if price retreats back into the OR before the breakout is confirmed.
   Arms automatically on the first bar that closes past the hard-stop level.
2. **Trailing MA exit** — once the hard stop is armed, if `MA20 > hard_stop_price` and
   `close < MA20` (bullish) or `close > MA20` (bearish), exit at `close`.

MA20 is a 100-minute moving average (20 × 5-min bars). It is loose enough that most winning
trades stay above it for a long time, letting them run to EOD.

MA8 is a 40-minute moving average (8 × 5-min bars). It hugs price more tightly, reacting to
smaller pullbacks. Using MA8 from entry would shake out too many otherwise-good trades.
Using it only after a profit threshold is reached captures winners that have already run.

---

## Switching Trigger Options

Three natural candidates, in order of recommendation:

### Option A — After trailing arm (recommended default)

**Switch condition**: `trailing_armed` latches True (price has moved `1 × or_range` past entry).

The `trailing_armed` flag already exists in all simulation blocks (reversal, BRE, BUE) as
the mechanism that arms the MA trailing stop. Re-using it as the MA8 upgrade point is
coherent: the arm says "trade is confirmed profitable by at least one OR range"; MA8 then
protects that gain.

- No new threshold parameter required
- Zero behavior change on trades that never arm (they exit via hard stop anyway)
- Symmetric for BULLISH and BEARISH

### Option B — Configurable favorable-move factor

**Switch condition**: `max_favorable_move >= factor × or_range`

Generalizes Option A. `factor = 1.0` reproduces Option A; `factor = 1.5` or `factor = 2.0`
requires a larger move before tightening. Useful if backtests show that upgrading at the
arm point is too aggressive and shakes out trades that would have continued.

Adds one CLI parameter: `--trailing-ma-switch-factor` (default `1.0`, implying after-arm
behavior when `--trailing-ma-switch after-target` is used).

### Option C — Bars-held threshold

**Switch condition**: `bars_held >= N`

Pure time-based: switch to MA8 after N 5-min bars regardless of price. Simpler but does
not reflect whether the trade has actually moved favorably.

---

## Chosen Design: Option B (superset of A)

Implement Option B with `factor = 1.0` as the default so that `--trailing-ma-switch after-arm`
is equivalent to `--trailing-ma-switch after-target --trailing-ma-switch-factor 1.0`.

This keeps the CLI clean (two flags, one behavior family) while giving full sweep flexibility.

---

## CLI Interface

```
--trailing-ma-switch  {none, after-arm, after-target}  (default: none)
--trailing-ma-switch-factor  FLOAT  (default: 1.0)
    Multiplier on OR range used when --trailing-ma-switch after-target is set.
    Ignored when --trailing-ma-switch is none or after-arm.
```

### Example usage

```bash
# Upgrade to MA8 once trailing arm fires (price moves 1× OR range past entry)
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --trailing-ma-switch after-arm

# Upgrade to MA8 once price moves 1.5× OR range past entry
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --trailing-ma-switch after-target --trailing-ma-switch-factor 1.5

# Backtest-level sweep (op_momentum_backtest.py directly)
python op_momentum_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --trailing-ma ma20 \
  --trailing-ma-switch after-arm
```

---

## Implementation Plan

### 1. Compute MA8 (op_momentum_backtest.py, line ~299)

Add alongside the existing MA20/MA50/MA200 computation:

```python
df["MA8"] = df["Close"].rolling(8).mean()
```

### 2. Add parameters to `compute_signals_with_backtest()`

```python
trailing_ma_switch: str = "none",   # "none" | "after-arm" | "after-target"
trailing_ma_switch_factor: float = 1.0,
```

### 3. Per-bar loop — primary trade simulation

Add two variables before the loop:

```python
use_ma8 = False
ma8_upgrade_threshold = (
    or_range if trailing_ma_switch == "after-arm"
    else trailing_ma_switch_factor * or_range
)
```

Inside the loop, before the exit checks:

```python
if not use_ma8 and trailing_ma_switch != "none":
    if trailing_ma_switch == "after-arm" and hard_stop_armed:
        use_ma8 = True
    elif trailing_ma_switch == "after-target" and max_favorable_move >= ma8_upgrade_threshold:
        use_ma8 = True

effective_ma = "ma8" if use_ma8 else trailing_ma
```

Replace the MA20 trailing-stop check to use `bar["MA8"]` when `effective_ma == "ma8"`.
The upgrade is a **one-way latch** — once `use_ma8` is True it stays True for the rest
of the day. This mirrors how `hard_stop_armed` works.

### 4. Apply same pattern to reversal, BRE, and BUE sub-loops

Each secondary simulation block has its own `trailing_armed` flag and per-bar MA check.
Add the same `use_ma8` latch to each block for consistency. The arm-based trigger is
natural here since these blocks already use `rev_trailing_armed` / `br_trailing_armed` /
`bru_trailing_armed`.

### 5. Propagate through `run_backtest()`

Add `trailing_ma_switch` and `trailing_ma_switch_factor` to the function signature and
pass them through to `compute_signals_with_backtest()`.

### 6. CLI changes

**op_momentum_backtest.py** — add to `parse_args()`:

```python
parser.add_argument(
    "--trailing-ma-switch",
    choices=["none", "after-arm", "after-target"],
    default="none",
)
parser.add_argument(
    "--trailing-ma-switch-factor",
    type=float,
    default=1.0,
)
```

**op_momentum_selector_backtest.py** — add the same two flags and pass them to
`run_backtest()` / `compute_signals_with_backtest()`.

---

## What to Validate After Implementation

### Correctness checks

1. **No-switch baseline unchanged** — run with `--trailing-ma-switch none` and confirm
   P&L matches current default. The `use_ma8 = False` path must never touch MA8.
2. **MA8 only activates after threshold** — add a unit test: inject a sequence of bars where
   `max_favorable_move` stays below threshold for 5 bars, then crosses on bar 6. Assert
   `exit_reason == "trailing_stop_ma20"` for the first 5 bars and `exit_reason ==
   "trailing_stop_ma8"` once MA8 is active.
3. **One-way latch** — once `use_ma8` is True it must not revert to False even if price
   dips back below the threshold.
4. **Symmetric for BEARISH** — verify the BEARISH path uses `bar_close > bar_MA8` (not `<`)
   when MA8 is active.

### Backtest sweep

Run the following comparisons over a full year (2025) and a multi-year window (2021–2025)
using the standard SOA config (`M1+A1+A2, top-3, weights 50/30/20, regime-filter ma8`):

| Config | Command flag |
|--------|--------------|
| Baseline (no switch) | `--trailing-ma-switch none` |
| Switch after arm | `--trailing-ma-switch after-arm` |
| Switch at 1.5× OR range | `--trailing-ma-switch after-target --trailing-ma-switch-factor 1.5` |
| Switch at 2.0× OR range | `--trailing-ma-switch after-target --trailing-ma-switch-factor 2.0` |

Key metrics to compare:
- Total return, win rate, EV/trade
- Average mins held (winners) — MA8 should shorten hold time on big winners
- Average win P&L and average loss P&L — the tradeoff is win capture vs shakeout
- Number of trades exiting via `trailing_stop_ma8` vs `trailing_stop_ma20`

Record results in `backtest_result/auto_switch_profit_protection/FINDINGS.md`.

---

## Edge Cases

| Case | Expected behavior |
|------|-------------------|
| MA8 is NaN (insufficient warmup bars) | Fall back to MA20 check; never trigger on NaN |
| OR range is zero (flat opening) | `filter_flat_or=True` skips this day; no division issue |
| Trade exits via hard stop before arm fires | `use_ma8` stays False; hard stop takes precedence as normal |
| MA8 < hard_stop_price | MA8 trailing check guard: `bar_MA8 > hard_stop_price` required (same guard as MA20) |
| `--trailing-ma ma50` with switch enabled | On upgrade, switch to MA8 instead of MA50; MA50 is no longer checked |

---

## Notes

- MA8 should be added to the output `rows` dict (alongside `ma20`, `ma200`) so the
  switching trigger point is visible in per-trade analysis.
- The `exit_reason` for MA8 exits should be `"trailing_stop_ma8"` to distinguish from
  `"trailing_stop_ma20"` in reports and aggregate stats.
- The live trade engine (`position_monitor.py`) is **not in scope for this change** until
  the backtest confirms positive edge. Document the live engine integration as a follow-on
  task once backtest results are in.
