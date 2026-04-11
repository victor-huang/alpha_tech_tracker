# ANAB → CRDO Swap — Benchmark Findings

**Date:** 2026-04-10  
**Context:** ANAB was flagged for sparse intraday data in live trading (min 17 bars/day in March 2026).  
Evaluated CRDO and NXT as replacements using 2025 full-year and 2026 YTD data.

---

## Liquidity Screen (2026 YTD, Jan–Apr 9)

| Ticker | Bars/Day avg | Min Bars | Trades/5m | Price | OR%  | Verdict |
|--------|-------------|----------|-----------|-------|------|---------|
| ANAB   | 39.5        | 17       | 9         | $61   | 1.95% | Removed — catastrophically sparse |
| CRDO   | 77.4        | 72       | 50        | $121  | 3.65% | **Selected** — full bars, strong OR |
| NXT    | 67.8        | 46       | 24        | $110  | 2.22% | Rejected — sparse (min 46), low trades |

NXT's min 46 bars/day is similar to EXPE/FN which were removed from the pool for the same reason.

---

## Performance Benchmark

Params: `--regime-filter --regime-ma 8 --weights 50 30 20`, DEFAULT_TICKERS with one swap at slot 12.

### 2025 Full Year

| Config | M1 (09:30/3) | WR | M2 (09:30/1) | WR |
|---|---|---|---|---|
| Baseline (ANAB) | +90.71% / $9,071 | 35% | +109.30% / $10,930 | 32% |
| CRDO replaces ANAB | +87.50% / $8,750 | 36% | +100.13% / $10,013 | 34% |
| NXT replaces ANAB | +86.24% / $8,624 | 35% | +110.17% / $11,017 | 34% |

### 2026 YTD (Jan 1 – Apr 9)

| Config | M1 (09:30/3) | WR | M2 (09:30/1) | WR |
|---|---|---|---|---|
| Baseline (ANAB) | +52.65% / $5,265 | 45% | +38.14% / $3,814 | 30% |
| CRDO replaces ANAB | +51.66% / $5,166 | 46% | +35.55% / $3,555 | 29% |
| NXT replaces ANAB | +51.16% / $5,116 | 46% | +38.13% / $3,813 | 31% |

---

## Extended Benchmark — M1+A1+A2, top-2, 60/40 weights, reversal+reentry (2026-04-10)

Config: `--weights 60 40 --top 2 --reversal --bearish-reentry --bullish-reentry`  
Windows: `--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100`

| Year | Baseline (ANAB) | CRDO | Δ vs Base | NXT | Δ vs Base |
|------|----------------|------|-----------|-----|-----------|
| 2020 | +92.56% / $9,256 | **+95.53% / $9,553** | **+2.97pp** | +95.53% / $9,553 | +2.97pp |
| 2021 | +192.81% / $19,281 | +156.95% / $15,695 | -35.86pp | +156.95% / $15,695 | -35.86pp |
| 2022 | +258.38% / $25,838 | +252.85% / $25,285 | -5.53pp | +246.03% / $24,603 | -12.35pp |
| 2023 | +363.27% / $36,327 | +334.94% / $33,494 | -28.33pp | +353.07% / $35,307 | -10.20pp |
| 2024 | +166.60% / $16,660 | +147.80% / $14,780 | -18.80pp | +156.35% / $15,635 | -10.25pp |
| 2025 | +295.00% / $29,500 | +264.03% / $26,403 | -30.97pp | +274.13% / $27,413 | -20.87pp |
| 2026 YTD | +117.52% / $11,752 | +105.50% / $10,550 | -12.02pp | +103.88% / $10,388 | -13.64pp |
| **Total** | **+1,486.14%** | **+1,357.60%** | **-128.54pp** | **+1,385.94%** | **-100.20pp** |

Win rates: all 3 variants 25–29% across years. Avg win: CRDO ~+1.37%, NXT ~+1.38%, Baseline ~+1.35% — similar quality per trade, difference is in signal frequency and ticker selection.

### Observations

- **2020/2021 CRDO = NXT** — neither ticker has historical data before their listing dates; the 16th pool slot fires no signals, leaving the other 15 tickers to drive results equally
- **CRDO beats baseline in 2020** (+2.97pp) — only year it leads outright
- **NXT is closer to baseline overall** (-100pp vs CRDO's -129pp) in this config — the reversal+reentry flags activate more NXT afternoon signals than CRDO
- **2023 worst gap for CRDO** (-28pp); NXT holds up better (-10pp) — NXT has stronger afternoon continuation signals in trending years
- **2026 YTD: CRDO edges NXT** (+105.5% vs +103.9%) — small but consistent advantage in recent live conditions
- **Overall returns are much higher** than the 50/30/20 top-3 config — 60/40 top-2 concentrates capital more aggressively, amplifying both wins and the ANAB gap

### Config Comparison (Baseline only)

| Config | 6-yr Total | Best Year | Worst Year |
|--------|-----------|-----------|------------|
| top-3, 50/30/20, M2+A1+A2 | +694% | 2023 (+170%) | 2020 (+81%) |
| top-2, 60/40, M1+A1+A2, reversal+reentry | +1,486% | 2023 (+363%) | 2020 (+93%) |

The reversal+reentry flags and concentrated top-2 weighting roughly double the headline return, with 2023 as the standout beneficiary.

---

## Decision

**CRDO selected** as ANAB replacement in `DEFAULT_TICKERS`.

**Rationale:**
- CRDO has full bar coverage (min 72/day) — reliable for live signal detection
- 3.65% OR% is the highest in the pool — strong opening range moves
- P&L drag vs ANAB is small (-3pp M1, -9pp M2 in 2025) and acceptable given ANAB's live data unreliability
- NXT rejected despite matching ANAB's P&L on M2: min 46 bars/day is a live trading risk, same failure mode as EXPE/FN

**Note:** CRDO is a relatively newer listing — the 2025 backtest lookback has limited history to score it highly via the rolling 60-day EV gate. Expect its contribution to grow as more history accumulates.
