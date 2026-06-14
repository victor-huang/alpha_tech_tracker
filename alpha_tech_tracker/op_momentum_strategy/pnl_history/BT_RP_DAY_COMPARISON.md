# BT vs RP Day-by-Day Comparison Workflow

How to pick a sample of days from a saved backtest run, compare them against the
live trade engine replay, and classify any gaps as bugs or structural differences.

---

## When to use this

- After fixing a BT or live engine bug, verify the fix closed the expected gap.
- Periodically audit that BT and RP are tracking each other (no new bugs crept in).
- Investigate a specific date that looked suspicious in a live session log.

---

## Step 1 — Produce a saved BT run log

Run the selector backtest over the target year and save stdout to a log file.
Use the standard SOA config (weights 60/40, M1+A1+A2, reversal+BRE+BRU+DD):

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --doubledown --doubledown-start 5 \
  --top 2 --start 2024-01-01 --end 2024-12-31 \
  > backtest_result/bt_2024_run.log 2>&1
```

The log contains one trade row per primary position per day, formatted as:
```
  YYYY-MM-DD   WINDOW  RANK  TICKER  DIRECTION  SCORE  ENTRY_TIME  EXIT_TIME  ENTRY_PRICE  EXIT_PRICE  PNL_PER_SHARE  PNL_PCT  WIN_LOSS  EXIT_REASON
```

---

## Step 2 — Pick N random days

Use a fixed random seed so the selection is reproducible:

```python
import re, random
from collections import defaultdict

log_path = "backtest_result/bt_2024_run.log"
daily = defaultdict(float)

with open(log_path) as f:
    for line in f:
        m = re.match(r'\s*(2024-\d{2}-\d{2})\s+\w+\s+\d+\s+\w+.*?\s([+-]\$[\d.]+)\s+[+-][\d.]+%', line)
        if m:
            date = m.group(1)
            pnl_str = m.group(2).replace('$', '').replace('+', '')
            daily[date] += float(pnl_str)

dates = sorted(daily.keys())
random.seed(42)   # change seed each round to avoid repeating the same days
selected = sorted(random.sample(dates, 10))
for d in selected:
    print(f"{d}")
```

> **Note:** `daily[date]` sums per-share P&L from the log, NOT capital P&L. It is
> useful for picking days but not for the comparison table — use the CLI `Total return ($)`
> line for actual capital P&L (Step 3).

---

## Step 3 — Run BT and RP for each selected day

Run both in a loop and capture the capital P&L line for each:

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
cd /Users/victorhuang/work/alpha_tech_tracker

BT_FLAGS="--weights 60 40
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
  --reversal --bearish-reentry --bullish-reentry
  --doubledown --doubledown-start 5
  --top 2"

RP_FLAGS="--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
  --mock-trade-execution --top 2 --capital 10000
  --rank-weighted-sizing 60 40
  --reversal --bearish-reentry --bullish-reentry
  --doubledown --doubledown-start 5"

for DATE in 2024-01-10 2024-02-12 ...; do
  BT=$(PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
    $BT_FLAGS --start "$DATE" --end "$DATE" 2>&1 \
    | grep 'Total return (\$)' | awk '{print $NF}')

  RP=$(PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
    $RP_FLAGS --replay-date "$DATE" 2>&1 \
    | grep "Daily P&L:" | grep -oP 'cap: [+-]\$[\d.]+' | grep -oP '[+-]\$[\d.]+')

  echo "$DATE  BT=$BT  RP=$RP"
done
```

**Key flag notes:**
- BT uses `--weights 60 40`; RP uses `--rank-weighted-sizing 60 40` (different flag names, same effect).
- BT `Total return ($)` is no-compound capital P&L on a $10k day-reset base (default).
- RP `cap:` in the `Daily P&L` line is the capital P&L using fractional shares against the `--capital` base.
- Both must use `--doubledown --doubledown-start 5` or neither — DD changes results significantly.

---

## Step 4 — Build the comparison table

```python
rows = [
    ("2024-01-10", -82.77,  -98.00),
    ("2024-02-12", +72.77,  +41.35),
    # ...
]

print(f"{'Date':<12} {'BT ($)':>10} {'RP ($)':>10} {'Δ ($)':>10}  {'Gap?'}")
print("-" * 58)
for date, bt, rp in rows:
    diff = rp - bt
    flag = "  <-- GAP" if abs(diff) >= 5 else ""
    print(f"{date:<12} {bt:>+10.2f} {rp:>+10.2f} {diff:>+10.2f}{flag}")
```

A gap threshold of **$5** is a reasonable signal — smaller diffs are usually rounding.

---

## Step 5 — Dig into gap days

For each flagged date, run both tools again and capture the per-trade detail:

```bash
DATE=2024-01-10

echo "--- BT ---"
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  $BT_FLAGS --start "$DATE" --end "$DATE" 2>&1 \
  | grep -E "$DATE|Total return"

echo "--- RP ---"
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  $RP_FLAGS --replay-date "$DATE" 2>&1 \
  | grep -E "^\s+[A-Z]+\s+\[|Daily P&L"
```

The BT output shows one row per primary position (including annotated sub-trade P&L
rolled into `cap_pnl` invisibly). The RP output shows every discrete position —
primaries, DD add-ons, BRE/BRU/REV re-entries — as separate labeled rows.

**Reading the RP output labels:**
| Label | Meaning |
|---|---|
| `[Bullish]` / `[Bearish]` | Primary position |
| `[Doubledown]` | DD add-on; fired on a survivor when a co-pick stopped early |
| `[Reversal Trade]` | Reversal re-entry after primary stops out and price reverses |
| `[Bearish Cont.]` | Bearish re-entry (BRE) |
| `[Bullish Cont.]` | Bullish re-entry (BRU) |

---

## Step 6 — Classify each gap

Work through the gap by matching BT rows to RP rows and computing capital P&L
for each BT row using: `slot = portfolio × weight[rank-1]` (e.g. $10k × 60% = $6k
for rank-1). Then compare to RP's corresponding rows.

### Classification checklist

**Is the gap from a DD add-on?**
- BT approximates DD P&L as `freed_capital × addon_pnl_pct` where `addon_pnl_pct`
  is derived from `addon_entry ± 0.80 × bar_range` of the check bar.
- RP runs the DD as a live position with its own entry, hard stop (bar-range based
  since commit `ee0aca2`), and trailing exit — will diverge when price action during
  the DD window differs from the single-bar approximation.
- If the RP DD position ran for many bars or took a large move, expect divergence.
  **This is structural, not a bug.**

**Is the gap from a BRE/BRU/REV sub-trade?**
- BT rolls BRE (`br_pnl`), BRU (`bru_pnl`), and REV (`rev_pnl`) P&L into the
  primary row's `cap_pnl`. RP runs each as a separate live position.
- Slot size for sub-trades in RP may differ from BT's approximation when sequential
  capital timing differs (e.g., an M1 REV still open at A1 drain time reduces A1 budget).
- **If the picks are different between BT A1 and RP A1** — check whether an M1
  REV/BRU is still open at 13:20 in RP. This reduces the A1 budget which may cross
  the EV gate threshold for some tickers. **This is sequential capital timing —
  structural, not a bug.**

**Is the gap from a completely missing trade?**
- RP shows a trade that BT has no annotation for — or vice versa.
- Check `bars_held` for the primary stopout and compare to `dd_bars` (= `doubledown_start_min // 5`).
  If `bars_held > dd_bars`, BT correctly skips DD; if RP still fired DD, that would be a bug.
- Check whether BT has `reentry_cancelled_by_dd=True` on a row that has RP sub-trades.
  If yes, BT suppressed the sub-trade because DD fired — RP should do the same.

**Is the gap under $20 with no missing/extra trades?**
- Likely fractional share rounding or minor price differences between bar closes used
  by BT vs RP. **Accept as structural.**

---

## Known structural differences (as of 2026-05-10)

These are recurring gap causes that are **not bugs**. Do not try to fix them.

### 1. DD add-on exit path approximation (partially closed)

**BT:** scans bars from DD entry+1 through primary exit bar. If any bar's Low (BULLISH) or
High (BEARISH) breaches the bar-range stop, `effective_exit = stop_price`. Otherwise the
add-on exits with the primary. Stop price = `addon_entry ± 0.80 × bar_range` of the check bar.
(Bar-scan logic added 2026-05-10; prior to this, BT used `max/min(exit_price, stop_price)`
which never simulated an intrabar stop hit before the primary exited.)

**RP:** full live position — enters at check-bar close, stops intrabar if Low/High breaches
the same bar-range stop; otherwise exits via trailing MA or EOD.

**Residual divergence:** BT uses bar-close prices throughout (no intrabar fill simulation).
RP fills the stop at approximately `stop_price` but with real tick-level slippage. On days
where the DD position exits via trailing MA (price runs in favor, never hits stop), BT exits
at the primary's close while RP uses its own trailing-MA exit — these still diverge when the
primary and DD add-on reach their trailing exits at different bars.

### 2. Sequential capital timing

**BT:** computes all windows at once with full day visibility. A1 always gets the full M1
capital returned, even if an M1 REV was still open at A1 drain time.

**RP:** A1 budget = capital actually returned to `_window_returned` at 13:15. If an M1
REV/BRU is still open, that slot is withheld, reducing A1 budget. This can change:
- Which tickers clear the EV gate (EV gate is score-based, not budget-based — this doesn't change picks directly)
- Slot sizes for A1/A2 (different weights × smaller budget = smaller positions)
- Whether `min_capital` ($100 floor) is breached for any window

### 3. BRE/BRU/REV sub-trade slot size

BT allocates sub-trades as a fixed fraction of the primary slot. RP allocates from
the actual `_window_returned` pool at the time the watcher fires. These diverge when
other positions have returned partial capital by the time the watcher fires.

### 4. DD cancels BRU/BRE watchers

When DD fires on a survivor, RP cancels any pending BRU/BRE watchers for the stopout
tickers. BT marks those rows `reentry_cancelled_by_dd=True` and uses primary-only
`cap_pnl`. If the watcher would have fired profitably, BT captures zero sub-trade P&L
while RP also captures zero — these should match. But if timing of the watcher vs
the DD timer differs slightly, one system may include the sub-trade and the other may not.

---

## Quick reference: flag meanings in BT rows

When calling `run_selector_backtest()` directly (Python API), each row dict contains:

| Key | Meaning |
|---|---|
| `slot_capital` | Capital deployed for this primary position |
| `cap_pnl` | Total capital P&L including all sub-trades (BRE/BRU/REV/DD) |
| `exit_reason` | Primary exit reason (`hard_stop`, `fallback_20pct`, `trailing_stop_ma20`, `end_of_day`) |
| `bars_held` | Number of 5-min bars the primary was held |
| `rev_pnl` | Reversal sub-trade P&L (0 if no reversal) |
| `br_pnl` | Bearish re-entry P&L (0 if no BRE) |
| `bru_pnl` | Bullish re-entry P&L (0 if no BRU) |
| `dd_addon_cap_pnl` | DD add-on P&L added to the winner row (0 if not winner) |
| `dd_addon_entry` | DD add-on entry price (present only on winner rows where DD fired) |
| `dd_addon_stop_price` | DD add-on hard-stop price (`addon_entry ± 0.80 × bar_range`) |
| `dd_addon_stop_breached` | True if bar-scan found the stop hit before primary exit |
| `dd_addon_effective_exit` | Exit price used for DD P&L computation |
| `reentry_cancelled_by_dd` | True if this stopout's BRU/BRE watcher was cancelled because DD fired |

> **Note:** `run_selector_backtest()` requires `windows` as a list of dicts:
> `[{"label": "M1", "opening_start": "09:30", "opening_bars": 3}, ...]`
> and dates as `datetime.date` objects. Weights and morning_split are only applied
> via the CLI (`_apply_capital_flow`); direct API calls return rows with
> `slot_capital=0` unless `_apply_capital_flow` is called separately.
> **Use the CLI for capital-accurate results.**

---

## Interpreting results across many days

After running 20+ days, the following patterns hold (validated through 2024–2026):

| Gap type | Typical magnitude | Direction | Classification |
|---|---|---|---|
| DD approximation divergence | $5–$40/day | Both ways | Structural |
| Sequential capital timing (M1 REV open at A1) | $10–$80/day | RP worse | Structural |
| BRE/BRU sub-trade slot divergence | $5–$30/day | Both ways | Structural |
| Fractional share rounding | <$1/day | Both ways | Structural |
| Exact match (no sub-trades) | $0 | — | ✓ |

**Expect ~50–60% of sampled days to be within $5.** Days with large sub-trade
activity (especially M1 REV or DD on high-volatility tickers) will show the largest gaps.
If a day has no sub-trades at all (all primary-only exits) and still shows a large gap,
investigate as a potential bug.
