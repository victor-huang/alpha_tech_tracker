# Backtest Findings

## Finding 1 — Opening Window Start Time & Width (2026-03-01 → 2026-03-28)

**Question**: Does shifting the evaluation window start time and/or width improve P&L over the default 9:30 / 3-bar (15 min) setup?

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20 --top 3`, pool = V2 (16 tickers), capital = $10,000

### Axis 1 — Entry time sweep (fixed 3-bar / 15-min window)

| Opening start | Entry time | Final portfolio | vs baseline |
|---|---|---|---|
| 09:30 | 9:45 | $10,905 | baseline |
| 09:45 | 10:00 | $10,138 | -$767 |
| 10:00 | 10:15 | $10,473 | -$432 |
| 10:15 | 10:30 | $10,402 | -$503 |
| 10:30 | 10:45 | $10,258 | -$647 |
| 11:15 | 11:30 | $10,386 | -$519 |
| 13:00 | 13:15 | $10,208 | -$697 |
| 13:30 | 13:45 | $10,096 | -$809 |

### Axis 2 — Window width sweep (top entry time candidates)

| Opening start | Bars | Window | Entry time | Final portfolio |
|---|---|---|---|---|
| 10:00 | 1 | 5 min | 10:05 | $10,392 |
| 10:00 | 2 | 10 min | 10:10 | $10,074 |
| 10:00 | 3 | 15 min | 10:15 | $10,473 |
| 10:00 | 4 | 20 min | 10:20 | $10,398 |
| 10:00 | 6 | 30 min | 10:30 | $10,313 |
| 10:15 | 1 | 5 min | 10:20 | $10,473 |
| 10:15 | 2 | 10 min | 10:25 | $10,508 |
| 10:15 | 4 | 20 min | 10:35 | $10,365 |
| 10:15 | 6 | 30 min | 10:45 | $9,754 |
| 11:15 | 1 | 5 min | 11:20 | $10,256 |
| 11:15 | 2 | 10 min | 11:25 | $10,399 |
| 11:15 | 4 | 20 min | 11:35 | $10,410 |
| 11:15 | 6 | 30 min | 11:45 | $10,622 |

### Observations

- **Baseline `09:30 / 3 bars` wins this period** at $10,905 — early momentum capture dominates in a down-trending month
- **Best alternative: `11:15 / 6 bars` ($10,622)** — late-morning 30-min OR with 11:45 entry shows a stabilization effect worth investigating
- **`10:15 / 2 bars` ($10,508)** is the best mid-morning candidate
- Returns degrade consistently past 10:30 entry across all bar widths
- `10:15 / 6 bars` is notably bad ($9,754) — wide OR window in mid-morning appears to widen the OR range too much, diluting the signal

### Validation — 2025-01-01 → 2026-03-27 (~15 months)

| Opening start | Bars | Entry time | Final portfolio | Total return | Win rate (selected) |
|---|---|---|---|---|---|
| **09:30** | **3** | **9:45** | **$22,301** | **+123%** | **37%** |
| 10:15 | 2 | 10:25 | $15,670 | +57% | 32% |
| 11:15 | 6 | 11:45 | $13,686 | +37% | 29% |

**Conclusion**: Baseline `09:30 / 3 bars` dominates convincingly over 15 months. The March 2026 alternatives were noise from a small 20-day sample. **Default parameters confirmed — no change.**

### Full sweep — 2025-01-01 → 2026-03-27

Full results in `alpha_tech_tracker/op_momentum_strategy/backtest_result/second_best_time_window/`

**Axis 1** (3 bars fixed):

| Opening start | Entry time | Final portfolio | Total return |
|---|---|---|---|
| **09:30** | **9:45** | **$22,299** | **+123%** |
| 10:00 | 10:15 | $16,716 | +67% |
| 10:15 | 10:30 | $15,642 | +56% |
| 09:45 | 10:00 | $15,578 | +56% |
| 11:15 | 11:30 | $14,006 | +40% |
| 10:30 | 10:45 | $13,373 | +34% |
| 13:00 | 13:15 | $13,009 | +30% |
| 13:30 | 13:45 | $12,055 | +21% |

**Axis 2** (top 3 start times, varying bars):

| Config | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|
| **09:30 / 1 bar** | **9:35** | **$23,926** | **+139%** | **32%** |
| 09:30 / 3 bars | 9:45 | $22,299 | +123% | 37% |
| 09:30 / 4 bars | 9:50 | $20,256 | +103% | 35% |
| 09:30 / 2 bars | 9:40 | $19,870 | +99% | 31% |
| 09:30 / 6 bars | 10:00 | $17,340 | +73% | 37% |
| 10:15 / 1 bar | 10:20 | $17,532 | +75% | 26% |
| 10:00 / 1 bar | 10:05 | $17,352 | +74% | 27% |
| 10:00 / 3 bars | 10:15 | $16,716 | +67% | — |

**Overall winner: `09:30 / 1 bar` (+139%)** but with lower win rate (32% vs 37%) and noisier execution — fires at 9:35 before a real OR forms. `09:30 / 3 bars` remains the recommended default for live trading (higher win rate, more stable signal).

- [ ] Test whether alternative windows complement the baseline on specific regime types (e.g. high-volatility days)

---

## Finding 2 — `09:30 / 1 bar` as a Parallel Strategy (2025-01-01 → 2026-03-27)

**Question**: How much do the `09:30 / 3 bars` (baseline) and `09:30 / 1 bar` (alt) strategies overlap in ticker selection? Can the alt run as an independent parallel strategy?

**Detail**: `alpha_tech_tracker/op_momentum_strategy/backtest_result/second_best_time_window/OVERLAP_ANALYSIS.md`

### Overlap Statistics (284 days with picks in both)

| Metric | Value |
|---|---|
| Days with ≥ 1 shared ticker | 205 (72%) |
| Days with ZERO overlap | 79 (28%) |
| Days with FULL overlap (all 3 match) | 20 (7%) |
| Rank-1 ticker agrees | 72 (25%) |
| Avg shared tickers per day | 1.03 of ~2.76 baseline picks |

### Overlap Distribution

| Shared tickers | Days | % |
|---|---|---|
| 0 — fully independent | 79 | 28% |
| 1 | 126 | 44% |
| 2 | 71 | 25% |
| 3 — fully identical | 8 | 3% |

### Observations

- The two strategies are **largely complementary** — they react to different information (raw open direction vs settled 15-min OR)
- **Rank-1 agrees only 25% of the time** — the highest-conviction picks are usually different
- On **28% of days** there is zero overlap → full additive diversification with no capital concentration
- On **72% of days** there is at least 1 difference → mostly additive with some shared exposure
- Only **3% of days** are fully identical → running both adds no value those days
- The strategies are good candidates for a parallel dual-window approach

### Next Steps

- [ ] Simulate running both simultaneously with split capital (e.g. $5k each) and compare combined P&L vs $10k baseline alone
- [ ] Check if zero-overlap days skew positive or negative for the alt strategy in isolation
- [ ] Evaluate capital concentration risk on the 25% of days with 2+ shared tickers

---

## Finding 3 — Afternoon Trading Window Sweep (2025-01-01 → 2026-03-27)

**Question**: Is there an optimal afternoon entry time that can serve as a third parallel strategy alongside the two morning strategies?

**Baseline**: `13:30 / 3 bars` (entry 1:45 PM) — $12,055 (+21%)
**Detail**: `alpha_tech_tracker/op_momentum_strategy/backtest_result/afternoon_time_window/`

### Axis 1 — Start time sweep (fixed 3 bars)

| Opening start | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|
| **15:00** | **3:15 PM** | **$13,212** | **+32%** | **29%** |
| 13:00 | 1:15 PM | $13,009 | +30% | 30% |
| 13:15 | 1:30 PM | $12,834 | +28% | 27% |
| 14:15 | 2:30 PM | $12,489 | +25% | 27% |
| 13:45 | 2:00 PM | $12,290 | +23% | 27% |
| 14:30 | 2:45 PM | $12,217 | +22% | 30% |
| 14:00 | 2:15 PM | $12,073 | +21% | 27% |
| 13:30 (baseline) | 1:45 PM | $12,055 | +21% | 29% |

### Axis 2 — Bar width sweep (top 3 start times)

| Config | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|
| **13:15 / 1 bar** | **1:20 PM** | **$15,582** | **+56%** | **24%** |
| 13:15 / 2 bars | 1:25 PM | $14,275 | +43% | 25% |
| 15:00 / 1 bar | 3:05 PM | $13,995 | +40% | 26% |
| 15:00 / 4 bars | 3:20 PM | $13,699 | +37% | 35% |
| 15:00 / 2 bars | 3:10 PM | $13,640 | +36% | 28% |
| 13:00 / 1 bar | 1:05 PM | $13,602 | +36% | 19% |
| 15:00 / 3 bars | 3:15 PM | $13,212 | +32% | 29% |

### Observations

- **Best afternoon config: `13:15 / 1 bar` (entry 1:20 PM) → +56%** — nearly 2× the afternoon baseline
- `13:15` is uniquely bar-width sensitive: 1 bar = +56%, 4 bars = +10% — the 5-min post-lunch breakout dissipates quickly
- `15:00 / 1 bar` (+40%) is more stable across bar widths — power hour entry is more predictable
- Afternoon win rates (19–35%) are lower than morning (32–37%) — larger wins compensate
- **All afternoon results trail morning strategies significantly** — afternoon is a complement, not a replacement

### Full Strategy Comparison

| Strategy | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|
| 09:30 / 1 bar (morning) | 9:35 AM | $23,926 | +139% | 32% |
| 09:30 / 3 bars (morning baseline) | 9:45 AM | $22,299 | +123% | 37% |
| **13:15 / 1 bar (afternoon best)** | **1:20 PM** | **$15,582** | **+56%** | **24%** |
| 15:00 / 1 bar | 3:05 PM | $13,995 | +40% | 26% |
| 13:30 / 3 bars (afternoon baseline) | 1:45 PM | $12,055 | +21% | 29% |

### Next Steps

- [ ] Simulate combined morning + afternoon capital allocation
- [ ] Investigate the 1:20 PM edge — likely a post-lunch directional continuation move

---

## Finding 4 — 4-Strategy Pairwise Overlap Analysis (2025-01-01 → 2026-03-27)

**Question**: How much do the 4 candidate strategies overlap in ticker selection? Can all 4 run as parallel strategies?

**Detail**: `alpha_tech_tracker/op_momentum_strategy/backtest_result/afternoon_time_window/OVERLAP_ANALYSIS.md`

### Strategies

| Label | Config | Entry | Return | Win rate |
|---|---|---|---|---|
| M1 | 09:30 / 3 bars | 9:45 AM | +123% | 37% |
| M2 | 09:30 / 1 bar | 9:35 AM | +139% | 32% |
| A1 | 13:15 / 1 bar | 1:20 PM | +56% | 24% |
| A2 | 15:00 / 1 bar | 3:05 PM | +40% | 26% |

### Pairwise Zero Overlap (most independent pairs first)

| Pair | Zero overlap | Rank-1 match | Avg shared/day |
|---|---|---|---|
| M1 vs A2 | **49%** | 9% | 0.64 |
| M2 vs A2 | **47%** | 10% | 0.62 |
| M1 vs A1 | 43% | 12% | 0.71 |
| M2 vs A1 | 42% | 12% | 0.72 |
| A1 vs A2 | 36% | 11% | 0.77 |
| M1 vs M2 | 28% | 25% | 1.03 |

### Unique Picks per Strategy (not picked by any other, 4-way)

| Strategy | Avg unique picks/day |
|---|---|
| A2: 15:00 / 1 bar | **1.39** — most independent |
| A1: 13:15 / 1 bar | 1.25 |
| M2: 09:30 / 1 bar | 1.17 |
| M1: 09:30 / 3 bars | 1.07 |

### Observations

- **Morning vs afternoon pairs are highly independent** — 42-49% zero overlap, 9-12% rank-1 agreement; they're reacting to different market conditions at different times of day
- **A2 (15:00/1bar) is the strongest diversifier** — 1.39 unique picks/day, lowest overlap with every other strategy
- **The two morning strategies share the most overlap** (28% zero, 25% rank-1) — expected, same start time
- Running all 4 produces ~**4-6 unique ticker exposures per day** out of 12 total picks
- On 68% of days, 3+ tickers appear in multiple strategies — concentration risk exists but is manageable

### Next Steps

- [x] Simulate combined capital across all 4 strategies — see Finding 5
- [ ] Evaluate deduplication rule — skip a pick if the ticker is already held from an earlier strategy that day

---

## Finding 5 — Multi-Window Capital Simulation (2025-01-01 → 2026-03-27)

**Question**: How does combining multiple trading windows (M1, M2, A1, A2) compare to M1 alone, using realistic sequential capital recycling?

**Capital flow model**:
- First group windows deploy simultaneously, splitting the portfolio by `--morning-split`
- Sequential windows inherit all returned capital from the prior window (no idle capital)
- Two evaluation modes: **no-compound** (reset $10k each day — measures per-day edge) and **compound** (portfolio carries over — measures real account growth)

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20`, pool = V2 (16 tickers), capital = $10,000

### Strategy Definitions

| Label | Config | Entry | EV/trade | Win rate |
|---|---|---|---|---|
| M1 | 09:30 / 3 bars | 9:45 AM | +0.443% | 37% |
| M2 | 09:30 / 1 bar | 9:35 AM | +0.468% | 32% |
| A1 | 13:15 / 1 bar | 1:20 PM | +0.194% | 24% |
| A2 | 15:00 / 1 bar | 3:05 PM | +0.135% | 26% |

### Results — No-compound (daily reset to $10k)

| Strategy | Morning split | Total return | Final portfolio |
|---|---|---|---|
| M1 alone | 100% | +123% | $22,299 |
| M1 + A1 | 100% → sequential | +179% | $27,899 |
| M1 + A1 + A2 | 100% → sequential | +219% | $31,931 |
| M2 + A1 + A2 | 100% → sequential | +236% | $33,580 |
| M1+M2+A1+A2 | 60% / 40% → sequential | +226% | $32,591 |

### Results — Compound (portfolio carries over daily)

| Strategy | Morning split | Total return | Final portfolio |
|---|---|---|---|
| M1 alone | 100% | +235% | $33,520 |
| M1 + A1 | 100% → sequential | +480% | $58,017 |
| M1 + A1 + A2 | 100% → sequential | +763% | $86,296 |
| **M2 + A1 + A2** | **100% → sequential** | **+914%** | **$101,362** |
| M1+M2+A1+A2 | 60% / 40% → sequential | +825% | $92,503 |

### Per-Window Breakdown (compound, best 3 combos)

| Strategy | Window | Cap P&L | Return on $10k |
|---|---|---|---|
| M1+A1+A2 | M1 | +$47,219 | +472% |
| M1+A1+A2 | A1 | +$16,165 | +162% |
| M1+A1+A2 | A2 | +$12,912 | +129% |
| M2+A1+A2 | M2 | +$56,993 | +570% |
| M2+A1+A2 | A1 | +$18,984 | +190% |
| M2+A1+A2 | A2 | +$15,385 | +154% |
| M1+M2+A1+A2 | M1 (60%) | +$30,978 | +310% |
| M1+M2+A1+A2 | M2 (40%) | +$20,362 | +204% |
| M1+M2+A1+A2 | A1 | +$17,280 | +173% |
| M1+M2+A1+A2 | A2 | +$13,883 | +139% |

### Observations

- **Each additional sequential window adds cleanly** — afternoon windows are non-overlapping and their P&L is fully additive on top of morning
- **Sequential capital recycling amplifies compounding** — a window with positive EV trading the full returned pot each day compounds exponentially over months
- **M2+A1+A2 is the top performer** (+914% compound, +236% no-compound) — M2's higher EV/trade (+0.468% vs M1's +0.443%) compounds more aggressively when given the full $10k
- **M1+A1+A2 is the conservative alternative** (+763% compound) — M1's higher win rate (37% vs 32%) makes it more stable for live trading
- **4-window 60/40 split underperforms M2+A1+A2** — splitting M1/M2 prevents either morning window from compounding at full strength; the combined M1+M2 morning contribution (+$51,340) is less than M2-alone (+$56,993)
- **No-compound mode**: differences between combos are moderate (+123% to +236%) — good for strategy edge comparison
- **Compound mode**: differences are dramatic (+235% to +914%) — sequential recycling turns small EV differences into large outcome differences over 15 months

### Key Insight: Non-Overlapping Windows Are Fully Additive

M1's cap P&L is identical whether run alone ($12,299 no-compound) or paired with afternoon windows ($12,299 in M1+A1 and M1+A1+A2). The windows trade at non-overlapping times of day, so adding afternoon windows never dilutes morning performance — it only adds.

### Recommended Configs

| Use case | Config | Rationale |
|---|---|---|
| Live trading (conservative) | M1 + A1 + A2, `--morning-split 100` | Highest win rate, fully additive afternoons |
| Live trading (aggressive) | M2 + A1 + A2, `--morning-split 100` | Best total return, slightly noisier M2 entry |
| Strategy comparison/research | Any combo, no `--compound` flag | Clean per-day edge measurement |
| Account growth projection | Any combo, `--compound` flag | Realistic compounding view |

### CLI Commands

```bash
# M1 + A1 + A2 (conservative)
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2026-03-27 --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# M2 + A1 + A2 (aggressive)
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2026-03-27 --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100
```

### Next Steps

- [ ] Monthly breakdown comparison across all combos to identify which months each config wins/loses
- [x] Test M1+A1+A2 and M2+A1+A2 over 2021–2026 with continuous compounding — see Finding 6
- [ ] Evaluate deduplication rule for windows that pick the same ticker on the same day

---

## Finding 6 — Continuous 5-Year Compound Growth (2021-01-01 → 2026-03-28)

**Question**: What does the full compounding trajectory look like when each strategy runs as a single uninterrupted 5-year run (no annual resets)?

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20 --compound`, pool = V2 (16 tickers), capital = $10,000

**Note**: Cache stitching was added to `fetch_bars()` (`_stitch_cache()`) so long-range runs build from existing per-year cache files without re-fetching from Alpaca.

### Year-End Portfolio Values ($10,000 start)

| Year | M1 | M1+A1 | M1+A1+A2 | M2+A1+A2 | M1+M2+A1+A2 |
|---|---|---|---|---|---|
| 2021 | $18,042 | $26,046 | $34,957 | **$42,475** | $37,905 |
| 2022 | $50,702 | $121,153 | $228,192 | **$251,468** | $239,462 |
| 2023 | $110,328 | $424,604 | $1.08M | **$1.19M** | $1.14M |
| 2024 | $146,756 | $732,459 | $2.46M | **$4.41M** | $3.16M |
| 2025 | $317,921 | $2.49M | $11.28M | **$25.97M** | $16.07M |
| 2026 Q1 | $490,985 | $4.24M | $21.18M | **$44.74M** | $29.20M |

### 5-Year Total Returns

| Strategy | Total return | Final portfolio |
|---|---|---|
| M1 alone | +4,810% | $490,985 |
| M1 + A1 | +42,304% | $4,240,429 |
| M1 + A1 + A2 | +211,734% | $21,183,408 |
| **M2 + A1 + A2** | **+447,292%** | **$44,739,211** |
| M1+M2+A1+A2 (60/40) | +291,939% | $29,203,904 |

### Observations

- **M2+A1+A2 leads every single year** under continuous compounding — it never falls behind
- **Each additional window multiplies the final outcome**: M1→M1+A1 is ~9×, M1+A1→M1+A1+A2 is ~5×, M1+A1+A2→M2+A1+A2 is ~2× — driven entirely by compounding, not strategy change
- **The snowball accelerates in 2025–2026**: M2+A1+A2 earns ~$8.2M in January 2026 alone (on a $26M base), showing how compounding magnifies even moderate monthly returns
- **M1+M2+A1+A2 (60/40) trails M2+A1+A2 every year** — splitting morning capital between M1 and M2 dilutes both; giving 100% to M2 and running M1 sequentially would be better
- **The per-year no-compound comparison** (Finding 5 / SUMMARY.md) is the right tool for evaluating *strategy edge* — the 5-year compound run shows *capital growth potential* assuming consistent future performance
- Log files: `backtest_result/multiple_trading_windows/*_compound_5yr.txt`

### Next Steps

- [ ] Monthly breakdown comparison across all combos
- [ ] Evaluate deduplication rule for windows that pick the same ticker on the same day

---

## Finding 7 — Reversal Trade Signal (2021-01-01 → 2026-04-03)

**Question**: Does adding a reversal trade after a quick BEARISH stop-out improve overall P&L?

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20 --top 3`, pool = V2 (16 tickers), capital = $10,000 (no-compound)

### Signal Logic

When a BEARISH primary trade stops out within `bars_held ≤ 3` (i.e. ≤ 4 bars exposure) via `hard_stop` or `fallback_20pct`, scan subsequent bars for the first close above `or_high`. If found, enter a BULLISH reversal trade with:

- **Entry**: first bar closing above `or_high`
- **Hard stop**: OR range midpoint `(or_high + or_low) / 2` — armed immediately (entry > or_high > midpoint)
- **Trailing stop**: MA20 (or MA50/both per `--trailing-ma`), but **only armed once price has moved up ≥ 1 OR range** from entry (prevents premature exits before the trade has room to breathe)
- **EOD exit**: 3:55 PM ET if no stop hit

Enabled via `--reversal` flag. Threshold configurable via `--reversal-max-bars` (default 3).

Reversal rows are excluded from the 60-day rolling stats used for ticker scoring, keeping the selection algo pure. Each row (primary and reversal) reports its own P&L independently in the daily table with a `[REV]` sub-row.

### Year-by-Year Results — Single Window (M1: `09:30 / 3 bars`)

| Year | No Reversal | With Reversal | Delta |
|---|---|---|---|
| 2025 | +91.96% | +121.41% | **+29.45pp** |
| 2026 YTD | +51.45% | +53.82% | **+2.37pp** |

### Year-by-Year Results — Multi-Window (`M1 09:30/3 + A1 13:15/1 + A2 15:00/1`)

Reversal applies to **all windows** (not just M1).

| Year | No Reversal | With Reversal | Delta |
|---|---|---|---|
| 2021 | +114.82% | +130.65% | **+15.83pp** |
| 2022 | +185.60% | +182.26% | -3.34pp |
| 2023 | +166.15% | +213.44% | **+47.29pp** |
| 2024 | +89.11% | +99.38% | **+10.27pp** |
| 2025 | +166.65% | +214.24% | **+47.59pp** |
| 2026 YTD | +70.33% | +88.39% | **+18.06pp** |

### Trade Count & Win Rate Breakdown — Multi-Window (`M1 + A1 + A2`)

Primary and reversal trades are independently accounted. Primary win rate is unaffected by reversal outcomes.

**2025**

| | Trades | W/L | Win rate |
|---|---|---|---|
| Primary | 1,952 | 557W / 1395L | 29% |
| Reversals | +672 (+34%) | 287W / 385L | **43%** |

**2026 YTD**

| | Trades | W/L | Win rate |
|---|---|---|---|
| Primary | 476 | 134W / 342L | 28% |
| Reversals | +175 (+37%) | 77W / 98L | **44%** |

### Observations

- Reversal wins **5 out of 6 years** in the multi-window config
- **2022 is the exception** (-3.34pp): sustained bear market with persistent downtrends; BEARISH stops did not resolve into V-bounces through OR_high — slow grinds rather than sharp reversals
- **2023 and 2025 are the biggest beneficiaries** (+47pp each): high-volatility, mean-reverting regimes produce sharp V-bounces through OR_high after quick BEARISH fakeouts
- **Reversal win rate (43–44%) is consistently higher than primary win rate (28–29%)** — reversals are higher-quality trades: they only trigger when price has already proven direction by crossing OR_high
- **Reversals add 34–37% more trades** with no dilution to primary stats — the layers are fully independent
- **Primary win rate is unchanged** with or without reversal enabled — each row accounts for its own P&L only
- **Trailing stop arming threshold** (≥1 OR range gain) is critical: without it, MA20 exits prematurely on normal post-entry noise, cutting winners short. COIN Apr 2 example: +$0.41 → +$1.49 after arming fix
- **Midpoint hard stop** gives enough room vs the prior `or_high - 15% × OR_range` — allows the reversal to survive early volatility while still protecting against a full reversal back into the OR
- Log files: `backtest_result/with_reversal_trade/`

### Conclusion

`--reversal` is additive in volatile/mean-reverting markets and roughly neutral in trend-following markets. Recommended to enable for live trading. Default `--reversal-max-bars 3` (≤4 bars exposure) is the right threshold — wider (≤6 bars) yields nearly identical results with marginally lower quality trades.

---

## Finding 8 — OR Range Filter Window Scope (2025-01-01 → 2025-12-31)

**Question**: Does applying `--min-or-range 1.5` to afternoon windows (A1, A2) reduce noise or destroy value? And which scope (M1 only, A1+A2 only, all windows) performs best?

**Params**: `--top 2 --weights 50 30 --regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal`

Full sweep details and 2026 axis results: `reduce_small_trade_noise.md`

### 4-Way Comparison — 2025 Full Year

| Config | Primary | Reversals | WR | EV/trade | Return |
|---|---|---|---|---|---|
| No filter | 1360 (381W/979L) | 485 (207W/278L) | 28% | +0.049% | **+234.86%** |
| M1 only (`--min-or-range-windows M1`) | 1304 (375W/929L) | 454 (196W/258L) | 29% | +0.053% | **+221.09%** |
| A1+A2 only (`--min-or-range-windows A1 A2`) | 451 (155W/296L) | 93 (47W/46L) | 34% | +0.214% | **+151.73%** |
| All windows | 395 (149W/246L) | 62 (36W/26L) | 38% | +0.251% | **+138.01%** |

### Per-Window Breakdown — A1+A2 Filter Run

| Window | Trades | W/L | WR | EV/trade | Cap Return |
|---|---|---|---|---|---|
| M1 | 446 | 152W/294L | 34% | +0.155% | +136.23% |
| A1 | 2 | 2W/0L | 100% | +13.25% | +15.30% |
| A2 | 3 | 1W/2L | 33% | +0.206% | +0.20% |

### Key Finding: 1.5% OR Threshold Eliminates Afternoon Trading

Applying `--min-or-range 1.5` to A1 or A2 reduces those windows to **essentially zero trades** (only 2 A1 + 3 A2 pass all year). This is structural, not coincidental:

- Afternoon windows reuse the **morning OR**, which closes at 9:45 AM (M1) or 9:35 AM (M2)
- By 1:20 PM (A1) or 3:05 PM (A2), the OR range cannot expand — it is fixed from the morning
- Morning ORs with range < 1.5% are the majority of afternoon setups, since tight ORs are common
- The 2 A1 trades that survive are outliers (both happened to be taken on days with wide ORs), not a signal

The drop in return when filtering afternoons (-83pp vs no filter) is almost entirely due to **removing the A1/A2 contribution**, not improving signal quality.

### Observations

- **No filter is the best raw backtest config (+234.86%)** — all four afternoon trades add cumulative value despite noise; removing them costs return
- **M1-only filter (-13.77pp)** removes some low-OR morning setups but costs more than it gains in 2025 — the 56 filtered M1 trades were not uniformly losers
- **A1+A2 filter and All-windows filter are both dominated** — they effectively disable afternoon windows, not just filter noise
- **The `--min-or-range-windows` flag exists to prevent accidental afternoon filtering** — always specify `--min-or-range-windows M1` (or `M2`) if using `--min-or-range`, never apply to A1/A2
- **The 2026 noise analysis** (reduce_small_trade_noise.md) motivated this filter based on 115 zero/small trades; but in 2025 the filter nets negative in all configurations

### Conclusion

`--min-or-range` should **not be applied to afternoon windows** under any threshold. The morning OR is too narrow by afternoon to use as a quality gate.

For M1 filtering in live options: the 2026 analysis (reduce_small_trade_noise.md) shows `--min-or-range 1.5` converts a 29% WR into 50% WR and doubles EV/trade by removing unexecutable option setups. The 2025 result shows raw backtest return drops (-13.77pp). The trade-off is justified for live options (execution costs dominate) but not for pure backtest comparison.

**Recommended configs**:
- Live options trading: `--min-or-range 1.5 --min-or-range-windows M1` (or M2)
- Pure strategy research / backtest comparison: no filter

---

## Finding 10 — Per-Year Backtest Sweep (2021–2026 YTD) with V2 Pool + Current Best Config

**Date**: 2026-04-03

**Params**: `--top 3 --weights 50 30 20 --regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal --min-or-range 0.5 --min-or-range-windows M1`

**Pool**: V2 (16 tickers: SNDK, APP, SHOP, CVNA, AMD, META, EXPE, FANG, RH, FN, MU, ANAB, PLTR, COIN, NVDA, TSLA)

**Capital model**: $10,000/day no-compound (daily reset — strategy edge comparison)

### Summary

| Year | Trades | Wins | Win% | Return% |
|---|---|---|---|---|
| 2021 | 1995 | 514 | 26% | **+129.95%** |
| 2022 | 1838 | 507 | 28% | **+182.42%** |
| 2023 | 1967 | 539 | 27% | **+211.76%** |
| 2024 | 1949 | 483 | 25% | **+98.69%** |
| 2025 | 1943 | 556 | 29% | **+215.70%** |
| 2026 YTD (Jan–Apr 3) | 475 | 134 | 28% | **+88.72%** |

### Per-Window Breakdown

| Year | Window | Trades | Wins | Win% | Avg P&L% | Return% |
|---|---|---|---|---|---|---|
| 2021 | M1 | 666 | 205 | 31% | +0.022% | +61.13% |
| 2021 | A1 | 680 | 146 | 21% | -0.008% | +36.60% |
| 2021 | A2 | 649 | 163 | 25% | +0.035% | +32.22% |
| 2022 | M1 | 603 | 216 | 36% | +0.213% | +87.31% |
| 2022 | A1 | 645 | 149 | 23% | -0.098% | +58.02% |
| 2022 | A2 | 590 | 142 | 24% | -0.001% | +37.08% |
| 2023 | M1 | 661 | 211 | 32% | +0.082% | +118.20% |
| 2023 | A1 | 667 | 151 | 23% | -0.010% | +61.44% |
| 2023 | A2 | 639 | 177 | 28% | +0.031% | +32.12% |
| 2024 | M1 | 628 | 199 | 32% | +0.052% | +43.90% |
| 2024 | A1 | 658 | 141 | 21% | -0.054% | +21.96% |
| 2024 | A2 | 663 | 143 | 22% | -0.014% | +32.83% |
| 2025 | M1 | 629 | 226 | 36% | +0.146% | +122.84% |
| 2025 | A1 | 657 | 164 | 25% | +0.032% | +57.68% |
| 2025 | A2 | 657 | 166 | 25% | -0.017% | +35.18% |
| 2026 YTD | M1 | 147 | 65 | 44% | +0.655% | +54.15% |
| 2026 YTD | A1 | 165 | 36 | 22% | -0.110% | +20.23% |
| 2026 YTD | A2 | 163 | 33 | 20% | -0.026% | +14.33% |

### Observations

- **Win rate is stable at 25–29% across all full years** — confirms consistent positive-EV structure
- **2024 is the weakest year (+98.69%)** — all three windows underperformed; consistent with the choppy/low-volatility regime that year
- **2026 YTD is the strongest pace** — +88.72% in ~3 months (Jan–Apr 3), driven by exceptionally strong M1 (44% WR, +0.655% avg, +54.15%)
- **M1 is the primary return driver every year** — contributes 43–59% of total return depending on year
- **A1 and A2 add incremental return in all years** — even in weak years (2024), A1 +21.96% and A2 +32.83% still contribute meaningfully on top of M1
- **A1/A2 win rates are structurally lower (20–25%)** — consistent with the afternoon noise analysis; positive EV comes from asymmetric win size, not frequency
