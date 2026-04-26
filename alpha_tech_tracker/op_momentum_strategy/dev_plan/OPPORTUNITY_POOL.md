# Feature Dev Plan — Opportunity Pool

**Date:** 2026-04-25  
**Status:** Planning  
**Branch:** open_market_momentum_stategy

---

## Overview

Introduce a dedicated capital pool ("opportunity pool") that is funded independently of the primary window capital (M1/A1/A2). The pool deploys on high-quality signals — first use case is the double-down (DD) signal. Capital recycles sequentially within the day: when a deployment exits, the returned capital (principal + P&L) is immediately available for the next DD signal that fires later in the same day.

P&L is tracked both independently (to evaluate the pool's own effectiveness) and included in all aggregate daily/weekly/monthly/yearly reporting.

---

## Capital Model

### Sizing
- Pool size = `opportunity_pct × initial_capital`
- Default flag: `--opportunity-capital 50` → 50% of initial capital
- Example: $10,000 initial → $5,000 opportunity pool

### Reset behavior
- `--compound off` (default): pool resets to its initial size at the start of each day, consistent with window capital reset
- `--compound on`: pool balance carries over day-to-day (grows with wins, shrinks with losses)

### Intra-day recycling
The pool recycles sequentially across windows within the same day:

```
Day start: pool = $5,000

M1 DD fires at 9:50 AM:
  → deploy $5,000 from pool
  → M1 winner exits at 11:30 AM: returned = $5,000 + P&L

A1 DD fires at 1:20 PM:
  → pool balance = returned M1 amount (e.g. $5,200)
  → deploy full $5,200 from pool
  → A1 winner exits at 2:45 PM: returned = $5,200 + P&L

A2 DD fires at 3:05 PM:
  → pool balance = returned A1 amount
  → deploy full pool into A2 winner
  → A2 winner exits at 3:55 PM (EOD)

Day end: pool P&L = sum of all three deployments
```

If a deployment has NOT exited by the time the next DD fires, the pool is still locked — skip that DD. (Most M1 trades exit well before 1:20 PM, so sequential availability is the common case.)

---

## Trade Entry & Exit Mechanics

The opportunity pool uses identical mechanics to the existing DD add-on leg:

- **Entry price:** close of the bar at OR close + 5 min (same `dd_addon_entry`)
- **Hard stop:** entry ± 80% × (High − Low) of the check bar in the adverse direction
- **Exit:** winner's natural exit price, or hard stop price, whichever is worse for the trade
- **P&L:** signed return — can be negative if hard stop is hit

These values are already annotated on winner rows by `_annotate_doubledown_addon`. The opportunity pool reuses them without re-computing.

---

## Implementation Steps

### Step 1 — CLI flag
Add to `_parse_args()`:

```python
parser.add_argument(
    "--opportunity-capital",
    type=float,
    default=0.0,
    dest="opportunity_capital_pct",
    help=(
        "Size of the opportunity pool as a percentage of initial capital "
        "(e.g. 50 = 50%%). Pool deploys on DD signals independently of "
        "window capital. Default: 0 (disabled)."
    ),
)
```

Print in config header:
```
Opportunity pool : $5,000 (50% of initial)   ← or "disabled"
```

### Step 2 — Annotate eligibility (no code change needed)

`_annotate_doubledown_addon` already sets `dd_addon_entry`, `dd_addon_effective_exit`, `dd_addon_pnl_pct`, and `dd_freed_ranks` on winner rows. Any row with `dd_freed_ranks` is eligible for opportunity pool deployment — no additional annotation required.

### Step 3 — New function `_apply_opportunity_pool`

```python
def _apply_opportunity_pool(
    trade_rows: list,
    windows: list,
    initial_pool: float,
    compound: bool = False,
) -> None:
    """
    Deploy the opportunity pool on DD-eligible winner rows, recycling
    capital sequentially within each day across windows.

    Mutates winner rows in-place, adding:
      opp_cap_pnl       float   dollar P&L from this deployment
      opp_deployed      float   capital deployed (pool balance at entry)
      opp_returned      float   capital returned after exit
    """
```

Logic:
1. Group `trade_rows` by date, then by window order (M1 → A1 → A2)
2. Maintain `pool` running balance; reset to `initial_pool` each day if not compounding
3. For each day, iterate windows in order:
   - Find winner row with `dd_freed_ranks` (DD eligible)
   - If pool > 0 and winner's `bars_held >= dd_bars` (position still open at DD check time):
     - `opp_cap_pnl = pool × dd_addon_pnl_pct`
     - `opp_returned = pool + opp_cap_pnl`
     - Set `opp_cap_pnl`, `opp_deployed = pool`, `opp_returned` on row
     - Fold into winner's `cap_pnl`, `pnl_pct`, `success` (same pattern as DD)
     - `pool = opp_returned`  ← capital available for next window's DD
   - If pool <= 0 or winner not available: skip

### Step 4 — Call site

In `__main__`, after `_apply_doubledown`:

```python
if args.opportunity_capital_pct > 0:
    initial_pool = args.capital * args.opportunity_capital_pct / 100
    _apply_opportunity_pool(
        trade_rows,
        resolved_windows,
        initial_pool=initial_pool,
        compound=args.compound,
    )
```

### Step 5 — Stats tracking

Add to `_stats_from_trades`:

```python
opp_rows = [r for r in active if r.get("opp_cap_pnl", 0.0) != 0.0]
opp_total = len(opp_rows)
opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
opp_losses = opp_total - opp_wins
opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)
```

Return in stats dict:
```python
"opp_total": opp_total,
"opp_wins": opp_wins,
"opp_losses": opp_losses,
"opp_net_cap_pnl": opp_net_cap_pnl,
```

### Step 6 — Reporting

**`_print_stats_block`** — add after DD row:
```
Opportunity pool: N  (XW / YL)  net cap P&L: +$Z
```

**`_print_capital_stats_block`** — add a dedicated opportunity pool section:
```
OPPORTUNITY POOL  ($5,000 initial | 50% of capital)
────────────────────────────────────────────────
Deployments         : N  (XW / YL)
Win rate            : XX%
Net P&L             : +$Z
Final pool balance  : $Z
Pool return (%)     : +XX%
```

**Daily table (`_print_daily_table`)** — print `[OPP]` row immediately after `[DD]` row when opportunity pool deploys, using same column layout:
```
                       [OPP]        entry   exit    P&L$    P&L%   WIN/LOSS   opp pool $5,000
```

**Weekly/monthly/yearly breakdowns** — no change needed; `cap_pnl` on each row already includes `opp_cap_pnl` after Step 3 folds it in.

---

## Pre-Implementation Checklist

- [ ] Confirm `opp_cap_pnl` folds into `cap_pnl` AFTER the weekly/monthly aggregation reads `cap_pnl` — verify ordering in `__main__`
- [ ] Guard: if pool is still deployed (prior window's winner hasn't exited yet), skip rather than double-deploy
- [ ] Guard: `pool <= 0` after a loss shouldn't cause a deployment of zero or negative capital
- [ ] `--compound on` path: pool carries over across days — verify it doesn't reset inside `_apply_opportunity_pool`
- [ ] Baseline comparison: run without `--opportunity-capital` flag and verify no change to existing numbers
- [ ] Verify `[OPP]` row appears in the daily table correctly aligned alongside `[DD]` row
- [ ] Verify weekly/monthly/yearly totals increase by exactly `opp_net_cap_pnl` when the flag is enabled

---

## Open Questions

1. **Future signals:** The plan is extensible — other high-quality signals (e.g. strong opening momentum, reversal with large OR range) can deploy the pool using the same `_apply_opportunity_pool` function with a different eligibility check. Document signal types as an enum for future expansion.

2. **Pool sizing per deployment:** Currently the full pool balance deploys each time. A future option could be `--opportunity-max-deploy PCT` to cap each deployment at a fraction of the pool, allowing simultaneous multi-window deployments.

3. **Minimum pool threshold:** Should there be a `min_pool` floor (like `MIN_WINDOW_CAPITAL`) below which the pool skips deployment? Add `--opportunity-min-capital` flag in a future pass.
