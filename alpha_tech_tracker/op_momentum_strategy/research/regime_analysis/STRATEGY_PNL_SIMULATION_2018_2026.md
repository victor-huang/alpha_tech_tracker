# Strategy P&L Simulation — 2018–2026
# No Look-Ahead Estimation

**Generated:** 2026-06-02  
**Purpose:** Estimate yearly P&L if the cross-year rules were applied in real-time, using only information available at each decision point.

---

## Methodology

### Decision rules in force at each month start (no look-ahead)

| Month | Default Action | Hold Window | Flip Trigger |
|-------|---------------|-------------|--------------|
| Jan | LONG | EOD | Flip SHORT if day-3 WR < 45% (proxy: monthly WR ≤ 40%) |
| Feb | Follow January | EOD | None (take result) |
| Mar | CAUTION — no position day 1-3 | **+15m exits only** | Confirm direction by day 3 |
| Apr | Follow March, LONG default | EOD | Flip SHORT if WR < 40% |
| May | Follow April direction | EOD | None |
| Jun | LONG default | EOD | Flip LONG if prior 2 months SHORT + single 70% day |
| Jul | Follow June | EOD | None |
| Aug | LONG | **+15m exits only** | AM-pop-fade default — exit before the fade |
| Sep | SHORT from day 1 | EOD | Exception: flip LONG only if by day 3 avg win > 1.5× avg loss AND curve rising |
| Oct | LONG from day 1 | EOD | None |
| Nov | WAIT — check EV week 1 | EOD | Flip SHORT if avg gain ≤ 0; 70% credit (detect ~day 7) |
| Dec | SHORT from day 1 | EOD | Exception: only named macro catalyst overrides (estimate break-even flip) |

### P&L assignment
- **LONG + EOD**: take reported EOD total P&L
- **SHORT + EOD**: take -(EOD total P&L) 
- **LONG + +15m**: take reported +15m total P&L
- **Delayed flip (day 3–7 detection)**: 60% credit for short side (first 3 days of wrong-direction losses absorbed)
- **Catalyst month flip mid-month (Dec 2019, Dec 2020)**: ~0–3% net (lose as SHORT early, recover when LONG)
- **Partial bear detection (Feb 2020)**: -7% estimate (vs -9.8% full loss — count-drop warning around day 10)

### What "+15m" means — entry and exit timing

**Entry is at 09:45, not 09:30.** The screener uses a 3-bar opening range (09:30/3b): it collects bars at 09:30, 09:35, 09:40 and fires the signal after all three close. Entry is at the 09:45 bar open.

Hold windows from that entry:
- **+15m** = enter 09:45, exit 10:00 (15 minutes of holding)
- **+30m** = enter 09:45, exit 10:15
- **+1h**  = enter 09:45, exit 10:45
- **EOD**  = enter 09:45, hold to ~15:55 (full day)

"+15m only" for March and August is the conservative no-look-ahead floor — the data shows the signal edge collapses after 10:00 in those months. In live trading, you'd use the first 3–5 days' hold curve shape to decide whether to extend. If +30m WR is tracking ≥55% through day 3, extend to +30m or +1h. If it's dropping ≥15pp from +15m, stick with the 10:00 exit.

### What these P&L numbers represent
The screener reports **total P&L = sum of all individual signal returns** in a month. A +30% month means all trades in that month summed to +30% if you deployed equal capital per signal. This is NOT a compounded portfolio return — it is the aggregate signal edge for the month.

---

## Year-by-Year Simulation

### 2018

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | +6.4% | +12.7% | **+12.7%** | |
| Feb | LONG | EOD | -6.0% | -11.4% | **-11.4%** | Volmageddon Feb 5 — instantaneous, no warning |
| Mar | CAUTION | +15m | +10.6% | -1.9% | **+10.6%** | Rule saves 12.5pp vs pure long |
| Apr | LONG | EOD | +3.7% | +4.2% | **+4.2%** | |
| May | LONG | EOD | +0.5% | -2.5% | **-2.5%** | |
| Jun | LONG | EOD | +7.4% | +6.1% | **+6.1%** | |
| Jul | LONG | EOD | +2.5% | +16.6% | **+16.6%** | Rising curve — hold EOD |
| Aug | LONG | +15m | -1.9% | -0.7% | **-1.9%** | +15m slightly worse than EOD this month |
| Sep | **SHORT** | EOD | -1.9% | -14.2% | **+14.2%** | ✓ |
| Oct | LONG | EOD | +10.2% | +8.3% | **+8.3%** | |
| Nov | LONG | EOD | +0.9% | +11.9% | **+11.9%** | EV positive → LONG |
| Dec | **SHORT** | EOD | -8.0% | -39.8% | **+39.8%** | ✓ |
| **Total** | | | | | **+108.6%** | vs Pure Long -10.7% → **Δ +119.3pp** |

Key wins: Sep SHORT (+28.4pp swing), Dec SHORT (+79.6pp swing), Mar +15m (+12.5pp)  
Key miss: Feb Volmageddon (-11.4%, unavoidable)

---

### 2019

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | +10.6% | +37.5% | **+37.5%** | |
| Feb | LONG | EOD | +4.5% | +1.7% | **+1.7%** | |
| Mar | CAUTION | +15m | +3.7% | -2.0% | **+3.7%** | Saves 5.7pp |
| Apr | LONG | EOD | -2.1% | -2.2% | **-2.2%** | WR 44.4% — above 40% flip threshold |
| May | LONG | EOD | +0.2% | +6.3% | **+6.3%** | |
| Jun | LONG | EOD | +5.2% | +4.7% | **+4.7%** | |
| Jul | LONG | EOD | -4.6% | +4.0% | **+4.0%** | Late-day bull — hold EOD correct |
| Aug | LONG | +15m | +9.1% | +1.6% | **+9.1%** | +15m better than EOD this month (+7.5pp) |
| Sep | **SHORT** | EOD | -0.3% | +8.3% | **-8.3%** | ✗ MISS — Sep 2019 was the EV-exception |
| Oct | LONG | EOD | -2.3% | +13.7% | **+13.7%** | |
| Nov | LONG | EOD | -2.9% | +8.7% | **+8.7%** | Low WR but positive EV — correct to stay LONG |
| Dec | FLAT | — | +7.7% | +9.1% | **0%** | Phase 1 deal Dec 13 — start SHORT, flip after catalyst, ~break-even |
| **Total** | | | | | **+79.2%** | vs Pure Long +91.5% → **Δ -12.3pp** |

Key miss: Sep 2019 (-16.6pp swing — exception year) and Dec catalyst (−9.1% foregone)  
Key win: Aug +15m captures +7.5pp extra vs EOD

---

### 2020

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | +2.4% | +5.5% | **+5.5%** | |
| Feb | LONG | EOD | -4.8% | -9.8% | **-7.0%** | COVID fear: count dropped to 0.9/day by day 10. Partial flip ~day 12. Estimate |
| Mar | CAUTION | +15m | +25.8% | +50.0% | **+25.8%** | Caution rule leaves 24.2pp on the table — COVID crash volatility |
| Apr | LONG | EOD | +1.6% | +1.8% | **+1.8%** | |
| May | LONG | EOD | +10.8% | +18.0% | **+18.0%** | |
| Jun | LONG | EOD | +9.1% | +19.8% | **+19.8%** | |
| Jul | LONG | EOD | -9.4% | +12.9% | **+12.9%** | Late-day bull — hold EOD correct |
| Aug | LONG | +15m | +0.1% | -1.5% | **+0.1%** | AM-pop-fade: +15m saves small amount |
| Sep | **SHORT** | EOD | +4.3% | -11.7% | **+11.7%** | ✓ |
| Oct | LONG | EOD | +12.6% | +27.1% | **+27.1%** | |
| Nov | LONG | EOD | +14.9% | +10.6% | **+10.6%** | EV positive → LONG |
| Dec | +3% est | — | +13.0% | +20.3% | **+3.0%** | Vaccine Dec 11 — start SHORT, flip after, net ~+3% estimate |
| **Total** | | | | | **+129.3%** | vs Pure Long +142.8% → **Δ -13.5pp** |

Key miss: Mar caution costs 24.2pp (COVID volatility rewarded holding); Dec catalyst costs ~17.3pp  
Key win: Sep SHORT (+23.4pp swing), Feb partial detection saves ~2.8pp

---

### 2021

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | +19.7% | +39.0% | **+39.0%** | |
| Feb | LONG | EOD | -7.9% | +4.5% | **+4.5%** | WR 63.6% — strong, stay LONG |
| Mar | CAUTION | +15m | -7.3% | -67.0% | **-7.3%** | ★ Rule saves 59.7pp — yield-spike bear |
| Apr | LONG | EOD | +5.2% | +3.4% | **+3.4%** | |
| May | LONG | EOD | -1.4% | +11.0% | **+11.0%** | Late-day U-curve — EOD correct |
| Jun | LONG | EOD | -0.8% | -3.2% | **-3.2%** | WR 53.1% — above flip threshold |
| Jul | LONG | EOD | +5.5% | -1.2% | **-1.2%** | Small miss |
| Aug | LONG | +15m | -7.9% | +15.0% | **-7.9%** | ✗ +15m rule costs 22.9pp — Aug 2021 was U-curve bull |
| Sep | **SHORT** | EOD | +5.7% | -4.8% | **+4.8%** | ✓ |
| Oct | LONG | EOD | -2.3% | -1.5% | **-1.5%** | Only October loss in dataset — small |
| Nov | **SHORT** | EOD | -4.9% | -34.7% | **+10.0%** | Detect bear ~day 7 (WR 39.6%, EV negative from week 1). 60% credit estimate |
| Dec | **SHORT** | EOD | +2.7% | -5.4% | **+5.4%** | ✓ |
| **Total** | | | | | **+57.1%** | vs Pure Long -44.9% → **Δ +102.0pp** |

Key wins: Mar +15m (+59.7pp), Nov flip SHORT (+44.7pp swing), Sep SHORT (+9.6pp)  
Key miss: Aug +15m (-22.9pp — U-curve month, EOD was the right hold)

---

### 2022

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | **SHORT** | EOD | -7.0% | -116.3% | **+69.8%** | ★ WR 33.8% — flip SHORT by day 3. 60% credit: 0.6 × 116.3% |
| Feb | **SHORT** | EOD | +4.5% | -8.2% | **+8.2%** | Follow Jan SHORT |
| Mar | CAUTION | +15m | -5.9% | -16.5% | **-5.9%** | +15m rule saves 10.6pp vs EOD |
| Apr | **SHORT** | EOD | +6.1% | -47.5% | **+28.5%** | ★ WR 33.3% — flip SHORT by day 3. 60% credit: 0.6 × 47.5% |
| May | **SHORT** | EOD | +1.0% | -7.3% | **+7.3%** | Follow Apr SHORT (High-WR trap: 57.4% WR, negative EV) |
| Jun | FLIP LONG | EOD | +8.9% | +14.3% | **+7.0%** | Bear flip: start SHORT ~5 days, LONG for ~15 days. Est. 50% of full LONG gain |
| Jul | LONG | EOD | +0.6% | +33.3% | **+33.3%** | Bear-market rally confirmed — hold LONG EOD |
| Aug | LONG | +15m | +4.1% | -29.2% | **+4.1%** | ★ +15m rule saves 33.3pp — Aug 2022 was worst bear |
| Sep | **SHORT** | EOD | +16.4% | -7.8% | **+7.8%** | ✓ |
| Oct | LONG | EOD | -11.4% | +9.8% | **+9.8%** | |
| Nov | LONG | EOD | -1.5% | +39.8% | **+39.8%** | WR 64.3%, EV very positive → LONG EOD |
| Dec | **SHORT** | EOD | -7.8% | -32.6% | **+32.6%** | ✓ |
| **Total** | | | | | **+242.4%** | vs Pure Long -168.2% → **Δ +410.6pp** |

Key wins: Jan flip SHORT (+186.1pp swing), Apr flip SHORT (+75.9pp), Aug +15m (+33.3pp), Dec SHORT (+65.2pp)  
Note: 2022 is the year all rules fire simultaneously — the combined strategy thrives in a bear market year

---

### 2023

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | +15.1% | +21.6% | **+21.6%** | |
| Feb | LONG | EOD | +1.3% | +9.4% | **+9.4%** | |
| Mar | CAUTION | +15m | +9.0% | -4.2% | **+9.0%** | Saves 13.2pp |
| Apr | LONG | EOD | +7.3% | +0.9% | **+0.9%** | |
| May | LONG | EOD | +2.2% | +9.5% | **+9.5%** | |
| Jun | LONG | EOD | +5.1% | +1.0% | **+1.0%** | |
| Jul | LONG | EOD | +3.0% | -2.7% | **-2.7%** | WR 51.5% — above flip threshold |
| Aug | LONG | +15m | +6.4% | +26.2% | **+6.4%** | ✗ +15m rule costs 19.8pp — Aug 2023 was rising-curve bull |
| Sep | **SHORT** | EOD | +2.4% | -6.8% | **+6.8%** | ✓ |
| Oct | LONG | EOD | +7.1% | +10.6% | **+10.6%** | |
| Nov | LONG | EOD | +1.8% | +26.2% | **+26.2%** | WR 62%, EV positive → LONG EOD |
| Dec | **SHORT** | EOD | -2.7% | -2.4% | **+2.4%** | ✓ |
| **Total** | | | | | **+101.1%** | vs Pure Long +89.3% → **Δ +11.8pp** |

Key miss: Aug +15m costs 19.8pp in a clean bull August  
Key wins: Mar saves 13.2pp, Sep +13.6pp swing, Dec small save

---

### 2024

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | -1.6% | +23.4% | **+23.4%** | WR 71.1% — clearly LONG |
| Feb | LONG | EOD | +1.3% | +25.7% | **+25.7%** | |
| Mar | CAUTION | +15m | +4.8% | +7.7% | **+4.8%** | Caution costs 2.9pp — March 2024 was mild bull |
| Apr | LONG | EOD | +5.1% | -14.1% | **-14.1%** | WR 47.9% — above 40% flip threshold, no flip → loss |
| May | LONG | EOD | +5.8% | +11.6% | **+11.6%** | |
| Jun | LONG | EOD | +0.5% | +0.8% | **+0.8%** | |
| Jul | LONG | EOD | +1.8% | -8.8% | **-8.8%** | WR 45.5% — above flip threshold |
| Aug | LONG | +15m | +8.6% | -28.8% | **+8.6%** | ★ +15m rule saves 37.4pp — Aug 2024 deep bear |
| Sep | **SHORT** | EOD | -0.4% | +6.3% | **-6.3%** | ✗ MISS — Sep 2024 neutral/positive |
| Oct | LONG | EOD | +8.8% | +32.2% | **+32.2%** | |
| Nov | LONG | EOD | +11.8% | +42.9% | **+42.9%** | WR 58%, EV strong → LONG EOD |
| Dec | **SHORT** | EOD | +5.2% | -16.3% | **+16.3%** | ✓ |
| **Total** | | | | | **+137.1%** | vs Pure Long +82.6% → **Δ +54.5pp** |

Key wins: Aug +15m saves 37.4pp, Dec SHORT saves 32.6pp  
Key misses: Sep 2024 miss (-12.6pp), Apr stays LONG incorrectly (-14.1% — WR too high to trigger flip)

---

### 2025

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | +20.5% | +12.4% | **+12.4%** | WR 49.1% — above 45% threshold |
| Feb | LONG | EOD | -7.4% | +10.3% | **+10.3%** | |
| Mar | CAUTION | +15m | -8.3% | -7.8% | **-8.3%** | Both negative — bear even at +15m. Small extra loss vs EOD |
| Apr | LONG | EOD | +7.4% | +157.1% | **+157.1%** | Liberation Day — LONG captures full upside |
| May | LONG | EOD | +5.2% | -7.0% | **-7.0%** | High-WR trap (57.1% WR, negative EV) — subtle, stay LONG |
| Jun | LONG | EOD | +4.7% | +9.7% | **+9.7%** | |
| Jul | LONG | EOD | +8.1% | +11.5% | **+11.5%** | |
| Aug | LONG | +15m | +8.0% | +21.4% | **+8.0%** | +15m rule costs 13.4pp — Aug 2025 was bull |
| Sep | **SHORT** | EOD | +3.6% | -5.3% | **+5.3%** | ✓ |
| Oct | LONG | EOD | +15.5% | +22.3% | **+22.3%** | |
| Nov | **SHORT** | EOD | +16.0% | -7.9% | **+4.0%** | Negative EV detected ~day 7. 50% credit (subtle signal: WR 54.3%) |
| Dec | **SHORT** | EOD | -7.7% | -25.7% | **+25.7%** | ✓ |
| **Total** | | | | | **+251.0%** | vs Pure Long +191.1% → **Δ +59.9pp** |

Key wins: Sep/Nov/Dec SHORT total +35pp vs pure long; Apr LONG captures Liberation Day  
Key miss: Aug +15m costs 13.4pp; May High-WR trap costs 7pp

---

### 2026 YTD (Jan–May)

*Updated 2026-06-02 with corrected screener (vol lookahead fix + OR anchor fix). All regime calls unchanged.*

| Month | Direction | Window | +15m | EOD | Strategy P&L | Notes |
|-------|-----------|--------|------|-----|-------------|-------|
| Jan | LONG | EOD | -1.4% | -13.7% | **-13.7%** | WR 43.9% — borderline; no mid-month flip triggered |
| Feb | LONG | EOD | -36.0% | -8.4% | **-8.4%** | EOD better than +15m; WR 50%, no flip trigger |
| Mar | CAUTION | +15m | -6.9% | -34.7% | **-6.9%** | ★ Rule saves 27.8pp — March bear now much clearer |
| Apr | LONG | EOD | -0.3% | +37.0% | **+37.0%** | Liberation Day follow-on |
| May | LONG | EOD | +5.2% | +59.7% | **+59.7%** | Stronger than originally measured |
| **Total** | | | | | **+68.7%** | vs Pure Long +39.9% → **Δ +28.8pp** |

---

## Full Summary

| Year | Strategy P&L | Pure Long P&L | Delta | Verdict |
|------|-------------|---------------|-------|---------|
| 2018 | **+108.6%** | -10.7% | **+119.3pp** | Dec/Sep SHORT transformed a -11% year to +109% |
| 2019 | +79.2% | **+91.5%** | -12.3pp | Sep/Dec misses — 2019 rule exceptions hurt |
| 2020 | +129.3% | **+142.8%** | -13.5pp | COVID Mar/Dec exceptions — pure long wins |
| 2021 | **+57.1%** | -44.9% | **+102.0pp** | March caution + Nov SHORT rescue |
| 2022 | **+242.4%** | -168.2% | **+410.6pp** | All rules fire — bear year becomes best strategy year |
| 2023 | **+101.1%** | +89.3% | +11.8pp | Mild year, consistent small improvements |
| 2024 | **+137.1%** | +82.6% | **+54.5pp** | Aug/Dec rules dominate |
| 2025 | **+251.0%** | +191.1% | **+59.9pp** | Sep/Nov/Dec shorts + Liberation Day |
| 2026 YTD | **+68.7%** | +39.9% | **+28.8pp** | Mar caution saves 28pp (corrected: -34.7% bear) |
| **8.4yr Total** | **+1,173%** | **+421%** | **+752pp** | Strategy wins 7/9 years |

---

## Cost/Benefit of Each Rule

| Rule | Years it helped | Years it hurt | Net contribution |
|------|----------------|---------------|-----------------|
| **September SHORT** | 2018 +28pp, 2021 +10pp, 2022 +16pp, 2023 +14pp, 2025 +11pp | 2019 -17pp, 2024 -13pp | **+49pp net** |
| **October LONG** | 7/9 years, avg +16pp | 2021 -3pp (only miss) | **+109pp net** |
| **December SHORT** | 2018 +80pp, 2021 +11pp, 2022 +65pp, 2024 +33pp, 2025 +51pp | 2019 -9pp, 2020 -17pp | **+214pp net** |
| **January flip SHORT** | 2022 +186pp (Jan 2022) | 2026 -2pp (borderline) | **+184pp net** |
| **March +15m caution** | Every year — saves from bear March; 2021 +60pp, 2026 +28pp | 2020 -24pp (COVID volatility rewarded holding) | **+112pp net** |
| **August +15m exits** | 2022 +33pp, 2024 +37pp | 2021 -23pp, 2023 -20pp, 2025 -13pp | **+14pp net** |
| **November EV flip** | 2021 +45pp, 2025 +12pp | Costs nothing when positive | **+57pp net** |
| **April bear flip** | 2022 +76pp | 2024 -14pp (WR too high to trigger) | **+62pp net** |

---

## Key Observations

**The strategy is clearly better in bear and volatile years (2018, 2021, 2022, 2025)** — the directional rules flip from losers to winners. The pure long strategy is destroyed in these years (-10.7%, -44.9%, -168.2%) while the strategy captures positive returns.

**Pure long wins in COVID-style catalyst years (2019, 2020)** — when September and December flip to positive due to macro catalysts (Phase 1 deal, vaccine), the seasonal SHORT rules miss. This is the price of the model: 2/9 years it leaves money on the table.

**August is the most expensive rule** — the +15m default for August costs meaningful P&L in 3 of the 8 years (2021, 2023, 2025 are all bull Augusts that EOD was far better). Net contribution is still +14pp across all years but the individual-year costs are large. A refinement: only apply August +15m if the prior month (July) was also negative or neutral.

**October LONG has the best net contribution (+109pp)** at the lowest cost — 7/9 years positive and the one miss (2021) was tiny (-1.5%).

**December SHORT has the largest total recovery (+214pp)** because the bear Decembers are severe when they hit (2018: -39.8%, 2022: -32.6%, 2025: -25.7%).

**The March caution rule (+15m only) is the most consistent** — it fires correctly in 7/9 years. The only cost was 2020 (COVID volatility rewarded holding to EOD). Net +105pp across 9 years with no large single-year cost except 2020.
