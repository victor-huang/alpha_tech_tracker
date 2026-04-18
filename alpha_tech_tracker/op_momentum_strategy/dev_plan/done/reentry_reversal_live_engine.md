# Re-entry & Reversal: Live Engine Implementation Plan

Port the three second-leg trade patterns from the backtest
(`op_momentum_selector_backtest.py` / `op_momentum_backtest.py`) into the live engine
(`trade_engine.py`, `position_monitor.py`).

---

## Pattern Reference

| Pattern | Primary signal | Trigger condition | New direction | Hard stop | Trailing arm |
|---|---|---|---|---|---|
| **Reversal** | BEARISH | primary stops out ≤ N bars AND price > OR\_high | BULLISH | midpoint (armed immediately) | entry + OR\_range |
| **Bearish re-entry** | BEARISH | primary stops out ≤ N bars AND reversal did NOT fire AND price < OR\_low | BEARISH | midpoint | entry − OR\_range |
| **Bullish re-entry** | BULLISH | primary stops out ≤ N bars AND price > OR\_high | BULLISH | midpoint (armed immediately) | entry + OR\_range |

Reversal and bullish re-entry share identical entry/exit mechanics; they differ only in which
primary signal they follow.

Eligible exit reasons for all three: `hard_stop` or `fallback_20pct`.

---

## Files Changed

| File | Change type |
|---|---|
| `models.py` | Extend `ActivePosition`; add `ReentryWatcher` dataclass |
| `position_monitor.py` | Track `bars_held`; create watchers on close; scan watchers each bar |
| `trade_engine.py` | New params; `_enter_reentry()` callback; pass overrides to `_enter_position()` |
| `op_momentum_trade_engine.py` | Six new CLI flags |
| `tests/op_momentum_trade_engine/test_position_monitor.py` | New `TestReentryWatcher` class |
| `tests/op_momentum_trade_engine/test_trade_engine.py` | Two new re-entry tests |

---

## Step 1 — `models.py`

### 1a. Extend `ActivePosition`

Add three fields:

```python
bars_held: int = 0
# Incremented each bar while the position is open (no exit fired).
# Used by PositionMonitor to check re-entry eligibility on close.

trailing_arm_price: Optional[Decimal] = None
# When set, the MA20/MA50 trailing stop is gated behind this price level.
# Re-entry positions set this to entry ± or_range; primary positions leave it None
# (existing behaviour: trailing fires as soon as MA crosses hard_stop_price).

window_label: str = "W1"
rank: int = 0
window_budget: Optional[Decimal] = None
# Carried from entry so the re-entry callback can open the second-leg position
# under the same window/rank/budget context.
```

### 1b. Add `ReentryWatcher` dataclass

```python
@dataclass
class ReentryWatcher:
    ticker: str
    reentry_type: str           # "reversal" | "bearish_reentry" | "bullish_reentry"
    primary_signal: str         # "BEARISH" or "BULLISH"
    or_high: Decimal
    or_low: Decimal
    or_range: Decimal
    midpoint: Decimal
    window_label: str
    rank: int
    window_budget: Optional[Decimal]
    primary_exit_bar_time: Optional[datetime] = None
    # The bar timestamp when the primary trade closed.
    # Re-entry trigger is skipped on this same bar to match backtest behaviour
    # (backtest scans post_open.iloc[exit_bar_idx + 1:]).
```

---

## Step 2 — `position_monitor.py`

### 2a. New `__init__` parameters

```python
enable_reversal: bool = False
reversal_max_bars: int = 3
enable_bearish_reentry: bool = False
bearish_reentry_max_bars: int = 3
enable_bullish_reentry: bool = False
bullish_reentry_max_bars: int = 5
re_entry_callback = None    # callable(watcher: ReentryWatcher, trigger_price: Decimal)
```

Store as `self._enable_reversal`, etc. Add `self._reentry_watchers: list = []`.

### 2b. `_evaluate_stop()` — track `bars_held`

At the end of the method, in the path where no `exit_reason` was set:

```python
if exit_reason is None:
    pos.bars_held += 1
```

### 2c. `_close_position()` — spawn re-entry watcher

After `pos.is_closed = True` and before placing the exit order, call
`self._maybe_create_reentry_watcher(pos, reason)`.

```python
def _maybe_create_reentry_watcher(self, pos: ActivePosition, reason: str):
    if reason not in ("hard_stop", "fallback_20pct"):
        return

    midpoint = (pos.or_high + pos.or_low) / _D("2")

    # Reversal takes priority over bearish re-entry for the same closed position.
    if (
        self._enable_reversal
        and pos.signal == "BEARISH"
        and pos.bars_held <= self._reversal_max_bars
    ):
        self._reentry_watchers.append(ReentryWatcher(
            ticker=pos.ticker,
            reentry_type="reversal",
            primary_signal="BEARISH",
            or_high=pos.or_high,
            or_low=pos.or_low,
            or_range=pos.or_range,
            midpoint=midpoint,
            window_label=pos.window_label,
            rank=pos.rank,
            window_budget=pos.window_budget,
            primary_exit_bar_time=pos.entry_bar_time,
        ))
        return  # reversal and bearish re-entry are mutually exclusive

    if (
        self._enable_bearish_reentry
        and pos.signal == "BEARISH"
        and pos.bars_held <= self._bearish_reentry_max_bars
    ):
        self._reentry_watchers.append(ReentryWatcher(
            ticker=pos.ticker,
            reentry_type="bearish_reentry",
            primary_signal="BEARISH",
            or_high=pos.or_high,
            or_low=pos.or_low,
            or_range=pos.or_range,
            midpoint=midpoint,
            window_label=pos.window_label,
            rank=pos.rank,
            window_budget=pos.window_budget,
            primary_exit_bar_time=pos.entry_bar_time,
        ))

    if (
        self._enable_bullish_reentry
        and pos.signal == "BULLISH"
        and pos.bars_held <= self._bullish_reentry_max_bars
    ):
        self._reentry_watchers.append(ReentryWatcher(
            ticker=pos.ticker,
            reentry_type="bullish_reentry",
            primary_signal="BULLISH",
            or_high=pos.or_high,
            or_low=pos.or_low,
            or_range=pos.or_range,
            midpoint=midpoint,
            window_label=pos.window_label,
            rank=pos.rank,
            window_budget=pos.window_budget,
            primary_exit_bar_time=pos.entry_bar_time,
        ))
```

### 2d. `on_bar()` — scan watchers

After the existing position loop, call:

```python
self._check_reentry_watchers(ticker, close, bar_time)
```

```python
def _check_reentry_watchers(self, ticker: str, close: Decimal, bar_time):
    fired = []
    for w in self._reentry_watchers:
        if w.ticker != ticker:
            continue
        # Skip the bar that closed the primary trade
        if w.primary_exit_bar_time is not None and bar_time == w.primary_exit_bar_time:
            continue
        if w.reentry_type in ("reversal", "bullish_reentry"):
            triggered = close > w.or_high
        else:  # bearish_reentry
            triggered = close < w.or_low
        if triggered:
            fired.append(w)

    for w in fired:
        self._reentry_watchers.remove(w)
        if self._re_entry_callback:
            threading.Thread(
                target=self._re_entry_callback,
                args=(w, close),
                daemon=True,
            ).start()
```

Spawning a thread matches how `_enter_position` is already called from
`_signal_selection_loop_for_window` — it involves I/O (contract selection, order placement)
and must not block the monitor loop.

### 2e. `_evaluate_stop()` — honour `trailing_arm_price`

Gate MA trailing stop checks behind the arm threshold for re-entry positions:

```python
def _trailing_armed(self, pos: ActivePosition, close: Decimal) -> bool:
    if pos.trailing_arm_price is None:
        return True   # primary positions: arm is implicit (MA crossing hard_stop_price)
    if pos.signal == "BULLISH":
        return close >= pos.trailing_arm_price
    return close <= pos.trailing_arm_price
```

In `_evaluate_stop()`, wrap the MA20/MA50 trailing stop checks:

```python
if self._trailing_armed(pos, close):
    # ... existing MA20 / MA50 trailing stop logic ...
```

### 2f. `close_all()` — clear watchers EOD

```python
self._reentry_watchers.clear()
```

---

## Step 3 — `trade_engine.py`

### 3a. New `__init__` parameters

```python
enable_reversal: bool = False
reversal_max_bars: int = 3
enable_bearish_reentry: bool = False
bearish_reentry_max_bars: int = 3
enable_bullish_reentry: bool = False
bullish_reentry_max_bars: int = 5
```

Store as instance attributes.

### 3b. `_enter_position()` — add `hard_stop_override` and `trailing_arm_price` params

```python
def _enter_position(
    self,
    event: SignalEvent,
    rank: int = 0,
    window_label: str = "W1",
    window_budget=None,
    hard_stop_override=None,       # new: used by re-entry to set midpoint as stop
    trailing_arm_price=None,       # new: passed through to ActivePosition
):
```

When `hard_stop_override` is set, use it instead of the normal OR-range calculation:

```python
if hard_stop_override is not None:
    bull_hard_stop = hard_stop_override
    bear_hard_stop = hard_stop_override
```

Pass `trailing_arm_price` to `ActivePosition(trailing_arm_price=trailing_arm_price, ...)`.

Also set `window_label`, `rank`, and `window_budget` on the constructed `ActivePosition`.

### 3c. Add `_enter_reentry()` callback

```python
def _enter_reentry(self, watcher: ReentryWatcher, trigger_price: Decimal):
    reentry_signal = (
        "BEARISH" if watcher.reentry_type == "bearish_reentry" else "BULLISH"
    )
    trailing_arm = (
        trigger_price + watcher.or_range
        if reentry_signal == "BULLISH"
        else trigger_price - watcher.or_range
    )
    event = SignalEvent(
        ticker=watcher.ticker,
        signal=reentry_signal,
        entry_price=trigger_price,
        stock_price=trigger_price,
        or_high=watcher.or_high,
        or_low=watcher.or_low,
        or_range=watcher.or_range,
        ma50_at_signal=trigger_price,
    )
    logger.info(
        "RE-ENTRY [%s] %s %s trigger=%.2f hard_stop=%.2f trailing_arm=%.2f",
        watcher.reentry_type,
        watcher.ticker,
        reentry_signal,
        float(trigger_price),
        float(watcher.midpoint),
        float(trailing_arm),
    )
    self._enter_position(
        event,
        rank=watcher.rank,
        window_label=watcher.window_label,
        window_budget=watcher.window_budget,
        hard_stop_override=watcher.midpoint,
        trailing_arm_price=trailing_arm,
    )
```

### 3d. Pass re-entry config to `PositionMonitor` in `run()`

```python
self._monitor = PositionMonitor(
    ...,
    enable_reversal=self._enable_reversal,
    reversal_max_bars=self._reversal_max_bars,
    enable_bearish_reentry=self._enable_bearish_reentry,
    bearish_reentry_max_bars=self._bearish_reentry_max_bars,
    enable_bullish_reentry=self._enable_bullish_reentry,
    bullish_reentry_max_bars=self._bullish_reentry_max_bars,
    re_entry_callback=self._enter_reentry,
)
```

---

## Step 4 — `op_momentum_trade_engine.py` (CLI)

Add to `_parse_args()`:

```
--reversal                         action=store_true, default=False
--reversal-max-bars INT            default=3
--bearish-reentry                  action=store_true, default=False
--bearish-reentry-max-bars INT     default=3
--bullish-reentry                  action=store_true, default=False
--bullish-reentry-max-bars INT     default=5
```

Pass all six to `OpMomentumTradeEngine(...)`.

---

## Step 5 — Tests

### `test_position_monitor.py` — new class `TestReentryWatcher`

| Test | What it verifies |
|---|---|
| `test_bars_held_increments_while_open` | `bars_held` goes from 0 → 1 → 2 as bars arrive without stop |
| `test_reversal_watcher_created_on_bearish_hard_stop` | BEARISH position, hard_stop within 3 bars → watcher in `_reentry_watchers` |
| `test_reversal_watcher_not_created_beyond_max_bars` | `bars_held=4`, `reversal_max_bars=3` → no watcher |
| `test_reversal_not_created_on_trailing_ma_exit` | exit_reason=trailing_stop_ma20 → no watcher |
| `test_reversal_fires_when_price_crosses_or_high` | watcher exists, bar arrives with close > or_high → callback called with correct watcher |
| `test_reversal_skips_primary_exit_bar` | trigger close arrives on the same bar_time as primary exit → not fired yet; fires on next bar |
| `test_bearish_reentry_watcher_suppressed_when_reversal_enabled` | both flags on, BEARISH stops out → only reversal watcher added (not bearish re-entry) |
| `test_bearish_reentry_fires_when_price_crosses_or_low` | bearish_reentry watcher, close < or_low → callback called |
| `test_bullish_reentry_watcher_created_on_bullish_hard_stop` | BULLISH position, hard_stop within 5 bars → watcher |
| `test_watchers_cleared_on_close_all` | watchers exist, `close_all()` called → `_reentry_watchers` empty |

### `test_trade_engine.py` — two new tests

| Test | What it verifies |
|---|---|
| `test_enter_reentry_reversal_builds_bullish_signal` | `_enter_reentry` with `reentry_type="reversal"` calls `_enter_position` with `signal="BULLISH"`, `hard_stop_override=midpoint` |
| `test_enter_reentry_bearish_reentry_builds_bearish_signal` | `reentry_type="bearish_reentry"` → `signal="BEARISH"`, correct `trailing_arm_price` |

---

## Implementation Order

1. `models.py` — new fields on `ActivePosition`, `ReentryWatcher` dataclass
2. `position_monitor.py` — `bars_held`, watcher creation, `_check_reentry_watchers`, `_trailing_armed`, EOD cleanup
3. `trade_engine.py` — new params, `_enter_reentry`, updated `_enter_position` signature, pass to `PositionMonitor`
4. `op_momentum_trade_engine.py` — CLI flags
5. Tests

## Open Questions / Trade-offs

- **Re-entry position sizing**: currently inherits `rank` and `window_budget` from the primary.
  A tighter budget (e.g. half the primary) could be added via a `reentry_capital_fraction` param
  if warranted by backtest analysis.
- **Multiple re-entries per day**: the current plan allows at most one watcher per closed position.
  Chaining (re-entry stops out → another re-entry) is not modelled in the backtest and is not
  planned here.
- **Reversal + bullish re-entry on same ticker**: if both flags are on and a BULLISH primary stops
  out, only a bullish re-entry watcher is created (reversal only follows BEARISH primaries).
  No conflict.
