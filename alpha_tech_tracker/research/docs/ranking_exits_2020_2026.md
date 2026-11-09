# Momentum scores and exit rules for the top-15 lists (2020–2026)

Entry filters (industry strength, SEC growth, streaks) did not improve the top-15 lists in [selection_filters_2020_2026.md](selection_filters_2020_2026.md). This study tries the two remaining levers: a different ranking score, and rules for selling between the biweekly rebalances.

Script: `alpha_tech_tracker/research/ranking_exits.py`. Outputs: `research/top_performers_output/uptrend_formation/ranking_exits/`.

## Setup

- **Same universe and book as the selection study:**
  - Start-of-year tiers, checkpoints every 10 trading days, 2020-01-02 → 2026-11-06.
  - Equal-weight top 15 per tier, 10 bps per unit of traded weight.
  - No market gate, no holding buffer unless stated.
- **References** (from the selection study):
  - Large: trend + risk-adjusted 120-day momentum + clean (no faded jump or heavy-volume drop in 60 days).
  - Mid: trend + composite.
  - Small: trend + composite + prefer turnaround.
- **Daily book for exits:**
  - Holdings are followed day by day.
  - When a rule fires, the name is sold at that close (paying the 10 bps) and the money stays in cash until the next checkpoint.
  - With no rule, the daily book reproduces the biweekly backtest exactly: Large 20.1%, Small 15.2%.
- **Measurement:** returns, Sharpe and drawdown are measured on the biweekly series, like the selection study.

## New scores

| Score | How it's computed |
|---|---|
| resid120 | 120-day sum of daily log returns after removing the stock's SPY beta (beta from the trailing 250 days), divided by their volatility |
| industry_rel120 | 120-day return minus its Nasdaq industry median (5+ members), per unit of 60-day volatility |
| high52 | closeness to the 52-week high |
| skip20 | 120-day return excluding the last 20 days, per unit of volatility |
| blend | average percentile of risk_adj_120, resid120 and high52 |
| composite_resid | the composite score with resid120 in place of risk_adj_120 |

Each score was tested with the trend filter, with and without the "clean" exclusion. The Small-style scores were also tested with turnaround names moved to the front.

### Score results (top 15, no buffer)

"Better" counts the calendar years where the rule's return beat the reference's.

| Tier | Rule | CAGR | Sharpe | Max DD | Better |
|---|---|---|---|---|---|
| Large | **reference** | **20.1%** | **0.85** | **−30%** | |
| Large | resid120 + clean | 17.3% | 0.82 | −29% | 2/7 |
| Large | industry_rel120 + clean | 18.7% | 0.81 | −30% | 4/7 |
| Large | skip20 + clean | 15.6% | 0.71 | −31% | 2/7 |
| Large | high52, blend | lower | ≤ 0.70 | | ≤ 2/7 |
| Mid | **reference** | **4.1%** | **0.32** | **−32%** | |
| Mid | composite_resid | 4.5% | 0.35 | −32% | 5/7 |
| Mid | high52, buffer 40 | 7.0% | 0.45 | −33% | |
| Small | **reference** | **15.2%** | **0.73** | **−39%** | |
| Small | composite_resid + prefer turnaround | 15.4% | 0.74 | −40% | 4/7 |
| Small | blend | 13.5% | 0.59 | −42% | 5/7 |

**No score beats the references.**
- Residual momentum has slightly lower volatility, but it costs Large 2.8 points a year.
- Swapping it into the composite changes Small and Mid by noise-sized amounts.
- Mid stays below its equal-weight universe (9.3%) under every score.

## Exit and sizing rules

| Rule | Sells when |
|---|---|
| ma50 | the close is below the 50-day average |
| trail15 / trail25 | the close is 15% / 25% below its peak since entry |
| down_jump | a heavy-volume down day (move ≥ max(8%, 3σ) on ≥ 3× volume) |
| inverse_vol | no exit; weights ∝ 1 / 60-day volatility instead of equal |

### Exit results (top 15, no buffer)

| Tier | Rule | CAGR | Sharpe | Max DD | Exits / yr | Better | 2020 | 2022 | 2025 |
|---|---|---|---|---|---|---|---|---|---|
| Large | reference, no exit | 20.1% | 0.85 | −30% | 0 | | 53.3% | −8.3% | 30.2% |
| Large | **ma50** | 18.7% | **0.89** | **−21%** | 82 | 3/7 | 63.1% | −4.6% | 21.0% |
| Large | trail25 | 20.0% | 0.86 | −28% | 6 | 3/7 | | | |
| Large | trail15 | 14.6% | 0.69 | −28% | 36 | 2/7 | | | |
| Large | down_jump | 19.5% | 0.84 | −29% | 5 | 1/7 | | | |
| Large | inverse_vol | 8.9% | 0.47 | −40% | 0 | 1/7 | | | |
| Mid | reference, no exit | 4.1% | 0.32 | −32% | 0 | | | | |
| Mid | trail25 | 5.0% | 0.38 | −28% | 2 | 2/7 | | | |
| Small | reference, no exit | 15.2% | 0.73 | −39% | 0 | | 43.6% | −14.8% | 14.9% |
| Small | **trail15** | **17.1%** | **0.87** | **−26%** | 21 | 2/7 | 71.9% | −16.0% | 12.6% |
| Small | trail25 | 15.9% | 0.78 | −34% | 4 | 2/7 | 53.7% | −15.2% | 14.9% |
| Small | ma50 | 13.5% | 0.76 | −25% | 92 | 3/7 | | | |
| Small | inverse_vol + ma50 | 13.7% | 0.84 | −22% | 92 | 4/7 | | | |

## Findings

1. **Exits work as crash insurance, not as a return source.**
   - Large MA50 exit:
     - Cuts the worst drawdown from −30% to −21% and raises Sharpe from 0.85 to 0.89.
     - Gains in 2020 and 2022, gives back in 2023, 2025 and 2026.
     - Net cost is 1.4 points a year.
     - It trades a lot: about 82 exits a year, roughly 5 per slot.
   - Small 15% trailing stop:
     - Lifts CAGR from 15.2% to 17.1%, Sharpe from 0.73 to 0.87, and the drawdown from −39% to −26%.
     - Almost all the gain is the March 2020 crash; it is behind the reference in 5 of 7 years.
   - Both behave like the market gate: worth it if you want smaller drawdowns, but the evidence rests on two bear episodes.
2. **Wide stops do little and tight stops hurt Large.** The 25% trail barely fires (4–7 times a year). The 15% trail costs Large 5.5 points a year by selling leaders on normal pullbacks.
3. **A heavy-volume down day is not a useful exit.** Those names are already removed at entry by the "clean" rule, and selling on the day locks in the drop.
4. **Inverse-volatility weighting hurts Large badly** (20.1% → 8.9%). The biggest winners are the high-volatility names, and the weighting shrinks them. It only helps when combined with an exit for Small.
5. **Ranking scores are not the bottleneck.** Six alternative momentum definitions land within noise of risk-adjusted 120-day momentum, or below it.

## Suggested use

- Keep the lists from the selection study.
- If a smaller drawdown matters more than the last point of return, add **one** exit rule:
  - Large: sell on a close below the 50-day average.
  - Small: a 15% trailing stop from the peak since entry.
- Treat either as an alternative to the QQQ market gate, not something to stack on it: both pay off in the same crash years.
- Mid: still skip.

## Caveats

- **Execution:** exits assume selling at the close that triggered the rule. Real fills on a breakdown day, especially in small caps, will be worse than the flat 10 bps.
- **Few crashes:** the exit results depend mostly on 2020 and 2022. Two crashes are not enough to estimate the trade-off precisely.
- **Measurement:** drawdowns come from biweekly marks; intra-period drawdowns are deeper for the no-exit books.
- **Selection risk:** 16 scores × 3 tiers and 8 exit rules × 3 bases were tested on the same seven years.
- **Survivorship:** see the selection study's caveats.
