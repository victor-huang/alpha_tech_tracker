# Op Momentum Trade Engine

Live options (and stock) trading engine based on the opening-range momentum strategy.
Runs intraday each market day: selects the top 3 tickers by composite score,
fires a signal after the opening range closes, buys a weekly option (or stock),
and manages the position until an exit condition fires or market close.

---

## Strategy Summary

| Parameter | Value |
|---|---|
| Account size | $25,000 |
| Active symbols per day | 3 (top by composite score) |
| Opening range | First 3 × 5-min bars (9:30–9:45 AM ET) |
| Option expiry | Weekly (next Friday), monthly fallback |
| Strike selection | ITM strike where time premium ≈ 1% of stock price |
| Capital per symbol | 45% of options buying power |
| Position weights | 50% / 30% / 20% by rank (when `--rank-weighted-sizing`) |

**Signal conditions (evaluated after opening range closes):**

- **BULLISH** — close above OR midpoint, above MA20, above MA200
- **BEARISH** — close in bottom 20% of OR range, below MA20
- **NEUTRAL** — no trade

**Exit conditions (checked every 30 seconds):**

- Hard stop: price reverses past `OR_high − 15% × OR_range` (bull) or `OR_low + 15% × OR_range` (bear)
- Trailing stop: price crosses MA20 (default) or MA50
- Fallback: price retreats to 20th/80th percentile of OR range before stop arms
- End of day: force-close at 3:55 PM ET

---

## Prerequisites

### 1. Alpaca account with options trading enabled

Log in at [alpaca.markets](https://alpaca.markets) and enable options trading under
**Account → Options Trading**. The engine requires **Level 2** approval (buying calls and puts).

Paper trading accounts also require options to be enabled separately.

### 2. API credentials

```bash
export ALPACA_API_KEY="your_api_key_here"
export ALPACA_SECRET_KEY="your_secret_key_here"
```

Add these to your shell profile (`~/.zshrc` or `~/.bash_profile`) to avoid setting
them each session.

### 3. Python virtualenv

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
```

---

## Running the Engine

All commands must be run from the project root:

```bash
cd /Users/victorhuang/work/alpha_tech_tracker
export PYTHONPATH=.
```

### Recommended daily run (paper, mock fills, regime filter)

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --log-level INFO
```

### Live trading (real money)

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --live \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100
```

### With option price monitor (smart limit prices + CSV snapshots)

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --collect-option-prices \
  --option-price-interval 300
```

`--collect-option-prices` enables a background thread that:
- Snapshots bid/ask/intrinsic/time value every N seconds for all tickers
- Writes CSVs to `market_data/options_price_data/YYYY-MM-DD/{ticker}_{call|put}.csv`
- Feeds the cached time premium back to the engine to compute smarter entry/exit limit prices

### Stock trading

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --trade-type stock
```

### Run as background daemon

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine start \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100

# Check status
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine status

# Stop
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine stop
```

---

## Log Files

Logs are written to `logs/op_momentum_YYYY-MM-DD.log` (date stamped at startup) and
rotated automatically at midnight, keeping 30 days of history. In foreground `run`
mode, logs also print to the terminal.

```bash
tail -f logs/op_momentum_$(date +%Y-%m-%d).log
```

---

## All CLI Options

```
positional arguments:
  {run,start,stop,status,restart}
      run: foreground | start: daemon | stop | status | restart

optional arguments:
  --live                    Use live trading account (default: paper trading)
  --mock-trade-execution    Simulate order fills at mid bid/ask — no real orders placed
  --tickers                 Override ticker universe, e.g. --tickers NVDA TSLA
  --stop-pct                Hard stop as fraction of OR range (default: 0.15)
  --trailing-ma             MA for trailing stop: ma20, ma50, or both (default: ma20)
  --max-loss-pct            Per-trade max loss as fraction of entry price (e.g. 0.02)
  --armed-ma20-exit         Use MA20 as trailing exit once hard stop is armed
  --regime-filter           Suppress BULLISH signals on QQQ bearish days
  --regime-ma               N-day MA for QQQ regime filter (default: 5)
  --rank-weighted-sizing    Weight positions 50/30/20% by rank
  --opening-start           Single-window start time HH:MM ET (default: 09:30)
  --window LABEL START BARS Define a named trading window (repeatable)
  --morning-split PCT       Capital split % for simultaneous morning windows
  --trade-type              Trade type: options (default) or stock
  --collect-option-prices   Enable background option price collection and fair-price advisor
  --option-price-interval   Snapshot interval in seconds (default: 300)
  --log-file                Override log file path (default: logs/op_momentum_YYYY-MM-DD.log)
  --log-level               Log verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)
  --pid-file                PID file for daemon mode

Re-entry & Reversal (all off by default):
  --reversal                If a BEARISH primary stops out within N bars and price later
                            crosses above OR high, enter BULLISH with midpoint as hard stop
  --reversal-max-bars INT   Max bars_held for BEARISH primary to qualify (default: 3)
  --bearish-reentry         If a BEARISH primary stops out within N bars and price later
                            crosses below OR low, re-enter BEARISH with midpoint as hard stop
                            (suppressed when --reversal is enabled and both would fire)
  --bearish-reentry-max-bars INT  Max bars_held for BEARISH primary to qualify (default: 3)
  --bullish-reentry         If a BULLISH primary stops out within N bars and price later
                            crosses above OR high, re-enter BULLISH with midpoint as hard stop
  --bullish-reentry-max-bars INT  Max bars_held for BULLISH primary to qualify (default: 5)
```

---

## Re-entry & Reversal Trades

Three optional second-leg patterns can be enabled. Each watches for a specific price
level after the primary position closes, then opens a new position in the same window.

| Pattern | Primary | Trigger | New direction | Hard stop | Trailing arm gate |
|---|---|---|---|---|---|
| Reversal | BEARISH | price crosses above OR high | BULLISH | midpoint (armed immediately) | entry + OR range |
| Bearish re-entry | BEARISH | price crosses below OR low | BEARISH | midpoint | entry − OR range |
| Bullish re-entry | BULLISH | price crosses above OR high | BULLISH | midpoint (armed immediately) | entry + OR range |

**Eligibility**: the primary must have stopped out via hard stop or fallback (not trailing MA),
and the number of bars held must not exceed the configured max (`--reversal-max-bars`, etc.).

**Priority**: reversal and bearish re-entry cannot both fire from the same BEARISH primary.
When `--reversal` is enabled, it takes priority and the bearish re-entry watcher is suppressed.

**Trailing arm**: re-entry positions delay the MA trailing stop until price moves favorably
by one full OR range from the entry price, preventing premature exits on shallow fills.

**EOD**: all pending watchers are cleared when `close_all()` runs at 3:55 PM — no re-entry
trades can fire after EOD wind-down begins.

### Example commands

Reversal only (BEARISH primary flips BULLISH on OR-high cross within 3 bars):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --reversal --reversal-max-bars 3
```

Reversal + bullish re-entry (cover both BEARISH and BULLISH primary stopouts):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --reversal --reversal-max-bars 3 \
  --bullish-reentry --bullish-reentry-max-bars 5
```

All three patterns (adds bearish re-entry for cases where reversal is not eligible):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --reversal --reversal-max-bars 3 \
  --bearish-reentry --bearish-reentry-max-bars 3 \
  --bullish-reentry --bullish-reentry-max-bars 5
```

> Note: these patterns have not yet been backtest-validated for the current ticker pool.
> Run `op_momentum_selector_backtest.py` with the equivalent flags before enabling in live trading.

---

## Daily Timeline

```
Before 9:30 AM  Score all tickers via 60-day rolling backtest → pick top 3
                Download 5 days of 5-min bars to warm MA20 / MA50 / MA200

9:30 AM         WebSocket stream opens; option price monitor starts (if enabled)

9:30–9:45 AM    Collect 3 opening bars (opening range)

9:45 AM         Evaluate signal (BULLISH / BEARISH / NEUTRAL)
                  → On signal: select ITM weekly option (time premium ≈ 1% of stock)
                               size position from buying power
                               place BUY limit order at fair price

9:45 AM–3:55 PM Monitor stops every 30 seconds

3:55 PM         Force-close any remaining open positions

After close     Print daily trade summary, exit
```

---

## Strike Selection

The engine uses **`TimePremiumContractSelector`** which finds the ITM strike where the
option's time premium (mid − intrinsic) just falls to or below 1% of the current stock
price. This targets a consistent cost-of-carry regardless of IV.

For example, with TSLA at $300 (1% target = $3):
- Scans ITM call strikes from near-ATM downward
- Selects the first strike where `mid − intrinsic ≤ $3`
- Falls back to deepest ITM if all strikes have higher time premium

The legacy fixed-offset selector (`ITMOptionContractSelector`) is still available in
`contract_selector.py` for backtesting or custom use.

---

## Ticker Universe

Defined in `config.py` (16 tickers, pool v2):

```python
TICKERS = [
    "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
    "EXPE", "FANG", "RH", "FN", "MU",
    "ANAB", "PLTR", "COIN", "NVDA", "TSLA",
]
```

The engine scores all 16 each morning and trades the top 3.
To override for a single run, use `--tickers`.

---

## Running Tests

```bash
PYTHONPATH=. python -m pytest tests/op_momentum_trade_engine/ -v
```
