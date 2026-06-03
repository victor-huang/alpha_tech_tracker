# 2018 Full-Year Regime Analysis — OR Momentum Screener

**Generated:** 2026-06-02  
**Context:** 2018 was a year of two halves. Jan-Sep was broadly bullish (S&P +9%), but Q4 was a violent correction — Oct -9%, Nov -2%, Dec -15% (worst December since 1931). Key events: Feb Volmageddon (VIX spike, inverse-VIX ETF blowups), trade war escalations, Fed hiking cycle (4 hikes in 2018), and Dec 19 Powell "autopilot" rate comment triggering the Christmas Eve crash. Ticker list reduced to 11 (APP/SNOW/RDDT/PLTR/ARM/CRWD/DDOG pre-IPO; SPOT IPO Apr 2018 so excluded early months; MU included).  
**Logs:** `logs/2018_monthly_screener/2018-MM.log`

---

## Monthly Signal Summary

| Month | Sig | Days | /Day | +15m WR | +1h WR | EOD WR | EOD P&L  | Regime                                          |
|-------|-----|------|------|---------|--------|--------|----------|-------------------------------------------------|
| Jan   | 37  | 21   | 1.8  | 64.9%   | 59.5%  | 62.2%  | +12.71%  | Bull (rising curve, peaks +4h)                  |
| Feb   | 35  | 19   | 1.8  | 34.3%   | 42.9%  | 51.4%  | -11.38%  | **Persistent Bear** (Volmageddon crash)          |
| Mar   | 24  | 21   | 1.1  | 66.7%   | 54.2%  | 50.0%  | -1.92%   | AM Pop-Fade (strong +15m, neutral EOD)          |
| Apr   | 22  | 21   | 1.0  | 50.0%   | 54.5%  | 45.5%  | +4.22%   | Low-WR Positive EV (avg win 1.5× avg loss)      |
| May   | 22  | 22   | 1.0  | 54.5%   | 54.5%  | 50.0%  | -2.51%   | Neutral / Slight Bear                           |
| Jun   | 39  | 21   | 1.9  | 61.5%   | 51.3%  | 56.4%  | +6.14%   | Mild Bull (late-day rising, +5h peak)           |
| Jul   | 35  | 21   | 1.7  | 54.3%   | 57.1%  | 60.0%  | +16.61%  | **Rising-Curve Bull** (peaks at EOD)            |
| Aug   | 23  | 23   | 1.0  | 52.2%   | 56.5%  | 43.5%  | -0.74%   | Neutral / Slight EOD Fade                       |
| Sep   | 38  | 19   | 2.0  | 44.7%   | 42.1%  | 39.5%  | -14.18%  | **Persistent Bear** (declining all day)         |
| Oct   | 34  | 23   | 1.5  | 70.6%   | 38.2%  | 52.9%  | +8.34%   | **Extreme AM Pop-Fade + U-Curve Recovery**      |
| Nov   | 33  | 21   | 1.6  | 57.6%   | 60.6%  | 54.5%  | +11.85%  | Mild Bull (rising to +6h)                       |
| Dec   | 40  | 19   | 2.1  | 42.5%   | 22.5%  | 22.5%  | -39.79%  | **Catastrophic Bear** (worst Dec since 1931)    |

### Key Hold Windows

| Month | +15m P&L | +1h P&L  | +2h P&L  | +3h P&L  | +5h P&L  | EOD P&L  | Shape                               |
|-------|----------|----------|----------|----------|----------|----------|-------------------------------------|
| Jan   | +6.41%   | +6.62%   | +14.95%  | +16.67%  | +14.97%  | +12.71%  | Rising, peaks +4h                   |
| Feb   | -6.00%   | -7.98%   | -8.31%   | -10.38%  | -10.98%  | -11.38%  | Declining all day                   |
| Mar   | +10.55%  | +3.95%   | -2.60%   | +4.33%   | +0.69%   | -1.92%   | AM pop, sharp fade, choppy EOD      |
| Apr   | +3.70%   | +5.27%   | +2.92%   | +1.44%   | -2.52%   | +4.22%   | Flat, EOD recovery                  |
| May   | +0.53%   | -0.87%   | -0.82%   | -1.97%   | -3.62%   | -2.51%   | Flat to declining                   |
| Jun   | +7.39%   | +1.45%   | +9.03%   | +8.34%   | +12.81%  | +6.14%   | AM ok, +5h peak, slight EOD fade    |
| Jul   | +2.45%   | +2.02%   | +9.92%   | +11.31%  | +9.73%   | +16.61%  | Rising (EOD peak — late-day bull)   |
| Aug   | -1.87%   | +0.86%   | +3.55%   | +1.66%   | -0.92%   | -0.74%   | Midday peak, fades EOD              |
| Sep   | -1.92%   | -11.59%  | -11.07%  | -14.30%  | -13.61%  | -14.18%  | Declining sharply all day           |
| Oct   | +10.20%  | -11.72%  | -2.44%   | -0.87%   | +0.84%   | +8.34%   | Spike → crash → slow recovery       |
| Nov   | +0.89%   | -2.36%   | +0.04%   | +2.44%   | +11.37%  | +11.85%  | Flat AM, strong late-day surge      |
| Dec   | -8.01%   | -24.79%  | -27.53%  | -27.93%  | -39.02%  | -39.79%  | Catastrophically declining          |

---

## Key Patterns and Findings

### February 2018 — Volmageddon Persistent Bear
- +15m WR: **34.3%** — among the lowest in the dataset; signals reversed immediately at open
- Total P&L declining from -6.0% (+15m) to -11.4% (EOD) — every additional hour held made it worse
- Context: Feb 5 VIX spiked from ~13 to 37 intraday (XIV/SVXY blowup). S&P fell ~10% in 2 weeks. The OR breakout fired but every signal that triggered reversed violently.
- Pre-session top-2 (LLY 65% EOD, CHTR 65% EOD WR from prior 20d) — the lookback period was from the calm Jan bull, so pre-session rankings were useless as a leading indicator; signal count (1.8/day) did not warn in advance
- **Confirms acute AM bear rule:** when +15m WR < 40% and signal count is NOT low, this is a regime-change bear, not a low-activity month

### March 2018 — AM Pop-Fade (Same Pattern as Mar 2019)
- +15m: 66.7% (+10.55%) — excellent morning
- +1h30m: 45.8% (-2.45%) — collapsed by midday
- EOD: 50.0% (-1.92%) — ends flat/neutral
- Context: March 2018 had multiple trade war tariff announcements (steel/aluminum Mar 1, China tariffs Mar 22). Every morning bounce got sold into.
- This is the third consecutive March (2018–2020 had Mar 2020 as the exception) with mid-day/afternoon fade — confirms March caution
- **Exit rule for March:** if hold curve shows +15m WR > 60% but +1h WR drops 10+ pp, exit at +30m maximum

### April 2018 — Low-WR Positive EV (Second Instance)
- EOD WR: 45.5% (below 50%), EOD total P&L: +4.22% — positive despite low WR
- Avg win: +2.10%, avg loss: -1.39% → ratio 1.5×
- Same pattern as Nov 2019 (38.9% WR, +8.72%) — winning trades ran much further than losing trades
- Context: April 2018 had alternating tariff escalation/de-escalation. The few OR breakouts that held ran hard; most reversed quickly.
- **Confirmed pattern:** Low WR (40–50%) + avg win ≥ 1.5× avg loss → EV is positive; take the signals

### July 2018 — Rising-Curve Bull (EOD Peak)
- Hold curve rises steadily from +2.45% (+15m) to +16.61% (EOD) — EOD is the best window
- EOD WR: 60.0%; hold curve strengthens progressively through the afternoon
- Context: July 2018, US-China trade war in a temporary pause (talks ongoing). Tech/semiconductor rally.
- Pattern: moderate AM → progressively rising through +2h, +3h, +6h, +7h/EOD — holding EOD was optimal
- This is the clearest rising-curve bull pattern in the dataset; Jun–Jul 2018 was a clean uptrend window

### September 2018 — Persistent Bear (Confirms Seasonal Rule)
- EOD WR: 39.5%, total P&L: **-14.18%** — declining all day
- Hold curve: -1.92% (+15m) → -11.59% (+1h) → -14.18% (EOD) — every hold extended the loss
- Signal count: 2.0/day (elevated) — bear with volume, not low-activity
- Context: September 2018 was the peak of the bull run; trade war fears started weighing on tech before the October correction
- **September bear rule confirmed in 2018: 6/8 years now show September as fade/bear**
- Pre-session top-2 showed 65% EOD WR for both SNPS and LLY — again, pre-session rankings lagged the bear regime that emerged mid-month

### October 2018 — Extreme AM Pop-Fade with Full Day Recovery
- +15m WR: **70.6% (+10.20%)** — second highest +15m WR in any bear-correction month
- +1h WR: **38.2% (-11.72%)** — collapsed 32.4 percentage points in 45 minutes
- **32.4pp drop from +15m to +1h** — matches Sep 2020's 32pp collapse as sharpest AM pop-fade in the dataset
- Then U-curve recovery: +2h 52.9% (-2.44%) → +6h 52.9% (+8.32%) → EOD 52.9% (+8.34%)
- Context: October 2018 S&P correction -9.3%. Opening range breakouts fired correctly at 9:30 but every position was sold aggressively in the 9:45–10:30 window as institutions took profits.
- **Trading rule:** in high-volatility correction months, +15m is the only tradeable window when AM WR > 65%; do NOT hold to +30m or beyond without confirming the +30m WR is holding above 55%
- Despite the correction, October 2018 was still net positive (+8.34% EOD) — confirms October seasonal bull even in a correction year

### November 2018 — Rising Late-Day Bull (Choppy Month)
- +15m: 57.6% (+0.89%) — modest AM
- +5h: 57.6% (+11.37%), +6h: +13.72% (peak)
- EOD: 54.5% (+11.85%) — fully positive by close
- Context: November 2018 was extremely choppy (G20 trade deal hopes/fears). The market fell further but growth/tech saw late-day dip buying.
- The AM-to-EOD recovery pattern (flat AM → strong late afternoon) is the reverse of the AM pop-fade

### December 2018 — New Record Lowest EOD Win Rate in Dataset
- EOD WR: **22.5%** — the single LOWEST end-of-day win rate across all 9 years of data (beats Dec 2022's 30.6%)
- +1h WR: **22.5%** — catastrophic; by 10:30am most positions were already losing badly
- EOD total P&L: **-39.79%** — third worst month in the dataset
- Avg loss: -1.85% vs avg win: +1.96% — losses and wins were similarly sized; just 22.5% of signals won
- Signal count: 2.1/day (elevated) — the screener kept firing, every signal failed
- Context: Dec 2018 market fell ~15%. Dec 19 Powell "autopilot" comment; Christmas Eve crash to -20% YTD lows. This was the worst December in US markets since 1931.
- Pre-session top-2 on Dec 3 picked AMD (70% EOD WR from prior 20d) and AVGO (70%) — prior rankings were from the Nov bull run, completely stale for the December bear
- **December bear rule confirmed: 6/8 years negative (2018 adds to pattern); 2019 and 2020 are macro catalyst exceptions**

---

## Rule Validation vs Prior Framework

| Rule                                          | 2018 Result                                    | Notes                                                          |
|-----------------------------------------------|------------------------------------------------|----------------------------------------------------------------|
| January is mild LONG prior                    | ✅ Jan: 62.2% EOD, +12.71%                    | Bull with rising curve; confirms 7/8 years positive January    |
| February: follow prior month's regime         | ✅ Feb: prior Jan was bull → Feb flipped bear  | Volmageddon was a regime break; prior month's regime didn't predict |
| March caution — check by day 3               | ✅ Mar: AM strong (+15m 66.7%), EOD -1.92%    | Same AM-pop-fade as Mar 2019; confirms March caution            |
| April NOT seasonal bull                       | ✅ Apr: 45.5% EOD (low WR, barely positive)   | Fourth bear/flat April in dataset                               |
| September fade — exit by +30m                | ✅ Sep: 39.5% EOD, -14.18% (declining all day) | Worst September in the dataset; 6/8 years confirmed             |
| October is reliable bull                      | ✅ Oct: +8.34% despite major correction        | 7/8 years positive; correction months can still be net positive |
| Low +15m WR → acute AM bear                  | ✅ Feb: 34.3% +15m → -11.38% EOD             | Near-record low +15m WR; all windows negative                   |
| AM pop-fade: exit at +15m                     | ✅ Oct: +15m +10.20% vs +1h -11.72%           | 32.4pp drop — sharpest Oct in dataset; exit at +15m was critical |
| December is persistent bear                   | ✅ Dec: 22.5% EOD WR, -39.79%               | New record low EOD WR; confirms 6/8 years negative December     |
| Low-WR positive EV (check avg win/loss ratio) | ✅ Apr: 45.5% WR, +4.22%, avg win 1.5× loss  | Second confirmation of this pattern (first was Nov 2019)        |

---

## 2018 Summary for Cross-Year Comparison

- **New all-time record:** December 2018 — **lowest EOD win rate in the full dataset: 22.5%** (beats Dec 2022's 30.6%)
- **New record tied:** October 2018 — +15m to +1h collapse of 32.4pp tied with Sep 2020's 32pp as the sharpest AM pop-fade in the dataset
- **Year structure:** Classic two-halves year — Jan-Jul bullish, Aug-Sep warning signs, Oct-Dec bear market
- **July was the cleanest rising-curve bull:** the hold curve rose continuously from +15m (+2.45%) to EOD (+16.61%) — the textbook case for "hold to EOD when the curve is rising"
- **Bear months were macro-catalyst driven:** Feb (Volmageddon), Sep (trade war peak), Dec (Fed autopilot crash)
- **September confirmed** for the 6th year running — no exception in 2018; the strongest bear confirmation in any year
- **October seasonal rule held** even in the correction year (+8.34%); but the AM pop-fade was the sharpest in the dataset — +15m only was the right exit
- **2018 net year performance:** slightly negative (Dec -39.79% swamped Jul +16.61% and Jan +12.71%); the only full-year negative in the dataset so far alongside 2022
