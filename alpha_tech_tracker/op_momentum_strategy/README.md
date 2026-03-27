# Op Momentum Trade Engine

Live options trading engine based on the opening-range momentum strategy.
Runs intraday each market day: selects the top 2 tickers by 30-day return,
fires a signal after the 15-minute opening range, buys a weekly option, and
manages the position until an exit condition fires or market close.

---

## Strategy Summary

| Parameter | Value |
|---|---|
| Account size | $25,000 |
| Active symbols per day | 2 (top by 30-day return) |
| Opening range | First 3 × 5-min bars (9:30–9:45 AM ET) |
| Option expiry | Weekly (next Friday) |
| BULLISH entry | CALL, strike ≈ 10% below current price |
| BEARISH entry | PUT, strike ≈ 10% above current price |
| Capital per symbol | 45% of options buying power |

**Signal conditions (evaluated after opening range closes):**

- **BULLISH** — close above OR midpoint, above MA20, above MA200
- **BEARISH** — close in bottom 20% of OR range, below MA20
- **NEUTRAL** — no trade

**Exit conditions (checked every 30 seconds):**

- Hard stop: price reverses past `OR_high − 15% × OR_range` (bull) or `OR_low + 15% × OR_range` (bear)
- Trailing stop: price crosses MA50
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

---

## Running the Engine

All commands must be run from the project root:

```bash
cd /Users/victorhuang/work/alpha_tech_tracker
```

### Paper trading (default — uses simulated money)

```bash
PYTHONPATH=. \
  ALPACA_API_KEY="..." \
  ALPACA_SECRET_KEY="..." \
  ~/.pyenv/versions/alpha_tech_tracker/bin/python \
  -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine
```

### Live trading (real money)

```bash
PYTHONPATH=. \
  ALPACA_API_KEY="..." \
  ALPACA_SECRET_KEY="..." \
  ~/.pyenv/versions/alpha_tech_tracker/bin/python \
  -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  --live
```

### Override the ticker universe

Skip the 30-day ranking and trade specific symbols:

```bash
... --tickers NVDA CRWD
```

### Verbose logging

```bash
... --log-level DEBUG
```

### All CLI options

```
usage: op_momentum_trade_engine.py [-h] [--live] [--simulate]
                                   [--tickers TICKERS [TICKERS ...]]
                                   [--stop-pct STOP_PCT]
                                   [--trailing-ma {ma20,ma50,both}]
                                   [--max-loss-pct MAX_LOSS_PCT]
                                   [--armed-ma20-exit] [--regime-filter]
                                   [--regime-ma REGIME_MA]
                                   [--rank-weighted-sizing]
                                   [--opening-start OPENING_START]
                                   [--pid-file PID_FILE] [--log-file LOG_FILE]
                                   [--log-level {DEBUG,INFO,WARNING,ERROR}]
                                   {run,start,stop,status,restart}

optional arguments:
  --live                Use live trading account (default: paper trading)
  --simulate            Simulate order fills at mid bid/ask — no real orders placed
  --tickers             Override ticker universe, e.g. --tickers NVDA CRWD
  --stop-pct            Hard stop as fraction of OR range (default: 0.15)
  --trailing-ma         MA to use for trailing stop: ma20, ma50, or both (default: ma20)
  --max-loss-pct        Per-trade max loss as fraction of entry price (e.g. 0.02 = 2%)
  --armed-ma20-exit     Use MA20 as trailing exit once hard stop is armed
  --regime-filter       Suppress BULLISH signals on QQQ bearish days
  --regime-ma           N-day MA period for QQQ regime filter (default: 5)
  --rank-weighted-sizing  Weight positions by rank: 50/30/20%
  --opening-start       Opening window start time HH:MM ET (default: 09:30)
  --log-level           Log verbosity (default: INFO)
```

---

## Daily Timeline

```
Before 9:30 AM  Fetch 30-day returns for all tickers → pick top 2
                Download 30 days of 5-min bars to warm MA20 / MA50 / MA200

9:30 AM         WebSocket stream opens for the 2 active tickers

9:30–9:45 AM    Collect 3 opening bars (opening range)

9:45 AM         Evaluate signal (BULLISH / BEARISH / NEUTRAL)
                  → On signal: select weekly option contract
                               size position from buying power
                               place BUY limit order at mid-price

9:45 AM–3:55 PM Monitor stops every 30 seconds

3:55 PM         Force-close any remaining open positions

After close     Print daily trade summary, exit
```

---

## Ticker Universe

The default candidates are defined in `config.py`:

```python
TICKERS = ["NVDA", "CRWD", "COIN", "JNJ", "XOM", "CAT"]
```

The engine ranks these by 30-day return each morning and trades the top 2.
To change the universe permanently, edit the `TICKERS` list in `config.py`.
To override for a single run, use `--tickers`.

---

## Running Daily with cron

To start the engine automatically each trading day before market open:

```bash
crontab -e
```

Add this line (runs at 9:15 AM ET, Mon–Fri):

```
15 9 * * 1-5 cd /Users/victorhuang/work/alpha_tech_tracker && \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  ~/.pyenv/versions/alpha_tech_tracker/bin/python \
  -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  >> ~/logs/op_momentum.log 2>&1
```

The engine exits automatically after the 3:55 PM EOD close, so no teardown cron is needed.

---

## Backtest

To evaluate the strategy on historical data before running live:

```bash
PYTHONPATH=. \
  ALPACA_API_KEY="..." \
  ALPACA_SECRET_KEY="..." \
  ~/.pyenv/versions/alpha_tech_tracker/bin/python \
  alpha_tech_tracker/op_momentum_strategy/op_momentum_backtest.py \
  --days 30 \
  --tickers NVDA CRWD COIN
```

See `op_momentum_backtest.py` for full backtest options (`--start`, `--end`, `--stop-pct`, etc.).

---

## Running Tests

```bash
PYTHONPATH=. \
  ~/.pyenv/versions/alpha_tech_tracker/bin/python \
  -m pytest tests/op_momentum_trade_engine/ -v
```
