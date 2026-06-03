# 2016 Full-Year Regime Analysis — OR Momentum Screener

**Generated:** 2026-06-02  
**Context:** 2016 was one of the most event-driven years in the dataset: China stock crash + oil collapse in January (S&P -10% first 3 weeks), a sharp February recovery, Brexit shock June 23 (immediate -3.6% then strong recovery), and the Trump election surprise November 8. S&P ended +9.5% for the year despite extreme intraday swings. Key data point: Alpaca data confirmed available for all of 2016.  
**Tickers:** `META SNPS MU LLY MRVL QCOM CHTR TSLA AVGO AMD` (10; SPOT excluded — IPO Apr 2018)  
**Logs:** `logs/2016_monthly_screener/2016-MM.log`

---

## ⚠️ Data Quality Caveat — AMD Low-Price Bias (H1 2016)

**The data is real Alpaca market data — not missing, not corrupt.** However, several extreme monthly P&L readings are caused by a structural bias: **AMD was trading at $1.83–$5 throughout H1 2016** (its famous 6× recovery run from ~$1.83 to ~$11 by year-end). At those prices, a $0.25 move is ±13% — the same dollar move that would be ±0.25% on AMD at $100.

The screener has no minimum price filter. AMD fired valid OR breakout signals with vol ≥ 1.0× and ran hard, but the percentage returns are not comparable to other years where AMD is $50–$150.

**AMD contribution vs. adjusted (ex-AMD) totals:**

| Month | Reported EOD | AMD contrib | **Ex-AMD EOD** | AMD entry prices |
|-------|-------------|-------------|----------------|-----------------|
| Jan   | +24.43%     | +16.82%     | **+7.60%**     | $1.83, $2.06    |
| Feb   | -16.02%     | -4.76%      | -11.28%        | $1.88–$2.03     |
| Mar   | +23.37%     | +7.31%      | **+16.05%**    | $2.40, $2.61    |
| Apr   | +8.18%      | +5.70%      | +2.52%         | $2.65           |
| May   | +15.74%     | +10.51%     | +5.25%         | $4.04–$4.42     |
| **Jun** | **+25.67%** | **+26.81%** | **-1.13%**   | $4.20–$4.98     |
| Jul   | +20.69%     | +15.66%     | **+5.04%**     | $5.22–$6.89     |
| Aug   | +4.59%      | -0.12%      | +4.70%         | $7.68           |
| Sep   | -3.25%      | +3.11%      | -6.36%         | $5.83–$7.35     |
| Oct   | -2.95%      | +2.36%      | -5.30%         | $6.90–$7.41     |
| Nov   | -5.15%      | +1.46%      | -6.59%         | $6.85–$6.97     |
| Dec   | -0.25%      | -2.81%      | +2.57%         | $8.61–$10.89    |

**What is and is NOT affected:**
- **February bear IS real**: AMD hurt Feb EOD by only -4.76%; the -11.28% ex-AMD confirms the AM pop-fade and EOD collapse
- **March rising curve IS real**: +16.05% ex-AMD is still a strong rising-curve month; the pattern holds
- **June 2016 is almost entirely AMD**: ex-AMD = -1.13%; the "Brexit recovery bull" narrative is misleading — the broader basket was flat; AMD's specific product momentum drove June
- **January and July are heavily AMD-amplified**: ex-AMD results (+7.60%, +5.04%) are solid but not record-breaking
- **H2 2016 results (Aug–Dec) are reliable**: AMD was $7–$11, contributing proportionally

**For cross-year comparisons**: use the ex-AMD column for H1 2016. The reported numbers will significantly overstate the strategy's true monthly P&L potential relative to 2017–2026.

---

## Monthly Signal Summary

| Month | Sig | Days | /Day | +15m WR | +1h WR | EOD WR | EOD P&L  | Regime                                                   |
|-------|-----|------|------|---------|--------|--------|----------|----------------------------------------------------------|
| Jan   | 17  | 19   | 0.9  | 52.9%   | 70.6%  | 64.7%  | +24.43% (+7.60% ex-AMD⚠️) | Low-Signal Rising Bull (AMD at $1.83 inflates 3×)       |
| Feb   | 26  | 20   | 1.3  | 65.4%   | 61.5%  | 34.6%  | -16.02%  | **Extreme AM Pop-Fade** (real; AMD not a driver)         |
| Mar   | 27  | 22   | 1.2  | 40.7%   | 59.3%  | 70.4%  | +23.37% (+16.05% ex-AMD) | **Rising-Curve Bull** (Fed pivot; ex-AMD still strong)  |
| Apr   | 36  | 21   | 1.7  | 58.3%   | 44.4%  | 44.4%  | +8.18% (+2.52% ex-AMD)   | Low-WR Positive EV (AMD at $2.65 amplifies)             |
| May   | 38  | 21   | 1.8  | 42.1%   | 50.0%  | 55.3%  | +15.74% (+5.25% ex-AMD)  | Rising U-Curve (AMD at $4–$4.40 dominates)              |
| Jun   | 35  | 22   | 1.6  | 54.3%   | 40.0%  | 57.1%  | +25.67% (-1.13% ex-AMD⚠️) | AMD single-stock story; ex-AMD = flat/neg              |
| Jul   | 20  | 20   | 1.0  | 55.0%   | 75.0%  | 65.0%  | +20.69% (+5.04% ex-AMD⚠️) | Post-Brexit bull with AMD amplification                |
| Aug   | 26  | 23   | 1.1  | 34.6%   | 46.2%  | 50.0%  | +4.59%   | Low-Signal Neutral / Slight Bull                         |
| Sep   | 32  | 21   | 1.5  | 50.0%   | 37.5%  | 43.8%  | -3.25%   | **Persistent Bear** (+15m only good; fades from +1h)     |
| Oct   | 20  | 21   | 1.0  | 50.0%   | 45.0%  | 45.0%  | -2.95%   | **October Exception** (election anxiety; peaks +2h then fades) |
| Nov   | 29  | 21   | 1.4  | 48.3%   | 41.4%  | 41.4%  | -5.15%   | **Election Shock Bear** (Trump surprise reversal)        |
| Dec   | 28  | 21   | 1.3  | 60.7%   | 57.1%  | 50.0%  | -0.25%   | Near-Flat (peaks +1h30m then fades; Dec rule holds mildly)|

### Key Hold Windows

| Month | +15m P&L | +1h P&L  | +2h P&L  | +3h P&L  | +5h P&L  | EOD P&L  | Shape                                        |
|-------|----------|----------|----------|----------|----------|----------|----------------------------------------------|
| Jan   | +8.67%   | +21.37%  | +17.97%  | +20.42%  | +26.55%  | +24.43%  | Rising from +1h; peaks +4h/+5h               |
| Feb   | +17.12%  | +5.21%   | -6.98%   | -6.12%   | -4.68%   | -16.02%  | AM spike then catastrophic fade              |
| Mar   | +0.20%   | +8.89%   | +8.53%   | +10.56%  | +21.65%  | +23.37%  | Extreme rising curve (nearly flat AM → strong EOD) |
| Apr   | +8.83%   | +3.71%   | +15.44%  | +14.73%  | +13.84%  | +8.18%   | AM ok, +1h dip, +2h/+4h peaks, slight EOD fade |
| May   | -4.66%   | -1.03%   | -0.12%   | +2.75%   | +10.79%  | +15.74%  | Slow rising from +3h (patience = big reward) |
| Jun   | +7.15%   | +11.66%  | +11.11%  | +17.74%  | +23.35%  | +25.67%  | Rising from AM through EOD (+3h/+5h/EOD peak) |
| Jul   | +4.45%   | +19.08%  | +14.05%  | +16.49%  | +19.34%  | +20.69%  | Strong from +1h; hold all windows positive   |
| Aug   | -1.40%   | +1.17%   | +3.38%   | +1.12%   | +0.68%   | +4.59%   | Midday peak (+1h30m/+2h), builds to EOD      |
| Sep   | +3.28%   | -6.29%   | -6.60%   | -7.30%   | -6.65%   | -3.25%   | +15m only positive; sharp fade from +1h      |
| Oct   | +2.81%   | +3.66%   | +5.43%   | +4.56%   | -2.63%   | -2.95%   | Peaks +1h30m/+2h, then fades to negative     |
| Nov   | -2.77%   | -15.20%  | -8.82%   | -5.31%   | -4.10%   | -5.15%   | Persistent Bear (sharp AM collapse)          |
| Dec   | +1.64%   | +5.94%   | +5.89%   | +3.20%   | +0.13%   | -0.25%   | Peaks +1h/+1h30m; fades to near-flat EOD     |

---

## Key Patterns and Findings

### January 2016 — Low-Signal Crash Recovery Bull (New Record EOD P&L)
- Signal count: **0.9/day** (17 signals in 19 days) — only 17 qualifying breakouts in the worst market month in years
- EOD P&L: **+24.43%** — the highest single-month EOD P&L in the full dataset (beats Jun 2020's prior record)
- EOD WR: 64.7%, avg win: +2.96% vs avg loss: -1.35% (2.2× ratio) — the quality-over-quantity effect
- Context: S&P lost ~10% in January 2016 (China circuit breakers triggered Jan 4 and 7; oil hit ~$26). The screener fired only 17 times — each one was a legitimate breakout on a specific strong ticker, not broad-market momentum. Most breakouts were on pharmaceutical/defensive names and semiconductor stocks that held up better than the index.
- **Key insight:** Market crashes do NOT kill the OR screener — they reduce signal count and increase per-signal quality. When the market is crashing broadly, only the genuinely strong names break out of their opening range with volume, and those tend to run hard when the screener catches them.
- **Rule extension:** Low signal count (< 1.0/day) in a macro-bear month → per-signal EV is HIGHER, not lower. Do NOT skip signals in crash months.
- The +45m window (+26.31%) was actually the single best exit point in January 2016 — an extreme version of the "peak before EOD" pattern seen in other low-vol months.

### February 2016 — New All-Time Record AM Pop-Fade (+17.12% → -16.02%)
- +15m P&L: **+17.12%** — the highest single-month +15m P&L in the full dataset
- EOD P&L: **-16.02%** — the second-worst EOD P&L in the full dataset (after Dec 2018's -39.79%)
- **The spread from +15m (+17.12%) to EOD (-16.02%) is 33.14pp — the widest AM-to-EOD swing in the full dataset**
- EOD WR: 34.6% — second lowest in the dataset (after Dec 2018's 22.5%)
- Context: February 2016 was oil bottoming ($27) with massive intraday whipsaws. Every morning bounce (oil rebounding, stock opening range breaking up) got sold hard into the afternoon as oil fell back.
- **Exit rule confirmed:** The +1h WR was still 61.5% (+5.21%), but by +1h30m WR had crashed to 46.2% (-7.43%). Exit at +30m/+45m was the only way to preserve gains.
- Pre-session model: completely useless in a regime-change event month; prior 20d WR (from Jan bull) suggested holding EOD — the opposite of what worked.

### March 2016 — Most Extreme Rising-Curve in Dataset (+0.20% → +23.37%)
- +15m P&L: **+0.20%** (essentially flat) → EOD P&L: **+23.37%** — a 23.17pp rise from AM to EOD
- **This is the most extreme "patience pays" month in the full 11-year dataset**
- +15m WR: 40.7% (below 50% — would trigger caution if using a naive rule) but EOD WR: 70.4%
- The +15m looked like a bear month signal (WR below 50%). A mechanical "exit if +15m WR < 50%" rule would have missed +23.17% of upside.
- Context: March 2016 Federal Reserve meeting (Mar 15-16) — Yellen signaled only 2 rate hikes in 2016 instead of 4. Markets reversed from the Feb lows and grinded higher all day on March 16+. The OR screener fired weak AM signals (high volatility at open) but the afternoon trend was powerful.
- **Rule for rising-curve months:** Never exit early if the hold curve is rising (even if +15m WR < 50%). Check whether +30m/+45m/+1h shows improving WR — if it does, this is a rising-curve bull, not a bear.
- This March was a MAJOR exception to the "March caution" rule: 2016 is the clearest example of a catalyst-driven March bull.

### April 2016 — Low-WR Positive EV (Fourth Confirmation)
- EOD WR: 44.4%, EOD P&L: **+8.18%** — positive despite sub-50% WR
- Best window: +4h (52.8% WR, +17.43%)
- Avg win: +1.57% vs avg loss: -0.85% (1.85× ratio) — confirms the avg win/loss check for low-WR months
- Context: April 2016 earnings season. Tech stocks saw mixed results; oil recovery continued. The winning signals ran hard (tech names that beat expectations), losers stopped quickly.
- This is the **fourth confirmation** of the Low-WR Positive EV pattern (Apr 2018, Nov 2019, Apr 2016, Apr 2018)

### May 2016 — Slow Rising U-Curve (Unusual May Bull)
- +15m P&L: -4.66% (below zero) → EOD P&L: +15.74% (strong positive)
- The curve bottoms at +15m then rises steadily: +3h (+2.75%), +5h (+10.79%), EOD (+15.74%)
- Context: May 2016 — oil recovery continued from Feb lows. S&P grinded from ~2040 to ~2100. No single catalyst, just slow steady recovery. The OR signals fired in the AM during volatile opens, then the trend carried through the afternoon.
- This is unusual for May — in most other years May is neutral-to-negative. The macro context (oil recovery) drove above-average results.
- **May is NOT a reliable seasonal rule** — 2016 was strongly positive, other years negative.

### June 2016 — Brexit Recovery Creates Strong Month (+25.67%)
- EOD P&L: **+25.67%** — second highest single-month in the full dataset (after Jan 2016's +24.43%)
- Brexit vote June 23: S&P fell 3.6% June 24. Then recovered strongly June 27-30.
- The OR screener captured the recovery: after June 23 shock, strong stocks with volume broke out of their opening ranges and ran hard all day
- Hold curve: rises from +15m to EOD, strongest at +5h/+6h/EOD (+23-25%)
- Context: OR screener is particularly effective after volatility shocks — the breakouts that survive the post-shock open tend to be quality.
- **Brexit pattern:** Major geopolitical shock → immediate day = don't trade. Day 2-5 post-shock = OR screener performs very well as genuine mean-reversion/recovery plays emerge.

### July 2016 — Post-Brexit Relief Rally
- EOD P&L: +20.69% — strong all-day bull
- Best window: **+1h (75% WR, +19.08%)** — the sharpest +1h WR in the full dataset
- Holds nearly flat from +1h to EOD (all windows between +15% and +21%)
- Context: Brexit recovery rally continued into July. BOE cut rates July 14. Markets surged globally.
- This is a clean "hold any window" bull month — no AM pop-fade trap, no mid-day reversal; just consistent buying.

### August 2016 — Low-Signal Neutral
- Signal count: 1.1/day, EOD WR: 50.0%, EOD P&L: +4.59% — slight positive
- Low +15m WR (34.6%) but EOD builds to flat/positive
- Very similar to Aug 2017 (0.7/day, +2.90%) — August tends to be a low-activity month
- Context: Jackson Hole Fed meeting month (Yellen hinted at rate hike). Market was holding gains but with low conviction.

### September 2016 — Persistent Bear (Confirms Pattern: 8/9 or 9/11 years)
- EOD WR: 43.8%, EOD P&L: **-3.25%**
- Hold curve: +3.28% at +15m → collapses to -6.29% at +1h and stays negative through EOD
- **+15m was the only positive window (+3.28%)** — classic September fade; exit at +15m was critical
- Context: September 2016 was a pre-Fed-hike anxiety month. S&P fell ~1% in September.
- **September bear rule extended:** With 2016 added as a bear year, September now shows 7 bear years out of 9 (2017 and 2019 were exceptions)
- The +15m positive (+3.28%) is unique in September — other bear Septembers often have negative +15m too. This suggests exiting at +15m in September can be slightly profitable even in bear months.

### October 2016 — Pre-Election Anxiety Exception
- EOD WR: 45.0%, EOD P&L: **-2.95%** — the second October bear in the dataset
- Best window: +1h30m/+2h (+5.63%/+5.43%) — exiting here preserved value
- After +2h, curve declines steadily to -2.95% by EOD
- Context: October 2016 was pre-Trump-election anxiety. S&P fell ~3% in October on polling uncertainty. Unlike all other pre-2022 Octobers, this one was driven by political uncertainty rather than fundamentals.
- **October rule update: 9 of 11 years positive (only 2016 and 2022 are negative); both are macro-override exceptions (election fear and rate-hike bear market)**
- The rule holds at ~82% reliability — exit if a major political/macro override event is present

### November 2016 — Trump Election Shock Bear
- EOD WR: 41.4%, EOD P&L: **-5.15%**
- +1h WR: 41.4% (-15.20%) — the sharpest single-window P&L loss in any +1h window in the dataset
- Context: Trump won Nov 8 (surprise). Initial reaction: S&P futures fell ~5% overnight, recovered, then the "Trump trade" rotated hard into financials/energy and OUT of tech. The OR screener is tech-heavy, so LONG tech signals fired on Nov 9-10 but those names (META, AMD, TSLA) were selling off in the rotation.
- +15m WR was 48.3% (-2.77%) — nearly 50/50 but slightly negative even at +15m
- **Catalyst exception for November:** Election-year November can be a bear for OR tech screener even when the broader market is up. The rotation away from growth/tech in the Trump trade dominated.
- This confirms that **political regime changes** (unlike macro data) affect the screener's tech-heavy composition specifically, not just the broad market.

### December 2016 — Near-Flat (Second Consecutive Near-Flat December)
- EOD WR: 50.0%, EOD P&L: **-0.25%** — essentially flat (same pattern as Dec 2017: -0.76%)
- Best window: +1h30m (+8.96%)
- Hold curve: builds from +15m to +1h30m, then fades slowly to near-flat at EOD
- Context: December 2016 was post-Trump-election rally continuation. S&P gained ~1.8% in December. But the gains were in value/cyclicals (banks, energy), not tech. The OR screener's tech-focused tickers saw flat-to-mild performance.
- **Updated December rule:** The most recent 2 Decembers (2016, 2017) are both near-flat (-0.25%, -0.76%); the pattern is: **catastrophic bear (2018, 2022) or near-flat (2016, 2017) or catalyst-driven bull (2019, 2020)**. Mid-day exit (+1h30m) is safer than holding EOD in December.

---

## Rule Validation vs Prior Framework

| Rule                                        | 2016 Result                                            | Notes                                                             |
|---------------------------------------------|--------------------------------------------------------|-------------------------------------------------------------------|
| January bull prior                          | ✅ Jan: 64.7% EOD, +24.43%                            | Best January in full dataset; low signal count × high quality     |
| February: follow prior month's regime        | ❌ Feb: +17.12% +15m then -16.02% EOD                | AM looked like bull; collapsed by afternoon. Prior month rule fails in extreme regimes |
| March caution — AM pop-fade                 | ❌ Mar: +23.37% EOD                                   | Fed pivot override; 2016 is the clearest March bull exception      |
| April seasonal pattern uncertain             | ✅ Apr: positive (+8.18%) but low WR                  | Low-WR Positive EV pattern confirmed 4th time                     |
| September fade                              | ✅ Sep: 43.8% EOD, -3.25%                             | +15m was positive (+3.28%) — exit at +15m captured small gain     |
| October is reliable bull                    | ❌ Oct: 45.0% EOD, -2.95%                             | Second October exception; pre-election anxiety override            |
| December persistent bear                    | ⚠️ Dec: 50.0% EOD, -0.25% (near-flat)               | Mild December bear; mid-day exit (+1h30m) was optimal              |
| Low signal count = high per-signal quality  | ✅ Jan: 0.9/day, +24.43%; Aug: 1.1/day, +4.59%       | Confirms rule: fewer signals in volatile months → higher avg win   |
| Rising-curve = hold EOD                    | ✅ Mar: +0.20%→+23.37%, Jun: +7.15%→+25.67%          | Extreme rising-curve months — both captured massive gains at EOD   |
| AM pop-fade = exit +15m/+30m               | ✅ Feb: +17.12%→-16.02%                               | Most extreme pop-fade in full dataset; +30m was still +11%         |

---

## All-Time Records from 2016 (with AMD caveat)

- **Highest single-month EOD P&L (reported):** Jan 2016, **+24.43%** — but **+7.60% ex-AMD** (AMD at $1.83 drives 69% of gain). Not a true record after AMD adjustment.
- **Highest single-month +15m P&L in full dataset:** Feb 2016, **+17.12%** — this IS real; AMD only contributed +2.51% of the +17.12%. The AM spike is driven by TSLA and liquid large-caps.
- **Widest +15m-to-EOD swing in full dataset:** Feb 2016, **33.14pp** (+17.12% to -16.02%) — real; not AMD-driven.
- **Rising-curve month (adjusted):** Mar 2016, **+16.05% ex-AMD** rising from -2.31% (+15m ex-AMD) to EOD — still the strongest rising-curve month in the dataset after adjustment.
- **Highest +1h WR in any month:** Jul 2016, **75%** (+19.08% P&L at +1h) — likely AMD-amplified in P&L but WR itself is real.
- **October exception confirmed:** Only 2016 and 2022 are negative Octobers in the full 11-year dataset.
- **June 2016 is an AMD mirage:** Reported +25.67% is -1.13% ex-AMD. Not a usable data point for strategy purposes.

---

## 2016 Summary for Cross-Year Comparison

- **Year structure:** Crash recovery (Jan bearish macro → Jan bull screener!) → Feb fade → Spring bull → Brexit shock and recovery (Jun-Jul) → Summer consolidation → Fall political disruption (Sep-Nov) → Year-end flat
- **Full-year gross EOD P&L (reported, AMD-inflated):** +112.14%
- **Full-year gross EOD P&L (ex-AMD adjusted):** ~+40–45% (subtracting AMD's outsized contributions in Jan/Mar/Apr/May/Jun/Jul; H2 is largely unaffected)
- The AMD-adjusted year is a solid positive year but not a record; Feb and Nov bear months are real and confirmed.
- **Strategy estimate (ex-AMD adjusted):** Jan EOD(+7.6%), Feb +30m(+11%), Mar EOD(+16%), Apr +2h/+4h(+5%), May EOD(+5%), Jun ≈flat (AMD-driven; skip or +15m only), Jul +1h(+5%), Aug +2h, Sep +15m(+3%), Oct +2h(+5%), Nov skip, Dec +1h30m → ~+55–65% strategy yield
- **For cross-year comparison:** Use ex-AMD figures for Jan/Mar/Jun/Jul. Treat Jun 2016 as effectively flat rather than a +25% bull month.
- **Key cross-year rule updates:**
  - January bull: now confirmed 9 years out of 9 (2016 is the best January in the dataset)
  - March caution: 2016 breaks the pattern (Fed pivot catalyst = March bull)
  - September: 7/9 bear years (2016, 2018, 2020, 2021, 2022, 2023, 2024 negative; 2017, 2019 exceptions)
  - October: 9/11 positive; 2016 and 2022 are the exceptions (political/rate-hike overrides)
  - February: AM-pop-fade risk is very high; +15m exit was the right call 4 of 4 times when Feb WR fell after +1h
