# Extra factors for spotting top performers (2020–2026)

This report tests three price-derived factors on the biweekly checkpoint panels from [uptrend_formation_2020_2026.md](uptrend_formation_2020_2026.md), with closed-end funds excluded:

- earnings-style jumps
- comebacks from deep drawdowns
- listing age

Script: `alpha_tech_tracker/research/winner_factors.py`. Outputs: `research/top_performers_output/uptrend_formation/winner_factors/`.

## Factor definitions

| Factor | Definition |
|---|---|
| jump_held_60d | An up-jump in the last 60 trading days, still holding at least half of it. A jump is a close-to-close move of at least 8% and at least 3× the stock's 60-day daily standard deviation, on at least 3× its 50-day average share volume. |
| jump_faded_60d | An up-jump in the last 60 days that gave back more than half |
| drop_60d | A down-jump with the same thresholds in the last 60 days |
| jumps_250d_2plus | Two or more up-jumps in the last year |
| turnaround | 1-year low ≥ 50% below the high of the prior ~18 months, and the stock has crossed back above its 200-day average after being below it within the last 60 days |
| listed_lt_1y / listed_1_3y | Trading days since the first cached bar. Unknown, and left out, while the cache start (Sep 2018) hides the real listing date. |

The cached bars have no open price, so the overnight gap itself can't be isolated. A "jump" is the whole day's move on heavy volume, which is usually an earnings or news reaction.

## Results

**Each factor on its own.** The table shows the next 60 days within each size group:

- **Lift:** how much more likely the stock is to finish in the top 5%.
- **Vol-matched lift:** the same, compared only with stocks of similar volatility.
- **Loss lift:** how much more likely it is to finish in the bottom 5%.
- **Excess:** return beyond same-volatility peers.

| Factor | Tier | Names per checkpoint | Lift | Vol-matched lift | Loss lift | Excess | Excess, QQQ > MA200 | Years positive |
|---|---|---|---|---|---|---|---|---|
| jump_held_60d | Large | 38 | 1.76 | 0.94 | 1.91 | −0.3% | −0.1% | 2/7 |
| jump_held_60d | Small | 78 | 1.33 | 0.87 | 1.46 | +0.4% | +0.4% | 4/7 |
| jump_faded_60d | Large | 15 | 1.94 | 0.92 | 2.85 | −3.0% | −2.9% | 1/7 |
| jump_faded_60d | Mid | 33 | 1.53 | 0.87 | 2.22 | −1.6% | −1.7% | 0/7 |
| jumps_250d_2plus | Large | 48 | 2.32 | 1.14 | 2.96 | −2.1% | −1.8% | 1/7 |
| **turnaround** | **Large** | 31 | 2.47 | **1.27** | 1.92 | **+1.5%** | **+1.9%** | 4/7 |
| **turnaround** | **Mid** | 70 | 1.71 | 1.07 | 1.60 | +0.5% | +0.8% | 4/7 |
| **turnaround** | **Small** | 95 | 1.51 | 1.11 | 1.23 | **+1.5%** | **+1.7%** | **6/7** |
| listed_lt_1y | Large | 7 | 2.16 | 1.16 | 4.26 | −3.6% | −3.8% | 3/7 |
| listed_lt_1y | Small | 19 | 1.32 | 1.01 | 2.09 | −2.1% | −2.3% | 2/7 |
| listed_1_3y | Small | 67 | 1.34 | 0.98 | 1.90 | −2.6% | −2.1% | 3/7 |

**Added to the early-momentum list.** Excess of flagged names with the factor minus those without it:

| Factor | Large | Mid | Small |
|---|---|---|---|
| turnaround | +0.8% (4/7 yrs) | +0.8% (4/7) | **+2.4% (6/7)** |
| jump_held_60d | −0.6% | +0.1% | −0.6% |
| jump_faded_60d | −6.2% | −3.0% | 0.0% |
| drop_60d | −3.3% | −1.1% | −5.4% |
| listed_lt_1y | −3.9% | −2.8% | −1.8% |
| listed_1_3y | −0.9% | −1.8% | −6.3% |

Inside the ranked top-30 lists the samples get small: 24–600 names with the factor across all checkpoints. The direction mostly agrees. Turnaround adds +4.9% in the Large risk-adjusted momentum list (5 of 7 years) and +1.3% in the Small composite list.

**How common each factor was among the yearly top-10 winners.** Each row is the share of stocks showing the factor at any checkpoint in January–June of their year:

| Factor | Winners | Other stocks | Ratio |
|---|---|---|---|
| jump_held_60d | 60% | 26% | 2.3× |
| jumps_250d_2plus | 49% | 18% | 2.6× |
| turnaround | 60% | 25% | 2.4× |
| listed_lt_1y | 8% | 3% | 2.5× |
| listed_1_3y | 18% | 9% | 2.0× |

## Findings

1. **Turnaround is the one factor that adds an edge.** It beats same-volatility peers in every size group, most consistently in Small caps (6 of 7 years). The edge is in up markets (QQQ above its 200-day average); in down markets it lags by 0.5–1.8%. It also adds to the momentum lists, which mostly favour stocks near their highs. Winners showing the turnaround signal in the first half of their year:

| Year | Winners | Context |
|---|---|---|
| 2020 | 25 of 30 | after the COVID crash |
| 2021 | 11 of 30 | |
| 2022 | 17 of 30 | energy and tankers |
| 2023 | 27 of 30 | the 2022 rebound: NVDA, META, COIN, MARA, RIOT |
| 2024 | 17 of 30 | |
| 2025 | 22 of 30 | memory and miners: WDC, MU, STX, AU, HL |
| 2026 | 16 of 30 | |
2. **Jumps mark volatility, not an edge.** Winners have more jump days (2.3–2.6× as common), but so do losers. After matching on volatility the lift is about 0.9–1.1, and the return against peers is flat to negative. Useful as a negative filter: a faded jump (Large −3.0%, Mid −1.6%) or a recent big drop on heavy volume (−1% to −5% inside the momentum list) is a reason to skip a name.
3. **Young listings are lottery tickets.** They are more likely to land in the top 5% (lift 1.3–2.2), but 2–4× more likely to land in the bottom 5%, and their return against peers is negative in all tiers. The universe only includes stocks still listed today, so failed IPOs and de-SPACs are missing. The real result is worse, which makes this conclusion safe.
4. **Winners look different in hindsight from what predicts them.** Every factor is 2–2.6× more common among winners, yet only turnaround predicts returns. The others are common among winners because winners are volatile.


## Industry-group strength

- **Labels:** current sector and industry labels from the Nasdaq screener (one request, 149 industries, 99.6% of panel rows labelled). They are cached in `market_data/top_performers/industries.csv` and refreshed every 30 days. Code: `alpha_tech_tracker/research/industry_groups.py`.
- **Group measures:** at each checkpoint, every industry with at least 5 stocks in the universe (all tiers combined) gets:
  - its median 60- and 120-day return, and its percentile among industries;
  - its breadth: the share of members with close > MA50 > MA200 and a rising MA200.

| Factor | Definition |
|---|---|
| group_top20_120d / _60d | Stock's industry is in the top 20% of industries by median 120- / 60-day return |
| group_bottom20_120d | Industry in the bottom 20% by median 120-day return |
| group_breadth_60 | At least 60% of the industry's stocks are in an uptrend |
| leader_in_top_group | Industry in the top 20% (120-day), the stock beats its industry's median, and it is in an uptrend itself |

**Each factor on its own.** Columns are as in the first results table:

| Factor | Tier | Vol-matched lift | Loss lift | Excess | Years positive |
|---|---|---|---|---|---|
| group_top20_120d | Large | 1.22 | 0.86 | +0.9% | 5/7 |
| group_top20_120d | Mid | 1.09 | 0.84 | +0.5% | 4/7 |
| group_top20_120d | Small | 1.12 | 0.81 | +1.4% | 5/7 |
| group_top20_60d | Large | 1.27 | 0.88 | +1.2% | 5/7 |
| group_top20_60d | Small | 1.06 | 0.80 | +1.7% | 5/7 |
| group_bottom20_120d | Large / Mid / Small | 1.00–1.03 | 1.42–1.50 | −1.0% / −1.0% / −1.3% | 2/7 each |
| leader_in_top_group | Large | 1.34 | 0.84 | +1.0% | 4/7 |
| group_breadth_60 | Large / Mid / Small | 0.99–1.08 | 0.57–0.66 | +0.6% / +0.7% / +1.6% | 3–4/7 |

**Added to the candidate lists.** Excess with the factor minus without it:

| List | Tier | top-group (120d) | top-group (60d) | bottom-group | leader in top group |
|---|---|---|---|---|---|
| early momentum | Large | **+2.2% (6/7)** | +2.9% (4/7) | −1.6% | +2.6% (5/7) |
| early momentum | Mid | +0.8% (4/7) | +1.7% (4/7) | **−3.6% (worse in 6/7)** | +0.3% |
| early momentum | Small | +2.1% (4/7) | +2.5% (4/7) | **−3.7% (worse in 6/7)** | +0.4% |
| top-30 trend+riskadj120 | Large | +1.3% (4/7) | +1.2% (4/7) | −2.2% | +1.7% (5/7) |
| top-30 trend+riskadj120 | Mid | −0.2% | −0.3% | −0.2% | −0.2% |
| top-30 trend+composite | Small | +0.2% | −1.5% | −0.7% | +0.2% |

**Winners:** 70% of yearly winners were in a top-20% industry at some checkpoint in January–June, against 48% of other stocks (1.5×). 55% were leaders in a top industry, against 24% (2.3×).

**Findings:**

1. **Group strength is a real, broad edge, and it lowers risk.** Stocks in top-20% industries beat same-volatility peers in every size group, in 4–5 of 7 years. Unlike jumps and young listings, they are also less likely to end in the bottom 5% (loss lift 0.8–0.9).
2. **It is most useful for trimming the wide momentum list.** Keeping only early-momentum names whose industry is in the top 20% roughly halves to thirds the list (32–45% of names kept). Those names did 2–3% better over 60 days. Momentum names in the weakest industries lag by 1.6–3.7%.
3. **It adds to the Large ranked list** (+1.2% to +1.7%, 4–5 of 7 years), **but not to the Mid list or the Small composite.** The composite's calm, steady names don't depend on their industry's trend.
4. **Breadth (most of the group in uptrends) adds less than group return** and isn't consistent year to year.

**Caveats specific to industry groups:**

- **Current labels:** labels are today's, applied to all years. A company that changed business is labelled by its current one.
- **Coarse, quirky categories:** Nasdaq's industries are broad and sometimes odd (e.g. Agilent under "Industrials").
- **The stock counts in its own group:** each group's median includes the stock itself. For 5–10 member groups, a single big mover can lift its own group's rank.


## Sales and earnings growth from SEC filings

- **Data:**
  - Quarterly revenue and net income come from SEC XBRL company facts: the nightly bulk `companyfacts.zip`, with ticker → CIK from `company_tickers.json`. Code: `alpha_tech_tracker/research/sec_fundamentals.py`.
  - Requests carry the contact from the `SEC_USER_AGENT` environment variable, as SEC's fair-access policy requires.
  - A compact extract of 2,774 companies (about 14 MB) is cached at `market_data/top_performers/sec/sec_quarters.pkl` and rebuilt after 30 days. The 1+ GB zip is deleted after extraction.
- **Point in time:** each quarter keeps its first-filed value and filing date, and a checkpoint only sees quarters filed before it. Late filers are handled; SMCI's delayed 2024 quarters appear only from February 2025. Q4 is the annual value minus Q1–Q3, known from the 10-K date. Reports for quarters that ended more than 200 days earlier are ignored.
- **Earnings use net income, not EPS:** first-filed EPS mixes pre- and post-split share counts. NVDA's 2024 10-for-1 split made a derived Q4 EPS negative.
- **Coverage:** 56–74% of panel rows. Foreign filers (20-F / 6-K, many ADRs such as PDD, SE and NIO) have no quarterly US-GAAP data, and some banks use other revenue tags.

| Factor | Definition (latest quarter vs the same quarter a year earlier) |
|---|---|
| sales_growth_25 | Revenue growth ≥ 25% |
| sales_accel | Revenue growth > 0 and at least 5 points faster than the previous quarter's growth |
| sales_accel_2q | Revenue growth positive and faster than the prior quarter, two quarters in a row |
| earnings_growth_25 | Net income growth ≥ 25% from a positive base |
| earnings_accel | Net income growth positive and faster than the previous quarter's |
| margin_expansion | Net margin up at least 1 point year over year |
| growth_accel_combo | Revenue growth ≥ 20% and accelerating, and net income growth ≥ 20% |
| sales_decel | Revenue growth at least 10 points slower than the previous quarter's |

**Each factor on its own.** Excess is the next 60 days' return beyond same-volatility peers; years positive is in parentheses:

| Factor | Vol-matched lift (L / M / S) | Excess, Large | Excess, Mid | Excess, Small |
|---|---|---|---|---|
| sales_growth_25 | 1.27 / 1.17 / 1.13 | +0.6% (6/7) | +0.3% (4/7) | +0.4% (4/7) |
| sales_accel | 1.05 / 1.08 / 1.05 | −0.0% (2/7) | +0.7% (5/7) | +0.5% (4/7) |
| sales_accel_2q | 1.04 / 1.06 / 1.06 | +0.2% | +0.6% | +1.1% (5/7) |
| earnings_growth_25 | 1.16 / 1.08 / 0.91 | +0.3% | +0.5% (6/7) | +0.5% |
| earnings_accel | 1.06 / 1.10 / 0.83 | 0.0% | +0.5% | +0.5% |
| margin_expansion | 1.10 / 1.08 / 1.04 | +0.2% | +0.3% | +0.5% |
| **growth_accel_combo** | **1.32 / 1.40 / 1.14** | **+1.1% (5/7)** | **+1.2% (5/7)** | +0.5% (5/7) |
| sales_decel | 1.04 / 1.07 / 1.00 | −0.3% | +0.3% | +0.6% |

**Added to the candidate lists.** Excess with the factor minus without it:

| List | sales_growth_25 | sales_accel_2q | margin_expansion | growth_accel_combo | sales_decel |
|---|---|---|---|---|---|
| early momentum, Large | **+2.6% (5/7)** | +0.1% | +1.3% (5/7) | **+2.5% (5/7)** | −0.4% |
| early momentum, Mid | −0.0% | **+1.8% (6/7)** | +1.1% | −1.1% | −0.6% |
| early momentum, Small | −0.3% | +1.3% (5/7) | +1.2% | +0.8% | **−1.9% (better in 1/7)** |
| top-30 trend+riskadj120, Large | +1.7% (4/7) | −0.3% | +0.6% | +1.6% (2/7) | +0.9% |
| top-30 trend+composite, Small | −1.0% | +0.9% (5/7) | −0.6% | +1.5% (4/7) | −1.7% |

**Winners:** 61% of yearly winners with data had 25%+ sales growth at some checkpoint in January–June, against 30% of other stocks (2.0×). For growth_accel_combo it was 28% against 14% (2.0×). Earnings acceleration was no more common among winners (0.95×).

**Portfolio test** (in [selection_filters_2020_2026.md](selection_filters_2020_2026.md)), top 15, no gate:

| Tier | Variant | CAGR | Sharpe | Max DD | Years better than base |
|---|---|---|---|---|---|
| Large | trend+riskadj120+clean (base) | 20.1% | 0.85 | −30% | |
| Large | + prefer sales growth / combo | 18.2% | 0.76 | −33% | 3/7 |
| Large | + require sales growth ≥ 25% | 21.4% | 0.82 | −37% | 3/7 |
| Large | + prefer margin expansion / earnings growth | 15.6% | 0.70 | −33% | 3/7 |
| Mid | trend+riskadj120+clean (base) | 1.9% | 0.21 | −47% | |
| Mid | + require sales growth ≥ 25% | 4.5% | 0.30 | −41% | 5/7 |
| Small | trend+composite+prefer_turnaround (base) | 15.2% | 0.73 | −39% | |
| Small | + exclude sales_decel | 13.7% | 0.65 | −42% | 4/7 |
| Small | + prefer sales_accel_2q | 14.6% | 0.71 | −38% | 3/7 |
| Small | composite + prefer growth_accel_combo | 12.8% | 0.65 | −41% | 2/7 |

**Findings:**

1. **Growth level matters more than acceleration.** Revenue acceleration alone, in one quarter, and earnings acceleration add almost nothing against same-volatility peers. Strong sales growth (≥ 25%), and especially growth that is high and accelerating with growing earnings (growth_accel_combo), beat peers in 5–6 of 7 years.
2. **Fundamentals help sort the wide momentum list but not the ranked top 15.** Inside early momentum, Large names with strong sales growth or the combo did +2.5% better. Inside the ranked lists the gains shrink, and in the portfolio test no SEC rule improved the recommended Large or Small lists. Requiring growth adds a little return in Large caps at the cost of a deeper drawdown (−37%) and a lower Sharpe.
3. **Momentum already prices most of it.** The risk-adjusted momentum ranking already favours stocks whose growth shows in the price. The same happened with industry strength: a real signal across many names, no gain once the top 15 is picked.
4. **Mid caps:** requiring sales growth is the best Mid-cap rule so far (4.5%, better in 5 of 7 years), but it still trails simply owning the Mid universe (9.3%).
5. **Use:** fundamentals are a good way to read or trim the wide early-momentum list (keep strong-growth and accelerating names, drop small caps with sharply slowing sales). They are not an addition to the recommended top-15 rules.

**Caveats:**
- **Coverage:** 30–40% of stock-checkpoints have no SEC data, mostly foreign filers. A "require" rule therefore also drops most ADRs.
- **Restatements:** the first-filed value is used. Later restatements are ignored on purpose, to avoid look-ahead.
- **Net income is noisy:** it includes one-off items such as tax charges and impairments. Operating income or adjusted EPS might give cleaner earnings signals.

## Dilution, cash burn and gross profitability from SEC filings

Same SEC bulk data as the growth section, with five more fields, each taken as first filed:
- shares outstanding (cover page, else balance sheet)
- total assets
- cash
- operating cash flow (quarters derived from year-to-date totals)
- gross profit (else revenue minus cost of revenue)

| Factor | Definition |
|---|---|
| dilution_10 | shares outstanding up ≥ 10% from a year earlier |
| buyback_2 | shares outstanding down ≥ 2% |
| cash_burn | trailing-4-quarter operating cash flow below zero |
| low_runway | burning cash with under 4 quarters of cash at the current burn rate |
| gp_top30 | trailing gross profit / total assets in the top 30% of its checkpoint and tier |

- **Splits:** share counts are not split-adjusted. A one-year change above +80% or below −45% is treated as a likely split and left unscored, so a 3-for-2 split can still read as dilution.
- **Coverage:**
  - Share counts and cash flow are known for 57–77% of stock-checkpoints.
  - Gross profit for 35–45%, since banks and many service companies don't report it.

### Signal results (60-day excess vs volatility peers)

| Factor | Large | Mid | Small | Inside the early-momentum list |
|---|---|---|---|---|
| dilution_10 | −1.6% (1/7 yrs +) | −1.6% (0/7) | −1.0% (1/7) | Large −3.2%, Mid −1.5% |
| cash_burn | −1.5% (2/7) | −2.0% (1/7) | −1.4% (2/7) | Large −5.0%, Mid −3.0%, Small −2.1% |
| low_runway | −3.8% (2/7) | −3.0% (0/7) | −2.0% (1/7) | Large −5.1%, Mid −2.1%, Small +0.9% |
| buyback_2 | +1.0% (7/7) | +0.3% (4/7) | +0.6% (4/7) | Small +3.2% (5/7) |
| gp_top30 | +0.0% (5/7) | +0.6% (5/7) | +0.6% (6/7) | Mid +1.7% (6/7) |

- **Lottery tickets:** diluters and cash burners make up 2–3× their share of the top-10 yearly winners, but they underperform on average. Many lottery tickets, a few big wins.
- **Consistency:** this is the most consistent negative evidence in the study. Dilution is negative in 6–7 of 7 years in every tier.
- **Inside the Small top-30 composite list:**
  - dilution: −2.9%
  - low runway: −5.9%
  - buybacks: +2.4% (6/7)
  - high gross profitability: +1.9% (5/7)

## Suggested use (after the portfolio test)

The portfolio results are in [selection_filters_2020_2026.md](selection_filters_2020_2026.md#factor-rules-turnaround-faded-jumps-and-industry-groups).

- **Keep:** exclude faded jumps and heavy-volume drops from the Large list. This lifted it from 17.8% to 20.1% a year (Sharpe 0.78 → 0.85), better in 5 of 7 years.
- **Keep:** move turnaround names to the front of the Small composite list. This lifted it from 13.1% to 15.2% a year (Sharpe 0.66 → 0.73), though much of that came from 2020.
- **Don't use industry strength as a hard filter or ranking tilt in the Large list.** Although top-industry names beat peers in the signal test, requiring a top industry cut the Large list to 7.4% a year, and favouring leaders cut it to 12.9%. Dropping bottom-20% industries was neutral. Industry strength remains useful for reading the wide early-momentum list, not for picking the top 15.
- **Don't use:** listing age, or "had a big jump", as positive signals.
- **Keep, for Small:** exclude names whose share count rose 10%+ in a year, and move high gross-profit names to the front. The Small list rises from 15.2% to 18.6% a year (see the selection study).
- **SEC growth fundamentals:** use them to read or trim the wide early-momentum list (strong sales growth, growth_accel_combo, no sharp sales slowdown in small caps). They didn't improve the recommended top-15 lists.

## Caveats

- **Survivorship:** the universe is stocks listed today. This helps turnaround and young listings the most, since names that fell and never came back are missing. Turnaround's edge is likely smaller than shown.
- **Overlap and selection:** the 60-day windows overlap, so the number of truly independent samples is much smaller than the checkpoint count. Several factors and thresholds were tested on the same data.
- **Jumps are not earnings-dated:** the jump definition catches news days as well as earnings, and there are no earnings dates or surprise data.
