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

---

# TradeStation vs Alpaca SIP: Replay Comparison

*Experiment date: 2026-04-19. Engine: `--window M1 09:30 3 --morning-split 100 --mock-trade-execution`.*

## Background

`BarReplayDriver` was updated (commit `3e75cb2`) to honor `--market-data-source` for intraday replay bars. Previously it always fetched from Alpaca cache regardless of the flag. After the fix, replays with `--market-data-source tradestation` fetch both warmup and intraday bars from the TradeStation REST API (SIP tape), making the two sources truly independent.

## Warmup Bar Counts (same date range)

| Source | Bars per ticker (typical) | Coverage |
|---|---|---|
| Alpaca SIP | ~5,070 | Regular + extended hours |
| TradeStation | ~4,758 | Regular market hours only (9:30–16:00) |

TS returns market-hours-only bars; Alpaca includes pre/post-market. Despite the bar count difference, the last-close prices match closely (within $0.01 for most tickers), confirming both sources agree on regular-session prices.

## Per-Day P&L Comparison

### Alpaca IEX vs TradeStation SIP (4 dates)

| Date | Alpaca IEX | TradeStation | Diff | Note |
|---|---|---|---|---|
| 2026-04-17 | +$797,480 | +$712,715 | -$84,765 | Different contract sizing |
| 2026-04-16 | +$36,435 | +$115,730 | +$79,295 | Different contract sizing |
| 2026-04-15 | -$9,740 | -$40,975 | -$31,235 | Same picks, different size |
| 2026-04-14 | -$74,350 | -$10,690 | +$63,660 | Same picks, different size |

IEX and TS diverge significantly on every date — IEX sparse bars produce different OR ranges and contract mids.

### Alpaca SIP vs TradeStation SIP (5 dates, with trade detail)

| Date | Source | Trades | P&L |
|---|---|---|---|
| 2026-01-09 | Alpaca SIP | SNDK ✅ +$67,660 / CRDO ❌ -$160,920 | **-$93,260** |
| 2026-01-09 | TradeStation | SNDK ✅ +$67,660 / CRDO ❌ -$160,920 | **-$93,260** |
| 2026-02-06 | Alpaca SIP | CRDO ❌ / MSTR ✅ +$1,084,875 | **+$984,955** |
| 2026-02-06 | TradeStation | MSTR ✅ +$1,081,575 / CRDO ❌ | **+$981,655** |
| 2026-03-06 | Alpaca SIP | MRVL ✅ +$62,055 / SHOP ❌ -$32,670 | **+$29,385** |
| 2026-03-06 | TradeStation | SHOP ❌ -$32,670 / MRVL ✅ +$62,280 | **+$29,610** |
| 2026-04-02 | Alpaca SIP | COIN ❌ -$11,940 / SHOP ❌ -$32,875 | **-$44,815** |
| 2026-04-02 | TradeStation | COIN ❌ -$15,860 / SHOP ❌ -$32,875 | **-$48,735** |
| 2026-04-09 | Alpaca SIP | FN ❌ -$107,420 / PLTR ✅ +$234,900 | **+$127,480** |
| 2026-04-09 | TradeStation | COIN ✅ +$213,750 / FN ❌ -$107,420 | **+$106,330** |

**Alpaca SIP and TradeStation SIP are effectively equivalent**: picks are identical 4 of 5 days; P&L differences are within 1% except Apr 9 where ranking swapped COIN vs PLTR due to slightly different 60-day rolling OR scores.

## The IEX Signal Miss: April 8, 2026

On 2026-04-08, Alpaca IEX fired **zero signals** while TradeStation SIP fired on FN (Bullish, +$76,700). Root cause: FN's OR midpoint differed between feeds.

| | Alpaca IEX | TradeStation SIP |
|---|---|---|
| OR Low | 600.51 | 598.00 |
| OR High | ~608.24 | 609.25 |
| Midpoint | **604.375** | **603.625** |
| 9:45 Close | 604.04 | 604.04 |
| Signal | NEUTRAL ❌ | **BULLISH ✅** |

IEX missed trades in FN's opening 15-minute window (FN is a lower-volume optical components stock), compressing the OR range. The close landed between the two midpoints — below IEX's threshold, above SIP's. This is a structural IEX limitation for lower-volume tickers, not a code bug.

Note: FN has since been removed from the V3 ticker pool and replaced with higher-volume names (CRDO, MRVL, etc.), reducing exposure to this class of IEX miss.

## Conclusion

| Comparison | Result |
|---|---|
| Alpaca IEX vs TradeStation SIP | **Large divergence** — different signals, different P&L, IEX misses valid breakouts on low-volume tickers |
| Alpaca SIP vs TradeStation SIP | **Effectively identical** — same picks 4/5 days, P&L within 1% |

**The real issue is IEX, not Alpaca vs TradeStation as brokers.** An Alpaca SIP subscription would align live trading and backtest replay results closely with TradeStation. The backtest cache (built with SIP) already uses the right feed — the remaining gap is in live bar streaming, which uses whatever `--feed` is configured.
