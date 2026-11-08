# Cutting the momentum screen to a tradable list (2020–2026)

The early-momentum screen from [uptrend_formation_2020_2026.md](uptrend_formation_2020_2026.md) flags roughly 70–85 names per tier every two weeks. This study tests whether ranking those stocks and keeping a fixed top 15 per tier keeps the edge.

Script: `alpha_tech_tracker/research/selection_filters.py`. Outputs: `research/top_performers_output/uptrend_formation/selection_filters/`. Related factor work: [winner_factors_2020_2026.md](winner_factors_2020_2026.md).

> **Correction (2026-11-08):** the first version of this report had a market-gate bug that overstated every gated result.
>
> - **The bug:** the backtest loaded prices only from November 2019. The QQQ 200-day average then had too little history until about mid-2020, so it read as "below average". Gated portfolios sat in cash from January to about June 2020, which accidentally skipped the COVID crash.
> - **What it inflated:** gated returns, Sharpe ratios and drawdowns. The small-cap composite's "18.7% a year, −11% max drawdown" was mostly this artifact.
> - **The fix:** prices now load from October 2018, and every number below is from the corrected run.
> - **What was unaffected:** the signal tests (excess vs same-volatility peers) in the uptrend and factor studies loaded enough history.

## Setup

- **Universe and checkpoints:** the same checkpoint panels as the uptrend study: start-of-year tiers, every 10 trading days, 2020-01-02 → 2026-11-06.
- **Excluded names:** closed-end funds (matched on sponsor + Trust/Fund in the name), the QQQ ETF, and BNY. BNY was tiered from another issuer's share history. The funds had passed the ETF name filter, and any ranking that rewards low volatility filled up with them.
- **Signal test:** 60-day forward log return of the picks minus the average of stocks in the same checkpoint, tier and volatility quintile.
- **Portfolio test:**
  - Equal-weight top 15 per tier, rebalanced every checkpoint.
  - 10 bps cost per unit of traded weight, each side.
  - Optional gate: cash while QQQ is below its 200-day average.
  - Optional buffer: keep a holding while it stays within the top 40.
- **Comparison:** the equal-weight tier universe, SPY, QQQ and IWM.

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
| streak / factor variants | see the sections below | |

## Portfolio results (top 15, no buffer)

| Tier | Variant | CAGR (no gate) | Sharpe | Max DD | CAGR (gated) | Sharpe (gated) |
|---|---|---|---|---|---|---|
| Benchmark | SPY | 14.0% | 0.84 | −29% | | |
| Benchmark | QQQ | 17.9% | 0.85 | −34% | | |
| Benchmark | IWM | 8.7% | 0.48 | −38% | | |
| Large | universe | 10.9% | 0.64 | −34% | 7.5% | 0.53 |
| Large | early_momentum_all | 5.4% | 0.36 | −43% | 6.6% | 0.43 |
| Large | mom120 | 25.2% | 0.82 | −44% | 16.7% | 0.64 |
| Large | **trend+riskadj120** | **17.8%** | 0.78 | −30% | 15.3% | 0.73 |
| Large | trend+riskadj120+persist | 8.1% | 0.43 | −35% | 7.1% | 0.41 |
| Large | trend+composite | 5.7% | 0.43 | −26% | 5.9% | 0.49 |
| Mid | universe | 9.3% | 0.50 | −39% | 5.9% | 0.39 |
| Mid | mom120 | 11.1% | 0.46 | −58% | 10.8% | 0.46 |
| Mid | trend+riskadj120 | 0.5% | 0.15 | −50% | 3.0% | 0.25 |
| Mid | trend+composite | 4.1% | 0.32 | −32% | 4.5% | 0.37 |
| Small | universe | 10.8% | 0.51 | −43% | 7.4% | 0.42 |
| Small | early_momentum_all | 4.8% | 0.32 | −56% | 9.6% | 0.45 |
| Small | mom120 | 19.3% | 0.60 | −54% | 11.1% | 0.46 |
| Small | trend+riskadj120 | 3.3% | 0.27 | −54% | 1.1% | 0.19 |
| Small | **trend+composite** | **13.1%** | 0.66 | −41% | 13.0% | 0.67 |
| Small | trend+lowvol_control | 3.5% | 0.29 | −42% | 4.7% | 0.36 |

Calendar-year returns (no gate):

| Tier | Variant | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|---|---|
| — | SPY | 15.7 | 31.2 | −19.0 | 26.0 | 25.3 | 18.2 | 8.5 |
| Large | universe | 16.9 | 21.9 | −17.9 | 18.6 | 14.5 | 17.6 | 10.4 |
| Large | trend+riskadj120 | 45.7 | 25.4 | −10.0 | 2.9 | 30.3 | 29.6 | 10.1 |
| — | IWM | 18.4 | 17.5 | −21.9 | 16.8 | 12.1 | 13.8 | 10.8 |
| Small | universe | 31.6 | 26.0 | −27.8 | 16.1 | 12.4 | 21.9 | 7.2 |
| Small | trend+composite | 19.4 | 34.7 | −11.8 | 24.8 | 1.4 | 12.0 | 17.6 |

## Findings

1. **The wide screen has no portfolio value on its own.** Holding all ~70–85 early-momentum names did worse than the plain tier universe in every tier: 5.4%, −0.5% and 4.8% a year for Large, Mid and Small. The winners are in it, but so are many names that fade.
2. **Large caps: trend filter + risk-adjusted 120-day momentum, top 15.** 17.8% a year against 10.9% for the Large universe and 14.0% for SPY, with a −30% max drawdown (SPY −29%). It beat the universe in 5 of 7 years, but its Sharpe (0.78) is a little below SPY's (0.84). Raw 120-day momentum earns more (25%) but has −44% drawdowns.
3. **Small caps: trend filter + composite.** 13.1% a year against 10.8% for the Small universe and 8.7% for IWM, with a similar −41% drawdown. It is a modest improvement, and 2024 (+1.4%) was weak. The low-volatility control earns only 3.5%, so the composite's return isn't just from holding calm stocks.
4. **Mid caps: no ranking beats the plain universe.** Only raw momentum (11.1%) edges past it, with −58% drawdowns.
5. **The market gate as a cash switch is mixed.**
   - It improved Sharpe in 86 of 159 variant/tier/buffer combinations.
   - It cuts the 2022 losses sharply, but it sat in cash through the V-shaped rebound after the March 2020 crash and through parts of 2023.
   - On the plain universes it lowers both return and Sharpe.
   - It helps most for the wide, weak lists (early_momentum_all and the Mid lists).
   - This differs from the signal result. Momentum beating same-volatility peers mainly while QQQ is above its 200-day average still holds; that is relative performance, not a reason to hold cash.
6. **Persistence hurts.** Requiring a top-30 rank at the previous checkpoint cut Large CAGR from 17.8% to 8.1%. Waiting two weeks gives up the early part of the move.
7. **The rank-40 holding buffer** halves turnover. It helps raw 120-day momentum in Large caps (25.2% → 30.7%) but hurts the other variants: trend+riskadj120 Large 17.8% → 13.4%, composite Small 13.1% → 9.5%.

## Does time on the list help?

A stock's streak is the number of checkpoints in a row it has been on the early-momentum list. The signal tables below come from a one-off analysis; the portfolio rules are in `selection_filters.py`.

**The yearly top-10 winners stay on the list far longer than other flagged stocks:**

| | Checkpoints on the list per year (median, of ~25) | Longest streak (median) |
|---|---|---|
| Winners | 10–15 | 6–9.5 |
| Other flagged stocks | 3 | 2–3 |

This is hindsight: a stock that rises all year stays on the list.

**Return beyond same-volatility peers over the next 60 days, by streak (early-momentum list):**

| Tier | 1 (new) | 2 | 3–4 | 5–8 | 9–16 |
|---|---|---|---|---|---|
| Large | −0.0% | +0.1% | +0.4% | +1.3% | +4.2% |
| Mid | −0.1% | +0.6% | +0.1% | +0.4% | +0.3% |
| Small | +0.8% | +1.6% | +0.9% | −0.8% | −7.0% |

- **Large:** long streaks look like a plus. This holds after controlling for momentum (top-third 120-day return: +4.3% for 9+ streaks against +1.5% for new entries) and spans 95 distinct stocks. 2026 is the biggest contributor.
- **Small:** long streaks are a minus. Strong small caps on the list 9+ checkpoints lag by about 7%.
- **Persistence:** this explains why the persistence filter hurt. It removed only new entries, which in the Large top 15 had the best next-two-week return (+1.1%, against +0.3% for streaks of 2–4).

**Portfolio test of the streak rules.** All runs hold the top 15 with no buffer; the gated column is in parentheses. The rules:

- **streak_first:** among the top 30, rank longer streaks first.
- **hold_on_list:** keep a holding while it stays on the early-momentum list.
- **streak_cap:** exclude names with a streak above 8.

| Tier | Variant | CAGR | Sharpe | Max DD | Years better than base (no gate) | CAGR 2020–2025 vs base |
|---|---|---|---|---|---|---|
| Large | trend+riskadj120 (base) | 17.8% (15.3%) | 0.78 | −30% | | |
| Large | + streak_first | 19.4% (17.4%) | 0.80 | −33% | 5/7 | 17.8% vs 19.1% |
| Large | + hold_on_list | 15.3% (14.5%) | 0.68 | −31% | | |
| Large | + streak_cap | 15.9% (13.6%) | 0.75 | −30% | | |
| Small | trend+composite (base) | 13.1% (13.0%) | 0.66 | −41% | | |
| Small | + streak_cap | 13.5% (13.3%) | 0.67 | −41% | | |
| Small | mom120 (base) | 19.3% (11.1%) | 0.60 | −54% | | |
| Small | + streak_cap | 24.1% (16.5%) | 0.67 | −50% | 6/7 | 26.4% vs 21.6% |

- **Large, streak_first: not adopted.** Its edge is all 2026 (+28.6% against +10.1%). Over 2020–2025 it compounds *below* the base (17.8% vs 19.1%), and it lost 10 points in 2021 and 2022.
- **hold_on_list: worse** in every tier.
- **Small, streak_cap: the one streak rule that holds.** For raw momentum it is better in 6 of 7 years, gated or not. The composite rarely holds long-running names, so the cap barely changes it.

## Factor rules: turnaround, faded jumps and industry groups

These variants use the factors from [winner_factors_2020_2026.md](winner_factors_2020_2026.md):

- **clean:** exclude names with a faded up-jump or a heavy-volume drop in the last 60 days.
- **no_weak_group:** exclude bottom-20% industries.
- **top_group:** require a top-20% industry.
- **prefer_leader / prefer_turnaround:** within the top 30, move industry leaders or turnaround names to the front.
- **combo:** clean + no_weak_group + prefer leader and turnaround.

| Tier | Variant | CAGR (no gate) | Sharpe | Max DD | Years better than base | CAGR (gated) |
|---|---|---|---|---|---|---|
| Large | trend+riskadj120 (base) | 17.8% | 0.78 | −30% | | 15.3% |
| Large | **+ clean** | **20.1%** | **0.85** | −30% | 5/7 | 16.8% |
| Large | + no_weak_group | 17.7% | 0.77 | −31% | 4/7 | 14.7% |
| Large | + top_group | 7.4% | 0.41 | −30% | 1/7 | 6.3% |
| Large | + prefer_leader | 12.9% | 0.59 | −34% | 0/7 | 11.4% |
| Large | + prefer_turnaround | 18.0% | 0.79 | −31% | 2/7 | 16.2% |
| Large | + combo | 14.4% | 0.65 | −32% | 2/7 | 12.1% |
| Mid | trend+riskadj120 (base) | 0.5% | 0.15 | −50% | | 3.0% |
| Mid | + clean | 1.9% | 0.21 | −47% | 4/7 | 4.7% |
| Mid | + combo | 2.5% | 0.23 | −38% | 4/7 | 2.6% |
| Small | trend+composite (base) | 13.1% | 0.66 | −41% | | 13.0% |
| Small | + clean | 12.4% | 0.64 | −41% | 3/7 | 12.5% |
| Small | + no_weak_group | 13.3% | 0.67 | −41% | 4/7 | 13.7% |
| Small | + top_group | 15.6% | 0.66 | −50% | 4/7 | 16.6% |
| Small | + prefer_leader | 13.8% | 0.65 | −42% | 4/7 | 15.7% |
| Small | **+ prefer_turnaround** | **15.2%** | **0.73** | −39% | 5/7 | 15.6% |
| Small | trend+riskadj120 (base) | 3.3% | 0.27 | −54% | | 1.1% |
| Small | + combo | 11.4% | 0.48 | −45% | 5/7 | 10.5% |

Calendar-year returns (no gate):

| Tier | Variant | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|---|---|
| Large | trend+riskadj120 | 45.7 | 25.4 | −10.0 | 2.9 | 30.3 | 29.6 | 10.1 |
| Large | + clean | 53.3 | 30.5 | −8.3 | 2.9 | 33.7 | 30.2 | 9.2 |
| Small | trend+composite | 19.4 | 34.7 | −11.8 | 24.8 | 1.4 | 12.0 | 17.6 |
| Small | + prefer_turnaround | 43.6 | 27.0 | −14.8 | 25.0 | 1.8 | 14.9 | 18.4 |

- **Large, clean: the most reliable improvement found.** Dropping names with a faded jump or a heavy-volume drop raised return in 5 of 7 years (one tie). It also holds over 2020–2025 (21.9% vs 19.1%). The Sharpe of 0.85 now matches SPY, with a higher return. This matches the signal finding that faded jumps and heavy-volume drops lag their peers by 3–6%.
- **Large, industry filters hurt in a portfolio**, although top-industry names beat peers in the signal test. Requiring a top-20% industry cut the return to 7.4%; favouring leaders cut it to 12.9%. The likely cause, not yet verified: the ranking then piles 15 names into one or two hot industries, so they reverse together.
- **Small, prefer_turnaround helps, but mostly via 2020.** +2.1 points a year and Sharpe 0.66 → 0.73. Excluding the 2020 rebound (+43.6% vs +19.4%), it is ahead in 4 of the other 6 years by 0.3–2.9 points and behind in 2021 and 2022.
- **Small, top_group** raises return (15.6%) but deepens the drawdown to −50%.
- **Mid:** still nothing beats the plain universe.
- **Turnaround and the combo rescue the weak small-cap risk-adjusted list** (3.3% → 11.4%), but it still trails the composite.

## SEC fundamentals rules

Sales and earnings growth from SEC filings ([winner_factors_2020_2026.md](winner_factors_2020_2026.md#sales-and-earnings-growth-from-sec-filings)) were tested on top of the recommended lists. None improved them:

| Tier | Variant | CAGR (no gate) | Sharpe | Max DD | Years better than base | CAGR (gated) |
|---|---|---|---|---|---|---|
| Large | trend+riskadj120+clean (base) | 20.1% | 0.85 | −30% | | 16.8% |
| Large | + prefer sales growth / combo | 18.2% | 0.76 | −33% | 3/7 | 13.8% |
| Large | + require sales growth ≥ 25% | 21.4% | 0.82 | −37% | 3/7 | 17.8% |
| Large | + prefer margin / earnings growth | 15.6% | 0.70 | −33% | 3/7 | 13.0% |
| Mid | trend+riskadj120+clean (base) | 1.9% | 0.21 | −47% | | 4.7% |
| Mid | + require sales growth ≥ 25% | 4.5% | 0.30 | −41% | 5/7 | 4.7% |
| Small | trend+composite+prefer_turnaround (base) | 15.2% | 0.73 | −39% | | 15.6% |
| Small | + exclude sharp sales slowdown | 13.7% | 0.65 | −42% | 4/7 | 14.4% |
| Small | + prefer two quarters of sales acceleration | 14.6% | 0.71 | −38% | 3/7 | 12.6% |
| Small | composite + prefer growth_accel_combo | 12.8% | 0.65 | −41% | 2/7 | 11.6% |

## Suggested list for the biweekly run (≈ 30 names)

- **Large:** trend filter + risk-adjusted 120-day momentum, excluding names with a faded jump or a heavy-volume drop in the last 60 days. Top 15.
- **Small:** trend filter + composite, with turnaround names moved to the front of the top 30. Top 15, with a $20M dollar-volume floor and the 8-checkpoint streak cap as safeguards.
- **Mid:** skip.
- **Market gate:** optional. It reduces 2022-style bear-market losses but cost 0–3.5 points a year over this period by missing the 2020 rebound: Large list 17.8% → 15.3%, Small composite unchanged.

## Caveats

- **Survivorship:** the universe is stocks listed today, so 2020–2021 momentum picks that later delisted (SPACs, meme stocks) are missing. This flatters momentum and turnaround the most.
- **Selection risk:**
  - Over 30 variants were tested on the same seven years.
  - The composite weights and factor thresholds were set once, not tuned, but choosing the best row is still selection.
  - Treat the winning rows as candidates to confirm on new data.
- **Few independent regimes:** the gate's value rests on one bear market (2022) and one crash (2020).
- **Costs and execution:** 10 bps may be light for small caps. Results assume trading at the checkpoint close.
- **Industry labels:** they are today's Nasdaq labels, applied to all years.
- **BNY and B tickers:** BNY was excluded. B (now Barrick) has a ticker-reuse history that may affect a handful of Small-cap picks.
