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
  --rank-weighted-sizing --capital 10000 \
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
