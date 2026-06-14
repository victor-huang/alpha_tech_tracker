# BEARISH Re-Entry Feature — Implementation Overview

## Motivation

During a scan of A2-window BEARISH signals in Q1 2026 (151 signals), we found that **74% of trades stopped out early had the stock price drop below the original entry within the next 30 minutes**. The average potential re-entry gain was +$1.69/share. This indicated a recurring structural pattern: the A2 BEARISH signal fires correctly, but the initial position gets stopped out on a minor bounce before the real move resumes.

The BEARISH re-entry feature captures this follow-through drop by re-entering BEARISH after the first exit, once price confirms a new close below OR_low.

---

## What It Does

When a primary BEARISH trade stops out early (hard stop or fallback), the strategy watches for price to re-confirm the bearish setup:

1. **Eligibility check** — A re-entry is considered when:
   - Signal is BEARISH
   - The primary exit reason is `hard_stop` or `fallback_20pct`
   - The primary trade was held for at most `bearish_reentry_max_bars` bars
   - No reversal trade fired on the same primary (mutual exclusion)

2. **Re-entry trigger** — Scans bars after the primary exit for the first bar where `close < or_low`

3. **Re-entry trade management**:
   - Entry: closing price of the first bar below OR_low
   - Hard stop: `midpoint` (top of OR)
   - Trailing arm: position is armed when price drops `>= effective_or_range` below entry
   - Trailing exit (MA20): armed AND `bar_ma20 < midpoint` AND `close > bar_ma20`
   - EOD: force-close at 3:55 PM ET

4. **P&L accounting**: `br_pnl` is added to `cap_pnl` using the same `slot_capital` as the primary trade — not double-counting capital, just applying re-entry gain/loss to the slot.

---

## Design Decisions

### Mutual Exclusion with Reversal

The reversal feature (`--reversal`) goes BULLISH after a BEARISH stop-out. The bearish re-entry stays BEARISH. When both flags are enabled simultaneously they are mutually exclusive on any given primary trade — whichever trigger fires first chronologically wins, with reversal winning same-bar ties.

**Recommended usage**: run `--reversal` and `--bearish-reentry` as independent flags without
combining them on the same run. Each fires freely on days the other does not — the live engine
handles them as independent bar-by-bar watchers, and independent backtest runs produce numbers
that are consistent with live behaviour (no lookahead interaction).

### Hard Stop = Midpoint

The re-entry hard stop is set to the `midpoint` of the OR (halfway between OR_high and OR_low). Rationale:
- If price reclaims the midpoint after already closing below OR_low, the bearish thesis is invalidated.
- This gives the re-entry more room than the primary hard stop (which was tighter, causing the original exit).

### Trailing Arm Condition

The trailing stop is armed only when price drops `>= effective_or_range` below the re-entry price. This prevents premature exits on shallow follow-through moves.

### `is_bearish_reentry` Flag

All rows in the results DataFrame carry `is_bearish_reentry: bool`. Re-entry rows are excluded from rolling statistics (same as `is_reversal`) so they don't skew the 60-day scoring window used for ticker selection.

### `effective_or_range`

Both the primary trade's stops and the re-entry's trailing arm use `effective_or_range`. If `or_range < avg_pre_bar_range / 4` (degenerate zero-range bars), the pre-bar average is substituted. This prevents absurdly tight stops on bars with near-zero OR.

---

## Configuration Parameters

| CLI Flag | Default | Description |
|---|---|---|
| `--bearish-reentry` | off | Enable the BEARISH re-entry feature |
| `--bearish-reentry-max-bars N` | 3 | Only re-enter if primary held ≤ N bars before stopping out |

**`max-bars` interpretation:**
- `1` — only re-enters after 1-bar stops (very tight, stopped on first bar)
- `3` — re-enters after 1–3 bar stops (recommended; captures most early exits)
- `5` — re-enters after 1–5 bar stops (slightly too permissive, marginal degradation vs 3)

---

## Code Locations

| File | Change |
|---|---|
| `op_momentum_backtest.py` | `compute_signals_with_backtest`: `effective_or_range`, bearish re-entry trade loop; `run_backtest`: wires `enable_bearish_reentry`, `bearish_reentry_max_bars` |
| `op_momentum_selector_backtest.py` | `run_selector_backtest`: wires new params; rolling stats excludes `is_bearish_reentry`; `_apply_capital_flow`: adds `br_pnl` to `cap_pnl`; `_print_daily_table`: prints `[BRE]` sub-row; `_print_stats_block`: prints re-entry count; CLI: `--bearish-reentry`, `--bearish-reentry-max-bars` |

---

## Relationship to Existing Features

| Feature | Direction after stop | Condition to trigger |
|---|---|---|
| `--reversal` | BULLISH (reverses) | `close > or_high` after BEARISH stop |
| `--bearish-reentry` | BEARISH (continues) | `close < or_low` after BEARISH early stop |

The two can coexist in the same run. On any given trade, at most one fires (mutual exclusion via `rev_entry_price`).
