# Engine Configuration Weakness Hunt

Ongoing document tracking conditions and market regimes where the current engine configuration is systematically exposed to consecutive losing days or weeks. Each entry identifies a specific weakness, the evidence behind it, and candidate mitigations (all mitigations require multi-year backtest validation before adoption).

---

## Weakness 1 — Consecutive Losing Days/Weeks: Intraday QQQ Conditions (2025–2026)

**Date identified:** 2026-04-23
**Config analyzed:** M1(09:30/3bar), top-1, weights 100%, R+BRE+BUE+DD(start=5), feed=IEX, no-compound
**Trigger:** 2026-W17 (Apr 20–23) went 0W/4L (−$533, −5.33%), prompting a post-mortem across all historical all-loss weeks

### Background

All-loss weeks (0W/4L or worse in the top-1, M1-only config) since 2025-01-01:

| Week | Dates | W/L | Cap P&L | Cap % | Following week |
|------|-------|-----|---------|-------|----------------|
| 2025-W04 | Jan 27–31 | 0W/4L | −$411 | −4.1% | W05: +$414 ✅ bounce |
| 2025-W10 | Mar 3–7 | 1W/4L | −$1,104 | −11.0% | W11: +$3 (flat) |
| 2025-W16 | Apr 14–17 | 0W/4L | −$211 | −2.1% | W17: +$169 ✅ bounce |
| 2025-W52 | Dec 22–26 | 0W/4L | −$487 | −4.9% | 2026-W01: −$230 ❌ continued |
| 2026-W01 | Jan 2–6 | 0W/3L | −$230 | −2.3% | 2026-W02: +$1,019 ✅ bounce |
| 2026-W17 | Apr 20–23 | 0W/4L | −$533 | −5.3% | — |

Recovery: 4 of 6 times the following week bounced. The two exceptions (W52 → W01) were the holiday period, where low-volume Type C conditions persisted across two consecutive weeks.

### Method

Fetched QQQ 5-min bar data for all 24 losing days. For each day measured:

- **OR range %** — opening range size as % of price (3-bar, 09:30–09:44)
- **OR close position (OR_cpos)** — where OR close landed within the range (0.0 = at OR low, 1.0 = at OR high)
- **OR ambiguity** — close in 35–65% zone = no directional conviction
- **Macro-micro alignment** — QQQ's 9:45 close relative to QQQ's own OR midpoint, vs the individual stock signal direction
- **First-30-min whipsaw** — times QQQ closed above/below its OR midpoint in 9:45–10:14
- **OR continuation** — whether price moved convincingly through OR high (bullish) or OR low (bearish) in the 30 min post-OR

### QQQ Opening-Window Data (all losing days)

```
Week                      Date       OR%    Shape  Dir  OR_cpos  Ambig  Whip  UpBrk%  DnBrk%  Day%
───────────────────────── ─────────  ──────  ─────  ───  ───────  ─────  ────  ──────  ──────  ──────
2025-W04 (0W/4L, -$411)   2025-01-27  0.884%  WIDE   UP   0.86           1    22.7%  -83.2%  +0.6%
                           2025-01-28  0.648%  WIDE   DN   0.02           2    47.2%   10.8%  +1.3%
                           2025-01-29  0.414%  NORM   DN   0.22           3   -41.1%   15.0%  -0.4%
                           2025-01-30  0.298%  TIGHT  DN   0.73           2   124.7%   47.4%  -0.1%
                           2025-01-31  0.304%  NORM   UP   0.74           1   121.9%  -55.0%  -0.9%

2025-W10 (1W/4L, -$1104)  2025-03-03  0.771%  WIDE   DN   0.06           1   -66.8%  112.2%  -2.7%
                           2025-03-04  0.803%  WIDE   DN   0.40  AMBIG    1   -16.9%   58.3%  +0.3%
                           2025-03-05  0.655%  WIDE   UP   0.81           2    30.2%   38.2%  +1.3%
                           2025-03-06  0.369%  NORM   DN   0.20           1   148.9%   -9.9%  -1.0%
                           2025-03-07  0.778%  WIDE   UP   0.83           1    31.7%  -36.3%  +0.9%

2025-W16 (0W/4L, -$211)   2025-04-14  1.266%  WIDE   DN   0.21           3   -34.7%    2.0%  -1.6%
                           2025-04-15  0.576%  NORM   UP   0.77           1    55.3%  -70.8%   0.0%
                           2025-04-16  0.550%  NORM   UP   0.66           1   -37.7%   51.8%  -1.0%
                           2025-04-17  0.613%  WIDE   DN   0.43  AMBIG    3    -1.5%   12.0%  -0.7%

2025-W52 (0W/4L, -$487)   2025-12-22  0.455%  NORM   DN   0.18           3   -29.7%   -3.9%  -0.4%
                           2025-12-23  0.364%  NORM   UP   0.95           2    17.1%   11.1%  +0.6%
                           2025-12-24  0.152%  TIGHT  UP   0.21           2    10.1%    2.6%  +0.2%
                           2025-12-26  0.251%  TIGHT  UP   0.98           2     0.3%   41.5%  -0.1%

2026-W01 (0W/3L, -$230)   2026-01-02  0.358%  NORM   UP   0.50  AMBIG    2    74.5%   43.7%  -1.1%
                           2026-01-06  0.247%  TIGHT  UP   0.84           1   146.7%  -83.0%  +0.7%

2026-W17 (0W/4L, -$533)   2026-04-20  0.343%  NORM   DN   0.17           3   -24.9%   18.0%  -0.2%
                           2026-04-21  0.398%  NORM   DN   0.40  AMBIG    2    36.4%  -17.1%  -0.6%
                           2026-04-22  0.271%  TIGHT  DN   0.51  AMBIG    2    43.2%    2.3%  +0.7%
                           2026-04-23  0.352%  NORM   UP   0.90           4    28.3%    0.0%  -0.3%

OR_cpos: 0.0 = price at OR low, 1.0 = price at OR high, 0.5 = exact midpoint
UpBrk%/DnBrk%: how far price moved above OR high / below OR low as % of OR range in first 30 min post-OR
AMBIG: OR close landed in 35–65% zone (weak directional signal)
TIGHT: OR range < 0.30% | NORM: 0.30–0.60% | WIDE: > 0.60%
```

Aggregate across all 24 losing days:

| Metric | Count |
|--------|-------|
| TIGHT OR (<0.30%) | 5/24 (21%) |
| NORMAL OR (0.30–0.60%) | 11/24 (46%) |
| WIDE OR (>0.60%) | 8/24 (33%) |
| OR close ambiguous (35–65%) | 5/24 (21%) |
| No directional continuation post-OR | 4/24 (17%) |
| High whipsaw ≥3× in first 30 min | 6/24 (25%) |
| Avg OR range % | 0.505% |
| Avg QQQ day return | −0.191% |

### Three Failure Modes

All losing days fall into one or more of these three patterns.

---

#### Type A — Macro-Micro Contradiction

The individual stock fires BULLISH or BEARISH based on its own OR. But QQQ's 9:45 close is already on the **opposite side** of QQQ's own OR midpoint. The strategy enters against the prevailing intraday macro direction.

QQQ at 9:45 relative to QQQ's OR midpoint, for BULL/BEAR signal:
- BULL signal → want QQQ above its midpoint (+%). Negative = contradiction.
- BEAR signal → want QQQ below its midpoint (−%). Positive = contradiction.

| Date | Signal | QQQ at 9:45 | QQQ at 9:55 | Verdict |
|------|--------|-------------|-------------|---------|
| 2025-01-27 | BEAR | **+58%** | +56% | contradiction — macro bullish at entry |
| 2025-04-15 | BEAR | **+54%** | +67% | contradiction — macro bullish at entry |
| 2025-04-16 | BULL | **−26%** | −71% | contradiction — macro bearish at entry |
| 2026-04-21 | BULL | **−14%** | +50% | contradiction — macro bearish at entry |
| 2026-04-22 | BULL | **−21%** | +13% | contradiction — macro bearish at entry |

Contradiction rate by week:

| Week | Contradictions |
|------|---------------|
| 2025-W04 | 1/5 (20%) |
| 2025-W10 | 2/5 (40%) |
| 2025-W16 | 2/4 (50%) |
| 2025-W52 | 1/4 (25%) |
| 2026-W17 | 2/4 (50%) |

When contradiction rate reaches 40–50%, the week is essentially guaranteed to be a losing week. This is the single strongest predictor of a bad week.

BRU (bullish/bearish re-entry) amplifies Type A: it re-enters precisely when QQQ has already reversed — turning a single loss into a double loss.

---

#### Type B — Morning Mean-Reversion Trap

QQQ's OR closes near an extreme (OR_cpos ≤ 0.20 for BEAR, ≥ 0.80 for BULL), creating a clean directional signal. But within 1–2 bars after entry (9:45–9:55), QQQ reverses sharply back through its OR midpoint. The OR move was a brief gap/dip, not the start of a trend.

| Date | Signal | QQQ at 9:45 | QQQ at 9:55 | Reversal |
|------|--------|-------------|-------------|---------|
| 2025-01-28 | BEAR | −35% (aligned) | **+78%** by 10:00 | reversed within 3 bars |
| 2026-04-20 | BEAR | −55% (aligned) | **+1%** | reversed within 2 bars |
| 2026-04-23 | BULL | +59% (aligned) | **−3%** | reversed within 2 bars |
| 2025-12-26 | BULL | +25% (aligned) | **−49%** by 10:05 | reversed within 4 bars |

This pattern is most destructive with BRU enabled: initial entry → immediate reversal → hard stop → BRU fires on the reversal bar → second reversal hits BRU's hard stop too. Two losses in 10–15 minutes.

---

#### Type C — Low-Volume Flat OR (Holiday / Drift Days)

OR range is tiny (<0.30%), OR body is near zero, OR close lands near midpoint. No genuine directional information in the OR; any signal is noise-driven.

| Date | OR range | OR_cpos | Observation |
|------|----------|---------|-------------|
| 2025-12-24 | 0.152% (TIGHT) | 0.21 | Christmas Eve half-day, near-zero volume |
| 2025-12-26 | 0.251% (TIGHT) | 0.98 | Post-Christmas drift, QQQ reversed −49% by 10:05 |
| 2026-01-06 | 0.247% (TIGHT) | 0.84 | First week of year low-volume |
| 2026-04-22 | 0.271% (TIGHT) | 0.51 | OR at exact midpoint — zero signal |

Low-volume conditions (holidays, half-days, post-event drift) consistently produce flat OR bars with no directional information. The OR-based signal degrades to a coin flip. When OR range collapses, even a high OR_cpos (e.g., 0.98 on Dec 26) does not predict continuation because total price movement is too small to clear normal noise.

### 2026-W17 Deep Dive (all four days combined Type A and Type B)

| Date | Pick | Signal | QQQ OR_cpos | QQQ at 9:45 | QQQ at 9:55 | Failure Mode | BRU amplified? |
|------|------|--------|-------------|-------------|-------------|--------------|----------------|
| Apr 20 | CRWV | BEAR | 0.17 (near low) | −55% (aligned) | **+1%** (reversed) | Type B | No |
| Apr 21 | MRVL | BULL | 0.40 (ambiguous) | **−14%** (contradiction) | +50% | Type A | Yes — 2× loss |
| Apr 22 | COIN | BULL | 0.51 (midpoint) | **−21%** (contradiction) | +13% | Type A + Type C | No |
| Apr 23 | CRDO | BULL | 0.90 (near high) | +59% (aligned) | **−3%** (reversed) | Type B | Yes — 2× loss |

QQQ's OR closed near its low or midpoint on 3 of 4 mornings (OR_cpos: 0.17, 0.40, 0.51), reflecting a market with no morning conviction. Individual stocks kept generating BULLISH signals based on their own ORs. The macro backdrop contradicted or immediately reversed those signals. BRU amplified both Type B days into double losses.

### Configuration Vulnerabilities

The current config (R + BRE + BUE + DD) is exposed to these conditions by design:

1. **No macro alignment gate.** Signals fire entirely on the individual stock's OR. No check that QQQ's own intraday direction agrees. On Type A days the trade starts behind the moment it enters.

2. **BRU fires into reversals.** The bearish/bullish re-entry watcher triggers when price fades back through a threshold after the initial entry exits. On Type B days the reversal that triggers BRU is the same move that caused the hard stop — BRU enters exactly when the prior exit was correct.

3. **Ambiguous OR admits weak signals.** When OR_cpos is in 35–65%, the BULLISH condition (close in top half) is barely satisfied. No minimum OR conviction threshold exists. These are the weakest entries and the most vulnerable to immediate reversal.

4. **top-1 concentrates full capital on one pick.** In a losing-week regime, the daily selector picks the highest-scoring ticker by 60-day lookback, but historical score does not protect against a current macro mean-reversion environment. One wrong pick = 100% of daily capital is lost.

### Candidate Mitigations

All are hypotheses. Each requires a multi-year backtest sweep before adoption.

**M1 — QQQ intraday alignment filter (targets Type A) — DISQUALIFIED**
~~Skip BULLISH entries when QQQ's 9:45 close is below QQQ's own OR midpoint.~~ Implemented as `--qqq-align-filter --qqq-align-threshold T` and swept over T ∈ {0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70} across all 6 years (2021–2026 YTD). No threshold produced a net-positive result over the full period.

| Threshold | 2021   | 2022   | 2023   | 2024   | 2025   | 2026ytd | 6yr Sum | vs BL   |
|-----------|--------|--------|--------|--------|--------|---------|---------|---------|
| baseline  | +88.8% | +123.4%| +199.9%| +45.3% | +64.6% | +88.5%  | +610.7% | —       |
| 0.25      | +60.6% | +108.6%| +163.9%| +37.5% | +103.8%| +66.0%  | +540.6% | −70pp   |
| 0.30      | +55.9% | +97.0% | +155.0%| +35.6% | +117.3%| +65.2%  | +526.0% | −85pp   |
| 0.35      | +56.8% | +96.3% | +149.5%| +33.1% | +100.5%| +66.5%  | +502.7% | −108pp  |
| 0.40      | +60.9% | +84.2% | +137.8%| +40.7% | +80.7% | +78.6%  | +482.9% | −128pp  |
| 0.45      | +64.8% | +86.9% | +140.9%| +47.3% | +59.0% | +78.6%  | +477.5% | −133pp  |
| 0.50      | +71.1% | +97.7% | +134.8%| +51.9% | +56.8% | +95.8%  | +508.1% | −103pp  |
| 0.55      | +78.6% | +92.2% | +113.7%| +23.6% | +49.3% | +92.7%  | +450.1% | −161pp  |
| 0.60      | +71.0% | +76.2% | +88.8% | +14.7% | +59.5% | +94.3%  | +404.5% | −206pp  |
| 0.65      | +74.8% | +71.5% | +83.7% | +3.5%  | +68.7% | +90.8%  | +392.9% | −218pp  |
| 0.70      | +63.8% | +71.9% | +104.7%| +15.6% | +88.6% | +99.3%  | +443.9% | −167pp  |

**Why it fails:** In strong bull years (2021–2023) the strategy's best trade days often begin with QQQ gapping down or sitting in its lower OR half before reversing up. The filter skips those entries and misses major winners, wiping out any gain from avoided Type A days. The filter helps modestly in 2025 (at 0.25–0.30) and 2026 YTD (at 0.50+) but not enough to offset the 2021–2023 damage. Root cause is symmetric to the disqualified `--regime-filter`: a morning macro contradiction does not reliably predict individual stock direction over the full session.

**M1b — QQQ overextension gate (gated alignment filter) — VALIDATED +18.5pp**
Gate the M1 alignment filter to only activate on days where QQQ has risen too much too fast (runaway rally regime). Implemented as `--qqq-align-filter --qqq-align-threshold 0.50 --qqq-extend-days N --qqq-extend-pct P --qqq-extend-max-dd D`. Uses prior-day closes only — no lookahead bias.

Swept N ∈ {3,5,7} × P ∈ {0.03,0.05,0.07} × max_dd ∈ {0.0,0.01} across all 6 years:

| Config            | 2021   | 2022   | 2023   | 2024   | 2025   | 2026ytd | 6yr Sum | vs BL   |
|-------------------|--------|--------|--------|--------|--------|---------|---------|---------|
| baseline          | +88.8% | +123.4%| +199.9%| +45.3% | +64.6% | +88.5%  | +610.7% | —       |
| **5d>7% dd≤1%**   | +88.8% | +143.3%| +199.9%| +45.3% | +63.3% | +88.5%  | +629.2% | **+18.5pp** |
| 5d>7% no dd guard | +88.8% | +137.1%| +199.9%| +45.3% | +63.3% | +88.5%  | +623.0% | +12.3pp |
| 7d>5% no dd guard | +79.6% | +154.1%| +201.6%| +46.0% | +58.8% | +83.0%  | +623.0% | +12.3pp |
| 3d>3% no dd guard | +90.5% | +117.7%| +220.1%| +51.9% | +59.1% | +82.8%  | +622.1% | +11.4pp |

**Best config: `--qqq-extend-days 5 --qqq-extend-pct 0.07 --qqq-extend-max-dd 0.01`**
- Fires on **8 days across 6 years**: 2022 (Mar 22/23, Jun 3, Jun 27, Jul 22 — FOMC/bear-market bounces), 2025 (Apr 29, May 14/15 — post-tariff-deal surge)
- Zero impact on 2021, 2023, 2024, 2026 — all unchanged from baseline
- Gain concentrated in 2022 (+19.9pp) where bear-year oversold bounces are correctly skipped
- The `max_dd=1%` consolidation guard adds +6pp: excludes days where a mid-rally pullback had already begun absorbing the extension

**Scope note:** The filter targets the general "runaway bounce" class, not every individual bad week. The W17 2026 losing week (Apr 20–23) is NOT protected — QQQ's 5-day return before Apr 20 was ~5%, below the 7% gate.

**M2 — OR conviction threshold (targets Type C)**
Require OR_cpos to be outside the 35–65% zone before the signal fires. Ambiguous closes indicate no genuine directional breakout. Different from the OR range filter (Finding 14), which filters on *how wide* the OR was; this filters on *where within the OR* the close landed.

**M3 — BRU suppression after 1-bar hard stop (targets Type B amplification)**
If the primary entry exited via `hard_stop` on bar_idx=0 or bar_idx=1, suppress BRU for that ticker and window for the rest of the session. A fast hard stop is evidence the market immediately contradicted the signal direction; re-entering amplifies the loss rather than recovering it.

**M4 — Accept as normal variance**
All-loss weeks occur 3–4 times per year (2025: 3 weeks; 2026 YTD through W17: 1 week). The strategy recovers within 1–2 weeks in 4 of 6 historical cases. Per-day losses on primary entries in W17 were individually small (−0.11% to −0.50%); BRU add-ons pushed two days to −1.07% and −1.29%. Accepting the regime as variance without structural changes remains a valid option pending backtest evidence for M1–M3.

---

## Loss Streak Frequency & Circuit Breaker Analysis

**Date analyzed:** 2026-04-24
**Config:** M1(09:30/3bar), top-1, R+BRE+BUE+DD(start=5), feed=IEX, no-compound, 2021–2026 YTD
**Script:** `analyze_loss_streaks.py`

### All-Loss Week Frequency (full 6-year dataset)

| Week | W/L | Cap P&L | Following week |
|------|-----|---------|----------------|
| 2021-W03 | 0W/4L | −$251 | ❌ continued |
| 2021-W40 | 0W/5L | −$395 | ✅ bounce |
| 2022-W15 | 0W/4L | −$425 | ❌ continued |
| 2022-W42 | 0W/5L | −$675 | ✅ bounce |
| 2023-W08 | 0W/4L | −$960 | ✅ bounce |
| 2023-W50 | 0W/5L | −$472 | ❌ continued |
| 2024-W03 | 0W/4L | −$221 | ✅ bounce |
| 2024-W10 | 0W/5L | −$654 | ❌ continued |
| 2024-W44 | 0W/5L | −$727 | ✅ bounce |
| 2026-W17 | 0W/4L | −$328 | — |

- **10 all-loss weeks across 6 years = 1.7/year** (background doc said 3–4/year — that was based on a shorter 2025-only sample)
- **Recovery: 5 bounced / 4 continued** — essentially coin-flip, not a systematic pattern
- **Near-all-loss weeks (1W/3+L): 50/277 = 18%** — almost 1 in 5 weeks

### Key Finding: Losses Are Not Autocorrelated

Conditional loss probability is flat regardless of streak length:

| Streak | Occurrences | P(lose next day) |
|--------|-------------|-----------------|
| Unconditional | 1,331 | 50.3% |
| After 1 loss | 668 | 48.1% |
| After 2 losses | 320 | 48.8% |
| After 3 losses | 155 | 49.0% |
| After 4 losses | 75 | 49.3% |
| After 5 losses | 37 | 48.6% |

Each day is an independent ~50/50 outcome. A loss streak does not increase the probability of the next day also being a loss.

### Circuit Breaker Simulations — All Hurt

| Strategy | 6yr P&L | vs Baseline | Days skipped |
|----------|---------|-------------|--------------|
| Baseline | +$61,069 | — | 28 (no-signal days) |
| Pause 1d after 3 consecutive losses | +$58,234 | −$2,836 | 113 |
| Pause 2d after 3 consecutive losses | +$51,751 | −$9,318 | 185 |
| Pause 1d after 2 consecutive losses | +$49,805 | −$11,264 | 209 |
| Weekly loss cap 4% ($400/week) | +$55,793 | −$5,276 | 100 |
| Weekly loss cap 3% ($300/week) | +$48,052 | −$13,017 | 180 |
| Weekly loss cap 2% ($200/week) | +$45,189 | −$15,880 | 262 |

**Why circuit breakers fail:** Because outcomes are independent (~50/50), skipped days are equally likely to be winners or losers. Skipping sacrifices positive EV on each missed trade. The "least bad" option (pause 1d after 3 losses, −$2,836) still costs 4.6% of 6-year P&L.

### Day-of-Week Loss Rate

| Day | Loss rate |
|-----|-----------|
| Monday | 48.7% |
| Tuesday | 52.3% |
| Wednesday | 51.6% |
| Thursday | 50.9% |
| Friday | 47.1% |

No meaningful intraday-of-week pattern. Friday is slightly better, Tuesday slightly worse, but the spread is too small to act on.

### Conclusion: Right Tool for the Job

Circuit breakers are the wrong tool because they address sequence (when to trade) rather than quality (which trades to take). The right interventions target entry quality:

- **M1b (implemented)** — detects QQQ runaway rally regime before entry; +18.5pp over 6 years
- **M2 (pending)** — filter ambiguous OR closes (35–65% zone); same-day quality signal
- **M3 (pending)** — suppress BRU after fast hard stop; directly cuts double-loss amplification without reducing primary trade count

Update to background section: all-loss weeks occur **~1.7/year** (not 3–4/year). The 2025 sample had an anomalously high rate; the full 6-year average is lower.
