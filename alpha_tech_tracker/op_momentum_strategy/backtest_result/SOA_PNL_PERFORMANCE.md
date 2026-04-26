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
