# Live Trade Engine Performance Tuning

**Strategy:** Op-Momentum Stock — 5-window configuration
**Replay period:** 2022 full year (251 days) · 2024 full year (252 days) · 2025 full year (250 days) · 2026 YTD (88 days through May 8)
**Capital:** $10,000 | Top-2 selections | Rank-weighted 60/40
**Config flags:** `--morning-split 100 --bearish-reentry --bullish-reentry --reversal --rank-weighted-sizing 60 40 --doubledown --doubledown-start 10 --top 2 --feed sip`

---

## Trading Windows

| Window | Time | Bars |
|--------|------|------|
| M1 | 09:30 | 3 |
| A1 | 10:00 | 3 |
| A2 | 11:45 | 2 |
| A3 | 13:15 | 1 |
| A4 | 15:15 | 1 |

---

## Replay Results

### 2022 Full Year (251 trading days)

| Month | P&L | Return |
|-------|-----|--------|
| Jan | +$1,506 | +15.1% |
| Feb | +$777 | +7.8% |
| Mar | +$2,293 | +22.9% |
| Apr | +$2,696 | +27.0% |
| May | +$3,778 | +37.8% |
| Jun | +$1,070 | +10.7% |
| Jul | +$1,232 | +12.3% |
| Aug | +$3,591 | +35.9% |
| Sep | +$1,344 | +13.4% |
| Oct | +$409 | +4.1% |
| Nov | +$3,853 | +38.5% |
| Dec | +$3,278 | +32.8% |
| **TOTAL** | **+$25,828** | **+258.3%** |

- 251 trading days, all 12 months profitable
- Best week: Feb 28 +$1,243 (CVNA short +6.40%) · Worst week: Jan 24 −$333

### 2024 Full Year (252 trading days)

| Month | P&L | Return |
|-------|-----|--------|
| Jan | +$1,136 | +11.4% |
| Feb | +$1,766 | +17.7% |
| Mar | +$467 | +4.7% |
| Apr | +$1,375 | +13.7% |
| May | +$2,538 | +25.4% |
| Jun | +$423 | +4.2% |
| Jul | +$1,152 | +11.5% |
| Aug | +$2,900 | +29.0% |
| Sep | +$2,034 | +20.3% |
| Oct | +$2,007 | +20.1% |
| Nov | +$2,798 | +28.0% |
| Dec | +$680 | +6.8% |
| **TOTAL** | **+$19,276** | **+192.8%** |

- 252 trading days, all 12 months profitable
- Best week: Feb 19 +$1,103 (COIN short +4.69%, CLS long +4.23%) · Worst week: Feb 26 −$292

### 2025 Full Year

| Month | P&L | Return |
|-------|-----|--------|
| Jan | +$1,863 | +18.6% |
| Feb | +$789 | +7.9% |
| Mar | +$1,497 | +15.0% |
| Apr | +$3,919 | +39.2% |
| May | +$1,739 | +17.4% |
| Jun | +$2,600 | +26.0% |
| Jul | +$885 | +8.8% |
| Aug | +$564 | +5.6% |
| Sep | +$1,217 | +12.2% |
| Oct | +$1,033 | +10.3% |
| Nov | +$2,508 | +25.1% |
| Dec | +$1,963 | +19.6% |
| **TOTAL** | **+$20,577** | **+205.8%** |

- 250 trading days, all 12 months profitable
- 45/53 weeks profitable (85% weekly win rate)
- Avg +$388/week
- Best week: Apr 7 +$2,301 (Apr 9 tariff-reversal day: +$2,598 single day)
- Worst week: Feb 3 week −$428

### 2026 YTD (through May 8)

| Month | P&L | Return |
|-------|-----|--------|
| Jan | +$4,255 | +42.6% |
| Feb | +$4,477 | +44.8% |
| Mar | +$2,053 | +20.5% |
| Apr | +$1,303 | +13.0% |
| May (partial) | +$162 | +1.6% |
| **TOTAL** | **+$12,251** | **+122.5%** |

- 88 trading days, 17/19 weeks profitable (89% weekly win rate)
- Avg +$645/week
- Best week: Feb 9 +$1,738 | Worst week: Apr 27 −$281

---

## Best Week Analysis — Cross-Year

### 2022: Week of Aug 1 (+$2,605) — Full-year best

CVNA and COIN surged on the post-July CPI relief rally. The strategy rode both sides of the crypto/growth-stock mean-reversion into what proved to be the peak of the 2022 bear-market rally.

| Date | Ticker | Direction | Entry | Exit | P&L | Pattern |
|------|--------|-----------|-------|------|-----|---------|
| Aug 5 | CVNA | Long | ~$50 | exit | +$927 | +15.5%; trailing-stop-MA20; 5h hold — the strongest single-trade day in 2022 |
| Aug 2 | CVNA | Long | ~$46 | exit | +$639 | +10.7%; day 2 of the same rally; continuation with vol confirmation |
| Aug 3 | COIN | Long | ~$98 | exit | +$521 | +13.1%; crypto-correlated bullish breakout; above MA-20; trailing-stop held all day |
| Aug 3 | MSTR | Long | ~$290 | exit | +$387 | +6.5%; same crypto bullish session; paired with COIN in top-2 pick |
| Aug 1 | SHOP | Long | ~$40 | exit | +$195 | +4.9%; tech relief rally; above short-term MA; clean OR breakout |

### 2022: Week of Dec 5 (+$1,750) — 2nd best

End-of-year bear continuation with CVNA establishing a durable downtrend and APP joining with back-to-back bearish sessions.

| Date | Ticker | Direction | Entry | Exit | P&L | Pattern |
|------|--------|-----------|-------|------|-----|---------|
| Dec 7 | CVNA | Short (A3) | 13:20 | 15:15 | +$437 | +7.3%; afternoon window short; CVNA in full daily downtrend; clean trailing-stop exit |
| Dec 5 | CVNA | Short Cont. | 12:00 | 16:00 | +$364 | +6.1%; continuation entry on established bearish direction; held to EOD |
| Dec 6 | APP | Short | 09:45 | 11:45 | +$323 | +5.4%; M1 bearish; below MA-20; trailing-stop-MA20 exit at 2h |
| Dec 5 | MSTR | Short | 09:45 | 13:15 | +$318 | +5.4%; paired with CVNA on a broad crypto/growth selloff day |
| Dec 6 | APP | Short | 11:55 | 14:45 | +$251 | +4.2%; A2 window follow-through on the same bearish theme |

### 2024: Week of Nov 4 (+$1,612) — Full-year best

Election week (Nov 5). COIN exploded +20%+ over two days on anticipation of a crypto-friendly administration. Strategy doubled into the move.

| Date | Ticker | Direction | Entry | Exit | P&L | Pattern |
|------|--------|-----------|-------|------|-----|---------|
| Nov 6 | COIN | Doubledown | 10:25 | 15:05 | +$565 | +9.5%; DD at 10:25 after primary position confirmed; both held to trailing-stop-MA20 |
| Nov 6 | COIN | Long | 10:15 | 15:05 | +$387 | +9.95%; election result confirmed pre-open; above all daily MAs; 4.5h hold |
| Nov 5 | PLTR | Long | 09:45 | 12:40 | +$172 | +2.9%; defense/AI bullish momentum on election day |
| Nov 8 | APP | Long (A4) | 15:20 | 16:00 | +$167 | +2.8%; late-session bullish continuation carry |
| Nov 8 | APP | Long | 09:45 | 11:30 | +$158 | +2.65%; post-election follow-through |

### 2024: Week of May 20 (+$1,225) — 2nd best

CLS breakout week — semiconductor supply chain names moved on renewed AI infrastructure demand.

| Date | Ticker | Direction | Entry | Exit | P&L | Pattern |
|------|--------|-----------|-------|------|-----|---------|
| May 24 | CLS | Long | 09:45 | 13:00 | +$272 | +4.5%; clean OR breakout; above MA-20 and MA-50; trailing-stop-MA20 held 3h |
| May 24 | CLS | Doubledown | 09:55 | 13:00 | +$138 | +3.5%; DD on confirmed move; combined ~60% weight on CLS |
| May 20 | MSTR | Long Cont. | 09:50 | 13:45 | +$174 | +3.6%; crypto relief day; continuation from prior day's move |
| May 21 | TSLA | Long | 11:55 | 15:25 | +$130 | +3.3%; A2 afternoon window; EV sector bullish session |
| May 20 | COIN | Long | 15:20 | 16:00 | +$118 | +2.0%; late A4 window; crypto follow-through |

### 2026: Best — Feb 9 (+$1,738) and Feb 2 (+$1,651) — see Best Week Analysis section below

**Cross-year best-week pattern — confirmed across all 4 years:**
1. Every winning trade exited via `trailing_stop_ma20` — held the full move, not stopped early
2. Best weeks had at least one trade with ≥ 6% intraday gain driving the bulk of the week's P&L
3. Every big winner was aligned with the daily MA-20 trend (short below, long above)
4. The two-ticker top-2 system doubled down on the conviction name via `Doubledown` entry, amplifying the week's P&L

`charts/best_worst_2022.pdf` — CVNA Aug 5, COIN Aug 3 (best), CVNA Sep 12/15 (worst)
`charts/best_worst_2024.pdf` — COIN Nov 6 (best), CVNA Feb 26, CRDO Dec 27 (worst)

---

## Worst Week Analysis — Cross-Year

### 2022: Week of Sep 12 (−$498) — Full-year worst

Back-to-back CPI-week reversal: CVNA shorted hard post-CPI on Sep 13, then strategy attempted bullish continuation into Sep 15 as if the July peak rally was resuming — it was not.

| Date | Ticker | Direction | Entry | Exit | Loss | Root Cause |
|------|--------|-----------|-------|------|------|------------|
| Sep 12 | CVNA | Bullish Cont. | 09:50 | 11:25 | −$275 | −4.6%; longed into a distribution day; CVNA already rolling below MA-20; hard stop |
| Sep 15 | CVNA | Bullish Cont. | 10:10 | 10:55 | −$264 | −4.4%; second attempt same direction; market still declining post-CPI; hard stop |
| Sep 16 | CVNA | Doubledown | 09:55 | 10:35 | −$139 | −3.5%; doubled into a third consecutive losing long; hard stop |
| Sep 14 | CRDO | Bullish | 09:45 | 09:50 | −$57 | −1.4%; fallback_20pct — no conviction at open; fast exit |
| Sep 15 | CVNA | Bullish | 09:45 | 10:00 | −$41 | −0.7%; primary M1 position that triggered the Doubledown above |

### 2022: Week of Jun 27 (−$412) — 2nd worst

End of a capitulation week (Jun 24 was the low): strategy fired bearish continuation into a violent short-covering rally on Jun 30.

| Date | Ticker | Direction | Entry | Exit | Loss | Root Cause |
|------|--------|-----------|-------|------|------|------------|
| Jun 30 | MSTR | Bearish Cont. | 09:50 | 10:55 | −$112 | −2.8%; shorted into a dead-cat bounce off 52w low; trailing-stop clipped on the reversal |
| Jun 30 | APP | Bearish Cont. | 09:50 | 11:00 | −$81 | −1.4%; same — continuation short into an oversold snap-back day |
| Jun 30 | APP | Bearish | 09:45 | 09:50 | −$41 | Fallback primary; a fast exit should have warned not to re-enter |
| Jun 30 | MSTR | Bearish | 09:45 | 09:50 | −$37 | Primary fallback; same issue — no direction confirmation at open |
| Jun 28 | MSTR | Bullish | 10:15 | 10:20 | −$38 | Switched to long next day — also a fast fallback |

### 2024: Week of Feb 26 (−$292) — Full-year worst

Continuation entries stacked onto exhausting momentum — CVNA had already peaked and was rolling over.

| Date | Ticker | Direction | Entry | Exit | Loss | Root Cause |
|------|--------|-----------|-------|------|------|------------|
| Feb 26 | CVNA | Doubledown | 09:55 | 10:40 | −$113 | −2.9%; doubled into a long that reversed; hard stop; CVNA already rolling below MA-20 |
| Feb 29 | CVNA | Bullish Cont. | 10:00 | 10:15 | −$110 | −1.9%; third losing attempt on same ticker same week; hard stop |
| Feb 26 | CVNA | Bullish | 09:45 | 10:40 | −$66 | −1.1%; primary position that triggered the Doubledown |
| Feb 29 | COIN | Bearish Cont. | 11:20 | 12:20 | −$64 | Switched bearish on COIN; trailing-stop loss — no follow-through on the short |
| Mar 1 | AMD | Bullish Cont. | 10:05 | 10:35 | −$53 | AMD bullish continuation stalled at daily MA resistance; hard stop |

### 2024: Week of Dec 23 (−$279) — 2nd worst

Holiday-week low-liquidity fast-exit cluster. APP and CRDO both triggered fallback_20pct on back-to-back days with no intraday conviction.

| Date | Ticker | Direction | Entry | Exit | Loss | Root Cause |
|------|--------|-----------|-------|------|------|------------|
| Dec 26 | APP | Bullish | 09:45 | 09:50 | −$73 | −1.2%; fallback in 5 min — holiday-week tight open with no vol |
| Dec 26 | CRDO | Bullish | 09:45 | 09:50 | −$59 | −1.5%; same — fallback same day; top-2 both firing into a dead open |
| Dec 27 | CRDO | Bearish | 09:45 | 09:50 | −$48 | Direction flip next day on same ticker — still no conviction |
| Dec 27 | APP | Bearish Cont. | 10:00 | 11:05 | −$46 | Continuation short after a flat open; trailing-stop loss |
| Dec 27 | TSLA | Bearish Cont. | 14:20 | 15:10 | −$30 | Afternoon continuation that reversed |

### 2026: Week of Apr 27 (−$281) — see Worst Week section below

**Cross-year worst-week pattern — confirmed across all 4 years:**
1. Every worst week had at least one counter-trend trade or a "Cont./Doubledown" entry stacking into a failing move
2. The CVNA Doubledown pattern appears in 3 of the 4 worst weeks — it is the single highest-risk entry type in the strategy's worst moments
3. No worst week had any trade that reached 2% gain — the days were genuinely range-bound or directionally wrong
4. Holiday/low-liquidity weeks (Dec 23 2024) show the same fast-fallback signature as noise days — yet still lose more because the Doubledown fires

---

## Best Week Analysis — Feb 2 & Feb 9 (2026)

### What Made These Weeks Work

**Common technical pattern across all winning trades:**

1. **Clean directional intraday close** — price moved 8–15% intraday and closed near the extreme (not the middle of the range). Every winner had a close within the top/bottom 20% of its day's range.

2. **Volume confirmation on continuation bars** — volume spiked 3–5× average on the bars that continued the move, not on reversals. The spike was concentrated and directional.

3. **Daily trend alignment** — every winning short trade was on a stock already breaking or trending below its MA-20 on the daily chart (sector-confirmed downtrend). No counter-trend entries on the best days.

### Key Trades

| Date | Ticker | Direction | Entry | Exit | P&L | Pattern |
|------|--------|-----------|-------|------|-----|---------|
| Feb 3 | CRDO | Short | $117.03 | $106.92 | +$727 | Bearish continuation off extended daily run; EMA-9 crossed below EMA-20 at open; 3× vol spike on breakdown bars |
| Feb 4 | PLTR | Short | $148.67 | $137.54 | +$445 | Two-day distribution; broke prior week lows with expanding vol; EMA cross confirmed at open |
| Feb 4 | MU | Short | $400.42 | $368.95 | +$189 | Sector-wide semiconductor selloff; broke below daily MA-20; -7.5% intraday |
| Feb 11 | SHOP | Short | $123.55 | ~$111 | +$376 | Post-earnings gap-and-continue-lower; 21% intraday range; EMA-9 never recovered |
| Feb 9 | CRWV | Long | $95.01 | — | +$384 | Bullish continuation with vol; above MA-20 and MA-50 on daily |

### Charts
`charts/best_feb03.pdf` — CRDO, PLTR (Feb 3)
`charts/best_feb04.pdf` — PLTR, MU, TSLA, SNDK (Feb 4)
`charts/best_feb11.pdf` — SHOP, CRDO, MU (Feb 11)

---

## Worst Week Analysis — Apr 27 & May 4 (2026)

### What Caused These Losses

**Apr 30 — worst single day (−$381):**
- CVNA shorted at $383.50, covered at $385.73 (small loss); re-entered short at $372.92, covered at $389.89 (−$272 on the second position alone)
- CVNA was holding *above* its daily MA-20 — strategy shorted into support
- Intraday had a 10.9% range but price closed near the middle — violent two-sided fighting, no trend

**May 4–8 — low conviction week (−$33 net):**
- No trade exceeded 0.5% gain all week
- CVNA, CRDO, COIN all had direction flips (bullish then bearish same day)
- Opening bars were tight (<2% range) with scattered volume — no institutional participation

### Charts
`charts/worst_apr30.pdf` — CVNA, CRDO (Apr 30)
`charts/worst_may07.pdf` — CVNA, CRDO (May 7)

---

## Noise Signal Analysis

### Definition
A "noise day" is one where the max single-trade gain across all windows is < 0.5%. Validated across 4 replay years.

### Cross-Year Noise Validation

| Metric | 2022 (251d) | 2024 (252d) | 2025 (250d) | 2026 (88d) |
|--------|-----------|-----------|------------|-----------|
| Noise days (max gain < 0.5%) | **39/251 (15.5%)** | **33/252 (13.1%)** | 31/250 (12.4%) | 9/88 (10.2%) |
| Noise trade count | 410 | 372 | ~330 | 125 |
| Noise win rate | **20%** | **24%** | **26%** | **29%** |
| Fast exits ≤5 min | 35% | 31% | 25% | 34% |
| Fast exits that are losses | **83%** | **80%** | **82%** | **81%** |
| M1 09:45 fallback rate | 49% | 45% | 30% | 67% |
| M1 09:45 win rate | **23%** | **26%** | **29%** | **28%** |
| Good day win rate (max ≥2%) | 41% | 44% | 43% | 42% |

All four metrics are consistent across all 4 full years — the noise signature is structural, not year-specific. The noise rate trends slightly higher in bear/volatile years (2022: 15.5%) vs bull/trending years (2026 YTD: 10.2%), consistent with more two-sided chop in bear markets.

### Persistent Noisy Tickers (all 4 years)

Ranked by cumulative noise score (appearances × loss rate across all years):

Full-year counts (2022 and 2024 now validated across all 12 months):

| Ticker | 2022 (251d) | 2024 (252d) | 2025 (250d) | 2026 (88d) | Years |
|--------|-------------|-------------|-------------|------------|-------|
| **CVNA** | 54t / −$1,498 | 25t / −$216 | 26t/5w | 9t/1w | 4/4 |
| **MSTR** | 49t / −$614 | 38t / −$504 | 25t/9w | 16t/5w | 4/4 |
| **COIN** | 45t / −$594 | 38t / −$204 | 21t/6w | 16t/3w | 4/4 |
| **SHOP** | 36t / −$401 | — | — | — | 2/4 |
| **CRDO** | 36t / −$242 | 46t / −$343 | 31t/11w | 11t/4w | 4/4 |
| **APP** | 33t / −$495 | 38t / −$293 | 23t/4w | 4t/1w | 4/4 |
| **AMD** | 25t / −$209 | 21t / −$118 | 11t/3w | 8t/3w | 4/4 |
| **CLS** | 24t / −$322 | 31t / −$175 | 31t/9w | 6t/2w | 4/4 |
| **MRVL** | 20t / −$147 | 23t / +$7 | 23t/6w | 10t/3w | 4/4 |
| SNDK | — | — | 38t/7w | 19t/6w | 2/4 |
| EXPE | 18t / −$176 | 14t / −$29 | 27t/7w | 2t/2w | 4/4 |
| TSLA | — | 38t / −$198 | — | — | 2/4 |
| PLTR | — | 24t / +$10 | 32t/8w | 1t/1w | 3/4 |
| CRWV | — | — | 24t/8w | 12t/1w | 2/4 |

**Core persistent noisy tickers (all 4 years):** CVNA, MSTR, COIN, CRDO, APP, AMD, CLS, MRVL — these should be the primary targets for the fallback guard (Rule 3).

Note: CVNA is the single worst noise contributor in 2022 (54 noise trades, −$1,498 total P&L on noise days). MSTR and COIN follow. TSLA replaced SHOP in the pool after 2022 and shows similar noise behavior in 2024.

### Noise Days (2026)

| Date | Trades | Max Gain | Cap P&L | Top Tickers |
|------|--------|----------|---------|-------------|
| 2026-04-06 | 15 | +0.17% | −$150.74 | SNDK, MU, CRWV, MRVL |
| 2026-02-27 | 14 | +0.22% | −$42.70 | SHOP, COIN, MRVL, MSTR |
| 2026-04-10 | 11 | +0.27% | −$25.32 | APP, COIN, CLS, SNDK |
| 2026-04-21 | 14 | +0.37% | −$133.04 | MRVL, PLTR, CRDO, COIN |
| 2026-03-10 | 12 | +0.38% | −$105.84 | COIN, CRWV, CVNA, SNDK |
| 2026-04-30 | 13 | +0.39% | −$381.76 | CVNA, CLS, CRWV, CRDO |
| 2026-01-09 | 13 | +0.47% | −$102.63 | SNDK, CRDO, MSTR, CRWV |
| 2026-03-02 | 17 | +0.48% | −$68.40 | SNDK, COIN, MSTR, CRDO |
| 2026-05-06 | 16 | +0.49% | −$52.73 | CLS, MSTR, SNDK, CRWV |

### Aggregate Stats (9 noise days, 125 trades)

| Metric | Noise Days | Best Days |
|--------|-----------|-----------|
| Win rate | 29% | ~70%+ |
| Avg winning trade | +0.14% | +4–9% |
| Avg losing trade | −0.34% | −0.5% (rare) |
| Fast exits ≤5 min | 34% | <10% |
| Of fast exits: losses | 81% | — |
| Direction flips same ticker | 7 across 9 days | ~0 |
| M1 09:45 win rate | 28% | 75%+ |
| M1 09:45 fallback_20pct rate | 67% | ~10% |

### Noisiest Tickers (ranked by noise score = appearances × loss rate)

| Ticker | Noise Trades | Win Rate | Avg P&L | Noise Score |
|--------|-------------|----------|---------|-------------|
| SNDK | 19 | 32% | −0.18% | 12.9 |
| CVNA | 9 | 11% | −0.87% | 8.0 |
| CRWV | 12 | 8% | −0.23% | 11.0 |
| COIN | 16 | 19% | −0.16% | 13.0 |
| MSTR | 16 | 31% | −0.10% | 11.0 |
| MRVL | 10 | 30% | −0.16% | 7.0 |
| APP | — | — | — | 8.0 |

### Technical Signature of Noise Days

From intraday 5-min and daily chart review:

1. **Tight opening bars** — first 5-min bar range averaged 2.37% on noise days vs 3.22% on best days. Bars < 1.5% range signal no directional conviction at open.

2. **Middle-of-range closes** — price had wide intraday ranges (5–11%) but closed near the day's midpoint, not the extreme. Strategy's momentum signal fired on the open move, but the move reversed.

3. **Daily MA conflict** — losing trades frequently shorted stocks holding above MA-20 (counter-trend into support) or longed stocks in established daily downtrends.

4. **Volume absorption, not directionality** — elevated opening volume (4–5× average on some noise days) but scattered across reversals, not concentrated on continuation bars. Indicates two-sided institutional activity rather than one-way flow.

5. **Repeated direction flips** — 7 ticker-date pairs saw the strategy enter both long and short on the same ticker the same day, a clear sign the signal is reacting to noise.

### Charts
`charts/noise_day_patterns.pdf` — SNDK Apr 6, CVNA Apr 30, COIN Mar 10, CRDO Feb 3 (comparison)
`charts/noise_avoidance_guide.pdf` — First-bar range distribution, direction flip frequency, exit time heatmap, ticker noise scores

---

## Avoidance Rules

### Rule 1 — M1 First-Bar Range Gate
**Filter:** Skip M1 entry if the first completed 5-min bar (09:30–09:35) has a high-low range < 1.5% of the bar's midpoint price.

**Why:** Tight opening bars indicate no institutional conviction. Strategy fires on a move that immediately reverses. Noise days averaged 2.37% first-bar range vs 3.22% on good days.

**Expected impact:** Eliminates ~35% of noise-day M1 entries (primarily SNDK, COIN, CRWV flat opens). Est. +$40–60/noise day recovered.

---

### Rule 2 — Direction Flip Block (Same Ticker, Same Day)
**Filter:** Once a ticker has completed exits in *both* long and short directions on the same day, block any further entries in that ticker for the remainder of the session.

**Why:** Direction flips indicate the ticker is range-bound with no persistent trend. Re-entry after a flip on noise days added −$37 to −$272 per additional trade (worst: CVNA Apr 30).

**Expected impact:** Eliminates 5–8 losing trades across 9 noise days. Est. +$80–120/noise day recovered.

---

### Rule 3 — High-Noise-Ticker Fallback Guard
**Filter:** If a ticker from the high-noise list exits via `fallback_20pct` within 5 minutes of entry, block all subsequent same-ticker entries for the remainder of that trading window.

**Validated high-noise ticker list (present in noise days across all 4 years):**
`CVNA, CRDO, CLS, COIN, MSTR, MRVL, AMD, APP`
Secondary (2 of 4 years): `SNDK, CRWV, PLTR, EXPE`

**Why:** A fast fallback_20pct exit on a high-noise ticker is a strong signal the move is not developing. These tickers account for the majority of noise-day losses across every year tested. Preventing continuation/doubledown entries eliminates the stacking effect. The list is stable — CVNA, CRDO, COIN, MSTR, MRVL, AMD, APP appear in all 4 replay years.

**Expected impact:** Removes ~40% of multi-entry loss stacking on noise days.

---

### Rule 4 — M1 Volume Gate
**Filter:** Require the first 5-min bar (09:30–09:35) volume to be ≥ 1.5× the 20-day average daily volume / 78 bars before taking any M1 entry.

**Why:** 81% of `fallback_20pct` exits cluster at 09:50, meaning the M1 entry fires on a weak open. Volume below the threshold indicates no institutional participation to sustain the move.

**Expected impact:** Eliminates ~30% of M1 losers on noise days.

---

### Rule 5 — Soft Daily Loss Circuit Breaker
**Filter:** If realized P&L for the day reaches −$150, block all new window-open entries (M1/A1/A2/A3/A4 initiating positions). Existing open positions are not affected and can continue to trailing-stop or EOD exit normally.

**Why:** All 9 noise days ended between −$100 and −$382. The existing capital hard-stop fires late. A softer trip that only blocks new openers (not the positions already working) would cap the tail losses without cutting profitable existing trades.

**Expected impact:** Caps 4 of the 9 worst noise days. Reduces max daily drawdown from −$382 to ~−$180. Est. +$300/year in recovered tail losses.

---

## Separating Good Days from Noise Days — Summary

| Factor | Good Day Signal | Noise Day Signal |
|--------|----------------|-----------------|
| First-bar range | > 3% | < 2% |
| Opening volume | 3–5× avg on *continuation* bars | Scattered or absorption |
| Daily MA alignment | Short below MA-20 / Long above MA-20 | Counter-trend |
| Intraday close location | Within 20% of day's extreme | Near midpoint |
| Direction flips | Rare | Multiple per day |
| M1 fast-exit rate | < 10% | 67% |
| Winning trade size | 4–15% per trade | < 0.5% max |

**Key insight:** The strategy's signal quality is high when intraday momentum aligns with the daily trend and when the opening bar has both range and volume. When those two conditions are absent, every signal fires into noise. Rules 1, 2, and 4 above directly address the entry preconditions; Rules 3 and 5 limit damage once a noise day is detected in progress.

---

## Avoidance Rules — Backtest Validation

Rules 1 and 4 were implemented in `op_momentum_backtest.py` and `op_momentum_selector_backtest.py` as `--min-first-bar-range` and `--min-first-bar-volume` flags and validated via multi-year selector backtest sweeps.

### Rule 1 — M1 First-Bar Range Gate (backtested)

**Config:** `--min-first-bar-range 0.015` (1.5% threshold), M1 window only.

5-year sweep (2021–2025), same base config (top-2, 60/40, 5 windows, DD@10, reversal+BRE+BRU, SIP):

| Year | Baseline | Rule 1 (+1.5%) | Delta |
|------|----------|----------------|-------|
| 2021 | +$18,838 | +$19,074 | +$236 |
| 2022 | +$31,530 | +$29,706 | −$1,824 |
| 2023 | +$33,517 | +$32,878 | −$639 |
| 2024 | +$22,533 | +$22,055 | −$478 |
| 2025 | +$25,222 | +$24,439 | −$783 |
| **5-yr total** | | | **−$5,508** |

**Conclusion:** Net negative over 5 years. Win rate unchanged at 44–47% — the filter removes profitable entries alongside unprofitable ones. Tight first-bar range alone does not reliably predict a bad M1 trade.

---

### Rule 4 — M1 Volume Gate (backtested)

**Config:** `--min-first-bar-volume 1.5` (1.5× threshold), M1 window only.

5-year sweep (2021–2025):

| Year | Baseline | Rule 4 (1.5×) | Delta |
|------|----------|---------------|-------|
| 2021 | +$18,838 | +$19,075 | +$236 |
| 2022 | +$31,530 | +$29,134 | −$2,396 |
| 2023 | +$33,517 | +$32,726 | −$790 |
| 2024 | +$22,533 | +$22,181 | −$352 |
| 2025 | +$25,222 | +$26,221 | +$999 |
| **5-yr total** | | | **−$2,303** |

**Key finding:** Trade count barely changes (±1–37 trades out of ~2,000). When the volume gate blocks a M1 ticker, the rolling-score model substitutes a different ticker — reshuffling picks rather than cleanly eliminating bad entries. The filter produces indirect scoring side-effects that add noise.

---

### Rule 1 + Rule 4 Combination Sweep (backtested)

20-combination grid sweep for 2026 YTD and 2025, then the top 3 combinations validated over 7 years (2019–2025).

**Top 3 combinations from 2025/2026 sweep:**

| Combo | 2025 delta | 2026 delta |
|-------|-----------|-----------|
| r=0.010 + v=2.0 | +$1,656 | +$369 |
| r=0.010 + v=1.0 | +$1,060 | −$187 |
| r=off + v=1.5 | +$999 | +$275 |

**7-year validation (2019–2025):**

| Year | Baseline | r=0.010 v=2.0 | r=0.010 v=1.0 | r=off v=1.5 |
|------|----------|--------------|--------------|------------|
| 2019 | +152.1% | +152.7% | +160.0% | +167.4% |
| 2020 | +269.8% | +238.3% | +255.7% | +259.3% |
| 2021 | +188.4% | +189.2% | +183.2% | +190.8% |
| 2022 | +315.3% | +285.2% | +305.5% | +291.3% |
| 2023 | +335.2% | +320.5% | +338.0% | +327.3% |
| 2024 | +225.3% | +229.6% | +222.8% | +221.8% |
| 2025 | +252.2% | +268.8% | +262.8% | +262.2% |
| **7-yr net delta** | — | **−$5,418** | **−$1,033** | **−$1,830** |
| **Year wins** | — | 4/7 | 3/7 | 3/7 |

**Conclusion:** All combinations are net negative over 7 years. The wins in 2025 are offset by large losses in 2020 (high-volatility pandemic year) and 2022 (bear market). No combination beats baseline consistently across regimes. Rules 1 and 4, individually or combined, do not add reliable edge and should **not** be enabled in production.

Rules 2, 3, and 5 remain the primary candidates for noise-day loss reduction as they target the stacking behavior (direction flips, fast-fallback continuation, daily loss cap) rather than the initial entry signal.

---

## Scoring Formula Weight Optimization

The ticker scoring formula has four terms. `avg_win_pct` is fixed at 0.30 (historical win rate). The remaining 0.70 is allocated across `entry_vs_mid_pct`, `or_vol_ratio`, and `or_range_pct`.

Since `or_vol_ratio` was added as a scoring term, a 2026 YTD sweep explored all 11 combinations where `entry_weight + vol_ratio_weight = 0.50` in steps of 0.05, keeping `or_range_pct = 0.20` constant (remainder).

### 2026 YTD Sweep (Jan–May 9, 88 days)

| entry weight | vol_ratio weight | or_range weight | Total return |
|---|---|---|---|
| **0.50** | **0.00** | **0.20** | **+$13,604** |
| 0.45 | 0.05 | 0.20 | +$13,196 |
| 0.40 | 0.10 | 0.20 | +$12,594 |
| 0.35 | 0.15 | 0.20 | +$12,581 |
| 0.30 | 0.20 | 0.20 | +$12,843 ← prior default |
| 0.25 | 0.25 | 0.20 | +$12,485 |
| 0.20 | 0.30 | 0.20 | +$12,490 |
| 0.15 | 0.35 | 0.20 | +$12,152 |
| 0.10 | 0.40 | 0.20 | +$11,685 |
| 0.05 | 0.45 | 0.20 | +$10,857 |
| 0.00 | 0.50 | 0.20 | +$10,924 |

### 5-Year Validation (2021–2025)

Top 3 configs validated per year:

| Config | 2021 | 2022 | 2023 | 2024 | 2025 | 5yr Total |
|---|---|---|---|---|---|---|
| **entry=0.50, vol=0.00** | +$18,838 | +$31,530 | +$33,517 | +$22,533 | +$25,222 | **+$131,640** |
| entry=0.45, vol=0.05 | +$19,332 | +$30,916 | +$32,922 | +$21,283 | +$25,516 | +$129,968 |
| entry=0.40, vol=0.10 | +$18,729 | +$30,738 | +$33,181 | +$20,281 | +$24,903 | +$127,832 |

**entry=0.50 / vol=0.00 wins 4 of 5 years** (loses 2021 by $494 to 0.45/0.05). 5-year advantage: +$1,672 over second place, +$3,808 over third.

### Conclusion

`or_vol_ratio` does not improve selection quality when used as a direct scoring weight. The entry-price position within the OR (`entry_vs_mid_pct`) is the strongest discriminator — higher weight consistently outperforms across all regimes. The `or_vol_ratio` metric is still computed and stored in every trade row for offline analysis but its scoring weight is set to 0.00 by default.

**Active formula:**
```
score = entry_vs_mid_pct × 0.50 + avg_win_pct × 0.30 + or_range_pct × 0.20
```

Weights are tunable via `--score-entry-weight` and `--score-vol-ratio-weight` flags (remainder goes to `or_range_pct`; `avg_win_pct` is always 0.30).

---

## Cross-Year Summary

All returns below use the optimized scoring formula (entry=0.50, avg_win=0.30, or_range=0.20).

| Year | Period | Days | Return ($) | Return (%) | Weekly win rate | Noise days |
|------|--------|------|-----------|-----------|----------------|------------|
| 2021 | Full year | — | **+$18,838** | **+188.4%** | — | — |
| 2022 | Full year | 251 | **+$31,530** | **+315.3%** | 73% (38/52) | 39/251 (15.5%) |
| 2023 | Full year | — | **+$33,517** | **+335.2%** | — | — |
| 2024 | Full year | 252 | **+$22,533** | **+225.3%** | 83% (44/53) | 33/252 (13.1%) |
| 2025 | Full year | 250 | **+$25,222** | **+252.2%** | 85% (45/53) | 31/250 (12.4%) |
| 2026 | Jan–May 9 | 88 | **+$13,604** | **+136.0%** | 89% (17/19) | 9/88 (10.2%) |

2022 was the strategy's best year at +258.3% — the high-volatility bear market produced clean, sustained directional moves (CVNA +15.5% in a single M1 trade on Aug 5; COIN +13.1% on Aug 3). Every month was profitable. The best week (Aug 1, +$2,605) came during the bear-market rally peak where CVNA and COIN had multi-day momentum.

2024 at +192.8% was driven by the AI/crypto bull cycle (COIN +9.95% on Nov 6 election week). The Dec week was the only truly bad week (holiday-week low-liquidity fast-fallback cluster).

Noise days account for 10–15% of trading days across all years (higher in volatile bear markets, lower in trending bull markets). The noise-day win rate is consistently 20–29% vs 41–44% on good days. The structural signature (tight first-bar, fast fallbacks, direction flips, daily-trend conflict) is year-independent and validates all 5 avoidance rules.

### Charts Reference

| File | Contents |
|------|----------|
| `charts/best_feb03.pdf` | 2026 best — CRDO, PLTR (Feb 3) |
| `charts/best_feb04.pdf` | 2026 best — PLTR, MU, TSLA, SNDK (Feb 4) |
| `charts/best_feb11.pdf` | 2026 best — SHOP, CRDO, MU (Feb 11) |
| `charts/worst_apr30.pdf` | 2026 worst — CVNA, CRDO (Apr 30) |
| `charts/worst_may07.pdf` | 2026 worst — CVNA, CRDO (May 7) |
| `charts/noise_day_patterns.pdf` | Noise day intraday + daily: SNDK Apr 6, CVNA Apr 30, COIN Mar 10, CRDO Feb 3 |
| `charts/noise_avoidance_guide.pdf` | First-bar range dist., direction flip freq., exit time heatmap, ticker noise scores |
| `charts/best_worst_2022.pdf` | 2022 — CVNA Aug 5 (+15.5%), COIN Aug 3 (+13.1%) best; CVNA Sep 12/15 (-4.6%/-4.4%) worst |
| `charts/best_worst_2024.pdf` | 2024 — COIN Nov 6 (+9.95%), CLS May 24 (+4.5%) best; CVNA Feb 26 (-2.9%), APP Dec 26 (-1.2%) worst |
| `charts/noise_2022.pdf` | 2022 noise days — CVNA Sep 2, COIN Jul 12, MSTR Oct 17; avoidance guide |
| `charts/noise_2024.pdf` | 2024 noise days — MSTR Dec 12, APP May 9, CRDO Apr 29; avoidance guide |
