# Code Review — 2026-05-02 Remaining Commits

Adversarial review of May 2 commits not covered in the prior session's review
(b76b1eb, 5710ad6, ca390b3, f6a9727 were reviewed separately).

| SHA | Summary |
|---|---|
| `d65b875` | feat: sweep and lock optimal 4-window config (A1/A2/A3) |
| `94a7bae` | fix: correct sequential window capital flow in backtest and live replay |
| `2638c09` | fix: cancel BRU/sub-trades in BT when Phase 2 capital recycled or DD fires |
| `fc9e17b` | fix: annotate cancelled sub-trades in BT display |
| `4b556df` | feat: add stock fill quality analysis script |
| `92134dd` | feat: add --score-feed flag to decouple selector scoring feed |
| `0d68e09` | feat: add entry/exit times to sub-leg and DD rows in execution log |
| `63603dc` | docs: document G37/G38 structural BT/RP gaps |
| `f97189b` | fix: use Alpaca client in mock/replay mode |
| `866d491` | feat: add QQQ/VIX/P&L weekly chart and generation script |
| `3e25830` | feat: add dual-engine bar broadcaster via Unix domain socket |
| `5e9ad95` | feat: integrate broadcaster heartbeat into stream watchdog |

---

## CONFIRMED BUGS

None.

---

## DISMISSED FINDINGS

### Socket reader thread race on engine stop (3e25830 / 5e9ad95)

Concern: `readline()` blocks; `stop()` closes the socket before the reader thread wakes.

`_reader_loop()` handles both outcomes of socket closure:
- `OSError` → caught at line 124, `break` exits the loop.
- Empty string `""` → caught at line 126 `if not line: break`, exits the loop.

Either path leads to the reader thread exiting within milliseconds of socket close, well
within the 3-second `join(timeout=3)` in `stop()`. **Not a bug.**

### Zero entry_price in Phase 2 (94a7bae)

Concern: `_compute_primary_cap_pnl` returns 0 when `entry_price <= 0`, causing
`day_pnl_correction = cap_pnl - 0 = cap_pnl` (double-subtraction).

`cap_pnl` is computed at line 261 by the same `_compute_primary_cap_pnl` call — if
`entry_price <= 0`, `cap_pnl` is already 0 there. So Phase 2's correction becomes
`0 - 0 = 0`. No double-counting. Zero entry_price is also a data-error scenario that
can't produce a non-zero `cap_pnl` through any other path. **Not a bug.**

### DD re-entry cancellation scope (2638c09)

Concern: Cancellation keyed on `(window_label, ticker)` could match watchers from
other windows for the same ticker.

Filter: `w.window_label == label and w.ticker in stopout_tickers`. The `window_label`
guard prevents matching watchers from other windows. If SHOP trades in both M1 and A1,
an M1 DD stopout only cancels M1 watchers. **Not a bug.**

### 94a7bae — Phase logic edge cases

Three edge cases verified clean:
- No closed positions when next window opens: `available` starts at `portfolio`,
  loop adds nothing, window gets full portfolio. Correct.
- Phase 1 (primary still running) blocked correctly: line 314 checks
  `primary_exit_time > this_drain` and locks the slot capital out.
- PRE-CLOSE / flat-bar tickers with no sub-entries fall through to `cap_pnl`
  (computed at line 261) without entering Phase 2/3. Correct.

---

## OVERALL ASSESSMENT

All May 2 code-changing commits (beyond the BRE/BUE trailing-stop commits already
reviewed) are clean. No new issues require action.
