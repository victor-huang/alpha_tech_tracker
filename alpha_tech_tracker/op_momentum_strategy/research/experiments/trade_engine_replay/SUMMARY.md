# Trade Engine Replay Summary

**Period:** 2026-01-02 to 2026-04-02 (63 trading days)

**Parameters:**
```
--regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1
--morning-split 100 --bearish-reentry --bullish-reentry --reversal --mock-trade-execution
--top 2 --capital 10000
```

**Notes:**
- Stock trades use direct equity positions; options trades use weekly ITM contracts via MockContractSelector.
- Capital recycles sequentially: M1 → A1 → A2. Starting cap per day = $10,000 (no-compound mode).
- `cap %` = cap_pnl / $10,000 (daily return on starting capital).
- 2026-03-19: zero trades fired (regime filter + no qualifying signals across all windows).
- 2026-01-14 options: replay crashed on cache read; P&L recorded as $0.00.

---

## 1. Daily Results — Stock

| Date | Picks | Cap P&L | Cap % | # Trades | Best Trade |
|------|-------|---------|-------|----------|------------|
| 2026-01-02 | APP, ANAB | +$167.32 | +1.67% | 10 | APP +$297.88 (+4.17%) [trailing_stop_ma20] |
| 2026-01-05 | SNDK, FN | +$93.06 | +0.93% | 9 | FN +$83.68 (+2.24%) [trailing_stop_ma20] |
| 2026-01-06 | SNDK, APP | +$629.93 | +6.30% | 9 | SNDK +$175.77 (+6.16%) [trailing_stop_ma20] |
| 2026-01-07 | RH, SNDK | +$54.27 | +0.54% | 8 | RH +$69.72 (+1.19%) [trailing_stop_ma20] |
| 2026-01-08 | SNDK, RH | +$753.51 | +7.54% | 8 | RH +$298.76 (+5.10%) [trailing_stop_ma20] |
| 2026-01-09 | SNDK, CVNA | -$4.62 | -0.05% | 9 | RH +$55.76 (+0.95%) [end_of_day] |
| 2026-01-12 | SNDK, ANAB | -$19.28 | -0.19% | 7 | SNDK +$4.16 (+0.13%) [fallback_20pct] |
| 2026-01-13 | SNDK, ANAB | -$51.26 | -0.51% | 9 | SHOP +$27.36 (+0.43%) [end_of_day] |
| 2026-01-14 | APP, PLTR | +$315.78 | +3.16% | 5 | APP +$387.09 (+5.50%) [trailing_stop_ma20] |
| 2026-01-15 | ANAB, FANG | +$279.33 | +2.79% | 8 | ANAB +$197.34 (+5.17%) [end_of_day] |
| 2026-01-16 | APP, SHOP | +$171.63 | +1.72% | 5 | APP +$113.19 (+1.72%) [trailing_stop_ma20] |
| 2026-01-20 | FN, CVNA | -$31.30 | -0.31% | 9 | AMD +$63.40 (+1.35%) [trailing_stop_ma20] |
| 2026-01-21 | APP | +$11.53 | +0.12% | 5 | AMD +$32.60 (+0.66%) [trailing_stop_ma20] |
| 2026-01-22 | SNDK, MU | +$58.41 | +0.58% | 11 | SNDK +$41.09 (+1.18%) [end_of_day] |
| 2026-01-23 | ANAB, COIN | -$18.47 | -0.18% | 9 | RH +$38.48 (+0.65%) [end_of_day] |
| 2026-01-26 | ANAB, APP | +$65.88 | +0.66% | 8 | RH +$46.44 (+0.77%) [trailing_stop_ma20] |
| 2026-01-27 | RH, CVNA | +$67.20 | +0.67% | 11 | RH +$90.30 (+1.54%) [trailing_stop_ma20] |
| 2026-01-28 | SNDK, CVNA | -$66.17 | -0.66% | 8 | MU +$6.49 (+0.14%) [end_of_day] |
| 2026-01-29 | SNDK, PLTR | -$14.77 | -0.15% | 9 | PLTR +$46.20 (+1.02%) [trailing_stop_ma20] |
| 2026-01-30 | ANAB, SHOP | +$285.74 | +2.86% | 7 | SHOP +$278.16 (+5.28%) [end_of_day] |
| 2026-02-02 | RH | -$22.48 | -0.22% | 6 | CVNA -$0.84 (-0.03%) [fallback_20pct] |
| 2026-02-03 | SHOP, APP | +$462.57 | +4.63% | 10 | SHOP +$309.32 (+6.41%) [trailing_stop_ma20] |
| 2026-02-04 | PLTR, APP | +$587.52 | +5.88% | 8 | PLTR +$315.90 (+7.08%) [trailing_stop_ma20] |
| 2026-02-05 | PLTR, APP | +$184.28 | +1.84% | 6 | COIN +$105.04 (+2.69%) [end_of_day] |
| 2026-02-06 | META | +$0.54 | +0.01% | 6 | APP +$11.95 (+0.59%) [end_of_day] |
| 2026-02-09 | FANG | +$31.14 | +0.31% | 8 | APP +$37.29 (+0.73%) [end_of_day] |
| 2026-02-10 | SNDK, FN | -$20.93 | -0.21% | 7 | SHOP +$28.88 (+0.60%) [trailing_stop_ma20] |
| 2026-02-11 | SHOP, SNDK | +$519.82 | +5.20% | 8 | SHOP +$429.40 (+9.16%) [trailing_stop_ma20] |
| 2026-02-12 | SHOP, CVNA | +$570.77 | +5.71% | 8 | CVNA +$360.78 (+7.11%) [trailing_stop_ma20] |
| 2026-02-13 | FANG | +$188.02 | +1.88% | 7 | ANAB +$141.18 (+3.30%) [end_of_day] |
| 2026-02-17 | COIN, RH | +$156.38 | +1.56% | 9 | SNDK +$90.65 (+2.14%) [end_of_day] |
| 2026-02-18 | COIN, RH | +$228.93 | +2.29% | 4 | FN +$122.48 (+2.94%) [end_of_day] |
| 2026-02-19 | — | +$204.38 | +2.04% | 5 | CVNA +$193.48 (+4.33%) [end_of_day] |
| 2026-02-20 | SHOP, SNDK | +$265.74 | +2.66% | 10 | SHOP +$212.42 (+4.51%) [trailing_stop_ma20] |
| 2026-02-23 | SHOP, APP | -$54.19 | -0.54% | 8 | SHOP +$36.67 (+0.81%) [trailing_stop_ma20] |
| 2026-02-24 | ANAB, FN | -$61.44 | -0.61% | 9 | FN +$33.04 (+0.79%) [trailing_stop_ma20] |
| 2026-02-25 | SHOP, FN | +$157.47 | +1.57% | 6 | FN +$77.42 (+1.79%) [trailing_stop_ma20] |
| 2026-02-26 | SHOP, FN | +$195.53 | +1.96% | 9 | FN +$139.72 (+3.32%) [trailing_stop_ma20] |
| 2026-02-27 | SHOP, FN | +$103.15 | +1.03% | 9 | PLTR +$61.69 (+1.47%) [end_of_day] |
| 2026-03-02 | SNDK, COIN | +$120.62 | +1.21% | 9 | FN +$67.62 (+1.69%) [end_of_day] |
| 2026-03-03 | COIN, FN | -$70.01 | -0.70% | 8 | MU -$0.60 (-0.01%) [fallback_20pct] |
| 2026-03-04 | SHOP, RH | +$448.64 | +4.49% | 8 | APP +$187.44 (+3.66%) [end_of_day] |
| 2026-03-05 | SHOP, EXPE | +$114.47 | +1.14% | 8 | FN +$124.52 (+2.94%) [end_of_day] |
| 2026-03-06 | EXPE, SHOP | +$544.75 | +5.45% | 6 | FN +$242.72 (+5.84%) [end_of_day] |
| 2026-03-09 | EXPE, RH | +$565.90 | +5.66% | 10 | RH +$232.73 (+4.65%) [end_of_day] |
| 2026-03-10 | COIN, SHOP | -$151.66 | -1.52% | 9 | SNDK -$2.28 (-0.06%) [fallback_20pct] |
| 2026-03-11 | ANAB, CVNA | +$98.15 | +0.98% | 12 | ANAB +$140.01 (+2.85%) [trailing_stop_ma20] |
| 2026-03-12 | NVDA | +$13.92 | +0.14% | 6 | NVDA +$27.25 (+0.59%) [trailing_stop_ma20] |
| 2026-03-13 | NVDA | -$5.98 | -0.06% | 3 | FN -$0.16 (-0.00%) [fallback_20pct] |
| 2026-03-16 | — | -$49.51 | -0.50% | 7 | FN +$7.84 (+0.19%) [trailing_stop_ma20] |
| 2026-03-17 | SHOP, EXPE | +$97.03 | +0.97% | 9 | MU +$47.30 (+0.94%) [end_of_day] |
| 2026-03-18 | ANAB | -$31.13 | -0.31% | 7 | ANAB +$31.96 (+0.64%) [trailing_stop_ma20] |
| 2026-03-19 | ANAB | +$0.00 | +0.00% | 0 | no trades |
| 2026-03-20 | SHOP, PLTR | +$22.71 | +0.23% | 8 | PLTR +$31.80 (+0.69%) [trailing_stop_ma20] |
| 2026-03-23 | SHOP, PLTR | +$206.25 | +2.06% | 7 | COIN +$68.38 (+1.32%) [trailing_stop_ma20] |
| 2026-03-24 | COIN, PLTR | +$532.41 | +5.32% | 6 | COIN +$458.38 (+8.90%) [trailing_stop_ma20] |
| 2026-03-25 | COIN, PLTR | -$29.36 | -0.29% | 8 | FN +$13.58 (+0.31%) [trailing_stop_ma20] |
| 2026-03-26 | EXPE, AMD | +$174.90 | +1.75% | 7 | AMD +$172.80 (+3.98%) [trailing_stop_ma20] |
| 2026-03-27 | COIN, SHOP | +$104.73 | +1.05% | 7 | COIN +$68.64 (+1.61%) [trailing_stop_ma20] |
| 2026-03-30 | FN, CVNA | +$398.56 | +3.99% | 8 | CVNA +$236.88 (+5.68%) [trailing_stop_ma20] |
| 2026-03-31 | SHOP, FANG | +$0.96 | +0.01% | 10 | FN +$55.12 (+1.34%) [end_of_day] |
| 2026-04-01 | CVNA, COIN | -$80.99 | -0.81% | 9 | PLTR +$0.15 (+0.00%) [fallback_20pct] |
| 2026-04-02 | COIN, SHOP | +$272.11 | +2.72% | 11 | SHOP +$145.16 (+3.33%) [trailing_stop_ma20] |

---

## 2. Daily Results — Options

| Date | Picks | Cap P&L | Cap % | # Trades | Best Trade |
|------|-------|---------|-------|----------|------------|
| 2026-01-02 | APP, ANAB | +$1,950.00 | +19.50% | 10 | APP +$2710.00 (+33.25%) [trailing_stop_ma20] |
| 2026-01-05 | SNDK, FN | +$2,050.00 | +20.50% | 9 | RH +$1560.00 (+10.66%) [end_of_day] |
| 2026-01-06 | SNDK, APP | +$6,220.00 | +62.20% | 9 | SNDK +$1950.00 (+35.58%) [trailing_stop_ma20] |
| 2026-01-07 | RH, SNDK | +$30.00 | +0.30% | 8 | RH +$250.00 (+8.25%) [trailing_stop_ma20] |
| 2026-01-08 | SNDK, RH | +$4,470.00 | +44.70% | 8 | SNDK +$2420.00 (+47.64%) [trailing_stop_ma20] |
| 2026-01-09 | SNDK, CVNA | +$430.00 | +4.30% | 9 | RH +$840.00 (+6.52%) [end_of_day] |
| 2026-01-12 | SNDK, ANAB | -$240.00 | -2.40% | 7 | SNDK +$50.00 (+1.03%) [fallback_20pct] |
| 2026-01-13 | SNDK, ANAB | +$140.00 | +1.40% | 9 | SHOP +$560.00 (+3.47%) [end_of_day] |
| 2026-01-14 | — | +$0.00 | +0.00% | 0 | no trades |
| 2026-01-15 | ANAB, FANG | +$3,290.00 | +32.90% | 8 | ANAB +$1750.00 (+40.98%) [end_of_day] |
| 2026-01-16 | APP, SHOP | +$2,190.00 | +21.90% | 5 | APP +$1030.00 (+12.76%) [trailing_stop_ma20] |
| 2026-01-20 | FN, CVNA | -$240.00 | -2.40% | 9 | AMD +$640.00 (+10.32%) [trailing_stop_ma20] |
| 2026-01-21 | APP | +$10.00 | +0.10% | 5 | AMD +$160.00 (+4.75%) [trailing_stop_ma20] |
| 2026-01-22 | SNDK, MU | +$600.00 | +6.00% | 11 | SNDK +$590.00 (+8.59%) [end_of_day] |
| 2026-01-23 | ANAB, COIN | +$210.00 | +2.10% | 9 | RH +$600.00 (+4.64%) [end_of_day] |
| 2026-01-26 | ANAB, APP | +$430.00 | +4.30% | 8 | SNDK +$360.00 (+5.67%) [trailing_stop_ma20] |
| 2026-01-27 | RH, CVNA | +$210.00 | +2.10% | 11 | FANG +$360.00 (+5.56%) [end_of_day] |
| 2026-01-28 | SNDK, CVNA | -$250.00 | -2.50% | 8 | SNDK +$70.00 (+1.31%) [fallback_20pct] |
| 2026-01-29 | SNDK, PLTR | -$330.00 | -3.30% | 9 | PLTR +$300.00 (+6.98%) [trailing_stop_ma20] |
| 2026-01-30 | ANAB, SHOP | +$1,950.00 | +19.50% | 7 | SHOP +$1460.00 (+37.24%) [end_of_day] |
| 2026-02-02 | RH | -$180.00 | -1.80% | 6 | CVNA -$10.00 (-0.19%) [fallback_20pct] |
| 2026-02-03 | SHOP, APP | +$4,340.00 | +43.40% | 10 | ANAB +$1680.00 (+20.00%) [end_of_day] |
| 2026-02-04 | PLTR, APP | +$4,110.00 | +41.10% | 8 | CVNA +$2140.00 (+43.06%) [end_of_day] |
| 2026-02-05 | PLTR, APP | +$1,470.00 | +14.70% | 6 | COIN +$1200.00 (+16.60%) [end_of_day] |
| 2026-02-06 | META | +$40.00 | +0.40% | 6 | APP +$240.00 (+4.52%) [end_of_day] |
| 2026-02-09 | FANG | +$550.00 | +5.50% | 8 | ANAB +$360.00 (+2.94%) [end_of_day] |
| 2026-02-10 | SNDK, FN | -$290.00 | -2.90% | 7 | SHOP +$240.00 (+3.81%) [trailing_stop_ma20] |
| 2026-02-11 | SHOP, SNDK | +$3,440.00 | +34.40% | 8 | SHOP +$2260.00 (+60.43%) [trailing_stop_ma20] |
| 2026-02-12 | SHOP, CVNA | +$3,310.00 | +33.10% | 8 | CVNA +$2580.00 (+56.58%) [trailing_stop_ma20] |
| 2026-02-13 | FANG | +$1,280.00 | +12.80% | 7 | ANAB +$900.00 (+14.75%) [end_of_day] |
| 2026-02-17 | COIN, RH | +$3,750.00 | +37.50% | 9 | SNDK +$2600.00 (+15.29%) [end_of_day] |
| 2026-02-18 | COIN, RH | +$1,850.00 | +18.50% | 4 | FN +$1530.00 (+21.49%) [end_of_day] |
| 2026-02-19 | — | +$1,330.00 | +13.30% | 5 | CVNA +$1380.00 (+29.55%) [end_of_day] |
| 2026-02-20 | SHOP, SNDK | +$1,580.00 | +15.80% | 10 | SHOP +$1120.00 (+31.82%) [trailing_stop_ma20] |
| 2026-02-23 | SHOP, APP | -$910.00 | -9.10% | 8 | SHOP +$200.00 (+5.49%) [trailing_stop_ma20] |
| 2026-02-24 | ANAB, FN | -$360.00 | -3.60% | 9 | FN +$470.00 (+5.87%) [trailing_stop_ma20] |
| 2026-02-25 | SHOP, FN | +$1,870.00 | +18.70% | 6 | FN +$1110.00 (+13.70%) [trailing_stop_ma20] |
| 2026-02-26 | SHOP, FN | +$2,160.00 | +21.60% | 9 | FN +$2000.00 (+20.73%) [trailing_stop_ma20] |
| 2026-02-27 | SHOP, FN | +$2,140.00 | +21.40% | 9 | PLTR +$1600.00 (+10.93%) [end_of_day] |
| 2026-03-02 | SNDK, COIN | +$2,080.00 | +20.80% | 9 | RH +$1040.00 (+6.44%) [end_of_day] |
| 2026-03-03 | COIN, FN | -$820.00 | -8.20% | 8 | META -$10.00 (-0.11%) [fallback_20pct] |
| 2026-03-04 | SHOP, RH | +$3,390.00 | +33.90% | 8 | APP +$1700.00 (+25.37%) [end_of_day] |
| 2026-03-05 | SHOP, EXPE | +$3,100.00 | +31.00% | 8 | FN +$1560.00 (+22.00%) [end_of_day] |
| 2026-03-06 | EXPE, SHOP | +$7,520.00 | +75.20% | 6 | FN +$4260.00 (+29.06%) [end_of_day] |
| 2026-03-09 | EXPE, RH | +$6,100.00 | +61.00% | 10 | SNDK +$1920.00 (+27.04%) [end_of_day] |
| 2026-03-10 | COIN, SHOP | -$1,930.00 | -19.30% | 9 | MU -$20.00 (-0.37%) [hard_stop] |
| 2026-03-11 | ANAB, CVNA | +$1,730.00 | +17.30% | 12 | SNDK +$1760.00 (+11.03%) [end_of_day] |
| 2026-03-12 | NVDA | -$60.00 | -0.60% | 6 | NVDA +$110.00 (+4.25%) [trailing_stop_ma20] |
| 2026-03-13 | NVDA | -$30.00 | -0.30% | 3 | FN +$0.00 (+0.00%) [fallback_20pct] |
| 2026-03-16 | — | -$370.00 | -3.70% | 7 | FN +$100.00 (+1.46%) [trailing_stop_ma20] |
| 2026-03-17 | SHOP, EXPE | +$670.00 | +6.70% | 9 | MU +$430.00 (+7.54%) [end_of_day] |
| 2026-03-18 | ANAB | -$80.00 | -0.80% | 7 | ANAB +$280.00 (+3.33%) [trailing_stop_ma20] |
| 2026-03-19 | ANAB | +$0.00 | +0.00% | 0 | no trades |
| 2026-03-20 | SHOP, PLTR | -$80.00 | -0.80% | 8 | PLTR +$220.00 (+5.37%) [trailing_stop_ma20] |
| 2026-03-23 | SHOP, PLTR | +$1,680.00 | +16.80% | 7 | SNDK +$910.00 (+10.39%) [end_of_day] |
| 2026-03-24 | COIN, PLTR | +$2,340.00 | +23.40% | 6 | COIN +$1760.00 (+60.90%) [trailing_stop_ma20] |
| 2026-03-25 | COIN, PLTR | -$250.00 | -2.50% | 8 | FN +$190.00 (+2.25%) [trailing_stop_ma20] |
| 2026-03-26 | EXPE, AMD | +$1,140.00 | +11.40% | 7 | AMD +$860.00 (+30.39%) [trailing_stop_ma20] |
| 2026-03-27 | COIN, SHOP | +$460.00 | +4.60% | 7 | COIN +$260.00 (+10.04%) [trailing_stop_ma20] |
| 2026-03-30 | FN, CVNA | +$3,020.00 | +30.20% | 8 | CVNA +$1690.00 (+39.95%) [trailing_stop_ma20] |
| 2026-03-31 | SHOP, FANG | +$550.00 | +5.50% | 10 | FN +$1380.00 (+10.55%) [end_of_day] |
| 2026-04-01 | CVNA, COIN | -$800.00 | -8.00% | 9 | FN +$0.00 (+0.00%) [hard_stop] |
| 2026-04-02 | COIN, SHOP | +$2,000.00 | +20.00% | 11 | AMD +$900.00 (+10.03%) [end_of_day] |

---

## 3. Weekly Summary

| Week (Mon) | # Days | Stock P&L | Stock % | Options P&L | Options % | Notes |
|------------|--------|-----------|---------|-------------|-----------|-------|
| 2025-12-29 | 1 | +$167.32 | +1.67% | +$1,950.00 | +19.50% | — |
| 2026-01-05 | 5 | +$1,526.15 | +15.26% | +$13,200.00 | +132.00% | Best opts: 2026-01-06 (+$6,220.00); Best stk: 2026-01-08 (+$753.51) |
| 2026-01-12 | 5 | +$696.20 | +6.97% | +$5,380.00 | +53.80% | Best opts: 2026-01-15 (+$3,290.00) |
| 2026-01-19 | 4 | +$20.17 | +0.21% | +$580.00 | +5.80% | — |
| 2026-01-26 | 5 | +$337.88 | +3.38% | +$2,010.00 | +20.10% | — |
| 2026-02-02 | 5 | +$1,212.43 | +12.14% | +$9,780.00 | +97.80% | Best opts: 2026-02-03 (+$4,340.00); Best stk: 2026-02-04 (+$587.52) |
| 2026-02-09 | 5 | +$1,288.82 | +12.89% | +$8,290.00 | +82.90% | Best opts: 2026-02-11 (+$3,440.00); Best stk: 2026-02-12 (+$570.77) |
| 2026-02-16 | 4 | +$855.43 | +8.55% | +$8,510.00 | +85.10% | Best opts: 2026-02-17 (+$3,750.00) |
| 2026-02-23 | 5 | +$340.52 | +3.41% | +$4,900.00 | +49.00% | Worst opts: 2026-02-23 (-$910.00) |
| 2026-03-02 | 5 | +$1,158.47 | +11.59% | +$15,270.00 | +152.70% | Best opts: 2026-03-06 (+$7,520.00); Worst opts: 2026-03-03 (-$820.00); Best stk: 2026-03-06 (+$544.75) |
| 2026-03-09 | 5 | +$520.33 | +5.20% | +$5,810.00 | +58.10% | Best opts: 2026-03-09 (+$6,100.00); Worst opts: 2026-03-10 (-$1,930.00); Best stk: 2026-03-09 (+$565.90) |
| 2026-03-16 | 5 | +$39.10 | +0.39% | +$140.00 | +1.40% | — |
| 2026-03-23 | 5 | +$988.93 | +9.89% | +$5,370.00 | +53.70% | Best stk: 2026-03-24 (+$532.41) |
| 2026-03-30 | 4 | +$590.64 | +5.91% | +$4,770.00 | +47.70% | Best opts: 2026-03-30 (+$3,020.00); Worst opts: 2026-04-01 (-$800.00) |

---

## 4. Monthly Summary

| Month | # Days | Stock P&L | Stock % | Options P&L | Options % | Opt vs Stock |
|-------|--------|-----------|---------|-------------|-----------|--------------|
| Jan 2026 | 20 | +$2,747.72 | +27.49% | +$23,120.00 | +231.20% | 8.4x |
| Feb 2026 | 19 | +$3,697.20 | +36.99% | +$31,480.00 | +314.80% | 8.5x |
| Mar 2026 | 22 | +$3,106.35 | +31.07% | +$30,160.00 | +301.60% | 9.7x |
| Apr 2026 | 2 | +$191.12 | +1.91% | +$1,200.00 | +12.00% | 6.3x |

---

## 5. Total Portfolio Summary

Starting capital: **$10,000** per day (no-compound, daily reset)

| Metric | Stock | Options |
|--------|-------|---------|
| Total Cap P&L (63 days) | +$9,742.39 | +$85,960.00 |
| Total Cap % (sum of daily) | +97.42% | +859.60% |
| Win days | 44 | 44 |
| Loss days | 18 | 17 |
| Flat / no-trade days | 1 | 2 |
| Win rate (excl. flat) | 71.0% | 72.1% |
| Best day | 2026-01-08 (+$753.51) | 2026-03-06 (+$7,520.00) |
| Worst day | 2026-03-10 (-$151.66) | 2026-03-10 (-$1,930.00) |
| Options vs Stock multiplier | — | 8.8x |

---

## 6. Weekly Analysis & Notes

### Week of 2025-12-29 (2026-01-02 to 2026-01-02)

Stock: +$167.32 (+1.67%) — 1/1 winning days
Options: +$1,950.00 (+19.50%) — 1/1 winning days

- First trading day of 2026. QQQ bearish regime active — all bullish signals suppressed, only bearish entries allowed.
- APP Bearish M1 trade was the anchor; options leverage amplified the 4.17% stock gain into a +33.25% option return (+$2,710 on 1 contract).
- Options outperformed stock 11.7x on this single day, setting the tone for the replay period.

### Week of 2026-01-05 (2026-01-05 to 2026-01-09)

Stock: +$1,526.15 (+15.26%) — 4/5 winning days
Options: +$13,200.00 (+132.00%) — 5/5 winning days

- Strong opening week — bearish regime continued, SNDK dominated M1 picks (4 of 5 days). All 5 days profitable on options.
- Options dramatically outperformed stock: +$13,200 vs +$1,526 (8.6x). 1/6 APP PUT +$2,710 and 1/8 SNDK PUT +$2,420 were the week's anchors.
- Stock had only 1 small loss day (1/9 -$4.62); options stayed positive every day through put leverage on a declining market.

### Week of 2026-01-12 (2026-01-12 to 2026-01-16)

Stock: +$696.20 (+6.97%) — 3/5 winning days
Options: +$5,380.00 (+53.80%) — 3/5 winning days

- Choppier week — 2 down days (Mon/Tue) as SNDK/ANAB picks gave mixed signals. Regime filter still active.
- 1/15 ANAB/FANG options blowout: +$3,290 (ANAB calls held to EOD +$1,750). Stock only +$279.
- Options showed higher vol: -$240 worst day vs -$51 stock. 1/14 options replay crashed (cache error), recorded as $0.

### Week of 2026-01-19 (2026-01-20 to 2026-01-23)

Stock: +$20.17 (+0.21%) — 2/4 winning days
Options: +$580.00 (+5.80%) — 3/4 winning days

- Short week (MLK Mon). Only 4 trading days. Near-flat stock (+$20) but options positive (+$580).
- 1/22 SNDK/MU options held to EOD: SNDK +$590, giving the week's best options day at +$600.
- Regime filter causing single-pick days (APP alone 1/21, SNDK/MU 1/22); fewer signals led to lower trade counts.

### Week of 2026-01-26 (2026-01-26 to 2026-01-30)

Stock: +$337.88 (+3.38%) — 3/5 winning days
Options: +$2,010.00 (+20.10%) — 3/5 winning days

- Mid-January mixed week. Consecutive losses 1/28–1/29 (SNDK bearish stalled, CVNA/PLTR reversals hit hard stops).
- Options had wide P&L range: +$1,950 (1/30 SHOP held EOD +$1,460) vs -$330 (1/29); characteristic of leveraged instruments.
- Stock was more resilient: -$66 and -$15 on loss days vs -$250 and -$330 options — leverage cuts both ways in reversals.

### Week of 2026-02-02 (2026-02-02 to 2026-02-06)

Stock: +$1,212.43 (+12.14%) — 4/5 winning days
Options: +$9,780.00 (+97.80%) — 4/5 winning days

- Explosive bull week. SHOP and APP dominated M1 picks 2/3–2/5, all delivering strong options returns (+$4,340, +$4,110, +$1,470).
- Options total: +$9,780 vs stock +$1,212 (8.1x ratio). CVNA calls EOD 2/4 +$2,140 was the single best trade of the week.
- 2/2 sole loss day (RH single pick, -$180 opts); regime transitioned from bearish to mixed, enabling bullish entries from 2/3.

### Week of 2026-02-09 (2026-02-09 to 2026-02-13)

Stock: +$1,288.82 (+12.89%) — 4/5 winning days
Options: +$8,290.00 (+82.90%) — 4/5 winning days

- Steady positive week. SHOP/SNDK/CVNA picks on 2/11–2/12 delivered back-to-back strong options days (+$3,440 and +$3,310).
- 2/10 aligned loss: both SNDK/FN bearish picks failed (-$291 stock, -$290 opts) — rare case where direction was fully wrong.
- FANG-only days (2/9, 2/13) showed moderate options upside (+$550, +$1,280); FANG is a lower-volatility signal generator.

### Week of 2026-02-16 (2026-02-17 to 2026-02-20)

Stock: +$855.43 (+8.55%) — 4/4 winning days
Options: +$8,510.00 (+85.10%) — 4/4 winning days

- Short week (Presidents Day Mon). All 4 trading days profitable for both modes — rare perfect week.
- COIN/RH picks 2/17–2/18 then SHOP/SNDK 2/20 gave consistent directional moves. Options +$8,510 vs stock +$855 (9.9x).
- 2/19 had no pre-market picks listed (regime/score threshold) but afternoon windows still fired trades, generating +$1,330 options.

### Week of 2026-02-23 (2026-02-23 to 2026-02-27)

Stock: +$340.52 (+3.41%) — 3/5 winning days
Options: +$4,900.00 (+49.00%) — 3/5 winning days

- Volatile week. Two large down days: 2/23 SHOP/APP failed (-$910 opts, -$54 stock) and 2/24 ANAB/FN gave -$360 opts.
- Strong 3-day recovery 2/25–2/27 on SHOP/FN picks: +$6,170 options, +$456 stock. FN calls hit trailing stop three consecutive days.
- Stock drawdown contained (-$115 combined losses vs -$1,270 options) — leveraged instruments amplify drawdowns on bad signal days.

### Week of 2026-03-02 (2026-03-02 to 2026-03-06)

Stock: +$1,158.47 (+11.59%) — 4/5 winning days
Options: +$15,270.00 (+152.70%) — 4/5 winning days

- Best options week of the period: +$15,270 (152.7% on $10k/day). SHOP/EXPE/RH picks all fired cleanly.
- 3/6 options hit +$7,520 — the highest single-day options return in the dataset. FN put held EOD +$4,260 was the anchor trade.
- Stock also strong: +$1,158 for the week with 3/6 (+$545) and 3/9 (+$566) both exceeding 5% stock return — aligned directional clarity.

### Week of 2026-03-09 (2026-03-09 to 2026-03-13)

Stock: +$520.33 (+5.20%) — 3/5 winning days
Options: +$5,810.00 (+58.10%) — 2/5 winning days

- Abrupt mid-week reversal: 3/10 was the worst day of the 63-day period for both modes (-$1,930 opts, -$152 stock on COIN/SHOP picks).
- Recovery was immediate 3/11 (+$1,730 opts, +$98 stock on ANAB/CVNA) but 3/12–3/13 were thin (NVDA-only picks, near-flat).
- The week's wins (3/9 +$6,100) far exceeded losses (3/10 -$1,930) — options' asymmetry held: big wins offset small/medium losses.

### Week of 2026-03-16 (2026-03-16 to 2026-03-20)

Stock: +$39.10 (+0.39%) — 2/5 winning days
Options: +$140.00 (+1.40%) — 1/5 winning days

- Weakest week of the period. Regime filter heavily active; 3/16 had no qualifying M1 picks (zero listed). Options barely positive +$140.
- 3/17 brief recovery (+$670 opts, +$97 stock on SHOP/EXPE) sandwiched between loss days on each side.
- 3/19 complete zero-trade day: regime filter + no qualifying signals across all 3 windows (M1, A1, A2). First full no-trade day.

### Week of 2026-03-23 (2026-03-23 to 2026-03-27)

Stock: +$988.93 (+9.89%) — 4/5 winning days
Options: +$5,370.00 (+53.70%) — 4/5 winning days

- Strong rebound week (4/5 days positive). SHOP/PLTR/COIN/EXPE picks delivered consistently. COIN puts 3/24 +$1,760 (trailing stop) standout.
- 3/24 best combined day: COIN/PLTR bearish opts +$2,340 + stock +$532. Regime appears to have shifted — EXPE/AMD bullish entries 3/26.
- Options 5.4x stock for the week (+$5,370 vs +$989); stock win rate (4/5) matched options, showing directional consensus.

### Week of 2026-03-30 (2026-03-30 to 2026-04-02)

Stock: +$590.64 (+5.91%) — 3/4 winning days
Options: +$4,770.00 (+47.70%) — 3/4 winning days

- Final week spanning March end + April open. FN/CVNA on 3/30 was the highlight: CVNA put trailing stop +$1,690 in options, stock +$399.
- 3/31 near-flat stock (+$0.96) but options +$550 from SHOP/FANG afternoon window picks — multi-window system adding afternoon alpha.
- 4/1 loss day (CVNA/COIN picks reversed -$800 opts, -$81 stock). 4/2 close +$2,000 opts, +$272 stock capped the period positively.

---

## 7. Key Observations

- **Options total: +$85,960.00 (+859.60% on $10k/day)** vs **Stock: +$9,742.39 (+97.42%)** — options outperformed by **8.8x** over the 63-day period.
- **Top 5 options days:** 2026-03-06 (+$7,520.00), 2026-01-06 (+$6,220.00), 2026-03-09 (+$6,100.00), 2026-01-08 (+$4,470.00), 2026-02-03 (+$4,340.00).
- **Worst 5 options days:** 2026-03-10 (-$1,930.00), 2026-02-23 (-$910.00), 2026-03-03 (-$820.00), 2026-04-01 (-$800.00), 2026-03-16 (-$370.00).
- **Stock win rate:** 71.0% (44W/18L/1 flat). **Options win rate:** 72.1% (44W/17L/2 flat).
- **Most frequent pre-market picks:** SHOP (20x), SNDK (14x), ANAB (11x), COIN (11x), APP (10x).
- **Leverage asymmetry:** On winning days options averaged +$2,117.73 vs stock +$239.23. On losing days options averaged -$424.71 vs stock -$43.53.
- **Best month:** Mar 2026 for options (+$30,160.00); Feb 2026 for stock (+$3,697.20).
- **Regime filter impact:** Visible in March 16 week (near-flat +$140 opts, +$39 stock) and scattered no-trade days — regime suppression prevented losses on reversal-prone bearish days.

---

*Generated 2026-04-05. Source files: `backtest_result/trade_engine_replay/stock_{{DATE}}.txt` and `options_{{DATE}}.txt`.*
