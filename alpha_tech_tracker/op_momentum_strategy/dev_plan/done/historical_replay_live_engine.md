# Historical Replay Mode — Live Trade Engine

Run the live engine against a past trading date using cached Alpaca 5-min bar
data, so the full signal → entry → position-monitor → exit flow can be validated
against backtest results without waiting for a live market session.

---

## Goal

After enabling features like reversal / re-entry in the live engine, we want to
confirm they produce the same trades (entry price, exit reason, P&L direction)
as the corresponding backtest run on the same date. The replay mode feeds
historical bars through the identical code paths used in production, exposing
any divergence between backtest logic and live-engine logic.

---

## How the Live Engine Ingests Bars (Current Architecture)

```
Alpaca WebSocket
    └── StockDataStream.subscribe_bars()
            └── LiveSignalEngine._handle_bar(bar)        # async, per 1-min bar
                    └── _aggregate_bars()                 # group into 5-min bars
                            └── _process_five_min_bar()  # update history + MAs
                                    └── _try_fire_signal() → on_signal callback
                                                              ↓
                                            OpMomentumTradeEngine._on_signal_for_window()
                                                              ↓
                                            _signal_selection_loop_for_window() (deadline thread)
                                                              ↓
                                            _enter_position() → PositionMonitor.add_position()

_monitor_loop() [main thread, every 30s]
    └── PositionMonitor.on_bar(ticker)
            └── signal_engine.get_latest_bar(ticker)  # reads latest bar already in _history
                    └── _evaluate_stop() → exit or bars_held++
                            └── _check_reentry_watchers()
```

The WebSocket is the only real-time dependency. Everything downstream is
deterministic given the bar stream. Replacing the WebSocket with a historical
feed is sufficient to replay a full session.

---

## Implementation Plan

### Overview

Add a `--replay-date YYYY-MM-DD` flag to `op_momentum_trade_engine.py` that:

1. Fetches 5-min bars for the target date from the Alpaca historical API (same
   call used by the backtest cache, so already warm in most cases)
2. Runs ticker selection against the target date's rolling lookback (same
   `TickerSelector` path, pointed at historical data)
3. Constructs `LiveSignalEngine` and `PositionMonitor` exactly as in live mode
4. Replaces the WebSocket stream with a `BarReplayDriver` that injects bars in
   order through `signal_engine._process_five_min_bar()` (5-min bars directly,
   no 1-min aggregation needed)
5. Replaces all `datetime.now(ET)` calls with a `ReplayClock` that returns
   timestamps derived from the current bar being replayed
6. Prints a trade summary at the end in the same format as a live session

---

### Step 1 — `ReplayClock` utility  (`models.py` or new `replay.py`)

A thin wrapper that makes `datetime.now(ET)` return a controlled value. All
call sites that currently call `datetime.now(ET)` will be updated to call
`_now_et()` from a module-level function that the replay mode can swap out.

```python
_clock: Optional[Callable[[], datetime]] = None

def _now_et() -> datetime:
    if _clock is not None:
        return _clock()
    return datetime.now(ET)

def set_replay_clock(fn: Callable[[], datetime]):
    global _clock
    _clock = fn

def clear_replay_clock():
    global _clock
    _clock = None
```

**Call sites to update** (replace `datetime.now(ET)` with `_now_et()`):

| File | Line(s) | Purpose |
|---|---|---|
| `signal_engine.py` | 103 | `_session_date` initialisation |
| `signal_engine.py` | 235 | Regime filter date gate |
| `signal_engine.py` | 376 | Bar date check in `_handle_bar` |
| `signal_engine.py` | 467 | Regime calculation start date |
| `trade_engine.py` | 74 | Ticker selection date |
| `trade_engine.py` | 216 | Window state deadline initialisation |
| `trade_engine.py` | 527 | Signal buffering deadline check |
| `trade_engine.py` | 724–725 | EOD gate in `_monitor_loop` |

All existing live behaviour is unchanged — `_now_et()` falls through to
`datetime.now(ET)` when no clock is set.

---

### Step 2 — `BarReplayDriver`  (new file `replay.py`)

Fetches historical 5-min bars and drives them into the signal engine one bar at
a time, advancing the replay clock per bar.

```python
@dataclass
class BarReplayDriver:
    tickers: list
    replay_date: date
    signal_engine: "LiveSignalEngine"
    on_bar_injected: Optional[Callable] = None  # hook for position monitor

    def run(self):
        bars = self._fetch_bars()        # returns {ticker: [_FiveMinBar, ...]}
        timeline = self._merge_timeline(bars)  # sorted by timestamp

        for bar in timeline:
            set_replay_clock(lambda ts=bar.timestamp: ts)
            self.signal_engine._process_five_min_bar(bar)
            if self.on_bar_injected:
                self.on_bar_injected(bar.symbol)

        clear_replay_clock()

    def _fetch_bars(self) -> dict:
        # Reuse fetch_alpaca_bars() from op_momentum_backtest.py
        # Uses the existing cache at market_data/cache/ — no extra API calls
        # if the backtest cache is already warm for this date.
        ...

    def _merge_timeline(self, bars: dict) -> list:
        # Flatten {ticker: [bar, ...]} into a single list sorted by timestamp.
        # Bars at the same timestamp are ordered arbitrarily (inter-ticker order
        # doesn't matter since each ticker has its own independent state).
        all_bars = [b for bars_list in bars.values() for b in bars_list]
        return sorted(all_bars, key=lambda b: b.timestamp)
```

**Fetching bars:**

The backtest already caches 5-min bars at:
```
market_data/cache/{source}_5min_{ticker}_{start}_{end}.json
```

`fetch_bars()` in `op_momentum_backtest.py` (line 1179) reads from this cache.
`_fetch_bars()` in `BarReplayDriver` will call the same function, so no new
Alpaca API calls are needed for already-tested dates. The returned DataFrame
columns are `Open, High, Low, Close, Volume` indexed by ET timestamp — these
need to be converted to `_FiveMinBar` objects, exactly as
`_catch_up_opening_bars_for_window()` already does (signal_engine.py line 347).

---

### Step 3 — Replay entry point in `trade_engine.py`

Add a `run_replay(replay_date, tickers_override=None)` method to
`OpMomentumTradeEngine`:

```python
def run_replay(self, replay_date: date, tickers_override=None):
    from alpha_tech_tracker.op_momentum_strategy.replay import BarReplayDriver

    # Step 1: Ticker selection for the replay date
    # TickerSelector.select() internally calls fetch_bars() which respects cache.
    # Set the clock to replay_date so rolling-lookback end date is correct.
    set_replay_clock(lambda: ET.localize(datetime.combine(replay_date, time(9, 30))))
    all_tickers = self._ticker_selector.select(tickers_override) if not tickers_override \
        else tickers_override

    # Step 2: Build signal engine and position monitor (same as live run())
    signal_engine = LiveSignalEngine(
        tickers=all_tickers, ..., windows=self._windows
    )
    signal_engine._warmup_from_cache(replay_date)  # see Step 4

    self._monitor = PositionMonitor(alpaca_client=..., signal_engine=signal_engine, ...)
    self._signal_engine = signal_engine

    # Step 3: Start signal-collection deadline threads (same as run())
    for win in self._windows:
        t = threading.Thread(target=self._signal_selection_loop_for_window, args=(win,))
        t.daemon = True
        t.start()

    # Step 4: Drive bars through signal engine
    def on_bar(ticker):
        self._monitor.on_bar(ticker)
        # Check EOD using the replay clock
        now = _now_et()
        if now.hour > EOD_EXIT_TIME[0] or (now.hour == EOD_EXIT_TIME[0]
                                            and now.minute >= EOD_EXIT_TIME[1]):
            self._monitor.close_all("end_of_day")

    driver = BarReplayDriver(
        tickers=all_tickers,
        replay_date=replay_date,
        signal_engine=signal_engine,
        on_bar_injected=on_bar,
    )
    driver.run()

    # Step 5: Print summary
    self._monitor.print_summary()
    clear_replay_clock()
```

---

### Step 4 — Warmup from cache (`signal_engine.py`)

The signal engine's `_warmup()` method (line 108) currently calls the Alpaca
API for MA200 warmup bars. For replay we need it to draw from the backtest
cache instead, using the replay date as the reference point.

Add `_warmup_from_cache(replay_date: date)`:

```python
def _warmup_from_cache(self, replay_date: date):
    # Fetch ~210 days of 5-min bars ending on replay_date - 1
    # (same cache used by backtest) and populate self._history per ticker.
    warmup_end = replay_date - timedelta(days=1)
    warmup_start = replay_date - timedelta(days=220)
    bars = fetch_bars(self._tickers, str(warmup_start), str(warmup_end))
    for ticker, df in bars.items():
        self._history[ticker] = df  # df already has MA20/MA50/MA200 columns
```

`fetch_bars()` from `op_momentum_backtest.py` already computes MA columns when
building the DataFrame, so the history will be ready for `_process_five_min_bar`
to append to.

---

### Step 5 — CLI flag in `op_momentum_trade_engine.py`

Add to `parse_args()`:

```
--replay-date DATE    Replay a historical session (YYYY-MM-DD). Feeds cached
                      5-min bars through the live engine instead of a live
                      WebSocket stream. Implies --mock-trade-execution.
```

In `_main()`, when `args.replay_date` is set:

```python
if args.replay_date:
    from datetime import date as _date
    replay_date = _date.fromisoformat(args.replay_date)
    engine = OpMomentumTradeEngine(..., mock_trade_execution=True, ...)
    engine.run_replay(replay_date, tickers_override=args.tickers)
    sys.exit(0)
```

Replay always uses `mock_trade_execution=True` — it never places real orders.

---

### Step 6 — Tests

Add `tests/op_momentum_trade_engine/test_replay.py`:

| Test | What it verifies |
|---|---|
| `test_replay_clock_returns_injected_time` | `set_replay_clock(lambda: t)` → `_now_et()` returns `t`; `clear_replay_clock()` restores live |
| `test_bar_replay_driver_injects_bars_in_timestamp_order` | Two tickers with interleaved bars → `on_bar_injected` calls are in ascending timestamp order |
| `test_bar_replay_driver_advances_clock_per_bar` | After each bar, `_now_et()` equals that bar's timestamp |
| `test_replay_driver_fetch_converts_cache_df_to_five_min_bars` | DataFrame rows from cache → valid `_FiveMinBar` with correct symbol and ET timestamp |
| `test_replay_eod_triggers_close_all` | Clock advances past 3:55 PM ET → `monitor.close_all("end_of_day")` called |
| `test_run_replay_fires_signal_on_known_date` | Integration: fixture date + known bars → `_enter_position` called with expected signal direction |

---

## Files Changed

| File | Change |
|---|---|
| `models.py` or new `replay.py` | Add `_now_et()`, `set_replay_clock()`, `clear_replay_clock()` |
| `signal_engine.py` | Replace `datetime.now(ET)` → `_now_et()`; add `_warmup_from_cache()` |
| `trade_engine.py` | Replace `datetime.now(ET)` → `_now_et()`; add `run_replay()` |
| `op_momentum_trade_engine.py` | Add `--replay-date` flag; call `engine.run_replay()` when set |
| `replay.py` (new) | `BarReplayDriver` dataclass |
| `tests/op_momentum_trade_engine/test_replay.py` (new) | Unit + integration tests |

---

## Example Commands

Replay a specific past date (uses cached bars, mock fills):

```bash
PYTHONPATH=. python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-03-17 \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100
```

Replay with re-entry flags to compare against a backtest run that used them:

```bash
PYTHONPATH=. python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-03-17 \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --reversal --reversal-max-bars 3 \
  --bullish-reentry --bullish-reentry-max-bars 5
```

Override tickers to narrow the replay to specific symbols:

```bash
PYTHONPATH=. python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-03-17 \
  --tickers NVDA TSLA COIN \
  --window M1 09:30 3 --morning-split 100
```

---

## Implementation Order

1. `replay.py` — `_now_et()` / `set_replay_clock()` / `BarReplayDriver`
2. `signal_engine.py` — swap `datetime.now(ET)` → `_now_et()`; add `_warmup_from_cache()`
3. `trade_engine.py` — swap `datetime.now(ET)` → `_now_et()`; add `run_replay()`
4. `op_momentum_trade_engine.py` — `--replay-date` CLI flag
5. Tests

---

## Open Questions / Trade-offs

- **1-min vs 5-min bars for replay**: `_handle_bar()` accepts raw 1-min bars and
  aggregates them into 5-min bars internally. `_process_five_min_bar()` takes
  already-aggregated 5-min bars. Since the backtest cache stores 5-min bars and
  that's what `fetch_bars()` returns, injecting directly via
  `_process_five_min_bar()` is simpler. The 1-min aggregation path is not
  exercised but that path is already covered by `TestLivePipingFullDay`.

- **Signal collection deadline during replay**: `_signal_selection_loop_for_window()`
  polls `datetime.now(ET)` in a sleep loop until the collection deadline. With
  the replay clock advancing per-bar rather than wall-clock time, the deadline
  will appear to be reached as soon as the first bar past the opening window is
  injected. The thread polling interval (0.5s) is wall-clock — this is
  acceptable since replay is not intended to be real-time accurate at
  sub-second granularity.

- **Regime filter in replay**: `_bearish_regime_dates` is built from QQQ MA
  data up to `today`. In replay mode, the clock is set to the replay date so
  the regime filter will use the correct historical QQQ data, as long as the
  warmup window covers the lookback period.

- **Position monitor's `on_bar` call frequency**: In live mode the monitor loop
  calls `on_bar` every 30 seconds. In replay it is called once per 5-min bar
  (every bar injected). This means exits happen at the exact bar boundary, which
  matches backtest behaviour exactly — this is actually more accurate than live.
