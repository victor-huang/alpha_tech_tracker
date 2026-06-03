# Screener Regime Engine — Implementation Plan

## Overview

Add a **RegimeEngine** that sits on top of the MA/OR screener's existing signal output.
It consumes daily signal results (win rates, hold curves), applies the 4-layer ruleset
documented in `op_momentum_screener_analysis/MASTER_REGIME_SUMMARY.md`, and produces two decisions per
session: **which direction to trade** (LONG / SHORT / NEUTRAL / NO_POSITION) and **when
to exit** (+15m / +30m / +1h / +2h / +3h / +5h / EOD).

The screener's `run_live()` uses regime output to filter signals and annotate SMS alerts.
The live trade engine can optionally consume it as a direction filter and timed-exit
override (Part 4, separate PR after screener validation).

No changes to signal detection logic — `compute_or_ma_signals()` runs unchanged.
The regime layer is a pure post-filter applied to the screener's output.

---

## Data Structures

### `DailyRegimeMetrics`

One record per trading day. Computed at the end of the prior session using the warmup
bars that are already loaded at `run_live()` startup.

```python
@dataclass
class DailyRegimeMetrics:
    date: date
    signal_count: int
    eod_wr: float        # fraction, e.g. 0.63 = 63%
    avg_gain: float      # mean % return per signal at EOD
    avg_win: float       # mean % of winning trades at EOD (positive)
    avg_loss: float      # mean % of losing trades at EOD (negative)
    hold_curve: dict     # {"+15m": 0.8, "+30m": 0.6, "+1h": 0.3, "+5h": -0.1, "EOD": -0.2}
```

### `RegimeState`

Output of `RegimeEngine.get_current_regime()`. Consumed by `run_live()` each poll cycle.

```python
@dataclass
class RegimeState:
    direction: str    # "LONG" | "SHORT" | "NEUTRAL" | "NO_POSITION"
    hold_window: str  # "+15m" | "+30m" | "+1h" | "+2h" | "+3h" | "+5h" | "EOD"
    regime_type: str  # "Rising Bull" | "AM Pop-Fade" | "Persistent Bear" |
                      # "U-Curve" | "High-WR Trap" | "Low-WR Positive EV" |
                      # "Seasonal Default" | "Transition"
    source: str       # "seasonal" | "rolling_confirmed" | "transition"
    notes: str        # human-readable explanation for logging / SMS
```

---

## RegimeEngine

### File

```
alpha_tech_tracker/op_momentum_strategy/regime_engine.py
```

### Logic layers

Applied in order. Each layer can override the prior one.

#### Layer 1 — Seasonal prior

Simple month lookup. Fires from day 1 with no rolling data required.

```
January   → LONG,        EOD        (default; verify by day 3)
February  → NEUTRAL,     +30m       (follow prior month)
March     → NO_POSITION, —          (wait for day-3 confirmation)
April     → NEUTRAL,     +1h        (no assumption; confirm days 1–3)
May       → LONG,        +1h        (mild bull default)
June      → NEUTRAL,     +1h        (let hold curve confirm)
July      → NEUTRAL,     EOD        (follow prior month regime)
August    → NEUTRAL,     +15m       (AM-pop-fade default; extend if Jul was rising-curve)
September → SHORT,       +15m       (7/10 years bear or fade)
October   → LONG,        EOD        (9/11 years positive)
November  → NEUTRAL,     —          (wait for week-1 EV check)
December  → SHORT,       +1h        (reduce size; 8/10 years negative)
```

#### Layer 2 — Five-day rolling check

Requires at least 3 trading days of `DailyRegimeMetrics`. Overrides the seasonal prior
when confirmed. Regime types mapped from MASTER_REGIME_SUMMARY Layer 3:

| Regime type | Detection condition | Direction | Hold window |
|---|---|---|---|
| Rising Bull | hold curve rises +15m→+3h→EOD across all 3+ days | LONG | EOD |
| AM Pop-Fade | +15m avg positive, drops ≥15pp by +30m | LONG | +15m |
| Persistent Bear | EOD WR < 40% AND hold curve declining +15m→EOD | SHORT | EOD |
| U-Curve | AM negative, midday bear, EOD recovery | LONG | +3h entry (emit note) |
| High-WR Trap | EOD WR ≥ 55% AND avg_gain ≤ 0 | LONG | +15m |
| Low-WR Positive EV | EOD WR < 50% AND avg_win ≥ 1.5 × \|avg_loss\| | LONG | +5h |

#### Layer 3 — Transition detection

Scans the last 10 trading days for flip signals. Highest priority — overrides layers 1
and 2 when triggered.

```
Bear → Bull flip:
  Any single day with EOD WR ≥ 70%
  after ≥ 5 consecutive days with EOD WR < 40%
  → LONG from next session, hold EOD
  (zero false positives across 9 years per MASTER_REGIME_SUMMARY)

Bull → Bear flip (3 conditions, all required):
  ① 3 consecutive days with EOD WR < 40%
  ② Hold curve declining at every window (+15m → +1h → EOD all negative)
  ③ avg_loss / avg_win ratio > 0.80
  → SHORT from next session, hold EOD
```

#### Layer 4 — Pre-session top-2 divergence (screener only)

Applies only in `run_live()`. The pre-session top-2 ranking (computed at 9:25 from
`_rank_tickers_by_eod_win_rate`) can diverge from signal analysis. Divergence rules from
MASTER_REGIME_SUMMARY §Pre-Session Top-2 Independence Rule:

- **Both agree** on LONG → strongest confirmation, hold EOD
- **Pre-session LONG, signal analysis in AM-pop-fade or midday-bear** → use pre-session
  as independent LONG; still exit at +15m (regime type is weaker)
- **Signal analysis LONG, pre-session weak** → trust signal analysis; pre-session lags
  in sudden breakouts (Jan 2021, Aug 2023 pattern)

Divergence state is logged at session start and included in the pre-session SMS.

**Not used in the live trade engine.** The trade engine uses `TickerSelector` (composite
score) for ticker selection — `_rank_tickers_by_eod_win_rate` is never called there.
`get_current_regime()` is called without `presession_top2_wr`, running layers 1–3 only.

### Persistence

```
market_data/regime_state/regime_metrics_{year}.json
```

Append-only list of `DailyRegimeMetrics` dicts, one file per year. The engine loads the
last 10 trading days automatically at instantiation. New records are appended after EOD
metric computation completes.

### Public interface

```python
class RegimeEngine:
    def __init__(self, data_dir: str = "market_data/regime_state")

    def add_daily_result(self, metrics: DailyRegimeMetrics) -> None
        # Appends to in-memory history and persists to JSON.

    def get_current_regime(self, presession_top2_wr: float = None) -> RegimeState
        # Applies all 4 layers. presession_top2_wr is the EOD WR of the top-2
        # pre-session ranking for today (passed in from run_live at 9:25).

    def summary_str(self) -> str
        # One-line description of current regime for logging / SMS prefix.
```

---

## Part 2 — Daily Metrics Collection

### Ownership: `RegimeEngine.compute_and_add_metrics()`

Metric computation lives in `regime_engine.py`, not in the screener. Both the screener
and the trade engine call this method independently at startup with their own warmup bar
data. Neither process depends on the other having run first.

```python
def compute_and_add_metrics(
    self,
    warmup_bars: dict,   # {ticker: DataFrame} with MA columns, covers prior ~14 days
    target_date: date,   # the day to compute metrics FOR (yesterday)
    or_start: str,
    or_bars: int,
    collection_bars: int,
    source: str = "alpaca",
    feed: DataFeed = DataFeed.SIP,
) -> Optional[DailyRegimeMetrics]:
```

No `qqq_bars` parameter — the method owns QQQ data entirely:

- If `"QQQ"` is present in `warmup_bars`, use it directly.
- If absent, fetch QQQ 5-min bars internally using `fetch_bars(["QQQ"], ...)` with the
  same `source` and `feed` used for the ticker pool. The fetch window matches the warmup
  range already in `warmup_bars` (derived from the earliest index across all tickers).

This means callers never need to think about QQQ. The screener passes its warmup dict
as-is (QQQ is already included there). The trade engine passes `TickerSelector.fetch_bars()`
output as-is (QQQ may or may not be present — the method handles both cases).

**Cache check first:** if a record for `target_date` already exists in the in-memory
history (loaded from JSON at init), skip all computation and return the cached record.
This prevents double-computation when both the screener and trade engine start in the
same session.

Steps when cache misses:
1. Resolve QQQ bars (from `warmup_bars` or fetch internally)
2. Add MA columns to all bar DataFrames (`_add_ma_columns`)
3. Run `compute_or_ma_signals()` on `target_date` — produces signal list
4. For each signal: call `_forward_pct()` at each hold window (`_HIST_HOLD_MIN`) using
   the per-ticker warmup DataFrame
5. Aggregate across all signals: compute `eod_wr`, `avg_gain`, `avg_win`, `avg_loss`,
   `hold_curve`
6. Call `add_daily_result()` to persist and return the new `DailyRegimeMetrics`

Returns `None` if fewer than 3 signals fired (insufficient sample; regime engine falls
back to seasonal prior for that day's slot in the rolling window).

### Callers

**Screener** (`run_live()` startup, after warmup loads):
```python
regime_engine = RegimeEngine()
regime_engine.compute_and_add_metrics(warmup_bars, yesterday, or_start, or_bars, collection_bars)
```

`warmup_bars` already contains QQQ — no extra work needed.

**Trade engine** (`OpMomentumTradeEngine.run()`, between `TickerSelector.fetch_bars()`
and `TickerSelector.select()`):
```python
if self._regime_engine:
    self._regime_engine.compute_and_add_metrics(
        ticker_dfs, yesterday, opening_start, opening_bars, collection_bars,
        source=source, feed=self._score_feed,
    )
```

`ticker_dfs` is the bar dict from `fetch_bars()` — passed directly with no changes.
If QQQ is absent, `compute_and_add_metrics` fetches it using the same source and feed,
keeping the data consistent with the selector's bars.

### Import boundary

`trade_engine.py` currently has **zero imports** from `ma_open_range_momentum_screener.py`
and this must stay zero. To enforce that:

- `_forward_pct` and `_rank_tickers_by_eod_win_rate` are **moved** from
  `ma_open_range_momentum_screener.py` into `regime_engine.py`. The screener
  imports them back from `regime_engine.py` after the move.
- `regime_engine.py` imports from `ma_open_range_momentum_screener.py` only:
  `compute_or_ma_signals` (signal scan).
- `trade_engine.py` imports from `regime_engine.py` only: `RegimeEngine`,
  `_rank_tickers_by_eod_win_rate` (used by `ScreenerTickerSelector`).

Dependency graph (no cycles):

```
ma_open_range_momentum_screener.py
    └── imports compute_or_ma_signals (stays local)
    └── imports _forward_pct, _rank_tickers_by_eod_win_rate ← from regime_engine.py

regime_engine.py
    └── imports compute_or_ma_signals ← from ma_open_range_momentum_screener.py

trade_engine.py
    └── imports RegimeEngine, _rank_tickers_by_eod_win_rate ← from regime_engine.py
    (zero imports from ma_open_range_momentum_screener.py)
```

---

## Part 3 — `run_live()` Integration

### Startup sequence (`run_live()`)

```
1. fetch warmup bars (Alpaca historical, prior ~14 days)
2. regime_engine.compute_and_add_metrics(warmup_bars, yesterday, ...)
      ↳ QQQ resolved internally; cache hit skips recomputation
3. (at 9:25 ET) _rank_tickers_by_eod_win_rate(warmup_bars, today, ...)
      ↳ pre-session top-2 WR — Layer 4 input + pre-session SMS
4. regime_engine.get_current_regime(presession_top2_wr=...)
      ↳ layers 1–4 applied; regime state fixed for the session
5. pre-session SMS: top-2 ranking + regime direction + hold window
6. poll loop begins
```

```python
regime_engine = RegimeEngine()
regime_engine.compute_and_add_metrics(warmup_bars, yesterday, or_start, or_bars, collection_bars)

# at 9:25 ET — pre-session top-2 (screener only, Layer 4 input)
ranked = _rank_tickers_by_eod_win_rate(warmup_ticker_bars, today, or_start, or_bars)
presession_top2_wr = ranked[0][1]["win_rates"][None] / 100 if ranked else None

regime = regime_engine.get_current_regime(presession_top2_wr=presession_top2_wr)
logger.info("Regime: %s", regime_engine.summary_str())
_notify(f"Regime: {regime.direction} | Hold: {regime.hold_window} | {regime.notes}")
```

### Startup sequence (`OpMomentumTradeEngine.run()`)

```
1. selector.fetch_bars()                 ← TickerSelector or ScreenerTickerSelector
2. regime_engine.compute_and_add_metrics(ticker_dfs, yesterday, ...)
      ↳ QQQ fetched internally if absent; cache hit skips recomputation
      ↳ _rank_tickers_by_eod_win_rate NOT called — not used in trade engine
3. regime_engine.get_current_regime()    ← layers 1–3 only (no presession_top2_wr)
4. selector.select(ticker_dfs, direction=regime.direction)
      ← scoring_selector ignores direction kwarg; win_rate_selector uses it for top-N vs bottom-N
5. LiveSignalEngine.start()
```

### In the confirmed-signal block (inside poll loop)

Two changes, both additive:

**1. Direction filter** — before sending signal SMS:

```python
if regime.direction == "SHORT" and sig["direction"] == "BULL":
    logger.info("Regime filter: skipping BULL signal for %s (SHORT regime)", sig["ticker"])
    continue
if regime.direction == "LONG" and sig["direction"] == "BEAR":
    logger.info("Regime filter: skipping BEAR signal for %s (LONG regime)", sig["ticker"])
    continue
if regime.direction == "NO_POSITION":
    logger.info("Regime filter: skipping %s signal (NO_POSITION — March day-3 pending)", sig["ticker"])
    continue
```

NEUTRAL passes both directions through unchanged.

**2. Hold annotation** — append to signal SMS:

```python
sms = format_sms(sig)
sms += f"\nHold: {regime.hold_window} [{regime.regime_type}]"
```

---

## Part 4 — Live Trade Engine Integration (separate PR)

### Dependency

Parts 1–3 must be running in live screener mode for at least one week before Part 4 is
implemented. Regime decisions should be validated against actual screener signal outcomes
before wiring into capital-deploying trade execution.

### 4a — `ScreenerTickerSelector`

A new selector class in `trade_engine.py` that uses the screener's EOD win rate ranking
instead of the composite score. Enabled via `--selector win_rate_selector` CLI flag.

```python
class ScreenerTickerSelector:
    def __init__(
        self,
        tickers: list,
        top_n: int,
        or_start: str = OPENING_START_TIME,
        or_bars: int = OPENING_BARS,
        lookback_days: int = 20,
        alpaca_feed: DataFeed = DataFeed.SIP,
        market_data_client=None,
    )

    def fetch_bars(self) -> dict:
        # same fetch logic as TickerSelector.fetch_bars() — Alpaca or TradeStation

    def select(self, ticker_dfs: dict = None, direction: str = "LONG") -> list[str]:
        # calls _rank_tickers_by_eod_win_rate(ticker_dfs, today, or_start, or_bars, lookback_days)
        # direction="LONG"  → returns top-N tickers by EOD win rate
        # direction="SHORT" → returns bottom-N tickers by EOD win rate
```

Comparison with `TickerSelector`:

| | `TickerSelector` (`scoring_selector`) | `ScreenerTickerSelector` (`win_rate_selector`) |
|---|---|---|
| Ranking metric | Composite score (EV, win rate, OR range) | EOD win rate, unconditional OR-close hold |
| Lookback | 60 days rolling | 20 days rolling |
| Signal gate | Yes — only trades with signals in lookback | No — pure historical WR |
| EV gate | Yes | No |
| Regime filter | Optional | No (handled by `RegimeEngine`) |
| `rolling_stats` | Populated — used for re-entry EV gating | Empty dict — re-entry EV gate skipped |

**`rolling_stats` fallback:** `OpMomentumTradeEngine._enter_reentry()` checks
`rolling_stats.get(ticker)` for EV gating. When `ScreenerTickerSelector` is active,
`rolling_stats` is an empty dict — the EV gate condition evaluates to `ev_trade=0`,
which passes the `> min_ev` check when `min_ev=0.0` (the default). No code change
needed; behavior is correct by default. If `--min-ev` is explicitly set above 0, the
caller is opting into EV gating and should use `TickerSelector` instead.

**CLI flag:** `--selector {scoring_selector,win_rate_selector}` on `op_momentum_trade_engine.py`.
Default is `scoring_selector` (no behavioral change). When `win_rate_selector` is set,
`ScreenerTickerSelector` is instantiated in place of `TickerSelector`.

`OpMomentumTradeEngine.__init__` accepts either selector via duck typing — both expose
`fetch_bars()` and `select()` with identical signatures. No base class required.

### 4b — Direction filter in `OpMomentumTradeEngine`

Add `regime_engine: Optional[RegimeEngine] = None` parameter to `__init__`. In the
`on_signal` callback (where a `SignalEvent` is accepted before calling `_enter_position`):

```python
if self._regime_engine:
    regime = self._regime_engine.get_current_regime()
    if event.signal == "BULLISH" and regime.direction == "SHORT":
        logger.info("Regime filter: skipping BULLISH signal for %s", event.ticker)
        return
    if event.signal == "BEARISH" and regime.direction == "LONG":
        logger.info("Regime filter: skipping BEARISH signal for %s", event.ticker)
        return
    if regime.direction == "NO_POSITION":
        logger.info("Regime filter: no-position day, skipping %s", event.ticker)
        return
```

### 4b — Timed exit in `ActivePosition` + `PositionMonitor`

Add `timed_exit_minutes: Optional[int] = None` field to `ActivePosition` (and to
`to_dict` / `from_dict` for session persistence).

In `PositionMonitor._check_exit()` (the per-bar exit evaluation), add before EOD check:

```python
if pos.timed_exit_minutes is not None and pos.entry_time is not None:
    timed_exit_dt = pos.entry_time + timedelta(minutes=pos.timed_exit_minutes)
    if now_et >= timed_exit_dt:
        return "timed_exit"
```

`OpMomentumTradeEngine._enter_position()` sets `timed_exit_minutes` from
`regime.hold_window` when regime engine is active:

```python
_HOLD_WINDOW_MINUTES = {
    "+15m": 15, "+30m": 30, "+1h": 60,
    "+2h": 120, "+3h": 180, "+5h": 300, "EOD": None,
}
timed_exit = _HOLD_WINDOW_MINUTES.get(regime.hold_window) if self._regime_engine else None
```

Hard stop and trailing MA remain active. The timed exit fires first when the hold window
is shorter than the trailing MA would have triggered; the trailing MA fires first when
the regime recommends a long hold (EOD) and price reverses.

---

## Implementation Phases

### Phase 1 — RegimeEngine (standalone, no live integration)

1. `DailyRegimeMetrics` and `RegimeState` dataclasses in `regime_engine.py`
2. `RegimeEngine.__init__()` with JSON load
3. `RegimeEngine.add_daily_result()` with JSON append
4. `RegimeEngine._seasonal_prior(month)`
5. `RegimeEngine._rolling_check(history)` — 6 regime types
6. `RegimeEngine._transition_check(history)` — bear→bull and bull→bear
7. `RegimeEngine.get_current_regime()` — chain all layers
8. Unit tests: cover each regime type, each seasonal month, both transition directions

### Phase 2 — Daily metrics collection

9. `RegimeEngine.compute_and_add_metrics()` in `regime_engine.py` — cache check, signal
   scan via `compute_or_ma_signals`, forward return aggregation via `_forward_pct`
10. Unit tests: mock warmup bars, verify cache hit skips recomputation, verify metric
    aggregation matches manual calculation for a known signal set

### Phase 3 — `run_live()` integration

11. Instantiate `RegimeEngine` at startup; compute and add yesterday's metrics
12. Compute `presession_top2_wr` and pass to `get_current_regime()`
13. Pre-session SMS with regime state
14. Direction filter in confirmed-signal block
15. Hold annotation appended to signal SMS
16. Smoke test: `--live --dry-run` for 3 consecutive sessions; verify regime state logged
    correctly and direction filter fires on expected signals

### Phase 4 — Trade engine integration (separate PR, after Phase 3 validated)

17. `ScreenerTickerSelector` class in `trade_engine.py` — `fetch_bars()`, `select()` via
    `_rank_tickers_by_eod_win_rate`; `rolling_stats` returns empty dict
18. `--selector {scoring_selector,win_rate_selector}` CLI flag in `op_momentum_trade_engine.py`
19. `timed_exit_minutes: Optional[int] = None` and `disable_ma_stop: bool = False` fields
    on `ActivePosition`. In `to_dict`: serialize both. In `from_dict`: use
    `d.get("timed_exit_minutes", None)` and `d.get("disable_ma_stop", False)` — never
    direct key access — so sessions saved before this change restore without `KeyError`.
20. Timed exit check in `PositionMonitor._check_exit()`; trailing MA check skipped when
    `pos.disable_ma_stop` is set
21. `regime_engine` and `disable_ma_stops_for_regime_hold` parameters on
    `OpMomentumTradeEngine`; startup sequence calls `compute_and_add_metrics` between
    `fetch_bars` and `select`
22. Direction filter in `_on_signal` callback
23. `timed_exit_minutes` and `disable_ma_stop` wiring in `_enter_position` — set when
    `--regime-hold` and `--disable-ma-stops-for-regime-hold-only` are both active
24. `--disable-ma-stops-for-regime-hold-only` CLI flag in `op_momentum_trade_engine.py`
25. Tests: `test_trade_engine.py` — `ScreenerTickerSelector` returns top-N by EOD WR;
    BULLISH signal skipped in SHORT regime; BEARISH signal skipped in LONG regime;
    `test_position_monitor.py` — timed exit fires before EOD; hard stop fires before
    timed exit; trailing MA skipped when `disable_ma_stop=True`; trailing MA fires when
    `disable_ma_stop=False` and price crosses MA before timed exit

---

## CLI Flag Reference

### Flags (trade engine — `op_momentum_trade_engine.py`)

> **Note:** The existing `--regime-filter` / `--regime-ma` flags control the **QQQ
> MA-based regime filter** inside `TickerSelector.select_top_n()` — an unrelated system
> that checks whether QQQ is above/below a moving average to tighten the ticker pool.
> The flags below are the **MASTER_REGIME_SUMMARY pattern-based regime engine** and are
> fully independent. Both can be active at the same time without conflict.

| Flag | Values | Default | Effect |
|---|---|---|---|
| `--enable-regime-engine` | *(present/absent)* | off | Instantiates `RegimeEngine`; direction filter applied to all signals |
| `--regime-hold` | *(present/absent)* | off | Timed exit from regime hold window; requires `--enable-regime-engine` |
| `--disable-ma-stops-for-regime-hold-only` | *(present/absent)* | off | Disables trailing MA stop (MA20/MA50) when `--regime-hold` is active; hard stop remains armed; requires `--regime-hold` |
| `--selector` | `scoring_selector`, `win_rate_selector` | `scoring_selector` | Ticker selection strategy |

### Dependencies

`--regime-hold` requires `--enable-regime-engine` — without a regime there is no hold window
to apply.

`--disable-ma-stops-for-regime-hold-only` requires `--regime-hold` — disabling trailing
MA only makes sense when the timed exit is the intended exit mechanism.

`--selector win_rate_selector` requires `--enable-regime-engine` — without it the selector
has no direction source and can only default to LONG (top-N), losing bear/bottom-N
selection entirely.

### Valid combinations

| Flags | Selector | Regime active | Behavior |
|---|---|---|---|
| *(none)* | `scoring_selector` | No | Current behavior unchanged |
| `--enable-regime-engine` | `scoring_selector` | Yes (layers 1–3) | Composite score picks; direction filter suppresses wrong-direction signals; timed exit off |
| `--enable-regime-engine --regime-hold` | `scoring_selector` | Yes | Composite score picks; direction filter + timed exit; trailing MA still active |
| `--enable-regime-engine --regime-hold --disable-ma-stops-for-regime-hold-only` | `scoring_selector` | Yes | Composite score picks; direction filter + timed exit; trailing MA disabled; hard stop only |
| `--selector win_rate_selector --enable-regime-engine` | `win_rate_selector` | Yes | EOD WR top-N (LONG) or bottom-N (SHORT); direction filter; timed exit off |
| `--selector win_rate_selector --enable-regime-engine --regime-hold` | `win_rate_selector` | Yes | EOD WR selection + direction filter + timed exit; trailing MA still active |
| `--selector win_rate_selector --enable-regime-engine --regime-hold --disable-ma-stops-for-regime-hold-only` | `win_rate_selector` | Yes | Full screener-style regime mode; timed exit + hard stop only; trailing MA disabled |

### Bear selection behavior by selector

| Regime = SHORT | `scoring_selector` | `win_rate_selector` |
|---|---|---|
| Ticker selection | Composite top-N (not optimized for bear — warns in log) | Bottom-N by EOD WR |
| Signal accepted | BEARISH only | BEARISH only |
| Contract | PUT | PUT |
| Future | Regime-aware score suppression/boost | No change needed |

---

## Guard Conditions

- **Insufficient signal count** (`< 3` signals on a prior day): `_compute_prior_day_metrics`
  returns `None`; regime engine logs a warning and falls back to seasonal prior for that
  day's slot in the rolling window.
- **No rolling history** (first week of the year or missing files): `get_current_regime`
  uses seasonal prior only; logs that rolling check was skipped.
- **March day-1 through day-3 with no confirmation**: return `NO_POSITION` with a note
  to re-evaluate after day 3. Do not silently default to NEUTRAL.
- **November**: no seasonal prior — always return `NEUTRAL` with note "wait for week-1 EV
  check" until 5 trading days of data are available, then apply rolling check.
- **Timed exit + hard stop collision**: hard stop always remains armed regardless of
  `timed_exit_minutes` or `--disable-ma-stops-for-regime-hold-only`. If price hits the
  hard stop before the timed exit fires, the hard stop takes precedence.
  `timed_exit_minutes` is a ceiling, not a floor.
- **Trailing MA + timed exit**: when `--disable-ma-stops-for-regime-hold-only` is off
  (default), trailing MA and timed exit are both active — timed exit is the time ceiling,
  trailing MA fires if price reverses before the window expires. When the flag is on,
  trailing MA is suppressed for the duration of the position; only hard stop and timed
  exit govern the exit.
- **Regime flip mid-session**: `get_current_regime()` is called once at session start
  and once again at 9:25 pre-session. It does not re-evaluate intraday. The hold window
  and direction are fixed for the session at that point. This matches the doc's warning:
  "Don't try to flip hold windows mid-day based on a pattern that needs days to confirm."

---

## Files Changed

| File | Change |
|---|---|
| `regime_engine.py` (new) | `DailyRegimeMetrics`, `RegimeState`, `RegimeEngine` including `compute_and_add_metrics()`; receives `_forward_pct` and `_rank_tickers_by_eod_win_rate` moved from screener |
| `ma_open_range_momentum_screener.py` | Remove `_forward_pct` and `_rank_tickers_by_eod_win_rate` (moved to `regime_engine.py`); import them back from `regime_engine`; `run_live()` startup: instantiate `RegimeEngine`, call `compute_and_add_metrics`, direction filter, hold annotation |
| `trade_engine.py` | `ScreenerTickerSelector` class (imports `_rank_tickers_by_eod_win_rate` from `regime_engine.py`); `regime_engine` + `disable_ma_stops_for_regime_hold` params on `OpMomentumTradeEngine`; startup sequence; direction filter in signal callback (Phase 4) |
| `op_momentum_trade_engine.py` | `--selector {scoring_selector,win_rate_selector}`, `--enable-regime-engine`, `--regime-hold`, `--disable-ma-stops-for-regime-hold-only` CLI flags (Phase 4) |
| `models.py` | `timed_exit_minutes: Optional[int] = None` and `disable_ma_stop: bool = False` fields on `ActivePosition`; `from_dict` uses `.get()` for both fields for backward-compatible session restore (Phase 4) |
| `position_monitor.py` | timed exit check + trailing MA suppression via `disable_ma_stop` in `_check_exit()` (Phase 4) |
| `tests/op_momentum_trade_engine/test_regime_engine.py` (new) | Phase 1–2 unit tests |
| `tests/op_momentum_trade_engine/test_trade_engine.py` | Phase 4: `ScreenerTickerSelector`, direction filter tests |
| `tests/op_momentum_trade_engine/test_position_monitor.py` | Phase 4: timed exit tests |

### Analysis and reference docs

All screener P&L findings, per-year regime analysis, and backtest logs live in:
```
alpha_tech_tracker/op_momentum_strategy/op_momentum_screener_analysis/
```
Key files: `MASTER_REGIME_SUMMARY.md` (regime rules source of truth), `{YEAR}_REGIME_ANALYSIS.md`
(per-year breakdown), `logs/` (raw backtest run output).
