# Rebalance interval: 2 weeks vs monthly, quarterly and trend-based schedules (2020–2026)

The question: would the recommended lists ([recommended_rules_2020_2026.md](recommended_rules_2020_2026.md)) do better if they were rebalanced less often, or on a schedule set by the market trend (QQQ against its 50- and 200-day averages)?

Script: `alpha_tech_tracker/research/rebalance_interval.py`, run one year at a time. Outputs: `research/top_performers_output/uptrend_formation/rebalance_interval/`:
- `<year>/summary.csv` and `<year>/by_offset.csv`: per tier, exit and schedule (and starting offset for fixed schedules)
- `<year>/qqq_trend.csv`: QQQ's trend state at each checkpoint
- `summary_by_year.csv`: all years chained together

## Setup

- **Rules:** the recommended Large and Small rules with their trailing stops (25% Large, 15% Small); each schedule was also run without stops.
- **Schedules:** the lists are rebuilt at the biweekly checkpoints, so every schedule rebalances on a subset of them and holds day by day in between. A stopped-out name sits in cash until the next rebalance.
  - **Fixed:** every checkpoint (2 weeks), every 2nd (about a month) or every 6th (about 3 months). Each was run from every starting offset, and the average is reported.
  - **Trend-based:** at each checkpoint, the wanted interval depends on QQQ's trend state: above both averages ("uptrend"), above the 200-day only, or below the 200-day. The book rebalances once that many checkpoints have passed since the last rebalance.
- **Each year is run separately:** it starts in cash on the year's first checkpoint, and daily data is cut at the year's end. The totals below chain the seven years.
- **Costs:** 10 bps per unit traded.

## Results with trailing stops

"Uptrend" means QQQ above both its 50- and 200-day averages; "else" covers every other state.

| Tier | Schedule | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* | 7-year total | Years ahead of 2 weeks | Turnover / year |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Large | **2 weeks** | 104% | 14% | −6% | 0% | 61% | 29% | 51% | **+581%** | | 13.8 |
| Large | 1 month | 81% | 9% | −16% | 6% | 58% | 24% | 33% | +360% | 1 | 8.1 |
| Large | 3 months | 60% | 21% | −22% | 8% | 44% | 28% | 26% | +276% | 2 | 3.3 |
| Large | uptrend 1m, else 2w | 68% | 19% | −6% | 8% | 41% | 39% | 44% | +472% | 3 | 10.0 |
| Large | uptrend 3m, else 2w | 50% | 12% | −6% | −2% | 57% | 47% | 42% | +407% | 1 | 7.2 |
| Large | uptrend 2w, else 1m | 97% | 13% | −18% | 0% | 66% | 8% | 31% | +328% | 1 | 10.9 |
| Large | uptrend 2w, else 3m | 79% | 15% | −29% | 3% | 62% | 21% | 10% | +225% | 3 | 9.0 |
| Small | 2 weeks | 73% | 36% | −8% | 21% | 7% | 8% | 26% | +277% | | 14.8 |
| Small | 1 month | 45% | 37% | −9% | 27% | 10% | 4% | 22% | +215% | 3 | 9.1 |
| Small | 3 months | 22% | 32% | −15% | 22% | 8% | 0% | 15% | +108% | 2 | 3.2 |
| Small | uptrend 1m, else 2w | 27% | 34% | −8% | 21% | 13% | 7% | 30% | +200% | 3 | 10.7 |
| Small | uptrend 3m, else 2w | 14% | 30% | −8% | 21% | 10% | −8% | 25% | +109% | 1 | 7.0 |
| Small | **uptrend 2w, else 1m** | 85% | 36% | −4% | 25% | 8% | 7% | 22% | +321% | 4 | 12.1 |
| Small | **uptrend 2w, else 3m** | 87% | 37% | −10% | 33% | 10% | 9% | 22% | **+347%** | **5** | 10.1 |

\* 2026 through Nov 6. A year counts as "ahead" when it beats 2 weeks by more than 0.5 points.

The QQQ trend at the checkpoints: below the 200-day at 23 of 26 checkpoints in 2022, at 2 in 2020 and 2023, at 1 in 2026, and at none in 2021 and 2024.

The fixed schedules depend heavily on their start date. For example, Large on a 3-month cycle ranged from 7% to 42% in 2026, and on a monthly cycle from 5% to 43% in 2025.

## Findings

1. **Large: keep the 2-week cycle.**
   - It is the best schedule over the seven years by about 3 points a year (32.3% vs 29.0% for the next best).
   - Holding longer in an uptrend gave up most of the 2020 rebound (104% → 50–68%).
   - Holding longer when the market is weak turned 2022's −6% into −16% to −29%.
   - The 180-day ranking with breakout slots needs frequent refreshes in every kind of market. Trend-based schedules only shuffled luck between years: "uptrend 3m" won 2025 by 18 points and lost 2020 by 54.
2. **Small: the opposite of Large.**
   - Both versions of "2 weeks in an uptrend, otherwise hold longer" beat 2 weeks: holding 3 months gave 24.4% a year vs 21.4%, ahead in 5 of 7 years, with about 30% less trading.
   - Most of the gain came from 2020. The rule held the post-crash list through the rebound instead of selling names that had just dipped.
   - A likely reason: small caps tend to recover after short pullbacks, so selling them on a dip locks in the low.
   - It was behind in 2022 (−10% vs −8%) and 2026 (22% vs 26%).
3. **Holding Small longer in an uptrend is wrong.**
   - It was about level with 2 weeks over 2023–2026, but turned 2020's 73% into 14–27%.
   - The earlier 2023–2026 view, that both directions helped Small, did not survive 2020.
4. **Fixed longer intervals never help.** Monthly and quarterly cycles lost for both tiers over the seven years.
5. **The trailing stops hurt slightly in 2022's choppy decline** (Large −6.3% vs −4.1% without; Small −7.9% vs −7.0%). They earn their keep in fast crashes such as 2020.

## Decision

- **Large:** 2 weeks, unchanged.
- **Small:** 2 weeks for now. The candidate is **"2 weeks while QQQ is above both its 50- and 200-day averages, otherwise hold 1 month."** Paper-track it next to the current Small list before switching. It is the milder of the two winners (23.3% a year, ahead in 4 of 7 years), and it depends less on when a dip happens than the 3-month version.

## Caveats

- **Chosen after the fact:** 8 schedules were tried on the same seven years, and the Small winner's edge comes mostly from one year (2020).
- **One path per year:** each trend-based schedule ran on a single path per year, while the fixed schedules showed how much the start date alone matters.
- **Rare weak markets:** QQQ was below its 200-day average at only 28 of 180 checkpoints, 23 of them in 2022, so the 200-day part of the trend rules is thinly tested.
- **Fresh start each year:** each year starts in cash, so the 2-week figures differ slightly from the continuous backtest (for example, 2025 Large: 29.0% here vs 32.4% continuous).
