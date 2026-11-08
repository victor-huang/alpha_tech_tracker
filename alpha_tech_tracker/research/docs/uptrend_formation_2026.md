# Experiment: Can a biweekly scan spot 2026's top performers early?

As of 2026-11-07. Script: `alpha_tech_tracker/research/uptrend_formation.py --year 2026`. Raw outputs: `research/top_performers_output/uptrend_formation/2026/`.

> **Update:** the 7-year follow-up ([uptrend_formation_2020_2026.md](uptrend_formation_2020_2026.md)) shows the large-cap momentum edge is regime-dependent. It only held while QQQ was above its 200-day average.

**Answer:** trend screens catch every 2026 winner while ~70% of its gain is still ahead, but they also flag ~275–390 other stocks every two weeks. For Mid and Small caps the screens' edge is almost entirely "these stocks are volatile": flagged stocks land in the bottom 5% about as often as in the top 5%. **Large caps are the exception**: 60-day momentum keeps a real 1.35x edge after controlling for volatility.

## Setup

- **Universe:** 2,922 stocks that met the price (≥ $2) and liquidity (≥ $2M median daily $ volume) filters on 2025-12-31: 878 Large, 996 Mid, 1,048 Small. Size group = market value on 2025-12-31.
- **Winners:** the 2026 YTD top 10 per size group (30 stocks) from `top10_by_year_2020_2026.csv`, after removing AZN (data artifact, see below).
- **Checkpoints:** every 10 trading days from 2026-01-02 to 2026-11-03 (22 in total). Every feature uses only data up to that day's close.
- **Screens:**
  - *trend template*: close > 50-day MA > 200-day MA, 200-day MA rising, within 15% of the 52-week high, ≥ 30% above the 52-week low, top 20% for 120-day return.
  - *early momentum*: close > 50-day MA, 50-day MA rising, top 10% within its size group for 60-day return.
  - *breakout*: new 52-week high in the last 10 days on ≥ 1.5x normal share volume.
- **Forward test:** at every checkpoint with 60 trading days of future data (18 checkpoints), a stock "wins" if its next-60-day return is in the top 5% of its size group, and "loses" if it is in the bottom 5%.

## 1. When would each screen have caught the winners?

| Screen | Winners caught | Median YTD gain when first flagged | Median share of the year's gain still ahead |
| --- | --- | --- | --- |
| Trend template | 30 / 30 | +34% | 73% (Large 78%, Mid 68%, Small 68%) |
| Early momentum | 30 / 30 | +42% | 71% (Large 78%, Mid 65%, Small 70%) |
| Breakout | 20 / 30 | +71% | 24% |

- Early momentum first flagged 10 winners in January, 4 in February and 9 in March. All 30 were flagged by June.
- On 2026-01-02, 27% of the eventual winners already passed early momentum, versus 10% of all stocks.
- Breakouts are late: by the time a winner makes a new high on heavy volume, most of the move is done.

## 2. What did winners look like versus other stocks?

Median within-size-group percentile of the winners (0.50 = typical stock):

| Feature | Jan 2 | Jan 16 | Mar 3 | Apr–Oct range |
| --- | --- | --- | --- | --- |
| 20-day return | 0.44 | 0.83 | 0.88 | 0.54–0.94 |
| 60-day return | 0.57 | 0.80 | 0.86 | 0.88–0.97 |
| 120-day return | 0.55 | 0.73 | 0.85 | 0.92–0.99 |
| Biggest 1-day gain, last 20 days | 0.70 | 0.91 | 0.75 | 0.77–0.89 |
| 50-day MA slope | 0.55 | 0.58 | 0.80 | 0.86–0.96 |
| Distance from 52-week high | 0.34 | 0.54 | 0.61 | 0.59–0.88 |
| Volume surge (10d vs 60d) | 0.58 | 0.68 | 0.49 | 0.40–0.64 |
| Volatility contraction | 0.42 | 0.23 | 0.70 | 0.27–0.69 |

- **Earliest sign:** large single-day up moves and short-term momentum, visible by the second checkpoint (Jan 16).
- **No signal:** volume surge and volatility contraction ("tight base") hover near 0.5 all year.
- **Not especially near highs:** winners sit at only the 0.6–0.9 percentile for distance from the 52-week high, well below their momentum ranks, because they pull back hard and often.
- **Two kinds of winner:** for 6 of 30 (MRNA, RVMD, BE, SEZL, KOD, ELVN) a single day made up ≥ 35% of the year's gain (trial results and other news). The other 24 rose in steadier trends.

## 3. Does any of this predict, looking forward?

Pooled over 18 checkpoints. Base rate: 5% win, 5% lose. *Vol-matched lift* compares the hit rate with what stocks of the same volatility achieved anyway (1.0 = no edge beyond volatility).

| Rule | Size group | Flagged per checkpoint | Top-5% rate | Bottom-5% rate | Lift | Vol-matched lift |
| --- | --- | --- | --- | --- | --- | --- |
| 60-day return, top decile | Large | 88 | 12.6% | 9.9% | 2.52 | **1.35** |
| 20-day return, top decile | Large | 88 | 11.6% | 10.3% | 2.32 | **1.37** |
| Early momentum | Large | 83 | 12.2% | 10.2% | 2.43 | **1.34** |
| 20-day return, top decile | All | 293 | 9.0% | 9.6% | 1.80 | 1.16 |
| Biggest 1-day gain, top decile | All | 293 | 10.9% | 12.9% | 2.18 | 1.07 |
| Early momentum | All | 274 | 8.5% | 9.9% | 1.68 | 1.05 |
| Trend template | All | 387 | 6.0% | 6.6% | 1.19 | 0.96 |
| Breakout | All | 64 | 5.1% | 7.1% | 1.01 | 0.85 |
| Volume surge, top decile | All | 293 | 5.2% | 6.3% | 1.04 | 0.88 |
| Near 52-week high, top decile | All | 297 | 3.2% | 3.5% | 0.63 | 0.95 |

- **Mid and Small:** every momentum rule raises the chance of a top-5% result and of a bottom-5% result by about the same amount. It identifies volatile stocks, not winners.
- **Large:** momentum keeps a modest edge after the volatility control (about 12% top-5% vs 10% bottom-5%).
- **Breakouts and nearness to highs do not help** on a 60-day forward basis.

## Data correction found during the experiment

AZN's "+106%" is an artifact. On 2026-02-02 its price doubled (91 → 185) while share volume fell to 0.3x normal, which is the ADR-to-ordinary-share switch, not trading. Real 2026 return is about +2%. It is removed from the 2026 Large list (BE moves to #9, SN is #10), and `top_performers.py` now flags this pattern as `ratio_change` (a move of ≥ 40% in one day without a volume spike).

## Caveats

- **One year:** 2026's themes (memory chips, refiners, biotech) may not repeat. Run the same experiment for 2020–2025 before trusting any rule.
- **Overlapping windows:** 60-day forward windows from checkpoints 10 days apart overlap, so the 18 checkpoints are not independent samples.
- **Survivorship:** only stocks listed today are included; 2026 delistings are missing.
- **Price-only features:** no earnings, news or sector data.

## Next steps

1. Run `--year 2020` … `--year 2025` to see whether the Large-cap momentum edge holds in other years.
2. If it does, test a concrete biweekly rule for Large caps, such as buying the top 10 by 60-day return that pass early momentum, against SPY.
