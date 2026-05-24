# Ranking Formula Retune

**Current formula:**
```
score = entry_vs_mid_pct × 0.50 + avg_win_pct × 0.30 + or_range_pct × 0.20
```
Hard gate: `ev_trade ≤ 0 → excluded` (ticker not eligible that day).

**Base config for all experiments:**
`--top 2 --window M1 09:30 3 --feed sip --min-hold-bars 1 --lookback 45`

**Baselines:**
- lb60 8yr sum: +31.7% (original default)
- lb45 8yr sum: +63.2% (current best — new baseline to beat)

---

## Motivation

From prior tests:
- Scoring beats random by +39pp over 8 years → formula has real signal
- But anti-predictive in 2024 (−10pp vs random) and 2025 (−15pp vs random)
- `avg_win_pct` (0.30 weight) uses 45d rolling history → lags regime shifts
- `avg_loss_pct` is computed but never scored
- `or_vol_ratio` always computed (with acceleration boost) but weighted at 0.00
- Only `entry_vs_mid_pct` and `or_vol_ratio` weights are CLI-controllable; `avg_win_pct = 0.30` is hardcoded

---

## Phase 1 — Factor Ablation

**Goal:** Identify what each factor contributes individually. Find out if one factor dominates or if blending is actually better.

**New flag added:** `--score-avg-win-weight` (exposes the hardcoded 0.30)

All tests: `--lookback 45`, M1-only.

| ID | entry | avg_win | or_range | vol | Label |
|---|---|---|---|---|---|
| A1 | 1.00 | 0.00 | 0.00 | 0.00 | pure entry_vs_mid |
| A2 | 0.00 | 1.00 | 0.00 | 0.00 | pure avg_win_pct |
| A3 | 0.00 | 0.00 | 1.00 | 0.00 | pure or_range_pct |
| A4 | 0.34 | 0.33 | 0.33 | 0.00 | equal thirds |
| A5 | 0.50 | 0.30 | 0.20 | 0.00 | current baseline (control) |

### Results (2019–2026)

| Year | lb45 base | A1 entry | A2 avg_win | A3 or_range | A4 equal | A5 current |
|---|---|---|---|---|---|---|
| 2019 | +18.1% | +15.7% | +3.7% | +10.4% | +13.5% | +18.1% |
| 2020 | +16.1% | +21.0% | +3.2% | +14.7% | +17.8% | +16.1% |
| 2021 | +5.1% | +7.4% | +4.1% | +9.6% | +8.3% | +5.1% |
| 2022 | -1.1% | +20.0% | +2.8% | +5.1% | +10.1% | -1.1% |
| 2023 | +5.9% | -6.3% | +0.2% | -1.0% | -1.4% | +5.9% |
| 2024 | -11.6% | -8.8% | +2.8% | -3.6% | -4.6% | -11.6% |
| 2025 | -5.6% | -5.2% | +2.5% | -4.4% | -4.3% | -5.6% |
| 2026 | +36.3% | +36.8% | +1.2% | +37.0% | +35.0% | +36.3% |
| **8yr sum** | **+63.2%** | **+80.5%** | **+20.5%** | **+67.8%** | **+74.4%** | **+63.2%** |

**Finding:** `avg_win_pct` alone is nearly useless (+20.5%). `entry_vs_mid_pct` alone (+80.5%) beats the blended formula (+63.2%). The current formula dilutes the strongest signal with a weak one.

---

## Phase 2 — or_vol_ratio Weight Sweep

**Goal:** Test whether OR volume vs rolling avg predicts follow-through.  
**No code changes** — uses existing `--score-vol-ratio-weight` flag.  
`or_range_pct` absorbs the displaced weight (residual = 1 − 0.50 − 0.30 − vol_weight).

All tests: `--lookback 45`, M1-only.

| ID | entry | avg_win | or_range | vol | Label |
|---|---|---|---|---|---|
| C0 | 0.50 | 0.30 | 0.20 | 0.00 | baseline (no vol) |
| C1 | 0.50 | 0.30 | 0.15 | 0.05 | vol light |
| C2 | 0.50 | 0.30 | 0.10 | 0.10 | vol moderate |
| C3 | 0.50 | 0.30 | 0.05 | 0.15 | vol heavy |
| C4 | 0.50 | 0.30 | 0.00 | 0.20 | vol replaces or_range |

### Results (2019–2026)

| Year | lb45 base | C1 v0.05 | C2 v0.10 | C3 v0.15 | C4 v0.20 |
|---|---|---|---|---|---|
| 2019 | +18.1% | +18.6% | +18.0% | +19.4% | +19.9% |
| 2020 | +16.1% | +14.1% | +15.0% | +14.7% | +15.9% |
| 2021 | +5.1% | +5.3% | +7.2% | +9.6% | +9.6% |
| 2022 | -1.1% | +0.7% | +3.2% | +5.1% | +2.8% |
| 2023 | +5.9% | +5.7% | +4.3% | -1.0% | -1.7% |
| 2024 | -11.6% | -11.5% | -10.4% | -3.6% | -9.2% |
| 2025 | -5.6% | -5.4% | -5.4% | -4.4% | -3.9% |
| 2026 | +36.3% | +37.2% | +35.6% | +37.0% | +38.3% |
| **8yr sum** | **+63.2%** | **+64.7%** | **+66.8%** | **+74.5%** | **+71.7%** |

**Finding:** `or_vol_ratio` at vol=0.15 adds +11.3pp. Replacing `avg_win` with vol entirely is also good (+8.5pp). C3 is the best vol configuration.

---

## Phase 1+2 Combinations — "Drop avg_win, redistribute"

Best single factors from ablation: entry (strong) + vol_ratio (moderate). Test combinations where avg_win=0 and entry+vol dominate.

| ID | entry | avg_win | or_range | vol | Label |
|---|---|---|---|---|---|
| E1 | 0.80 | 0.00 | 0.05 | 0.15 | **WINNER** — entry heavy + vol moderate |
| E2 | 0.65 | 0.00 | 0.20 | 0.15 | entry medium + vol moderate |
| E3 | 0.50 | 0.00 | 0.35 | 0.15 | or_range absorbs avg_win |
| E4 | 0.70 | 0.00 | 0.15 | 0.15 | entry heavy + vol moderate balanced |
| E5 | 0.85 | 0.00 | 0.00 | 0.15 | max entry + vol |

### Results (2019–2026)

| Year | lb45 base | A1(e=1.0) | C3(v=.15) | E1(e.80v.15) | E2(e.65v.15) | E3(e.50v.15) | E4(e.70v.15) | E5(e.85v.15) |
|---|---|---|---|---|---|---|---|---|
| 2019 | +18.1% | +15.7% | +17.1% | **+17.8%** | +17.6% | +17.1% | +18.1% | +17.8% |
| 2020 | +16.1% | +21.0% | +14.7% | +20.8% | +19.7% | **+21.7%** | +20.1% | +21.2% |
| 2021 | +5.1% | +7.4% | +9.6% | **+10.1%** | +6.2% | +5.8% | +6.3% | +10.1% |
| 2022 | -1.1% | **+20.0%** | +5.1% | +13.1% | +6.4% | +5.6% | +10.7% | +12.9% |
| 2023 | **+5.9%** | -6.3% | -1.0% | -2.4% | -2.8% | +2.1% | -1.2% | -3.0% |
| 2024 | -11.6% | -8.8% | **-3.6%** | -9.3% | -12.6% | -13.0% | -8.4% | -10.0% |
| 2025 | -5.6% | -5.2% | -4.4% | **-1.2%** | -2.7% | -6.3% | -1.8% | -3.1% |
| 2026 | +36.3% | +36.8% | +37.0% | **+39.0%** | +36.3% | +35.4% | +35.3% | +36.3% |
| **8yr sum** | **+63.2%** | +80.5% | +74.5% | **+87.8%** | +68.2% | +68.4% | +79.2% | +82.2% |

**E1 is the winner: +87.8% (+24.6pp over lb45 baseline)**

---

## Phase 3 — EV Trend Signal

**Goal:** Reward tickers whose recent performance is *accelerating* vs their 45d rolling average.  
Signal: `ev_trend = ev_trade_15d − ev_trade_45d` (positive = heating up, negative = fading).

**New additions:**
- `compute_ticker_stats()` returns `ev_trend` = 15d EV − 45d EV
- `score_ticker()` takes `score_ev_trend_weight` param
- CLI: `--score-ev-trend-weight`, `--ev-trend-days`
- `avg_win_pct` weight reduced by ev_trend weight to keep sum = 1.0

All tests: `--lookback 45`, recent window = 15d, M1-only.

| ID | entry | avg_win | or_range | ev_trend | Label |
|---|---|---|---|---|---|
| B1 | 0.50 | 0.20 | 0.20 | 0.10 | light trend signal |
| B2 | 0.50 | 0.10 | 0.20 | 0.20 | moderate trend signal |
| B3 | 0.50 | 0.00 | 0.20 | 0.30 | avg_win fully replaced by trend |

### Results (2019–2026)

| Year | lb45 base | B1 t0.10 | B2 t0.20 | B3 t0.30 |
|---|---|---|---|---|
| 2019 | +18.1% | +17.0% | +11.8% | +5.6% |
| 2020 | +16.1% | +16.9% | +21.9% | +18.7% |
| 2021 | +5.1% | +4.0% | -1.2% | -3.5% |
| 2022 | -1.1% | +4.2% | +5.8% | +7.6% |
| 2023 | +5.9% | +9.1% | +4.6% | +10.3% |
| 2024 | -11.6% | -11.7% | -12.4% | -9.5% |
| 2025 | -5.6% | -3.9% | -3.1% | -0.0% |
| 2026 | +36.3% | +35.5% | +40.2% | +43.5% |
| **8yr sum** | **+63.2%** | **+71.0%** | **+67.7%** | **+72.7%** |

**Finding:** EV trend adds modest +7–10pp over lb45 but DOES NOT beat E1 (+87.8%). The signal improves 2022 and 2025 but hurts 2019 and 2021. Best standalone result is B3 (+72.7%).

**Combination test — E1 + ev_trend (entry=0.80, vol=0.15, ev_trend=0.05, avg_win=0.00, or_range=0.00):**
8yr sum = +81.2% — WORSE than E1 alone by -6.6pp. Signals do not stack beneficially.

---

## Phase 4 — Direction-Split EV Gate

**Goal:** Apply EV gate per signal direction (BULLISH/BEARISH separately).

**New flag:** `--direction-split-ev` (boolean)  
**Scope:** Gate only — blended avg_win_pct stays in the score.

All tests: `--lookback 45`, M1-only.

| ID | Flags | Description |
|---|---|---|
| D1 | `--direction-split-ev` | Direction gate + current baseline weights |
| D2 | `--direction-split-ev` + E1 weights | Direction gate + best weights found |

### Results (2019–2026)

| Year | lb45 base | D1 | D2 |
|---|---|---|---|
| 2019 | +18.1% | +9.2% | +10.2% |
| 2020 | +16.1% | +12.4% | +16.6% |
| 2021 | +5.1% | +6.6% | +16.2% |
| 2022 | -1.1% | **-25.3%** | -7.9% |
| 2023 | +5.9% | +6.8% | +8.8% |
| 2024 | -11.6% | -13.4% | -10.1% |
| 2025 | -5.6% | -12.8% | -9.6% |
| 2026 | +36.3% | +30.4% | +18.9% |
| **8yr sum** | **+63.2%** | **+13.9%** | **+43.1%** |

**DISQUALIFIED.** Direction-split gate is catastrophically bad. D1: -49.3pp vs lb45. D2: -20.1pp vs lb45. 2022 D1 = -25.3% (vs -1.1% baseline). The gate removes too many valid tickers — in weak years bearish-only or bullish-only tickers represent real signal, but the gate cuts them.

---

## Phase 5 — Combine Winners + SOA Validation

**E1 is the sole winner** from Phases 1–4. B3 and B1 beat lb45 but not E1; combining them hurts.

E1 on full SOA config (M1+A1+A2 + reversal + BRE + BRU + DD) — see below.

---

## Findings Summary

| Phase | Best config | 8yr M1-only | vs lb45 |
|---|---|---|---|
| Phase 1 (ablation) | A1: pure entry (e=1.0) | +80.5% | +17.3pp |
| Phase 2 (vol_ratio) | C3: vol=0.15 | +74.5% | +11.3pp |
| Phase 1+2 combo | **E1: entry=0.80, vol=0.15, avg_win=0.00** | **+87.8%** | **+24.6pp** |
| Phase 3 (ev_trend) | B3: ev_trend=0.30 | +72.7% | +9.5pp |
| Phase 4 (dir-split) | DISQUALIFIED | +13.9% | -49.3pp |
| E1+ev_trend combo | Stacks worse than E1 | +81.2% | +18.0pp |
| **Final winner** | **E1 (entry=0.80 vol=0.15 avg_win=0.00)** | **+87.8%** | **+24.6pp** |

### SOA Validation (full production config)

`--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal --bearish-reentry --bullish-reentry --doubledown --doubledown-start 5 --lookback 45`

| Year | SOA base (lb45) | SOA + E1 weights | delta |
|---|---|---|---|
| 2019 | +31.26% | +28.32% | -2.94pp |
| 2020 | +14.42% | +31.98% | **+17.56pp** |
| 2021 | +29.09% | +26.37% | -2.72pp |
| 2022 | +6.18% | +18.95% | **+12.77pp** |
| 2023 | +60.87% | +52.34% | -8.53pp |
| 2024 | +17.55% | +21.41% | +3.86pp |
| 2025 | +20.90% | +29.50% | **+8.60pp** |
| 2026 | +50.83% | +53.57% | +2.74pp |
| **8yr sum** | **+231.1%** | **+262.4%** | **+31.3pp** |

**E1 improves SOA config by +31.3pp (8yr), wins 5 of 8 years.**  
E1 is particularly strong in volatile/bear years: 2020 (+17.6pp), 2022 (+12.8pp), 2025 (+8.6pp).  
SOA base wins only 2019, 2021, and 2023 (pure bull years where avg_win_pct had real predictive signal).

**Final recommendation:** Use `--score-entry-weight 0.80 --score-avg-win-weight 0.00 --score-vol-ratio-weight 0.15` for all production runs.

---

## Oracle Picker — Theoretical Selection Ceiling

**Purpose:** Establish the upper bound on return achievable through perfect ticker selection, holding all other trade mechanics (entry/stop/exit) constant.

**Methodology:** `--oracle-picks` runs the full backtest for all tickers every day using the real entry/stop/exit rules, then picks the top-2 by actual realized P&L — pure hindsight. This is **not a tradeable strategy**; it is a benchmark.

**Run:** `--oracle-picks --top 2 --window M1 09:30 3 --lookback 45 --start 2026-01-01 --end 2026-05-23`

### Results — Full oracle ceiling table (2022–2026)

| Year | Oracle return | Oracle WR | E1 scored | E1 capture | QQQ B&H |
|---|---|---|---|---|---|
| 2022 | **+351.98%** | 65% | +18.95% | 5.4% | -33.71% |
| 2023 | **+310.27%** | 73% | +52.34% | 16.9% | +54.84% |
| 2024 | **+271.66%** | 75% | +21.41% | 7.9% | +26.99% |
| 2025 | **+297.10%** | 74% | +29.50% | 9.9% | +20.40% |
| 2026 YTD | **+181.79%** | 73% | +36.66% | 20.2% | +17.03% |

### Results (2026 YTD detail)

| Picker | Return | Win Rate | EV/trade | Avg win | Avg loss |
|---|---|---|---|---|---|
| **Oracle (perfect hindsight)** | **+181.79%** | **76%** | **+1.884%** | +2.58% | -0.28% |
| E1 scored (entry=0.80, vol=0.15) | +36.66% | 37% | +0.392% | — | — |
| Random (EV-gated, seed=42) | +3.74% | 35% | +0.040% | — | — |
| QQQ buy-and-hold | +17.03% | — | — | — | — |

### Monthly oracle breakdown

| Month | Picks | W/L | Return% |
|---|---|---|---|
| Jan 2026 | 40 | 32W/8L | +39.73% |
| Feb 2026 | 37 | 31W/6L | +63.93% |
| Mar 2026 | 43 | 34W/9L | +21.99% |
| Apr 2026 | 41 | 30W/11L | +34.84% |
| May 2026 | 32 | 19W/13L | +21.30% |
| **Total** | **193** | **146W/47L** | **+181.79%** |

### Key findings

1. **Ceiling = +181.79% YTD** with the M1 morning-only config. Adding afternoon windows (A1, A2) and SOA features would raise this further.
2. **Oracle WR cap = 76%.** Even with perfect selection, 1-in-4 trades lose because the OR momentum setup itself fails on those days. No scorer can ever exceed ~76% WR on M1 picks.
3. **E1 captures ~20% of ceiling.** The 4.9× gap (+36.66% vs +181.79%) is entirely a selection problem — the trade execution logic is correct.
4. **Avg loss asymmetry.** Oracle avg loss is only -0.28% vs avg win +2.58% — a 9:1 win/loss ratio. The hard stop rules are working; the problem is picking the wrong ticker, not the stops being too loose.
5. **No losing months.** Oracle had positive returns every month in 2026 YTD. May was the weakest (3W/7L in W18) but still +21.30% for the month overall.

---

## MA Momentum Gate Analysis (Jan 2025)

**Config:** `--top 2 --window M1 09:30 3 --bearish-reentry --bullish-reentry --reversal --start 2025-01-01 --end 2025-01-31 --feed sip --min-hold-bars 1 --stop-pct 0.4 --ma-momentum-gate`

**Gate rule:** BULLISH signal requires OR range overlapping or above both 5-min MA20 and MA50, and close > MA20 or MA50. BEARISH is the mirror.

### Oracle vs base comparison (Jan 2025)

| Metric | Oracle | Base |
|--------|--------|------|
| Total P&L | +53.91% | −6.17% |
| Trades | 40 | 19 |
| Win rate | 75% | 21% |
| Slots matched | 2/40 | — |

**60pp gap breakdown:**

| Root cause | Approx gap | Description |
|------------|-----------|-------------|
| EV gate blocks Jan runners | ~40pp | MSTR, CRDO, COIN, APP, MU, MRVL, CVNA, PLTR all had negative rolling 60d EV entering Jan from bad Nov–Dec 2024 |
| MA momentum gate over-filters | ~18pp | 6 zero-pick days (Jan 8, 14, 15, 17, 22, 27) — oracle picks 2 winners each; gate blocks all signals |
| Scoring puts META over better tickers | ~10pp | META has strong rolling EV stats but was in downtrend; base picks META as rank#1 while oracle picks SHOP/COIN/CHTR |

**Key observation:** EV gate is anti-predictive at regime inflection points. The 9 best Jan 2025 tickers (CRDO +6.57%, MSTR +6.41%, COIN +4.59%, SHOP +4.76%, APP +3.41%, MU +3.41%) all had negative rolling EV entering Jan because their Nov–Dec 2024 was weak — exactly when the regime shifted.

---

## Walk-Forward Parameter Sweep (Dec 2024 → Jan 2025)

**Question:** Can tuning entry time, bar count, and stop-pct on Dec 2024 improve Jan 2025 performance?

**Sweep space:** 3 entry times × 5 bar counts × 6 stop-pct = 90 combos  
**Script:** `alpha_tech_tracker/op_momentum_strategy/param_sweep.py`

### Train/test correlation: +0.004 (essentially zero)

Dec 2024 P&L has no predictive power over Jan 2025 P&L. Of 90 combos, 88 lost money in either Dec or Jan (or both).

### Two configs profitable in BOTH months

| Config | Dec 2024 | Jan 2025 | Notes |
|--------|----------|---------|-------|
| `09:40 / 2 bars / stop 0.30` | +7.93% | +9.44% | Best train AND #4 test |
| `09:40 / 2 bars / stop 0.20` | +6.33% | +6.58% | #2 train AND #10 test |

**Structural findings:**
- `09:40` entry time is consistently better than `09:30` or `09:35` for this config — extra 10 min lets MA momentum gate use more settled values
- 2-bar OR window at `09:40` (9:40–9:50 = 20-min window) is the sweet spot
- Tight stops (0.20–0.30) beat wider stops (0.40+) in both months
- `09:35/1b/` configs were best in Jan (+16.6%) but worst in Dec (−17.9%) — pure noise, not usable

**Recommendation:** Consider `--window M1 09:40 2 --stop-pct 0.3` as a more robust alternative to `09:30 3 / stop 0.4`. Recovers ~13pp of the ~60pp oracle gap vs EV gate, but EV gate remains the dominant bottleneck.

---

## Per-Ticker Stats Analysis — 2025 Full Year

**Config:** Same as MA momentum gate analysis above, applied to all 12 months of 2025.

### 2025 yearly totals per ticker

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% | Verdict |
|--------|--------|-----|-----|-------|-------|-------|--------|---------|
| CVNA | +42.47% | 43% | 2.10 | +1.88% | −0.89% | +12.62% | −2.84% | CONSISTENT |
| APP | +25.09% | 43% | 1.66 | +1.69% | −1.01% | +7.10% | −5.74% | CONSISTENT |
| COIN | +22.45% | 36% | 2.14 | +1.85% | −0.86% | +14.17% | −2.35% | HIGH-BETA |
| TSLA | +21.11% | 45% | 1.70 | +1.41% | −0.83% | +5.85% | −5.29% | CONSISTENT |
| CLS | +7.99% | 37% | 1.96 | +2.23% | −1.14% | +12.17% | −3.78% | MIXED |
| MRVL | +6.31% | 40% | 1.94 | +1.53% | −0.79% | +4.11% | −1.85% | MIXED |
| META | +6.12% | 43% | 1.50 | +0.75% | −0.50% | +2.88% | −1.28% | MIXED |
| EXPE | +4.69% | 40% | 1.54 | +0.91% | −0.59% | +4.25% | −3.04% | MIXED |
| MU | +4.29% | 40% | 1.57 | +1.14% | −0.73% | +6.41% | −2.01% | MIXED |
| CRWV | +3.68% | 37% | 1.75 | +2.77% | −1.58% | +12.17% | −3.98% | MIXED |
| CHTR | +3.64% | 35% | 1.98 | +1.07% | −0.54% | +3.16% | −2.15% | MIXED |
| PLTR | +2.94% | 43% | 1.39 | +1.25% | −0.90% | +4.30% | −2.82% | MIXED |
| AMD | +0.56% | 36% | 1.83 | +1.32% | −0.72% | +4.63% | −1.61% | MIXED |
| MSTR | −0.35% | 31% | 2.43 | +2.20% | −0.90% | +7.46% | −3.82% | HIGH-BETA |
| SHOP | −2.43% | 36% | 1.62 | +1.25% | −0.77% | +4.77% | −2.44% | MIXED |
| JPM | −6.22% | 34% | 1.56 | +0.58% | −0.37% | +2.75% | −1.51% | MIXED |
| CRDO | −25.51% | 32% | 1.96 | +2.36% | −1.20% | +6.66% | −5.44% | AVOID |

### Monthly P&L grid (abridged — months 01–12)

```
Ticker   01      02      03      04      05      06      07      08      09      10      11      12
CVNA   -2.31   +4.57   +8.25  +21.06   -1.23   -0.58   -5.39   +3.72   +5.76   +4.08   +0.16   +4.38
APP    -3.57   +2.45   +6.26   +7.63   -0.90   -1.52   -0.11   +5.46   -5.69   +3.53   +8.88   +2.65
COIN   -2.52   +9.68   -3.26   -3.63   +3.68  +27.58   +2.12   -2.08   -2.96   +0.26   -3.04   -3.39
TSLA   -5.38   +5.76   -2.47   +0.03   -1.16   +7.48   +0.01   +9.50   +0.95   +1.31   +4.78   +0.29
CRDO   +1.90   -1.95   -3.50   +4.93   -2.82   +0.25   -3.33   +7.51  -19.34   -2.80   +0.57   -6.94
JPM    -2.43   +3.84   +0.85   -2.37   -0.70   -0.07   +0.22   -2.35   -0.54   -1.91   -1.19   +0.41
```

### Monthly pool health

| Month | # Positive / Active | Pool total | Regime |
|-------|---------------------|-----------|--------|
| 2025-01 | 4/16 | −33.6% | Bearish/choppy |
| 2025-02 | 12/16 | +46.6% | Strong bull |
| 2025-03 | 8/16 | +4.7% | Neutral |
| 2025-04 | 10/17 | +26.0% | Bull |
| 2025-05 | 8/17 | +8.3% | Mild bull |
| 2025-06 | 10/17 | +44.6% | Strong bull |
| 2025-07 | 11/17 | +15.7% | Bull |
| 2025-08 | 9/17 | +30.3% | Bull |
| 2025-09 | 4/17 | −51.0% | **Selloff** |
| 2025-10 | 7/17 | −7.5% | Weak/choppy |
| 2025-11 | 12/17 | +35.6% | Strong bull |
| 2025-12 | 8/17 | −2.8% | Mixed |

### Filtering patterns identified

**Pattern 1 — W/L ratio alone is insufficient**
- MSTR: W/L 2.43 → near-zero total (−0.35%). CRDO: W/L 1.96 → −25.5%.
- High W/L only means wins > losses when they occur; a single bad month (CRDO Sep −19.3%) destroys the year.
- Better gate: **W/L ≥ 1.5 AND worst rolling monthly drawdown ≤ −6%**

**Pattern 2 — Win rate ≥ 38% is a strong predictor of yearly profitability**

| WR tier | Tickers | Avg yearly P&L |
|---------|---------|---------------|
| ≥ 43% | CVNA, APP, META, TSLA, PLTR | +20.3% avg |
| 38–42% | MRVL, EXPE, MU, AMD | +4.0% avg |
| < 38% | COIN, CHTR, SHOP, JPM, CRDO, MSTR | +0.7% avg |

**Pattern 3 — Monthly pool vote as regime signal**
When ≥ 10/17 tickers have positive rolling EV → favorable regime (Feb +46.6%, Jun +44.6%, Nov +35.6%). When ≤ 4/17 positive → skip or reduce size (Jan −33.6%, Sep −51.0%).

**Pattern 4 — Direction split matters per ticker**

| Ticker | Bull 2025 total | Bear 2025 total | Implication |
|--------|----------------|----------------|-------------|
| EXPE | −1.29% | +3.80% (67% WR) | Bearish-only edge |
| SHOP | +4.37% | −0.64% | Bullish-only edge |
| PLTR | +0.67% | −5.71% (0% WR) | Kill bear signals |
| MSTR | +3.15% | −2.90% | Bullish-only |
| MU | +2.86% | −3.28% | Bullish-only |

**Actionable filters (priority order):**

| Filter | Targets | Evidence |
|--------|---------|----------|
| Rolling WR floor ≥ 35% | Removes JPM (34%), CRDO (32%), MSTR (31%), CHTR (35%) | Clear 3-tier WR separation |
| Worst monthly drawdown ≤ −6% (rolling) | Removes CRDO (Sep −19.3%), MSTR (Dec −9.3%) | Catastrophic single-month risk |
| Direction-split EV gate (Phase 4 — per direction) | Blocks PLTR BEAR (0% WR Jan), allows EXPE BEAR (67% WR Jan) | Best near-term addition; recovers ~4pp in Jan alone |
| Pool vote gate: skip day if < 6/17 tickers pass EV gate | Reduces Jan/Sep exposure | Jan: only 7/17 EV-pass; Sep correlates with market selloff |

---

## Per-Ticker Stats Analysis — 2026 YTD (Jan–May 23)

**Same config as 2025 analysis.**

### 2026 YTD totals per ticker

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| CRWV | +33.86% | 57% | 2.17 | +2.38% | −1.10% | +8.30% | −3.07% |
| SHOP | +24.80% | 41% | 2.12 | +2.11% | −1.00% | +9.30% | −2.87% |
| PLTR | +23.65% | 51% | 2.00 | +1.78% | −0.89% | +7.49% | −2.50% |
| CRDO | +18.79% | 43% | 1.77 | +2.61% | −1.47% | +8.64% | −2.96% |
| CHTR | +14.75% | 46% | 1.77 | +1.45% | −0.82% | +10.94% | −1.78% |
| EXPE | +14.70% | 44% | 1.80 | +1.55% | −0.86% | +12.93% | −1.83% |
| APP | +13.52% | 43% | 1.71 | +1.72% | −1.01% | +5.58% | −2.43% |
| COIN | +8.35% | 40% | 1.81 | +2.01% | −1.11% | +8.80% | −2.40% |
| TSLA | +7.91% | 44% | 2.38 | +1.03% | −0.43% | +5.80% | −1.37% |
| AMD | +6.41% | 40% | 1.81 | +1.57% | −0.87% | +4.48% | −2.45% |
| MU | +6.24% | 34% | 2.14 | +2.42% | −1.13% | +7.46% | −2.55% |
| META | +5.92% | 39% | 1.99 | +0.99% | −0.50% | +4.63% | −1.22% |
| JPM | +0.93% | 33% | 1.97 | +0.74% | −0.37% | +3.43% | −0.91% |
| CVNA | −0.42% | 33% | 2.06 | +2.20% | −1.06% | +12.71% | −4.55% |
| MSTR | −2.00% | 30% | 2.50 | +2.13% | −0.85% | +6.71% | −2.08% |
| CLS | −5.96% | 34% | 1.73 | +1.86% | −1.08% | +4.68% | −3.23% |
| MRVL | −6.10% | 35% | 1.48 | +1.23% | −0.83% | +3.49% | −1.79% |

### Monthly grid

```
Ticker     Jan      Feb      Mar      Apr      May(~23)
CRWV     +10.73    -1.72    +4.76    +9.88   +10.21
SHOP      +3.34   +29.19    -2.81    -0.43    -4.50
PLTR      +6.01   +11.45    +7.76    -0.65    -0.92
CRDO      -3.00   +26.40    -2.95    -6.19    +4.53
CHTR      +0.35    +0.14    -0.46   +16.62    -1.91
EXPE      +4.17   +18.39    -4.24    +1.22    -4.85
APP      +13.85   +15.22    -2.87    -5.45    -7.24
MRVL      -1.63    +5.97    -1.91    -3.37    -5.16
CLS       +4.18    -0.69    -5.62    -0.86    -2.97
CVNA      +4.41   +13.65    +3.99   -12.24   -10.23
```

### Monthly pool health

| Month | # Positive / Active | Pool total | Regime |
|-------|---------------------|-----------|--------|
| 2026-01 | 13/17 | +49.0% | Strong bull |
| 2026-02 | 13/17 | +136.0% | Exceptional bull |
| 2026-03 | 6/17 | +1.9% | Neutral/choppy |
| 2026-04 | 6/17 | −2.4% | Choppy |
| 2026-05 | 5/17 | −19.2% | Bearish (ongoing) |

### Cross-year ticker consistency (2025 + 2026 combined)

| Tier | Tickers | 2025 total | 2026 YTD |
|------|---------|-----------|---------|
| Consistently strong | CRWV, PLTR, APP, EXPE | strong both years | strong both years |
| Regime-dependent | COIN, SHOP, TSLA | volatile 2025 | strong 2026 |
| Consistently weak | JPM, MSTR | −6.2%, −0.35% | +0.9%, −2.0% |
| High-beta unreliable | CRDO, CVNA | +1.9%, +42.5% | +18.8%, −0.4% |
| Fading | MRVL, CLS | +6.3%, +8.0% | −6.1%, −6.0% |

### Key 2026 observations

1. **Jan–Feb 2026 were exceptional** (pool +49% and +136%) — almost all tickers won. This inflated yearly totals for everything; the real signal is regime-driven, not ticker-specific.

2. **Mar–May 2026 reversed hard** — only 5–6/17 tickers positive. Pool total −19% in May alone. Regime shift from bull to choppy/bear.

3. **CRWV is the 2026 standout** — 57% WR and W/L 2.17, positive in 4/5 months. Entered the V3 pool and immediately became top performer.

4. **MSTR/CVNA pattern** — high W/L (2.50/2.06) but low WR (30%/33%). These are "lottery ticket" tickers — when they hit, they hit big; but in choppy months they grind losses. Consistent with 2025 findings.

5. **WR floor ≥ 38% filter would exclude MSTR (30%), CVNA (33%), JPM (33%), CLS (34%)** in 2026 — same tickers as 2025. This filter is stable across years.

---

## Per-Ticker Stats Analysis — 2024 Full Year

**Same config as 2025/2026 analysis.**

### 2024 yearly totals per ticker

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| CRDO | +14.32% | 35% | 2.17 | +2.21% | −1.02% | +8.29% | −3.17% |
| AMD | +10.61% | 36% | 2.06 | +1.55% | −0.75% | +4.34% | −2.14% |
| MU | +7.20% | 40% | 1.83 | +1.27% | −0.69% | +4.14% | −1.67% |
| JPM | +6.67% | 39% | 1.91 | +0.46% | −0.24% | +2.33% | −0.71% |
| TSLA | +4.90% | 38% | 1.81 | +1.44% | −0.79% | +6.21% | −2.66% |
| CHTR | +4.23% | 44% | 1.32 | +0.75% | −0.57% | +3.33% | −1.86% |
| SHOP | +3.82% | 34% | 2.26 | +1.36% | −0.60% | +4.63% | −3.07% |
| META | +2.63% | 42% | 1.48 | +0.67% | −0.45% | +2.56% | −1.11% |
| MRVL | −1.42% | 35% | 1.54 | +1.00% | −0.65% | +4.74% | −2.06% |
| COIN | −1.86% | 37% | 1.58 | +1.95% | −1.24% | +5.98% | −6.75% |
| CLS | −2.63% | 36% | 1.89 | +1.49% | −0.79% | +5.70% | −2.34% |
| APP | −7.28% | 36% | 1.61 | +1.46% | −0.91% | +7.54% | −3.77% |
| EXPE | −15.49% | 34% | 1.15 | +0.52% | −0.45% | +2.22% | −1.94% |
| CVNA | −27.32% | 31% | 1.78 | +1.73% | −0.97% | +10.52% | −3.19% |
| MSTR | −35.42% | 28% | 1.99 | +2.50% | −1.25% | +8.38% | −6.80% |
| PLTR | −35.99% | 33% | 1.32 | +1.21% | −0.92% | +3.97% | −3.63% |

### Monthly grid (abridged)

```
Ticker   01      02      03      04      05      06      07      08      09      10      11      12
CRDO   +3.47   -1.65   +3.12   -2.08   +3.87   -2.38   +0.43   +9.56   +6.09   -2.01   +0.33   -4.43
AMD   +11.58   +5.10   -7.73   -1.24   -3.20   +0.62   +4.96   -7.63   +6.31   +0.79   +1.47   -0.44
MSTR   -8.87   +3.62   -6.01   +1.41   -5.38  -13.73   -2.82   -4.09   +3.67   +4.45  -10.01   +2.35
PLTR   -4.95   +2.55   -8.73   -4.10   +3.10   +0.33   +4.91   -3.78   -2.14   -6.02   -4.91  -12.26
CVNA   -1.36   +1.86   -3.10   -0.70   -7.35   -6.90   -7.99   -0.38   +9.60   -2.69   -3.03   -5.28
EXPE   -0.12   -2.90   -2.45   -6.36   +0.64   +0.19   -2.43   +2.75   -1.62   -1.09   -2.30   +0.18
```

### Monthly pool health

| Month | # Positive / Active | Pool total | Regime |
|-------|---------------------|-----------|--------|
| 2024-01 | 7/16 | −6.3% | Choppy |
| 2024-02 | 12/16 | +25.0% | Bull |
| 2024-03 | 6/16 | −26.5% | **Selloff** |
| 2024-04 | 4/16 | −19.3% | **Selloff** |
| 2024-05 | 9/16 | −2.8% | Mixed |
| 2024-06 | 5/16 | −36.6% | **Worst month** |
| 2024-07 | 10/16 | +15.3% | Bull |
| 2024-08 | 6/16 | −21.9% | Bearish |
| 2024-09 | 12/16 | +51.8% | **Best month** |
| 2024-10 | 6/16 | −5.8% | Choppy |
| 2024-11 | 6/16 | −15.3% | Bearish |
| 2024-12 | 6/16 | −30.5% | **Selloff** |

### Key 2024 observations

1. **2024 was the hardest year** — pool total −73pp. Only 4 of 12 months were bull; Jun (−36.6%), Dec (−30.5%), Mar (−26.5%), Aug (−21.9%) were brutal. The pool vote gate (≤5/16 positive → avoid) would have flagged 6 of 12 months.

2. **MSTR and PLTR both −35%+ in 2024** — their 2025/2026 recovery (MSTR near flat, PLTR +23%) explains why they passed EV gate entering 2025 poorly. The EV gate was correctly bearish on MSTR/PLTR entering 2025; the problem was that it also blocked COIN, CRDO, MU which recovered.

3. **EXPE W/L dropped to 1.15** in 2024 — the lowest in the pool. 2024 was structurally bad for EXPE signals. This year-over-year W/L instability is why a 60-day rolling W/L filter is more actionable than a yearly one.

4. **Sep 2024 was the mirror of Sep 2025** — Sep 2024 was the best month (+51.8%, 12/16 positive) while Sep 2025 was the worst (−51.0%, 4/17 positive). Regime flips happen suddenly and are not predictable from prior months.

---

## Cross-Year Summary (2024–2026 YTD)

### Ticker P&L across all three periods

| Ticker | 2024 | 2025 | 2026 YTD | 3yr trend |
|--------|------|------|---------|-----------|
| CRWV | — | +3.68% | +33.86% | Rising (new entrant) |
| PLTR | −36.0% | +2.94% | +23.65% | Strong recovery |
| CVNA | −27.3% | +42.47% | −0.42% | High variance |
| COIN | −1.86% | +22.45% | +8.35% | Recovering |
| APP | −7.28% | +25.09% | +13.52% | Recovery then strong |
| TSLA | +4.90% | +21.11% | +7.91% | Consistently positive |
| CRDO | +14.32% | −25.51% | +18.79% | Boom/bust cycle |
| AMD | +10.61% | +0.56% | +6.41% | Declining but positive |
| MU | +7.20% | +4.29% | +6.24% | Steady |
| SHOP | +3.82% | −2.43% | +24.80% | Strong 2026 recovery |
| CHTR | +4.23% | +3.64% | +14.75% | Steady to rising |
| META | +2.63% | +6.12% | +5.92% | Consistently modest |
| MSTR | −35.4% | −0.35% | −2.00% | Structurally weak |
| EXPE | −15.5% | +4.69% | +14.70% | Recovery |
| JPM | +6.67% | −6.22% | +0.93% | Weak/mixed |
| MRVL | −1.42% | +6.31% | −6.10% | Inconsistent |
| CLS | −2.63% | +7.99% | −5.96% | Inconsistent |

### Stable filter thresholds (validated across 3 years)

| Filter | 2024 excludes | 2025 excludes | 2026 excludes | Stability |
|--------|--------------|--------------|--------------|-----------|
| **WR ≥ 35%** | MSTR (28%), CVNA (31%), PLTR (33%), EXPE (34%) | MSTR (31%), CRDO (32%), JPM (34%) | MSTR (30%), CVNA (33%), JPM (33%) | **High** — same bottom tier each year |
| **W/L ≥ 1.5** | PLTR (1.32), CHTR (1.32), EXPE (1.15) | PLTR (1.39) | MRVL (1.48) | Medium — varies with regime |
| **Pool vote ≥ 7/16 positive** | Would skip 6/12 months in 2024 | Would skip Jan, Sep | Would skip Mar–May 2026 | **High** — strongly regime-correlated |

### Most actionable finding

**Rolling WR ≥ 35% is the single most stable filter across all three years.** MSTR falls below 35% in all three years (28%, 31%, 30%). CVNA: below in 2024 (31%) and 2026 (33%). PLTR: below in 2024 (33%) and 2025 marginal (43%). This threshold would remove the worst performers in each year without needing to identify regime shifts.

---

## Per-Ticker Stats Analysis — 2023 Full Year

**Config:** M1 09:30/3bar, stop=0.4, ma-momentum-gate, lookback=60, n=2, feed=SIP

### Monthly P&L% per ticker

```
Ticker       01      02      03      04      05      06      07      08      09      10      11      12    TOTAL    WR%    W/L    Best    Worst
AMD       -1.16   +1.32   +2.84   -1.85   +3.84   +4.67   -1.51  +14.65   +2.66   +5.02   -0.32   -2.78   +27.39    44%   1.76   +5.76    -2.20
APP      -11.06   +2.44   -7.23   -4.24   +3.00   +8.85   -2.15   +1.44   +4.96   -0.52   -1.91   +3.52    -2.89    34%   1.70   +8.41    -7.20
CHTR      +2.29   -0.97   -3.21   +3.73   +2.78   -0.44   -1.37   +1.18   +1.77   -1.24   +0.60   -3.81    +1.32    34%   1.98   +3.00    -1.58
CLS       +3.48   +1.34   -0.15   -1.70   +4.76   +1.43   +3.27   -2.06   -1.20   -0.21   -5.52   -3.02    +0.41    32%   2.17   +4.03    -2.61
COIN     +10.93  +13.23  -20.17   -0.06   -8.03   -1.74   -2.89   +0.66   -0.36   -5.50   +5.37   -2.46   -11.02    32%   2.16  +12.85    -6.51
CRDO      -4.22   -5.00   -3.31   -1.95  +10.56  +10.38   -0.49   +2.47   +0.16   -6.85   +5.61   -4.30    +3.07    35%   1.90  +11.71    -2.73
CVNA      +5.19  -10.87   -5.47   -2.19   -5.39   +5.29  +16.97   -8.66   -8.01   -2.61   +3.26   -0.49   -12.99    33%   1.95  +13.03    -5.19
EXPE      -2.58   +1.73   -1.26   -1.15   -2.65   -3.40   +3.07   +1.07   +1.14   -4.68   +5.43   +2.33    -0.95    36%   1.74   +5.24    -1.63
JPM       -3.90   -0.07   +4.86   +0.26   -1.82   -0.17   -2.10   +1.66   +0.53   -1.89   -2.61   +2.10    -3.15    33%   1.80   +4.11    -1.04
META      -3.55   -2.68   -3.23   -2.72   -1.71   -1.31   +1.92   +1.50   +0.86   -5.68   +3.87   +0.32   -12.42    33%   1.56   +2.40    -1.54
MRVL      +0.27   +1.16   +2.68   -0.85   +4.84   +6.63   -1.98   +8.83   +0.34   -4.70   +5.94   -5.00   +18.15    41%   2.02   +4.34    -1.89
MSTR      -5.47   -3.11  -18.14   -8.67   -0.38   -0.15  +11.48   -3.22   -8.89   -3.30   -3.34   -1.13   -44.32    21%   2.13  +11.04    -3.39
MU        -2.49   +0.17   -5.75   -4.33   +4.74   +3.36   -4.62   +4.70   -3.81   -5.07   -0.63   -1.17   -14.89    33%   1.38   +4.10    -1.74
PLTR      -4.06   -2.59   -5.31   -4.91  +15.38   -4.09   +1.24  +20.48   +0.59   -1.87   +7.34   -0.61   +21.58    35%   2.11   +6.27%   -3.27
SHOP      -8.34   +4.54   -5.85   -0.42   +8.83   +5.27   -4.82   +4.13   -2.42   -4.81   +0.74   -2.48    -5.64    37%   1.38   +4.12    -2.77
TSLA     +12.61   -1.23   +1.36   +3.32   +4.08   -0.70   -0.07   +3.23   +1.25   -1.17   -0.47   -2.03   +20.18    42%   1.75   +8.42    -2.23
POOL     -12.06   -0.60  -67.34  -27.74  +42.81  +33.90  +15.95  +52.06  -10.42  -45.08  +23.35  -21.01   -16.18
```

### 2023 Yearly Summary (sorted by total P&L)

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| AMD | +27.39% | 44% | 1.76 | +1.32% | −0.75% | +5.76% | −2.20% |
| PLTR | +21.58% | 35% | 2.11 | +2.16% | −1.02% | +6.27% | −3.27% |
| TSLA | +20.18% | 42% | 1.75 | +1.40% | −0.80% | +8.42% | −2.23% |
| MRVL | +18.15% | 41% | 2.02 | +1.25% | −0.62% | +4.34% | −1.89% |
| CRDO | +3.07% | 35% | 1.90 | +1.68% | −0.89% | +11.71% | −2.73% |
| CHTR | +1.32% | 34% | 1.98 | +0.72% | −0.37% | +3.00% | −1.58% |
| CLS | +0.41% | 32% | 2.17 | +1.15% | −0.53% | +4.03% | −2.61% |
| EXPE | −0.95% | 36% | 1.74 | +0.97% | −0.56% | +5.24% | −1.63% |
| APP | −2.89% | 34% | 1.70 | +1.54% | −0.90% | +8.41% | −7.20% |
| JPM | −3.15% | 33% | 1.80 | +0.56% | −0.31% | +4.11% | −1.04% |
| SHOP | −5.64% | 37% | 1.38 | +0.97% | −0.70% | +4.12% | −2.77% |
| COIN | −11.02% | 32% | 2.16 | +3.16% | −1.46% | +12.85% | −6.51% |
| META | −12.42% | 33% | 1.56 | +0.80% | −0.51% | +2.40% | −1.54% |
| CVNA | −12.99% | 33% | 1.95 | +3.85% | −1.97% | +13.03% | −5.19% |
| MU | −14.89% | 33% | 1.38 | +0.75% | −0.54% | +4.10% | −1.74% |
| MSTR | −44.32% | 21% | 2.13 | +2.14% | −1.00% | +11.04% | −3.39% |

**Pool total: −16.18%**

### Monthly pool health

| Month | Positive/Active | Pool total |
|-------|----------------|------------|
| 2023-01 | 6/16 | −12.06% |
| 2023-02 | 8/16 | −0.60% |
| 2023-03 | 4/16 | −67.34% ← worst month |
| 2023-04 | 3/16 | −27.74% |
| 2023-05 | 10/16 | +42.81% |
| 2023-06 | 8/16 | +33.90% |
| 2023-07 | 6/16 | +15.95% |
| 2023-08 | 13/16 | +52.06% ← best month |
| 2023-09 | 10/16 | −10.42% |
| 2023-10 | 1/16 | −45.08% ← extreme pool failure |
| 2023-11 | 9/16 | +23.35% |
| 2023-12 | 4/16 | −21.01% |

### Key findings

- **Pool total −16.18%** — the strategy underperformed in 2023 despite TSLA/AMD/PLTR being strong market years. The OR momentum pattern didn't align well with the grinding, low-vol recovery from 2022
- **MSTR −44.32% with only 21% WR** — an extreme outlier and the worst WR in any year across all analysis. MSTR 2023 was dominated by large directional whipsaws on crypto sentiment
- **High W/L but low WR is common in 2023** — e.g. COIN (2.16 W/L, 32% WR), CVNA (1.95 W/L, 33% WR), MSTR (2.13 W/L, 21% WR). Big winners but too many losses — the EV gate doesn't help when losses are frequent
- **AMD, TSLA, PLTR, MRVL top 4 in 2023** — same tickers that are strong in 2025 and 2026. Structural consistency
- **Mar–Apr 2023 were catastrophic** (−67.34% and −27.74%, only 4/16 and 3/16 positive). Banking crisis / SVB collapse triggered mean-reverting gap behavior that breaks OR momentum
- **Aug 2023 and May–Jun strong** (10–13/16 positive) — pool vote signal matches well
- **Oct 2023: 1/16 positive, −45.08%** — extreme regime failure (rate hike peak). The single worst pool vote reading across all years analyzed

### Cross-year comparison update (2023–2026)

CRWV was not in the pool in 2023 (pre-IPO). SNDK not in 2023 data (assumed same pool gap).

| Ticker | 2023 | 2024 | 2025 | 2026 YTD | Pattern |
|--------|------|------|------|---------|---------|
| AMD | +27.39% | +10.61% | +0.56% | +6.41% | **Declining but positive all 4 years** |
| TSLA | +20.18% | +4.90% | +21.11% | +7.91% | **Consistently positive** |
| MRVL | +18.15% | −1.42% | +6.31% | −6.10% | Strong in bull years, weak in choppy |
| PLTR | +21.58% | −36.0% | +2.94% | +23.65% | High variance — strong in clear-trend years |
| CRDO | +3.07% | +14.32% | −25.51% | +18.79% | Boom/bust, 1-year rotation |
| MSTR | −44.32% | −35.4% | −0.35% | −2.00% | **Structurally broken — worst 3 of 4 years** |
| COIN | −11.02% | −1.86% | +22.45% | +8.35% | Recovering (crypto correlation) |
| META | −12.42% | +2.63% | +6.12% | +5.92% | Weak 2023 then mid-tier |
| MU | −14.89% | +7.20% | +4.29% | +6.24% | Bad 2023, steady since |
| SHOP | −5.64% | +3.82% | −2.43% | +24.80% | Inconsistent |
| CVNA | −12.99% | −27.3% | +42.47% | −0.42% | Extremely high variance |

### Updated stable filter thresholds (now validated across 4 years)

| Filter | 2023 excludes | 2024 excludes | 2025 excludes | 2026 excludes | Stability |
|--------|--------------|--------------|--------------|--------------|-----------|
| **WR ≥ 35%** | MSTR (21%), CLS (32%), COIN (32%), CVNA (33%), JPM (33%), META (33%), MU (33%) | MSTR (28%), CVNA (31%), PLTR (33%), EXPE (34%) | MSTR (31%), CRDO (32%), JPM (34%) | MSTR (30%), CVNA (33%), JPM (33%) | **High** — MSTR below threshold all 4 years |
| **W/L ≥ 1.5** | SHOP (1.38), MU (1.38) | PLTR (1.32), CHTR (1.32), EXPE (1.15) | PLTR (1.39) | MRVL (1.48) | Medium — varies by regime |
| **Pool vote ≥ 7/16 positive** | Would skip Jan, Mar, Apr, Jul, Oct, Dec (6/12 months) | Would skip 6/12 months | Would skip Jan, Sep | Would skip Mar–May | **High** — consistent regime signal |

**MSTR is the only ticker below WR 35% in all 4 years (21%, 28%, 31%, 30%).** Removing it would have saved significant losses without cutting any top performer.

---

## Per-Ticker Stats Analysis — 2022 Full Year

**Config:** M1 09:30/3bar, stop=0.4, ma-momentum-gate, lookback=60, n=2, feed=SIP

### Monthly P&L% per ticker

```
Ticker       01      02      03      04      05      06      07      08      09      10      11      12    TOTAL    WR%    W/L    Best    Worst
AMD       +1.75   +7.72   +3.45   +1.33   +9.86   +5.12   +2.43   +8.97   +8.24   -2.60   +2.73   +2.84   +51.83    54%   1.74   +8.90    -2.84
APP       -4.42   +5.42   -2.91   +7.92  +18.33   -9.16   -3.43   +4.42   -1.16   -8.68   -6.75  +14.52   +14.10    37%   1.90  +11.46    -4.69
CHTR      +1.73   -0.34   -0.31   +5.09   -3.96   +0.43   -4.98   +2.33   +6.71   -5.84   +1.98   +1.37    +4.21    33%   2.16   +4.48    -1.96
CLS       +0.50   +1.57   +1.67   +0.50  +10.24   +3.51  -10.53   +5.80   +1.70   -4.54   +0.73   +1.81   +12.96    39%   2.12   +4.23    -8.56
COIN      -2.33   -7.72   +3.86   +5.83   +0.40  -12.84   +6.88  +12.27   -0.60  -12.81   -8.13   -0.88   -16.08    36%   1.71  +13.10    -4.30
CRDO        ---   -4.01   +2.02   +2.71   +3.34   +7.45  +13.99   -9.54   -8.31   +2.80   -5.35   -0.59    +4.52    37%   1.70   +9.08    -3.25
CVNA      +1.52  -14.91   +3.18  +14.80  -15.73   -3.68   -8.03  +31.72   -0.31   -2.36  +36.73  +13.56   +56.51    46%   1.58  +28.05    -6.34
EXPE      +4.11   -4.29   +6.37   -2.45  +11.69   +4.87   -7.81   +0.20   +6.66  -13.32   +2.12   -1.85    +6.32    37%   1.84   +9.08    -2.11
JPM       +2.38   -2.98   -1.47   -0.43   +2.31   -0.38   -5.89   +0.41   +0.09   +1.51   -1.36   -1.35    -7.15    35%   1.37   +3.43    -1.43
META      -1.18   +2.65   +7.54   +6.14   -0.09   -3.84   -1.72   -2.62   +0.51   +7.37   -1.98   +1.87   +14.65    41%   2.01   +3.85    -1.96
MRVL      -5.78   +0.70   +0.67   +3.72   -0.44   -0.15   -2.14   +8.83   -1.81   +9.05   -3.02   -2.13    +7.51    37%   1.77   +6.80    -3.36
MSTR      +0.17   +3.69   -0.43   +8.41   -4.69  -15.09   -2.25   +4.93   +2.07   -0.30  -15.15   +8.89    -9.75    40%   1.34   +7.55    -7.21
MU        -1.96   -1.94  +12.16   +3.32   +4.58   -4.77   -4.16   +7.31   -2.32   +5.22   -5.45   -0.35   +11.65    35%   1.80   +5.02    -1.84
PLTR      +1.65   -1.63   +6.73   +2.00   +0.11   -7.03   -2.45   +1.08   +3.58   -4.70   +0.55   +2.13    +2.03    42%   1.59   +5.31    -4.04
SHOP      +5.35   +3.33   +5.78   +3.62   -0.89   +0.34   -3.00  +11.97   -1.77   +8.25   -5.20   +4.26   +32.05    48%   1.52   +8.51%   -3.77
TSLA      +0.50   -3.50   +0.32   +8.63   -2.03   -4.27   -0.82   -5.96   +4.17   +7.31   +3.99   +5.54   +13.88    42%   1.45   +7.07    -2.61
POOL      +4.00  -16.23  +48.63  +71.14  +33.04  -39.49  -33.89  +82.13  +17.45  -13.63   -3.56  +49.65  +199.24
```

### 2022 Yearly Summary (sorted by total P&L)

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| CVNA | +56.51% | 46% | 1.58 | +3.87% | −2.44% | +28.05% | −6.34% |
| AMD | +51.83% | 54% | 1.74 | +1.73% | −1.00% | +8.90% | −2.84% |
| SHOP | +32.05% | 48% | 1.52 | +2.22% | −1.46% | +8.51% | −3.77% |
| META | +14.65% | 41% | 2.01 | +1.32% | −0.66% | +3.85% | −1.96% |
| APP | +14.10% | 37% | 1.90 | +2.64% | −1.39% | +11.46% | −4.69% |
| TSLA | +13.88% | 42% | 1.45 | +1.67% | −1.15% | +7.07% | −2.61% |
| CLS | +12.96% | 39% | 2.12 | +1.41% | −0.66% | +4.23% | −8.56% |
| MU | +11.65% | 35% | 1.80 | +1.34% | −0.74% | +5.02% | −1.84% |
| MRVL | +7.51% | 37% | 1.77 | +1.72% | −0.97% | +6.80% | −3.36% |
| EXPE | +6.32% | 37% | 1.84 | +1.54% | −0.84% | +9.08% | −2.11% |
| CRDO | +4.52% | 37% | 1.70 | +1.94% | −1.14% | +9.08% | −3.25% |
| CHTR | +4.21% | 33% | 2.16 | +1.23% | −0.57% | +4.48% | −1.96% |
| PLTR | +2.03% | 42% | 1.59 | +1.92% | −1.21% | +5.31% | −4.04% |
| JPM | −7.15% | 35% | 1.37 | +0.54% | −0.40% | +3.43% | −1.43% |
| MSTR | −9.75% | 40% | 1.34 | +2.19% | −1.63% | +7.55% | −7.21% |
| COIN | −16.08% | 36% | 1.71 | +2.59% | −1.51% | +13.10% | −4.30% |

**Pool total: +199.24%** — best year in the full analysis (2022–2026)

### Monthly pool health

| Month | Positive/Active | Pool total |
|-------|----------------|------------|
| 2022-01 | 10/15 | +4.00% |
| 2022-02 | 7/16 | −16.23% |
| 2022-03 | 12/16 | +48.63% |
| 2022-04 | 14/16 | +71.14% ← best month in entire analysis |
| 2022-05 | 9/16 | +33.04% |
| 2022-06 | 6/16 | −39.49% |
| 2022-07 | 3/16 | −33.89% |
| 2022-08 | 13/16 | +82.13% |
| 2022-09 | 9/16 | +17.45% |
| 2022-10 | 7/16 | −13.63% |
| 2022-11 | 7/16 | −3.56% |
| 2022-12 | 10/16 | +49.65% |

### Key findings

- **Pool total +199.24%** — the strategy's best year by far. Bear market (2022) created strong, sustained OR breakouts in both directions that the MA momentum gate caught cleanly
- **AMD +51.83% with 54% WR** — highest WR of any ticker in any year across the full analysis. Semiconductor bear market trends triggered consistent BEARISH OR signals
- **CVNA +56.51%** — extreme volatility in 2022 (bankruptcy concerns) created huge winners in both directions. 46% WR + very large avg win ($3.87%) = massive positive EV
- **SHOP +32.05%** — strong trending behavior in the growth-stock selloff. 48% WR
- **Only 3 tickers negative in 2022**: JPM (−7.15%), MSTR (−9.75%), COIN (−16.08%) — all financial/crypto-correlated, where bear market = mean reversion not trend
- **MSTR 40% WR but W/L only 1.34** — not a WR filter catch in 2022, but W/L < 1.5 catches it
- **Apr 2022: 14/16 positive, +71.14%** — single best pool month. Broad market selloff triggered clean BEARISH signals across almost every ticker
- **Jun–Jul 2022: 6/16 and 3/16 positive** — brief period when even the bear-market bearish signals became choppy (oversold bounce confusion)
- **Aug 2022 rebound: +82.13%, 13/16 positive** — sharp counter-rally triggered strong BULLISH OR signals
- **Pool vote signal remains valid**: Jun (−39%), Jul (−34%) had only 6/3 positive; Apr (+71%), Aug (+82%) had 14/13 positive

### Cross-year comparison update (2022–2026)

| Ticker | 2022 | 2023 | 2024 | 2025 | 2026 YTD | Pattern |
|--------|------|------|------|------|---------|---------|
| AMD | +51.83% | +27.39% | +10.61% | +0.56% | +6.41% | **Declining but positive all 5 years — most consistent ticker in pool** |
| TSLA | +13.88% | +20.18% | +4.90% | +21.11% | +7.91% | **Positive all 5 years** |
| CVNA | +56.51% | −12.99% | −27.3% | +42.47% | −0.42% | Extreme variance — alternates good/bad years |
| SHOP | +32.05% | −5.64% | +3.82% | −2.43% | +24.80% | Alternates strong/weak years |
| META | +14.65% | −12.42% | +2.63% | +6.12% | +5.92% | Bad 2023, steady since |
| MRVL | +7.51% | +18.15% | −1.42% | +6.31% | −6.10% | Good in trend years, weak in chop |
| PLTR | +2.03% | +21.58% | −36.0% | +2.94% | +23.65% | High variance, strong in clear-trend years |
| CRDO | +4.52% | +3.07% | +14.32% | −25.51% | +18.79% | Boom/bust 1-year rotation |
| MSTR | −9.75% | −44.32% | −35.4% | −0.35% | −2.00% | **Negative 4 of 5 years — structural exclude** |
| COIN | −16.08% | −11.02% | −1.86% | +22.45% | +8.35% | Crypto-correlated; recovering |
| JPM | −7.15% | −3.15% | +6.67% | −6.22% | +0.93% | Mixed — weak in high-vol years |
| MU | +11.65% | −14.89% | +7.20% | +4.29% | +6.24% | Semiconductor cycle: good in down years, bad in recovery |

### Updated stable filter thresholds (validated across 5 years)

| Filter | 2022 | 2023 | 2024 | 2025 | 2026 | Stability |
|--------|------|------|------|------|------|-----------|
| **WR ≥ 35%** | MSTR (40% — passes!), COIN (36%), CHTR (33%) | MSTR (21%), CLS (32%), COIN (32%) | MSTR (28%), CVNA (31%) | MSTR (31%), CRDO (32%) | MSTR (30%), CVNA (33%) | **Medium** — MSTR passes in 2022 but still lost money (W/L=1.34) |
| **W/L ≥ 1.5** | MSTR (1.34), JPM (1.37), TSLA (1.45) | SHOP (1.38), MU (1.38) | PLTR (1.32), EXPE (1.15) | PLTR (1.39) | MRVL (1.48) | Medium — different excludes each year |
| **W/L ≥ 1.5 AND WR ≥ 33%** | MSTR caught (1.34), JPM caught | MSTR caught (21% WR) | MSTR caught, CVNA caught | MSTR caught | MSTR caught | **High** — combined filter catches MSTR all 5 years |
| **Pool vote ≥ 7/16** | Skips Feb, Jun, Jul, Oct, Nov | Skips Jan, Mar, Apr, Oct, Dec | Skips most months | Skips Jan, Sep | Skips Mar–May | **High** |

**Key 2022 insight:** MSTR had 40% WR in 2022 (passes WR filter) but only 1.34 W/L (fails W/L filter). **The combined W/L ≥ 1.5 AND WR ≥ 33% filter catches MSTR in all 5 years** — neither filter alone is sufficient.

---

## Per-Ticker Stats Analysis — 2021 Full Year

**Config:** M1 09:30/3bar, stop=0.4, ma-momentum-gate, lookback=60, n=2, feed=SIP
**Note:** COIN and APP entered pool mid-year (COIN IPO Apr 2021, APP data starts Apr). CRWV and SNDK not yet in pool.

### Monthly P&L% per ticker

```
Ticker       01      02      03      04      05      06      07      08      09      10      11      12    TOTAL    WR%    W/L    Best    Worst
AMD       +2.00   -3.76   -3.43   +1.07   -0.88   +0.87   +0.53   +0.13   -0.56   -0.34   +9.16   +1.24    +6.02    36%   1.83   +7.95    -2.15
APP         ---     ---     ---   -5.26   -1.44   +1.12   +3.27   +5.01   +3.70   -1.93   -1.52  -12.98   -10.04    33%   1.61   +3.90    -2.92
CHTR      +2.91   +0.19   +1.09   -2.49   -0.04   -0.78   +2.72   -1.95   +1.22   -1.82   +1.48   +2.06    +4.59    33%   2.42   +3.41    -0.88
CLS       -4.83   +2.40   -5.93   -4.30   -1.47   -2.87   +4.94   +1.57   -3.14   -6.60   +0.80   +2.33   -17.10    27%   1.78   +4.32    -3.15
COIN        ---     ---     ---   -4.80   +1.25   -2.12   -3.29   -7.56   +3.93   +7.40   -1.37   +1.62    -4.95    31%   1.88   +5.08    -2.93
CVNA      +1.76  -13.78   +2.83   +5.67   -0.27   +0.79   -4.17   -0.63   +1.53   -0.05   -2.04  +15.18    +6.81    39%   1.76   +7.32    -3.34
EXPE      +0.49   -4.22   -2.22   -4.13   -4.46   +0.14   -3.98   -1.36   -0.67   -3.86   +0.68  +11.15   -12.44    35%   1.35   +5.17    -2.81
JPM       +0.68   +1.58   -3.06   -3.84   -1.12   +1.72   +0.96   -0.32   +0.75   -0.80   -1.55   -0.97    -5.97    35%   1.51   +2.16    -1.00
META      -0.74   +0.45   +0.17   -1.58   +0.03   +1.88   +2.62   -0.04   +2.69   +3.17   -0.32   +0.64    +8.97    43%   1.86   +3.54    -2.08
MRVL      -6.13   +4.71   -4.83   +3.81   -2.87   +0.07   -2.53   -3.30   +0.35   -0.01   +2.03   +3.79    -4.90    36%   1.61   +3.50    -2.17
MSTR      +7.95   -3.64   -3.72   +0.13  -11.97   +2.83   -3.31   -4.41   -1.07   +4.38   +6.47   +1.41    -4.95    35%   1.66   +9.78    -5.85
MU        -0.63   -6.66   +0.28   -0.30   +0.20   +2.15   -2.69   +1.36   +0.70   +2.99   -2.68   +1.63    -3.64    36%   1.63   +3.85    -1.86
PLTR      +1.06  +11.01   -4.30   +4.68   +1.32   -4.69   +0.47   -0.07   +7.34   +0.26   +4.42   -3.53   +17.98    47%   1.41  +12.10    -5.40
SHOP      -4.54   -0.38   +3.24   +0.38   +3.31   -0.09   -4.94   -1.57   -2.71   +0.37   +2.54   -2.78    -7.18    35%   1.65   +4.96    -2.71
TSLA      +5.43   -2.23   -4.51   -0.05   -6.00   +0.98   +4.32   +3.06   -1.46   +0.94   +7.82   +6.13   +14.41    36%   1.79   +9.33    -3.20
POOL      +5.41  -14.33  -24.40  -11.02  -24.39   +2.00   -5.10  -10.09  +12.60   +4.11  +25.92  +26.92   -12.37
```

### 2021 Yearly Summary (sorted by total P&L)

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| PLTR | +17.98% | 47% | 1.41 | +1.57% | −1.11% | +12.10% | −5.40% |
| TSLA | +14.41% | 36% | 1.79 | +1.36% | −0.76% | +9.33% | −3.20% |
| META | +8.97% | 43% | 1.86 | +0.84% | −0.45% | +3.54% | −2.08% |
| CVNA | +6.81% | 39% | 1.76 | +1.73% | −0.98% | +7.32% | −3.34% |
| AMD | +6.02% | 36% | 1.83 | +1.22% | −0.67% | +7.95% | −2.15% |
| CHTR | +4.59% | 33% | 2.42 | +0.81% | −0.33% | +3.41% | −0.88% |
| MU | −3.64% | 36% | 1.63 | +1.09% | −0.67% | +3.85% | −1.86% |
| MRVL | −4.90% | 36% | 1.61 | +0.90% | −0.56% | +3.50% | −2.17% |
| MSTR | −4.95% | 35% | 1.66 | +1.84% | −1.11% | +9.78% | −5.85% |
| COIN | −4.95% | 31% | 1.88 | +1.72% | −0.92% | +5.08% | −2.93% |
| JPM | −5.97% | 35% | 1.51 | +0.55% | −0.37% | +2.16% | −1.00% |
| SHOP | −7.18% | 35% | 1.65 | +1.34% | −0.81% | +4.96% | −2.71% |
| APP | −10.04% | 33% | 1.61 | +1.59% | −0.99% | +3.90% | −2.92% |
| EXPE | −12.44% | 35% | 1.35 | +1.06% | −0.79% | +5.17% | −2.81% |
| CLS | −17.10% | 27% | 1.78 | +1.09% | −0.61% | +4.32% | −3.15% |

**Pool total: −12.37%**

### Monthly pool health

| Month | Positive/Active | Pool total |
|-------|----------------|------------|
| 2021-01 | 8/13 | +5.41% |
| 2021-02 | 6/13 | −14.33% |
| 2021-03 | 5/13 | −24.40% |
| 2021-04 | 6/15 | −11.02% |
| 2021-05 | 5/15 | −24.39% |
| 2021-06 | 10/15 | +2.00% |
| 2021-07 | 8/15 | −5.10% |
| 2021-08 | 5/15 | −10.09% |
| 2021-09 | 9/15 | +12.60% |
| 2021-10 | 7/15 | +4.11% |
| 2021-11 | 9/15 | +25.92% |
| 2021-12 | 11/15 | +26.92% ← best month |

### Key findings

- **Pool total −12.37%** — weak year. Low-vol grinding bull market; OR momentum requires sustained directional moves, not slow drift
- **CLS −17.10% with only 27% WR** — lowest WR in any year across the full 6-year analysis
- **PLTR top performer at +17.98%** — driven by Feb (+11%) and Sep (+7.34%) spikes. Confirms PLTR as a high-variance regime-dependent ticker, not a consistent hold
- **AMD and TSLA positive again** — continuing the 6/6 streak; AMD +6.02%, TSLA +14.41%
- **Feb–May 2021: four consecutive brutal months** (−74pp total, 5–6/15 positive) — meme-stock era choppiness destroyed OR momentum across the board
- **Nov–Dec 2021 strong** (+25.92%, +26.92%) — Omicron volatility spike created the clean trend conditions the strategy needs
- **MSTR: 35% WR, 1.66 W/L — passes both filters in 2021, still loses −4.95%** — the one year where no mechanical filter catches it. Confirms MSTR should be a hard-coded exclude

### Full 6-year cross-year summary (2021–2026)

| Ticker | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD | +yrs | Pattern |
|--------|------|------|------|------|------|---------|------|---------|
| AMD | +6.02% | +51.83% | +27.39% | +10.61% | +0.56% | +6.41% | **6/6** | Most consistent — positive every year |
| TSLA | +14.41% | +13.88% | +20.18% | +4.90% | +21.11% | +7.91% | **6/6** | Positive every year |
| CHTR | +4.59% | +4.21% | +1.32% | +4.23% | +3.64% | +14.75% | **6/6** | Steady low-return, positive every year |
| META | +8.97% | +14.65% | −12.42% | +2.63% | +6.12% | +5.92% | 5/6 | One bad year (2023 restructuring chop) |
| PLTR | +17.98% | +2.03% | +21.58% | −36.0% | +2.94% | +23.65% | 4/6 | High variance, regime-dependent |
| CVNA | +6.81% | +56.51% | −12.99% | −27.3% | +42.47% | −0.42% | 3/6 | Extreme variance, alternates good/bad |
| MU | −3.64% | +11.65% | −14.89% | +7.20% | +4.29% | +6.24% | 3/6 | Semiconductor cycle dependent |
| MRVL | −4.90% | +7.51% | +18.15% | −1.42% | +6.31% | −6.10% | 3/6 | Good in trend years |
| CRDO | — | +4.52% | +3.07% | +14.32% | −25.51% | +18.79% | 3/5 | Boom/bust rotation |
| SHOP | −7.18% | +32.05% | −5.64% | +3.82% | −2.43% | +24.80% | 2/6 | Strong in bear years |
| APP | −10.04% | +14.10% | −2.89% | −7.28% | +25.09% | +13.52% | 2/6 | Bipolar extremes |
| COIN | −4.95% | −16.08% | −11.02% | −1.86% | +22.45% | +8.35% | 2/6 | Crypto-correlated; only good post-2024 |
| CLS | −17.10% | +12.96% | +0.41% | −2.63% | +7.99% | −5.96% | 2/6 | Highly cyclical |
| EXPE | −12.44% | +6.32% | −0.95% | −15.5% | +4.69% | +14.70% | 2/6 | Travel-cycle dependent |
| JPM | −5.97% | −7.15% | −3.15% | +6.67% | −6.22% | +0.93% | 1/6 | Weak overall |
| MSTR | −4.95% | −9.75% | −44.32% | −35.4% | −0.35% | −2.00% | **0/6** | **Negative every year — hard exclude** |

### Filter conclusion (6-year validated)

**MSTR is the only ticker with 0 positive years in 6** — hard-code it out of the pool.

**Combined gate W/L ≥ 1.5 AND WR ≥ 33%** catches MSTR in 5 of 6 years (misses 2021 where it has 35% WR and 1.66 W/L but still loses). Catches CLS (2021: 27% WR), EXPE (2021: 1.35 W/L; 2024: 1.15 W/L), COIN (2021: 31% WR), and PLTR (2024: 1.32 W/L) in the right years.

**AMD, TSLA, CHTR are the three most reliable pool members** — positive in all 6 years.

---

## Per-Ticker Stats Analysis — 2020 Full Year

**Config:** M1 09:30/3bar, stop=0.4, ma-momentum-gate, lookback=60, n=2, feed=SIP
**Note:** COIN, APP, CRWV, SNDK not yet in pool. PLTR IPO Oct 2020 (only 3 months of data). Pool size 12–13 tickers.

### Monthly P&L% per ticker

```
Ticker       01      02      03      04      05      06      07      08      09      10      11      12    TOTAL    WR%    W/L    Best    Worst
AMD       +1.06   +4.27  -12.61   +6.09   +3.42   -7.13   +2.00   +1.70   -2.64   -0.99   -0.72   -4.58   -10.12    32%   1.96   +6.86    -2.69
CHTR      +2.75   +1.33   +1.41   +1.80   -1.93   -1.23   -2.00   +0.02   +3.10   +2.33   +2.35   +1.04   +10.98    44%   1.84   +2.62    -1.25
CLS       -2.45   +1.98  -10.53  -10.15   -2.02   -3.15   -3.58   +2.86   +1.52   +9.19   +4.99   +2.13    -9.20    30%   2.06   +8.40    -7.64
CVNA      -3.86  +14.51  -28.86   +2.74   -2.48  +14.93   -6.11  +12.36  +12.58  -14.41   -4.99   +4.91    +1.32    38%   1.68  +13.29    -7.13
EXPE      -1.32   -0.73  -17.57   -2.68   -8.75   +1.50   -4.55   -1.47   +0.29   +1.86   -6.51   +1.04   -38.91    30%   1.42   +6.99    -7.02
JPM       +1.15   +2.31   -8.33   +3.49   +6.74   +1.99   -2.25   +0.39   -2.91   -1.67   +1.27   -1.17    +1.01    37%   1.82   +3.07    -3.27
META      -0.75   +0.87   -5.72   -0.40   -0.87   +3.21   -4.34   +1.26   +0.65   -0.32   -2.63   +1.92    -7.12    33%   1.73   +3.18    -2.75
MRVL      -1.97   -2.73   -9.86   -4.40   -0.21   +1.94   -1.42   -2.13   -1.96   -4.97   -4.08   -6.27   -38.04    25%   1.25   +2.40    -3.12
MSTR      -7.08   -0.33   -7.69   -4.98   -1.98   -3.92   -8.46   +4.27   +4.05  +10.32  +11.23   +0.29    -4.28    28%   2.22   +1.48%   -2.92
MU        +1.78   -0.93  -10.72   +2.43   -1.28   -3.72   +0.07   +0.66   +1.33   -3.93   -7.46   +5.65   -16.12    36%   1.24   +3.99    -7.26
PLTR        ---     ---     ---     ---     ---     ---     ---     ---     ---   -7.63  +16.83   +7.01   +16.21    34%   2.37  +13.35    -5.17
SHOP      -0.85   +0.08  -12.17   -0.07   +2.43   -1.46   +1.19   +6.71   +3.04   -2.34   -1.52   +0.38    -4.57    36%   1.74   +6.59    -2.74
TSLA      +2.57   +4.83   -4.93   +0.09   -5.22   +2.54   -2.83   +4.17   +3.24   +3.57   +7.85   -5.81   +10.09    33%   2.05   +8.28    -4.89
POOL      -8.96  +25.47 -127.57   -6.04  -12.13   +5.51  -32.30  +30.81  +22.28   -8.99  +16.62   +6.54   -88.75
```

### 2020 Yearly Summary (sorted by total P&L)

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| PLTR | +16.21% | 34% | 2.37 | +3.73% | −1.58% | +13.35% | −5.17% |
| CHTR | +10.98% | 44% | 1.84 | +0.82% | −0.44% | +2.62% | −1.25% |
| TSLA | +10.09% | 33% | 2.05 | +2.11% | −1.03% | +8.28% | −4.89% |
| CVNA | +1.32% | 38% | 1.68 | +2.36% | −1.40% | +13.29% | −7.13% |
| JPM | +1.01% | 37% | 1.82 | +0.88% | −0.48% | +3.07% | −3.27% |
| MSTR | −4.28% | 28% | 2.22 | +1.48% | −0.67% | +6.09% | −2.92% |
| SHOP | −4.57% | 36% | 1.74 | +1.41% | −0.81% | +6.59% | −2.74% |
| META | −7.12% | 33% | 1.73 | +0.93% | −0.54% | +3.18% | −2.75% |
| CLS | −9.20% | 30% | 2.06 | +1.74% | −0.84% | +8.40% | −7.64% |
| AMD | −10.12% | 32% | 1.96 | +1.56% | −0.80% | +6.86% | −2.69% |
| MU | −16.12% | 36% | 1.24 | +0.87% | −0.70% | +3.99% | −7.26% |
| MRVL | −38.04% | 25% | 1.25 | +0.81% | −0.65% | +2.40% | −3.12% |
| EXPE | −38.91% | 30% | 1.42 | +1.37% | −0.97% | +6.99% | −7.02% |

**Pool total: −88.75%** — worst year in the full 7-year analysis

### Monthly pool health

| Month | Positive/Active | Pool total |
|-------|----------------|------------|
| 2020-01 | 5/12 | −8.96% |
| 2020-02 | 8/12 | +25.47% |
| 2020-03 | 1/12 | −127.57% ← single worst month in entire analysis (COVID crash) |
| 2020-04 | 6/12 | −6.04% |
| 2020-05 | 3/12 | −12.13% |
| 2020-06 | 6/12 | +5.51% |
| 2020-07 | 3/12 | −32.30% |
| 2020-08 | 10/12 | +30.81% |
| 2020-09 | 9/12 | +22.28% |
| 2020-10 | 5/13 | −8.99% |
| 2020-11 | 6/13 | +16.62% |
| 2020-12 | 9/13 | +6.54% |

### Key findings

- **Pool total −88.75%** — worst year in the full analysis. COVID crash (Mar) plus repeated volatility whipsaws destroyed OR momentum signals. The strategy requires trends, not gap-and-reverse panic moves
- **Mar 2020: −127.57%, only 1/12 positive** — the single worst month across all 7 years. COVID crash produced violent daily gaps that broke every OR signal
- **EXPE −38.91% and MRVL −38.04%** — both near 25–30% WR and W/L around 1.25. Travel sector (EXPE) was structurally impaired by COVID; MRVL had no directional conviction in 2020
- **AMD −10.12%** — the only year in 7 where AMD is negative. COVID disrupted the usual semiconductor trending behavior in H1; H2 recovery came too late
- **TSLA and CHTR positive** — TSLA +10.09% (EV momentum still intact post-crash); CHTR +10.98% (cable/broadband benefited from work-from-home — steady trending)
- **PLTR only 3 months (Oct–Dec 2020)** — +16.21% in just 3 months; IPO momentum generated strong OR signals immediately
- **Jul 2020: 3/12 positive, −32.30%** — second brutal month; post-bounce uncertainty created chop rather than trend
- **Aug–Sep 2020 recovery** (10/12 and 9/12 positive) — vaccine optimism created clean bullish OR trends; best pool vote readings of the year
- **MSTR: 28% WR** — caught by WR ≥ 33% filter in 2020. Negative every year across all 7 years now confirmed

### 7-year cross-year summary (2020–2026)

| Ticker | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD | +yrs | Pattern |
|--------|------|------|------|------|------|------|---------|------|---------|
| TSLA | +10.09% | +14.41% | +13.88% | +20.18% | +4.90% | +21.11% | +7.91% | **7/7** | **Only ticker positive every year including 2020** |
| CHTR | +10.98% | +4.59% | +4.21% | +1.32% | +4.23% | +3.64% | +14.75% | **7/7** | Steady low-return, positive every year |
| AMD | −10.12% | +6.02% | +51.83% | +27.39% | +10.61% | +0.56% | +6.41% | 6/7 | One bad year (2020 COVID), dominant otherwise |
| META | −7.12% | +8.97% | +14.65% | −12.42% | +2.63% | +6.12% | +5.92% | 5/7 | Two bad years (2020, 2023) |
| PLTR | +16.21% | +17.98% | +2.03% | +21.58% | −36.0% | +2.94% | +23.65% | 5/6* | High variance; terrible 2024 |
| CVNA | +1.32% | +6.81% | +56.51% | −12.99% | −27.3% | +42.47% | −0.42% | 4/7 | Extreme variance |
| JPM | +1.01% | −5.97% | −7.15% | −3.15% | +6.67% | −6.22% | +0.93% | 3/7 | Inconsistent, weak overall |
| SHOP | −4.57% | −7.18% | +32.05% | −5.64% | +3.82% | −2.43% | +24.80% | 3/7 | Strong only in bear years |
| MU | −16.12% | −3.64% | +11.65% | −14.89% | +7.20% | +4.29% | +6.24% | 3/7 | Semiconductor cycle |
| MRVL | −38.04% | −4.90% | +7.51% | +18.15% | −1.42% | +6.31% | −6.10% | 3/7 | Bad in 2020/2021, improving |
| EXPE | −38.91% | −12.44% | +6.32% | −0.95% | −15.5% | +4.69% | +14.70% | 3/7 | Travel-cycle, COVID-impaired |
| CLS | −9.20% | −17.10% | +12.96% | +0.41% | −2.63% | +7.99% | −5.96% | 3/7 | Cyclical |
| MSTR | −4.28% | −4.95% | −9.75% | −44.32% | −35.4% | −0.35% | −2.00% | **0/7** | **Negative all 7 years — permanent exclude** |

*PLTR IPO Oct 2020, only 3 months counted

### Filter conclusion (7-year validated)

**TSLA and CHTR are positive in all 7 years** — the two most reliable pool members across any market regime including COVID.

**AMD positive 6/7** — the one miss (2020) was COVID-specific. Otherwise dominant.

**MSTR negative all 7 years** — no further analysis needed. Remove from pool.

**EXPE and MRVL both had catastrophic 2020** (−38.91%, −38.04%) — both caught by WR ≤ 30% and W/L ≤ 1.42/1.25 filters. The combined filter (W/L ≥ 1.5 AND WR ≥ 33%) would have excluded both in 2020.

---

## Per-Ticker Stats Analysis — 2019 Full Year

**Config:** M1 09:30/3bar, stop=0.4, ma-momentum-gate, lookback=60, n=2, feed=SIP
**Note:** COIN, APP, PLTR, CRWV, SNDK not yet in pool. Pool size 12 tickers.

### Monthly P&L% per ticker

```
Ticker       01      02      03      04      05      06      07      08      09      10      11      12    TOTAL    WR%    W/L    Best    Worst
AMD       -0.30   -1.23   +5.64   -0.36   +0.63   -0.48   +2.62   +3.05   -5.02   +4.44   +3.82   +3.70   +16.51    39%   2.11   +6.20    -2.91
CHTR      +2.01   -0.02   +1.05   -2.86   -2.43   +1.19   -1.45   -3.56   +1.36   +0.35   +4.01   -1.59    -1.95    34%   1.77   +2.45    -0.86
CLS       -2.56   +2.26   +1.97   -1.36   +1.12   -3.06   +1.05   -2.10   +3.04   -1.37   -1.75   -2.09    -4.86    34%   1.79   +3.46    -5.29
CVNA      +7.86   -6.26  +11.76   -3.19   +2.82   +3.39   -4.18   +6.29   +6.43   +8.78   -0.28   -1.57   +31.85    43%   1.59   +7.49    -6.43
EXPE      +2.57   -0.46   -2.74   +0.27   -1.30   +1.11   -1.71   -1.16   +0.71   -0.08   +6.92   +2.47    +6.59    42%   1.76   +4.92    -1.01
JPM       +1.54   -1.70   -0.60   -2.82   +0.04   -0.61   -1.47   -0.49   +1.49   +0.86   -0.91   +0.96    -3.71    32%   1.77   +1.57    -0.94
META      -4.05   -0.56   -1.48   +0.91   -0.79   +3.05   +1.08   -3.00   +1.35   -0.78   -0.20   -3.13    -7.60    31%   1.88   +4.25    -1.04
MRVL      +3.61   +1.70   +1.96   +0.44   +1.73   -0.99   -1.14   +0.52   +0.92   -1.65   +2.34   +4.36   +13.79    41%   2.65   +3.07    -1.35
MSTR      -5.77   +1.03   +1.32   -1.07   -2.51   -0.88   +2.21   -3.36   +4.39   -7.55   -6.86   -1.20   -20.25    28%   1.39   +3.92    -1.27
MU        -0.67   -1.78   -0.70   -4.98   -1.03   +6.86   -2.50   +1.55   -0.51   -1.93   +4.26   -0.58    -2.00    41%   1.28   +2.84    -1.85
SHOP      +1.08   -2.32   +4.16   +6.18   +5.61   -0.03   +5.03  +11.12   +1.98   +3.75   +1.73   +6.60   +44.89    50%   2.18   +5.35    -2.04
TSLA      +1.60   +1.95   +1.66   +1.71   -7.64   +2.58   -1.42   -0.73   +3.28   +7.99   -0.96   +1.58   +11.61    38%   2.14   +9.93    -3.70
POOL      +6.90   -7.41  +24.00   -7.13   -3.74  +12.15   -1.88   +8.13  +19.42  +12.82  +12.13   +9.51   +84.88
```

### 2019 Yearly Summary (sorted by total P&L)

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| SHOP | +44.89% | 50% | 2.18 | +1.35% | −0.62% | +5.35% | −2.04% |
| CVNA | +31.85% | 43% | 1.59 | +1.80% | −1.13% | +7.49% | −6.43% |
| AMD | +16.51% | 39% | 2.11 | +1.41% | −0.67% | +6.20% | −2.91% |
| MRVL | +13.79% | 41% | 2.65 | +1.04% | −0.39% | +3.07% | −1.35% |
| TSLA | +11.61% | 38% | 2.14 | +1.33% | −0.62% | +9.93% | −3.70% |
| EXPE | +6.59% | 42% | 1.76 | +0.55% | −0.32% | +4.92% | −1.01% |
| CHTR | −1.95% | 34% | 1.77 | +0.57% | −0.32% | +2.45% | −0.86% |
| MU | −2.00% | 41% | 1.28 | +0.75% | −0.59% | +2.84% | −1.85% |
| JPM | −3.71% | 32% | 1.77 | +0.45% | −0.25% | +1.57% | −0.94% |
| CLS | −4.86% | 34% | 1.79 | +0.88% | −0.49% | +3.46% | −5.29% |
| META | −7.60% | 31% | 1.88 | +0.64% | −0.34% | +4.25% | −1.04% |
| MSTR | −20.25% | 28% | 1.39 | +0.66% | −0.47% | +3.92% | −1.27% |

**Pool total: +84.88%**

### Monthly pool health

| Month | Positive/Active | Pool total |
|-------|----------------|------------|
| 2019-01 | 7/12 | +6.90% |
| 2019-02 | 4/12 | −7.41% |
| 2019-03 | 8/12 | +24.00% |
| 2019-04 | 5/12 | −7.13% |
| 2019-05 | 6/12 | −3.74% |
| 2019-06 | 6/12 | +12.15% |
| 2019-07 | 5/12 | −1.88% |
| 2019-08 | 5/12 | +8.13% |
| 2019-09 | 10/12 | +19.42% ← best month |
| 2019-10 | 6/12 | +12.82% |
| 2019-11 | 6/12 | +12.13% |
| 2019-12 | 6/12 | +9.51% |

### Key findings

- **Pool total +84.88%** — solid year. Fed pivot + late-cycle bull market created good OR trending conditions in H2
- **SHOP +44.89%, 50% WR** — highest WR of any ticker in any year (tied with 2022 AMD). 2019 was SHOP's best year; e-commerce momentum generated clean daily breakouts
- **CVNA +31.85%** — strong used-car momentum pre-COVID; consistent monthly wins
- **MSTR −20.25%** — caught by WR=28% filter. Negative for the 9th consecutive year (going back as far as data exists)
- **MU W/L only 1.28** — caught by W/L filter. Semiconductors choppy in 2019 trade-war uncertainty
- **META −7.60% at 31% WR** — caught by both filters. 2019 was the FB privacy/regulation overhang year
- **CHTR marginally negative** (−1.95%) — only miss in its 9-year streak; otherwise the most boring-consistent ticker in the pool
- **Sep 2019: 10/12 positive, +19.42%** — Fed cut optimism created broad trending conditions; pool vote signal strongly confirmed

---

## Per-Ticker Stats Analysis — 2018 Full Year

**Config:** M1 09:30/3bar, stop=0.4, ma-momentum-gate, lookback=60, n=2, feed=SIP
**Note:** COIN, APP, PLTR, CRWV, SNDK not yet in pool. Pool size 12 tickers.

### Monthly P&L% per ticker

```
Ticker       01      02      03      04      05      06      07      08      09      10      11      12    TOTAL    WR%    W/L    Best    Worst
AMD       +1.26   -6.45   -3.69   -3.91   -1.69  +10.24   +2.61   +5.45   -0.07   +1.97  +10.73   -4.52   +11.93    42%   2.03   +5.84    -2.19
CHTR      +2.59   +3.75   +2.62   +1.91   -2.23   +4.37   -0.41   -0.08   -1.68   +1.55   +3.10   -2.09   +13.41    43%   1.83   +2.96    -1.41
CLS       +3.63   +1.32   -1.11   +1.84   +0.19   -1.21   -3.55   -0.77   -0.41   -3.58   +4.36   +0.30    +1.00    33%   2.13   +3.41    -1.14
CVNA      -2.93   +2.57   +1.93   +2.80   -9.32  +17.34   -6.74   +2.86   -1.03  -14.19  +13.29   +8.55   +15.14    36%   2.28  +10.58    -4.05
EXPE      +0.96   -2.47   -5.60   -4.60   -0.35   -1.09   +0.88   +0.31   +2.96   +0.87   -1.72   -1.68   -11.54    31%   1.52   +2.46    -2.47%
JPM       -2.86   +0.42   -1.95   -0.91   +4.43   -0.48   +5.14   +0.18   -0.35   -1.33   +1.76   -1.92    +2.14    36%   1.88   +1.95    -0.84
META      +2.72   -1.83   -0.36   +0.26   +0.70   +1.35   +2.73   -2.78   +1.73   +2.83   -2.49   +1.26    +6.11    35%   2.38   +3.60    -1.47
MRVL      -1.01   -1.18   -4.85   -4.80   -3.44   +0.59   -0.51   +0.97   -3.84   +0.87   -1.69   -1.77   -20.65    32%   1.47   +2.60    -2.03
MSTR      -9.19   -2.92   -1.55   -6.80   -4.08   -2.63   -5.55   -0.28   -2.84   -2.75   -3.59   -6.71   -48.89    17%   1.26   +3.85    -1.90
MU        +0.71   -3.18   +2.72   -1.44   -4.29   +2.54   +0.26   +0.51   +7.29   -3.52   +1.64   -1.35    +1.89    35%   2.15   +5.43    -2.81
SHOP      -3.73   +6.64   -4.55   +2.78   -3.39   +3.59  +10.20   -0.19   +1.98   +6.54   -3.28   -8.81    +7.76    34%   1.95   +6.29    -3.35
TSLA      +4.86   +2.62   +4.81   +0.03   +3.33   -1.46   +2.88   -2.65   -2.35   +8.14   -1.42   -5.26   +13.52    42%   1.63   +4.59    -1.71
POOL      -2.99   -0.71  -11.58  -12.84  -20.13  +33.16   +7.94   +3.53   +1.39   -2.59  +20.68  -24.01    -8.16
```

### 2018 Yearly Summary (sorted by total P&L)

| Ticker | Total% | WR% | W/L | AvgW% | AvgL% | Best% | Worst% |
|--------|--------|-----|-----|-------|-------|-------|--------|
| CVNA | +15.14% | 36% | 2.28 | +2.51% | −1.10% | +10.58% | −4.05% |
| TSLA | +13.52% | 42% | 1.63 | +1.07% | −0.66% | +4.59% | −1.71% |
| CHTR | +13.41% | 43% | 1.83 | +0.91% | −0.50% | +2.96% | −1.41% |
| AMD | +11.93% | 42% | 2.03 | +1.93% | −0.95% | +5.84% | −2.19% |
| SHOP | +7.76% | 34% | 1.95 | +1.38% | −0.71% | +6.29% | −3.35% |
| META | +6.11% | 35% | 2.38 | +0.84% | −0.35% | +3.60% | −1.47% |
| JPM | +2.14% | 36% | 1.88 | +0.52% | −0.28% | +1.95% | −0.84% |
| MU | +1.89% | 35% | 2.15 | +1.52% | −0.71% | +5.43% | −2.81% |
| CLS | +1.00% | 33% | 2.13 | +0.74% | −0.35% | +3.41% | −1.14% |
| EXPE | −11.54% | 31% | 1.52 | +0.70% | −0.46% | +2.46% | −2.47% |
| MRVL | −20.65% | 32% | 1.47 | +0.91% | −0.62% | +2.60% | −2.03% |
| MSTR | −48.89% | 17% | 1.26 | +0.70% | −0.55% | +3.85% | −1.90% |

**Pool total: −8.16%**

### Monthly pool health

| Month | Positive/Active | Pool total |
|-------|----------------|------------|
| 2018-01 | 7/12 | −2.99% |
| 2018-02 | 6/12 | −0.71% |
| 2018-03 | 4/12 | −11.58% |
| 2018-04 | 6/12 | −12.84% |
| 2018-05 | 4/12 | −20.13% ← worst month |
| 2018-06 | 7/12 | +33.16% ← best month |
| 2018-07 | 7/12 | +7.94% |
| 2018-08 | 6/12 | +3.53% |
| 2018-09 | 4/12 | +1.39% |
| 2018-10 | 7/12 | −2.59% |
| 2018-11 | 6/12 | +20.68% |
| 2018-12 | 3/12 | −24.01% |

### Key findings

- **Pool total −8.16%** — weak year. Trade-war uncertainty + rate-hike fear created choppy, non-trending market for most of 2018
- **MSTR −48.89% with only 17% WR** — the worst single-ticker year in the entire 9-year analysis. Crypto bear market 2018: MSTR was all losses, almost no wins. Every filter catches it (WR=17%, W/L=1.26)
- **TSLA, CHTR, AMD all positive** — confirms the reliable-trio pattern going back to 2018
- **MRVL −20.65%** — caught by W/L=1.47 filter; semiconductor weakness in 2018 trade-war. Same pattern as 2019
- **EXPE −11.54%** — caught by WR=31% filter. Travel sector choppy in rate-hike environment
- **Jun 2018: +33.16%, 7/12 positive** — sharp relief rally after May selloff; only 3 months had ≥ 7/12 positive in 2018
- **Dec 2018: 3/12 positive, −24.01%** — year-end rate-hike selloff, pool collapse. Same pool-vote-signal pattern
- **May 2018: 4/12 positive, −20.13%** — ZTE ban / trade-war escalation hit semis and tech hard
- **Pool vote rarely reaches ≥ 8/12** in 2018 — the whole year was regime-unfriendly; no month had clean majority positive

### 9-year cross-year summary (2018–2026)

| Ticker | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD | +yrs |
|--------|------|------|------|------|------|------|------|------|---------|------|
| TSLA | +13.52% | +11.61% | +10.09% | +14.41% | +13.88% | +20.18% | +4.90% | +21.11% | +7.91% | **9/9** |
| CHTR | +13.41% | −1.95% | +10.98% | +4.59% | +4.21% | +1.32% | +4.23% | +3.64% | +14.75% | 8/9 |
| AMD | +11.93% | +16.51% | −10.12% | +6.02% | +51.83% | +27.39% | +10.61% | +0.56% | +6.41% | 8/9 |
| META | +6.11% | −7.60% | −7.12% | +8.97% | +14.65% | −12.42% | +2.63% | +6.12% | +5.92% | 5/9 |
| CVNA | +15.14% | +31.85% | +1.32% | +6.81% | +56.51% | −12.99% | −27.3% | +42.47% | −0.42% | 6/9 |
| SHOP | +7.76% | +44.89% | −4.57% | −7.18% | +32.05% | −5.64% | +3.82% | −2.43% | +24.80% | 5/9 |
| MU | +1.89% | −2.00% | −16.12% | −3.64% | +11.65% | −14.89% | +7.20% | +4.29% | +6.24% | 4/9 |
| MRVL | −20.65% | +13.79% | −38.04% | −4.90% | +7.51% | +18.15% | −1.42% | +6.31% | −6.10% | 4/9 |
| CLS | +1.00% | −4.86% | −9.20% | −17.10% | +12.96% | +0.41% | −2.63% | +7.99% | −5.96% | 4/9 |
| JPM | +2.14% | −3.71% | +1.01% | −5.97% | −7.15% | −3.15% | +6.67% | −6.22% | +0.93% | 3/9 |
| EXPE | −11.54% | +6.59% | −38.91% | −12.44% | +6.32% | −0.95% | −15.5% | +4.69% | +14.70% | 3/9 |
| MSTR | −48.89% | −20.25% | −4.28% | −4.95% | −9.75% | −44.32% | −35.4% | −0.35% | −2.00% | **0/9** |

### Final filter conclusions (9-year validated)

**TSLA: positive in all 9 years** — the single most robust ticker in the pool across every market regime: bull, bear, COVID, trade war, rate hikes. Never negative.

**CHTR: 8/9 positive** (only miss: −1.95% in 2019, essentially flat). Second most consistent.

**AMD: 8/9 positive** (only miss: −10.12% in 2020 COVID). Otherwise dominant across all regimes.

**MSTR: negative in all 9 years (0/9)** — MSTR should not be in the pool. The combined W/L ≥ 1.5 AND WR ≥ 33% filter catches it in 8 of 9 years (misses only 2021). But given the 9/9 negative record, the correct action is a hard-coded exclude.

**EXPE: 3/9 positive, worst years are catastrophic** (−38.91% in 2020, −15.5% in 2024, −11.54% in 2018) — structurally weak for OR momentum. Combined filter catches all bad years.

**JPM: 3/9 positive** — consistently weak. The only positive years are modest; negatives compound. Low W/L (1.37–1.88 range) and low WR reflect its mean-reverting financial-sector behavior.

**MRVL: 4/9, extreme variance** — catastrophic in 2018 (−20.65%) and 2020 (−38.04%) but excellent in 2019 (+13.79%) and 2023 (+18.15%). Hard to filter consistently.

---

## Cross-Year Filter Pattern Summary (9-Year Synthesis: 2018–2026)

### Tier 1 — Structural findings (hold in any regime)

**TSLA: positive all 9 years.** The only ticker never negative. Not regime-dependent — trends on OR in bull, bear, volatile, and choppy markets alike.

**CHTR: 8/9 positive** (only miss: −1.95% in 2019, essentially flat). Low return per year (+1–14%) but never catastrophic. Functions as a ballast in bad years.

**AMD: 8/9 positive, dominant in volatile/bear years** (2022 +52%, 2023 +27%, 2018 +12%, 2019 +17%). The one miss (2020 −10%) was COVID black-swan specific.

**MSTR: negative all 9 years — hard exclude.** No filter needed. Remove from pool permanently. Combined filter catches it 8/9 years but the 9-year track record settles it.

### Tier 2 — Mechanical filter patterns

**Combined W/L ≥ 1.5 AND WR ≥ 33% is the most stable exclusion gate.** Neither alone is sufficient:
- WR alone misses MSTR in 2021 (35% WR, still −5%)
- W/L alone insufficient in years where MSTR barely passes
- Combined catches MSTR 8/9, MRVL in 2018/2020, EXPE in 2018/2020/2024, CVNA in bad years

**Pool vote ≥ 7/pool is a reliable regime gate.** Consistent across all 9 years:
- ≤ 3/pool positive → always catastrophic month (Mar 2020: 1/12 −128%, Oct 2023: 1/16 −45%, Jul/Dec 2022)
- ≥ 11/pool positive → always strongly positive (Apr 2022: 14/16 +71%, Aug 2022: 13/16 +82%, Aug 2023: 13/16 +52%)
- 5–9 range is noisy but still directionally valid

### Tier 3 — Regime patterns (structural, not filterable by ticker)

OR momentum is regime-dependent at the year level. No per-ticker filter fixes a bad regime year.

| Regime | Years | Pool performance |
|--------|-------|-----------------|
| High-vol bear/correction | 2022, 2018 H2 | Strong (+199% in 2022) |
| High-vol recovery/rally | 2019, 2025 | Strong (+85% in 2019) |
| Grinding low-vol bull | 2021, 2023 | Weak (−12%, −16%) |
| Rate-hike / macro shock chop | 2018, 2024 | Weak (−8%, −73%) |
| Black swan gap-and-reverse | 2020 | Worst (−89%) |

Volatility is a prerequisite. High-VIX environments (2018 Q4, 2020 crash-recovery, 2022, 2025 tariff shock) generate clean OR breakouts. Low-VIX grinding bulls (2021, 2023, 2024) produce frequent false signals and mean reversions.

### Most actionable takeaways

1. **Remove MSTR from the pool permanently** — 9 years, 0 positive years. Unique in the dataset.
2. **Apply combined W/L ≥ 1.5 AND WR ≥ 33% as a rolling exclusion gate** — most stable filter for catching chronic losers (EXPE, MRVL, JPM) in their bad years.
3. **Use pool vote as a regime switch** — if fewer than 7/pool tickers show positive rolling EV, reduce size or sit out. Consistent signal across all 9 years.
4. **TSLA, CHTR, AMD are the anchor tickers** — if ever constrained to a smaller pool, these three are the core.
5. **Don't expect filters to fix bad regime years** — in 2020/2021/2023/2024, even the best tickers were flat or marginally positive. Regime is the dominant variable, not ticker selection.

---

## Dynamic Filter Backtest — 9-Year Validation (2018–2026)

**Date:** 2026-05-24

**Goal:** validate two regime-adaptive CLI flags across all 9 years and confirm they improve the strategy's worst years without destroying the best.

### Flags implemented

**`--dynamic-ev-gate` (mode: `percentile`)** — instead of a fixed EV floor, exclude the bottom N% of positive-EV candidates by their rolling EV score. The exclusion percentage varies by daily pool vote:

| Pool vote | Regime | Exclude bottom |
|-----------|--------|----------------|
| ≥ 10/pool | Bull   | 10% of candidates |
| 6–9/pool  | Neutral| 25% of candidates |
| ≤ 5/pool  | Bear   | 40% of candidates |

Key property: the floor moves with the market. In a strong year, even the bottom 10% have decent EV → gate is lenient. In a bad year, bottom 40% represents real chronic losers → gate cuts them.

**`--adaptive-lookback`** — recomputes rolling stats with a shorter window in trending regimes (recent signal more predictive) and longer in choppy regimes (require more evidence):

| Pool vote | Regime  | Lookback |
|-----------|---------|----------|
| ≥ 10/pool | Bull    | 30 days  |
| 6–9/pool  | Neutral | 60 days  |
| ≤ 5/pool  | Bear    | 90 days  |

Both flags use pool vote derived from `date < d` data only — no lookahead.

### 9-Year Results (no-compound, $10k daily reset, M1 09:30/3bars, stop=0.4, ma-momentum-gate)

```
Year      Baseline    dyn-ev(pct)   adapt-lb     both
2018         -0.9%       -1.8%       +11.9%      +9.9%
2019        +10.9%      +17.3%       +13.6%     +21.2%
2020        +25.2%       +6.0%       +16.4%     +14.8%
2021         +7.2%       +5.0%        +2.9%      +2.5%
2022        -26.5%      -18.2%       -21.3%      -6.3%
2023         -0.3%       -3.0%        -1.3%      -6.0%
2024        -26.9%      -17.8%       -14.9%     -10.7%
2025         +9.7%      +22.9%       +11.9%     +24.6%
2026        +50.0%      +51.0%       +37.7%     +35.7%
──────────────────────────────────────────────────────
TOTAL       +48.5%      +61.3%       +56.9%     +85.8%
Year wins:   3            1            1           4
```

### Delta vs baseline

```
Year        dyn-ev Δ    adapt-lb Δ    both Δ
2018          -0.9pp      +12.8pp     +10.8pp
2019          +6.4pp       +2.7pp     +10.3pp
2020         -19.2pp       -8.9pp     -10.4pp
2021          -2.3pp       -4.3pp      -4.7pp
2022          +8.3pp       +5.2pp     +20.2pp
2023          -2.7pp       -1.0pp      -5.7pp
2024          +9.1pp      +12.0pp     +16.1pp
2025         +13.2pp       +2.2pp     +14.9pp
2026          +1.0pp      -12.3pp     -14.3pp
──────────────────────────────────────────────
TOTAL         +12.8pp      +8.4pp     +37.3pp
```

### Interpretation

**Combined (`--dynamic-ev-gate --adaptive-lookback`) is the strongest result at +85.8% cumulative** (+37.3pp over 9-year baseline). The two filters are complementary:

- `dyn-ev` percentile aggressively cuts the weakest pool members in bear/neutral months → big wins in 2022 (+20pp combined), 2024 (+16pp), 2025 (+15pp)
- `adapt-lb` shortens the lookback window in trending environments so recovering tickers re-qualify faster → helps in 2018 (+13pp) and 2024 (+12pp)
- Together they reinforce in the same direction in bad-regime years (2022, 2024) and strong momentum years (2019, 2025)

**Known costs:**
- 2020: −10pp combined — both filters are too restrictive in what turned out to be a massive recovery year (COVID gap-and-reverse)
- 2023: −6pp combined — chop year where the filters cut candidates that were actually marginally positive
- 2026 YTD: −14pp combined — YTD strong trending year; adapt-lb shortens the window too aggressively, losing the longer performance track that correctly identified strong tickers

**Prior threshold mode (WR/W/L absolute gates) vs new percentile mode:**

The first implementation used fixed WR ≥ 33% and W/L ≥ 1.5 thresholds. This destroyed 2019 (−12pp) and 2020 (−28pp) because rolling 60-day stats are noisy — in early months of strong years, many tickers show low rolling WR even when their underlying momentum is good. The percentile mode fixes this: the bar moves with the pool, so in a strong year all tickers appear healthy relative to each other and very few get cut.

### How the two filters work

Both filters use the same daily **pool vote** signal as their regime detector — the count of tickers with positive rolling EV that morning, computed from `date < d` data only (no lookahead).

#### `--dynamic-ev-gate` (percentile mode)

Every day before picks are made, the strategy ranks all tickers that currently have positive rolling EV from lowest to highest. It then cuts the bottom N% of that ranked list based on the regime:

- **Bull** (pool vote ≥ 10): cut bottom 10% — roughly 1 ticker out of ~12 candidates
- **Neutral** (6–9): cut bottom 25% — roughly 3 tickers
- **Bear** (≤ 5): cut bottom 40% — roughly 4–5 tickers

The floor is **relative to today's pool**, not a fixed absolute number. If the whole market is strong, even the "bottom 10%" have decent EV and the gate barely changes anything. If the whole market is choppy, the bottom 40% are genuinely the weakest performers relative to their peers.

This is what fixed the 2019/2020 problem with the old threshold mode: when WR ≥ 33% was the hard gate, good tickers with a temporarily noisy 60-day WR of 31% got cut. The percentile gate only asks "is this ticker in the bottom N% of today's pool?" — it doesn't care about the absolute number.

#### `--adaptive-lookback`

The rolling stats window (default 60 days) that determines each ticker's EV, WR, and W/L is also adjusted by the same pool vote:

- **Bull** (≥ 10): shrink to 30 days — use only recent performance
- **Neutral** (6–9): keep at 60 days
- **Bear** (≤ 5): extend to 90 days — require a longer track record

In a trending year, the shorter 30-day window lets a recovering ticker's recent good trades dominate its stats sooner, instead of being dragged down by a bad period 2 months ago. In a choppy environment, the longer 90-day window filters out tickers that had a lucky 2-week run but lack sustained quality.

#### How they interact together

The two passes happen sequentially in the daily loop:

1. Compute rolling stats with the fixed 60-day lookback → get pool vote
2. If `--dynamic-ev-gate`: determine bull/neutral/bear tier → compute EV percentile floor from positive-EV candidates
3. If `--adaptive-lookback`: use pool vote to pick 30/60/90-day window → **recompute** rolling stats with the new window
4. Score all tickers → apply EV floor gate → pick top 2

Step 3 recomputes the stats, which also updates the EV values the percentile floor is applied against. In a bull regime, the gate fires on 30-day stats (more responsive). In a bear regime, on 90-day stats (more conservative). The two filters reinforce each other in the same direction.

### CLI usage

```bash
# Recommended combined config
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --window M1 09:30 3 --min-hold-bars 1 --ma-momentum-gate \
  --reversal --bearish-reentry --bullish-reentry \
  --feed sip --stop-pct 0.4 \
  --dynamic-ev-gate --adaptive-lookback \
  --start 2022-01-01 --end 2024-12-31

# Tune exclusion percentages (default: bull=10%, neutral=25%, bear=40%)
  --dg-bull-exclude-pct 0.10 --dg-neutral-exclude-pct 0.25 --dg-bear-exclude-pct 0.40

# Use old threshold mode (fixed WR/W/L gates — not recommended)
  --dynamic-ev-gate --dg-mode threshold
```

---

## Walk-Forward Parameter Tuning — 2025

**Date:** 2026-05-24

**Goal:** validate that the `--dynamic-ev-gate` and `--adaptive-lookback` parameter defaults are sound, and determine whether tuning them per-period adds value beyond the static defaults.

### Method

4 quarterly out-of-sample folds across 2025. Each fold uses the prior 6 months as in-sample to grid-search 36 parameter combinations, then applies the best-found config to the next quarter (zero lookahead).

| Fold | In-sample | OOS |
|------|-----------|-----|
| 1 | 2024-07-01 → 2024-12-31 | 2025-Q1 |
| 2 | 2024-10-01 → 2025-03-31 | 2025-Q2 |
| 3 | 2025-01-01 → 2025-06-30 | 2025-Q3 |
| 4 | 2025-04-01 → 2025-09-30 | 2025-Q4 |

**Grid searched (36 combos):**

| Parameter | Values swept |
|-----------|-------------|
| `dg_bear_exclude_pct` | 0.25, 0.40, 0.55 |
| `dg_neutral_exclude_pct` | 0.15, 0.25 |
| `al_bear_days` | 60, 90, 120 |
| `al_bull_days` | 20, 30 |

`dg_bull_exclude_pct` (0.10) and bull/bear vote thresholds (10/5) held fixed.

### OOS Results

```
Fold   OOS Period           Baseline   Static-def   WF-best   WF vs Base
1      2025-Q1               -2.99%      +5.77%      +8.18%    +11.2pp
2      2025-Q2               +7.23%     +16.80%     +18.15%    +10.9pp
3      2025-Q3               -4.96%      -7.06%      -5.48%     -0.5pp
4      2025-Q4              +10.42%      +9.25%     +10.50%     +0.1pp
──────────────────────────────────────────────────────────────────────
TOTAL  (4 quarters)          +9.7%      +24.8%      +31.3%    +21.6pp
       vs baseline Δ                   +15.1pp     +21.6pp
```

### Best params selected per fold

```
Fold   bear_excl   neut_excl   bear_days   bull_days
1          0.55        0.25          90          20
2          0.55        0.25          90          20
3          0.40        0.25          90          20
4          0.25        0.25          60          20
```

**Param stability:**
- `neut_excl` = 0.25 — **STABLE** across all 4 folds
- `bull_days` = 20 — **STABLE** across all 4 folds
- `bear_excl` drifts 0.55 → 0.40 → 0.25 across the year
- `bear_days` = 90 for folds 1–3, drops to 60 in fold 4

### Interpretation

**Walk-forward tuned params (+31.3%) beat static defaults (+24.8%) by +6.5pp** and the unfiltered baseline (+9.7%) by +21.6pp. Param tuning on top of the filter adds genuine value.

**Q1 and Q2 drive the gains (+11pp each)** — both cover the tariff-shock/choppy period where the bear filters earned the most. Q3 and Q4 are essentially flat vs baseline (±0.5pp), meaning the filters cause no damage in cleaner trending conditions.

**The drift in `bear_excl` (0.55 → 0.25) is regime signal, not noise.** The market shifted from choppy (H1 2025) to trending (H2 2025) — the walk-forward naturally selected a more permissive gate for the back half. This confirms the filter is doing the right thing adaptively.

### Confirmed parameter defaults

| Parameter | Default | Status |
|-----------|---------|--------|
| `dg_neutral_exclude_pct` | 0.25 | Confirmed stable |
| `al_bull_days` | 20 | Confirmed stable (update from 30) |
| `dg_bear_exclude_pct` | 0.40 | Good middle ground across regime transitions |
| `al_bear_days` | 90 | Good middle ground (drops to 60 in trending regime) |
| `dg_bull_exclude_pct` | 0.10 | Not tuned; keep conservative |

**Recommended default change:** `--al-bull-days` should be updated from 30 to **20** — it was selected by all 4 folds and never lost to 30 in any top-5.

---

## Walk-Forward Parameter Tuning — 2026 YTD

**Date:** 2026-05-24

**Starting point:** stable params confirmed from 2025 WF (`neut_excl=0.25`, `bull_days=20`) are held fixed. Only the regime-sensitive params are swept.

### Method

2 folds (data through 2026-05-23). 9 combos per fold.

| Fold | In-sample | OOS |
|------|-----------|-----|
| 1 | 2025-07-01 → 2025-12-31 | 2026-Q1 (Jan–Mar) |
| 2 | 2025-10-01 → 2026-03-31 | 2026-Apr–May |

**Grid searched (9 combos — smaller than 2025 since stable params are fixed):**

| Parameter | Values swept |
|-----------|-------------|
| `dg_bear_exclude_pct` | 0.25, 0.40, 0.55 |
| `al_bear_days` | 60, 90, 120 |

### OOS Results

```
Fold   OOS Period                  Baseline   Static-def   WF-best   WF vs Base
1      2026-Q1 (Jan–Mar)           +49.17%     +36.89%     +36.89%    -12.3pp
2      2026-Apr–May                 +0.86%     +12.91%     +12.91%    +12.1pp
──────────────────────────────────────────────────────────────────────────────
TOTAL                               +50.0%      +49.8%      +49.8%     -0.2pp
       vs baseline Δ                            -0.2pp       -0.2pp
```

### Best params selected per fold

```
Fold   bear_excl   bear_days   (neut_excl=0.25  bull_days=20 fixed)
1          0.25          60
2          0.40          60
```

**Param stability:**
- `bear_days` = 60 — **STABLE** across both folds
- `bear_excl` varies (0.25 → 0.40) — regime-dependent

### Interpretation

**2026 total result is essentially flat vs baseline (−0.2pp).** The two folds tell opposing stories that cancel:

- **Q1 (Jan–Mar): filters hurt −12.3pp** — 2026-Q1 was a strong trending market (the strategy's best quarter on record at +49%). The filters cut good tickers in what turned out to be an excellent period. This is the known structural cost of the filters in pure trending years.

- **Apr–May: filters help +12.1pp** — the tariff-shock correction hit in April. The bear/neutral filters correctly excluded the weaker pool members during the choppy drawdown period. Same pattern as 2025-Q1 and Q2.

**`bear_days=60` stable across both 2026 folds** (down from 90 in 2025). This reflects 2026's faster-moving regime — the strategy needs a shorter lookback to respond quickly to the sharp Q1 trend and the Apr correction. The 90-day window carries too much historical data from the prior choppy period.

**`bear_excl` varies with regime** (0.25 in the trending fold, 0.40 in the choppy fold) — consistent with the 2025 pattern where it drifted 0.55 → 0.25 as the market transitioned from choppy to trending.

### Cross-year parameter evolution

| Period | `bear_excl` | `bear_days` | Regime |
|--------|------------|------------|--------|
| 2025-H1 (Q1–Q2) | 0.55 | 90 | Tariff-shock / choppy |
| 2025-H2 (Q3–Q4) | 0.25–0.40 | 60–90 | Recovery / trending |
| 2026-Q1 | 0.25 | 60 | Strong trend |
| 2026-Apr–May | 0.40 | 60 | Correction / choppy |

The `bear_days=60` emerging as stable in 2026 (vs 90 in 2025 H1) suggests the optimal lookback shortens in a faster-moving market. If 2026 continues with high volatility and sharp regime transitions, 60 days may become the new neutral-regime default.

### Updated recommended defaults

| Parameter | 2025 WF default | 2026 WF signal | Recommendation |
|-----------|----------------|----------------|----------------|
| `neut_excl` | 0.25 (stable) | — (fixed) | Keep 0.25 |
| `bull_days` | 20 (stable) | — (fixed) | Keep 20 |
| `bear_excl` | 0.40 | 0.25–0.40 | Keep 0.40 (middle ground) |
| `bear_days` | 90 | 60 (stable) | Consider updating to 75 as compromise |
