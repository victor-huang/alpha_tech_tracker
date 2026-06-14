# Historical Feed vs Live Trade Feed — Bar Divergence Study

## Background

The live trade engine can replay a past trading day in two modes:

1. **API/cache mode** (default): fetches 5-min bars from Alpaca's historical API (IEX feed), cached under `market_data/cache/`
2. **Live data dir mode** (`--live-data-dir`): reads bars recorded during the actual session by `BarRecorder`, stored as `{date}/{feed}_{ticker}_5min.csv`

Both modes use IEX data, but the bar values can differ because:
- Historical API bars are assembled server-side from IEX tick data after the session ends
- Live-recorded bars are constructed in real time from the WebSocket stream, which may have different bar edge timestamps, partial ticks at bar boundaries, and latency effects

This study documents the first observed divergence to calibrate replay accuracy expectations.

---

## Methodology

**Date studied:** 2026-04-13

**Engine config (both runs):**
```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --replay-date 2026-04-13 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 5 \
  --top 2 --capital 10000 \
  --rank-weighted-sizing 60 40 --feed iex \
  --mock-trade-execution --log-level DEBUG
```

**Run A:** no `--live-data-dir` (API/cache source)

**Run B:** `--live-data-dir alpha_tech_tracker/op_momentum_strategy/live_trade_market_data/` (recorded CSV source)

---

## Results

| Metric | Run A (API/cache) | Run B (Live CSV) |
|---|---|---|
| Capital P&L | **+$393.76** | **+$333.63** |
| Total trades | 10 | 9 |

### Run A — Trade Summary (API/cache)

| Window | Ticker | Direction | Entry | Exit | P&L |
|---|---|---|---|---|---|
| M1 | CRWV | Bullish | 9:45 AM | 11:25 AM (stop) | negative |
| M1 | CLS | Bullish | 9:45 AM | 3:55 PM (EOD) | positive |
| A1 | FN | Bullish (BUE) | 1:20 PM | 3:55 PM (EOD) | positive |
| A1 | SNDK | Bullish | 1:20 PM | 3:55 PM (EOD) | positive |
| A2 | FN | Bullish (BUE re-entry) | 3:05 PM | 3:55 PM (EOD) | positive |
| A2 | SNDK | Bullish (DD) | 3:05 PM | 3:55 PM (EOD) | positive |

Key: CRWV exits at 11:25 AM. A2 window (3:05 PM) picks **FN + SNDK** (Bullish signals). SNDK fires a BUE, FN fires a double-down.

### Run B — Trade Summary (Live CSV)

| Window | Ticker | Direction | Entry | Exit | P&L |
|---|---|---|---|---|---|
| M1 | CRWV | Bullish | 9:45 AM | 11:35 AM (stop) | negative |
| M1 | CLS | Bullish | 9:45 AM | 3:55 PM (EOD) | positive |
| A1 | APP | Bearish | 1:20 PM | 3:55 PM (EOD) | positive |
| A1 | SHOP | Bearish | 1:20 PM | 3:55 PM (EOD) | positive |
| A2 | APP | Bearish (Reversal) | 3:05 PM | 3:55 PM (EOD) | positive |

Key: CRWV exits 1 bar later (11:35 vs 11:25). A2 picks **APP + SHOP** (Bearish). APP fires a Reversal re-entry. No FN/SNDK activity in afternoon.

---

## Root Cause Analysis

### Divergence 1 — CRWV exit time (11:25 vs 11:35)

The CRWV position stops out 1 bar earlier in Run A. The historical API bar at ~11:25 ET has a different `low` value from the WebSocket-recorded bar, causing the hard stop threshold to trigger one bar sooner. Since capital from this position is recycled into A1/A2, the timing difference also affects position sizing downstream.

### Divergence 2 — A2 ticker selection (FN+SNDK vs APP+SHOP)

This is the primary P&L driver. At the 15:00 OR window:

- **Run A (API bars):** FN and SNDK score highest — both show Bullish conditions at 3:05 PM based on historical IEX bars
- **Run B (Live CSV bars):** APP and SHOP score highest — APP shows a Bearish condition at 3:05 PM based on live-stream IEX bars

The OR high/low/close for the 15:00–15:05 bar differ between the two sources for these tickers. Even small OHLC differences (cents) can flip whether a close is above or below the MA20 or within the top vs bottom of the OR range.

### Why IEX bars differ between API and WebSocket

IEX constructs bars differently depending on how they are accessed:

1. **Historical REST API**: bars are assembled post-session from the complete IEX TOPS feed. Prices reflect final consolidated tick data.
2. **Live WebSocket stream**: bars are built in real time as ticks arrive. Due to network latency, the bar's "close" is the last tick received before the engine's aggregation window closes, which may differ slightly from the post-session consolidated close.

Additionally, bar edge assignment (which bar a tick belongs to) can differ at exactly `:00` and `:05` second boundaries between the two pipelines.

---

## Implications

### For replay accuracy

**`--live-data-dir` mode is more faithful to what the engine would have done on the day.** It uses the same bars the signal engine would have seen in real time — same OHLC values, same bar edge assignment.

**API/cache mode** is useful for approximate replay and scenario testing, but ticker selection and exit timing can diverge from live behavior, especially for:
- Afternoon windows (A2 most sensitive — 1-bar OR, small price moves dominate)
- Tickers near signal thresholds (MA20, OR midpoint/edges)
- Fast-moving tickers where bar edges see large tick-to-tick moves

### For live trade vs backtest comparison

- Backtest uses Alpaca historical API bars (same as Run A)
- Live engine sees WebSocket bars (same as Run B)
- This structural difference explains some backtest vs live P&L gap

For the most accurate live engine performance projection, run selector backtests against CSV bars recorded during live sessions rather than historical API bars.

### A2 window sensitivity

The A2 window (15:00 / 1 bar) is especially sensitive to bar construction differences because:
- Only 1 bar forms the OR — a single OHLC difference can flip direction
- Price action at 3:00–3:05 PM is often trend-continuation (power hour), making the direction call high-stakes
- The OR range is often narrow (low volatility), so the MA20 threshold matters more

---

## Quantitative Summary

| Item | Value |
|---|---|
| Date | 2026-04-13 |
| P&L difference | $60.13 (Run A higher) |
| Trades difference | 1 trade (Run A has 10 vs Run B 9) |
| Root cause | IEX bar OHLC divergence between historical REST API and live WebSocket |
| Most affected window | A2 (15:00 / 1 bar) |
| Exit timing divergence | CRWV: 1 bar earlier in API mode |
| Ticker selection divergence | A2: FN+SNDK (Bullish) vs APP+SHOP (Bearish) |

---

## Recommendation

When evaluating live engine performance against a specific trading day:

1. **Use `--live-data-dir`** if `BarRecorder` data exists for that date — this is the ground truth for what the engine would have traded
2. **API/cache replay** is a reasonable approximation but expect ±1 trade and ±10–15% P&L variance on days where afternoon windows are active
3. **Do not mix** API replay P&L with live trade P&L in win-rate or EV calculations without accounting for this structural difference
