# SNPS — candle patterns at wave lows and highs

Which 5-min candles mark SNPS's wave reversals, 2025 and 2026 (to Oct 13). Studies run 2026-10-14. Method and terms: [README](README.md); the same study for AMD, with every definition spelled out: [AMD.md](AMD.md).

## Summary

- Volume separates SNPS's extremes the least: real lows 0.92–0.93x average vs 0.77–0.78x elsewhere, and the wick + volume rule is the weakest of the seven at lows (42% / 40%).
- Long tail + confirmation still works (53% / 54% at lows, 50% / 47% at highs).
- Tops: wick + volume dropped from 53% (2025) to 43% (2026).
- Shared with every monitored ticker: a long wick alone is no better than the baseline, closing beyond the previous bar is late (below the baseline), and the reversal bar is wider and on heavier volume than the bars around it.

## Candidates

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 3,069 | 33.2% | 3,792 | 29.0% | 233 |
| 2026 | 2,476 | 30.9% | 2,521 | 29.7% | 183 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2025: at the real low | 21% | 16% | 0.39 | 54% | **1.11x** | **0.92x** |
| Bottoms 2025: other candidates | 22% | 17% | 0.40 | 51% | 0.96x | 0.78x |
| Bottoms 2026: at the real low | 24% | 18% | 0.38 | 50% | **1.13x** | **0.93x** |
| Bottoms 2026: other candidates | 24% | 21% | 0.43 | 47% | 0.91x | 0.77x |
| Tops 2025: at the real high | 15% | 21% | 0.61 | 55% | **1.03x** | **0.89x** |
| Tops 2025: other candidates | 18% | 19% | 0.61 | 52% | 0.84x | 0.75x |
| Tops 2026: at the real high | 17% | 24% | 0.59 | 50% | **1.04x** | **0.91x** |
| Tops 2026: other candidates | 21% | 24% | 0.59 | 46% | 0.85x | 0.77x |

## Bottom signals (baseline 33.2% in 2025, 30.9% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 53% / 5.0% / 0.41 | 54% / 5.8% / 0.45 |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | 42% / 4.1% / 0.43 | 40% / 4.4% / 0.46 |
| Piercing | 61% / 1.1% / 0.08 | 44% / 0.9% / 0.09 |
| Push | 53% / 1.0% / 0.08 | 47% / 1.2% / 0.10 |
| Engulfing | 38% / 1.4% / 0.16 | 39% / 0.9% / 0.10 |
| Volume ≥ 1.5x average | 41% / 21.8% / 2.30 | 39% / 23.3% / 2.46 |
| Range ≥ 1.5x average bar | 44% / 31.4% / 3.11 | 41% / 31.4% / 3.23 |
| Next bar confirms (+1 bar) | 45% / 32.3% / 3.11 | 41% / 29.2% / 2.96 |
| Long tail | 41% / 14.6% / 1.57 | 39% / 15.9% / 1.70 |
| Long tail combo | 41% / 14.5% / 1.54 | 41% / 15.8% / 1.62 |
| Lower wick ≥ 50% (shape only) | 34% / 18.3% / 2.37 | 31% / 19.2% / 2.58 |
| Morning star | 25% / 1.0% / 0.17 | 26% / 1.6% / 0.26 |
| Close beyond the previous bar's extreme | 24% / 8.4% / 1.52 | 22% / 7.7% / 1.46 |

## Top signals (baseline 29.0% in 2025, 29.7% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 50% / 4.6% / 0.43 | 47% / 4.7% / 0.42 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | 53% / 5.4% / 0.47 | 43% / 4.1% / 0.40 |
| Dark cloud (bearish piercing) | 64% / 0.6% / 0.05 | 62% / 0.7% / 0.04 |
| Push | 65% / 1.0% / 0.07 | 56% / 0.7% / 0.05 |
| Engulfing | never fired | never fired |
| Volume ≥ 1.5x average | 42% / 24.4% / 2.66 | 42% / 22.2% / 2.22 |
| Range ≥ 1.5x average bar | 40% / 25.3% / 2.94 | 42% / 28.3% / 2.83 |
| Next bar confirms (+1 bar) | 41% / 32.4% / 3.68 | 39% / 30.2% / 3.28 |
| Long tail | 39% / 13.1% / 1.55 | 37% / 13.4% / 1.52 |
| Long tail combo | 40% / 12.9% / 1.51 | 38% / 13.2% / 1.48 |
| Upper wick ≥ 50% (shape only) | 30% / 17.9% / 2.77 | 29% / 18.3% / 2.63 |
| Evening star | 22% / 1.0% / 0.22 | 23% / 1.3% / 0.24 |
| Close beyond the previous bar's extreme | 23% / 9.3% / 1.90 | 23% / 9.2% / 1.72 |

## Reproduction

Same scripts and settings as [AMD.md](AMD.md#reproduction): 5-min SIP bars with volume, real-time wave replay, candidates within 1 average bar of the running extreme after a 3-average-bar move, hits within one bar of the finished wave's extreme.
