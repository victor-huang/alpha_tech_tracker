# Option Strategy Optimization

Analysis of whether and how to use options as the primary trading instrument to amplify
P&L from the opening-range momentum signal, and what improvements to option selection
would make that viable.

**Last updated:** 2026-05-03
**Config analyzed:**
```
--top 2 --weights 60 40
--window M1 09:30 3 --window A1 10:00 3 --window A2 13:15 1 --window A3 15:15 1
--morning-split 100
--reversal --bullish-reentry --doubledown --doubledown-start 10
--feed sip
```

---

## Stock Backtest Baseline (2026-01-01 to 2026-05-01)

| Month | Trades | W/L   | Cap P&L   | Return  |
|-------|--------|-------|-----------|---------|
| Jan   | 130    | 54/76 | +$3,442   | +34.4%  |
| Feb   | 124    | 57/67 | +$5,013   | +50.1%  |
| Mar   | 142    | 68/74 | +$1,966   | +19.7%  |
| Apr   | 140    | 70/70 | +$1,856   | +18.6%  |
| **Total** | **542** | **251/291 (46.3% WR)** | **+$12,275** | **+122.75%** |

QQQ buy-and-hold over the same period: **+9.95%**. Strategy edge is clear: 46.3% win rate
with strongly asymmetric payoff (winners consistently larger than losers).

---

## Theoretical Case for Options

With a deep ITM call or put (delta ~0.75), a 1% stock move translates to ~0.75% option
move. But capital deployed is only the option premium — typically 5-15% of the stock
price for an ITM weekly. That gives **5-10× leverage on capital** relative to buying the
stock directly.

Example at current position sizes ($10k account, rank-1 = $6,000):
- Stock: $6,000 buys ~5-6 shares of SNDK at ~$1,100 → $60 on a 1% move
- Options: same $6,000 buys ~10 contracts at $60 each → controls 1,000 shares → $750 on a 1% move

In theory: same signals × 5-10× leverage = dramatically higher returns on winning days.

---

## Real Costs That Offset Leverage

### Execution overhead (from analyze_entry_slippage.py, week of 2026-04-28)

| Date  | Execution overhead vs mid | vs fair price | Time value paid at entry |
|-------|--------------------------|---------------|--------------------------|
| 04-28 | -$155                    | -$490         | $2,578                   |
| 04-29 | -$13                     | -$160         | $12,694 (FN outlier)     |
| 04-30 | -$61                     | -$220         | $3,306                   |
| 05-01 | -$176                    | -$235         | $1,923                   |

**Time value paid is not all lost at exit** — theta only erodes partially over a 1-4 hour
same-day hold. What matters is the round-trip bid-ask spread cost:

| Ticker category | Typical spread % | Round-trip cost per contract |
|-----------------|-----------------|------------------------------|
| Liquid (COIN, AMD, CVNA, MSTR, CRWV, APP, SHOP) | 3-8% | ~$2-4 per $50 option |
| Illiquid (SNDK, FN, CRDO, RH) | 8-16% | ~$6-14 per $50 option |

Compared to stocks where the round-trip spread is 0.1-0.5% of notional, options carry
a structurally higher round-trip cost, particularly for illiquid tickers in the pool.

### The step-2 escalation pattern

Across the past week, step-2 fills (FILL_ESC chasing ask) are the single largest source
of above-fair-price fills. Step-1 fills at mid are consistently favorable or neutral; the
cost concentration is in escalation:

| Step | Typical vs-mid impact | vs-fair impact |
|------|-----------------------|----------------|
| Step 1 | +$57 to +$213 (favorable) | +$29 to +$125 |
| Step 2 | -$95 to +$46 | -$195 to -$160 |
| Step 3+ | mixed | -$240 worst case |

---

## Option Selection Improvements

### 1. Use 2-week expiry (8-12 DTE) for illiquid tickers

SNDK, FN, CRDO, and RH all have spread percentages of 8-16% on weeklies (1-5 DTE).
Switching to the next-week expiry typically halves the spread on illiquid names because
more market makers participate at longer DTEs. Theta cost increase is negligible for
same-day holds.

**Affected tickers:** SNDK, FN, CRDO, RH
**Expected improvement:** reduce round-trip spread cost by ~50% on these names

### 2. Add a delta floor of 0.65

The current `TimePremiumContractSelector` finds the shallowest ITM strike where time
premium ≤ 1% of stock price per 5 DTE. Strikes with delta < 0.65 lose leverage advantage
quickly when the stock moves against you. Adding a delta floor of 0.65 ensures every
contract has enough directional sensitivity to justify the spread cost.

**Implementation:** in `contract_selector.py`, after selecting the strike by time premium
threshold, verify `option_delta >= 0.65`; if not, go one strike deeper ITM.

### 3. Differentiate call vs put strike depth (volatility skew)

For BEARISH signals (buying puts), implied vol skew means puts at the same delta as
calls carry higher time premium. Targeting delta 0.70 for calls vs 0.75 for puts
partially compensates for the skew premium paid on downside protection.

### 4. Size by delta-adjusted notional to mirror stock strategy

The stock engine deploys 60%/40% of capital by rank. To truly mirror this in options,
size by **delta-adjusted notional** rather than fixed contract count:

```
contracts = floor(target_capital / (delta × 100 × stock_price))
```

Where `target_capital` = rank-weighted budget ($6,000 for rank-1 on $10k).
This keeps P&L scale directly comparable to the stock strategy and ensures the leverage
ratio is consistent across different tickers and price levels.

### 5. Keep stock-price-based exit signals (already correct)

The current engine monitors stock price for hard stop and trailing MA exit, not option
price. This is the right design — option bid-ask noise should never trigger a stop.
Do not change this.

---

## Bottom Line: When Options Outperform Stocks

Options amplify P&L **when:**
- The trade is a winner — leverage multiplies the gain
- The ticker has liquid options (spread ≤ 8%)
- The hold time is short (< 2 hours, limiting theta decay and avoiding EOD crush)
- The option fills at or below mid (step-1 fill)

Options **underperform** stocks when:
- The trade is a loser — leverage multiplies the loss too
- The ticker is SNDK, FN, CRDO, or RH (spread cost erodes edge)
- Escalation hits step 2+ (pays above fair price)
- The position is held into EOD (options decay accelerates in the last 30 min)

---

## Recommended Next Steps

1. **Empirical comparison**: run `analyze_entry_slippage.py` side-by-side with both
   engine logs on overlapping dates. Compare net daily P&L options vs stocks on the
   same signal days. Already have 2-week overlap (04-28 to 05-01) with both logs.

2. **Implement 2-week expiry fallback for illiquid tickers**: add a per-ticker DTE
   preference to `contract_selector.py`. Start with SNDK, FN, CRDO, RH.

3. **Backtest options P&L using real historical option chain data**: the current
   backtest only models stock P&L. Adding an option pricer layer (intrinsic + time value
   approximation by DTE) would let the selector backtest directly compare option vs stock
   returns for each signal.

4. **Monitor time value paid vs theta decay empirically**: use `fetch_ts_orders` output
   to track `time_value_paid` at entry vs `time_value_paid` at exit over a month. If
   exit time value ≈ entry time value (short holds, little decay), options are strictly
   better than stocks on winning days. If exit time value is consistently much lower,
   theta is eating the leverage gain.
