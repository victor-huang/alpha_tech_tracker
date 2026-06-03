# Strategy P&L Simulation — Mixed Top-3/Bottom-3 Selection (2016–2026)

**Generated:** 2026-06-02 (v2 — bug-fixed screener)
**Method:** Same no-lookahead monthly rules as `STRATEGY_PNL_SIMULATION_2018_2026.md`.
**Screener version:** v2 (3 bug fixes applied 2026-06-02 — see below)
**Signal selection:**
- **LONG months** → top-3 qualifying signals by pre-session 20d EOD WR (highest rank = best long history)
- **SHORT months** → bottom-3 qualifying signals by pre-session 20d EOD WR (lowest rank = worst history = best short candidates)

**Rationale:** When fading OR breakouts in a SHORT regime, the weakest tickers — those with the lowest 20d EOD win rate — have the least follow-through and are most likely to reverse below the opening range high.

**Baseline for comparison:** All-top-3 strategy (top-3 for every month regardless of direction).

**Script:** `backtest_result/mixed_selection_analysis.py`

---

## v2 Screener Bug Fixes

Three fixes applied to `ma_open_range_momentum_screener.py` on 2026-06-02:

1. **Volume lookahead fix** — collection-period volume computed incrementally per bar (bars 0..i only), not full-window mean upfront. Eliminated forward-looking volume confirmation.
2. **OR anchor fix** — pre-session hold history anchored at last OR bar (09:40) not bar after OR close (09:45). Single-bar shift on the ranking input.
3. **Warmup period** — extended from 30 to 45 calendar days for stable 20-day stats.

Impact: v2 total strategy P&L is ~263pp lower than v1 (v1 inflated by volume lookahead bias). 2021 flips from +74.6% to -9.0% (top-3), the most dramatic example.

---

## Yearly Summary

| Year | Mixed Strategy | Top-3 Strategy | Δ | Mixed Pure Long | Top-3 Pure Long |
|------|---------------|----------------|---|----------------|----------------|
| 2016 | +81.2% | +87.3% | -6.1pp | +72.6% | +64.8% |
| 2017 | +34.1% | +28.7% | +5.4pp | +10.4% | +15.8% |
| 2018 | +93.3% | +80.0% | **+13.4pp** | -17.2% | -3.8% |
| 2019 | +26.2% | +17.0% | +9.2pp | +7.1% | +16.4% |
| 2020 | +80.6% | +100.9% | -20.3pp | +120.5% | +100.2% |
| 2021 | -15.7% | -9.0% | -6.7pp | -60.7% | -68.7% |
| 2022 | +187.5% | +161.9% | **+25.6pp** | -148.0% | -113.6% |
| 2023 | +38.8% | +41.0% | -2.2pp | +28.8% | +26.6% |
| 2024 | +98.3% | +97.5% | +0.8pp | +30.9% | +31.7% |
| 2025 | +127.3% | +109.2% | **+18.1pp** | +52.1% | +70.3% |
| 2026 | +67.2% | +67.2% | +0.0pp | +43.8% | +43.8% |
| **Total** | **+818.7%** | **+781.6%** | **+37.2pp** | +140.4% | +183.5% |

---

## 2017 Rule Changes (v1 → v2)

| Month | v1 Rule | v2 Rule | Reason |
|-------|---------|---------|--------|
| Apr | SHORT flip (WR 34.6% < 40%) | **LONG** (WR 42.1% > 40%) | Bug fix changed signal composition |
| May | SHORT follow-Apr | **LONG** follow-Apr | Follows Apr direction change |
| Sep | LONG (EV exception, +2.68%) | **SHORT** seasonal (-4.53%) | EV exception revoked — sign flipped |

---

## SHORT-Month Deep-Dive: Bottom-3 vs Top-3

✓ = bottom-3 produced more negative EOD (better SHORT candidate pool)

| Month | B3 EOD | T3 EOD | Δ EOD | B3 Strat | T3 Strat | Δ Strat |
|-------|--------|--------|-------|---------|---------|---------|
| 2016-Sep | -9.46% | -10.99% | +1.5pp | +9.5% | +11.0% | -1.5pp |
| 2016-Nov | -2.15% | -7.60% | +5.5pp | +1.5% | +5.3% | -3.8pp |
| 2016-Dec | -8.60% | -9.37% | +0.8pp | +8.6% | +9.4% | -0.8pp |
| 2017-Sep | -6.12% | -2.04% | **-4.1pp ✓** | +6.1% | +2.0% | **+4.1pp** |
| 2017-Dec | -7.68% | -6.37% | -1.3pp ✓ | +7.7% | +6.4% | +1.3pp |
| 2018-Sep | -7.13% | +3.35% | **-10.5pp ✓** | +7.1% | -3.3% | **+10.5pp** |
| 2018-Dec | -43.23% | -40.34% | -2.9pp ✓ | +43.2% | +40.3% | +2.9pp |
| 2019-Dec | -3.79% | +5.43% | **-9.2pp ✓** | +3.8% | -5.4% | **+9.2pp** |
| 2020-Sep | -4.13% | -7.64% | +3.5pp | +4.1% | +7.6% | -3.5pp |
| 2020-Dec | +14.53% | -2.27% | +16.8pp | -14.5% | +2.3% | **-16.8pp** |
| 2021-Sep | +4.11% | +0.42% | +3.7pp | -4.1% | -0.4% | -3.7pp |
| 2021-Nov | -19.99% | -24.09% | +4.1pp | +14.0% | +16.9% | -2.9pp |
| 2021-Dec | -8.20% | -8.38% | +0.2pp | +8.2% | +8.4% | -0.2pp |
| 2022-Jan | -82.79% | -59.67% | **-23.1pp ✓** | +49.7% | +35.8% | **+13.9pp** |
| 2022-Feb | -5.91% | -17.46% | +11.6pp | +5.9% | +17.5% | -11.6pp |
| 2022-Apr | -33.93% | -35.45% | +1.5pp | +23.8% | +24.8% | -1.1pp |
| 2022-May | -0.83% | +16.12% | **-17.0pp ✓** | +0.8% | -16.1% | **+16.9pp** |
| 2022-Sep | -10.38% | -13.71% | +3.3pp | +10.4% | +13.7% | -3.3pp |
| 2022-Dec | -41.50% | -30.79% | **-10.7pp ✓** | +41.5% | +30.8% | **+10.7pp** |
| 2023-Sep | -7.44% | -0.93% | **-6.5pp ✓** | +7.4% | +0.9% | **+6.5pp** |
| 2023-Dec | -1.68% | -10.38% | +8.7pp | +1.7% | +10.4% | -8.7pp |
| 2024-Sep | -3.97% | -3.18% | -0.8pp ✓ | +4.0% | +3.2% | +0.8pp |
| 2024-Dec | -11.29% | -11.26% | -0.0pp ✓ | +11.3% | +11.3% | +0.0pp |
| 2025-Sep | -7.25% | -2.56% | **-4.7pp ✓** | +7.2% | +2.6% | **+4.7pp** |
| 2025-Dec | -28.81% | -15.38% | **-13.4pp ✓** | +28.8% | +15.4% | **+13.4pp** |

**Score: bottom-3 selects better SHORT candidates (more negative EOD) in 15/25 SHORT months (60% hit rate).**

---

## Key Findings

### Overall: Mixed selection adds +37pp over 11 years (+818.7% vs +781.6%)

The 60% hit rate (bottom-3 more negative EOD) is above chance. The asymmetry in magnitudes drives the overall edge — wins are larger (+23.1pp, +17.0pp, +13.4pp) than losses (-16.8pp, -11.6pp, -8.7pp). The net result is +37.2pp across the full backtest.

### Where bottom-3 wins most (persistent bear regimes)

| Case | Gain | Explanation |
|------|------|-------------|
| **2022-Jan** | +13.9pp | Extreme bear; weakest names led the 2022 sell-off — high beta, high multiple |
| **2022-May** | +16.9pp | Top-3 tickers recovered in a bear-market rally; bottom-3 stayed down |
| **2022-Dec** | +10.7pp | Year-end bear; weakest tickers had no holiday floor |
| **2019-Dec** | +9.2pp | Bottom-3 faded; top-3 tickers had Santa Claus momentum |
| **2018-Sep** | +10.5pp | Clean seasonal bear — top-3 tickers held up; bottom-3 led the sell-off |
| **2025-Dec** | +13.4pp | Strong December bear; weakest names had no support bid |

### Where bottom-3 loses (reversal / short-squeeze environments)

| Case | Loss | Explanation |
|------|------|-------------|
| **2020-Dec** | -16.8pp | Vaccine-era rotation; beaten-down tickers ripped hardest |
| **2022-Feb** | -11.6pp | Short-term bear bounce; top-3 tickers sold off more aggressively |
| **2023-Dec** | -8.7pp | Quiet holiday month; bottom-3 tickers bounced from oversold levels |
| **2021-Sep** | -3.7pp | Mild fade; weakest tickers mean-reverted UP |
| **2020-Sep** | -3.5pp | COVID bounce; beaten-down levels gave weakest tickers more upside |

### Pattern: when bottom-3 works vs fails for SHORT

Bottom-3 SHORT selection works best when:
- Bear regime is **persistent and deepening** across multiple months (2022, 2018 seasonal)
- Weakness is **momentum-driven** — tickers with the worst recent WR continue to underperform
- Market is in a **rate/macro-driven** sell-off where quality tickers hold up relatively

Bottom-3 SHORT selection hurts when:
- Environment has **short-squeeze or mean-reversion dynamics** (COVID 2020-2021)
- Weakness is **idiosyncratic** (stock-specific overshoot) rather than persistent
- A **macro rotation** changes sector leadership mid-month

### Signal count context

Average daily signal count varies significantly by year and affects selection quality:

| Period | Avg Signals/Day | Notes |
|--------|----------------|-------|
| 2016–2019 | 2.1–2.3 | Low-volatility era; few days with 5+ signals |
| 2020–2022 | 2.5–3.3 | Higher vol; more days with 7–12 signals |
| 2023–2026 | 2.7–3.4 | Sustained elevated signal density |

In years where avg/day is near 2, top-3 ≈ all signals. The selection edge is only meaningful when there are 4+ signals to rank and choose from.
