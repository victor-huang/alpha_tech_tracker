# MDB — candle patterns at wave lows and highs

Which 5-min candles mark MDB's wave reversals, 2025 and 2026 (to Oct 13). Studies run 2026-10-14. Method and terms: [README](README.md); the same study for AMD, with every definition spelled out: [AMD.md](AMD.md).

## Summary

- MDB's volume runs light: other near-low bars trade 0.77x average volume, real lows 1.00–1.02x, so 'heavy' volume here means about average.
- The wick + volume rule faded in 2026 (52% → 36% at lows); long tail + confirmation held (59% / 50% at lows, 51% / 56% at highs).
- Push was unusually accurate at lows in 2026 (64%, 0.12 a day).
- Shared with every monitored ticker: a long wick alone is no better than the baseline, closing beyond the previous bar is late (below the baseline), and the reversal bar is wider and on heavier volume than the bars around it.

## Candidates

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 3,119 | 32.7% | 3,480 | 27.7% | 239 |
| 2026 | 2,761 | 25.9% | 2,839 | 25.6% | 185 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2025: at the real low | 24% | 14% | 0.38 | 52% | **1.18x** | **1.00x** |
| Bottoms 2025: other candidates | 25% | 18% | 0.39 | 49% | 0.91x | 0.78x |
| Bottoms 2026: at the real low | 23% | 17% | 0.39 | 52% | **1.15x** | **1.02x** |
| Bottoms 2026: other candidates | 24% | 21% | 0.40 | 48% | 0.83x | 0.77x |
| Tops 2025: at the real high | 16% | 21% | 0.61 | 55% | **1.11x** | **1.01x** |
| Tops 2025: other candidates | 21% | 22% | 0.61 | 48% | 0.85x | 0.76x |
| Tops 2026: at the real high | 18% | 23% | 0.59 | 50% | **1.13x** | **1.05x** |
| Tops 2026: other candidates | 23% | 24% | 0.57 | 45% | 0.81x | 0.73x |

## Bottom signals (baseline 32.7% in 2025, 25.9% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 59% / 6.4% / 0.46 | 50% / 5.7% / 0.44 |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | 52% / 6.4% / 0.52 | 36% / 4.2% / 0.45 |
| Piercing | 62% / 0.8% / 0.05 | 54% / 1.0% / 0.07 |
| Push | 57% / 1.2% / 0.09 | 64% / 2.0% / 0.12 |
| Engulfing | 29% / 0.7% / 0.10 | 17% / 0.6% / 0.12 |
| Volume ≥ 1.5x average | 47% / 27.4% / 2.50 | 38% / 29.6% / 3.02 |
| Range ≥ 1.5x average bar | 44% / 31.6% / 3.10 | 39% / 32.7% / 3.25 |
| Next bar confirms (+1 bar) | 46% / 32.5% / 3.02 | 37% / 28.4% / 2.99 |
| Long tail | 44% / 15.1% / 1.48 | 36% / 13.5% / 1.44 |
| Long tail combo | 45% / 15.1% / 1.44 | 37% / 13.5% / 1.40 |
| Lower wick ≥ 50% (shape only) | 33% / 19.4% / 2.50 | 25% / 17.2% / 2.65 |
| Morning star | 20% / 1.2% / 0.26 | 25% / 1.8% / 0.28 |
| Close beyond the previous bar's extreme | 25% / 8.9% / 1.54 | 18% / 7.7% / 1.68 |

## Top signals (baseline 27.7% in 2025, 25.6% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 51% / 5.4% / 0.43 | 56% / 5.4% / 0.38 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | 37% / 4.8% / 0.53 | 39% / 4.1% / 0.42 |
| Dark cloud (bearish piercing) | 91% / 1.0% / 0.05 | 58% / 1.0% / 0.07 |
| Push | 64% / 0.9% / 0.06 | 58% / 1.0% / 0.07 |
| Engulfing | never fired | never fired |
| Volume ≥ 1.5x average | 41% / 28.2% / 2.81 | 46% / 31.1% / 2.68 |
| Range ≥ 1.5x average bar | 42% / 29.1% / 2.85 | 44% / 33.6% / 3.06 |
| Next bar confirms (+1 bar) | 41% / 32.8% / 3.30 | 35% / 27.4% / 3.15 |
| Long tail | 32% / 11.3% / 1.46 | 37% / 15.4% / 1.66 |
| Long tail combo | 32% / 11.2% / 1.43 | 38% / 15.4% / 1.60 |
| Upper wick ≥ 50% (shape only) | 26% / 16.5% / 2.57 | 25% / 17.2% / 2.69 |
| Evening star | 31% / 1.9% / 0.25 | 22% / 1.5% / 0.27 |
| Close beyond the previous bar's extreme | 22% / 10.3% / 1.87 | 17% / 7.7% / 1.81 |

## Reproduction

Same scripts and settings as [AMD.md](AMD.md#reproduction): 5-min SIP bars with volume, real-time wave replay, candidates within 1 average bar of the running extreme after a 3-average-bar move, hits within one bar of the finished wave's extreme.
