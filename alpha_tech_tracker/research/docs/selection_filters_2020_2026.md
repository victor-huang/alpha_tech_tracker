# Cutting the momentum screen to a tradable list (2020–2026)

The early-momentum screen from [uptrend_formation_2020_2026.md](uptrend_formation_2020_2026.md) flags roughly 70–85 names per tier every two weeks. This study tests whether ranking those stocks and keeping a fixed top 15 per tier keeps the edge.

Script: `alpha_tech_tracker/research/selection_filters.py`. Outputs: `research/top_performers_output/uptrend_formation/selection_filters/`.

## Setup

- **Universe and checkpoints:** the same checkpoint panels as the uptrend study: start-of-year tiers, every 10 trading days, 2020-01-02 → 2026-11-06.
- **Excluded names:** closed-end funds (matched on sponsor + Trust/Fund in the name), the QQQ ETF, and BNY. BNY was tiered from another issuer's share history.
  - The funds had passed the ETF name filter. Any ranking that rewards low volatility filled up with them.
- **Signal test:** 60-day forward log return of the picks minus the average of stocks in the same checkpoint, tier and volatility quintile.
- **Portfolio test:**
  - Equal-weight top 15 per tier, rebalanced every checkpoint.
  - 10 bps cost per unit of traded weight, each side.
  - Optional gate: cash while QQQ is below its 200-day average.
  - Optional buffer: keep a holding while it stays within the top 40.
- **Comparison:** the equal-weight tier universe (gated and ungated), plus SPY, QQQ and IWM.

## Variants

| Variant | Eligible | Ranked by |
|---|---|---|
| early_momentum_all | early-momentum screen (all ~70–85 names) | — |
| mom120 | all | 120-day return |
| riskadj120 | all | 120-day return ÷ 60-day volatility |
| trend+riskadj120 | close > MA50 > MA200, MA200 rising | risk-adjusted 120-day return |
| …+persist | same, and ranked within the top 30 at the previous checkpoint | same |
| …+liquid | same, and 20-day median dollar volume ≥ $20M | same |
| trend+composite | trend filter | 0.4 risk-adj 120d + 0.2 near 52w high + 0.2 up-day share + 0.2 small biggest 1-day gain |
| trend+lowvol_control | trend filter | lowest 60-day volatility (control) |

## Portfolio results (gate on, top 15, no buffer unless noted)

| Tier | Variant | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|---|
| Benchmark | SPY | 14.0% | 17.4% | 0.84 | −29% |
| Benchmark | QQQ | 17.9% | 22.6% | 0.85 | −34% |
| Benchmark | IWM | 8.7% | 23.7% | 0.48 | −38% |
| Large | universe, ungated | 10.9% | 19.4% | 0.64 | −34% |
| Large | universe, gated | 10.9% | 11.6% | 0.95 | −14% |
| Large | early_momentum_all | 8.6% | 16.4% | 0.59 | −30% |
| Large | **trend+riskadj120** | **16.6%** | 20.7% | 0.85 | −22% |
| Large | mom120, buffer 40 | 19.9% | 29.5% | 0.77 | −40% |
| Large | trend+riskadj120+persist | 9.9% | 21.0% | 0.56 | −27% |
| Mid | universe, gated | 9.7% | 15.4% | 0.68 | −20% |
| Mid | early_momentum_all | 4.0% | 19.0% | 0.30 | −48% |
| Mid | trend+riskadj120 | 6.6% | 21.2% | 0.41 | −34% |
| Mid | trend+composite | 8.4% | 11.9% | 0.74 | −13% |
| Small | universe, gated | 11.6% | 19.5% | 0.66 | −31% |
| Small | early_momentum_all | 15.6% | 29.1% | 0.64 | −46% |
| Small | trend+riskadj120 | 6.9% | 27.2% | 0.38 | −51% |
| Small | **trend+composite** | **18.7%** | 16.7% | 1.11 | −11% |
| Small | trend+lowvol_control | 10.2% | 10.3% | 0.99 | −14% |

Calendar-year returns, gate on:

| Tier | Variant | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|---|---|
| Large | universe, gated | 20.7 | 21.9 | −4.7 | 8.3 | 14.5 | 13.1 | 4.6 |
| Large | trend+riskadj120 | 38.0 | 25.4 | −6.4 | −2.5 | 30.3 | 32.9 | 7.3 |
| Small | universe, gated | 40.5 | 26.0 | −9.2 | −0.3 | 12.4 | 21.3 | −1.6 |
| Small | trend+composite | 66.2 | 34.7 | −4.7 | 14.8 | 1.4 | 15.4 | 15.2 |
| — | SPY (ungated) | 15.7 | 31.2 | −19.0 | 26.0 | 25.3 | 18.2 | 8.5 |

## Findings

1. **The wide screen has no portfolio value on its own.** Holding all ~70–85 early-momentum names did worse than the plain tier universe in Large and Mid. Its Small-cap return came with 46% drawdowns. The winners are in it, but so are many names that fade.
2. **The market gate is the most reliable piece.** Gating the plain Large universe raises its Sharpe from 0.64 to 0.95 and cuts its max drawdown from −34% to −14%, at the same return. The gate improves Sharpe in 48 of 54 variant/tier/buffer combinations. The exceptions are mostly raw 120-day momentum without the trend filter. In 2022 its top names were energy stocks that kept rising while QQQ fell (+4% to +7% above same-volatility peers in below-average checkpoints).
3. **Large caps: trend filter + risk-adjusted 120-day momentum, top 15.** 16.6% CAGR against 10.9% for the gated universe and 14.0% for SPY. It beat the gated universe in 5 of 7 years and beat its same-volatility peers in 5 of 7 years. Its Sharpe (0.85) is only level with SPY's and below the gated universe's (0.95), so the extra return comes with extra risk.
4. **Small caps: trend filter + composite (smooth, near-high, risk-adjusted).** 18.7% CAGR with −11% max drawdown. The low-volatility control gets a similar Sharpe but only 10% CAGR. The composite also beat same-volatility peers in 5 of 7 years, so it adds return beyond simply holding calm stocks. 2020 is a large share of the gain (+66%). It still beat the gated universe in 2021, 2022, 2023 and 2026.
5. **Mid caps: no momentum ranking beats just holding the gated universe.** The low-volatility control (Sharpe 0.95) and the composite (0.74) are the best Mid variants.
6. **Persistence hurts.** Requiring a top-30 rank at the previous checkpoint cut Large CAGR from 16.6% to 9.9%. Waiting two weeks gives up the early part of the move.
7. **The liquidity floor ($20M a day) costs little** and is worth keeping for execution. **The rank-40 holding buffer** halves turnover. It helps raw 120-day momentum in Large caps but hurts most other variants.
8. **Raw 120-day momentum is a high-volatility bet.** In Large caps it earns 17–20% a year with −40% drawdowns, and in Mid caps it fell 30% in 2026. Adjusting for volatility trades some return for much less risk.

## Suggested list for the biweekly run (≈ 30 names)

- **Large:** trend filter + risk-adjusted 120-day momentum, top 15.
- **Small:** trend filter + composite, top 15, with a $20M dollar-volume floor.
- **Mid:** skip, or hold the low-volatility trend names as a defensive sleeve.
- **Market gate:** while QQQ is below its 200-day average, hold nothing new.

## Caveats

- **Survivorship:** the universe is stocks listed today, so 2020–2021 momentum picks that later delisted (SPACs, meme stocks) are missing. This flatters momentum the most.
- **Selection risk:**
  - Eight variants, three tiers and two gate settings were tested on the same seven years.
  - The composite weights were set once and not tuned, but choosing the best row is still selection.
  - Treat the winning rows as candidates to confirm on new data, not settled rules.
- **Few independent regimes:** gated periods are mostly 2022 and part of 2020. One bear market drives most of the gate's value.
- **Costs and execution:** 10 bps may be light for small caps. Results assume trading at the checkpoint close.
- **Earlier small-cap results may shift slightly:** the closed-end funds were also in the earlier uptrend study's Small-cap numbers. Those numbers are measured against same-volatility peers, so the funds should move them only a little.
- **BNY and B tickers:** BNY was excluded. B (now Barrick) has a ticker-reuse history that may affect a handful of Small-cap picks.

## Does time on the list help?

A stock's streak is the number of checkpoints in a row it has been on the list. The tables compare the next 60 days' return with same-volatility peers, by streak length. This was a one-off analysis, not part of `selection_filters.py`.

**The yearly top-10 winners stay on the early-momentum list far longer than other flagged stocks:**

| | Checkpoints on the list per year (median, of ~25) | Longest streak (median) |
|---|---|---|
| Winners | 10–15 | 6–9.5 |
| Other flagged stocks | 3 | 2–3 |

This is hindsight: a stock that rises all year stays on the list. The useful question is whether a long streak predicts more gains.

**Return beyond same-volatility peers over the next 60 days, by streak (early-momentum list):**

| Tier | 1 (new) | 2 | 3–4 | 5–8 | 9–16 |
|---|---|---|---|---|---|
| Large | −0.0% | +0.1% | +0.4% | +1.3% | +4.2% |
| Mid | −0.1% | +0.6% | +0.1% | +0.4% | +0.3% |
| Small | +0.8% | +1.6% | +0.9% | −0.8% | −7.0% |

**Large caps: a long streak is a plus.**
- In the top-15 list (trend + risk-adjusted 120-day momentum), excess rises from +1.1% for new entries to +5.2% at 5–8 checkpoints and +8.7% at 9–16. The 9–16 bucket has only 44 observations.
- **It isn't just stronger momentum:** among large caps in the top third by 120-day return, 9+ checkpoint streaks returned +4.3% against +1.5% for new entries.
- **It's broad:** 95 distinct stocks reached a 9+ streak. The most frequent were WDC, CIEN, ZM, NVDA, STX, TER and LITE.
- **By year:** long-streak excess was positive in 5 of 7 years, negative in 2021 and 2022. 2026 (+15.9%) is the biggest contributor.

**Small caps: a long streak is a minus.** Fresh entries do best. Strong small caps that have been on the list 9+ checkpoints lose about 7% against peers over the next 60 days, the worst in 2024 to 2026. In the small-cap composite top 15 the pattern is weaker, since few names stay long.

**Mid caps:** no consistent pattern.

**How to use it (to be confirmed in a portfolio test):**
- **Large:** rank long-streak names first, or don't drop them for a slightly higher-ranked newcomer.
- **Small:** consider dropping names after about 8 checkpoints (4 months) on the list.

This also explains why the earlier "persist" filter (ranked at the previous checkpoint) hurt. It removed only new entries, and in the Large top 15 those had the best next-two-week return of the short-streak names (+1.1%, against +0.3% for streak 2–4). It never added weight to the long streaks where the edge is.

### Portfolio test of the streak rules

Streak here is the number of checkpoints in a row on the early-momentum list. The three rules:

- **streak_first:** among the top 30 by score, rank longer streaks first.
- **hold_on_list:** keep a holding while it stays on the early-momentum list, even after it falls out of the top 15.
- **streak_cap:** exclude names with a streak above 8.

All runs use the gate, top 15 and no buffer.

| Tier | Variant | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|---|
| Large | trend+riskadj120 (base) | 16.6% | 20.7% | 0.85 | −22% |
| Large | + streak_first | 19.2% | 21.6% | 0.92 | −29% |
| Large | + hold_on_list | 15.8% | 21.3% | 0.80 | −25% |
| Large | + streak_cap | 14.9% | 18.2% | 0.85 | −22% |
| Small | trend+composite (base) | 18.7% | 16.7% | 1.11 | −11% |
| Small | + streak_cap | 19.0% | 16.7% | 1.13 | −11% |
| Small | mom120 (base) | 18.7% | 44.4% | 0.60 | −56% |
| Small | + streak_cap | 24.5% | 44.8% | 0.70 | −48% |

Calendar-year returns:

| Tier | Variant | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|---|---|
| Large | trend+riskadj120 | 38.0 | 25.4 | −6.4 | −2.5 | 30.3 | 32.9 | 7.3 |
| Large | + streak_first | 45.3 | 14.9 | −9.7 | −0.6 | 36.7 | 33.8 | 24.4 |
| Small | mom120 | 68.9 | 71.5 | −8.0 | 7.4 | −8.6 | 30.3 | −2.8 |
| Small | + streak_cap | 78.7 | 80.8 | −8.0 | 9.9 | −3.2 | 44.5 | 1.0 |

**Findings:**

- **Large, streak_first: the whole gain is 2026.** Over 2020–2025, both versions compound to the same 18.3% a year. It also adds 7 points of drawdown and lost 10 points in 2021. Not adopted. The signal result came from overlapping 60-day windows dominated by the 2026 memory and optical-networking runs (WDC, STX, LITE, CIEN).
- **Large, hold_on_list: worse.** Holding names after they leave the top 15 lowered return and Sharpe in all three tiers.
- **Small, streak_cap: consistent for raw momentum.** It improved the result in 6 of 7 years, with 2022 even, and cut the worst drop from −56% to −48%. This is the only streak result that holds year by year. For the recommended small-cap composite it changes almost nothing, because the composite rarely picks long-running names: it already penalises big single-day jumps and rewards steadiness.
- **Mid:** streak_cap lifts trend+riskadj120 from 6.6% to 8.4%, still below the gated universe (9.7%).

**Takeaway:**
- **Large:** a stock's time on the list doesn't add a usable rule beyond the momentum ranking.
- **Small:** the cap ("drop after ~4 months on the list") is worth keeping as a safeguard for any momentum-style small-cap list. The composite list already behaves this way.
