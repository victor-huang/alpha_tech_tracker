# Ticker Set Selection Experiment Plan

## Objective

Test whether a structured 50/50 QQQ + Russell 2000 ticker pool (drawn from the prior year's most active names) improves or changes the strategy's return characteristics vs. the current hand-curated `DEFAULT_TICKERS` and `ACTIVELY_TRADE_TICKERS` lists.

---

## Base Engine Config (fixed across all tests)

```bash
--selector win-rate
--enable-regime-engine
--window M1 09:30 3
--trailing-ma none --stop-pct 0
--regime-hold
--top 8 --capital 80000
--mock-trade-execution
--fixed-signal-alloc
--feed sip
--replay-date YYYY-MM-DD
```

Engine: `alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine`
Script: `run_replay_m1_winrate_regimehold_cap80k.sh`

---

## Ticker Pool Construction Rule

### Pool size
- 10 tickers from QQQ (top 10 most active in QQQ, prior year)
- 10 tickers from Russell 2000 (top 10 most active in Russell 2000, prior year)
- Combined pool of 20 tickers passed via `--tickers`

### "Most active" definition
Rank by **average daily dollar volume** (price × volume) over the prior calendar year.  
Use Alpaca SIP 5-min bar data already cached — aggregate to daily and sort descending.

### Year-mapping rule

| Testing year | Ticker pool drawn from |
|---|---|
| 2026 | 2025 most active |
| 2025 | 2024 most active |
| 2024 | 2023 most active |
| 2023 | 2022 most active |
| 2022 | 2021 most active |
| 2021 | 2020 most active |
| 2020 | 2019 most active |
| 2019 | 2018 most active |
| 2018 | 2017 most active |

> Russell 2000 members change each year; use the index membership for the prior year when computing the ranking, then select the top 10.

---

## Candidate Ticker Sets by Year

These are starting candidates — validate against actual prior-year dollar-volume rankings before locking in.

| Test Year | QQQ candidates (prior yr) | Russell 2000 candidates (prior yr) |
|---|---|---|
| 2026 | NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX | SMCI RIVN SOFI PLUG RIOT MARA UPST JOBY ACHR HIMS |
| 2025 | NVDA TSLA META MSFT AMZN AAPL AMD AVGO SMCI GOOGL | RIVN SOFI PLUG MARA RIOT UPST SPCE OPEN CLOV WKHS |
| 2024 | NVDA TSLA META MSFT AMZN AAPL AMD AVGO GOOGL NFLX | RIVN SOFI PLUG MARA RIOT SPCE GME AMC UPST CLOV |
| 2023 | TSLA NVDA META AMZN MSFT AAPL AMD GOOGL AVGO SMCI | RIVN SOFI PLUG MARA RIOT GME AMC SPCE CLOV OPEN |
| 2022 | TSLA NVDA META AMZN MSFT AAPL AMD GOOGL AVGO NFLX | RIVN SOFI PLUG MARA RIOT GME AMC SPCE CLOV LCID |
| 2021 | TSLA NVDA AMZN MSFT AAPL META AMD GOOGL NFLX QCOM | GME AMC SOFI PLUG MARA RIOT SPCE CLOV WKHS RIDE |
| 2020 | TSLA AMZN MSFT AAPL NVDA NFLX GOOGL AMD META INTC | PLUG FUEL NKLA NIO SPCE MARA RIOT WKHS GME BLNK |
| 2019 | AMZN MSFT AAPL NVDA GOOGL NFLX META TSLA INTC QCOM | ROKU TLRY CGC AAOI ONEM BYND WDC SNAP LYFT PINS |
| 2018 | AMZN MSFT AAPL NVDA GOOGL NFLX TSLA INTC CSCO QCOM | GBT HMHC LADR CDNA TLYS NVAX MGTX ODP KRTX ALRM |

> **Before each year's run:** verify the above candidates are still reasonable via `fetch_bars` spot-check. Replace any ticker with insufficient bar coverage (< 60% of trading days with ≥ 70 bars).

---

## Phase 1 — Initial Characteristics (2026, Feb + May)

**Goal:** Quickly validate whether the QQQ/R2K pool produces sensible behavior before committing to full-year runs.

### Steps

1. **Identify 2026 ticker pool** (using 2025 actives — see table above).
2. **Warm bar cache**: run `op_momentum_selector_backtest.py` for all 20 tickers from `2025-11-01` through `2026-06-06` (year + 60-day warmup). This populates `market_data/cache/sip_5min_*` so the parallel replay doesn't hit the Alpaca API on every date.
3. **Run Feb 2026** (2026-02-03 → 2026-02-28):
   ```bash
   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026
   # Then filter summary to Feb dates, or run with a date-range variant
   ```
4. **Run May 2026** (2026-05-01 → 2026-05-30).
5. **Review metrics**: monthly P&L, DW-Sharpe, utilization, win-rate vs current `ACTIVELY_TRADE_TICKERS` baseline.
6. **Decision gate**: if Feb+May look directionally positive, continue to Phase 2; otherwise adjust pool construction rules.

### What to look for
- Is utilization ≥ 50%? (If pool has too many illiquid R2K names, selector skips days.)
- Win-rate selector score stability — no ticker dominating with thin history.
- Monthly P&L sign and magnitude relative to `DEFAULT_TICKERS` baseline.

---

## Phase 2 — Full Year 2026 Confirmation

**Goal:** Confirm Phase 1 characteristics hold across all market regimes (bull, bear, chop, earnings seasons).

### Steps

1. **Warm bar cache**: run `op_momentum_selector_backtest.py` for the 20-ticker pool from `2025-11-01` → EOY 2026.
2. **Run full 2026** via the existing script:
   ```bash
   ./run_replay_m1_winrate_regimehold_cap80k.sh --year 2026
   ```
3. **Baseline comparison**: run same year with `ACTIVELY_TRADE_TICKERS` (19 tickers, already tested).
4. **Review**: monthly table, DW-Sharpe, utilization, RODC.
5. **Decision gate**: finalize the pool-construction rule (or adjust R2K ratio, size, or activity metric) before moving to historical years.

---

## Phase 3 — Historical Walkforward (2018–2025)

Run one year at a time, starting from the most recent (2025) and working backward to 2018. Review each year's result before proceeding.

### Per-Year Workflow

```
Step A  Determine ticker pool (prior-year top 10 QQQ + top 10 R2K)
Step B  Cache bars:  year-start - 60 days  →  year-end
        (e.g., for 2025: 2024-11-01 → 2025-12-31)
Step C  Run backtest in max parallel 20:
        ./run_replay_m1_winrate_regimehold_cap80k.sh --year YYYY
Step D  Print summary (--summary flag)
Step E  Review monthly P&L, DW-Sharpe, utilization
Step F  Note any pool-construction issues (coverage gaps, illiquid names)
Step G  Optionally adjust rules, then re-run before proceeding to next year
```

### Bar Caching Command

There is no standalone cache-only command. Bar data is cached automatically as a side
effect of `fetch_bars()`, which is called internally by `op_momentum_selector_backtest.py`.
Running a full-year selector backtest before the replay warms the SIP cache for all tickers
in one sequential API fetch — so the 20-parallel replay processes all hit the local cache
instead of hitting the Alpaca API concurrently.

```bash
# Example for 2025 (covers year + 60 days warmup)
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --tickers NVDA TSLA META AMZN MSFT AAPL AMD AVGO GOOGL NFLX \
            SMCI RIVN SOFI PLUG RIOT MARA UPST JOBY ACHR HIMS \
  --start 2024-11-01 --end 2025-12-31 \
  --feed sip
```

Cache files are written to `market_data/cache/sip_5min_{ticker}_{start}_{end}.json`.
`_stitch_cache()` assembles long ranges from existing per-year files automatically —
if a prior year's cache already exists for a ticker, it will not be re-fetched.

> Adjust `--tickers`, `--start`, `--end` per the year-mapping table. Run this once
> before kicking off the day-by-day replay to avoid per-day API fetches under parallel load.

### Year Schedule

| Year | Ticker pool source | Cache window | Status |
|---|---|---|---|
| 2025 | 2024 actives | 2024-11-01 → 2025-12-31 | pending |
| 2024 | 2023 actives | 2023-11-01 → 2024-12-31 | pending |
| 2023 | 2022 actives | 2022-11-01 → 2023-12-31 | pending |
| 2022 | 2021 actives | 2021-11-01 → 2022-12-31 | pending |
| 2021 | 2020 actives | 2020-11-01 → 2021-12-31 | pending |
| 2020 | 2019 actives | 2019-11-01 → 2020-12-31 | pending |
| 2019 | 2018 actives | 2018-11-01 → 2019-12-31 | pending |
| 2018 | 2017 actives | 2017-11-01 → 2018-12-31 | pending |

---

## Review Checklist per Year

After each `--summary` output, record:

- [ ] Year, ticker pool (list 20 tickers)
- [ ] Monthly P&L table
- [ ] Full-year total $ and % on $80k
- [ ] DW-Sharpe
- [ ] Capital utilization %
- [ ] Mean daily RODC
- [ ] Notable months (outlier good/bad)
- [ ] Pool issues (tickers with < 50% bar coverage)
- [ ] Rule changes made before next year's run

Target file: `backtest_result/ticker_set_selection/YYYY_results.md`

---

## Tooling Gaps to Address

Before Phase 3 can run cleanly, confirm or build:

1. **Bar warm-up script**: no standalone cache command exists — warming is done via `op_momentum_selector_backtest.py` for the full year range. Consider wrapping this in a `cache_bars_for_year.sh` helper that takes `--year` and `--tickers` and runs the backtest purely for its caching side-effect.
2. **Coverage checker**: quick script to count days with ≥ 70 bars per ticker, flag any < 60% coverage so we can swap tickers before the full run.
3. **Ticker pool validator**: helper to pull prior-year avg dollar volume from cached bars and rank the candidates, confirming the table above.

---

## Success Criteria

- QQQ/R2K pool produces DW-Sharpe ≥ current `ACTIVELY_TRADE_TICKERS` baseline for at least 6 of 9 years.
- Capital utilization stays ≥ 40% across all years (confirms pool liquidity is adequate).
- No single ticker dominates > 40% of filled trades in any year (confirms pool diversity is working).
