# Why the books trail QQQ before 2018 (2026-11-15)

**Question:** in the up years before 2018 the books rarely beat QQQ, while from 2018 they usually do. Is it the selection factor, something that drove QQQ in particular years, a technology theme, geopolitical events, something built into the strategy, or something else? Crash years (2008, 2009) are left for later.

**Short answer:** mostly two things, and re-tuning fixes neither.

1. **QQQ has a structural edge over any equal-weighted stock list, in every era.** It is about half Technology and is driven by a few mega-caps. The equal-weighted Large tier trails it by about 4 points a year before 2018 and about 6 points a year in 2020–2026. The books, being equal-weighted and light on mega-caps, start every year behind.
2. **The books' own edge depends on a fat right tail of Large stocks, and before 2018 that tail was thin.** The strategy makes its money from a few Large names that double or triple. In 2010–2019 only 0–5 Large stocks a year rose 100% or more; in 2020–2026, 10–28 a year (except 2022). The top-10 picks beat their own tier by about +2 points a year in the pre-2018 up years against about +25 in 2020–2026. With no big winners to ride, the books earn roughly the tier's return minus costs, and lose to QQQ by its structural edge.

On top of that, the books lose most of their ground in **sharp rallies after a pullback** (often after a macro shock), and the leadership of the time (commodities, China internet, consumer, biotech) sat **outside QQQ**. 2023 (QQQ +56%, Large top 10 +0.5%) shows the same failure after 2018 whenever a rally is led by mega-caps.

Scope: the up years 2006, 2007 and 2010–2017, with 2005 and 2018–2026 for comparison. 2005–2019 use the historical data (`wiki_dataset_guide.md`; 2005–2013 are survivor-biased best cases). 2020–2026 use the Alpaca data. Outputs and scripts: `top_performers_output/uptrend_formation_historical/qqq_gap/`.

## The gap, year by year (Large top 10)

`gap` = Large top 10 minus QQQ. `tier vs QQQ` = the equal-weighted Large tier minus QQQ. `picks vs tier` = a simplified top 10 by the Large score (trend filter, 180-day return / vol^0.5, re-picked every checkpoint, no costs) against the tier average, summed over the year's 26 two-week periods. `QQQ top 5` = share of the QQQ stand-in's return from its 5 biggest contributors. `book Tech` = share of the book's position-days in Technology (QQQ is about 50%). `mega-caps held` = average share of the year the book held QQQ's 10 biggest contributors. `doublers` = Large stocks up 100%+ that year.

| Year | QQQ | Large 10 | gap | tier vs QQQ | picks vs tier | QQQ top 5 | book Tech | mega-caps held | doublers |
|---|---|---|---|---|---|---|---|---|---|
| 2006 | 4.8 | -3.3 | -8.1 | +11.2 | -10.0 | 55% | 12% | 12% | 3 |
| 2007 | 18.8 | 26.1 | +7.3 | -5.6 | +32.1 | 87% | 16% | 10% | 16 |
| 2010 | 18.4 | 9.8 | -8.6 | -4.2 | +7.3 | 86% | 20% | 18% | 1 |
| 2011 | 1.9 | -24.0 | -25.9 | -6.2 | -28.6 | 215% | 5% | 9% | 0 |
| 2012 | 15.9 | 15.8 | -0.1 | -2.2 | +4.0 | 47% | 8% | 12% | 2 |
| 2013 | 32.4 | 26.7 | -5.7 | -5.4 | -1.3 | 42% | 16% | 10% | 5 |
| 2014 | 20.1 | 19.0 | -1.1 | -6.6 | +9.6 | 61% | 15% | 5% | 2 |
| 2015 | 9.8 | 8.1 | -1.7 | -12.9 | +20.8 | 97% | 14% | 16% | 3 |
| 2016 | 9.4 | 7.8 | -1.6 | +4.2 | -9.5 | 60% | 17% | 2% | 2 |
| 2017 | 31.5 | 7.0 | -24.5 | -11.2 | -3.0 | 53% | 27% | 8% | 2 |
| 2019 | 38.4 | 29.6 | -8.8 | -9.3 | +1.0 | 54% | 24% | 2% | 4 |
| **2006–2017 avg** | | | **-7.0** | **-3.9** | **+2.1** | | **15%** | **10%** | **4** |
| 2020–2026 avg (2022 incl.) | | | | about -6 | about +25 | | 31% | about 4%* | 16 |

\* 2020–2026 has no market caps in this analysis, so the mega-cap share there is the share of position-days in a fixed list (AAPL, MSFT, AMZN, GOOGL/GOOG, META, NVDA, TSLA, AVGO, NFLX and a few others).

The pre-2018 gap of -7.0 a year splits into about -3.9 from the tier against QQQ, +2.1 from the picks against the tier, and about -5 from the book itself (costs of ~160 trades a year, about 3 points; the breakout slots; rebalance timing) compared with the simplified top 10.

**The QQQ stand-in** (`benchmark.csv`): the 100 largest non-financial NASDAQ stocks in our universe, cap-weighted at the start of each year. It tracks QQQ within 0–2 points in most years and up to 8 in a few (2005, 2006, 2008, 2010, 2014), close enough to see what drove it.

## The hypotheses, one by one

### 1. Re-tune the selection factor? Mostly no

Large top 10 rerun with one setting changed at a time, 2005–2026 (`variants_all.csv`, `variants_summary.csv`). The base setting reproduces the committed and published books (2015 +8.1%; 2020–2026 +140, +17, -6, +1, +79, +26, +41%).

| Setting | vs QQQ, pre-2018 up years (avg/yr) | vs base, pre-2018 | Years beating QQQ (of 10) | CAGR 2018–2026 |
|---|---|---|---|---|
| base (180-day / vol^0.5, breakout slots, 25% trail, 10 names, 2 weeks) | -7.0 | 0 | 1 | 29.3% |
| no breakout slots | -5.0 | +2.0 | 4 | 30.2% |
| 20 names | -5.2 | +1.8 | 3 | 20.9% |
| rebalance every 8 weeks | -5.6 | +1.4 | 3 | 28.7% |
| 250-day lookback | -5.8 | +1.2 | 3 | 20.8% |
| 30 names | -5.8 | +1.2 | 3 | 15.2% |
| no trend filter | -6.2 | +0.8 | 2 | 29.6% |
| no stop | -6.4 | +0.6 | 3 | 29.6% |
| raw return (no vol scaling) | -6.4 | +0.6 | 3 | 29.5% |
| rebalance every 4 weeks | -6.9 | +0.1 | 3 | 30.0% |
| 120-day lookback | -7.3 | -0.3 | 3 | 19.8% |
| vol^1 | -7.7 | -0.7 | 2 | 24.4% |
| 15% trail | -8.0 | -1.0 | 2 | 26.1% |
| 60-day lookback | -8.1 | -1.1 | 1 | 14.9% |
| QQQ | 0 | +7.0 | – | 18.5% |

- The best change closes about 2 of the 7 points, and no setting beats QQQ in more than 4 of 10 years.
- The best setting changes every year (no slots in 2007 and 2015, 8-week rebalance in 2010, 250-day lookback in 2012 and 2014, no trend filter in 2016, 20 names in 2017). Picking one would be fitting to noise.
- What helps before 2018 (more names, longer lookbacks) costs 8–14 points of CAGR in 2018–2026. The rules are tuned to the years of big momentum winners, and that is the trade-off.
- **Dropping the breakout slots** is the one change that helps a little in both periods (+2.0 a year before, +0.9 points of CAGR after). Worth its own test across tiers.
- **The momentum factor itself did work in 2013–2015** (12-month top decile minus bottom decile of the Large tier: +25, +22, +36 points a year, `factor.csv`), but the top 10 by our score captured little of it in 2013. The problem is concentration in a few names in a market with no big winners, not momentum as such.

### 2. Something that drove QQQ in particular years? Yes: mega-cap Tech, every year

- Technology is about 50% of the stand-in in every year and contributes most of its return: 16.6 of 18.7 points in 2007, 16.2 of 34.5 in 2013, 9.6 of 14.6 in 2014, 19.7 of 30.9 in 2017 (`sectors.csv`).
- In narrow years, 5 stocks make most or all of QQQ's return (`qqq_top_contributors.csv`): 2007 87% (Google, Apple, Baidu, Microsoft, Intel), 2010 86% (Baidu, Apple, Oracle, Amazon), 2011 215% (Apple, Google, Intel; the rest of the stand-in lost money), 2015 97% (Amazon, Alphabet, Microsoft). Those are the years QQQ beats the equal-weighted tier by 4–13 points.
- In our Large tier the average Tech stock did no better than other sectors in those years. QQQ's edge came from a few names, weighted by size.
- The books held those names about 10% of the year before 2018, and a fixed list of mega-caps about 4% of position-days in 2020–2026: the score prefers fast, volatile movers, and a mega-cap rising 30–50% rarely ranks in the top 10.

### 3. A new technology or theme? Yes: the leaders sat outside QQQ before 2018

What the Large top 10 held (largest sectors by position-days) and its best trades:

| Years | Leadership the book rode | Best trades of the year |
|---|---|---|
| 2005–2008 | energy, materials, industrials (the commodity boom) | SWN +112%, Tenaris +68%, Mastercard +47%, Baidu +47% |
| 2010–2014 | consumer discretionary, China internet, biotech | Intuitive Surgical, Baidu, Monster, Alexion, Vipshop, Cheniere: +20% to +50% |
| 2015–2017 | gaming, chips, FANG (thin) | Activision +38%, Amazon +37%, NVIDIA +33% |
| 2020–2026 | cloud, EV, AI, chips, storage (Tech 23–41% of the book) | Zoom +155%, Tesla +133%, AppLovin +256%, Super Micro +157%, Robinhood +179%, SanDisk +175% |

Before 2018 the momentum leaders were mostly outside QQQ, and their best moves were +20% to +70%. From 2020 the leaders were Tech or Tech-adjacent, inside or alongside QQQ, and moved +100% to +250%. Right tail of the Large tier (`right_tail.csv`):

| | Large stocks up 100%+ | Large stocks up 50%+ | 99th-percentile Large return |
|---|---|---|---|
| 2010–2019 | 0–5 a year (0–1%) | 3–93 | +40% to +100% |
| 2020–2026 (ex 2022) | 10–28 a year (1.4–3.4%) | 48–125 | +100% to +237% |

### 4. Geopolitical and macro events? They are when the gap opens, and the reason is the strategy's design

Months in the 13 up years 2005–2007 and 2010–2019 (`monthly_gap.csv`):

| Kind of month | Months | Large top 10 vs QQQ (avg) | Total |
|---|---|---|---|
| Rebound (QQQ 7%+ below its high at the start, month > +3%) | 13 | -3.9 | **-50** |
| Strong month near the high (> +3%) | 42 | -0.8 | **-32** |
| Normal month | 80 | +0.3 | +23 |
| Down month (< -3%) | 21 | +0.6 | +14 |

The rebounds follow known shocks: Aug–Sep 2006 after the May–July commodity and emerging-market selloff; Sep 2010 (QQQ +13%) as QE2 was priced in after the flash crash and the euro-debt scare; Oct 2011 (+10%) after the US downgrade and the euro crisis; Oct 2015 (+11%) after China's devaluation and the Aug 24 flash crash; Jan 2019 (+9%) after the late-2018 selloff and the Fed pause. 2016 also had the Feb–Mar reversal (a momentum crash: the 12-month long-short lost 30 points that year) and the November election rotation into value and financials.

The mechanism is built in: after a pullback the trend filter and the 180-day score favour the names that held up, while the rebound is led by the beaten-down names and the mega-caps. The books hold up slightly better than QQQ in down months but capture much less of its up months. In 2020–2026 the same months read the other way (strong months +2.5 a month, rebounds +0.7, `monthly_gap_2020_2026.csv`), because the leaders the book held were the high-beta names leading the rallies.

### 5. Built into the strategy? Partly

- **Not the cause:** idle cash and stops. Up-year books are ~99% invested with 0–5 stop-outs a year; names dropped at a checkpoint do about as well as QQQ afterwards (±1%, `mechanics.csv`).
- **Equal weight, sector-blind:** the book is underweight Tech by 30–45 points and almost never holds the mega-caps, so it cannot keep up in a mega-cap-led rally (2017; and 2023 after 2018).
- **Churn:** about 160 trades a year for 10 slots (average hold about 3 weeks), roughly 3 points a year of costs at 10 bps a side.
- **Breakout slots:** cost 9 points in 2010 and 20 in 2007; about 2 a year on average before 2018.
- **Lag in V-shaped rebounds** (above).

### 6. Other factors

- **The rules were chosen on 2020–2026**, the years with the fattest right tail, so the earlier years are out of sample and the rules fit the later regime by construction.
- **Universe and survivorship:** before 2014 the universe is smaller (1,061–1,614 against 1,900–2,300) and missing every company that died; 2020–2026 (Alpaca) has only today's listed names, which flatters those years somewhat (against the survivor-free data, Mid moved 8–33 points in 2017–2019, Large a few).
- **Data quality found along the way:** a few Large-tier names have junk market caps (first SEC share counts back-filled before 2009 such as Frontier at 312 billion shares, Talend counts 1,000× too high, a few bad raw prices), which puts small and mid caps in the Large tier: 0–10 trades a year in Large top 10, worth -3 to +4 points (`cap_check.csv`, `cap_flagged.csv`). Not the cause of the gap, but worth fixing in `historical/shares.py`.

## Follow-up tests: the doubler switch (2026-11-15)

The ideas below were tested on the Large top-10 book's daily equity, 2005–2026 (`overlays.py`, `switch_sweep.py`, `mag7.py`, `topn_caps.py`). Every signal is measured at a checkpoint close and acted on the next day; each switch costs 0.1%.

**The rule (the "doubler switch").** Every 10 trading days, count the Large-tier names up 100%+ over the last 250 trading days and divide by the tier's size. If the share is **1.5% or more**, hold the Large book; otherwise hold the **alternative**: QQQ, or the **top 7**, the 7 largest US NASDAQ companies on the last close before the year, equal weight, reset each January. The book keeps running in the background; the switch only decides where the money sits. It flips about 2.5 times a year and holds the book about half the time. Use the share, not a count: the Alpaca Large tier (about 880 names in 2026) is two to three times the historical one (300–470).

| Strategy | Pre-2018 up years vs QQQ | CAGR 2005–17 | CAGR 2018–26 | CAGR 2005–26 | Years beat QQQ | Worst drawdown |
|---|---|---|---|---|---|---|
| QQQ | 0 | 11.1% | 18.5% | 14.1% | – | -49% |
| Large top 10 book | -7.0 | 0.6% | 29.3% | 11.5% | 7 | -56% |
| Top 7 alone | +2.1 | 13.8% | 23.8% | 17.8% | 13 | -49% |
| **Switch: book / QQQ** | -1.6 | 11.8% | 34.6% | **20.6%** | 11 | -51% |
| **Switch: book / top 7** | -0.5 | 13.4% | 38.2% | **23.0%** | 11 | -48% |
| 50% book / 50% QQQ | -3.5 | 6.1% | 24.5% | 13.2% | 8 | -51% |
| Rebound rule (QQQ 40 days after a 10% dip) | -4.1 | 6.2% | 16.4% | 10.3% | – | -60% |

- **The switch is robust to its threshold.** With QQQ as the alternative, any count from 3 to 15 names or share from 0.5% to 3% gives 18–21% a year. Picking the threshold on 2005–2017 alone gives 1.5%, which then earns 34.6% a year in 2018–2026. It is not fully out-of-sample: the idea itself came from this research.
- **Its gains come from avoiding the book's bad years:** 2009 (-28.7% → +33.3%), 2011 (-24.0% → -2.2%), 2022 (-5.5% → -24.2% with QQQ, but better than QQQ's -33%), 2023 (+0.5% → +60.2% with QQQ, +119% with the top 7). The pre-2018 up years still trail QQQ slightly with QQQ as the alternative; with the top 7 they roughly match it.
- **Fixed blends and the rebound rule don't work.** A fixed split only averages the two sides; the rebound rule helps 2006 and 2009 but costs too much in 2020 and 2026.
- **The hindsight Mag 7 is not a fair test.** AAPL, MSFT, GOOGL, AMZN, NVDA, META and TSLA held since 2005 make 31.1% a year, but the names were chosen in 2023 because they had won. The point-in-time top 7 is the fair version; it equals the Mag 7 in 2021–2025, and AVGO replaces TSLA in 2026.
- **Basket size:** top 3 / 5 / 7 / 10 make 16.9% / 16.9% / 17.8% / 15.8% a year alone, and 21.8% / 21.4% / 23.0% / 22.8% as the switch's alternative. Seven is the best balance, with ten close behind; fewer names only add drawdown (top 3: -57%). The top 5 missed NVDA and META in 2023–2024.
- **Choice:** the top 7 earns more; QQQ is a single ticker and easier to run. Both are kept as options.
- **Risks:** seven names are concentrated (2022: -47% vs QQQ -33%); 2005–2026 favoured mega-caps, and 2000–2002, when the largest NASDAQ names fell 60–80%, is not in the data; 2026 so far has the top 7 at +5.8% vs QQQ +11.3%. The top-7 lists before 2020 come from the QQQ stand-in with ADRs and known bad caps removed; listings carry only today's exchange, so movers are patched by hand (Oracle on NASDAQ until 2013, Mondelez from 2013, plus the NYSE-to-NASDAQ moves in `benchmark.py`). Other moves between the two exchanges may still be missing. 2020–2026 caps use yfinance closes with splits undone and the SEC share counts in `market_data/top_performers/shares.json`; gaps for NVDA (2021–2023) and META (before mid-2022) were filled from the nearest stored count.
- **Paper tracking:** the main repo's `research/paper_lists.py` prints the doubler share and the switch's side at each checkpoint and lists the year's top 7 as `large_switch_top7` (status "hold" when the switch is on the top 7, "off" when on the book). `TOP7_BY_YEAR` must be refreshed each January. On 2026-11-03 the share was 2.4% (21 of 877), down from 5.5% in August, so the switch is still on the book. Paper tracking uses the top-15 Large list, while this test used the top 10.

## Down years (2008, 2018, 2022): the market cash rule (2026-11-15 / 16)

**Question:** were there warning signals before the big drops, and does moving to cash, or shorting QQQ, pay when they fire? Tested on QQQ alone and on the doubler switch (book / QQQ, book / top 7), every year 2005–2026, so the cost of false alarms in up years counts. Signals are taken at the close and acted on the next day; cash earns the 13-week T-bill; a short pays 0.5% a year to borrow; each switch costs 0.1%. Scripts: `downside.py`, `dist_days.py`, `dist_reentry.py`, `dist_rearm.py`, `ftd.py`, `dist_rearm_smooth.py`, `min_stay_sweep.py`.

**Default rule (since 2026-11-16, `research/cash_rule.py` on the main branch, printed by `exit_watch` daily and `paper_lists`):**

1. **Distribution day:** QQQ closes up 0.2% or less (flat or down) on volume above its prior 20-day average and above the day before.
2. **Exit:** 6+ distribution days in the last 25 sessions (counted only since the last re-entry) with QQQ closing below both its 50- and 200-day averages.
3. **Re-entry:** a close back above the 50-day.
4. **Re-exit:** after an exit, any later close below the 50-day goes back to cash, no new distribution days needed.
5. **Minimum stay:** no re-exit or re-entry within 10 sessions of the previous switch (the first exit is not delayed).
6. **Disarm:** once QQQ is above both averages with the 50-day above the 200-day, re-exits stop until the next exit.
7. In cash, hold T-bills / a money-market fund, not a short.

| Doubler switch with QQQ, 2005–2026 | CAGR | Worst drawdown | 2008 | 2018 | 2022 | Cash-rule switches a year |
|---|---|---|---|---|---|---|
| No cash rule | 20.6% | -55% | -39.9 | -5.9 | -24.2 | – |
| Previous rule: cash while QQQ < 50d and < 200d | 20.0% | -26% | +9.0 | -10.0 | -15.1 | 6.6 |
| **Default rule** | **21.8%** | **-23%** | -2.3 | +3.6 | -9.7 | 2.9 |
| Default rule, switch with top 7 | 23.8% | -23% | -4.1 | +3.3 | -9.4 | 2.9 |

QQQ alone: 14.1% / -54% with no rule, 12.1% / -25% with the previous rule, 14.5% / -21% with the default rule. The default rule was the best of about 50 variants on the same 22 years, so part of its edge over the previous rule may be luck; expect about 21%. Minimum stays of 0–12 days all give 21.0–21.8%; at 0.3% a switch every variant loses 0.6–0.9 points a year and the order holds.

On 2026-11-05 the rule moved to cash (7 distribution days, QQQ 647 below its 50-day 722 and 200-day 680); on 2026-11-13 it was still in cash, and so was the previous rule.

**What was found on the way:**

- **Warning signals.** VIX over 25, an inverted 10y–3m curve and high-yield credit (HYG/LQD) under its 100-day average fired 2–3 months before the 2008 peak, and credit and VIX months before the 2022 peak, but they also fire often in normal markets: credit is "on" 36% of all days and cuts QQQ to 4% a year as a cash rule; the curve warned only in 2008, 15 months early. Trend signals (QQQ below its 50- and 200-day) fire about 10% off the peak and each time a much larger fall followed (-47%, -15%, -28%).
- **Cash beats shorting.** Shorting QQQ on the 50/200 signal makes +50% in 2008 but costs 12–17 points in 2010, 2011 and 2019 (16.5% a year, -48% drawdown, against 20.0% / -26% in cash). Every signal did worse short than in cash.
- **Faster average exits** (QQQ below its 20- and 200-day; 20-day below a falling 50-day) fire on the same days in the crashes but whipsaw back in during bear-market rallies: 2008 and 2018 get worse and none beats the 50/200 rule.
- **Distribution days with a capitulation re-entry** (a worst-2% day on 1.5x volume, then +2% and +1% days on rising volume): as first specified (near-flat days only) it never fires; with flat-or-down days it exits about once a year in sensible places but the re-entry is too rare: in cash 85% of the time (2012-04 to 2015-08, 2016-09 to 2018-10, 2022-09 to 2024-05), 2.1% a year.
- **O'Neil follow-through-day re-entry** (day 4–7 or 4–10 of a rally attempt, +1.25% or +1.7% on rising volume, with or without a failed-follow-through exit): follow-through days come in bear-market rallies (2008-01-31, 2008-06-19, 2008-11-04; 2022-03-02, 2022-06-24), so the best version is 19.6% / -38%. It helps only V-shaped bottoms (2018-11, 2019-01, 2020-04).
- **Distribution exit + 50-day re-entry:** catches 2018 (exit 2018-10-05 on 11 distribution days) and early 2020, but about 4 exits a year in normal pullbacks and a bad 2008: 18.4%. Requiring QQQ also below its 200-day cuts the exits to 29–33 in 22 years; adding the re-exit and the uptrend disarm gives 21.4% / -24%.
- **Damping the whipsaw around the 50-day:** bands of 1–3%, 2–3 confirming closes, weekly or checkpoint-only checks and a falling-50-day condition all cut trades but cost return and protection (they delay the re-exit in fast drops and the re-entry in V-shaped recoveries). Only a minimum stay after each switch helps: 10 days cuts switches from 3.8 to 2.9 a year at 21.8% / -23%.
- **2018 in detail:** QQQ peaked 2018-08-29 (177.29) and bottomed 2018-12-24 (136.87, -23%). The default rule went to cash once (2018-10-11, 161.30) and came back 2019-01-15 (154.88); the previous rule switched 9 times between October and January, each time buying back higher. Over 2018–2019 together: no rule +30.2%, previous rule +15.3%, default +26.5%; a quick drop and fast recovery is the case where doing nothing still wins.

**Live rule set:** the doubler switch (book vs QQQ or the top 7) plus this cash rule. Risks: tuned on one 22-year history; 2000–2002 is not in the data; slippage on the 2–4 switches a year; quick crashes followed by fast rebounds (2019, 2023) cost return.

## What this suggested testing next (original list)

Items 1, 3 and 4 are covered by the follow-up above.

1. **A core in QQQ plus a momentum satellite**, or a switch: hold QQQ when the Large tier's right tail is thin (e.g. few names up 50%+ over 6 months) and the momentum book when it is fat. The doubler count is known only afterwards, so the test needs a signal measured at the checkpoint.
2. **Drop the breakout slots** across tiers (the one setting that helps in both periods).
3. **A mega-cap allowance:** let the largest names (or a cap-weighted sleeve) into the Large book so a mega-cap-led rally is not missed entirely.
4. **A rebound rule** after a 7%+ QQQ pullback (hold the index for a few weeks), tested against the 2009, 2010, 2011, 2015 and 2019 rebounds and against 2020–2026.
5. **Fix the junk market caps** and rerun the tiers.

## Corrections (2026-11-16)

A code review found the QQQ stand-in used today's exchange for every year, so Oracle (NASDAQ until July 2013) was missing and Mondelez (NYSE as Kraft until October 2012) was included in 2005-2012. With both fixed and everything rerun, the stand-in tracks QQQ slightly better (mean gap 3.0 points a year, was 3.2) and Oracle joins the 2007-2013 top 7. The top-7 results move by 0.1-0.4 points a year and the QQQ-based results not at all; the figures above are the corrected ones. `dist_days_*.csv` (the first, near-flat distribution-day test) was not rerun; its top-7 rows predate this fix.

## Files

`top_performers_output/uptrend_formation_historical/qqq_gap/`: `focus_years.csv` (the table above), `benchmark.csv`, `qqq_top_contributors.csv`, `sectors.csv`, `factor.csv`, `variants_<year>.csv`, `variants_all.csv`, `variants_summary.csv`, `mechanics.csv`, `book_sectors.csv`, `megacap_held.csv`, `monthly_gap.csv`, `monthly_gap_2020_2026.csv`, `right_tail.csv`, `cap_check.csv`, `cap_flagged.csv`; follow-up: `overlays_*.csv`, `switch_sweep*.csv`, `doubler_signal.csv`, `mag7_*.csv`, `topn_caps_*.csv`, `nasdaq_caps_2020_2026.csv`; down years: `downside_*.csv`, `dist_days_*.csv`, `dist_days_v2_*.csv`, `dist_reentry_*.csv`, `dist_rearm_*.csv`, `ftd_*.csv`, `dist_rearm_smooth_*.csv`, `min_stay_sweep.csv`. Scripts in `scripts/` were run from the session scratchpad (`variants.py` imports the top_n_by_year `top_n_books.py`; Alpaca years with `VARIANT_PANEL_DIR` set to the Alpaca panels and SEC CIKs from the local ticker file).
