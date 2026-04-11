# Fair Price Backtest — Design & Usage Guide

## Purpose

`fair_price_backtest.py` measures how well `get_fair_price` works against real historical data.

For each ticker and date it:
1. Selects the option contracts the live engine would have traded that morning
2. Reconstructs the `OptionPriceMonitor` cache from historical 1-min option bars
3. Calls `get_fair_price` every 5 minutes throughout the trading day
4. Checks whether each fair price could actually be filled in the next 15 minutes by scanning real trade ticks — separately for sell and buy directions

The goal is to answer: **"Is the fair price we compute achievable in the real market?"**

---

## How It Works

### Step 1 — Contract Selection

At 9:30 AM the script fetches the opening stock price and selects one CALL and one PUT using the same logic as the live trade engine:

- **Standard** (default): `ITMOptionContractSelector` — fixed 10% ITM offset from opening price
- **Time-premium**: `TimePremiumContractSelector` — shallowest ITM strike within a DTE-adjusted time premium cap

The selected contract is held fixed for the entire day. This matches live trading where the contract is chosen at entry time.

### Step 2 — Cache Reconstruction

Every 5 minutes the script:
1. Looks up the 1-min option bar at that timestamp (bar `low`/`high` used as bid/ask proxy)
2. Looks up the most recent trade tick before that timestamp for time value estimation
3. Appends a snapshot to a rolling 6-snapshot cache (30-minute window)

**Bar lookup window:**
- **Normal** (≥ 30 bars/day): looks back up to 5 minutes for the nearest bar
- **Sparse** (< 30 bars/day): looks back up to 60 minutes — deep ITM options trade infrequently; intrinsic value dominates so a slightly stale bar is still a useful price anchor

### Step 3 — Fair Price Call

Every 5 minutes (after the cache has at least one snapshot), `get_fair_price` is called with the current stock price. The pricing branch used is recorded:

| Branch | Condition | Fair Price |
|---|---|---|
| `liquid` | spread ≤ 15% and bid ≥ intrinsic | mid |
| `stale_bid` | bid < intrinsic | intrinsic + median cache time value |
| `wide_spread` | spread > 15%, bid ≥ intrinsic | intrinsic + median cache time value |
| `no_cache` | cache empty | intrinsic + 20% of spread |

### Step 4 — Fill Simulation

For each fair price call, the script scans real trade ticks in the next 15 minutes:

- **Sell fill**: a trade at or above fair price — someone was willing to pay your ask
- **Buy fill**: a trade at or below fair price — a seller accepted at or below your bid

This gives separate fill rates for each direction so you can evaluate the fair price from both sides.

---

## Output

Results are written to `back_test_result/fair_price_backtest/YYYY-MM-DD/`:

### `detail.csv` — one row per fair_price call

| Column | Description |
|---|---|
| `timestamp` | When the fair_price call was made |
| `stock_price` | Stock mid at that moment |
| `bid` / `ask` / `mid` | Option quote (bar low/high proxy) |
| `intrinsic` | How deep ITM the option is |
| `spread_pct` | Bid/ask spread as % of mid |
| `cache_size` | Snapshots in the rolling cache (0–6) |
| `median_tv` | Median time value from cache — used for wide/stale branches |
| `fair_price` | Computed limit price |
| `bar_density` | `normal` (≥30 bars/day) or `sparse` (<30 bars/day) |
| `branch` | Pricing branch: `liquid`, `stale_bid`, `wide_spread`, `no_cache` |
| `improvement_vs_bid` | `fair_price − bid` — extra value vs just taking the bid |
| `improvement_vs_mid` | `fair_price − mid` — positive means above mid, negative means below |
| `sell_fill_found` | True if a trade ≥ fair_price occurred within lookahead window |
| `sell_fill_price` | First trade price at or above fair_price |
| `sell_minutes_to_fill` | Minutes until sell fill |
| `buy_fill_found` | True if a trade ≤ fair_price occurred within lookahead window |
| `buy_fill_price` | First trade price at or below fair_price |
| `buy_minutes_to_fill` | Minutes until buy fill |

### `summary.csv` / stdout table — aggregated by ticker/type/bar_density/branch

| Column | Description |
|---|---|
| `Bars` | `normal` or `sparse` — bar density for the contract |
| `Branch` | Pricing branch that fired |
| `N` | Number of fair_price calls in this group |
| `Sell%` | % of calls where a sell fill was found within lookahead |
| `sell_min` | Avg minutes until sell fill |
| `Buy%` | % of calls where a buy fill was found within lookahead |
| `buy_min` | Avg minutes until buy fill |
| `vs_bid` | Avg `fair_price − bid` — improvement over selling at bid |
| `vs_mid` | Avg `fair_price − mid` — how fair_price sits relative to mid |

Contracts with no bar data appear as `bar_density=no_bars` or `sparse (N bars)` rows with 0 count.

---

## Interpreting Results

### Fill rate

`Sell%` is an **upper bound** on real fill rate — it counts any trade at or above fair_price as a fill, but in practice queue position and exchange routing affect whether your specific order gets matched. On liquid contracts (TSLA, NVDA) with tight spreads, Sell% closely approximates real fill probability.

**What good looks like:**
- `liquid` branch, Sell% > 70% — mid is achievable, fills are fast
- `stale_bid` branch with high Sell% — cache median successfully reconstructed fair value when the bid was stale
- `vs_bid > 0` — capturing more than the bid on every fill

**Red flags:**
- `liquid` branch with low Sell% — market makers are quoting but not transacting at mid; contract may be less liquid than the spread suggests
- `stale_bid` with low Sell% — cache estimate was too aggressive; fair_price landed above where trades happened
- High `Buy%` but low `Sell%` — fair_price is systematically below where trades occurred; could price higher

### `vs_mid` interpretation

- `vs_mid ≈ 0` on liquid branch — expected, fair_price is mid
- `vs_mid > 0` on stale_bid/wide_spread — cache pushed fair_price above the distorted mid
- `vs_mid < 0` — fair_price is conservative (below mid); less risk of no fill but leaving value on the table

### Sparse contracts

For options with fewer than 30 bars per day (e.g. RH), the 60-minute lookback means the bid/ask proxy is potentially very stale. Results for `bar_density=sparse` contracts should be interpreted cautiously — the fill rates reflect the stale-bar price anchor, not a live quote. Low fill rates on sparse contracts often mean the market moved significantly since the last bar, not that `get_fair_price` is poorly calibrated.

---

## CLI Reference

```bash
# Always source credentials and virtualenv first
source ~/.bash_profile
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# Basic run
python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \
    --tickers TSLA NVDA --date 2026-04-10

# Multiple tickers, full pool
python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \
    --tickers TSLA NVDA META AMD PLTR COIN --date 2026-04-10

# TimePremiumContractSelector (same as live engine default)
python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \
    --tickers TSLA --date 2026-04-10 --option-selector time-premium

# Custom lookahead window (default 15 min)
python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \
    --tickers TSLA --date 2026-04-10 --lookahead 30

# Custom output directory
python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \
    --tickers TSLA NVDA --date 2026-04-10 \
    --output-dir back_test_result/fair_price_backtest

# Verbose logging to see every fair_price call
python -m alpha_tech_tracker.op_momentum_strategy.fair_price_backtest \
    --tickers TSLA --date 2026-04-10 --log-level DEBUG
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `--tickers` | required | One or more ticker symbols |
| `--date` | required | Trading date `YYYY-MM-DD` |
| `--option-selector` | `standard` | `standard` (ITM offset) or `time-premium` |
| `--time-premium-pct-cap` | `0.01` | Time premium cap for `time-premium` selector |
| `--lookahead` | `15` | Minutes to scan for fills after each fair_price call |
| `--output-dir` | `back_test_result/fair_price_backtest` | Output directory |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## Limitations

1. **Bid/ask proxy**: Alpaca does not provide historical bid/ask quotes for options. Bar `low`/`high` are used as bid/ask proxies. These are trade-based OHLCV bars, not quote-based — the spread approximation is less accurate on wide-spread or thinly traded contracts.

2. **Single contract per day**: The contract is selected once at 9:30 AM opening price. In live trading, entry only fires on a signal (could be 9:45 AM or later), and the stock may have moved. The backtest measures pricing quality across the full day on a fixed contract, not just at signal time.

3. **Fill simulation is optimistic**: Any trade at or above (sell) / at or below (buy) fair_price counts as a fill. In practice, queue position and order routing mean not every such trade results in your order being filled. Treat `Sell%` as an upper bound.

4. **Requires broker API keys**: Contract selection uses the Alpaca broker API (`get_options_contracts`), which requires options trading to be enabled on the account. Historical data fetching only requires data API keys.
