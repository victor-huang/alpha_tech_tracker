# M1 Walk-Forward Optimization Test

Tests whether the best M1 window config selected from the past 2 months of data
predicts strong performance in the following out-of-sample month.

---

## Methodology

**Technique:** Rolling 2-month walk-forward optimization.

**Config space swept per training window:**
- Bars: 1–10 (entry times 9:35–10:20)
- Stop-pct: 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0
- 80 total combos per sweep

**Base flags (fixed across all runs):**
```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 \
  --window M1 09:30 <bars> \
  --bearish-reentry --bullish-reentry --reversal \
  --feed sip \
  --min-hold-bars 1 \
  --stop-pct <stop_pct>
```

**Per step:**
1. **Sweep training window** (2 months) → find best config by P&L
2. **Apply best config to test month** → out-of-sample (OOS) P&L
3. **Sweep test month** → oracle P&L (best possible in hindsight)
4. **Record:** OOS P&L, oracle P&L, efficiency ratio (OOS / oracle), config selected

**Efficiency ratio** = OOS P&L ÷ Oracle P&L.
- Near 1.0 → config selection is highly predictive
- Near 0 → past config doesn't generalize; regime changed
- Negative → selected config actively lost money in test month

---

## Roll Schedule

| Step | Training Window | Best Config → | Test Month | Oracle |
|---|---|---|---|---|
| 1 | Dec 2025 + Jan 2026 | → | Feb 2026 | Feb sweep |
| 2 | Jan 2026 + Feb 2026 | → | Mar 2026 | Mar sweep |
| 3 | Feb 2026 + Mar 2026 | → | Apr 2026 | Apr sweep |
| 4 | Mar 2026 + Apr 2026 | → | May 2026 | May sweep |

---

## Results

### Step 1 — Train: Dec 2025 + Jan 2026 → Test: Feb 2026

**Training top-5 (Dec 2025 + Jan 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 10 | 10:20 | 1.0 | +$2,673 |
| #2 | 2 | 9:40 | 0.7 | +$2,499 |
| #3 | 10 | 10:20 | 0.9 | +$2,454 |
| #4 | 9 | 10:15 | 0.5 | +$2,395 |
| #5 | 9 | 10:15 | 0.9 | +$2,302 |

**Best config selected:** `bars=10 stop=1.0`

| Metric | Value |
|---|---|
| OOS P&L (Feb 2026, selected config) | +$1,840 |
| Oracle P&L (Feb 2026, best sweep) | +$3,445 |
| Oracle config | bars=6 (10:00) stop=0.9 |
| Efficiency ratio | **0.534** |

---

### Step 2 — Train: Jan 2026 + Feb 2026 → Test: Mar 2026

**Training top-5 (Jan 2026 + Feb 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 3 | 9:45 | 0.8 | +$4,911 |
| #2 | 3 | 9:45 | 0.9 | +$4,862 |
| #3 | 3 | 9:45 | 0.4 | +$4,721 |
| #4 | 3 | 9:45 | 0.6 | +$4,648 |
| #5 | 3 | 9:45 | 1.0 | +$4,586 |

**Best config selected:** `bars=3 stop=0.8`

| Metric | Value |
|---|---|
| OOS P&L (Mar 2026, selected config) | +$370 |
| Oracle P&L (Mar 2026, best sweep) | +$1,778 |
| Oracle config | bars=8 (10:10) stop=0.3 |
| Efficiency ratio | **0.208** |

---

### Step 3 — Train: Feb 2026 + Mar 2026 → Test: Apr 2026

**Training top-5 (Feb 2026 + Mar 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 3 | 9:45 | 0.4 | +$3,749 |
| #2 | 1 | 9:35 | 0.6 | +$3,573 |
| #3 | 1 | 9:35 | 0.5 | +$3,395 |
| #4 | 1 | 9:35 | 1.0 | +$3,284 |
| #5 | 3 | 9:45 | 0.7 | +$3,269 |

**Best config selected:** `bars=3 stop=0.4`

| Metric | Value |
|---|---|
| OOS P&L (Apr 2026, selected config) | +$410 |
| Oracle P&L (Apr 2026, best sweep) | +$1,477 |
| Oracle config | bars=1 (9:35) stop=0.9 |
| Efficiency ratio | **0.278** |

---

### Step 4 — Train: Mar 2026 + Apr 2026 → Test: May 2026 YTD

**Training top-5 (Mar 2026 + Apr 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 1 | 9:35 | 0.6 | +$2,670 |
| #2 | 1 | 9:35 | 0.5 | +$2,407 |
| #3 | 1 | 9:35 | 1.0 | +$2,352 |
| #4 | 1 | 9:35 | 0.9 | +$2,228 |
| #5 | 10 | 10:20 | 0.4 | +$2,156 |

**Best config selected:** `bars=1 stop=0.6`

| Metric | Value |
|---|---|
| OOS P&L (May 2026 YTD, selected config) | +$180 |
| Oracle P&L (May 2026 YTD, best sweep) | +$1,432 |
| Oracle config | bars=10 (10:20) stop=0.9 |
| Efficiency ratio | **0.126** |

---

## Summary Table

| Step | Test Month | Selected Config | OOS P&L | Oracle P&L | Efficiency |
|---|---|---|---|---|---|
| 1 | Feb 2026 | bars=10 stop=1.0 | +$1,840 | +$3,445 | 0.534 |
| 2 | Mar 2026 | bars=3 stop=0.8 | +$370 | +$1,778 | 0.208 |
| 3 | Apr 2026 | bars=3 stop=0.4 | +$410 | +$1,477 | 0.278 |
| 4 | May 2026 YTD | bars=1 stop=0.6 | +$180 | +$1,432 | 0.126 |
| **Total** | | | **+$2,800** | **+$8,132** | **0.344** |

---

## Interpretation Guide

| Efficiency Ratio | Interpretation |
|---|---|
| ≥ 0.70 | Strong predictability — past 2 months is a reliable guide |
| 0.40–0.70 | Moderate predictability — useful but noisy |
| 0.10–0.40 | Weak predictability — regime shifts frequently |
| ≤ 0.10 or negative | Config is not stable — past 2 months is not a useful signal |

---

## Key Questions This Test Answers

1. **Is there a stable M1 config?** Does the same bars/stop-pct keep winning across steps, or does it flip every month?
2. **How much does the regime matter?** Large efficiency drops in specific months likely map to known regime events (VIX spikes, trend reversals).
3. **Is 2 months enough lookback?** If efficiency is consistently low, a longer training window or regime-conditional selection may be needed.
4. **How much P&L are we leaving on the table?** Oracle total vs OOS total gives the upper bound on what better config selection could have earned.

---

## Findings

### Overall: Weak predictability (0.344 efficiency)

The past 2 months of training data is a poor predictor of next-month config. We captured
only 34.4% of the oracle P&L ($2,800 vs $8,132). The config that wins the training window
rarely matches the oracle for the test month.

### Config instability — flips every step

The best config changed completely each step with no common thread:

| Step | Selected | Oracle |
|---|---|---|
| 1 | bars=10 (10:20) | bars=6 (10:00) |
| 2 | bars=3 (9:45) | bars=8 (10:10) |
| 3 | bars=3 (9:45) | bars=1 (9:35) |
| 4 | bars=1 (9:35) | bars=10 (10:20) |

No single bar count or stop-pct dominates. The training winner and the oracle winner
disagree in every single step. This is the hallmark of regime-dependent behaviour —
the market structure shifts faster than a 2-month lookback can track.

### Efficiency degrades over time

| Step | Test Month | Efficiency |
|---|---|---|
| 1 | Feb 2026 | 0.534 — best, near "moderate" |
| 2 | Mar 2026 | 0.208 — weak |
| 3 | Apr 2026 | 0.278 — weak |
| 4 | May 2026 YTD | 0.126 — near useless |

Feb was the only step with meaningful predictability. Mar–May degraded steadily —
likely because the early 2026 trending regime (Jan–Feb) gave way to a choppier,
more volatile regime (Mar–Apr tariff shock, elevated VIX) that flipped optimal configs.

### Step 2 anomaly: bars=3 dominates training but fails OOS

In Step 2, all top-5 training configs were bars=3 (strong consensus). Yet the Mar 2026
oracle is bars=8 — the opposite end of the spectrum. This is the clearest case of the
training window overfitting to Jan–Feb's trending character while March turned choppy.

### What the oracle configs tell us

| Month | Oracle config | Interpretation |
|---|---|---|
| Feb 2026 | bars=6 (10:00) | Mid-morning OR — moderate trending |
| Mar 2026 | bars=8 (10:10) | Long OR — slow/grindy month |
| Apr 2026 | bars=1 (9:35) | Shortest OR — high volatility / fast moves |
| May 2026 YTD | bars=10 (10:20) | Longest OR — very slow/late-breaking month |

The oracle config alternates between short and long OR every month. This is consistent
with the regime analysis finding that no single bar count wins all periods.

### Conclusions

1. **2-month lookback is insufficient** for stable config selection — the regime can
   shift completely within a single month (e.g. Jan trending → March choppy).
2. **Selecting by P&L rank alone is fragile** — the training winner is often near the
   wrong end of the next month's ranking.
3. **Regime-conditional selection is the correct path** — using VIX + QQQ MA alignment
   at signal time to pick bars dynamically is more promising than optimizing over a
   trailing window.
4. **The consistent positive OOS P&L ($180–$1,840) is encouraging** — even a poorly
   selected config stays positive in 2026 because the year's broad trend lifts all boats.
   The test will be more discriminating in a bear or choppy year.

---

## 3-Month Training Window Comparison

Re-ran with 3-month training windows (Nov–Jan, Dec–Feb, Jan–Mar, Feb–Apr).
Oracle results are identical — only training sweeps changed.

| Step | Test | 2mo Selected | 2mo OOS | 3mo Selected | 3mo OOS | Oracle |
|---|---|---|---|---|---|---|
| 1 | Feb 2026 | bars=10 s=1.0 | +$1,840 | bars=10 s=1.0 | +$1,840 | +$3,445 |
| 2 | Mar 2026 | bars=3 s=0.8 | +$370 | bars=2 s=0.7 | +$476 | +$1,778 |
| 3 | Apr 2026 | bars=3 s=0.4 | +$410 | bars=3 s=0.8 | +$359 | +$1,477 |
| 4 | May 2026 | bars=1 s=0.6 | +$180 | bars=1 s=0.6 | +$180 | +$1,432 |
| **Total** | | | **+$2,800** | | **+$2,855** | **+$8,132** |
| **Efficiency** | | | **0.344** | | **0.351** | |

**The 3-month window is essentially no better** — +$55 improvement (+0.7pp efficiency).
The same config is selected in steps 1 and 4; steps 2 and 3 differ slightly but neither
improves meaningfully. The problem is not the length of the lookback — it's that the
regime can flip within a single month, making any trailing window a lagging indicator.

**Key observation:** In step 3, adding Nov–Dec 2025 data (3mo) vs just Dec 2025 (2mo)
actually made the result slightly *worse* ($359 vs $410) — older data introduced noise
from a different regime rather than signal.

### Window Length Conclusion (2-month vs 3-month)

3-month is essentially no better than 2-month. The root cause is regime instability, not data
scarcity. The 6-month test below revisits this conclusion.

---

## 6-Month Training Window

Re-ran with 6-month rolling training windows. Adds Jan 2026 as a new test month.
Oracle for Feb–May reused from prior runs; Jan 2026 oracle swept fresh.

### Step 1 — Train: Jul–Dec 2025 → Test: Jan 2026

**Training top-5 (Jul–Dec 2025):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 7 | 10:05 | 0.3 | +$3,831 |
| #2 | 7 | 10:05 | 0.6 | +$2,802 |
| #3 | 7 | 10:05 | 0.5 | +$2,558 |
| #4 | 4 | 9:50 | 1.0 | +$2,177 |
| #5 | 6 | 10:00 | 0.3 | +$2,064 |

**Best config selected:** `bars=7 stop=0.3`

| Metric | Value |
|---|---|
| OOS P&L (Jan 2026, selected config) | +$460 |
| Oracle P&L (Jan 2026, best sweep) | +$2,538 |
| Oracle config | bars=10 (10:20) stop=0.4 |
| Efficiency ratio | **0.181** |

---

### Step 2 — Train: Aug 2025–Jan 2026 → Test: Feb 2026

**Training top-5 (Aug 2025–Jan 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 3 | 9:45 | 0.8 | +$3,567 |
| #2 | 10 | 10:20 | 0.3 | +$3,461 |
| #3 | 10 | 10:20 | 1.0 | +$3,375 |
| #4 | 10 | 10:20 | 0.9 | +$2,926 |
| #5 | 7 | 10:05 | 0.3 | +$2,840 |

**Best config selected:** `bars=3 stop=0.8`

| Metric | Value |
|---|---|
| OOS P&L (Feb 2026, selected config) | +$2,867 |
| Oracle P&L (Feb 2026, best sweep) | +$3,445 |
| Oracle config | bars=6 (10:00) stop=0.9 |
| Efficiency ratio | **0.832** |

---

### Step 3 — Train: Sep 2025–Feb 2026 → Test: Mar 2026

**Training top-5 (Sep 2025–Feb 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 3 | 9:45 | 0.8 | +$6,972 |
| #2 | 3 | 9:45 | 0.9 | +$6,292 |
| #3 | 3 | 9:45 | 0.5 | +$6,229 |
| #4 | 3 | 9:45 | 0.6 | +$6,070 |
| #5 | 3 | 9:45 | 0.4 | +$5,524 |

**Best config selected:** `bars=3 stop=0.8`

| Metric | Value |
|---|---|
| OOS P&L (Mar 2026, selected config) | +$370 |
| Oracle P&L (Mar 2026, best sweep) | +$1,778 |
| Oracle config | bars=8 (10:10) stop=0.3 |
| Efficiency ratio | **0.208** |

---

### Step 4 — Train: Oct 2025–Mar 2026 → Test: Apr 2026

**Training top-5 (Oct 2025–Mar 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 3 | 9:45 | 0.8 | +$7,683 |
| #2 | 3 | 9:45 | 0.9 | +$7,007 |
| #3 | 3 | 9:45 | 0.5 | +$6,661 |
| #4 | 3 | 9:45 | 0.6 | +$6,410 |
| #5 | 3 | 9:45 | 0.7 | +$6,289 |

**Best config selected:** `bars=3 stop=0.8`

| Metric | Value |
|---|---|
| OOS P&L (Apr 2026, selected config) | +$359 |
| Oracle P&L (Apr 2026, best sweep) | +$1,477 |
| Oracle config | bars=1 (9:35) stop=0.9 |
| Efficiency ratio | **0.243** |

---

### Step 5 — Train: Nov 2025–Apr 2026 → Test: May 2026 YTD

**Training top-5 (Nov 2025–Apr 2026):**

| Rank | Bars | Entry | Stop% | Train P&L |
|---|---|---|---|---|
| #1 ← selected | 3 | 9:45 | 0.8 | +$5,927 |
| #2 | 3 | 9:45 | 0.7 | +$5,536 |
| #3 | 3 | 9:45 | 0.4 | +$5,523 |
| #4 | 3 | 9:45 | 0.9 | +$5,475 |
| #5 | 3 | 9:45 | 0.6 | +$5,139 |

**Best config selected:** `bars=3 stop=0.8`

| Metric | Value |
|---|---|
| OOS P&L (May 2026 YTD, selected config) | +$682 |
| Oracle P&L (May 2026 YTD, best sweep) | +$1,432 |
| Oracle config | bars=10 (10:20) stop=0.9 |
| Efficiency ratio | **0.476** |

---

## All-Window Comparison

| Step | Test | 2mo Selected | 2mo OOS | 3mo Selected | 3mo OOS | 6mo Selected | 6mo OOS | Oracle |
|---|---|---|---|---|---|---|---|---|
| — | Jan 2026 | — | — | — | — | bars=7 s=0.3 | +$460 | +$2,538 |
| 1 | Feb 2026 | bars=10 s=1.0 | +$1,840 | bars=10 s=1.0 | +$1,840 | bars=3 s=0.8 | +$2,867 | +$3,445 |
| 2 | Mar 2026 | bars=3 s=0.8 | +$370 | bars=2 s=0.7 | +$476 | bars=3 s=0.8 | +$370 | +$1,778 |
| 3 | Apr 2026 | bars=3 s=0.4 | +$410 | bars=3 s=0.8 | +$359 | bars=3 s=0.8 | +$359 | +$1,477 |
| 4 | May 2026 | bars=1 s=0.6 | +$180 | bars=1 s=0.6 | +$180 | bars=3 s=0.8 | +$682 | +$1,432 |
| **Total (same 4mo)** | | | **+$2,800** | | **+$2,855** | | **+$4,278** | **+$8,132** |
| **Efficiency** | | | **0.344** | | **0.351** | | **0.527** | |

*6-month totals above use only the 4 overlapping test months (Feb–May) for apples-to-apples comparison. Full 5-month total: $+4,738, efficiency 0.444 (oracle $+10,670).*

---

## 6-Month Findings

### Significantly better: 0.527 efficiency on shared months (vs 0.344 / 0.351)

The 6-month window is the first meaningful improvement. On the same 4 test months (Feb–May),
it captures $4,278 vs $2,800 for 2-month — a 53% increase in OOS P&L.

### Config stability — bars=3 s=0.8 locks in

Steps 2–5 all select `bars=3 stop=0.8` with strong consensus in the top-5:
- Step 3: all top-5 are bars=3 (strong agreement)
- Step 4: all top-5 are bars=3 (unanimous)
- Step 5: all top-5 are bars=3 (unanimous)

This is a complete reversal from the 2/3-month pattern where the config flipped every step.
The longer window suppresses month-to-month noise and identifies bars=3 as the dominant
regime over Jul 2025–Apr 2026.

### Feb 2026 efficiency jumps to 0.832

The 6-month window selects `bars=3 s=0.8` for Feb 2026, capturing $2,867 — vs $1,840 from
the 2/3-month window which selected `bars=10 s=1.0`. The Jul–Dec 2025 trending period
(heavily bars=3 dominant) is what tips the training winner to bars=3 for the first time.

### Mar/Apr 2026 remain weak despite config stability

Even with bars=3 s=0.8 consistently selected, Mar (0.208) and Apr (0.243) efficiency stays
low. The oracle configs for those months are bars=8 and bars=1 respectively — the opposite
ends of the spectrum. This confirms that Mar/Apr 2026 (tariff shock, high VIX) represent a
genuine regime break that no trailing-window method can predict from the prior trending regime.

### May 2026 jumps from 0.126 to 0.476

The same `bars=3 s=0.8` config captures $682 in May vs $180 from the shorter windows. May
2026 is closer to the bars=3 regime than the choppy Mar/Apr, so the stable selection pays off.

### Step 1 (Jan 2026) weak — regime mismatch

Jul–Dec 2025 training selected `bars=7 s=0.3` — the Jul–Oct 2025 period is very different from
the Jan 2026 trending regime. Jan oracle (bars=10) is at the long end; bars=7 partially captures
this but efficiency is only 0.181. The 2H-2025 training set is mixed (choppy summer + trending
Nov–Dec), making the winner noisy.

### Conclusions

1. **6-month window is meaningfully better** than 2/3-month for stable, trending regimes —
   efficiency 0.527 vs 0.344–0.351 on the same test months.
2. **Config stability improves dramatically** — bars=3 s=0.8 wins Steps 2–5 with near-unanimous
   top-5 consensus. Longer lookback reduces overfitting to short-term regime noise.
3. **Regime breaks (Mar/Apr 2026 tariff shock) remain unpredictable** from any trailing window —
   this is an irreducible risk that requires real-time regime detection (VIX / MA alignment).
4. **Practical recommendation:** use 6-month training as the default selection window;
   supplement with VIX ≥ 22 override (switch to shorter OR / tighter stop) from the regime
   correlation analysis.
5. **bars=3 s=0.8 (entry 9:45, stop 80% of OR range) is the emerging all-weather default**
   for the current 2025–2026 regime.
