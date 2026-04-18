# Double-Down on Winner: Live Engine Implementation Plan

Port the double-down add-on leg from `op_momentum_selector_backtest.py` into the live
engine (`trade_engine.py`).

**Backtest result (IEX feed, top-2, 60/40 weights, M1+A1+A2, reversal+BRE+BRU on):**
DD wins every year across 7 years (+24 to +69pp per year). Default `--doubledown-start`
is 10 min; the full sweep is documented in `dev_plan/double_down_on_winner.md`.

---

## How It Works

At `OR close + doubledown_start_min` minutes per window:

1. Scan all primary positions in the window — find stopped-out ones (`hard_stop` or
   `fallback_20pct`) that have **no active re-entry/reversal leg**.
2. Find the highest-ranked (lowest rank number) survivor still open.
3. Compute freed capital = sum of returned capital from all eligible stopouts.
4. If freed capital > 0 and a survivor exists: enter an add-on leg on the survivor.

**Add-on leg parameters:**

| Parameter | Value |
|---|---|
| Entry price | Close of the DD bar (current bar at check time) |
| Hard stop | Same as entry price (break-even protection) |
| Hard stop armed | Immediately (`initial_hard_stop_armed=True`) |
| Trailing stop | Same MA logic as the primary position |
| Capital deployed | 100% of freed capital (bypasses `CAPITAL_PER_SYMBOL`) |

DD fires **once per window per day**. If no eligible stopout + survivor pair exists at
the check time, DD is skipped silently.

---

## Files Changed

| File | Change type |
|---|---|
| `models.py` | Add `is_doubledown_addon: bool = False` to `ActivePosition` |
| `position_sizer.py` | Add `full_budget: bool = False` param to `compute()` and `compute_stock()` |
| `trade_engine.py` | New state, three new methods, hook into drain and replay loop |
| `op_momentum_trade_engine.py` | Two new CLI flags wired to engine constructor |

---

## Step 1 — `models.py`

Add one field to `ActivePosition`:

```python
is_doubledown_addon: bool = False
# True for the add-on leg entered by the double-down check.
# Used to exclude DD positions from _window_primary_deployed tracking
# and to label them in logs and the daily summary.
```

---

## Step 2 — `position_sizer.py`

Add `full_budget: bool = False` to both `compute()` and `compute_stock()`. When True,
the entire `window_budget` is used as the position budget (bypasses `CAPITAL_PER_SYMBOL`).

```python
def compute(self, option_symbol, capital_weight=_D("1"), window_budget=None,
            mock_stock_price=None, full_budget: bool = False):
    if full_budget and window_budget is not None:
        budget = window_budget
    elif window_budget is not None:
        budget = window_budget * CAPITAL_PER_SYMBOL * capital_weight
    else:
        buying_power = ...
        budget = buying_power * CAPITAL_PER_SYMBOL * capital_weight
    contracts = max(1, int(budget / (mid_price * 100)))
    ...
```

The `full_budget=True` path is used only for DD add-on entries. All other callers are
unaffected (default False).

---

## Step 3 — `trade_engine.py`

### 3a. New constructor parameters

```python
enable_doubledown: bool = False,
doubledown_start_min: int = 10,
```

### 3b. New instance state (set in `__init__`)

```python
self._enable_doubledown: bool = enable_doubledown
self._doubledown_start_min: int = doubledown_start_min
self._dd_timers: dict = {}   # {window_label: threading.Timer}
self._dd_fired: set = set()  # window labels where DD already fired today
```

### 3c. New method: `_compute_position_returned_capital(pos)`

Computes capital actually returned from a single closed position (principal + P&L).
Mirrors the backtest formula in `_compute_dd_deployed`.

```python
def _compute_position_returned_capital(self, pos: ActivePosition) -> _D:
    entry = pos.simulated_entry_mid or pos.entry_stock_price
    exit_ = pos.simulated_exit_mid or pos.exit_fill_price
    if not entry or entry <= 0 or not exit_ or pos.slot_capital is None:
        return pos.slot_capital or _D("0")
    if pos.trade_type == "stock":
        raw = (exit_ - entry) if pos.signal == "BULLISH" else (entry - exit_)
        return pos.slot_capital + pos.slot_capital / entry * raw
    else:
        raw = (exit_ - entry) if pos.signal == "BULLISH" else (entry - exit_)
        return pos.slot_capital + _D(pos.contracts) * _D("100") * raw
```

### 3d. New method: `_schedule_dd_check_for_window(win)`

Starts a `threading.Timer` that fires `_check_doubledown_for_window` at the right time.
Only used in live/mock mode — replay uses inline bar-by-bar checks instead (see Step 3f).

```python
def _schedule_dd_check_for_window(self, win: WindowConfig):
    if not self._enable_doubledown or win.label in self._dd_fired:
        return
    today = _now_et().date()
    opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
    or_open = ET.localize(datetime.combine(today, opening_start_t))
    or_close = or_open + timedelta(minutes=win.opening_bars * 5)
    dd_check_time = or_close + timedelta(minutes=self._doubledown_start_min)
    eod_h, eod_m = [int(x) for x in EOD_EXIT_TIME.split(":")]
    eod_time = ET.localize(datetime.combine(today, datetime.strptime(EOD_EXIT_TIME, "%H:%M").time()))
    if dd_check_time >= eod_time:
        logger.info("DD [%s]: check time %s is at/after EOD, skipping", win.label, dd_check_time.strftime("%H:%M"))
        return
    delay = (dd_check_time - _now_et()).total_seconds()
    if delay <= 0:
        logger.info("DD [%s]: check time already passed, skipping", win.label)
        return
    t = threading.Timer(delay, self._check_doubledown_for_window, args=(win,))
    t.daemon = True
    t.start()
    self._dd_timers[win.label] = t
    logger.info("DD [%s]: check scheduled at %s ET (+%d min)", win.label, dd_check_time.strftime("%H:%M"), self._doubledown_start_min)
```

### 3e. New method: `_check_doubledown_for_window(win)`

The core DD logic. Scans positions, computes freed capital, enters the add-on leg.

```python
def _check_doubledown_for_window(self, win: WindowConfig):
    label = win.label
    if label in self._dd_fired:
        return
    self._dd_fired.add(label)

    with self._monitor._lock:
        all_positions = list(self._monitor._positions)

    # All primary (non-re-entry) positions in this window
    window_primary = [
        p for p in all_positions
        if p.window_label == label
        and p.trailing_arm_price is None
        and not p.is_doubledown_addon
    ]

    survivors = [p for p in window_primary if not p.is_closed]
    if not survivors:
        logger.info("DD [%s]: no survivors, skipping", label)
        return

    # Ranks that have an open re-entry leg — their freed capital is already committed
    open_reentry_ranks = {
        p.rank for p in all_positions
        if p.window_label == label
        and not p.is_closed
        and p.trailing_arm_price is not None
    }

    stopouts = [
        p for p in window_primary
        if p.is_closed
        and p.exit_reason in ("hard_stop", "fallback_20pct")
        and p.rank not in open_reentry_ranks
        and p.slot_capital is not None
    ]

    if not stopouts:
        logger.info("DD [%s]: no eligible stopouts, skipping", label)
        return

    freed_capital = sum(
        (self._compute_position_returned_capital(p) for p in stopouts), _D("0")
    )
    freed_ranks = [p.rank for p in stopouts]

    if freed_capital <= 0:
        logger.info("DD [%s]: freed capital is zero, skipping", label)
        return

    # Highest-ranked (lowest rank number) survivor is the winner
    winner = min(survivors, key=lambda p: p.rank)

    latest_bar = self._signal_engine.get_latest_bar(winner.ticker)
    if latest_bar is None:
        logger.warning("DD [%s]: no bar available for %s, skipping", label, winner.ticker)
        return
    dd_entry_price = _D(str(latest_bar["Close"]))

    logger.info(
        "DD [%s] firing: winner=%s freed=%.2f from ranks %s entry=%.2f",
        label, winner.ticker, float(freed_capital), freed_ranks, float(dd_entry_price),
    )
    _notify(
        f"[DD] [{label}] ADD-ON {winner.ticker} freed=${float(freed_capital):.0f}"
        f" from rank(s) {freed_ranks} @ ~${float(dd_entry_price):.2f} (break-even stop)"
    )

    # Subtract freed capital from _window_returned to prevent double-counting
    # with sequential window budgets (the capital is being re-deployed, not free).
    with self._returned_lock:
        current = self._window_returned.get(label, _D("0"))
        self._window_returned[label] = max(_D("0"), current - freed_capital)

    event = SignalEvent(
        ticker=winner.ticker,
        signal=winner.signal,
        entry_price=dd_entry_price,
        stock_price=dd_entry_price,
        or_high=winner.or_high,
        or_low=winner.or_low,
        or_range=winner.or_range,
        ma50_at_signal=dd_entry_price,
        signal_bar_time=latest_bar.name if hasattr(latest_bar, "name") else None,
    )

    with self._signal_lock:
        self._window_state[label]["open_position_count"] += 1

    self._enter_position(
        event,
        rank=winner.rank,
        window_label=label,
        window_budget=freed_capital,
        hard_stop_override=dd_entry_price,
        initial_hard_stop_armed=True,
        reentry_type="doubledown",
    )
```

### 3f. Changes to `_enter_stock_position` / `_enter_option_position`

Two changes needed:

**a) Pass `full_budget=True` to sizer for DD add-ons:**

```python
full_budget = (reentry_type == "doubledown")
contracts, limit_price = sizer.compute(
    option_symbol, capital_weight, window_budget,
    mock_stock_price=mock_stock_price,
    full_budget=full_budget,
)
```

**b) Exclude DD add-ons from `_window_primary_deployed` tracking:**

```python
is_reentry = trailing_arm_price is not None or reentry_type == "doubledown"
if not is_reentry and slot_capital is not None:
    with self._returned_lock:
        ...
        self._window_primary_deployed[window_label] += slot_capital
```

**c) Set `is_doubledown_addon` on the created position:**

```python
pos = ActivePosition(
    ...
    is_doubledown_addon=(reentry_type == "doubledown"),
)
```

### 3g. Hook `_schedule_dd_check_for_window` into `_drain_pending_signals_for_window`

Called at the end of the drain, after all initial positions are entered:

```python
def _drain_pending_signals_for_window(self, win: WindowConfig):
    ...
    for rank, (score, ticker, event) in enumerate(scored):
        ...
        self._enter_position(event, rank=rank, ...)

    # Schedule DD check after all initial positions are entered
    self._schedule_dd_check_for_window(win)
```

### 3h. Replay mode — inline DD check in `_on_bar`

In `run_replay()`, `threading.Timer` doesn't work against a virtual clock.
Add a `_dd_check_times` dict computed once before the replay loop:

```python
_dd_check_times = {}
for win in self._windows:
    opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
    or_open = ET.localize(datetime.combine(replay_date, opening_start_t))
    or_close = or_open + timedelta(minutes=win.opening_bars * 5)
    _dd_check_times[win.label] = or_close + timedelta(minutes=self._doubledown_start_min)

_dd_checked_windows = set()

def _on_bar(ticker):
    for win in self._windows:
        lbl = win.label
        if (self._enable_doubledown
                and lbl not in _dd_checked_windows
                and lbl in _drained_windows  # only after OR has been drained
                and _now_et() >= _dd_check_times[lbl]):
            _dd_checked_windows.add(lbl)
            self._check_doubledown_for_window(win)
    # existing drain + monitor calls follow
    ...
```

### 3i. Reset DD state at run/replay start

In `run()` and `run_replay()`, reset per-session state alongside the other daily resets:

```python
self._dd_timers = {}
self._dd_fired = set()
```

---

## Step 4 — `op_momentum_trade_engine.py`

### 4a. CLI flags

```python
parser.add_argument(
    "--doubledown",
    action="store_true",
    default=False,
    help="Enable double-down add-on leg when a co-pick stops out early.",
)
parser.add_argument(
    "--doubledown-start",
    type=int,
    default=10,
    dest="doubledown_start_min",
    metavar="MINUTES",
    help=(
        "Minutes after OR close to fire the double-down check and enter the add-on leg. "
        "Must be a multiple of 5. Default: 10."
    ),
)
```

### 4b. Wire to engine constructor

```python
OpMomentumTradeEngine(
    ...
    enable_doubledown=args.doubledown,
    doubledown_start_min=args.doubledown_start_min,
)
```

### 4c. Log summary line

Add to the startup log block (alongside reversal/re-entry lines):

```python
f"  Double-down  : {'on (+' + str(args.doubledown_start_min) + 'min, break-even stop)' if args.doubledown else 'off'}"
```

---

## Capital Accounting Invariant

The sequential window budget for A1 must equal all M1 capital currently either:
- Freely available (returned from closed positions and NOT redeployed into DD), or
- Tied up in still-open M1 primary and DD add-on positions.

The deduction in `_check_doubledown_for_window` (Step 3e) preserves this invariant:

| Time | `_window_returned["M1"]` | `open_primary_capital` | A1 budget |
|---|---|---|---|
| Rank-2 stops out | $3,600 | $6,000 (rank-1) | $9,600 |
| DD add-on enters | $0 (deducted) | $6,000 + $3,600 = $9,600 | $9,600 ✓ |
| DD add-on exits (+$200 P&L) | $3,800 (returned) | $6,000 (rank-1) | $9,800 ✓ |

Without the deduction, A1 would incorrectly see $13,200 ($3,600 + $6,000 + $3,600).

---

## Pre-Implementation Checks (from RETRO_APRIL_2026.md)

| Check | DD-specific concern |
|---|---|
| **State must latch** | `_dd_fired` is a set — DD fires once per window per day, never re-evaluated |
| **Cleanup scope** | `_dd_timers` keyed by `window_label`, not ticker |
| **EOD guard** | `_schedule_dd_check_for_window` skips if check time >= `EOD_EXIT_TIME` |
| **Degenerate input** | Guard: no survivors, freed_capital == 0, no latest bar available |
| **Re-entry exclusion** | Ranks with an open re-entry/reversal leg are excluded from stopout pool |
| **Derived fields** | `is_doubledown_addon=True` prevents DD from being counted in `_window_primary_deployed` |
| **Replay parity** | Inline bar check in `_on_bar` matches timer-based live check — both fire at the same virtual time |

---

## Tests to Write

| Test class | Scenario |
|---|---|
| `TestDoubleDown` | rank-2 stops out, rank-1 survives → DD fires, add-on entered with full freed capital |
| `TestDoubleDown` | rank-2 stops out but has open re-entry → DD skipped (excluded rank) |
| `TestDoubleDown` | both positions stop out → no survivor, DD skipped |
| `TestDoubleDown` | both positions survive → no stopout, DD skipped |
| `TestDoubleDown` | DD fires for M1; A1 budget = rank-1 slot + DD addon slot (no double-count) |
| `TestDoubleDown` | DD check time >= EOD → timer never started |
| `TestDoubleDown` | replay mode: DD fires inline at correct bar, not before drain |

---

## CLI Usage Example

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --top 2 --rank-weighted-sizing 60 40 \
  --doubledown --doubledown-start 10 \
  --feed iex
```
