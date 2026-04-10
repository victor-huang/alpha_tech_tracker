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

## Decision

**CRDO selected** as ANAB replacement in `DEFAULT_TICKERS`.

**Rationale:**
- CRDO has full bar coverage (min 72/day) — reliable for live signal detection
- 3.65% OR% is the highest in the pool — strong opening range moves
- P&L drag vs ANAB is small (-3pp M1, -9pp M2 in 2025) and acceptable given ANAB's live data unreliability
- NXT rejected despite matching ANAB's P&L on M2: min 46 bars/day is a live trading risk, same failure mode as EXPE/FN

**Note:** CRDO is a relatively newer listing — the 2025 backtest lookback has limited history to score it highly via the rolling 60-day EV gate. Expect its contribution to grow as more history accumulates.
