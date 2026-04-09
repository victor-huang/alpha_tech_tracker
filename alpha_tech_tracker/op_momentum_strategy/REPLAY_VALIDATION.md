# Replay vs Backtest Validation

Validates the live trade engine's cap P&L against the selector backtest on specific
historical dates. Run in `--mock-trade-execution --trade-type stock` mode so the
engine replays actual historical bars with simulated fills.

---

## Validation Command

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --mock-trade-execution --trade-type stock \
  --regime-filter --regime-ma 8 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 --reversal --top 2 \
  --bearish-reentry --bullish-reentry \
  --rank-weighted-sizing 60 40 --capital 10000 \
  --replay-date <YYYY-MM-DD>
```

Equivalent backtest (use `--weights 50 30 20` to match engine's `RANK_WEIGHTS`):

```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest \
  --start <DATE> --end <DATE> \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 --regime-filter --regime-ma 8 \
  --reversal --bearish-reentry --bullish-reentry \
  --top 2 --weights 50 30 20 --capital 10000
```

**Note on weights**: The engine uses `RANK_WEIGHTS = [0.50, 0.30, 0.20]` from
`config.py`. For top-2, this becomes `[0.50, 0.30]` (truncated, not renormalized).
Pass `--weights 50 30 20` to the backtest — `_parse_weights` truncates to `[0.5, 0.3]`
for `top_n=2`.

---

## Results (2026-04-05 audit)

| Date | Backtest Cap | Replay Cap | Diff | Status |
|------|-------------|-----------|------|--------|
| 2026-02-03 | +$380.98 | +$394.77 | +$13.79 | Structural — see D1 |
| 2026-02-11 | +$532.01 | +$532.09 | +$0.08 | ✓ |
| 2026-02-24 | -$43.74 | -$55.49 | -$11.75 | Structural — see D2 |
| 2026-02-26 | +$139.87 | +$137.95 | -$1.92 | ✓ known — see D3 |
| 2026-04-01 | -$66.77 | -$68.31 | -$1.54 | ✓ known — see D3 |

---

## Structural Differences

### D1 — Reversal/BRE priority: live engine blocks BRE when reversal-eligible

**Impact:** +$13.79 on 2026-02-03.

**What happens**: When a BEARISH primary exits via `hard_stop` or `fallback_20pct`
with `bars_held ≤ reversal_max_bars`, `_maybe_create_reentry_watcher` creates a
reversal watcher and returns early — no BRE watcher is created. If the reversal
trigger (close > OR high) never fires, the BRE opportunity is also missed.

The backtest handles this correctly: it exhaustively scans remaining bars for the
reversal trigger first; only if no reversal trigger is found does it check for BRE.
It has full lookahead.

**Example (2026-02-03, APP):**
- APP primary: BEARISH, hard_stop, bars_held=1 → reversal watcher created
- Reversal trigger = close > OR high (483.85); APP never reaches 483.85
- BRE trigger = close < OR low (460.07); APP drops to 459.50
- Backtest: no reversal found → BRE fires at 459.50, exits EOD at 461.98, pnl=-$2.48/share → cap_pnl = -$16.19
- Live engine: reversal watcher expires at EOD without firing; BRE never entered
- M1 diff: replay +$16.19 more than backtest (missing BRE loss)

**Why it can't be fully fixed**: Creating both watchers simultaneously causes
regressions on dates where BRE fires before reversal (case 3: BRE at bar X,
reversal at bar Y > X). The backtest uses reversal via lookahead; the live engine
would enter BRE first. The two systems produce opposite outcomes and the backtest
figures change substantially. Tested and reverted 2026-04-05.

**Net effect on A1/A2**: When an M1 position is still open at A1 drain time (e.g.,
SHOP still running), the backtest includes its unrealized P&L in the A1 budget
(`available = portfolio + first_group_pnl`). The live engine passes only the
returned capital at cost (`slot_capital` of open positions). A1 gets ~$304 less
capital than backtest when SHOP has unrealized +$320 gain. This cascades to A2.

---

### D2 — ANAB sparse bars: signal arrives after collection deadline

**Impact:** -$11.75 on 2026-02-24.

**What happens**: ANAB has very few trades in the opening period. Its 5-min bars
arrive significantly after the expected signal time. On 2026-02-24 the ANAB M1
signal fires at ~10:45 AM, well past the 9:50 AM deadline. The A2 signal fires
after 3:10 PM. Both are skipped with "Max positions reached / past deadline."

The backtest ignores intraday bar timestamps: it takes the first N bars after the
opening start regardless of their actual wallclock time, so ANAB is ranked and
selected normally.

**Example (2026-02-24):**
- Pre-market picks (live selector): ANAB (score=2.239), FN (score=1.945) — matches backtest
- M1 actual execution: FN (score=1.946, fires on time) + FANG (score=1.929, fires at deadline) — ANAB arrives after both slots filled
- A2 actual execution: SNDK + FN — ANAB arrives after both slots filled
- FANG and FN (reversal) have larger losses than ANAB's tiny fallback exits

**Breakdown:**
- M1: -$4.41 (FANG replaces ANAB)
- A1: +$0.02 ✓ (same picks, CVNA+FN)
- A2: -$7.34 (FN+reversal replaces ANAB)

**Why it can't be fully fixed**: The backtest's "ignore intraday timing" assumption
is not achievable in real-time. In live trading, ANAB also fires late, so the
replay behavior is actually more representative of live execution.

---

### D3 — A1/A2 capital: unrealized M1 P&L not forwarded (small, recurring)

**Impact:** -$1.92 on 2026-02-26, -$1.54 on 2026-04-01.

When an M1 position is still open at A1 drain time, the backtest gives A1:
```
available = initial_capital + sum(closed_M1_cap_pnl)
```
The live engine gives A1:
```
available = sum(M1_returned_capital) + M1_undeployed
         = sum(slot_capital_at_cost for open M1) + sum(slot_capital + cap_pnl for closed M1) + M1_undeployed
```
The difference is `sum(unrealized_cap_pnl for still-open M1 positions)`. For small
unrealized gains this is ≤$5 in absolute cap P&L terms.

---

---

## Feature Gaps: Replay vs Live Trading

### Stock trades (trade-type stock)

Replay is highly accurate for stock trades. The three ✓ validation dates are within $2.

| Area | Replay | Live |
|------|--------|------|
| Entry price | Bar close (`event.stock_price`) | Same when `mock_trade_execution=True`; live quote mid otherwise |
| Exit price | Bar close or stop level (exact) | Same |
| Order fills | Instant | 3-step escalation: mid → ask/bid → market, up to 120s |
| Re-entry callback | Synchronous — fires within same bar | Background thread — fires async |
| Notifications | Disabled | SMS + Telegram enabled |

**P&L impact:** None for entry/exit pricing. Fill timing could shift entry by 1-2 bars in live
(order placed at 9:45, filled at 9:46:30 — first monitoring bar still 9:50, same as replay).

### Options trades (trade-type options)

Options replay has inherent limitations. Treat as directional validation only, not P&L-exact.

| Area | Replay | Live | Impact |
|------|--------|------|--------|
| Contract selection | `MockContractSelector` — fixed 90%/110% strike offset, synthetic OCC symbol | `TimePremiumContractSelector` — fetches live ITM contracts, picks shallowest ITM within DTE-adjusted time premium cap | HIGH — strike differs, entry prices off ±2-5% per trade |
| Entry price | `mock_entry_price()` — fixed 20% time premium over intrinsic | Live API bid/ask mid, or `OptionPriceMonitor` fair price if enabled | MEDIUM — ±2-8% per trade |
| Exit price | `mock_exit_price()` — zero theta decay (`_TIME_DECAY = 1.0`) | Live API bid/ask mid; same zero-decay mock if `mock_trade_execution=True` | MEDIUM — both modes overstate P&L on multi-bar holds; real theta ≈ 3-10%/day in final week |
| `OptionPriceMonitor` | Cannot use (requires live WebSocket) | Optional; improves entry/exit pricing accuracy | LOW — usually off in paper mode too |

**Biggest actionable gap:** `MockContractSelector` uses a fixed 90%/110% offset that can't
replicate `TimePremiumContractSelector`'s market-driven strike selection. To improve fidelity,
persist the actual selected contract symbols during a live/paper run and replay using those
saved symbols instead of the mock formula.

### Re-entry callback threading

In replay, re-entry callbacks (reversal, BRE, BRU) fire **synchronously** within the same bar
loop — the re-entry position is created before the next bar is processed.

In live, a background thread is spawned. In practice the bar loop runs every ~30s, so the
thread finishes well before the next bar. However under heavy load or delayed GIL scheduling,
there is a theoretical risk of the re-entry position missing its first monitoring bar.

---

## Bugs Fixed During This Audit (2026-04-05)

### B1 — `_parse_weights` renormalized truncated weights

**File:** `op_momentum_selector_backtest.py`

`_parse_weights([0.5, 0.3, 0.2], n=2)` previously renormalized to `[0.625, 0.375]`
instead of truncating to `[0.5, 0.3]`. This caused backtest slot capitals to differ
from the engine's `RANK_WEIGHTS[0]=0.5` and `RANK_WEIGHTS[1]=0.3`.

**Fix:** If `len(fracs) >= n`, return `fracs[:n]` without renormalization.

### B2 — Signal-at-deadline bypassed ranked drain

**File:** `trade_engine.py` line ~721

`if now < state["collection_deadline"]` used strict `<`. A signal arriving at
exactly the deadline (common for sparse tickers like ANAB at the boundary) fired
as a bypass (rank=0 entry) instead of being buffered for the ranked drain.

**Fix:** Changed to `if now <= state["collection_deadline"]`.

---

## Multi-Day Period Comparison Studies

Compares the selector backtest output against trade engine replay over full trading
periods. Both systems run with identical parameters; the replay simulates live
execution by playing historical 5-min bars through the live engine code path.

### Methodology

**Replay script** (`/tmp/run_replays_2025.py`): invokes
`op_momentum_trade_engine run --mock-trade-execution` for each trading day using
`ThreadPoolExecutor(max_workers=4)`. Parses `cap:` line from each run's stdout.
Outputs one CSV row per day to `/tmp/replay_results_2025.csv`.

**Comparison script** (`/tmp/compare_2025.py`): parses the backtest execution log
(produced with `--show-execution-log`) and the replay CSV, diffs per-window
per-rank picks, and totals cap P&L.

**Shared config for all studies:**
```
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
--regime-filter --regime-ma 8 --top 2 --rank-weighted-sizing 60 40
--trade-type stock --bearish-reentry --bullish-reentry --reversal --full-day
--capital 10000
```

---

### Study 1 — Jan–Mar 2026 (38 trading days, 2026-04-05)

| Metric | Value |
|--------|-------|
| Days covered | 38 |
| Identical days | 23 (61%) |
| Days with pick differences | 15 (39%) |
| Backtest total cap P&L | (not recorded) |
| Replay total cap P&L | (not recorded) |
| Net cumulative difference | **+$4.04** (replay vs backtest, essentially zero) |

**Most common dropped tickers** (in backtest but missed in replay):
ANAB, FN, RH — all sparse-bar tickers whose signals arrive after the collection
drain fires in replay.

**Interpretation**: Over a short recent period, backtest and replay are nearly
P&L-equivalent. The +$4.04 cumulative gap across 38 days is noise — individual
day differences cancel out.

---

### Study 2 — Full Year 2025 (245 trading days, 2026-04-08)

| Metric | Value |
|--------|-------|
| Days covered | 245 |
| Identical days | 68 (28%) |
| Days with pick differences | 177 (72%) |
| Backtest total cap P&L | **+$16,424** |
| Replay total cap P&L | **+$24,782** |
| Net difference | **Replay +$8,357 ahead** |

**Most common dropped tickers** (in backtest but missed in replay):

| Ticker | Days dropped | Notes |
|--------|-------------|-------|
| ANAB | 92× | ~1,737 intraday bars vs pool median ~3,750 |
| RH | 70× | ~3,222 bars, thin morning volume |
| FN | 55× | ~3,222 bars, thin morning volume |
| PLTR | 28× | Occasionally sparse in early 2025 |
| CVNA | 19× | — |
| COIN | 18× | — |

**Why replay exceeds backtest by +$8,357**: Different ticker selection, not better
execution. When sparse-bar tickers (ANAB, RH, FN) are dropped in replay, the engine
substitutes the next-ranked ticker. Over 177 days those substitute tickers happened
to produce higher actual returns on those specific days. The 2025 market environment
(volatile tech names) amplified these divergences.

**This is not a bug** — replay behavior is more representative of live execution.
In live trading, ANAB/RH/FN also arrive late and would be replaced by the same
substitute tickers the replay selects.

**Root cause of differences (structural, same as D2 above)**:
- Backtest ignores intraday bar timestamps — takes first N bars regardless of
  actual wallclock arrival time
- Live engine (and replay) respects real timing — sparse tickers miss the
  collection deadline and are skipped

**Cache bugs fixed before running this study** (2026-04-08, 3 bugs in `fetch_bars()`):
1. Stitch path saved empty trimmed results → 92-byte corrupt cache files
2. Exact cache hit path served corrupt 92-byte empty file as valid data
3. Delta-fetch computed inverted date range when large multi-month files extended
   past the requested end date → Alpaca API error

Deleted 10,734 corrupt 92-byte files and 1,321 corrupt multi-month files, plus all
`selector_2025*.json` selector cache files, before the final replay run.

---

### Study 3 — 2024 Monthly Breakdown (Jan–Aug 2024, 2026-04-08)

**Tools used:**
- `/tmp/run_replays_month.py` — generic per-month replay runner, `ThreadPoolExecutor(max_workers=4)`, credentials passed via env
- `/tmp/compare_month.py` — parses backtest execution log + replay CSV, diffs per-window per-rank picks

**Cache bugs found during this study** (2026-04-08):
- 3,026 additional corrupt multi-month files discovered across all years: files where
  `actual_start > fname_start + 14 days` (IEX 3-month look-back artifact — requests for
  long historical ranges return only ~3 months of intraday data, but the filename records
  the full requested range). Previous sweeps only checked end-date gaps; start-date gaps
  were added to the detection logic.
- Deleted with: check both `actual_start > fname_start + 14d` and `actual_end < fname_end - 14d`
- All `selector_2024*.json` caches also deleted after cleanup.

#### Monthly Results

| Month | Days | Identical | BT Cap P&L | RP Cap P&L | Diff (RP−BT) |
|-------|------|-----------|-----------|-----------|-------------|
| Jan 2024 | 21 | 7 (33%) | +$1,220.95 | +$744.16 | **−$476.79** |
| Feb 2024 | 19 | 4 (21%) | +$1,612.37 | +$1,767.83 | **+$155.46** |
| Mar 2024 | 20 | 3 (15%) | +$1,742.68 | +$1,987.19 | **+$244.51** |
| Apr 2024 | 22 | 9 (41%) | +$1,774.59 | +$1,130.12 | **−$644.47** |
| May 2024 | 22 | 5 (23%) | +$873.37 | +$677.28 | **−$196.09** |
| Jun 2024 | 19 | 7 (37%) | +$840.19 | +$504.32 | **−$335.87** |
| Jul 2024 | 22 | 7 (32%) | +$1,873.22 | +$1,107.52 | **−$765.70** |
| Aug 2024 | 22 | 5 (23%) | +$2,420.35 | +$2,140.96 | **−$279.39** |
| **8-mo total** | **167** | **47 (28%)** | **+$12,357.72** | **+$10,059.38** | **−$2,298.34** |

Note: June 2024 backtest shows only 19 trading days (one day had no signal on any ticker).

#### Most Common Dropped Tickers (across all 8 months)

| Ticker | Approx. drops | Pattern |
|--------|--------------|---------|
| ANAB | ~60× | Consistently sparse — misses across every month |
| RH | ~40× | Sparse in afternoon windows especially |
| FN | ~40× | Strongest in Jul–Aug; FN ran hard those months |
| COIN | ~15× | Sporadic, mainly morning windows |
| CVNA | ~10× | Sporadic |

#### Interpretation

Backtest leads by **−$2,298** over 8 months (−18.6% of BT total). Only Feb and Mar 2024
went in replay's favor (+$400 combined); the remaining 6 months favor backtest.

**Why backtest leads here (vs replay leading in full-year 2025):**
- In 2024, ANAB/RH/FN were frequently the strongest picks on the days they were dropped.
  Their substitutes underperformed. The direction of the outcome (backtest wins or replay
  wins) is entirely determined by whether the dropped tickers outperformed their replacements
  on those specific days — it has no systematic direction.
- 2025's bull/volatile environment happened to make substitutes outperform; 2024's patterns
  ran the other way for 6 of 8 months.

**Identical rate**: 28% across 8 months — exactly matches the 2025 full-year rate (28%).
This confirms the sparse-bar timing gap is a stable structural property of these tickers,
not a year-specific artifact.
