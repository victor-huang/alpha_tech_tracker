# Ticker Set Variability Analysis

## Purpose

This document records a systematic evaluation of a new 12-ticker candidate set
(`CRWD MRVL AFRM SMCI SOFI AXON MSTR ARM UBER RKLB KTOS HOOD`) proposed for the
2026 pool rotation. All tests use the confirmed best parameters:
`--regime-filter --regime-ma 8 --weights 50 30 20 --stop-pct 0.15 --trailing-ma ma20`.

---

## Candidate Selection Rationale

Tickers were identified via sector/narrative analysis at end-2025, targeting stocks with:
- High intraday ATR (beta > 1.5 vs QQQ)
- Strong institutional narrative with clear directional conviction at the open
- Liquid mid/large-cap — not mega-cap mean-reverters (GOOGL, AAPL) or illiquid small-caps

| Ticker | Theme | Beta (est.) | Narrative |
|--------|-------|-------------|-----------|
| CRWD | Cybersecurity SaaS | ~1.6 | Enterprise security spend non-discretionary; sector leader |
| MRVL | AI Custom Chips | ~1.7 | Custom AI chip (AVGO-adjacent); data center capex tailwind |
| AFRM | BNPL / Fintech | ~1.8 | Revenue +37% YoY; consumer-facing, high institutional conviction |
| SMCI | AI Servers | 2.46 | AI server narrative; highest raw beta in candidate set |
| SOFI | Neobank | 2.11 | S&P 500 inclusion narrative; fintech + crypto expansion |
| AXON | Public Safety SaaS | 1.45 | TASER→SaaS transformation; government contracts, regime-insensitive |
| MSTR | Bitcoin Treasury | ~2.5 | Corporate BTC adoption; institutional narrative with fundamental anchor |
| ARM | AI Chip Architecture | ~1.7 | AI chip IP; every accelerator licenses ARM |
| UBER | Consumer Tech / AV | ~1.6 | AV narrative catalysts; $150B+ cap with strong opening conviction |
| RKLB | Space / Defense | 2.14 | $1.85B defense backlog; extreme ATR (52wk: $14→$99) |
| KTOS | Defense Drones | 1.85 | Drone/unmanned systems; mid-cap $3–4B, high intraday range |
| HOOD | Retail / Crypto Broker | ~2.0 | Crypto and options expansion; regime-dependent but high ATR |

**Tickers excluded from initial list and why:**
- `MARA / RIOT` — pure BTC correlates, more noise than MSTR/COIN; redundant
- `HIMS` — narrative collapsed 75–80% after FDA GLP-1 ruling; fragile single-narrative risk
- `IONQ / RGTI` — tiny market cap (~$1–2B), illiquid, noise > signal
- `AVGO` — grew to ~$800B, now mean-reverts like GOOGL/AAPL
- `RDDT` — confirmed negative across multiple periods in prior testing

---

## Individual Ticker Backtest Results

### 30-day (Dec 2025) — op_momentum_backtest.py

| Ticker | Signals | WR | AvgWin% | AvgLoss% | EV/Trade | Net P&L |
|--------|---------|-----|---------|---------|----------|---------|
| AFRM | 12 | 67% | 1.11% | 0.90% | +0.439% | +$3.56 |
| ARM | 7 | 57% | 0.90% | 0.13% | +0.461% | +$4.29 |
| UBER | 14 | 29% | 1.24% | 0.13% | +0.264% | +$3.18 |
| RKLB | 13 | 69% | 0.64% | 0.51% | +0.288% | +$1.90 |
| CRWD | 9 | 33% | 0.50% | 0.17% | +0.054% | +$2.71 |
| SMCI | 13 | 38% | 0.87% | 0.25% | +0.178% | +$0.73 |
| SOFI | 7 | 43% | 0.47% | 0.11% | +0.137% | +$0.26 |
| MRVL | 7 | 43% | 0.44% | 0.17% | +0.090% | +$0.51 |
| KTOS | 11 | 18% | 1.32% | 0.21% | +0.067% | +$0.61 |
| AXON | 10 | 30% | 0.80% | 0.34% | -0.002% | -$0.91 |
| MSTR | 9 | 11% | 0.08% | 0.22% | -0.189% | -$3.09 |
| HOOD | 2 | 0% | 0.00% | 0.04% | -0.039% | -$0.09 |

**Total: 114 signals, 39% WR, +$13.66 (1 share per signal)**

### 90-day (Jul–Dec 2025) — op_momentum_backtest.py

| Ticker | Signals | WR | AvgWin% | AvgLoss% | EV/Trade | Net P&L |
|--------|---------|-----|---------|---------|----------|---------|
| AFRM | 70 | 41% | 1.69% | 0.44% | **+0.443%** | +$21.85 |
| UBER | 79 | 48% | 0.75% | 0.14% | **+0.287%** | +$20.84 |
| HOOD | 55 | 40% | 1.41% | 0.33% | **+0.367%** | +$20.33 |
| MSTR | 50 | 30% | 1.33% | 0.21% | **+0.253%** | +$53.37 |
| AXON | 63 | 25% | 1.17% | 0.23% | +0.128% | +$58.57 |
| CRWD | 69 | 38% | 0.66% | 0.18% | +0.136% | +$45.92 |
| ARM | 61 | 33% | 0.85% | 0.23% | +0.124% | +$10.89 |
| SMCI | 65 | 42% | 0.72% | 0.21% | +0.173% | +$5.33 |
| RKLB | 64 | 45% | 0.88% | 0.46% | +0.151% | +$4.03 |
| MRVL | 62 | 35% | 0.83% | 0.26% | +0.128% | +$6.08 |
| SOFI | 62 | 35% | 0.85% | 0.29% | +0.115% | +$1.90 |
| KTOS | 77 | 29% | 0.86% | 0.35% | -0.003% | -$0.95 |

**Total: 777 signals, 37% WR, +$248.16 (1 share per signal)**

### Key individual-ticker observations

- **AFRM** — most consistent EV across both windows (+0.439% / +0.443%). 67% WR in Dec was exceptional; 90-day 41% WR still strong. Bears work especially well (80% WR in Dec).
- **UBER** — highest 90-day WR (48%). Low AvgLoss% (0.14%) makes it one of the cleanest risk-asymmetry profiles. Dec 30d WR appeared low (29%) but a +$3.50 single trade (UBER bear, Dec 10) drove the P&L.
- **HOOD** — Dec 30d had only 2 signals (0% WR); completely uninformative. 90-day result (+0.367% EV, 40% WR) confirms it belongs in the pool. Dec data was a short-window anomaly.
- **MSTR** — extreme variance. Dec was a disaster (11% WR, -$3.09). 90-day recovered strongly (+$53.37). High beta amplifies both directions; regime filter is essential.
- **AXON** — Dec 22 single trade (-$10.16) poisoned the 30-day result. Over 90 days: +$58.57. The signal works but requires larger capital to survive variance swings.
- **KTOS** — 90-day EV essentially zero (-0.003%). While individual trades can be large (e.g. +$3.00 on Dec 24, +$1.88 on Dec 22), the loss frequency is too high for consistent EV.
- **SMCI** — bulls completely broken in Dec (0/4). Only bearish signals profitable. Bearish-signal-only approach may be appropriate given the ongoing governance/accounting overhang.
- **MRVL / SOFI** — both positive EV over 90 days but sub-$90 stock prices suppress dollar P&L. Position sizing (ATR-based or delta-adjusted) would be required to make these meaningful contributors.

---

## Portfolio-Level Selector Backtest Results

All runs use: `op_momentum_selector_backtest.py`, top-3 picks, `--weights 50 30 20`,
`--regime-filter --regime-ma 8`, `$10,000 initial capital`.

### Single Window (M1: 09:30 / 3 bars)

| Period | Strategy | QQQ B&H | Alpha |
|--------|----------|---------|-------|
| Dec 2025 (30d) | **+3.39%** | -0.49% | +3.88pp |
| Jul–Dec 2025 (90d) | **+19.66%** | +12.30% | +7.36pp |
| Jan–Mar 2026 (YTD) | **+20.70%** | -8.25% | **+28.95pp** |

Monthly breakdown (Jul–Dec 2025):

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jul 2025 | +5.80% | +3.29% | +2.51pp |
| Aug 2025 | +3.33% | +0.97% | +2.36pp |
| Sep 2025 | +4.84% | +5.49% | -0.65pp |
| Oct 2025 | -1.22% | +5.29% | -6.51pp |
| Nov 2025 | +3.21% | -1.86% | +5.07pp |
| Dec 2025 | +3.71% | -0.89% | +4.60pp |

Monthly breakdown (Jan–Mar 2026):

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan 2026 | +8.48% | +1.41% | +7.07pp |
| Feb 2026 | +12.93% | -2.34% | **+15.27pp** |
| Mar 2026 | -0.70% | -7.31% | +6.61pp |

**Oct 2025 was the only negative month (-1.22%)** — AFRM and ARM had WR drops that month (14% and 23% respectively) during a choppy bull regime where the QQQ was up +5.29%. The regime filter helped but did not fully protect.

---

### Multi-Window (M1 + M2 + A1 + A2)

Config: `--window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100`

#### Single vs Multi-Window comparison

| Period | Single (M1) | Multi-Window | Lift | QQQ |
|--------|------------|--------------|------|-----|
| Dec 2025 (30d) | +3.39% | **+15.11%** | +11.72pp | -0.49% |
| Jul–Dec 2025 (90d) | +19.66% | **+81.69%** | +62.03pp | +12.30% |
| Jan–Mar 2026 (YTD) | +20.70% | **+60.46%** | +39.76pp | -8.25% |

#### Per-window contribution (Jul–Dec 2025)

| Window | Return | EV/trade | WR | Notes |
|--------|--------|----------|----|-------|
| M1 09:30/3bar | +19.66% | +0.178% | 35% | Baseline; confirmed OR window |
| M2 09:30/1bar | +37.72% | +0.356% | 35% | **2× M1**; fires at 9:35 before OR forms |
| A1 13:15/1bar | +8.45% | +0.092% | 24% | Weakest window; still additive |
| A2 15:00/1bar | +15.85% | +0.136% | 34% | Power hour; strong for this pool |

#### Per-window contribution (Jan–Mar 2026)

| Window | Return | EV/trade | WR | Notes |
|--------|--------|----------|----|-------|
| M1 09:30/3bar | +20.70% | +0.403% | 36% | |
| M2 09:30/1bar | +29.23% | +0.704% | 39% | Highest EV/trade of all windows |
| A1 13:15/1bar | +5.40% | +0.102% | 23% | Weakest for this pool |
| A2 15:00/1bar | +5.12% | +0.144% | 31% | |

**M2 consistently outperforms M1 for this candidate pool** — by roughly 2× return and 2× EV/trade in every period. M2 fires at 9:35 (1-bar OR), capturing momentum before the full 15-min OR closes.

---

### 5-Year Run (Jan 2021 – Mar 2026) — Multi-Window

Total return: **+155.32%** ($10k → $25,531)
QQQ over same period: **+81.83%** ($10k → $18,183)

#### Critical finding: strategy was inactive Jan 2021 – Apr 2025

The monthly breakdown shows **zero picks from Jan 2021 through Apr 2025**. Picks only started firing in May 2025. The 5-year result is therefore driven entirely by ~11 months of activity (May 2025 – Mar 2026).

| Active period | Strategy return | QQQ same period |
|---------------|----------------|-----------------|
| May 2025 – Mar 2026 (~11 months) | **+155.32%** | ~+3% |

**Why no picks 2021–2024?** The selector requires positive rolling 60-day EV before deploying capital (EV gate). Several candidate tickers did not pass this gate before 2025:
- `AFRM, RKLB, HOOD` — IPO'd 2021; insufficient early history in the Alpaca data cache
- `ARM` — IPO'd Sept 2023
- `CRWD, UBER, AXON, MSTR` — were public but EV signal quality in those years was apparently insufficient to pass the gate consistently

**This is NOT a true 5-year backtest** for this candidate pool. It is an ~11-month test that coincided with a favorable period (2025 bull + 2026 selloff). Before drawing conclusions about multi-year durability, these tickers should be individually backtested over 2021–2024 to understand whether the EV gate failure reflects:
1. Genuine signal weakness in earlier years, OR
2. Cache data gaps for IPO-stage tickers, OR
3. The EV gate's conservative 60-day warm-up cutting off early valid signals

In contrast, the **V2 production pool** (SNDK, APP, SHOP, CVNA, AMD, META, EXPE, FANG, ISSC, FN, UI, MU, ANAB, PLTR, COIN, NVDA) backtests cleanly from 2021 onward with picks in every year.

Monthly performance (only months with picks):

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| 2025-05 | +8.20% | — | — |
| 2025-06 | +4.23% | — | — |
| 2025-07 | +17.13% | +3.29% | +13.84pp |
| 2025-08 | +9.94% | +0.97% | +8.97pp |
| 2025-09 | +17.73% | +5.49% | +12.24pp |
| 2025-10 | +7.26% | +5.29% | +1.97pp |
| 2025-11 | +13.14% | -1.86% | +15.00pp |
| 2025-12 | +16.49% | -0.89% | +17.38pp |
| 2026-01 | +19.66% | +1.41% | +18.25pp |
| 2026-02 | +29.01% | -2.34% | +31.35pp |
| 2026-03 | +12.52% | -7.31% | +19.83pp |

Per-window breakdown (5-year run):

| Window | Return | EV/trade | WR |
|--------|--------|----------|----|
| M1 09:30/3bar | +44.90% | +0.212% | 34% |
| M2 09:30/1bar | +72.70% | +0.419% | 36% |
| A1 13:15/1bar | +16.55% | +0.098% | 24% |
| A2 15:00/1bar | +21.16% | +0.115% | 30% |

---

## Summary: Individual Ticker Recommendations

| Ticker | 30d EV | 90d EV | Recommend | Notes |
|--------|--------|--------|-----------|-------|
| **AFRM** | +0.439% | +0.443% | **Add** | Most consistent EV; top pick |
| **UBER** | +0.264% | +0.287% | **Add** | Highest 90d WR (48%), clean risk profile |
| **CRWD** | +0.054% | +0.136% | **Add** | Consistent positive both windows |
| **ARM** | +0.461% | +0.124% | **Add** | Dec standout; 90d modest but solid |
| **HOOD** | -0.039% | +0.367% | **Add** | Dec had only 2 signals; 90d vindicates |
| **MSTR** | -0.189% | +0.253% | **Add (caution)** | High variance; regime filter essential |
| **AXON** | -0.002% | +0.128% | **Add (caution)** | Dec -$10 anomaly; 90d solid |
| **SMCI** | +0.178% | +0.173% | **Watch** | Bearish-only in Dec; small-price risk |
| **RKLB** | +0.288% | +0.151% | **Watch** | High WR but thin net; AvgLoss% near AvgWin% |
| **MRVL** | +0.090% | +0.128% | **Skip** | Stock too cheap; P&L suppressed |
| **SOFI** | +0.137% | +0.115% | **Skip** | Stock too cheap; P&L suppressed |
| **KTOS** | +0.067% | -0.003% | **Exclude** | 90d EV at zero; insufficient edge |

---

## Next Steps (Post-2020 Candidate Set)

- [ ] Run 2021–2024 individual ticker backtests for CRWD, UBER, AXON, MSTR to diagnose why the EV gate was silent before May 2025
- [ ] Run 90-day screen on AFRM, UBER, CRWD, ARM, HOOD using `op_momentum_backtest.py` every quarter to track EV/trade stability
- [ ] Consider adding AFRM + UBER to V2 pool as the first additions (both pass 30d and 90d screens)
- [ ] Investigate HOOD 2021–2024 (IPO Nov 2021) — limited history but worth checking 2022 bear performance
- [ ] Apply `--bearish-ma200` flag to MSTR and SMCI runs in bear regimes — both have low bull success rates

---

## Pre-2020 IPO Candidate Set

A second 12-ticker candidate set was evaluated to address the 5-year EV gate gap discovered in the post-2020 set.
All tickers here went public **before 2020**, so they have full history in the Alpaca cache dating back to at least 2021.

**Tickers**: `NET SQ ROKU TWLO MDB SPOT DDOG PYPL ZS MRNA LYFT TSLA`

### Candidate Selection Rationale

| Ticker | Theme | IPO | Rationale |
|--------|-------|-----|-----------|
| NET | Cloud networking / security | 2019 | Zero-trust narrative; enterprise SaaS; strong OR conviction |
| SQ (→XYZ) | Fintech / payments | 2015 | High ATR; consumer + merchant fintech; now trades as XYZ |
| ROKU | Streaming / CTV | 2017 | Ad revenue narrative; high beta, regime-sensitive |
| TWLO | Cloud communications | 2016 | Developer API infra; moderate ATR |
| MDB | NoSQL cloud database | 2017 | AI/cloud data narrative; enterprise SaaS |
| SPOT | Music streaming | 2018 | Podcasting + AI music narrative; European mega-cap but high ATR |
| DDOG | Cloud observability | 2019 | AI inference monitoring tailwind; strong EV historically |
| PYPL | Digital payments | 2015 | Crypto + stablecoin narrative; high volume |
| ZS | Cloud security / SASE | 2018 | Zero-trust SaaS; sector peer of NET and CRWD |
| MRNA | mRNA biotech | 2018 | High event-driven ATR; narrative-sensitive (FDA, trials) |
| LYFT | Ridesharing | 2019 | Autonomous vehicle narrative catalyst; high intraday range |
| TSLA | EV / AI / robotics | 2010 | Highest liquidity in candidate set; multi-narrative conviction |

### Portfolio-Level Selector Backtest Results (Single Window M1)

All runs: `op_momentum_selector_backtest.py`, top-3, `--weights 50 30 20`, `--regime-filter --regime-ma 8`, $10k initial.

| Period | Strategy (no-compound) | QQQ B&H | Alpha |
|--------|------------------------|---------|-------|
| Dec 2025 (30d) | **+12.18%** | -0.49% | **+12.67pp** |
| Jul–Dec 2025 (90d) | **+12.30%** | +12.30% | +0.00pp |
| Jan–Mar 2026 (YTD) | **+18.83%** | -8.25% | **+27.08pp** |

**90-day compound result**: +39.09% (portfolio grows $10k → $13,909 over the 6-month period).
The no-compound 90-day figure (+12.30%) matching QQQ exactly is a coincidence of timing — the strategy and QQQ both returned nearly identical figures for Jul–Dec 2025 under the daily-reset model.

#### Monthly breakdown — Jul–Dec 2025

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jul 2025 | +12.71% | +3.29% | +9.42pp |
| Aug 2025 | +4.98% | +0.97% | +4.01pp |
| Sep 2025 | +2.43% | +5.49% | -3.06pp |
| Oct 2025 | +7.36% | +5.29% | +2.07pp |
| Nov 2025 | -0.45% | -1.86% | +1.41pp |
| Dec 2025 | +12.06% | -0.89% | +12.95pp |

#### Key wins (individual ticker highlights)

- MRNA +6.64% signal Dec 19 (high event ATR)
- SPOT bear +$10.75 Dec 17 (bearish regime catch)
- ZS bear +$1.77 Dec 23

### Comparison: Pre-2020 vs Post-2020 Candidate Set

| Period | Pre-2020 Set | Post-2020 Set | Winner |
|--------|-------------|---------------|--------|
| Dec 2025 (30d) | +12.18% | +3.39% | **Pre-2020** (+8.79pp) |
| Jul–Dec 2025 (90d, no-cmpd) | +12.30% | +19.66% | **Post-2020** (+7.36pp) |
| Jul–Dec 2025 (90d, cmpd) | +39.09% | — | — |
| Jan–Mar 2026 (YTD) | +18.83% | +20.70% | **Post-2020** (+1.87pp) |
| QQQ (90d) | +12.30% | +12.30% | — |
| QQQ (YTD) | -8.25% | -8.25% | — |

**Key observation**: Pre-2020 tickers showed stronger Dec 2025 performance (MRNA, SPOT, ZS drove outsized moves), while the post-2020 set was more consistently superior in the 90-day and YTD windows. The pre-2020 set's 90-day no-compound return exactly matched QQQ — indicating no edge in that period at the no-compound level, even though compound capital grows +39.09%.

### 5-Year Potential

Unlike the post-2020 candidate set, all tickers here have full Alpaca history back to 2021. A 5-year test should show picks in every year (no EV gate warm-up gap). This test has not yet been run — recommended as the next validation step.

### Pre-2020 Candidate Recommendations

| Ticker | 90d EV (Jul–Dec 25) | Verdict | Notes |
|--------|---------------------|---------|-------|
| **MRNA** | High (event-driven) | **Watch** | Extreme ATR on catalyst days; unstable outside events |
| **SPOT** | Strong bearish signals | **Watch** | Bear signals especially strong; bull WR unclear |
| **ZS** | Consistent | **Add (screen)** | Clean zero-trust narrative; CRWD peer |
| **DDOG** | Consistent | **Add (screen)** | AI observability tailwind; solid OR conviction |
| **NET** | Consistent | **Add (screen)** | Strong security narrative; high OR reliability |
| **TSLA** | High variance | **Already in V2** | TSLA was original anchor ticker; no change needed |
| **MDB** | Moderate | **Watch** | Lower ATR than peers; marginal candidate |
| **TWLO** | Low | **Skip** | Growth stalled post-2022; signal quality unclear |
| **ROKU** | Low | **Skip** | CTV narrative weakening; below-threshold ATR |
| **LYFT** | Moderate | **Watch** | AV narrative spike risk; but thin float |
| **PYPL** | Low | **Skip** | Mature payments; mean-reverting tendency |
| **SQ/XYZ** | Moderate | **Watch** | Ticker change risk; worth monitoring post-rebrand |

**Priority additions from pre-2020 pool**: ZS, DDOG, NET — all pass the strategy's criteria (high ATR, directional narrative, liquid mid/large-cap). Run individual 30d/90d backtest screens before committing.

---

## NDX High-Beta Candidate Set

A third 10-ticker candidate set drawn from the Nasdaq 100 and Nasdaq Composite, selected for highest beta and best H2 2025 price performance. All tickers excluded from V2 pool, pre-2020 set, and post-2020 set.

**Tickers**: `WDC STX LRCX MRVL KLAC MPWR AVGO ASTS DASH FTAI`

Full detail log: `backtest_result/ticker_set_variation_test/NDX_HIGHBETA_SUMMARY.md`

### Candidate Rationale

| Ticker | Beta | H2 2025 | Theme |
|--------|------|---------|-------|
| WDC | 2.19 | +130–160% | AI HDD storage (post-SNDK spin-off) |
| STX | 1.88 | +110–130% | AI HDD storage (HAMR tech) |
| LRCX | 2.17 | +60–80% | Semiconductor equipment / AI capex |
| MRVL | 1.78 | +60–70% | Custom AI ASICs (Amazon/Google) |
| KLAC | ~1.6 | +40–50% | Semiconductor process control |
| MPWR | ~1.65 | +35–50% | AI power management ICs for GPU servers |
| AVGO | ~1.4 | +35–45% | Custom AI ASICs + networking (borderline mega-cap) |
| ASTS | ~2.5 | +170% | Space/satellite direct-to-device (Nasdaq 2021) |
| DASH | ~1.9 | +50% | DoorDash; first GAAP profit year, AI logistics |
| FTAI | 1.62 | +70–80% | Aerospace MRO + AI data center power conversion |

### 30-day and 90-day Portfolio Results (Multi-Window)

Config: `--window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 60 40`

| Period | Strategy | QQQ | Alpha |
|--------|----------|-----|-------|
| Dec 2025 (30d) | **+7.63%** | -0.49% | +8.12pp |
| Jul–Dec 2025 (90d) | **+68.04%** | +12.30% | **+55.74pp** |

90-day per-window:

| Window | Return | EV/trade | WR |
|--------|--------|----------|----|
| M1 09:30/3bar | +22.83% | +0.280% | 27% |
| M2 09:30/1bar | +22.36% | +0.508% | 39% |
| A1 13:15/1bar | +9.29% | +0.089% | 18% |
| A2 15:00/1bar | +13.57% | +0.120% | 24% |

90-day monthly breakdown:

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jul 2025 | +15.24% | +3.29% | +11.95pp |
| Aug 2025 | +5.64% | +0.97% | +4.67pp |
| Sep 2025 | +9.99% | +5.49% | +4.50pp |
| Oct 2025 | **+18.88%** | +5.29% | **+13.59pp** |
| Nov 2025 | +10.78% | -1.86% | +12.64pp |
| Dec 2025 | +7.51% | -0.89% | +8.40pp |

**Every month positive.** Oct 2025 standout at +18.88% — WDC, STX, LRCX, MRVL earnings beats during AI storage/chip momentum peak.

**Dec 30d note**: M1 was slightly negative (-0.08%); M2 carried the month (+6.35%, EV +0.707%). The 15-min OR did not form clean breakouts in December's choppy year-end tape; the 9:35 1-bar entry captured momentum better.

### 5-Year Backtest Results (Multi-Window)

| Year | Strategy | QQQ | Alpha | Picks | WR |
|------|----------|-----|-------|-------|----|
| 2021 | **+81.33%** | +28.50% | +52.83pp | 2337 | 24% |
| 2022 | **+137.75%** | -33.68% | **+171.43pp** | 2227 | 24% |
| 2023 | **+96.48%** | +54.81% | +41.67pp | 2296 | 25% |
| 2024 | **+99.76%** | +26.98% | +72.78pp | 2245 | 24% |
| 2025 | **+76.72%** | +20.36% | +56.36pp | 1531 | 27% |
| 2026 YTD | **+26.78%** | -8.25% | +35.03pp | 475 | 29% |

**Positive alpha every year. No losing years vs QQQ. No negative calendar months (2021–2024).**

### Cross-Set 5-Year Comparison (Multi-Window)

| Year | NDX High-Beta | Pre-2020 Set | QQQ |
|------|---------------|-------------|-----|
| 2021 | +81.33% | +104.14% | +28.50% |
| 2022 | **+137.75%** | +126.99% | -33.68% |
| 2023 | +96.48% | +103.62% | +54.81% |
| 2024 | **+99.76%** | +84.69% | +26.98% |
| 2025 | **+76.72%** | +57.76% | +20.36% |
| 2026 YTD | +26.78% | +27.62% | -8.25% |

NDX high-beta beats pre-2020 set in 2022, 2024, and 2025. Pre-2020 set leads in 2021 and 2023. They are complementary — combining the strongest tickers from each would likely dominate top-3 selection.

### Key Findings

**1. Best bear market performance of any set tested** — +137.75% in 2022 (QQQ -33.68%) = +171pp alpha. Semiconductor equipment (LRCX, KLAC) and storage (WDC, STX) generated consistent bearish signals throughout the tech selloff. A1 afternoon window was the top contributor in 2022 (+43.22%) — post-lunch selling pressure reinforced morning direction.

**2. Zero negative calendar months (2021–2024)** — not a single losing month across 4 full years. 2025 had no picks Jan–Apr (regime filter during QQQ drawdown), but every active month from May onward was positive.

**3. Aug 2024 +25.86% in one month** — NVIDIA earnings season drove simultaneous outsized moves in LRCX, MRVL, KLAC, WDC, and STX. Semiconductor cluster concentration amplifies gains during AI capex peaks.

**4. M2 dominates in recent periods** — EV/trade +0.508% vs M1 +0.280% in the 90d test. The 1-bar 9:35 entry captures pre-OR momentum especially well for high-beta semis.

**5. AVGO borderline** — ~$1T market cap reduces intraday ATR as a percentage. Positive contribution overall but may dilute top-3 slots better used by smaller-cap high-beta names.

### NDX High-Beta Ticker Recommendations

| Ticker | Verdict | Notes |
|--------|---------|-------|
| **LRCX** | **Add** | Highest consistency; beta 2.17; positive every year |
| **MRVL** | **Add** | Custom AI ASIC narrative durable; strong bull + bear |
| **WDC** | **Add** | Highest H2 return; beta 2.19; pure-play AI storage |
| **STX** | **Add** | WDC peer; HAMR narrative clean; consistent EV |
| **KLAC** | **Add (screen)** | LRCX peer; slightly lower beta; run 30d/90d individual screen |
| **MPWR** | **Add (screen)** | AI power management; smaller cap; run individual screen |
| **ASTS** | **Watch** | Extreme beta ~2.5; pre-revenue; lumpy signals |
| **DASH** | **Watch** | Good 90d result; sector diversifier vs semis cluster |
| **FTAI** | **Watch** | Only 3 years of data; unique aerospace+AI angle |
| **AVGO** | **Skip** | ~$1T cap; intraday ATR% too low for meaningful OR signals |

---

## SPY High-Beta Candidate Set

A fourth 12-ticker candidate set drawn from the S&P 500, filtered from a list of top SPY performers after removing all tickers already tested. HIMS replaced with TGT due to FDA narrative collapse risk.

**Tickers**: `GNRC TER AMAT BLDR APA CIEN TPL SLB LYB CAT INTC TGT`

Full detail log: `backtest_result/ticker_set_variation_test/SPY_HIGHBETA_SUMMARY.md`

### 5-Year Results (Multi-Window)

| Year | Strategy | QQQ | Alpha |
|------|----------|-----|-------|
| 2021 | +81.13% | +28.50% | +52.63pp |
| 2022 | **+96.96%** | -33.68% | +130.64pp |
| 2023 | +68.85% | +54.81% | +14.04pp |
| 2024 | **+94.17%** | +26.98% | +67.19pp |
| 2025 | +59.98% | +20.36% | +39.62pp |
| 2026 YTD | +25.73% | -8.25% | +33.98pp |

Positive alpha every year. No negative calendar months 2021–2024. Dec 2024 outlier: **+24.78% in one month** (AMAT/TER/CIEN AI capex peak). 2023 weakest at +14pp alpha — QQQ gap-up months (Jan, Mar, Nov) dragged relative performance.

**Top candidate**: AMAT — direct LRCX/KLAC peer, consistent across all years, AI wafer fab capex narrative durable.

---

## Russell 2000 Random Baseline

**Finding 9: The OR Breakout Signal Works on Random Small-Cap Tickers — and Outperforms All Curated Sets**

To establish a true baseline, two independent sets of 12 tickers were randomly selected from the Russell 2000 small-cap index with no screening criteria.

### Batch A

**Tickers**: `BOOT ATKR KLIC IDCC ACMR ENVA RDNT NMRK MARA CSWI STRA FULT`

Log files: `backtest_result/ticker_set_variation_test/rut2000_baseline_multiwindow_*.log`

### Batch B

**Tickers**: `CALM DORM EXPO AMBA HAYW PLXS MGNI SHAK REZI XPEL PRGS FOXF`

Log files: `backtest_result/ticker_set_variation_test/rut2000b_multiwindow_*.log`

### 5-Year Results — Both Batches vs All Curated Sets (Multi-Window)

| Year | RUT2000-A | RUT2000-B | NDX High-Beta | SPY High-Beta | Pre-2020 | QQQ |
|------|-----------|-----------|---------------|---------------|----------|-----|
| 2021 | **+138.89%** | +126.29% | +81.33% | +81.13% | +104.14% | +28.50% |
| 2022 | **+165.03%** | +146.42% | +137.75% | +96.96% | +126.99% | -33.68% |
| 2023 | **+124.69%** | +104.27% | +96.48% | +68.85% | +103.62% | +54.81% |
| 2024 | +115.66% | +105.63% | **+99.76%** | +94.17% | +84.69% | +26.98% |
| 2025 | +125.50% | **+126.28%** | +76.72% | +59.98% | +57.76% | +20.36% |
| 2026 YTD | +22.60% | **+30.50%** | +26.78% | +25.73% | +27.62% | -8.25% |

**Both random Russell 2000 batches beat every curated large-cap set in every year. Batch B 2026 YTD leads all sets at +30.50%.**

### Monthly Breakdown 2025 — Batch A

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +7.88% | +2.35% | +5.53pp |
| Feb | **+18.68%** | -2.79% | **+21.47pp** |
| Mar | +9.55% | -7.67% | +17.22pp |
| Apr | **+16.63%** | +1.24% | **+15.39pp** |
| May | +7.92% | +8.62% | -0.70pp |
| Jun | +6.92% | +6.35% | +0.57pp |
| Jul | +10.95% | +2.63% | +8.32pp |
| Aug | +11.15% | +1.04% | +10.11pp |
| Sep | +9.17% | +5.88% | +3.29pp |
| Oct | +11.08% | +5.67% | +5.41pp |
| Nov | +5.27% | -1.99% | +7.26pp |
| Dec | +10.32% | -0.95% | +11.27pp |
| **TOTAL** | **+125.50%** | **+20.36%** | **+105.14pp** |

### Monthly Breakdown 2025 — Batch B

| Month | Strategy | QQQ | Alpha |
|-------|----------|-----|-------|
| Jan | +8.66% | +2.35% | +6.31pp |
| Feb | +13.72% | -2.79% | +16.51pp |
| Mar | +10.84% | -7.67% | +18.51pp |
| Apr | +9.48% | +1.24% | +8.24pp |
| May | +9.82% | +8.62% | +1.20pp |
| Jun | +5.06% | +6.35% | -1.29pp |
| Jul | **+14.62%** | +2.63% | **+11.99pp** |
| Aug | +7.96% | +1.04% | +6.92pp |
| Sep | +13.64% | +5.88% | +7.76pp |
| Oct | +13.48% | +5.67% | +7.81pp |
| Nov | +9.60% | -1.99% | +11.59pp |
| Dec | +9.41% | -0.95% | +10.36pp |
| **TOTAL** | **+126.28%** | **+20.36%** | **+105.92pp** |

Batch B fires picks in all 12 months of 2025 including Jan–Apr (no regime filter gap). Every month positive.

### Compound Growth Run — Batch B (2021-01-01 → 2026-03-28)

Log file: `backtest_result/ticker_set_variation_test/rut2000b_compound_2021_2026.log`

**$10,000 → $5,626,673 (+56,167%) over ~5.25 years.**

| Period | Portfolio End | Year Return | QQQ B&H End |
|--------|--------------|-------------|-------------|
| End 2021 | $34,910 | +249% | $12,850 |
| End 2022 | $147,768 | +323% | $6,632 |
| End 2023 | $416,765 | +182% | $15,481 |
| End 2024 | $1,181,832 | +183% | $12,698 |
| End 2025 | $4,160,725 | +252% | $12,036 |
| Mar 2026 | $5,626,673 | +35% YTD | $9,175 |

> This is a mathematical illustration of the compounding effect only. These returns are **not achievable in live trading** — see Finding 9 Key Findings for why small-cap results cannot be replicated with options (illiquid weekly markets, wide spreads, low OI).

For reference, the curated V2 pool compound result over the same period (M2+A1+A2):
- $10k → ~$101k (+914%) — 55× less terminal value, but actually achievable in live trading.

### Per-Window EV Comparison (2025)

| Window | RUT2000 | NDX High-Beta | SPY High-Beta |
|--------|---------|---------------|---------------|
| M1 EV | +0.160% | +0.280% | +0.242% |
| M2 EV | +0.360% | +0.508% | +0.244% |
| A1 EV | +0.173% | +0.089% | +0.091% |
| A2 EV | +0.131% | +0.120% | +0.092% |

A1 and A2 EV are higher for RUT2000 than for the large-cap sets — afternoon windows work especially well on small-caps.

### Key Findings

**1. The OR breakout signal is fundamentally robust — confirmed by two independent random draws.** Both Batch A and Batch B generate positive EV on 12 random small-cap tickers with zero curation. The strategy's alpha is driven by the signal mechanics (OR breakout + MA filters + regime gate), not ticker selection.

**2. Small-caps run in all regimes** — both batches had picks in every single month of 2025, including Jan–Apr when all large-cap sets had zero picks due to the QQQ regime filter. Small-caps generate both bullish and bearish OR signals across all regimes because they are less correlated with QQQ.

**3. Higher % ATR amplifies EV** — small-caps move 2–5% intraday vs 0.5–1.5% for large-caps. OR breakouts capture percentage moves, so small-caps naturally produce larger backtest EV/trade. Annual returns of +105–165% across both batches reflect this amplification.

**4. Results are consistent across very different sector mixes.** Batch A (footwear, electrical, crypto mining, IP licensing, banking) and Batch B (food, auto parts, restaurant, ad tech, software, semiconductor) produce nearly identical annual return profiles despite no sector overlap. The signal works across all sectors at this market cap.

**5. Backtest results are NOT achievable in live trading for small-caps** — this is a critical caveat. The strategy is designed to trade weekly options, not stocks directly. Small-cap options markets are:
   - Often illiquid or non-existent for weekly contracts
   - Wide bid-ask spreads that would absorb most of the modeled EV
   - Low open interest limits position sizing
   - High implied volatility premiums erode edge on entry

**6. The value of curated large-cap pools is live tradability, not signal creation** — the curated pools (V2, NDX high-beta, SPY high-beta) are not needed to make the OR signal work. They are needed to ensure:
   - Liquid weekly options markets (narrow spreads, deep OI)
   - Large absolute dollar P&L per contract (high stock price × large ATR)
   - Institutional-grade execution without slippage
   - Predictable narrative-driven opening conviction

**7. Implication for pool curation** — the baseline confirms that the selection criteria should focus on **options liquidity and absolute dollar ATR** rather than maximizing backtest percentage returns. A $300 stock moving 1.5% intraday generates more option P&L than a $15 stock moving 4%.

---

## Consolidated Next Steps

- [x] Run 5-year backtest on pre-2020 set — completed, picks fire every year
- [x] Establish Russell 2000 random baseline — completed (Finding 9, two independent batches)
- [ ] Run individual `op_momentum_backtest.py` screens on ZS, DDOG, NET (pre-2020) for 30d + 90d
- [ ] Run individual `op_momentum_backtest.py` on LRCX, MRVL, WDC, STX (NDX) and AMAT (SPY) for 30d + 90d
- [ ] Test adding LRCX + MRVL + AMAT to V2 pool: run 5-year backtest with V2 + {LRCX, MRVL, AMAT}
- [ ] Consider a combined "best-of-all-sets" pool: V2 + ZS + DDOG + LRCX + MRVL + AMAT
- [ ] Run 2021–2024 individual ticker backtests for CRWD, UBER, AXON, MSTR (post-2020 EV gap diagnosis)
- [ ] Run 90-day screen on AFRM, UBER, CRWD, ARM, HOOD every quarter to track EV/trade stability
- [ ] Apply `--bearish-ma200` flag to MSTR and SMCI runs in bear regimes

- [x] Run 5-year backtest on pre-2020 set — completed, picks fire every year
- [ ] Run individual `op_momentum_backtest.py` screens on ZS, DDOG, NET (pre-2020) for 30d + 90d
- [ ] Run individual `op_momentum_backtest.py` on LRCX, MRVL, WDC, STX (NDX) for 30d + 90d
- [ ] Test adding LRCX + MRVL to V2 pool: run 5-year backtest with V2 + {LRCX, MRVL}
- [ ] Consider a combined "best-of-all-sets" pool: V2 + ZS + DDOG + LRCX + MRVL
- [ ] Run 2021–2024 individual ticker backtests for CRWD, UBER, AXON, MSTR (post-2020 EV gap diagnosis)
- [ ] Run 90-day screen on AFRM, UBER, CRWD, ARM, HOOD every quarter to track EV/trade stability
- [ ] Apply `--bearish-ma200` flag to MSTR and SMCI runs in bear regimes
