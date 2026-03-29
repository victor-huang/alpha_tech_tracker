# 4-Strategy Overlap Analysis

**Strategies compared** (2025-01-01 → 2026-03-27):

| Label | Config | Entry time | Return | Win rate |
|---|---|---|---|---|
| M1 | 09:30 / 3 bars | 9:45 AM | +123% | 37% |
| M2 | 09:30 / 1 bar | 9:35 AM | +139% | 32% |
| A1 | 13:15 / 1 bar | 1:20 PM | +56% | 24% |
| A2 | 15:00 / 1 bar | 3:05 PM | +40% | 26% |

---

## Pairwise Overlap

| Pair | Days both active | Zero overlap | 1 shared | 2 shared | 3 shared | Rank-1 match | Avg shared/day |
|---|---|---|---|---|---|---|---|
| M1 vs M2 | 284 | 79 (28%) | 126 (44%) | 71 (25%) | 8 (3%) | 72 (25%) | 1.03 |
| M1 vs A1 | 282 | 121 (43%) | 123 (44%) | 37 (13%) | 1 (0%) | 34 (12%) | 0.71 |
| M1 vs A2 | 275 | 134 (49%) | 106 (39%) | 34 (12%) | 1 (0%) | 24 (9%) | 0.64 |
| M2 vs A1 | 290 | 122 (42%) | 126 (43%) | 42 (14%) | 0 (0%) | 36 (12%) | 0.72 |
| M2 vs A2 | 285 | 133 (47%) | 126 (44%) | 26 (9%) | 0 (0%) | 28 (10%) | 0.62 |
| A1 vs A2 | 288 | 104 (36%) | 148 (51%) | 33 (11%) | 3 (1%) | 33 (11%) | 0.77 |

### Key observations

- **Morning vs afternoon pairs are the most independent**: M1/A2 and M2/A2 have ~47-49% zero overlap and rank-1 agreement of only 9-10% — almost entirely different trades
- **M1 vs A1** and **M2 vs A1** also strong: 42-43% zero overlap, 12% rank-1 agreement
- **The two morning strategies (M1 vs M2)** are the most correlated at 1.03 avg shared/day and 25% rank-1 match — expected since they use the same start time
- **The two afternoon strategies (A1 vs A2)** share 0.77 tickers/day — more correlated than any morning/afternoon pair but still mostly independent (36% zero overlap)

---

## 4-Way Analysis (267 days all 4 strategies active)

### Cross-strategy ticker overlap per day

| Tickers shared across 2+ strategies | Days | % |
|---|---|---|
| 0 — fully independent | 1 | 0% |
| 1 | 20 | 7% |
| 2 | 77 | 29% |
| 3 | 103 | 39% |
| 4 | 57 | 21% |
| 5 | 8 | 3% |
| 6 | 1 | 0% |

### Unique picks per strategy (not picked by any other)

| Strategy | Avg unique picks/day |
|---|---|
| A2: 15:00 / 1 bar | **1.39** — most independent |
| A1: 13:15 / 1 bar | 1.25 |
| M2: 09:30 / 1 bar | 1.17 |
| M1: 09:30 / 3 bars | 1.07 — least independent |

---

## Interpretation

Running all 4 strategies together means ~12 picks/day (4 strategies × ~3 picks), but due to overlap the actual **unique ticker exposure** is roughly 4-6 distinct tickers/day on average.

- **A2 (15:00/1bar)** contributes the most independent signal — 1.39 unique picks/day — making it the strongest diversifier in the portfolio
- **A1 (13:15/1bar)** also highly independent vs the morning strategies (42-43% zero overlap pairwise)
- The morning pair (M1+M2) share the most overlap with each other but are largely independent from the afternoon pair
- On only **1 out of 267 days** were all 4 strategies completely non-overlapping

## Practical Takeaway

The 4-strategy system trades roughly **4-6 unique tickers per day** across 12 total picks. The afternoon strategies (especially A2) pick genuinely different names than the morning. A combined system would:
- Spread capital across up to ~6 names daily with different entry timings
- Have low rank-1 correlation between morning and afternoon (9-12%) — the "best bet" each session is usually a different ticker
- Accept some concentration risk on 2-3 tickers that appear in multiple strategies (~68% of days have 3+ shared tickers somewhere)

## Next Steps

- [ ] Simulate combined capital across all 4 strategies with equal split ($2,500 each) vs $10,000 in M1 alone
- [ ] Consider whether the overlap concentration (3-4 shared tickers on 60% of days) needs a deduplication rule — e.g. skip a pick if already held from an earlier strategy that day
