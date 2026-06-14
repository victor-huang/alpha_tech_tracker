# SPY High-Beta Candidate Set — 5-Year Backtest Results

**Tickers**: `GNRC TER AMAT BLDR APA CIEN TPL SLB LYB CAT INTC TGT`

**Parameters**: `--regime-filter --regime-ma 8 --weights 50 30 20 --stop-pct 0.15 --trailing-ma ma20`
**Windows**: `--window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 60 40`

Log files: `spy_highbeta_multiwindow_2021.log` … `spy_highbeta_multiwindow_2026_ytd.log`
30d / 90d logs: `spy_highbeta_multiwindow_30d.log`, `spy_highbeta_multiwindow_90d.log`

---

## Candidate Selection Rationale

Drawn from the S&P 500 index; filtered to remove tickers already tested in V2 pool, pre-2020 set, post-2020 set, and NDX high-beta set. Ranked by estimated beta; HIMS replaced by TGT due to narrative collapse risk (FDA GLP-1 ruling).

| Ticker | Beta (est.) | Sector | Theme |
|--------|------------|--------|-------|
| GNRC | ~1.8 | Power equipment | Energy transition / backup power; high cyclical ATR |
| TER | ~1.65 | Semiconductor test | AI chip test demand; same capex cycle as LRCX |
| AMAT | ~1.55 | Semiconductor equipment | AI wafer fab capex; direct LRCX/KLAC peer |
| BLDR | ~1.55 | Construction materials | Housing cycle; high intraday range |
| APA | ~1.50 | E&P oil | Higher-beta energy; regime-sensitive |
| CIEN | ~1.40 | Optical networking | AI data center interconnects |
| TPL | ~1.35 | Land royalties | Texas oil/gas royalties; volatile |
| SLB | ~1.30 | Oil services | Energy capex cycle |
| LYB | ~1.25 | Chemicals | Cyclical; moderate ATR |
| CAT | ~1.20 | Construction/mining equipment | AI data center infrastructure |
| INTC | ~1.15 | Semiconductors | High realized vol; turnaround narrative |
| TGT | ~1.10 | Retail | Consumer cycle; moderate ATR |

---

## Year-by-Year Summary

| Year | Strategy | QQQ B&H | Alpha | Picks | WR |
|------|----------|---------|-------|-------|----|
| 2021 | **+81.13%** | +28.50% | **+52.63pp** | 2474 | 26% |
| 2022 | **+96.96%** | -33.68% | **+130.64pp** | 2224 | 28% |
| 2023 | **+68.85%** | +54.81% | **+14.04pp** | 2419 | 27% |
| 2024 | **+94.17%** | +26.98% | **+67.19pp** | 2502 | 26% |
| 2025 | **+59.98%** | +20.36% | **+39.62pp** | 1654 | 26% |
| 2026 YTD | **+25.73%** | -8.25% | **+33.98pp** | 459 | 29% |

**Positive alpha every year. No losing years vs QQQ.**
**No negative calendar months across 2021–2024.**
**2025 picks start May (regime filter blocks Jan–Apr).**

---

## Monthly Breakdowns

### 2021 (+81.13% vs QQQ +28.50%)

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +5.96% | +1.67% | +4.29pp |
| Feb | +6.10% | +0.10% | +6.00pp |
| Mar | +10.24% | +1.34% | +8.90pp |
| Apr | +8.54% | +6.09% | +2.45pp |
| May | +5.09% | -1.35% | +6.44pp |
| Jun | +5.58% | +6.73% | -1.15pp |
| Jul | +2.91% | +3.24% | -0.33pp |
| Aug | +6.46% | +4.96% | +1.50pp |
| Sep | +11.47% | -7.03% | +18.50pp |
| Oct | +5.62% | +9.04% | -3.42pp |
| Nov | +4.68% | +2.51% | +2.17pp |
| Dec | +8.48% | +1.21% | +7.27pp |
| **TOTAL** | **+81.13%** | **+28.50%** | **+52.63pp** |

### 2022 (+96.96% vs QQQ -33.68%)

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +6.13% | -9.59% | +15.72pp |
| Feb | +6.41% | -4.02% | +10.43pp |
| Mar | +10.11% | +3.74% | +6.37pp |
| Apr | +14.86% | -12.10% | +26.96pp |
| May | +9.69% | -1.22% | +10.91pp |
| Jun | +10.60% | -7.01% | +17.61pp |
| Jul | +3.00% | +8.70% | -5.70pp |
| Aug | +5.03% | -3.99% | +9.02pp |
| Sep | +3.92% | -7.90% | +11.82pp |
| Oct | +6.44% | +2.57% | +3.87pp |
| Nov | +9.68% | +3.87% | +5.81pp |
| Dec | +11.10% | -6.74% | +17.84pp |
| **TOTAL** | **+96.96%** | **-33.68%** | **+130.64pp** |

### 2023 (+68.85% vs QQQ +54.81%)

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +2.01% | +11.41% | -9.40pp |
| Feb | +3.32% | -0.42% | +3.74pp |
| Mar | +5.69% | +10.31% | -4.62pp |
| Apr | +0.84% | +0.67% | +0.17pp |
| May | +9.33% | +9.44% | -0.11pp |
| Jun | +6.72% | +8.30% | -1.58pp |
| Jul | +5.37% | +5.40% | -0.03pp |
| Aug | +8.52% | -2.23% | +10.75pp |
| Sep | +8.33% | -7.38% | +15.71pp |
| Oct | +6.52% | -2.80% | +9.32pp |
| Nov | +7.34% | +14.35% | -7.01pp |
| Dec | +4.86% | +7.76% | -2.90pp |
| **TOTAL** | **+68.85%** | **+54.81%** | **+14.04pp** |

### 2024 (+94.17% vs QQQ +26.98%)

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +3.38% | +3.56% | -0.18pp |
| Feb | +2.33% | +5.50% | -3.17pp |
| Mar | +8.50% | +1.24% | +7.26pp |
| Apr | +7.22% | -4.83% | +12.05pp |
| May | +6.48% | +6.70% | -0.22pp |
| Jun | +11.70% | +6.82% | +4.88pp |
| Jul | +4.98% | -2.00% | +6.98pp |
| Aug | +1.56% | +1.35% | +0.21pp |
| Sep | +8.86% | +2.86% | +6.00pp |
| Oct | +8.04% | -1.02% | +9.06pp |
| Nov | +6.35% | +6.43% | -0.08pp |
| Dec | **+24.78%** | +0.37% | **+24.41pp** |
| **TOTAL** | **+94.17%** | **+26.98%** | **+67.19pp** |

> **Dec 2024 +24.78% in one month** — AMAT, TER, GNRC, CIEN all had strong moves; semiconductor equipment + AI data center infrastructure narrative peaked.

### 2025 (+59.98% vs QQQ +20.36%)

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan–Apr | — (0 picks) | -6.27% combined | — |
| May | +2.87% | +8.62% | -5.75pp |
| Jun | +6.62% | +6.35% | +0.27pp |
| Jul | +9.26% | +2.63% | +6.63pp |
| Aug | +4.01% | +1.04% | +2.97pp |
| Sep | +7.15% | +5.88% | +1.27pp |
| Oct | +8.33% | +5.29% | +3.04pp |
| Nov | +10.41% | -1.99% | +12.40pp |
| Dec | +11.33% | -0.95% | +12.28pp |
| **TOTAL** | **+59.98%** | **+20.36%** | **+39.62pp** |

### 2026 YTD (+25.73% vs QQQ -8.25%)

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +12.46% | +1.41% | +11.05pp |
| Feb | +9.22% | -2.34% | +11.56pp |
| Mar | +4.05% | -7.31% | +11.36pp |
| **TOTAL** | **+25.73%** | **-8.25%** | **+33.98pp** |

---

## Cross-Set 5-Year Comparison (All Multi-Window)

| Year | NDX High-Beta | SPY High-Beta | Pre-2020 | QQQ |
|------|---------------|---------------|----------|-----|
| 2021 | +81.33% | +81.13% | +104.14% | +28.50% |
| 2022 | **+137.75%** | +96.96% | +126.99% | -33.68% |
| 2023 | +96.48% | +68.85% | +103.62% | +54.81% |
| 2024 | **+99.76%** | +94.17% | +84.69% | +26.98% |
| 2025 | **+76.72%** | +59.98% | +57.76% | +20.36% |
| 2026 YTD | +26.78% | +25.73% | +27.62% | -8.25% |

All three candidate sets beat QQQ every year. NDX high-beta leads in 3 of 5 full years. SPY high-beta and pre-2020 are close in 2025 and 2026 YTD.

---

## Key Findings

### 1. Positive Alpha Every Year, No Negative Calendar Months

Like the NDX high-beta set, this pool has no losing calendar months across 2021–2024. Every month from Jan 2021 through Dec 2024 was positive for the strategy. 2025 had zero picks Jan–Apr (regime filter), then every active month positive.

### 2. 2022 Bear Year: +96.96% vs QQQ -33.68%

Second-best bear market performance after NDX high-beta (+137.75%). Every month positive in 2022. Apr (+14.86%), Dec (+11.10%), Jun (+10.60%), and Mar (+10.11%) were the top months. The SPY high-beta pool has more diversified sector exposure (energy, construction, chemicals) — the breadth of bearish signals across sectors drove consistent monthly returns.

### 3. Dec 2024 Outlier: +24.78% in One Month

Similar in magnitude to NDX's Aug 2024 (+25.86%). AMAT, TER, and CIEN drove outsized moves during the December 2024 semiconductor and AI data center infrastructure momentum peak. One month contributing ~25% of the annual return highlights concentration risk but also confirms the strategy's ability to capture momentum explosions.

### 4. 2023 Weakest Relative Year (+14pp alpha)

The SPY set's +68.85% was the weakest alpha vs QQQ (+54.81%) of any year at +14pp. Jan (-9.4pp vs QQQ), Mar (-4.6pp), and Nov (-7.0pp) dragged. These were months when QQQ had sharp gap-up rallies that the OR strategy missed. Still positive overall for the year.

### 5. AMAT Is the Strongest Individual Contributor

AMAT (Applied Materials) appears across the strongest monthly returns and is the most direct analog to LRCX/KLAC already in the NDX set. Its semiconductor equipment narrative is durable (AI wafer fab investment), beta ~1.55, and it shows up as a top-3 pick consistently across multiple years. **AMAT is the clearest add-to-pool candidate from this set.**

### 6. M1 Leads in This Pool (vs NDX Where M2 Led)

In 90-day and most annual tests, M1 (15-min OR) has higher EV/trade and WR than M2 (1-bar) for this pool. SPY-listed names with lower beta tend to form cleaner 15-min opening ranges than high-beta NDX semis. M2 adds return but at lower EV efficiency here.

---

## Ticker Recommendations

| Ticker | Verdict | Rationale |
|--------|---------|-----------|
| **AMAT** | **Add** | LRCX/KLAC peer; AI wafer fab capex; consistent across all years |
| **TER** | **Add (screen)** | Semiconductor test equipment; same capex cycle; run 30d/90d individual screen |
| **GNRC** | **Add (screen)** | High beta ~1.8; energy transition narrative; run individual screen |
| **CIEN** | **Watch** | Optical networking AI infra; contributed to Dec 2024 outlier |
| **BLDR** | **Watch** | Housing cycle; good ATR but narrative less durable than AI/semis |
| **APA** | **Watch** | E&P oil; regime-sensitive; works in energy bull markets |
| **CAT** | **Watch** | AI data center infrastructure angle; lower ATR but consistent |
| **TPL** | **Watch** | High volatility land royalties; useful in energy regimes |
| **SLB** | **Skip** | Oil services; narrative too dependent on energy cycle |
| **LYB** | **Skip** | Chemicals; insufficient directional narrative for OR strategy |
| **INTC** | **Skip** | Declining market share; turnaround narrative unreliable |
| **TGT** | **Skip** | Retail; low beta in practice; mean-reverting tendency |

**Priority addition**: AMAT — run individual `op_momentum_backtest.py` 30d/90d screen before adding to V2.

---

## Next Steps

- [ ] Run individual `op_momentum_backtest.py` on AMAT, TER, GNRC for 30d + 90d EV/WR breakdown
- [ ] Test adding AMAT to V2 pool alongside LRCX/MRVL from NDX set
- [ ] Consider "semiconductor equipment cluster" test: V2 + {LRCX, MRVL, AMAT, TER} — 4 names covering equipment, ASICs, and test
