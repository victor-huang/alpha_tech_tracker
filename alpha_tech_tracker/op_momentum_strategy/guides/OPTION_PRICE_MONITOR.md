# Option Price Monitor — Design Document

## Purpose

`OptionPriceMonitor` serves two roles:

1. **Background collector** — snapshots bid/ask/intrinsic/time-value data for monitored contracts every N seconds during market hours and writes it to per-day CSV files.
2. **Pricing advisor** — given a live contract and stock price, returns a fair limit price within the bid/ask spread using intrinsic value as a hard floor and historical time-value data from the in-memory cache.

The two roles are independent: the advisor (`get_fair_price`) works without the collector running, but has better estimates when the cache has been warmed by recent snapshots.

---

## Contract and Ticker Selection

### Tickers

The monitor accepts an explicit `tickers` list at construction. In live trading this is populated from `config.TICKERS` (the 16-ticker default pool). No automatic filtering is applied.

### Strike Selection

Strike selection is delegated to `TradeEngineStrikeSelector`, which wraps `TimePremiumContractSelector`. For each ticker and each snapshot cycle the selector picks **two contracts** — one CALL and one PUT — using the same logic the live trade engine uses at order time:

```
target_premium = (time_premium_pct_cap / reference_dte) × dte × stock_price
```

Defaults: `time_premium_pct_cap = 1%`, `reference_dte = 5`.

| DTE | Target premium (stock = $300) |
|-----|-------------------------------|
| 5 (weekly) | $3.00 |
| 4 (Mon entry) | $2.40 |
| 25 (monthly fallback) | $15.00 |

The selector scans ITM strikes from near-ATM toward deeper ITM, batch-fetching quotes in a single API call, and returns the **shallowest ITM strike whose time premium falls at or below the target**. If no strike qualifies, it falls back to the deepest ITM. If the weekly expiry has no usable quotes, it falls back to the monthly expiry.

Because the monitor tracks the same contracts the engine would actually trade, the time-value cache it builds is calibrated to real execution prices rather than arbitrary strikes.

---

## Snapshot Collection

Every `interval_seconds` (default: 300) during market hours `_snapshot_all_tickers()` runs:

1. Fetch the current stock bid/ask; use mid as `stock_price`.
2. Call `contract_selector.select_contracts(ticker, stock_price)` → list of `ContractSpec`.
3. For each spec, call `_fetch_stats()`:
   - Fetch option bid/ask quote.
   - Fetch last trade (`get_option_latest_trade_by_occ`).
   - Compute all time-value fields (see below).
4. Append the row to the in-memory cache (`_update_cache`).
5. Append the row to the day's CSV file.

---

## Stats Computed per Snapshot

Given `bid`, `ask`, `stock_price`, and `strike`:

```
mid             = (bid + ask) / 2
intrinsic       = max(0, stock_price − strike)    # call
                = max(0, strike − stock_price)    # put
spread_pct      = (ask − bid) / mid × 100
bid_time_value  = bid − intrinsic
ask_time_value  = ask − intrinsic
mid_time_value  = mid − intrinsic
daily_theta     = mid_time_value / days_to_expiry
```

### best_time_value (trade-adjusted)

In addition to mid-based time value, each snapshot fetches the **last trade** for the contract:

- If the last trade is **within 30 minutes**: `best_time_value = max(0, last_trade_price − intrinsic)` — the time premium a real buyer actually paid.
- If the last trade is **older than 30 minutes** (stale), **unavailable**, or the fetch fails: `best_time_value = mid_time_value`.

`best_time_value` is what gets stored in the in-memory cache and used by `get_fair_price`. `mid_time_value` is kept in the CSV for reference.

**Why prefer trade data over mid?** On wide-spread options, the mid can sit far from where deals actually happen. The last trade reflects a real transaction. The 30-minute staleness gate prevents using an outdated trade price after the stock has moved significantly.

---

## In-Memory Cache

```python
_cache: dict[option_symbol → deque(maxlen=6)]
```

Each entry holds up to 6 snapshots (6 × 5 min = 30-minute rolling window). The cache is keyed by OCC symbol. It is populated only by the background collector — if `start()` is never called, the cache is empty and `get_fair_price` will use the `no_cache` fallback.

`_median_time_value(option_symbol)` returns the median of `best_time_value` across all cached snapshots, clamping negative values to zero. The median is used instead of the mean to reduce sensitivity to outlier quotes.

---

## CSV Output

Files are written to:
```
{output_dir}/{YYYY-MM-DD}/{ticker}_{call|put}.csv
```

Each row contains:

| Field | Description |
|-------|-------------|
| `timestamp` | Snapshot time (ET) |
| `ticker` | Underlying symbol |
| `option_type` | `call` or `put` |
| `option_symbol` | Full OCC symbol |
| `strike` | Strike price |
| `expiry` | Expiry date |
| `expiry_type` | `weekly` or `monthly` |
| `days_to_expiry` | Calendar days to expiry |
| `stock_price` | Stock mid at snapshot time |
| `bid` / `ask` / `mid` | Option bid/ask/mid |
| `intrinsic_value` | Intrinsic at snapshot stock price |
| `bid_time_value` | `bid − intrinsic` |
| `ask_time_value` | `ask − intrinsic` |
| `mid_time_value` | `mid − intrinsic` |
| `last_trade_price` | Last trade price (or null) |
| `last_trade_timestamp` | Last trade time (or null) |
| `last_trade_time_value` | `last_trade_price − intrinsic` if recent; null if stale/missing |
| `best_time_value` | `last_trade_time_value` if recent, else `mid_time_value` |
| `spread_pct` | `(ask − bid) / mid × 100` |
| `daily_theta_approx` | `mid_time_value / days_to_expiry` |

---

## Fair Price Algorithm (`get_fair_price`)

Called at order time to determine a limit price for a sell order. Takes the current `stock_price` as an input (re-fetched after entry fill, not stale from signal time).

### Step 1 — Fetch live quote

Fetch bid/ask for the contract. Returns `0` on failure — caller must handle this.

### Step 2 — Compute intrinsic value

```
intrinsic = max(0, stock_price − strike)   # call
          = max(0, strike − stock_price)   # put
```

Intrinsic is the hard floor: we never place a sell limit below this value. Selling below intrinsic means leaving guaranteed exercise profit on the table.

### Step 3 — Choose pricing branch

| Condition | Branch | Fair price |
|-----------|--------|-----------|
| `spread_pct ≤ 15%` and `bid ≥ intrinsic` | `liquid` | `mid` |
| Cache has snapshots, `bid < intrinsic` | `stale_bid` | `intrinsic + median_tv` |
| Cache has snapshots, spread wide | `wide_spread` | `intrinsic + median_tv` |
| No cache yet | `no_cache` | `intrinsic + 20% of spread` |

**Liquid branch**: when the spread is tight and the bid is at or above intrinsic, the mid is a reliable estimate. Market makers are quoting reasonably and splitting the spread is appropriate.

**Stale bid / wide spread branch**: when the market maker's bid has fallen below intrinsic (a stale or manipulated quote) or the spread is too wide to trust the mid, we reconstruct fair value from first principles: intrinsic value plus the median time premium observed in the last 30 minutes. The median is preferred over the current mid to avoid reacting to momentary spread widening.

**No cache branch**: on the first run of the day (cache empty), fall back to `intrinsic + 20% of spread`. This is conservative — it sits well inside the spread but avoids placing the limit at the bid floor.

### Step 4 — Clamp and quantize

```
fair = max(fair, intrinsic)   # hard floor
fair = min(fair, ask)         # cap at ask — resting above ask is not useful
fair = _quantize_option_price(fair)
```

If `ask < intrinsic` (entire quote is mispriced), a warning is logged and `ask` is returned as the best available price.

### Tick quantization — Penny Pilot Program

All tickers in the pool participate in the CBOE Penny Pilot Program:

| Price | Tick size |
|-------|-----------|
| < $3.00 | $0.01 |
| ≥ $3.00 | $0.05 |

Standard non-pilot increments ($0.05 / $0.10) are intentionally not used — they would place limit orders at suboptimal prices.

---

## Configuration Constants

| Constant | Default | Description |
|----------|---------|-------------|
| `_LIQUID_SPREAD_THRESHOLD` | 15% | Spread above which the quote is considered wide |
| `_CACHE_MAXLEN` | 6 | Max snapshots per contract (30-min window at 5-min interval) |
| `_RECENT_TRADE_MAX_AGE_SECONDS` | 1800 | Last trade older than this is treated as stale |

---

## End-to-End Flow: Cache Warm-Up to Fair Price

### Phase 1 — Cache warm-up (background, every 5 min)

Every snapshot cycle, for each monitored ticker:

1. Fetch stock bid/ask → compute `stock_price` (mid).
2. `TradeEngineStrikeSelector.select_contracts()` → pick the CALL and PUT the engine would trade.
3. For each contract, `_fetch_stats()`:
   - Fetch option bid/ask quote.
   - Fetch last trade; compute `best_time_value` (trade TV if ≤30 min, else mid TV).
4. Append row to `_cache[option_symbol]` (rolling 6-snapshot deque).

After 30 minutes of market activity the cache holds up to 6 `best_time_value` readings per contract — a stable, trade-anchored estimate of time premium.

### Phase 2 — Fair price at exit time

When the position monitor fires an exit signal, `get_fair_price()` is called with a freshly fetched `stock_price` (not the stale signal-time price):

```
fair_price = monitor.get_fair_price(ticker, option_symbol, option_type, stock_price)
```

1. **Fetch live bid/ask** for the contract.
2. **Compute intrinsic** from current stock price and strike.
3. **Branch on spread quality:**

| Condition | Branch | Fair price |
|-----------|--------|------------|
| `spread_pct ≤ 15%` and `bid ≥ intrinsic` | `liquid` | `mid` |
| Cache populated, bid stale or spread wide | `stale_bid` / `wide_spread` | `intrinsic + median(best_time_value)` |
| Cache empty | `no_cache` | `intrinsic + 20% of spread` |

4. **Clamp and quantize:**
   ```
   fair = max(fair, intrinsic)   # hard floor — never sell below exercise value
   fair = min(fair, ask)         # cap at ask
   fair = _quantize_option_price(fair)   # Penny Pilot tick ($0.01 or $0.05)
   ```

### Why the cache improves wide-spread estimates

Without the cache, on a wide-spread option the only anchor is the current bid/ask mid — which can sit far from where trades actually happen. The cache contributes up to 6 snapshots of `best_time_value`, preferring real last-trade prices over mid, so the median reflects what buyers actually paid for time premium over the last 30 minutes. This is a more reliable anchor than the instantaneous mid on a thinly quoted contract.

### Concrete example

Stock at $302, strike $280 call, bid=$21, ask=$30 (spread=32% → wide branch):

```
intrinsic        = $302 − $280 = $22.00
spread_pct       = ($30 − $21) / $25.50 × 100 = 35%  → wide, skips liquid branch
median cache TV  = $1.80  (from last 3 snapshots)
fair             = $22.00 + $1.80 = $23.80
clamp check      = $21 ≤ $23.80 ≤ $30  ✓
quantize         = $23.80  (already on $0.05 tick)
```

If the cache were empty (`no_cache` branch): `fair = $22.00 + 20% × $9.00 = $23.80` — coincidentally the same here, but when spread volatility is high the cache median is more stable than the 20%-of-spread estimate.

---

## Integration with the Live Trade Engine

The trade engine constructs `OptionPriceMonitor` with `--collect-option-prices` and calls `monitor.start()` to begin background collection. At exit time, `position_monitor.py` calls `monitor.get_fair_price(ticker, symbol, option_type, stock_price)` to determine the limit price for the closing sell order.

```
TradeEngine
  └── OptionPriceMonitor.start()          ← background collector warms cache
  └── PositionMonitor.on_exit_signal()
        └── get_fair_price(...)           ← advisor reads from warmed cache
              └── OrderExecutor.place_limit_sell(fair_price)
```

If the monitor was not started (e.g. `--collect-option-prices` omitted), `get_fair_price` still works but always hits the `no_cache` branch.
