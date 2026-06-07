# Direction-Aware Win-Rate Selector — Verification Plan

**Proposed change:** Replace the current overall-win-rate ranking with separate bullish and bearish win-rate rankings. On LONG regime days rank top-N by trailing bullish WR; on SHORT regime days rank top-N by trailing bearish WR. Add a dual-side floor threshold to suppress tickers that have lost edge on both sides for 2+ consecutive quarters.

**Reference analysis:** `WIN_RATE_SELECTOR_BACKTEST_06_06_2026.md` → Ticker Cycle Analysis section

---

## What Changes in the Engine

### Current behavior
```
pre-market: rank tickers by overall win rate (bull + bear combined)
→ pick top-8
→ regime filter drops signals that don't match day's direction
```

### New behavior
```
pre-market: check today's regime direction forecast
  if LONG  → rank tickers by trailing bullish win rate only
  if SHORT → rank tickers by trailing bearish win rate only
  if CAUTION/NO_POSITION → skip selection entirely (no change)
→ pick top-8 from direction-specific ranking
→ regime filter still applies as safety (no change)

additionally:
  if ticker.bull_wr_trailing_90d < 0.45 AND
     ticker.bear_wr_trailing_90d < 0.45 for 2+ consecutive quarters
  → suppress ticker from selection until either WR recovers
```

### Files likely to change
- `op_momentum_selector_backtest.py` — win-rate ranking logic
- `op_momentum_trade_engine.py` — pre-market ticker selection
- Possibly `signal_engine.py` — needs to track bull/bear WR separately

---

## Implementation Spec

All rules below are derived from 10 years of backtest data (2017–2026, 19 tickers, ~1,200 ticker-years of directional signal history). Numbers are chosen to generalize across conditions, not to fit specific years.

### Rule 1 — Lookback Window: 90 Calendar Days

**Rule:** compute direction-specific WR from the trailing 90 calendar days of completed trades for that direction.

**Derived from data:**
- Tickers average 8–15 directional trades per 90-day window (observed from quarterly counts across all years)
- 30-day window: too few signals (3–5 per direction) — WR swings ±30% on a single trade result
- 180-day window: stale — includes prior-cycle phase data that no longer reflects current behavior (TSLA 2022 bearish WR would still inflate its 2023 bearish ranking well into the year)
- 90 days captures approximately one full market regime cycle (based on regime engine's observed LONG/SHORT rotation cadence)

### Rule 2 — Minimum Directional Trade Count: 10

**Rule:** a ticker's direction-specific WR is only used for ranking if it has completed ≥ 10 trades in that direction within the 90-day window. Below 10, the ticker is excluded from direction-specific ranking.

**Derived from data:**
- From 10-year quarterly analysis: tickers with < 5 directional trades in a quarter showed WR values of 0% or 100% (noise from sample size)
- At 8–10 trades, WR stabilizes within ±10% of its true trailing rate
- Threshold set at 10 (not 5) to add a safety margin against early-year data sparsity
- In practice, most established tickers exceed 10 directional trades per 90 days — this only affects new tickers entering the pool or tickers in very low-signal regimes

**Fallback when below threshold:**
- If ticker has ≥ 20 total trades (bull + bear) in 90 days but fewer than 10 in one direction: use overall WR as proxy for that direction's ranking score
- If ticker has < 20 total trades in 90 days: exclude from pre-market selection entirely until history builds

### Rule 3 — Direction-Specific Scoring Formula

**Rule:** rank by a composite score that weights both win rate and average gain magnitude:

```
direction_score = WR × (1 + avg_pct_of_wins × 2)
```

Where:
- `WR` = trailing 90-day win rate for the relevant direction (0.0–1.0)
- `avg_pct_of_wins` = average % P&L of winning trades only, in that direction, over 90 days

**Why magnitude matters (derived from data):**

| Ticker/Year | Direction | WR | Avg win % | Score | Notes |
|---|---|---|---|---|---|
| TSLA 2021 | Bearish | 64% | +1.015% | 0.64 × (1 + 2.03) = 1.94 | High score — strong bear edge |
| AVGO 2021 | Bearish | 44% | +0.12% | 0.44 × (1 + 0.24) = 0.55 | Low score — weak bear edge |
| DDOG 2025 | Bearish | 72% | +0.471% | 0.72 × (1 + 0.94) = 1.40 | Strong — correctly ranks high on SHORT days |
| DDOG 2025 | Bullish | 33% | +0.112% | 0.33 × (1 + 0.22) = 0.40 | Weak — correctly ranks low on LONG days |

Pure WR ranking would miss the magnitude difference between a ticker that wins 55% at +0.8% average vs one that wins 55% at +0.1% average. The multiplier of 2 on avg_pct is chosen conservatively — it ensures magnitude influences ranking without over-weighting a few lucky large-win outliers.

**Tiebreaker:** when scores are within 0.05 of each other, use trailing vol ratio (signal day volume / 90-day avg volume) as the secondary sort — same tiebreak as the existing selector.

### Rule 4 — Dual-Side Floor Threshold: 45%

**Rule:** a ticker is flagged as "at-risk" when its trailing 90-day WR falls below 45% in a given direction.

**Derived from data:**
- From 10-year scan of all 190 ticker-years: the two genuine "both-sides-dead" cases were AVGO 2020 (43% bull, 36% bear) and MU 2023 (33% bull, 43% bear) — both below 45% on both sides
- All one-sided declines had the weak side in the 28–44% range while the strong side remained 50–77%
- 45% is conservative — it sits above the noise floor (where WR has no predictive power) without prematurely flagging tickers in temporary dips (e.g. AMD 2018 bear WR = 38% but recovered the next quarter)

### Rule 5 — Suppression Trigger: 45 Consecutive Trading Days Both Sides Below 45%

**Rule:** suppress a ticker from pre-market selection when both its bull WR and bear WR have been below 45% continuously for 45 or more trading days (≈ 2 calendar months).

**Why 45 trading days (not calendar quarters):**
- Calendar quarters have variable trade counts — a Q4 with 8 directional trades is too sparse to declare a ticker "dead"
- Rolling 45-day window is data-driven: from the observed trade frequency, 45 trading days guarantees ≥ 8–10 directional trades even in low-signal periods — enough for the WR estimate to be meaningful
- 45 days is long enough to exclude temporary dips: both AVGO 2020 and MU 2023 showed recovery within 60–90 trading days of their worst periods — so 45 days sustained weakness would have triggered suppression, but they would have recovered naturally under Rule 6 without permanent removal

**Why not shorter (e.g. 20 days):**
- AMD bear WR dropped to 38% for a single month in 2020 before recovering — a 20-day window would have incorrectly suppressed it
- The 45-day floor matches the lookback granularity used in Rule 1

### Rule 6 — Suppression Recovery: Either Side Crosses 50% for 20 Trading Days

**Rule:** a suppressed ticker re-enters the pool for its recovered direction when its trailing 90-day WR for that direction has been ≥ 50% continuously for 20 trading days (≈ 1 calendar month).

- Recovery on bull side only → ticker re-enters LONG-day ranking; remains excluded from SHORT-day ranking until bear WR also recovers
- Recovery on bear side only → symmetric
- 20-day recovery window prevents a single good week from prematurely reinstating a ticker
- 50% recovery threshold (vs 45% suppression floor) creates a 5-point hysteresis band — avoids rapid suppression/recovery oscillation around the threshold

**Derived from:** AVGO and MU both showed clean recovery trends lasting 20+ trading days before returning to consistent performance — shorter windows would have resulted in re-suppression on the first volatile week after recovery.

### Rule 7 — Pool Quality Fallback

**Rule:** if fewer than 3 tickers in the pool have valid direction-specific WR (≥ 10 directional trades in 90 days) on the day's regime direction, fall back to overall WR ranking for the full pool.

**Why 3 tickers:**
- With fewer than 3 valid direction-specific scores, top-8 selection would be dominated by fallback logic anyway — it is cleaner to apply the fallback uniformly than to mix direction-specific and overall scores in the same ranking pass
- In practice, this only triggers at the very start of a new year (before 90 days of history build up) or when a new ticker cohort enters the pool — never observed in mature years of the backtest

### Rule 8 — New Ticker Onboarding Grace Period

**Rule:** a ticker added to the pool enters a 90-day grace period during which it is ranked by overall WR (bull + bear combined). Direction-specific ranking activates once it has ≥ 10 trades in each direction within its first 90 days.

**Why:** new tickers entering during a predominantly LONG-regime stretch (e.g. PLTR entering in 2020) may accumulate 20+ bullish trades but only 3–5 bearish ones. Using a bear WR of 3/5 = 60% to rank it on SHORT days would be misleading — the sample is too small. Overall WR is a safer proxy during onboarding.

**Derived from:** CRWD entered the pool mid-2019 with initial trades heavily biased toward LONG-regime days. Using its early bear-only WR (2–3 trades) for SHORT-day ranking would have produced erratic scores.

---

### Summary of Rules

| Rule | Parameter | Value | Basis |
|---|---|---|---|
| Lookback window | 90 calendar days | Balances recency vs sample size; captures one regime cycle |
| Minimum directional trades | 10 per direction in 90d | Below 10, WR swings ±30% on single trade |
| Scoring formula | `WR × (1 + avg_win_pct × 2)` | Magnitude matters — pure WR misses high-avg-win tickers |
| Floor threshold | 45% | Both "both-sides-dead" cases were below 45% on both sides |
| Suppression trigger | 45 trading days both < 45% | Long enough to exclude temporary dips; shorter windows false-fired on AMD 2020 |
| Recovery threshold | 50% for 20 trading days | 5-point hysteresis prevents oscillation; 20d ensures sustained trend |
| Pool fallback | < 3 valid scores → use overall WR | Prevents mixed-score ranking in sparse early-year periods |
| New ticker grace | 90d or until ≥ 10 per direction | Avoids ranking on unstable early directional WR |

---

## Verification Steps

### Step 1 — Unit Tests: Direction-Specific WR Computation

**Goal:** confirm the selector correctly computes and separates bull vs bear win-rate histories.

| Test | Setup | Expected |
|---|---|---|
| Bull WR computed from bullish signals only | Feed 10 bullish signals (7 wins, 3 losses) + 5 bearish (2 wins, 3 losses) | Bull WR = 70%, Bear WR = 40% |
| Bear WR computed from bearish signals only | Same as above | Bear WR = 40% independent of bull history |
| No bullish history yet | Ticker only has bearish signal history | Bull WR = None or 0 — ticker not ranked on LONG days |
| No bearish history yet | Ticker only has bullish signal history | Bear WR = None or 0 — ticker not ranked on SHORT days |
| Rolling window respects lookback period | Feed signals beyond the lookback window | Old signals outside window do not affect current WR |

### Step 2 — Unit Tests: Pre-Market Ranking Logic

**Goal:** confirm the right ranking is applied per regime direction.

| Test | Regime | Ticker pool | Expected top pick |
|---|---|---|---|
| LONG day uses bull WR | LONG | TSLA bull WR=40%, CRWD bull WR=70% | CRWD ranked above TSLA |
| SHORT day uses bear WR | SHORT | TSLA bear WR=77%, CRWD bear WR=50% | TSLA ranked above CRWD |
| Same ticker, different regime | LONG vs SHORT | TSLA (bull=40%, bear=77%) | LONG: TSLA low; SHORT: TSLA high |
| CAUTION regime — no selection | CAUTION | Any pool | No tickers selected |
| Ties broken consistently | LONG | Two tickers with equal bull WR | Deterministic tiebreak (e.g. vol ratio) |

### Step 3 — Unit Tests: Dual-Side Floor Suppression

**Goal:** confirm the retirement threshold triggers and recovers correctly.

| Test | Setup | Expected |
|---|---|---|
| Ticker suppressed when both WR < 45% for 2Q | Set bull WR=40%, bear WR=38% for Q1+Q2 | Ticker excluded from pre-market selection |
| Ticker NOT suppressed after only 1 quarter | Set both WR < 45% for Q1 only | Ticker still eligible in Q2 |
| Ticker recovers when bull WR climbs back | After 2Q suppression, bull WR rises to 52% | Ticker re-enters pool on LONG days |
| Ticker recovers when bear WR climbs back | After 2Q suppression, bear WR rises to 50% | Ticker re-enters pool on SHORT days |
| AVGO 2020 scenario — should NOT be removed | 1 year both WR < 45%, then recovery | No removal triggered (only 1 year, < 2 quarters threshold) |

### Step 4 — Backtest Regression: Known Cycle-Flip Cases

Run the updated selector on years where we know tickers flipped from bull to bear cycle. Confirm slot allocation improved.

**TSLA 2023** (bull WR 40%, bear WR 77%)
- Old behavior: TSLA selected in top-8 on LONG days → wastes slot at 40% WR
- New behavior: TSLA ranked low on LONG days → healthier bull ticker fills slot
- Verify: count of LONG-day TSLA trades should drop; total LONG-day P&L should improve

**DDOG 2025** (bull WR 33%, bear WR 72%)
- Old: DDOG selected on LONG days → 33% WR drag
- New: DDOG dropped from LONG-day top-8 → another ticker takes the slot
- Verify: LONG-day DDOG trade count drops significantly in 2025

**MRVL 2023** (bull WR 39%, bear WR 76%)
- Same pattern — verify MRVL LONG-day count drops, SHORT-day count preserved

| Metric to compare | Baseline (current) | Target (direction-aware) |
|---|---|---|
| LONG-day primary WR | Current | Should increase (weak bull tickers excluded) |
| SHORT-day primary WR | Current | Should increase (weak bear tickers excluded) |
| Total primary P&L | Baseline year P&L | Equal or better |
| Mean RODC | Baseline | Equal or better |
| DW-Sharpe | Baseline | Equal or better (less variance from mismatched slots) |

### Step 5 — Backtest Comparison: Full Year Side-by-Side

Run both configurations (current vs direction-aware) on 2023, 2024, 2025 fixed-alloc and compare full-year metrics.

```bash
# Current (baseline — already have logs)
logs/replay_2023_stock_m1_winrate_regimehold_cap80k_fixedalloc/
logs/replay_2024_stock_m1_winrate_regimehold_cap80k_fixedalloc/
logs/replay_2025_stock_m1_winrate_regimehold_cap80k_fixedalloc/

# New (direction-aware — run after implementation)
logs/replay_2023_stock_m1_winrate_regimehold_cap80k_fixedalloc_diraware/
logs/replay_2024_stock_m1_winrate_regimehold_cap80k_fixedalloc_diraware/
logs/replay_2025_stock_m1_winrate_regimehold_cap80k_fixedalloc_diraware/
```

**Pass criteria:**
- Total P&L ≥ baseline in at least 2 of 3 years
- Mean RODC ≥ baseline in at least 2 of 3 years
- DW-Sharpe ≥ baseline in at least 2 of 3 years
- No year shows a >10% P&L regression vs baseline (directional change, not rounding)

### Step 6 — Audit: Slot Allocation Quality

Use `audit_fixedalloc_backtest.py` extended with a new check:

**New Check 9 — Direction alignment:**
On every LONG regime day, verify no selected ticker had a trailing bull WR below 45% at selection time (i.e., the selector correctly excluded weak bull tickers).
On every SHORT regime day, verify no selected ticker had a trailing bear WR below 45%.

```python
# Pseudo-code for the new audit check
for each trading day:
    regime = get_regime(day)
    for each ticker selected that day:
        if regime == LONG:
            assert ticker.bull_wr_at_selection >= 0.45 or no_bull_history
        if regime == SHORT:
            assert ticker.bear_wr_at_selection >= 0.45 or no_bear_history
```

**New Check 10 — Suppression correctness:**
Verify no suppressed ticker appears in any selection during its suppression window.

---

## Edge Cases to Watch

| Case | Risk | How to detect |
|---|---|---|
| New ticker with < 20 bull signals | Bull WR unstable — may rank too high or too low | Add minimum-trades guard before using direction-specific WR |
| Regime flip mid-day | Selection was made as LONG, regime updated to SHORT intraday | Selection is pre-market only — intraday regime changes should not re-rank |
| All top-8 tickers have weak bull WR on a LONG day | Pool quality collapsed — may select 0 tickers | Log warning; fall back to overall WR ranking if fewer than 3 tickers have valid bull WR history |
| Ticker has only SHORT-regime history | Enters pool mid-year during bearish stretch | Bull WR undefined — exclude from LONG days until sufficient history builds |
| 2-quarter suppression window crosses year boundary | Q3+Q4 of one year triggers suppression in Q1 next year | Suppression window must be calendar-based, not year-reset |

---

## Success Definition

The change is considered verified and ready to deploy when:

1. All unit tests in Steps 1–3 pass
2. Known cycle-flip tickers (TSLA 2023, DDOG 2025, MRVL 2023) show reduced LONG-day trade count with no overall P&L regression
3. Full-year backtest (Step 5) meets pass criteria on all 3 test years
4. Audit checks 9 and 10 pass on all backtest years
5. No edge case from Step 6 triggers unexpected behavior in the logs
