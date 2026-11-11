# Short hedge: shorting the weakest Large names in a downtrend (2020–2026)

The question: the Large list lost 9% in 2022 and 2% in 2023. Why, and can a market-timing rule, a short hedge, a different selection rule or a Large/Small blend help without giving up the good years?

Script: `alpha_tech_tracker/research/short_hedge.py`. Outputs: `research/top_performers_output/uptrend_formation/short_hedge/2020_…_2026/`:
- `summary.csv`, `by_year.csv`
- `basket.csv`: the short basket at every checkpoint, its period return and whether the hedge was on

## Why 2022 and 2023 lost (one-off diagnostics)

**2022 (−9%, QQQ −34%):** two whipsaws, not a slide. The Jan 3 period lost 8% as the 2021 growth holdings broke (DAVA −23%, ARGX −20%, SYNA −19%) and the Jun 10 period lost 15% when oil crashed (DVN, HAL, VLO −20% each); the other 24 periods made about +15%. The number of Large names passing the trend filter fell from 364 in January to about 50 from May to October, almost all energy and staples, so the 15 slots became a sector bet. The trailing stops cost about 2 points (−7% without them).

**2023 (−2%, QQQ +53%):** a narrow mega-cap rebound from a bear low. The trend filter (price > 50-day > 200-day, 200-day rising) admitted the leaders months late and the 180-day score, still containing the 2022 lows, ranked them far down:

| Stock | First eligible | Gain before | Gain after | Rank when eligible |
|---|---|---|---|---|
| NVDA | Mar 2 | +63% | +112% | 87 |
| META | Mar 30 | +67% | +70% | 136 |
| AMD | Apr 14 | +43% | +61% | 229 |
| AVGO | Feb 15 | +10% | +88% | 212 |
| AMZN | Jul 12 | +52% | +16% | 302 |

The book held the fading 2022 themes instead (solar, energy, steel, defensives). An equal weight of every eligible Large name made about +9% that year; the best of the 60 ranking settings made 7% and the median 0%. "Recovery mode" rules that loosen the filter or shorten the lookback when QQQ has just reclaimed its 200-day did not help (2023 between −2% and −6%).

**2021 (+11%, QQQ +31%) and 2023: why the list lags QQQ in mega-cap years.** QQQ's gains in both years came from the mega-caps, which the ranking almost never holds: the 180-day / vol^0.5 score prefers the fastest, most volatile movers over a steady 40% year. In 2021 GOOGL (+61%), MSFT (+41%), AVGO (+45%) and AAPL (+34%) were eligible at 17–23 of 26 checkpoints and never held, ranking around 100–220. The book held MRNA, PLUG, LCID, NIO and AGNT instead and lost 14% in the Feb 17 period and 9% in the Nov 16 period while QQQ fell 7% and 3%. Splitting the 2021 book: breakout-slot picks +4%, score picks +18%, an equal weight of every eligible Large name +21%. In 2023 the book did hold NVDA, META and ADBE from mid-year but had already lost on 2022 themes; an equal weight of QQQ's own members made about 17% that year, so an equal-weight 15-name book cannot track a cap-weighted index in a narrow year.

Levers tested against this (one-off scripts): 30 or 50 names (16.8% / 14.5% a year; 2021 4% / 13%), a full volatility adjustment (24.2%; 2021 16%), and a mega-cap-only universe (19–27%; 2021 −6% to −15%). Each helps one of the two years and costs far more in 2020, 2024 and 2025.

**Mega-cap breakout sleeve.** A sleeve that buys the mega-caps on a breakout (fresh 52-week high after a 60-day base, or a high-volume gap-up, above the 50- and 200-day averages) and exits on a checkpoint close below the 50-day or a 25% trailing stop:

| Universe | Exit | CAGR | Worst drop | Trades | Win rate | 2021 | 2022 | 2023 | 2026* |
|---|---|---|---|---|---|---|---|---|---|
| QQQ | | 18.9% | −34% | | | 31% | −34% | 53% | 11% |
| AAPL NVDA TSLA GOOGL META MSFT AMZN | below 50-day | 16.2% | −39% | 74 | 49% | 37% | −12% | 58% | −21% |
| same | 25% trailing stop | 26.0% | −40% | 23 | 65% | 50% | −40% | 80% | −1% |
| those 7 + 13 big caps | 25% trailing stop | 23.9% | −25% | 50 | 74% | 38% | −20% | 38% | 16% |
| top 20 by dollar volume | 25% trailing stop | 23.4% | −34% | 87 | 55% | 25% | −26% | 29% | 23% |

Large 80% / Mag-7 sleeve 20% (50-day exit): 29.2% a year, 2021 17%, 2023 8%, 2020 76%, 2026 36%. The sleeve lifts the two mega-cap years and pays in 2020 and 2026; a plain 80/20 with QQQ gives almost the same yearly profile with no trading. The base-before-breakout entry has a slightly better win rate and average trade than any breakout, but the trailing-stop versions are close to buy-and-hold of the big caps (15 of 20 names held on average). Not adopted.

## Setup

- **Long book:** the recommended Large 15 (25% trailing stop, 2 weeks), alone or 70/30 with the recommended Small 15 (15% stop), re-split every checkpoint.
- **Signal:** QQQ's close at the checkpoint below both its 50- and 200-day averages. On at 25 of 176 checkpoints: spring 2020, most of 2022, and January 2023.
- **Short basket:** the 15 lowest 180-day return / vol^0.5 scores among the 300 most traded Large names, equal weight, rebuilt each checkpoint, no stop. Shorted at 25% or 50% of the book while the signal is on.
- **Costs:** 10 bps per unit traded on the short side and a 1% borrow rate while on.

## Results

| Book | CAGR | Worst drop | Sharpe | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|---|---|
| Large | 31.7% | −27% | 1.12 | 103% | 11% | −9% | −2% | 60% | 32% | 55% |
| Large + short 25% | 32.4% | −25% | 1.15 | 91% | 11% | +5% | −5% | 60% | 32% | 54% |
| **Large + short 50%** | **32.9%** | **−24%** | 1.15 | 79% | 11% | **+19%** | −9% | 60% | 32% | 53% |
| Large 70 / Small 30 | 29.2% | −24% | 1.21 | 94% | 18% | −8% | 4% | 43% | 25% | 48% |
| Large 70 / Small 30 + short 25% | 29.9% | −24% | 1.24 | 82% | 18% | +5% | 1% | 43% | 25% | 47% |
| Large 70 / Small 30 + short 50% | 30.4% | −26% | 1.23 | 71% | 18% | +20% | −3% | 43% | 25% | 46% |

\* Through Nov 6. Worst drop is measured at rebalance dates.

The basket's return while the hedge was on: −49% over 2022, but +27% in spring 2020 and +13% in January 2023, when the beaten-down names squeezed higher.

### What else was tried (one-off scripts, Large 15 alone)

| Overlay while the signal is on | CAGR | Worst drop | 2020 | 2022 | 2023 |
|---|---|---|---|---|---|
| cash (QQQ < 200-day) | 24.6% | −29% | 77% | −10% | −8% |
| half cash (QQQ < 50- and 200-day) | 29.2% | −24% | 90% | −6% | −4% |
| cash (QQQ 50-day < 200-day) | 28.7% | −27% | 101% | −7% | 0% |
| short QQQ 50% | 29.2% | −26% | 81% | +1% | −5% |
| short QQQ 100% | 26.3% | −31% | 60% | +10% | −7% |

Large/Small blends (both books run day by day with their stops, re-split every checkpoint; the two books' 2-week returns correlate 0.5):

| Book | CAGR | Worst drop | Sharpe | 2022 | 2023 |
|---|---|---|---|---|---|
| Large 15 | 31.7% | −27% | 1.12 | −9% | −2% |
| Large 70 / Small 30 | 29.2% | −24% | 1.21 | −8% | +4% |
| Large 50 / Small 50 | 27.2% | −24% | 1.24 | −8% | +8% |
| Large loose filter 70 / Small 30 | 32.0% | −24% | 1.27 | −11% | +9% |
| Large loose filter + short 25% weakest, 70 / Small 30 | 32.7% | −24% | 1.31 | −2% | +7% |

Selection changes for 2023: only price above the 200-day as the trend filter gave 35.7% a year (2023 +5%, 2025 +47%) but a −31% worst drop and 2022 −13%; a mega-cap-only universe fixed 2023 (+7–9%) and lost badly elsewhere; ranking by closeness to the 52-week high made 8.5%.

## Findings

1. **Going to cash never helped.** The signals fire after most of the damage and miss the sharp rebounds of spring 2020 and early 2023.
2. **Shorting QQQ fixes 2022 and gives it back in 2020.** QQQ snapped back while the signal was still on.
3. **Shorting the weakest names is the one overlay that improved both return and drawdown.** The weakest 15 fell twice as much as QQQ in 2022. It costs 2020 (−24 points at 50%) and January 2023 (−7 points).
4. **The Small blend fixes 2023, the short leg fixes 2022.** Blending costs 2.5–4.5 points of CAGR for a better Sharpe, and barely improves the worst drop (−27% to −24%) because both lists fell together in 2022. Together (70/30 + short 25%) no year is below +1%, at about 2 points a year less than Large alone.
5. **2023 is not fixable inside the trend rule.** Every ranking setting made under 7% that year; the market was a narrow mega-cap rebound from a bear low and the trend filter admitted the leaders months late, ranked 90–230.

## Decision

- **Adopted for paper tracking (2026-11-10):** Large + short 50% of the weakest 15 while QQQ is below both averages. `paper_lists` writes the basket as `large_short_hedge` with status `short` or `off`; `exit_watch` does not watch it (no stop).
- **Not adopted:** the mega-cap breakout sleeve and wider lists (see above), the Large/Small blend (the user prefers the short hedge), cash or QQQ-short overlays, the loose trend filter (pending a walk-forward check), the mega-cap universe.

## Caveats

- **One bear market.** The hedge was on at 25 checkpoints, 20 of them in 2020 and 2022. Its edge is a 2022 result.
- **Squeezes.** The weakest names rose 13–27% in two of the three episodes; at 50% that is a 7–14 point hit to the book.
- **Practicality:** borrow availability and short-sale costs for the weakest names are assumed at 1% a year; no intraperiod stop on the short side.
- **Chosen after the fact** on the same seven years as the rest of the rules, with survivorship in the universe (only stocks listed today; delisted losers are missing from the short basket, which understates its 2022 gain and overstates squeezes).
