# Research: Beating QQQ in Bear Years

**Goal:** Understand why OR selector underperforms in bear years (2022: -28.4% vs QQQ -33.7%) and find scoring improvements to reduce bear-year drawdowns without hurting bull years.  
**Baseline config (Exp 16):** `--top 1 --window M1 09:30 3 --min-hold-bars 1 --ma-momentum-gate --feed sip --normalize-or-by-adr --stop-pct 0.4 --reversal --bearish-reentry --bullish-reentry --score-entry-weight 0.60 --score-avg-win-weight 0.00 --score-win-rate-weight 0.10 --score-ev-trend-weight 0.10 --ev-trend-days 15 --min-pool-vote 4 --score-rel-strength-weight 0.15`  
**Baseline result:** 8yr no-compound **+273.2%** | 2022: -28.4% | 2023: +66.8% | 2025: +34.3%

---

## Investigation 1: 2022 Bearish Signal Direction Gap

**Question:** In 2022 (QQQ transitioned from bull to bear), was the OR selector not firing enough BEARISH signals? Can we add scoring components to boost bearish signals during regime shifts?

### Key Finding: Direction Rate is NOT the Problem

With the best-known config (Exp 16):
- Our bear rate in 2022: **52%** of primary trades
- Oracle bear rate in 2022: **51%** of primary trades

The strategy fires roughly the same proportion of bearish signals as the oracle. The problem is **which specific ticker wins on a given day**, not the overall directional balance.

### Missed-Bearish Analysis: 22 Days

On 22 days in 2022, oracle fires BEARISH but we fire BULLISH.

**P&L cost: +71.4pp left on table** (oracle avg +2.14% per day vs our avg -0.90%)

Per-day breakdown:

| Date | Our Ticker | Our P&L | Oracle | Oracle P&L | QQQ OR | QQQ Dir |
|---|---|---|---|---|---|---|
| 2022-01-04 | TSLA | -0.90% | SHOP | +8.52% | -0.112 | BEAR |
| 2022-01-25 | CVNA | -5.53% | CHTR | +0.88% | -0.052 | BEAR |
| 2022-02-07 | CVNA | -2.14% | META | +3.85% | +0.379 | BULL |
| 2022-02-14 | EXPE | -1.39% | JPM | +0.45% | +0.294 | BULL |
| 2022-02-15 | EXPE | +1.39% | AMD | +2.47% | +0.096 | BULL |
| 2022-02-22 | AMD | -0.12% | APP | +3.72% | +0.703 | BULL |
| 2022-02-23 | PLTR | -1.35% | EXPE | +1.25% | -0.305 | BEAR |
| 2022-05-02 | AMD | -2.57% | CLS | +1.47% | +0.569 | BULL |
| 2022-05-20 | APP | +1.99% | CLS | +4.23% | +0.082 | BULL |
| 2022-06-01 | META | -0.47% | MRVL | +2.97% | +0.351 | BULL |
| 2022-06-06 | CLS | -0.61% | CVNA | +3.70% | -0.100 | BEAR |
| 2022-07-15 | CRDO | -1.08% | PLTR | +1.01% | +0.081 | BULL |
| 2022-08-26 | CVNA | -0.15% | SHOP | +4.29% | -0.091 | BEAR |
| 2022-09-06 | MRVL | -0.68% | EXPE | +1.24% | -0.308 | BEAR |
| 2022-09-26 | PLTR | +0.66% | CHTR | +3.43% | +0.662 | BULL |
| 2022-10-27 | SHOP | +0.78% | MU | +3.47% | +0.022 | BULL |
| 2022-11-03 | JPM | -1.43% | CHTR | +0.23% | -0.338 | BEAR |
| 2022-11-15 | SHOP | -3.40% | JPM | +0.55% | -0.089 | BEAR |
| 2022-12-15 | CVNA | +0.00% | MU | +0.86% | -0.301 | BEAR |
| 2022-12-16 | META | -0.79% | TSLA | +3.41% | +0.116 | BULL |
| 2022-12-28 | CLS | -0.46% | JPM | -0.23% | +0.536 | BULL |
| 2022-12-30 | TSLA | -1.63% | MU | -0.24% | +0.121 | BULL |

**Root cause — `entry_vs_mid_pct` dominance at w=0.60:**

| Feature | Our BULLISH pick (avg) | Oracle BEARISH pick (avg) | Δ |
|---|---|---|---|
| entry_vs_mid_pct | +1.39 | +0.78 | -0.61 |
| score | higher by ~0.61 | — | — |

BULLISH tickers in a bear market often have big gap-up opens — wide ORs with price near the high. These score very high on `entry_vs_mid_pct`. The BEARISH oracle picks have modest OR positioning but represent the correct regime call. The `entry_vs_mid_pct` scoring metric can't distinguish between "strong bullish breakout" and "gap-up that will fail".

**Rel-strength effect (Exp 16):** Adding `score_rel_strength_weight=0.15` actually made direction alignment slightly *worse* (20 → 22 missed-bearish days), even though it improved the 8yr total by +24.8pp. In a bear market, the cross-pool MA50 comparison can rank a BULLISH gap-up ticker as "pool outperformer", giving it even more scoring edge.

### QQQ OR Direction on Missed-Bearish Days

Of the 22 missed-bearish days, QQQ OR itself was:
- **BEARISH (QQQ OR < 0): 9/22 = 41%**
- **BULLISH (QQQ OR > 0): 13/22 = 59%**

On 59% of the missed days, QQQ itself opened bullish. Increasing `qqq_or_weight` would push our scoring *further toward BULLISH* on those 13 days — making things worse, not better. Only the 9 bearish-QQQ days could potentially benefit from a higher `qqq_or_weight`.

---

## Experiment 17a — `score_dir_ev_weight` (Direction-Specific Historical EV)

**Hypothesis:** Separate the historical EV gate into direction-specific terms: reward tickers that have historically performed well specifically in the signal's direction (`ev_trade_bullish` for BULLISH signals, `ev_trade_bearish` for BEARISH signals).

**Implementation:** New parameter `score_dir_ev_weight` in `score_ticker()` and `run_selector_backtest()`. CLI flag: `--score-dir-ev-weight`. Default: 0.0.

**Multi-year sweep results (dir_ev combined with rs=0.15):**

| rs | dir_ev | or_range | 2022 | 2023 | 2024 | 2025 | 4yr Δ |
|---|---|---|---|---|---|---|---|
| 0.15 | 0.00 | 0.05 | -28.4% | +66.8% | +10.9% | +34.3% | baseline |
| 0.10 | 0.05 | 0.05 | +0.0pp | -1.2pp | +4.7pp | -5.0pp | -1.5pp |
| 0.10 | 0.10 | 0.00 | +0.1pp | -1.4pp | +4.3pp | -7.9pp | -4.9pp |
| 0.05 | 0.10 | 0.05 | +2.7pp | -4.8pp | +4.2pp | -10.8pp | -8.7pp |
| 0.15 | 0.05 | 0.00 | +1.8pp | -1.7pp | +4.6pp | -17.8pp | -13.2pp |

**Result:** dir_ev hurts 2025 significantly at any meaningful weight (-5pp to -18pp) with negligible benefit elsewhere. **Not viable. Keeping at default=0.0.**

---

## Experiment 17b — Higher `qqq_or_weight`

**Hypothesis:** Increasing `qqq_or_weight` (which aligns scores with QQQ OR direction) would push us toward BEARISH on the 9/22 missed-bearish days when QQQ itself was bearish.

**Multi-year sweep (qqq_or_weight vs entry_weight, rs=0.15 fixed):**

| qqq_or | entry | 2019 Δ | 2020 Δ | 2021 Δ | 2022 Δ | 2023 Δ | 2024 Δ | 2025 Δ | 2026 Δ | 8yr Δ |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.40 | 0.60 | +42.0% | +30.9% | +38.7% | -28.4% | +66.8% | +10.9% | +34.3% | +78.1% | baseline |
| 0.50 | 0.50 | +3.0pp | -7.7pp | -7.2pp | +5.8pp | +2.0pp | -2.8pp | +9.5pp | -6.8pp | -4.2pp |
| 0.55 | 0.45 | +2.4pp | -11.0pp | -15.5pp | +12.5pp | -11.2pp | +0.5pp | +10.6pp | -5.2pp | -16.8pp |
| 0.60 | 0.40 | +0.4pp | -10.6pp | -19.9pp | +1.3pp | -13.2pp | +0.9pp | +10.2pp | -3.7pp | -34.6pp |
| 0.70 | 0.30 | -3.8pp | -11.6pp | -20.6pp | +11.9pp | -18.2pp | -10.0pp | +7.2pp | -0.0pp | -45.1pp |

Missed-bearish count: qqq=0.60 → 20 (was 22), qqq=0.80 → 21 (was 22). Minimal improvement.

**Result:** Every qqq weight increase trades away large 2021/2023 gains for modest 2022 improvement. The 8yr total degrades monotonically. **Not viable.**

---

## Experiment 18 — QQQ Daily MA Regime Scoring (`--qqq-regime-weight`)

**Hypothesis:** Use QQQ's daily MA position as a multi-day regime signal to boost BEARISH ticker scores when the market is in a confirmed downtrend. Unlike `qqq_or_weight` (same-day intraday OR), this uses prior-day's MA20/MA50 values — no lookahead.

**Implementation:** New `--qqq-regime-weight` CLI flag in `run_selector_backtest()`. Pre-computes daily closes from QQQ 5-min bars, then rolls MA20 and MA50. Uses prior trading day's values to avoid lookahead. Three regime tiers:

| Tier | Condition | Factor |
|---|---|---|
| Neutral | QQQ ≥ MA20 | 0.0 (no adjustment) |
| Mild bear | QQQ < MA20, ≥ MA50 | 0.33 |
| Moderate bear | QQQ < MA50, MAs not both falling | 0.67 |
| Full bear | QQQ < MA50 AND MA20+MA50 both falling | 1.0 |

Score adjustment: `s += qqq_regime_weight * factor * (+1 BEARISH / −1 BULLISH)` (symmetric by default).

**Two refinement flags:**
- `--qqq-regime-full-only`: collapses to binary — only fires at full_bear tier (QQQ < MA50 AND both MAs declining). Skips mild/moderate tiers. Prevents false signals during brief corrections in bull years.
- `--qqq-regime-bearish-only`: asymmetric mode — only boosts BEARISH signals, does not penalise BULLISH. Preserves bullish signal quality.

**2022 regime distribution (251 eval days):**
- Neutral (QQQ ≥ MA20): 90 days
- Mild bear: 13 days
- Moderate bear: 35 days
- Full bear: 110 days — 44% of the year in confirmed downtrend

### Symmetric mode sweep (all tiers, penalises BULLISH):

| weight | 2022 Δ | 2020 Δ | 2023 Δ | 2025 Δ | 8yr Δ |
|---|---|---|---|---|---|
| 0.10 | +3.1pp | -8.4pp | +0.0pp | +0.5pp | -9.8pp |
| 0.20 | +3.8pp | -8.4pp | -6.3pp | +0.5pp | -18.8pp |
| 0.30 | +8.1pp | -8.4pp | -8.6pp | -7.8pp | -26.3pp |

**Result:** Symmetric mode destroys 2020 (COVID crash) and 2023 at any weight. The mild/moderate tiers fire during corrections in bull years, penalising correct bullish picks. Not viable.

### `full+bear` mode sweep (`--qqq-regime-full-only --qqq-regime-bearish-only`):

| weight | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 8yr sum | Δ baseline |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 (baseline) | +42.0% | +30.9% | +38.7% | -28.4% | +66.8% | +10.9% | +34.3% | +78.1% | +273.2pp | — |
| 0.20 | +42.0% | +30.9% | +38.7% | -29.4% | +66.8% | +10.9% | +34.3% | +74.5% | +268.5pp | -4.6pp |
| 0.30 | +42.0% | +30.9% | +38.7% | -29.4% | +66.8% | +10.9% | +34.3% | +74.5% | +268.5pp | -4.6pp |
| **0.40** | +42.0% | +30.9% | +38.7% | **-26.2%** | +66.8% | +10.9% | +34.3% | +74.5% | +271.8pp | -1.4pp |
| **0.50** | +42.0% | +30.9% | +38.7% | **-23.9%** | +66.8% | +10.9% | +34.3% | +74.5% | **+274.1pp** | **+0.9pp** |
| 0.60 | +42.0% | +30.9% | +38.7% | -23.9% | +66.8% | +10.9% | +26.1% | +74.5% | +266.0pp | -7.2pp |
| 0.70 | +42.0% | +30.9% | +38.7% | -20.1% | +66.8% | +10.9% | +26.1% | +71.0% | +266.3pp | -6.9pp |
| 0.80 | +42.0% | +30.9% | +38.7% | -20.1% | +66.8% | +9.9% | +26.1% | +71.0% | +265.3pp | -7.9pp |
| 1.00 | +42.0% | +30.9% | +38.7% | -16.0% | +66.8% | +9.9% | +26.1% | +71.0% | +269.4pp | -3.8pp |
| 1.20 | +42.0% | +30.9% | +38.7% | -16.0% | +66.8% | +9.9% | +26.1% | +71.0% | +269.4pp | -3.8pp |

**Top 3 configs:**
1. **`full+bear w=0.50`** — 8yr +274.1pp (+0.9pp) | 2022 improves to -23.9%, 2025/2026 clean
2. `full+bear w=0.40` — 8yr +271.8pp (-1.4pp) | 2022 -26.2%, cleaner 2026 hit
3. `full+bear w=1.00/1.20` — 8yr +269.4pp (-3.8pp) | 2022 best (-16.0%) but 2025 drops -8.2pp

### Why the `full+bear` mode has limited impact

**The MA lag problem:** In 2025 (37 full_bear days) and 2026 (30/94 days), the full_bear tier fires during sharp-correction-then-recovery periods. QQQ is still below MA50 with both MAs pointing down even as individual tickers recover. The feature boosts BEARISH picks during these recovery days → some wrong-direction trades → 2026 loses 3.6pp at w=0.50.

This lag is inherent to MA-based regime detection. In sustained bear markets (2022: 110 full_bear days, QQQ below MA50 for most of year), the feature works correctly. In V-shaped recoveries (2025, 2026), the MA50 slope doesn't reset for 4-6 weeks after the actual bottom.

**Why 2019–2024 are clean:** The full_bear tier requires QQQ < MA50 AND both MAs falling simultaneously. In normal bull years, this condition is rarely met (2022 was the main exception). 2020 COVID crash was sharp but brief — by the time MA slope data confirmed "full bear", QQQ was already recovering.

### Conclusion

`full+bear w=0.50` is the **only config that beats the 8yr baseline** (+0.9pp), with surgical impact:
- 2022 improves: -28.4% → -23.9% (+4.5pp)
- 2019–2024 unchanged (0.0pp in all non-2022 years)
- 2025 unchanged (0.0pp)
- 2026 small cost: -3.6pp

The gain is modest and the 2026 cost is real. The fundamental limitation is MA lag during recoveries. A stronger approach would combine this signal with pool-vote confirmation (only fire when BOTH QQQ is in full_bear AND pool_vote is low), which would avoid firing during individual-ticker recoveries. Not yet implemented.

**Current best-known: Exp 16 baseline at +273.2pp.** `full+bear w=0.50` at +274.1pp is a marginal improvement not worth changing the default. Available as `--qqq-regime-weight 0.50 --qqq-regime-full-only --qqq-regime-bearish-only` for anyone who wants 2022 bear protection with minimal collateral.

---

## Conclusion

There is no scoring weight adjustment that fixes the 2022 directional miss without degrading other years. The problem is structural:

1. **`entry_vs_mid_pct` at w=0.60 dominates.** In a bear regime, gap-up tickers score extremely well on this metric even though their ORs will fail
2. **59% of missed-bearish days had bullish QQQ OR** — no QQQ weight adjustment can fix those days
3. **`dir_ev_weight`** hurts trend years; **higher `qqq_or_weight`** systematically hurts bull years
4. **QQQ MA regime (Exp 18)** best variant gives only +0.9pp 8yr due to MA lag during recoveries

The 2022 loss (-28.4%) is partially structural — the strategy still beats QQQ that year (-33.7%), confirming the OR momentum approach works even in bear markets. The 22 missed-bearish days represent the remaining improvement ceiling.

**Best-known config (Exp 16) at 8yr +273.2pp remains optimal.** The path forward is the `--dynamic-ev-gate` / `--adaptive-lookback` plan — reducing activity in bear/choppy regimes by raising the evidence quality bar, rather than trying to predict direction within the scoring formula.
