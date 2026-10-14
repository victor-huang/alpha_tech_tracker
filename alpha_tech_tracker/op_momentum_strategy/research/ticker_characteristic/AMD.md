# AMD — candle patterns at wave lows and highs

Which 5-min candles mark AMD's wave reversals, measured on 2026 (Jan 2 – Oct 13) and checked on 2025.
Studies run 2026-10-13/14. Method and terms: [README](README.md).

## Summary

- **At a real wave low or high, AMD's candle is bigger and on heavier volume than the look-alike bars
  around it — the shape barely differs.** At real lows the median bar is 1.20x the average bar range on
  1.23x average volume, against 0.94–0.97x and 0.88–0.94x for other near-low bars. Tops look the same
  (1.09–1.10x range, 1.20–1.21x volume vs 0.82–0.87x and 0.84–0.87x).
- **A long wick alone is no signal:** a lower wick of 50%+ of the range is at the real low 33–34% of the time,
  the same as any near-low bar (32%).
- **Two practical signals held in both years** (bottoms, baseline 32%):
  - a long tail followed by a bar that closes above its high: **57% at the real low in 2025 and 2026**,
    about once every two days, entered one bar late;
  - a lower wick of 50%+ on 1.5x average volume: **57% (2026) / 46% (2025)**, no wait.
- **Push and piercing are the most accurate (50–88%) but rare** — about once every one to three weeks.
- **Even the best signal is wrong about 43% of the time and catches only 6–8% of the lows.** It improves the
  odds of buying the low; it does not make lows predictable, and it has not yet been tested for P&L.

## Data and method

- AMD 5-min SIP bars, split-adjusted, with volume, Nov 2025 – Oct 13 2026 and Nov 2024 – Dec 2025.
- Real-time wave replay; candidate bars and hits as defined in the [README](README.md).
- Features of the candidate bar: lower and upper wick, close position in the range (0 = at the low, 1 = at
  the high), body, each as a share of the bar's range; range vs the average bar; volume vs the previous 78
  bars' average.
- Patterns: the five reversal patterns in `alpha_tech_tracker/technical_analysis.py` (`long_tail_reversal`,
  `long_tail_reversal_combo`, `engulfing_reversal`, `piercing_reversal`, `push_reversal`), with their daily
  1–1.5% minimum move replaced by the ticker's average 5-min bar (piercing's hard-coded 1.5% re-implemented
  with that minimum); plus morning / evening star (a big bar, a small body, then a bar closing past the first
  bar's midpoint) and two one-bar confirmations.

| Year | Candidate bottoms | At the real low | Candidate tops | At the real high | Sessions |
|---|---|---|---|---|---|
| 2025 | 3,039 | 980 (32.2%) | 3,462 | 949 (27.4%) | 230 / 234 |
| 2026 | 2,202 | 710 (32.2%) | 2,821 | 743 (26.3%) | 179 |

## The candle at the extreme vs the look-alikes (medians)

| | Lower wick | Upper wick | Close position | Body | Range vs avg bar | Volume vs avg |
|---|---|---|---|---|---|---|
| Bottoms 2026: at the real low | 26% | 18% | 0.40 | 48% | **1.20x** | **1.23x** |
| Bottoms 2026: other candidates | 25% | 21% | 0.42 | 47% | 0.94x | 0.88x |
| Bottoms 2025: at the real low | 23% | 16% | 0.42 | 51% | **1.20x** | **1.23x** |
| Bottoms 2025: other candidates | 25% | 21% | 0.41 | 46% | 0.97x | 0.94x |
| Tops 2026: at the real high | 19% | 22% | 0.59 | 49% | **1.09x** | **1.20x** |
| Tops 2026: other candidates | 22% | 24% | 0.57 | 46% | 0.82x | 0.87x |
| Tops 2025: at the real high | 19% | 24% | 0.61 | 50% | **1.10x** | **1.21x** |
| Tops 2025: other candidates | 23% | 24% | 0.58 | 44% | 0.87x | 0.84x |

Reading: the reversal bar is a small capitulation — a wider bar on more volume (sellers flush, buyers absorb
it, or the mirror at tops). Wick and close position are almost the same as the bars around it.

## Bottom signals (baseline precision 32.2% both years)

| Signal | 2026 precision / recall / per day | 2025 precision / recall / per day |
|---|---|---|
| Piercing | 88% / 1.0% / 0.04 | 67% / 1.0% / 0.07 |
| Push | 50% / 1.0% / 0.08 | 72% / 2.4% / 0.14 |
| Engulfing | 33% / 0.9% / 0.10 | 50% / 1.2% / 0.10 |
| **Long tail, next bar closes above its high (+1 bar)** | **57% / 7.5% / 0.52** | **57% / 6.6% / 0.50** |
| **Lower wick ≥ 50% and volume ≥ 1.5x** | **57% / 7.8% / 0.54** | **46% / 6.1% / 0.57** |
| Lower wick ≥ 50%, next bar closes above its high (+1) | 49% / 8.9% / 0.72 | 43% / 8.2% / 0.82 |
| Next bar closes above this bar's high (+1) | 48% / 32% / 2.68 | 45% / 30% / 2.79 |
| Long tail combo | 47% / 18% / 1.55 | 44% / 17% / 1.64 |
| Volume ≥ 1.5x average | 46% / 37% / 3.19 | 43% / 35% / 3.46 |
| Long tail | 46% / 18% / 1.59 | 42% / 17% / 1.70 |
| Volume ≥ 2x average | 44% / 17% / 1.51 | 44% / 18% / 1.74 |
| Range ≥ 1.5x average bar | 42% / 33% / 3.16 | 44% / 34% / 3.30 |
| Close above the previous bar's high, volume ≥ 1.5x | 39% / 3.2% / 0.33 | 41% / 2.8% / 0.29 |
| Lower wick ≥ 60% | 35% / 11% / 1.21 | 33% / 10% / 1.33 |
| Lower wick ≥ 50% | 34% / 19% / 2.25 | 33% / 18% / 2.37 |
| Lower wick ≥ 40% | 33% / 30% / 3.60 | 33% / 29% / 3.72 |
| Green bar | 31% / 37% / 4.74 | 32% / 38% / 5.01 |
| Morning star | 30% / 1.8% / 0.25 | 29% / 1.7% / 0.25 |
| Close above the previous bar's high | 26% / 9.2% / 1.40 | 25% / 8.3% / 1.41 |

## Top signals (baseline precision 26.3% in 2026, 27.4% in 2025)

| Signal | 2026 precision / recall / per day | 2025 precision / recall / per day |
|---|---|---|
| Push (bearish) | 75% / 2.4% / 0.13 | 69% / 1.0% / 0.06 |
| Dark cloud (bearish piercing) | 67% / 0.5% / 0.03 | 67% / 0.4% / 0.03 |
| **Upper wick ≥ 50% and volume ≥ 1.5x** | **45% / 5.8% / 0.54** | **44% / 6.2% / 0.58** |
| **Long tail, next bar closes below its low (+1 bar)** | **44% / 4.7% / 0.45** | **49% / 5.5% / 0.46** |
| Volume ≥ 1.5x average | 40% / 34% / 3.58 | 43% / 36% / 3.36 |
| Range ≥ 1.5x average bar | 39% / 28% / 2.99 | 42% / 30% / 2.87 |
| Volume ≥ 2x average | 38% / 18% / 1.92 | 45% / 20% / 1.80 |
| Long tail combo (bearish) | 37% / 12% / 1.37 | 38% / 13% / 1.44 |
| Long tail (bearish) | 36% / 12% / 1.42 | 37% / 13% / 1.49 |
| Next bar closes below this bar's low (+1) | 35% / 28% / 3.35 | 39% / 30% / 3.08 |
| Upper wick ≥ 50%, next bar closes below its low (+1) | 35% / 7.5% / 0.91 | 35% / 7.0% / 0.82 |
| Close below the previous bar's low, volume ≥ 1.5x | 30% / 1.8% / 0.25 | 35% / 2.3% / 0.27 |
| Evening star | 27% / 1.8% / 0.27 | 25% / 1.5% / 0.24 |
| Upper wick ≥ 50% | 26% / 16% / 2.58 | 24% / 15% / 2.59 |
| Red bar | 24% / 36% / 6.33 | 26% / 38% / 5.94 |
| Close below the previous bar's low | 17% / 8.2% / 1.96 | 18% / 7.5% / 1.68 |
| Engulfing (bearish) | never fired | never fired |

`engulfing_reversal`'s bearish side needs the second bar to open above the first bar's close, which rarely
happens between consecutive 5-min bars, so it never fired on AMD's tops.

## What it means

1. **Look for size and volume, not just shape.** A long-tail bar is a better low only because the pattern
   requires a decent-sized bar; the wick itself adds nothing. The combination that works is the long wick on
   heavy volume, or the long tail confirmed by the next bar.
2. **Confirmation costs one bar and buys accuracy.** "Next bar closes above the signal bar's high" alone is at
   the low 45–48% of the time and catches about 30% of lows; on a long-tail bar it reaches 57%.
3. **Closing beyond the previous bar is late, not early.** At bottoms it is at the low only 25–26% of the
   time (below the baseline): by then the low is usually two or more bars back.
4. **Piercing and push are the high-confidence tier** but too rare to trade alone (one firing every one to
   three weeks).
5. **This is about finding the low, not about profit.** In the dip-buying tests the high-volume signal bar
   had a *lower* win rate under the first-reversal exit (2026, Jan–Jun 35% vs 54% for low volume), because a
   capitulation bar is wide and so is the distance to the stop. Being at the low is necessary, not sufficient.

## Related AMD results

- **Light-volume dips buy better** (ticker-tuning doc, Findings 27–31 work): long-tail dip buys where the dip's
  average volume is under 0.77x the prior up wave's beat other dips in every year 2021–2026 (+0.07% vs −0.08%
  per trade in 2023–26, 45% vs 39% won; first bearish long tail exit, stop 1 average bar). Across 27 tickers the
  same rule did nothing, so it is AMD-specific or chance.
- **Piercing was AMD's best entry pattern** chosen on 2020–22 (+0.28% per trade) and held on 2023–26 (+0.21%,
  54% won, 43 trades).
- **Drive long on AMD** made +37% summed per trade over 2020–2026 with the first-bar-low stop; a daily MA20 switch
  turned it into −16% (Finding 28). Jul–Oct 2026: drive long −1.5% with the first-bar-low stop, +2.7% with the
  2 x average-bar stop; overnight above MA200 +14.2%; buy and hold +9.1%.
- **Wave turns confirm too late to trade on their own:** buying AMD's confirmed turns up from July to October 2026
  lost −8.5% over 180 trades (median 15 minutes and 0.5% after the low).

## Next steps

- Trade the bottom signals with the top signals as exits on AMD 2020–2024 (years the signals were not found on):
  long tail + confirming bar, lower wick + volume, and push / piercing, with stops and costs.
- Repeat this page's study for the other monitored tickers to see which share AMD's "size and volume" profile.

## Reproduction

One-off scripts, not committed (session scratchpad): `extreme_candles.py` takes a pickle of 5-min bars with
volume (from `StockBarsRequest(..., Adjustment.SPLIT, DataFeed.SIP)` through `regular_hours`, volume re-attached
because `regular_hours` keeps OHLC only) and a year, replays the waves with `alpha_tech_tracker.wave.Wave` exactly
as `analyze_bars` does (session reset, minimum wave size = 2 x the trailing 78-bar average range %), collects
the candidate bars, labels hits against each finished wave's lowest low / highest high (wicks, within one bar),
and tabulates the features and patterns above.
