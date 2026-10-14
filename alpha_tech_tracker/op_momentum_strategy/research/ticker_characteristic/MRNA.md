# MRNA — candle patterns at wave lows and highs

Which 5-min candles mark MRNA's wave reversals, 2025 and 2026 (to Oct 13). Studies run 2026-10-14. Method and terms: [README](README.md); the same study for AMD, with every definition spelled out: [AMD.md](AMD.md).

## Summary

- Bottoms are the hardest to call of the seven: the lowest baseline (26.8% / 27.4%) and long tail + confirmation reaches only 51% / 47%, catching 4% of lows.
- Tops read better, especially in 2026: long tail + confirmation 55%, wick + volume 44%, push 67%.
- Real highs come with 1.21x volume in 2026 (0.92x elsewhere).
- Shared with every monitored ticker: a long wick alone is no better than the baseline, closing beyond the previous bar is late (below the baseline), and the reversal bar is wider and on heavier volume than the bars around it.

## Candidates

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 3,996 | 26.8% | 2,993 | 31.6% | 230 |
| 2026 | 2,767 | 27.4% | 2,758 | 26.4% | 185 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2025: at the real low | 22% | 17% | 0.39 | 51% | **1.00x** | **1.01x** |
| Bottoms 2025: other candidates | 25% | 21% | 0.42 | 45% | 0.82x | 0.78x |
| Bottoms 2026: at the real low | 22% | 17% | 0.38 | 55% | **1.02x** | **1.01x** |
| Bottoms 2026: other candidates | 23% | 20% | 0.42 | 48% | 0.81x | 0.73x |
| Tops 2025: at the real high | 17% | 22% | 0.62 | 51% | **1.17x** | **1.09x** |
| Tops 2025: other candidates | 21% | 23% | 0.61 | 47% | 0.94x | 0.87x |
| Tops 2026: at the real high | 17% | 23% | 0.59 | 51% | **1.20x** | **1.21x** |
| Tops 2026: other candidates | 20% | 23% | 0.62 | 48% | 0.96x | 0.92x |

## Bottom signals (baseline 26.8% in 2025, 27.4% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 51% / 4.0% / 0.37 | 47% / 3.8% / 0.34 |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | 45% / 6.0% / 0.61 | 47% / 4.7% / 0.41 |
| Piercing | 50% / 0.2% / 0.02 | 44% / 0.5% / 0.05 |
| Push | 50% / 0.5% / 0.04 | 44% / 0.9% / 0.09 |
| Engulfing | 40% / 0.6% / 0.07 | 33% / 0.9% / 0.11 |
| Volume ≥ 1.5x average | 43% / 28.4% / 3.10 | 42% / 26.0% / 2.56 |
| Range ≥ 1.5x average bar | 39% / 21.5% / 2.55 | 41% / 24.5% / 2.46 |
| Next bar confirms (+1 bar) | 36% / 27.3% / 3.57 | 38% / 31.3% / 3.40 |
| Long tail | 35% / 11.6% / 1.53 | 33% / 8.7% / 1.07 |
| Long tail combo | 36% / 11.6% / 1.51 | 34% / 8.4% / 1.03 |
| Lower wick ≥ 50% (shape only) | 25% / 17.6% / 3.27 | 26% / 16.1% / 2.56 |
| Morning star | 14% / 0.6% / 0.19 | 28% / 1.5% / 0.21 |
| Close beyond the previous bar's extreme | 18% / 8.0% / 2.03 | 18% / 8.7% / 1.95 |

## Top signals (baseline 31.6% in 2025, 26.4% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 48% / 4.8% / 0.42 | 55% / 6.5% / 0.47 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | 40% / 5.5% / 0.59 | 44% / 7.8% / 0.71 |
| Dark cloud (bearish piercing) | 71% / 0.5% / 0.03 | 77% / 1.4% / 0.07 |
| Push | 60% / 1.0% / 0.07 | 67% / 1.4% / 0.08 |
| Engulfing | never fired | never fired |
| Volume ≥ 1.5x average | 41% / 31.0% / 3.19 | 36% / 37.9% / 4.24 |
| Range ≥ 1.5x average bar | 43% / 32.0% / 3.18 | 34% / 31.9% / 3.73 |
| Next bar confirms (+1 bar) | 44% / 29.1% / 2.82 | 40% / 31.5% / 3.12 |
| Long tail | 40% / 15.0% / 1.58 | 37% / 17.0% / 1.82 |
| Long tail combo | 41% / 14.9% / 1.52 | 38% / 16.9% / 1.76 |
| Upper wick ≥ 50% (shape only) | 33% / 17.9% / 2.31 | 27% / 18.0% / 2.64 |
| Evening star | 22% / 1.1% / 0.21 | 21% / 1.1% / 0.21 |
| Close beyond the previous bar's extreme | 23% / 7.5% / 1.39 | 24% / 10.2% / 1.71 |

## Reproduction

Same scripts and settings as [AMD.md](AMD.md#reproduction): 5-min SIP bars with volume, real-time wave replay, candidates within 1 average bar of the running extreme after a 3-average-bar move, hits within one bar of the finished wave's extreme.
