# CRWV — candle patterns at wave lows and highs

Which 5-min candles mark CRWV's wave reversals, 2025 and 2026 (to Oct 13). Studies run 2026-10-14. Method and terms: [README](README.md); the same study for AMD, with every definition spelled out: [AMD.md](AMD.md).

## Summary

- Volume marks CRWV's extremes more than any other ticker here: 1.39x average at real lows in 2025 (0.97x elsewhere) and 1.34x at highs; volume ≥ 1.5x caught 45% of 2025's lows.
- Long tail + confirmation: 56% / 51% at lows, 57% / 49% at highs (2025 / 2026).
- 2025 covers only the months after the March 2025 listing (178 sessions).
- Shared with every monitored ticker: a long wick alone is no better than the baseline, closing beyond the previous bar is late (below the baseline), and the reversal bar is wider and on heavier volume than the bars around it.

## Candidates

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 2,493 | 31.4% | 2,355 | 29.3% | 178 |
| 2026 | 2,669 | 29.3% | 2,534 | 28.8% | 182 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2025: at the real low | 24% | 16% | 0.37 | 53% | **1.24x** | **1.39x** |
| Bottoms 2025: other candidates | 26% | 20% | 0.40 | 45% | 0.96x | 0.97x |
| Bottoms 2026: at the real low | 22% | 16% | 0.39 | 53% | **1.08x** | **1.17x** |
| Bottoms 2026: other candidates | 23% | 22% | 0.41 | 46% | 0.84x | 0.84x |
| Tops 2025: at the real high | 17% | 23% | 0.60 | 51% | **1.19x** | **1.34x** |
| Tops 2025: other candidates | 23% | 24% | 0.60 | 45% | 0.92x | 0.90x |
| Tops 2026: at the real high | 19% | 24% | 0.60 | 50% | **1.15x** | **1.25x** |
| Tops 2026: other candidates | 21% | 25% | 0.59 | 46% | 0.92x | 0.87x |

## Bottom signals (baseline 31.4% in 2025, 29.3% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 56% / 7.2% / 0.56 | 51% / 5.2% / 0.45 |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | 48% / 8.0% / 0.74 | 41% / 6.6% / 0.70 |
| Piercing | 88% / 0.9% / 0.04 | 55% / 0.8% / 0.06 |
| Push | 71% / 1.5% / 0.10 | 67% / 1.3% / 0.08 |
| Engulfing | 50% / 1.3% / 0.11 | 47% / 0.9% / 0.08 |
| Volume ≥ 1.5x average | 45% / 44.8% / 4.42 | 43% / 33.9% / 3.36 |
| Range ≥ 1.5x average bar | 45% / 36.3% / 3.51 | 42% / 29.2% / 2.99 |
| Next bar confirms (+1 bar) | 46% / 31.4% / 3.03 | 41% / 28.5% / 2.98 |
| Long tail | 39% / 16.5% / 1.84 | 35% / 12.3% / 1.52 |
| Long tail combo | 40% / 16.5% / 1.79 | 36% / 12.3% / 1.48 |
| Lower wick ≥ 50% (shape only) | 31% / 17.1% / 2.45 | 28% / 18.8% / 2.85 |
| Morning star | 23% / 1.3% / 0.24 | 29% / 1.3% / 0.19 |
| Close beyond the previous bar's extreme | 21% / 7.2% / 1.49 | 18% / 6.4% / 1.56 |

## Top signals (baseline 29.3% in 2025, 28.8% in 2026)

Precision / recall / firings per day.

| Signal | 2025 | 2026 |
|---|---|---|
| **Long tail, next bar confirms (+1 bar)** | 57% / 7.2% / 0.51 | 49% / 6.2% / 0.51 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | 43% / 7.5% / 0.70 | 38% / 5.7% / 0.63 |
| Dark cloud (bearish piercing) | 83% / 0.7% / 0.03 | 100% / 0.3% / 0.01 |
| Push | 64% / 1.0% / 0.06 | 54% / 1.0% / 0.07 |
| Engulfing | never fired | never fired |
| Volume ≥ 1.5x average | 42% / 42.3% / 4.05 | 40% / 36.1% / 3.68 |
| Range ≥ 1.5x average bar | 41% / 31.8% / 3.15 | 38% / 30.5% / 3.28 |
| Next bar confirms (+1 bar) | 44% / 29.4% / 2.71 | 37% / 28.6% / 3.16 |
| Long tail | 43% / 16.5% / 1.56 | 35% / 13.8% / 1.61 |
| Long tail combo | 44% / 16.5% / 1.52 | 35% / 13.8% / 1.61 |
| Upper wick ≥ 50% (shape only) | 29% / 16.1% / 2.20 | 28% / 15.7% / 2.33 |
| Evening star | 21% / 1.0% / 0.19 | 25% / 1.4% / 0.22 |
| Close beyond the previous bar's extreme | 21% / 7.4% / 1.41 | 17% / 7.0% / 1.65 |

## Reproduction

Same scripts and settings as [AMD.md](AMD.md#reproduction): 5-min SIP bars with volume, real-time wave replay, candidates within 1 average bar of the running extreme after a 3-average-bar move, hits within one bar of the finished wave's extreme.
