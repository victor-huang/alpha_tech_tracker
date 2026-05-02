---
description: 'Sweep A1/A2/A3 window times and bar counts to find optimal intraday trading windows after new data or backtest logic updates. Tests the current year first, then validates top candidates across all available years.'
---

# Re-optimize Trading Windows

Find the best A1, A2, and A3 window time + bar-count combinations for the confirmed 4-window config. Each window is swept independently with the others fixed.

## Step 0 — Parse arguments

Parse `$ARGUMENTS` for these values:

- **--start-year YYYY** — earliest year for multi-year validation. Default: `2020`.
- **--sweep-year YYYY** — year to run the initial full sweep on. Default: current year (check today's date).
- **--sweep-year-end YYYY-MM-DD** — end date for the sweep year. Default: last day of sweep year (or today if sweep year is current year).
- **--skip-a1** — skip the A1 sweep (A1 already locked).
- **--skip-a2** — skip the A2 sweep (A2 already locked).
- **--skip-a3** — skip the A3 sweep (A3 already locked).
- **--parallel N** — max parallel backtest jobs. Default: `20`.
- **--feed FEED** — market data feed passed to every backtest run. Accepted values: `sip`, `iex`. Default: `sip`. SIP is the authoritative feed for consistency with live engine scoring; use `iex` only if the account lacks SIP access.

Set constants:
```
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker
VENV=~/.pyenv/versions/alpha_tech_tracker/bin/activate
PROJ=/Users/victorhuang/work/alpha_tech_tracker
SCRIPT=alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py
SUMMARY=${PROJ}/alpha_tech_tracker/op_momentum_strategy/backtest_result/multiple_trading_windows/SUMMARY.md
OUTDIR=${PROJ}/backtest_result/window_reoptimize_$(date +%Y_%m_%d)
```

The **locked config** (never changes between runs — `${FEED}` is substituted from the argument):
```
COMMON="--morning-split 100 --bearish-reentry --bullish-reentry --reversal
        --weights 60 40 --doubledown --doubledown-start 10
        --top 2 --capital 10000
        --feed ${FEED}"
```

> **Warning**: Never mix results from different feeds in the same comparison table. If re-running a sweep that was previously run with a different feed, note the feed change in the SUMMARY.md entry and do not compare absolute return figures across feeds.

The **current best windows** (baseline for comparison — update these if prior sweeps changed them):
```
M1 = "09:30 3"
A1 = "10:00 3"   (locked — confirmed best across 7 years)
A2 = "13:15 1"   (locked — confirmed best across 7 years)
A3 = "15:15 1"   (locked — confirmed best across 7 years)
```

Create `$OUTDIR`. Report all resolved parameters before proceeding.

---

## Phase 1 — A1 Window Sweep (skip if `--skip-a1`)

### 1a — Full sweep on sweep year

**Sweep**: 6 start times × 3 bar counts = 18 configs + 1 baseline = 19 jobs.

- **Start times**: `10:00 10:30 11:00 11:30 12:00 12:30`
- **Bar counts**: `1 2 3`
- **Fixed windows**: M1 `09:30/3` → A1 `{sweep}` → A2 `13:15/1` → A3 `15:15/1`
- **Baseline**: M1 `09:30/3` → A1 `13:15/1` → A2 `15:00/1` (old 3-window layout, for reference)

Windows **must** be passed in chronological order in the CLI: `--window M1 ... --window A1 ... --window A2 ... --window A3 ...`

Run all 19 jobs in parallel (respect `--parallel` limit). Save logs to `$OUTDIR/a1_{time}b{bars}_sweep_year.txt` and `$OUTDIR/a1_baseline_sweep_year.txt`.

Wait for all jobs to finish, then parse results:

For each config extract from the log:
- Total return % and P&L (from `TOTAL` line)
- A1 slot: trades, WR, EV/trade, return % (from `PER-WINDOW BREAKDOWN`)

Sort by total return descending and display a ranked table:

```
Rank | Config      | Total% | Δ_vs_base | A1_Ret% | A1_T | A1_WR | A1_EV
-----|-------------|--------|-----------|---------|------|-------|------
```

**Identify the top 5 configs** by total return for multi-year validation.

### 1b — Multi-year validation (top 5 configs)

Run each of the 5 winning A1 configs + baseline across **all years** from `--start-year` through the year before the sweep year. Each year is a separate job. Total jobs = 6 configs × N years (respect `--parallel` limit, batch if needed).

Save logs to `$OUTDIR/a1_{time}b{bars}_{year}.txt`.

Parse and display:
1. **Total returns table** — configs as rows, years as columns
2. **Delta vs baseline table** — same layout, showing pp difference
3. **Average delta** and **negative year count** per config

**Select the best A1** using these criteria (in order):
1. Zero or fewest negative delta years
2. Highest average delta across all years
3. Breaks ties: wins most individual years

Report the chosen A1 config and lock it in for subsequent phases.

---

## Phase 2 — A2 Window Sweep (skip if `--skip-a2`)

Use the A1 winner from Phase 1 (or the locked `A1 = "10:00 3"` if `--skip-a1`).

### 2a — Full sweep on sweep year

**Sweep**: 9 start times × 3 bar counts = 27 configs + 1 baseline = 28 jobs.

- **Start times**: `11:00 11:30 12:00 12:30 13:00 13:15 13:30 14:00 14:30`
- **Bar counts**: `1 2 3`
- **Fixed windows**: M1 `09:30/3` → A1 `{winner}` → A2 `{sweep}` → A3 `15:15/1`
- **Baseline**: same config with A2 = `13:15/1` (current locked A2)

Batch into groups of `--parallel` if > parallel limit. Save to `$OUTDIR/a2_{time}b{bars}_sweep_year.txt`.

Parse and rank identically to Phase 1a (A2 slot stats instead of A1).

**Identify top 3 configs** by total return.

### 2b — Multi-year validation (top 3 configs)

Same process as 1b but for A2. Jobs = 4 configs (3 + baseline) × N years.

**Select the best A2** using the same criteria. A good A2 must:
- Have a high fire rate (trade count close to full year's trading days × 2) — low fire rate means capital is blocked by upstream sub-trades
- Never go negative vs baseline across all years

Report and lock in the chosen A2.

---

## Phase 3 — A3 Window Sweep (skip if `--skip-a3`)

Use A1 and A2 winners from Phases 1–2 (or locked values if skipped).

### 3a — Full sweep on sweep year

**Sweep**: 6 start times × 3 bar counts = 18 configs + 1 baseline = 19 jobs.

- **Start times**: `13:30 14:00 14:30 15:00 15:15 15:30`
- **Bar counts**: `1 2 3`
- **Fixed windows**: M1 `09:30/3` → A1 `{winner}` → A2 `{winner}` → A3 `{sweep}`
- **Baseline**: same config with A3 = `15:15/1` (current locked A3)

Save to `$OUTDIR/a3_{time}b{bars}_sweep_year.txt`.

Parse and rank. **Identify top 3 configs** by total return.

### 3b — Multi-year validation (top 3 configs)

Jobs = 4 configs × N years.

**Select the best A3**. Key heuristic: late windows (15:00+) generally outperform early afternoon A3 because capital hasn't returned from A2 sub-trades before 14:30.

Report and lock in the chosen A3.

---

## Phase 4 — Final Config Validation

Run the **complete confirmed config** (M1 + A1-winner + A2-winner + A3-winner) across all years and collect full per-window stats. Jobs = N+1 years (include sweep year).

Save to `$OUTDIR/final_{year}.txt`.

Collect for each year and each window:
- Trades, WR, EV/trade, return %
- Total return % and P&L

---

## Phase 5 — Document Results in SUMMARY.md

Append a new dated section to `$SUMMARY` with:

### Section structure

```markdown
## Window Re-optimization — {TODAY_DATE}

### Context
- Sweep year: {SWEEP_YEAR} ({SWEEP_YEAR}-01-01 → {SWEEP_YEAR_END})
- Validation years: {START_YEAR} → {SWEEP_YEAR - 1}
- Feed: {FEED} (sip = default; iex if specified via --feed iex)
- Config flags: --reversal --bearish-reentry --bullish-reentry --doubledown --doubledown-start 10 --weights 60 40 --top 2 --capital 10000 --feed {FEED}

### Window Decisions

| Window | Previous | New | Avg Δ | Reasoning |
|--------|----------|-----|-------|-----------|
| A1     | ...      | ... | ...   | ...       |
| A2     | ...      | ... | ...   | ...       |
| A3     | ...      | ... | ...   | ...       |

### Final Confirmed Config
[CLI command block]

### Per-Year Total Returns (confirmed config)
[Table: year | M1_Ret% | A1_Ret% | A2_Ret% | A3_Ret% | Total% | Total P&L]

### Per-Window Trade Stats
[Table: year | M1 T/WR/EV | A1 T/WR/EV | A2 T/WR/EV | A3 T/WR/EV]

### Change vs Previous Config
[Table: year | Old Total% | New Total% | Δ pp, plus avg delta]

### CLI
[Canonical backtest command with confirmed windows]

Log files: backtest_result/window_reoptimize_{DATE}/
```

If any window's new winner matches the existing locked value, note "no change" for that window.

---

## Phase 6 — Summary Report to User

Print a concise summary:

1. **What changed** — which windows (if any) were updated and by how much avg delta improved
2. **What stayed the same** — windows where the current config was already optimal
3. **Full confirmed config** — the 4-window CLI command ready to copy-paste
4. **7-year return table** — one row per year showing the confirmed config's total return
5. **Output directory** — `$OUTDIR` path for all log files
