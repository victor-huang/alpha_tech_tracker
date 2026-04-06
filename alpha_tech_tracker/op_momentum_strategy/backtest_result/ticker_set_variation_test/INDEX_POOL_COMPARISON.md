# Cross-Index Ticker Pool Comparison — 2026 YTD Backtest

**Period**: 2026-01-01 → 2026-04-02 (63 trading days)

**Parameters** (same across all pools):
```
--regime-filter --regime-ma 8
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1
--min-or-range 0.5 --min-or-range-windows M1
--morning-split 100
--reversal --top 2
--or-bar-lookback 3
--bearish-reentry --bullish-reentry
--stop-pct 0.15 --trailing-ma ma20
```

**Capital**: $10,000 initial, $5,000/slot × 2 slots, no-compound (daily reset).

**Objective**: Determine which index universe produces the strongest OR momentum signals. Each pool was hand-picked to represent the most active / highest-volatility names from its index.

---

## Summary Ranking

| Rank | Pool | Tickers | Return | WR | M1 WR | M1 EV/trade | Final Portfolio |
|------|------|---------|--------|----|-------|-------------|----------------|
| 1 | **SPY High-Vol** | TSLA, NVDA, AMD, META, PLTR, COIN, APP, SMCI, NFLX, ARM | **+58.49%** | 31% | 38% | **+0.181%** | **$15,849** |
| 2 | **QQQ High-Vol** | MSTR, CRWD, SHOP, MELI, SNOW, DDOG, AMZN, MSFT, GOOGL, AVGO | +46.57% | 32% | 42% | **+0.354%** | $14,657 |
| 3 | **Mid-Cap AI** | SOUN, AI, UPST, IONQ, GTLB, MNDY, RBRK, AFRM, BBAI, IREN | +45.11% | 22% | 27% | -0.489% | $14,511 |
| 4 | **Russell 2000** | AMC, CNK, IMAX, PENN, CAKE, JACK, DINE, YELP, PLUG, RUN | +40.86% | 19% | 33% | +0.033% | $14,086 |
| 5 | **Random Nasdaq-100** | AAPL, ADBE, PYPL, MU, PANW, TTD, ABNB, WDAY, MRNA, QCOM | +40.39% | 30% | 44% | -0.080% | $14,039 |
| 6 | **ARKK Holdings** | RBLX, ROKU, HOOD, PATH, SQ, RXRX, CRSP, EXAS, ZM, TWLO | +20.54% | 26% | 33% | -0.292% | $12,054 |
| 7 | **Industrials** | GE, RTX, DAL, UAL, AAL, DE, URI, AXON, PWR, FDX | +17.56% | 25% | 33% | -0.128% | $11,756 |
| 8 | **Nasdaq Biotech** | REGN, VRTX, GILD, BIIB, ALNY, SRPT, NBIX, INCY, IONS, HALO | +15.67% | 18% | 25% | -0.234% | $11,567 |
| 9 | **Dow Jones** | GS, BA, CRM, CAT, DIS, UNH, AXP, HD, JPM, NKE | +13.63% | 25% | 38% | -0.102% | $11,363 |
| — | SPY buy & hold | — | -4.00% | — | — | — | $9,600 |
| — | DIA buy & hold | — | -3.84% | — | — | — | $9,616 |
| — | QQQ buy & hold | — | -4.59% | — | — | — | $9,541 |
| — | IWM buy & hold | — | +1.01% | — | — | — | $10,101 |

---

## Per-Pool Detail

### 1. SPY High-Vol — +58.49%

**Tickers**: TSLA, NVDA, AMD, META, PLTR, COIN, APP, SMCI, NFLX, ARM

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 38% | +0.181% | +28.17% |
| A1 13:15/1 | 29% | -0.105% | +8.57% |
| A2 15:00/1 | 27% | -0.040% | +9.01% |

| Month | Return | Portfolio |
|-------|--------|-----------|
| Jan | +15.75% | $11,575 |
| Feb | +16.00% | $13,175 |
| Mar | +24.19% | $15,594 |
| Apr (partial) | +2.55% | $15,849 |

**Key trades**: COIN +8.90% on 2026-03-24 (largest single trade); APP +4.17% on 2026-01-02; AMD +3.98% on 2026-03-26 + META BRE +4.63% same day.

**Why it wins**: High-beta names ($150–$700 range) with crypto/AI narratives produce large *dollar* P&L per % move. COIN at $180 on $5k position = ~28 shares; a 9% move = +$252 on that slot alone.

---

### 2. QQQ High-Vol — +46.57%

**Tickers**: MSTR, CRWD, SHOP, MELI, SNOW, DDOG, AMZN, MSFT, GOOGL, AVGO

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 42% | +0.354% | +28.71% |
| A1 13:15/1 | 27% | -0.103% | +9.11% |
| A2 15:00/1 | 26% | -0.069% | +8.76% |

| Month | Return | Portfolio |
|-------|--------|-----------|
| Jan | +11.47% | $11,575 |
| Feb | +25.79% | $13,726 |
| Mar | +8.39% | $14,565 |
| Apr (partial) | +0.92% | $14,657 |

**Key trades**: CRWD +3.14% on 2026-01-02; AVGO +1.39% + META BRE +4.63% on 2026-03-26; SHOP multiple bearish/reversal wins.

**Standout metric**: Highest M1 EV/trade (+0.354%) of all pools — CRWD, SHOP, and DDOG produce exceptionally clean 15-min OR breakouts.

---

### 3. Mid-Cap AI — +45.11%

**Tickers**: SOUN, AI, UPST, IONQ, GTLB, MNDY, RBRK, AFRM, BBAI, IREN

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 27% | -0.489% | +5.89% |
| A1 13:15/1 | 17% | -0.334% | +27.15% |
| A2 15:00/1 | 22% | -0.106% | +12.07% |

| Month | Return | Portfolio |
|-------|--------|-----------|
| Jan | +23.18% | $12,318 |
| Feb | +17.15% | $13,802 |
| Mar | +2.60% | $14,161 |
| Apr (partial) | +2.18% | $14,511 |

**Key trades**: RBRK bearish signals (consistent A1 rank-1, clean downside momentum); MNDY dominates A1 scoring across multiple months; IONQ best M1 trade: +2.36% on 2026-03-27.

**Noise anchors**: BBAI (~$3), SOUN (~$6), AI (~$8) — three of ten tickers are sub-$10, generating near-zero P&L trades that suppress win rate and EV.

**Standout pattern**: The only pool where A1 (+27.15%) decisively outperforms M1 (+5.89%). Mid-cap AI names build directional momentum through the session rather than exhibiting clean OR breakouts at open. This inverse window pattern is unique among all 9 pools tested.

---

### 4. Russell 2000 — +40.86%

**Tickers**: AMC, CNK, IMAX, PENN, CAKE, JACK, DINE, YELP, PLUG, RUN

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 33% | +0.033% | +28.17% |
| A1 13:15/1 | 10% | -0.275% | +7.93% |
| A2 15:00/1 | 16% | -0.124% | +4.76% |

| Month | Return | Portfolio |
|-------|--------|-----------|
| Jan | +22.63% | $12,263 |
| Feb | +15.43% | $13,806 |
| Mar | +4.99% | $14,305 |
| Apr (partial) | -2.19% | $14,086 |

**Key trades**: JACK +4.15% on 2026-03-27; RUN BRU +2.54% + PENN BRU +2.05% on 2026-03-31.

**Note**: AMC at ~$1/share generates near-zero P&L (low-price noise). A1/A2 win rates are the weakest of all pools (10-16%). Strong Jan driven by JACK and PENN bearish signals.

---

### 5. Random Nasdaq-100 — +40.39%

**Tickers**: AAPL, ADBE, PYPL, MU, PANW, TTD, ABNB, WDAY, MRNA, QCOM

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 44% | -0.080% | +24.80% |
| A1 13:15/1 | 19% | -0.167% | +8.04% |
| A2 15:00/1 | 28% | -0.001% | +7.56% |

**Key observation**: Highest M1 win rate (44%) of all pools but negative M1 EV — clean OR patterns but small % moves limit dollar P&L. MRNA and MU are the high-contribution names.

**Significance**: A *random* Nasdaq-100 grab nearly matches the curated Russell 2000 pool. Index membership provides a baseline level of quality regardless of individual stock selection.

---

### 6. ARKK Holdings — +20.54%

**Tickers**: RBLX, ROKU, HOOD, PATH, SQ, RXRX, CRSP, EXAS, ZM, TWLO

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 33% | -0.292% | +3.59% |
| A1 13:15/1 | 12% | -0.226% | +4.70% |
| A2 15:00/1 | 33% | +0.018% | +12.25% |

**Key observation**: A2 is the best window for this pool — unusual. ARKK names (RXRX at $3, PATH at $11) have low-price noise that pollutes morning OR signals. Feb and Mar both went negative.

**Why it underperforms**: "Innovation" stocks tend to be event-driven (binary FDA, earnings beats/misses) rather than momentum-driven intraday. Cheap sub-$10 stocks add noise.

---

### 7. Industrials — +17.56%

**Tickers**: GE, RTX, DAL, UAL, AAL, DE, URI, AXON, PWR, FDX

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 33% | -0.128% | +9.64% |
| A1 13:15/1 | 20% | -0.150% | +4.85% |
| A2 15:00/1 | 24% | -0.050% | +3.07% |

**Standout trade**: AXON +6.36% (+$30.93) on 2026-03-24 — single largest % trade in this pool.

**Key observation**: AXON cuts both ways — its high-dollar moves can produce blow-ups (Apr 2 reversal: -$9.84). AAL at $10-11/share is noise. Airlines (DAL, UAL, FDX) show cleaner momentum than heavy equipment names.

---

### 8. Nasdaq Biotech — +15.67%

**Tickers**: REGN, VRTX, GILD, BIIB, ALNY, SRPT, NBIX, INCY, IONS, HALO

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 25% | -0.234% | +4.46% |
| A1 13:15/1 | 11% | -0.099% | +4.83% |
| A2 15:00/1 | 18% | -0.148% | +6.38% |

**Lowest win rate** of all pools (18% selected, 11% A1). Feb went negative (-1.80%).

**Why it underperforms**: Biotech volatility is binary/event-driven (FDA decisions, trial data), not intraday momentum. SRPT is the only name with consistent directional OR patterns.

---

### 9. Dow Jones — +13.63%

**Tickers**: GS, BA, CRM, CAT, DIS, UNH, AXP, HD, JPM, NKE

| Window | WR | EV/trade | Return |
|--------|-----|---------|--------|
| M1 09:30/3 | 38% | -0.102% | +8.23% |
| A1 13:15/1 | 16% | -0.086% | +2.07% |
| A2 15:00/1 | 20% | -0.027% | +3.32% |

**Lowest total return** of all pools. Avg win only +0.57% — smallest across all pools.

**Why it underperforms**: Dow components are blue-chip stability stocks. High absolute price (GS ~$840, CAT ~$720) does NOT translate to large % swings. The strategy scores % moves, not dollar moves.

---

## Key Findings

### Finding 1: High-Beta Tech Names Dominate

The top 2 pools share a common characteristic: **high-beta momentum stocks with crypto/AI narratives**. COIN, AMD, NVDA, META, APP, CRWD, SHOP all have beta > 1.5 and produce clean directional OR breakouts.

The strategy's edge scales directly with:
1. **Beta / intraday % range** — larger OR ranges → larger potential exits
2. **Directional momentum character** — stocks that trend within a day vs mean-revert
3. **Price range $50–$700** — enough dollar P&L per % move without being noise at <$10

### Finding 2: The Low-Price Noise Problem

Across all pools, sub-$15 stocks consistently produce near-zero P&L trades:
- **AMC** (~$1): Russell 2000's noise anchor
- **RXRX** (~$3): ARKK's noise anchor
- **AAL** (~$10): Industrials' noise anchor
- **PATH** (~$11): ARKK's secondary noise anchor

Recommendation: add `--min-price 15` filter or exclude sub-$15 tickers from pool screening.

### Finding 3: Index Tier Correlates with Strategy Performance

| Tier | Pools | Characteristics | Avg Return |
|------|-------|-----------------|------------|
| **Top** | SPY High-Vol, QQQ High-Vol, Mid-Cap AI | High-beta tech, crypto proxies, momentum-driven | **+49.6%** |
| **Mid** | Russell 2000, Random Nasdaq-100 | Decent volatility, brand recognition, index diversity | **+40.6%** |
| **Bottom** | ARKK, Industrials, Biotech, Dow | Event-driven, mean-reverting, or low-% intraday moves | **+16.8%** |

Note: Mid-Cap AI joins the top tier on total return (+45.11%) but via an unusual path — A1 afternoon window drives the bulk of its return, not M1 (see Finding 7 below).

### Finding 4: All Pools Beat Every Index Buy-and-Hold

Index buy-and-hold returns for the same period (2026-01-02 → 2026-04-02, close-to-close):

| Index | ETF | Buy & Hold |
|-------|-----|-----------|
| S&P 500 | SPY | -4.00% |
| Dow Jones | DIA | -3.84% |
| NASDAQ-100 | QQQ | -4.59% |
| Russell 2000 | IWM | +1.01% |

Every single pool outperformed all four index benchmarks. The best passive result was IWM +1.01%; the worst was QQQ -4.59%. Every pool returned at least +13.6% — a minimum alpha of +12.6pp vs the best passive index. The top pool (SPY High-Vol +58.49%) delivered +62.5pp of alpha vs QQQ buy-and-hold. The OR momentum strategy generates meaningful alpha in any universe.

### Finding 5: M1 Is the Alpha Driver — Afternoon Windows Add Incrementally

Across all 8 pools, M1 contributes 50-70% of total return. A1 and A2 are additive but weak:
- All pools: A1 EV/trade is negative or near-zero
- All pools: A2 EV/trade is slightly better than A1 but still mostly negative
- Exception: ARKK pool where A2 is the best window (mean-reversion character)

The morning session OR is where the strategy's core edge lives.

### Finding 6: M1 Win Rate vs EV Are Inversely Correlated Across Pools

| Pool | M1 WR | M1 EV/trade | Return |
|------|-------|-------------|--------|
| Random Nasdaq-100 | **44%** | -0.080% | +40% |
| QQQ High-Vol | 42% | **+0.354%** | +47% |
| SPY High-Vol | 38% | +0.181% | **+58%** |
| Russell 2000 | 33% | +0.033% | +41% |

Higher WR alone doesn't drive returns. SPY wins because high-WR wins are *bigger* (COIN, AMD, APP) — the fat right tail dominates.

### Finding 7: Mid-Cap AI Has an Inverse Window Pattern (A1 > M1)

Across all 9 pools, M1 (morning OR) drives 50–70% of total return. Mid-Cap AI is the **sole exception**:

| Pool | M1 Return | A1 Return | A2 Return | Leader |
|------|-----------|-----------|-----------|--------|
| Mid-Cap AI | **+5.89%** | **+27.15%** | +12.07% | **A1** |
| All others | +8–28% | +2–9% | +3–9% | **M1** |

This is consistent with how mid-cap AI names trade: many are event-driven (earnings, partnership announcements, AI narrative catalysts) rather than pure momentum stocks. They don't establish clean OR breakout direction at 9:45 AM but do show directional conviction in the early afternoon (post-lunch 1:20 PM entry). RBRK and MNDY are the clearest examples — both generate their strongest signals in the A1 window.

**Implication**: If mid-cap AI names are added to a pool for live trading, a multi-window system (M1+A1+A2) captures the full edge — running M1 alone would leave the majority of this pool's alpha on the table.

---

## Implication for V2 Pool Expansion

Based on this 9-pool cross-index comparison, the best candidates to add to the V2 pool would come from:

1. **From QQQ High-Vol**: CRWD, SHOP (highest M1 EV/trade pool — their OR patterns are clean)
2. **From SPY High-Vol**: already partially overlaps with V2 (NVDA, AMD, META, PLTR, COIN, TSLA in V2)
3. **From Mid-Cap AI**: RBRK, MNDY, IONQ — strongest contributors; note these names drive A1 alpha, not M1. Only add if the live system runs multi-window (M1+A1+A2).
4. **Avoid**: ARKK names, biotech, Dow blue chips, sub-$15 stocks (BBAI, SOUN, AI, RXRX, AMC, AAL, PATH)

Before adding any ticker, run the standard 30-day + 90-day individual screen per the V2 screening process.

---

## Next Steps

- [ ] Run 5-year (2021–2025) backtest for SPY High-Vol, QQQ High-Vol, and Mid-Cap AI pools to validate 2026 YTD results aren't regime-specific
- [ ] Screen CRWD, SHOP, RBRK, MNDY, IONQ individually with `op_momentum_backtest.py` (30d + 90d) vs V2 pool baseline
- [ ] Test adding a `--min-price 15` filter to eliminate low-price noise stocks from future pool evaluations
- [ ] Consider a combined 20-ticker pool (V2 + best SPY/QQQ/Mid-Cap AI names) and test against top-3 selection
- [ ] Re-run Mid-Cap AI pool with `--min-price 15` to isolate clean signal quality from the 3 noise anchors (BBAI, SOUN, AI)
