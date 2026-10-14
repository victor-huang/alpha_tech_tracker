# SNDK — candle patterns at wave lows and highs

Which 5-min candles mark SNDK's wave reversals, 2025 and 2026 (to Oct 13). Studies run 2026-10-14. Method and terms: [README](README.md); the same study for AMD, with every definition spelled out: [AMD.md](AMD.md).

## Summary

- The clearest 2026 bottoms of the seven: long tail + confirmation 60% (catching 7.6% of lows), piercing 86%, push 73%, and real lows on 1.36x volume against 1.01x elsewhere.
- Tops in 2026: long tail + confirmation 58%, push 86% (0.04 a day).
- 2025 covers the months after the February 2025 listing (210 sessions).
- Shared with every monitored ticker: a long wick alone is no better than the baseline, closing beyond the previous bar is late (below the baseline), and the reversal bar is wider and on heavier volume than the bars around it.

## Candidates

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 2,693 | 31.1% | 3,081 | 27.8% | 210 |
| 2026 | 2,130 | 34.0% | 2,935 | 27.0% | 177 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2025: at the real low | 22% | 17% | 0.40 | 54% | **1.16x** | **0.98x** |
| Bottoms 2025: other candidates | 22% | 20% | 0.38 | 50% | 0.94x | 0.77x |
| Bottoms 2026: at the real low | 24% | 17% | 0.38 | 49% | **1.28x** | **1.36x** |
| Bottoms 2026: other candidates | 25% | 21% | 0.42 | 46% | 1.00x | 1.01x |
| Tops 2025: at the real high | 16% | 22% | 0.63 | 52% | **1.10x** | **0.95x** |
| Tops 2025: other candidates | 21% | 23% | 0.60 | 47% | 0.84x | 0.73x |
| Tops 2026: at the real high | 19% | 22% | 0.62 | 52% | **1.16x** | **1.36x** |
| Tops 2026: other candidates | 23% | 25% | 0.57 | 43% | 0.83x | 0.85x |

## Bottom signals (baseline 31.1% in 2025, 34.0% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 52% / 5.8% / 0.45 | 60% / 7.6% / 0.51 |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | 47% / 6.6% / 0.56 | 48% / 8.1% / 0.69 |
| Piercing | 44% / 0.5% / 0.04 | 86% / 0.8% / 0.04 |
| Push | 47% / 0.8% / 0.07 | 73% / 1.1% / 0.06 |
| Engulfing | 65% / 1.6% / 0.10 | 31% / 0.7% / 0.09 |
| Volume ≥ 1.5x average | 42% / 32.9% / 3.17 | 46% / 43.1% / 3.86 |
| Range ≥ 1.5x average bar | 41% / 32.0% / 3.15 | 44% / 37.6% / 3.48 |
| Next bar confirms (+1 bar) | 42% / 29.1% / 2.74 | 44% / 28.0% / 2.63 |
| Long tail | 43% / 16.2% / 1.50 | 40% / 18.0% / 1.82 |
| Long tail combo | 44% / 16.2% / 1.47 | 42% / 18.0% / 1.75 |
| Lower wick ≥ 50% (shape only) | 34% / 17.8% / 2.09 | 36% / 18.2% / 2.10 |
| Morning star | 29% / 1.7% / 0.23 | 16% / 0.8% / 0.21 |
| Close beyond the previous bar's extreme | 24% / 8.5% / 1.41 | 23% / 7.2% / 1.27 |

## Top signals (baseline 27.8% in 2025, 27.0% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 53% / 5.7% / 0.44 | 58% / 5.8% / 0.43 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | 48% / 7.2% / 0.60 | 41% / 7.3% / 0.75 |
| Dark cloud (bearish piercing) | 38% / 0.6% / 0.06 | 60% / 0.8% / 0.05 |
| Push | 38% / 1.2% / 0.12 | 86% / 0.8% / 0.04 |
| Engulfing | never fired | never fired |
| Volume ≥ 1.5x average | 40% / 29.0% / 2.96 | 44% / 43.3% / 4.19 |
| Range ≥ 1.5x average bar | 39% / 32.1% / 3.31 | 43% / 32.4% / 3.22 |
| Next bar confirms (+1 bar) | 41% / 29.6% / 2.95 | 37% / 27.0% / 3.13 |
| Long tail | 39% / 15.0% / 1.57 | 41% / 14.9% / 1.54 |
| Long tail combo | 40% / 14.9% / 1.52 | 42% / 14.9% / 1.52 |
| Upper wick ≥ 50% (shape only) | 28% / 17.5% / 2.56 | 25% / 15.6% / 2.68 |
| Evening star | 23% / 0.8% / 0.14 | 19% / 1.0% / 0.23 |
| Close beyond the previous bar's extreme | 21% / 8.3% / 1.58 | 20% / 7.8% / 1.68 |

## Reproduction

Same scripts and settings as [AMD.md](AMD.md#reproduction): 5-min SIP bars with volume, real-time wave replay, candidates within 1 average bar of the running extreme after a 3-average-bar move, hits within one bar of the finished wave's extreme.
