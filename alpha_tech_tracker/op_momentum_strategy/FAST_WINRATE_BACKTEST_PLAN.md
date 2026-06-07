# Fast Win-Rate Selector Backtest — Implementation Plan

## Problem

The current backtest spawns one full OS process per trading day via
`run_replay_m1_winrate_regimehold_cap80k.sh`. Measured cost: **3m 13s per day**.

At 252 days/year × 20 parallel processes: ~40 min/year, ~6 hours for 9 years (2018–2026).

## Goal

Implement a fast in-process backtest in `ma_open_range_momentum_screener.py` that mirrors
the win-rate selector strategy logic exactly, optimized for batch execution.

Target: **full year in < 30 seconds**, 9 years in < 5 minutes, single process.

---

## Why the Live Engine Is Slow for Backtesting

The live engine is built for live trading. Each replay process pays overhead that is
irrelevant to backtesting:

| Overhead | Live engine | Fast backtest |
|---|---|---|
| Process startup (imports, logging, threading) | ~10s | zero |
| Warmup bar loading per day (disk + deser × 20 tickers) | ~1-3s per day | once at start |
| Bar-by-bar playback (WebSocket-style event loop) | every bar | skip |
| Exit monitoring (hard stop, trailing MA, re-entry watchers) | per bar | skip (EOD hold) |
| Position monitor thread | per day | skip |

With `--regime-hold --stop-pct 0 --trailing-ma none`, every trade exits at EOD.
Bar-by-bar simulation adds zero information — entry and exit are fully determined
at signal time.

---

## What to Mirror from the Live Engine

### 1. Pre-session ranking — `WinRateTickerSelector.select()`

```
ranked = _rank_tickers_by_eod_win_rate(ticker_bars, day, or_start, or_bars, lookback=20)

if LONG regime:   picks = ranked[:top_n]             # top-N by EOD win rate
if SHORT regime:  picks = reversed(ranked[-top_n:])  # bottom-N (worst first)
```

Tickers with no prior-day EOD win-rate history are excluded from `ranked` and cannot trade.

### 2. Win-rate signal conditions — `signal_engine._try_fire_win_rate_signal()`

Scan collection window bars one at a time (no lookahead):

```
For each bar i in [or_bars-1 .. or_bars-1+collection_bars-1]:
    col_vol = mean(volumes[0..i])          # incremental, mirrors live cbuf
    overlapping_mas = MAs where or_low ≤ MA ≤ or_high

    if not overlapping_mas: continue       # no MA in OR range → skip bar

    BULLISH: close > OR_mid
             AND col_vol > vol_20day_avg

    BEARISH: close < OR_mid
             AND col_vol < vol_20day_avg
             AND close < MA20
             AND (MA200 missing OR close < MA200)

    First bar that qualifies → entry_price = bar.close, done
```

`vol_20day_avg` = mean of collection-window volumes over the past 20 trading days
(same time slots, same bar count), computed by `_compute_collection_vol_20day_avg()`.

### 3. Regime direction — `RegimeEngine`

Reuse `RegimeEngine` exactly as the live engine does:

```python
# For each day:
regime_engine.compute_and_add_metrics(bars_5m, prev_day, or_start, or_bars, collection_bars)
presession_top_wr = ranked[0][1]["win_rates"][None] / 100.0 if ranked else None
regime = regime_engine.get_current_regime(presession_top2_wr=presession_top_wr, as_of_date=day)
direction = regime.direction   # "LONG" / "SHORT" / "NEUTRAL" / "NO_POSITION"
```

Regime filter:
- `LONG` → only BULLISH signals trade
- `SHORT` → only BEARISH signals trade
- `NEUTRAL` → both directions allowed
- `NO_POSITION` / `CAUTION` → no trades that day

### 4. Capital allocation — "drain" logic

```python
slot_capital = capital / len(signals_fired)   # NOT capital / top_n
```

When fewer signals fire than `top_n`, the capital is evenly split among what fired.
When zero signals fire, deployed = 0.

### 5. Exit — regime-hold (EOD)

```python
exit_price = day_df.iloc[-1]["Close"]   # last 5-min bar of the day (~15:55)
pnl = (exit - entry) / entry * slot_capital * direction_sign
```

No stop, no trailing MA, no intrabar exit logic needed.

---

## Implementation

### New functions to add to `ma_open_range_momentum_screener.py`

#### A. `_winrate_signal_day(ticker, df, day, or_start_time, or_bars, collection_bars, vol_20day_avg)`

Pure function. Scans one ticker for one day.
Returns `(signal, entry_price)` or `(None, None)`.
Mirrors `_try_fire_win_rate_signal()` exactly.

No class state, no threading — just DataFrame math.

#### B. `run_winrate_selector_backtest(tickers, start_date, end_date, ...)`

Main entry point. Algorithm:

```
Step 0 — Bulk load (once)
    fetch_bars(tickers + QQQ, start_date - 65 days, end_date, feed=sip)
    _add_ma_columns() on each DataFrame

Step 1 — Identify trading days from bar index dates

Step 2 — Init RegimeEngine (one instance, reused across all days)

Step 3 — For each trading day:
    a. ranked = _rank_tickers_by_eod_win_rate(ticker_bars, day, ...)
    b. regime_engine.compute_and_add_metrics(bars_5m, prev_day, ...)
       regime = regime_engine.get_current_regime(as_of_date=day)
       direction = regime.direction
    c. picks = ranked[:top_n] or reversed(ranked[-top_n:])
    d. For each ticker in picks:
         vol_avg = _compute_collection_vol_20day_avg(...)
         signal, entry = _winrate_signal_day(...)
         apply regime direction filter
    e. slot_capital = capital / len(fired_signals)
    f. pnl per trade = (exit - entry) / entry * slot_capital * sign
    g. Append daily result

Step 4 — Print summary
```

Signature:
```python
def run_winrate_selector_backtest(
    tickers,
    start_date,
    end_date,
    or_start=_DEFAULT_OR_START,   # "09:30"
    or_bars=_DEFAULT_OR_BARS,     # 3
    collection_bars=3,            # mirrors --extend-collection-bars 2 (1 base + 2 ext)
    top_n=8,
    capital=80_000.0,
    feed="sip",
    lookback_days=20,
    use_regime_engine=True,
    verbose=False,                # print per-day breakdown
) -> dict:
```

Returns `{"daily": [...]}` where each entry has `date, pnl, deployed, trades`.

#### C. `_print_winrate_backtest_summary(daily_results, capital, ...)`

Custom output format (not tied to replay script format):

```
╔══ Win-Rate Selector Backtest ══════════════════════════════════════
║  Pool     : NVDA TSLA META AMZN MSFT + 15 more  (20 tickers)
║  Config   : 09:30/3b  collect=3  top-8  $80,000  sip
║  Period   : 2026-01-02 → 2026-06-06  (106 trading days)
╠══ MONTHLY ══════════════════════════════════════════════════════════
║  Jan 2026    21d   +$  3,456.78   ( +4.3%)
║  Feb 2026    19d   +$  9,223.16   (+11.5%)
║  Mar 2026    21d   +$  2,100.00   ( +2.6%)
╠══ SUMMARY ══════════════════════════════════════════════════════════
║  Total       106d   +$24,567.89   (+30.7% on $80,000)
║  Trade days  82 / 106  (77.4%)
║  Avg deployed   $73,456  |  util 91.8%
║  Mean RODC      +0.312%
║  DW-Sharpe      4.23
╚════════════════════════════════════════════════════════════════════

# With --verbose: also prints per-day table
── DAILY ──────────────────────────────────────────────────────────
  2026-01-02 Thu  [NVDA AAPL TSLA         ]  +$  1,234.56
  2026-01-05 Mon  [—                      ]  $      0.00
```

### CLI integration

Add `winrate-backtest` to the `action` choices in `_build_arg_parser()`:

```bash
python -m alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
  winrate-backtest \
  --tickers NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX \
            HOOD SOFI SMCI HIMS IONQ MARA RIOT ASTS RKLB JOBY \
  --start 2026-01-02 --end 2026-06-06 \
  --top 8 --capital 80000 \
  --collection-bars 3 \
  --feed sip \
  --verbose
```

New CLI args to add (reuse existing where possible):
| Arg | Default | Note |
|---|---|---|
| `--start` | required | already exists |
| `--end` | required | already exists |
| `--tickers` | DEFAULT_TICKERS | already exists |
| `--top` | `8` | new |
| `--capital` | `80000` | new |
| `--collection-bars` | `3` | already exists |
| `--lookback-days` | `20` | new |
| `--no-regime` | off | new flag, disables RegimeEngine |
| `--verbose` | off | new flag, enables per-day table |
| `--feed` | `sip` | already exists |

---

## What the Fast Backtest Skips (Valid for This Config)

| Feature | Skipped because |
|---|---|
| Bar-by-bar exit monitoring | `--regime-hold` → EOD exit only |
| Hard stop price | `--stop-pct 0` |
| Trailing MA exit | `--trailing-ma none` |
| Re-entry / reversal / doubledown | not in base config |
| Fractional share rounding | ~0.1% rounding diff, acceptable |
| Option contract logic | stock mode only |
| Process startup + logging infra | single in-process execution |

---

## Parity Verification (before declaring done)

After implementation, run both approaches on the same dates and compare:

```bash
# Fast backtest
python -m alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
  winrate-backtest --tickers ... --start 2026-02-02 --end 2026-02-27 \
  --top 8 --capital 80000 --verbose

# Replay (ground truth)
./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026 --summary
# filter Feb only
```

Pass criteria:
- [ ] Per-day P&L within ±1% of replay for ≥ 90% of days
- [ ] Monthly totals within ±2% of replay
- [ ] "Drain" capital check: day with 1 signal deploys full $80k
- [ ] Regime filter: same days skipped as in replay logs
- [ ] No-trade days match (regime blocks / no valid signal)

Acceptable divergence sources:
- Fractional share rounding (< 0.2% per trade)
- Screener vs signal_engine `_add_ma_columns` floating point differences

---

## File Changes

| File | Change |
|---|---|
| `ma_open_range_momentum_screener.py` | Add `_winrate_signal_day()`, `run_winrate_selector_backtest()`, `_print_winrate_backtest_summary()`; update `_build_arg_parser()` and `main()` |

No other files changed. New code is additive — existing screener functions untouched.

---

## Expected Performance

| Scenario | Current replay | Fast backtest |
|---|---|---|
| 1 day | 3m 13s | < 1s |
| 1 year (252d) | ~40 min | ~20-30s |
| 9 years (2018–2026) | ~6 hours | ~3-5 min |

The dominant cost in the fast backtest is `_rank_tickers_by_eod_win_rate` (called once per day,
iterates 20 days × N tickers × ~78 bars). If 9-year runs are still slow, the next optimization
is to pre-compute daily EOD returns and OR-close prices in a single vectorized pass, replacing
the per-day DataFrame scans. That is left as a follow-up if needed.

---

## Calibration Results (2026-06-06)

Implementation complete and calibrated to the May 2026 replay.

### Ground truth

Replay config (`run_replay_m1_winrate_regimehold_cap80k.sh`):
```
--selector win-rate --enable-regime-engine
--window M1 09:30 3 --morning-split 100
--top 8 --capital 80000
--stop-pct 0 --trailing-ma none --regime-hold
--fixed-signal-alloc --mock-trade-execution --feed sip
```
Replay ticker pool (19 tickers): `SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT`

### Calibrated fast BT command

```bash
python -m alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener winrate-backtest \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --start YYYY-MM-01 --end YYYY-MM-30 \
  --or-bars 3 --collection-bars 3 --top 8 --capital 80000 --feed sip
```

No `--lookback-days` flag needed — default is now 60, matching the live engine (`ROLLING_LOOKBACK_DAYS = 60`).

### May 2026 parity

| | Total P&L |
|---|---|
| Fast BT | +$2,025.34 |
| Replay | +$2,055.47 |
| **Gap** | **-$30.13** |

Day-by-day: 18/20 days match within cents. The two exceptions:
- **5/26**: Replay +$29.88 (SNPS direct-entry), fast BT $0.00 — structural diff, accepted
- **5/27**: -$0.10 rounding from fractional shares in replay

### Key fixes applied during calibration

| Issue | Fix |
|---|---|
| Wrong lookback (30 → 60) | `run_winrate_selector_backtest()` default and CLI `--lookback-days` both changed to 60 to match `ROLLING_LOOKBACK_DAYS` |
| EOD exit at 15:55 vs 15:50 | `_winrate_exit_with_fallback()` clips `day_df` to `< 15:55` before taking the last bar — matches `BarReplayDriver`'s strict `< 15:55` cutoff |
| Wrong ticker pool | Must pass the 19-ticker replay pool; `DEFAULT_TICKERS` (V3) is different |

### Accepted structural differences

| Diff | Cause | Frequency |
|---|---|---|
| SNPS direct-entry trades | SNPS occasionally fires via `_on_signal_for_window` direct path even when outside top-8 pre-market picks | ~1–2 per month |
| Fractional share rounding | Replay uses fractional shares; fast BT uses exact dollar allocation | ±$0.10–$0.20 per trade |
