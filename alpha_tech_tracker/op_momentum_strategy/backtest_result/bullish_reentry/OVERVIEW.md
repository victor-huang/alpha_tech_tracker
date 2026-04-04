# BULLISH Re-Entry Feature — Implementation Overview

## Motivation

The BULLISH re-entry is the symmetric counterpart to the BEARISH re-entry (`--bearish-reentry`).

After a BULLISH primary trade stops out early on a pullback, the market sometimes resumes higher and breaks above OR_high — the full opening range breakout that the primary trade originally anticipated. The BULLISH re-entry catches this continuation move.

---

## What It Does

When a BULLISH primary trade stops out early, the strategy watches for price to re-confirm the bullish setup:

1. **Eligibility check** — A re-entry is considered when:
   - Signal is BULLISH
   - The primary exit reason is `hard_stop` or `fallback_20pct`
   - The primary trade was held for at most `bullish_reentry_max_bars` bars

2. **Re-entry trigger** — Scans bars after the primary exit for the first bar where `close > or_high` (full OR breakout confirmed)

3. **Re-entry trade management**:
   - Entry: closing price of the first bar above OR_high
   - Hard stop: `midpoint` (falling back to midpoint = bullish thesis dead)
   - Trailing arm: position is armed when price rises `>= effective_or_range` above entry
   - Trailing exit (MA20): armed AND `bar_ma20 > midpoint` AND `close < bar_ma20`
   - EOD: force-close at 3:55 PM ET

4. **P&L accounting**: `bru_pnl` is added to `cap_pnl` using the same `slot_capital` as the primary trade.

---

## Design Decisions

### Trigger: `close > or_high` (not a relaxed threshold)

Two relaxed thresholds were evaluated before settling on `close > or_high`:

| Trigger | Nov 2025 Return | 2025 Return | BRU WR |
|---|---|---|---|
| `close > or_low + 0.6 × or_range` | +17.88% | +271.07% | 30% |
| `close > or_low + 0.8 × or_range` | +16.32% | +266.57% | 34% |
| `close > or_high` | +16.77% | **+269.69%** | **38%** |

`0.8×` underperforms the BRE-alone baseline in 2025. `0.6×` adds return but at a 30% win rate. `> or_high` has the highest win rate and is the cleanest signal — price must break out above the entire opening range, which is strong directional confirmation.

### Hard Stop = Midpoint

If price falls back to the OR midpoint after already breaking above OR_high, the bullish momentum is broken. Midpoint gives the trade meaningful room (entry is above OR_high, stop is at midpoint = ~50% of OR range).

### Trailing Arm Condition

Armed when price rises `>= effective_or_range` above the re-entry price. Prevents premature exits on shallow follow-through.

### No Mutual Exclusion Needed

Unlike BRE (which is mutually exclusive with `--reversal`), BRU has no competing feature — there is no "BULLISH reversal to BEARISH" pattern implemented. BRU fires independently on any eligible BULLISH primary stop-out.

### `is_bullish_reentry` Flag

All rows carry `is_bullish_reentry: bool`. Re-entry rows are excluded from rolling statistics so they don't skew the 60-day scoring window.

---

## Configuration Parameters

| CLI Flag | Default | Description |
|---|---|---|
| `--bullish-reentry` | off | Enable the BULLISH re-entry feature |
| `--bullish-reentry-max-bars N` | 5 | Only re-enter if primary held ≤ N bars before stopping out |

---

## Comparison with BEARISH Re-Entry

| Feature | BEARISH re-entry (`--bearish-reentry`) | BULLISH re-entry (`--bullish-reentry`) |
|---|---|---|
| Primary signal | BEARISH | BULLISH |
| Re-entry trigger | `close < or_low` | `close > or_high` |
| Hard stop | midpoint | midpoint |
| Trailing arm | drop `≥ effective_or_range` from entry | rise `≥ effective_or_range` from entry |
| Mutual exclusion | yes (with `--reversal`) | no |
| Typical win rate | 56–71% | 38–44% |
| Tag in daily table | `[BRE]` | `[BRU]` |

BRE wins at a higher rate because `close < or_low` is a smaller incremental move from a BEARISH entry (already at the bottom 20% of OR). BRU's trigger `close > or_high` requires a larger round trip — stop-out then full breakout — so it fires less cleanly but still adds meaningful return every year.

---

## Code Locations

| File | Change |
|---|---|
| `op_momentum_backtest.py` | `compute_signals_with_backtest`: `bru_threshold = or_high`, bullish re-entry trade loop; `run_backtest`: wires `enable_bullish_reentry`, `bullish_reentry_max_bars` |
| `op_momentum_selector_backtest.py` | `run_selector_backtest`: wires new params; rolling stats excludes `is_bullish_reentry`; `_apply_capital_flow`: adds `bru_pnl` to `cap_pnl`; `_print_daily_table`: prints `[BRU]` sub-row; `_print_stats_block`: prints bullish re-entry count; CLI: `--bullish-reentry`, `--bullish-reentry-max-bars` |
