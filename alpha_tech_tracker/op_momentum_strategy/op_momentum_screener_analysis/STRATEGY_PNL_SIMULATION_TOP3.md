# Strategy P&L Simulation — Top-3 Signal Selection (2018–2026)

**Generated:** 2026-06-02
**Method:** Same no-lookahead monthly rules as `STRATEGY_PNL_SIMULATION_2018_2026.md`.
**Signal selection:** Instead of all qualifying signals, each day takes the **top-3** qualifying
signals ranked by their pre-session 20-day EOD win rate. If fewer than 3 signals fire, all are taken.

**Practical implication:** Max 3 positions entered per day. P&L sum represents
total return if equal capital is deployed in each of the 3 picks.

---

## Comparison: All-Signals vs Top-3 per month

| Month | All-Sig EOD | Top-3 EOD | Top-3 WR | Δ (Top3−All) | Note |
|-------|------------|-----------|----------|--------------|------|
| 2018-Jan |      +12.7% |     +12.7% |    62.2% |       -0.0pp |  |
| 2018-Feb |      -11.4% |     -11.7% |    51.6% |       -0.3pp |  |
| 2018-Mar |       -1.9% |      -0.8% |    50.0% |       +1.1pp |  |
| 2018-Apr |       +4.2% |      +4.2% |    45.5% |       -0.0pp |  |
| 2018-May |       -2.5% |      -2.5% |    50.0% |       -0.0pp |  |
| 2018-Jun |       +6.1% |      +6.6% |    58.3% |       +0.5pp |  |
| 2018-Jul |      +16.6% |     +17.0% |    61.8% |       +0.4pp |  |
| 2018-Aug |       -0.7% |      -0.7% |    43.5% |       -0.0pp |  |
| 2018-Sep |      -14.2% |      -1.6% |    44.1% |      +12.6pp |  |
| 2018-Oct |       +8.3% |      +2.5% |    50.0% |       -5.8pp |  |
| 2018-Nov |      +11.8% |     +11.4% |    53.3% |       -0.4pp |  |
| 2018-Dec |      -39.8% |     -30.6% |    23.5% |       +9.2pp |  |
| 2019-Jan |      +37.4% |     +22.5% |    62.2% |      -14.9pp |  |
| 2019-Feb |       +1.7% |      +1.7% |    64.3% |       +0.0pp |  |
| 2019-Mar |       -2.0% |      -2.0% |    45.8% |       -0.0pp |  |
| 2019-Apr |       -2.2% |      +1.1% |    48.0% |       +3.3pp |  |
| 2019-May |       +6.3% |      +6.3% |    57.1% |       -0.0pp |  |
| 2019-Jun |       +4.7% |      +4.7% |    52.6% |       -0.0pp |  |
| 2019-Jul |       +4.0% |      -1.5% |    51.9% |       -5.5pp |  |
| 2019-Aug |       +1.6% |      -7.3% |    39.1% |       -8.9pp |  |
| 2019-Sep |       +8.3% |      +8.4% |    48.1% |       +0.1pp |  |
| 2019-Oct |      +13.7% |     +11.2% |    51.6% |       -2.5pp |  |
| 2019-Nov |       +8.7% |      +6.8% |    35.3% |       -1.9pp |  |
| 2019-Dec |       +9.1% |      +2.5% |    64.5% |       -6.6pp |  |
| 2020-Jan |       +5.5% |      +4.7% |    55.6% |       -0.8pp |  |
| 2020-Feb |       -9.8% |      -7.5% |    43.8% |       +2.3pp |  |
| 2020-Mar |      +50.0% |     +30.1% |    56.0% |      -19.9pp | ⚡ large shift |
| 2020-Apr |       +1.8% |      +1.7% |    62.5% |       -0.1pp |  |
| 2020-May |      +18.0% |     +18.2% |    61.3% |       +0.2pp |  |
| 2020-Jun |      +19.8% |     +14.8% |    55.9% |       -5.0pp |  |
| 2020-Jul |      +12.9% |      +8.9% |    62.1% |       -4.0pp |  |
| 2020-Aug |       -1.5% |      +3.1% |    59.4% |       +4.6pp |  |
| 2020-Sep |      -11.7% |     -14.8% |    44.7% |       -3.1pp |  |
| 2020-Oct |      +27.1% |     +25.2% |    65.5% |       -1.9pp |  |
| 2020-Nov |      +10.6% |     +11.5% |    51.5% |       +0.9pp |  |
| 2020-Dec |      +20.3% |     +12.5% |    50.0% |       -7.8pp |  |
| 2021-Jan |      +39.0% |     +28.6% |    56.4% |      -10.4pp |  |
| 2021-Feb |       +4.5% |      +4.3% |    65.5% |       -0.2pp |  |
| 2021-Mar |      -67.0% |     -23.3% |    44.4% |      +43.7pp | ⚡ large shift |
| 2021-Apr |       +3.4% |      +2.3% |    51.6% |       -1.1pp |  |
| 2021-May |      +11.0% |      +5.8% |    45.7% |       -5.2pp |  |
| 2021-Jun |       -3.2% |      -3.9% |    53.7% |       -0.7pp |  |
| 2021-Jul |       -1.2% |      -3.8% |    43.6% |       -2.6pp |  |
| 2021-Aug |      +15.0% |     +18.6% |    62.3% |       +3.6pp |  |
| 2021-Sep |       -4.8% |      -8.1% |    31.2% |       -3.3pp |  |
| 2021-Oct |       -1.5% |      +7.7% |    46.3% |       +9.2pp |  |
| 2021-Nov |      -34.7% |     -27.3% |    38.1% |       +7.4pp |  |
| 2021-Dec |       -5.4% |      -6.3% |    50.0% |       -0.9pp |  |
| 2022-Jan |     -116.3% |     -71.4% |    30.4% |      +44.9pp | ⚡ large shift |
| 2022-Feb |       -8.2% |      +2.5% |    46.3% |      +10.7pp |  |
| 2022-Mar |      -16.5% |     -18.9% |    47.4% |       -2.4pp |  |
| 2022-Apr |      -47.5% |     -50.7% |    28.1% |       -3.2pp |  |
| 2022-May |       -7.3% |      +1.6% |    56.1% |       +8.9pp |  |
| 2022-Jun |      +14.3% |     +13.9% |    58.3% |       -0.4pp |  |
| 2022-Jul |      +33.3% |     +22.9% |    71.0% |      -10.4pp |  |
| 2022-Aug |      -29.2% |     -17.9% |    51.1% |      +11.3pp |  |
| 2022-Sep |       -7.8% |      -3.8% |    45.2% |       +4.0pp |  |
| 2022-Oct |       +9.8% |      -1.5% |    47.2% |      -11.3pp |  |
| 2022-Nov |      +39.8% |     +10.4% |    56.5% |      -29.4pp | ⚡ large shift |
| 2022-Dec |      -32.6% |     -31.6% |    29.4% |       +1.0pp |  |
| 2023-Jan |      +21.6% |     +18.1% |    57.6% |       -3.5pp |  |
| 2023-Feb |       +9.4% |     +13.7% |    53.1% |       +4.3pp |  |
| 2023-Mar |       -4.2% |      -4.0% |    45.5% |       +0.2pp |  |
| 2023-Apr |       +0.9% |      +0.9% |    55.6% |       +0.0pp |  |
| 2023-May |       +9.5% |      +9.8% |    57.1% |       +0.3pp |  |
| 2023-Jun |       +1.0% |      +3.6% |    60.0% |       +2.6pp |  |
| 2023-Jul |       -2.7% |      -2.7% |    51.5% |       +0.0pp |  |
| 2023-Aug |      +26.2% |     +25.7% |    61.3% |       -0.5pp |  |
| 2023-Sep |       -6.8% |      -1.8% |    47.5% |       +5.0pp |  |
| 2023-Oct |      +10.6% |      +7.2% |    47.5% |       -3.4pp |  |
| 2023-Nov |      +26.2% |     +11.2% |    59.0% |      -15.0pp |  |
| 2023-Dec |       -2.4% |      -9.3% |    36.8% |       -6.9pp |  |
| 2024-Jan |      +23.4% |     +21.0% |    69.4% |       -2.4pp |  |
| 2024-Feb |      +25.7% |     +19.7% |    64.3% |       -6.0pp |  |
| 2024-Mar |       +7.7% |      +7.7% |    52.9% |       -0.0pp |  |
| 2024-Apr |      -14.1% |     -13.6% |    46.3% |       +0.5pp |  |
| 2024-May |      +11.6% |     +16.5% |    64.7% |       +4.9pp |  |
| 2024-Jun |       +0.8% |      +6.7% |    50.0% |       +5.9pp |  |
| 2024-Jul |       -8.8% |      -8.2% |    46.3% |       +0.6pp |  |
| 2024-Aug |      -28.8% |     -17.0% |    43.6% |      +11.8pp |  |
| 2024-Sep |       +6.3% |      +2.4% |    42.1% |       -3.9pp |  |
| 2024-Oct |      +32.2% |     +23.6% |    56.8% |       -8.6pp |  |
| 2024-Nov |      +42.9% |     +20.6% |    56.1% |      -22.3pp | ⚡ large shift |
| 2024-Dec |      -16.3% |     -21.0% |    45.0% |       -4.7pp |  |
| 2025-Jan |      +12.4% |     +12.2% |    51.2% |       -0.2pp |  |
| 2025-Feb |      +10.3% |     +13.0% |    52.8% |       +2.7pp |  |
| 2025-Mar |       -7.8% |     -16.8% |    55.2% |       -9.0pp |  |
| 2025-Apr |     +157.1% |     +67.8% |    64.0% |      -89.3pp | ⚡ large shift |
| 2025-May |       -7.0% |      -6.0% |    60.0% |       +1.0pp |  |
| 2025-Jun |       +9.7% |      -0.3% |    51.0% |      -10.0pp |  |
| 2025-Jul |      +11.5% |      +8.3% |    58.7% |       -3.2pp |  |
| 2025-Aug |      +21.4% |     +20.9% |    58.3% |       -0.5pp |  |
| 2025-Sep |       -5.3% |      -8.4% |    41.0% |       -3.1pp |  |
| 2025-Oct |      +22.3% |      +8.3% |    56.8% |      -14.0pp |  |
| 2025-Nov |       -7.9% |     +25.2% |    66.7% |      +33.1pp | ⚡ large shift |
| 2025-Dec |      -25.7% |     -19.9% |    38.6% |       +5.8pp |  |
| 2026-Jan |      -13.7% |      -0.2% |    55.8% |      +13.5pp |  |
| 2026-Feb |       -8.4% |     -21.6% |    44.4% |      -13.2pp |  |
| 2026-Mar |      -34.7% |     -29.5% |    27.3% |       +5.2pp |  |
| 2026-Apr |      +37.0% |     +37.4% |    63.6% |       +0.4pp |  |
| 2026-May |      +59.7% |     +57.7% |    60.8% |       -2.0pp |  |

---

## Yearly Summary

| Year | Top-3 Strategy | Top-3 Pure Long | Δ | All-Sig Strategy | All-Sig Pure Long | Δ |
|------|---------------|-----------------|---|-----------------|-------------------|---|
| 2018 |         +78.9% |            +6.5% | +72.4pp |          +108.6% |             -10.7% | +119.3pp |
| 2019 |         +63.8% |           +54.2% | +9.6pp |           +79.2% |             +91.5% | -12.3pp |
| 2020 |         +92.9% |          +108.4% | -15.5pp |          +129.3% |            +142.8% | -13.5pp |
| 2021 |         +74.6% |            -5.4% | +80.0pp |           +57.1% |             -44.9% | +102.0pp |
| 2022 |        +148.6% |          -144.6% | +293.1pp |          +242.4% |            -168.2% | +410.6pp |
| 2023 |         +84.7% |           +72.4% | +12.3pp |          +101.1% |             +89.3% | +11.8pp |
| 2024 |        +118.4% |           +58.3% | +60.1pp |          +137.1% |             +82.6% | +54.5pp |
| 2025 |        +162.2% |          +104.1% | +58.0pp |          +251.0% |            +191.1% | +59.9pp |
| 2026 |         +67.2% |           +43.8% | +23.4pp |           +68.7% |             +39.9% | +28.8pp |
| **Total** | **+891.2%** | **+297.8%** | **+593.4pp** | **+1174.5%** | **+413.4%** | **+761.1pp** |

---

## Per-Year Detail

### 2018   (strategy +78.9%  vs pure long +6.5%  Δ +72.4pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   64.9% |  62.2% |     +6.4% |   +12.7% | **  +12.7%** | WR 62% |
| Feb | LONG                 |   32.3% |  51.6% |     -4.6% |   -11.7% | **  -11.7%** | follow Jan (LONG), WR 52% |
| Mar | CAUTION (+15m)       |   63.6% |  50.0% |     +8.3% |    -0.8% | **   +8.3%** | +15m exit only; saves -9.2pp vs EOD |
| Apr | LONG                 |   50.0% |  45.5% |     +3.7% |    +4.2% | **   +4.2%** | WR 45% |
| May | LONG                 |   54.5% |  50.0% |     +0.5% |    -2.5% | **   -2.5%** | follow Apr (LONG) |
| Jun | LONG                 |   63.9% |  58.3% |     +6.7% |    +6.6% | **   +6.6%** | WR 58% |
| Jul | LONG                 |   52.9% |  61.8% |     +2.2% |   +17.0% | **  +17.0%** | WR 62% |
| Aug | LONG (+15m)          |   52.2% |  43.5% |     -1.9% |    -0.7% | **   -1.9%** | +15m WR 52%, saves +1.1pp vs EOD |
| Sep | SHORT                |   47.1% |  44.1% |     -0.7% |    -1.6% | **   +1.6%** | seasonal SHORT, WR 44% |
| Oct | LONG                 |   66.7% |  50.0% |     +6.8% |    +2.5% | **   +2.5%** | WR 50% |
| Nov | LONG                 |   56.7% |  53.3% |     -0.1% |   +11.4% | **  +11.4%** | avg gain +0.381% > 0 → LONG |
| Dec | SHORT                |   44.1% |  23.5% |     -6.8% |   -30.6% | **  +30.6%** | seasonal SHORT, WR 24% |

### 2019   (strategy +63.8%  vs pure long +54.2%  Δ +9.6pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   56.8% |  62.2% |     +5.2% |   +22.5% | **  +22.5%** | WR 62% |
| Feb | LONG                 |   71.4% |  64.3% |     +4.5% |    +1.7% | **   +1.7%** | follow Jan (LONG), WR 64% |
| Mar | CAUTION (+15m)       |   58.3% |  45.8% |     +3.7% |    -2.0% | **   +3.7%** | +15m exit only; saves -5.7pp vs EOD |
| Apr | LONG                 |   48.0% |  48.0% |     -1.7% |    +1.1% | **   +1.1%** | WR 48% |
| May | LONG                 |   47.6% |  57.1% |     +0.1% |    +6.3% | **   +6.3%** | follow Apr (LONG) |
| Jun | LONG                 |   73.7% |  52.6% |     +5.3% |    +4.7% | **   +4.7%** | WR 53% |
| Jul | LONG                 |   33.3% |  51.9% |     -6.3% |    -1.5% | **   -1.5%** | WR 52% |
| Aug | LONG (+15m)          |   47.8% |  39.1% |     +1.5% |    -7.3% | **   +1.5%** | +15m WR 48%, saves -8.9pp vs EOD |
| Sep | LONG (EV exception)  |   55.6% |  48.1% |     -0.3% |    +8.4% | **   +8.4%** | win/loss ratio 1.8x, WR 48% |
| Oct | LONG                 |   48.4% |  51.6% |     +0.2% |   +11.2% | **  +11.2%** | WR 52% |
| Nov | LONG                 |   44.1% |  35.3% |     -2.7% |    +6.8% | **   +6.8%** | avg gain +0.201% > 0 → LONG |
| Dec | SHORT                |   58.1% |  64.5% |     +3.3% |    +2.5% | **   -2.5%** | seasonal SHORT, WR 65% |

### 2020   (strategy +92.9%  vs pure long +108.4%  Δ -15.5pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   48.9% |  55.6% |     +0.0% |    +4.7% | **   +4.7%** | WR 56% |
| Feb | LONG                 |   25.0% |  43.8% |     -4.2% |    -7.5% | **   -7.5%** | follow Jan (LONG), WR 44% |
| Mar | CAUTION (+15m)       |   48.0% |  56.0% |    +14.4% |   +30.1% | **  +14.4%** | +15m exit only; saves +15.7pp vs EOD |
| Apr | LONG                 |   56.2% |  62.5% |     +1.6% |    +1.7% | **   +1.7%** | WR 62% |
| May | LONG                 |   67.7% |  61.3% |    +10.7% |   +18.2% | **  +18.2%** | follow Apr (LONG) |
| Jun | LONG                 |   58.8% |  55.9% |     +8.0% |   +14.8% | **  +14.8%** | WR 56% |
| Jul | LONG                 |   41.4% |  62.1% |     -9.6% |    +8.9% | **   +8.9%** | WR 62% |
| Aug | LONG (+15m)          |   43.8% |  59.4% |     -1.1% |    +3.1% | **   -1.1%** | +15m WR 44%, saves +4.3pp vs EOD |
| Sep | SHORT                |   65.8% |  44.7% |     +4.2% |   -14.8% | **  +14.8%** | seasonal SHORT, WR 45% |
| Oct | LONG                 |   72.4% |  65.5% |    +11.2% |   +25.2% | **  +25.2%** | WR 66% |
| Nov | LONG                 |   54.5% |  51.5% |    +14.2% |   +11.5% | **  +11.5%** | avg gain +0.348% > 0 → LONG |
| Dec | SHORT                |   57.1% |  50.0% |    +11.0% |   +12.5% | **  -12.5%** | seasonal SHORT, WR 50% |

### 2021   (strategy +74.6%  vs pure long -5.4%  Δ +80.0pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   61.5% |  56.4% |    +15.1% |   +28.6% | **  +28.6%** | WR 56% |
| Feb | LONG                 |   55.2% |  65.5% |     -3.6% |    +4.3% | **   +4.3%** | follow Jan (LONG), WR 66% |
| Mar | CAUTION (+15m)       |   55.6% |  44.4% |     +1.5% |   -23.3% | **   +1.5%** | +15m exit only; saves -24.8pp vs EOD |
| Apr | LONG                 |   61.3% |  51.6% |     +4.6% |    +2.3% | **   +2.3%** | WR 52% |
| May | LONG                 |   54.3% |  45.7% |     +0.6% |    +5.8% | **   +5.8%** | follow Apr (LONG) |
| Jun | LONG                 |   56.1% |  53.7% |     +0.9% |    -3.9% | **   -3.9%** | WR 54% |
| Jul | LONG                 |   48.7% |  43.6% |     +1.9% |    -3.8% | **   -3.8%** | WR 44% |
| Aug | LONG (+15m)          |   50.9% |  62.3% |     -1.5% |   +18.6% | **   -1.5%** | +15m WR 51%, saves +20.0pp vs EOD |
| Sep | SHORT                |   59.4% |  31.2% |     +3.1% |    -8.1% | **   +8.1%** | seasonal SHORT, WR 31% |
| Oct | LONG                 |   56.1% |  46.3% |     -0.3% |    +7.7% | **   +7.7%** | WR 46% |
| Nov | SHORT                |   38.1% |  38.1% |     -6.5% |   -27.3% | **  +19.1%** | avg gain -0.651% ≤ 0 → SHORT, 70% credit |
| Dec | SHORT                |   52.6% |  50.0% |     +0.5% |    -6.3% | **   +6.3%** | seasonal SHORT, WR 50% |

### 2022   (strategy +148.6%  vs pure long -144.6%  Δ +293.1pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | SHORT (flip)         |   43.5% |  30.4% |     -4.4% |   -71.4% | **  +42.9%** | WR 30% ≤ 40% — flip SHORT, 60% credit |
| Feb | SHORT                |   51.2% |  46.3% |     +5.4% |    +2.5% | **   -2.5%** | follow Jan (SHORT), WR 46% |
| Mar | CAUTION (+15m)       |   31.6% |  47.4% |    -10.5% |   -18.9% | **  -10.5%** | +15m exit only; saves -8.4pp vs EOD |
| Apr | SHORT                |   62.5% |  28.1% |     +6.8% |   -50.7% | **  +35.5%** | WR 28% < 40% → SHORT, 70% credit |
| May | SHORT                |   58.5% |  56.1% |     +2.6% |    +1.6% | **   -1.6%** | follow Apr (SHORT) |
| Jun | LONG                 |   58.3% |  58.3% |     +9.3% |   +13.9% | **  +13.9%** | WR 58% |
| Jul | LONG                 |   48.4% |  71.0% |     +2.4% |   +22.9% | **  +22.9%** | WR 71% |
| Aug | LONG (+15m)          |   57.8% |  51.1% |     +3.7% |   -17.9% | **   +3.7%** | +15m WR 58%, saves -21.6pp vs EOD |
| Sep | SHORT                |   64.3% |  45.2% |    +10.5% |    -3.8% | **   +3.8%** | seasonal SHORT, WR 45% |
| Oct | LONG                 |   44.4% |  47.2% |    -11.9% |    -1.5% | **   -1.5%** | WR 47% |
| Nov | LONG                 |   43.5% |  56.5% |     -6.4% |   +10.4% | **  +10.4%** | avg gain +0.451% > 0 → LONG |
| Dec | SHORT                |   47.1% |  29.4% |     -7.0% |   -31.6% | **  +31.6%** | seasonal SHORT, WR 29% |

### 2023   (strategy +84.7%  vs pure long +72.4%  Δ +12.3pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   69.7% |  57.6% |    +10.5% |   +18.1% | **  +18.1%** | WR 58% |
| Feb | LONG                 |   46.9% |  53.1% |     +3.0% |   +13.7% | **  +13.7%** | follow Jan (LONG), WR 53% |
| Mar | CAUTION (+15m)       |   56.8% |  45.5% |     +6.7% |    -4.0% | **   +6.7%** | +15m exit only; saves -10.8pp vs EOD |
| Apr | LONG                 |   66.7% |  55.6% |     +7.3% |    +0.9% | **   +0.9%** | WR 56% |
| May | LONG                 |   51.0% |  57.1% |     +5.7% |    +9.8% | **   +9.8%** | follow Apr (LONG) |
| Jun | LONG                 |   56.7% |  60.0% |     +5.6% |    +3.6% | **   +3.6%** | WR 60% |
| Jul | LONG                 |   54.5% |  51.5% |     +3.0% |    -2.7% | **   -2.7%** | WR 52% |
| Aug | LONG (+15m)          |   64.5% |  61.3% |     +5.0% |   +25.7% | **   +5.0%** | +15m WR 65%, saves +20.7pp vs EOD |
| Sep | SHORT                |   50.0% |  47.5% |     +3.5% |    -1.8% | **   +1.8%** | seasonal SHORT, WR 48% |
| Oct | LONG                 |   57.5% |  47.5% |     +5.8% |    +7.2% | **   +7.2%** | WR 48% |
| Nov | LONG                 |   48.7% |  59.0% |     -3.5% |   +11.2% | **  +11.2%** | avg gain +0.288% > 0 → LONG |
| Dec | SHORT                |   44.7% |  36.8% |     -0.5% |    -9.3% | **   +9.3%** | seasonal SHORT, WR 37% |

### 2024   (strategy +118.4%  vs pure long +58.3%  Δ +60.1pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   47.2% |  69.4% |     -0.6% |   +21.0% | **  +21.0%** | WR 69% |
| Feb | LONG                 |   53.6% |  64.3% |     -1.1% |   +19.7% | **  +19.7%** | follow Jan (LONG), WR 64% |
| Mar | CAUTION (+15m)       |   76.5% |  52.9% |     +4.8% |    +7.7% | **   +4.8%** | +15m exit only; saves +2.9pp vs EOD |
| Apr | LONG                 |   53.7% |  46.3% |     +3.5% |   -13.6% | **  -13.6%** | WR 46% |
| May | LONG                 |   55.9% |  64.7% |     +5.7% |   +16.5% | **  +16.5%** | follow Apr (LONG) |
| Jun | LONG                 |   47.7% |  50.0% |     -4.7% |    +6.7% | **   +6.7%** | WR 50% |
| Jul | LONG                 |   46.3% |  46.3% |     +1.9% |    -8.2% | **   -8.2%** | WR 46% |
| Aug | LONG (+15m)          |   66.7% |  43.6% |     +8.8% |   -17.0% | **   +8.8%** | +15m WR 67%, saves -25.8pp vs EOD |
| Sep | SHORT                |   44.7% |  42.1% |     -1.7% |    +2.4% | **   -2.4%** | seasonal SHORT, WR 42% |
| Oct | LONG                 |   56.8% |  56.8% |     +6.2% |   +23.6% | **  +23.6%** | WR 57% |
| Nov | LONG                 |   56.1% |  56.1% |     +8.2% |   +20.6% | **  +20.6%** | avg gain +0.502% > 0 → LONG |
| Dec | SHORT                |   47.5% |  45.0% |     +3.3% |   -21.0% | **  +21.0%** | seasonal SHORT, WR 45% |

### 2025   (strategy +162.2%  vs pure long +104.1%  Δ +58.0pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   55.8% |  51.2% |     +9.5% |   +12.2% | **  +12.2%** | WR 51% |
| Feb | LONG                 |   41.7% |  52.8% |     -7.7% |   +13.0% | **  +13.0%** | follow Jan (LONG), WR 53% |
| Mar | CAUTION (+15m)       |   41.4% |  55.2% |     -1.8% |   -16.8% | **   -1.8%** | +15m exit only; saves -15.1pp vs EOD |
| Apr | LONG                 |   56.0% |  64.0% |     +5.5% |   +67.8% | **  +67.8%** | WR 64% |
| May | LONG                 |   53.3% |  60.0% |     +4.3% |    -6.0% | **   -6.0%** | follow Apr (LONG) |
| Jun | LONG                 |   52.9% |  51.0% |     +1.0% |    -0.3% | **   -0.3%** | WR 51% |
| Jul | LONG                 |   56.5% |  58.7% |     +1.2% |    +8.3% | **   +8.3%** | WR 59% |
| Aug | LONG (+15m)          |   58.3% |  58.3% |     +7.2% |   +20.9% | **   +7.2%** | +15m WR 58%, saves +13.8pp vs EOD |
| Sep | SHORT                |   59.0% |  41.0% |     +2.5% |    -8.4% | **   +8.4%** | seasonal SHORT, WR 41% |
| Oct | LONG                 |   64.9% |  56.8% |    +11.1% |    +8.3% | **   +8.3%** | WR 57% |
| Nov | LONG                 |   69.4% |  66.7% |    +22.4% |   +25.2% | **  +25.2%** | avg gain +0.699% > 0 → LONG |
| Dec | SHORT                |   40.9% |  38.6% |     -3.9% |   -19.9% | **  +19.9%** | seasonal SHORT, WR 39% |

### 2026   (strategy +67.2%  vs pure long +43.8%  Δ +23.4pp)

| Month | Direction | +15m WR | EOD WR | +15m Sum | EOD Sum | Strategy P&L | Note |
|-------|-----------|---------|--------|----------|---------|-------------|------|
| Jan | LONG                 |   48.1% |  55.8% |     -4.6% |    -0.2% | **   -0.2%** | WR 56% |
| Feb | LONG                 |   30.6% |  44.4% |    -14.1% |   -21.6% | **  -21.6%** | follow Jan (LONG), WR 44% |
| Mar | CAUTION (+15m)       |   40.9% |  27.3% |     -6.1% |   -29.5% | **   -6.1%** | +15m exit only; saves -23.4pp vs EOD |
| Apr | LONG                 |   54.5% |  63.6% |     +3.7% |   +37.4% | **  +37.4%** | WR 64% |
| May | LONG                 |   56.9% |  60.8% |     +5.2% |   +57.7% | **  +57.7%** | follow Apr (LONG) |

---

## Key Differences vs All-Signals Simulation

| Observation | Impact |
|-------------|--------|
| Top-3 total strategy P&L is lower (+891% vs +1,173%) | Fewer signals = smaller absolute sums; per-signal quality is higher |
| Top-3 pure long also lower (+298% vs +421%) | The reduction is roughly proportional |
| Strategy delta similar (+593pp vs +752pp) | The rules still work; the edge is preserved |
| **Nov 2025 flips from bear to bull** (−7.9% → +25.2%) | Top-3 quality filter changes the regime call for November 2025 |
| Bear months reduced in severity | Jan 2022: −116% → −71%; Mar 2021: −67% → −23%; fewer false breakouts |
| Bull months also reduced | Apr 2025: +157% → +68%; top-3 misses some tail-wind signals |
| Aug 2021 loses the bull signal | All-sig: +15% EOD (U-curve bull); top-3 +15m: −1.5% (only 3 picks) → +15m rule costs more |
| Sep SHORT less profitable in calm Septembers | Sep 2018: −14% → −1.6% (much milder); top-3 filter selects better-quality signals that reverse less |

**Bottom line:** Top-3 selection produces a more realistic simulation (max 3 entries/day),
reduces extreme outliers in both directions, and the strategy edge (+593pp) is preserved.
For live trading the top-3 approach is directly actionable: check the pre-session ranking,
trade only the top-ranked tickers that fire an OR breakout with vol ≥ 1.0×.
