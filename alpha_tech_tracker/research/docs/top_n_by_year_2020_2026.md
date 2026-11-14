# Top 5 vs top 10, year by year (2020–2026)

The question: holding only the top 5 or top 10 names of each recommended list, what does each year look like month by month, which trades made it, and which list size suits each tier?

Outputs: `research/top_performers_output/uptrend_formation/top_n_by_year/`:
- `monthly_pnl.csv`: monthly return of every book and QQQ, per list size and year
- `yearly_summary.csv`: year return, worst drop, trades, win rate, average trade
- `top<N>_<year>_trades.pdf`: a summary page (equity curves, monthly table, trade stats), then every trade in checkpoint order, 6 per page: daily candles with the 8/20/50/200-day averages, the holding period shaded (green gain, red loss) and the trade's return and exit reason
- `scripts/top_n_books.py <out.pkl> <N> <year>` and `scripts/top_n_charts.py <in.pkl> <ohlc cache.pkl> <out.pdf>`: one-off scripts (not in the test suite)

## Setup

- **Rules:** the recommended rules. Large is 180-day / vol^0.5 with breakout slots in the first 5 places, 25% trailing stop. Small is composite + no dilution + prefer gross profit, 15% trailing stop. Mid is the reclaim + growth list, never-held names first, 15% trailing stop.
- **Book:** top N, equal weight, checked every 10 trading days. A holding is kept while it ranks within N (Mid: while it stays on the list). 0.1% cost per trade; the trailing stop is held day by day, and a stopped name goes to cash until the next checkpoint.
- **Each year is a separate run** that starts in cash in January and ends Dec 31 (2026: Nov 12); Mid's never-held memory resets each year. The compounded figures chain these runs, so they differ a little from one continuous book.

## Results

| Book | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* | Compounded | Per year |
|---|---|---|---|---|---|---|---|---|---|
| Large top 5 | 110% | −2% | −17% | −3% | 25% | −3% | 35% | 2.7× | ≈16% |
| **Large top 10** | 140% | 17% | −6% | 1% | 79% | 26% | 41% | **8.4×** | **≈36%** |
| Mid top 5 | 39% | 39% | −13% | 16% | 47% | 18% | 12% | 3.8× | ≈21% |
| **Mid top 10** | 55% | 55% | −15% | 31% | 59% | 17% | 13% | **5.6×** | **≈28%** |
| **Small top 5** | 86% | 35% | −23% | 29% | 10% | 21% | 47% | **4.9×** | **≈26%** |
| Small top 10 | 64% | 38% | −10% | 35% | 2% | 20% | 31% | 4.4× | ≈24% |
| QQQ | 46% | 29% | −33% | 56% | 28% | 21% | 13% | 3.4× | ≈20% |

\* Through Nov 12.

Worst drop within each year:

| Book | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|
| Large top 5 | −28% | −19% | −26% | −23% | −11% | −37% | −12% |
| Large top 10 | −27% | −21% | −27% | −17% | −14% | −31% | −21% |
| Mid top 5 | −38% | −19% | −27% | −19% | −12% | −24% | −32% |
| Mid top 10 | −37% | −17% | −24% | −17% | −11% | −26% | −25% |
| Small top 5 | −31% | −17% | −24% | −16% | −13% | −23% | −7% |
| Small top 10 | −31% | −11% | −21% | −12% | −11% | −19% | −8% |
| QQQ | −29% | −11% | −35% | −11% | −14% | −23% | −15% |

Biggest trades in the top 10 books:

| Year | Large | Mid | Small |
|---|---|---|---|
| 2020 | ZM +155%, TSLA +133%, SE +129% | THO +51%, NVCR +44% | MSTR +78%, CYRX +61% |
| 2021 | AGNT +94%, MRNA +87% | SPSC +43%, NXH +40% | CRTO +50%, VCEL +36% |
| 2022 | PBR +41%, TME +32% | HP +44% | GLNG +65%, CLFD +43% |
| 2023 | PLTR +44% | WING +40%, DUOL +38% | ANF +62%, BVN +43% |
| 2024 | APP +256%, SMCI +157%, VRT +100% | IONQ +143%, TMDX +53% | VITL +57%, LQDT +39% |
| 2025 | HOOD +179%, RKLB +107%, PLTR +60% | BE +45%, LIF +45% | WLDN +110%, B +52% |
| 2026 | SNDK +175% / +108%, WDC +51% | BB +73%, HNGE +66% | KRT +41% |

## Findings

1. **Large needs 10 names.** Top 10 beat top 5 in every year, by 4 to 54 points. In the top 5 the breakout slots take places 1–5, so the 180-day momentum leaders that make Large's year (APP, SMCI, VRT in 2024; HOOD, RKLB in 2025; SNDK, WDC in 2026) only enter at places 6–10.
2. **Mid is better with 10** in 5 of 7 years; 5 names make it hostage to one trade (IONQ was most of 2024) and to a run of stops (Sep–Oct 2026: −13% and −18% with 5 names, −7% and −15% with 10).
3. **Small is a close call.** Top 5 compounds slightly more (4.9× vs 4.4×), but top 10 won 3 of 7 years and lost less in the bad ones (2022 −10% vs −23%). Small's best names sit at the top of its ranking.
4. **Every book is uneven.** Large top 10 had two flat years (2022, 2023) and three big ones. All books lost far less than QQQ in 2022 and all trailed QQQ's 2023 rebound, which came from 2022's losers that momentum rules do not hold.
5. **A few trades make each year.** IONQ (Mid 2024), WLDN (Small 2025), HOOD and RKLB (Large 2025), SNDK (Large 2026). Win rates are 43–64%; average trades 0–7%.

## Decision

Best mix from these runs: **Large top 10, Mid top 10, Small top 5** (Small top 10 is a reasonable lower-risk alternative). This matches the 2020–2026 concentration study, which found Large top 10 the best risk-adjusted Large book. The paper-tracked lists stay at 15; these sizes are not paper-tracked yet.

## Caveats

- **In-sample:** the rules and list sizes were judged on the same seven years.
- **Separate one-year runs:** books restart in cash each January.
- **Chart prices:** charts use fresh adjusted OHLC bars from Alpaca, while trades use the cached closes; a name whose adjustment changed since (CTVA in 2026) shows a scaled price axis, with the shape and trade return unaffected.
- **Survivorship and execution:** as in [selection_filters_2020_2026.md](selection_filters_2020_2026.md); stops fill at the close that breaches them.
