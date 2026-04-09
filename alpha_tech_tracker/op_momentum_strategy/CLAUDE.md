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
| `signal_engine.py` | `LiveSignalEngine`: WebSocket bar aggregation, opening-range signal detection |
| `position_monitor.py` | `PositionMonitor`: intraday stop/exit loop (hard stop, trailing MA, EOD) |
| `order_executor.py` | Alpaca order placement with limit→ask/bid escalation and market fallback |

### Support Modules

| File | Purpose |
|---|---|
| `config.py` | Constants, Alpaca credentials loader, Telegram/SMS `_notify()` helper |
| `models.py` | Shared dataclasses: `ActivePosition`, `SignalEvent`, `_FiveMinBar`, `WindowConfig`; `_D()`, `_stock_bid_ask()` |
| `contract_selector.py` | `TimePremiumContractSelector` (live default), `ITMOptionContractSelector` (legacy), `_fetch_contracts_with_expiry_fallback()` |
| `option_price_monitor.py` | Background bid/ask/intrinsic/time-value snapshots + `get_fair_price()` pricing advisor |
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

## Ticker Pool V2 (16 tickers — current default)

```python
DEFAULT_TICKERS = [
    "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
    "EXPE", "FANG", "RH", "FN", "MU",
    "ANAB", "PLTR", "COIN", "NVDA", "TSLA",
]
```

Added PLTR, COIN, NVDA in March 2026 after 30-day + 90-day screening. Added TSLA April 2026 (+10.9pp over 5 years). Pool v2 outperforms the original 13-ticker pool by +11pp over 5 years.

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
All tickers in the pool (TSLA, NVDA, META, AMD, COIN, PLTR, etc.) are on the CBOE Penny Pilot Program. The correct tick increments are:

| Price | Penny Pilot (pool tickers) | Standard non-pilot |
|---|---|---|
| < $3.00 | $0.01 | $0.05 |
| ≥ $3.00 | $0.05 | $0.10 |

Using non-pilot increments causes limit orders to be placed at suboptimal price points ($0.01–$0.05 off per order). Do not change `_quantize_option_price()` to use $0.10 ticks.

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
| `test_parse_windows.py` | `_parse_windows()` — CLI window args → `WindowConfig` objects, morning-split fractions |
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

# Selector backtest — single year, no-compound (strategy edge)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
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

# Live engine — foreground, paper, mock fills
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --morning-split 100

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

# Run tests
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m pytest tests/op_momentum_trade_engine/ -v
```

---

## Pitfalls to Avoid

1. **Never compare no-compound results to compound results** — they are not comparable. Rerun the baseline with the same flags before comparing.
2. **Non-overlapping windows are additive** — if M1's cap P&L changes when you add A1, there is a bug or flag mismatch.
3. **`python` uses Python 2.7** in this project — always use `pyenv activate alpha_tech_tracker` or the full pyenv path before running scripts.
4. **Long date range cache misses** — if running a multi-year range for the first time, `_stitch_cache()` will assemble from per-year files automatically. If those don't exist, run per-year first to warm the cache.
5. **`--morning-split` expects percentages** (e.g., `100` not `1.0`), summing ≤ 100.
6. **Stock quote mock format** — `_stock_bid_ask()` reads the nested Alpaca structure `QuoteResponse.QuoteData[0].All`; flat dicts like `{"bid_price": ...}` will raise `KeyError`.
7. **TimePremiumContractSelector threshold scales with DTE** — the 1% cap applies to a 5-day weekly; monthly fallback contracts will have a proportionally larger absolute target, which is intentional.
