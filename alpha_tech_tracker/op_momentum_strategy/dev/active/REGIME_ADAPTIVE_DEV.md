# Regime-Adaptive M1 Config — Dev Doc

## Overview

The `--regime-adaptive` flag makes the M1 window select its `bars` (OR window length)
and `stop_pct` dynamically each morning based on two pre-market signals:

1. **VIX** — prior day's close (no lookahead)
2. **QQQ 5-min MA alignment score** — count of MA8/20/50/200 that QQQ price is above
   at the 9:40 bar (the bar that closes at 9:45, i.e. the M1/3-bar entry moment)

This replaces a single fixed `--window M1 09:30 <bars> --stop-pct <stop>` with a
per-day lookup from a cross-year validated config table.

Only the M1 window is affected. Afternoon windows (A1, A2, …) keep their fixed config.

---

## Regime Config Table

Derived from the 8-year (2018–2025) cross-year sweep documented in
`M1_WINDOW_SWEEP_FINDINGS.md`.

| Bucket | VIX | MA score | Bars | Entry | Stop | Confidence |
|---|---|---|---|---|---|---|
| `vix_hi_ma_strong` | ≥ 22 | ≥ 3 | 4 | 9:50 | 0.4 | **High** (2020:114d, 2022:90d) |
| `vix_hi_ma_weak`   | ≥ 22 | ≤ 2 | 5 | 9:55 | 0.5 | Medium (2022:103d; 2021 flat) |
| `vix_mid_ma_strong`| 17–22 | ≥ 3 | 6 | 10:00 | 0.7 | Medium (2021:69d, 2023:55d) |
| `vix_mid_ma_weak`  | 17–22 | ≤ 2 | 6 | 10:00 | 0.5 | Medium (2021:67d, 2023:53d) |
| `vix_lo` (fallback)| < 17 | any | 5 | 9:55 | 0.5 | Low — no consistent winner |

VIX thresholds: `VIX_LO = 17`, `VIX_HI = 22`.
MA strong threshold: score ≥ 3 (out of 4 MAs above price).

---

## Implementation — Option A (pre-compute all regime configs)

### Why Option A

The backtest pre-computes all signals once via `compute_signals_with_backtest()` for
each (ticker, window). With regime-adaptive, different days need different `(bars, stop_pct)`.
Option A pre-computes the 4 distinct configs (only 3 unique bar counts: 4, 5, 6) at startup,
then the day loop just picks the right cache entry. No per-day re-computation.

Startup cost: ~3× signal computation time for the M1 window (4 configs but bars=6 covers
two buckets with different stop; since stop affects exit P&L not OR formation, both
buckets use the same bars=6 signal set with different stop applied at trade execution).

Actually: `stop_pct` IS baked into each signal row's P&L at signal computation time
(it determines the stop price during the simulated trade). So we need separate pre-computed
sets for each unique `(bars, stop_pct)` pair.

Unique regime `(bars, stop)` pairs: `(4, 0.4)`, `(5, 0.5)`, `(6, 0.7)`, `(6, 0.5)`.
That's 4 pre-computed M1 result sets.

### Data Flow

```
startup:
  1. fetch VIX daily data (yfinance ^VIX), shift +1 BDay → vix_prior
  2. fetch QQQ 5-min bars (fetch_bars), compute rolling MA8/20/50/200 → qqq_5min
  3. for each trading day d: classify → day_config_map[d] = (bars, stop)
  4. for each unique (bars, stop) in day_config_map.values():
       pre-compute M1 signals → regime_cache[(bars, stop)]
       build primary_window_results and results_by_date indexes

day loop (for d in trading_days):
  5. look up day_config_map[d] → (day_bars, day_stop)
  6. select eff_primary_wr and eff_by_date from regime_cache[(day_bars, day_stop)]
  7. use eff_primary_wr / eff_by_date in the scorer instead of the fixed ones (M1 only)
  8. compute or_close_min using day_bars (not win["opening_bars"])
  9. store "regime" bucket name in each trade_row
```

### New functions

```python
def _fetch_regime_data(fetch_start, eval_end, source, feed)
    → (vix_prior: pd.Series, qqq_5min: pd.DataFrame)

def _classify_day_regime(d, vix_prior, qqq_5min)
    → str  # bucket name, e.g. "vix_hi_ma_strong", or None on missing data

def _build_day_config_map(trading_days, vix_prior, qqq_5min)
    → dict[date, (int, float)]  # date → (bars, stop_pct)

def _build_m1_signals_for_config(bars, stop_pct, tickers, all_bars, **shared_kwargs)
    → dict[ticker, pd.DataFrame]  # same structure as all_window_results["M1"]
```

### Changes to `run_selector_backtest()`

New parameter: `regime_adaptive: bool = False`

After signal pre-computation:
```python
if regime_adaptive:
    vix_prior, qqq_5min = _fetch_regime_data(...)
    day_config_map = _build_day_config_map(trading_days, vix_prior, qqq_5min)
    regime_cache = {}
    for key in set(day_config_map.values()):
        r_bars, r_stop = key
        m1_wr = _build_m1_signals_for_config(r_bars, r_stop, tickers, all_bars, ...)
        regime_cache[key] = {
            "primary": _build_primary(m1_wr),
            "by_date": _build_by_date(m1_wr),
        }
```

Day loop changes (M1 window only):
```python
if regime_adaptive and label == "M1":
    day_key = day_config_map.get(d, REGIME_ADAPTIVE_CONFIGS["vix_lo"])
    eff_primary_wr = regime_cache[day_key]["primary"]
    eff_by_date    = regime_cache[day_key]["by_date"]
    eff_bars       = day_key[0]
else:
    eff_primary_wr = primary_window_results[label]
    eff_by_date    = results_by_date[label]
    eff_bars       = win["opening_bars"]
```

### Known limitations

- **Double-down not supported** with `--regime-adaptive` (exits with an error if both flags
  are set). Double-down uses `opening_bars_by_label` which is a fixed dict; per-day bar
  counts would require restructuring `_annotate_doubledown_addon`.
- **Capital flow drain timing**: `_apply_capital_flow` uses a fixed `drain_min[M1]` for
  all days. In regime-adaptive mode, M1's OR closes at 9:50 (bars=4) or 10:00 (bars=6)
  depending on the day. The difference (≤10 min) is unlikely to affect A1 availability
  since A1 starts at 10:30+ in all tested configs. Noted as a known minor inaccuracy.
- **Rolling stats use fixed-config lookback**: the rolling 60-day ticker stats (win rate,
  avg P&L) are computed from whichever pre-computed config applies to that day. Days
  classified into different configs see slightly different lookback pools — this is
  intentional and correct (each config's historical stats should inform its own scoring).

---

## CLI Usage

```bash
# Regime-adaptive M1, fixed afternoon windows
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 \
  --window M1 09:30 3 \          # bars here is the fallback; overridden per day
  --window A1 13:15 1 \
  --window A2 15:00 1 \
  --regime-adaptive \
  --bearish-reentry --bullish-reentry --reversal \
  --feed sip --min-hold-bars 1 \
  --start 2025-01-01 --end 2025-12-31

# Without afternoon windows (M1 only)
python ... --window M1 09:30 3 --regime-adaptive \
  --bearish-reentry --bullish-reentry --reversal \
  --feed sip --start 2025-01-01 --end 2025-12-31
```

The `bars` value in `--window M1 09:30 <bars>` is used only as a fallback when VIX or QQQ
data is unavailable for a given day. All other days use the regime table above.

---

## Output additions

Each trade row gains a `"regime"` field (e.g. `"vix_mid_ma_strong"`).
The daily summary line gains a `[REGIME]` prefix showing which bucket fired:

```
2025-03-14  [vix_hi_ma_weak / bars=5 s=0.5]  TSLA  +2.1%  ...
```

The end-of-run summary prints a regime distribution table:

```
Regime distribution (250 days):
  vix_lo              116 days  (46%)   avg P&L/day  +$X
  vix_mid_ma_strong    46 days  (18%)   avg P&L/day  +$X
  vix_mid_ma_weak      47 days  (19%)   avg P&L/day  +$X
  vix_hi_ma_strong     24 days  (10%)   avg P&L/day  +$X
  vix_hi_ma_weak       17 days   (7%)   avg P&L/day  +$X
  fallback              0 days   (0%)
```
