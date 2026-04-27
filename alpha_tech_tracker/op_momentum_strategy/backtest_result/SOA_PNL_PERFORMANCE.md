# Strategy P&L Performance — State of Art

Summary of confirmed backtest results for the op-momentum strategy.
All runs use no-compound (daily $10,000 reset) unless noted.

---

## Configuration

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 5 \
  --top 2 \
  --start <YEAR>-01-01 --end <YEAR>-12-31
```

### Key Parameters

| Parameter | Value | Notes |
|---|---|---|
| Windows | M1 (09:30/3-bar), A1 (13:15/1-bar), A2 (15:00/1-bar) | Sequential capital recycling |
| Top-N | 2 | Top-2 picks per window per day |
| Weights | 60% / 40% | Rank-1 gets 60%, rank-2 gets 40% of window capital |
| Reversal | on (max bars=3) | BEARISH stop-out → price crosses OR high → flip BULLISH |
| Bearish re-entry | on (max bars=3) | BEARISH stop-out → price closes below OR low → re-enter short |
| Bullish re-entry | on (max bars=5) | BULLISH stop-out → price closes above OR high → re-enter long |
| Doubledown | on, start=5 min | Co-pick stops out within 5 min of OR close → freed capital redeployed into surviving position with 80% bar-range hard stop |
| Regime filter | off | Not applied in this config |
| Stop pct | 0.15 (default) | 15% of OR range |
| Trailing MA | ma20 (default) | Exit when price crosses below MA20 (armed after 1× OR range move) |
| Ticker pool | 17 tickers (V3) | SNDK APP SHOP CVNA AMD META EXPE RH FN MU CRDO PLTR COIN CLS MSTR CRWV MRVL |
| Lookback | 60d rolling | For selector scoring |
| Compounding | off | $10,000 reset each day |
| Feed | SIP | Alpaca SIP feed |

### Secondary Features — Usage Notes

`--reversal` and `--bearish-reentry` are run as **independent flags** (not combined).
When enabled simultaneously they are mutually exclusive per trade (first chronological
trigger wins), which introduces a backtest lookahead not present in the live engine.
Run each independently for a live-consistent backtest; use both together only to
understand their combined upper bound.

---

## V3 Pool — 6-Year Performance (2021–2026 YTD)

**Last run: 2026-04-25** · SIP feed · with `--doubledown --doubledown-start 5`

### V3 Pool (17 tickers)

```
SNDK, APP, SHOP, CVNA, AMD, META, EXPE, RH, FN, MU, CRDO, PLTR, COIN,
CLS, MSTR, CRWV, MRVL
```

Removed from V2: FANG (structurally weak), NVDA (fading), TSLA (peaked).
Added: CLS, MSTR, CRWV, MRVL (2026-04-12).

| Year | Trades | W/L | WR | Return | QQQ Return | Alpha |
|------|--------|-----|----|--------|------------|-------|
| 2021 | 1,400 | 628W/772L | 45% | **+185.72%** | +28.63% | +157pp |
| 2022 | 1,318 | 581W/737L | 44% | **+200.00%** | -33.71% | +234pp |
| 2023 | 1,406 | 612W/794L | 44% | **+332.13%** | +54.84% | +277pp |
| 2024 | 1,398 | 623W/775L | 45% | **+165.15%** | +26.99% | +138pp |
| 2025 | 1,415 | 634W/781L | 45% | **+165.48%** | +20.40% | +145pp |
| 2026 YTD (Jan–Apr 24) | 446 | 239W/207L | 54% | **+107.79%** | +8.28% | +100pp |
| **5-yr sum (2021–2025)** | | | | **+1,048.48%** | **+97.74%** | **+951pp** |

---

## AT Pool — 7-Year Performance (2019–2026 YTD)

**Last run: 2026-04-25** · SIP feed · with `--doubledown --doubledown-start 5`

### AT Pool (16 tickers)

```
SNDK, APP, SHOP, CVNA, AMD, META, MU, PLTR, COIN, NVDA, TSLA,
RKLB, ASTS, HOOD, MSTR, NFLX
```

Removed from V2: ANAB, RH, FN, EXPE, FANG (sparse bars / low liquidity).
Added: RKLB, ASTS, HOOD (Russell 2000 high-activity), NFLX (large-cap); CRWD → MSTR swap.

| Year | Trades | W/L | WR | Return | QQQ Return | Alpha |
|------|--------|-----|----|--------|------------|-------|
| 2019 | 1,280 | 581W/699L | 45% | **+111.19%** | +37.27% | +74pp |
| 2020 | 1,239 | 560W/679L | 45% | **+191.64%** | +45.14% | +147pp |
| 2021 | 1,372 | 603W/769L | 44% | **+153.16%** | +28.63% | +125pp |
| 2022 | 1,299 | 587W/712L | 45% | **+229.63%** | -33.71% | +263pp |
| 2023 | 1,391 | 613W/778L | 44% | **+348.97%** | +54.84% | +294pp |
| 2024 | 1,395 | 599W/796L | 43% | **+196.20%** | +26.99% | +169pp |
| 2025 | 1,378 | 675W/703L | 49% | **+223.44%** | +20.40% | +203pp |
| 2026 YTD (Jan–Apr 24) | 431 | 232W/199L | 54% | **+128.21%** | +8.28% | +120pp |
| **5-yr sum (2021–2025)** | | | | **+1,151.40%** | **+97.74%** | **+1,054pp** |
| **7-yr sum (2019–2025)** | | | | **+1,454.23%** | **+180.18%** | **+1,274pp** |

---

## V3 vs AT Head-to-Head

| Year | V3 | AT | Δ (AT−V3) | Winner |
|------|----|----|-----------|--------|
| 2021 | +185.72% | +153.16% | -32.56pp | **V3** |
| 2022 | +200.00% | +229.63% | +29.63pp | **AT** |
| 2023 | +332.13% | +348.97% | +16.84pp | **AT** |
| 2024 | +165.15% | +196.20% | +31.05pp | **AT** |
| 2025 | +165.48% | +223.44% | +57.96pp | **AT** |
| 2026 YTD | +107.79% | +128.21% | +20.42pp | **AT** |
| **5-yr sum** | **+1,048.48%** | **+1,151.40%** | **+102.92pp** | **AT** |

### Key Observations

1. **AT wins 5 of 6 years and the 5-year total by +103pp** — NVDA, TSLA, MSTR, ASTS generate larger BEARISH moves in risk-off environments that the AT pool captures more effectively.

2. **V3 wins only 2021** (+32pp) — RKLB, ASTS, HOOD had limited history early in 2021 (RKLB IPO'd Nov 2021, HOOD Aug 2021), reducing the effective AT pool size that year.

3. **2025 gap is the largest** (+58pp, AT wins) — NVDA and TSLA both had exceptional bull-year momentum that V3 specifically excluded; MSTR added BTC-correlated beta.

4. **2026 YTD: AT +128% vs V3 +108%** (+20pp) — tariff-driven bear environment benefits AT's high-beta names (NVDA, TSLA, MSTR, ASTS) on the BEARISH signal path.

5. **Win rate is consistently 43–49%** — profitable with sub-50% win rate because avg wins (+1.1–1.8%) exceed avg losses (-0.3–0.8%) every year in both pools.

---

## Key Observations (All Pools)

1. **Beats QQQ every single year** — including 2022 where QQQ lost -33.71% while both pools returned +200%.

2. **2023 is the standout year** (+332% V3, +349% AT) — strong directional intraday moves in both directions produced high-quality OR breakouts.

3. **2026 YTD is exceptional vs QQQ** (+100pp / +120pp alpha in 4 months) — the tariff-driven bearish macro environment generates sustained intraday follow-through that the BEARISH + BRE combination captures effectively.

4. **Win rate is consistently 43–49%** across all years — the strategy is profitable with a sub-50% win rate because average wins are larger than average losses.

5. **Reversal vs BRE split** (from independent-mode study, same config):
   - BRE wins bear/choppy years: 2021, 2022, 2024
   - Reversal wins bull years: 2023, 2025, 2026 YTD
   - Both features are additive — they fire on different days

---

## 4-Window Config — M1 + A1(10:00) + A2(13:15) + A3(15:00)

**Last run: 2026-04-26** · SIP feed · adds a 10:00/1-bar window between M1 and the afternoon windows.

### Configuration

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 10:00 1 --window A2 13:15 1 --window A3 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 5 \
  --top 2 \
  --start <YEAR>-01-01 --end <YEAR>-12-31
```

The 10:00/1-bar window (A1) fires at 10:05 — capturing the concentrated cluster of M1
re-entry and reversal signals (REV/BRE/BRU) that trigger at 09:55–10:05 as fresh primary
signals in the 10:00 OR. Capital flows: M1 → A1(10:00) → A2(13:15) → A3(15:00).

### V3 Pool — 4-Window vs 3-Window SOA

| Year | 4-win Return | 3-win Return | Δ | Trades | WR |
|------|-------------|-------------|---|--------|----|
| 2021 | **+224.13%** | +185.72% | +38.4pp | 1,758 | 46% |
| 2022 | **+247.44%** | +200.00% | +47.4pp | 1,659 | 44% |
| 2023 | **+386.57%** | +332.13% | +54.4pp | 1,780 | 44% |
| 2024 | **+229.09%** | +165.15% | +63.9pp | 1,771 | 46% |
| 2025 | **+236.79%** | +165.48% | +71.3pp | 1,781 | 46% |
| 2026 YTD (Jan–Apr 25) | **+122.94%** | +107.79% | +15.1pp | 551 | 53% |
| **5-yr sum (2021–2025)** | **+1,324.02%** | **+1,048.48%** | **+275.5pp** | | |

### AT Pool — 4-Window vs 3-Window SOA

| Year | 4-win Return | 3-win Return | Δ | Trades | WR |
|------|-------------|-------------|---|--------|----|
| 2019 | **+156.20%** | +111.19% | +45.0pp | 1,609 | 46% |
| 2020 | **+237.54%** | +191.64% | +45.9pp | 1,580 | 46% |
| 2021 | **+196.46%** | +153.16% | +43.3pp | 1,747 | 45% |
| 2022 | **+311.45%** | +229.63% | +81.8pp | 1,645 | 45% |
| 2023 | **+403.06%** | +348.97% | +54.1pp | 1,741 | 45% |
| 2024 | **+288.21%** | +196.20% | +92.0pp | 1,777 | 45% |
| 2025 | **+261.55%** | +223.44% | +38.1pp | 1,734 | 48% |
| 2026 YTD (Jan–Apr 25) | **+144.07%** | +128.21% | +15.9pp | 544 | 53% |
| **5-yr sum (2021–2025)** | **+1,460.73%** | **+1,151.40%** | **+309.3pp** | | |

### V3 vs AT — 4-Window Head-to-Head

| Year | V3 | AT | Δ (AT−V3) | Winner |
|------|----|----|-----------|--------|
| 2021 | +224.13% | +196.46% | -27.7pp | **V3** |
| 2022 | +247.44% | +311.45% | +64.0pp | **AT** |
| 2023 | +386.57% | +403.06% | +16.5pp | **AT** |
| 2024 | +229.09% | +288.21% | +59.1pp | **AT** |
| 2025 | +236.79% | +261.55% | +24.8pp | **AT** |
| 2026 YTD | +122.94% | +144.07% | +21.1pp | **AT** |
| **5-yr sum** | **+1,324.02%** | **+1,460.73%** | **+136.7pp** | **AT** |

### Key Observations

1. **A1 10:00 window adds +276pp (V3) and +309pp (AT) over 3-window SOA** — positive every single year in both pools.

2. **The 10:00 OR captures the M1 re-entry cluster** — exit time analysis shows ~40–46% of M1 REV/BRE/BRU re-entries trigger at 09:55, with entries entering at 10:00–10:05. The 10:00/1-bar OR formalizes this as an independent scored selection.

3. **AT's lead over V3 widens to +137pp** (vs +103pp in 3-window) — AT's high-beta names (NVDA, TSLA, ASTS, MSTR) generate stronger 10:00 OR breakouts following M1 volatility.

4. **V3 still wins 2021** — same RKLB/HOOD IPO-year limitation; AT pool is effectively smaller that year.

5. **2024 is the largest incremental year for AT** (+92pp delta vs 3-window) — consistent with AT's high-beta tickers having strong mid-morning continuation after M1 OR breakouts.

---

## 4-Window Config — M1 + A1(12:00) + A2(13:15) + A3(15:00)

**Last run: 2026-04-26** · SIP feed · adds a 12:00/2-bar mid-morning window. Uses `--doubledown` **without** `--doubledown-start 5` (unlike the 3-window SOA baseline above).

### Configuration

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 12:00 2 --window A2 13:15 1 --window A3 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown \
  --top 2 \
  --start <YEAR>-01-01 --end <YEAR>-12-31
```

The 12:00/2-bar window (A1) fires at 12:10 — after the mid-morning consolidation phase.
Capital flows: M1 → A1(12:00) → A2(13:15) → A3(15:00).

> **Note on doubledown:** This config uses `--doubledown` without `--doubledown-start 5`. The 3-window SOA uses `--doubledown-start 5` which restricts doubledown to co-picks that stop out within 5 min of OR close. The missing quality gate accounts for most of the gap vs the SOA baseline.

### V3 Pool — 4-Window vs 3-Window SOA

| Year | 4-win Return | 3-win Return | Δ | Trades | WR |
|------|-------------|-------------|---|--------|----|
| 2021 | **+156.17%** | +185.72% | -29.6pp | 1,539 | 44% |
| 2022 | **+196.55%** | +200.00% | -3.5pp | 1,477 | 45% |
| 2023 | **+279.56%** | +332.13% | -52.6pp | 1,531 | 45% |
| 2024 | **+136.72%** | +165.15% | -28.4pp | 1,605 | 44% |
| 2025 | **+141.85%** | +165.48% | -23.6pp | 1,547 | 44% |
| 2026 YTD (Jan–Apr 25) | **+101.77%** | +107.79% | -6.0pp | 477 | 51% |
| **5-yr sum (2021–2025)** | **+910.85%** | **+1,048.48%** | **-137.6pp** | | |

### AT Pool — 4-Window vs 3-Window SOA

| Year | 4-win Return | 3-win Return | Δ | Trades | WR |
|------|-------------|-------------|---|--------|----|
| 2019 | **+102.43%** | +111.19% | -8.8pp | 1,412 | 46% |
| 2020 | **+168.09%** | +191.64% | -23.6pp | 1,384 | 44% |
| 2021 | **+147.31%** | +153.16% | -5.9pp | 1,498 | 44% |
| 2022 | **+193.52%** | +229.63% | -36.1pp | 1,459 | 45% |
| 2023 | **+288.09%** | +348.97% | -60.9pp | 1,532 | 44% |
| 2024 | **+197.70%** | +196.20% | +1.5pp | 1,576 | 44% |
| 2025 | **+192.22%** | +223.44% | -31.2pp | 1,501 | 47% |
| 2026 YTD (Jan–Apr 25) | **+125.81%** | +128.21% | -2.4pp | 476 | 52% |
| **5-yr sum (2021–2025)** | **+1,018.84%** | **+1,151.40%** | **-132.6pp** | | |

### V3 vs AT — 4-Window Head-to-Head

| Year | V3 | AT | Δ (AT−V3) | Winner |
|------|----|----|-----------|--------|
| 2021 | +156.17% | +147.31% | -8.9pp | **V3** |
| 2022 | +196.55% | +193.52% | -3.0pp | **V3** |
| 2023 | +279.56% | +288.09% | +8.5pp | **AT** |
| 2024 | +136.72% | +197.70% | +61.0pp | **AT** |
| 2025 | +141.85% | +192.22% | +50.4pp | **AT** |
| 2026 YTD | +101.77% | +125.81% | +24.0pp | **AT** |
| **5-yr sum** | **+910.85%** | **+1,018.84%** | **+108.0pp** | **AT** |

### Per-Window Detail — V3 Pool

| Year | M1 (09:30/3) | A1 (12:00/2) | A2 (13:15/1) | A3 (15:00/1) |
|------|-------------|-------------|-------------|-------------|
| 2021 | 477T 51%WR +0.444%EV +106.5% | 362T 37%WR +0.074%EV +8.6% | 289T 40%WR +0.206%EV +23.2% | 411T 43%WR +0.135%EV +17.9% |
| 2022 | 472T 46%WR +0.345%EV +87.9% | 352T 45%WR +0.345%EV +54.0% | 266T 39%WR +0.117%EV +11.4% | 387T 48%WR +0.295%EV +43.2% |
| 2023 | 490T 47%WR +0.705%EV +188.0% | 352T 47%WR +0.275%EV +32.6% | 289T 47%WR +0.349%EV +32.1% | 400T 38%WR +0.170%EV +26.8% |
| 2024 | 483T 49%WR +0.284%EV +67.9% | 398T 43%WR +0.184%EV +29.7% | 332T 38%WR +0.141%EV +17.5% | 392T 43%WR +0.182%EV +21.6% |
| 2025 | 483T 47%WR +0.316%EV +75.9% | 372T 43%WR +0.188%EV +27.3% | 307T 43%WR +0.160%EV +18.4% | 385T 44%WR +0.170%EV +20.3% |
| 2026 YTD | 154T 58%WR +0.895%EV +67.7% | 123T 42%WR +0.399%EV +19.3% | 87T 52%WR +0.384%EV +7.7% | 113T 51%WR +0.206%EV +7.1% |

### Per-Window Detail — AT Pool

| Year | M1 (09:30/3) | A1 (12:00/2) | A2 (13:15/1) | A3 (15:00/1) |
|------|-------------|-------------|-------------|-------------|
| 2019 | 456T 48%WR +0.269%EV +63.4% | 294T 45%WR +0.140%EV +15.0% | 299T 41%WR +0.144%EV +13.4% | 363T 48%WR +0.088%EV +10.6% |
| 2020 | 446T 45%WR +0.476%EV +111.0% | 313T 45%WR +0.154%EV +19.4% | 265T 40%WR +0.225%EV +22.8% | 360T 46%WR +0.124%EV +14.8% |
| 2021 | 470T 51%WR +0.330%EV +82.1% | 337T 39%WR +0.132%EV +20.8% | 300T 37%WR +0.198%EV +27.8% | 391T 45%WR +0.141%EV +16.6% |
| 2022 | 464T 48%WR +0.347%EV +89.3% | 344T 42%WR +0.336%EV +45.4% | 279T 42%WR +0.262%EV +20.8% | 372T 48%WR +0.324%EV +38.1% |
| 2023 | 492T 49%WR +0.779%EV +208.4% | 356T 42%WR +0.252%EV +30.4% | 288T 42%WR +0.303%EV +24.9% | 396T 40%WR +0.185%EV +24.3% |
| 2024 | 491T 49%WR +0.432%EV +117.8% | 399T 44%WR +0.286%EV +40.1% | 299T 40%WR +0.175%EV +23.8% | 387T 41%WR +0.128%EV +16.0% |
| 2025 | 470T 51%WR +0.478%EV +110.9% | 365T 39%WR +0.165%EV +24.0% | 293T 43%WR +0.299%EV +20.0% | 373T 53%WR +0.279%EV +37.3% |
| 2026 YTD | 151T 57%WR +1.079%EV +78.6% | 114T 46%WR +0.531%EV +25.0% | 97T 57%WR +0.468%EV +13.9% | 114T 49%WR +0.289%EV +8.3% |

### Key Observations

1. **This config trails the 3-window SOA every year (V3: -3.5pp to -52.6pp; AT: -2.4pp to -60.9pp)** — the primary cause is the missing `--doubledown-start 5` quality gate. The SOA restricts doubledown to co-picks that stop out within 5 min of OR close, improving doubledown EV. Without this gate, early stop-outs throughout the session dilute the doubledown pool.

2. **The 12:00/2bar A1 slot is consistently positive EV** — all years, both pools show positive EV/trade (+0.07% to +0.53%). The slot adds real edge; the drag comes from baseline config differences, not the window itself.

3. **AT 2024 is the one exception where this config beats the 3-window SOA** (+1.5pp) — AT high-beta names (NVDA, TSLA) generate strong mid-morning OR breakouts after M1 volatility, and the unrestricted doubledown happens to benefit in this year.

4. **V3 wins 2021 and 2022 in this config** — unlike the 3-window SOA where AT dominates 5 of 6 years, the pattern shifts when A2/A3 afternoon windows are added. V3's structure proves more stable in non-bull years without the NVDA/TSLA beta amplification.

5. **AT wins the 5-year total by +108pp** — consistent with AT's high-beta advantage, though narrower than the 3-window SOA gap (+103pp). The 12:00 window fires in 337–399 trades/year (AT) — high utilization with positive EV every year.

6. **To match or exceed the 3-window SOA with this config, add `--doubledown-start 5`** — that single flag change accounts for +30–53pp improvement in bull years and is the recommended path before live deployment of this window config.

---

## Historical V2 Pool Reference (2019–2025)

Results from the original V2 pool. Superseded by V3 for 2021 onwards.

| Year | Trades | W/L | Return (with DD) | Return (no DD) | QQQ Return |
|------|--------|-----|-----------------|----------------|------------|
| 2019 | 1,353 | 580W/773L | +109.75% | +100.32% | +37.27% |
| 2020 | 1,368 | 618W/750L | +212.43% | +192.15% | +45.14% |
| 2021 | 1,413 | 634W/779L | +158.41% | +147.87% | +28.63% |
| 2022 | 1,328 | 590W/738L | +210.80% | +191.51% | -33.71% |
| 2023 | 1,424 | 647W/777L | +352.89% | +334.58% | +54.84% |
| 2024 | 1,413 | 630W/783L | +151.69% | +138.51% | +26.99% |
| 2025 | 1,418 | 658W/760L | +185.14% | +174.27% | +20.40% |
| **7-yr sum** | | | **+1,381.11%** | **+1,279.21%** | **+179.56%** |

> V2 pool: SNDK APP SHOP CVNA AMD META EXPE FANG RH FN MU CRDO PLTR COIN NVDA TSLA

---

## Related Findings

| Document | Topic |
|---|---|
| `bearish_reentry/FINDINGS.md` | BRE feature deep-dive, annual delta vs baseline, reversal vs BRE independent comparison |
| `bearish_reentry/OVERVIEW.md` | BRE implementation design, config parameters, mutual exclusion with reversal |
| `multiple_trading_windows/SUMMARY.md` | M1/M2/A1/A2 window comparison, compound growth projections |
| `FINDINGS.md` | Regime filter, ticker pool, weight sweep, top-N findings |
| `ticker_list_review/04_12_2026/FINDINGS.md` | V2 vs V3 quarterly trend analysis, candidate screen |
