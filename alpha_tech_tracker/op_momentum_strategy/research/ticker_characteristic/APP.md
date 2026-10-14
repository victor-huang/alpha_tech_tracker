# APP — candle patterns at wave lows and highs

Which 5-min candles mark APP's wave reversals, 2025 and 2026 (to Oct 13). Studies run 2026-10-14. Method and terms: [README](README.md); the same study for AMD, with every definition spelled out: [AMD.md](AMD.md).

## Summary

- 2026 is harder to read than 2025: fewer candidates hit (baseline 24.6% vs 32.2%) and volume says less (1.13x at real lows vs 0.91x elsewhere, against 1.21x vs 0.90x in 2025).
- The long tail confirmed by the next bar still lifted precision most in 2026 (47% vs a 24.6% baseline, lift 1.9); the wick + volume rule fell to 38% and push to 33%.
- Tops held up better than bottoms in 2026: long tail + confirmation 51%, volume ≥ 1.5x 38%.
- Shared with every monitored ticker: a long wick alone is no better than the baseline, closing beyond the previous bar is late (below the baseline), and the reversal bar is wider and on heavier volume than the bars around it.

## Candidates

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 2,975 | 32.2% | 3,267 | 30.2% | 225 |
| 2026 | 2,794 | 24.6% | 2,873 | 24.3% | 178 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2025: at the real low | 22% | 17% | 0.39 | 52% | **1.18x** | **1.21x** |
| Bottoms 2025: other candidates | 24% | 21% | 0.41 | 46% | 0.94x | 0.90x |
| Bottoms 2026: at the real low | 22% | 18% | 0.38 | 52% | **1.13x** | **1.13x** |
| Bottoms 2026: other candidates | 25% | 22% | 0.44 | 45% | 0.85x | 0.91x |
| Tops 2025: at the real high | 19% | 22% | 0.61 | 52% | **1.07x** | **1.19x** |
| Tops 2025: other candidates | 22% | 24% | 0.59 | 46% | 0.87x | 0.87x |
| Tops 2026: at the real high | 21% | 25% | 0.59 | 47% | **1.09x** | **1.07x** |
| Tops 2026: other candidates | 23% | 25% | 0.58 | 45% | 0.84x | 0.83x |

## Bottom signals (baseline 32.2% in 2025, 24.6% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 53% / 6.1% / 0.48 | 47% / 5.2% / 0.43 |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | 47% / 7.0% / 0.64 | 38% / 5.5% / 0.56 |
| Piercing | 94% / 1.6% / 0.07 | 46% / 0.9% / 0.07 |
| Push | 83% / 2.5% / 0.13 | 33% / 0.9% / 0.10 |
| Engulfing | 50% / 0.9% / 0.08 | 11% / 0.1% / 0.05 |
| Volume ≥ 1.5x average | 45% / 34.7% / 3.26 | 34% / 27.8% / 3.19 |
| Range ≥ 1.5x average bar | 45% / 33.6% / 3.20 | 37% / 30.2% / 3.17 |
| Next bar confirms (+1 bar) | 48% / 31.6% / 2.81 | 32% / 27.2% / 3.30 |
| Long tail | 38% / 15.3% / 1.72 | 34% / 13.8% / 1.58 |
| Long tail combo | 39% / 15.3% / 1.67 | 34% / 13.8% / 1.55 |
| Lower wick ≥ 50% (shape only) | 31% / 16.8% / 2.31 | 19% / 13.1% / 2.62 |
| Morning star | 32% / 1.5% / 0.20 | 26% / 1.3% / 0.20 |
| Close beyond the previous bar's extreme | 26% / 8.2% / 1.35 | 15% / 6.8% / 1.76 |

## Top signals (baseline 30.2% in 2025, 24.3% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 52% / 4.7% / 0.39 | 51% / 5.2% / 0.39 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | 45% / 5.5% / 0.53 | 38% / 3.9% / 0.40 |
| Dark cloud (bearish piercing) | 50% / 0.4% / 0.04 | 36% / 0.6% / 0.06 |
| Push | 67% / 1.2% / 0.08 | 40% / 1.1% / 0.11 |
| Engulfing | never fired | never fired |
| Volume ≥ 1.5x average | 44% / 34.1% / 3.36 | 38% / 25.8% / 2.69 |
| Range ≥ 1.5x average bar | 42% / 26.7% / 2.78 | 37% / 27.8% / 2.93 |
| Next bar confirms (+1 bar) | 41% / 29.3% / 3.13 | 34% / 27.2% / 3.12 |
| Long tail | 38% / 11.5% / 1.33 | 36% / 14.0% / 1.53 |
| Long tail combo | 39% / 11.5% / 1.30 | 37% / 14.0% / 1.48 |
| Upper wick ≥ 50% (shape only) | 29% / 15.2% / 2.27 | 24% / 16.0% / 2.61 |
| Evening star | 30% / 1.3% / 0.19 | 34% / 1.7% / 0.20 |
| Close beyond the previous bar's extreme | 24% / 8.9% / 1.63 | 16% / 6.9% / 1.74 |

## Reproduction

Same scripts and settings as [AMD.md](AMD.md#reproduction): 5-min SIP bars with volume, real-time wave replay, candidates within 1 average bar of the running extreme after a 3-average-bar move, hits within one bar of the finished wave's extreme.
