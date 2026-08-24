# Watch list — as of 2026-08-23

Ranked over the trailing 2 week(s). **QQQ closed ABOVE its daily MA20 -> longs allowed**

Direction is decided by each ticker's opening range at 09:45, not in advance. A
candidate only trades if its OR closes on the biased side.

## Long candidates

| tkr | intraday hit | EOD hit | avg 15:50 | worst | trend | C/P | vol |
|---|---:|---:|---:|---:|---|---:|---:|
| SPCX | 100% | 100% | +2.67% | +0.34% | n/a | 0.72 | 0.75x |
| HOOD | 33% | 100% | +0.74% | +0.34% | MIXED | 2.40 | 4.37x |
| DECK | 100% | 67% | +0.51% | -0.96% | DOWNTREND | 0.65 | 1.27x |

Blocked: MRNA (MA20 extension, +4.90%), SNDK (MA20 extension, +2.73%), GWRE (MA20 extension, +0.65%)

## Short candidates

| tkr | intraday hit | EOD hit | avg 15:50 | worst | trend | C/P | vol |
|---|---:|---:|---:|---:|---|---:|---:|
| CRWV | 75% | 75% | +1.13% | -2.65% | MIXED | 0.70 | 0.47x |
| SPOT | 67% | 67% | +1.08% | -1.13% | MIXED | 2.41 | 0.59x |
| COIN | 100% | 100% | +0.95% | +0.47% | RECOVERY_ATTEMPT | 2.34 | 4.16x |

Blocked: APP (MA20 extension, +1.10%), META (MA20 extension, +0.89%), FN (MA20 extension, +1.99%), RH (MA20 extension, +0.32%)

## Review notes

Reviewed picks after weighing the other columns — **long SPCX, LLY, HOOD; short
CRWV, AMAT, AMD** — which differs from the mechanical ranking above:

- **DECK dropped** (ranked 3rd long): `DOWNTREND` label and put-heavy 0.65 C/P both
  argue against a long. Replaced with **LLY**, the only clean `STRONG_UP` at a sane
  extension (+5.7% over MA50) and the most call-heavy OI in the pool at 6.63.
- **SPOT and COIN dropped** (ranked 2nd and 3rd short): both have call-heavy OI
  fighting the short (2.41 and 2.34). COIN is additionally `RECOVERY_ATTEMPT` — a
  2.13x-volume reclaim of MA20 and MA50 with 15.5% runway to its MA200. Replaced
  with **AMAT** (put-heavy 0.50, below both MAs) and **AMD** (bull side won 1 of 6,
  nothing contradicting).
- **HOOD kept** despite 33% intraday hit: it won every session at 15:50 on 4.37x
  opening volume with call-heavy OI. Small grinding gains rather than momentum.
- Blocked names are right-direction-but-too-stretched, not rejected: MRNA sits 103%
  above its MA50 on the 08-19 gap; FN, APP and META are the strongest bear
  structures in the pool.

## Reliability

Recent-behaviour screen, not a forecast. A 2023-2026 walk-forward over 4,293
trades put ranking-based selection at +3.5bp per trade over taking every signal.
Average favourable excursion runs 1.5-2.2% per trade while holding to 15:50
captures near zero — any edge is in the exit, not the pick. See
`research/experiments/OR_WINRATE_STRATEGY_STUDY.md`.

## Files

| file | |
|---|---|
| `ticker_stats.txt` | full report output |
| `option_open_interest.json` | OI at bands [12, 16, 20] for the 2026-09-18 expiry |
| `range_distribution.pdf` | 20-session daily range% histogram per ticker |
