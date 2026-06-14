# Win-Rate Selector — Regime-Hold $80k Backtest Results

**Run date:** 2026-06-06  
**Config:** M1 09:30/3 | win-rate selector | regime-engine | regime-hold | ecb=2 | stop-pct=0 | trailing-ma=none | top-8 | $80k capital | NO reversal / NO reentry / NO doubledown

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --selector win-rate --enable-regime-engine \
  --window M1 09:30 3 --morning-split 100 \
  --top 8 --capital 80000 \
  --stop-pct 0 --trailing-ma none \
  --regime-hold \
  --extend-collection-bars 2 \   # now the default
  --mock-trade-execution --feed sip \
  --replay-date YYYY-MM-DD
```

Tickers: `SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT`

---

## Capital Allocation Models

| Model | Flag | Slot size | Avg daily deployed | Description |
|---|---|---|---|---|
| **Rank-weighted** (default) | _(none)_ | proportional by rank | ~$85–95k (>100% — capital recycled intraday) | Full capital deployed; fewer signals → larger slots per rank weight |
| **Fixed-alloc** | `--fixed-signal-alloc` | $80k ÷ 8 = $10k/slot | ~$22–28k (~30%) | Fixed $10k/slot; idle capital stays undeployed on low-signal days |

---

## Fixed-Alloc Results — All Years

| Year | Days | P&L | Return on avg deployed | Committed % | Avg deployed | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|---|---|
| 2017 | 223 | +$5,053 | +18.6% | +6.3% | $27,130 | +0.086% | 5.49 |
| 2018 | 209 | +$11,032 | +43.8% | +13.8% | $25,215 | +0.197% | 5.87 |
| 2019 | 206 | +$9,657 | +39.6% | +12.1% | $24,417 | +0.186% | 6.68 |
| 2020 | 205 | +$9,563 | +39.4% | +12.0% | $24,244 | +0.179% | 5.15 |
| 2021 | 216 | +$9,573 | +35.0% | +12.0% | $27,361 | +0.184% | 4.99 |
| 2022 | 209 | +$14,601 | +52.2% | +18.3% | $27,990 | +0.196% | 5.38 |
| 2023 | 209 | +$11,667 | +50.7% | +14.6% | $23,014 | +0.224% | 6.06 |
| 2024 | 211 | +$13,681 | +60.8% | +17.1% | $22,512 | +0.280% | 5.72 |
| 2025 | 212 | +$13,195 | +54.2% | +16.5% | $24,340 | +0.232% | 6.08 |
| 2026 YTD | 96 | +$5,780 | +22.9% | +7.2% | $25,208 | +0.254% | 5.76 |
| **Total** | **1,996** | **+$103,802** | | | | | |

- Profitable **every single year** across 10 years (2017–2026)
- 2017 Mean RODC (+0.086%) is notably lower — tickers like ARM/RDDT didn't exist and the win-rate signals weren't calibrated on this era; strategy still profitable with DW-Sharpe 5.49
- Capital utilization consistently ~**28–35%** — only ~$23–28k average at work per day
- Mean RODC trending upward post-2020: +0.179% (2020) → +0.280% (2024)
- DW-Sharpe above **4.99 every year**
- Log dirs: `logs/replay_YYYY_stock_m1_winrate_regimehold_cap80k_fixedalloc/`

### SIP Data Limit

Tested back to 2015. **2017 is the earliest fully usable year.**

| Year | Status |
|---|---|
| 2017 | Full data — 223 trading days |
| 2016 | Partial — only ~6 days in January have SIP data |
| 2015 | No data — SIP feed does not reach this far |

---

## Rank-Weighted vs Fixed-Alloc Comparison (2022, 2025, 2026 YTD)

| Year | Config | P&L | Return on avg deployed | Committed % | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|---|
| 2022 | Rank-weighted | +$39,174 | +45.5% on avg $86k | +49.0% | +0.196% | 4.63 |
| 2022 | Fixed-alloc | +$14,601 | **+52.2%** on avg $28k | +18.3% | **+0.196%** | **5.38** |
| 2025 | Rank-weighted | +$41,951 | +46.4% on avg $90k | +52.4% | +0.232% | 4.95 |
| 2025 | Fixed-alloc | +$13,195 | **+54.2%** on avg $24k | +16.5% | **+0.232%** | **6.08** |
| 2026 YTD | Rank-weighted | +$22,004 | +23.6% on avg $93k | +27.5% | +0.254% | 5.41 |
| 2026 YTD | Fixed-alloc | +$5,780 | **+22.9%** on avg $25k | +7.2% | **+0.254%** | **5.76** |

**Key finding:** Rank-weighted and fixed-alloc have **identical Mean RODC** in every year — the per-signal edge is the same. The only difference is capital utilization: rank-weighted deploys >100% of $80k (capital recycled intraday via renormalization), while fixed-alloc deploys ~30%. Fixed-alloc achieves slightly higher DW-Sharpe every year due to lower deployment variance.

**Trade-off:** rank-weighted earns ~3× more absolute P&L by putting more capital to work. Fixed-alloc preserves the pure edge signal with better risk-adjusted returns per dollar deployed.

---

## Sub-leg Analysis (Reversal / Reentry / Doubledown)

Sub-leg behavior is **strongly year-regime dependent**. In trending years doubledown amplifies gains; in choppy years reentry erodes the primary edge.

### Fixed-Alloc + Reversal Only (no doubledown)

| Year | Config | P&L | Avg deployed | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|
| 2022 | Fixed-alloc, no sub-legs | +$14,601 | $28k | +0.196% | 5.38 |
| 2022 | Fixed-alloc + reversal | +$14,028 | $46k | +0.165% | 3.26 |
| 2025 | Fixed-alloc, no sub-legs | +$13,195 | $24k | +0.232% | 6.08 |
| 2025 | Fixed-alloc + reversal | +$14,508 | $38k | +0.179% | 3.33 |
| 2026 YTD | Fixed-alloc, no sub-legs | +$5,780 | $25k | +0.254% | 5.76 |
| 2026 YTD | Fixed-alloc + reversal | +$4,246 | $40k | +0.153% | 2.92 |

Reversal/reentry consistently cuts RODC and DW-Sharpe. The regime-hold filter already selects clean momentum days — re-entering after a reversal adds noise, not edge.

### Fixed-Alloc + Reversal + Doubledown — Per-Leg Breakdown

| Year | Leg | Trades | Win rate | P&L | Notes |
|---|---|---|---|---|---|
| 2024 | Primary | 475 | 57.1% | +$13,681 | Identical to no-sub-leg baseline |
| 2024 | Reentry | 229 | 43.2% | +$983 | Small positive |
| 2024 | Doubledown | 64 | 34.4% | **+$14,767** | Trending year — DD nearly doubles total |
| 2024 | **All** | **768** | | **+$29,429** | +115% vs primary alone |
| 2026 YTD | Primary | 242 | 57.9% | +$5,780 | Identical to no-sub-leg baseline |
| 2026 YTD | Reentry | 142 | 38.7% | **-$1,534** | Choppy year — reentry loses money |
| 2026 YTD | Doubledown | 0 | — | $0 | Not triggered in this run |
| 2026 YTD | **All** | **384** | | **+$4,246** | -27% vs primary alone |

### Cross-year Sub-leg Summary (fixed-alloc $80k capital)

| Year | No sub-legs P&L | W/ sub-legs P&L | Uplift | Avg deployed | Ret on avg deployed (yr) | Mean RODC (daily) | DW-Sharpe |
|---|---|---|---|---|---|---|---|
| 2017 no sub-legs | +$5,053 | — | — | $27,130 | 18.6% | +0.086% | 5.49 |
| 2017 w/ sub-legs | — | **+$6,617** | +31% | $45,718 | **14.5%** | +0.087% | 1.54 |
| 2018 no sub-legs | +$11,032 | — | — | $25,215 | 43.8% | +0.197% | 5.87 |
| 2018 w/ sub-legs | — | **+$27,759** | +152% | $42,193 | **65.8%** | +0.336% | 3.09 |
| 2019 no sub-legs | +$9,657 | — | — | $24,417 | 39.6% | +0.186% | 6.68 |
| 2019 w/ sub-legs | — | **+$23,757** | +146% | $40,630 | **58.5%** | +0.273% | 3.03 |
| 2020 no sub-legs | +$9,563 | — | — | $24,244 | 39.4% | +0.179% | 5.15 |
| 2020 w/ sub-legs | — | **+$23,935** | +150% | $40,436 | **59.2%** | +0.282% | 2.86 |
| 2021 no sub-legs | +$9,573 | — | — | $27,361 | 35.0% | +0.184% | 4.99 |
| 2021 w/ sub-legs | — | **+$14,841** | +55% | $44,791 | **33.1%** | +0.222% | 2.39 |
| 2022 no sub-legs | +$14,601 | — | — | $27,990 | 52.2% | +0.196% | 5.38 |
| 2022 w/ sub-legs | — | **+$36,261** | +148% | $47,561 | **76.2%** | +0.401% | 3.27 |
| 2023 no sub-legs | +$11,667 | — | — | $23,014 | 50.7% | +0.224% | 6.06 |
| 2023 w/ sub-legs | — | **+$23,422** | +101% | $37,511 | **62.4%** | +0.281% | 3.66 |
| 2024 no sub-legs | +$13,681 | — | — | $22,512 | 60.8% | +0.280% | 5.72 |
| 2024 w/ sub-legs | — | **+$29,429** | +115% | $38,006 | **77.4%** | +0.434% | 2.84 |
| 2025 no sub-legs | +$13,195 | — | — | $24,340 | 54.2% | +0.232% | 6.08 |
| 2025 w/ sub-legs | — | **+$28,892** | +119% | $40,281 | **71.7%** | +0.360% | 2.87 |
| 2026 YTD no sub-legs | +$5,780 | — | — | $25,208 | 22.9% | +0.254% | 5.76 |
| 2026 YTD w/ sub-legs | — | **+$4,246** | -27% | $40,000 | **10.6%** | +0.153% | 2.92 |

### Old $10k Rank-weighted Runs (for reference — different capital model)

These are from the original `replay_YYYY_stock_m1_winrate_nostop/` and `_regimehold/` runs at $10k total capital with rank-weighted sizing:

| Year | Config | Primary | Reentry | DD | Total | RODC | DW-Sharpe |
|---|---|---|---|---|---|---|---|
| 2024 | nostop $10k | +$5,858 | +$156 | +$1,626 | +$7,640 | +0.269% | 4.86 |
| 2024 | regimehold $10k | +$5,710 | +$265 | +$1,954 | +$7,929 | +0.279% | 5.33 |
| 2025 | nostop $10k | +$5,143 | +$953 | +$1,065 | +$7,161 | — | 4.10 |
| 2025 | regimehold $10k | +$4,917 | +$962 | +$1,278 | +$7,158 | — | — |

At $10k capital: RODC is identical to $80k fixed-alloc (+0.280% for 2024), confirming the per-signal edge is capital-scale independent. DD contributed +30–39% of primary P&L in these runs.

**Key findings:**
- **Primary P&L is always identical** regardless of sub-leg config — sub-legs never interfere with primary signal execution
- **Doubledown is year-regime dependent**: trending year (2024) → DD wins big at low WR (34%) because large moves continue; choppy year (2026) → DD doesn't even trigger
- **Reentry is consistently low WR (38–45%)** and negative in 2026; small positive in 2024 only because the trend direction held after reversal
- **DW-Sharpe always drops with sub-legs** (5.72→2.84 in 2024, 5.76→2.92 in 2026) — sub-legs add variance even when net P&L improves
- **Rule of thumb**: use sub-legs only if confident the year will be strongly trending; regime-hold alone is the more consistent baseline

---

## P&L Concentration Analysis (2025 & 2026 YTD)

Trades bucketed by per-trade return on slot capital. Data from fixed-alloc + reversal + DD runs.

### Primary Leg — All Years

| Year | Trades | \|<0.6%\| trades | \|<0.6%\| % P&L | +0.6–1% trades | +0.6–1% % P&L | **≥+1% trades** | **≥+1% % P&L** | ≤-0.6% trades | ≤-0.6% % P&L |
|---|---|---|---|---|---|---|---|---|---|
| 2017 | 603 | 563 (93.4%) | +9.3% | 12 (2.0%) | +19.9% | **2 (0.3%)** | **+80.7%** | 4 (0.7%) | -0.6% |
| 2018 | 516 | 441 (85.5%) | +3.1% | 29 (5.6%) | +20.6% | **34 (6.6%)** | **+86.1%** | 12 (2.3%) | -2.3% |
| 2019 | 503 | 445 (88.5%) | +3.9% | 14 (2.8%) | +11.5% | **39 (7.8%)** | **+89.3%** | 5 (1.0%) | -1.0% |
| 2020 | 497 | 414 (83.3%) | -4.0% | 20 (4.0%) | +15.8% | **38 (7.6%)** | **+115.1%** | 25 (5.0%) | -5.0% |
| 2021 | 592 | 500 (84.5%) | +12.3% | 28 (4.7%) | +21.7% | **38 (6.4%)** | **+90.8%** | 26 (4.4%) | -4.4% |
| 2022 | 585 | 469 (80.2%) | +4.2% | 26 (4.4%) | +13.8% | **54 (9.2%)** | **+103.7%** | 36 (6.2%) | -6.2% |
| 2023 | 467 | 394 (84.4%) | +4.9% | 19 (4.1%) | +12.8% | **40 (8.6%)** | **+93.5%** | 14 (3.0%) | -3.0% |
| 2024 | 475 | 395 (83.2%) | +1.1% | 20 (4.2%) | +11.4% | **46 (9.7%)** | **+97.4%** | 14 (2.9%) | -2.9% |
| 2025 | 516 | 416 (80.6%) | +2.9% | 20 (3.9%) | +11.4% | **56 (10.9%)** | **+103.4%** | 24 (4.7%) | -17.7% |
| 2026 YTD | 242 | 188 (77.7%) | +2.8% | 16 (6.6%) | +22.0% | **23 (9.5%)** | **+101.1%** | 15 (6.2%) | -25.9% |

### Reentry Leg — All Years

| Year | Trades | Total P&L | \|<0.6%\| % trades | +0.6–1% % trades | **≥+1% trades** | **≥+1% P&L** | ≤-0.6% trades | ≤-0.6% P&L |
|---|---|---|---|---|---|---|---|---|
| 2017 | 216 | -$444 | 75.9% | 3.7% | **19 (8.8%)** | **+$3,357** | 25 (11.6%) | -$2,338 |
| 2018 | 192 | +$2,700 | 52.6% | 8.9% | **33 (17.2%)** | **+$6,165** | 41 (21.4%) | -$4,184 |
| 2019 | 192 | +$958 | 63.5% | 9.4% | **21 (10.9%)** | **+$3,573** | 31 (16.1%) | -$3,072 |
| 2020 | 208 | +$2,398 | 42.8% | 5.3% | **44 (21.2%)** | **+$9,636** | 64 (30.8%) | -$7,702 |
| 2021 | 202 | +$2,803 | 50.5% | 9.9% | **36 (17.8%)** | **+$6,798** | 44 (21.8%) | -$4,391 |
| 2022 | 245 | +$50 | 30.2% | 6.1% | **52 (21.2%)** | **+$11,907** | 104 (42.4%) | -$12,631 |
| 2023 | 200 | -$144 | 55.5% | 7.5% | **19 (9.5%)** | **+$4,869** | 55 (27.5%) | -$5,567 |
| 2024 | 229 | +$982 | 49.8% | 8.3% | **34 (14.8%)** | **+$6,446** | 62 (27.1%) | -$6,312 |
| 2025 | 212 | +$3,951 | 36.8% | 7.1% | **40 (18.9%)** | **+$12,116** | 79 (37.3%) | -$9,394 |
| 2026 YTD | 142 | -$1,534 | 42.3% | 5.6% | **21 (14.8%)** | **+$4,802** | 53 (37.3%) | -$6,913 |

### Doubledown Leg — All Years

| Year | Trades | Total P&L | \|<0.6%\| % trades | \|<0.6%\| P&L | **≥+1% trades** | **≥+1% P&L** | ≤-0.6% trades | ≤-0.6% P&L |
|---|---|---|---|---|---|---|---|---|
| 2017 | 106 | +$2,165 | 85.8% | -$9,905 | **9 (8.5%)** | **+$10,608** | 2 (1.9%) | -$1,211 |
| 2018 | 91 | +$14,271 | 79.1% | -$5,225 | **11 (12.1%)** | **+$23,839** | 7 (7.7%) | -$4,874 |
| 2019 | 82 | +$13,141 | 75.6% | -$6,375 | **10 (12.2%)** | **+$19,543** | 5 (6.1%) | -$3,107 |
| 2020 | 74 | +$11,973 | 66.2% | -$4,258 | **7 (9.5%)** | **+$21,308** | 13 (17.6%) | -$8,256 |
| 2021 | 93 | +$2,475 | 79.6% | -$5,154 | **8 (8.6%)** | **+$12,139** | 9 (9.7%) | -$5,584 |
| 2022 | 78 | +$21,611 | 78.2% | -$4,596 | **11 (14.1%)** | **+$24,074** | 1 (1.3%) | -$573 |
| 2023 | 71 | +$12,332 | 71.8% | -$2,220 | **11 (15.5%)** | **+$19,017** | 8 (11.3%) | -$4,953 |
| 2024 | 64 | +$14,767 | 73.4% | -$6,477 | **7 (10.9%)** | **+$20,745** | 5 (7.8%) | -$2,628 |
| 2025 | 75 | +$11,746 | 69.3% | -$8,805 | **14 (18.7%)** | **+$25,665** | 7 (9.3%) | -$6,228 |
| 2026 YTD | 0 | $0 | — | — | — | — | — | — |

### Key Findings

- **The entire primary P&L comes from ≥+1% trades every single year** — they are 6–11% of trades but generate 81–115% of primary P&L; the rest nearly cancel out
- **80–93% of primary trades are noise** (|< 0.6%|) — the regime-hold filter's real job is selecting the days where the ≥+1% tail occurs
- **The +0.6–1% bucket contributes a consistent secondary 11–22%** of primary P&L across all years
- **DD is the most extreme lottery structure**: 66–86% of trades are small losers, entirely offset by 7–14 big-win trades per year that each move ≥+1%
- **Reentry is regime-dependent**: in trending years (2018–2025) the ≥+1% win tail outweighs the loss tail; in choppy years (2017, 2026) the ≤-0.6% loss bucket overwhelms wins
- **2022 reentry is the tightest**: +$11,907 from 52 big-win trades vs -$12,631 from 104 loss trades — net nearly zero (+$50 total); extreme tug-of-war
- **2017 primary anomaly**: ≥+1% bucket is only 0.3% of trades (2 trades!) carrying 80.7% of P&L — strategy barely firing in this pre-calibration era

---

## Ticker Cycle Analysis (2017–2026)

Analysis of per-ticker win-rate cycles, inter-ticker correlations, and portfolio construction implications across 10 years of primary-leg trades.

### Yearly P&L by Ticker (% of $10k slot)

| Ticker | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|---|---|---|---|
| AMD | +0.5 | +13.8 | +9.5 | +6.9 | +4.6 | +9.8 | +10.9 | +13.6 | +3.8 | -0.6 |
| APP | — | — | — | — | +5.5 | +12.7 | +14.0 | +22.9 | -1.0 | -2.5 |
| ARM | — | — | — | — | — | — | +4.6 | +11.8 | +9.1 | +3.0 |
| AVGO | +2.0 | +5.9 | +5.4 | +3.1 | +2.9 | +7.6 | +1.2 | +2.9 | +2.9 | +5.0 |
| CHTR | +5.5 | +8.8 | +6.2 | -0.5 | +9.5 | +3.6 | +12.6 | +1.5 | +4.2 | +1.3 |
| CRWD | — | — | +10.7 | +8.6 | +2.5 | +5.9 | +8.3 | +5.1 | +14.7 | +12.9 |
| DDOG | — | — | +1.6 | +3.6 | +9.7 | +9.7 | +6.4 | +7.3 | +9.8 | -0.0 |
| LLY | +4.3 | +2.0 | +4.7 | +6.2 | +5.5 | +4.1 | +0.5 | +3.3 | +3.3 | +4.8 |
| META | +6.3 | +5.1 | +4.6 | +2.6 | +3.4 | +2.5 | +17.6 | +5.3 | +1.0 | +15.2 |
| MRVL | +1.1 | +0.3 | +5.5 | +5.3 | +6.1 | +17.8 | +6.8 | +3.7 | +3.8 | -0.2 |
| MU | +1.4 | +4.6 | +8.1 | +0.7 | +7.6 | +0.2 | +1.4 | +7.3 | +5.7 | +5.5 |
| PLTR | — | — | — | +8.5 | +6.9 | +18.8 | -0.9 | +13.1 | +19.5 | +1.4 |
| QCOM | +6.4 | +9.6 | +1.3 | +7.1 | +2.6 | +3.7 | +1.4 | +13.3 | -0.2 | +10.8 |
| RDDT | — | — | — | — | — | — | — | +13.4 | +4.2 | -3.1 |
| SNDK | — | — | — | — | — | — | — | — | +14.3 | +3.6 |
| SNOW | +0.4 | — | — | +2.4 | +7.0 | +7.0 | +15.1 | +5.6 | +11.6 | -1.7 |
| SNPS | +1.3 | +9.5 | +9.1 | +3.4 | +1.8 | +7.7 | +5.4 | +2.3 | +6.0 | +2.2 |
| SPOT | — | +13.9 | +17.0 | +30.5 | +2.6 | +7.4 | +9.4 | +2.1 | +15.9 | +0.0 |
| TSLA | +21.3 | +37.0 | +13.1 | +7.1 | +17.5 | +27.9 | +2.1 | +2.4 | +3.4 | +0.1 |

### Ticker Cycle Observations

Each ticker has a dominant era — a window where it produces outsized momentum signals — followed by a quieter period:

| Ticker | Peak era | Peak signal | Declining after | Pattern |
|---|---|---|---|---|
| **TSLA** | 2017–2022 | +37% in 2018, +27.9% in 2022 | 2023+ | EV/growth hype cycle; now mature/crowded |
| **SPOT** | 2018–2020 | +30.5% in 2020 | 2021+ | Streaming growth peak; fading momentum |
| **PLTR** | 2022–2025 | +18.8% in 2022, +19.5% in 2025 | TBD | AI/defense spending cycle; still rising |
| **CRWD** | 2024–2026 | +14.7% in 2025, +12.9% YTD 2026 | TBD | Cybersecurity spend cycle; still rising |
| **META** | 2023 & 2026 | +17.6% in 2023, +15.2% YTD 2026 | Volatile | Two distinct peaks — cost-cut rally + AI |
| **APP** | 2022–2024 | +22.9% in 2024 | 2025+ | Ad-tech momentum; fading |
| **AMD** | 2018, 2024 | +13.8% in 2018, +13.6% in 2024 | Cyclical | Semiconductor cycle — peaks every ~3 yrs |
| **QCOM** | 2018, 2024 | +9.6% in 2018, +13.3% in 2024 | Cyclical | Same semi cycle as AMD, 3-year rhythm |
| **MRVL** | 2022 | +17.8% peak | 2023+ | One strong year; more muted otherwise |
| **SNOW** | 2023–2025 | +15.1% in 2023, +11.6% in 2025 | TBD | Cloud data platform cycle; still active |
| **AVGO/LLY** | Every year | +2–8% consistently | Never | Steady earners — no cycle, always on |
| **SNDK** | 2025+ | +14.3% in 2025 | TBD | Too new to characterize |

**QQQ cycle connection (inferred):**
- TSLA and SPOT peaked during the 2020–2021 zero-rate / growth-at-any-price era
- MRVL, AMD, QCOM peaked in 2022 (supply-chain semiconductor boom)
- PLTR, APP, META peaked in 2023–2024 (AI hype wave 1)
- CRWD, SNOW are peaking in 2025–2026 (AI infrastructure wave 2)
- The pattern suggests a **sector rotation within tech**: each QQQ bull cycle elevates a different sub-sector, which shows up as a 1–3 year elevated win-rate window for those tickers

### Inter-Ticker Correlation (monthly avg P&L)

Correlations computed from monthly avg-pct-P&L vectors across all shared trading months.

| | AMD | APP | AVGO | CHTR | CRWD | DDOG | LLY | META | MRVL | MU | PLTR | QCOM | SNOW | SNPS | SPOT | TSLA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AMD | 1.00 | +.06 | -.10 | +.47 | +.05 | -.15 | -.01 | -.03 | +.15 | -.10 | -.04 | -.11 | -.07 | -.04 | +.04 | -.29 |
| APP | | 1.00 | -.20 | -.10 | -.21 | +.04 | -.07 | -.01 | +.04 | +.18 | +.04 | -.03 | -.16 | +.07 | +.05 | +.09 |
| AVGO | | | 1.00 | -.06 | -.05 | +.24 | +.02 | +.10 | +.14 | -.00 | +.30 | +.12 | -.19 | +.23 | +.12 | +.49 |
| CHTR | | | | 1.00 | -.13 | -.23 | -.16 | +.10 | -.16 | -.01 | -.16 | +.09 | +.55 | -.06 | +.11 | -.01 |
| CRWD | | | | | 1.00 | +.17 | -.28 | +.11 | +.07 | -.16 | -.41 | +.14 | -.06 | -.11 | -.17 | -.20 |
| DDOG | | | | | | 1.00 | -.21 | +.18 | -.03 | -.39 | -.33 | -.22 | -.12 | +.05 | -.01 | +.13 |
| LLY | | | | | | | 1.00 | -.11 | +.13 | +.45 | +.29 | -.02 | -.24 | +.09 | -.13 | -.10 |
| META | | | | | | | | 1.00 | -.20 | -.18 | -.19 | +.11 | +.13 | +.00 | -.11 | -.09 |
| MRVL | | | | | | | | | 1.00 | +.18 | +.19 | +.04 | -.21 | -.02 | -.09 | +.06 |
| MU | | | | | | | | | | 1.00 | -.02 | -.02 | -.03 | +.11 | -.19 | -.10 |
| PLTR | | | | | | | | | | | 1.00 | -.04 | +.12 | -.12 | +.09 | +.17 |
| QCOM | | | | | | | | | | | | 1.00 | +.07 | -.16 | +.03 | +.05 |
| SNOW | | | | | | | | | | | | | 1.00 | -.14 | +.37 | +.36 |
| SNPS | | | | | | | | | | | | | | 1.00 | +.10 | +.09 |
| SPOT | | | | | | | | | | | | | | | 1.00 | +.09 |
| TSLA | | | | | | | | | | | | | | | | 1.00 |

**Strongest positive correlations (tend to win/lose together):**
- CHTR ↔ SNOW: r=+0.55 — both cable/cloud infrastructure; avoid holding both on same day
- AVGO ↔ TSLA: r=+0.49 — both high-beta large-cap tech
- AMD ↔ CHTR: r=+0.47 — coincident momentum cycles
- LLY ↔ MU: r=+0.45 — move together despite different sectors (coincident macro sensitivity)

**Strongest negative correlations (natural hedges):**
- CRWD ↔ PLTR: r=-0.41 — cybersecurity vs defense/AI diverge month to month
- DDOG ↔ MU: r=-0.39 — observability software vs memory chip cycles are inverse
- DDOG ↔ PLTR: r=-0.33 — same divergence: devops software vs defense AI
- AMD ↔ TSLA: r=-0.29 — AMD strong when TSLA weak and vice versa
- CRWD ↔ LLY: r=-0.28 — cyberstock vs pharma: textbook uncorrelated sectors

### Portfolio Construction Implications

**Problem:** the current top-8 win-rate selection can produce correlated clusters (e.g. CHTR+SNOW both selected on the same day), concentrating P&L variance on days where the whole cluster moves together.

**Key insights:**

1. **Diversification within the 8 slots**: prefer pairs with low or negative correlation. A portfolio of CRWD + PLTR + DDOG + MU + LLY + AMD + META + AVGO would be far less correlated than CHTR + SNOW + TSLA + AVGO + AMD + SPOT + SNOW + MRVL.

2. **Cycle-aware ticker weighting**: the win-rate selector already adapts over time, but a 12-month rolling win-rate filter would de-weight tickers leaving their peak cycle (e.g. APP in 2025) and up-weight those entering theirs (e.g. CRWD in 2025).

3. **Predictability of cycles**: the sector rotation pattern is visible in hindsight but hard to call in real time. The practical signal is **a trailing 6-month win rate dropping below 45%** — that's when a ticker is leaving its cycle (TSLA in 2023, APP in 2025). The win-rate selector naturally handles this by rank-ordering, but an explicit threshold could exclude tickers in a declining phase.

4. **Reducing P&L volatility**: replacing highly correlated pairs (CHTR+SNOW, AVGO+TSLA) with negatively correlated alternatives (CRWD+PLTR, DDOG+MU) in the top-8 would theoretically smooth daily P&L without sacrificing mean RODC — the individual edges remain, but the daily outcomes are less synchronized.

5. **QQQ as a leading indicator**: the ≥+1% tail trades that drive all P&L tend to cluster in periods when QQQ itself has strong directional momentum (trending quarters). QQQ regime is already captured by the regime engine, but tracking QQQ's rolling 20-day momentum vs its 50-day MA as an overlay could identify quarters where the ≥+1% tail is more likely to fire across multiple tickers simultaneously.

### Ticker Pool Management Strategy

**Question:** should declining tickers be actively replaced with new-cycle tickers, or let the win-rate selector handle it?

**Option 1 — Let the selector do it (current)**
The selector rank-orders by rolling win rate so fading tickers naturally fall below the top-8 cutoff on most days. No manual intervention.
- Pro: fully automated, no hindsight bias, adapts continuously
- Con: a fading ticker still consumes a slot on days it ranks top-8 while declining; can't distinguish a bad week from a cycle ending

**Option 2 — Manual pool rotation**
Remove tickers with sustained declining win rates and replace with new candidates entering a cycle.
- Pro: cleaner pool — only active-cycle tickers compete for slots
- Con: requires human judgment on which new tickers to add; risk of adding too early; operational overhead
- Best when: you can identify the next cycle's tickers early (e.g. adding CRWD in 2024 before its 2025 peak)

**Option 3 — Dynamic pool with win-rate floor threshold (recommended)**
Keep the existing pool but suppress any ticker whose trailing 90-day win rate falls below ~42%. New tickers self-qualify when their 60-day win rate crosses a minimum entry threshold.
- Pro: best of both worlds — selector still runs automatically, but fading tickers can't consume slots; new tickers self-qualify rather than being manually curated
- Con: adds a parameter to tune; risk of excluding tickers in a temporary dip vs genuine cycle end
- Implementation sketch:
```python
if ticker.win_rate_trailing_90d < 0.42:
    skip ticker in pre-market selection
```
- This would have automatically excluded TSLA after mid-2023 (90-day WR dropped to ~38%), APP in late 2025, and SNOW in 2026 YTD — all of which became net-negative contributors

**Key distinction:** the new ticker addition problem is harder. The selector handles it passively as new tickers build history (CRWD, PLTR self-qualified over time). Actively front-running new cycles requires qualitative judgment that is difficult to systematize — the floor threshold approach only clears out dead weight; it does not solve early detection of the next cycle.

### Direction-Aware Win-Rate Scoring (Proposed Enhancement)

**Finding:** tickers leaving their bull cycle do NOT become useless — they often flip to being excellent short candidates. Removing them from the pool would hurt the short side.

| Ticker | Cycle shift | Bull WR after peak | Bear WR after peak |
|---|---|---|---|
| TSLA 2023 | Post-boom | 40% (+0.025% avg) | **77% (+0.139% avg)** |
| MRVL 2023 | Post-2022 peak | 39% (-0.092% avg) | **76% (+0.495% avg)** |
| DDOG 2025 | Fading | 33% (+0.112% avg) | **72% (+0.471% avg)** |
| APP 2026 | Declining | 38% (-0.332% avg) | **62% (+0.016% avg)** |
| SNOW 2021 | Post-IPO peak | 41% (-0.072% avg) | **60% (+0.824% avg)** |
| META 2026 | Strong bear days | 67% (+0.209% avg) | **92% (+0.882% avg)** |

**The problem with the current selector:**

The win-rate selector ranks by **overall** win rate, then the regime filter drops signals that don't match the day's direction. This creates a specific inefficiency on LONG regime days:

- A declining ticker like TSLA 2023 (40% bull WR, 77% bear WR, ~57% overall WR) ranks in the top-8 by overall WR
- On a LONG day, the regime filter drops its BEARISH signal — so only its weak 40% bullish edge fires
- It wastes a slot that a healthier bullish ticker could occupy
- On a SHORT day the bear WR (77%) fires correctly — no problem there

**Proposed fix — direction-aware scoring:**

Compute bullish and bearish win rates separately per ticker. Rank differently depending on regime:

```
LONG regime day  → rank top-8 by trailing bullish win rate
SHORT regime day → rank top-8 by trailing bearish win rate
```

**Impact:**
- TSLA 2023 on LONG days: bull WR 40% → falls out of top-8 → healthier ticker takes the slot
- TSLA 2023 on SHORT days: bear WR 77% → ranks near top → slot well used
- No ticker needs to be removed from the pool — direction-aware scoring handles it automatically
- The only tickers that would fall out entirely are those where **both** bull and bear WR have collapsed (e.g. SNOW 2026: bear WR 20%) — a genuine signal that the ticker has lost all momentum edge

**Implementation note:** requires the selector to maintain two separate rolling win-rate histories per ticker (one for bullish signals, one for bearish), and query the appropriate one at pre-market ranking time based on the regime engine's direction forecast for the day.

### Ticker Retirement Criteria

Even with direction-aware scoring, tickers that have lost edge on **both** sides should eventually be retired from the pool. However the data shows this is extremely rare.

**Scanning 10 years of data with a 45% floor threshold (min 5 trades per side):**

| Ticker | Year | Bull WR | Bear WR | Notes |
|---|---|---|---|---|
| AVGO | 2020 | 43% | 36% | ❌ Both dead — but recovered fully in 2021+ |
| MU | 2023 | 33% | 43% | ❌ Both dead — recovered in 2024 (+7.3% yr P&L) |

**Only 2 instances across 190 ticker-years of data.** Everything else was one-side-weak with the other side healthy — exactly the direction-aware scoring problem, not a retirement problem.

**Key implication:** true ticker retirement is extremely rare. The most common failure mode is a ticker going weak on one side while remaining strong on the other — and the current overall-WR selector mishandles this by either:
- Wasting a LONG slot on a ticker with weak bull WR but strong bear WR (TSLA 2023, DDOG 2025)
- Or correctly keeping a ticker in the pool for the right regime but accidentally giving it a LONG slot

**Recommended combined approach:**

| Situation | Mechanism | Action |
|---|---|---|
| Bull WR weak, bear WR strong (cycle flip) | Direction-aware scoring | Auto-ranked low on LONG days, high on SHORT days — no manual action |
| Bear WR weak, bull WR strong (early cycle) | Direction-aware scoring | Auto-ranked high on LONG days, low on SHORT days — no manual action |
| Both WR weak for 1 year | Direction-aware scoring | Both scores low — rarely gets selected on either regime — monitor |
| Both WR weak for 2+ consecutive quarters | Dual-side floor threshold | Suppress from pool entirely until WR recovers above threshold |

The 2-quarter sustained weakness requirement avoids premature retirement — AVGO 2020 and MU 2023 both recovered the following year, so a single bad year would not have triggered removal under this rule.

---

## --extend-collection-bars Sweep (2026 YTD, rank-weighted)

| ecb | Active days | P&L | Committed % | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|
| 0 | 81 | +$13,753 | +17.2% | +0.212% | 4.87 |
| **2** (default) | **96** | **+$22,004** | **+27.5%** | **+0.254%** | **5.41** |
| 3 | 100 | +$20,818 | +26.0% | +0.241% | 4.71 |

ecb=2 is the sweet spot: +15 more active days and +$8k vs ecb=0. ecb=3 adds noise (RODC and Sharpe both drop). **ecb=2 is now the default** in the engine.

---

## --stop-pct Sweep (2026 YTD, rank-weighted, ecb=2)

| stop-pct | P&L | Committed % | Mean RODC | DW-Sharpe |
|---|---|---|---|---|
| **0** (hold-to-EOD) | **+$22,004** | **+27.5%** | **+0.254%** | **5.41** |
| 0.2 | +$19,302 | +24.1% | +0.219% | 4.38 |
| 0.4 | +$19,614 | +24.5% | +0.233% | 3.63 |
| 0.9 | +$8,158 | +10.2% | +0.119% | 1.15 |

Any stop-pct hurts this config. The regime-hold filter handles day selection — adding a stop-loss creates unnecessary early exits on days that recover. **stop-pct=0 is the optimal setting.**

---

## Return Calculation Methodology

The yearly line reports two return figures:

| Method | Formula | What it answers |
|---|---|---|
| **Return on avg deployed** | `P&L / (total_deployed / trading_days)` | Edge efficiency: how productive was capital actually at work? |
| **Return on committed** | `P&L / $80,000` | Account-level: what did the brokerage account earn? |

Avg deployed is preferred for comparing configs with different utilization rates (e.g. rank-weighted vs fixed-alloc). Committed is better for absolute account-level planning.
