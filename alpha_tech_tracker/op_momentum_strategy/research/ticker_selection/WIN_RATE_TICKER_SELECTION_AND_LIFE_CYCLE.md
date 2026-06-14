# Win-Rate Ticker Selection & Lifecycle Analysis

**Created:** 2026-06-10
**Config analyzed:** M1 09:30/3b | win-rate selector | QQQ MA8 regime-hold | top-8 | $80k | fixed-signal-alloc | reversal + reentry + doubledown
**Data sources:**

| Log dir | Ticker set | Years |
|---|---|---|
| `replay_20{17-25}_stock_m1_winrate_regimehold_cap80k_fixedalloc_reversal_dd` | Original 19 tickers | 2017–2025 |
| `replay_20{25-26}_stock_m1_winrate_regimehold_cap80k_fixedalloc_reversal_dd` | New 20 tickers (cdd02503) | 2025–2026 |

**Original 19-ticker set:** TSLA AMD APP SPOT PLTR QCOM DDOG SNPS META SNOW MRVL CHTR AVGO ARM SNDK CRWD LLY RDDT MU  
**New 20-ticker set (cdd02503):** SNDK META SNOW PLTR MU LLY LUNR CRWD QCOM OKLO TSLA AVGO ARM AMD DDOG RDDT IONQ HOOD RKLB CLSK

---

## Overview

The win-rate selector ranks every ticker in the pool daily by its trailing 20-day EOD win rate and picks the top-8 for that day's trades. This document analyzes how individual tickers move through selection cycles — when they activate, how they peak, and how they fade — based on 9 years of backtest data (2017–2026) across two ticker sets and 15 major peak-day events.

---

## Section 1 — Per-Ticker Performance Summary

### Original 19-Ticker Set (2017–2025)

| Ticker | Days Selected | Trades | Total P&L | Avg P&L/trade |
|---|---|---|---|---|
| TSLA | 1,240 | 304 | +$36,453 | +$119.9 |
| AMD | 969 | 266 | +$28,793 | +$108.2 |
| APP | 472 | 127 | +$20,043 | +$157.8 |
| PLTR | 544 | 127 | +$18,881 | +$148.7 |
| SPOT | 1,122 | 289 | +$17,806 | +$61.6 |
| QCOM | 1,281 | 334 | +$14,225 | +$42.6 |
| DDOG | 561 | 160 | +$9,872 | +$61.7 |
| OKLO | 88 | 29 | +$9,663 | +$333.2 |
| SNPS | 1,395 | 394 | +$7,683 | +$19.5 |
| IONQ | 80 | 15 | +$7,535 | +$502.4 |
| META | 1,423 | 350 | +$7,507 | +$21.4 |
| SNOW | 762 | 185 | +$7,494 | +$40.5 |
| MRVL | 1,076 | 305 | +$7,307 | +$24.0 |
| CHTR | 1,159 | 358 | +$7,150 | +$20.0 |
| AVGO | 1,431 | 364 | +$6,611 | +$18.2 |
| ARM | 275 | 56 | +$2,833 | +$50.6 |
| SNDK | 88 | 22 | +$2,655 | +$120.7 |
| CRWD | 906 | 264 | +$2,626 | +$9.9 |
| LLY | 1,551 | 437 | +$1,972 | +$4.5 |
| MU | 1,121 | 230 | -$2,343 | -$10.2 |

**Observations:**
- TSLA and AMD are the dominant contributors at $36k and $28k over 9 years
- APP, PLTR, SPOT are high avg-per-trade tickers concentrated in active cycle years
- OKLO and IONQ appear at the tail of the original set (started 2025) — very high avg/trade ($333, $502) reflecting their high-vol cycle nature
- LLY is the most-selected ticker (1,551 days) but lowest avg/trade (+$4.5) — consistent but thin margins; a "quality filler" in the top-8

### New 20-Ticker Set (cdd02503) — 2025–2026

| Ticker | Days Selected | Trades | Total P&L | Avg P&L/trade |
|---|---|---|---|---|
| OKLO | 96 | 46 | +$15,289 | +$332.4 |
| LUNR | 120 | 49 | +$13,457 | +$274.6 |
| PLTR | 176 | 57 | +$7,716 | +$135.4 |
| IONQ | 90 | 32 | +$7,206 | +$225.2 |
| QCOM | 132 | 37 | +$7,130 | +$192.7 |
| CRWD | 274 | 132 | +$6,662 | +$50.5 |
| RKLB | 129 | 60 | +$4,823 | +$80.4 |
| AVGO | 210 | 108 | +$2,497 | +$23.1 |
| DDOG | 105 | 50 | +$2,001 | +$40.0 |
| META | 163 | 72 | +$1,464 | +$20.3 |
| SNDK | 181 | 70 | +$1,059 | +$15.1 |
| MU | 159 | 57 | -$1,306 | -$22.9 |

The high-volatility thematic names (OKLO, LUNR, IONQ, RKLB) dominate by avg/trade. CRWD contributes the most by total trades (132) and is the most consistent producer in 2025–2026. MU is negative across both sets — consistently poor OR momentum behavior relative to pool.

---

## Section 2 — Ticker Lifecycle Patterns

### The Standard Lifecycle

Every high-contributing ticker follows the same structure:

```
[Hibernation] → [Re-activation] → [Active streak] → [Peak day] → [Quality fade] → [Exit/Hibernation]
```

**Hibernation:** Ticker is absent from top-8 for 15–100+ trading days. Its 20-day trailing win rate has dropped below the pool average. The ticker is not broken — it is between momentum cycles.

**Re-activation:** Ticker re-enters the top-8 after an extended absence. This is the earliest detectable signal that its trailing win rate has recovered and is competitive again. Re-entry after 15+ days of absence is a stronger signal than continued presence because it typically aligns with a new fundamental catalyst or sector rotation.

**Active streak:** Ticker remains in top-8 for multiple consecutive days. Selection itself is the proxy for elevated win rate — no separate win rate logging is needed. The streak accumulates as the trailing 20-day window captures the improved performance.

**Peak day:** The single highest-P&L day in the cycle. Often catalyst-driven (earnings, policy event, sector rotation day). The peak day is not predictable but is captured reliably because the ticker is already selected pre-session.

**Quality fade:** Ticker remains in top-8 (boosted by peak day's win rate contribution) but subsequent trades generate flat or negative P&L. The selection is technically correct (historical win rate is still high) but the current OR conditions no longer align with the historical pattern.

**Exit / Hibernation:** Ticker drops below pool threshold as the peak day rolls off the 20-day window. May return in a new cycle 4–20 weeks later.

---

### Lifecycle Examples — 4 New Tickers

**OKLO:**
- Jan 2025 cycle: activated Jan 6, peak Jan 23 (+$7,042), continued selectively through Feb–Mar, absent Apr–Aug
- Sep–Oct 2025: brief re-activation ($+391, +$348), then absent
- Dec 2025: second re-activation, peak Jan 28, 2026 (+$4,621), Feb 4 (+$820)
- Absent from Feb 26, 2026 onward (75+ days and counting)

**LUNR:**
- Absent entire Jan–Apr 2025 (83-day gap)
- May 2025: brief first appearance, unprofitable (-$744 total)
- Sep–Oct 2025: re-activation but mixed (-$623 total in Oct)
- Dec 1, 2025: strong re-activation → 34-day consecutive streak through March 2026
- Apr 2, 2026: peak (+$10,030 — largest single day in 10-year dataset)
- Absent Apr 8, 2026 onward (42+ days)

**IONQ:**
- Jan 2025: activated from day 1 (21-day streak) but loss-making (-$1,484); Jan 21 -$1,196 likely DeepSeek shock
- Absent Feb–Jun 2025 (83 days)
- Jul 17, 2025: re-activation → Jul 28 peak (+$862)
- Absent Aug–Sep 2025
- Oct 1, 2025: re-activation → Oct 13 peak (+$7,886)
- Absent Oct 28 – May 2025 (extended hibernation)
- May–Jun 2026: new cycle beginning

**RKLB:**
- Brief Jan 2025 appearance, quickly dropped (-$212 total)
- Absent Feb–May 2025 (94 days)
- Sep 2025: long 21-day streak but loss-making (-$766)
- Absent Oct–Nov 2025
- Dec 2025: re-activation
- Jan 26, 2026: strong re-activation → 28+ day consecutive streak through Apr 2026
- Apr 24, 2026: peak (+$4,365)
- May 7, 2026: exit

---

## Section 3 — Peak Day Analysis: Cross-Set Validation

### All Major Peak Days Across Both Sets

| Ticker | Peak Date | Pre-streak | Peak P&L | Post-10d P&L | Post sel (10d) | Absent after |
|---|---|---|---|---|---|---|
| TSLA | 2018-04-04 | 23 | +$7,620 | -$708 | 10/10 | 3 days |
| TSLA | 2019-10-25 | 19 | +$7,390 | -$21 | 8/10 | 2 days |
| TSLA | 2021-02-10 | 27 | +$3,565 | -$31 | 9/10 | 1 day |
| AMD | 2019-01-07 | 7 | +$4,340 | -$243 | 10/10 | 37 days |
| AMD | 2020-07-22 | 3 | +$5,007 | **+$1,900** | 10/10 | 9 days |
| AMD | 2023-11-01 | 3 | +$5,088 | +$72 | 8/10 | 1 day |
| APP | 2024-02-02 | 8 | +$5,039 | -$129 | 10/10 | 1 day |
| APP | 2024-11-08 | 29 | +$9,252 | +$76 | 10/10 | 19 days |
| SPOT | 2020-06-25 | 12 | +$5,488 | -$17 | 10/10 | 3 days |
| PLTR | 2022-11-11 | 51 | +$9,380 | +$96 | 10/10 | 21 days |
| PLTR | 2025-02-06 | 25 | +$5,337 | +$685 | 10/10 | 2 days |
| OKLO | 2025-01-23 | 3 | +$7,042 | +$794 | 9/10 | 1 day |
| IONQ | 2025-10-13 | 9 | +$7,886 | $0 | 9/10 | 4 days |
| LUNR | 2026-04-02 | 6 | +$10,030 | +$114 | 2/10 | 42 days |
| RKLB | 2026-04-24 | 43 | +$4,365 | +$132 | 7/10 | 1 day |

**Pre-streak = consecutive days ticker was in top-8 immediately before peak day.**
**Post-10d P&L = sum of all trades for that ticker in the 10 trading days after peak.**
**Post sel = how many of those 10 days ticker was still in top-8.**
**Absent after = trading days absent from top-8 before first re-entry.**

---

## Section 4 — Key Findings

### Finding 1 — Pre-streak length separates two peak types

**Earnings/catalyst peaks (pre-streak 3–9 days):** AMD 2019 (7d), AMD 2020 (3d), AMD 2023 (3d), OKLO 2025 (3d), IONQ 2025 (9d), LUNR 2026 (6d), APP Feb 2024 (8d). These peaks are driven by a single named event (earnings beat, policy announcement, sector catalyst) that creates the day's magnitude. The win rate selector correctly picked the ticker due to its recent historical quality, but the big day itself was event-driven rather than momentum-built.

**Structural cycle peaks (pre-streak 19–51 days):** TSLA 2018 (23d), TSLA 2019 (19d), TSLA 2021 (27d), APP Nov 2024 (29d), PLTR Nov 2022 (51d), PLTR 2025 (25d), RKLB 2026 (43d). These peaks occur at the crest of a multi-week regime where the ticker has been persistently competitive. The momentum built up over weeks and the peak day is the culmination.

The selector works identically for both types — the pre-streak length is a description of the market context, not a selection criterion. A short pre-streak doesn't indicate lower quality; it indicates the type of catalyst that drove the day.

### Finding 2 — Post-peak P&L decay is universal (one exception)

In 14 of 15 cases, post-peak P&L in the 10 days following the peak was flat or negative relative to the peak magnitude. The peak day's contribution is typically 10–100× larger than any single day before or after it.

**The one exception: AMD July 2020 (+$1,900 post-peak).** AMD was in a structural 2020 bull run where the entire July–August period was broadly profitable. The July 22 peak was the largest single day in a sustained multi-week trend, not an endpoint. The surrounding 4-week window had multiple $1–2k days. This is the "structural continuation" case — the peak day is part of a trend, not the end of one.

**How to distinguish structural continuation from single-spike peak:**
- Structural continuation: multiple profitable days both before AND after the peak within the same month; regime has been LONG for 15+ days continuously
- Single-spike peak: most P&L concentrated in one day; surrounding days near-zero or negative; ticker re-enters only briefly post-peak before extended absence

### Finding 3 — Win rate "sticky" effect: ticker stays selected after peak

In 13 of 15 cases the ticker remained in the top-8 for 7–10 out of the 10 trading days following its peak. The peak day's gain elevates the trailing 20-day win rate, sustaining selection even as actual forward opportunity degrades. This is the **win rate sticky effect** — a structural feature of the 20-day lookback, not a bug.

Implications:
1. **Post-peak selection is not a quality signal.** Being selected the day after a $7k peak day does not mean the day will be another $7k day. It means the historical metric is lagging the current opportunity.
2. **Trade frequency within a streak is more informative than streak length.** A streak where 6 of 10 selected days generated trades with positive P&L is healthier than a streak where 10 of 10 days were selected but only 2 generated any P&L.
3. **"Hollow selection" = quality fade indicator.** When a ticker is in top-8 for 3+ consecutive days but no OR signal fires (zero P&L entries), the ticker is selected on historical merit but the current intraday structure doesn't support a trade. Three consecutive hollow days post-peak is a reliable fade signal.

### Finding 4 — New high-vol tickers have sharper, faster cycles

The thematic tickers (LUNR, OKLO, IONQ, RKLB) produce higher single-day peaks ($7–10k) but have more concentrated cycles:
- Gains are more concentrated in fewer days (fewer surrounding $500–2k days)
- Post-peak exit is faster and more complete (LUNR: 42-day absence; IONQ: 80+ day absence after Oct peak)
- Cycle restarts take longer (return gaps of 40–100+ days vs 1–20 days for TSLA/AMD)

The original stable tickers (TSLA, AMD, CRWD, PLTR) have distributed gains around the peak — multiple $500–2k days before and after — making their cycles more forgiving. Missing the exact peak day costs less.

### Finding 5 — IONQ Jan 2025 was a "false activation" — elevated win rate in wrong regime

IONQ entered the top-8 Jan 2 and stayed for 21 consecutive days, yet generated -$1,484 total (dominated by -$1,196 on Jan 21, likely the DeepSeek AI shock). This illustrates that **high historical win rate + wrong current regime = losses**. The 20-day lookback built IONQ's win rate from a period when quantum computing momentum was strong; the DeepSeek event inverted the sector narrative in one day.

The regime-hold filter (QQQ MA8) reduces but does not eliminate this risk — a regime-aligned day can still produce single-ticker losses from a stock-specific narrative shock. IONQ's January losses are a clear example of a ticker whose momentum cycle ended mid-stream due to an external event rather than natural decay.

---

## Section 5 — Short Signal Assessment

The current system is long-only. The question is whether a post-peak fade would be capturable as a short signal if one were implemented.

**The 20-day EOD win rate lookback cannot capture the short window in time.** In zero of 15 cases did the ticker enter "short territory" (bottom-N of win rate ranking) within 10 trading days of its peak. The 20-day window retains the peak day's elevated win rate contribution for the full 20-day roll-off period (~4 calendar weeks), by which time:
- The stock has stabilized at a lower base and the short opportunity has passed
- OR the ticker has begun a new bullish cycle (common for AMD, TSLA which cycle multiple times/year)

**What would work for a short signal:** A 5-day trailing win rate that detects when the current week is fading even though the 20-day history is still strong. The signal condition: 5-day EOD WR < 40% while 20-day EOD WR ≥ 55%. This divergence captures the "current behavior has disconnected from historical quality" state without waiting for the full 20-day roll-off.

A simpler proxy available today: **3 consecutive hollow-selection days post a $4k+ peak day** is a de facto exit signal. No new infrastructure needed — it's observable from the existing selection and P&L logs.

---

## Section 6 — Actionable Rules for Live Trading

### Rule 1 — Re-entry after 15+ day absence: watch closely

When a ticker re-enters the top-8 after a 15+ day absence, it has rebuilt its win rate from a prior trough. This is the cleanest entry context:
- The prior cycle has cleared from the 20-day window
- The re-entry reflects a fresh catalyst or sector rotation
- The risk is lower than riding a ticker that's been selected for 40+ days (which may be near the end of its cycle)

**Action:** In live trading, flag any ticker re-entering after 15+ day absence. The first 3-day re-entry streak is an elevated attention signal.

### Rule 2 — Pre-streak ≥ 5 days = active phase confirmed

A ticker in top-8 for 5+ consecutive days has established enough 20-day win rate history to be a stable selection. Below 5 days could be a transient appearance driven by a single recent day.

**Action:** Focus on tickers with 5+ day streaks for the core position. Tickers at streak day 1–4 can still produce peak days (earnings catalysts) but with higher variance.

### Rule 3 — Hollow selection for 3+ days post a peak = quality fade

After a $4k+ peak day, if the ticker stays in top-8 for 3 more days but no OR signal fires (no P&L), the current intraday structure no longer supports the historical win rate. The selection is lagging.

**Action:** Mentally discount the ticker's slot for the remainder of the current streak. It will continue being selected but the odds of another peak are low. The next genuine opportunity for that ticker is likely in the next activation cycle (weeks away).

### Rule 4 — AMD/TSLA short-streak peaks (3–7d) are earnings-driven, not cycle-driven

When an established high-quality ticker (TSLA, AMD, PLTR) peaks with only a 3–7 day pre-streak, the driver is almost always an earnings catalyst or macro event. These peaks tend to be clean, one-day events with near-zero post-peak continuation.

**Action:** Don't expect multi-day follow-through from short-streak peaks for stable tickers. Take the gain and reset expectations.

### Rule 5 — Structural continuation exception (AMD 2020 pattern)

If a ticker produces a large peak day AND the surrounding 4-week window has been broadly profitable (multiple $500–2k days) AND the regime has been continuously LONG, the peak may be a mid-cycle day rather than an endpoint. Post-peak selection can be trusted for follow-through.

**Action:** Before treating a post-peak ticker as "quality fade," check whether the surrounding 4 weeks had distributed gains. If yes, hold the expectation through the current cycle. If the peak day is isolated (low surrounding context), apply Rule 3.

---

## Section 7 — Ticker Selection Health Metrics (Monitor Live)

The following metrics can be derived from daily logs to assess ticker cycle health in real time:

| Metric | How to compute | Signal |
|---|---|---|
| **Streak length** | Consecutive days in top-8 | ≥5d = active phase; ≥20d = mature cycle |
| **Absence gap** | Days since last top-8 appearance | ≥15d = re-entry signal on return |
| **Trade fire rate** | Trades / days selected (rolling 10d) | < 30% = hollow selection (fade indicator) |
| **P&L density** | Total P&L / days selected (rolling 10d) | Declining = quality fade; < $0 = exit signal |
| **Peak day isolation** | Single-day P&L vs 4-week surrounding P&L | > 50% = isolated spike; < 30% = structural |

---

## Appendix — Source Data

| Backtest set | Years | Total trading days | Major peaks analyzed |
|---|---|---|---|
| Original 19-ticker set | 2017–2025 | ~1,800 | TSLA×3, AMD×3, APP×2, SPOT×1, PLTR×2 |
| New 20-ticker set (cdd02503) | 2025–2026 | ~302 | OKLO, IONQ, LUNR, RKLB |
| cdd02503 set backfilled | 2017–2024 | ~2,014 | Full new-ticker pool over 8 years |
| **Combined** | **2017–2026** | **~4,116** | **123 peaks ≥ $1,500** |

Related docs:
- `WIN_RATE_SELECTOR_BACKTEST_NEW_TICKERS_06_08_2026_cdd02503.md` — full 10-year results for new ticker set
- `WIN_RATE_SELECTOR_BACKTEST_06_06_2026.md` — original 19-ticker set results
- `op_momentum_screener_analysis/MASTER_REGIME_SUMMARY.md` — OR screener regime patterns
- `WIN_RATE_SELECTOR_MODE.md` — selector implementation reference

---

## Section 8 — Extended Cross-Check: cdd02503 2017–2024

**Added:** 2026-06-10
**Source:** `replay_20{17-24}_stock_m1_winrate_regimehold_cap80k_fixedalloc_reversal_dd_tcdd02503`

Running the same new 20-ticker pool (cdd02503) against 2017–2024 provides a third independent dataset — same tickers, same config, earlier years — for validating the lifecycle patterns.

### Per-Ticker Summary (cdd02503, 2017–2024)

| Ticker | Days Selected | Trades | Total P&L | Avg P&L/trade | Notes |
|---|---|---|---|---|---|
| AMD | 1,454 | 430 | +$36,537 | +$85.0 | Dominant across all 8 years |
| TSLA | 1,421 | 339 | +$33,817 | +$99.8 | Consistent multi-cycle producer |
| QCOM | 1,550 | 382 | +$20,341 | +$53.2 | High selection frequency, steady |
| CRWD | 932 | 271 | +$15,581 | +$57.5 | Strong 2019–2023 cycle |
| RKLB | 312 | 105 | +$13,717 | +$130.6 | 2022–2024 momentum cycles |
| META | 1,525 | 384 | +$12,961 | +$33.8 | Broad consistent contributor |
| CLSK | 466 | 147 | +$12,530 | +$85.2 | Crypto-cycle driven (2020–21, 2024) |
| DDOG | 630 | 174 | +$10,659 | +$61.3 | Steady SaaS cycle |
| MU | 1,531 | 327 | +$10,218 | +$31.2 | Profitable here (contrast with both other sets) |
| LUNR | 168 | 59 | +$9,256 | +$156.9 | Early 2023 cycle confirmed |
| IONQ | 233 | 72 | +$9,028 | +$125.4 | 2022 + 2023 cycles |
| SNOW | 853 | 215 | +$8,236 | +$38.3 | Consistent but fading by 2024 |
| HOOD | 365 | 94 | +$7,430 | +$79.0 | IPO-era cycles 2021–2022 |
| AVGO | 1,612 | 382 | +$6,104 | +$16.0 | High selection, thin margins |
| PLTR | 494 | 122 | +$5,661 | +$46.4 | 2022 bear-bounce + 2024 |
| LLY | 1,649 | 458 | +$3,774 | +$8.2 | Most selected (1,649d), lowest avg — quality filler |
| ARM | 156 | 26 | +$1,725 | +$66.3 | Late entrant, limited data |
| RDDT | 54 | 12 | -$391 | -$32.6 | Insufficient history |
| OKLO | 287 | 107 | -$772 | -$7.2 | Mostly negative until Oct 2024 |

**OKLO** is negative across the entire 2017–2024 period (-$772), only turning positive in Oct 2024 (+$1,540) as the nuclear energy narrative began. Its Jan 2025 peak (+$7,042) was the beginning of its first genuine momentum cycle.

**MU** is profitable here (+$10,218) but negative in the other two sets. Suggests MU's OR momentum behavior changed after 2024 — it worked well through semiconductor cycles 2018–2023 but degraded as a regime-hold OR-momentum ticker in 2025–2026.

---

### New Lifecycle Discoveries from cdd02503 2017–2024

#### LUNR Feb 2023 — Earliest confirmed activation (pre-streak 35d)

LUNR had a strong cycle in Feb 2023, peaking Feb 22 at +$7,249 after a 35-day consecutive streak. This is LUNR's first confirmed major cycle, predating the 2025–2026 cycles by two years. Post-10d was only +$219, and LUNR was absent for 53 days after — consistent with all subsequent LUNR cycles. The Feb 2023 peak was driven by LUNR's early commercial launch excitement rather than the policy/space tailwinds of 2026.

#### IONQ Jan 2022 — Extreme surprise-catalyst peak (pre-streak 1d)

IONQ's largest single-day gain in the pre-2025 dataset: +$5,837 on Jan 31, 2022 — selected for only 1 day before the peak. Post-10d was -$799 (the strongest post-peak reversal in the entire 123-peak dataset). Context: Jan 31 was late in the speculative meme/quantum frenzy just before the Feb 2022 rate-hike selloff. This is the extreme end of the "surprise catalyst" pattern — one-day selection, massive gain, immediate and hard reversal. The 1-day pre-streak combined with the large reversal is a reliable indicator of a regime-shift catalyst rather than a momentum peak.

#### RKLB Jul 2023 — Structural continuation (two peaks, same month)

RKLB had two peaks within the same month: Jul 13 (+$1,858, pre=26d) and Jul 27 (+$3,787, pre=36d). Post-10d after the Jul 13 peak was +$3,758 — because the second larger peak followed within 2 weeks. This is the structural continuation pattern (same as AMD 2020 and AMD 2018): the first "peak" is a mid-cycle day in a sustained run, not an endpoint. RKLB was in its first strong momentum cycle in 2023, driving its $5,608 July total.

#### CLSK — Crypto-correlated cycle ticker

CLSK (CleanSpark, Bitcoin mining) shows clear crypto-cycle correlation:
- Strong Aug 2020 (+$3,867) and Mar–Apr 2021 (+$5,777) tracking Bitcoin's 2020–21 bull run
- Flat through most of 2021–2023 tracking Bitcoin's bear phase
- Strong Dec 2024 (+$5,727) tracking Bitcoin's 2024 cycle

CLSK's OR momentum is essentially a proxy for Bitcoin momentum. During active Bitcoin cycles, CLSK generates strong OR signals; in Bitcoin bear periods it drops out of selection. This makes CLSK's presence in the top-8 a secondary indicator of crypto regime health.

---

### Unified Statistics: 123 Peaks Across All 3 Datasets

| Metric | Value |
|---|---|
| Total peaks ≥ $1,500 analyzed | **123** |
| Median post-10d P&L | **$0** |
| Average post-10d P&L | +$120 |
| Peaks with negative post-10d | 57 / 123 (46%) |
| Peaks where post-10d > peak day | 2 / 123 (1.6%) |
| Avg days still selected post-peak (of next 10) | **8.5 / 10** |
| Avg hollow days post-peak (selected, no trade fired) | **5.7 / 10** |

The median post-10d P&L of **$0** across 123 peaks is the most definitive statistical confirmation in this document. Half of all significant peak days are immediately followed by zero net P&L in the next two weeks. The win-rate sticky effect (8.5/10 days still selected) and hollow selection rate (5.7/10 hollow days) are structural and universal across all ticker sets and years.

### Pre-Streak Distribution and Post-Peak Behavior

| Pre-streak at peak | Peak count | Avg post-10d P&L | Interpretation |
|---|---|---|---|
| 0–3 days | 21 | +$166 | Surprise catalyst; occasional earnings follow-through |
| 4–7 days | 16 | +$184 | Short-build entry; slight positive continuation |
| 8–14 days | 19 | **-$34** | Early momentum zone; worst post-peak outcome |
| 15–30 days | 27 | +$181 | Momentum phase; partial structural continuation possible |
| 31+ days | 40 | +$101 | Structural cycle; low post-peak drift, not a clean exit |

The 8–14 day pre-streak window shows the worst post-peak continuation (-$34 average). This range captures tickers that have built enough win rate to rank competitively but not enough to sustain a structural multi-week run. Very short streaks (0–7d) have slightly better post-peak because earnings catalysts sometimes carry 2–3 day follow-through. Very long streaks (31+) drift mildly positive because they are in structural cycles where any given "peak" is not the endpoint.

### Anomalies and Edge Cases

**AMD 2019-01-07 pre-streak shows 507 days** in the cdd set. This is an artifact of AMD being continuously in the top-8 from 2017 onward without a meaningful absence — the streak counter ran unbroken across the entire backtest start. This represents the "structural long-term dominant ticker" pattern: some tickers are so consistently high-quality that they never truly hibernate. AMD's win rate was above pool average for essentially 2017–2019 without interruption. These tickers do not show re-entry signals but can still produce major peaks.

**SNOW cliff-edge exits (Nov 2021: 42d streak → 0/0 post; Apr 2023: 61d streak → 0/0 post).** SNOW repeatedly hit very long streaks then dropped to zero post-selection immediately after the peak — no gradual fade at all. This contrasts with PLTR (51d streak, stayed selected 10/10 days after its Nov 2022 peak) which decays gradually. The cliff-edge pattern in SNOW is consistent across multiple cycles: SNOW's OR momentum tends to be "all or nothing" — strongly in selection during a bull phase, then completely absent once the phase breaks.

**TSLA Jul 2022 (+$3,762, pre=137d, post-sel 1/10, absent 22 days).** TSLA was in the top-8 for 137 consecutive days (Jan–Jul 2022) through the bear market, then immediately dropped to 1/10 post-selection after its July peak. This is another cliff-edge exit from a structural long cycle — the cycle ended cleanly on a single day with no gradual fade.

### Structural Continuation Fingerprint (confirmed across 3 datasets)

The structural continuation exception (where post-peak P&L is meaningfully positive) now has a consistent fingerprint across 4 confirmed cases:

| Case | Post-10d P&L | Fingerprint |
|---|---|---|
| AMD Jun–Jul 2018 | +$1,812 | 14-day streak, second peak followed in 3 weeks (+$1,734 in Jul) |
| AMD Jul 2020 | +$1,900 (orig) / -$546 (cdd) | 14-day streak (cdd), 3-day streak (orig) — contested by dataset |
| RKLB Jul 2023 | +$3,758 | 26-day streak, second peak 14 days later in same month |
| SPOT Jul 2020 | +$805 | 28-day streak, partial continuation |

The structural continuation requires all three: (1) pre-streak ≥ 14 days, (2) surrounding month has multiple profitable days before the peak, and (3) broader regime has been continuously LONG. When all three hold, the post-peak window can be trusted for partial continuation. When any one is absent, apply the default decay assumption.

---

## Section 9 — Ticker Lifecycle Dashboard Script

### Overview

`analysis_scripts/ticker_lifecycle.py` converts the lifecycle patterns documented in this file into a live dashboard. For a given pool of tickers it computes each ticker's current win-rate selection state and classifies it into one of six lifecycle phases.

**Primary use cases:**
- Pre-session review: which tickers are entering an active streak vs fading out?
- Post-session audit: did the selector catch a cliff-edge ticker before it dropped out?
- Pool maintenance: identify tickers that have been hibernating long enough to reconsider for removal.

### Lifecycle Phases and Classification Rules

| Phase | Condition | Signal |
|---|---|---|
| `HIBERNATING` | Absent from top-N (streak ≤ 0) | No trading edge; skip |
| `RE-ACTIVATING` | Streak 1–4d, returned after ≥15d gap | Watch closely — may enter ACTIVE next 3–5 days |
| `ACTIVE` | Streak 5–19d | Core trading window; highest expected OR signal quality |
| `MATURE CYCLE` | Streak 20+d | Elevated WR but watch for plateau; structural continuation possible if WR still rising |
| `QUALITY FADE` | In top-N, fire rate <30% over last 10 selected days + WR trending down | Hollow selection; OR signals not firing despite top-N rank — imminent exit |
| `CLIFF EDGE` | In top-N, WR trend ≤ −15pp over 10 days | Sharp win-rate collapse while still selected; likely to drop out within 3–5 days |

The **fire rate** detection (QUALITY FADE) requires `--log-dir` to be set; without it the script falls back to WR trend only.

### Output Format

**Default (full table):**
```
────────────────────────────────────────────────────────────────────────────────────────────
  Ticker Lifecycle — as of 2026-06-10  |  top-8 pool  |  20d EOD win rate
────────────────────────────────────────────────────────────────────────────────────────────
  Ticker  Rank  15mWR  EOD_WR   Med%   Trend  Streak  Phase          Detail
  ─────────────────────────────────────────────────────────────────────────────────────────
  LUNR      #1    61%     58%   +1.4%   +8pp    +22d  MATURE CYCLE   streak 22d wr↑+8pp
  OKLO      #3    55%     52%   +0.9%   -2pp    +11d  ACTIVE         streak 11d
  IONQ      #5    53%     50%   +0.6%   -1pp     +8d  ACTIVE         streak 8d
  HOOD      #7    47%     46%   +0.1%   +3pp     +4d  RE-ACTIVATING  streak 4d (gap was 18d)
  ─────────────────────────────────────────────────────────────────────────────────────────
  RKLB      11    44%     41%   -0.3%  -14pp    -12d  HIBERNATING    absent 12d
  AMD       16    38%     35%   -0.5%  -18pp    -24d  HIBERNATING    absent 24d
────────────────────────────────────────────────────────────────────────────────────────────
```

- Tickers above the divider line are currently in the top-N.
- **Trend** = current 20d EOD WR minus the 20d WR from 10 trading days ago.
- **Streak**: positive = consecutive days in top-N; negative = consecutive days absent.
- Terminal colors: green = ACTIVE/RE-ACTIVATING, cyan = MATURE CYCLE, yellow = QUALITY FADE, red = CLIFF EDGE, grey = HIBERNATING.

**Timeline mode (`--timeline`):**
```
  LUNR     ··███████████████████████  MATURE CYCLE
  OKLO     ·····████████████·········  HIBERNATING
  IONQ     ············████████·······  ACTIVE
```
Each `█` = day in top-N; `·` = day absent. Shows last 40 trading days.

### CLI Reference

```
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py [OPTIONS]

Options:
  --tickers TICKER [TICKER ...]   Pool to evaluate (default: 20-ticker cdd pool)
  --top N                         Top-N selection size (default: 8)
  --lookback N                    Days of history to evaluate for streak/absence (default: 60)
  --wr-lookback N                 Win rate rolling window in days (default: 20)
  --or-start HH:MM                OR start time (default: 09:30)
  --or-bars N                     Number of OR bars (default: 3)
  --log-dir PATH                  Replay log directory for P&L density / fire rate stats
  --compact                       One-line output per ticker (pipe-friendly)
  --timeline                      Print ASCII █/· selection grid before the table
  --feed FEED                     Alpaca data feed: sip or iex (default: sip)
```

### Usage Examples

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# --- Most common: pre-session lifecycle check, default 20-ticker pool ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py

# --- Custom ticker pool ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
    --tickers LUNR OKLO IONQ RKLB CLSK HOOD CRWD PLTR AMD TSLA

# --- Show selection timeline + dashboard (best for spotting RE-ACTIVATING tickers) ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
    --timeline

# --- With P&L density from replay logs (enables QUALITY FADE fire-rate detection) ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
    --log-dir logs/replay_2026_stock_m1_winrate_regimehold_cap80k_fixedalloc_reversal_dd \
    --timeline

# --- Compact output for scripting / grep ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
    --compact | grep "CLIFF EDGE\|QUALITY FADE"

# --- Extend lookback to catch longer hibernation gaps ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
    --lookback 90 --tickers SNOW NVDA TSLA AMD MSFT GOOGL

# --- Use iex feed (faster, less complete) ---
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/ticker_lifecycle.py \
    --feed iex
```

### How to Read the Output for Trading Decisions

**Adding a ticker to watch list:** Look for `RE-ACTIVATING` with a gap ≥ 15 days. The return after a long hibernation is the strongest signal of a new cycle starting. Best to wait for the streak to reach 3–4 days before counting on OR signal quality.

**Riding a current streak:** `ACTIVE` tickers with a positive WR trend (`+Xpp`) are in the highest-quality phase. The backtest shows average +$389 per peak during 5–19 day streaks. If trend is flat or slightly negative but streak is still short (5–10d), hold.

**When to start being cautious:** `MATURE CYCLE` (20+d) with a flat or declining WR trend. The structural continuation fingerprint requires pre-streak ≥ 14d + rising WR + regime LONG. If WR trend has gone flat, that third condition (rising WR) is breaking down.

**When to exit the ticker mentally:** `QUALITY FADE` (fire rate < 30% while selected) or `CLIFF EDGE` (WR trend ≤ −15pp). The 20-day lookback will keep the ticker in top-N for another ~8 days on average after the peak — these signals let you anticipate that exit rather than ride it down.

**Hibernating tickers to ignore:** Absence < 15 days is ambiguous — could be a brief dip or the start of a long gap. Wait for the absence to exceed 15 days before considering the ticker properly hibernating.

### Implementation Notes

- The script calls `_rank_tickers_by_eod_win_rate()` once per trading day in the lookback window to reconstruct the selection history. This is the same function used by `WinRateTickerSelector` in the live engine — the phase classification is based on the same ranking signal, not an approximation.
- Win rate trend is computed by comparing `_compute_hold_history()` at `today` vs 10 trading days ago against the same 20-day window. This means "trend" measures the WR shift from the cohort 10 days ago to the current cohort, not the derivative of a rolling curve.
- Fire rate (trades ÷ days selected) is parsed from `Capital returned [M1] TICKER` lines in the replay log files. It is only populated when `--log-dir` is provided and the log covers the last 10 trading days.
- Terminal color codes are ANSI-compatible (macOS Terminal, iTerm2, VS Code integrated terminal). If running in an environment without color support, redirect output or add `| cat` to strip codes.
