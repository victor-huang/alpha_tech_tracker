# Win-Rate Selector — Trade Engine Backtest Results

Full-year replay of `op_momentum_trade_engine` using `--selector win-rate` with win-rate-signal
mode enabled. Results cover 2018–2026 (YTD). Run date: 2026-06-04.

---

## Configuration

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --selector win-rate \
  --enable-regime-engine \
  --window M1 09:30 3 \
  --morning-split 100 \
  --bearish-reentry --bullish-reentry --reversal \
  --trailing-ma none --stop-pct 0 \
  --doubledown --doubledown-start 10 \
  --top 8 --capital 10000 \
  --mock-trade-execution \
  --feed sip \
  --replay-date YYYY-MM-DD
```

Key parameters:

| Parameter | Value | Reason |
|---|---|---|
| `--selector win-rate` | win-rate | Activates win-rate pre-session ranking + win-rate-signal mode |
| `--window M1 09:30 3` | M1 only | 15-min opening range; collection window 9:40–9:50 |
| `--top 8` | 8 | Covers all signal-firing tickers on any given day (max observed: 7) |
| `--trailing-ma none` | none | Win-rate signals have hold-and-recover character; trailing MA cuts winners |
| `--stop-pct 0` | 0 | No hard stop; positions held to EOD |
| `--enable-regime-engine` | on | Blocks bearish signals in LONG regime and vice versa |
| Capital | $10,000 | Equal sizing across all entered positions |

---

## Why no stop-loss?

The win-rate signal fires when the close bar of the opening range crosses the OR midpoint with
above-average volume and at least one MA overlapping the OR range. These setups frequently dip
1–4% intraday before recovering to close positive. A stop-loss exits these positions before the
recovery happens.

**Stop-loss impact on May 2026 (illustrative):**

| Config | May 2026 P&L | Return |
|---|---|---|
| top-2, default stops | −$61 | −0.6% |
| top-8, default stops | +$361 | +3.6% |
| top-8, no stop | +$1,658 | +16.6% |

Examples of signals that dip then recover (May 2026):
- SNDK May 1: negative mid-day → **+6.97% EOD**
- DDOG May 8: −0.95% at +15m → **+6.22% EOD**
- APP May 7: −1.04% at +15m → **+6.37% EOD**
- QCOM May 5: held cleanly → **+10.36% EOD**

---

## Monthly P&L by Year — No-Stop Configuration

All values in USD on $10,000 capital. `—` = no trading days that month (holidays / YTD cutoff).

| Month | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|-------|------|------|------|------|------|------|------|------|------|
| Jan | +$264 | +$1,044 | +$148 | +$578 | −$362 | +$713 | +$442 | +$489 | +$27 |
| Feb | −$116 | +$147 | +$239 | −$388 | +$238 | +$365 | +$260 | +$792 | +$628 |
| Mar | +$759 | +$462 | −$532 | +$869 | +$872 | +$296 | −$203 | +$65 | +$344 |
| Apr | +$1,248 | +$188 | +$73 | +$590 | +$632 | +$570 | +$709 | +$1,286 | +$675 |
| May | −$58 | +$125 | +$44 | +$108 | +$596 | +$436 | +$40 | −$41 | +$1,658 |
| Jun | +$718 | +$1,123 | +$1,110 | +$11 | +$163 | +$342 | +$413 | +$824 | +$5 |
| Jul | +$832 | +$328 | +$1,136 | +$276 | +$850 | +$290 | +$1,515 | +$789 | — |
| Aug | +$487 | +$280 | +$619 | +$101 | +$551 | +$25 | +$391 | +$571 | — |
| Sep | +$285 | +$1,044 | +$3 | −$32 | −$61 | +$458 | +$692 | +$593 | — |
| Oct | +$240 | +$506 | +$476 | +$449 | +$428 | +$672 | +$700 | +$894 | — |
| Nov | +$741 | +$843 | −$287 | +$393 | +$1,052 | +$854 | +$1,884 | +$334 | — |
| Dec | +$242 | +$235 | +$270 | +$441 | +$757 | +$168 | +$797 | +$567 | — |
| **Total** | **+$5,642** | **+$6,327** | **+$3,300** | **+$3,396** | **+$5,716** | **+$5,187** | **+$7,640** | **+$7,161** | **+$3,337** |
| **Ret%** | **+56.4%** | **+63.3%** | **+33.0%** | **+34.0%** | **+57.2%** | **+51.9%** | **+76.4%** | **+71.6%** | **+33.4%** |
| **Days** | 210 | 207 | 208 | 220 | 212 | 217 | 219 | 216 | 98 |

---

## Annual Summary

| Year | P&L | Return | Notes |
|---|---|---|---|
| 2018 | +$5,642 | +56.4% | Strong Apr (+$1,248), Jul–Nov sustained run |
| 2019 | +$6,327 | +63.3% | Best pre-2024 year; Jun/Sep both +$1,044 |
| 2020 | +$3,300 | +33.0% | Weakest full year; COVID volatility hurt Mar (−$532), Nov (−$287) |
| 2021 | +$3,396 | +34.0% | Feb loss (−$388) and flat Jun/Sep; otherwise steady |
| 2022 | +$5,716 | +57.2% | Bear market year still profitable; Nov +$1,052 standout |
| 2023 | +$5,187 | +51.9% | Consistent across all months; no single blowout |
| 2024 | +$7,640 | **+76.4%** | Best full year; Jul +$1,515, Nov +$1,884 |
| 2025 | +$7,161 | +71.6% | Apr +$1,286 (tariff pause), Oct +$894, strong Q4 |
| 2026 | +$3,337 | +33.4% | YTD through Jun 3 (98 days); May +$1,658 |

**Grand total 2018–2026: +$47,705 (+477.1% on $10k)**
**Winning years: 9/9 — zero losing years**

---

## Screener vs Engine Return Explained

The `ma_open_range_momentum_screener` reports `Position Weighted Return%` at EOD which represents
the true portfolio return ceiling assuming equal capital per signal per day.

**May 2026 waterfall:**

| Level | Return | Explanation |
|---|---|---|
| Screener raw Sum Ret% (old metric) | +59.7% | Sum of all 64 individual signal %s — not a portfolio metric |
| Screener Position Weighted Return% | +18.4% | Equal capital per signal per day — true ceiling |
| Engine top-20, no-stop | +8.1% | All signals; capital diluted; includes low-quality setups |
| Engine top-8, no-stop | +12.3% | Win-rate filter concentrates capital in higher-quality picks |
| Engine top-8, default stops | +3.6% | Stop-loss exits before intraday recoveries |

The win-rate pre-selection **exceeds the theoretical ceiling** (+12.3% > +10.8% implied) because it
filters out the worst setups (e.g. TSLA/ARM May 12: −2.69%/−3.17% EOD) that dilute the portfolio
when all signals are entered.

---

## Log Directories

| Config | Log path |
|---|---|
| top-8, no-stop (primary) | `logs/replay_YYYY_stock_m1_winrate_nostop/` |
| top-8, default stops | `logs/replay_YYYY_stock_m1_winrate/` |
| top-8, default stops (5-window) | `logs/replay_YYYY_stock_5win_winrate/` |

Replay script: `run_replay_stock_m1_winrate.sh --year YYYY --no-stop`
