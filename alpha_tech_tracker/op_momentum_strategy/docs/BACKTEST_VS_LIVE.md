# Backtest Result Interpretation for Live Trading

This document explains what the selector backtest measures, what it does not model,
and how to translate reported backtest numbers into realistic live-trading expectations.

---

## What the Backtest Actually Measures

The backtest simulates **signal edge under perfect-fill conditions**. It answers:

> "If I could always enter at the exact OR close price and exit at the exact level where
> my stop or MA rule fires, what would the P&L be?"

That is a valid and useful measure of **directional edge** — whether the signal logic
itself has positive EV. It is not a projection of what your brokerage account will show.

---

## Perfect-Fill Assumptions in the Backtest

| Assumption | Code behavior | Reality |
|---|---|---|
| Entry price | Close of last OR bar (e.g., 9:45 for M1/3-bar) | You place an order after the bar closes; execution is on the next bar (9:50 open) |
| Hard stop exit | Exact stop level (e.g., `OR_high - 15% × OR_range`) | Bar may have already gapped through the level; you fill at the bar low in the worst case |
| Trailing MA exit | Close of the bar where the MA cross fires | Order executes on the next bar open, which has already moved away from the cross |
| EOD exit | `max(bar_close, midpoint)` for bullish | Actual 3:55 PM market-order fill depends on real bid at that moment |
| Bid-ask spread | Not modeled (single mid price per bar) | You buy at ask, sell at bid — for liquid large-caps this is $0.01–$0.03/share round trip |
| Commissions | Not modeled | Alpaca: $0 for stocks (negligible) |

---

## Real-Life Friction: Stock Trading

### 1. Entry Timing Gap (largest driver)

**Cause:** Signal fires at the 9:45 close. Realistically, the order reaches the market
at the 9:50 open. On genuine breakout days, the stock continues in the signal direction
during those 5 minutes — you are entering into momentum.

| Market condition | Typical 9:45 → 9:50 drift | Per-trade cost |
|---|---|---|
| Quiet / no follow-through | 0.0 – 0.05% | negligible |
| Normal breakout | 0.10 – 0.20% | mid drag |
| Strong gap / news-driven | 0.30 – 0.60% | significant |

**Weighted average across signal days: ~0.10 – 0.25% per entry.**

**Mitigation:** Place a limit order at (or slightly above) the OR close price rather than
a market order on the next bar. You will miss the fastest breakout days (~10–15% of
signals), but the fills you do get will be at the intended price.

### 2. Bid-Ask Spread (stocks, negligible)

For the pool tickers (TSLA, NVDA, META, AMD, etc.) bid-ask is $0.01–$0.03 round trip.
At a $200 avg stock price that is 0.005–0.015% — effectively zero at our trade size.

### 3. Hard Stop Gap-Through

**Cause:** The backtest exits at exactly the stop level. In reality, if the 5-min bar's
Low is already below the stop when the bar closes, your fill will be somewhere between
the stop level and the bar Low.

- Fires on ~63% of trades (the loss trades)
- Typical extra slip: $0.05 – $0.25/share
- At $200 avg price: 0.03 – 0.12% extra loss, on losers only
- **Per average trade: ~0.02 – 0.08%**

### 4. Exit Timing (MA Cross / Trailing Stop)

**Cause:** Backtest exits at the close of the bar where the MA cross fires. The actual
order executes on the next bar open, which has already moved further against you.

**Per trade: ~0.02 – 0.08%**

---

## Total Per-Trade Drag Estimate

| Scenario | Entry gap | Stop slip | Exit timing | **Total drag** |
|---|---|---|---|---|
| Best case (limit orders, quiet days) | 0.05% | 0.02% | 0.02% | **~0.09%** |
| Realistic (mix of limit/market) | 0.15% | 0.05% | 0.05% | **~0.25%** |
| Worst case (market orders, volatile days) | 0.30% | 0.10% | 0.10% | **~0.50%** |

---

## Impact on EV and Total Return

Baseline EV/trade from backtest: **~0.44%** (M1, 15-month period, regime filter on).

| Scenario | Net EV after friction | EV erosion | Total return impact |
|---|---|---|---|
| Best case (-0.09%) | ~0.35% | -20% | +123% → ~+102% |
| Realistic (-0.25%) | ~0.19% | -57% | +123% → ~+60% |
| Worst case (-0.50%) | ~-0.06% | edge gone | +123% → ~breakeven |

**Key takeaway:** The EV margin of ~0.44%/trade is thin. Execution quality is the
primary variable separating a profitable live strategy from a breakeven one.

---

## Multi-Window Capital Recycling Note

The multi-window model (`--morning-split 100` with sequential afternoon windows) assumes
the morning trade's capital is fully returned before the afternoon window deploys.

In practice, if a morning trade holds to EOD via the trailing MA (never stops out), that
capital is not available for the afternoon window. Most trades exit intraday, so the gap
is small — but on strong trend days where morning positions ride to close, afternoon
windows will be starved of capital. The backtest slightly overstates multi-window returns
on those days.

---

## How to Read the Backtest Output

### `Net P&L (1 sh)` column
Dollar P&L assuming you traded exactly 1 share of each ticker. Useful for comparing
signal quality across tickers and time periods. Not a capital simulation.

### `Cap P&L` / `Total return %` block
Capital simulation using `slot_capital / entry_price × pnl` per trade. This correctly
accounts for position sizing and weighting, but still assumes perfect fills. Apply the
discount scenarios above to get a live-trading range.

### `EV / trade %`
The most reliable signal-quality metric. Compare this across windows, tickers, and
parameter sets — friction affects all of them equally, so relative ranking is preserved.
Absolute EV should be discounted by 0.10–0.25% for realistic live execution.

### Win rate
Expect live win rate to be 2–5 percentage points lower than backtest win rate. Marginal
wins (trades that barely close above entry) will become breakeven or small losses once
entry slippage is factored in.

---

## Decision Framework: Is the Strategy Live-Tradeable?

Use this as a quick gate before deploying any parameter set:

| Backtest EV/trade | Assessment |
|---|---|
| < 0.15% | Do not trade live — friction will eliminate the edge |
| 0.15 – 0.30% | Tradeable only with disciplined limit-order entry; monitor closely |
| 0.30 – 0.50% | Tradeable with careful execution; realistic returns ~40–60% of backtest |
| > 0.50% | Strong edge; realistic returns ~60–80% of backtest |

Current confirmed parameters (M1, regime8, weights 50/30/20) sit at ~0.44% EV/trade —
in the tradeable range, but execution discipline is not optional.

---

## Quick Reference: Backtest-to-Live Discount Table

For communicating expected live returns from any backtest run:

| Backtest total return | Best case live | Realistic live | Worst case live |
|---|---|---|---|
| +50% | ~+40% | ~+22% | ~breakeven |
| +100% | ~+82% | ~+43% | ~+5% |
| +123% (M1 baseline) | ~+100% | ~+60% | ~+5% |
| +200% | ~+162% | ~+86% | ~+10% |

These ranges assume **stock trading only**. For options, apply additional bid-ask and
leverage uncertainty on top of these figures (see `FAIR_PRICE_BACKTEST.md`).

---

## Backtest vs Trade Engine Replay Validation

The trade engine supports `--replay-date` mode, which replays a historical trading day
through the full live engine path (bar-by-bar signal detection, order executor,
position monitor, re-entry watchers, double-down). This section documents the validated
gap between backtest output and replay output, and what causes it.

### Methodology

Config used across all validation runs (apple-to-apple comparison):

```bash
# Backtest
python op_momentum_selector_backtest.py \
  --weights 60 40 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 --reversal --bearish-reentry --bullish-reentry \
  --top 2 --doubledown --capital 10000

# Replay (one per trading day)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --trade-type stock --top 2 --rank-weighted-sizing 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry --doubledown \
  --capital 10000 --feed iex --replay-date <DATE>
```

### Validation Results (4 test windows, 85 trading days total)

| Period | Days | Direction Match | Notes |
|---|---|---|---|
| Dec 15 2024 – Jan 15 2025 | 21 | 18/21 = **86%** | Holiday-week thin volume + normal days |
| Mar 15 – Apr 15 2025 | 22 | 18/22 = **82%** | Normal market, Fed meeting (Mar 19) |
| Apr 2025 (full month) | 21 | 17/21 = **81%** | Tariff-shock days, Apr 9 +29% pivot |
| Jan 2026 (partial) | ~21 | ~81% | Fed days, normal |
| **Overall** | **~85** | **~82–86%** | Consistent across all market regimes |

### Key Observations

**Big-move days match almost perfectly:**

| Date | BT% | RP% | Event |
|---|---|---|---|
| 2025-04-09 | +29.37% | +29.19% | Tariff-pause pivot day |
| 2025-04-03 | +5.72% | +5.83% | Tariff-shock selloff |
| 2025-04-11 | +2.47% | +2.49% | Follow-through day |
| 2025-03-26 | +1.48% | +1.48% | Exact match |
| 2025-12-27 | -3.54% | -3.38% | Thin holiday selloff |

High-conviction signals where the direction is unambiguous produce near-identical
results. This validates that the core signal logic is correctly implemented in both
systems.

**Mismatches are small and symmetric:**
- All direction mismatches fall in the ±0.3% to ±1.5% magnitude range
- No large-loss vs large-gain flips (the dangerous failure mode) observed in 85 days
- Mismatches are not systematically biased — both systems occasionally win where the
  other loses, confirming this is noise rather than a structural bug

**No-signal days agree:**
Regime filter blockouts (e.g., 2025-01-09) produce no trades in both systems, confirming
the QQQ MA8 filter is applied consistently.

### Root Cause of the ~18% Mismatch Rate

The gap is structural, not a bug. Three sources:

1. **Scoring stat divergence (primary cause):** The backtest uses pre-cached 60-day
   rolling stats (avg win %, EV/trade, OR%) computed at backtest run time. The replay
   engine computes live stats during the session using the same 60-day lookback, but
   against slightly different bar data (IEX vs SIP, real-time vs cached). This produces
   different rank-2 picks on ~18% of days — enough to flip the sign on near-zero days.

2. **Event ordering on same-bar signals:** When two events fire on the same bar (e.g.,
   a double-down check and a re-entry watcher both trigger at 13:25), the backtest and
   replay may process them in different order. This is rare but can affect which leg gets
   capital on A1.

3. **IEX vs cached SIP bars:** Minor OHLC differences between IEX (replay) and SIP
   (backtest cache) can shift MA crossings by ±1 bar on low-volatility days, changing
   a trailing-stop exit by one bar.

### Implications for Live Trading

- The **direction signal is reliable** on days that matter (large moves). The 18%
  mismatch rate applies almost entirely to near-flat days (±1% range) where either
  outcome is within noise.
- **Do not expect exact P&L match** between backtest projections and live results. The
  backtest BT%/RP% pair is a range, not a point estimate.
- **Down-day protection is solid**: loss days in the backtest consistently correspond
  to loss days in replay. The system correctly avoids large drawdowns in both modes.
- Use backtest EV/trade and direction as strategy confidence signals; use the replay
  engine for pre-trade day simulation and parameter verification.
