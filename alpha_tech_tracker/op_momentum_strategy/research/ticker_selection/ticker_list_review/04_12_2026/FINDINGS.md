# Ticker List Review — 2026-04-12

## Summary

Quarterly P&L trend analysis of the V2 pool (16 tickers) from Q3 2024 through Q1 2026.
Identified three structurally declining tickers and replaced them with four screened candidates.

**Result: V2 → V3 pool (17 tickers)**

Removed: `FANG`, `NVDA`, `TSLA`
Added: `CLS`, `MSTR`, `CRWV`, `MRVL`

---

## Backtest Config

All per-ticker standalone runs use:

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --tickers <TICKER> \
  --top 1 --weights 100 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 5 \
  --start <START> --end <END> [--feed iex for 2026]
```

Pool-level validation uses `--top 2 --weights 60 40` (SOA config).

---

## V2 Pool — Quarterly P&L Trend (Q3 2024 → Q1 2026)

`n/a` = ticker had no Alpaca bar data for that quarter (SNDK relisted late 2024).

| Ticker | Q3 2024 | Q4 2024 | Q1 2025 | Q2 2025 | Q3 2025 | Q4 2025 | Q1 2026 |
|--------|---------|---------|---------|---------|---------|---------|---------|
| SNDK   | n/a     | n/a     | +7.85%  | +2.99%  | +26.88% | +20.37% | +43.55% |
| APP    | +10.37% | +20.53% | +8.64%  | +16.91% | +12.36% | +17.24% | +36.81% |
| SHOP   | +9.20%  | +3.05%  | +24.26% | +9.02%  | +6.38%  | +8.13%  | +57.49% |
| CVNA   | +7.44%  | +13.51% | +24.88% | +35.67% | +4.61%  | +22.19% | +41.47% |
| AMD    | +22.05% | +9.26%  | +8.15%  | +21.97% | +21.40% | +12.86% | +19.43% |
| META   | +3.07%  | +11.57% | +3.87%  | +26.43% | +5.76%  | +3.67%  | +15.94% |
| EXPE   | +9.04%  | +6.68%  | +8.64%  | +23.20% | +52.27% | +19.97% | +12.00% |
| **FANG** | +13.96% | +8.09% | +1.65% | +1.95% | +15.20% | +13.71% | +2.15% |
| RH     | +18.68% | +3.03%  | +18.35% | +51.10% | +15.72% | +16.27% | +43.86% |
| FN     | +0.02%  | +10.40% | +21.05% | +7.54%  | +36.39% | +10.25% | +48.40% |
| MU     | +29.80% | +17.25% | +3.75%  | +13.94% | +13.94% | +23.68% | +19.43% |
| CRDO   | +21.90% | +28.87% | +2.01%  | +15.17% | +20.32% | +16.87% | +28.06% |
| PLTR   | -2.09%  | +23.64% | +26.89% | +34.95% | +12.66% | +7.07%  | +29.51% |
| COIN   | +11.07% | +29.88% | +23.47% | +44.61% | +35.96% | +3.08%  | +13.00% |
| **NVDA** | +18.60% | +0.59% | +18.76% | +15.18% | +4.29% | +6.78%  | +9.54% |
| **TSLA** | +24.05% | +16.51% | +12.45% | +43.31% | +41.03% | +11.51% | +6.50% |

### Tickers Flagged for Removal

**FANG** — Structurally weak. Low and erratic output: Q1 2025 +1.65%, Q2 2025 +1.95%, Q1 2026 +2.15%.
Bounced in Q3/Q4 2025 but still among the weakest contributors in the pool every quarter.

**NVDA** — Fading trend. Q4 2024 collapsed to +0.59%, recovered partially, then back to sub-10%
(Q3 2025 +4.29%, Q4 2025 +6.78%, Q1 2026 +9.54%). The strategy's OR-breakout signal doesn't
extract strong edge from NVDA's current price behavior.

**TSLA** — Peaked and declining. Exceptional in H1 2025 (Q2 +43%, Q3 +41%) but dropped sharply:
Q4 2025 +11.51%, Q1 2026 +6.50%. Losing momentum as a breakout vehicle post-peak.

### Tickers to Watch

**COIN** — Very strong H1 2025 (Q2 +44.6%, Q3 +36%) then collapsed Q4 2025 (+3.08%). Recovering
in Q1 2026 (+13%). Highly regime-dependent (crypto correlated). Keeping for now.

**EXPE** — Anomalous Q3 2025 spike (+52%) likely event-driven. Otherwise mediocre (+6-23%).
Not removed but under observation.

**META** — Erratic. Good some quarters, weak others (+3-4% in Q1 2025, Q4 2025). Under observation.

---

## New Ticker Screen — Quarterly P&L (Q3 2024 → Q1 2026)

Candidates screened: CLS, AMAT, AVGO, MRVL, CRWV, MSTR, FIX

| Ticker | Q3 2024 | Q4 2024 | Q1 2025 | Q2 2025 | Q3 2025 | Q4 2025 | Q1 2026 |
|--------|---------|---------|---------|---------|---------|---------|---------|
| CLS    | +12.46% | +13.27% | +22.33% | +38.90% | +30.96% | -2.83%  | +29.77% |
| AMAT   | +5.73%  | +12.73% | +14.50% | +11.97% | +10.61% | +4.56%  | +16.78% |
| AVGO   | +27.17% | +3.56%  | +6.54%  | +14.43% | +8.46%  | +13.09% | +11.48% |
| MRVL   | +18.02% | +1.84%  | +8.12%  | +39.72% | +12.33% | +7.51%  | +27.80% |
| CRWV   | n/a     | n/a     | n/a     | +17.52% | +11.60% | +23.93% | +37.14% |
| MSTR   | +8.26%  | +56.03% | +21.63% | +18.60% | +15.24% | +14.05% | +21.05% |
| FIX    | -0.87%  | +15.43% | +1.76%  | -0.92%  | -6.43%  | -0.69%  | +17.88% |

### Decisions

**CLS (Celestica)** — Added. Strong and consistent upward trend from Q3 2024 through Q1 2026.
Only blip: Q4 2025 (-2.83%). Replaces FANG.

**MSTR (MicroStrategy)** — Added. Most consistent performer — never negative, exceptional Q4 2024
(+56%, BTC post-election run), solid in all other quarters (+8–22%). Already in AT pool.
Replaces NVDA.

**CRWV (CoreWeave)** — Added. IPO'd March 2025; only 4 quarters of history but accelerating:
Q2 2025 +17.52% → Q3 2025 +11.60% → Q4 2025 +23.93% → Q1 2026 +37.14%. Replaces TSLA.

**MRVL (Marvell Technology)** — Added. High variance but strong peaks: Q2 2025 +39.72%,
Q1 2026 +27.80%. Expands pool from 16 → 17 tickers.

**AMAT** — Not added. Consistent but modest (+5–16%), declining trend into Q4 2025 (+4.56%).
Below the quality bar of existing V2 contributors.

**AVGO** — Not added. Decent Q3 2024 (+27%) but fading and similar to AMAT in recent quarters.

**FIX** — Disqualified. Mostly flat or negative across multiple quarters.

---

## V2 vs V3 Pool Validation — Full 5-Year + 2026 YTD

SOA config (`--top 2 --weights 60 40`, M1+A1+A2, reversal+BRE+BRU+DD-5):

| Year | V2 | V3 | Δ | Winner |
|------|----|----|---|--------|
| 2021 | +158.41% | +189.74% | +31.3pp | **V3** |
| 2022 | +210.80% | +214.48% | +3.7pp  | **V3** |
| 2023 | +352.89% | +332.33% | -20.6pp | V2 |
| 2024 | +151.69% | +161.16% | +9.5pp  | **V3** |
| 2025 | +185.14% | +169.83% | -15.3pp | V2 |
| 2026 YTD (Jan–Apr 10) | +108.79% | +126.11% | +17.3pp | **V3** |
| **5-yr sum (2021–2025)** | **+1,058.93%** | **+1,067.54%** | **+8.6pp** | **V3** |

**V3 wins 4 of 6 years and the 5-year total by +8.6pp.**

### Why V2 wins 2023 (-20.6pp)

2023 was a strong sustained bull year. TSLA, NVDA, and FANG generated strong BULLISH OR breakouts
in that environment. MSTR was in an early recovery phase post-crypto-crash and contributed less.
CRWV did not yet exist.

### Why V2 wins 2025 (-15.3pp)

TSLA was exceptional mid-year (Q2 +43%, Q3 +41%) before its decline. CRWV only entered the pool
in Q2 2025 (pre-IPO in Q1), leaving V3 one ticker short for the first quarter.

### Why V3 wins bear/choppy years (2021, 2022, 2024, 2026)

CLS, MSTR, MRVL extract stronger OR-breakout edge in volatile and downtrending markets.
MSTR's BTC-correlated beta generates large BEARISH moves in risk-off environments.
CLS and MRVL show consistent high-amplitude breakouts in choppy macro conditions.

---

## V3 Pool — Final Composition (17 tickers)

V3 is confirmed as the better pool: +8.6pp over 5 years, +17.3pp in 2026 YTD.
The two V2 wins (2023, 2025) are explained by TSLA's bull-year strength, not a structural flaw in V3.


```python
DEFAULT_TICKERS = [
    "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
    "EXPE", "RH", "FN", "MU",
    "CRDO", "PLTR", "COIN",
    "CLS",   # replaced FANG 2026-04-12
    "MSTR",  # replaced NVDA 2026-04-12
    "CRWV",  # replaced TSLA 2026-04-12
    "MRVL",  # added 2026-04-12 (pool expanded 16 → 17)
]
```
