# 2026 top-10 winners, checkpoint by checkpoint, against the top-15 lists

Script: `alpha_tech_tracker/research/winner_progression.py --years 2026 --rule current|mom120`. Outputs: `research/top_performers_output/uptrend_formation/winner_progression/2026/<rule>/`:
- `grid.csv`
- `progression.csv` (every winner × checkpoint with features)
- `episodes.csv` (each holding stretch: entry, exit, why it left, when it came back)
- `feature_comparison.csv`

Lists: the recommended rules from [selection_filters_2020_2026.md](selection_filters_2020_2026.md):
- **Large:** trend + risk-adjusted 120-day momentum + clean.
- **Small:** trend + composite + no dilution + prefer gross profit.
- **Mid:** trend + composite, for reference only.

## How to read the grids

Each cell is one checkpoint, every 10 trading days. "YTD when first held" is the year-to-date gain at the first checkpoint the list held the stock.

| Cell | Meaning |
|---|---|
| `H4` | held, ranked 4 |
| `27` | in an uptrend but ranked 27 (not held) |
| `T` | failed the trend filter (below its 50-day average, 50-day below 200-day, or 200-day falling) |
| `X` | removed by an exclusion rule (dilution for Small; faded jump or heavy-volume drop for Large) |
| `.` | not in the tier |

### Large

```
       01-02 01-16 02-02 02-17 03-03 03-17 03-31 04-15 04-29 05-13 05-28 06-11 06-26 07-13 07-27 08-10 08-24 09-08 09-22 10-06 10-20 11-03  year  first held  YTD then
MRNA       T   358   229   195    89    61    75    55     T     T     T    96    22   106     T   157   171   189   119    87    51    89   762%   never
SNDK      H2    H1    H2    H2    H1    H1    H1    H1    H1    H1    H1    H1    H1     T     T     T     T    82    40    77     T     T   252%   01-02        +16%
DELL       T     T     T     T     T     T   170   272   216    72   H11    16   H11    H1    H1    H1    H7    H2    H3    H7     T     T   164%   05-28       +154%
MU       H15    H5    H3    H6    H6    H4     T    28    21    H4    H4    H2    H6    18     T     T     T    62    H4    24     T     T   142%   01-02        +11%
RVMD      H5    H4    27    16    30     T     T    20    50   113   102   112    48    50    H4    H5    H2    H4     T     T     T     T   141%   01-02         −1%
MPC        T     T     T   321   298   177   103   208   157   207   124    61    36    H3    H3   H13    H6   H12    32    H8    H2   H10   132%   07-13        +84%
VLO        T   232   165   183   161   103    50    59    85   169   116    50    39    17    H7   H15   H12    18    42   H11   H11     T   116%   07-27        +89%
AMD        T   270   242     T     T     T     T     X     X    87    16    23    30    16     T     T     T    H7    H2   H13     T     T   110%   09-08       +136%
BE         T   H11   H11    43    46    95     T   124   116    64    31    21     T     T     T     T     T   143    88   131     T     T    99%   01-16        +72%
SN       362   399   394   356     T     T     T   241   183     T     T   230   185   210   136    63    24    25     T    29    21    H2    99%   11-03        +88%
```

### Small

```
       01-02 01-16 02-02 02-17 03-03 03-17 03-31 04-15 04-29 05-13 05-28 06-11 06-26 07-13 07-27 08-10 08-24 09-08 09-22 10-06 10-20 11-03  year  first held  YTD then
CDNA       T   355   326     T     T     T     T     T   292   265   171   156   235   230   271   196   107    70    18    81   100   135   317%   never
PLSE       T     T     T     T   307   144   173     T     T   238   237   220   176   211   114    91    75   123    88   135   160   123   288%   never
ERAS      65   102    84    74    58   112   146   209     T     T     T     T   247   271   224   265     T     T     T     T     T     T   287%   never
TWST       T     T   265   161   214    90   137   204   211   187   162   105   115   203   267   107   117   217    96   115     T     T   281%   never
KOD      249   216     T     T   222     T   170     X     X     X     T     T     T     X     X     X     T     T     T     X     X     X   255%   never
ABCL       T     T     T     T     T     T     T     T     T     T     T   264   204   275     T   102   144   144    79   104     T     T   247%   never
ATEX       T     T     T     T   133    42    96   214    77   H12   H11   132   168   130   164   228     T     T     T     T     T     T   241%   05-13       +153%
ORKA       T     X     X     X     X     X     X     X     X     X     T     X     X     X     X     X     X     T     T     T     T     X   239%   never
ETON       T     T     T     T     T     T    34    36    43    35    42    36    H1    H1    37    38    40    54    50     T     T     T   234%   06-26       +111%
ELVN       T     T     X     X     X     X     X     X     X     X     T     T     X     X     X     X     X     X     T     T     T     T   221%   never
```

### Mid (reference)

Mid caught 3 of 10:
- SYRE once, in May.
- INSW in August.
- ANDG and HNGE only on 11-03, after a 150% gain.

The rest ranked 20–400 while in an uptrend.

## Why winners were missed

Checkpoints are counted only while each winner still had at least 25% of its year's gain ahead.

| Reason not held | Large | Mid | Small |
|---|---|---|---|
| held | 13 | 1 | 2 |
| in an uptrend, but ranked below 15 | **65** | **67** | **51** |
| below its 50-day average | 27 | 46 | 31 |
| 50-day below 200-day, or 200-day falling | 4 | 28 | 19 |
| excluded: dilution (Small) | | | 20 |
| excluded: heavy-volume drop | 2 | | |

### Medians while the winners were still running, against the list's own picks

| Tier | Group | 60-day vol | 120-day return | Risk-adj 120 | Off 52-week high | Max 1-day gain (20d) | Sales growth | Cash burn |
|---|---|---|---|---|---|---|---|---|
| Large | winners, not held | **0.50** | 36% | 0.78 | −8% | 7% | 9% | 0 |
| Large | winners, held | 0.71 | 226% | 3.30 | −2% | 11% | 57% | 0 |
| Large | top-15 picks | 0.43 | 113% | 2.45 | −2% | 6% | 23% | 0 |
| Small | winners, not held | **0.73** | 56% | 0.77 | −13% | 9% | 38% | 1 |
| Small | top-15 picks | **0.29** | 43% | 1.50 | 0% | 3% | 6% | 0 |

## What the 2026 winners had that the lists don't reward

1. **High volatility.** Small winners ran at 73% annualized volatility, while the Small list's picks ran at 29%. Every ranking we use divides by volatility (risk-adjusted momentum) or rewards smoothness (the composite), so a fast, jumpy stock ranks 100–300 even after doubling. The Small list is effectively a low-volatility small-cap list.
2. **One theme per tier.**
   - Small: 9 of 10 winners were health-care and biotech.
   - Large: memory and semiconductors (SNDK, MU, AMD, DELL) and refiners (MPC, VLO). PBF in Mid is also a refiner.
   - Mid: tankers (FRO, INSW).
3. **Dilution is normal for biotech winners.** KOD, ORKA and ELVN were removed by the dilution rule for most of the year, because biotechs raise cash after good news.
4. **Late recognition in Large:**
   - DELL, AMD, MPC, VLO and SN were first held after gains of 84–154%. The 120-day window needs months to rank a new leader.
   - SNDK, MU and RVMD were held from January, but dropped out for long stretches whenever they dipped below their 50-day average.

## Does fixing this help in other years? (all 2020–2026)

Each rule was checked over all seven years for winner capture and the top-15 portfolio (no buffer, no gate). "Winners" counts all 70 yearly top-10 stocks, including a few outside the Small universe.

| Tier | Rule | Winners held | Median days into the year when first held | Gain ahead then | Gain captured | CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|---|---|---|
| Large | current: risk-adjusted 120d + clean | 65/70 | 144 | 44% | 13% | 20.1% | 0.85 | −30% |
| Large | **raw 120-day return + clean** | **69/70** | **104** | **52%** | **21%** | **23.1%** | 0.81 | −32% |
| Large | raw 60-day return + clean | 70/70 | 89 | 59% | 22% | 18.2% | 0.71 | −43% |
| Large | risk-adjusted 120d + prefer top-quartile sector | 64/70 | 138 | 45% | 7% | 11.2% | 0.56 | −29% |
| Small | current | 16/70 | 213 | 31% | 4% | 18.6% | 0.83 | −43% |
| Small | raw 120-day return + clean | 53/70 | 176 | 36% | 22% | 13.9% | 0.51 | −57% |
| Small | raw 60-day return + clean | 52/70 | 118 | 44% | 8% | 4.8% | 0.34 | −65% |

**Large, raw 120-day return:**
- Catches more winners, about 40 days earlier, and keeps 21% of their gain instead of 13%.
- The book makes 23.1% a year instead of 20.1%, at higher volatility (32% vs 25%).
- Sharpe is a little lower and the worst drawdown a little deeper.
- It is not a steady improvement. It wins big in 2020 (85% vs 53%) and 2026 (49% vs 9%), but loses in 2021 (1% vs 31%), 2023 and 2024: better in 3 of 7 years.

**Small:** chasing the winners does not pay. Raw momentum catches 53 of 70 winners, but the book falls to 13.9% with a −57% drawdown, because the many high-volatility losers outweigh the few winners. The low-volatility Small list makes more money while missing the stars.

**Sector preference hurts both** (Large 20.1% → 11.2%). The 2026 themes were not visible early enough in sector medians to help.

## Conclusions

- **The missing "factor" is volatility itself.** Big yearly winners are mostly high-volatility stocks, so a list built to beat the market steadily will keep missing them. Catching more top-10 names and earning the best return are different goals here.
- **Large:** a raw 120-day version is a reasonable alternative if you want more winner exposure. It catches 69 of 70 winners earlier and returns more, but is bumpier and only better in 3 of 7 years. One option is to run both lists and hold the union of their top 8; that has not been tested.
- **Small:**
  - Keep the low-volatility list for returns.
  - The biotech run was invisible to it by design: high volatility, dilution, no gross profit.
  - Catching such runs would need a separate high-volatility list with its own risk limits.
- **Treat the 2026 explanations as hypotheses.** They come from one year and 30 stocks. Only the all-years table above is evidence.

## Rerun with the plain 120-day rule (`--rule mom120`)

Every tier is ranked by raw 120-day return. It keeps the trend filter and the "clean" exclusion, but drops the volatility adjustment and the dilution and gross-profit rules.

### First pick-up, exits and re-entries

| Tier | Rule | Winners held | Holding stretches | Came back after leaving | Median first entry | Median YTD at first entry | Median gain earned while held |
|---|---|---|---|---|---|---|---|
| Large | current | 9/10 | 15 | 6 | 05-28 | +84% | 19% |
| Large | mom120 | **10/10** | 20 | 10 | **04-22** | +84% | 22% |
| Mid | current | 4/10 | 5 | 1 | 09-28 | +142% | −3% |
| Mid | mom120 | 8/10 | 13 | 5 | 07-04 | +111% | 18% |
| Small | current | 2/10 | 2 | 0 | 06-04 | +132% | 33% |
| Small | mom120 | **10/10** | 16 | 6 | 06-26 | **+154%** | 29% |

Why holdings were dropped:

| Exit reason | Large current | Large mom120 | Small mom120 |
|---|---|---|---|
| closed below the 50-day average | 6 | 10 | 4 |
| still in an uptrend, but ranked below 15 | 7 | 7 | 8 |
| heavy-volume drop | 0 | 0 | 1 |
| still held on 11-03 | 2 | 3 | 3 |

### Large (mom120)

```
       01-02 01-16 02-02 02-17 03-03 03-17 03-31 04-15 04-29 05-13 05-28 06-11 06-26 07-13 07-27 08-10 08-24 09-08 09-22 10-06 10-20 11-03
MRNA       T   201    46    38    19    H9   H13    18     T     T     T    55    20    18     T    51    H2    H3    H1    H1    H1    H1
SNDK      H2    H1    H1    H1    H1    H1    H1    H1    H1    H1    H1    H1    H1     T     T     T     T    H6    H6    28     T     T
DELL       T     T     T     T     T     T   148   210   105    30   H15    H8    H5    H1    H1    H1    H1    H1    H2    H2     T     T
MU        H8    H5    H5    H4    H4    H4     T   H11    H9    H3    H2    H2    H2    H2     T     T     T   H11    H4   H14     T     T
RVMD     H13    H6   H11    H7   H10     T     T    H5    H8    27    28    32    17    25    H4    H8    H7    16     T     T     T     T
MPC        T     T     T   278   250   125    88   175   107   162   109    71    43   H14    H8    20   H14    26    41    23    H9   H13
VLO        T   163   120   120   105    61    40    64    63   129    90    60    40    17   H10    21    19    31    48    29    19     T
AMD        T   135    99     T     T     T     T     X     X    35    16   H15   H15    H5     T     T     T    H4    H5    H8     T     T
BE         T    H3    H2    H6    H5   H11     T   H14   H12   H12    H8    H5     T     T     T     T     T    25    24    54     T     T
SN       354   373   387   316     T     T     T   174   106     T     T   170   108   145    71    40    23    30     T    39    17    H3
```

### Small (mom120)

```
       01-02 01-16 02-02 02-17 03-03 03-17 03-31 04-15 04-29 05-13 05-28 06-11 06-26 07-13 07-27 08-10 08-24 09-08 09-22 10-06 10-20 11-03
CDNA       T   145    96     T     T     T     T     T   144   203   219   203   135   112    23   H14   H10    H5    H7    H2    H2    H1
PLSE       T     T     T     T   212   126   176     T     T    89    56    48    38    35    H5    62    H5    17    23    H6    H5   H13
ERAS      34    H8    H5    H5    H4    H2    H2    H2     T     T     T     T     X     X    24   114     T     T     T     T     T     T
TWST       T     T   102    54    52    44    66    66    53    49    34    24   H12   H14    21   H15    H3    H7    H5     X     T     T
KOD      H11    18     T     T    19     T    H9    24    20    52     T     T     T    80    31    38     T     T     T   H15    H9    H5
ABCL       T     T     T     T     T     T     T     T     T     T     T    95    33    68     T    H7    H4    H1    H3    H3     T     T
ATEX       T     T     T     T    66    49    34    53    23    27   H12    H7    H4    H2    H1    H9     T     T     T     T     T     T
ORKA       T    46    31    38    39   H15   H15    20    17    35     T    21   H11    H9    H3    H4    H2     T     T     T     T    59
ETON       T     T     T     T     T     T   159   124   200    82    49    37    30   H10    H2   H11    H1    H2    27     T     T     T
ELVN       T     T   116   168   107    80    25    30    26    64     T     T   H10    29    18    17    25    22     T     T     T     T
```

### Notable stretches (mom120)

- **SNDK:** held from 01-02 at +16% YTD to 07-13 at +605%, 13 checkpoints in a row. It left when it closed below its 50-day average and came back on 09-08 at +632%. It ended the year at +252%, so the 50-day exit kept most of a gain that later halved.
- **MRNA** (+762% for the year):
  - First held 03-17 at +83%, then dropped on 04-15 because it slipped to rank 18.
  - Came back 9 checkpoints later, on 08-24 at +371%, and was still held on 11-03.
  - The current rule never held it.
- **MU:** three stretches. It left twice on a close below the 50-day average and came back 1–3 checkpoints later. It earned +97% in the second stretch alone.
- **DELL:** held from 05-28 (+154%) to 10-20, earning +46%. It ranked 30–210 before then, because its 120-day gain wasn't large yet.
- **Small:**
  - Every winner was held at some point.
  - Most were first held only after 100%+ gains: CDNA at +150%, TWST +215%, ELVN +225%, ATEX +198%.
  - KOD and ORKA entered early (−7% and +36%), but each dropped within a checkpoint or two when their rank slipped to 18–24, then came back much later.

### What the rerun shows

1. **The plain 120-day rule finds the winners: 10/10 in Large and Small.** In Large it finds them about a month earlier on the calendar, but at the same median YTD gain (+84%). A 120-day window only ranks a stock high after it has already moved a lot.
2. **Most drops are rank churn, not breakdowns.** Half the exits came while the stock was still in an uptrend, at ranks 16–30. With a top-15 cutoff and no buffer, a winner falls out on a normal pause and often comes back 1–5 checkpoints later. That costs the gain in between plus two trades. A holding buffer (keep while ranked ≤ 40) would have kept most of these, for example MRNA from 03-17 and KOD from 03-31. Its cost elsewhere is in [selection_filters_2020_2026.md](selection_filters_2020_2026.md): about 5 points a year on the Large list.
3. **Closing below the 50-day average is the other main exit.** It saved SNDK's gain, but cut MU and BE twice each before they recovered.
4. **2026 flatters the plain rule.** Over 2020–2026 the Small version made 13.9% a year with a −57% drawdown, against 18.6% for the current Small rule. Large made 23.1% vs 20.1%, but was better in only 3 of 7 years. Catching all ten 2026 winners does not make it the better book.
