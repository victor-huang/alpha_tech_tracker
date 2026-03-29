# P&L Audit Guide

## What the audit verifies

`audit_pnl.py` independently recalculates every P&L number in a backtest log file and confirms that:

1. **Per-trade capital P&L** — shares × pnl/share matches the logged `cap_pnl` for each trade
2. **Intra-day window capital flow** — the capital available to each window follows the correct allocation rules
3. **Day-to-day compounding** — each day starts from the prior day's ending portfolio (compound mode), or resets to $10K (non-compound mode)
4. **Weekly P&L totals** — sum of daily cap P&L per ISO week matches the log's weekly breakdown
5. **Monthly P&L totals** — same for monthly breakdowns, using both logged% and normalised% (`pnl / (trading_days × $10K)`)
6. **Entry/exit price validity** (optional) — spot-checks logged prices against real Alpaca 5-min bar data

## Capital flow rules (what the audit checks against)

Given a portfolio value `P` at the start of a day:

### First group (simultaneous)

Simultaneous windows each deploy at the same time. Each gets a fixed fraction of the current portfolio:

```
window_capital[i] = P × morning_split[i]
```

The splits are read directly from the log header, e.g.:
- `[M1] 09:30 / 3 bars  (simultaneous, 60% of portfolio)` → 60%
- `[M2] 09:30 / 1 bars  (simultaneous, 40% of portfolio)` → 40%
- `[M1] 09:30 / 3 bars  (simultaneous, 100% of portfolio)` → 100% (single morning window)

### Sequential windows

Each sequential window inherits all capital returned from the prior step:

```
available = P + first_group_pnl
A1 capital = available
available  = available + A1_pnl
A2 capital = available
```

If a window's allocated capital is below `$100`, it is skipped for that day.

### Per-trade allocation within a window

Ranks 1/2/3 receive 50%/30%/20% of the window capital:

```
slot_capital = window_capital × weight[rank - 1]
shares       = slot_capital / entry_price
cap_pnl      = shares × pnl_per_share
```

### End-of-day portfolio update

**Compound mode** — the ending portfolio carries over to the next trading day:

```
portfolio = portfolio + total_cap_pnl
```

**Non-compound mode** — trades always execute on $10K; the equity curve tracks cumulative P&L separately:

```
trade_portfolio  = $10,000  (constant)
running_portfolio = $10,000 + sum(all daily cap P&Ls so far)
```

## Auto-detection of mode and window config

The script reads the log header automatically — no manual configuration needed:

- **Compound mode** is detected from the header line `Compounding : on/off`
- **Window composition** is detected from lines like:
  ```
  [M1] 09:30 / 3 bars  (simultaneous, 60% of portfolio)
  [A1] 13:15 / 1 bars  (sequential, inherits all returned capital)
  ```
  This means the same script works unchanged for M1+M2+A1+A2, M1+A1+A2, M2+A1+A2, or any other combination.

## Audit results (2026-01-01 → 2026-03-27)

### Compound: `m1_m2_a1_a2_compound_2026.txt`

Run: `--window M1 09:30 3 --window M2 09:30 1 --window A1 13:15 1 --window A2 15:00 1 --morning-split 60 40 --compound`

**All 59 trading days passed** — every daily cap P&L and portfolio value matched within $0.02 rounding tolerance.

| Period | Calc P&L | Logged P&L | Portfolio |
|---|---|---|---|
| 2026-01 | +$2,831.44 | +$2,831.44 (+28.31%) | $12,831.44 |
| 2026-02 | +$3,272.25 | +$3,272.25 (+32.72%) | $16,103.69 |
| 2026-03 | +$2,064.89 | +$2,064.89 (+20.65%) | $18,168.58 |
| **Total** | **+$8,168.58** | **+$8,168.58 (+81.69%)** | **$18,168.58** |

### Non-compound: `m1_m2_a1_a2_2026.txt`

Same window config, no `--compound`.

**All 59 trading days passed.**

| Period | Calc P&L | Logged P&L | Portfolio |
|---|---|---|---|
| 2026-01 | logged values | match calc | within $0.02 |
| **Total** | **+$6,060.93** | **+$6,060.93 (+60.61%)** | **$16,060.93** |

### Non-compound: `m1_a1_a2_2026.txt`

Run: `--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100` (no M2).

**All 59 trading days passed.** Final portfolio: $16,426.22.

Entry/exit prices spot-checked against real Alpaca bar data — all sampled prices fall within each day's actual trading range.

## How to run the audit

Run from `alpha_tech_tracker/op_momentum_strategy/`:

```bash
cd /Users/victorhuang/work/alpha_tech_tracker/alpha_tech_tracker/op_momentum_strategy
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker
export PYENV_VERSION=3.8.18/envs/alpha_tech_tracker
```

### Full audit — default compound log

```bash
pyenv exec python audit_pnl.py
```

### Full audit — default non-compound log

```bash
pyenv exec python audit_pnl.py --no-compound
```

### Full audit — any log file

```bash
pyenv exec python audit_pnl.py --log backtest_result/multiple_trading_windows/m1_a1_a2_2026.txt
```

The script auto-detects compound mode and window composition from the log header.

### Single-day detail

```bash
pyenv exec python audit_pnl.py --date 2026-01-08
pyenv exec python audit_pnl.py --log backtest_result/multiple_trading_windows/m1_a1_a2_2026.txt --date 2026-01-08
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

## Non-compound return% columns

In non-compound mode, the weekly and monthly tables show two return% columns:

| Column | Formula | Description |
|---|---|---|
| `Logged%` | `pnl / $10K` | Matches the log's own return% (raw ratio to starting capital) |
| `Norm%` | `pnl / (trading_days × $10K)` | Normalised for number of days — comparable across weeks/months of different lengths |

## Changing the target log file

Pass `--log <path>` to audit any log file. The script reads the window composition and compound mode directly from the header — **no code changes required**.

The only constants that must match the log are in `audit_pnl.py`:

```python
INITIAL_CAPITAL = 10_000.0
WEIGHTS         = [0.50, 0.30, 0.20]   # rank-1/2/3 per-trade allocation
MIN_CAPITAL     = 100.0
```

Update `WEIGHTS` if the log was generated with different `--weights` flags.

## Script location

```
alpha_tech_tracker/op_momentum_strategy/audit_pnl.py
```
