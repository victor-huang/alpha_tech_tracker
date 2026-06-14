# Consolidation Breakout Signal — Design Proposal

**Status:** Proposed / paused — no implementation yet  
**Applies to:** Afternoon windows (A1, A2) — potentially any window  
**Author:** Victor Huang  
**Date:** 2026-04-24

---

## Motivation

The current A1/A2 signal fires at the close of the opening-range (OR) period: if the last OR bar closes above the midpoint + MA, enter bullish; below + MA, enter bearish. This means the entry decision is made at the **same moment** the range forms — with no post-OR confirmation.

A consolidation breakout alternative treats the A1/A2 window as a **waiting zone** and only enters when price explicitly breaks out of it in a subsequent bar. The hypothesis is that confirmed breakouts from a tight afternoon range will have better directional follow-through than raw OR momentum entries.

---

## Signal Definition

### Phase 1 — Build the consolidation zone

The first `opening_bars` bars of the window (e.g., 1 bar = 5 min at 13:15) define the consolidation zone:

```
consol_high = max(High) across consolidation bars
consol_low  = min(Low)  across consolidation bars
consol_range = consol_high - consol_low
```

If `consol_range == 0` (flat / no volume), skip — no trade.

### Phase 2 — Watch for breakout

After the consolidation period closes, monitor each subsequent 5-min bar until EOD (or a configured cutoff):

**Bullish breakout** (all conditions):
```
close > consol_high
AND close > MA20
```

**Bearish breakout** (all conditions):
```
close < consol_low
AND close < MA20
```

Signal fires on the **first bar** that satisfies the condition. If neither fires before the cutoff, no trade.

### Entry / exit mechanics

Once signal fires, position is opened identically to the current OR-breakout flow:
- `or_high = consol_high`, `or_low = consol_low`, `or_range = consol_range`
- Hard stop, fallback 20%, trailing MA stop — all unchanged
- Re-entry watchers (reversal, BRE, BUE) — unchanged
- Capital sequencing (A1 → A2 sequential) — unchanged

---

## Architecture Changes Required

### 1. `models.py` — `WindowConfig`

Add a `mode` field:

```python
@dataclass
class WindowConfig:
    label: str
    opening_start: str
    opening_bars: int
    capital_fraction: float = 1.0
    is_sequential: bool = False
    mode: str = "or_breakout"          # NEW: "or_breakout" | "consolidation_breakout"
    breakout_cutoff: str = None        # NEW: "15:50" — stop watching before EOD
```

No changes needed to `ActivePosition` or `SignalEvent` — `or_high/or_low` map directly to `consol_high/consol_low`.

### 2. `op_momentum_backtest.py`

After computing the consolidation zone from the first N bars, scan the remaining intraday bars:

```python
if win.mode == "consolidation_breakout":
    post_consol = day_from_start.iloc[opening_bars:]
    for ts, bar in post_consol.iterrows():
        if cutoff and ts.time() >= cutoff_time:
            break
        ma20_at_ts = compute_ma20_at(ts)
        if bar.Close > consol_high and bar.Close > ma20_at_ts:
            signal = BULLISH; entry_bar = bar; break
        elif bar.Close < consol_low and bar.Close < ma20_at_ts:
            signal = BEARISH; entry_bar = bar; break
```

MA values at each post-consolidation bar are already available (full bar history is pre-computed before the signal loop).

### 3. `signal_engine.py`

Add a new state dict `_watching_breakout` per window per ticker. After OR period closes in consolidation mode, store levels and flip into watching state. On each subsequent bar, check watchers before checking for new OR periods:

```python
# When opening_buf is full (consolidation period complete):
if win.mode == "consolidation_breakout":
    self._watching_breakout[label][ticker] = {
        "consol_high": or_high,
        "consol_low": or_low,
        "consol_range": or_range,
        "midpoint": midpoint,
        "cutoff_time": win.breakout_cutoff,
    }
    # do NOT fire signal yet

# On each subsequent bar arrival, before OR accumulation:
for label, watchers in self._watching_breakout.items():
    if ticker in watchers:
        w = watchers[ticker]
        if w["cutoff_time"] and bar_time >= w["cutoff_time"]:
            del watchers[ticker]; continue
        if close > w["consol_high"] and close > ma20:
            self._fire_signal(ticker, label, BULLISH, w)
            del watchers[ticker]
        elif close < w["consol_low"] and close < ma20:
            self._fire_signal(ticker, label, BEARISH, w)
            del watchers[ticker]
```

### 4. CLI plumbing

- `op_momentum_trade_engine.py` `parse_args()`: add `--consolidation-windows A1 A2` and `--breakout-cutoff 15:50`
- `_parse_windows()`: inject `mode="consolidation_breakout"` and `breakout_cutoff` into matching `WindowConfig`
- `op_momentum_selector_backtest.py`: same CLI passthrough

### Estimated scope

| File | Change |
|---|---|
| `models.py` | +2 fields to `WindowConfig` |
| `op_momentum_backtest.py` | ~30 lines — post-consolidation bar scan |
| `signal_engine.py` | ~50 lines — `_watching_breakout` state + per-bar watcher check |
| `op_momentum_trade_engine.py` | ~15 lines — CLI flag + `_parse_windows()` |
| `op_momentum_selector_backtest.py` | ~10 lines — CLI passthrough |

No new modules required.

---

## Design Questions (unresolved)

### A. Consolidation window width

A1 and A2 currently use `opening_bars=1` (a single 5-min bar). A 1-bar consolidation zone is narrow — just the high/low of that bar. Options:

- Keep `opening_bars=1` and accept the tight range (more breakout signals, noisier)
- Widen to `opening_bars=3` specifically for consolidation mode (fewer signals, tighter confirmation)
- Sweep both in backtest before deciding

### B. EOD cutoff for A2

A2 consolidation starts at 15:00. With 1 bar, the zone closes at 15:05 and watching starts with only 55 min until market close. A `--breakout-cutoff 15:50` guard prevents entering with < 10 min remaining. This should be validated in backtest — tighter cutoffs reduce signal count; looser cutoffs risk holding into the close.

### C. Midpoint filtering

The current OR signal requires `close > midpoint` (top 50%) for bullish. For consolidation breakout, a close above `consol_high` already implies that condition trivially. Midpoint filtering can be dropped — or replaced with a minimum breakout magnitude (e.g., `close > consol_high + 0.1 × consol_range`).

### D. Interaction with re-entry watchers

Re-entry signals (reversal, BRE, BUE) are created after a primary position exits and watch for re-entry relative to the original OR midpoint. These are independent of window mode and should work unchanged. Verify in backtest that A1 consolidation breakout → reversal watcher chain behaves as expected.

---

## Backtest Validation Plan (when development resumes)

1. Run baseline A1/A2 with current `or_breakout` mode over 2025-01-01 → 2025-12-31
2. Run same period with `consolidation_breakout` on A1+A2, `opening_bars=1`
3. Run with `opening_bars=3` variant
4. Compare: EV per trade, win rate, avg hold time, total return
5. Verify M1 P&L is identical across all runs (capital independence check)
6. Sweep `breakout_cutoff` values for A2: 15:30, 15:45, 15:50
