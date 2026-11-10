# Concentration: holding the top 3, 5, 10 or 15 names (2020–2026)

The question: how does the result change when only the top N names of each recommended list are held?

Script: `alpha_tech_tracker/research/concentration.py`. Outputs: `research/top_performers_output/uptrend_formation/concentration/2020_…_2026/`:
- `summary.csv`
- `by_year.csv`
- `top_contributors.csv`
- `walk_forward_grid.csv`, `walk_forward.csv` and `walk_forward_summary.csv` (the hindsight check below)

## Setup

- **Book:** one continuous book from Jan 2020 to Nov 6 2026 per list and N, equal weight, held day by day with the list's trailing stop. Costs are 10 bps per unit traded.
- **Lists:**
  - **Large, recommended:** 180-day return / vol^0.5, with the 3 gap-up + 2 new-high breakout slots in the first 5 places. Rebalanced every 2 weeks, 25% trailing stop.
  - **Large, score only:** the same ranking without breakout slots. Same schedule and stop.
  - **Small, recommended:** rebalanced every 2 weeks while QQQ is above both its 50- and 200-day averages, otherwise monthly ([rebalance_interval_2020_2026.md](rebalance_interval_2020_2026.md)). 15% trailing stop.
- **Measures:**
  - **Worst drop:** measured on rebalance dates only, so real drops within a period were deeper.
  - **Sharpe:** from the rebalance-period returns.

## Results

| List | Top N | CAGR | Total | Sharpe | Worst drop | Worst period | Turnover |
|---|---|---|---|---|---|---|---|
| Large, recommended | 15 | 31.3% | +545% | 1.11 | −27% | −19% | 97 |
| Large, recommended | **10** | **35.5%** | +701% | **1.16** | −26% | −21% | 116 |
| Large, recommended | 5 | 14.5% | +153% | 0.67 | −42% | −16% | 167 |
| Large, recommended | 3 | 11.3% | +108% | 0.50 | −47% | −17% | 170 |
| Large, score only | 15 | 23.8% | +331% | 0.85 | −37% | −20% | 68 |
| Large, score only | 10 | 35.0% | +681% | 1.04 | −31% | −22% | 69 |
| Large, score only | 5 | 49.9% | +1,495% | 1.11 | −41% | −25% | 74 |
| Large, score only | **3** | **64.5%** | **+2,912%** | **1.20** | **−48%** | **−27%** | 72 |
| Small | 15 | 22.8% | +307% | 1.13 | −18% | −16% | 86 |
| Small | 10 | 24.7% | +352% | 1.13 | −18% | −16% | 89 |
| Small | 5 | 29.7% | +494% | 1.05 | −25% | −16% | 89 |
| Small | 3 | 34.2% | +650% | 1.01 | −33% | −17% | 92 |

Results by year:

| List | Top N | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Large, recommended | 15 | 103% | 11% | −9% | −2% | 60% | 32% | 51% |
| Large, recommended | 10 | 139% | 13% | −8% | −1% | 76% | 30% | 43% |
| Large, score only | 3 | 195% | 45% | 2% | −14% | 147% | 116% | 51% |
| Large, score only | 5 | 167% | 30% | −10% | −14% | 154% | 72% | 35% |
| Small | 15 | 83% | 35% | −4% | 24% | 8% | 6% | 22% |
| Small | 3 | 111% | 48% | −29% | 32% | 10% | 38% | 68% |

\* Through Nov 6.

### Where the top-3 gains came from

These figures are for the top-3 books without stops, as the sum of each stock's weighted period returns.

| List | Stocks held over time | Share of gains from the top 5 | Top contributors |
|---|---|---|---|
| Large, score only | 140 | 53% | SNDK (2025–26), APP (2024), TSLA (2020), PDD, VST, SE, PLTR, VRT |
| Small | 193 | 58% | WLDN, MSTR (one +78% two-week period in 2020), ANF, VITL, UNFI |

## Findings

1. **The ranking is informative at the very top.**
   - In the score-only Large list, return rises steadily as N shrinks: 24% → 35% → 50% → 65%.
   - Sharpe also rises (0.85 → 1.20), so the gain is not only extra risk.
2. **Breakout slots and concentration don't mix.**
   - On the 15-name Large list the slots add 7.5 points a year (31.3% vs 23.8%).
   - On a top-3 or top-5 list they are the whole list: pure breakout chasing, at 11–15% a year.
3. **Concentration is a bet on catching a few big winners.**
   - Five stocks produced over half the top-3 gains.
   - Missing one of SNDK or APP would change the result materially.
   - Worst drops reach −48% at rebalances, deeper within periods, and a single two-week period lost 27%.
4. **Small gains less from concentration.** Sharpe falls as N shrinks, and the top 3 lost 29% in 2022.
5. **Large top 10 (recommended rule) is the best risk-adjusted Large book.** It gives 35.5% a year, Sharpe 1.16 and a worst drop of −26%.

## Hindsight check

Three checks on whether the 64.5% top-3 result leans on hindsight. Checks 1 and 2 were run from a one-off script with the same inputs and books; check 3 is part of `concentration.py`.

1. **No future data enters the ranking.**
   - Every ranking input (`ret_180d`, `vol_60d`, the averages, breakout flags, SEC factors) uses data up to the checkpoint close only.
   - The panel's forward columns (`fwd_ret`, `ret_to_end`, `excess`) feed the evaluation reports only.
   - Tiers are set from the last close before each year. The share count is the median of filings from 120 days before to 60 days after that close, which is a minor leak of share count only, with no price information.
2. **Trading at the signal's own close adds a little.** Buying at the next day's close instead:

   | Large list | Top N | Same close | Next-day close |
   |---|---|---|---|
   | Score only | 3 | 64.5% | 60.7% |
   | Score only | 5 | 49.9% | 46.2% |
   | Recommended (slots) | 15 | 31.3% | 28.3% |

3. **The 180-day choice holds up out of sample.**
   - **Method:** all 60 walk-forward-tuning settings were run as Large books holding the top 3, 5 or 15, with a 25% trailing stop and 2-week rebalancing. The settings are 5 lookbacks × 3 volatility powers × clean filter on/off × breakout slots on/off.
   - **Selection:** for each test year, the setting with the best compounded return over the earlier years only was chosen, and its return in the test year recorded.
   - **Outputs:** `walk_forward_grid.csv`, `walk_forward.csv` and `walk_forward_summary.csv`.

   Top 3, setting chosen each year:

   | Test year | Trained on | Setting chosen | Test-year return | Its rank of 60 | Median setting |
   |---|---|---|---|---|---|
   | 2021 | 2020 | 180-day, vol^0, clean | 24% | 9 | −5% |
   | 2022 | 2020–21 | 180-day / vol^0.5, clean | −3% | 6 | −22% |
   | 2023 | 2020–22 | 180-day / vol^0.5, clean | −24% | 58 | 22% |
   | 2024 | 2020–23 | 180-day / vol^0.5 | 147% | 9 | 35% |
   | 2025 | 2020–24 | 180-day, vol^0, clean | 92% | 4 | −8% |
   | 2026* | 2020–25 | 180-day, vol^0, clean | 157% | 2 | 28% |

   CAGR over 2022–2026:

   | Top N | Walk-forward (out of sample) | 180-day / vol^0.5, fixed (in sample) | Best setting in hindsight | Median setting |
   |---|---|---|---|---|
   | 3 | **55%** | 48% | 65% | 9% |
   | 5 | **34%** | 36% | 45% | 7% |
   | 15 | **23%** | 18% (23% with slots) | 23% | 13% |

   - Every year's choice was a 180-day setting, starting from 2020 data alone. The fixed 180-day / vol^0.5 setting is therefore not a hindsight pick.
   - At 15 names, the walk-forward chose the recommended rule (180-day / vol^0.5 + slots) every year from 2022 on, so its backtest carries almost no selection bias.
   - The setting matters enormously: the median setting made under 10% a year at 3 or 5 names.
   - Single years swing hard. In 2023 the top-3 choice ranked 58th of 60 and lost 24% while the median setting made 22%.

\* Through Nov 6.

**Conclusion:**
- **Formula:** no look-ahead was found in the formula itself.
- **Setting choice:** the 180-day setting was chosen out of sample in every test year, so the top-3 result is not mainly a lucky pick. An earlier version of this check called it one, based on how much worse the other lookbacks did. That comparison measured how sensitive the book is to the setting, not hindsight.
- **What still flatters it:**
  - The grid itself (lookbacks, volatility powers, slots) was designed in 2026.
  - Survivorship (only stocks listed today) helps concentrated books most.
  - Same-close execution adds about 4 points a year.
  - Only 5–6 test years.
- **Expectation:** plan for roughly 40–50% a year for Large top 3, with −50% or worse drawdowns and occasional years like 2023's −24%.
- **Risk:** the 15-name list is far less sensitive to the setting.

## Decision

- **Main lists:** unchanged for now. Large top 10 is the safer upgrade if the account moves off 15.
- **Paper-tracked:**
  - **Large top 3, ranked by the 180-day score alone, with a 25% trailing stop:** added to `paper_lists` as `large_top3` and checked daily by `exit_watch`. It is a candidate for a small satellite allocation only. Expect less than the backtest (see the hindsight check).
  - **Small:** "2 weeks in an uptrend, otherwise monthly" ([rebalance_interval_2020_2026.md](rebalance_interval_2020_2026.md)).

## Caveats

- **Selection luck:** the most concentrated books rest on a handful of stocks. The walk-forward check covers the choice of setting but not the design of the grid.
- **Execution:** closing-price fills and 10 bps costs flatter concentrated positions, especially in small caps.
- **Drawdowns understated:** they are measured at rebalance dates only.
- **Survivorship:** the universe is stocks listed today, as in [selection_filters_2020_2026.md](selection_filters_2020_2026.md).
