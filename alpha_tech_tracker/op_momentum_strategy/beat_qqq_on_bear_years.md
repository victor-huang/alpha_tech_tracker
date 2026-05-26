# Research: Beating QQQ in Bear Years

**Goal:** Understand why OR selector underperforms in bear years (2022: -28.4% vs QQQ -33.7%) and find scoring improvements to reduce bear-year drawdowns without hurting bull years.  
**Baseline config (Exp 16):** `--top 1 --window M1 09:30 3 --min-hold-bars 1 --ma-momentum-gate --feed sip --normalize-or-by-adr --stop-pct 0.4 --reversal --bearish-reentry --bullish-reentry --score-entry-weight 0.60 --score-avg-win-weight 0.00 --score-win-rate-weight 0.10 --score-ev-trend-weight 0.10 --ev-trend-days 15 --min-pool-vote 4 --score-rel-strength-weight 0.15`  
**Baseline result:** 8yr no-compound **+273.2pp** | 2022: -28.4% | 2023: +66.8% | 2025: +34.3%  
**Best-known (Exp 20):** 8yr **+282.9pp** | 2022: -19.7% | 2023: +66.8% | 2025: +38.9%

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

## Experiment 19 — MA200 5-Tier Regime + Asymmetric Recovery Latch

**Hypothesis:** Exp 18's limitation is MA lag — the MA50 slope stays negative for 4-6 weeks after a market bottom, misfiring during V-shaped recoveries. The root cause is that the 4-tier system treats every "QQQ below MA50 with both MAs falling" day equally, whether it's day 10 of a real bear or day 60 of a recovery.

Two structural improvements based on market microstructure:
1. **Accelerating decline toward MA200:** Once QQQ breaks MA50, the move historically accelerates toward MA200. A 5th tier that gates the highest-conviction signal on MA200 (not just MA50) would avoid false positives in recoveries where QQQ never broke MA200.
2. **Asymmetric recovery:** Declines are fast, recoveries are slow. Once QQQ has broken below MA200, bearish picks should still receive a partial boost during the recovery phase — even when QQQ technically reclaims MA20 — until the market has structurally stabilized (MA20 slope turns positive).

### Implementation

**`--qqq-regime-ma200`** — enables 5-tier system:

| Tier | Condition | Factor |
|---|---|---|
| Neutral | QQQ ≥ MA20 | 0.0 |
| Warning | QQQ < MA20, ≥ MA50 | 0.25 |
| Acceleration | QQQ < MA50, ≥ MA200 | 0.55 |
| Deep bear | QQQ < MA200, MAs not both falling | 0.75 |
| True bear | QQQ < MA200 AND both MAs falling | 1.0 |

With `--qqq-regime-full-only`: only the true bear tier (QQQ < MA200 + both MAs falling) fires; all others collapse to 0.

**`--qqq-regime-recovery-floor F`** — recovery latch:
- Activates when prior-day QQQ < MA200 (first break below)
- Releases when QQQ ≥ MA200 **AND** MA20 slope turns positive (dual-condition)
- While active: `factor = max(factor, F)` — floors regime signal even on days QQQ recovers above MA20

**Lookahead safety:** all conditions use prior trading day's values (index `_pi = _ri - 1`). No change to the existing lookahead-safe architecture.

**Data availability note:** MA200 requires 200 days of QQQ history in the cache. For single-year runs where the cache doesn't extend 200 trading days before eval_start (e.g., 2026 YTD when cache starts ~Oct 2025), MA200 is NaN and the code silently falls back to 4-tier. The latch also does not activate in this case.

### 2022 vs 2025 sweep (2-year validation)

Config: `--qqq-regime-full-only --qqq-regime-bearish-only` throughout.

| Config | 2022 | 2025 | Δ 2022 | Δ 2025 | sum Δ |
|---|---|---|---|---|---|
| baseline | -28.4% | +34.3% | — | — | — |
| exp18 fb w=0.50 | -23.9% | +34.3% | +4.5pp | 0.0pp | +4.5pp |
| ma200 fb w=0.50 | -23.9% | +34.3% | +4.5pp | 0.0pp | +4.5pp |
| ma200 fb w=0.60 | -23.9% | +26.1% | +4.5pp | -8.1pp | -3.6pp |
| ma200 fb w=0.70 | -20.1% | +26.1% | +8.3pp | -8.1pp | +0.2pp |
| **ma200 fb w=0.50 rf=0.25** | **-19.7%** | **+34.3%** | **+8.7pp** | **0.0pp** | **+8.7pp** |
| ma200 fb w=0.60 rf=0.25 | -19.7% | +26.1% | +8.7pp | -8.1pp | +0.6pp |
| ma200 fb w=0.50 rf=0.15 | -23.9% | +34.3% | +4.5pp | 0.0pp | +4.5pp |

**Key finding:** `ma200 fb w=0.50 rf=0.25` adds +4.2pp on top of Exp 18 purely through the recovery latch.

**Why 2025 is unaffected:** QQQ's 2025 correction (sharp V-shaped) never broke below MA200. The true bear tier and the latch both never activated — feature is completely dormant in 2025 regardless of weight or floor.

**Why the recovery floor adds value in 2022:** QQQ broke below MA200 around May 2022. From that point, whenever QQQ briefly recovered above MA20 during counter-rallies (Oct-Dec 2022 dead-cat bounces), the 4-tier factor would drop to 0 — the feature went silent at exactly the wrong time. The latch keeps the floor at 0.25 through those bounces until QQQ is structurally recovered (above MA200 AND MA20 slope positive). The release condition was never triggered in 2022 (QQQ didn't genuinely recover MA200 + positive MA20 slope until 2023), so the floor was active throughout the Oct-Dec recovery phase.

**Why `rf=0.15` was not enough:** The floor of 0.15 was below the threshold needed to change any ticker rankings. A single counter-rally BULLISH pick would need the BEARISH alternative to score at least 0.15×weight higher. At 0.15×0.50=0.075, this wasn't decisive. At 0.25×0.50=0.125, it shifted several days.

### Full 8-year sweep

| Config | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 8yr sum | Δbaseline |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | +42.0% | +30.9% | +38.7% | -28.4% | +66.8% | +10.9% | +34.3% | +78.1% | +273.2pp | — |
| exp18 fb w=0.50 | same | same | same | -23.9% | same | same | same | +74.5% | +274.1pp | +0.9pp |
| **ma200 fb w=0.50 rf=0.25** | **same** | **same** | **same** | **-19.7%** | **same** | **same** | **same** | **+74.5%** | **+278.3pp** | **+5.1pp** |
| ma200 fb w=0.60 rf=0.25 | same | same | same | -19.7% | same | same | +26.1% | +74.5% | +269.8pp | -3.4pp |
| ma200 fb w=0.70 | same | same | same | -20.1% | same | same | +26.1% | +74.5% | +269.4pp | -3.8pp |

**2026 behavior:** For the 2026 YTD run, the cache only spans ~Oct 2025 → May 2026 (~155 days), so MA200 is NaN and both `exp18` and `ma200 rf=0.25` fall back to 4-tier identical behavior (-3.6pp vs baseline). The 30 full_bear days in 2026 are from the April 2026 tariff selloff triggering the old MA50-based condition — not the new MA200 condition. The -3.6pp in 2026 is the same for all `full+bear` configs regardless of MA200/latch flags.

### 2022 regime distribution with MA200 (5-tier)

From the `--qqq-regime-ma200` run on 2022:
- Neutral (≥ MA20): ~90 days
- Warning (< MA20, ≥ MA50): ~13 days
- Acceleration (< MA50, ≥ MA200): ~35 days  ← QQQ breaking MA50 but not yet MA200 (Jan–May 2022)
- Deep bear (< MA200, MAs not both falling): ~3 days
- True bear (< MA200, both MAs falling): ~110 days  ← the 44% of 2022 in confirmed downtrend

With `full+bear` mode the acceleration zone (35 days) is suppressed to 0 — this is stricter than Exp 18 and is why `ma200 fb w=0.50` alone gives the same result as `exp18 fb w=0.50`. The additional gain from `rf=0.25` comes entirely from the latch on the true_bear days.

### Conclusion

`ma200 fb w=0.50 rf=0.25` is the **new best-known bear-protection config**:
- **2022: -28.4% → -19.7% (+8.7pp)** — nearly halves the 2022 bear-year loss
- **2019, 2020, 2021, 2023, 2024, 2025: zero impact** — feature is entirely dormant in these years
- **2026: -3.6pp** — same as Exp 18, driven by April tariff correction (not a new regression)
- **8yr total: +278.3pp vs baseline +273.2pp (+5.1pp)** — materially better than Exp 18 (+0.9pp)

The mechanism is surgically targeted: it only activates in years where QQQ breaks below MA200 for an extended period (2022 in our 8yr sample). The recovery floor correctly holds the bearish signal through dead-cat bounces without requiring manual tuning of the recovery timing.

**CLI for this config:**
```bash
--qqq-regime-weight 0.50 --qqq-regime-full-only --qqq-regime-bearish-only \
--qqq-regime-ma200 --qqq-regime-recovery-floor 0.25
```

---

## Experiment 20 — Fine-Tuning: Weight × Floor Grid + Entry Weight Reduction

**Motivation:** Exp 19 established `w=0.50 rf=0.25` as the best config. Two further questions:
1. Is `w=0.50` optimal, or is there a better weight just above or below it?
2. The oracle analysis showed `entry_vs_mid_pct` dominates the scoring gap (+0.61 avg on 22 missed days). Reducing `score_entry_weight` makes the gap cheaper to overcome — can this unlock more 2022 recovery without regressing other years?

**Oracle context (from Investigation 1):** On the 22 missed-bearish days, our BULLISH pick averaged entry_vs_mid=+1.39 vs oracle BEARISH +0.78 — a gap of 0.61. At `score_entry_weight=0.60`, this translates to a 0.366 scoring advantage for the BULLISH pick. The regime boost (`w × factor`) only flips the pick when it exceeds this gap. Lower entry weight shrinks the gap; higher regime weight raises the boost.

### Grid A — regime_weight × recovery_floor (entry_weight=0.60 fixed)

Sweep: weights [0.50–0.80] × floors [0.00–0.50], both years in parallel at max_workers=25.

**Δ 2022 / Δ 2025 (pp vs baseline):**

| w \ rf | 0.00 | 0.15 | 0.25 | 0.35 | 0.50 |
|---|---|---|---|---|---|
| 0.50 | +4.5 / 0.0 | +4.5 / 0.0 | **+8.7 / 0.0** ★ | **+8.7 / 0.0** ★ | **+8.7 / 0.0** ★ |
| **0.55** | +4.5 / +4.7 | +4.5 / +4.7 | **+8.7 / +4.7** ★ | **+8.7 / +4.7** ★ | **+8.7 / +4.7** ★ |
| 0.60 | +4.5 / -8.1 | +4.5 / -8.1 | +8.7 / -8.1 | +8.7 / -8.1 | +8.7 / -8.1 |
| 0.70 | +8.3 / -8.1 | +8.3 / -8.1 | +12.5 / -8.1 | +12.5 / -8.1 | +12.5 / -8.1 |
| 0.80 | +8.3 / -8.1 | +12.5 / -8.1 | +12.5 / -8.1 | +12.5 / -8.1 | +12.5 / -8.1 |

★ = Δ2022 > +6pp AND Δ2025 ≥ -3pp

**`w=0.55` is a new sweet spot** — it improves *both* 2022 (+8.7pp) and 2025 (+4.7pp) for any floor ≥ 0.25. The `--qqq-regime-bearish-only` flag means the regime boost only ever helps bearish picks; at w=0.55 it crosses the threshold on some profitable bearish days in 2025 that w=0.50 narrowly missed. At w=0.60 it overshoots and picks wrong-direction trades in 2025 (the -8.1pp cliff from Exp 19 is unchanged).

The floor has no additional effect above rf=0.25 — the decisive picks are already determined by the true-bear tier (factor=1.0), not the latch floor.

### Grid B — entry_weight × regime_weight (recovery_floor=0.25 fixed)

Sweep: entry_weights [0.60, 0.55, 0.50] × regime_weights [0.50, 0.55, 0.60, 0.70].

| Config | 2022 | 2025 | Δ2022 | Δ2025 | sum Δ |
|---|---|---|---|---|---|
| e=0.60 w=0.50 rf=0.25 (Exp19) | -19.7% | +34.3% | +8.7pp | 0.0pp | +8.7pp |
| e=0.60 w=0.55 rf=0.25 | -19.7% | +38.9% | +8.7pp | +4.7pp | +13.4pp ★ |
| e=0.55 w=0.55 rf=0.25 | -18.2% | +48.3% | +10.2pp | +14.0pp | +24.2pp ★ |
| e=0.50 w=0.55 rf=0.25 | -15.1% | +53.3% | +13.3pp | +19.0pp | +32.3pp ★ |
| e=0.50 w=0.60 rf=0.25 | -14.1% | +53.3% | +14.3pp | +19.0pp | +33.4pp ★ |

2-year numbers looked exceptional for e=0.50/0.55 — required 8yr validation.

### 8-year validation

| Config | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 8yr_sum | Δbaseline |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | +42.0% | +30.9% | +38.7% | -28.4% | +66.8% | +10.9% | +34.3% | +78.1% | +273.2pp | — |
| Exp19 e=0.60 w=0.50 rf=0.25 | same | same | same | -19.7% | same | same | same | +74.5% | +278.3pp | +5.1pp |
| **e=0.60 w=0.55 rf=0.25** | **same** | **same** | **same** | **-19.7%** | **same** | **same** | **+38.9%** | **+74.5%** | **+282.9pp** | **+9.8pp** |
| e=0.55 w=0.55 rf=0.25 | same | +34.2% | +35.3% | -18.2% | +67.7% | +9.6% | +48.3% | +72.0% | +290.8pp | +17.6pp |
| e=0.50 w=0.55 rf=0.25 | +44.9% | +25.2% | +35.4% | -15.1% | +66.4% | +8.6% | +53.3% | +67.7% | +286.4pp | +13.2pp |
| e=0.50 w=0.60 rf=0.25 | +44.9% | +25.2% | +35.4% | -14.1% | +66.4% | +8.6% | +53.3% | +67.7% | +287.4pp | +14.2pp |

**Per-year Δ vs baseline (! = >5pp change):**

| Config | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | sum Δ |
|---|---|---|---|---|---|---|---|---|---|
| Exp19 e=0.60 w=0.50 rf=0.25 | 0 | 0 | 0 | +8.7! | 0 | 0 | 0 | -3.6 | +5.1 |
| **e=0.60 w=0.55 rf=0.25** | **0** | **0** | **0** | **+8.7!** | **0** | **0** | **+4.7** | **-3.6** | **+9.8** |
| e=0.55 w=0.55 rf=0.25 | 0 | +3.3 | -3.4 | +10.2! | +1.0 | -1.3 | +14.0! | -6.1! | +17.6 |
| e=0.50 w=0.55 rf=0.25 | +3.0 | -5.7! | -3.3 | +13.3! | -0.4 | -2.3 | +19.0! | -10.4! | +13.2 |
| e=0.50 w=0.60 rf=0.25 | +3.0 | -5.7! | -3.3 | +14.3! | -0.4 | -2.3 | +19.0! | -10.4! | +14.2 |

### Why entry weight reduction is rejected

**`e=0.50` configs** hurt 2020 badly (-5.7pp). 2020 was the COVID fast-crash-then-recovery — the best picks that year were strong gap-up breakouts with high `entry_vs_mid_pct`. Lowering entry weight globally de-prioritises exactly those signals in a high-momentum year. The 2026 regression (-10.4pp) is also more severe.

**`e=0.55` configs** are less damaging (2020 improves slightly, +3.3pp) but introduce -3.4pp in 2021 and -6.1pp in 2026. Higher headline 8yr sum (+17.6pp) hides meaningful regressions in specific years.

Entry weight reduction is a **global regime change**, not a surgical improvement. It changes pick selection in every year, not just bear years. The appropriate place to reduce entry weight is in a regime-aware scoring feature (e.g., lower entry weight specifically when pool_vote is low or QQQ is in full_bear), not a blanket global reduction.

### Conclusion

**`e=0.60 w=0.55 rf=0.25` is the new best-known config (+9.8pp 8yr = +282.9pp total):**
- 2022: -28.4% → -19.7% (**+8.7pp** bear protection preserved from Exp19)
- 2025: +34.3% → +38.9% (**+4.7pp** bonus from w=0.55 sweet spot)
- 2019–2024: **zero impact** on all 6 years — completely surgical
- 2026: -3.6pp, identical to Exp19 (not a new regression)

The `w=0.55` improvement over `w=0.50` comes from the `bearish-only` asymmetry: at w=0.55, the regime boost is large enough to elevate some genuinely profitable bearish picks in 2025 that w=0.50 narrowly missed selecting. Since bullish picks are never penalised (bearish-only flag), this can only help or be neutral — any regime-boosted bearish pick that gets selected either wins or the loss is constrained by the same stop-loss rules.

**CLI for best-known (Exp 20):**
```bash
--score-entry-weight 0.60 \
--qqq-regime-weight 0.55 --qqq-regime-full-only --qqq-regime-bearish-only \
--qqq-regime-ma200 --qqq-regime-recovery-floor 0.25
```

---

## Experiment 21 — Top-2: No-Bullish Filter + Bear Entry Weight (2026-05-25)

**Motivation:** Top-2 naturally hedges 2022 better (-11.1% vs -28.4% for top-1) because 2 picks/day tend to split BULLISH/BEARISH. The experiments above all target top-1. This experiment asks: can regime flags further improve top-2 2022 without hurting total 8yr return?

**New flags implemented:**
- `--qqq-regime-no-bullish` — on full-bear days (regime factor = 1.0 per `--qqq-regime-full-only + --qqq-regime-ma200`), exclude all BULLISH signal tickers from selection entirely
- `--qqq-regime-bear-entry-weight F` — on full-bear days, override `score_entry_weight` to `F`, reducing entry-vs-mid dominance

### 2022/2025 Sprint Results (top-2 base config)

| Config | 2022 | 2025 | Δ2022 | Δ2025 |
|---|---|---|---|---|
| baseline | -11.1% | +45.3% | — | — |
| exp20 | -8.9% | +38.9% | +2.1p | -6.4p |
| exp20 + no-bull | +4.9% | +32.6% | +16.0p | -12.7p |
| exp20 + bear-ew=0.20 | -1.7% | +36.5% | +9.4p | -8.7p |
| exp20 + bear-ew=0.30 | -3.0% | +38.0% | +8.1p | -7.3p |
| no-bull only | +6.6% | +32.6% | +17.7p | -12.7p |
| exp20 + no-bull + ew=0.30 | +6.8% | +31.8% | +17.8p | -13.5p |
| MA8 after-arm | -6.3% | +28.8% | +4.8p | -16.5p |
| MA8 + exp20 | -11.3% | +23.6% | -0.2p | -21.7p |

Key: MA8 trailing stop is **toxic for top-2** (-16 to -22pp net). The 2025 performance in the CLAUDE.md entry for MA8 was with M1+A1+A2 multi-window; with M1 alone and 2 picks, the 2025 bull bounces get stopped out too early.

### 8-Year Validation

| Config | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 8yr_sum | Δbase |
|---|---|---|---|---|---|---|---|---|---|---|
| top2 baseline | +22.5% | +11.7% | +26.3% | -11.1% | +30.2% | +1.2% | +45.3% | +52.1% | +178.3pp | — |
| + exp20 | +22.5% | +11.7% | +26.3% | -8.9% | +30.2% | +1.5% | +38.9% | +52.1% | +174.4pp | -4.0pp |
| + no-bull | +22.5% | +12.0% | +28.4% | +6.6% | +30.2% | -0.8% | +32.6% | +47.1% | +178.7pp | +0.4pp |
| + exp20 + no-bull | +22.5% | +12.0% | +28.4% | +4.9% | +30.2% | -0.8% | +32.6% | +47.1% | +177.0pp | -1.3pp |
| + exp20 + bear-ew=0.20 | +22.5% | +11.4% | +27.0% | -1.7% | +30.2% | +0.5% | +36.5% | +50.8% | +177.3pp | -1.0pp |
| + exp20 + bear-ew=0.30 | +22.5% | +11.4% | +27.0% | -3.0% | +30.2% | +0.5% | +38.0% | +50.8% | +177.5pp | -0.8pp |
| + exp20 + no-bull + ew=0.30 | +22.5% | +12.0% | +28.4% | +6.8% | +30.2% | -0.8% | +31.8% | +47.5% | +178.5pp | +0.1pp |

### Finding: Top-2 Regime Filtering is a Break-Even Trade

The no-bullish filter **does turn 2022 profitable** (+6.6% vs -11.1% baseline) — but the 2022 gain is almost entirely consumed by a -12.7pp regression in 2025 and -5pp in 2026. 

**Why the 2025 regression is so large:** In April-May 2025 (tariff crash), QQQ briefly fell below MA200 with both MAs falling — triggering full-bear. Those same days had powerful V-shaped recoveries with large BULLISH signals. The no-bullish filter excluded those recovery picks.

**Net result across 8 years:** All variants land within ±4pp of the baseline (+178.3pp). The **`no-bull` variant is the only one above baseline (+0.4pp)** — it swaps the -11.1% 2022 for +6.6% without changing the 8yr total meaningfully.

**Decision framework:**
- If year-to-year drawdown profile matters (avoiding a -11% year): use `no-bull` (+0.4pp 8yr, 2022: +6.6%)
- If maximizing 8yr total: stick with the top-2 baseline (best at +178.3pp among top-2 regime configs)
- top-1 + exp20 (+282.9pp) remains the best single-pick config for maximizing 8yr returns

**CLI for top-2 + no-bull:**
```bash
--top 2 \
--qqq-regime-weight 0.55 --qqq-regime-full-only --qqq-regime-ma200 \
--qqq-regime-recovery-floor 0.25 --qqq-regime-no-bullish
```

---

## Experiment 22 — `--qqq-regime-bearish-ev-only`: Targeted EV Gate Bypass (2026-05-25)

**Motivation:** Oracle rank comparison revealed the root cause of 2022 losses. On 44 of 61 trading days in H1 2022 (72%), the oracle rank-1 pick had score rank = 999 — meaning it was **filtered before scoring** by the `ev_trade < 0` gate. Tickers like SHOP BEARISH (+8.52%), AMD BEARISH (+8.90%), APP BEARISH (+5.41%) had negative combined 90-day EV because the prior lookback window covered a strong bull period. Their directional EV (`ev_trade_bearish`) was likely positive.

**Root cause in code:** `if stats["ev_trade"] < min_ev: continue` runs before all scoring — it blocks every ticker with negative combined EV regardless of directional quality. This filter was designed for bull markets where combined EV is a good quality signal.

**New flag `--qqq-regime-bearish-ev-only`:** On full-bear QQQ days (regime factor >= 1.0 per `--qqq-regime-full-only + --qqq-regime-ma200`), BEARISH signals bypass the combined EV gate. Instead, the direction-split EV gate (`--direction-split-ev`, on by default) checks `ev_trade_bearish >= 0`. This admits tickers with negative combined EV but positive bearish-specific EV.

### H1+H2 2022 Sweep Results (top-1)

| Config | H1-2022 | H2-2022 | 2022 | Δfull |
|---|---|---|---|---|
| baseline | -25.8% | -2.6% | -28.4% | — |
| + exp20 | -18.1% | -5.8% | -23.9% | +4.5p |
| bear-ev-only alone | -18.1% | -5.8% | -23.9% | +4.5p |
| bear-ev-only + no-bull | +8.9% | +4.6% | +13.5% | **+41.9p ★** |
| bear-ev-only + bear-ew=0.30 | -2.9% | -2.5% | -5.4% | +23.0p ★ |
| bear-ev-only + no-bull + bear-ew=0.30 | +16.6% | +4.6% | +21.2% | **+49.6p ★** |
| top2 + bear-ev-only | -9.7% | +0.8% | -8.9% | +19.5p ★ |
| top2 + bear-ev-only + no-bull | +1.1% | +2.5% | +3.5% | +31.9p ★ |

Key: `bear-ev-only` alone does nothing (+4.5pp, same as exp20). The flag only unlocks value when combined with `no-bull` — which drops BULLISH picks on full-bear days, forcing selection among BEARISH plays only. The combination turns 2022 profitable for the first time.

### 8-Year Validation

| Config | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 8yr | Δbase |
|---|---|---|---|---|---|---|---|---|---|---|
| top1 baseline | +42.0% | +30.9% | +38.7% | -28.4% | +66.8% | +10.9% | +34.3% | +78.1% | +273.2pp | — |
| top1 + exp20 | +42.0% | +30.9% | +38.7% | -19.7% | +66.8% | +10.9% | +38.9% | +74.5% | +282.9pp | +9.8pp |
| top1 + bear-ev-only + no-bull | +42.0% | +30.9% | +40.6% | +20.1% | +66.8% | +9.2% | +29.4% | +64.3% | +303.2pp | **+30.1pp ★** |
| top1 + bear-ev-only + no-bull + ew=0.30 | +42.0% | +28.4% | +40.6% | +27.7% | +66.8% | +9.2% | +28.5% | +64.3% | +307.5pp | **+34.4pp ★** |
| top2 baseline | +22.5% | +11.7% | +26.3% | -11.1% | +30.2% | +1.2% | +45.3% | +52.1% | +178.3pp | — |
| top2 + exp20 | +22.5% | +11.7% | +26.3% | -8.9% | +30.2% | +1.5% | +38.9% | +52.1% | +174.4pp | -4.0pp |
| top2 + bear-ev-only + no-bull | +22.5% | +12.0% | +28.4% | +4.9% | +30.2% | -0.8% | +32.6% | +47.1% | +177.0pp | -1.3pp |
| top2 + bear-ev-only + no-bull + ew=0.30 | +22.5% | +12.0% | +28.4% | +6.8% | +30.2% | -0.8% | +31.8% | +47.5% | +178.5pp | +0.1pp |

### Findings

**Top-1: breakthrough improvement (+34.4pp 8yr, 2022 from -28.4% to +27.7%).** The flag combination surgically targets the root cause — it only fires when:
1. QQQ is confirmed in full-bear regime (below MA200, both MAs falling)
2. The signal is BEARISH
3. The combined EV is negative but bearish-specific EV is positive

**Why the 2025 and 2026 regressions occur (-5.8pp 2025, -13.7pp 2026):** In April-May 2025 and early 2026 (tariff crash + QQQ selloffs), QQQ briefly fell below MA200 with both MAs falling — triggering full-bear. Those same days also had valid BULLISH signals from gap-up tickers that scored well. The `no-bull` component drops those BULLISH picks, costing ~5-14pp in those recovery windows.

**Top-2: break-even (+0.1pp net 8yr).** The 2022 improvement (+17.8pp) is consumed by -13.5pp in 2025 and -4.6pp in 2026. The two-pick structure already diversifies some of the directional risk.

**New best-known config (top-1):** 8yr **+307.5pp** (was +282.9pp with exp20 only).

**Full runnable command:**
```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 1 \
  --window M1 09:30 3 \
  --min-hold-bars 1 \
  --ma-momentum-gate \
  --feed sip \
  --qqq-or-weight 0.40 \
  --normalize-or-by-adr \
  --stop-pct 0.4 \
  --reversal --bearish-reentry --bullish-reentry \
  --score-entry-weight 0.60 \
  --score-avg-win-weight 0.00 \
  --score-win-rate-weight 0.10 \
  --score-ev-trend-weight 0.10 \
  --ev-trend-days 15 \
  --score-rel-strength-weight 0.15 \
  --min-pool-vote 4 \
  --qqq-regime-weight 0.55 \
  --qqq-regime-full-only \
  --qqq-regime-bearish-only \
  --qqq-regime-ma200 \
  --qqq-regime-recovery-floor 0.25 \
  --qqq-regime-bearish-ev-only \
  --qqq-regime-no-bullish \
  --qqq-regime-bear-entry-weight 0.30 \
  --start 2022-01-01 --end 2022-12-31
```

---

## Conclusion

There is no scoring weight adjustment that fixes the 2022 directional miss without degrading other years. The problem is structural:

1. **`entry_vs_mid_pct` at w=0.60 dominates.** In a bear regime, gap-up tickers score extremely well on this metric even though their ORs will fail
2. **59% of missed-bearish days had bullish QQQ OR** — no QQQ weight adjustment can fix those days
3. **`dir_ev_weight`** hurts trend years; **higher `qqq_or_weight`** systematically hurts bull years
4. **QQQ MA regime (Exp 18)** best variant gives only +0.9pp 8yr due to MA lag during recoveries
5. **MA200 5-tier + recovery latch (Exp 19)** achieves +5.1pp 8yr — surgically targets sustained bear markets (QQQ below MA200) while remaining dormant in all other years
6. **Fine-tuned w=0.55 (Exp 20)** achieves +9.8pp 8yr — `w=0.55` sweet spot adds +4.7pp in 2025 on top of Exp19 with zero new regressions across 2019–2024
7. **Top-2 no-bullish filter (Exp 21)** is break-even over 8yr (+0.4pp). It converts the -11.1% 2022 to +6.6% but the gain is offset by -12.7pp in 2025. Preferred only if avoiding a down year matters more than maximizing total return.
8. **`--qqq-regime-bearish-ev-only` + no-bull (Exp 22)** achieves **+34.4pp 8yr net** for top-1 by bypassing the combined EV gate for BEARISH signals on confirmed full-bear days. Turns 2022 from -28.4% to +27.7%. The 2025/2026 regressions (-5.8pp / -13.7pp) reflect V-shaped recovery days where BULLISH picks were excluded.

**Best-known config (top-1, max 8yr return):** Exp 22 bear-ev-only + no-bull + ew=0.30 at **+307.5pp**:
```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 1 \
  --window M1 09:30 3 \
  --min-hold-bars 1 \
  --ma-momentum-gate \
  --feed sip \
  --qqq-or-weight 0.40 \
  --normalize-or-by-adr \
  --stop-pct 0.4 \
  --reversal --bearish-reentry --bullish-reentry \
  --score-entry-weight 0.60 \
  --score-avg-win-weight 0.00 \
  --score-win-rate-weight 0.10 \
  --score-ev-trend-weight 0.10 \
  --ev-trend-days 15 \
  --score-rel-strength-weight 0.15 \
  --min-pool-vote 4 \
  --qqq-regime-weight 0.55 \
  --qqq-regime-full-only \
  --qqq-regime-bearish-only \
  --qqq-regime-ma200 \
  --qqq-regime-recovery-floor 0.25 \
  --qqq-regime-bearish-ev-only \
  --qqq-regime-no-bullish \
  --qqq-regime-bear-entry-weight 0.30 \
  --start YYYY-01-01 --end YYYY-12-31
```

---

## Exp 23 — `--qqq-regime-bear-ctp` (Bear Close-To-Price threshold expansion)

**Date:** 2026-05-25  
**Goal:** Improve 2022 bear-year performance by expanding the BEARISH OR signal threshold on confirmed full-bear QQQ days.

### What it does

On days where QQQ is in a confirmed full-bear regime (factor ≥ 1.0: QQQ < MA200, both MA20+MA50 falling), the standard bottom-20% BEARISH entry threshold is loosened to a configurable percentage (`--qqq-regime-bear-ctp 0.35` = bottom 35%). BULLISH threshold and all other scoring are unaffected. Uses prior-day QQQ MA values — no lookahead.

**Why:** In a confirmed bear regime, tickers that close in the 20–35% zone of the OR range (above the standard 20% threshold but still weak) represent genuine bearish momentum that the standard filter misses. 2022 had 37 full-bear QQQ days with limited bearish signal coverage; CTP adds valid trades on those no-trade days.

### Implementation

- `bear_ctp_dates` set computed once at startup (full-bear QQQ days in eval window, using prior-day MA values)
- QQQ fetch moved before signal pre-computation so `bear_ctp_dates` is available when `compute_signals_with_backtest()` runs
- New parameters: `bear_ctp_dates: set`, `bear_ctp: float` passed through `run_backtest()` → `compute_signals_with_backtest()`
- CLI flag: `--qqq-regime-bear-ctp F`

### 8-year sweep results (top-1, exp22 base config)

```
Config                        2019   2020   2021   2022   2023   2024   2025   2026   8yr   Δbaseline
baseline                     +42.0  +30.9  +38.7  -28.4  +66.8  +10.9  +34.3  +78.1  +273.2pp    +0.0pp
+ exp22                      +42.0  +28.4  +40.6  +27.7  +66.8   +9.2  +28.5  +64.3  +307.5pp   +34.4pp
+ exp22 + ctp0.35            +41.6  +33.1  +37.8  +36.8  +66.8   +6.4  +30.8  +64.2  +317.5pp   +44.3pp ★
+ exp22 + ctp0.40            +41.6  +33.1  +37.8  +65.8  +66.8   +6.0  +22.0  +57.0  +330.1pp   +57.0pp
+ exp22 + ctp0.45            +41.2  +33.1  +35.2  +39.9  +66.8   +6.0  +18.2  +59.8  +300.2pp   +27.0pp
+ exp22 + ctp0.50            +41.6  +33.1  +37.5  +37.5  +66.8   +7.5  +25.7  +57.6  +307.4pp   +34.2pp
```

**`ctp0.35` is the cleanest trade** (+44.3pp 8yr, +10pp over exp22): 2022 recovers from −28.4% to +36.8%, while 2025 and 2026 stay close to exp22 (−3.5pp and −0.1pp respectively).

**`ctp0.40` has best raw 8yr** (+57pp) but large year swings: 2022 +65.8% (exceptional), 2025 −12.3pp vs baseline, 2026 −21pp vs baseline.

### Displacement analysis (why ctp0.40 hurts 2025/2026)

Per-day comparison (exp22 vs exp22+ctp0.40) at top-1 for 2025 and 2026:

**2025 (−11.55pp total Δ):**
- `same_ticker` (153 days): Σδ = 0pp — no change
- `ticker_swap` (27 days): Σδ = **−6.67pp** — CTP displaced a good standard bearish pick with a mid-zone ticker 16/27 times
- `ctp_new_trade` (6 days): Σδ = −3.00pp — new trades on no-trade bear days (3/6 WR)
- `base_only_no_ctp` (5 days): Σδ = −1.89pp

**2026 (−24pp total Δ, top-1 pnl-pct sum):**
- `ticker_swap` (9 days): Σδ = −3.98pp (6/9 worse)
- `ctp_new_trade` (12 days): Σδ = **−9.12pp** — 3/12 WR (25%) on full-bear no-trade days in March–April 2026 tariff crash
- `base_only_no_ctp` (1 day): Σδ = −10.94pp

Root cause: CTP expands the bearish pool on bear days, changing rank ordering and displacing good existing picks. In high-volatility bear regimes (March–April 2025/2026), mid-zone bearish entries have low quality (25% WR vs standard bearish ~40%+ WR).

### `--qqq-regime-bear-ctp-fallback-only` — investigated and removed

A "fallback-only" modifier was implemented and tested: apply CTP threshold only when no standard bottom-20% bearish signal exists (preventing displacement). It fixed 2025 (+1.3pp vs −6.5pp for ctp0.40) but made 2026 worse (−12.5pp vs −7.3pp) by blocking the 3 good ticker swaps (+8.02pp gross positive) while leaving the bad `ctp_new_trade` category untouched. **Removed** — no net benefit.

### 8-year sweep results (top-2, exp22 base config)

```
Config                        2019   2020   2021   2022   2023   2024   2025   2026   8yr   Δbaseline
baseline                     +22.5  +11.7  +26.3  -11.1  +30.2   +1.2  +45.3  +52.1  +178.3pp    +0.0pp
+ exp22                      +22.5  +12.0  +28.4   +6.8  +30.2   -0.8  +31.8  +47.5  +178.5pp    +0.1pp
+ exp22 + ctp0.35            +21.7  +16.3  +26.8  +30.6  +30.2   -1.0  +25.6  +42.2  +192.5pp   +14.2pp ★
+ exp22 + ctp0.40            +21.7  +16.3  +26.8  +37.8  +30.2   -1.2  +16.7  +38.4  +186.7pp    +8.4pp
+ exp22 + ctp0.45            +21.7  +16.3  +25.5  +18.9  +30.2   -1.2  +14.2  +39.7  +165.4pp   −12.9pp
+ exp22 + ctp0.50            +21.9  +16.3  +26.4  +24.6  +30.2   -1.7  +13.7  +40.4  +171.8pp    −6.6pp
```

**Key finding:** At top-2, exp22 alone is essentially flat (+0.1pp) because `--qqq-regime-no-bullish` suppresses the second bullish pick on bear days, costing −13.5pp in 2025. CTP adds value in 2022 but the 2025/2026 year damage is larger at top-2 than top-1.

**`ctp0.35` remains best** at top-2 (+14.2pp 8yr), but 2025 costs −19.6pp vs baseline. `ctp0.40+` all hurt 8yr at top-2.

### Is `--qqq-regime-bear-ctp` useful?

**Top-1 — yes, clearly useful.** `ctp0.35` adds a clean +10pp over exp22 (8yr) with 2022 recovering from −28.4% to +36.8% and 2025/2026 staying within −3.5pp / −0.1pp of exp22. The tradeoff is narrow and one-sided in bear years.

**Top-2 — questionable.** The underlying problem at top-2 isn't CTP — it's that `exp22` itself barely helps at top-2 (+0.1pp 8yr). `--qqq-regime-no-bullish` suppresses the second pick on bear days and costs −13.5pp in 2025. CTP adding 2022 benefit on top of an already-impaired base config is a weaker signal.

**The broader question for the live M1+A1+A2 top-2 setup:** the exp22 bear regime settings were tuned at top-1 and don't translate well to top-2. Before leaning on CTP, it's worth asking whether `--qqq-regime-no-bullish` should be dropped — that alone would recover most of the 2025 gap without touching CTP at all. The exp22 base config needs re-evaluation at top-2 before CTP adds reliable value.

### Recommendation

For **top-1 M1-only strategy**: `--qqq-regime-bear-ctp 0.35` is a clean addition — +10pp 8yr over exp22, 2022 fully recovered, minimal year damage.

For **top-2 / multi-window live strategy**: hold off on CTP; re-evaluate exp22 base config (specifically `--qqq-regime-no-bullish`) at top-2 first.

### CLI

```bash
# exp22 + ctp0.35 (recommended for top-1)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 1 --window M1 09:30 3 --min-hold-bars 1 --ma-momentum-gate \
  --feed sip --qqq-or-weight 0.40 --normalize-or-by-adr --stop-pct 0.4 \
  --reversal --bearish-reentry --bullish-reentry \
  --score-entry-weight 0.60 --score-avg-win-weight 0.00 \
  --score-win-rate-weight 0.10 --score-ev-trend-weight 0.10 --ev-trend-days 15 \
  --score-rel-strength-weight 0.15 --min-pool-vote 4 \
  --qqq-regime-weight 0.55 --qqq-regime-full-only --qqq-regime-bearish-only \
  --qqq-regime-ma200 --qqq-regime-recovery-floor 0.25 \
  --qqq-regime-bearish-ev-only --qqq-regime-no-bullish \
  --qqq-regime-bear-entry-weight 0.30 \
  --qqq-regime-bear-ctp 0.35 \
  --start YYYY-01-01 --end YYYY-12-31
```

---

**Previous best-known (Exp 20, more balanced):** **+282.9pp** — better if 2025/2026 bull performance is weighted more:
```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 1 \
  --window M1 09:30 3 \
  --min-hold-bars 1 \
  --ma-momentum-gate \
  --feed sip \
  --qqq-or-weight 0.40 \
  --normalize-or-by-adr \
  --stop-pct 0.4 \
  --reversal --bearish-reentry --bullish-reentry \
  --score-entry-weight 0.60 \
  --score-avg-win-weight 0.00 \
  --score-win-rate-weight 0.10 \
  --score-ev-trend-weight 0.10 \
  --ev-trend-days 15 \
  --score-rel-strength-weight 0.15 \
  --min-pool-vote 4 \
  --qqq-regime-weight 0.55 \
  --qqq-regime-full-only \
  --qqq-regime-bearish-only \
  --qqq-regime-ma200 \
  --qqq-regime-recovery-floor 0.25 \
  --start YYYY-01-01 --end YYYY-12-31
```
