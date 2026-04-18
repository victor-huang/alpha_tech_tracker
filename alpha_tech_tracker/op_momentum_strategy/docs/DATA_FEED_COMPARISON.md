# Alpaca Data Feed Comparison: IEX vs SIP

## Background

Alpaca offers two data feeds for historical and live market data:

- **IEX** (free tier): covers ~10-15% of market volume from the IEX exchange only. Can return sparse or stale bar data, particularly for lower-volume tickers and during extended hours.
- **SIP** (requires funded live account): full consolidated tape across all US exchanges. Authoritative bid/ask quotes and complete intraday bar coverage.

The backtest cache system encodes the feed name in the cache filename (`alpaca_sip_5min_...` vs `alpaca_iex_5min_...`) so both feeds can coexist without manual cleanup.

## Bar Count Comparison (2026 YTD, Jan 2 – Apr 9)

5-min bars returned per ticker for the same period:

| Ticker | IEX bars | SIP bars | Ratio |
|--------|----------|----------|-------|
| TSLA   | 5,611    | 12,863   | 2.29x |
| COIN   | 5,392    | 12,611   | 2.34x |
| AMD    | 5,392    | 12,631   | 2.34x |
| SNDK   | 5,294    | 12,640   | 2.39x |
| RH     | 3,550    | 6,128    | 1.73x |
| FN     | 4,517    | 6,070    | 1.34x |

SIP returns roughly **2x more bars** for liquid large-caps. The extra bars are mostly extended-hours trades that IEX misses. During regular market hours (09:30–16:00), IEX still misses quieter 5-min windows where volume is below IEX's reporting threshold.

## Backtest Performance Comparison

Params used for all runs:
```
--regime-filter --regime-ma 8 --weights 60 40
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1
--morning-split 100 --reversal --bearish-reentry --bullish-reentry --top 2
```

### 5-Year Annual Results (no-compound, $10k/day reset)

| Year | SIP Return | IEX Return | Winner | Delta |
|------|-----------|-----------|--------|-------|
| 2021 | +164.49%  | +156.95%  | **SIP** | +7.5pp |
| 2022 | +221.95%  | +252.85%  | **IEX** | +30.9pp |
| 2023 | +357.13%  | +334.78%  | **SIP** | +22.4pp |
| 2024 | +168.48%  | +147.69%  | **SIP** | +20.8pp |
| 2025 | +206.93%  | +264.03%  | **IEX** | +57.1pp |
| **5-yr avg** | **+223.8%** | **+231.3%** | IEX +7.5pp avg | |

SIP wins 3 of 5 years. IEX wins 2 years with large margins (2022: +30.9pp, 2025: +57.1pp).

### 2026 YTD (Jan 1 – Apr 9, no-compound)

| Feed | Return  | Trades | Win Rate | QQQ   |
|------|---------|--------|----------|-------|
| SIP  | +106.64% | 336   | 31%      | -0.49% |
| IEX  | +105.50% | 345   | 28%      | -0.49% |

Nearly identical over this period — difference within noise.

### Short-Range (Apr 1–9, no-compound)

| Feed | Return | Trades | Win Rate |
|------|--------|--------|----------|
| SIP  | +7.27% | 35     | 37%      |
| IEX  | +7.57% | 34     | 26%      |

## Why IEX Sometimes Beats SIP in Backtests

IEX generates **~8-10% more trades** than SIP (noisier, sparser data fires more signals at different price points). In years where the extra IEX signals happen to land on profitable days, IEX wins. The IEX advantage is likely **not repeatable in live trading** because:

1. **Stale IEX quotes**: IEX bid/ask can freeze for hours while the stock moves (confirmed live: RH bid=120.64/ask=132.99 frozen 2+ hours on 2026-04-10 while stock traded at $125-$127). Backtest entries/exits priced off stale bars are unreachable in live execution.
2. **Sparse bars create phantom signals**: A flat/synthetic IEX bar with `or_high == or_low` (OR range = 0) triggers a false BEARISH signal because `close ≤ or_low + 0.20×0` is always true. SIP bars have real spread so this case is rare. (Fixed with OR range = 0 guard in `_try_fire_signal`.)
3. **Higher baseline win rate on IEX**: IEX shows 40-41% baseline win rate vs 31-35% on SIP. The inflated win rate suggests IEX bars are creating favorable-looking entry/exit conditions that don't reflect true market prices.

## Recommendation

- **Backtest**: Use SIP (`_ALPACA_FEED = DataFeed.SIP` in `op_momentum_backtest.py`). More conservative, more realistic calibration. SIP is the default.
- **Live trading**: SIP everywhere — `signal_engine.py`, `alpaca_client/client.py`. Avoids stale quote issues that caused real execution problems on IEX.
- **Switching feeds**: Change `_ALPACA_FEED` in `op_momentum_backtest.py`. Cache files are keyed by feed name so no manual cleanup is needed.

## Implementation Notes

- Cache filenames: `market_data/cache/alpaca_{sip|iex}_5min_{ticker}_{start}_{end}.json`
- Feed constant: `_ALPACA_FEED = DataFeed.SIP` in `op_momentum_backtest.py` (line ~27)
- `_cache_source("alpaca")` → `"alpaca_sip"` or `"alpaca_iex"` depending on `_ALPACA_FEED`
- Live feed set in `signal_engine.py` (WebSocket + warmup bars) and `alpaca_client/client.py` (`get_stock_quote`)
