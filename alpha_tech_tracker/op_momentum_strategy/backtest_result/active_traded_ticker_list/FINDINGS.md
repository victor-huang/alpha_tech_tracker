# ACTIVELY_TRADE_TICKERS — Benchmark Findings

**Date:** 2026-04-10  
**Period:** 2021-01-01 → 2025-12-31 (5 years, no-compound)  
**Params:** regime-filter --regime-ma 8, --weights 50 30 20, --stop-pct 0.15, --trailing-ma ma20

---

## Pool Composition

### V2 Pool (DEFAULT_TICKERS — baseline, 16 tickers)
```
SNDK, APP, SHOP, CVNA, AMD, META, EXPE, FANG, RH, FN, MU, ANAB, PLTR, COIN, NVDA, TSLA
```

### ACTIVELY_TRADE_TICKERS (new, 16 tickers)
```
SNDK, APP, SHOP, CVNA, AMD, META, MU, PLTR, COIN, NVDA, TSLA,
RKLB, ASTS, HOOD, CRWD, NFLX
```

**Changes:** removed ANAB, RH, FN, EXPE, FANG (sparse bars / low trade count in March 2026 data);  
added RKLB, ASTS, HOOD (Russell 2000 high-activity), CRWD, NFLX (large-cap).

### March 2026 Liquidity Screen (why these were removed)

| Ticker | Bars/Day | MinBars | Trades/5m | Verdict |
|--------|----------|---------|-----------|---------|
| ANAB   | 39.5     | 17      | 9         | Removed — catastrophically sparse |
| RH     | 54.5     | 36      | 15        | Removed — frequently missing session data |
| FN     | 66.0     | 50      | 20        | Removed — sparse + very low trades |
| EXPE   | 70.2     | 53      | 28        | Removed — sparse + low trades |
| FANG   | 74.6     | 66      | 38        | Removed — marginal bars + low trades |

### March 2026 Liquidity Screen (why these were added)

| Ticker | Bars/Day | MinBars | Trades/5m | OR%  | Source        |
|--------|----------|---------|-----------|------|---------------|
| NFLX   | 78.2     | 78      | 650       | 1.67% | Large-cap     |
| CRWD   | 77.0     | 73      | 51        | 2.65% | Large-cap     |
| RKLB   | 78.1     | 77      | 84        | 3.22% | Russell 2000  |
| HOOD   | 78.2     | 78      | 84        | 2.28% | Russell 2000  |
| ASTS   | 77.8     | 77      | 52        | 3.49% | Russell 2000  |

---

## Results: M1 Window (09:30 / 3 bars, entry 9:45 AM)

| Metric         | V2 Pool  | ACTIVELY_TRADE |
|----------------|----------|----------------|
| 5-year total   | +371.54% | +351.98%       |
| Trades         | 3,228    | 3,093          |
| Win rate       | 33%      | 34%            |
| Avg win        | +1.63%   | +1.61%         |
| Avg loss       | -0.32%   | -0.36%         |

### Year-by-Year M1

| Year | V2 Pool  | ACTIVELY_TRADE | Δ      |
|------|----------|----------------|--------|
| 2021 | +50.63%  | +52.00%        | +1.37pp |
| 2022 | +104.49% | +106.16%       | +1.67pp |
| 2023 | +85.89%  | +83.60%        | -2.29pp |
| 2024 | +39.82%  | +41.26%        | +1.44pp |
| 2025 | +90.71%  | +68.95%        | -21.76pp |
| **Total** | **+371.54%** | **+351.98%** | **-19.56pp** |

**M1 verdict:** ACTIVELY_TRADE trails V2 by ~20pp over 5 years, driven mostly by a weaker 2025 (-22pp). 2021–2024 are roughly even.

---

## Results: M2 Window (09:30 / 1 bar, entry 9:35 AM)

| Metric         | V2 Pool* | ACTIVELY_TRADE |
|----------------|----------|----------------|
| 5-year total   | —        | +525.50%       |
| Trades         | —        | 3,242          |
| Win rate       | —        | 32%            |
| Avg win        | —        | +1.94%         |
| Avg loss       | —        | -0.27%         |

*V2 M2 not re-run; reference from prior studies: ~+450–500% range.

### Year-by-Year M2

| Year | ACTIVELY_TRADE |
|------|----------------|
| 2021 | +89.82%  |
| 2022 | +104.05% |
| 2023 | +107.91% |
| 2024 | +127.71% |
| 2025 | +96.05%  |
| **Total** | **+525.50%** |

**M2 verdict:** Strongly consistent — positive every year, no year below +89%. Best year 2024 (+128%). Much higher avg win (+1.94%) than M1 (+1.61%).

---

## Results: M1 + A1 + A2 (sequential capital recycling)

| Metric         | V2 Pool  | ACTIVELY_TRADE |
|----------------|----------|----------------|
| 5-year total   | —        | +680.07%       |
| Trades         | —        | 9,206          |
| Win rate       | —        | 27%            |
| Avg win        | —        | +1.15%         |
| Avg loss       | —        | -0.15%         |

### Year-by-Year M1+A1+A2

| Year | ACTIVELY_TRADE |
|------|----------------|
| 2021 | +108.29% |
| 2022 | +192.39% |
| 2023 | +163.41% |
| 2024 | +77.96%  |
| 2025 | +138.02% |
| **Total** | **+680.07%** |

---

## Results: M2 + A1 + A2 (sequential capital recycling) — BEST CONFIG

| Metric         | V2 Pool   | ACTIVELY_TRADE | Δ       |
|----------------|-----------|----------------|---------|
| 5-year total   | +798.10%  | +854.07%       | +55.97pp |
| Trades         | 9,895     | 9,355          | -540    |
| Win rate       | 26%       | 26%            | —       |
| Avg win        | +1.16%    | +1.28%         | +0.12pp |
| Avg loss       | -0.10%    | -0.12%         | -0.02pp |

### Year-by-Year M2+A1+A2

| Year | V2 Pool   | ACTIVELY_TRADE | Δ       |
|------|-----------|----------------|---------|
| 2021 | +148.71%  | +146.09%       | -2.62pp |
| 2022 | +172.75%  | +190.11%       | +17.36pp |
| 2023 | +169.49%  | +187.84%       | +18.35pp |
| 2024 | +123.23%  | +164.40%       | +41.17pp |
| 2025 | +183.90%  | +165.61%       | -18.29pp |
| **Total** | **+798.10%** | **+854.07%** | **+55.97pp** |

**M2+A1+A2 verdict:** ACTIVELY_TRADE wins by +56pp over 5 years. Dominant in 2022–2024 (+17 to +41pp/year). Only trails in 2025 (-18pp) and slightly in 2021 (-3pp).

---

## Summary Table

| Window config  | V2 Pool   | ACTIVELY_TRADE | Winner         |
|----------------|-----------|----------------|----------------|
| M1 alone       | +371.54%  | +351.98%       | V2 (-19.56pp)  |
| M2 alone       | —         | +525.50%       | —              |
| M1+A1+A2       | —         | +680.07%       | —              |
| M2+A1+A2       | +798.10%  | +854.07%       | **AT (+55.97pp)** |

## Key Takeaways

1. **M2+A1+A2 is the best config** for ACTIVELY_TRADE — +854% over 5 years, wins 3 of 5 years vs V2 pool.
2. **M1 alone slightly underperforms V2** — the removed tickers (especially EXPE/FANG) contributed to M1 morning signals in 2025; new Russell 2000 names (RKLB, ASTS) may need more history to fully contribute.
3. **Avg win is higher on AT** (+1.28% vs +1.16% for M2+A1+A2) — the new names have better OR% (ASTS 3.49%, RKLB 3.22%, CRWD 2.65%) which translates to larger winning moves.
4. **Fewer trades on AT** (9,355 vs 9,895) — cleaner pool, removed noisy low-liquidity names fire fewer signals.
5. **2025 is the weak year for AT** — new additions (RKLB, ASTS, HOOD) are newer listings with less backtest history in bear/volatile regimes; worth monitoring in live trading.

---

---

## Window Sweep — AT Pool (2026-04-10)

Full sweep of start-time × bar-count combinations for each window independently.  
Period: 2021-01-01 → 2025-12-31, no-compound, regime-ma 8, weights 50/30/20.

### Morning Window Sweep

| Config | Return% | P&L$ | WR | AvgWin | AvgLoss |
|---|---|---|---|---|---|
| **09:30 / 1 bar** | **+525.5%** | **$52,550** | 32% | +1.94% | -0.27% |
| 09:30 / 2 bars | +404.5% | $40,451 | 32% | +1.85% | -0.34% |
| 09:30 / 3 bars | +352.0% | $35,198 | 34% | +1.61% | -0.36% |
| 09:30 / 6 bars | +314.3% | $31,434 | 36% | +1.45% | -0.38% |
| 10:00 / 1 bar | +311.4% | $31,135 | 28% | +1.36% | -0.15% |
| 09:30 / 4 bars | +297.9% | $29,790 | 33% | +1.58% | -0.38% |
| 10:00 / 2 bars | +241.9% | $24,186 | 30% | +1.19% | -0.19% |
| 10:00 / 3 bars | +223.6% | $22,361 | 30% | +1.23% | -0.22% |
| 10:30 / 1 bar | +218.5% | $21,850 | 26% | +1.03% | -0.10% |
| 10:00 / 6 bars | +211.0% | $21,097 | 32% | +1.08% | -0.25% |
| 10:30 / 6 bars | +198.5% | $19,853 | 31% | +1.03% | -0.21% |
| 10:00 / 4 bars | +196.1% | $19,605 | 31% | +1.18% | -0.24% |
| 10:30 / 4 bars | +195.8% | $19,577 | 30% | +1.09% | -0.19% |
| 10:30 / 2 bars | +194.1% | $19,406 | 27% | +1.05% | -0.15% |
| 10:30 / 3 bars | +166.8% | $16,676 | 29% | +0.94% | -0.17% |

**Finding:** 09:30 / 1 bar is the clear best morning config — confirms V2 pool result. Every extra bar reduces return. Sharp dropoff after 10:00.

### Afternoon-1 Window Sweep

| Config | Return% | P&L$ | WR | AvgWin | AvgLoss |
|---|---|---|---|---|---|
| **11:00 / 3 bars** | **+224.9%** | **$22,492** | 29% | +1.04% | -0.15% |
| 12:00 / 1 bar | +203.2% | $20,321 | 22% | +1.01% | -0.07% |
| 11:00 / 2 bars | +198.6% | $19,856 | 26% | +1.05% | -0.13% |
| 14:00 / 1 bar | +192.2% | $19,222 | 23% | +0.91% | -0.06% |
| 12:00 / 2 bars | +188.4% | $18,835 | 26% | +0.91% | -0.09% |
| 12:30 / 1 bar | +187.0% | $18,704 | 22% | +0.93% | -0.05% |
| 13:15 / 1 bar (V2 best) | +184.9% | $18,492 | 23% | +0.87% | -0.05% |
| 11:30 / 1 bar | +179.1% | $17,911 | 24% | +0.93% | -0.07% |
| 13:30 / 1 bar | +178.8% | $17,879 | 23% | +0.86% | -0.05% |
| 11:30 / 2 bars | +176.0% | $17,596 | 26% | +0.96% | -0.10% |
| 11:30 / 3 bars | +172.8% | $17,276 | 27% | +0.97% | -0.13% |
| 13:30 / 3 bars | +170.2% | $17,016 | 26% | +0.85% | -0.09% |
| 14:00 / 2 bars | +167.8% | $16,779 | 26% | +0.84% | -0.09% |
| 11:00 / 1 bar | +167.5% | $16,748 | 25% | +0.90% | -0.09% |
| 13:30 / 2 bars | +153.8% | $15,380 | 23% | +0.92% | -0.08% |
| 13:15 / 2 bars | +148.2% | $14,824 | 23% | +0.85% | -0.08% |
| 13:00 / 3 bars | +145.7% | $14,566 | 25% | +0.88% | -0.10% |
| 14:00 / 3 bars | +145.3% | $14,525 | 25% | +0.83% | -0.10% |
| 13:00 / 1 bar | +144.1% | $14,407 | 21% | +0.86% | -0.06% |
| 13:15 / 3 bars | +142.1% | $14,214 | 28% | +0.75% | -0.10% |
| 12:30 / 2 bars | +141.7% | $14,172 | 24% | +0.85% | -0.09% |
| 12:30 / 3 bars | +139.9% | $13,988 | 24% | +0.91% | -0.11% |
| 12:00 / 3 bars | +132.4% | $13,235 | 25% | +0.81% | -0.11% |
| 13:00 / 2 bars | +119.3% | $11,925 | 24% | +0.75% | -0.08% |

**Finding:** `11:00 / 3 bars` (entry 11:15 AM) is the new best afternoon-1 for AT pool — beats the V2 best (13:15/1) by +40pp. AT pool's higher-OR% names have stronger mid-morning trend continuation. Recommended new label: **A1-AT**.

### Afternoon-2 Window Sweep

| Config | Return% | P&L$ | WR | AvgWin | AvgLoss |
|---|---|---|---|---|---|
| **14:00 / 1 bar** | **+192.2%** | **$19,222** | 23% | +0.91% | -0.06% |
| 14:00 / 2 bars | +167.8% | $16,779 | 26% | +0.84% | -0.09% |
| 15:15 / 1 bar | +158.5% | $15,847 | 26% | +0.72% | -0.06% |
| 15:15 / 2 bars | +153.1% | $15,309 | 31% | +0.66% | -0.08% |
| 15:00 / 2 bars | +150.2% | $15,015 | 27% | +0.73% | -0.08% |
| 15:30 / 1 bar | +150.0% | $14,999 | 30% | +0.59% | -0.06% |
| 14:00 / 3 bars | +145.3% | $14,525 | 25% | +0.83% | -0.10% |
| 15:00 / 3 bars | +145.2% | $14,524 | 29% | +0.69% | -0.09% |
| 15:00 / 1 bar (V2 best) | +141.2% | $14,120 | 24% | +0.73% | -0.05% |
| 14:30 / 2 bars | +140.7% | $14,073 | 26% | +0.75% | -0.08% |
| 15:30 / 2 bars | +139.3% | $13,928 | 36% | +0.50% | -0.08% |
| 15:15 / 3 bars | +137.3% | $13,734 | 32% | +0.60% | -0.10% |
| 14:30 / 3 bars | +133.6% | $13,363 | 26% | +0.76% | -0.09% |
| 14:30 / 1 bar | +126.1% | $12,612 | 22% | +0.74% | -0.05% |
| 15:30 / 3 bars | +119.7% | $11,970 | 38% | +0.45% | -0.10% |

**Finding:** `14:00 / 1 bar` (entry 2:05 PM) is the new best afternoon-2 for AT pool — beats the V2 best (15:00/1) by +51pp. Earlier entry captures directional move before power hour congestion. Recommended new label: **A2-AT**.

### Sweep Summary — Recommended AT Window Config

| Window | V2 Pool Best | AT Pool Best | Δ |
|---|---|---|---|
| Morning | 09:30 / 3 bars (+352%) | **09:30 / 1 bar (+526%)** | +174pp |
| Afternoon-1 | 13:15 / 1 bar (+185%) | **11:00 / 3 bars (+225%)** | +40pp |
| Afternoon-2 | 15:00 / 1 bar (+141%) | **14:00 / 1 bar (+192%)** | +51pp |

**Next step:** run combined M2 (09:30/1) + A1-AT (11:00/3) + A2-AT (14:00/1) multi-window backtest to measure combined P&L. Note that 11:00/3 bars closes at 11:15 and 14:00/1 bar starts at 14:00 — windows are non-overlapping.

---

## Output Files

| File | Description |
|------|-------------|
| `m1_09:30_3bars.txt` | AT pool — M1 window full output |
| `m2_09:30_1bar.txt` | AT pool — M2 window full output |
| `m1_a1_a2.txt` | AT pool — M1+A1+A2 full output |
| `m2_a1_a2.txt` | AT pool — M2+A1+A2 full output |
| `v2_baseline_m1.txt` | V2 pool — M1 baseline for comparison |
| `v2_baseline_m2_a1_a2.txt` | V2 pool — M2+A1+A2 baseline for comparison |
