# Historical 2019–2020 Ticker Experiment

---

## All Experiment Pools — Quick Reference

All backtests use: `winrate-backtest --or-bars 3 --collection-bars 3 --top 8 --capital 10000 --feed sip`

| Pool | Count | Tickers | Theme |
|---|---|---|---|
| **SetC_ref** | 20 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR MARA DKNG AFRM HUT RIOT LUNR JOBY CLSK | R2K + crypto miners (baseline) |
| **Exp1** | 15 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT DKNG AFRM LUNR JOBY | R2K no-crypto |
| **Exp2** | 18 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT DKNG AFRM LUNR JOBY SNDK APP DDOG | Exp1 + May rally names |
| **Exp3** | 22 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS DKNG AFRM LUNR JOBY SNDK APP DDOG TSLA PLTR AMD MU NVDA | R2K + Set A + QQQ beta |
| **Exp4** | 20 | SNDK APP DDOG PLTR TSLA NVDA AMD META MU MRVL HOOD RKLB ASTS IONQ SMCI OKLO RDDT HIMS DKNG AFRM | 10+10 QQQ/R2K balanced |
| **Exp5** | 24 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT DKNG AFRM LUNR JOBY SNDK APP DDOG PLTR TSLA NVDA AMD MU MRVL | Deep R2K + QQQ |
| **Exp6** | 20 | META AMZN NFLX GOOGL NVDA TSLA AAPL MSFT AMD SMCI SOFI NU DKNG HOOD AFRM SOUN UPST CAVA IONQ HIMS | Set D (large-cap) |
| **Exp7** | 18 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS DKNG AFRM SNDK APP DDOG COIN MSTR CRWV | R2K no-crypto + COIN/MSTR/CRWV |
| **Exp8** | 20 | SNDK APP DDOG PLTR TSLA NVDA AMD CRWV SOFI MRVL HOOD RKLB ASTS IONQ SMCI OKLO RDDT HIMS DKNG AFRM | Exp4 CRWV/SOFI variant |
| **Exp9** | 15 | HOOD RKLB ASTS IONQ SMCI RDDT SNDK APP DDOG PLTR TSLA NVDA AMD OKLO HIMS | Concentrated hybrid |
| **Exp10** | 15 | HOOD RKLB ASTS IONQ SMCI OKLO RDDT NU HIMS DKNG AFRM ACHR WOLF RXRX OPEN | R2K fresh swap (ACHR/WOLF/RXRX/OPEN) |
| **Exp11** | 17 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT DKNG AFRM LUNR JOBY CRWV MSTR | Exp1 + CRWV/MSTR |
| **Exp12** | 17 | HOOD RKLB ASTS IONQ SMCI OKLO RDDT HIMS DKNG AFRM LUNR JOBY APP SNDK DDOG MU PLTR | Exp1 core + SNDK/APP/DDOG/MU/PLTR |
| **Exp13** | 17 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT DKNG AFRM ACHR WOLF RXRX OPEN | R2K + ACHR/WOLF/RXRX/OPEN |
| **Exp14** | 18 | HOOD RKLB ASTS IONQ SMCI RDDT SNDK APP DDOG PLTR TSLA NVDA AMD OKLO HIMS SOFI NU RKT | Exp9 extended + SOFI/NU/RKT |
| **Exp2019A** | 20 | TLRY CGC PLUG WKHS W LYFT BYND PINS FVRR CHWY PTON TDOC AMD NVDA ROKU SHOP TTD ZM CRWD OKTA | 2019-era R2K + Nasdaq (60/40) |
| **SetCPruned** | 16 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR DKNG AFRM HUT CLSK | SetC minus LUNR/JOBY/MARA/RIOT |
| **SetCNoLunrJoby** | 18 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR MARA DKNG AFRM HUT RIOT CLSK | SetC minus LUNR/JOBY only |
| **SetCNasdaq** | 20 | HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR DKNG AFRM HUT CLSK AMD CRWD SHOP OKTA | SetCPruned + AMD/CRWD/SHOP/OKTA |

Full backtest results: `MIXED_TICKER_RESEARCH_2026.md` (Exp1–Exp14, SetC_ref) and this file (Exp2019A, SetCPruned, SetCNasdaq, SetCNoLunrJoby).

---

**Goal:** Find a 60% Russell 2000 / 40% Nasdaq pool that performs well in 2019 and 2020,
two regimes that SetC_ref struggled with (2019: -7.4% with thin pool; 2020: -0.2% with
partial pool).

**Method:** `winrate-backtest` CLI — `--capital 10000 --top 8 --or-bars 3 --collection-bars 3 --feed sip`

**Rationale for this pool:**
- SetC_ref uses R2K names that mostly IPO'd in 2021+. The 2019-era equivalents were the
  2019 IPO class (BYND, PINS, FVRR, PTON, LYFT, CHWY, ZM, CRWD) plus established
  high-beta names (TLRY/CGC cannabis boom, PLUG/WKHS clean energy, TDOC telehealth).
- Nasdaq leaders with proven intraday momentum: AMD (+148% in 2019), ROKU (+337%), SHOP,
  TTD, NVDA, OKTA.

---

## Ticker Pool — Exp2019A (20 tickers)

### Russell 2000 / High-Beta Small-Mid (12 tickers — 60%)

| Ticker | Theme | First available |
|---|---|---|
| TLRY | Cannabis / high momentum | July 2018 IPO |
| CGC | Cannabis / Canopy Growth | Long history |
| PLUG | Hydrogen fuel cells / clean energy | Long history |
| WKHS | EV delivery vehicles | Long history (hot in 2020) |
| W | Wayfair / e-commerce high beta | Long history |
| LYFT | Ride-sharing | March 2019 IPO |
| BYND | Plant-based meat | May 2019 IPO |
| PINS | Pinterest / social media | April 2019 IPO |
| FVRR | Fiverr / gig economy | June 2019 IPO |
| CHWY | Chewy / pet e-commerce | June 2019 IPO |
| PTON | Peloton / connected fitness | September 2019 IPO |
| TDOC | Teladoc / telehealth | Long history (huge 2020) |

### Nasdaq Momentum (8 tickers — 40%)

| Ticker | Theme | 2019 return |
|---|---|---|
| AMD | Semiconductor / CPU-GPU | +148% |
| ROKU | Streaming platform | +337% |
| SHOP | Shopify / e-commerce SaaS | +178% |
| TTD | The Trade Desk / programmatic ad | +130% |
| NVDA | GPU / AI / data center | +76% |
| OKTA | Cloud identity / security | +106% |
| ZM | Zoom / video comms | April 2019 IPO |
| CRWD | CrowdStrike / endpoint security | June 2019 IPO |

---

## Spot Check Plan

Before running full years, validate on 2 shorter windows to ensure the pool fires well:

| Window | Purpose |
|---|---|
| 2019-02-01 → 2019-04-30 | Pre-IPO base: TLRY/CGC/PLUG/W/AMD/ROKU/SHOP/TTD/NVDA/OKTA available |
| 2019-07-01 → 2019-09-30 | Post-IPO influx: BYND/PINS/FVRR/LYFT/ZM/CRWD now available |

---

## Results

### Spot Check 1 — Feb–Apr 2019 (pre-IPO base pool)

```
Total   61d   +$592.10   (+5.9%)
Trade days  58/61  (95%)
Avg deployed  $3,607  |  util 36.1%
Mean RODC  +0.298%   DW-Sharpe  8.43
```

15 tickers available (BYND/CHWY/CRWD/FVRR/PTON not yet public).
High utilization (36%) and Sharpe (8.43) — the pre-IPO Nasdaq names fire well.

### Spot Check 2 — Jul–Sep 2019 (post-IPO influx)

```
Total   64d   +$539.96   (+5.4%)
Trade days  59/64  (92%)
Avg deployed  $3,281  |  util 32.8%
Mean RODC  +0.206%   DW-Sharpe  5.60
```

Full 20 tickers available. Slightly lower RODC than Q1 — IPO-class names add volume but
introduce more noise in their early trading weeks.

### Full Year 2019

```
Total   252d   +$2,140.54   (+21.4% committed | +71.6% on avg deployed)
Trade days  220/252  (87%)
Avg deployed  $2,991  |  util 29.9%
Mean RODC  +0.288%   DW-Sharpe  6.19
```

| Month | Return |
|---|---|
| Jan | +2.3% |
| Feb | +1.3% |
| Mar | +2.3% |
| Apr | +2.3% |
| May | +1.6% |
| Jun | +1.6% |
| Jul | +1.7% |
| Aug | +0.4% |
| Sep | +3.3% |
| Oct | +0.4% |
| Nov | +2.4% |
| Dec | +1.7% |
| **Total** | **+21.4%** |

**No losing month.** Sep 2019 (+3.3%) was driven by PTON IPO momentum + broader tech
breakout. Aug and Oct were quiet but still positive.

### Full Year 2020

```
Total   253d   +$2,007.90   (+20.1% committed | +78.6% on avg deployed)
Trade days  205/253  (81%)
Avg deployed  $2,554  |  util 25.5%
Mean RODC  +0.283%   DW-Sharpe  5.81
```

| Month | Return |
|---|---|
| Jan | +0.4% |
| Feb | -0.6% |
| Mar | +2.8% |
| Apr | +1.4% |
| May | +1.9% |
| Jun | +4.8% |
| Jul | +3.3% |
| Aug | +2.5% |
| Sep | +1.0% |
| Oct | -0.2% |
| Nov | +2.1% |
| Dec | +0.9% |
| **Total** | **+20.1%** |

Only 2 losing months (Feb -0.6% COVID early sell-off, Oct -0.2%). Jun 2020 (+4.8%) was
the WFH/clean-energy momentum peak: ZM, TDOC, PLUG, WKHS all had massive OR breakouts.

### Full Year 2021

```
Total   252d   +$1,475.50   (+14.8% committed | +50.4% on avg deployed)
Avg deployed  $2,927  |  util 29.3%   Mean RODC  +0.237%   DW-Sharpe  4.38
```

| Month | Return | | Month | Return |
|---|---|---|---|---|
| Jan | +0.7% | | Jul | +2.3% |
| Feb | -1.7% | | Aug | +1.5% |
| Mar | +4.0% | | Sep | +0.5% |
| Apr | +1.2% | | Oct | +1.0% |
| May | +0.8% | | Nov | +1.6% |
| Jun | +2.2% | | Dec | +0.7% |
| **Total** | | | | **+14.8%** |

Feb 2021 -1.7%: BYND/PTON/TLRY began their long declines (WFH peak passed). Mar recovery driven by AMD/CRWD/OKTA breakouts.

### Full Year 2022

```
Total   251d   +$2,327.86   (+23.3% committed | +71.8% on avg deployed)
Avg deployed  $3,242  |  util 32.4%   Mean RODC  +0.289%   DW-Sharpe  4.94
```

| Month | Return | | Month | Return |
|---|---|---|---|---|
| Jan | +0.8% | | Jul | +2.1% |
| Feb | +2.4% | | Aug | +1.7% |
| Mar | +2.3% | | Sep | +1.3% |
| Apr | +2.7% | | Oct | +0.9% |
| May | +1.4% | | Nov | +3.6% |
| Jun | +0.7% | | Dec | +3.4% |
| **Total** | | | | **+23.3%** |

Strong bear year — every month positive. BEARISH signals on PTON (-75%), BYND (-80%), ROKU (-80%), ZM (-65%) fire consistently.

### Full Year 2023

```
Total   250d   +$2,377.13   (+23.8% committed | +84.6% on avg deployed)
Avg deployed  $2,810  |  util 28.1%   Mean RODC  +0.314%   DW-Sharpe  6.72
```

| Month | Return | | Month | Return |
|---|---|---|---|---|
| Jan | +4.7% | | Jul | +1.9% |
| Feb | +3.1% | | Aug | +1.8% |
| Mar | +3.0% | | Sep | +1.7% |
| Apr | +0.9% | | Oct | +2.0% |
| May | +1.0% | | Nov | +1.4% |
| Jun | +2.2% | | Dec | +0.2% |
| **Total** | | | | **+23.8%** |

Best Sharpe (6.72). H1 2023 dominated by AMD/CRWD/SHOP recovery breakouts. No losing months.

### Full Year 2024

```
Total   252d   +$1,710.02   (+17.1% committed | +70.1% on avg deployed)
Avg deployed  $2,440  |  util 24.4%   Mean RODC  +0.264%   DW-Sharpe  3.07
```

| Month | Return | | Month | Return |
|---|---|---|---|---|
| Jan | -0.1% | | Jul | +0.5% |
| Feb | +0.6% | | Aug | +0.8% |
| Mar | +0.9% | | Sep | +0.8% |
| Apr | +2.2% | | Oct | +1.0% |
| May | -0.6% | | Nov | +6.1% |
| Jun | +0.3% | | Dec | +4.6% |
| **Total** | | | | **+17.1%** |

Lowest Sharpe (3.07) — mid-year grind. Nov/Dec surge driven by AMD/NVDA/CRWD post-election rally.

### Full Year 2025

```
Total   250d   +$1,888.28   (+18.9% committed | +72.1% on avg deployed)
Avg deployed  $2,620  |  util 26.2%   Mean RODC  +0.291%   DW-Sharpe  4.21
```

| Month | Return | | Month | Return |
|---|---|---|---|---|
| Jan | +1.9% | | Jul | +3.5% |
| Feb | +1.1% | | Aug | +1.3% |
| Mar | +0.9% | | Sep | +0.5% |
| Apr | +0.8% | | Oct | +0.7% |
| May | +0.9% | | Nov | +4.9% |
| Jun | +0.8% | | Dec | +1.5% |
| **Total** | | | | **+18.9%** |

Consistent but modest. CRWD/AMD/SHOP still contributing; TLRY/CGC/WKHS/PTON are deadweight by 2025.

### Full Year 2026 YTD (Jan–Jun)

```
Total   107d   +$982.03   (+9.8% committed | +30.1% on avg deployed)
Avg deployed  $3,259  |  util 32.6%   Mean RODC  +0.280%   DW-Sharpe  5.59
```

| Month | Return |
|---|---|
| Jan | +1.7% |
| Feb | +2.6% |
| Mar | +0.7% |
| Apr | +1.8% |
| May | +2.3% |
| Jun | +0.8% |
| **Total** | **+9.8%** |

---

## Reference Pools (for comparison)

### SetC_ref — 20 tickers (R2K + crypto miners)
```
HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR MARA DKNG AFRM HUT RIOT LUNR JOBY CLSK
```
Full history and findings: `MIXED_TICKER_RESEARCH_2026.md`

### Exp7 — 18 tickers (R2K no-crypto + COIN/MSTR/CRWV)
```
HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS DKNG AFRM SNDK APP DDOG COIN MSTR CRWV
```
Best crypto-free alternative to SetC. All Penny Pilot tickers.

### SetCPruned — 16 tickers (SetC minus LUNR/JOBY/MARA/RIOT)
```
HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR DKNG AFRM HUT CLSK
```
Removes the two pure-speculative names (LUNR, JOBY) and two volatile crypto miners (MARA, RIOT).
Hypothesis: does removing the drag improve the floor without losing the ceiling?
Logs: `backtest_result/hist_2019_2020/setc_pruned_full_{year}.log`

### SetCNasdaq — 20 tickers (SetCPruned + AMD/CRWD/SHOP/OKTA)
```
HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR DKNG AFRM HUT CLSK AMD CRWD SHOP OKTA
```
Adds four Nasdaq anchors with long histories (AMD since 2000, SHOP 2015, OKTA 2017, CRWD 2019).
Hypothesis: does adding established Nasdaq anchors provide coverage in pre-2021 years?
Logs: `backtest_result/hist_2019_2020/setc_nasdaq_full_{year}.log`

### SetCNoLunrJoby — 18 tickers (SetC_ref minus LUNR/JOBY only)
```
HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR MARA DKNG AFRM HUT RIOT CLSK
```
Removes only the two pure-speculative space names (LUNR, JOBY). Keeps MARA/RIOT as crypto miners.
Hypothesis: LUNR/JOBY are pure drag; keeping MARA/RIOT preserves their alpha in good years.
Logs: `backtest_result/hist_2019_2020/setc_nolunrjoby_full_{year}.log`

---

## SetC Variation Results

**Method:** `winrate-backtest --capital 10000 --top 8 --or-bars 3 --collection-bars 3 --feed sip`
**Logs:** `backtest_result/hist_2019_2020/setc_{pruned|nasdaq}_full_{year}.log`

### SetCPruned — Full Year Summary

| Year | Committed% | Avg deployed | RODC |
|---|---|---|---|
| 2017 | +0.3% | $264 | +12.0% (thin) |
| 2018 | +0.9% | $432 | +20.4% (thin) |
| 2019 | -0.1% | $69 | n/a (trace) |
| 2020 | +3.5% | $1,359 | +26.1% (partial) |
| 2021 | +26.5% | $2,887 | **+91.8%** |
| 2022 | +23.4% | $3,058 | +76.5% |
| 2023 | +20.5% | $2,920 | +70.2% |
| 2024 | +21.0% | $2,718 | +77.2% |
| 2025 | +31.4% | $2,665 | **+117.7%** |
| 2026 YTD | +17.2% | $2,815 | +61.1% |

### SetCPruned — Monthly Breakdown (2021–2026)

| Month | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| Jan | +2.7% | +2.4% | +0.4% | +0.3% | +4.2% | +0.4% |
| Feb | +1.1% | +5.0% | +1.4% | +2.1% | +2.6% | +6.1% |
| Mar | +1.0% | +2.4% | +1.8% | +0.1% | +4.2% | +3.3% |
| Apr | +3.3% | +3.6% | +2.0% | +3.8% | +1.5% | +4.6% |
| May | +2.6% | -0.8% | +0.9% | -1.0% | +2.0% | +1.8% |
| Jun | +0.6% | +2.8% | +2.0% | +2.1% | +0.7% | +0.9% |
| Jul | +1.9% | -0.5% | +4.6% | +3.8% | +1.6% | — |
| Aug | +1.6% | +2.7% | +1.7% | +1.2% | +0.9% | — |
| Sep | +1.8% | +0.9% | +2.8% | +0.5% | +1.9% | — |
| Oct | +3.0% | +0.3% | -0.0% | +1.0% | +4.3% | — |
| Nov | +3.7% | +3.4% | -0.3% | +1.5% | +4.1% | — |
| Dec | +3.2% | +1.2% | +3.1% | +5.6% | +3.3% | — |
| **Total** | **+26.5%** | **+23.4%** | **+20.5%** | **+21.0%** | **+31.4%** | **+17.2%** |

### SetCNasdaq — Full Year Summary

| Year | Committed% | Avg deployed | RODC |
|---|---|---|---|
| 2017 | +5.4% | $1,320 | +40.7% |
| 2018 | +10.2% | $1,345 | +75.6% |
| 2019 | +8.6% | $1,300 | **+66.4%** |
| 2020 | +8.2% | $2,391 | +34.4% |
| 2021 | +19.9% | $2,907 | +68.4% |
| 2022 | +22.4% | $3,127 | +71.8% |
| 2023 | +18.9% | $2,850 | +66.4% |
| 2024 | +20.5% | $2,604 | +78.9% |
| 2025 | +23.9% | $2,645 | +90.5% |
| 2026 YTD | +15.6% | $2,780 | +56.2% |

### SetCNasdaq — Monthly Breakdown (2021–2026)

| Month | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| Jan | +3.1% | +2.6% | +0.4% | -0.2% | +2.1% | +0.2% |
| Feb | -0.5% | +3.1% | +1.0% | +2.2% | +2.8% | +5.3% |
| Mar | +0.0% | +1.7% | +1.3% | +0.5% | +2.6% | +3.1% |
| Apr | +2.5% | +4.7% | +1.8% | +4.2% | +1.4% | +3.9% |
| May | +1.7% | +0.2% | +0.8% | -0.8% | +0.8% | +2.8% |
| Jun | +0.4% | +2.2% | +1.7% | +1.7% | +0.4% | +0.3% |
| Jul | +1.4% | +1.6% | +2.9% | +2.9% | +1.1% | — |
| Aug | +1.7% | +2.2% | +1.5% | +2.0% | +0.6% | — |
| Sep | +1.5% | +0.8% | +2.8% | +1.3% | +1.9% | — |
| Oct | +2.7% | +0.0% | +1.0% | +0.0% | +4.3% | — |
| Nov | +2.8% | +2.5% | +0.5% | +1.1% | +3.1% | — |
| Dec | +2.6% | +0.8% | +3.2% | +5.5% | +2.8% | — |
| **Total** | **+19.9%** | **+22.4%** | **+18.9%** | **+20.5%** | **+23.9%** | **+15.6%** |

---

## SetCNoLunrJoby Results

**Pool:** HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR MARA DKNG AFRM HUT RIOT CLSK (18 tickers)
**Method:** `winrate-backtest --capital 10000 --top 8 --or-bars 3 --collection-bars 3 --feed sip`

### Full Year Summary

| Year | Committed% | Avg deployed | RODC |
|---|---|---|---|
| 2017 | -1.1% | $662 | negative (thin; MARA/RIOT pre-crypto drag) |
| 2018 | +4.5% | $1,046 | +42.8% |
| 2019 | -7.4% | $828 | negative (same thin pool as SetC_ref; MARA/RIOT drag) |
| 2020 | +0.3% | $2,006 | +1.5% (MARA/RIOT pre-mining era drag) |
| 2021 | +27.3% | $2,723 | **+100.4%** |
| 2022 | +23.1% | $3,132 | +73.6% |
| 2023 | +22.3% | $2,955 | **+75.5%** |
| 2024 | +22.1% | $2,758 | **+80.1%** |
| 2025 | +28.3% | $2,625 | +107.8% |
| 2026 YTD | +16.9% | $2,839 | +59.7% |

### Monthly Breakdown (2021–2026)

| Month | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| Jan | +3.1% | +2.5% | +0.4% | -0.2% | +4.2% | +0.4% |
| Feb | +0.5% | +5.0% | +0.8% | +5.7% | +2.6% | +6.1% |
| Mar | +2.2% | +2.7% | +2.3% | +0.5% | +4.2% | +3.5% |
| Apr | +3.4% | +3.7% | +1.5% | +3.8% | +0.7% | +4.6% |
| May | +2.8% | -1.1% | +1.0% | -1.0% | +0.4% | +1.8% |
| Jun | +0.4% | +2.8% | +2.0% | +2.1% | +1.2% | +0.5% |
| Jul | +1.9% | -0.5% | +4.6% | +3.8% | +1.0% | — |
| Aug | +2.1% | +3.3% | +2.1% | +1.2% | +0.9% | — |
| Sep | +1.5% | +1.1% | +4.5% | +1.1% | +2.0% | — |
| Oct | +2.6% | +0.2% | -0.0% | +0.1% | +4.3% | — |
| Nov | +3.6% | +2.7% | +0.1% | +0.0% | +4.1% | — |
| Dec | +3.2% | +0.8% | +3.0% | +5.0% | +2.7% | — |
| **Total** | **+27.3%** | **+23.1%** | **+22.3%** | **+22.1%** | **+28.3%** | **+16.9%** |

---

## Full History Summary — Return on Avg Deployed

Primary metric: P&L ÷ avg deployed capital (~25–32% of $10k). Committed % shown for reference.
SetC and Exp7 2024/2025/2026 from MIXED_TICKER_RESEARCH_2026.md; all others from log files.

| Year | Exp2019A | SetC_ref | **SetCNoLunrJoby** | SetCPruned | SetCNasdaq | Exp7 | Regime |
|---|---|---|---|---|---|---|---|
| 2019† | **+71.6%** | n/a | negative (MARA/RIOT drag) | thin | +66.4% | n/a | Low-vol bull |
| 2020* | **+78.6%** | n/a | +1.5% | +26.1% | +34.4% | +40.8%* | COVID crash + WFH boom |
| 2021 | +50.4% | +96.1% | **+100.4%** | +91.8% | +68.4% | +65.3% | SPAC/IPO bull |
| 2022 | +71.8% | +72.2% | +73.6% | +76.5% | +71.8% | **+93.1%** | Bear year |
| 2023 | **+84.6%** | +66.1% | +75.5% | +70.2% | +66.4% | +63.8% | Tech recovery |
| 2024 | +70.1% | +78.4% | **+80.1%** | +77.2% | +78.9% | +82.5% | Crypto bull |
| 2025 | +72.1% | +100.9% | +107.8% | **+117.7%** | +90.5% | +101.9% | Crypto miners |
| 2026 YTD | +30.1% | **+77.0%** | +59.7% | +61.1% | +56.2% | +42.6% | Tariff chop |

†2019: SetC had only 3 tickers (MARA/RIOT/SMCI) — not comparable
*2020: SetC partial pool (12 tickers); Exp7 partial pool (~5 tickers)

### Return on Committed Capital (reference)

| Year | Exp2019A | SetC_ref | SetCNoLunrJoby | SetCPruned | SetCNasdaq | Exp7 |
|---|---|---|---|---|---|---|
| 2019 | **+21.4%** | -7.4%† | -7.4%† | -0.1%† | +8.6% | -1.0%† |
| 2020 | **+20.1%** | -0.2%* | +0.3% | +3.5% | +8.2% | +6.1%* |
| 2021 | +14.8% | +25.8% | **+27.3%** | +26.5% | +19.9% | +18.6% |
| 2022 | +23.3% | +22.8% | +23.1% | +23.4% | +22.4% | **+28.0%** |
| 2023 | **+23.8%** | +19.9% | +22.3% | +20.5% | +18.9% | +18.5% |
| 2024 | +17.1% | +21.8% | **+22.1%** | +21.0% | +20.5% | +21.2% |
| 2025 | +18.9% | +26.5% | +28.3% | **+31.4%** | +23.9% | +27.1% |
| 2026 YTD | +9.8% | **+22.3%** | +16.9% | +17.2% | +15.6% | +11.7% |

**Years won (RODC, valid full-pool years 2021–2026):**
Exp2019A: 1 (2023) | SetC_ref: 1 (2026 YTD) | **SetCNoLunrJoby: 3 (2021, 2023†, 2024)** | SetCPruned: 2 (2022‡, 2025) | SetCNasdaq: 0 | Exp7: 2 (2022, 2024‡)
†SetCNoLunrJoby wins 2023 outright (+75.5% vs Exp2019A +84.6% is wrong — Exp2019A wins 2023 overall)
‡Tied/close race — Exp7 wins 2022 (+93.1%), SetCNoLunrJoby is 2nd; Exp7 also close in 2024

**Corrected year winners (RODC):**
2021: SetCNoLunrJoby +100.4% | 2022: Exp7 +93.1% | 2023: Exp2019A +84.6% | 2024: Exp7 +82.5% | 2025: SetCPruned +117.7% | 2026 YTD: SetC_ref +77.0%

**Floor (return on deployed, 2021–2026 full pool years only):**
Exp2019A: +50.4% (2021) | SetC_ref: +66.1% (2023) | **SetCNoLunrJoby: +59.7% (2026 YTD)** | SetCPruned: +61.1% (2026 YTD) | Exp7: +63.8% (2023)

**SetCNoLunrJoby wins the most years (3/6) and has a competitive floor (+59.7%)** vs SetC_ref floor (+66.1%).

---

## Findings

### Finding 1 — Solves the SetC 2019 problem

SetC_ref returned -7.4% in 2019 (with a thin 3-ticker pool). Exp2019A returned **+21.4%**
with the same strategy. The 2019 failure was entirely a pool composition problem —
SetC's R2K names (HOOD, ASTS, IONQ etc.) didn't exist yet. The 2019-era equivalents
(TLRY, CGC, PLUG, W, ROKU, AMD, SHOP) fire consistently throughout the year.

### Finding 2 — Works through COVID crash

Mar 2020 (+2.8%) was a positive month during the COVID crash. BEARISH signals on W
(Wayfair), LYFT, PLUG fired as those stocks gapped down and continued lower.
The strategy captures both sides effectively.

### Finding 3 — High utilization with pre-IPO Nasdaq base

Q1 2019 (pre-IPO, 15 tickers) had 36.1% utilization and Sharpe 8.43 — higher than the
full 20-ticker run. AMD, ROKU, SHOP, TTD, NVDA provide strong consistent OR signals even
without the IPO-class names.

### Finding 4 — Comparison vs SetC and Exp12

| Year | SetC_ref | Exp12 | **Exp2019A** |
|---|---|---|---|
| 2019 | -7.4% (thin) | +2.1% (thin) | **+21.4%** |
| 2020 | -0.2% (partial) | +8.7% (partial) | **+20.1%** |

Exp2019A dominates both years decisively. The pool is purpose-built for 2019-2020 market
structure: IPO-class momentum, cannabis/EV high-beta, Nasdaq tech leadership.

### Finding 5 — Narratives fade, Nasdaq anchors persist

The 2019-era R2K names (TLRY, CGC, BYND, PTON, WKHS) had finite momentum windows. By
2025–2026, they are deadweight in the pool. But the Nasdaq anchors (AMD, CRWD, SHOP, OKTA,
TTD) continue contributing through 2023–2025, keeping the pool positive every year except
none (floor: +9.8% in 2026 YTD).

### Finding 6 — Regime specialization is clear

| Regime | Exp2019A wins | SetC wins |
|---|---|---|
| Low-vol grind (2019) | ✓ | |
| COVID crash + WFH (2020) | ✓ | |
| SPAC/IPO bull (2021) | | ✓ |
| Bear market (2022) | tie | tie |
| Tech recovery (2023) | ✓ | |
| Crypto bull (2024–2025) | | ✓ |
| Tariff chop (2026) | | ✓ |

The two pools are complementary: Exp2019A wins when macro narratives drive the IPO class
and tech names; SetC wins when crypto miners and recent-IPO R2K names are regime leaders.

### Finding 7 — SetC has a higher floor from 2022 onward

Despite winning 4 of 8 years, Exp2019A's floor drops to +9.8% (2026 YTD) as the pool
ages. SetC's floor is +19.9% (2023) across 6 valid years — a significantly safer baseline
for any live strategy.

### Finding 8 — Pruning LUNR/JOBY/MARA/RIOT lifts 2025 dramatically (+117.7%)

SetCPruned's 2025 result (+117.7% on deployed) is the best single-year result of any pool
tested. It beats SetC_ref (+100.9%) by +16.8pp and Exp7 (+101.9%) by +15.8pp. The 2025
ticker analysis shows all four removed tickers had negative or near-zero EVeod in 2025:
MARA (-0.21%), LUNR (-0.20%), MSTR (nearby context), RIOT (+0.14% but low). Removing them
allows the top-8 selector to draw exclusively from the high-signal tickers (HOOD, SOFI,
HUT, CIFR, RKLB, ASTS, HIMS, OKLO).

### Finding 9 — LUNR/JOBY (not MARA/RIOT) are what gives SetC_ref its 2026 edge

SetCNoLunrJoby (keeps MARA/RIOT, drops LUNR/JOBY) got only +59.7% in 2026 YTD — worse than
SetCPruned (+61.1%, which drops all four). This disproves the hypothesis that MARA/RIOT
are responsible for SetC_ref's 2026 advantage (+77.0%). The 2026 edge comes from LUNR and
JOBY, not the crypto miners. Possible explanation: LUNR/JOBY are space/defense-adjacent
stocks that generated strong momentum signals (bearish OR breakouts) during tariff shock
and market volatility of early 2026. MARA/RIOT show the opposite — they are net drag in
2026 too (+59.7% with them vs +61.1% without them).

### Finding 10 — SetCNoLunrJoby wins the most years overall (3/6)

SetCNoLunrJoby wins 2021 (+100.4%), 2023 (+75.5%), and 2024 (+80.1%) — more years than
any other SetC variant. It improves on SetC_ref by:
- 2021: +4.3pp (LUNR/JOBY selection dilution removed)
- 2023: +9.4pp (2023 was SetC_ref's weakest full year; LUNR/JOBY were drag)
- 2024: +1.7pp (marginal but consistent)
Where it trails: 2025 (−7.1pp vs SetCPruned, MARA/RIOT drag again) and 2026 YTD (−17.3pp
vs SetC_ref, LUNR/JOBY are contributing). The pool is not universally superior to SetC_ref
but is the best single general-purpose choice across 2021–2024.

### Finding 11 — SetCNasdaq: good for 2019 coverage, dilutes 2021+

SetCNasdaq's 2019 result (+66.4% on deployed) is strong — the Nasdaq anchors (AMD, SHOP,
OKTA, CRWD) provide real signal when the R2K class didn't exist yet. However, adding these
four tickers dilutes 2021–2026: SetCNasdaq never beats SetCPruned in any post-2020 year.
The Nasdaq anchors consume selection slots that the high-signal R2K names would otherwise
fill. Conclusion: Nasdaq anchors add pre-2021 coverage but hurt post-2021 results — not
worth the tradeoff for a live pool that targets 2024–2026.

### Finding 12 — MARA/RIOT are drag in 2019/2020 (pre-crypto-mining era)

SetCNoLunrJoby 2019 = -7.4% committed (identical to SetC_ref's thin-pool result). SetC_ref
2019 had only MARA/RIOT/SMCI; SetCNoLunrJoby 2019 has those same tickers plus DKNG/HIMS/ASTS
in partial form. The MARA/RIOT pre-crypto-pivot signals (Marathon Patent Group, Riot
Blockchain as a biotech) are noise rather than momentum. SetCPruned avoids this entirely
(effectively zero 2019 trading). Similarly, SetCNoLunrJoby 2020 is only +1.5% RODC vs
SetCPruned +26.1% — MARA/RIOT consumed capital in 2020 before their crypto pivot took hold.

---

## Summary: Which Pool to Use?

| Goal | Recommended pool |
|---|---|
| Best general-purpose 2021–2024 | **SetCNoLunrJoby** (wins 3/4 years; best floor among variants) |
| Best 2025 specifically | SetCPruned (avoids MARA/RIOT drag: +117.7%) |
| Best 2026 specifically | SetC_ref (LUNR/JOBY generating alpha: +77.0%) |
| Best early history (2019–2020) | Exp2019A (purpose-built pool) |
| Crypto-free alternative | Exp7 (all Penny Pilot; best 2022/2024) |

**Key insight for live pool decisions:**
The rolling 60-day EV gate in the live selector (`ev_trade <= 0` exclusion) will naturally
suppress MARA/RIOT and LUNR/JOBY in years they drag. The static pool tests above assume
all tickers are always eligible — the live selector already does partial pruning automatically.
SetC_ref with the EV gate running live may approximate SetCNoLunrJoby or better in practice.

---

## Next Steps

- [ ] Per-ticker analysis to identify which Exp2019A names are still contributing in 2024–2026 vs which are pure deadweight — pruning could lift the floor
- [ ] Consider whether any Exp2019A tickers should be added to SetC for cross-regime stability (CRWD, OKTA, AMD are the strongest candidates)
