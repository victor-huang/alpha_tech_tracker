# Top 3, 5 and 10, year by year (2017–2026)

The question: holding only the top 3, 5 or 10 names of each recommended list, what does each year look like month by month, which trades made it, and which list size suits each tier?

Outputs: `research/top_performers_output/uptrend_formation/top_n_by_year/`:
- `monthly_pnl.csv` (2017–2026, `top` = 3, 5, 10): monthly return of every book and QQQ, per list size and year
- `yearly_summary.csv`: year return, worst drop, trades, win rate, average trade
- `top<N>_<year>_trades.pdf`: a summary page (equity curves, monthly table, trade stats), then every trade in checkpoint order, 6 per page: daily candles with the 8/20/50/200-day averages, the holding period shaded (green gain, red loss) and the trade's return and exit reason
- `hedged_monthly_pnl.csv`, `hedged_yearly_summary.csv`: the same books with the short hedge, plain (`Large5`) and hedged (`Large5+h`)
- `large_top3_monthly_pnl.csv`, `large_top3_yearly_summary.csv`, `large_top3_<year>_trades.pdf`: the `large_top3` book (top 3 Large by the 180-day score alone), plain and hedged
- `scripts/top_n_books.py <out.pkl> <N> <year>`, `scripts/top_n_charts.py <in.pkl> <ohlc cache.pkl> <out.pdf>` and `scripts/hedge_overlay.py <dir> <year> [list sizes]`: one-off scripts (not in the test suite)

## Setup

- **Rules:** the recommended rules. Large is 180-day / vol^0.5 with breakout slots in the first 5 places, 25% trailing stop. Small is composite + no dilution + prefer gross profit, 15% trailing stop. Mid is the reclaim + growth list, never-held names first, 15% trailing stop.
- **Book:** top N, equal weight, checked every 10 trading days. A holding is kept while it ranks within N (Mid: while it stays on the list). 0.1% cost per trade; the trailing stop is held day by day, and a stopped name goes to cash until the next checkpoint.
- **Years:** 2017–2026. Alpaca's daily bars start on 2016-01-04 (`DailyBarCache` skips earlier months), so 2017 is the first year with the 180–252 days of history the rules need; 2016 cannot be run.
- **Each year is a separate run** that starts in cash in January and ends Dec 31 (2026: Nov 12); Mid's never-held memory resets each year. The compounded figures chain these runs, so they differ a little from one continuous book.

## Results

| Book | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* | 2018–2026 | 2017–2026 | Per year (2017–2026) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Large top 5 | 8% | −9% | 33% | 110% | −2% | −17% | −3% | 25% | −3% | 35% | 3.2× | 3.5× | 13.5% |
| **Large top 10** | 9% | −5% | 32% | 140% | 17% | −6% | 1% | 79% | 26% | 41% | **10.5×** | **11.4×** | **28.0%** |
| Mid top 5 | 50% | −18% | 46% | 39% | 39% | −13% | 16% | 47% | 18% | 12% | 4.6× | 6.8× | 21.5% |
| **Mid top 10** | 50% | −18% | 52% | 55% | 55% | −15% | 31% | 59% | 17% | 13% | **7.0×** | **10.4×** | **26.8%** |
| **Small top 5** | 19% | 1% | 16% | 86% | 35% | −23% | 29% | 10% | 21% | 47% | **5.7×** | **6.8×** | **21.5%** |
| Small top 10 | 11% | −8% | 10% | 64% | 38% | −10% | 35% | 2% | 20% | 31% | 4.5× | 5.0× | 17.7% |
| QQQ | 32% | −2% | 38% | 46% | 29% | −33% | 56% | 28% | 21% | 13% | 4.7× | 6.1× | 20.2% |

\* Through Nov 12.

Worst drop within each year:

| Book | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|---|---|
| Large top 5 | −6% | −25% | −9% | −28% | −19% | −26% | −23% | −11% | −37% | −12% |
| Large top 10 | −9% | −23% | −9% | −27% | −21% | −27% | −17% | −14% | −31% | −21% |
| Mid top 5 | −8% | −35% | −23% | −38% | −19% | −27% | −19% | −12% | −24% | −32% |
| Mid top 10 | −8% | −35% | −22% | −37% | −17% | −24% | −17% | −11% | −26% | −25% |
| Small top 5 | −8% | −18% | −14% | −31% | −17% | −24% | −16% | −13% | −23% | −7% |
| Small top 10 | −7% | −23% | −9% | −31% | −11% | −21% | −12% | −11% | −19% | −8% |
| QQQ | −5% | −23% | −11% | −29% | −11% | −35% | −11% | −14% | −23% | −15% |

Biggest trades in the top 10 books:

| Year | Large | Mid | Small |
|---|---|---|---|
| 2017 | NVDA +33%, RACE +29% | NXST +23%, Z +17% | KAI +26%, TREE +23% |
| 2018 | ONC +64%, EC +26% | RVTY +23% | AVAV +33%, MED +30% |
| 2019 | SHOP +44%, BALL +32% | ZS +52%, ALNY +44% | LRN +27%, WING +26% |
| 2020 | ZM +155%, TSLA +133%, SE +129% | THO +51%, NVCR +44% | MSTR +78%, CYRX +61% |
| 2021 | AGNT +94%, MRNA +87% | SPSC +43%, NXH +40% | CRTO +50%, VCEL +36% |
| 2022 | PBR +41%, TME +32% | HP +44% | GLNG +65%, CLFD +43% |
| 2023 | PLTR +44% | WING +40%, DUOL +38% | ANF +62%, BVN +43% |
| 2024 | APP +256%, SMCI +157%, VRT +100% | IONQ +143%, TMDX +53% | VITL +57%, LQDT +39% |
| 2025 | HOOD +179%, RKLB +107%, PLTR +60% | BE +45%, LIF +45% | WLDN +110%, B +52% |
| 2026 | SNDK +175% / +108%, WDC +51% | BB +73%, HNGE +66% | KRT +41% |

## With the short hedge (2017–2026)

Each book plus a short of the 15 weakest liquid Large names at 50% of the book, on at a checkpoint while QQQ closes below its 50- and 200-day averages and not above a falling 20-day ([short_hedge_2020_2026.md](short_hedge_2020_2026.md), 20-day rebound hold-off). The same Large basket hedges every tier; for Mid and Small this is untested beyond these runs. Day by day, 10 bps per unit traded on the short side and 1% borrow. Outputs: `hedged_monthly_pnl.csv`, `hedged_yearly_summary.csv`, `scripts/hedge_overlay.py`.

The hedge was never on in 2017, so 2017 is the same with and without it. It was on at 25 checkpoints: Oct–Dec 2018 (4), Jan 2 2019, Mar 16 2020, 14 in 2022, Jan 3 2023, Mar–Apr 2025 (3) and Mar 31 2026.

| Book | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* | 2017–2026 | Per year | Worst drop |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Large top 5 | 8% | −9% | 33% | 110% | −2% | −17% | −3% | 25% | −3% | 35% | 3.5× | 13.5% | −37% |
| Large top 5 + hedge | 8% | −11% | 28% | 98% | −2% | **9%** | −9% | 25% | −1% | 34% | 3.9× | 14.9% | −32% |
| Large top 10 | 9% | −5% | 32% | 140% | 17% | −6% | 1% | 79% | 26% | 41% | 11.4× | 28.0% | −31% |
| **Large top 10 + hedge** | 9% | −7% | 28% | 126% | 17% | **24%** | −6% | 79% | 29% | 39% | **12.8×** | **29.5%** | −36% |
| Mid top 5 | 50% | −18% | 46% | 39% | 39% | −13% | 16% | 47% | 18% | 12% | 6.8× | 21.5% | −38% |
| Mid top 5 + hedge | 50% | −19% | 42% | 30% | 39% | **16%** | 9% | 47% | 22% | 10% | 7.7× | 23.0% | −44% |
| Mid top 10 | 50% | −18% | 52% | 55% | 55% | −15% | 31% | 59% | 17% | 13% | 10.4× | 26.8% | −37% |
| **Mid top 10 + hedge** | 50% | −19% | 47% | 46% | 55% | **12%** | 23% | 59% | 20% | 12% | **11.8×** | **28.4%** | −43% |
| Small top 5 | 19% | 1% | 16% | 86% | 35% | −23% | 29% | 10% | 21% | 47% | 6.8× | 21.5% | −32% |
| **Small top 5 + hedge** | 19% | 0% | 12% | 74% | 35% | **1%** | 21% | 10% | 24% | 46% | **7.6×** | **22.9%** | −36% |
| Small top 10 | 11% | −8% | 10% | 64% | 38% | −10% | 35% | 2% | 20% | 31% | 5.0× | 17.7% | −31% |
| Small top 10 + hedge | 11% | −9% | 6% | 54% | 38% | **18%** | 27% | 2% | 23% | 30% | 5.5× | 19.0% | −36% |
| QQQ | 32% | −2% | 38% | 46% | 29% | −33% | 56% | 28% | 21% | 13% | 6.1× | 20.2% | −35% |

\* Through Nov 12. 2017, 2021 and 2024 are unchanged (hedge never on); 2026 costs 1–2 points (Mar 31). Worst drop is the deepest drop within any one year, measured daily.

- **Every book gains 1.5–1.7 points a year**, and every 2022 turns from a loss into a gain (Large top 10 −6% → +24%, Mid top 10 −15% → +12%).
- **2025 gains 2–4 points** (Mar–Apr tariff selloff). **The other years it fires cost:** in each run the first hedged checkpoint came near a low: Mar 16 2020 (−8 to −14 points), Jan 2 2019 and Jan 3 2023 (−4 to −8 points), late 2018 (−1 point). The hold-off skipped none of these: QQQ was still below its 20-day each time.
- **The worst drop gets deeper** for every book except Large top 5 (−37% → −32%, its worst was 2025, which the hedge softened): the March 2020 short adds 4–6 points to every book's 2020 drop, which becomes the deepest of the nine years. The hedge improves bad years, not crashes that reverse within weeks.
- **Best mix with the hedge:** Large top 10, Mid top 10, Small top 5, unchanged.
- Each year is a separate run, so the hedge starts fresh on each year's first checkpoint (Jan 2 2019 and Jan 3 2023 are on); the continuous study above has the same checkpoints on.

## Top 3 (2017–2026)

The same three recommended rules held 3 names deep (Large here keeps its breakout slots, which then fill all 3 places; see `large_top3` below for the score-only version). Plain / with the short hedge; rows with `top` = 3 in the CSVs, `top3_<year>_trades.pdf`.

| Year | Large top 3 (slots) | Mid top 3 | Small top 3 | QQQ |
|---|---|---|---|---|
| 2017 | 17% / 17% | 51% / 51% | 14% / 14% | 32% |
| 2018 | −28% / −29% | −20% / −21% | **12% / 10%** | −2% |
| 2019 | 41% / 36% | 52% / 47% | 17% / 13% | 38% |
| 2020 | 52% / 43% | 29% / 21% | 75% / 64% | 46% |
| 2021 | 2% / 2% | 30% / 30% | 31% / 31% | 29% |
| 2022 | −21% / **+6%** | −11% / **+17%** | −34% / −14% | −33% |
| 2023 | 21% / 14% | 37% / 28% | 27% / 20% | 56% |
| 2024 | 37% / 37% | 39% / 39% | 4% / 4% | 28% |
| 2025 | −22% / −20% | −9% / −7% | **46% / 49%** | 21% |
| 2026* | 28% / 27% | 37% / 35% | 43% / 41% | 11% |
| **2017–2026** | 2.4× / 2.8× | 6.4× / 7.2× | 6.1× / 6.8× | 6.1× |
| Per year | 9.3% / 10.8% | 20.8% / 22.2% | 20.2% / 21.5% | 20.2% |
| Worst drop | −42% / −40% | −40% / −46% | −36% / −38% | −35% |

\* Through Nov 13.

List size, 2017–2026 compounded (plain):

| Tier | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Large (slots) | 2.4× | 3.5× | **11.4×** |
| Large, score only (`large_top3`) | **27.0×** | | |
| Mid | 6.4× | 6.8× | **10.4×** |
| Small | 6.1× | **6.8×** | 5.0× |

- **Mid gets worse with fewer names:** top 3 lags top 10 in 6 of 10 years; two bad picks sink a 3-name book (2025: −9% vs +17%).
- **Small top 3 is a coin flip against top 5:** it wins 2018 (+12% vs +1%) and 2025 (+46% vs +21%, WLDN +110%) but loses 2022 badly (−34% vs −23%; the hedge only gets it to −14%).
- **The breakout slots ruin a concentrated Large book:** with 3 places all going to breakouts, the momentum leaders enter late or not at all (APP +18% here vs +256% in `large_top3`). Only the score-only version is worth holding 3 deep.
- The hedge adds about 1.5 points a year to each book, nearly all in 2022.

## Large top 3 by the 180-day score alone (`large_top3`, 2017–2026)

The paper-tracked `large_top3` list run the same way: the top 3 Large names by 180-day return / vol_60d^0.5 with the trend filter and no breakout slots, 25% trailing stop, one run per year, plain and with the short hedge above. Outputs: `large_top3_monthly_pnl.csv`, `large_top3_yearly_summary.csv`, `large_top3_<year>_trades.pdf`, `scripts/large_top3_book.py <dir> <year>` and `scripts/large_top3_charts.py <in.pkl> <ohlc cache.pkl> <out.pdf>`.

| Year | large_top3 | + hedge | Worst drop | Large top 10 | QQQ | Best trades |
|---|---|---|---|---|---|---|
| 2017 | **−12%** | −12% | −25% | 9% | 32% | NVDA +20%, PYPL +13% |
| 2018 | −6% | −8% | −25% | −5% | −2% | ONC +64% |
| 2019 | 11% | 7% | −17% | 32% | 38% | SHOP +30% |
| 2020 | **196%** | 178% | −44% (−51% hedged) | 140% | 46% | TSLA +133%, SE +129% |
| 2021 | **50%** | 50% | −39% | 17% | 29% | AGNT +94%, MRNA +72% |
| 2022 | 2% | **33%** | −32% (−30%) | −6% | −33% | DVN +31%, PBR +30% |
| 2023 | −10% | −16% | −31% | 1% | 56% | GE +18% |
| 2024 | **145%** | 145% | −36% | 79% | 28% | APP +256%, VRT +100% |
| 2025 | **103%** | 109% | −31% (−25%) | 26% | 21% | RKLB +107%, HOOD +85% |
| 2026* | 46% | 45% | −39% | 41% | 11% | SNDK +175% / +108% |
| **2017–2026** | **27.0×** (39.7%/yr) | **30.0×** (41.2%/yr) | −44% (−51%) | 11.4× (28.0%/yr) | 6.1× | |
| 2018–2026 | 30.5× (47.0%/yr) | 34.0× (48.8%/yr) | | 10.5× (30.4%/yr) | 4.7× | |

\* Through Nov 13 (QQQ 11% to the same day; the other books run to Nov 12).

- **The highest-return book tested**, about 2.4× Large top 10 over 2017–2026 (3× over 2018–2026); chained 2020–2026 it is 29.4× (≈62% a year), in line with the continuous 64.5% in [concentration_2020_2026.md](concentration_2020_2026.md).
- **Four years make it.** 2020, 2021, 2024 and 2025 beat Large top 10 by 24–77 points; 2017, 2018, 2019 and 2023 lag it by 1–21 points, and 2023 trails QQQ by 66. It beats Large top 10 in 6 of 10 years.
- **2017 shows its weak spot:** −12% while QQQ rose 32%, with a −25% drop and no trade worse than −13%. In a calm year with rotating leaders it bought and sold NVDA four times and TSLA, MU, ISRG and RACE twice or more, each time selling a name that slipped out of the top 3 after a dip.
- **A few names make each year.** 2018–2026: 318 trades, 50% winners, average +5%. Summed over all their trades SNDK (+446%), APP (+261%), SE, VST, PDD, TSLA, PLTR and VRT (+100% to +150% each) carry the book; BNTX, VLO, DXCM, ABVX and NVDA lost 31–44%.
- **Much rougher to hold:** the worst drop within the year is 31–44% in 7 of 10 years (Large top 10: 9–31%).
- **The hedge helps it a little more than the other books** (+1.8 points a year): 2022 +2% → +33%, 2025 +6 points with a shallower drop, but March 2020 deepens that year's drop to −51%.

## Findings

1. **Large needs 10 names.** Top 10 beat top 5 in 9 of 10 years, by 4 to 54 points (2019: within 0.5 points). In the top 5 the breakout slots take places 1–5, so the 180-day momentum leaders that make Large's year (APP, SMCI, VRT in 2024; HOOD, RKLB in 2025; SNDK, WDC in 2026) only enter at places 6–10.
2. **Mid is better with 10** in 6 of 10 years (2017 and 2018 ties: the list held only 31 names all year); 5 names make it hostage to one trade (IONQ was most of 2024) and to a run of stops (Sep–Oct 2026: −13% and −18% with 5 names, −7% and −15% with 10).
3. **Small leans to 5.** Top 5 won 7 of 10 years and compounds 6.8× vs 5.0× over 2017–2026, though top 10 lost less in 2022 (−10% vs −23%). Small's best names sit at the top of its ranking.
4. **Every book is uneven.** Large top 10 had three losing or flat years (2018, 2022, 2023) and three big ones. Large trailed QQQ by 22–24 points in the calm 2017 rally, while Mid made 50%. Every book lost in the Oct and Dec 2018 selloffs except Small top 5 (+1% for the year). All books lost far less than QQQ in 2022 and all trailed QQQ's 2023 rebound, which came from 2022's losers that momentum rules do not hold.
5. **A few trades make each year.** IONQ (Mid 2024), WLDN (Small 2025), HOOD and RKLB (Large 2025), SNDK (Large 2026). Win rates are 43–64%; average trades 0–7%.

## Decision

Best mix from these runs: **Large top 10, Mid top 10, Small top 5**; top 3 helps only Large ranked by the score alone. Over 2017–2026 Large top 10 (11.4×) and Mid top 10 (10.4×) are clearly ahead of QQQ (6.1×) and Small top 5 (6.8×) about level; adding 2017 lifts Mid (50% that year) and trims Large and `large_top3`. This matches the 2020–2026 concentration study, which found Large top 10 the best risk-adjusted Large book. The paper-tracked lists stay at 15; these sizes are not paper-tracked yet. `large_top3` (27.0× over 2017–2026) is the highest-return Large option but rests on a few names a year and drops 30–45% most years; it fits as a smaller sleeve beside Large top 10, not a replacement.

## Caveats

- **In-sample:** the rules and list sizes were chosen on 2020–2026; 2017–2019 were added afterwards and are closer to out-of-sample.
- **Separate one-year runs:** books restart in cash each January.
- **Smaller 2017–2019 universe:** only stocks listed today (1,728 names in 2017, 1,849 in 2018, 1,930 in 2019 vs about 2,900 now), so delisted and acquired names are missing and those years are likely flattered most.
- **Chart prices:** charts use fresh adjusted OHLC bars from Alpaca, while trades use the cached closes; a name whose adjustment changed since (CTVA in 2026) shows a scaled price axis, with the shape and trade return unaffected.
- **Survivorship and execution:** as in [selection_filters_2020_2026.md](selection_filters_2020_2026.md); stops fill at the close that breaches them.
