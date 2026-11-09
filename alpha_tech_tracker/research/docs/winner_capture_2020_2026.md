# Do the top-15 lists catch the yearly winners, and do you need all 15? (2020–2026)

Script: `alpha_tech_tracker/research/winner_capture.py`. Outputs: `research/top_performers_output/uptrend_formation/winner_capture/`.

## Lists tested

These are the recommended lists from [selection_filters_2020_2026.md](selection_filters_2020_2026.md):
- **Large:** trend + risk-adjusted 120-day momentum + clean.
- **Small:** trend + composite + no dilution + prefer gross profit.
- **Mid:** trend + composite, for reference only. It is not recommended.

Setup:
- **Book:** top 15, rebalanced every 10 trading days, no market gate, 10 bps costs.
- **Winners:** each year's top-10 by tier (`docs/top10_by_year_2020_2026.csv`), limited to stocks in that year's universe.

## 1. Winner capture (top 15, no buffer)

| Tier | Winners | Held at some point that year | Median days into the year when first held | Median share of the year's gain still ahead then | Median share of the year's gain the book earned | Median checkpoints held |
|---|---|---|---|---|---|---|
| Large | 70 | **65 (93%)** | 144 | 44% | 13% | 5 |
| Mid | 67 | 11 (16%) | 192 | 49% | −4% | 1 |
| Small | 53 | 16 (30%) | 213 | 31% | 4% | 2 |

Winners held per year:

| Tier | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| Large | 10 | 9 | 10 | 8 | 9 | 10 | 9 |
| Small | 4 | 2 | 4 | 1 | 1 | 2 | 2 |

Distinct names held per year (15 slots):

| Tier | No buffer | Buffer 40 |
|---|---|---|
| Large | ~133 | ~104 |
| Small | ~156 | ~119 |

**What this means:**
- **Large:** the list finds almost every winner, but late (around late May) and briefly (about 5 checkpoints, 2–3 months). It earns a median 13% of a winner's yearly gain. The best captures held all year: SNDK 2026, SE 2020, TSLA 2020, WDC 2025.
- **Small:** the list holds only about 2 winners a year, and briefly. Its return comes from the whole basket of good small caps, not from catching the top 10.
- **Churn:** the lists rotate through 100–160 names a year. Each holding lasts weeks, not the whole year.

## 2. Book size (the same rule, top N)

| Tier | Top 5 | Top 8 | Top 10 | Top 15 | All tier stocks, equal weight |
|---|---|---|---|---|---|
| Large CAGR / Sharpe / Max DD | 14.8% / 0.58 / −45% | 18.4% / 0.74 / −30% | 17.1% / 0.72 / −29% | **20.1% / 0.85 / −30%** | 10.9% |
| Small CAGR / Sharpe / Max DD | 14.3% / 0.68 / −41% | 15.0% / 0.71 / −46% | 20.3% / 0.89 / −44% | 18.6% / 0.83 / −43% | 10.8% |

The highest-ranked names are not better. The top 5 does worse than the top 15 in Large, so the edge sits in the whole group, not in the top ranks.

## 3. Buying only some of the list

Each draw picks k names at random from the current top 15, keeps each one while it stays in the top 15, and fills empty slots at random. There are 200 draws per size. The figures are compound annual growth rates.

| Tier | Names held | 5th pct | 25th | Median | 75th | 95th pct | Beats its tier universe | Beats holding all 15 |
|---|---|---|---|---|---|---|---|---|
| Large | 3 | 3.8% | 10.4% | 16.0% | 22.2% | 31.2% | 73% | 32% |
| Large | 5 | 8.3% | 13.7% | 17.1% | 20.6% | 27.4% | 89% | 31% |
| Large | 8 | 11.6% | 16.1% | 18.8% | 21.2% | 24.4% | 97% | 34% |
| Large | all 15 | | | 20.1% | | | | |
| Small | 3 | −0.5% | 6.4% | 11.2% | 17.0% | 23.5% | 52% | 18% |
| Small | 5 | 4.7% | 11.2% | 14.8% | 18.4% | 23.8% | 79% | 23% |
| Small | 8 | 8.7% | 13.4% | 16.4% | 19.2% | 22.7% | 90% | 30% |
| Small | all 15 | | | 18.6% | | | | |

- **The median random subset trails the full list.** Large with 5 names returns 17.1% vs 20.1%, and Small 14.8% vs 18.6%. Drawdowns get deeper too: the median Large 3-name book drops −38%, vs −30% for all 15.
- **Why it trails:** fewer names means fewer chances to hold the occasional big winner, and those few big winners drive the list's return.
- **Spread:** with 3 names, Large outcomes run from 4% to 31% a year (5th to 95th percentile), and Small from about 0% to 24%.
- **Eight names keeps most of the edge:** Large beats its universe 97% of the time and Small 90% of the time, with a median about 1–2 points below the full list.

## Practical reading

- **The lists won't tell you which stock becomes a top-10 winner.** Large owns most winners for a while; Small mostly misses them and wins on breadth.
- **Run the book, not the picks:**
  - Hold all 15, or at least 8, in equal weight.
  - Replace names that drop out every two weeks.
  - A 40-name holding buffer cuts churn by about a quarter, from ~133 to ~104 names a year for Large. For Small it costs almost nothing (18.6% → 18.1%); for Large it costs about 5 points a year (20.1% → 15.1%).
- **Discretionary picking within the list is untested.** Random picking from it is a fair stand-in for picking with no real skill.

## Caveats

- **Winner returns** come from the yearly top-10 file. A few captured shares exceed 100%, because the book's holding periods cross the year boundary by a few days.
- **Same data, same survivorship and selection caveats** as the selection study.
- **Random draws** measure luck, not skill. Hold-while-in-top-15 is one of several possible part-list policies.
