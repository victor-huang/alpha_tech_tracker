# Walk-forward tuning of the momentum ranking (2020–2026)

The question: can tuning the ranking catch each year's top-10 winners earlier on years it has not seen, or does it only fit the years it was tuned on?

Script: `alpha_tech_tracker/research/walk_forward_tuning.py`. Outputs: `research/top_performers_output/uptrend_formation/walk_forward_tuning/`:
- `grid_by_year.csv`: every setting × tier × year.
- `walk_forward.csv`: the setting chosen each year and its test-year result.

Background for this study:
- The 2025 and 2026 winner views (`winner_progression.py --years 2025|2026`) both showed the plain 120-day ranking catching winners earlier than the risk-adjusted one.
- 2025's Large winners clustered in gold miners (AU, GFI, KGC), data storage (WDC, STX, MU) and AI networking (CLS, CIEN).

## Setup

- **Grid:** 60 settings, each using the trend filter, top 15 per tier, no buffer and no gate:
  - lookback: 60, 90, 120, 180 or 250-day return
  - volatility adjustment: return / vol_60d^a, with a = 0, 0.5 or 1
  - clean exclusion: on or off
  - 3 big-jump + 2 new-high breakout slots: on or off
- **Per setting, tier and year:**
  - book return
  - winners held
  - median share of the year's log gain still ahead when first held
  - mean share of the year's log gain earned (0 for a winner never held)
- **Walk-forward:** for each test year from 2022 to 2026, the setting with the best record over all earlier years was chosen and scored on the test year. "Best" was judged two ways: compounded book return, or mean winner capture.
- **References:** the current recommended rules, which were chosen with all seven years and so are not a fair out-of-sample comparison themselves.

## Results, 2022–2026 test years only

| Tier | Approach | CAGR | Winners held (of 50) | Median gain ahead at first hold | Mean share of winner gains earned |
|---|---|---|---|---|---|
| Large | current rule (risk-adj 120d + clean) | 12.4% | 46 | 38% | 12% |
| Large | plain 120d + clean (fixed) | 18.0% | 50 | 41% | 21% |
| Large | **walk-forward, chosen by book return** | **22.8%** | 46 | 40% | 18% |
| Large | walk-forward, chosen by winner capture | 13.6% | 50 | 46% | **26%** |
| Large | best setting in hindsight (ret180 / vol^0.5 + slots) | 23.6% | 48 | 46% | 19% |
| Mid | current (trend + composite) | 0.0% | 8 | 29% | 0% |
| Mid | walk-forward by return | −2.2% | 45 | 30% | 20% |
| Small | current (composite + no dilution + gross profit) | **11.8%** | 10 | 31% | 1% |
| Small | walk-forward by return | −3.0% | 36 | 51% | 11% |
| Small | walk-forward by winner capture | −3.3% | 38 | 44% | 10% |

Settings chosen each year (Large, by book return):

| Test year | Chosen setting | Year return | Current rule that year |
|---|---|---|---|
| 2022 | ret180 / vol^1 + slots | −6.9% | −8.3% |
| 2023 | ret180 / vol^1 + slots | −5.0% | 2.9% |
| 2024 | ret180 / vol^0.5 + slots | 58.6% | 33.7% |
| 2025 | ret180 / vol^0.5 + slots | 30.7% | 30.2% |
| 2026 | ret180 / vol^0.5 + slots | 52.2% | 9.2% |

### The chosen Large setting over the full period

These figures are in-sample, because the setting was picked partly on these years.

| Rule | CAGR | Sharpe | Max DD | Vol | Turnover / rebalance | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| current | 20.1% | 0.85 | −30% | 25% | 0.47 | 53% | 31% | −8% | 3% | 34% | 30% | 9% |
| ret180 / vol^0.5 + slots | **30.6%** | **1.08** | −28% | 29% | 0.56 | 102% | 11% | −7% | −2% | 59% | 31% | 52% |
| same, holding buffer 40 | 24.2% | 0.95 | −26% | 27% | 0.43 | | | | | | | |
| ret180 / vol^1 + slots | 24.0% | 0.98 | −24% | 25% | 0.59 | | | | | | | |
| ret180 / vol^0 (no slots) | 26.0% | 0.86 | −34% | 34% | 0.39 | | | | | | | |

## Findings

1. **Large: tuning holds up out of sample.**
   - Choosing by past book return gave 22.8% a year on the five unseen years, against 12.4% for the current rule and 23.6% for the best setting picked with hindsight.
   - From 2022 on it settled on the same family every year: a 180-day return, half or full volatility adjustment, and breakout slots.
   - It beat the current rule in 4 of the 5 test years.
2. **A longer lookback and a softer volatility adjustment are the changes that matter.**
   - Compared with the current rule, the 180-day lookback finds winners with more of their run left.
   - Partial volatility adjustment keeps high-volatility leaders in the list without letting them dominate.
   - Breakout slots add on top of that, unlike on the risk-adjusted 120-day list.
3. **Chasing winner capture directly costs return.** Choosing by capture held all 50 Large winners and earned 26% of their gains, but the book made only 13.6% a year: the same lottery-ticket trade-off seen in the Small studies.
4. **Mid and Small: tuning does not help.** No momentum setting chosen out of sample made money in 2022–2026. The quality-based Small rule (11.8%) remains far better, even though it holds almost no top-10 winners.

## Suggested use

- **Large candidate:** 180-day return / vol_60d^0.5, trend filter, with 3 big-jump + 2 new-high breakout slots. Paper-track it next to the current rule before switching. Its 2026 result is in-sample, so 2027 will be its first real out-of-sample year.
- **Small:** keep the current rule.
- **Mid:** still skip.

## Caveats

- **Few test years:** five test years, and the 2022 choice rested on only two training years.
- **Multiple testing:** the grid has 60 settings, so the best one in hindsight flatters itself. The walk-forward figure is the honest one.
- **Same base data:** survivorship and execution caveats as in [selection_filters_2020_2026.md](selection_filters_2020_2026.md).
- **No drawdown for the stitched series:** the walk-forward series was scored by yearly returns only.
