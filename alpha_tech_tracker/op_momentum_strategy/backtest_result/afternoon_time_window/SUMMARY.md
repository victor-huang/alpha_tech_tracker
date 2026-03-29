# Afternoon Opening Window Sweep — 2025-01-01 → 2026-03-27

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20 --top 3`, pool = V2 (16 tickers), capital = $10,000
**Baseline**: `13:30 / 3 bars` (entry 1:45 PM) — $12,055 (+21%)

## Axis 1 — Start time sweep (fixed 3 bars / 15-min window)

| Opening start | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|
| **15:00** | **3:15 PM** | **$13,212** | **+32%** | **29%** |
| 13:00 | 1:15 PM | $13,009 | +30% | 30% |
| 13:15 | 1:30 PM | $12,834 | +28% | 27% |
| 14:15 | 2:30 PM | $12,489 | +25% | 27% |
| 13:45 | 2:00 PM | $12,290 | +23% | 27% |
| 14:30 | 2:45 PM | $12,217 | +22% | 30% |
| 14:00 | 2:15 PM | $12,073 | +21% | 27% |
| **13:30 (baseline)** | **1:45 PM** | **$12,055** | **+21%** | **29%** |

**Top 3 start times**: `15:00`, `13:00`, `13:15`

## Axis 2 — Window width sweep (top 3 start times)

| Opening start | Bars | Window | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|---|---|
| **13:15** | **1** | **5 min** | **1:20 PM** | **$15,582** | **+56%** | **24%** |
| 13:15 | 2 | 10 min | 1:25 PM | $14,275 | +43% | 25% |
| 15:00 | 1 | 5 min | 3:05 PM | $13,995 | +40% | 26% |
| 15:00 | 4 | 20 min | 3:20 PM | $13,699 | +37% | 35% |
| 15:00 | 2 | 10 min | 3:10 PM | $13,640 | +36% | 28% |
| 13:00 | 1 | 5 min | 1:05 PM | $13,602 | +36% | 19% |
| 15:00 | 3 | 15 min | 3:15 PM | $13,212 | +32% | 29% |
| 13:00 | 4 | 20 min | 1:20 PM | $13,418 | +34% | 29% |
| 13:15 | 4 | 20 min | 1:35 PM | $10,977 | +10% | 28% |
| 13:15 | 6 | 30 min | 1:45 PM | $11,834 | +18% | 27% |
| 13:00 | 2 | 10 min | 1:10 PM | $12,630 | +26% | 25% |
| 13:00 | 6 | 30 min | 1:30 PM | $12,197 | +22% | 27% |

## Conclusions

- **Overall winner: `13:15 / 1 bar` (entry 1:20 PM) → $15,582 (+56%)** — a strong standout, almost 2× the baseline
- **Second: `13:15 / 2 bars` (entry 1:25 PM) → $14,275 (+43%)**
- **Third: `15:00 / 1 bar` (entry 3:05 PM) → $13,995 (+40%)**
- The `13:15` start time is uniquely sensitive to bar width — 1 bar is excellent (+56%), but 4 bars drops to +10%; the 5-min OR at 1:20 PM captures something that gets diluted quickly
- `15:00` is more stable across bar widths (32–40%) — power hour entry, more predictable
- Win rates are notably lower in the afternoon (19–35%) vs morning (32–37%) — bigger wins compensate
- All afternoon results trail the morning baseline (`09:30 / 3 bars` +123%) by a large margin

## Comparison vs Morning Strategies

| Strategy | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|
| 09:30 / 3 bars (morning baseline) | 9:45 AM | $22,299 | +123% | 37% |
| 09:30 / 1 bar (morning alt) | 9:35 AM | $23,926 | +139% | 32% |
| **13:15 / 1 bar (afternoon best)** | **1:20 PM** | **$15,582** | **+56%** | **24%** |
| 15:00 / 1 bar | 3:05 PM | $13,995 | +40% | 26% |
| 13:30 / 3 bars (afternoon baseline) | 1:45 PM | $12,055 | +21% | 29% |

## Next Steps

- [ ] Analyze ticker overlap between `13:15 / 1 bar` and morning strategies (09:30/3bar, 09:30/1bar) — if largely independent, it's a strong third parallel strategy candidate
- [ ] Simulate combined capital allocation across morning + afternoon strategies
- [ ] Investigate why `13:15 / 1 bar` specifically outperforms — post-lunch directional move?
