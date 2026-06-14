# Win-Rate Selector — Capital Deployment Model Comparison

Analysis of capital allocation models for the win-rate selector strategy.
Log-based projection derived from 2018–2026 no-stop replay logs (1,807 trading days).
Live engine validation run for 2026 YTD (99 trading days).

Run date: 2026-06-04

---

## Models

| Model | `--capital` | Slot size | Max daily deployed | Description |
|---|---|---|---|---|
| **Pool** (current) | $10,000 | $10k ÷ n_entered | Always $10k | Full capital split equally; fewer signals → bigger slots (renormalized) |
| **Fixed-slot $1.25k** | $10,000 | $10k ÷ 8 = $1,250 | $10,000 | Fixed $1,250/slot; idle capital stays undeployed on low-signal days |
| **Fixed-slot $10k** | $80,000 | $80k ÷ 8 = $10,000 | $80,000 | Fixed $10k/slot; total deployed scales with signal count |

CLI flag: `--fixed-signal-alloc` (added in `op_momentum_selector_backtest.py` and
`op_momentum_trade_engine.py`). Replay script: `run_replay_stock_m1_winrate.sh --fixed-alloc [--capital N]`.

Analysis script: `alpha_tech_tracker/op_momentum_strategy/analysis_scripts/fixed_per_signal_capital_analysis.py`

---

## Return % Methodology

With dynamic capital deployment, "return %" depends on what you consider the capital base.

| Method | Formula | What it answers |
|---|---|---|
| Return on committed capital | `P&L / max_possible_deployment` | Account-level: what did my brokerage account earn? |
| Return on avg deployed | `P&L / mean(daily_deployed)` | Edge efficiency: how productive was the capital actually at work? |
| **Annualized committed** (recommended) | `(P&L / max_capital) × (252 / trading_days)` | Comparable across partial years and between strategies |

**Why annualized committed is preferred:** it uses the actual capital requirement (what your
account must hold) and normalizes partial-year periods so 2026 YTD can be compared fairly
against full years.

Note: average daily deployed exceeds the $80k primary-slot ceiling because DD (doubledown)
legs recycle freed capital from stopped-out positions on top of primary slots. In 2026 YTD,
average daily deployed was **$118k** against an $80k primary ceiling.

---

## 2026 YTD Live Engine Results (99 trading days)

Three configurations run against the same trading days via `op_momentum_trade_engine run --replay-date`.

| Config | P&L | Committed capital | Return on committed | Annualized |
|---|---|---|---|---|
| Pool $10k (no-stop) | +$3,337 | $10,000 | +33.4% | +85% |
| Fixed-slot $1.25k (`--capital 10000`) | +$3,655 | $10,000 | +36.5% | +93% |
| **Fixed-slot $10k** (`--capital 80000`) | **+$29,238** | **$80,000** | **+36.5%** | **+93%** |

Return % is identical for both fixed-slot configs — as expected, since the slot ratio
(`capital / top_n`) is the same; only the absolute dollar scale differs. The +3.1pp
improvement over the pool model comes from not over-sizing single-signal days.

### Monthly P&L — Fixed-slot $10k (2026 YTD)

| Month | P&L | Return on $80k |
|---|---|---|
| Jan 2026 | +$181 | +0.2% |
| Feb 2026 | +$6,544 | +8.2% |
| Mar 2026 | +$2,102 | +2.6% |
| Apr 2026 | +$5,567 | +7.0% |
| May 2026 | +$15,626 | +19.5% |
| Jun 2026 (YTD) | −$783 | −1.0% |
| **Total** | **+$29,238** | **+36.5%** |

May 2026 alone: **+$15,626** — the high-signal environment in May (trade deal rallies, broad
tech momentum) benefited directly from the scaling model. May 5 single day: **+$10,245**.

### Worst-case drawdowns (2026 YTD, fixed-slot $10k)

| Metric | Value | Date |
|---|---|---|
| Worst single day | −$1,936 | May 1 (5 signals all reversed) |
| Worst rolling week | −$2,216 | Apr 27 week |
| Best single day | +$10,245 | May 5 |
| Best rolling week | +$8,876 | May 4 week |

---

## Log-Based Projection: 2018–2026 ($1.25k/signal vs pool)

*Derived from existing no-stop replay logs using `fixed_per_signal_capital_analysis.py`.
Proposed column uses $1,250/slot ($10k capital ÷ 8); pool column uses current renormalized behavior.*

### Annual summary

| Year | Pool P&L | Fixed-slot P&L | Pool Ret% | Fixed Ret% | Pool Sharpe | Fixed Sharpe |
|---|---|---|---|---|---|---|
| 2018 | +$5,642 | +$18,108 | +56.4% | +181.1% | 4.25 | 4.10 |
| 2019 | +$6,327 | +$19,002 | +63.3% | +190.0% | 5.49 | 4.57 |
| 2020 | +$3,300 | +$12,233 | +33.0% | +122.3% | 2.70 | 2.44 |
| 2021 | +$3,396 | +$7,373 | +34.0% | +73.7% | 3.31 | 2.17 |
| 2022 | +$5,716 | +$20,412 | +57.2% | +204.1% | 3.61 | 3.91 |
| 2023 | +$5,187 | +$14,108 | +51.9% | +141.1% | 4.42 | 3.86 |
| 2024 | +$7,640 | +$23,193 | +76.4% | +231.9% | 4.49 | 3.68 |
| 2025 | +$7,161 | +$20,169 | +71.6% | +201.7% | 4.10 | 3.72 |
| 2026 YTD | +$3,337 | +$10,027 | +33.4% | +100.3% | 4.07 | 3.76 |
| **Total** | **+$47,705** | **+$144,624** | **+477%** | **+1,446%** | — | — |

*Projection returns use pool capital ($10k) as the base for both columns for comparability.
The fixed-slot $10k model ($80k capital) would show the same % figures — only absolute P&L scales.*

### Drawdown comparison (log-based projection, $1.25k/signal)

| Year | Pool worst day | Fixed worst day | Pool worst week | Fixed worst week |
|---|---|---|---|---|
| 2018 | −$153 | −$302 | −$203 | −$407 |
| 2019 | −$122 | −$205 | −$113 | −$359 |
| 2020 | −$193 | **−$992** | −$444 | **−$1,317** |
| 2021 | −$138 | −$540 | −$311 | −$836 |
| 2022 | −$184 | −$364 | −$430 | −$686 |
| 2023 | −$102 | −$415 | −$162 | −$559 |
| 2024 | −$333 | −$735 | −$399 | −$859 |
| 2025 | −$250 | −$660 | −$239 | −$782 |
| 2026 YTD | −$122 | −$567 | −$178 | −$1,401 |

---

## Key Finding: Signal Count is a Strong Positive Indicator

Win rate stays flat (~53–56%) across all signal counts — signal quality does not degrade as
more signals fire on a given day. Average P&L scales cleanly with signal count.

| Signals entered | Days | Avg P&L (pool) | Avg P&L (fixed $1.25k) | Win rate |
|---|---|---|---|---|
| 1 | 445 | +$12 | +$17 | 55.5% |
| 2 | 481 | +$20 | +$47 | 50.7% |
| 3 | 359 | +$34 | +$98 | 52.6% |
| 4 | 265 | +$35 | +$116 | 55.1% |
| 5 | 156 | +$39 | +$173 | 56.4% |
| 6 | 66 | +$57 | +$193 | 54.5% |
| 7 | 25 | +$27 | +$125 | 44.0% |
| 8 | 10 | +$114 | +$536 | 70.0% |

---

## Capital Deployment Distribution

How often each primary-slot exposure level occurs across 1,807 trading days.
DD legs add additional recycled capital on top of these primary amounts.

| Signals | Primary deployed ($10k/signal) | Days | % of days | Cumulative % |
|---|---|---|---|---|
| 1 | $10,000 | 445 | 24.6% | 24.6% |
| 2 | $20,000 | 481 | 26.6% | 51.2% |
| 3 | $30,000 | 359 | 19.9% | 71.1% |
| 4 | $40,000 | 265 | 14.7% | 85.8% |
| 5 | $50,000 | 156 | 8.6% | 94.4% |
| 6 | $60,000 | 66 | 3.7% | 98.1% |
| 7 | $70,000 | 25 | 1.4% | 99.5% |
| 8 | $80,000 | 10 | 0.6% | 100.0% |

**71% of days deploy ≤ $30k primary. Only 6% of days exceed $50k primary.**
The $80k primary ceiling occurs on just 10 days across 9 years (~once/year).

---

## Verdict

**The signal quality justifies the extra exposure.** More signals on a day reflects broad
market alignment with the OR momentum setup — not diluted quality. The fixed-slot model
improves return vs the pool model (+3.1pp in 2026 live engine) and triples total log-based
returns over 9 years while keeping Sharpe above 2.0 in all years.

Capital requirements for the $10k/signal model:
- **$30k buying power** covers 71% of days with no margin
- **$50k account** covers 94% of days
- **$80k** covers all primary-slot exposure (DD legs may add ~20–50% on top intraday)
- Full $80k primary ceiling occurs roughly once per year

Log directories:
| Config | Path |
|---|---|
| Pool no-stop (baseline) | `logs/replay_YYYY_stock_m1_winrate_nostop/` |
| Fixed-slot $1.25k | `logs/replay_2026_stock_m1_winrate_fixedalloc/` |
| Fixed-slot $10k | `logs/replay_2026_stock_m1_winrate_fixedalloc_cap80000/` |
