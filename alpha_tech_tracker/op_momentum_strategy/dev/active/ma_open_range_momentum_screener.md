# MA / OR Screener — Implementation Plan

## Overview

A new screener (`ma_or_screener.py`) that monitors all tickers in the pool and fires SMS
alerts when an **Opening Range (OR) / Moving Average overlap signal** is detected.

Core idea: when the OR price range brackets a key 5-min MA, the market is giving you a
structural reference level — a breakout above OR mid with MA support (bull) or a breakdown
below OR mid with MA resistance (bear) is a high-quality setup.

Two modes:
- **Backtest** — run against a past date using Alpaca SIP historical data
- **Live** — poll TradeStation bar API on a timer; fire SMS when a signal is detected

---

## Signal Logic

### Opening Range

```
OR_High  = max(High)  of the first N 5-min bars starting at or_start (default 09:30)
OR_Low   = min(Low)   of the first N 5-min bars starting at or_start
OR_mid   = (OR_High + OR_Low) / 2
OR_range = OR_High - OR_Low

or_vol   = mean(Volume of the N OR bars)   # fixed once OR closes
```

`N` is configurable via `--or-bars` (default 3 = 15-minute OR, closes at 9:45).

### MA Overlap Condition

At each bar after the OR closes, compute MA20, MA50, MA200 on the 5-min price series.
A MA "overlaps" the OR range if its value falls inside [OR_Low, OR_High]:

```
overlapping_mas = [
    name for name, val in [("MA20", ma20), ("MA50", ma50), ("MA200", ma200)]
    if OR_Low <= val <= OR_High
]
ma_overlap = len(overlapping_mas) > 0
```

The OR boundaries are fixed at the N-th bar close; MA values update with each new bar.

### Volume Condition

`vol_ma20` and `vol_ma200` are rolling 20-bar and 200-bar MAs of the 5-min volume series,
recomputed at each bar. `or_vol` (average OR bar volume) is compared against these MAs:

```
bull_vol = or_vol > vol_ma200          # high-volume OR = buyer participation
bear_vol = or_vol < vol_ma200 and or_vol < vol_ma20   # low-volume OR = no buyers
```

### Signal Evaluation — Per-Bar After OR Closes

Signals are evaluated **on every 5-min bar from the N-th bar onwards** (not just the
N-th bar close). Once a signal fires for a ticker, it is latched for the session.

**Bull Signal** (all three must be true at any bar ≥ N):
1. `current_close > OR_mid`         — price in top half of OR range
2. `ma_overlap == True`             — at least one 5-min MA (20/50/200) inside OR range
3. `or_vol > vol_ma200`             — OR volume above 200-bar MA volume

**Bear Signal** (all three must be true at any bar ≥ N):
1. `current_close < OR_mid`         — price in bottom half of OR range
2. `ma_overlap == True`             — at least one 5-min MA inside OR range
3. `or_vol < vol_ma200 and or_vol < vol_ma20`  — OR volume below both volume MAs

### QQQ Context (display only)

Compute QQQ 5-min vol_ma200 at each bar. Report in SMS and backtest output:
- `QQQ above 200MV` if current QQQ close > QQQ vol_ma200
- `QQQ below 200MV` otherwise

Not used as a gate — display only.

---

## Data Requirements

### 5-min bars (tickers + QQQ)

| Purpose                         | Warmup needed             | Fetch window              |
|---------------------------------|---------------------------|---------------------------|
| OR computation (N bars)         | 0 (current-day only)      | —                         |
| 5-min MA20 price + vol          | 20 bars ≈ 2 h             | Prior-day bars + today    |
| 5-min MA50 price                | 50 bars ≈ 4 h             | ~1 day lookback           |
| 5-min MA200 price + vol_ma200   | 200 bars ≈ 3 trading days | ~5 day lookback           |

Fetch **10 calendar days** of 5-min bars to guarantee 200+ bar warmup across holidays.

### Daily bars (tickers + QQQ)

Tracked for display and future use. Not used in signal conditions at this stage.

| Purpose      | Days needed |
|--------------|-------------|
| Daily MA20   | 22          |
| Daily MA50   | 55          |
| Daily MA200  | 220         |

Fetch **260 calendar days** of daily bars. Store as a separate dict in the result;
compute and display daily MA values but do not gate signals on them.

### 1-min bars (tickers)

Fetched for the target date only. Not used in signal logic at this stage.
Included in the result dict as `bars_1m` to support future use cases.

---

## Architecture

### Single new file

```
alpha_tech_tracker/op_momentum_strategy/ma_or_screener.py
```

Reuse without modification:
- `fetch_bars()` from `op_momentum_backtest.py` — Alpaca SIP + TradeStation
- `_notify()` from `config.py` — ClickSend SMS
- `disable_notifications()` from `config.py` — suppress SMS in backtest / dry-run
- `MarketDataClient` broker abstraction — TradeStation live client injection

---

### Core signal function

```python
def compute_or_ma_signals(
    bars_5m: dict,        # {ticker: DataFrame} — must include MA20/50/200, VolMA20/200 columns
    qqq_bars_5m: pd.DataFrame,
    or_start: str,        # "09:30"
    or_bars: int,         # N bars defining OR
    target_date: date,
) -> list[dict]:
```

For each ticker:
1. Slice to `target_date`
2. Identify the N OR bars (from `or_start`)
3. Compute OR_High, OR_Low, OR_mid, or_vol (fixed once)
4. Iterate over each bar from the N-th bar onwards
5. At each bar: check bull/bear conditions; latch and record the first match
6. Return one signal dict per ticker that fired

Each signal dict:
```python
{
    "ticker":           "TSLA",
    "direction":        "BULL",           # "BULL" or "BEAR"
    "signal_bar_time":  "09:50",          # when the signal fired
    "or_high":          345.20,
    "or_low":           342.10,
    "or_mid":           343.65,
    "or_range":         3.10,
    "close":            344.50,           # close at signal bar
    "overlapping_mas":  ["MA20"],         # which MAs were inside OR range
    "ma20_5m":          343.80,
    "ma50_5m":          341.00,
    "ma200_5m":         338.50,
    "or_vol":           1_250_000,
    "vol_ma20_5m":      980_000,
    "vol_ma200_5m":     850_000,
    "daily_ma20":       340.00,           # tracked, not gated
    "daily_ma50":       335.00,
    "daily_ma200":      310.00,
    "qqq_above_200mv":  True,             # QQQ close vs QQQ vol_ma200
    "date":             "2026-05-31",
}
```

---

### Backtest function

```python
def run_backtest(
    target_date: date,
    tickers: list,
    or_bars: int = 3,
    or_start: str = "09:30",
    source: str = "alpaca",
    feed: str = "sip",
    print_all: bool = False,
) -> list[dict]:
```

Steps:
1. `disable_notifications()`
2. `fetch_start = target_date - 10 calendar days`
3. Fetch 5-min bars: `fetch_bars(tickers + ["QQQ"], fetch_start, target_date, source, feed)`
4. Fetch daily bars: `fetch_bars(tickers + ["QQQ"], daily_start, target_date, source, feed, timeframe="1Day")`
   - `daily_start = target_date - 260 calendar days`
5. Fetch 1-min bars for `target_date` only; store in a separate dict (not used in signals)
6. Add MA columns to each ticker's 5-min DataFrame: MA20, MA50, MA200, VolMA20, VolMA200
7. Add daily MA columns (display only)
8. Call `compute_or_ma_signals()`
9. Print result table; return signal list

---

### Live polling function

```python
def run_live(
    tickers: list,
    or_bars: int = 3,
    or_start: str = "09:30",
    market_data_client=None,     # TradeStation MarketDataClient
    poll_interval_sec: int = 30,
    dry_run: bool = False,
) -> None:
```

Steps:
1. On startup: pre-fetch 10-day 5-min warmup + 260-day daily bars (Alpaca SIP for warmup)
2. Compute `or_close_time = parse(or_start) + or_bars × 5 min`
3. **Polling loop** (repeats each day):
   - Sleep until current ET time ≥ `or_close_time`
   - Fetch today's 5-min bars from TradeStation; append to warmup buffer; recompute MAs
   - Re-evaluate `compute_or_ma_signals()` on the updated buffer
   - For each new signal (not yet sent): `_notify(format_sms(signal))`
   - Continue polling until EOD (15:55 ET) to catch per-bar signals that fire later
   - At 15:55 ET: send summary SMS; reset state for next day

Live mode evaluates the signal function after every new bar arrives (not just at OR close),
so a signal that doesn't fire at 9:45 can still fire at 10:00 or later if the MA/price/volume
conditions are met for the first time on a later bar.

---

## SMS Format

**Per-signal alert:**
```
BULL SIGNAL: TSLA | OR 342.10-345.20 (mid 343.65) | 9:50 close 344.50 | MA20=343.80 in OR | vol 1.47x 200MV
BEAR SIGNAL: COIN | OR 180.00-183.50 (mid 181.75) | 9:45 close 180.20 | MA50=181.40 in OR | vol 0.62x 200MV 0.71x 20MV
```

**Session summary (sent at 15:55 ET or end of backtest):**
```
OR Screener 2026-05-31 | 3 signals (2 BULL, 1 BEAR) | QQQ above 200MV (bullish)
```

---

## CLI

### Backtest mode (default)

```bash
PYTHONPATH=... python -m alpha_tech_tracker.op_momentum_strategy.ma_or_screener \
  --date 2026-05-29 --or-bars 3 --or-start 09:30

# Custom ticker pool
  --tickers TSLA NVDA AAPL

# Print all tickers (not just signal ones)
  --print-all
```

### Live mode

```bash
PYTHONPATH=... python -m alpha_tech_tracker.op_momentum_strategy.ma_or_screener \
  --live --or-bars 3

# No SMS (dry run)
  --live --dry-run

# Custom poll interval (seconds)
  --live --poll-interval 60
```

### Full arg table

| Arg                              | Default           | Description                                  |
|----------------------------------|-------------------|----------------------------------------------|
| `--date YYYY-MM-DD`              | today             | Target date (backtest mode)                  |
| `--live`                         | off               | Run live polling mode                        |
| `--or-bars N`                    | `3`               | Number of 5-min bars in the OR window        |
| `--or-start HH:MM`               | `09:30`           | OR window start time ET                      |
| `--tickers T1 T2 ...`            | `DEFAULT_TICKERS` | Override ticker pool                         |
| `--source {alpaca,tradestation}` | `alpaca`          | Data source for backtest                     |
| `--feed {sip,iex}`               | `sip`             | Alpaca feed for backtest                     |
| `--poll-interval N`              | `30`              | Seconds between live polls                   |
| `--dry-run`                      | off               | Suppress SMS in live mode                    |
| `--print-all`                    | off               | Print non-signal tickers in backtest output  |

---

## Implementation Phases

### Phase 1 — Backtest + Signal Logic

1. `_add_ma_columns(df)` — adds MA20/MA50/MA200/VolMA20/VolMA200 to a 5-min DataFrame
2. `compute_or_ma_signals()` — per-bar scan from OR close, returns signal dicts
3. `run_backtest()` — fetch → MA compute → signal scan → print table
4. CLI: `--date`, `--or-bars`, `--or-start`, `--tickers`, `--print-all`, `--source`, `--feed`
5. Unit tests: mock bar DataFrames, cover bull/bear/no-signal/MA-outside-OR cases

### Phase 2 — SMS + Live Polling

6. `format_sms(signal_dict)` — formats a single signal for SMS
7. `run_live()` — TradeStation polling loop, per-bar re-evaluation, `_notify()` calls
8. `--live`, `--dry-run`, `--poll-interval` CLI flags
9. Integration smoke test: `--live --dry-run` against today with TS session active

---

## Guard Conditions (from pre-implementation checklist)

- `OR_range == 0`: skip MA overlap check (trivially contains everything); emit warning
- `vol_ma200 == NaN` (insufficient warmup bars): skip volume condition; log warning
- Sparse tickers with missing bars: `_add_ma_columns()` uses `min_periods=1` to avoid
  propagating NaN into the entire MA series on short warmup
- Signal latching: once a ticker fires BULL or BEAR for the day, skip it on subsequent bars
  (no re-fire, no direction flip within the same session)
- Daily data lookahead: daily MA values in the result dict use the prior day's close
  (`.shift(1)`) — not today's close which is unknown at OR time
