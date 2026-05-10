# CLAUDE.md — op_momentum_strategy

Context guide for Claude when working in this directory.

---

## What This Module Does

Intraday opening-range momentum strategy for options trading. Each morning it:
1. Scores all tickers in a 16-ticker pool using a rolling 60-day backtest
2. Picks the top 3 by composite score
3. Fires a BULLISH or BEARISH signal after the opening range closes
4. Buys a weekly ITM option (CALL or PUT) and manages exits until EOD

The same signal logic drives both **live trading** (`trade_engine.py`) and **backtesting** (`op_momentum_selector_backtest.py`). Multiple non-overlapping intraday windows (morning + afternoon) are supported with sequential capital recycling.

---

## File Map

### Core Strategy

| File | Purpose |
|---|---|
| `op_momentum_backtest.py` | Core backtest engine: `run_backtest()`, `fetch_bars()`, `build_bearish_regime_dates()`, `_stitch_cache()` |
| `op_momentum_selector.py` | Live top-N picker: `select_top_n()`, `score_ticker()`, `compute_ticker_stats()`, CLI |
| `op_momentum_selector_backtest.py` | Multi-day selector simulation: `run_selector_backtest()`, `_apply_capital_flow()`, CLI |

### Live Trading

| File | Purpose |
|---|---|
| `op_momentum_trade_engine.py` | CLI entrypoint + daemon (run/start/stop/status/restart), log rotation |
| `trade_engine.py` | `OpMomentumTradeEngine` orchestrator + `TickerSelector` (top-N ranking) |
| `signal_engine.py` | `LiveSignalEngine`: 5-min bar aggregation, opening-range signal detection; bar source injected via `MarketDataClient` |
| `position_monitor.py` | `PositionMonitor`: intraday stop/exit loop (hard stop, trailing MA, EOD) |
| `order_executor.py` | Alpaca order placement with limit→ask/bid escalation and market fallback |

### Support Modules

| File | Purpose |
|---|---|
| `config.py` | Constants, Alpaca credentials loader, Telegram/SMS `_notify()` helper |
| `models.py` | Shared dataclasses: `ActivePosition`, `SignalEvent`, `_FiveMinBar`, `WindowConfig`; `_D()`, `_stock_bid_ask()` |
| `contract_selector.py` | `TimePremiumContractSelector` (live default), `ITMOptionContractSelector` (legacy), `_fetch_contracts_with_expiry_fallback()` |
| `option_price_monitor.py` | Background bid/ask/intrinsic/time-value snapshots + `get_fair_price()` pricing advisor |
| `option_fair_price_tester.py` | Live paper-account shadow-test for `get_fair_price()` — buys, places limit sell, escalates, records fills to CSV |
| `position_sizer.py` | `PositionSizer`: `compute()` for options, `compute_stock()` for stock sizing |
| `bar_recorder.py` | `BarRecorder`: records live 1-min and 5-min bars to CSV during trading sessions |

### Docs in This Directory

| File | Purpose |
|---|---|
| `FINDINGS.md` | All backtest findings with data tables (primary research log) |
| `step_to_create_new_trading_window.md` | 8-step process for evaluating and adding a new intraday window |
| `TICKER_SELECTION.md` | Ticker pool selection criteria and history |
| `OP_MOMENTUM_GUIDE.md` | Strategy methodology, signal rules, exit rules |
| `README.md` | Live trade engine setup and daily timeline |

### Backtest Results

| Path | Contents |
|---|---|
| `backtest_result/FINDINGS.md` | Deprecated — superseded by `FINDINGS.md` above |
| `backtest_result/multiple_trading_windows/SUMMARY.md` | 6-year per-year comparison table + 5-year compound growth table |
| `backtest_result/second_best_time_window/` | M1 vs M2 overlap analysis |
| `backtest_result/afternoon_time_window/` | Afternoon window sweep + M1/M2/A1/A2 overlap analysis |

---

## Strategy: Signal Logic

**Opening Range (OR)**: first N 5-min bars after market open.
- `OR High`, `OR Low`, `midpoint = (High + Low) / 2`

**BULLISH** — all true after OR closes:
- Close > midpoint (price in top 50% of OR)
- Close > MA20
- Close > MA200 (optional, `--bearish-ma200`)

**BEARISH** — all true:
- Close ≤ OR Low + 20% × OR range (bottom 20% of OR)
- Close < MA20
- Close < MA200 (optional, `--bearish-ma200` flag)

**Exit rules**:
- Hard stop: `--stop-pct` (default 0.15) as fraction of OR range from the breakout side; arms after one bar confirms
- Trailing stop: price crosses MA20 (default) or MA50 (`--trailing-ma`)
- EOD: force-close at 3:55 PM ET

---

## Ticker Pools

Two named pools are available via `--ticker-set`. The active pool is set in `op_momentum_selector.py`.

### V3 — Default pool (17 tickers, `DEFAULT_TICKERS`)

```python
DEFAULT_TICKERS = [
    "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
    "EXPE", "RH", "FN", "MU", "CRDO",
    "PLTR", "COIN", "CLS", "MSTR", "CRWV", "MRVL",
]
```

V3 replaced V2 in April 2026: removed FANG (structurally weak), NVDA (fading), TSLA (peaked); added CLS, MSTR, CRWV, MRVL. Wins 4 of 6 years and 5-yr total by +8.6pp over V2.

### AT — Actively-trade pool (16 tickers, `ACTIVELY_TRADE_TICKERS`)

```python
ACTIVELY_TRADE_TICKERS = [
    "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
    "MU", "PLTR", "COIN", "NVDA", "TSLA",
    "RKLB", "ASTS", "HOOD", "MSTR", "NFLX",
]
```

Higher-momentum / higher-volatility set. Includes NVDA and TSLA (excluded from V3). Shared tickers with V3: SNDK, APP, SHOP, CVNA, AMD, META, MU, PLTR, COIN, MSTR.

### Switching pools

```bash
# All three entry points accept --ticker-set {V3|AT}
# --tickers <explicit list> takes precedence over --ticker-set

python op_momentum_selector.py --ticker-set AT
python op_momentum_selector_backtest.py --ticker-set AT --start 2025-01-01 --end 2025-12-31
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run --ticker-set AT ...
```

---

## Confirmed Best Parameters

These are validated across 5+ years and should not be changed without re-running multi-year backtests:

| Parameter | Value | Flag |
|---|---|---|
| Trailing MA | ma20 | `--trailing-ma ma20` (default) |
| Hard stop | 15% of OR range | `--stop-pct 0.15` (default) |
| Opening bars | 3 (15-min OR) | `--opening-bars 3` |
| Regime filter | QQQ MA8 | `--regime-filter --regime-ma 8` |
| Position weights | 50/30/20% by rank | `--weights 50 30 20` |
| Top-N selection | 3 tickers/day | `--top 3` (default) |
| Lookback window | 60 days rolling | `--lookback 60` (default in selector) |

Parameters that are **opt-in only** (off by default, situational):
- `--armed-ma20-exit` — hurts in choppy markets
- `--max-loss-pct` — cap per-trade losses at a % of entry
- `--time-premium-pct-cap` — override default 1% time premium cap (see contract selection below)
- `--trailing-ma-switch` — upgrade trailing stop from MA20 to a faster MA after a profit threshold (regime-sensitive — see Trailing-MA Switch below)

---

## Trailing-MA Switch (fast MA profit-taking)

Tightens the trailing stop from MA20 to a configurable fast MA once the trade reaches a profit threshold. Locks in more of a winner at the cost of stopping out earlier on normal pullbacks.

**Flags** (live engine + backtest, identical semantics):

| Flag | Default | Meaning |
|---|---|---|
| `--trailing-ma-switch {none,after-arm,after-target}` | `none` | When to upgrade. `after-arm`: when favorable move ≥ 1× OR range. `after-target`: when move ≥ `factor × OR range`. `none`: disabled (no behavior change) |
| `--trailing-ma-switch-period N` | `8` | Period of the fast MA (e.g. 5, 8, 10, 13). Replaces MA20; never interacts with MA50 |
| `--trailing-ma-switch-factor F` | `1.0` | OR-range multiplier for `after-target` mode |

**State (per position):** `use_ma_fast` (latched once threshold met — never un-latches) and `max_favorable_move`. Both are persisted in `ActivePosition.to_dict` so behavior survives engine restarts.

**Move reference:** primary positions measure favorable move from OR midpoint; re-entries (reversal/BRE/BRU) measure from entry price. Matches the backtest exactly.

**Exit reason string:** `trailing_stop_ma{period}` (e.g. `trailing_stop_ma8`). Logs and exit-reason CSVs reflect the configured period.

**Regime sensitivity (2025 vs 2026 YTD on Top-2/M1+A1+A2/60-40 weights):**

| Year | Δ Return (after-arm, MA8) | Δ Win rate |
|---|---|---|
| 2025 (full year) | **+30.28 pp** | +4.7 pp |
| 2026 YTD (Jan–May) | **−3.25 pp** | +1.4 pp |

In strong-trend years (2025) MA8 protects winners that would otherwise round-trip; in chop (2026 YTD) it stops out trades the looser MA20 would have ridden back to profit. Do not enable as a default — backtest the year/regime first.

**Example — live engine with MA8 after-arm:**

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 5 \
  --top 2 --rank-weighted-sizing 60 40 \
  --trailing-ma-switch after-arm \
  --trailing-ma-switch-period 8
```

**Example — selector backtest (sweep periods):**

```bash
for P in 5 8 10 13; do
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
    --start 2025-01-01 --end 2025-12-31 \
    --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
    --reversal --bearish-reentry --bullish-reentry --doubledown --doubledown-start 5 \
    --top 2 --weights 60 40 \
    --trailing-ma-switch after-arm --trailing-ma-switch-period $P
done
```

---

## Contract Selection: TimePremiumContractSelector

The live engine uses `TimePremiumContractSelector` (in `contract_selector.py`), which selects the shallowest ITM strike where the option's time premium falls at or below a DTE-adjusted threshold:

```
target_premium = (time_premium_pct_cap / reference_dte) * dte * stock_price
```

Defaults: `time_premium_pct_cap=0.01` (1%), `reference_dte=5`.

| DTE | Target premium (stock=$300, cap=1%) |
|---|---|
| 5 (weekly) | $3.00 |
| 4 (Mon entry) | $2.40 |
| 25 (monthly fallback) | $15.00 |

- Scans ITM strikes near-ATM → deeper, batch-fetching all quotes in one API call
- Falls back to deepest ITM when no strike meets the target or quote fetch fails
- Shared weekly → monthly expiry fallback via `_fetch_contracts_with_expiry_fallback()`
- Exposed via `--time-premium-pct-cap` CLI flag

The legacy `ITMOptionContractSelector` (fixed offset) is still available for backtesting or custom use.

---

## OptionPriceMonitor

Two-role module at `option_price_monitor.py`:

**Role 1 — Background collector** (`--collect-option-prices`):
- Snapshots bid/ask/intrinsic/time value every N seconds for all tickers
- Writes `market_data/options_price_data/YYYY-MM-DD/{ticker}_{call|put}.csv`
- Uses `TradeEngineStrikeSelector` (wraps `TimePremiumContractSelector`) to pick the same contracts the engine would trade

**Role 2 — Pricing advisor**:
- `get_fair_price(ticker, symbol, option_type, stock_price)` returns a limit price within bid/ask
- Algorithm: liquid spread (≤15%) + bid ≥ intrinsic → use mid; stale bid or wide spread → `intrinsic + median_time_value_from_cache`; no cache → 20% of spread; always clamp to [bid, ask]

**Tick size — `_quantize_option_price()` (Penny Pilot Program)**:
Most pool tickers are on the CBOE Penny Pilot Program, but not all. Non-pilot tickers require $0.10 ticks at ≥$3 — placing $0.05-increment orders causes exchange rejections and escalation latency.

| Price | Penny Pilot | Standard non-pilot |
|---|---|---|
| < $3.00 | $0.01 | $0.05 |
| ≥ $3.00 | $0.05 | $0.10 |

`ticker_is_penny_pilot(ticker)` resolves the flag; non-pilot tickers are listed in `_NON_PENNY_PILOT_TICKERS` in `option_price_monitor.py`.

**Confirmed non-Penny-Pilot** (source: CBOE Penny Tick Type Report 2026-04-22 + live evidence):
- `CRDO` — absent from CBOE list; confirmed 2026-04-20 (4 live rejections, `required=0.1`)
- `RH` — absent from CBOE list; confirmed 2026-04-21 (6 live rejections)
- `FN` — absent from CBOE list; confirmed 2026-04-21 (2 live rejections)
- `CLS` — absent from CBOE list; Celestica has liquid options but is not enrolled
- `APP` — confirmed 2026-04-28 (6 live rejections across put and call orders, `required=0.1`)

All other V3 pool tickers (`SNDK`, `SHOP`, `CVNA`, `AMD`, `META`, `EXPE`, `MU`, `PLTR`, `COIN`, `MSTR`, `CRWV`, `MRVL`) are confirmed Penny Pilot per CBOE 2026-04-22 report.

When adding a new pool ticker, verify its Penny Pilot status before the first live session. If live fills show `required=0.1` tick rejections, add the ticker to `_NON_PENNY_PILOT_TICKERS`.

**Penny Pilot Audit script (`penny_pilot_audit.py`)**:
Probes each ticker's actual tick schedule against TradeStation's live order placement API. Selects next week's ITM call (same strike logic as `ITMOptionContractSelector`), places a LIMIT order at `floor(mid) + $0.07` — invalid for both the $0.05 Penny Pilot tick and $0.10 Non-Pilot tick — and reads the `RejectReason` to extract the required increment.

**Must be run during market hours (9:30 AM – 4:00 PM ET).** TradeStation queues after-hours DAY orders without tick validation, so the rejection never fires and results are unreliable outside those hours.

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# All DEFAULT_TICKERS + ACTIVELY_TRADE_TICKERS (23 unique):
python alpha_tech_tracker/op_momentum_strategy/penny_pilot_audit.py \
  --tickers AMD APP ASTS CLS COIN CRDO CRWV CVNA EXPE FN HOOD META MRVL MSTR MU NFLX NVDA PLTR RH RKLB SHOP SNDK TSLA

# DEFAULT_TICKERS only (17 tickers, default):
python alpha_tech_tracker/op_momentum_strategy/penny_pilot_audit.py

# Specific tickers:
python alpha_tech_tracker/op_momentum_strategy/penny_pilot_audit.py --tickers APP CLS CRDO FN RH

# Dry-run (contract selection + quote fetch, no orders placed — works any time):
python alpha_tech_tracker/op_momentum_strategy/penny_pilot_audit.py --dry-run \
  --tickers AMD APP ASTS CLS COIN CRDO CRWV CVNA EXPE FN HOOD META MRVL MSTR MU NFLX NVDA PLTR RH RKLB SHOP SNDK TSLA
```

If mismatches are found, the script prints the exact `frozenset` line to paste into `option_price_monitor.py`:
```
  Suggested update to option_price_monitor.py:
    _NON_PENNY_PILOT_TICKERS: frozenset = frozenset({'APP', 'CLS', 'CRDO', 'FN', 'RH'})
```

---

## FairPriceTester (`option_fair_price_tester.py`)

Live shadow-test that validates `get_fair_price()` against a real Alpaca account (paper or live). Useful for measuring whether the fair-price limit achieves fills above the market bid in practice.

**One test cycle:**
1. Select contract — manual `--strike` or via `TimePremiumContractSelector`
2. Buy 1 contract via limit escalation toward ask — re-fetches quote each step:
   - Step 1: limit at mid
   - Step 2: limit at mid + 20% of spread
   - Step 3: limit at mid + 40% of spread
   - … capped at ask; falls back to market only after the ask-level limit also fails
3. Re-fetch stock price after fill to compute an up-to-date intrinsic value
4. Compute `fair_price` via `get_fair_price()` logic — intrinsic is the hard floor
5. If `--floor-at-entry`: raise `fair_price` to at least the entry fill price
6. Place limit SELL at `fair_price`, poll bid/ask every 5s for 15s
7. If unfilled → cancel, market SELL to close; confirm fill within 10s
8. Log `UNCLOSED POSITION` error if sell phase raises an exception (e.g. PDT block)
9. Write `quotes_*.csv` (per-5s bid/ask log) and `summary_*.csv` to `output_dir`

**Pricing safeguards:**
- `fair_price` ≥ intrinsic — never place a sell below exercise value
- `fair_price` ≥ entry fill price when `--floor-at-entry` is set — prevents selling at a loss
- `BELOW INTRINSIC` warning logged + `below_intrinsic=True` in CSV if market fill comes in below intrinsic
- `UNCLOSED POSITION` error logged if the sell phase fails (e.g. PDT rejection) so the user knows to close manually before EOD

**Output files** (written to `market_data/fair_price_test/YYYY-MM-DD/`):
- `quotes_{ticker}_{type}_{ts}.csv` — per-5s quote snapshots + order status + fill fields
- `summary_{ticker}_{type}_{ts}.csv` — one row with entry price, fair_price, fill_method, fill_price, intrinsic_value, improvement_vs_mid, below_intrinsic

**Usage:**

```bash
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# --- Paper account (safe for testing) ---
ALPACA_API_KEY=<PK...> ALPACA_SECRET_KEY=<secret> \
python -m alpha_tech_tracker.op_momentum_strategy.option_fair_price_tester \
    --ticker TSLA --option-type call

# Manual strike, floor sell at entry price
ALPACA_API_KEY=<PK...> ALPACA_SECRET_KEY=<secret> \
python -m alpha_tech_tracker.op_momentum_strategy.option_fair_price_tester \
    --ticker RH --option-type call --strike 115 --floor-at-entry

# Run for 2 minutes (multiple cycles back-to-back)
ALPACA_API_KEY=<PK...> ALPACA_SECRET_KEY=<secret> \
python -m alpha_tech_tracker.op_momentum_strategy.option_fair_price_tester \
    --ticker SPOT --option-type call --strike 460 --duration 2

# --- Live account (real money — use with care) ---
source ~/.bash_profile   # loads live ALPACA_API_KEY / ALPACA_SECRET_KEY
python -m alpha_tech_tracker.op_momentum_strategy.option_fair_price_tester \
    --ticker RH --option-type call --strike 115 --floor-at-entry --live
```

**CLI flags:**

| Flag | Default | Description |
|---|---|---|
| `--ticker` | required | Ticker symbol |
| `--option-type` | `call` | `call` or `put` |
| `--strike` | None | Manual strike price; omit to use `TimePremiumContractSelector` |
| `--expiry` | next Friday | Expiry as `YYYY-MM-DD` |
| `--floor-at-entry` | off | Floor the sell limit at entry fill price — never sell at a loss |
| `--live` | off | Use live trading account; omit to use paper account |
| `--duration` | None | Run for N minutes with back-to-back cycles; omit for one cycle |
| `--output-dir` | `market_data/fair_price_test` | CSV output directory |
| `--log-level` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

**Notes:**
- Paper account keys have a `PK...` prefix; live keys have `AK...`. They are separate accounts with separate endpoints — do not mix them.
- Paper fill simulator only honors market orders — limit fills always time out in paper. The escalation logic is correct for live trading; paper runs are useful for validating flow and CSV output.
- The `no_cache` fair_price branch fires when no historical time-value data exists for the contract (first run of the day). Subsequent cycles on the same contract benefit from the collected cache.
- **PDT risk on live account**: each buy+sell cycle counts as a day trade. Exceeding 3 day trades in 5 days on a margin account under $25k triggers PDT protection and will block the sell order, leaving an open position. Use `--floor-at-entry` so the sell limit is at least at cost basis if you must trade live.

---

## Multi-Window System

The selector backtest supports running multiple non-overlapping intraday windows per day, with capital recycled sequentially between them.

### Current Window Labels

| Label | Config | Entry | EV/trade | Win rate |
|---|---|---|---|---|
| M1 | 09:30 / 3 bars | 9:45 AM | +0.443% | 37% |
| M2 | 09:30 / 1 bar | 9:35 AM | +0.468% | 32% |
| A1 | 13:15 / 1 bar | 1:20 PM | +0.194% | 24% |
| A2 | 15:00 / 1 bar | 3:05 PM | +0.135% | 26% |

### Capital Flow Model

- **First group** (`--morning-split`): simultaneous windows that each deploy `portfolio × split[i]` at the same time
- **Sequential windows**: each inherits all returned capital (principal + P&L) from the prior window
- **Non-overlapping additivity**: M1's cap P&L is identical whether M1 runs alone or combined with afternoon windows — adding windows only adds P&L, never dilutes morning performance

### Recommended Live Configs

| Use case | Config | CLI |
|---|---|---|
| Conservative | M1 + A1 + A2 | `--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100` |
| Aggressive | M2 + A1 + A2 | `--window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100` |

### Key Backtest Modes

- `--compound` off (default): resets portfolio to $10k each day — use for **strategy edge comparison**
- `--compound` on: carries portfolio over — use for **growth projection**

---

## Scoring Formula (op_momentum_selector.py)

```python
score = entry_vs_mid_pct * 0.50 + avg_win_pct * 0.30 + or_range_pct * 0.20
```

Tickers with `ev_trade <= 0` are excluded before scoring (negative EV gate).

---

## Cache System (op_momentum_backtest.py)

5-min bar data is cached per ticker at:
```
market_data/cache/{source}_5min_{ticker}_{start}_{end}.json
```

`_stitch_cache()` automatically assembles long date ranges from existing per-year cache files, avoiding redundant Alpaca API calls. Run any single-year backtest first to warm the cache; subsequent multi-year runs stitch automatically.

---

## Log Rotation

Live trade engine logs are written to `logs/op_momentum_YYYY-MM-DD.log` (date stamped at engine startup). A `TimedRotatingFileHandler` rotates at midnight and keeps 30 days. In foreground `run` mode, logs also print to the terminal.

```bash
tail -f logs/op_momentum_$(date +%Y-%m-%d).log
```

---

## Tests

All tests are in `tests/op_momentum_trade_engine/`. Run with:

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m pytest tests/op_momentum_trade_engine/ -v
```

### Test File Map

| File | What it covers |
|---|---|
| `conftest.py` | Shared helpers: `_make_alpaca_client()`, `_make_active_position()`, `_make_signal_engine_with_history()`, `_build_history_df()` |
| `test_config.py` | `_notify()`, `_send_telegram()`, `_load_config()` — credential loading, exception swallowing |
| `test_signal_engine.py` | `LiveSignalEngine` — BULLISH/BEARISH conditions, OR computation, regime filter |
| `test_contract_selector.py` | `TimePremiumContractSelector` (DTE-adjusted threshold, fallback), `ITMOptionContractSelector`, helper functions (`_next_friday`, `_strike_increment`, etc.) |
| `test_position_sizer.py` | `PositionSizer.compute()` and `compute_stock()` — sizing from buying power, window budget override |
| `test_position_monitor.py` | `PositionMonitor` — hard stop arming/exit, trailing MA exit, EOD exit, stock positions; `TestReentryWatcher` — `bars_held` tracking, watcher creation/suppression, reversal priority, trigger firing, EOD cleanup, `trailing_arm_price` gate |
| `test_bar_recorder.py` | `BarRecorder` — CSV creation, header, ET timestamp, per-ticker file separation |
| `test_option_price_monitor.py` | `OptionPriceMonitor`, `TradeEngineStrikeSelector`, `_parse_occ_symbol()`, `get_fair_price()` algorithm |
| `test_trade_engine.py` | `TickerSelector`, `OpMomentumTradeEngine._enter_position()`, signal buffer, rank-weighted sizing, multi-window state; `TestEnterReentry` — `_enter_reentry()` signal direction, hard stop override, trailing arm, rank/window passthrough |
| `test_parse_windows.py` | `_parse_windows()` — CLI window args → `WindowConfig` objects, morning-split fractions; `--ticker-set` resolution logic and arg parsing |
| `test_full_day_simulation.py` | End-to-end fixture-driven simulation: 5-min bar → signal → entry → monitoring bars → exit → P&L |

### Key Test Patterns

- **Mock Alpaca client**: `_make_alpaca_client()` returns a `MagicMock` with `._option_data_client` attached — set `.get_option_latest_quote.return_value` or `.side_effect` for quote sequences
- **Stock quote format**: `_stock_bid_ask()` expects nested Alpaca format — mock as:
  ```python
  client.get_stock_quote.return_value = {
      "QuoteResponse": {"QuoteData": [{"All": {"bid": 99.0, "ask": 101.0, ...}}]}
  }
  ```
- **Date patching**: patch `alpha_tech_tracker.op_momentum_strategy.contract_selector._today` for expiry-sensitive tests
- **Full-day fixtures**: JSON files in `tests/op_momentum_trade_engine/fixtures/` — each fixture has `opening_bars`, `monitoring_bars`, `mock_api`, and `expected` keys

---

## Key Backtest Results Summary

See `FINDINGS.md` for full detail. Major findings:

| Finding | Result |
|---|---|
| **Best opening window** | `09:30 / 3 bars` (+123% over 15 months, 37% WR) — recommended for live |
| **Highest return window** | `09:30 / 1 bar` (+139%, 32% WR) — noisier, fires before OR forms |
| **Regime filter** | MA8 improves EV every year, +16pp net over 5 years (~70 fewer trades/year) |
| **Position weights** | 50/30/20 beats equal weighting every year (+204pp over 5 years) |
| **Top-3 vs Top-5** | Top-3 wins by +56pp over 5 years |
| **Best multi-window combo** | M2+A1+A2: wins 4/6 years no-compound, leads every year compound |
| **5-year compound growth** | $10k → $44.7M (M2+A1+A2) vs $491k (M1 alone) |

---

## Common CLI Commands

```bash
# Always set PYTHONPATH first
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# Live selector (run after 9:45 AM ET)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector.py \
  --regime-filter --regime-ma 8

# Live selector — AT ticker pool
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector.py \
  --ticker-set AT --regime-filter --regime-ma 8

# Selector backtest — single year, no-compound (strategy edge)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20

# Selector backtest — AT ticker pool
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --ticker-set AT --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20

# Multi-window backtest (M2+A1+A2, aggressive)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# 5-year continuous compound run
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2021-01-01 --end 2026-03-28 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 --compound

# Live engine — foreground, paper, mock fills (Alpaca market data, default)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100

# Live engine — AT ticker pool
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --ticker-set AT --mock-trade-execution \
  --window M1 09:30 3 --morning-split 100

# Live engine — TradeStation market data feed (run tradestation_auth.py first)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --market-data-source tradestation \
  --mock-trade-execution \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100

# Live engine — with option price monitor
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100 \
  --collect-option-prices --option-price-interval 120

# Live engine — daemon
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine start \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100

python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine status
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine stop

# Historical date replay (live selector for a past date)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector.py \
  --date 2026-03-17 --regime-filter --regime-ma 8

# ── Replay engine: market data source variants ──────────────────────────────

# 1. Alpaca cache (default) — fetches historical 5-min bars from Alpaca IEX cache
#    Warmup + intraday bars both come from Alpaca. Fast; no live recording needed.
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-04-17 \
  --window M1 09:30 3 --morning-split 100 \
  --feed iex --full-day

# 2. TradeStation API — fetches historical bars from TS REST API for both warmup and intraday.
#    Requires a valid TS session (run tradestation_auth.py first).
#    Produces identical signals to Alpaca cache; warmup bar count differs (~4,758 vs ~5,148)
#    because TS returns market-hours-only bars.
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-04-17 \
  --market-data-source tradestation \
  --window M1 09:30 3 --morning-split 100 \
  --full-day

# 3. Alpaca recorded live CSV — replays bars captured by the live bar recorder (iex feed).
#    Files expected at: live_trade_market_data/{YYYY-MM-DD}/iex_{TICKER}_5min.csv
#    Warmup still comes from Alpaca cache; only intraday bars come from CSV.
#    Results match Alpaca cache when the recording covers the full session.
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-04-17 \
  --live-data-dir alpha_tech_tracker/op_momentum_strategy/live_trade_market_data \
  --live-data-feed iex \
  --window M1 09:30 3 --morning-split 100 \
  --feed iex --full-day

# 4. TradeStation recorded live CSV — replays bars captured from the TS feed.
#    Files expected at: live_trade_market_data/{YYYY-MM-DD}/tradestation_{TICKER}_5min.csv
#    WARNING: TS live recordings before _backfill_session() was added may be missing
#    the opening bars (9:30–~10:00), causing the OR window to shift and wrong picks.
#    Verify bar counts look complete (should be ~66 bars for a full day) before trusting results.
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-04-17 \
  --live-data-dir alpha_tech_tracker/op_momentum_strategy/live_trade_market_data \
  --live-data-feed tradestation \
  --window M1 09:30 3 --morning-split 100 \
  --full-day

# ── Replay data source comparison findings (2026-04-17) ─────────────────────
# Source                 | Bars  | Picks        | P&L
# Alpaca cache           | 1,273 | RH, MSTR     | +$797,480  ← ground truth
# Alpaca live CSV        | 1,160 | RH, MSTR     | +$797,480  ← matches (full recording)
# TradeStation API       | 1,273 | RH, MSTR     | +$797,480  ← matches (complete REST data)
# TradeStation live CSV  | 1,121 | SNDK, APP    | -$24,045   ← wrong (recording missed 9:30 open)

# Run tests
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m pytest tests/op_momentum_trade_engine/ -v
```

---

## Pre-Implementation Checklist

Before writing code for any new feature — signal filter, re-entry type, exit rule,
cache change, or data source parameter — work through this list. Each item maps to a
real bug found in this codebase (see `retrospects/RETRO_APRIL_2026.md` for full detail).

### Temporal alignment (data lookahead)
- Does every filter or gating signal use only data that is **known at signal time (~9:45 AM ET)**?
- Daily closes, rolling MAs on daily bars, and external index values (QQQ, VIX) are
  settled after market close — they must be shifted **+1 business day** before gating
  intraday signals.
- Sanity check: run the filter with shift=0 vs shift=1 and compare P&L. A large
  difference means you had a lookahead.

### Backtest / live engine parity
- Does the new logic behave identically in the backtest (batch scan) and live engine
  (bar-by-bar loop)?
- If two signals can both fire on the same day, is the **tie-breaking rule identical**
  in both? "First bar wins" and "exhaustive scan" only agree when at most one fires.
- Write a test where Signal A fires on bar 3 and Signal B fires on bar 5 — verify both
  environments pick A. Then swap: B on bar 3, A on bar 5 — verify both pick B.

### State that should latch
- Is the new condition meant to be **"ever crossed"** or **"currently above"**?
- Threshold-crossing conditions that should be permanent once met (arm flags, trailing
  stop activation) must be stored as a latched boolean — not recomputed from current price.
- Check: does price retreating below the threshold after first crossing change behavior?
  If not, use a persistent flag.

### Scope of cleanup / cancellation
- When a watcher, callback, or competing entry is cancelled, is the **cleanup scoped
  correctly**? Keying cleanup on `ticker` alone is almost always too broad when multiple
  windows can trade the same ticker simultaneously.
- The correct key is typically `(ticker, primary_exit_bar_time)` or equivalent.

### Derived fields after adding a new P&L component
- When a new P&L source (reversal, re-entry, rebate) is added to a trade row, audit
  **every derived flag and stat** computed from P&L: `success`, `win_rate`,
  `avg_win_pct`, `avg_loss_pct`, `ev_trade`.
- The `success` flag must match the `pnl_pct` field stored in the same row.

### Cache key completeness
- Does the new parameter **change the data returned**? If yes, it must be encoded in
  the cache key/filename.
- Test: fetch with param=A → confirm cache file created. Fetch with param=B → confirm
  a *different* cache file is created.

### Cache correctness under parallel access
- If the cache can be written by multiple processes simultaneously (e.g., sweep scripts):
  - Writes must be **atomic** (write to `.tmp`, then `Path.replace()`).
  - Reads and deletes must tolerate `FileNotFoundError` — another process may have
    evicted the file between your directory scan and your open/unlink.

### Degenerate input guards
- What happens when `or_range == 0`? `entry_price == 0`? `close == NaN`?
- Any percent-based condition relative to a range or price must guard against zero
  denominator. A condition like `close <= low + pct × range` is trivially true when
  `range == 0`.
- For sparse tickers: does the signal engine handle silent 5-min periods where no bars
  arrive? Missing bars must be synthesized as flat bars to keep MA series continuous.

### External constants
- Option tick sizes differ by program — most pool tickers use **Penny Pilot** ($0.01/<$3,
  $0.05/≥$3), but `CRDO`, `RH`, `FN`, and `CLS` are confirmed non-pilot ($0.05/$0.10).
  Add non-pilot tickers to `_NON_PENNY_PILOT_TICKERS` in `option_price_monitor.py`.
- When adding a new ticker: verify against the CBOE Penny Tick Type Report before live
  trading. Live fills showing `required=0.1` tick rejections also confirm non-pilot status.

---

## Pitfalls to Avoid

1. **Never compare no-compound results to compound results** — they are not comparable. Rerun the baseline with the same flags before comparing.
2. **Non-overlapping windows are additive** — if M1's cap P&L changes when you add A1, there is a bug or flag mismatch.
3. **`python` uses Python 2.7** in this project — always use `pyenv activate alpha_tech_tracker` or the full pyenv path before running scripts.
4. **Long date range cache misses** — if running a multi-year range for the first time, `_stitch_cache()` will assemble from per-year files automatically. If those don't exist, run per-year first to warm the cache.
5. **`--morning-split` expects percentages** (e.g., `100` not `1.0`), summing ≤ 100.
6. **Stock quote mock format** — `_stock_bid_ask()` reads the nested Alpaca structure `QuoteResponse.QuoteData[0].All`; flat dicts like `{"bid_price": ...}` will raise `KeyError`.
7. **TimePremiumContractSelector threshold scales with DTE** — the 1% cap applies to a 5-day weekly; monthly fallback contracts will have a proportionally larger absolute target, which is intentional.
