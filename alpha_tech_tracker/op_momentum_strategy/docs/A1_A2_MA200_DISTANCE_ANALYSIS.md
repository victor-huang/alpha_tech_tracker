# A1/A2 Window — MA200 Distance Analysis

**Date:** 2026-04-25  
**Backtest config:** Top-2, weights 60/40, M1+A1+A2, reversal+BRE+BUE+doubledown, feed=iex  
**Tickers:** V3 pool (SNDK, APP, SHOP, CVNA, AMD, META, EXPE, RH, FN, MU, CRDO, PLTR, COIN, CLS, MSTR, CRWV, MRVL)

---

## Question

Do A1 and A2 entry prices relative to the 5-min 20MA, 50MA, or 200MA predict trade outcome?

---

## Methodology

For each A1/A2 trade, the 5-min bar at the window open (13:15 for A1, 15:00 for A2) was looked up and MA values were read at that bar. Distance was computed as:

```
pct_above_maX = (entry_price - maX) / maX × 100
```

Sign preserved: positive = entry above MA, negative = below. Both bullish and bearish signals included as-is (bearish entries that are above MA200 indicate a stock extended in an uptrend reversing intraday).

Average distance was computed separately for winning and losing trades. The **gap = wins avg − losses avg**.

---

## A1 Window Results (13:15 / 1 bar)

| Year | Trades | WR | MA20 Gap | MA50 Gap | MA200 Gap |
|---|---|---|---|---|---|
| 2020 | 127 | 24.4% | +0.08pp | +0.10pp | **+0.94pp** |
| 2021 | 404 | 23.5% | +0.11pp | +0.29pp | **+0.63pp** |
| 2022 | 400 | 22.8% | +0.33pp | +0.85pp | **+1.24pp** |
| 2025 | 456 | 22.4% | +1.14pp | +1.34pp | **+1.56pp** |
| 2026 YTD | 146 | 26.0% | +0.44pp | +0.91pp | **+1.44pp** |

**MA200 is the strongest separator every single year without exception.**

### A1 top winners context (2025 and 2026)

| Date | Ticker | Signal | P&L% | MA200 dist |
|---|---|---|---|---|
| 2026-03-06 | FN | BEARISH | +5.84% | -4.65% |
| 2026-04-09 | MU | BULLISH | +3.14% | +3.88% |
| 2026-01-08 | CVNA | BEARISH | +2.71% | +0.97% |
| 2025-04-09 | RH | BEARISH | +14.52% | +2.25% |
| 2025-04-09 | FN | BEARISH | +8.79% | +6.25% |
| 2025-06-23 | COIN | BULLISH | +1.51% | +6.69% |

---

## A2 Window Results (15:00 / 1 bar)

| Year | Trades | WR | MA20 Gap | MA50 Gap | MA200 Gap |
|---|---|---|---|---|---|
| 2020 | 166 | 22.3% | -0.02pp | -0.03pp | **-0.62pp** ← reversed |
| 2021 | 416 | 27.9% | +0.17pp | +0.26pp | **+0.46pp** |
| 2022 | 425 | 26.8% | +0.35pp | +0.60pp | **+1.10pp** |
| 2025 | 462 | 28.4% | +0.39pp | +0.63pp | **+1.53pp** |
| 2026 YTD | 148 | 24.3% | +0.38pp | +0.37pp | **+1.05pp** |

---

## A1 vs A2 MA200 Gap Side-by-Side

| Year | A1 MA200 Gap | A2 MA200 Gap |
|---|---|---|
| 2020 | +0.94pp | **-0.62pp** |
| 2021 | +0.63pp | +0.46pp |
| 2022 | +1.24pp | +1.10pp |
| 2025 | +1.56pp | +1.53pp |
| 2026 YTD | +1.44pp | +1.05pp |

---

## Findings

### 1. MA200 is the only consistent signal; MA20/MA50 are noise

Across all years and both windows, MA200 distance is the strongest separator between wins and losses. MA20 and MA50 gaps are small and inconsistent — they offer minimal predictive value on their own.

### 2. A1 — pattern holds all 5 years

Winners are further above MA200 every year (+0.63 to +1.56pp gap). The effect strengthens in choppier/more trend-dependent markets (2022 onward) and is weaker in broad bull years (2021).

### 3. A2 — pattern holds 2022 onward; earlier years are unreliable

- **2022–2026:** A2 mirrors A1 almost exactly (+1.05 to +1.53pp gap). The filter is equally valid.
- **2021:** Weak signal (+0.46pp) — broad bull market, MA positioning less decisive.
- **2020:** Reversed (-0.62pp) — COVID crash + recovery created conditions where extended-above-MA200 stocks were fading, not continuing. A filter would have been counterproductive.

### 4. The filter strengthens in modern regimes

The MA200 gap has grown over time for both windows (small in 2020-2021, large in 2022-2026). This suggests the filter is most useful in post-2021 market conditions with higher volatility and more defined trends.

---

## Proposed Next Step

Sweep a `--min-ma200-distance` filter threshold for A1 and A2 over the **2022–2026** period (the regime where the signal is reliable). Candidate thresholds: 1.0%, 1.5%, 2.0%.

For each threshold, measure:
- Signal count reduction (how many trades filtered out)
- Win rate improvement
- Net P&L change (filter removes some losers but also some winners)

**Do not apply to the 2020 backtest** — the reversed pattern suggests the filter is regime-dependent and would hurt in crash/recovery environments.
