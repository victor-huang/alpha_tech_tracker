# Experiment: Do the 2026 uptrend findings hold up across 2020–2026?

As of 2026-11-07. Script: `PYTHONPATH=. python -m alpha_tech_tracker.research.uptrend_formation --year 2020 2021 2022 2023 2024 2025 2026`. Raw outputs: `research/top_performers_output/uptrend_formation/` (per year, plus `summary_*`, `excess_by_year_*`, `excess_by_regime_*`). Method details: [uptrend_formation_2026.md](uptrend_formation_2026.md).

**Answer:** spotting the winners early holds up every year. A simple momentum screen caught nearly every top-10 stock with 64–94% of its gain still ahead. The 2026 claim that large-cap momentum has a standing edge does **not** hold up. It paid in 2020 and 2025 and lost in 2021–2024. The adjustment that does hold up is a **market-regime gate**: with QQQ above its 200-day average, momentum stocks beat same-volatility peers in all three size groups. With QQQ below it, they lagged by 1–2.5% per 60 days.

## 1. Catching the winners: holds every year

| Year | Winners in universe | Caught by early momentum | Median share of gain still ahead | Breakout: share still ahead | Stocks flagged per checkpoint |
| --- | --- | --- | --- | --- | --- |
| 2020 | 28 | 28 | 86% | 68% | 176 |
| 2021 | 27 | 27 | 71% | 0% | 210 |
| 2022 | 27 | 27 | 72% | 0% | 223 |
| 2023 | 26 | 26 | 64% | 10% | 221 |
| 2024 | 25 | 25 | 94% | 44% | 233 |
| 2025 | 29 | 29 | 83% | 31% | 243 |
| 2026 | 30 | 30 | 72% | 24% | 274 |

- "Winners in universe" is below 30 when a top-10 stock failed the start-of-year price/liquidity filter or had no share-count data, which mostly affects renamed or SPAC tickers.
- Breakout signals (new 52-week high on heavy volume) are consistently late.
- The catch: every two weeks the screen also hands you 175–275 other stocks.

## 2. Forward edge beyond volatility: does not hold as a standing rule

60-day forward log return of flagged stocks minus same-volatility peers (same checkpoint, size group and volatility quintile), averaged per year, in %:

| Rule | Size group | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Years > 0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 60-day momentum, top decile | Large | +2.9 | −0.4 | −0.7 | −0.7 | −1.4 | +2.8 | +1.0 | 3 / 7 |
| 120-day momentum, top decile | Large | +3.6 | −2.1 | +1.2 | −0.2 | +0.3 | +3.3 | +0.8 | 5 / 7 |
| Early momentum | Large | +2.9 | −1.0 | −0.8 | −0.7 | −1.4 | +2.7 | +0.7 | 3 / 7 |
| 120-day momentum, top decile | Mid | +2.2 | +0.2 | −0.3 | +0.8 | +2.0 | +1.6 | −2.8 | 5 / 7 |
| Trend template | Mid | +0.3 | +0.0 | −0.9 | +0.5 | +1.9 | +1.1 | −0.7 | 5 / 7 |
| Trend template | Small | +0.6 | +1.6 | +1.0 | +1.2 | +0.4 | +0.4 | +0.2 | **7 / 7** |
| 60-day momentum, top decile | Small | +1.6 | +1.7 | +1.5 | −0.6 | −1.0 | +0.8 | +0.6 | 5 / 7 |

- **Large-cap momentum was a 2020 / 2025 / 2026 effect.** All three years followed a sharp sell-off and recovery. In 2021–2024 it was flat to negative.
- **Small-cap trend template is the only rule positive in all 7 years,** but small: about +0.7% per 60 days.
- Raw hit rates tell the same story. Large-cap 60-day momentum put more stocks in the bottom 5% than the top 5% in 2021 (7.4% vs 9.8%), 2022 and 2024.

## 3. The adjustment: gate on the market regime

The same excess returns pooled over all 170 checkpoints, split by whether QQQ closed above its 200-day average that day:

| Rule | Size group | QQQ above 200-day: excess | % checkpoints positive | QQQ below 200-day: excess | % checkpoints positive |
| --- | --- | --- | --- | --- | --- |
| 120-day momentum, top decile | Large | +1.12% | 59% | +0.39% | 53% |
| 120-day momentum, top decile | Mid | +1.06% | 65% | −0.76% | 41% |
| 60-day momentum, top decile | Large | +0.91% | 56% | −1.56% | 19% |
| 60-day momentum, top decile | Mid | +0.63% | 56% | −1.66% | 31% |
| 60-day momentum, top decile | Small | +0.85% | 57% | −0.12% | 34% |
| Early momentum | Large | +0.80% | 55% | −1.90% | 19% |
| Early momentum | Mid | +0.64% | 57% | −2.53% | 25% |
| Trend template | Small | +1.08% | 59% | −0.56% | 48% |
| Trend template | Mid | +0.97% | 65% | −2.24% | 31% |

- **Above the 200-day:** every momentum rule is positive in every size group, at roughly +0.6% to +1.1% per 60 days (about 3–5% a year before costs).
- **Below the 200-day:** momentum stocks lag their peers. The worst cases are early momentum on Mid (−2.5%) and Large (−1.9%).
- **Caveat:** 23 of the 32 below-average checkpoints are in 2022, so the "below" result rests mostly on one bear market. Also, 2021 and 2023–2024 were mostly above the average and large-cap momentum still did not pay, so the gate removes the worst periods but does not create an edge on its own.

## What changes from the 2026-only conclusions

| 2026-only conclusion | After 7 years |
| --- | --- |
| Large-cap 60-day momentum has a real 1.35x edge | Regime-dependent. Positive only in 2020, 2025 and 2026; only worth using while QQQ is above its 200-day average |
| Mid and Small momentum is just volatility | Mostly true for 60-day momentum. 120-day momentum (Mid) and the trend template (Small) show a small, steadier edge |
| Breakouts and volume surges don't help | Holds every year |
| Winners are caught early with ~70% of the gain ahead | Holds every year (64–94%) |

## Caveats

- **Small edges:** about 1% per 60 days is easily eaten by trading costs and slippage on 175–275 names. Any rule needs a narrower selection and a portfolio backtest.
- **Overlapping windows:** 60-day windows from checkpoints 10 days apart overlap, so the 170 checkpoints are far fewer independent observations.
- **Survivorship:** only stocks listed today are included. This flatters older years (2020–2021) the most, because later delistings are missing.
- **Price-only features:** no earnings, news or sector data.

## Next steps

1. Backtest a concrete biweekly rule: when QQQ is above its 200-day average, hold the top N by 120-day momentum (Large/Mid) or trend template (Small), equal-weighted, and go to cash otherwise. Compare with SPY/IWM after costs.
2. Narrow the selection (e.g. top 10–20 names per size group by momentum within the screen) to see whether the edge concentrates at the extreme.

**Update:** both steps are done in [selection_filters_2020_2026.md](selection_filters_2020_2026.md).
