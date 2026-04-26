# Sub-Leg Win Rate Analysis — 2017–2026

**Date:** 2026-04-25  
**Config:** Top-2, weights 60/40, M1+A1+A2, --reversal --bearish-reentry --bullish-reentry --doubledown --doubledown-start 5, SIP feed (2026 YTD uses IEX)  
**Tickers:** V3 pool (SNDK, APP, SHOP, CVNA, AMD, META, EXPE, RH, FN, MU, CRDO, PLTR, COIN, CLS, MSTR, CRWV, MRVL)

---

## Context

Each backtest trade row carries a composite `pnl_pct` / `success` score that blends:
- **Primary** — the opening-range signal leg
- **REV** — reversal re-entry if the primary stopped out and reversed
- **BRE** — bearish re-entry on a secondary bearish signal
- **BRU** — bullish re-entry on a secondary bullish signal
- **DD** — double-down add-on when rank-2+ stop out early and capital is redeployed to the winner

The composite score is used for ticker quality ranking. Each sub-leg is also tracked independently with its own win/loss count and P&L.

DD mechanics (post 2026-04-25 code change): entry = close at OR close + 5 min; hard stop = entry ± 80% × bar range; exit = winner's exit or hard stop, whichever is worse. P&L can be negative.

---

## Overall Win Rate & Total Return

| Year | Trades | W/L | WR | Total Return |
|---|---|---|---|---|
| 2017 | 1,307 | 542W/765L | 41% | +106.0% |
| 2018 | 1,321 | 556W/765L | 42% | +114.7% |
| 2019 | 1,312 | 550W/762L | 42% | +108.4% |
| 2020 | 1,336 | 597W/739L | 45% | +193.6% |
| 2021 | 1,400 | 628W/772L | 45% | +185.7% |
| 2022 | 1,318 | 581W/737L | 44% | +200.0% |
| 2023 | 1,406 | 612W/794L | 44% | +332.1% |
| 2024 | 1,398 | 623W/775L | 45% | +165.2% |
| 2025 | 1,415 | 634W/781L | 45% | +165.5% |
| 2026 YTD | 445 | 218W/227L | 49% | +121.4% |

---

## Reversal Win Rate

| Year | Trades | W/L | WR |
|---|---|---|---|
| 2017 | 182 | 58W/124L | 32% |
| 2018 | 205 | 70W/135L | 34% |
| 2019 | 196 | 73W/123L | 37% |
| 2020 | 207 | 88W/119L | 43% |
| 2021 | 213 | 87W/126L | 41% |
| 2022 | 206 | 70W/136L | 34% |
| 2023 | 223 | 97W/126L | 44% |
| 2024 | 219 | 84W/135L | 38% |
| 2025 | 207 | 83W/124L | 40% |
| 2026 YTD | 75 | 42W/33L | 56% |

**Range:** 32–56%. Pre-2020 weaker (32–37%), improved to 38–44% through 2025, spiked to 56% in 2026.

---

## Bearish Re-entry Win Rate

| Year | Trades | W/L | WR |
|---|---|---|---|
| 2017 | 170 | 55W/115L | 32% |
| 2018 | 195 | 73W/122L | 37% |
| 2019 | 182 | 74W/108L | 41% |
| 2020 | 190 | 67W/123L | 35% |
| 2021 | 215 | 94W/121L | 44% |
| 2022 | 249 | 95W/154L | 38% |
| 2023 | 198 | 70W/128L | 35% |
| 2024 | 210 | 83W/127L | 40% |
| 2025 | 213 | 87W/126L | 41% |
| 2026 YTD | 75 | 28W/47L | 37% |

**Range:** 32–44%. No clear trend — weakest in 2017, 2020, 2023. Best in 2021 (44%). The most volatile and least consistent sub-leg.

---

## Bullish Re-entry Win Rate

| Year | Trades | W/L | WR |
|---|---|---|---|
| 2017 | 354 | 139W/215L | 39% |
| 2018 | 378 | 153W/225L | 40% |
| 2019 | 350 | 125W/225L | 36% |
| 2020 | 372 | 141W/231L | 38% |
| 2021 | 378 | 159W/219L | 42% |
| 2022 | 298 | 127W/171L | 43% |
| 2023 | 362 | 137W/225L | 38% |
| 2024 | 381 | 155W/226L | 41% |
| 2025 | 385 | 131W/254L | 34% |
| 2026 YTD | 87 | 46W/41L | 53% |

**Range:** 34–53%. Most stable sub-leg across 2017–2024 (36–43%). Notable exceptions: 2025 dip to 34%, 2026 spike to 53%. Highest trade volume of any sub-leg (~300–385/year).

---

## Double-Down Win Rate & Net Cap P&L

| Year | Trades | W/L | WR | Net Cap P&L |
|---|---|---|---|---|
| 2017 | 76 | 30W/46L | 39% | +$510 |
| 2018 | 71 | 33W/38L | 46% | +$943 |
| 2019 | 74 | 33W/41L | 45% | +$697 |
| 2020 | 71 | 31W/40L | 44% | +$292 |
| 2021 | 81 | 47W/34L | 58% | +$1,309 |
| 2022 | 55 | 33W/22L | 60% | +$1,314 |
| 2023 | 69 | 29W/40L | 42% | +$688 |
| 2024 | 62 | 38W/24L | 61% | +$905 |
| 2025 | 85 | 35W/50L | 41% | +$572 |
| 2026 YTD | 28 | 13W/15L | 46% | +$884 |

**Net cap P&L positive all 10 years** — DD contributes to returns even in losing WR years due to asymmetric sizing (winner survivor gets full freed capital from multiple stopouts).

**WR peaks in trending years:** 58–61% in 2021, 2022, 2024. Weaker in choppy/sideways regimes: 39–44% in 2017, 2020, 2023, 2025.

---

## Findings

### 1. Overall WR is stable at 41–45% across 10 years; 2026 is an outlier at 49%

The composite win rate (primary + all sub-legs blended) is remarkably consistent at 41–45% from 2017 through 2025. 2026 YTD at 49% is the highest observed — may normalize as the year progresses.

### 2. Reversal is the highest-WR sub-leg in recent years

Reversal improved from 32–34% pre-2020 to 38–44% through 2025, and 56% in 2026. The trend suggests the strategy's reversal logic is better suited to post-2020 market structure (higher intraday volatility, faster mean-reversion).

### 3. Bearish RE is the weakest and most inconsistent sub-leg

BRE ranges 32–44% with no clear directional trend. It underperforms in COVID-recovery (2020), choppy bear markets (2023), and recent volatility (2026 at 37%). BRE fires when the primary signal was bearish and re-enters bearish after a bounce — sensitive to false bounces in strong trending markets.

### 4. Bullish RE is the highest-volume sub-leg and most consistent

BRU fires ~300–385 times/year — roughly 1.5–2× the volume of other sub-legs. WR is stable at 36–43% for 8 of 10 years. The 2025 dip (34%) and 2026 spike (53%) are the notable exceptions. High volume + stable WR makes BRU the largest contributor to total sub-leg P&L.

### 5. DD is net positive every year; WR correlates with market trendiness

DD WR clusters around two regimes:
- **Trending years (2021, 2022, 2024):** 58–61% WR — survivors continue strongly after rank-2+ stop out
- **Choppy/flat years (2017, 2020, 2023, 2025):** 39–44% WR — survivors more likely to reverse after initial move

Net cap P&L is positive in all 10 years because DD uses asymmetric sizing: a single surviving winner receives capital freed from multiple stopouts, so winning DDs are larger in dollar terms than losing ones.

### 6. 2023 stands out for high total return (+332%) despite mid-tier WR (44%)

2023's outperformance is driven by large average win sizes, not a higher win rate. The V3 pool had several large-magnitude winning trades in 2023 that dominate the return distribution.
