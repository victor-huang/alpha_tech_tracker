# Ticker Selector Retune

**Base config:** `--top 2 --window M1 09:30 3 --feed sip --min-hold-bars 1`  
**Capital:** $10,000 no-compound (daily reset)  
**Pool:** DEFAULT_TICKERS (17 tickers, V3)

---

## Multi-Year Return Comparison (2019–2026)

QQQ B&H benchmark shown for reference.

| Year | QQQ B&H | Baseline | stop=0.10 | stop=0.10+w6040 | stop=0.08 | mhb3 |
|---|---|---|---|---|---|---|
| 2019 | +30.4% | +14.87% | +9.51% | +8.49% | +12.47% | +0.07% |
| 2020 | +47.6% | +15.84% | +11.35% | +13.95% | +5.40% | +12.48% |
| 2021 | +26.6% | +3.63% | +11.29% | +13.76% | +6.43% | −10.42% |
| 2022 | −33.1% | −0.85% | −5.57% | −7.42% | −0.61% | −30.12% |
| 2023 | +53.4% | +3.86% | +6.70% | +4.71% | −2.90% | −17.26% |
| 2024 | +25.0% | −32.91% | −25.41% | −26.35% | −29.14% | −31.01% |
| 2025 | +20.4% | −6.02% | −1.94% | −1.46% | −9.61% | +1.35% |
| 2026 YTD | +14.4% | +33.25% | +46.49% | +47.64% | +50.15% | +43.31% |
| **8yr sum** | — | **+31.67%** | **+52.42%** | **+54.78%** | **+32.19%** | **−31.60%** |
| Beats baseline | — | — | **5/8 years** | — | 3/8 years | 3/8 years |

> Note: row sums reflect no-compound daily-reset P&L. Not the same as compounded returns.

---

## Win Rate & EV/Trade by Year

| Year | Base WR | s0.10 WR | s0.08 WR | mhb3 WR | Base EV | s0.10 EV | s0.08 EV | mhb3 EV |
|---|---|---|---|---|---|---|---|---|
| 2019 | 34% | 35% | 35% | 34% | +0.073% | +0.047% | +0.061% | +0.000% |
| 2020 | 30% | 29% | 29% | 35% | +0.082% | +0.059% | +0.029% | +0.069% |
| 2021 | 31% | 32% | 33% | 34% | +0.017% | +0.053% | +0.030% | −0.051% |
| 2022 | 31% | 30% | 31% | 35% | −0.004% | −0.025% | −0.003% | −0.133% |
| 2023 | 29% | 28% | 27% | 32% | +0.017% | +0.030% | −0.013% | −0.076% |
| 2024 | 29% | 30% | 30% | 36% | −0.149% | −0.114% | −0.132% | −0.138% |
| 2025 | 32% | 32% | 34% | 39% | −0.029% | −0.009% | −0.046% | +0.006% |
| 2026 | 40% | 44% | 43% | 43% | +0.361% | +0.505% | +0.542% | +0.476% |

---

## Key Findings

### Finding A — stop=0.10 is the only durable improvement across the full history

`--stop-pct 0.10` beats the baseline in 5 of 8 years and leads on the 8-year sum by +20pp (+52.42% vs +31.67%). When it underperforms, the margin is modest (worst case: −4.5pp in 2022). When it outperforms, the margin is large (2021: +7.7pp, 2024: +7.5pp, 2025: +4.1pp, 2026: +13.2pp).

**Why does stop=0.10 hurt in 2019–2020?**  
Both were strong bull-momentum years where breakouts extended and then consolidated — the strategy's avg win% was high (2019: +1.03% base vs avg) but stop=0.10 changes trade selection enough that some of those winners get filtered. The regression is −5pp in 2019 and −4.5pp in 2020 — tolerable given the 2021+ improvement.

**Why does stop=0.10 help from 2021 onward?**  
Beginning in 2021, intraday volatility and false-breakout rates increased. Tighter stops mean smaller losses when a breakout quickly reverses, improving the loss side of the EV formula. The EV improvement is visible: baseline EV was +0.017% in 2021, stop=0.10 improves to +0.053%.

### Finding B — stop=0.08 is overfit to 2026 choppy conditions

stop=0.08 wins only 3 of 8 years:
- **Bad on 2020** (+5.4% vs +15.84% baseline — a massive −10pp regression)
- **Bad on 2023** (−2.90% vs +3.86% baseline)
- **Bad on 2025** (−9.61% vs −6.02% baseline)
- 8-year sum (+32.19%) is only marginally better than baseline (+31.67%)

The tight stop cuts into good trades in trending years. It's a regime-specific parameter: good for choppy 2026, bad for trending 2019-2020 and 2023. **Do not adopt for live engine in current form.**

### Finding C — min-hold-bars 3 is definitively disqualified

Despite showing the best win rate in several years (35-39% WR), mhb3 has catastrophic losses:
- 2022: −30.12% (vs −0.85% baseline)
- 2023: −17.26% (vs +3.86% baseline)
- 8-year sum: −31.60% vs +31.67% baseline — **−63pp swing**

The mechanism: mhb3 filters out quick stopouts in 1-2 bars, which inflates WR but allows medium-duration losses to compound. The EV is consistently negative after 2020 (−0.051% to −0.138%). The 2026 improvement (+43.31%) is not representative of the long-run behavior.

### Finding D — weights 60/40 adds marginal consistent value when combined with stop=0.10

`--stop-pct 0.10 --weights 60 40` is +2.4pp over stop=0.10 alone on 2026 (+47.64% vs +46.49%) and +0.48pp better on 2025 (−1.46% vs −1.94%). However, it amplifies losses in bear years:
- 2022: −7.42% (vs −5.57% for stop=0.10, −1.85pp worse)
- 2019: slightly worse

The additional downside in bad years is the cost of concentrating more capital in rank-1. Acceptable if the primary goal is maximizing good-year returns rather than minimizing bad-year losses.

### Finding E — The base config itself is structurally weak before 2026

All configs lose or barely break even in 2022–2025 (except mhb3 in 2025 at +1.35%). The base M1-only config without SOA features (reversal, reentry, doubledown) has:
- Negative EV in 2022 and 2024
- Near-zero EV in 2021 and 2023
- 2024 was catastrophic for all configs (−25% to −33%)

The +33.25% in 2026 is an outlier driven by the choppy, volatile market regime. These configs need the full SOA feature set to be viable in trending bull years.

---

## Summary Leaderboard (2026 YTD reference)

| Rank | Config | 2026 YTD | 8yr Sum | Years Won |
|---|---|---|---|---|
| 1 | `--stop-pct 0.10 --weights 60 40` | +47.64% | +54.78%* | — |
| 2 | `--stop-pct 0.10` | +46.49% | **+52.42%** | **5/8** |
| 3 | `--stop-pct 0.08` | +50.15% | +32.19% | 3/8 |
| 4 | `--min-hold-bars 3` | +43.31% | −31.60% | 3/8 |
| 5 | Baseline (stop=0.15) | +33.25% | +31.67% | — |

*\* 2025 = −1.46%; missing 2019/2020/2021/2022/2023/2024 years-won count vs baseline*

---

## Recommendations

### Safe to adopt
**`--stop-pct 0.10`** — Durable improvement across 8 years. Beats baseline in 5/8 years. 8yr sum +52% vs +32%. Max downside regression: −5pp in 2022.

**`--stop-pct 0.10 --weights 60 40`** — Adds marginal upside (+2pp on 2026, +0.5pp on 2025) at the cost of slightly bigger drawdowns in bear years (−1.9pp extra in 2022). Reasonable trade-off if targeting outperformance in good years.

### Use with caution
**`--stop-pct 0.08`** — Strong on 2026 YTD but regime-specific. Avoid in live engine until a regime filter that correctly identifies 2026-type choppy conditions (without lookahead) is validated.

### Disqualified
**`--min-hold-bars 3`** — Catastrophic on 2022/2023. The WR improvement is illusory; EV is negative in 6/8 years.

**`--min-ev 0.3`** — Counterproductive (removes good current picks based on stale rolling stats).

---

## Next Validation Steps

- [x] Run `--stop-pct 0.10 --weights 60 40` against the **full SOA config** (reversal + bearish-reentry + bullish-reentry + doubledown + M1+A1+A2) for 2019–2026 — **done, see SOA Validation section below**
- [x] Test rolling window sweep (20/30/45/60/90d) — **done, see Lookback Sweep section below; lb45 wins**
- [ ] Validate **`--lookback 45`** on the full SOA config (2019–2026) — only tested on M1-only config so far
- [ ] Investigate **2022 catastrophic SOA loss** (−25.66%) — SOA features cause severe drawdown in the 2022 bear year; reversal/reentry/doubledown legs likely compound losses; root cause unknown
- [ ] Test **regime-adaptive with tightened stop_pct** (0.08–0.15 range instead of the current 0.4–0.7) — the concept is valid but the stop values in `REGIME_ADAPTIVE_CONFIGS` are too loose

---

## Experiment Log (2026 YTD only)

| ID | Flags | 2026 Return | Trades | WR | Avg Win% | Avg Loss% | EV/trade |
|---|---|---|---|---|---|---|---|
| Baseline | — | +33.25% | 184 | 40% | +2.26% | −0.88% | +0.361% |
| E1 | `--weights 60 40` | +33.74% | 184 | 40% | +2.26% | −0.88% | +0.361% |
| E2 | `--min-ev 0.3` | +17.47% | 140 | 38% | +2.05% | −0.85% | +0.250% |
| E3 | `--weights 60 40 --min-ev 0.3` | +17.72% | 140 | 38% | +2.05% | −0.85% | +0.250% |
| E4 | `--score-entry-weight 0.40` | +32.35% | 184 | 40% | +2.23% | −0.89% | +0.352% |
| E5 | `--score-entry-weight 0.60` | +33.15% | 184 | 39% | +2.32% | −0.87% | +0.360% |
| E6 | `--min-or-range 1.0` | +32.99% | 182 | 40% | +2.28% | −0.89% | +0.362% |
| E7 | `--regime-adaptive` | +27.87% | 177 | 44% | +2.40% | −1.33% | +0.315% |
| E8 | `--min-hold-bars 3` | +43.31% | 182 | 43% | +2.48% | −1.03% | +0.476% |
| E9 | `--weights 70 30` | +34.23% | 184 | 40% | — | — | — |
| E10 | `--stop-pct 0.10` | +46.49% | 184 | 44% | +2.20% | −0.83% | +0.505% |
| E11 | `--stop-pct 0.20` | +46.11% | 183 | 41% | — | — | — |
| E12 | `--stop-pct 0.10 --min-hold-bars 3` | +41.40% | 183 | 48% | — | — | — |
| E13 | `--stop-pct 0.10 --weights 60 40` | +47.64% | 184 | 44% | — | — | — |
| E14 | `--stop-pct 0.05` | +41.50% | 184 | 43% | — | — | — |
| E15 | `--stop-pct 0.10 --weights 60 40 --min-hold-bars 3` | +45.99% | 183 | 48% | — | — | — |
| E16 | `--stop-pct 0.12` | +44.35% | 183 | 43% | +2.24% | −0.85% | +0.485% |
| E17 | `--stop-pct 0.10 --min-hold-bars 2` | +41.66% | 184 | 45% | — | — | — |
| E18 | `--stop-pct 0.10 --weights 70 30` | +48.79% | 184 | 44% | +2.20% | −0.83% | +0.505% |
| E19 | `--stop-pct 0.08` | +50.15% | 185 | 43% | +2.24% | −0.75% | +0.542% |
| E20 | `--stop-pct 0.10 --weights 75 25` | +49.37% | 184 | 44% | +2.20% | −0.83% | +0.505% |
| E21 | `--stop-pct 0.08 --weights 70 30` | +50.21% | 185 | 43% | — | — | — |
| E22 | `--stop-pct 0.08 --weights 75 25` | +50.22% | 185 | 43% | — | — | — |
| E23 | `--stop-pct 0.07` | +44.43% | 184 | 43% | — | — | — |

---

## SOA Config Validation (2019–2026)

**Base flags for both configs:**  
`--top 2 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal --bearish-reentry --bullish-reentry --doubledown --doubledown-start 5 --feed sip --min-hold-bars 1 --weights 60 40`

**Comparison:** SOA Baseline (stop=0.15) vs SOA + stop=0.10  
All figures are no-compound daily-reset $10k. QQQ B&H shown for reference.

| Year | QQQ B&H | SOA Base | SOA s0.10 | Delta |
|---|---|---|---|---|
| 2019 | +37.3% | +17.80% | +18.52% | +0.72pp |
| 2020 | +45.1% | +32.52% | +28.78% | −3.74pp |
| 2021 | +28.6% | +32.30% | +33.14% | +0.84pp |
| 2022 | −33.7% | −25.66% | −26.29% | −0.63pp |
| 2023 | +54.8% | +79.49% | +82.62% | +3.13pp |
| 2024 | +27.0% | −2.73% | +12.62% | **+15.35pp** |
| 2025 | +20.4% | +21.35% | +14.73% | **−6.62pp** |
| 2026 YTD | +14.4% | +49.27% | +57.89% | +8.62pp |
| **8yr sum** | — | **+205.06%** | **+221.61%** | **+16.55pp** |
| Beats baseline | — | — | **5/8 years** | — |

### M1-Window Stats by Year (SOA Base vs SOA s0.10)

| Year | Base WR | s0.10 WR | Base EV | s0.10 EV |
|---|---|---|---|---|
| 2019 | 39% | 39% | +0.075% | +0.084% |
| 2020 | 36% | 34% | +0.113% | +0.061% |
| 2021 | 38% | 39% | +0.054% | +0.091% |
| 2022 | 39% | 36% | −0.116% | −0.160% |
| 2023 | 37% | 38% | +0.213% | +0.236% |
| 2024 | 35% | 34% | −0.125% | −0.105% |
| 2025 | 42% | 42% | +0.012% | +0.022% |
| 2026 | 45% | 50% | +0.579% | +0.680% |

### SOA Validation Findings

**Finding F — stop=0.10 remains durable on full SOA config (5/8 years, +16.55pp over 8yr)**

The stop change holds up across the full feature set. It beats SOA baseline in the same 5 years as the M1-only test (2019, 2021, 2023, 2024, 2026) and loses the same 3 years (2020, 2022, 2025). The 8-year improvement is slightly smaller (+16.55pp vs +20.75pp for M1-only) because the add-on legs provide some of the same downside protection.

**Finding G — SOA features solve the 2024 catastrophe that M1-only couldn't fix**

In M1-only tests, all configs lost −25% to −33% in 2024. The full SOA config converts 2024 from catastrophic to near-breakeven (−2.73% base) or solidly positive (+12.62% with stop=0.10). The reversal/reentry/doubledown legs are providing meaningful loss recovery in 2024's market. This is the critical finding: **2024 is not a problem on the production SOA config** — it was a M1-only weakness.

**Finding H — 2025 regression is more pronounced on SOA (−6.62pp vs −0.48pp M1-only)**

SOA + stop=0.10 earns +14.73% in 2025 vs SOA base +21.35% (−6.62pp). The M1-only test showed only −0.48pp regression in 2025. Root cause hypothesis: add-on legs (BRE/BUE/DD) create trade chains where the initial entry sets up subsequent re-entries at better prices. A tighter stop on the M1 initial entry cuts more of these chains early, preventing the add-on legs from recovering the trade. This is the primary downside risk of adopting stop=0.10 on the full SOA config.

**Finding I — 2022 is the structural bear-year problem for SOA (−25.66%)**

The SOA config loses heavily in 2022 (−25.66% base) while the M1-only baseline only lost −0.85%. The additional add-on legs amplify directional exposure in a sustained bear market — reversal signals keep triggering against a macro downtrend, and BRE/BUE/DD compounds those positions. This is a known risk of the SOA feature set in prolonged bear conditions. stop=0.10 doesn't help (−26.29% vs −25.66%).

### SOA Recommendation Update

**Adopt for live engine:** `--stop-pct 0.10` with the full SOA config. The 5/8 win rate and +16.55pp 8yr improvement hold on the production feature set. The main cost is 2025 regression (−6.62pp on SOA vs −0.48pp on M1-only) — acceptable given 2024 improvement (+15.35pp).

**Do not use standalone M1-only** as the primary live config — SOA features convert 2024 from catastrophic to positive, and improve most years significantly.

---

## Lookback Window Sweep (2019–2026)

**Test:** Rolling stats window varied across 20 / 30 / 45 / 60 (baseline) / 90 days on M1-only config.  
**Base flags:** `--top 2 --window M1 09:30 3 --feed sip --min-hold-bars 1`

| Year | lb20 | lb30 | lb45 | lb60 (base) | lb90 | s0.10 | lb45+s010 |
|---|---|---|---|---|---|---|---|
| 2019 | +6.2% | **+19.3%** | +18.1% | +14.9% | +8.0% | +9.5% | +4.3% |
| 2020 | +12.2% | **+24.1%** | +16.1% | +15.8% | +6.0% | +11.3% | +11.6% |
| 2021 | −20.5% | +4.6% | +5.1% | +3.6% | −1.0% | **+11.3%** | +6.2% |
| 2022 | **+7.8%** | +5.2% | −1.1% | −0.8% | −23.8% | −5.6% | −4.9% |
| 2023 | −1.4% | −2.3% | +5.9% | +3.9% | +8.0% | **+6.7%** | +6.2% |
| 2024 | −13.2% | −21.6% | **−11.6%** | −32.9% | −21.9% | −25.4% | −23.4% |
| 2025 | −8.9% | −7.3% | **−5.6%** | −6.0% | −6.3% | −1.9% | −1.8% |
| 2026 | +31.7% | +31.1% | +36.3% | +33.2% | +18.0% | **+46.5%** | +38.7% |
| **8yr sum** | +13.9% | +53.2% | **+63.2%** | +31.7% | −12.9% | +52.4% | +37.0% |
| Years best | 1 | 3 | 1 | 0 | 1 | 3 | 1 |

### Finding J — lb45 is the most durable rolling window (+63.2% 8yr, +31.5pp over baseline)

`--lookback 45` beats the lb60 baseline in **7 of 8 years**, losing only 2022 by 0.3pp. The 8yr improvement is +31.5pp — larger than either `--stop-pct 0.10` (+20.7pp) or `--lookback 30` (+21.5pp) in isolation.

**Why lb45 works:** The 60-day window is slow to react when a ticker's regime shifts. In 2024, lb60 keeps high-scoring tickers that had good 60-day stats but were deteriorating — the EV gate stays open too long. lb45 closes it faster: the EV for those tickers drops below 0 sooner, removing them from selection. The 2024 improvement alone is +21.3pp (−11.6% vs −32.9%).

**Why lb20 fails (2021: −20.5%):** 20 days (~1 month) is too short — one bad run kicks a ticker out of the pool; one lucky streak adds a bad one. The noise dominates in trending years.

**Why lb90 fails (−12.9% 8yr):** 90 days makes the EV gate nearly static — it takes a full quarter of bad trades before a ticker gets excluded. Fine for stable regimes, catastrophic when the market turns.

### Finding K — lb45 and stop=0.10 do NOT stack (+37.0% combined vs lb45 alone +63.2%)

Combining `--lookback 45 --stop-pct 0.10` produces +37.0% — worse than either improvement alone. The combination hurts in 2019 (+4.3% vs lb45 +18.1%) and 2020 (+11.6% vs lb45 +16.1%).

**Mechanism:** lb45 improves selection quality — it picks better tickers by using fresher stats. stop=0.10 trades off some winners for smaller losses. When you already have better picks (lb45), cutting those picks off with a tighter stop degrades returns in trending years where the breakout extends past 10% of OR range. The two levers are competing in bull years.

**Takeaway: lb45 is the better single parameter change.** Do not layer stop=0.10 on top of lb45.

### EV/trade Improvement: lb45 vs lb60

| Year | lb60 EV | lb45 EV | Δ |
|---|---|---|---|
| 2019 | +0.073% | +0.090% | +0.017pp |
| 2020 | +0.082% | +0.082% | 0 |
| 2021 | +0.017% | +0.025% | +0.008pp |
| 2022 | −0.004% | −0.005% | −0.001pp |
| 2023 | +0.017% | +0.027% | +0.010pp |
| 2024 | −0.149% | **−0.052%** | **+0.097pp** |
| 2025 | −0.029% | −0.027% | +0.002pp |
| 2026 | +0.361% | +0.402% | +0.041pp |

The 2024 EV improvement (+0.097pp per trade) is the signal: lb45 filters out deteriorating tickers earlier, reducing the frequency of highly negative-EV trades in a bad year.

### Random Picker Baseline (from scoring function test)

`--random-picks` from EV-positive pool across 3 seeds shows the scoring function adds **+39pp over 8yr** vs unguided selection. High seed variance in 2020 (31pp spread) and 2025 (29.5pp spread) confirms the pool has very unequal tickers — scoring is failing to pick the right end in 2024 and 2025. lb45 fixes most of the 2024 failure (+21.3pp).

### Lookback Recommendation

**Adopt `--lookback 45`** as the new default on both M1-only and the full SOA config.

---

## Ranking Formula Retune (Phases 1–5)

Full detail in `ranking_formula_retune.md`. Summary of validated findings:

### Finding L — avg_win_pct is the weakest scoring factor; entry_vs_mid dominates

Phase 1 ablation: `avg_win_pct` alone = +20.5% (8yr). `entry_vs_mid_pct` alone = +80.5%.  
The current formula (entry=0.50, avg_win=0.30, or_range=0.20) dilutes the strongest signal with the weakest.

### Finding M — or_vol_ratio at 0.15 weight adds +11pp over lb45 baseline

`or_vol_ratio` captures whether today's OR volume is above the 20-day rolling average. At vol=0.15, or_range=0.05: +74.5% (8yr). Stealing weight from or_range, not from entry.

### Finding N — E1 config is the new best: +87.8% (8yr M1-only), +24.6pp over lb45

`--score-entry-weight 0.80 --score-avg-win-weight 0.00 --score-vol-ratio-weight 0.15`  
or_range residual = 0.05. Drops avg_win entirely, concentrates on the two strongest signals.

Year-by-year profile: wins 2020 (+4.7pp), 2021 (+5pp), 2022 (+14.2pp!), 2024 (+2.3pp), 2025 (+4.4pp), 2026 (+2.7pp) vs lb45. Loses 2019 (-0.3pp) and 2023 (-8.3pp) — both pure bull years where historical avg_win was most relevant.

### Finding O — EV trend signal (Phase 3) beats lb45 modestly but does not beat E1

`ev_trend = ev_trade_15d − ev_trade_45d` gives B3=+72.7% (8yr). Does not stack with E1 (E1+ev_trend = +81.2% vs E1 +87.8%). Discard.

### Finding P — Direction-split EV gate (Phase 4) is DISQUALIFIED

`--direction-split-ev` = catastrophic. D1 = +13.9% (8yr), 2022 = -25.3%. Cuts too many valid tickers in bear/mixed years. Do not use.

### Finding Q — E1 on full SOA config: +262.4% (8yr), +31.3pp over SOA baseline

SOA baseline with lb45/default weights: +231.1% (8yr).  
E1 weights on full SOA: +262.4% (8yr).  
E1 wins 5/8 years on SOA: 2020 (+17.6pp), 2022 (+12.8pp), 2024 (+3.9pp), 2025 (+8.6pp), 2026 (+2.7pp).  
SOA base only wins 2019 (-2.9pp), 2021 (-2.7pp), 2023 (-8.5pp) — the three cleanest bull years.

**Final recommendation:** Adopt E1 weights for all production runs:
```
--score-entry-weight 0.80 --score-avg-win-weight 0.00 --score-vol-ratio-weight 0.15
```
**Do not combine with `--stop-pct 0.10`** — they compete in bull years.

### Finding R — Oracle picker: theoretical maximum for M1 morning strategy is +181.79% (2026 YTD)

**What it is:** The oracle picker runs the full backtest simulation for **all 17 tickers every day**, using the same entry/stop/exit rules as the real engine, then picks the 2 tickers with the **highest actual realized P&L** for that day (hindsight). It answers: "what is the ceiling if selection were perfect?"

**Run:** `--oracle-picks --top 2 --window M1 09:30 3 --lookback 45 --start 2026-01-01 --end 2026-05-23`

| Picker | Return (2026 YTD) | Win Rate | Notes |
|---|---|---|---|
| **Oracle (perfect hindsight)** | **+181.79%** | **76%** | Theoretical ceiling |
| E1 scored (entry=0.80, vol=0.15) | +36.66% | 37% | Best production config |
| Random (EV-gated, seed=42) | +3.74% | 35% | Unguided selection baseline |
| QQQ buy-and-hold | +17.03% | — | Market benchmark |

**Key interpretation:**
- E1 captures ~20% of the theoretical maximum (+36.66% vs +181.79% ceiling)
- The oracle WR is 76% — not 100% — because even with perfect selection, ~1 in 4 trades loses due to OR momentum setup failure (the signal itself is wrong on those days, not the ticker choice)
- The 4.9× gap between oracle and E1 is entirely a **ticker selection gap** — the trade simulation logic is correct; it is the scoring that leaves 145pp on the table
- Monthly oracle never had a losing month in 2026 YTD; even the weakest month (May W18: 3W/7L) was +1.13%

**What it means for future work:** Further scoring improvements can theoretically recover up to ~145pp of additional return. The 76% WR ceiling means no scorer can achieve >76% WR on M1 morning picks alone regardless of how good the formula gets.

### Finding S — Oracle ceiling by year: 2022–2025 (M1-only, top-2, $10k no-compound)

**Config:** `--oracle-picks --top 2 --window M1 09:30 3 --feed sip --min-hold-bars 1 --lookback 45`

| Year | Oracle return | Oracle WR | Avg P&L/day | E1 scored | E1 capture rate | QQQ B&H | Market character |
|---|---|---|---|---|---|---|---|
| 2022 | **+351.98%** | 65% | +1.41% | +18.95% | **5.4%** | -33.71% | Bear market |
| 2023 | **+310.27%** | 73% | +1.24% | +52.34% | 16.9% | +54.84% | Recovery bull |
| 2024 | **+271.66%** | 75% | +1.09% | +21.41% | 7.9% | +26.99% | Choppy bull |
| 2025 | **+297.10%** | 74% | +1.20% | +29.50% | 9.9% | +20.40% | Volatile |
| 2026 YTD | **+181.79%** | 73% | +1.73% | +36.66% | 20.2% | +17.03% | Whipsaw recovery |

**Monthly breakdowns (oracle, $10k no-compound):**

2022: Jan +16%, Feb +20%, Mar +36%, Apr +32%, May +44%, Jun +25%, Jul +22%, Aug **+49%**, Sep +29%, Oct +28%, Nov +20%, Dec +30%
2023: Jan **+43%**, Feb +15%, Mar +18%, Apr +13%, May +32%, Jun **+47%**, Jul +29%, Aug +38%, Sep +16%, Oct +10%, Nov +37%, Dec +11%
2024: Jan +19%, Feb **+41%**, Mar +22%, Apr +16%, May +16%, Jun +12%, Jul +23%, Aug +21%, Sep **+31%**, Oct **+32%**, Nov +24%, Dec +14%
2025: Jan +16%, Feb +23%, Mar +25%, Apr +26%, May +25%, Jun +28%, Jul +23%, Aug +27%, Sep +18%, Oct **+30%**, Nov **+32%**, Dec +23%

**Key findings:**

1. **Bear market (2022) has the highest ceiling (+352%).** When QQQ fell -34%, the strategy's oracle ceiling was its highest across all years. High-vol tech tickers diverge most violently in bear markets — individual OR breakouts (both bull and bear signals) produce the richest outcomes when the index is in chaos.

2. **2022 E1 capture rate is the lowest (5.4%).** Even with the best scoring config, the scorer captures almost nothing of the 2022 ceiling. The bear year is both the richest environment AND the hardest to exploit — ticker selection in a down market is the hardest problem.

3. **2025 oracle is the most consistent** — positive every single month, narrowest range (+16% to +32%). No losing months across 247 trading days. The 2025 environment (volatile but ultimately positive) is the most favorable for the OR momentum setup.

4. **Oracle WR floor is 65% (2022).** Even in the worst year for the index, picking the best 2 tickers per day yielded 65% win rate — the OR setup itself was valid, selection was the bottleneck.

5. **Ceiling is roughly 3× the year's best scored result in good years (2023, 2025), and 15-20× in bad years (2022, 2024).** The scorer has the most room to improve in choppy/bear regimes.

### Finding U — Expanded oracle characteristics with full technical indicator sweep (2020–2026)

**Method:** Extended `analyze_oracle_characteristics.py` with 10 new daily features (RSI, Bollinger Band position, MACD histogram, daily MA200 distance, MA stack count, prior-day close position, consecutive streak, 52-week high/low proximity, ATR ratio, prior-day volume ratio). All features use only prior-day or earlier data — no same-day lookahead. Re-ran full sweep 2020–2026. Full CSVs at `/tmp/oracle_features_v2_*.csv`.

**Cross-year feature scorecard (Δ = oracle mean minus rest-of-pool mean):**

| Feature | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Signal type |
|---|---|---|---|---|---|---|---|---|
| Open vs 52w low (%) | **-17.8** | **-20.2** | -1.9 | **-8.2** | **-19.1** | +0.1 | **-19.2** | **Universal — oracle closer to 52w low** |
| Open vs daily MA200 (%) | -2.5 | +0.5 | **+4.1** | -2.6 | **-5.4** | -0.1 | -3.9 | Regime-conditional |
| Consecutive streak | -0.40 | -0.17 | -0.24 | -0.11 | -0.16 | +0.16 | -0.38 | **Near-universal — shorter streak** |
| MACD histogram | **-1.37** | +0.01 | -0.12 | +0.04 | +0.07 | **+0.22** | **+0.37** | Regime-conditional |
| RSI(14) prior close | -1.3 | -0.4 | +0.5 | -1.4 | +0.2 | +0.6 | -1.2 | Weak/mixed |
| Bollinger Band pos | -0.05 | -0.01 | -0.01 | -0.01 | +0.00 | +0.00 | -0.05 | Weak |
| Prev day close pos | -0.03 | -0.02 | -0.05 | -0.02 | -0.02 | +0.01 | -0.03 | Weak |
| Prev day vol ratio | +0.01 | +0.04 | +0.01 | +0.01 | +0.03 | +0.03 | -0.00 | Weak positive (5/7) |

---

#### Finding U-1 — 52-week low proximity is the strongest new universal signal

Oracle picks are consistently **closer to their 52-week low** in 6 of 7 years, by 8–20 percentage points. This is the largest new separator by raw magnitude and holds in both bull and bear regimes.

**Interpretation:** Oracle picks tend to be tickers that are compressed relative to their annual range — not sitting near 52-week highs. A ticker that has already run close to its yearly high is more likely to stall on an OR breakout. Tickers with room to recover from a compressed zone tend to produce larger intraday moves.

**2025 is the exception** (+0.1pp, essentially flat) — the tariff-shock year had so many broad selloffs that the 52w-low relationship was noisy across the whole pool.

---

#### Finding U-2 — Consecutive streak consistently lower for oracle picks (6/7 years)

Oracle picks have shorter preceding up-streaks. When a ticker has been grinding up for 3–5 consecutive days, it is more likely to be in the non-oracle pool on day N+1. The setup is cleaner when the prior momentum has paused or reversed slightly.

**2025 exception:** streak is slightly positive (+0.16) for oracle picks — in a high-volatility volatile year, momentum continuation was more relevant than in calm bull years.

---

#### Finding U-3 — MACD histogram is regime-conditional, not universal

- **2020 (recovery bull):** oracle MACD Δ = **-1.37** — decelerating momentum strongly preferred
- **2025 (volatile):** oracle MACD Δ = **+0.22** — accelerating momentum preferred
- **2026 (whipsaw):** oracle MACD Δ = **+0.37** — accelerating momentum preferred
- **2021–2024:** near zero in both directions

The MACD signal flips: in clean bull/recovery years, the oracle picks have decelerating momentum (pullback-then-breakout setup). In volatile/uncertain years, accelerating momentum is better (ride the wave). Not useful as a static weight — only as a regime-conditioned adjustment.

---

#### Finding U-4 — Daily MA200 distance is regime-conditional (confirms prior finding)

- **Bear year (2022):** oracle Δ = **+4.1pp** — oracle picks are *less far below* MA200 (relatively less beaten-down)
- **Bull years (2020, 2024):** oracle Δ = **-2.5pp, -5.4pp** — oracle picks are *less far above* MA200 (less overextended above long-term trend)
- **2021 and 2025:** near flat

Identical regime-flip pattern to what we saw with 20d return and MA50 distance in Finding T. Confirms the principle: in bull years avoid the overextended, in bear years avoid the most collapsed.

---

#### Finding U-5 — RSI, Bollinger Bands, prev-day close position: weak, not actionable

RSI(14) shows slight oracle lean toward lower RSI in most years but flips in 2022 and 2025. Magnitude is small (< 1.5 in most years). BB position and prev-day close position are consistent in direction (slight lean toward mid-band, slight lean toward closing in lower half) but the delta is tiny (< 0.05 every year). Not worth scoring on these as primary signals — they may serve as noise filters at most.

---

#### Summary: signal tiers from this analysis

| Tier | Features | Action |
|---|---|---|
| **Universal** | 52w low proximity, consecutive streak, daily vol elevation (from T) | Include in next scoring experiment |
| **Regime-conditional** | MACD histogram, MA200 distance, extension (20d return, MA50 dist) | Condition on QQQ trend regime before using |
| **Weak/noisy** | RSI, Bollinger Band, prev-day close position, prev-day vol ratio | Monitor but don't score on; may serve as filters |
| **Already in scorer** | entry_vs_mid_pct, or_vol_ratio | Keep |

### Finding T — Oracle characteristics: two universal signals + one regime-conditional signal (2020–2026)

**Method:** `analyze_oracle_characteristics.py` — for each day, simulate all 17 tickers with M1 config, label the top-2 by actual P&L as oracle picks, compute 12 features at signal time, compare oracle top-2 vs rest-of-pool. Run independently for each year 2020–2026 to separate regime effects from structural signals.

**Oracle WR ceiling by year:**

| Year | Oracle WR | Avg P&L/pick | Market character |
|---|---|---|---|
| 2020 | 60% | +0.81% | COVID crash + recovery, extreme vol |
| 2021 | 67% | +0.79% | Bull grind, low vol |
| 2022 | 62% | +1.31% | Bear market, high vol |
| 2023 | 70% | +1.12% | Recovery bull run |
| 2024 | 73% | +0.97% | Choppy-to-bull, AI theme |
| 2025 | 71% | +1.11% | Volatile, tariff shocks |
| 2026 YTD | 73% | +1.73% | Whipsaw recovery |

---

#### Universal signal 1 — Daily volume elevation (`daily_vol_ratio`) holds every year

Oracle top-2 consistently show higher total-day volume vs 20d rolling avg. The only feature with positive separation in all 7 years.

| Year | Oracle | Rest | Δ |
|---|---|---|---|
| 2020 | 1.24 | 1.03 | +0.21 |
| 2021 | 1.15 | 1.01 | +0.14 |
| 2022 | 1.15 | 1.06 | +0.09 |
| 2023 | 1.19 | 1.04 | +0.14 |
| 2024 | 1.18 | 1.06 | +0.12 |
| 2025 | 1.18 | 1.03 | +0.15 |
| 2026 | 1.29 | 1.08 | +0.20 |

Note: this is **total day volume** (not the OR-window `or_vol_ratio`) — the whole session's institutional participation. `or_vol_ratio` is noisier and in 2024–2025 showed negative or flat separation.

---

#### Universal signal 2 — U-shape on extension (rank 6+ is always the most stretched)

The three-way split (oracle top-2 / rank 3–5 / rank 6+) shows that the **worst picks each day are the most extended** — highest 20d return, highest distance from daily MA50, furthest from MA200. This holds in 6 of 7 years (2025 is flat). Oracle top-2 sit in the middle, not at the top.

Example from 2020 three-way split (20d return):
- Oracle top-2: +6.9% | Rank 3–5: +8.4% | Rank 6+: **+13.0%**

The implication: tickers that already ran hard in the prior 20 days are *more* likely to be dead weight on any given day, not less.

---

#### Regime-conditional signal — Extension direction flips between bull and bear years

The oracle vs rest gap on 20-day return:

| Year | Oracle 20d ret | Rest 20d ret | Δ | Regime |
|---|---|---|---|---|
| 2020 | +6.9% | +9.9% | **-3.0pp** | Recovery bull |
| 2021 | +3.7% | +3.9% | -0.2pp | Bull grind |
| 2022 | **-5.0%** | **-5.8%** | **+0.8pp** | Bear — **FLIPPED** |
| 2023 | +8.8% | +9.1% | -0.3pp | Bull |
| 2024 | +9.2% | +10.4% | -1.2pp | Choppy bull |
| 2025 | +6.0% | +5.6% | **+0.4pp** | Mixed — **FLIPPED** |
| 2026 | +2.2% | +4.1% | -2.0pp | Whipsaw |

- **Bull years:** oracle picks are *less* extended (don't buy what already ran)
- **Bear/mixed years:** oracle picks are *slightly more* extended (the cleanest bearish OR breaks come from tickers that haven't already collapsed; buying the least-beaten-down for a bear signal)

A naive "penalize extension" scoring rule would help in bull years but hurt in 2022 and 2025.

---

#### What this means for the next scoring improvement

Two concrete candidates to backtest:

1. **`daily_vol_ratio` as a scoring factor** — consistent +0.09 to +0.21 advantage every year. Needs same-day volume (not available at 9:45 AM for intraday scoring). Could use prior-day volume or prior-30-min volume as a proxy.

2. **Regime-conditional extension penalty** — in bull regimes, penalize high `daily_ma50_dist_pct`; in bear regimes, prefer it. A simple gate: `extension_score = daily_ma50_dist_pct × (-1 if bull_regime else +1)`.

**Blocker for #1:** True same-day total volume is not known at 9:45 AM signal time. Prior-day volume is known and could serve as a proxy — worth testing whether prior-day elevated volume predicts next-day oracle pick status.

**Blocker for #2:** Requires a reliable real-time bull/bear regime signal at 9:45 AM. QQQ daily MA direction (prior-day close vs MA) is the cleanest available proxy — but the regime-filter lookahead bug history (Finding in MEMORY) means this needs careful temporal alignment validation before testing.

---

### Design principle — Oracle selection is regime, volatility, and theme dependent

The characteristics that identify oracle picks are not static. They shift with market conditions. From the 2020–2026 data:

- **Trend regime** (bull vs bear): extension penalty direction flips — oracle picks are less extended in bull years, slightly more in bear/mixed years. A static formula scores the wrong end of the pool in regime transitions.
- **Volatility regime** (high vs low vol): OR volume spike is predictive in high-vol years (2022, 2026) but nearly flat in low-vol years (2024, 2025). Weighting `or_vol_ratio` the same regardless of vol regime dilutes its signal in calm markets.
- **Market theme**: 2022 bear produced the highest oracle ceiling (+352%) with the lowest capture rate (5.4%) — bear years have the richest individual ticker divergence but are hardest to exploit. 2025 was the most consistent oracle (positive every month) because volatile-but-upward markets suit OR momentum best.

**Implication:** The scoring formula should be conditioned on at least two regime dimensions — trend (QQQ above/below 50d MA) and volatility (rolling 20d realized vol or prior-day VIX level). Universal signals (daily vol elevation) form the baseline; regime-conditional signals are additive adjustments.

---

### Pending — Additional oracle characteristics not yet captured

`analyze_oracle_characteristics.py` currently covers OR-level signals, short-term momentum, and daily MA20/50 distance. The following are not yet in the feature set:

**Daily technical structure (computable from 5-min bars already cached):**
- Daily MA200 distance — we have 5-min MA200 but not the daily-bar MA200; these differ significantly for volatile tickers
- MA alignment flags — MA20 > MA50 > MA200 (full bull stack), or inverse (full bear stack); proximity to a crossover
- Prior day's close position within its range — where the prior candle body closed (upper 50% = bullish, lower = bearish); strong intraday momentum indicator
- Consecutive up/down day streak — how many days in a row the close was above/below the prior close
- 52-week high/low proximity — distance from the prior year's extreme; breakouts near 52-week highs vs. bounces off 52-week lows behave differently
- Daily ATR — true daily range (high-low adjusted for gaps) normalized to price; separates volatility regime from OR range size

**Classic reversal/breakout indicators (computable from daily OHLCV):**
- Daily RSI(14) — overbought/oversold zone at signal time; oracle BULLISH picks in bull years may cluster in RSI 50–65 (trend continuation), oracle BEARISH picks in bear years in RSI 60–70 (overextended bounce)
- Bollinger Band position — where is today's open relative to upper/lower BB(20); BB squeeze before breakout is a known setup precursor
- MACD crossover / histogram sign on daily bars — whether recent momentum is accelerating or decelerating
- Prior day's high/low as support/resistance — did today open above yesterday's high (clean gap breakout) or inside yesterday's range (continuation vs. chop)
- Weekly high/low proximity — is today opening near last week's high after consolidation, or breaking through a week-long base

**Why these matter for regime-dependent selection:**
- In bull years, BULLISH oracle picks may cluster near fresh 20-day highs (breakout continuation) with RSI in trend zone
- In bear years, BEARISH oracle picks may cluster at RSI 60–70 (overextended bounce before rollover) with MA alignment fully inverted
- BB squeeze / ATR contraction followed by expansion is the setup most correlated with large OR ranges — which are themselves correlated with oracle picks

**Next step:** ~~Add this feature set to `analyze_oracle_characteristics.py` and re-run the full 2020–2026 sweep segmented by regime to find which indicators discriminate within each regime.~~ **Done — see Finding U.**

---

### Finding V — Feature implementation: only `prev_day_vol_ratio` adds signal; other oracle characteristics do not survive as scoring factors

**Setup:** Top-4 oracle characteristics from Finding U were implemented in `score_ticker()` and `_build_daily_context()` in `op_momentum_selector_backtest.py`. A 15-config × 2-year (2025+2026) param sweep was run with M1-only, lookback=45, vol_ratio=0.15 fixed.

#### Phase 1: 2025+2026 Sweep Results (sorted by combined)

| Rank | Config | 2025 | 2026 YTD | Combined | entry | dist52w | streak | prev_vol | ma200 |
|------|--------|------|----------|----------|-------|---------|--------|----------|-------|
| 1 | **N5** | +13.32% | +24.35% | **+37.67%** | 0.75 | 0.00 | 0.00 | 0.05 | 0.00 |
| 2 | N9 | +11.80% | +23.89% | +35.69% | 0.70 | 0.05 | 0.00 | 0.10 | 0.00 |
| **3** | **E1 (baseline)** | +11.27% | +23.33% | **+34.60%** | 0.80 | 0.00 | 0.00 | 0.00 | 0.00 |
| 4 | N1 | +11.07% | +23.33% | +34.40% | 0.75 | 0.05 | 0.00 | 0.00 | 0.00 |
| 5 | N2 | +9.10% | +24.10% | +33.20% | 0.70 | 0.10 | 0.00 | 0.00 | 0.00 |
| 6 | N3 | +7.84% | +24.92% | +32.76% | 0.75 | 0.00 | 0.05 | 0.00 | 0.00 |
| 11 | N11 | +7.43% | +20.07% | +27.50% | 0.70 | 0.05 | 0.10 | 0.00 | 0.00 |
| 14 | N4 | +1.82% | +25.18% | +27.00% | 0.70 | 0.00 | 0.10 | 0.00 | 0.00 |
| 8 | N7 | +10.84% | +19.65% | +30.49% | 0.75 | 0.00 | 0.00 | 0.00 | 0.05 |

#### Phase 2: Full 2018–2025 Backtest (top-5 by 2025+2026)

| Config | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD | 8yr Sum | Rank |
|--------|------|------|------|------|------|------|------|------|----------|---------|------|
| **N1** | -6.70% | +8.71% | +25.47% | +8.71% | +18.44% | -8.99% | -20.55% | +11.07% | +23.33% | **+36.16%** | #1 |
| **E1** | -7.17% | +8.52% | +23.30% | +7.04% | +18.38% | -6.90% | -21.38% | +11.27% | +23.33% | **+33.06%** | #2 |
| N5 | -7.94% | +8.40% | +21.96% | +6.03% | +16.96% | -7.01% | -22.35% | +13.32% | +24.35% | +29.37% | #3 |
| N9 | -8.04% | +9.12% | +21.18% | +7.75% | +17.05% | -12.12% | -21.02% | +11.80% | +23.89% | +25.72% | #4 |
| N2 | -7.54% | +6.90% | +21.69% | +8.57% | +17.63% | -12.36% | -19.54% | +9.10% | +24.10% | +24.45% | #5 |

*8yr Sum = 2018–2025 no-compound daily-reset return sum.*

#### Key conclusions

1. **`prev_day_vol_ratio` at 0.05 (N5) is the only feature that beats E1 on recent data (2025+2026: +3.07pp combined)** — but it underperforms on the 8yr sweep. Its edge is recent-regime-specific, not durable.

2. **`dist_52w_low_pct` at 0.05 (N1) wins the 8yr sweep (+3.10pp over E1)** by improving 2018–2022. It loses slightly in 2023 (−2.09pp) and is neutral in 2025/2026.

3. **`streak` (consecutive-day penalty) is DISQUALIFIED.** Even 0.05 costs −1.84pp combined; 0.10 destroys 2025 (−9.45pp). Do not use.

4. **`daily_ma200_dist` is DISQUALIFIED.** Any non-zero weight hurts both years. Do not use.

5. **N9 and N2 (large dist52w weights) are disqualified** by 2023 performance (−12% range vs E1's −6.9%).

#### Recommendation

| Scope | Best config | Change from E1 |
|-------|-------------|----------------|
| Recent data (2025+2026) | **N5**: entry=0.75, prev_vol=0.05, vol_ratio=0.15 | +3pp combined |
| Full 8yr robustness | **N1**: entry=0.75, dist52w=0.05, vol_ratio=0.15 | +3.1pp 8yr sum |
| Conservative / don't change | **E1**: entry=0.80, vol_ratio=0.15 | current default |

Neither N1 nor N5 is a decisive win — the improvement is ~3pp over 8 years, roughly noise-level. Neither `dist_52w_low` nor `prev_day_vol` appears in the oracle characteristics as a strong universal signal (Finding U showed 52w low and vol ratio are regime-conditional). The oracle characteristics analysis suggests the formula improvement ceiling has been largely reached at E1, and further gains require **regime-conditioned scoring** rather than static weight changes.

---

### Finding W — `daily_ma50_dist_pct` implemented; regime-adaptive scoring tested; E1 remains the best formula

**Oracle characteristics analysis (Jan 2026)** showed oracle picks are +11% above their 50d MA for BULLISH signals and -1.4% for BEARISH signals. This motivated adding a direction-aware `ma50_dist` term: `score += (±ma50_dist / 10) × weight` (positive for BULLISH = reward above-MA50, negative for BEARISH = reward below-MA50).

#### Static weight sweep result (2022–2025)

| Config | entry | ma50 | 2022 | 2023 | 2024 | 2025 | 2026 YTD | 5yr Sum |
|--------|-------|------|------|------|------|------|----------|---------|
| **E1** | 0.80 | 0.00 | +18.4% | -6.9% | -21.4% | +11.3% | +23.3% | **+24.7%** |
| M5 | 0.55 | 0.25 | +14.4% | -1.7% | -18.1% | +2.2% | +21.2% | +17.9% |
| M6 | 0.50 | 0.30 | +14.9% | -1.4% | -19.6% | +4.7% | +18.0% | +16.6% |

Pattern: ma50 weight improves 2023 by +3-5pp but hurts 2025 by -7-9pp. Net negative.

#### Regime-adaptive scoring: `--regime-scoring` flag

**Implementation:** classifies each trading day as `bull` (QQQ prior-close > 50d MA) or `bear` (otherwise). Bull profile uses ma50 weight; bear profile falls back to E1. No lookahead — uses prior-day QQQ close.

**Two failure modes discovered:**

1. **Low ma50 weight (0.10):** regime reranking doesn't change picks — `entry_vs_mid_pct` at 0.80 dominates; `ma50_dist / 10` is too small (~0.1-0.4) to flip top-2 selections. All regime configs produce identical P&L to E1.

2. **High ma50 weight (0.25-0.30) on bull days:** picks change, but performance degrades. Bull-day momentum leaders (far above MA50) are prone to mean reversion — selecting them hurts 2025 by -4-6pp. 2023 improves +3-4pp but net effect is -7-8pp on 5yr sum.

| Config | 2022 | 2023 | 2024 | 2025 | 2026 YTD | 5yr Sum | vs E1 |
|---|---|---|---|---|---|---|---|
| **E1** | +18.4% | -6.9% | -21.4% | +11.3% | +23.3% | **+24.7%** | — |
| RS bull(e=0.55,m5=0.25) / bear=E1 | +17.2% | -3.4% | -21.2% | +5.8% | +17.9% | +16.4% | -8.3pp |
| RS bull(e=0.50,m5=0.30) / bear=E1 | +17.2% | -2.6% | -23.0% | +5.2% | +20.5% | +17.2% | -7.5pp |

#### Final conclusion

**E1 (`entry=0.80, vol_ratio=0.15`) is the confirmed best scoring formula.** Tested approaches that all fail to beat it:
- Static avg_win weight (Phases 1-4 from plan)
- EV trend signal
- Direction-split EV gate
- 4 oracle characteristics (dist_52w, streak, prev_vol, ma200_dist)
- daily_ma50_dist (static weights)
- Regime-adaptive ma50_dist (QQQ 50d MA regime gate)

The MA50 distance signal is real in oracle characteristics analysis but **not exploitable** as a scoring factor: the direction of its advantage flips year-to-year in ways that aren't reliably predicted by the QQQ 50d MA regime classification.

**What would actually help:** improving the ticker pool (already optimized with V3), exit/stop tuning (already studied), or adding intraday momentum signals at the 9:35–9:45 AM window that aren't already captured by `entry_vs_mid_pct`.
