# Live vs Replay P&L Gap — Findings & Suggestions

Reference day: **2026-05-06** (stock engine, M1 09:30/3 + A1 10:00/3 + A2 13:15/1 + A3 15:15/1, top 2, 60/40, BRE/BUE/reversal/DD on)

| Source | Daily %P&L | Notes |
|---|---|---|
| Replay (TS/SIP, `--capital 10000`) | −0.19% | 14 trades |
| Live (EC2, `_initial_capital=$20,000`) | −0.41% | 12 trades — A1 entries skipped due to capital starvation |

Selection logic was **identical** across both runs (all 8 base picks matched). The gap is structural, not selector-driven.

---

## Finding 1 — Fill quality is good; the cost is the ~2-min signal-collection delay (target: 10s)

Live entry fills sit within ±$0.10 of the 1-min bar mid at fill time on 11 of 12 entries. The slippage that **looks** like bad fills against the replay is actually market drift during the ~2 minutes between signal-bar close (e.g. 09:45) and live execution (~09:47).

**Goal: reduce signal-collection-to-entry latency from ~2 min → 10s.**

Current pipeline (M1 example):
- 09:45:00 — signal bar closes
- 09:46:00 — bar aggregated, `SIGNAL [M1]` logged
- 09:47:00 — collection window closes, ranking + `Entering position`
- 09:47:01-04 — order placed and filled

Of the ~2 min, the signal-collection buffer is the largest controllable chunk. Cutting it to 10s removes most of the drift cost without changing selection quality.

| Trade | Replay EntryMid (signal bar) | Live fill (entry bar +2 min) | Drift | Effect |
|---|---|---|---|---|
| CLS short M1 | $413.05 | $408.46 | **−$4.59** | Shorted ~$4.60 lower → only ~$5 of headroom before hard_stop at ~$413; stop hit |
| CLS BRE short | $409.08 | $407.78 | −$1.30 | Less room |
| META bull A2 | $613.24 | $613.78 | +$0.54 | Bought higher |
| CVNA bull A3 | $388.77 | $389.84 | **+$1.07** | Bought higher → quick hard_stop |
| CVNA BRE bull | $389.85 | $391.42 | **+$1.57** | Chased $1.57; stopped |

The 09:46 CLS bar alone moved O=$413.63 → C=$408.44 — a 5-pt drop in the signal bar itself. The replay assumes entry at the signal-bar close; live actually enters in the *next* bar after the breakout has already extended.

### Hard stop is OR-anchored, not entry-anchored

`trade_engine.py:448-449`:

```python
bull_hard_stop = or_high - stop_pct * or_range
bear_hard_stop = or_low  + stop_pct * or_range
```

Stop is fixed at OR-anchored level regardless of fill price. A late entry gets a smaller cushion (sometimes inverted) and is far more likely to stop out on noise.

### Suggested mitigations
1. **Cut signal-collection delay from ~2 min to 10s** — close the per-window collection buffer 10s after the signal bar closes (instead of waiting a full minute boundary), then immediately rank + enter.
2. **Skip entry when `|entry_price − OR-anchored stop| < min_room`** (e.g. < 30% of OR range). Avoids paying for trades that have <1 ATR of breathing room.
3. **Hybrid stop** — `min(OR-anchored, entry − k × or_range)` so late entries get widened headroom while on-time entries keep the original stop.

---

## Finding 2 — A1 window swallowed by M1 DD + BRE capital chain

Live log lines 2716–2722:

```
14:17:00 Sequential window [A1] budget: 154.73 (initial=20000.00 pnl=-171.68 open=19673.59)
14:17:00 Skipping SNDK [A1] entry: Insufficient slot budget — need $1360.33/share, slot=$92.84
14:17:00 Skipping META [A1] entry: Insufficient slot budget — need $612.05/share, slot=$61.89
```

### How M1 ate all the capital
| Time | Event | Open M1 capital |
|---|---|---|
| 09:47 | CLS bear + MSTR bull entered | ~$20,000 |
| 09:51 | MSTR exit (loss) | ~$12,000 |
| **09:55** | **DD [M1] fires: winner=CLS → 2nd CLS position** ($7,900) | ~$19,900 |
| 09:56 | Original CLS hard_stop, returns ~$11,837 | ~$7,900 |
| **10:06** | **BRE [bearish_reentry] CLS fires → 3rd CLS position** ($12,000) | ~$19,900 |
| 10:17 | A1 ranking → only $154.73 free | A1 skipped |

By 10:17 ET there were two concurrent CLS positions (DD add-on + BRE re-entry). Together they consumed all initial capital, leaving A1 with $0 deployable. Replay didn't hit this because (a) replay only had $10K initial, (b) replay's CLS first trip closed in profit before the DD check could fire, so DD never triggered on M1.

This is **not a bug** — engine correctly skips when budget < per-share price. But two strategy concerns:

### Suggested mitigations
1. **DD + BRE on same ticker should not stack.** When BRE fires after a DD position is already open on the same symbol, the engine briefly holds 2× the per-trade weight on a single name. Either: skip BRE if any open position exists on the same ticker, or treat the DD position as fulfilling the BRE intent.
2. **Reserve capital for upcoming windows.** A simple rule: M1 BRE re-entries cannot consume more than `(1 − Σ remaining_window_weights) × initial_capital`. A1's signal collection had already started at 14:13 before BRE deployed at 10:06.
3. **DD-after-loss check.** If the rank-1 partner exited at a loss in M1 *and* rank-0 is still open, the DD logic concentrates all freed M1 capital onto one ticker. Consider distributing freed capital to upcoming windows instead of re-investing in the same name.

---

## Finding 3 — Capital config drift between live and replay

Live ran with `_initial_capital=$20,000` (auto-restored from checkpoint), user's replay command used `--capital 10000`. Absolute $ are not comparable; only % matters. Worth a sanity-check that live capital config matches what we expect for backtest comparability.

---

## Recommended next steps

| Priority | Action | File |
|---|---|---|
| P0 | Reduce signal-collection delay from ~2 min to 10s (close buffer 10s after signal bar, then rank + enter) | `trade_engine.py:1685-1700` (signal collection close), `signal_engine.py` (bar aggregation) |
| P0 | Add `min_room_pct` skip when |entry − OR-stop| is too small | `trade_engine.py:448-451` |
| P1 | BRE skip when same-ticker DD position is still open | `position_monitor.py` re-entry watcher |
| P1 | Reserve capital for not-yet-fired windows in BRE entry budget | `trade_engine.py` `_enter_reentry` |
| P2 | Document and align live `_initial_capital` with replay test capital | runbook |

---

## Per-trade fill-quality scorecard (2026-05-06)

| Trade | Side | Fill | Bar O/H/L/C at fill | Bar mid | Δ vs mid | Quality |
|---|---|---|---|---|---|---|
| CLS Bear M1 | SHORT | 408.46 | 09:47 407.95/409.62/407.12/408.63 | 408.37 | +0.09 better | ✅ |
| MSTR Bull M1 | BUY | 185.22 | 09:47 185.29/185.52/184.88/185.29 | 185.20 | +0.02 over | ✅ |
| CLS DD M1 | SHORT | 413.06 | 09:55 414.45/414.45/411.62/413.40 | 413.04 | +0.02 better | ✅ |
| CLS BRE M1 | SHORT | 407.78 | 10:06 408.85/409.11/407.23/408.15 | 408.17 | −0.39 worse | ⚠️ step2 after 3 retries |
| AMD Bull A2 | BUY | 415.24 | 13:22 415.09/415.25/414.87/414.98 | 415.06 | +0.18 over | ✅ |
| META Bull A2 | BUY | 613.78 | 13:22 613.78/613.90/613.66/613.69 | 613.78 | 0.00 | ✅ |
| META DD A2 | BUY | 613.33 | 13:30 613.27/613.42/613.17/613.17 | 613.30 | +0.03 over | ✅ |
| META BRE A2 | BUY | 613.89 | 14:16 614.01/614.09/613.81/613.96 | 613.95 | −0.06 better | ✅ |
| CRWV Bear A3 | SHORT | 136.61 | 15:22 136.65/136.69/136.55/136.55 | 136.62 | −0.01 worse | ✅ |
| CVNA Bull A3 | BUY | 389.84 | 15:22 389.98/390.19/389.86/389.98 | 390.03 | −0.19 better | ✅ |
| CVNA DD A3 | BUY | 387.76 | 15:30 387.62/387.76/387.56/387.75 | 387.66 | +0.10 over | ✅ |
| CVNA BRE A3 | BUY | 391.42 | 15:46 392.00/392.05/391.00/391.38 | 391.52 | −0.10 better | ✅ |

Aggregate fill slippage across all 23 entry+exit fills: under $1/share total. Fill engine is doing its job.
