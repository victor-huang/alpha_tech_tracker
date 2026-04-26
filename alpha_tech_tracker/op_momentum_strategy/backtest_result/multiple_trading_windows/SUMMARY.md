# Multi-Window Strategy Comparison

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20`, pool = V2 (16 tickers), capital = $10,000
**Mode**: no-compound (daily reset to $10k — measures per-day strategy edge)
**Capital flow**: first group deploys simultaneously per `--morning-split`; subsequent windows inherit all returned capital sequentially

## Strategy Definitions

| Label | Config | Entry | EV/trade | Win rate | Morning split |
|---|---|---|---|---|---|
| M1 | 09:30 / 3 bars | 9:45 AM | +0.443% | 37% | 100% |
| M2 | 09:30 / 1 bar | 9:35 AM | +0.468% | 32% | — |
| A1 | 13:15 / 1 bar | 1:20 PM | +0.194% | 24% | sequential |
| A2 | 15:00 / 1 bar | 3:05 PM | +0.135% | 26% | sequential |

## Per-Year Total Returns (no-compound)

| Strategy | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (Q1) |
|---|---|---|---|---|---|---|
| M1 alone | +60% | +108% | +80% | +30% | +79% | +45% |
| M1 + A1 | +97% | +160% | +128% | +55% | +125% | +54% |
| M1 + A1 + A2 | +127% | +195% | +159% | +82% | +155% | +64% |
| **M2 + A1 + A2** | **+147%** | +182% | **+168%** | **+132%** | **+180%** | +55% |
| M1+M2+A1+A2 (60/40) | +135% | **+189%** | +163% | +102% | +165% | +61% |

## Winner Per Year

| Year | Winner | Runner-up | M1-alone | Delta (winner vs M1) |
|---|---|---|---|---|
| 2021 | M2+A1+A2 (+147%) | M1+M2+A1+A2 (+135%) | +60% | **+87pp** |
| 2022 | M1+M2+A1+A2 (+189%) | M1+A1+A2 (+195%)* | +108% | **+87pp** |
| 2023 | M2+A1+A2 (+168%) | M1+M2+A1+A2 (+163%) | +80% | **+88pp** |
| 2024 | M2+A1+A2 (+132%) | M1+M2+A1+A2 (+102%) | +30% | **+102pp** |
| 2025 | M2+A1+A2 (+180%) | M1+M2+A1+A2 (+165%) | +79% | **+101pp** |
| 2026 Q1 | M1+A1+A2 (+64%) | M1+M2+A1+A2 (+61%) | +45% | **+19pp** |

*2022: M1+A1+A2 actually leads at +195% vs M1+M2+A1+A2 at +189%

## Observations

- **Every multi-window combo beats M1 alone in every single year** — adding non-overlapping windows consistently adds value with no exceptions
- **M2+A1+A2 wins 4 of 6 periods** (2021, 2023, 2024, 2025) — best overall performer; M2's higher EV/trade (+0.468%) benefits most from sequential capital recycling
- **M1+A1+A2 wins 2022 and 2026 Q1** — M1's higher win rate (37%) may advantage choppy/uncertain market conditions
- **M1+M2+A1+A2 (60/40 split) is never the best** in any single year — splitting M1/M2 prevents either morning window from reaching full capital efficiency
- **2024 shows the biggest spread**: M2+A1+A2 (+132%) vs M1+A1+A2 (+82%) — a +50pp gap in a low-signal year; M2's higher EV/trade matters most when good signals are scarce
- **The additive nature is consistent** — each window contributes independently; M1 cap P&L is identical whether run alone or combined with afternoon windows
- **Delta vs M1-alone grows over time** — multi-window advantage is largest in recent high-volatility years (2024–2025: +100pp+)

## Recommendations

| Use case | Config | Rationale |
|---|---|---|
| Live trading (conservative) | M1 + A1 + A2 | Highest win rate (37%), +127–195% per year, most consistent |
| Live trading (aggressive) | M2 + A1 + A2 | Best total return 4/6 years, noisier 9:35 AM entry |
| Uncertain/choppy markets | M1 + A1 + A2 | Wins in 2022 and 2026 Q1 |
| Strong trending markets | M2 + A1 + A2 | Largest edge in 2021, 2024, 2025 |

## CLI Commands

```bash
# M1 alone (baseline)
python op_momentum_selector_backtest.py \
  --start YYYY-01-01 --end YYYY-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20

# M1 + A1 + A2 (conservative)
python op_momentum_selector_backtest.py \
  --start YYYY-01-01 --end YYYY-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# M2 + A1 + A2 (aggressive)
python op_momentum_selector_backtest.py \
  --start YYYY-01-01 --end YYYY-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# M1+M2+A1+A2 (60/40 split)
python op_momentum_selector_backtest.py \
  --start YYYY-01-01 --end YYYY-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 60 40
```

## Log Files

Individual year logs in this directory (no-compound):
- `m1_{year}.txt` — M1 alone
- `m1_a1_{year}.txt` — M1 + A1
- `m1_a1_a2_{year}.txt` — M1 + A1 + A2
- `m2_a1_a2_{year}.txt` — M2 + A1 + A2
- `m1_m2_a1_a2_{year}.txt` — M1+M2+A1+A2 (60/40)

---

## Continuous 5-Year Compound Run (2021-01-01 → 2026-03-28)

**Mode**: compound (portfolio carries over uninterrupted across all years)
**Log files**: `*_compound_5yr.txt`

### Year-End Portfolio Values ($10,000 start)

| Year | M1 | M1+A1 | M1+A1+A2 | M2+A1+A2 | M1+M2+A1+A2 |
|---|---|---|---|---|---|
| 2021 | $18,042 | $26,046 | $34,957 | **$42,475** | $37,905 |
| 2022 | $50,702 | $121,153 | $228,192 | **$251,468** | $239,462 |
| 2023 | $110,328 | $424,604 | $1.08M | **$1.19M** | $1.14M |
| 2024 | $146,756 | $732,459 | $2.46M | **$4.41M** | $3.16M |
| 2025 | $317,921 | $2.49M | $11.28M | **$25.97M** | $16.07M |
| 2026 Q1 | $490,985 | $4.24M | $21.18M | **$44.74M** | $29.20M |

### 5-Year Total Returns

| Strategy | Total return | Final portfolio |
|---|---|---|
| M1 alone | +4,810% | $490,985 |
| M1 + A1 | +42,304% | $4,240,429 |
| M1 + A1 + A2 | +211,734% | $21,183,408 |
| **M2 + A1 + A2** | **+447,292%** | **$44,739,211** |
| M1+M2+A1+A2 (60/40) | +291,939% | $29,203,904 |

### Key Observations

- **M2+A1+A2 leads every single year** — never behind in any period
- **Each window added multiplies the final outcome**: M1→M1+A1 ≈9×, M1+A1→M1+A1+A2 ≈5×, M1+A1+A2→M2+A1+A2 ≈2×
- **Compounding snowball accelerates**: M2+A1+A2 earns ~$8.2M in Jan 2026 alone on a $26M base
- **60/40 morning split underperforms M2+A1+A2 every year** — giving 100% to the higher-EV morning window (M2) and running afternoons sequentially is strictly better than splitting
- **Use no-compound results (above) to evaluate strategy edge; use these compound results to project capital growth**

---

## M1 Bar Width Comparison: 3-bar vs 1-bar (with `--reversal`)

**Date**: 2026-04-03

**Question**: Does using a 1-bar (5-min) OR for the morning window outperform the 3-bar (15-min) OR when combined with A1+A2 and reversal?

**Note**: These runs include `--reversal` which the original multi-window table above does not. The 3-bar config also includes `--min-or-range 0.5 --min-or-range-windows M1`; the 1-bar config does not — so this is not a perfectly clean A/B on bar width alone.

| Config | Params |
|---|---|
| 3-bar + reversal | `--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal --min-or-range 0.5 --min-or-range-windows M1` |
| 1-bar + reversal | `--window M1 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal` |

### Per-Year Returns

| Year | 3-bar Return% | 1-bar Return% | Δ (1-bar vs 3-bar) | M1 WR (3-bar) | M1 WR (1-bar) |
|---|---|---|---|---|---|
| 2021 | +129.95% | +152.87% | **+22.92pp** | 31% | 32% |
| 2022 | +182.42% | +187.44% | **+5.02pp** | 36% | 30% |
| 2023 | +211.76% | +194.07% | **-17.69pp** | 32% | 30% |
| 2024 | +98.69% | +125.10% | **+26.41pp** | 32% | 30% |
| 2025 | +215.70% | +212.31% | **-3.39pp** | 36% | 31% |
| 2026 YTD | +88.72% | +67.99% | **-20.73pp** | 44% | 28% |
| **Score** | **3 wins** | **3 wins** | | | |

### Per-Window Detail (M1 only — A1/A2 are identical)

| Year | M1 config | Trades | Win% | Avg P&L% | M1 Return% |
|---|---|---|---|---|---|
| 2021 | 3-bar | 666 | 31% | +0.022% | +61.13% |
| 2021 | 1-bar | 689 | 32% | +0.114% | +84.03% |
| 2022 | 3-bar | 603 | 36% | +0.213% | +87.31% |
| 2022 | 1-bar | 629 | 30% | +0.028% | +92.91% |
| 2023 | 3-bar | 661 | 32% | +0.082% | +118.20% |
| 2023 | 1-bar | 690 | 30% | +0.047% | +100.47% |
| 2024 | 3-bar | 628 | 32% | +0.052% | +43.90% |
| 2024 | 1-bar | 697 | 30% | +0.054% | +70.17% |
| 2025 | 3-bar | 629 | 36% | +0.146% | +122.84% |
| 2025 | 1-bar | 680 | 31% | +0.136% | +119.13% |
| 2026 YTD | 3-bar | 147 | 44% | +0.655% | +54.15% |
| 2026 YTD | 1-bar | 160 | 28% | +0.226% | +33.54% |

### Observations

- **No consistent winner** — each config wins 3 of 6 years; neither dominates
- **1-bar fires ~50 more M1 trades/year** but win rate drops from ~33% → ~30% consistently — the extra trades are lower quality
- **3-bar wins in high-quality signal years** (2023, 2025, 2026 YTD) where the full 15-min OR provides better signal clarity; its higher avg P&L% per trade outweighs the volume deficit
- **1-bar wins in range-bound/lower-volatility years** (2021, 2022, 2024) where early entry captures moves that the 15-min OR would miss or dilute
- **2026 YTD is the strongest divergence** (-20.73pp): 3-bar shows a 44% WR vs 1-bar's 28% WR — the current high-volatility/uncertain regime strongly favors waiting for the full OR to form
- **Conclusion**: 3-bar remains the recommended live config given current market conditions (2026). Re-evaluate if regime shifts back to low-volatility trending.

### Effect of `--min-or-range 0.2` on 1-bar

Adding `--min-or-range 0.2 --min-or-range-windows M1` to the 1-bar config filters ~70 M1 trades/year (tight 5-min ORs). Win rate improves slightly (+1–3pp) but total return drops every single year:

| Year | 1-bar (no filter) | 1-bar (+or0.2) | Δ | M1 WR (no filter) | M1 WR (+or0.2) |
|---|---|---|---|---|---|
| 2021 | +152.87% | +137.18% | **-15.69pp** | 32% | 34% |
| 2022 | +187.44% | +173.05% | **-14.39pp** | 30% | 31% |
| 2023 | +194.07% | +186.54% | **-7.53pp** | 30% | 32% |
| 2024 | +125.10% | +108.38% | **-16.72pp** | 30% | 31% |
| 2025 | +212.31% | +200.33% | **-11.98pp** | 31% | 34% |
| 2026 YTD | +67.99% | +65.38% | **-2.61pp** | 28% | 28% |

The filtered trades have slightly lower win rate but still contribute net positive EV — removing them always costs return. The `--min-or-range 0.2` threshold is too low to act as a meaningful quality gate for the 1-bar window.

### 3-way Summary

| Year | 3-bar +or0.5 | 1-bar (no filter) | 1-bar +or0.2 | Winner |
|---|---|---|---|---|
| 2021 | +129.95% | +152.87% | +137.18% | 1-bar |
| 2022 | +182.42% | +187.44% | +173.05% | 1-bar |
| 2023 | +211.76% | +194.07% | +186.54% | 3-bar |
| 2024 | +98.69% | +125.10% | +108.38% | 1-bar |
| 2025 | +215.70% | +212.31% | +200.33% | 3-bar |
| 2026 YTD | +88.72% | +67.99% | +65.38% | 3-bar |
| **Score** | **3 wins** | **3 wins** | **0 wins** | |

`--min-or-range 0.2` on 1-bar is never the best config in any year — reject.

---

## A1/A2 `close_top_pct` Sweep — Preventing Immediate Bar-0 Exits

**Date**: 2026-04-09

**Background**: 1-bar afternoon windows (A1/A2) frequently exited on the very first monitored bar (`bars_held=0`) via `fallback_20pct`, because when the OR is a single 5-min bar the `close` is already near the OR boundary. The `close_top_pct` feature was introduced to fix this: a BULLISH signal only fires when `close >= OR_high - PCT * OR_range` (i.e. close in the top X% of the bar), and the hard stop is pre-armed at `OR_low` from bar 0, bypassing `fallback_20pct` entirely. Symmetrically for BEARISH.

**Params**: `--regime-filter --regime-ma 8 --reversal --top 2 --or-bar-lookback 3 --bearish-reentry --bullish-reentry`, per-window `close_top_pct=0.05` set via `--window LABEL START BARS 0.05`

### OR Bar Count Sweep — 2026 YTD (A1 13:15 + A2 15:00, close_top_pct=0.05)

| Bars | Total Return | Win Rate | A1 Trades | A1 WR | A1 EV/trade | A1 Cap P&L | A2 Trades | A2 WR | A2 EV/trade | A2 Cap P&L |
|------|-------------|----------|-----------|-------|------------|------------|-----------|-------|------------|------------|
| **1** | **+35.99%** | 30% | 118 | 28% | −0.009% | +$2,040 | 106 | 32% | −0.046% | +$1,559 |
| 2 | +5.43% | 34% | 82 | 33% | +0.014% | +$519 | 75 | 35% | −0.087% | +$25 |
| 3 | +7.44% | 39% | 77 | 39% | +0.051% | +$589 | 78 | 38% | 0.000% | +$154 |

- **1-bar wins on return (+35.99%)** despite lowest win rate — a handful of large breakout moves (SNDK Feb 24: +$29.47, FN Mar 6: +$30.34) drive the P&L; hard stop = bar extreme keeps individual losses tiny
- 2-bar and 3-bar have better win rates and positive/near-zero EV/trade but far fewer signals; the tighter OR condition misses the big moves
- EV/trade is negative for 1-bar (−0.009% / −0.046%) — results depend on fat-tail asymmetry, not a consistent per-signal edge
- **Verdict**: 1-bar is the right choice for afternoon windows with `close_top_pct=0.05`

### A1 Time Window Sweep — 2026 YTD (1-bar, close_top_pct=0.05)

| Start | Trades | W/L | WR | Cap P&L | Return |
|-------|--------|-----|----|---------|--------|
| 12:00 | 112 | 24W/88L | 21% | +$381 | +3.81% |
| 12:30 | 109 | 19W/90L | 17% | +$819 | +8.19% |
| **13:00** | **115** | **27W/88L** | **23%** | **+$2,044** | **+20.44%** |
| **13:15** | **118** | **33W/85L** | **28%** | **+$2,040** | **+20.40%** |
| 13:30 | 116 | 26W/90L | 22% | +$1,246 | +12.46% |
| 14:00 | 110 | 28W/82L | 25% | +$1,958 | +19.58% |
| 14:30 | 102 | 27W/75L | 26% | +$1,116 | +11.16% |

### A2 Time Window Sweep — 2026 YTD (1-bar, close_top_pct=0.05)

| Start | Trades | W/L | WR | Cap P&L | Return |
|-------|--------|-----|----|---------|--------|
| 14:00 | 110 | 28W/82L | 25% | +$1,958 | +19.58% |
| 14:30 | 102 | 27W/75L | 26% | +$1,116 | +11.16% |
| **15:00** | **106** | **34W/72L** | **32%** | **+$1,552** | **+15.52%** |
| 15:15 | 105 | 43W/62L | 41% | +$1,251 | +12.51% |
| 15:30 | 102 | 40W/62L | 39% | +$547 | +5.47% |
| 15:45 | 94 | 40W/54L | 43% | +$207 | +2.07% |

- **A1**: 13:00 and 13:15 are essentially tied at ~+20.4% — the post-lunch sweet spot is narrow; earlier (12:00–12:30) and later (13:30+) both trail
- **A2**: 15:00 wins on return (+15.5%); later windows (15:15–15:45) show higher win rates but smaller avg wins — big moves are over before they fire
- 14:00/14:30 overlap with A1 signals (same bar pool), making them poor A2 choices
- **Verdict**: 13:15/15:00 confirmed as the optimal timing for 2026 YTD

---

## A1 Start Time: 13:15 vs 12:30 — 5-Year Comparison (close_top_pct=0.05)

**Date**: 2026-04-09

**Question**: Does shifting A1 from 13:15 to 12:30 improve results? The 2025 sweep showed 12:30 returning +68.59% vs 13:15's +53.10%.

**Params**: `--regime-filter --regime-ma 8 --reversal --top 2 --or-bar-lookback 3 --bearish-reentry --bullish-reentry --morning-split 100 --window A1 {time} 1 0.05`

| Year | 13:15 Trades | 13:15 W/L | 13:15 WR | 13:15 Return | 12:30 Trades | 12:30 W/L | 12:30 WR | 12:30 Return | Winner |
|------|-------------|-----------|----------|-------------|-------------|-----------|----------|-------------|--------|
| 2021 | 469 | 102W/367L | 22% | +49.80% | 454 | 103W/351L | 23% | +52.36% | **12:30** (+2.6pp) |
| 2022 | 433 | 111W/322L | 26% | +59.62% | 430 | 102W/328L | 24% | +43.50% | **13:15** (+16.1pp) |
| 2023 | 453 | 96W/357L | 21% | +49.58% | 458 | 102W/356L | 22% | +54.93% | **12:30** (+5.4pp) |
| 2024 | 451 | 100W/351L | 22% | +43.49% | 468 | 112W/356L | 24% | +54.29% | **12:30** (+10.8pp) |
| 2025 | 443 | 103W/340L | 23% | +53.10% | 432 | 112W/320L | 26% | +68.59% | **12:30** (+15.5pp) |
| **5-yr total** | | | | **+255.59%** | | | | **+273.67%** | **12:30 (+18.1pp)** |

- **12:30 wins 4 of 5 years** and leads by +18pp total
- **2022 is the exception**: 13:15 wins by +16pp in the high-volatility bear year — post-lunch momentum resolved faster, making the earlier 12:30 entry noisier
- **Win rates are nearly identical** across both times — the difference is in avg win magnitude, not hit rate; 12:30 catches bigger directional moves that are partially diluted by 13:15
- Trade counts comparable (~430–470), so this is not a small-sample artefact

### Conclusion

12:30 shows a consistent edge over 13:15 across most market conditions. The sole exception is a sustained bear market year (2022). Given that 2026 Q1 (high volatility, tariff-driven selloff) favors 13:15 (+20.40% vs 12:30's +8.19%), caution is warranted before switching.

**Recommendation**: **Keep 13:15 as the live default for now** — it is more robust to volatile/uncertain regimes, which is the current market condition. Re-evaluate if the market returns to a trending bull environment where 12:30's earlier entry captures more directional follow-through.

| Use case | A1 time | Rationale |
|---|---|---|
| Live trading (current regime: volatile/tariff-driven) | 13:15 | Safer; wins 2022 and 2026 YTD |
| Bull/trending market | 12:30 | +18pp edge over 5 years; captures earlier directional move |

---

## A1/A2 Exit Speed Analysis — Noise vs Winners (close_top_pct=0.05)

**Date**: 2026-04-09

**Question**: With `close_top_pct=0.05` pre-arming the hard stop at the bar extreme, how quickly do winning vs losing trades exit? Are there structural similarities among the big winners that could help filter noise?

**Config**: `--regime-filter --regime-ma 8 --reversal --top 2 --or-bar-lookback 3 --bearish-reentry --bullish-reentry --window A1 13:15 1 0.05 --window A2 15:00 1 0.05 --morning-split 100`

**Method**: Called `compute_signals_with_backtest()` directly (primary trades only, no reversals/reentries) and bucketed each trade by `bars_held`: same-bar (0), 1 bar, 2 bars, 3+ bars.

### Exit Speed Breakdown

#### 2026 YTD (Jan 1 – Apr 8) — 491 trades

| Bucket | Count | WR | Avg PnL% | Total PnL | Avg OR range% |
|--------|-------|----|---------|-----------|---------------|
| 0 (same bar) | 153 | 0% | −0.066% | −$28.58 | 0.066% |
| 1 bar | 62 | 2% | −0.169% | −$35.89 | 0.185% |
| 2 bars | 41 | 2% | −0.151% | −$20.39 | 0.155% |
| **3+ bars** | **235** | **54%** | **+0.355%** | **+$255.54** | 0.220% |

#### 2025 Full Year — 2,143 trades

| Bucket | Count | WR | Avg PnL% | Total PnL | Avg OR range% |
|--------|-------|----|---------|-----------|---------------|
| 0 (same bar) | 666 | 0% | −0.052% | −$85.95 | 0.056% |
| 1 bar | 253 | 1% | −0.101% | −$64.28 | 0.108% |
| 2 bars | 173 | 4% | −0.109% | −$48.04 | 0.135% |
| **3+ bars** | **1,051** | **51%** | **+0.423%** | **+$882.95** | 0.253% |

**The pattern is identical across both years**: everything under 3 bars is noise (0–4% WR, net negative). All profit comes from 3+ bar trades.

### Top 10 Gains — 2026 YTD

| Date | Win | Ticker | Signal | Bars | Entry | PnL | Exit |
|------|-----|--------|--------|------|-------|-----|------|
| 2026-03-06 | A1 | FN | BEARISH | 27 | 519.83 | +$30.34 (+5.84%) | end_of_day |
| 2026-02-24 | A1 | SNDK | BEARISH | 22 | 659.59 | +$29.47 (+4.47%) | trailing_stop_ma20 |
| 2026-03-06 | A2 | FN | BEARISH | 11 | 510.76 | +$21.27 (+4.16%) | end_of_day |
| 2026-02-18 | A1 | FN | BEARISH | 27 | 521.25 | +$15.31 (+2.94%) | end_of_day |
| 2026-02-10 | A1 | FN | BEARISH | 31 | 479.63 | +$13.35 (+2.78%) | end_of_day |
| 2026-02-05 | A1 | SNDK | BEARISH | 32 | 588.73 | +$12.97 (+2.20%) | end_of_day |
| 2026-02-17 | A2 | SNDK | BEARISH | 11 | 603.82 | +$12.95 (+2.14%) | end_of_day |
| 2026-03-31 | A2 | SNDK | BULLISH | 11 | 624.24 | +$11.73 (+1.88%) | end_of_day |
| 2026-02-13 | A2 | SNDK | BEARISH | 11 | 638.18 | +$11.39 (+1.78%) | end_of_day |
| 2026-02-24 | A1 | MU | BEARISH | 22 | 428.44 | +$9.73 (+2.27%) | trailing_stop_ma20 |

### Top 10 Gains — 2025

| Date | Win | Ticker | Signal | Bars | Entry | PnL | Exit |
|------|-----|--------|--------|------|-------|-----|------|
| 2025-04-09 | A1 | META | BULLISH | 32 | 526.47 | +$58.85 (+11.18%) | end_of_day |
| 2025-04-09 | A1 | TSLA | BULLISH | 33 | 241.88 | +$30.56 (+12.63%) | end_of_day |
| 2025-04-09 | A1 | CVNA | BULLISH | 19 | 185.88 | +$24.02 (+12.92%) | trailing_stop_ma20 |
| 2025-12-12 | A1 | CVNA | BEARISH | 32 | 473.88 | +$18.38 (+3.88%) | end_of_day |
| 2025-04-09 | A1 | FN | BULLISH | 19 | 186.16 | +$16.36 (+8.79%) | trailing_stop_ma20 |
| 2025-04-09 | A1 | COIN | BULLISH | 27 | 163.19 | +$15.91 (+9.75%) | trailing_stop_ma20 |
| 2025-04-09 | A1 | EXPE | BULLISH | 21 | 142.97 | +$15.62 (+10.93%) | trailing_stop_ma20 |
| 2025-01-31 | A1 | TSLA | BEARISH | 32 | 417.71 | +$13.03 (+3.12%) | end_of_day |
| 2025-04-09 | A2 | META | BULLISH | 11 | 573.25 | +$12.07 (+2.11%) | end_of_day |
| 2025-04-09 | A1 | AMD | BULLISH | 32 | 84.82 | +$11.96 (+14.10%) | end_of_day |

### Top-20 Winner Traits vs Same-Bar Noise

| Trait | Top-20 Winners (2026) | Top-20 Winners (2025) | Same-Bar Noise |
|-------|----------------------|----------------------|----------------|
| Exit | 55% EOD, 45% trailing MA | 70% EOD, 30% trailing MA | 100% hard_stop |
| Signal | 90% BEARISH | 55% BULLISH / 45% BEARISH | 73% BEARISH |
| Window | A1: 65%, A2: 35% | A1: 85%, A2: 15% | A1/A2: ~50/50 |
| Avg bars held | 20.2 (101 mins) | 25.8 (129 mins) | 0 (< 5 mins) |
| Dominant tickers | SNDK (8), FN (7) | TSLA (4), FN (3), COIN (3) | spread evenly |
| Avg OR range% | 0.200% | 1.866% | 0.056–0.066% |
| Same-bar % of all trades | — | — | 31% (both years) |
| Same-bar total cost | — | — | −$28 (2026), −$86 (2025) |

### OR Range Filter — Does Not Help

Filtering by minimum OR range% improves WR at every threshold but **always reduces total PnL** — the filtered-out trades contain more value than the remaining ones in 2026, and the 2025 big winners (April 9 tariff-pause event) had huge OR ranges that are event-driven and not predictable.

| Threshold | 2025 trades kept | WR | PnL kept | PnL filtered |
|-----------|------------------|----|----------|--------------|
| OR≥0.10% | 942 | 34% | +$404 | +$281 |
| OR≥0.20% | 599 | 38% | +$376 | +$309 |
| OR≥0.30% | 357 | 42% | +$332 | +$352 |

### Conclusions

- **Fat-tail system by design**: absorb many cheap hard-stop losses (≤$1 each, hard stop = bar extreme), let rare big moves run to EOD or trailing MA. The structure is working as intended.
- **3+ bars is the key discriminant**: trades held 3+ bars have 51–54% WR; ≤2 bars is 0–4%. This is determined post-entry by whether the market keeps moving — no entry-side filter predicts it.
- **Winners are regime-dependent**: 2026 = almost all BEARISH (downtrend), concentrated in SNDK/FN; 2025 = balanced, dominated by one event day (Apr 9 tariff pause: 8 of top-15 trades from that single day).
- **Same-bar noise is cheap and stable**: 31% of trades both years, costs < $90/year total — not worth adding entry-side complexity to eliminate.
- **OR range filter rejected**: does not improve total PnL at any threshold in either year.

---

## New A1 Window Sweep — Adding an Early Afternoon Window (2026-04-26)

### Background & Code Fixes

Two bugs were found and fixed before running this sweep:

1. **Sequential window capital timing** — the backtest previously credited the full M1 final P&L to A1 even when an M1 trade was still open at A1's drain time. Fixed: `_apply_capital_flow` now checks each prior row's exit time (`or_close_min + bars_held × 5`) against the sequential window's drain time — locked slots have their `slot_capital` deducted, returning capital only flows when the trade actually exits. This matches live engine behaviour exactly.

2. **BRE/BRU/REV add-on double-deduction** — reversal and re-entry add-on rows share the same `(date, window)` key as their primary row and can have much longer `bars_held`. The timing fix was incorrectly deducting their `slot_capital` as if they deployed additional window capital (they don't — they reuse freed capital from the primary slot). Fixed: add-on rows (`is_reversal`, `is_bearish_reentry`, `is_bullish_reentry`) are skipped in the sequential available-capital computation.

### Sweep Configuration

**Params**: `--top 2 --weights 60 40 --morning-split 100 --reversal --bearish-reentry --bullish-reentry --doubledown --feed iex`

**Window layout**: `M1 09:30/3` → `A1 {sweep}` → `A2 13:15/1` → `A3 15:00/1`

Windows must be passed in chronological order. A1 is inserted between M1 and A2 for each candidate. Baseline uses the old layout: `M1 09:30/3 → A1 13:15/1 → A2 15:00/1` (no A3).

**Candidates**: 6 start times × 3 bar counts = 18 configurations
- Start times: 10:00, 10:30, 11:00, 11:30, 12:00, 12:30
- Bar counts: 1, 2, 3

### Results — 2026 YTD (Jan 1 – Apr 8)

| A1 Config | Trades | WinRate | EV/trade | A1 Cap P&L | Total P&L | Return% |
|---|---|---|---|---|---|---|
| **12:00 / 3 bars** | 121 | **53%** | +0.379% | **+$2,181** | +$12,763 | **+128%** |
| 10:00 / 1 bar | 85 | 48% | **+0.501%** | +$1,493 | +$12,435 | +124% |
| 12:30 / 1 bar | 120 | 35% | +0.175% | +$1,131 | +$11,653 | +117% |
| 12:00 / 1 bar | 118 | 33% | +0.148% | +$1,039 | +$11,973 | +120% |
| 11:00 / 3 bars | 114 | 43% | +0.197% | +$905 | +$11,604 | +116% |
| 11:00 / 1 bar | 102 | 40% | +0.243% | +$796 | +$11,851 | +119% |
| 10:30 / 1 bar | 95 | 40% | +0.034% | +$241 | +$11,245 | +112% |
| 11:30–12:00 / 2–3 bars | various | 34–43% | −0.057% to +0.197% | −$359 to +$906 | weakest tier | |

Dead zone: **10:30–11:30** range has the weakest EV/trade. 10:30 and 11:30 / 2-bar configs even go negative.

### Results — 2025 Full Year

| A1 Config | Trades | WinRate | EV/trade | A1 Cap P&L | Total P&L | Return% |
|---|---|---|---|---|---|---|
| 12:30 / 1 bar | 439 | 40% | +0.254% | +$5,576 | +$22,638 | **+226%** |
| 11:00 / 1 bar | 427 | 44% | +0.298% | +$5,264 | +$22,344 | +223% |
| 10:00 / 1 bar | 370 | 44% | **+0.380%** | +$4,877 | +$22,262 | +223% |
| 10:30 / 1 bar | 406 | 40% | +0.236% | +$4,794 | +$22,177 | +222% |
| 10:00 / 3 bars | 382 | **48%** | +0.308% | +$4,827 | +$22,098 | +221% |
| 12:00 / 3 bars | 460 | 38% | +0.191% | +$4,486 | +$21,726 | +217% |
| 11:00 / 2 bars | 425 | 39% | +0.137% | +$1,715 | +$18,852 | weakest |

**1-bar OR dominates 2025** — all top-4 configs use 1-bar. 2-bar is the weakest OR width.

### Results — 2023 Full Year

| A1 Config | WinRate | EV/trade | A1 Return% | Total Return% |
|---|---|---|---|---|
| **11:00 / 3 bars** | 50% | +0.524% | +130% | **+340%** |
| **11:30 / 2 bars** | 44% | +0.373% | +91% | **+320%** |
| **10:00 / 3 bars** | 41% | +0.409% | +84% | **+318%** |
| **11:00 / 2 bars** | 43% | +0.428% | +107% | **+312%** |
| **10:30 / 1 bar** | 38% | +0.326% | +69% | **+305%** |
| **10:30 / 2 bars** | 44% | +0.369% | +68% | **+297%** |
| **10:00 / 1 bar** | 44% | +0.431% | +68% | **+295%** |
| **10:30 / 3 bars** | 45% | +0.271% | +47% | **+276%** |
| 12:00–12:30 range | 35–41% | +0.15–0.26% | +40–55% | +241–268% |

**2023 key pattern**: 11:00 window dominates — 11:00/3bar is rank 1, 11:00/2bar is rank 4. Wide OR bars work well in 2023's recovery/bull environment. Late windows (12:00–12:30) are weak — later afternoon entries miss the mid-day directional moves.

### Results — 2024 Full Year

| A1 Config | WinRate | EV/trade | A1 Return% | Total Return% |
|---|---|---|---|---|
| **10:00 / 1 bar** | 48% | +0.472% | +79% | **+192%** |
| **11:00 / 3 bars** | 47% | +0.273% | +61% | **+173%** |
| **10:00 / 2 bars** | 45% | +0.355% | +60% | **+172%** |
| **10:30 / 1 bar** | 39% | +0.281% | +56% | **+167%** |
| **11:00 / 2 bars** | 42% | +0.237% | +49% | **+161%** |
| **12:00 / 1 bar** | 41% | +0.212% | +51% | **+161%** |
| **12:30 / 3 bars** | 42% | +0.207% | +45% | **+153%** |
| **11:30 / 1 bar** | 35% | +0.129% | +21% | **+131%** (weakest) |

**2024 key pattern**: 10:00/1bar dominates by a wide margin (+192% vs +173% for 2nd). Very early entry (10:00 AM) captures the first wave of intraday direction while the trend is strongest. 11:00/3bar is runner-up — wide OR still helps. Late windows (12:00+) are mediocre; 11:30/1bar is worst.

### Results — 2022 Full Year (Bear Market)

| A1 Config | Trades | WinRate | EV/trade | A1 Cap P&L | Total P&L | Return% |
|---|---|---|---|---|---|---|
| **10:00 / 3 bars** | 369 | 46% | **+0.492%** | **+$9,293** | +$26,122 | **+261%** |
| 10:30 / 1 bar | 376 | 41% | +0.450% | +$8,663 | +$25,189 | +252% |
| 10:30 / 2 bars | 384 | 39% | +0.388% | +$8,199 | +$25,122 | +251% |
| 12:30 / 3 bars | 426 | 44% | +0.348% | +$8,304 | +$24,763 | +248% |
| 11:00 / 2 bars | 417 | 42% | +0.309% | +$6,976 | +$23,953 | +240% |
| 11:00 / 1 bar | 388 | 44% | +0.211% | +$4,384 | +$21,084 | +211% |
| 12:00 / 1 bar | 384 | 36% | +0.152% | +$3,190 | +$18,955 | weakest |

**Early windows dominate the 2022 bear year** — 10:00–10:30 capture directional moves faster; later windows lose that edge as intraday reversals are more common in trending-down markets.

### Cross-Year Ranking Summary — Full 5-Year View

All 18 configs ranked by total return within each year. Average rank computed across all years with available data.

| Config | 2022 | 2023 | 2024 | 2025 | 2026 | Avg rank | Pattern |
|---|---|---|---|---|---|---|---|
| **10:30 / 1 bar** | #2 | #5 | #4 | #4 | #7 | **4.4** | **Most consistent — never below #7** |
| **11:00 / 3 bars** | #10 | #1 | #2 | — | #6 | 4.8 | Strong 2023/2024; weak in 2022 |
| **10:00 / 1 bar** | #12 | #8 | **#1** | #3 | #2 | 5.2 | Bull specialist; dominant in 2024/2026 |
| **10:00 / 3 bars** | **#1** | #3 | #12 | #5 | — | 5.2 | Bear specialist; dominant 2022 |
| **11:00 / 2 bars** | #5 | #4 | #5 | — | — | 5.2 | Consistent top-5 (2022–2024) |
| 10:00 / 2 bars | #9 | #10 | #3 | — | — | 7.3 | |
| 11:30 / 2 bars | #17 | #2 | #8 | — | — | 9.0 | High 2023 anomaly; poor 2022 |
| 12:30 / 1 bar | #14 | #15 | #14 | **#1** | #5 | 9.8 | Bull/trending specialist; weak in 2022/2024 |
| 11:00 / 1 bar | #16 | #12 | #16 | #2 | #4 | 10.0 | Good in recent years; poor 2022/2024 |
| 12:00 / 3 bars | #13 | #13 | #17 | #6 | **#1** | 10.0 | 2026 champion; middling elsewhere |

Note: "—" = data exists but not in the reported top-7 for that year (rank 8+).

**Key takeaways from full 5-year analysis:**
- **10:30/1bar replaces 11:00/1bar as the most consistent pick** — the 3-year partial analysis (2022/2025/2026) favored 11:00/1bar, but the full data shows it ranks #12 in 2023 and #16 in 2024, making 10:30/1bar the true all-regime performer
- **10:00/1bar is the bull-market specialist** — ranks #1 (2024), #2 (2026), #3 (2025), but falls to #12 in the 2022 bear year
- **10:00/3bar is the bear-market specialist** — dominates 2022 (#1), strong in 2023 (#3) and 2025 (#5), drops to #12 in the bull year 2024
- **2-bar OR is inconsistent** — no 2-bar config appears in the top-3 across all years; 2bar often beats 1bar in bear environments (10:30/2bar is #3 in 2022) but underperforms in bull years
- **12:00/3bar is a 2026-specific phenomenon** — ranks #13 in 2023 and #17 in 2024; not a durable edge

### Baseline vs Best New Config (per year)

| Year | Baseline (M1/A1-13:15/A2-15:00) | New 12:00/3bar (M1/A1/A2/A3) | Delta |
|---|---|---|---|
| 2025 | +$17,248 (+172%) | +$21,726 (+217%) | **+$4,478 (+45pp)** |
| 2026 YTD | +$11,024 (+110%) | +$12,763 (+128%) | **+$1,740 (+18pp)** |

M1 P&L is **identical** in both configs (confirmed non-overlapping), validating the capital model fix.

### Per-Window Detail — New vs Baseline (2025)

| Window | Baseline | New |
|---|---|---|
| M1 09:30/3 | 473T / 48% WR / +$8,922 | 473T / 48% WR / +$8,922 ← identical |
| A1 | 454T / 36% WR / +$3,590 (13:15/1bar) | 460T / 38% WR / +$4,486 (12:00/3bar) |
| A2 | 458T / 45% WR / +$4,737 (15:00/1bar) | 433T / 36% WR / +$3,721 (13:15/1bar) |
| A3 | — | 458T / 45% WR / +$4,597 (15:00/1bar) |

A3 in the new config is essentially the same window as old A2 — A3's contribution (+$4,597) is nearly identical to old A2 (+$4,737), confirming the window's independent edge is preserved.

### Conclusions (Updated — Full 5-Year View)

- **10:30/1bar is the most robust pick across all 5 years** (avg rank 4.4, never below #7) — the earlier partial analysis (3 years) incorrectly identified 11:00/1bar as most consistent; the complete data reverses this: 11:00/1bar ranks #12 in 2023 and #16 in 2024
- **10:00/1bar** is the second-best choice for bull/normal markets (ranks #1, #2, #3 in 2024/2026/2025), but drops to #12 in the 2022 bear year — regime-dependent
- **10:00/3bar is the bear-market specialist** — dominant in 2022 (#1), solid in 2023 (#3) and 2025 (#5); the 15-min OR filters noise in trending-down environments; drops to #12 in 2024
- **12:00/3bar led in 2026** but ranks #13 in 2023 and #17 in 2024 — regime-specific, not a durable edge
- **2-bar OR is inconsistent** — no consistent advantage; 10:30/2bar beats 10:30/1bar in 2022 but underperforms in 2024; avoid as a standalone recommendation
- **For live trading**: use **10:30/1bar** as the default A1 config — most durable across all market regimes; switch to **10:00/3bar** only in confirmed bear/trending-down environments

### Monthly P&L Drill-Down — June 2025 → April 2026

**Date**: 2026-04-26
**Mode**: no-compound ($10,000/day reset)
**Fixed windows**: M1 09:30/3 + A2 13:15/1 + A3 15:00/1 (identical across all configs)
**Variable**: A1 start time and bar count only
**Note**: Baseline uses old 3-window layout (M1 + A1 13:15/1 + A2 15:00/1, no A3)

| Month | Baseline 13:15/1 | 10:00/1bar | 10:30/1bar | 11:00/2bar | 11:00/3bar |
|---|---|---|---|---|---|
| 2025-06 | +$1,802 (+18%) | +$2,124 (+21%) | **+$2,680 (+27%)** | +$2,096 (+21%) | +$1,823 (+18%) |
| 2025-07 | +$862 (+9%) | +$841 (+8%) | +$755 (+8%) | +$722 (+7%) | +$725 (+7%) |
| 2025-08 | +$999 (+10%) | **+$2,060 (+21%)** | +$1,243 (+12%) | +$1,318 (+13%) | +$863 (+9%) |
| 2025-09 | +$781 (+8%) | **+$1,112 (+11%)** | +$1,021 (+10%) | +$1,013 (+10%) | +$975 (+10%) |
| 2025-10 | +$1,660 (+17%) | +$1,749 (+17%) | **+$2,049 (+20%)** | +$1,722 (+17%) | +$1,802 (+18%) |
| 2025-11 | +$1,728 (+17%) | +$1,792 (+18%) | **+$2,902 (+29%)** | +$2,387 (+24%) | +$2,892 (+29%) |
| 2025-12 | +$954 (+10%) | +$1,362 (+14%) | +$1,338 (+13%) | +$743 (+7%) | **+$1,447 (+14%)** |
| 2026-01 | +$3,897 (+39%) | +$4,155 (+42%) | +$4,145 (+41%) | +$4,270 (+43%) | **+$4,424 (+44%)** |
| 2026-02 | +$4,494 (+45%) | **+$5,552 (+56%)** | +$4,559 (+46%) | +$4,317 (+43%) | +$4,444 (+44%) |
| 2026-03 | +$2,502 (+25%) | +$2,425 (+24%) | +$2,232 (+22%) | +$2,445 (+24%) | **+$2,872 (+29%)** |
| 2026-04 | +$962 (+10%) | **+$1,709 (+17%)** | +$1,259 (+13%) | +$1,553 (+16%) | +$486 (+5%) |
| **TOTAL** | **+$20,641 (+206%)** | **+$24,880 (+249%)** | **+$24,184 (+242%)** | **+$22,587 (+226%)** | **+$22,754 (+228%)** |

**A1 window contribution (per-window):**

| Config | A1 Return% | A1 Win Rate | A1 EV/trade | A1 Trades |
|---|---|---|---|---|
| Baseline 13:15/1bar | +32% | 39% | +0.174% | 408 |
| **10:00/1bar** | **+43%** | **44%** | **+0.399%** | 323 |
| 10:30/1bar | +36% | 40% | +0.177% | 354 |
| 11:00/2bar | +21% | 39% | +0.146% | 397 |
| 11:00/3bar | +23% | 43% | +0.164% | 395 |

**Observations:**
- **10:00/1bar leads this 11-month window (+249%)** — highest A1 EV/trade (+0.399%), fewest trades (323) but highest quality; dominates Feb 2026 (+$5,552) and Aug 2025 (+$2,060)
- **10:30/1bar is very close (+242%)** — wins the most individual months (Jun, Oct, Nov 2025); most consistent month-to-month
- **11:00/2bar and 11:00/3bar trail** (+226%/+228%) despite more trades; 11:00/3bar has a weak Apr 2026 (+$486 vs +$1,709 for 10:00/1bar)
- **All four new configs beat baseline by +20–43pp**, confirming the early A1 window consistently adds value regardless of exact config
- **2026-04 is a regime divergence**: 10:00/1bar and 10:30/1bar hold up; 11:00/3bar collapses to +$486 — early entry is favored in volatile/tariff-driven conditions

---

### CLI — Recommended Configs (Based on Full 5-Year Analysis)

```bash
# Most consistent (10:30/1bar A1) — recommended default
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 --morning-split 100 \
  --window M1 09:30 3 --window A1 10:30 1 --window A2 13:15 1 --window A3 15:00 1 \
  --reversal --bearish-reentry --bullish-reentry --doubledown \
  --start YYYY-01-01 --end YYYY-12-31 --feed iex

# Bear-market specialist (10:00/3bar A1) — use in confirmed downtrend regimes
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 --morning-split 100 \
  --window M1 09:30 3 --window A1 10:00 3 --window A2 13:15 1 --window A3 15:00 1 \
  --reversal --bearish-reentry --bullish-reentry --doubledown \
  --start YYYY-01-01 --end YYYY-12-31 --feed iex

# Bull-market / trending variant (10:00/1bar A1) — use in trending bull environments
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 --morning-split 100 \
  --window M1 09:30 3 --window A1 10:00 1 --window A2 13:15 1 --window A3 15:00 1 \
  --reversal --bearish-reentry --bullish-reentry --doubledown \
  --start YYYY-01-01 --end YYYY-12-31 --feed iex

# Baseline for comparison (old 3-window layout)
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 --morning-split 100 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --reversal --bearish-reentry --bullish-reentry --doubledown \
  --start YYYY-01-01 --end YYYY-12-31 --feed iex
```
