# P&L & Win Rate Audit — `ma_open_range_momentum_screener.py`

Audit of the range-analysis output produced by:
```
python -m alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
  --tickers ... --start 2026-01-01 --end 2026-05-28 --min-vol-ratio 1
```

Status legend: `[ ]` Open | `[x]` Fixed

All issues fixed in one pass. Tests: 195/195 passing.

Severity legend: **Medium** = result is wrong or misleading in a material way | **Low** = cosmetic / minor mis-labeling

---

## S1 — Lookahead bias in `collection_vol` when signal fires on bar 1 of the collection window

**Status:** [x] Fixed
**Severity:** Medium — backtest can fire BULL signal using volume from bars that haven't closed yet

**File:** `ma_open_range_momentum_screener.py` lines 333–364

**What happens:**
`collection_vol` is computed as the mean of **all** `collection_bars` bars (e.g. 09:40, 09:45, 09:50)
before the per-bar scan loop runs. Then each bar is checked using that same pre-computed value:

```python
# computed once, before the loop
scan_slice = from_or.iloc[or_bars - 1 : or_bars - 1 + collection_bars]
collection_vol = float(scan_slice["Volume"].mean())   # includes future bars

# then used inside the loop for every bar
for idx, bar in from_or.iloc[scan_start:scan_end].iterrows():
    bull = close > or_mid and collection_vol > vol_20day_avg
```

When the signal fires at bar 1 of the collection window (09:40 for a 09:30/3b window), the volume
condition uses the mean of 09:40 + 09:45 + 09:50 volumes — two bars that haven't closed yet in
real time.

**Impact:**
- In backtest all bars are available, so results are internally consistent, but the volume filter
  is effectively forward-looking for early-firing signals.
- In live mode `collection_bars=n_bars` (only available bars), so live and backtest compute
  different `collection_vol` for the same signal on bar 1 or 2. A signal can pass the volume gate
  in backtest but fail live (or vice versa) if volumes differ across the 3-bar window.

**Fix (proposed):**
Inside the per-bar loop, compute `collection_vol` as the mean of bars up to and including the
current bar only:

```python
for i, (idx, bar) in enumerate(from_or.iloc[scan_start:scan_end].iterrows()):
    available_slice = from_or.iloc[scan_start : scan_start + i + 1]
    collection_vol = float(available_slice["Volume"].mean())
    bull = close > or_mid and collection_vol > vol_20day_avg
```

---

## S2 — `Exp Value` column is always identical to `Avg Gain` (redundant)

**Status:** [x] Fixed — replaced with Profit Factor (`sum(wins) / abs(sum(losses))`)
**Severity:** Low — no incorrect numbers, but the column adds no information

**File:** `ma_open_range_momentum_screener.py` line 1139

**What happens:**
The expected value formula is:
```python
exp_val = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
```

This is mathematically identical to `avg_gain` when wins and losses are disjoint and exhaustive:
```
exp_val = (n_wins/n) × (sum(wins)/n_wins) + (n_losses/n) × (sum(losses)/n_losses)
        = sum(wins)/n + sum(losses)/n
        = sum(pcts)/n
        = avg_gain
```

So `Exp Value` and `Avg Gain` always print the same number.

**Fix (proposed):**
Remove the `Exp Value` column from `_print_summary_block`, or replace it with a genuinely different
metric such as the **Sharpe-style ratio** (`avg_gain / stdev(pcts)`) or **profit factor**
(`sum(wins) / abs(sum(losses))`).

---

## S3 — Pre-session win rate table is unconditional; semantics differ from signal analysis

**Status:** [x] Fixed — added clarifying subtitle to the pre-session section header
**Severity:** Low — no math error, but juxtaposition is misleading

**File:** `ma_open_range_momentum_screener.py` `_compute_hold_history` / `_rank_tickers_by_eod_win_rate` (lines 934–1028)

**What happens:**
The pre-session win rate table (printed before the signal analysis section) measures:
> "If you entered every trading day at OR close unconditionally, what % of days was EOD positive?"

It does not filter for days where a BULL signal fired, nor does it apply the `min_vol_ratio` gate.
The signal analysis below it filters BULL + `min_vol_ratio`. These are different trade populations
printed back-to-back, with no clear note that the metrics are incomparable.

A ticker can show 70% EOD win rate in the pre-session table but only 40% win rate in the BULL
signal analysis (or vice versa), which can confuse interpretation.

**Fix (proposed):**
Add a header line above the pre-session win rate table making the unconditional nature explicit:
```
Pre-Session Win Rate (unconditional hold from OR close — no signal filter)
```

---

## S4 — Pre-session history entry anchor is 5 min off from earliest possible signal bar

**Status:** [x] Fixed — changed anchor from `or_bars * 5` to `(or_bars - 1) * 5` in both `_compute_hold_history` and `_build_presession_picks_rows`; tests updated accordingly
**Severity:** Low — minor calibration mismatch between pre-session history and signal P&L

**File:** `ma_open_range_momentum_screener.py` line 944

**What happens:**
`_compute_hold_history` anchors entry at:
```python
or_close_time = (datetime.strptime(or_start, "%H:%M") + timedelta(minutes=or_bars * 5)).time()
# For 09:30/3b: or_close_time = 09:45
```

This is the bar **after** the OR window closes (09:45 open, 09:50 close).

But `_scan_ticker` starts the collection scan at the **last OR bar** (`from_or.iloc[or_bars - 1]`),
which for 09:30/3b is the bar at 09:40 (close = 09:45). A signal can fire there — 5 minutes
earlier than what the pre-session history assumes as entry.

Consequence: when a signal fires on bar 1 of the collection window, the pre-session history win
rates are calibrated to an entry 5 minutes later than the actual signal entry. The discrepancy
disappears for signals firing on bar 2 (09:45), and reverses for bar 3 (09:50).

**Fix (proposed):**
Change the anchor in `_compute_hold_history` to match the first collection bar:
```python
or_close_time = (
    datetime.strptime(or_start, "%H:%M") + timedelta(minutes=(or_bars - 1) * 5)
).time()
# For 09:30/3b: or_close_time = 09:40
```

---

## S5 — `warmup_start` in `run_range_analysis` may provide fewer than 20 trading days for early-range signals

**Status:** [x] Fixed — bumped from 30 to 45 calendar days
**Severity:** Low — vol_20day_avg is statistically weaker for signals in the first few days of the date range

**File:** `ma_open_range_momentum_screener.py` line 1174

**What happens:**
```python
warmup_start = start_date - timedelta(days=30)
```

30 calendar days normally yields ~20–21 trading days, but in January (New Year's + MLK) or around
holiday clusters it can fall to 18–19 trading days. `_compute_collection_vol_20day_avg` then
computes the baseline from fewer samples, making the volume threshold noisier for the first
few signals in the range.

**Fix (proposed):**
Use a larger calendar buffer (e.g. 45 days) to ensure 20+ trading days are reliably available:
```python
warmup_start = start_date - timedelta(days=45)
```

---

## S6 — `Total P&L` column label is misleading (it is sum of % returns, not dollar P&L)

**Status:** [x] Fixed — renamed column to `Sum Ret%`
**Severity:** Low — cosmetic mis-labeling

**File:** `ma_open_range_momentum_screener.py` line 1140

**What happens:**
```python
total_pnl = sum(pcts)
```

The column header says `Total P&L` but the value is the **sum of per-trade percentage returns**,
not a dollar figure. For 10 signals each returning +2%, it prints `+20.00%`. This only equals
actual dollar P&L if every trade is sized identically (equal-weight assumption).

**Fix (proposed):**
Rename the column header to `Sum %` or `Tot Ret%` to make it unambiguous.

---

## S7 — CRWD appears twice in CLI command (not a code bug — input error)

**Status:** [ ] Acknowledged — no code change needed; remove the duplicate from future CLI invocations
**Severity:** Low — no double-counting (dict-based fetch and signal detection deduplicate automatically), but messy

**Command:**
```
--tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT CRWD
```

CRWD is listed at positions 10 and 20. The code deduplicates via dict keying in `bars_5m` and
`compute_or_ma_signals`, so no signal is counted twice. But the `tickers` list passed to
`run_range_analysis` has 20 entries instead of 19, which slightly affects display counts.

**Fix:** Remove the duplicate from the command.
