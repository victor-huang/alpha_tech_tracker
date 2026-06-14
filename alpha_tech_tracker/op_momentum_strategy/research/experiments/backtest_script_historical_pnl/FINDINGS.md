# Backtest Script Historical P&L — 5-Window Stock Strategy

## Configuration

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 \
  --window M1 09:30 3 \
  --window A1 10:00 3 \
  --window A2 11:45 2 \
  --window A3 13:15 1 \
  --window A4 15:15 1 \
  --morning-split 100 \
  --doubledown --doubledown-start 10 \
  --reversal --bullish-reentry --bearish-reentry \
  --feed sip \
  --start YYYY-01-01 --end YYYY-12-31
```

**Key parameters:**
- Capital: $10,000 per day (no-compound — each day resets to $10k)
- Top-2 tickers per window, rank-weighted 60%/40%
- Opening range: 3-bar (15 min) for M1 and A1, 2-bar for A2, 1-bar for A3/A4
- Sub-trades: reversal, bearish re-entry, bullish re-entry all enabled
- Double-down add-on starting at bar 10
- Feed: SIP

**Note:** 2015 produced zero trades. The 60-day rolling scorer needs prior trade history; with no cache before 2016 there is nothing to score tickers from.

Per-year log files are saved alongside this document.

---

## Annual Summary (no-compound, $10k/day)

| Year | Trades | Win Rate | Total P&L | Return | Avg/day |
|------|--------|----------|-----------|--------|---------|
| 2016 | 1,806 | 38% | +$10,766 | +108% | +$43 |
| 2017 | 1,860 | 39% | +$14,940 | +149% | +$60 |
| 2018 | 1,866 | 40% | +$12,615 | +126% | +$50 |
| 2019 | 1,926 | 40% | +$13,634 | +136% | +$54 |
| 2020 | 1,837 | 41% | +$23,848 | +238% | +$94 |
| 2021 | 1,953 | 43% | +$17,287 | +173% | +$69 |
| 2022 | 1,862 | 40% | +$27,308 | +273% | +$109 |
| 2023 | 1,941 | 43% | +$32,872 | +329% | +$131 |
| 2024 | 1,952 | 44% | +$19,827 | +198% | +$79 |
| 2025 | 1,983 | 44% | +$22,441 | +224% | +$90 |
| 2026 YTD* | 701 | 48% | +$12,447 | +124% | +$141 |

*2026 YTD through 2026-05-08 (88 trading days)

---

## Per-Window Breakdown (Return % on $10k)

| Window | Start/Bars | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|--------|-----------|------|------|------|------|------|------|------|------|------|------|----------|
| M1 | 09:30 / 3 | +64% | +73% | +43% | +44% | +116% | +63% | +112% | +126% | +55% | +69% | +67% |
| A1 | 10:00 / 3 | +14% | +27% | +24% | +31% | +39% | +30% | +27% | +52% | +44% | +43% | +16% |
| A2 | 11:45 / 2 | +11% | +27% | +28% | +32% | +16% | +16% | +52% | +59% | +34% | +45% | +15% |
| A3 | 13:15 / 1 | +14% | +10% | +13% | +15% | +38% | +37% | +25% | +65% | +33% | +33% | +11% |
| A4 | 15:15 / 1 | +5% | +13% | +18% | +14% | +29% | +26% | +57% | +27% | +32% | +34% | +16% |

---

## Trade Engine Replay Summary (no-compound, $10k/day)

Full live-engine replay using `op_momentum_trade_engine run --replay-date` with identical parameters. Replay includes fractional share sizing and full sub-trade execution (reversal, BRE, BRU, DD). Log dirs: `logs/replay_{YEAR}_stock_5win/`.

| Year | Days | Total P&L | Return | vs Backtest |
|------|------|-----------|--------|-------------|
| 2019 | 252 | +$14,209 | +142% | +6 pp |
| 2020 | 253 | +$24,033 | +240% | +2 pp |
| 2021 | 252 | +$18,689 | +187% | +14 pp |
| 2022 | 251 | +$29,538 | +295% | +22 pp |
| 2023 | 250 | +$34,683 | +347% | +18 pp |
| 2024 | 252 | +$20,492 | +205% | +7 pp |
| 2025 | 250 | +$23,161 | +232% | +8 pp |
| 2026 YTD* | 88 | +$12,622 | +126% | +2 pp |

*2026 YTD through 2026-05-08

The replay consistently exceeds the batch backtest by **+2 to +22 pp** per year, driven by fractional share sizing capturing more precise position sizes and sub-trade capital recycling computed at the per-bar level rather than approximated.

---

## Findings

### The strategy has never had a losing year (2016–2026)

Across 10 full years plus 2026 YTD, every year is profitable. Minimum full-year return: **+108% (2016)**. Maximum: **+329% (2023)**. No individual window has posted a negative annual return in any year.

### Returns have scaled up over time

- **2016–2019 average:** +130%/year
- **2020–2025 average:** +239%/year

The likely driver is the ticker pool maturing toward higher-volatility momentum names (APP, CVNA, CRDO, MSTR, etc.) that emerged or grew in prominence post-2019. The strategy's edge scales with OR range size and intraday volatility.

### Win rate has drifted upward

| Period | Avg Win Rate |
|--------|-------------|
| 2016–2019 | 39–40% |
| 2020–2023 | 41–43% |
| 2024–2026 | 44–48% |

The 2026 YTD win rate of 48% is the highest in the sample. Combined with the highest daily average (+$141/day), 2026 is pacing to be a top-3 year if the regime holds.

### M1 is the primary engine

M1 drives the bulk of the return in every year, ranging from **+43% (2018)** to **+126% (2023)**. When M1 has a weak year (2018/2019: ~+43–44%), the afternoon windows provide a meaningful cushion (+83–93% combined). When M1 fires well (2020, 2022, 2023), the afternoon windows push total return into 200–300%+ territory.

### A1 (10:00/3) is the most consistent sequential window

A1 has been positive every year, ranging **+14% to +52%**. It is the most reliable of the four sequential windows and acts as the first capital recycler after M1.

### A2 (11:45/2) has the widest year-to-year range

A2 ranged from **+11% (2016)** to **+59% (2023)**. It tends to shine in volatile/trending years (2022: +52%, 2023: +59%, 2025: +45%) and underperforms in low-volatility years (2016: +11%, 2020/2021: +16%).

### A3 and A4 are small but never a drag

A3 (13:15/1): **+10% to +65%** — best year was 2023, weakest was 2017.
A4 (15:15/1): **+5% to +57%** — best year was 2022, weakest was 2016. Notably A4 was only +5% in 2016, suggesting late-afternoon momentum was very thin that year.

### 2022 and 2023 were the golden years

2022 (+273%) showed the strategy works in bear/volatile markets — A2 and A4 were standouts. 2023 (+329%) showed it works in recovery rallies — A3 alone was +65%. Together that is **+602% across two years** on a $10k no-compound basis.
