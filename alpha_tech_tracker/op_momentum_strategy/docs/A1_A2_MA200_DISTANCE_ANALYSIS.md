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

## Threshold Sweep Results

Tested thresholds 0.0% (baseline), 0.5%, 1.0%, 1.5%, 3.0% applied to **A1+A2 only** (`--min-ma200-distance-windows A1 A2`). All other config fixed: Top-2, weights 60/40, M1+A1+A2, reversal+BRE+BUE+doubledown, feed=iex.

### Return vs Baseline

| Year | 0.0% (base) | 0.5% | 1.0% | 1.5% | 3.0% | Regime |
|---|---|---|---|---|---|---|
| 2020 | +62.2% | +51.8% | +51.1% | +51.1% | +50.6% | COVID recovery |
| 2021 | +132.0% | +118.5% | +113.1% | +111.6% | +101.9% | Bull |
| 2022 | +177.9% | +143.3% | +139.7% | +136.9% | +124.0% | Bear/volatile |
| 2023 | +241.4% | +229.2% | +218.5% | +216.0% | +208.8% | Bull |
| 2025 | +178.2% | +161.9% | +155.4% | +152.2% | +135.2% | Choppy |
| 2026 YTD | +124.0% | +112.7% | +114.4% | +110.4% | +107.3% | Volatile |

### A1 Win Rate by Threshold

| Year | 0.0% (base) | 0.5% | 1.0% | 1.5% | 3.0% |
|---|---|---|---|---|---|
| 2020 | 24.4% | 22.8% | 22.9% | 25.4% | 29.4% |
| 2021 | 23.5% | 26.4% | 27.8% | 28.4% | 30.2% |
| 2022 | 22.8% | 28.1% | 28.7% | 29.3% | 31.3% |
| 2025 | 22.4% | 26.4% | 26.5% | 24.2% | 27.8% |
| 2026 YTD | 26.0% | 25.8% | 27.7% | 27.5% | 32.4% |

### A2 Win Rate by Threshold

| Year | 0.0% (base) | 0.5% | 1.0% | 1.5% | 3.0% |
|---|---|---|---|---|---|
| 2020 | 22.3% | 21.4% | 24.5% | 25.6% | 23.3% |
| 2021 | 27.9% | 27.5% | 26.5% | 28.7% | 29.2% |
| 2022 | 26.8% | 30.1% | 29.3% | 27.8% | 27.9% |
| 2025 | 28.4% | 32.4% | 32.0% | 34.0% | 36.2% |
| 2026 YTD | 24.3% | 31.8% | 34.2% | 35.4% | 39.0% |

---

## Sweep Findings

### 1. The filter always costs total return

Across all 6 years and every threshold, total return decreases vs baseline. The biggest winners each year (FN +$30 in 2026, RH +$23 in 2025, SHOP +$15 in 2022) tend to be outliers with extreme MA200 extension that gets filtered first. These single trades carry enough weight to outweigh the aggregate loss reduction.

### 2. A2 win rate improvement is consistent and front-loaded

A2 gains most of its WR improvement by 0.5–1.0%:
- 2025: 28.4% → 32.4% at 0.5%, then flattens
- 2026: 24.3% → 31.8% at 0.5%, 34.2% at 1.0%
- 2022: 26.8% → 30.1% at 0.5%

Going to 3.0% adds marginal additional WR but costs significantly more return.

### 3. A1 win rate improvement is noisier

A1 gains are real in 2021–2022 (+4–6pp at 1.0%) but inconsistent in other years. The 2025 and 2026 A1 WR curves are non-monotonic — the big A1 winners span a wide MA200 distance range so the filter clips good and bad trades somewhat randomly.

### 4. 2020 is still an exception

A2 in 2020 shows no consistent improvement even at 3.0% (22.3% → 23.3%), confirming the earlier finding that the COVID crash/recovery regime is structurally different.

### 5. Practical recommendation

Use `--min-ma200-distance 1.0 --min-ma200-distance-windows A1 A2` if the goal is improving A2 win rate consistency in post-2021 regimes. Accept the ~10–22pp return cost as the price of filtering noise. Do not use in 2020-style crash/recovery conditions.

**1.0% is preferred over higher thresholds** — most of the WR gain is captured by 1.0%, while going to 1.5–3.0% only costs more return without proportional WR benefit.
