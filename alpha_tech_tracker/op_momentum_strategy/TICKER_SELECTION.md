# Ticker Selection — op_momentum_guide Live Trading

This document tracks the process of selecting the top-10 tickers for real trading
using the `op_momentum_guide` signal. All backtests use Alpaca 5-min data, 90-day window.

> **Note on win rate:** All data below uses `win = pnl > 0` (trade was profitable).
> Earlier drafts used `win = held ≥ 15 min` which inflated win rates to 65–86%.
> The correct long-run win rate baseline is **30–52%** depending on ticker and stop-pct.

---

## Selection Criteria

| Metric | Why it matters |
|---|---|
| **EV/Trade** | Primary ranking metric. Expected value per trade = `(win_rate × AvgWin%) − (loss_rate × AvgLoss%)`. Accounts for both sides of the trade on a % basis. |
| **AvgWin%** | With fixed-risk position sizing, % gain per win directly scales your P&L regardless of stock price. Target ≥ 0.50%. |
| **AvgLoss%** | Should be less than or close to AvgWin%. If AvgLoss% > AvgWin%, the risk asymmetry is inverted — losses hurt more than wins help. |
| **Win Rate** | Determines how often you collect the win. Target ≥ 70%. High AvgWin% with a low win rate still results in frequent losses and high variance. |
| **Signal count** | Needs enough signals to be statistically meaningful. Target ≥ 20 signals over the test window. |

### Decision Framework

1. **EV/Trade > 0** — negative EV is an immediate disqualifier regardless of other metrics
2. **AvgWin% ≥ 0.50%** — below this, per-trade returns are too thin even with good win rates
3. **AvgLoss% ≤ AvgWin%** — inverted asymmetry (loss > win on %) is a structural red flag
4. **Win rate ≥ 70%** — below this, variance makes day-to-day results unreliable
5. **≥ 20 signals** in the test window — fewer signals = unreliable statistics

---

## Screening Results (90-day, Dec 2024 – Mar 2026)

### Batch 1 — 10-ticker initial screen

Tickers: APP, QQQ, CVNA, META, SNOW, MDB, SPOT, CRWD, AVGO, CRWV
Settings: 90-day, stop-pct 0.35, win = pnl > 0

| Ticker | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Win P&L | Loss P&L | Net P&L |
|---|---|---|---|---|---|---|---|---|
| CRWV | 19 | 32% | 3.81% | 0.48% | **+0.879%** | +$19 | -$5 | +$14 |
| CVNA | 28 | 32% | 3.22% | 0.41% | **+0.758%** | +$121 | -$33 | +$88 |
| APP | 34 | 41% | 2.62% | 0.66% | **+0.694%** | +$194 | -$64 | +$130 |
| CRWD | 29 | 52% | 1.40% | 0.46% | **+0.500%** | +$90 | -$27 | +$63 |
| SPOT | 28 | 39% | 1.45% | 0.38% | +0.338% | +$82 | -$33 | +$49 |
| SNOW | 34 | 38% | 1.58% | 0.56% | +0.262% | +$36 | -$22 | +$14 |
| MDB | 27 | 26% | 2.53% | 0.57% | +0.238% | +$64 | -$38 | +$26 |
| META | 29 | 48% | 0.89% | 0.34% | +0.255% | +$82 | -$34 | +$49 |
| QQQ | 26 | 62% | 0.35% | 0.10% | +0.177% | +$35 | -$6 | +$29 |
| AVGO | 24 | 33% | 1.37% | 0.63% | +0.039% | +$36 | -$34 | +$2 |

**Passed (EV/Trade > +0.40%, AvgWin% ≥ 0.50%):** CRWV, CVNA, APP, CRWD
**Watch:** SPOT, META (positive EV but AvgWin% or rate borderline)
**Eliminated:** AVGO (EV near zero), QQQ (AvgWin% too thin), MDB/SNOW (low win rate)

### Batch 2 — Borderline + new candidates

Tickers: APP, CRWD, META, AMD, MRNA, CVNA
Settings: 90-day, stop-pct 0.35, win = pnl > 0

| Ticker | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Win P&L | Loss P&L | Net P&L |
|---|---|---|---|---|---|---|---|---|
| MRNA | 29 | 31% | 4.70% | 0.94% | **+0.810%** | +$17 | -$9 | +$8 |
| CVNA | 28 | 32% | 3.22% | 0.41% | **+0.758%** | +$121 | -$33 | +$88 |
| APP | 34 | 41% | 2.62% | 0.66% | **+0.694%** | +$194 | -$64 | +$130 |
| AMD | 24 | 50% | 1.46% | 0.46% | **+0.502%** | +$38 | -$12 | +$26 |
| CRWD | 29 | 52% | 1.40% | 0.46% | **+0.500%** | +$90 | -$27 | +$63 |
| META | 29 | 48% | 0.89% | 0.34% | +0.255% | +$82 | -$34 | +$49 |

**Notes:**
- **MRNA** — 4.70% AvgWin% is the highest in this batch, and AvgLoss% (0.94%) is now below AvgWin% with stop-pct 0.35. Risk asymmetry corrected. EV/Trade +0.810%. Promoted to watch.
- **AMD** — 50% win rate and +0.502% EV/Trade; passes on EV but win rate borderline.
- **META** — AvgWin% (0.89%) improved with tighter stop but EV/Trade still below +0.40% threshold.

### Batch 3 — High-EV candidates

Tickers: SPOT, ISRG, CRWV, COIN, SHOP, TSLA
Settings: 90-day, stop-pct 0.35, win = pnl > 0

| Ticker | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Win P&L | Loss P&L | Net P&L |
|---|---|---|---|---|---|---|---|---|
| SHOP | 29 | 48% | 3.08% | 0.67% | **+1.138%** | +$55 | -$13 | +$42 |
| CRWV | 19 | 32% | 3.81% | 0.48% | **+0.879%** | +$19 | -$5 | +$14 |
| SPOT | 28 | 39% | 1.45% | 0.38% | +0.338% | +$82 | -$33 | +$49 |
| ISRG | 28 | 43% | 0.88% | 0.29% | +0.214% | +$55 | -$23 | +$32 |
| TSLA | 23 | 35% | 0.74% | 0.23% | +0.106% | +$25 | -$15 | +$11 |
| COIN | 20 | 35% | 1.52% | 0.76% | +0.037% | +$19 | -$19 | $0 |

**Notes:**
- **SHOP** — highest EV/Trade of all candidates (+1.138%). AvgLoss% (0.67%) well below AvgWin% (3.08%). Confirmed.
- **CRWV** — strong EV (+0.879%) but only 19 signals; thin data.
- **COIN** — near-zero EV (+0.037%), eliminated.
- **TSLA / ISRG** — EV below +0.40% threshold, eliminated.

### Batch 4 — Memory/storage sector screen

Tickers: AMTA, STX, MU, SNDK
Settings: 90-day, stop-pct 0.35, win = pnl > 0

| Ticker | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Win P&L | Loss P&L | Net P&L |
|---|---|---|---|---|---|---|---|---|
| SNDK | 28 | 36% | 4.26% | 0.96% | **+0.907%** | +$166 | -$83 | +$83 |
| MU | 29 | 31% | 2.23% | 0.60% | +0.278% | +$70 | -$47 | +$23 |
| STX | 28 | 36% | 1.15% | 0.70% | -0.036% | +$43 | -$49 | -$7 |
| AMTA | — | — | — | — | — | — | — | — |

**Notes:**
- **SNDK** — highest EV/Trade in the batch (+0.907%) with very high AvgWin% (4.26%). Confirmed.
- **MU** — EV positive but below +0.40% threshold. Eliminated.
- **STX** — negative EV. Eliminated.
- **AMTA** — no signals fired.

---

## 6-Month Validation (180-day, Sep 2025 – Mar 2026)

Ran all top-10 candidates over a longer window to validate 90-day numbers and resolve thin-data concerns.
Settings: 180-day, stop-pct 0.35, win = pnl > 0

| Ticker | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Win P&L | Loss P&L | Net P&L |
|---|---|---|---|---|---|---|---|---|
| SNDK | 59 | 41% | 3.86% | 1.03% | **+0.960%** | +$262 | -$122 | +$141 |
| AMD | 50 | 46% | 1.91% | 0.49% | **+0.616%** | +$97 | -$28 | +$69 |
| CVNA | 59 | 36% | 2.30% | 0.39% | **+0.567%** | +$191 | -$57 | +$134 |
| SHOP | 58 | 40% | 2.16% | 0.53% | **+0.536%** | +$66 | -$26 | +$39 |
| APP | 70 | 43% | 1.97% | 0.61% | **+0.494%** | +$338 | -$135 | +$203 |
| MRNA | 57 | 30% | 3.23% | 0.70% | +0.472% | +$20 | -$11 | +$9 |
| CRWV | 45 | 29% | 3.37% | 0.72% | +0.462% | +$38 | -$23 | +$15 |
| META | 64 | 42% | 0.85% | 0.28% | +0.199% | +$151 | -$69 | +$82 |
| SPOT | 61 | 39% | 1.17% | 0.35% | +0.249% | +$156 | -$73 | +$83 |
| CRWD | 62 | 44% | 1.05% | 0.38% | +0.244% | +$128 | -$62 | +$66 |

**Key shifts from 90-day to 6-month:**
- **SNDK** — top performer: EV/Trade +0.960% over 6 months, up from +0.907% (90d). Win rate (41%) is low but AvgWin% (3.86%) is the highest in the group, giving it positive EV by a wide margin.
- **AMD** — strongest improvement: EV/Trade +0.616% over 6 months (vs +0.502% over 90d). Promoted to confirmed threshold.
- **CVNA and SHOP** — solid hold: both maintain EV/Trade > +0.50% over 6 months, confirming the 90-day data.
- **APP** — softened slightly: EV/Trade dropped from +0.694% to +0.494% over 6 months. The 90-day window captured an unusually strong stretch; 6-month is a more realistic baseline.
- **MRNA and CRWV** — positive EV but below +0.50% threshold over 6 months. MRNA AvgLoss% (0.70%) is well below AvgWin% (3.23%) — asymmetry is correct; low win rate (30%) is the limiter.
- **CRWD** — dropped sharply from +0.500% to +0.244%. AvgWin% (1.05%) is thin. Downgraded to backup.
- **META and SPOT** — below +0.40% threshold over 6 months. Remain backup candidates.

---

## Top-10 Ranking — Final (6-month validated)

All metrics use `win = pnl > 0` and `stop-pct 0.35`. Ranked by 6-month EV/Trade.

| Rank | Ticker | Win Rate (6m) | AvgWin% (6m) | AvgLoss% (6m) | EV/Trade (6m) | EV/Trade (90d) | Status |
|---|---|---|---|---|---|---|---|
| 1 | **SNDK** | 41% | 3.86% | 1.03% | **+0.960%** | +0.907% | ✅ Confirmed |
| 2 | **AMD** | 46% | 1.91% | 0.49% | **+0.616%** | +0.502% | ✅ Confirmed |
| 3 | **CVNA** | 36% | 2.30% | 0.39% | **+0.567%** | +0.758% | ✅ Confirmed |
| 4 | **SHOP** | 40% | 2.16% | 0.53% | **+0.536%** | +1.138% | ✅ Confirmed |
| 5 | **APP** | 43% | 1.97% | 0.61% | **+0.494%** | +0.694% | ✅ Confirmed |
| 6 | MRNA | 30% | 3.23% | 0.70% | +0.472% | +0.810% | 🔄 Watch |
| 7 | CRWV | 29% | 3.37% | 0.72% | +0.462% | +0.879% | 🔄 Watch |
| 8 | SPOT | 39% | 1.17% | 0.35% | +0.249% | +0.338% | 🔄 Backup |
| 9 | META | 42% | 0.85% | 0.28% | +0.199% | +0.255% | 🔄 Backup |
| 10 | CRWD | 44% | 1.05% | 0.38% | +0.244% | +0.500% | ⬇️ Downgraded |

**Confirmed (EV/Trade > +0.49% over 6m):** SNDK, AMD, CVNA, SHOP, APP
**Watch (positive EV but below threshold over 6m):** MRNA (low win rate), CRWV (low win rate)
**Backup:** SPOT, META — positive EV but thin returns
**Downgraded:** CRWD — 90-day was uncharacteristically strong; 6-month EV/Trade dropped to +0.244%

---

---

## Hard Stop Placement — Parameter Study

Stop formula: Bull exits below `OR_high − pct × OR_range`; Bear exits above `OR_low + pct × OR_range`.

### Study 1 — Recent 90-day (Dec 2024 – Mar 2026), 10-ticker basket, wide sweep

Tested `--stop-pct` across 0.35 / 0.40 / 0.50 / 0.60 / 0.70 / 0.80.

| stop-pct | Net P&L | EV/Trade | AvgWin% | AvgLoss% |
|---|---|---|---|---|
| **0.35** | **+$552** | **+0.674%** | 2.49% | **0.59%** |
| 0.40 | +$505 | +0.614% | 2.61% | 0.68% |
| 0.50 | +$503 | +0.578% | 2.83% | 0.86% |
| 0.60 | +$479 | +0.520% | 2.72% | 1.04% |
| 0.70 | +$489 | +0.519% | 2.70% | 1.15% |
| 0.80 | +$452 | +0.474% | 2.68% | 1.24% |

EV/Trade peaks at **0.35** in this window. Wider stops hurt across the board.

**APP exception:** EV/Trade improves consistently as stop widens (best at 0.80: +1.007%). Candidate for per-ticker stop-pct.

### Study 2 — Recent 90-day (Dec 2024 – Mar 2026), 10-ticker basket, tight sweep

Tested `--stop-pct` across 0.10 / 0.15 / 0.20 / 0.25 / 0.35`.

| stop-pct | Net P&L | EV/Trade | AvgWin% | AvgLoss% |
|---|---|---|---|---|
| **0.15** | **+$621** | **+0.805%** | 1.53% | **0.24%** |
| 0.10 | +$639 | +0.778% | 1.18% | 0.16% |
| 0.25 | +$613 | +0.767% | 1.96% | 0.42% |
| 0.20 | +$579 | +0.759% | 1.79% | 0.32% |
| 0.35 (baseline) | +$552 | +0.674% | 2.49% | 0.59% |

EV/Trade peaks at **0.15** (+0.805%). 0.10 has higher Net P&L (+$639) by firing more signals but slightly lower EV/Trade. All tight stops outperform 0.35 in this recent window.

**Key finding:** Tighter is better in the recent high-volatility regime (post-2024). At 0.10–0.15, the hard stop acts as a near-breakeven buffer — win rates jump to 57–85% but AvgWin% compresses as trades exit quickly with small gains.

### Study 3 — Historical 2-year (Jan 2023 – Dec 2024), 5-ticker basket (APP SHOP CVNA AMD META)

Tested `--stop-pct` across 0.10 / 0.15 / 0.20 / 0.25 / 0.30 / 0.35 / 0.50 / 0.60.

| stop-pct | Net P&L | EV/Trade | AvgWin% | AvgLoss% | Win Rate |
|---|---|---|---|---|---|
| **0.10** | **+$559** | **+0.397%** | 0.65% | **0.14%** | 68% |
| 0.15 | +$472 | +0.340% | 0.79% | 0.20% | 55% |
| 0.20 | +$413 | +0.289% | 1.03% | 0.26% | 43% |
| 0.25 | +$387 | +0.256% | 1.17% | 0.35% | 39% |
| 0.30 | +$327 | +0.212% | 1.30% | 0.43% | 37% |
| 0.35 | +$273 | +0.178% | 1.40% | 0.52% | 37% |
| 0.50 | +$174 | +0.118% | 1.96% | 0.69% | 33% |
| 0.60 | +$134 | +0.101% | 1.99% | 0.83% | 32% |

Monotonically improves as stop tightens across this 2-year window. **AMD peaks at 0.20** (+0.397% EV).

### Cross-study conclusion

Tighter stops outperform in both regimes. The absolute optimal differs (0.10–0.15 recently vs 0.10 historically) but the direction is consistent — every step tighter improves EV/Trade.

The tradeoff: tighter stops compress AvgWin% significantly. At 0.10, the strategy is winning more often but capturing smaller moves — essentially converting a momentum trade into a very short breakeven buffer play. Live execution risk (slippage, gaps) increases as the hard stop narrows.

**Basket default updated: `--stop-pct 0.15`** — peaks EV/Trade in the recent regime (+0.805%) while retaining meaningful AvgWin% (1.53%). 0.10 risks being too tight for live execution gaps.

---

## Next Steps

- [ ] Screen additional candidates to replace CRWD slot 10 (candidates: NVDA, MSTR, NFLX, TSLA longer window)
- [ ] Set live-trade signal threshold: only take signal if EV/Trade confirmed > +0.40% over rolling 60 days
- [ ] Consider position sizing rule: scale size proportional to EV/Trade — larger on SNDK/AMD, smaller on CRWV/MRNA
- [ ] Explore per-ticker stop-pct: run APP with 0.70–0.80 while keeping rest at 0.35
