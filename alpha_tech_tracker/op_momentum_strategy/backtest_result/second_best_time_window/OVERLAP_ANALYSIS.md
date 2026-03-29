# Ticker Selection Overlap Analysis

**Baseline**: `09:30 / 3 bars` (entry 9:45) — $22,299 (+123%)
**Alternative**: `09:30 / 1 bar` (entry 9:35) — $23,926 (+139%)
**Window**: 2025-01-01 → 2026-03-27 (284 trading days with picks in both)

## Summary

| Metric | Value |
|---|---|
| Days both strategies have picks | 284 |
| Days with ≥ 1 shared ticker | 205 (72%) |
| Days with ZERO overlap | 79 (28%) |
| Days with FULL overlap (all baseline picks in alt) | 20 (7%) |
| Days where rank-1 ticker matches | 72 (25%) |
| Avg shared tickers per day | 1.03 of 2.76 baseline picks |

## Overlap Count Distribution

| Shared tickers | Days | % |
|---|---|---|
| 0 (fully independent) | 79 | 28% |
| 1 | 126 | 44% |
| 2 | 71 | 25% |
| 3 (fully overlapping) | 8 | 3% |

## Interpretation for a Combined Strategy

The two strategies are **largely independent** — on any given day:
- **28% of days**: completely different picks → full additive diversification
- **44% of days**: 1 ticker in common, 2-4 unique across both → mostly additive
- **25% of days**: 2 tickers shared → moderate overlap, some capital concentration risk
- **3% of days**: all 3 match → running both adds no diversification

Only **25% rank-1 agreement** means the highest-conviction pick usually differs between the two — the 1-bar strategy is reacting to a genuinely different signal (the raw 9:30 open) vs the 15-min settled OR.

## Case for Running as a Parallel Strategy

- On the **72% of days with at least 1 difference**, the 1-bar strategy adds net-new exposure
- The strategies are complementary by design: 1-bar captures opening breakout momentum, 3-bar waits for the OR to settle
- Combined, they could cover up to 6 picks/day (on zero-overlap days) with different entry timing
- Risk: on the 25% of days with 2+ shared tickers, capital concentration doubles on those names

## Next Steps

- [ ] Simulate running both strategies simultaneously with split capital (e.g. $5k each) and measure combined P&L vs $10k in baseline alone
- [ ] Check whether zero-overlap days are systematically different (e.g. higher volatility, different regime)
- [ ] Evaluate whether the 1-bar picks on zero-overlap days are net positive or negative on their own
