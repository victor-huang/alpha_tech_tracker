# Mid caps: why momentum fails, and the reclaim + growth list (2020–2026)

The question: the recommended rules skip the Mid tier ($2–10B at the start of each year, about 900 names). Why do the Large and Small rules not work there, and is there a Mid rule worth trading?

Script: `alpha_tech_tracker/research/mid_reclaim.py`. Outputs: `research/top_performers_output/uptrend_formation/mid_reclaim/2020_…_2026/`:
- `summary.csv`, `by_year.csv`: the recommended setting with both rankings
- `walk_forward_grid.csv`, `walk_forward.csv`, `walk_forward_summary.csv`: 54 settings, each test year's setting chosen from earlier years only

The diagnostics and the rejected ideas below came from one-off scripts.

## Why momentum fails on Mid

The Mid universe is not a bad pond: an equal weight of every name made 9.8% a year (Large 11.5%, Small 11.3%). Its yearly top-10 winners also gained more than Large's in every year but 2026 (average 101–467% a year). Momentum ranking simply adds nothing there.

| Rule on the Mid tier (15 names, the tier's stop) | CAGR | Worst drop | 2022 | 2025 |
|---|---|---|---|---|
| Universe equal weight | 9.9% | −39% | −22% | 13% |
| Large rule (180-day / vol^0.5 + breakout slots, 25% stop) | 3.7% | −60% | −34% | −14% |
| 180-day score only | 8.4% | −50% | −31% | −1% |
| 250-day / vol^0.5 (best of the 60 ranking settings) | 17.5% | −43% | −25% | 33% |
| Small rule (quality composite, 15% stop) | 3.6% | −28% | −24% | −1% |

Across the 60 walk_forward_tuning settings the median Mid book made 4.5% a year, and choosing the setting each year from earlier years made −2.2% a year on 2022–2026.

1. **Mid momentum is thematic and reverses hard.** The 2022 book was 29% oil and gas plus semis and brokers; the 2025 picks included SOUN, RGTI, WULF and WGS. Every momentum rule had a worst drop of −43% to −62%.
2. **Mid winners don't look like momentum stocks early.** Most of each year's top 10 were rebounds and turnarounds ranked 100–400 when they first passed the trend filter (2021: CAR, DVN, AA, OVV, M; 2024: the Argentine banks BBAR, GGAL, BMA at 200–400 and RKLB at 404; 2026: RNG at 423).
3. **The steady Mid winners become next year's Large winners** (SMCI, APP, VRT, CLS, COIN, MSTR), which the Large list already holds.
4. **Already up 30%+ is not a signal on Mid.** About 40 Mid names cross a 30% six-month gain every two weeks. Over the next six months they did the same as an average Mid name (2026 +8.2% vs +8.4%, 2022 −5.7% vs −2.0%), 1–7% of them doubled and 8–31% fell 20% or more. Buying them and holding until a 20/50/200-day break made −1% to 14% a year.

## The reclaim + growth list

A 200-day reclaim alone (close back above the 200-day within the last 20–60 trading days, above the 20- and 50-day) fires on 100–170 Mid names per checkpoint and 600–800 different names a year; those names did no better than the whole tier. No ranking of that set worked: volume surge 7–10%, gap-up 2–6%, 20- or 60-day strength −1% to −4% (worst drop −55% to −71%), tight base 3–4%, industry cluster −3%.

Narrowing worked where ranking didn't. Of 19 filters tested on the reclaim set, only **sales growth ≥ 25%** helped consistently (19 names per checkpoint, 17.4% a year, better than the reclaim set in 6 of 7 years). Adding a **flat or rising 200-day average** turned it into a different pattern: a fast-growing company that dipped through a still-rising 200-day and recovered, not a turnaround.

**Rule:**
- Mid tier at the checkpoint
- Closed back above the 200-day within the last 40 trading days; above the 20- and 50-day now
- 200-day average flat or rising over the last 20 trading days
- Latest reported sales up 25% or more year over year (point in time: only quarters filed before the checkpoint)

**Book:** up to 15 names, checked every 2 weeks, the account split equally across whatever is held, 15% trailing stop held day by day. A name is sold when it leaves the list (reclaim older than 40 days, a broken average, a falling 200-day, slower sales) or hits its stop. The list averages about 12 names, so 49 of 176 checkpoints had more names than slots, and 5 had none (the book sits in cash).

**Ranking for the open slots:** highest 10-day / prior 60-day dollar volume first (`volume_surge`, default), or names the book has never held first (`fresh_first`).

### Results

| Book | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* | CAGR | Worst drop |
|---|---|---|---|---|---|---|---|---|---|
| Mid reclaim + growth, volume surge | 57% | 41% | −17% | 30% | 61% | 22% | 15% | 27.8% | −31% |
| Mid reclaim + growth, never held first | 59% | 38% | −13% | 32% | 63% | 21% | 24% | 30.3% | −31% |
| Mid universe equal weight | 20% | 18% | −22% | 21% | 12% | 13% | 12% | 9.8% | −39% |
| QQQ | 44% | 31% | −34% | 53% | 28% | 21% | 10% | 18.8% | −34% |

\* Through Nov 10. 0.1% cost per trade; worst drop measured at checkpoints. Turnover is high (about 250 trades a year): at 0.3% per trade the default book makes 21.8%.

Best names held: IONQ, HALO, WHD, SANM, DUOL, RSI, BL, BB, HRMY, HNGE. In 2026 the list caught 3 of the tier's top 10: BB (+73% while listed, from Apr 29), HNGE (+66%, from May 13) and SEZL (listed once, late, −6%). The other seven were already in uptrends from late 2025 (TXG, PBF, INSW, FRO, SYRE), had slow sales (RNG +6%, ANDG +16%) or had no 200-day history. The list makes its money from many moderate winners held a few weeks each, not from the year's biggest winners.

### Walk-forward

54 settings: reclaim window 20/40/60 days × sales growth 15/25/40% × 200-day slope floor −1/0/+1% × the two rankings. Each test year uses the setting with the best compounded return over the earlier years.

| Test year | Chosen setting | Test return | Rank of 54 | Median setting | Best setting |
|---|---|---|---|---|---|
| 2022 | 60 days, 40% growth, +1% slope, never held first | −5% | 6 | −16% | 9% |
| 2023 | same | 6% | 47 | 25% | 94% |
| 2024 | 40 days, 25%, 0%, never held first | 63% | 7 | 31% | 76% |
| 2025 | same | 21% | 13 | 13% | 36% |
| 2026* | same | 24% | 10 | 12% | 40% |

| 2022–2026 | CAGR |
|---|---|
| Walk-forward choice | 19.8% |
| Fixed recommended setting (volume surge) | 19.5% |
| Best setting in hindsight | 22.8% |
| Median setting | 11.6% |

The rule holds up out of sample: the walk-forward lands next to the fixed setting and about 8 points above the median setting. From 2024 on it chose the recommended filter with the never-held-first ranking every year.

## What did not help

| Idea | Best result | vs current 28.3% | Why |
|---|---|---|---|
| Hold while fundamentals and chart hold (sell below the 20-, 50- or 200-day or on slower sales, no 40-day limit) | 20.7% (20-day); 12–15% (50/200-day) | −8 to −16 pts | The gain comes in the first few weeks after the reclaim; names still above their 20-day after 40 days do worse from then on |
| Let winners run instead of re-splitting | 23.0% | −5 pts | One or two names grow large: 2024 +128%, 2025 −2% to −15% |
| Fixed holding periods (28–182 days) | 9–14% | | |
| Watch sold names, re-admit when they regain the exit price or the earlier high | 6.7–9.7% | −19 to −22 pts | Re-entries averaged ~0% per trade, 36% winners; they crowd out fresh list names |
| Same, ranking re-entries by gain since first entry within 20–150% | 16.0% | −12 pts | The band helps (vs 8.2% for 0–200%), but re-entry still costs |
| Boost names held before (gain since first entry 20–150%) when ranking the list | 28.7% | +0.4 pts | Noise: ranking only matters at the 49 checkpoints with more than 15 names |
| Rank by number of appearances on the list | 27.0% | −1.3 pts | Long-listed names are stale reclaims |
| Fundamental sell rule (sales growth below 25%, 10% or none) | within 1 pt | | Sales are reported quarterly; they rarely change during a 3–4 week hold |

## Findings

1. **Mid momentum does not work.** Mid's big winners are rebounds and themes that a 180-day ranking finds late or never, and Mid's momentum names reverse harder than Large's.
2. **Narrowing beats ranking.** A fresh 200-day reclaim is a broad gate; sales growth ≥ 25% and a flat-or-rising 200-day are what make the list.
3. **It is a swing trade.** The median hold is about 19 days. Every way of holding longer, re-admitting or favouring known names gave part of the edge back; a fresh first reclaim is where the return is.
4. **It survives a walk-forward** (19.8% a year on 2022–2026, picked from earlier years only).

## Decision

- **Paper-tracked from 2026-11-11** as `mid_reclaim_growth` in `paper_lists`, ranked `fresh_first` (never-held names first; the walk-forward's choice from 2024 on), 15% trailing stop watched by `exit_watch`. The book is replayed from the start of the previous year so the never-held order knows every earlier purchase; `rank` in the list is the volume-surge order. The backtest default in `mid_reclaim.py` stays `volume_surge` for comparison.
- **Not adopted:** Mid momentum rankings, buying names already up 30%+, holding until a chart or fundamental break, re-admitting sold names, boosts for names held before.

## Caveats

- **Found on the same seven years** after testing about 30 filters and rankings; the walk-forward covers only five test years and one bear market.
- **Uneven over time:** about 7.5% a year in 2020–2022 for the equal-weight list, 36% in 2023–2026.
- **Costs and liquidity:** about 250 trades a year; Mid names at $2–10B are liquid, but the cost assumption (0.1%) matters (21.8% at 0.3%).
- **Thin list:** 3–4 names at some checkpoints, none at 5; the account is then concentrated or in cash.
- **Survivorship:** the universe holds only stocks listed today.
