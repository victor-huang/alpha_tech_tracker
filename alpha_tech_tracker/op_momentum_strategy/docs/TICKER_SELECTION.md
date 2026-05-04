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

### Batch 5 — Non-tech sector screen (Q1 2026 rotation candidates)

Tickers: HOOD, BNTX, VRT, OXY, EXPE, AA
Settings: 90-day (Dec 2025 – Mar 2026), stop-pct 0.15, win = pnl > 0

| Ticker | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Win P&L | Loss P&L | Net P&L |
|---|---|---|---|---|---|---|---|---|
| EXPE | 29 | 45% | 1.97% | 0.21% | **+0.770%** | +$65 | -$9 | +$57 |
| AA | 31 | 55% | 0.89% | 0.35% | +0.327% | +$9 | -$3 | +$6 |
| OXY | 34 | 56% | 0.55% | 0.21% | +0.215% | +$5 | -$2 | +$3 |
| HOOD | 28 | 36% | 1.07% | 0.30% | +0.187% | +$9 | -$5 | +$4 |
| VRT | 33 | 48% | 0.57% | 0.19% | +0.179% | +$19 | -$7 | +$11 |
| BNTX | 20 | 50% | 0.55% | 0.23% | +0.159% | +$6 | -$2 | +$4 |

**Notes:**
- **EXPE** — standout result: EV/Trade +0.770% beats most confirmed tech tickers. AvgLoss% (0.21%) is extremely tight; AvgWin% (1.97%) provides strong asymmetry. 120-min avg hold on wins confirms follow-through. Promoted to watch.
- **AA** — bull signal strong (15/18 = 83%) but bear signal broken (2/13 = 15%). Regime-dependent; eliminated for now.
- **HOOD, OXY, VRT, BNTX** — positive EV but all below +0.40% threshold. Eliminated.

### Batch 6 — Q1 2026 sector rotation leaders (Energy / Materials / Industrials)

Motivation: Q1 2026 marked a clear rotation out of tech into Energy (+21–25% YTD), Materials (+17.9%), and Industrials (+14–16%). Screened high-beta sector leaders across both 90-day and 365-day windows.

Tickers: GEV, HWM, FCX, VLO, FANG, MPC, DVN
Settings: 90-day (Dec 2025 – Mar 2026) and 365-day (Mar 2025 – Mar 2026), stop-pct 0.15, win = pnl > 0

#### 90-day results

| Ticker | Sector | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Net P&L |
|---|---|---|---|---|---|---|---|
| FANG | Energy/E&P | 27 | 63% | 0.59% | 0.28% | +0.269% | +$12 |
| VLO | Energy/Refining | 29 | 55% | 0.57% | 0.20% | +0.225% | +$13 |
| FCX | Materials/Copper | 31 | 42% | 0.67% | 0.15% | +0.191% | +$4 |
| GEV | Industrials/Power | 31 | 42% | 0.69% | 0.19% | +0.180% | +$47 |
| MPC | Energy/Refining | 28 | 50% | 0.44% | 0.19% | +0.121% | +$7 |
| HWM | Industrials/Aerospace | 33 | 39% | 0.49% | 0.23% | +0.055% | +$3 |
| DVN | Energy/E&P | 29 | 52% | 0.27% | 0.25% | +0.021% | +$0 |

#### 365-day results

| Ticker | Sector | Signals | Win Rate | AvgWin% | AvgLoss% | EV/Trade | Net P&L | Bull% | Bear% |
|---|---|---|---|---|---|---|---|---|---|
| FANG | Energy/E&P | 112 | 50% | 0.73% | 0.18% | **+0.279%** | +$45 | 58% | 38% |
| GEV | Industrials/Power | 132 | 43% | 0.89% | 0.20% | **+0.273%** | +$207 | 53% | 18% |
| DVN | Energy/E&P | 126 | 49% | 0.70% | 0.16% | **+0.263%** | +$11 | 53% | 43% |
| VLO | Energy/Refining | 121 | 52% | 0.65% | 0.17% | **+0.259%** | +$45 | 62% | 36% |
| FCX | Materials/Copper | 113 | 38% | 0.60% | 0.15% | +0.133% | +$8 | 56% | 16% |
| MPC | Energy/Refining | 130 | 45% | 0.46% | 0.13% | +0.137% | +$30 | 58% | 27% |
| HWM | Industrials/Aerospace | 133 | 44% | 0.33% | 0.16% | +0.057% | +$14 | 55% | 18% |

**Notes:**
- **FANG** — most balanced signal across bull and bear (58%/38%) over 365 days. Only ticker in this batch with reliable bearish follow-through. EV/Trade +0.279% over 365d. Added to candidate list for further validation.
- **GEV** — large dollar P&L (+$207) driven by high stock price (~$500–$890 range). EV/Trade +0.273% over 365d. Bear signal structurally weak (18%) — essentially a bull-only play. Added to candidate list for further validation.
- **VLO** — strong bull signal (62%) over 365d; bear side improving (36%) with longer window. Positive EV but below threshold; eliminated for now.
- **DVN** — best bear signal in batch (43% over 365d). Low stock price compresses dollar P&L. EV/Trade +0.263%. Eliminated for now.
- **FCX, MPC, HWM** — below threshold; eliminated.

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
**Watch (positive EV but below threshold over 6m):** MRNA (low win rate), CRWV (low win rate), EXPE (90d only — needs 6m validation), FANG (365d +0.279% — needs threshold run), GEV (365d +0.273% — bull-only, needs bear filter study)
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
- [ ] Run EXPE 6-month validation (180-day) — 90d EV/Trade +0.770% is strong; needs longer window confirmation
- [ ] Run FANG 6-month validation and tighter stop-pct sweep (0.10) — 365d EV/Trade +0.279%; closest non-tech/energy candidate to threshold
- [ ] Investigate GEV bull-only filter — 365d bear success 18% drags EV/Trade; test with bearish signals disabled or --bearish-ma200 to see if bull-only EV/Trade clears +0.40%

---

## Selector Portfolio Backtests — op_momentum_selector

The sections below cover **portfolio-level** results from `op_momentum_selector_backtest.py`, which scores and ranks all tickers daily, picks the top-3 by rolling EV gate + scoring formula, and simulates capital compounding ($10,000 / 3 slots = $3,333 per position).

### Ticker Universe

**Original 8:** SNDK, APP, SHOP, CVNA, AMD, META, EXPE, FANG

**Expanded 13 (current DEFAULT_TICKERS):** adds ISSC, FN, UI, MU, ANAB — selected after screening two custom batches over the 90-day window (Dec 2025 – Mar 2026).

Custom batch ranking that identified the additions (total P&L%, 90d):

| Ticker | Total P&L% | Win Rate | Notes |
|--------|-----------|----------|-------|
| ISSC | +23.92% | 62% | Top performer, high win rate |
| FN | +21.40% | 53% | Strong momentum |
| UI | +14.15% | 40% | Consistent |
| MU | +12.47% | 38% | Memory sector |
| ANAB | +9.52% | 45% | Biotech volatility |

---

### MA20 Trailing Stop Logic

Added to `op_momentum_backtest.py` (`compute_signals_with_backtest`).

**BULLISH:** once `MA20 > hard_stop_price` (= `OR_high − stop_pct × OR_range`), the trade exits if `Close < MA20`. This only activates when MA20 has risen above the safety floor, confirming the uptrend is real before locking in profit.

**BEARISH:** once `MA20 < OR_low`, the trade exits if `Close > MA20`. Uses `OR_low` (not `hard_stop_price`) as the threshold because `hard_stop = OR_low + stop_pct × OR_range` is above the entry — triggering on MA20 < hard_stop would fire before the trade is in profit.

Exit priority order: `hard_stop` → `fallback_20pct` → `trailing_stop_ma20` → `trailing_stop_ma50` → `end_of_day`

Controlled via `--trailing-ma {ma20 | ma50 | both}` (default: `both`).

---

### Full-Year Results 2021–2025 (13 tickers, stop-pct 0.15, --trailing-ma ma20)

Log files: `back_test_result/selector_bt_{year}_ma20.log`

| Year | Strategy Return | Final Portfolio | QQQ Return | Alpha vs QQQ | Win Rate | Avg Win | Avg Loss | EV/Trade |
|------|----------------|-----------------|-----------|--------------|----------|---------|----------|----------|
| 2021 | **+55.57%** | $15,556.87 | +28.50% | +27.1pp | 31% | +1.39% | -0.29% | +0.234% |
| 2022 | **+97.61%** | $19,760.54 | -33.68% | +131.3pp | 35% | +2.03% | -0.42% | +0.436% |
| 2023 | **+50.02%** | $15,001.69 | +54.81% | -4.8pp | 31% | +1.37% | -0.32% | +0.212% |
| 2024 | **+27.65%** | $12,764.55 | +26.98% | +0.7pp | 31% | +1.04% | -0.28% | +0.125% |
| 2025 | **+72.68%** | $17,268.36 | +20.36% | +52.3pp | 36% | +1.55% | -0.38% | +0.310% |

**5-year compound (sequential):** $10K × 1.5557 × 1.9761 × 1.5002 × 1.2765 × 1.7268 ≈ **$99,900** (~10× in 5 years)

---

### Past 90 Days (Dec 23 2025 – Mar 23 2026, stop-pct 0.15, --trailing-ma ma20)

Log file: `back_test_result/selector_bt_90d_ma20.log`

| Metric | Value |
|--------|-------|
| Strategy return | **+38.86%** |
| Final portfolio | $13,885.70 |
| QQQ return | -5.45% |
| Alpha vs QQQ | **+44.3pp** |
| Trades | 180 (73W / 107L) |
| Win rate | 41% |
| Avg win | +2.25% |
| Avg loss | -0.44% |
| EV/trade | **+0.648%** |

The past 90 days show the strongest EV/trade (+0.648%) of any period tested, driven by the volatile tariff selloff environment where OR breakouts produced extended directional moves.

---

### MA20 vs No Trailing Stop — Head-to-Head (stop-pct 0.15)

| Year | No trailing MA | MA20 stop | Δ |
|------|--------------|-----------|---|
| 2021 | +35.95% | **+55.57%** | +19.6pp |
| 2022 | +77.36% | **+97.61%** | +20.2pp |
| 2023 | **+69.06%** | +50.02% | -19.0pp |
| 2024 | +26.92% | **+27.65%** | +0.7pp |
| 2025 | +68.95% | **+72.68%** | +3.7pp |

MA20 trailing stop wins in 4 of 5 years. The exception is 2023 — a slow, grinding bull market where MA20 was triggered too early on winning trades before the full trend developed. MA20 adds most value in high-volatility trending years (2021: +19.6pp, 2022: +20.2pp) where it lets winners run while cutting fast when momentum stalls.

---

### Ticker Universe Comparison (90-day + 15-month, stop-pct 0.15, no trailing MA)

| Period | Orig 8 Return | Expanded 13 Return | QQQ | Winner |
|--------|--------------|-------------------|-----|--------|
| 90 days (Dec 25 – Mar 26) | +36.86% | **+47.57%** | -6.00% | 13 (+10.7pp) |
| 15 months (Jan 25 – Mar 26) | +114.04% | **+137.05%** | +14.08% | 13 (+23.0pp) |

Full-year head-to-head (stop-pct 0.15, no trailing MA):

| Year | Orig 8 | Expanded 13 | Winner |
|------|--------|-------------|--------|
| 2021 | +35.61% | +35.95% | 13 (+0.3pp) |
| 2022 | +71.65% | **+77.36%** | 13 (+5.7pp) |
| 2023 | +56.49% | **+69.06%** | 13 (+12.6pp) |
| 2024 | **+31.02%** | +26.92% | 8 (+4.1pp) |
| 2025 | +54.35% | **+68.95%** | 13 (+14.6pp) |

Expanded 13 wins in 4 of 5 years. 2024 is the only exception — the 5 added tickers (higher-beta small/mid caps) underperformed in the low-volatility 2024 melt-up.

---

## Annual Rotation Framework

### Why Backward-Looking Backtests Aren't Enough

The screening process above is validated — but it's backward-looking. It tells you a ticker was good over the past 90–180 days. It doesn't answer: *what would you have screened for on Jan 1 to know a ticker would work for the whole year?*

The answer is a set of observable, pre-backtest characteristics that strongly correlate with ORB strategy fit. These are the factors to evaluate before running a backtest on a new candidate.

---

### Pre-Backtest Quantitative Gates (Point-in-Time Screens)

These are computable from historical data at the start of any period — no backtest needed.

**1. Average Daily Range % (ADR%) — Most Important**

The entire strategy's edge is bounded by how much the stock moves intraday. The OR hard stop is 15% of the OR range — if the stock's daily range is narrow, the OR range is tiny and options premium costs eat all the edge.

- **Minimum: 60-day trailing ADR% > 3%**
- **Target: 4–8%** — the confirmed pool (SNDK, CVNA, APP, COIN, PLTR) all sit here
- **Rotation-out trigger: ADR% drops below 2.5% and holds there for 30+ trading days**

Academic basis: intraday continuation is strongest in stocks with high first-half-hour trading volume (Gao et al., 2018, JFE). High-volume opens produce wider OR ranges, which produce more meaningful ORB signals.

**2. Beta vs. QQQ > 1.5 (1-year trailing)**

High-beta names amplify directional market days — which is exactly when ORB signals are cleanest. The regime filter (QQQ MA8) captures *when* the market is trending; high beta captures *how much* a stock moves when it does.

- **Screen: 1-year trailing beta vs. QQQ > 1.5**
- Stocks with beta < 1.0 rarely form clean ORB patterns — this is why XOM, GLD, GDX, and most commodity ETFs consistently failed in sector screening

**3. Options Liquidity**

Since the strategy trades weekly options, not shares, execution quality gates:

- **Average daily options volume (6-month trailing) > 5,000 contracts/day**
- **Weekly ATM bid-ask spread < 3% of mid-price**
- Below 2,000 contracts/day: flag for watch; below 1,000: remove candidate

Smaller names (ISSC, FN, ANAB) may pass signal-level backtests but have execution friction in live trading. Verify options ADV before adding to the live pool.

**4. 52-Week High Proximity**

George & Hwang (2004) showed stocks near their 52-week high at the start of a period have +0.65%/month forward return alpha — persistent with no long-term reversal (unlike classic 12-month momentum which reverses at 3–5 years). The mechanism: when stocks finally break through the high, moves are sustained because prior resistance becomes support.

- **Prefer: current price within 15% of 52-week high**
- **Watchlist: 20–35% below 52-week high** — may still generate good bearish ORB signals
- **Rotation candidate: 35%+ below 52-week high with no fundamental catalyst**

**5. Short Interest 5–20% of Float**

The "squeeze potential" range. Enough trapped shorts to fuel follow-through on bullish OR breakouts (shorts stop out, amplifying the move), but not so high the stock is structurally broken.

- Below 3%: fewer trapped shorts → less acceleration on breakouts
- Above 30%: mean-reversion risk on failed signals is extreme

Explains COIN's behavior: high short interest → bearish signals drive pile-ons; bullish signals force covers. Both sides produce outsized moves.

**6. Prior Year Return in Top Quartile of Sector**

Classic momentum (Jegadeesh-Titman): stocks with the strongest prior 12-month returns have 3–12 month forward momentum. Stocks that finished the prior year in the top quartile of their sector are structurally more likely to generate clean ORB signals in the new year.

- **Screen: prior year return > +15% OR in top quartile of sector**
- Note: classic 12-month momentum reverses at 3+ years — the rolling 60-day EV gate in the selector handles this deterioration automatically

---

### Qualitative Criteria

**Sector Leadership**

Sector momentum persists 6–12 months (Mamais et al., 2025, Journal of Forecasting). At the start of each period, rank S&P sectors by 6-month relative strength vs. QQQ. Concentrate the pool in the top 2–3 sectors.

- 2021: Tech, Consumer Discretionary → APP, SHOP, CVNA
- 2022: Tech still worked via bearish signals in the downtrend
- 2024: Low-volatility melt-up → high-beta small caps (ISSC, ANAB) underperformed vs. larger tech
- Q1 2026: Energy, Materials rotation → FANG, GEV identified in sector screen

**"Trader Stock" Character**

High day-trader participation creates the crowd dynamics that amplify ORB continuation. Stocks with active fintwit/Reddit/Discord following tend to have more consistent ORB follow-through because retail traders entering after the OR closes amplify the move. Hard to quantify but observable — TSLA, PLTR, COIN, NVDA, APP all have this; FANG and ISSC are more episodic.

**Regular Catalyst Schedule**

Stocks with quarterly earnings that regularly produce large moves (±5%+ gap) demonstrate they can trend strongly on catalyst days — this correlates with trending on non-earnings ORB days (volatility clustering). Check the prior 4 quarters for large post-earnings gaps.

---

### Rotation-Out Signals

| Signal | Threshold | Action |
|---|---|---|
| ADR% contraction | 60-day ADR% drops >40% vs. prior-year average, holds 30+ days | Remove immediately |
| Rolling EV/trade | 60-day EV/trade drops below 0 for 20+ consecutive days | Remove (selector EV gate already handles daily) |
| Options liquidity | Options ADV below 2,000 contracts/day | Watch; remove below 1,000 |
| MA200 breakdown | Price below MA200 for 30+ consecutive days, no catalyst | Bearish-signals-only or remove |
| Sector RS decay | Stock's sector in bottom 2 by RS vs. QQQ for 8+ consecutive weeks | Flag for next quarterly review |
| Narrative collapse | Delisting risk, regulatory investigation, 3+ consecutive fundamental misses | Remove immediately |
| Beta decay | 60-day beta vs. QQQ drops below 1.0 | Watch; consider removing |

---

### Review Cadence: Quarterly Monitoring, Annual Structural Changes

The strategy already has two filtering layers operating at different timescales:

**Layer 1 — Daily (already automated):** The rolling 60-day EV gate in `op_momentum_selector.py` handles individual ticker performance decay automatically. If a ticker's EV/trade drops below 0, it gets gated out of the top-3 every day. No manual review needed for this layer.

**Layer 2 — Pool membership (what needs a cadence):** Which tickers are even in the candidate universe. This requires periodic review because the EV gate can't see ADR collapse, options illiquidity, or sector rotation until it's already reflected in backtest results — which lags reality by 30–60 days.

**Why not annual-only?** Evidence from this strategy's own data:
- CRWD degraded from +0.500% EV (90d) → +0.244% (6m) — within one quarter
- Q1 2026 energy/materials rotation was visible within 6–8 weeks of the year starting
- ADR contraction can occur in 4–6 weeks on individual names

**Quarterly Review (Jan, Apr, Jul, Oct):**
1. Run ADR% check on all pool tickers — flag any >30% below prior-year average
2. Check options ADV (6-month trailing) — flag below 5K contracts/day
3. Check sector relative strength — confirm pool is in the top 2–3 sectors
4. Screen 10–15 rotation candidates from gaining sectors through ADR/beta/options gates
5. Run 90-day backtest on candidates that pass the gates → add survivors to **rotation bench**
6. Remove immediately only on hard triggers: ADR collapse, options illiquidity, narrative event

**Annual Review (January):**
1. Make final add/remove decisions based on what quarterly flags surfaced
2. Run 6-month validation on any rotation bench candidates before promoting to live pool
3. Re-rank full pool by 1-year EV/trade to confirm ordering
4. Review sector allocation vs. leading sectors for the new year
5. Re-check ADR%, beta, and options ADV for all pool members against current-year thresholds
6. Recheck 52-week proximity for all pool members — flag structural laggards

**Immediate (event-driven, any time):**
- Delisting risk, regulatory action, reverse split, M&A announcement (target) → remove same day

**Key principle:** The quarterly review builds and maintains a **rotation bench** — candidates that have already passed the 90-day backtest screen and are ready to swap in. Without this bench, you're always 3–6 months behind sector rotations. When the annual review comes, you have validated candidates ready instead of names that still need testing.

---

## Pool Change Log

Tracks all additions and removals from `DEFAULT_TICKERS` with rationale and supporting backtest data.

| Date | Action | Ticker | Reason | 5-Year Δ |
|---|---|---|---|---|
| 2026-03-31 | **Removed** | UI | Alpaca returns only sparse extended-hours bars for UI (5 bars/day, all low-volume); no reliable morning session data. Backtest entry was firing at 3 PM instead of 9:45 AM, producing meaningless results. Data quality issue, not signal quality. | — |
| 2026-04-01 | **Added** | TSLA | 5-year backtest (2021–2026-03-31) with TSLA vs without: +10.9pp gain (+$1,090 on $10k). M1 window gained +8.3pp, A2 +4.3pp. High-beta, high-volatility ticker with clean OR breakout profile consistent with COIN and PLTR. | **+10.9pp** |
| 2026-04-01 | **Removed** | ISSC | Replaced by RH. ISSC is a thinly traded small-cap producing frequent `fallback_20pct` exits (no intraday momentum follow-through). Options ADV well below 5K threshold — execution friction in live trading. | — |
| 2026-04-01 | **Added** | RH | Swap test (-ISSC +RH) vs current pool: +19pp over 5 years (+$1,904 on $10k). M1 gained +20.5pp — largest single-window improvement of any ticker change tested. RH (Restoration Hardware) is a high-beta luxury retailer with strong OR breakout follow-through. All three windows improved. Baseline EV/trade improved from +0.276% → +0.288%. | **+19.0pp** |
| 2026-05-03 | **Removed** | RH | Confirmed non-Penny Pilot ticker — live orders rejected repeatedly with `required=0.10` tick. Using $0.05-increment limit prices caused exchange rejections and escalation latency in live trading. Replaced by JPM to eliminate execution friction. | — |
| 2026-05-03 | **Added** | JPM | Replaced RH due to RH's non-Penny Pilot tick issue. Screened 6 candidates (NFLX, AEM, AAPL, INTC, RTTD, JPM) over 2026 YTD (Jan–May) using the 4-window config (M1 09:30/3, A1 10:00/3, A2 13:15/1, A3 15:15/1), top-2, weights 60/40. JPM had negligible impact: -0.04pp vs RH on 2026 YTD (+122.71% vs +122.75%), and identical 5-year result (+117.95% both). JPM is Penny Pilot — no tick issues. INTC was the only candidate to edge RH (+122.92%, +0.17pp) but with a worse win rate (242W/300L vs 251W/291L), suggesting larger wins masking more frequent losses. JPM confirmed safe drop-in with zero 5-year P&L impact. Removed RH from `_NON_PENNY_PILOT_TICKERS` in `option_price_monitor.py`. | **~0pp** |

#### Candidate comparison (2026 YTD, RH replacement screen)

| Candidate | Total Return | vs RH | Notes |
|---|---|---|---|
| RH (baseline) | +122.75% | — | Non-Penny Pilot; live tick rejections |
| INTC | +122.92% | **+0.17pp** | Only candidate to beat RH; lower win rate (44.7%) offset by bigger wins |
| **JPM** | **+122.71%** | **-0.04pp** | Best overall: near-zero 2026 gap, identical 5-year, Penny Pilot ✅ |
| AAPL | +122.23% | -0.52pp | Strong Feb but weak Apr |
| RTTD | +121.76% | -0.99pp | — |
| NFLX | +121.74% | -1.01pp | — |
| AEM | +119.05% | -3.70pp | Worst of candidates |

### Current Pool (as of 2026-05-03) — 17 tickers

`SNDK, APP, SHOP, CVNA, AMD, META, EXPE, JPM, FN, MU, CRDO, PLTR, COIN, CLS, MSTR, CRWV, MRVL`
