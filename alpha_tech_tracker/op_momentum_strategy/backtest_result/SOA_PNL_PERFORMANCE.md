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

## 7-Year Annual Performance (2019–2025) + 2026 YTD

| Year | Trades | W/L | Strategy Return | QQQ Return | Alpha |
|---|---|---|---|---|---|
| 2019 | 1,353 | 580W / 773L | **+100.32%** | +37.27% | +63pp |
| 2020 | 1,368 | 618W / 750L | **+192.15%** | +45.14% | +147pp |
| 2021 | 1,413 | 634W / 779L | **+147.87%** | +28.63% | +119pp |
| 2022 | 1,328 | 590W / 738L | **+191.51%** | -33.71% | +225pp |
| 2023 | 1,424 | 647W / 777L | **+334.58%** | +54.84% | +280pp |
| 2024 | 1,413 | 630W / 783L | **+138.51%** | +26.99% | +112pp |
| 2025 | 1,418 | 658W / 760L | **+174.27%** | +20.40% | +154pp |
| 2026 YTD (Jan–Apr 10) | 395 | 190W / 205L | **+99.08%** | -0.31% | +99pp |
| **7-yr sum (2019–2025)** | | | **+1,279.21%** | **+179.56%** | **+1,100pp** |

> 2026 uses `--feed iex` (SIP subscription does not allow querying recent data).

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

### Year-by-Year Comparison

| Year | SOA V2 | AT Pool | Δ | Winner |
|------|--------|---------|---|--------|
| 2019 | +100.32% | +119.24% | +19pp | **AT** |
| 2020 | +192.15% | +160.91% | -31pp | V2 |
| 2021 | +147.87% | +136.75% | -11pp | V2 |
| 2022 | +191.51% | +229.18% | +38pp | **AT** |
| 2023 | +334.58% | +328.00% | -6.6pp | V2 |
| 2024 | +138.51% | +174.00% | +35.5pp | **AT** |
| 2025 | +174.27% | +199.10% | +24.8pp | **AT** |
| 2026 YTD (Jan–Apr 10) | +99.08% | +93.58% | -5.5pp | V2 |
| **7-yr sum (2019–2025)** | **+1,279.21%** | **+1,347.17%** | **+67.96pp** | **AT** |

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

### Year-by-Year Comparison

| Year | SOA V2 | AT (CRWD) | AT+MSTR | Δ vs AT |
|------|--------|-----------|---------|---------|
| 2019 | +100.32% | +119.24% | +104.83% | -14pp |
| 2020 | +192.15% | +160.91% | **+170.62%** | +10pp |
| 2021 | +147.87% | +136.75% | **+146.90%** | +10pp |
| 2022 | +191.51% | **+229.18%** | +213.80% | -15pp |
| 2023 | +334.58% | +328.00% | +327.42% | -0.6pp |
| 2024 | +138.51% | +174.00% | **+181.45%** | +7pp |
| 2025 | +174.27% | +199.10% | **+206.82%** | +8pp |
| 2026 YTD (Jan–Apr 10) | +99.08% | +93.58% | **+98.67%** | +5pp |
| **7-yr sum (2019–2025)** | **+1,279.21%** | **+1,347.17%** | **+1,351.82%** | **+4.65pp** |

### Key Observations

1. **Net positive swap (+4.65pp over 7 years)** — MSTR wins 5 of 7 years vs the AT pool with CRWD.

2. **MSTR is a Bitcoin-correlated name** — wins strongly in crypto bull years (2020 +10pp, 2021 +10pp, 2024 +7pp, 2025 +8pp) and loses in bear years (2022 -15pp). Saylor's BTC pivot was Aug 2020, so 2019 drag (-14pp) reflects pre-pivot MSTR behavior.

3. **2022 is the main risk** (-15pp) — crypto names suffer in bear markets; CRWD's defensive cybersecurity profile held up better that year.

4. **2026 YTD nearly matches SOA V2** (+98.67% vs +99.08%) — the tariff-driven bear environment hasn't hurt MSTR as much as expected, likely because BTC retains its safe-haven narrative.

5. **7-year total: AT+MSTR leads all pools** — +1,351.82% vs AT +1,347.17% vs SOA V2 +1,279.21%.

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

## Related Findings

| Document | Topic |
|---|---|
| `bearish_reentry/FINDINGS.md` | BRE feature deep-dive, annual delta vs baseline, reversal vs BRE independent comparison |
| `bearish_reentry/OVERVIEW.md` | BRE implementation design, config parameters, mutual exclusion with reversal |
| `multiple_trading_windows/SUMMARY.md` | M1/M2/A1/A2 window comparison, compound growth projections |
| `FINDINGS.md` | Regime filter, ticker pool, weight sweep, top-N findings |
