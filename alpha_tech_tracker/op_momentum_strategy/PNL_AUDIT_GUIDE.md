# P&L Audit Guide

## What the audit verifies

`audit_pnl.py` independently recalculates every P&L number in a backtest log file and confirms that:

1. **Per-trade capital P&L** — shares × pnl/share matches the logged `cap_pnl` for each trade
2. **Intra-day window capital flow** — the capital available to each window (M1, M2, A1, A2) follows the correct allocation rules
3. **Day-to-day compounding** — each day starts from the prior day's ending portfolio, gains and losses carry forward
4. **Weekly P&L totals** — sum of daily cap P&L per ISO week matches the log's weekly breakdown
5. **Monthly P&L totals** — same for monthly breakdowns
6. **Entry/exit price validity** (optional) — spot-checks logged prices against real Alpaca 5-min bar data

## Capital flow rules (what the audit checks against)

Given a portfolio value `P` at the start of a day:

### Morning group (simultaneous)

M1 and M2 deploy at the same time. Each gets a fixed fraction of the current portfolio:

```
M1 capital = P × morning_split[0]   # e.g. 60% → P × 0.60
M2 capital = P × morning_split[1]   # e.g. 40% → P × 0.40
```

### Sequential windows (A1, A2)

Each sequential window inherits all capital returned from the prior step:

```
A1 capital = P + M1_pnl + M2_pnl
A2 capital = A1 capital + A1_pnl
```

If a window's allocated capital is below `$100`, it is skipped for that day.

### Per-trade allocation within a window

Ranks 1/2/3 receive 50%/30%/20% of the window capital:

```
slot_capital = window_capital × weight[rank - 1]
shares       = slot_capital / entry_price
cap_pnl      = shares × pnl_per_share
```

### End-of-day portfolio update (compound mode)

```
portfolio = portfolio + M1_pnl + M2_pnl + A1_pnl + A2_pnl
```

This carries over to the next trading day.

## Audit results (2026-01-01 → 2026-03-27)

Run: `--window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 60 40 --compound`

**All 59 trading days passed** — every daily cap P&L and portfolio value matched within $0.02 rounding tolerance.

| Period | Calc P&L | Logged P&L | Portfolio |
|---|---|---|---|
| 2026-01 | +$2,831.44 | +$2,831.44 (+28.31%) | $12,831.44 |
| 2026-02 | +$3,272.25 | +$3,272.25 (+32.72%) | $16,103.69 |
| 2026-03 | +$2,064.89 | +$2,064.89 (+20.65%) | $18,168.58 |
| **Total** | **+$8,168.58** | **+$8,168.58 (+81.69%)** | **$18,168.58** |

Entry/exit prices spot-checked against real Alpaca bar data — all sampled prices fall within each day's actual trading range.

## How to run the audit

The script uses paths relative to its own directory, so run it from `alpha_tech_tracker/op_momentum_strategy/`:

```bash
cd /Users/victorhuang/work/alpha_tech_tracker/alpha_tech_tracker/op_momentum_strategy
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker
export PYENV_VERSION=3.8.18/envs/alpha_tech_tracker
```

### Full audit — all days

```bash
pyenv exec python audit_pnl.py
```

Output: one row per trading day showing logged vs calculated cap P&L, portfolio value, and a pass/fail flag. Followed by reproduced weekly and monthly breakdowns compared to the log.

### Single-day detail

```bash
pyenv exec python audit_pnl.py --date 2026-01-08
```

Shows the full capital flow trace for that date:
- Portfolio start value
- Capital allocated to each window
- Per-trade breakdown: slot capital, shares, calculated cap P&L

### Spot-check entry/exit prices against Alpaca

```bash
pyenv exec python audit_pnl.py --verify-prices
```

Fetches real 5-min bars from Alpaca (uses the local cache) and confirms each sampled entry/exit price falls within the day's actual High/Low range. Prints a warning line for any price that falls outside the range.

### Verbose mode — capital detail for every day

```bash
pyenv exec python audit_pnl.py --verbose
```

Prints the per-trade capital breakdown for all 59 days.

## Changing the target log file

The log path is set near the top of `audit_pnl.py`. It is relative to `alpha_tech_tracker/op_momentum_strategy/` (where the script lives):

```python
LOG_PATH = (
    "backtest_result/multiple_trading_windows/"
    "m1_m2_a1_a2_compound_2026.txt"
)
```

The capital flow parameters are also constants at the top of the file:

```python
INITIAL_CAPITAL = 10_000.0
MORNING_SPLIT   = [0.60, 0.40]   # M1, M2
WEIGHTS         = [0.50, 0.30, 0.20]
FIRST_GROUP     = ["M1", "M2"]
SEQUENTIAL      = ["A1", "A2"]
MIN_CAPITAL     = 100.0
```

Update these to match the `--morning-split` and `--weights` flags used when generating the log.

## Script location

```
alpha_tech_tracker/op_momentum_strategy/audit_pnl.py
```
