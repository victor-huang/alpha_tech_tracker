# CLAUDE.md — op_momentum_strategy

Context guide for Claude when working in this directory.

---

## What This Module Does

Intraday opening-range momentum strategy for options trading. Each morning it:
1. Scores all tickers in a 16-ticker pool using a rolling 60-day backtest
2. Picks the top 3 by score
3. Fires a BULLISH or BEARISH signal after the opening range closes
4. Buys a weekly option (CALL or PUT) and manages exits until EOD

The same signal logic drives both **live trading** (`op_momentum_trade_engine.py`) and **backtesting** (`op_momentum_selector_backtest.py`).

---

## File Map

| File | Purpose |
|---|---|
| `op_momentum_backtest.py` | Core backtest engine: `run_backtest()`, `fetch_bars()`, `build_bearish_regime_dates()`, `_stitch_cache()` |
| `op_momentum_selector.py` | Live top-N picker: `select_top_n()`, `score_ticker()`, `compute_ticker_stats()` |
| `op_momentum_selector_backtest.py` | Multi-day selector simulation: `run_selector_backtest()`, `_apply_capital_flow()`, CLI |
| `op_momentum_trade_engine.py` | Live trading daemon: WebSocket streaming, order placement, exit monitoring |
| `config.py` | Constants, Alpaca credentials loader, Telegram/SMS notification helpers |
| `contract_selector.py` | Option contract selection (strike, expiry) |
| `position_sizer.py` | Capital allocation per symbol |
| `order_executor.py` | Alpaca order placement wrapper |
| `position_monitor.py` | Intraday stop/exit monitoring loop |
| `signal_engine.py` | Signal evaluation logic |
| `models.py` | Shared data models |

### Docs in this directory

| File | Purpose |
|---|---|
| `FINDINGS.md` | All backtest findings with data tables (primary research log) |
| `step_to_create_new_trading_window.md` | 8-step process for evaluating and adding a new intraday window |
| `TICKER_SELECTION.md` | Ticker pool selection criteria and history |
| `OP_MOMENTUM_GUIDE.md` | Strategy methodology, signal rules, exit rules |
| `README.md` | Live trade engine setup and daily timeline |

### Backtest results

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
- Hard stop: `--stop-pct` (default 0.15) as fraction of OR range from the breakout side
- Trailing stop: price crosses MA20 (default) or MA50 (`--trailing-ma`)
- EOD: force-close at 3:55 PM ET

---

## Ticker Pool V2 (16 tickers — current default)

```python
DEFAULT_TICKERS = [
    "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
    "EXPE", "FANG", "RH", "FN", "MU",
    "ANAB", "PLTR", "COIN", "NVDA",
]
```

Added PLTR, COIN, NVDA in March 2026 after 30-day + 90-day screening. Pool v2 outperforms the original 13-ticker pool by +11pp over 5 years.

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

---

## Multi-Window System

The selector backtest supports running multiple non-overlapping intraday windows per day, with capital recycled sequentially between them.

### Current window labels

| Label | Config | Entry | EV/trade | Win rate |
|---|---|---|---|---|
| M1 | 09:30 / 3 bars | 9:45 AM | +0.443% | 37% |
| M2 | 09:30 / 1 bar | 9:35 AM | +0.468% | 32% |
| A1 | 13:15 / 1 bar | 1:20 PM | +0.194% | 24% |
| A2 | 15:00 / 1 bar | 3:05 PM | +0.135% | 26% |

### Capital flow model

- **First group** (`--morning-split`): simultaneous windows that each deploy `portfolio × split[i]` at the same time
- **Sequential windows**: each inherits all returned capital (principal + P&L) from the prior window
- **Non-overlapping additivity**: M1's cap P&L is identical whether M1 runs alone or combined with afternoon windows — adding windows only adds P&L, never dilutes morning performance

### Recommended live configs

| Use case | Config | CLI |
|---|---|---|
| Conservative | M1 + A1 + A2 | `--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100` |
| Aggressive | M2 + A1 + A2 | `--window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100` |

### Key backtest modes

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

# Historical date replay (live selector for a past date)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector.py \
  --date 2026-03-17 --regime-filter --regime-ma 8

# Run tests
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m pytest tests/unit/test_op_momentum_selector_backtest.py -v
```

---

## Pitfalls to Avoid

1. **Never compare no-compound results to compound results** — they are not comparable. Rerun the baseline with the same flags before comparing.
2. **Non-overlapping windows are additive** — if M1's cap P&L changes when you add A1, there is a bug or flag mismatch.
3. **`python` uses Python 2.7** in this project — always use `pyenv activate alpha_tech_tracker` or the full pyenv path before running scripts.
4. **Long date range cache misses** — if running a multi-year range for the first time, `_stitch_cache()` will assemble from per-year files automatically. If those don't exist, run per-year first to warm the cache.
5. **`--morning-split` expects percentages** (e.g., `100` not `1.0`), summing ≤ 100.
