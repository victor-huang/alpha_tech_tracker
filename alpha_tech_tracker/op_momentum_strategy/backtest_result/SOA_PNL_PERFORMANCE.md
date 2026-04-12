# Strategy P&L Performance — State of Affairs

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
| Doubledown | on, start=5 min | Co-pick stops out within 5 min of OR close → freed capital redeployed into surviving position with break-even hard stop |
| Regime filter | off | Not applied in this config |
| Stop pct | 0.15 (default) | 15% of OR range |
| Trailing MA | ma20 (default) | Exit when price crosses below MA20 (armed after 1× OR range move) |
| Ticker pool | 16 tickers (V2) | SNDK APP SHOP CVNA AMD META EXPE FANG RH FN MU CRDO PLTR COIN NVDA TSLA |
| Lookback | 60d rolling | For selector scoring |
| Compounding | off | $10,000 reset each day |

### Secondary Features — Usage Notes

`--reversal` and `--bearish-reentry` are run as **independent flags** (not combined).
When enabled simultaneously they are mutually exclusive per trade (first chronological
trigger wins), which introduces a backtest lookahead not present in the live engine.
Run each independently for a live-consistent backtest; use both together only to
understand their combined upper bound.

---

## 7-Year Annual Performance (2019–2025) + 2026 YTD — V2 Pool

Results include `--doubledown --doubledown-start 5`. Prior results (without DD) shown for reference.

| Year | Trades | W/L | Return (with DD) | Return (no DD) | DD Delta | QQQ Return | Alpha |
|---|---|---|---|---|---|---|---|
| 2019 | 1,353 | 580W / 773L | **+109.75%** | +100.32% | +9.4pp | +37.27% | +72pp |
| 2020 | 1,368 | 618W / 750L | **+212.43%** | +192.15% | +20.3pp | +45.14% | +167pp |
| 2021 | 1,413 | 634W / 779L | **+158.41%** | +147.87% | +10.5pp | +28.63% | +130pp |
| 2022 | 1,328 | 590W / 738L | **+210.80%** | +191.51% | +19.3pp | -33.71% | +244pp |
| 2023 | 1,424 | 647W / 777L | **+352.89%** | +334.58% | +18.3pp | +54.84% | +298pp |
| 2024 | 1,413 | 630W / 783L | **+151.69%** | +138.51% | +13.2pp | +26.99% | +125pp |
| 2025 | 1,418 | 658W / 760L | **+185.14%** | +174.27% | +10.9pp | +20.40% | +165pp |
| 2026 YTD (Jan–Apr 10) | 395 | 190W / 205L | **+108.79%** | +99.08% | +9.7pp | -0.31% | +109pp |
| **7-yr sum (2019–2025)** | | | **+1,381.11%** | +1,279.21% | **+101.9pp** | **+179.56%** | **+1,201pp** |

> 2026 uses `--feed iex` (SIP subscription does not allow querying recent data).
> DD wins every year — delta ranges from +9pp to +20pp.

---

## Key Observations

1. **Beats QQQ every single year** — including 2022 where QQQ lost -33.71% and the
   strategy returned +191.51%. The BEARISH signal path profits from downtrends that
   destroy buy-and-hold portfolios.

2. **2023 is the standout year** (+334.58%, +280pp alpha) — strong directional
   intraday moves in both directions produced high-quality OR breakouts.

3. **2026 YTD is exceptional relative to QQQ** (+99pp alpha in 3.5 months) —
   the tariff-driven bearish macro environment generates sustained intraday
   follow-through that the BEARISH + BRE combination captures effectively.

4. **Win rate is consistently 44–47%** across all years — the strategy is profitable
   with a sub-50% win rate because average wins are larger than average losses.

5. **Reversal vs BRE split** (from independent-mode study, same config):
   - BRE wins bear/choppy years: 2021 (+7pp), 2022 (+21pp), 2024 (+13pp)
   - Reversal wins bull years: 2023 (+43pp), 2025 (+20pp), 2026 YTD (+15pp)
   - Both features are additive — they fire on different days

---

## AT Pool — Same Config (2026-04-11)

Re-ran the identical SOA config against the **ACTIVELY_TRADE_TICKERS** (AT) pool.

### AT Pool (16 tickers)

```
SNDK, APP, SHOP, CVNA, AMD, META, MU, PLTR, COIN, NVDA, TSLA,
RKLB, ASTS, HOOD, CRWD, NFLX
```

Removed from V2: ANAB, RH, FN, EXPE, FANG (sparse bars / low liquidity).
Added: RKLB, ASTS, HOOD (Russell 2000 high-activity), CRWD, NFLX (large-cap).

### Year-by-Year Comparison (with --doubledown --doubledown-start 5)

| Year | SOA V2 | AT Pool | Δ | Winner |
|------|--------|---------|---|--------|
| 2019 | +109.75% | +128.24% | +18.5pp | **AT** |
| 2020 | +212.43% | +177.51% | -34.9pp | V2 |
| 2021 | +158.41% | +146.73% | -11.7pp | V2 |
| 2022 | +210.80% | +257.97% | +47.2pp | **AT** |
| 2023 | +352.89% | +346.14% | -6.8pp | V2 |
| 2024 | +151.69% | +191.15% | +39.5pp | **AT** |
| 2025 | +185.14% | +218.03% | +32.9pp | **AT** |
| 2026 YTD (Jan–Apr 10) | +108.79% | +99.72% | -9.1pp | V2 |
| **7-yr sum (2019–2025)** | **+1,381.11%** | **+1,465.77%** | **+84.7pp** | **AT** |

### Key Observations

1. **AT wins 4 of 7 years and the 7-year total by +68pp** — the higher-OR% names (ASTS 3.49%, RKLB 3.22%, CRWD 2.65%) generate larger winning moves under the reversal+BRE config.

2. **AT dominates bear/choppy years** — 2022 (+38pp), 2024 (+35.5pp), 2019 (+19pp). COIN's bearish asymmetry and CRWD/NVDA volatility drive outperformance when markets trend down intraday.

3. **2025 flip vs prior M1-only study** — in the M1-alone study, AT trailed V2 by -22pp in 2025. With reversal+BRE, AT wins 2025 by +25pp. The re-entry and reversal signals extract more value from the AT pool's volatile names.

4. **V2 edges AT in pure bull years** — 2020 (-31pp), 2021 (-11pp), 2023 (-7pp). EXPE/FANG/RH contributed strong BULLISH breakouts in those years; their removal hurts in sustained bull trends.

5. **2020 gap (-31pp) is the largest drag** — RKLB, ASTS, HOOD were not listed in 2020, effectively running with a smaller pool that year.

### Output Logs

| File | Description |
|------|-------------|
| `active_traded_ticker_list/soa_at_2019.txt` | AT pool — 2019 full output |
| `active_traded_ticker_list/soa_at_2020.txt` | AT pool — 2020 full output |
| `active_traded_ticker_list/soa_at_2021.txt` | AT pool — 2021 full output |
| `active_traded_ticker_list/soa_at_2022.txt` | AT pool — 2022 full output |
| `active_traded_ticker_list/soa_at_2023.txt` | AT pool — 2023 full output |
| `active_traded_ticker_list/soa_at_2024.txt` | AT pool — 2024 full output |
| `active_traded_ticker_list/soa_at_2025.txt` | AT pool — 2025 full output |
| `active_traded_ticker_list/soa_at_2026.txt` | AT pool — 2026 YTD full output |

---

## AT+MSTR Pool — CRWD → MSTR Swap (2026-04-11)

Ticker screening identified **MSTR (MicroStrategy)** as the best standalone replacement for CRWD:
- MSTR standalone: +70.10% (2025), +21.05% (2026 YTD) vs CRWD: +35.97% / +13.49%
- MSTR ADV ~20M shares/day (below Tier 1 floor but extreme beta; Bitcoin proxy since Aug 2020)
- Other screened candidates: SOFI (+60.73%/+14.22%), MARA (+67.19%/+2.62%), AVGO (+38.61%/+11.48%), RIOT (+28.12%/+11.45%), IBIT (+32.00%/+3.16%)

### AT+MSTR Pool (16 tickers)

```
SNDK, APP, SHOP, CVNA, AMD, META, MU, PLTR, COIN, NVDA, TSLA,
RKLB, ASTS, HOOD, MSTR, NFLX
```

Change: CRWD → MSTR

### Year-by-Year Comparison (with --doubledown --doubledown-start 5)

| Year | SOA V2 | AT (CRWD) | AT+MSTR | Δ vs AT |
|------|--------|-----------|---------|---------|
| 2019 | +109.75% | +128.24% | +114.23% | -14.0pp |
| 2020 | +212.43% | +177.51% | **+189.11%** | +11.6pp |
| 2021 | +158.41% | +146.73% | **+158.03%** | +11.3pp |
| 2022 | +210.80% | **+257.97%** | +243.30% | -14.7pp |
| 2023 | +352.89% | +346.14% | +344.81% | -1.3pp |
| 2024 | +151.69% | +191.15% | **+196.79%** | +5.6pp |
| 2025 | +185.14% | +218.03% | **+224.02%** | +6.0pp |
| 2026 YTD (Jan–Apr 10) | +108.79% | +99.72% | **+106.06%** | +6.3pp |
| **7-yr sum (2019–2025)** | **+1,381.11%** | **+1,465.77%** | **+1,470.29%** | **+4.5pp** |

### Key Observations

1. **Net positive swap (+4.65pp over 7 years)** — MSTR wins 5 of 7 years vs the AT pool with CRWD.

2. **MSTR is a Bitcoin-correlated name** — wins strongly in crypto bull years (2020 +10pp, 2021 +10pp, 2024 +7pp, 2025 +8pp) and loses in bear years (2022 -15pp). Saylor's BTC pivot was Aug 2020, so 2019 drag (-14pp) reflects pre-pivot MSTR behavior.

3. **2022 is the main risk** (-15pp) — crypto names suffer in bear markets; CRWD's defensive cybersecurity profile held up better that year.

4. **2026 YTD nearly matches SOA V2** (+98.67% vs +99.08%) — the tariff-driven bear environment hasn't hurt MSTR as much as expected, likely because BTC retains its safe-haven narrative.

5. **7-year total: AT+MSTR leads all pools** — +1,470.29% vs AT +1,465.77% vs SOA V2 +1,381.11%.

### Output Logs

| File | Description |
|------|-------------|
| `active_traded_ticker_list/soa_at_mstr_2019.txt` | AT+MSTR pool — 2019 full output |
| `active_traded_ticker_list/soa_at_mstr_2020.txt` | AT+MSTR pool — 2020 full output |
| `active_traded_ticker_list/soa_at_mstr_2021.txt` | AT+MSTR pool — 2021 full output |
| `active_traded_ticker_list/soa_at_mstr_2022.txt` | AT+MSTR pool — 2022 full output |
| `active_traded_ticker_list/soa_at_mstr_2023.txt` | AT+MSTR pool — 2023 full output |
| `active_traded_ticker_list/soa_at_mstr_2024.txt` | AT+MSTR pool — 2024 full output |
| `active_traded_ticker_list/soa_at_mstr_2025.txt` | AT+MSTR pool — 2025 full output |
| `active_traded_ticker_list/soa_at_mstr_2026.txt` | AT+MSTR pool — 2026 YTD full output |
| `active_traded_ticker_list/tier1_candidates/` | Individual standalone screens for SOFI, MARA, IBIT, RIOT, AVGO, MSTR, SHOP, CVNA, CRWD |

---

## Doubledown Impact Summary

`--doubledown --doubledown-start 5` added to all configs as of 2026-04-12. DD wins every year across all three pools.

| Pool | 7-yr sum (no DD) | 7-yr sum (with DD) | DD lift |
|------|-----------------|-------------------|---------|
| V2 | +1,279.21% | **+1,381.11%** | +101.9pp |
| AT | +1,347.17% | **+1,465.77%** | +118.6pp |
| AT+MSTR | +1,351.82% | **+1,470.29%** | +118.5pp |

Per-year DD delta ranges from **+9pp to +29pp** depending on year and pool. Largest gains in high-volatility years (2020, 2022) where stopouts are frequent and freed capital captures larger subsequent moves. See `dev_plan/double_down_on_winner.md` for full sweep analysis.

---

## Related Findings

| Document | Topic |
|---|---|
| `bearish_reentry/FINDINGS.md` | BRE feature deep-dive, annual delta vs baseline, reversal vs BRE independent comparison |
| `bearish_reentry/OVERVIEW.md` | BRE implementation design, config parameters, mutual exclusion with reversal |
| `multiple_trading_windows/SUMMARY.md` | M1/M2/A1/A2 window comparison, compound growth projections |
| `FINDINGS.md` | Regime filter, ticker pool, weight sweep, top-N findings |
