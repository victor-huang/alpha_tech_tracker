# Dev Plan: Port Scoring/Filtering Features from Backtest → Live Engine

**Date:** 2026-05-31  
**Branch:** open_market_momentum_stategy  

## Goal

Bring five CLI flags from `op_momentum_selector_backtest.py` into the live trade engine
(`op_momentum_trade_engine.py` → `trade_engine.py` → `signal_engine.py` /
`op_momentum_selector.py`) so they can be passed at engine startup and applied identically
in both replay and live modes.

| Flag | Default | Backtest location | Current engine support |
|---|---|---|---|
| `--ma-momentum-gate` | off | `compute_signals_with_backtest()` in `op_momentum_backtest.py` | ❌ missing |
| `--normalize-or-by-adr` | off | per-day scoring loop in `run_selector_backtest()` | ❌ missing |
| `--score-avg-win-weight` | 0.30 | `score_ticker()` call in `run_selector_backtest()` | ❌ `select_top_n()` always uses default |
| `--score-entry-weight` | 0.50 | `score_ticker()` call in `run_selector_backtest()` | ❌ `select_top_n()` always uses default |
| `--score-win-rate-weight` | 0.0 | `score_ticker()` call in `run_selector_backtest()` | ❌ missing |
| `--score-rel-strength-weight` | 0.0 | `score_ticker()` call in `run_selector_backtest()` | ❌ missing |
| `--min-pool-vote` | 0 | `run_selector_backtest()` day loop | ❌ missing |

---

## Feature Descriptions

### 1. `--ma-momentum-gate`

**What it does:** Suppresses signals where the OR range does not overlap both MA20 and MA50
in the signal direction. Acts as a signal-level filter (not just a score penalty).

**Backtest logic** (`op_momentum_backtest.py` lines 518–534):
```python
if ma_momentum_gate:
    if signal == "BULLISH":
        if not (or_high >= ma20 and or_high >= ma50_gate):
            continue   # no signal record emitted
        if not (close > ma20 or close > ma50_gate):
            continue
    else:  # BEARISH
        if not (or_low <= ma20 and or_low <= ma50_gate):
            continue
        if not (close < ma20):
            continue
```

**Live engine equivalent:** `signal_engine.py:LiveSignalEngine._try_fire_signal()` — after
the `signal = "BULLISH"/"BEARISH"` determination (line ~183) and before the `SignalEvent`
is constructed. `ma50` is already read from `latest["MA50"]` at line 168.

---

### 2. `--normalize-or-by-adr`

**What it does:** Divides each ticker's `or_range_pct` by its prior-day rolling ADR (20-day
average of `(High-Low)/Close * 100`) before scoring. Levels the playing field between
high/low volatility tickers — without this, high-ADR tickers like MSTR win the `or_range`
component almost every day.

**Backtest logic** (`op_momentum_selector_backtest.py` lines 1820–1823):
```python
if normalize_or_by_adr:
    _adr = adr_by_ticker_date.get(ticker, {}).get(d)
    if _adr and _adr > 0:
        sig["or_range_pct"] = sig["or_range_pct"] / _adr
```

`adr_by_ticker_date` is pre-computed at lines 1211–1231: per ticker, resample to daily,
compute `(High-Low)/Close * 100`, 20-day rolling mean, shift(1) to avoid lookahead.

**Live engine equivalent:** `select_top_n()` in `op_momentum_selector.py` — compute ADR per
ticker from the already-fetched `ticker_dfs` dict, then normalize `today_signals[ticker]["or_range_pct"]`
before passing to `score_ticker()`.

---

### 3. `--score-avg-win-weight`, `--score-entry-weight`, `--score-win-rate-weight`

**What they do:** Override the per-component weights in `score_ticker()`.

**Backtest logic:** Passed directly to `score_ticker(sig, stats, eff_entry, eff_vol, eff_aw, ..., score_win_rate_weight=...)`.

**Live engine gap:** `select_top_n()` calls `score_ticker(sig, stats)` with **no extra params**,
always using defaults (entry=0.50, avg_win=0.30, win_rate=0.0).

---

### 4. `--score-rel-strength-weight`

**What it does:** Cross-sectional score component: each ticker's MA50-distance relative to
the pool mean, direction-aware (positive for BULLISH outperformers, negative for laggards).

**Backtest logic:** `daily_context_by_ticker[ticker][d]["rel_ma50_dist_pct"]` is computed as:
```python
pool_mean_ma50 = mean(daily_ma50_dist_pct across all tickers for day d)
rel_ma50_dist_pct = daily_ma50_dist_pct[ticker] - pool_mean_ma50
```
`daily_ma50_dist_pct` = `(Open - MA50) / MA50 * 100` from daily OHLCV (shift(1) = prior-day close).

In `score_ticker()` line ~404: `rel_strength_term = direction_sign * rel_ma50_dist / 10.0`.

**Live engine equivalent:** Compute per ticker from `ticker_dfs` (using prior-day close →
daily MA50 → distance), compute cross-sectional pool mean, inject `rel_ma50_dist_pct` into
a `daily_context` dict passed to `score_ticker()`.

---

### 5. `--min-pool-vote`

**What it does:** If fewer than N tickers in the pool have positive rolling EV on a given day,
skip trading that day entirely (no picks returned).

**Backtest logic** (`op_momentum_selector_backtest.py` lines 1671–1676):
```python
pool_vote = sum(1 for s in rolling_stats.values() if s["ev_trade"] > 0)
if min_pool_vote_to_trade > 0 and pool_vote < min_pool_vote_to_trade:
    continue  # skip this window/day
```

**Live engine equivalent:** In `select_top_n()`, after computing `rolling_stats`, count
positive-EV tickers and return `{"picks": [], "no_signal": [], "negative_ev": [], "rolling_stats": rolling_stats}`
early if the vote is below threshold.

---

## Implementation Plan

### Step 1 — `signal_engine.py` (ma_momentum_gate)

**File:** `alpha_tech_tracker/op_momentum_strategy/signal_engine.py`

1. Add `ma_momentum_gate: bool = False` parameter to `LiveSignalEngine.__init__()` (after `trailing_ma_switch_period`).
2. Store as `self._ma_momentum_gate = ma_momentum_gate`.
3. In `_try_fire_signal()`, after the `signal = "BULLISH"/"BEARISH"` block and before the `SignalEvent(...)` construction, insert:

```python
if self._ma_momentum_gate:
    if pd.isna(ma50):
        logger.info("%s [%s]: ma_momentum_gate: MA50 not ready, skipping", ticker, win["label"])
        return
    ma50_d = _D(ma50)
    if signal == "BULLISH":
        if not (or_high >= ma20_d and or_high >= ma50_d):
            logger.info("%s [%s]: ma_momentum_gate: BULLISH suppressed (OR high below MA20/MA50)", ticker, win["label"])
            return
    else:
        if not (or_low <= ma20_d and or_low <= ma50_d):
            logger.info("%s [%s]: ma_momentum_gate: BEARISH suppressed (OR low above MA20/MA50)", ticker, win["label"])
            return
```

**Note:** `ma50` is already read from `latest["MA50"]` at line 168; `ma20_d` is at line 175. 
`ma50` may be NaN (the existing guard only checks `ma20`/`ma200`, not `ma50`).

---

### Step 2 — `op_momentum_selector.py` (select_top_n scoring params + adr + pool_vote + rel_strength)

**File:** `alpha_tech_tracker/op_momentum_strategy/op_momentum_selector.py`

Add to `select_top_n()` signature:
```python
score_entry_weight: float = 0.50,
score_avg_win_weight: float = 0.30,
score_win_rate_weight: float = 0.0,
score_rel_strength_weight: float = 0.0,
normalize_or_by_adr: bool = False,
adr_days: int = 20,
min_pool_vote_to_trade: int = 0,
```

**After computing `rolling_stats`** (currently line ~494), add pool_vote gate:
```python
if min_pool_vote_to_trade > 0:
    pool_vote = sum(1 for s in rolling_stats.values() if s["ev_trade"] > 0)
    if pool_vote < min_pool_vote_to_trade:
        return {"picks": [], "no_signal": list(tickers), "negative_ev": [], "rolling_stats": rolling_stats}
```

**Before the `for ticker in tickers` loop**, add ADR pre-computation if `normalize_or_by_adr`:
```python
adr_by_ticker = {}
if normalize_or_by_adr and ticker_dfs:
    for t, df in ticker_dfs.items():
        if df.empty:
            continue
        mh = df.between_time("09:30", "16:00")
        daily = mh.resample("D").agg(High=("High","max"), Low=("Low","min"), Close=("Close","last")).dropna(subset=["Close"])
        daily.index = daily.index.normalize().tz_localize(None)
        daily["adr_pct"] = (daily["High"] - daily["Low"]) / daily["Close"] * 100
        rolling_adr = daily["adr_pct"].rolling(adr_days, min_periods=5).mean().shift(1)
        adr_by_ticker[t] = {ts.date(): float(v) for ts, v in rolling_adr.items() if not pd.isna(v)}
```

**Compute cross-sectional rel_strength** if `score_rel_strength_weight > 0`:
```python
rel_strength_by_ticker = {}
if score_rel_strength_weight and ticker_dfs:
    ma50_dist_vals = {}
    for t, df in ticker_dfs.items():
        if df.empty:
            continue
        mh = df.between_time("09:30", "16:00")
        daily = mh.resample("D").agg(Open=("Open","first"), Close=("Close","last")).dropna(subset=["Close"])
        daily.index = daily.index.normalize().tz_localize(None)
        ma50 = daily["Close"].rolling(50, min_periods=20).mean()
        dist = (daily["Open"] - ma50) / ma50 * 100
        td = target_date - timedelta(days=1)  # prior-day open
        ma50_dist_vals[t] = float(dist.get(pd.Timestamp(td), float("nan")))
    valid_vals = [v for v in ma50_dist_vals.values() if not np.isnan(v)]
    pool_mean = sum(valid_vals) / len(valid_vals) if valid_vals else 0.0
    for t, v in ma50_dist_vals.items():
        rel_strength_by_ticker[t] = (v - pool_mean) if not np.isnan(v) else float("nan")
```

**In the per-ticker scoring block**, apply ADR normalization and inject rel_strength:
```python
sig = dict(today_signals[ticker])  # copy to avoid mutating cache
if normalize_or_by_adr:
    _adr = adr_by_ticker.get(ticker, {}).get(target_date)
    if _adr and _adr > 0:
        sig["or_range_pct"] = sig["or_range_pct"] / _adr

daily_ctx = None
if score_rel_strength_weight:
    daily_ctx = {"rel_ma50_dist_pct": rel_strength_by_ticker.get(ticker, float("nan"))}

s = score_ticker(
    sig, stats,
    score_entry_weight=score_entry_weight,
    score_avg_win_weight=score_avg_win_weight,
    score_win_rate_weight=score_win_rate_weight,
    score_rel_strength_weight=score_rel_strength_weight,
    daily_context=daily_ctx,
)
```

**Import guard:** `from datetime import timedelta` is already present; add `import numpy as np`
if not already imported (check — it's not in the current imports).

---

### Step 3 — `trade_engine.py` (TickerSelector + OpMomentumTradeEngine)

**File:** `alpha_tech_tracker/op_momentum_strategy/trade_engine.py`

#### 3a. TickerSelector

Add to `TickerSelector.__init__()` (after `armed_ma20_exit`):
```python
ma_momentum_gate: bool = False,
score_entry_weight: float = 0.50,
score_avg_win_weight: float = 0.30,
score_win_rate_weight: float = 0.0,
score_rel_strength_weight: float = 0.0,
normalize_or_by_adr: bool = False,
min_pool_vote_to_trade: int = 0,
```
Store all as `self._<name>`.

In `TickerSelector.select()`, pass to **all three** `select_top_n()` calls (replay mode,
main path, and prev-day fallback):
```python
score_entry_weight=self._score_entry_weight,
score_avg_win_weight=self._score_avg_win_weight,
score_win_rate_weight=self._score_win_rate_weight,
score_rel_strength_weight=self._score_rel_strength_weight,
normalize_or_by_adr=self._normalize_or_by_adr,
min_pool_vote_to_trade=self._min_pool_vote_to_trade,
```

`ma_momentum_gate` is handled by `LiveSignalEngine`, not `select_top_n`, so it does **not**
go into the `TickerSelector` → `select_top_n` call. `TickerSelector` stores it only so
`OpMomentumTradeEngine` can read it when building the signal engine.

#### 3b. OpMomentumTradeEngine

Add to `OpMomentumTradeEngine.__init__()`:
```python
ma_momentum_gate: bool = False,
score_entry_weight: float = 0.50,
score_avg_win_weight: float = 0.30,
score_win_rate_weight: float = 0.0,
score_rel_strength_weight: float = 0.0,
normalize_or_by_adr: bool = False,
min_pool_vote_to_trade: int = 0,
```
Store as `self._<name>`.

In `_run_window_selectors()` where `TickerSelector` is instantiated (line ~2203), pass all
non-ma-gate scoring params.

In the `LiveSignalEngine` instantiation(s) at lines 2415 and 2591, add:
```python
ma_momentum_gate=self._ma_momentum_gate,
```

---

### Step 4 — `op_momentum_trade_engine.py` (CLI + engine wiring)

**File:** `alpha_tech_tracker/op_momentum_strategy/op_momentum_trade_engine.py`

Add to `parse_args()`:
```python
parser.add_argument("--ma-momentum-gate", action="store_true", default=False, dest="ma_momentum_gate",
    help="Suppress signals where the OR range doesn't overlap both MA20 and MA50 in the signal direction.")
parser.add_argument("--normalize-or-by-adr", action="store_true", default=False, dest="normalize_or_by_adr",
    help="Normalize OR range by prior-day 20-day ADR before scoring (levels high/low-vol tickers).")
parser.add_argument("--score-entry-weight", type=float, default=0.50, dest="score_entry_weight",
    help="Score weight for entry_vs_mid_pct (default: 0.50).")
parser.add_argument("--score-avg-win-weight", type=float, default=0.30, dest="score_avg_win_weight",
    help="Score weight for avg_win_pct (default: 0.30).")
parser.add_argument("--score-win-rate-weight", type=float, default=0.0, dest="score_win_rate_weight",
    help="Score weight for rolling win_rate (default: 0.0).")
parser.add_argument("--score-rel-strength-weight", type=float, default=0.0, dest="score_rel_strength_weight",
    help="Score weight for cross-sectional relative MA50 strength vs pool mean (default: 0.0).")
parser.add_argument("--min-pool-vote", type=int, default=0, dest="min_pool_vote_to_trade",
    help="Skip day if fewer than N pool tickers have positive rolling EV (default: 0 = off).")
```

In both `OpMomentumTradeEngine(...)` instantiation blocks (foreground `run` and daemon
`start`), add:
```python
ma_momentum_gate=args.ma_momentum_gate,
score_entry_weight=args.score_entry_weight,
score_avg_win_weight=args.score_avg_win_weight,
score_win_rate_weight=args.score_win_rate_weight,
score_rel_strength_weight=args.score_rel_strength_weight,
normalize_or_by_adr=args.normalize_or_by_adr,
min_pool_vote_to_trade=args.min_pool_vote_to_trade,
```

---

## Parity Checklist (pre-implementation, see CLAUDE.md)

- [ ] **Temporal alignment:** ADR uses `shift(1)` so today's score uses yesterday's ADR. ✓ confirmed in backtest.
- [ ] **Temporal alignment:** `rel_ma50_dist_pct` uses prior-day open vs prior-day MA50 (shift(1) in daily series). Use `target_date - 1 bday` open.
- [ ] **Lookahead guard:** `min_pool_vote_to_trade` counts `rolling_stats` which only covers `date < target_date`. ✓ no lookahead.
- [ ] **`ma_momentum_gate` parity:** Check that `ma50` NaN handling in live engine matches backtest (`continue` on NaN, same as backtest line 521).
- [ ] **`normalize_or_by_adr` zero-division:** Guard `_adr > 0` before dividing (matches backtest line 1822).
- [ ] **`score_rel_strength_weight` with empty pool:** Guard `valid_vals` non-empty before computing pool mean.
- [ ] **`select_top_n()` returned dict shape:** All three early-return paths (pool_vote gate, no_signal, negative_ev) must return the same `{"picks", "no_signal", "negative_ev", "rolling_stats"}` shape that `TickerSelector.select()` reads.
- [ ] **Score weights sum ≤ 1.0:** `score_ticker()` raises `ValueError` if weights exceed 1.0 (lines 343–356). With `--score-win-rate-weight 0.10` + `--score-rel-strength-weight 0.05`, the default remaining budget for `or_range_weight = 1 - 0.50 - 0.30 - 0.10 - 0.05 = 0.05`. Document this constraint in help text.
- [ ] **Test:** Add unit tests in `tests/op_momentum_trade_engine/` covering:
  - `LiveSignalEngine._try_fire_signal()` with `ma_momentum_gate=True`, BULLISH gate passes/fails
  - `select_top_n()` with `min_pool_vote_to_trade=4` when only 3 tickers have positive EV → empty picks
  - `select_top_n()` with `normalize_or_by_adr=True` → `or_range_pct` is reduced proportionally
  - `select_top_n()` with `score_win_rate_weight=0.1` → score ranks shift correctly

---

## Suggested CLI Invocation (replay validation)

Run the backtest and the replay engine with identical params and verify picks match:

```bash
# Backtest reference
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2026-05-01 --end 2026-05-30 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --ma-momentum-gate \
  --normalize-or-by-adr \
  --score-avg-win-weight 0.30 --score-entry-weight 0.50 \
  --score-win-rate-weight 0.10 --score-rel-strength-weight 0.05 \
  --min-pool-vote 4

# Replay engine (after this feature is implemented)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-start 2026-05-01 --replay-end 2026-05-30 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --regime-filter --regime-ma 8 --rank-weighted-sizing 50 30 20 \
  --ma-momentum-gate \
  --normalize-or-by-adr \
  --score-avg-win-weight 0.30 --score-entry-weight 0.50 \
  --score-win-rate-weight 0.10 --score-rel-strength-weight 0.05 \
  --min-pool-vote 4 \
  --feed iex --full-day
```

---

## File Change Summary

| File | Change type | Scope |
|---|---|---|
| `signal_engine.py` | Add param + logic | `LiveSignalEngine.__init__`, `_try_fire_signal` |
| `op_momentum_selector.py` | Add params + logic | `select_top_n()` |
| `trade_engine.py` | Add params + wiring | `TickerSelector.__init__`, `TickerSelector.select`, `OpMomentumTradeEngine.__init__`, `_run_window_selectors` |
| `op_momentum_trade_engine.py` | Add CLI args + pass-through | `parse_args()`, both engine instantiation blocks |
| `tests/op_momentum_trade_engine/test_signal_engine.py` | New tests | `ma_momentum_gate` gate logic |
| `tests/op_momentum_trade_engine/test_trade_engine.py` | New tests | `min_pool_vote`, weight routing |
