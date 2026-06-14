# Option D Investigation: MA8 × MA20 Cross as Profit-Protection Trigger

## What Option D Is

After entry, monitor the intraday relationship between MA8 (8 × 5-min bars = 40 min) and
MA20 (20 × 5-min bars = 100 min). When MA8 rises above MA20 (BULLISH) or falls below MA20
(BEARISH), switch the trailing exit from MA20 to MA8 for the remainder of the trade.

Hypothesis: MA8 crossing above MA20 means short-term momentum is now stronger than
medium-term — the trend is accelerating. At that moment MA8 is already above MA20 (which
itself is above the hard stop), so the tighter MA8 is safely placed in profitable territory.
Using MA8 from entry would shake out too many trades; using it only after the cross reserves
MA8 for confirmed momentum moves.

---

## Three Design Decisions

### Decision 1 — Cross-based vs state-based activation

| Mode | When latch fires |
|---|---|
| **Cross-based** | MA8 was ≤ MA20 at entry, then crossed above *during* the trade |
| **State-based** | Any bar where MA8 > MA20, even if already true on bar 1 |

Cross-based is harder to implement (needs prior-bar tracking) and has a silent-fallback risk:
on strongly trending days MA8 may already be above MA20 at entry, so the cross never fires
in-trade and Option D silently behaves like baseline the whole day.

**Recommended: state-based.** If MA8 > MA20 on bar 1, upgrade immediately. On choppy days
where they never cross, fall back to baseline MA20 throughout.

### Decision 2 — One-way latch vs continuous toggle

| Mode | Behavior after upgrade |
|---|---|
| **One-way latch** | Once MA8 > MA20 seen, stay on MA8 even if MA8 later drops back below MA20 |
| **Continuous toggle** | Use MA8 when MA8 > MA20, revert to MA20 when MA8 ≤ MA20 |

Continuous toggle means *loosening* the trailing stop mid-trade — the opposite of profit
protection. **Use one-way latch.**

### Decision 3 — Guard condition for MA8

Current MA20 guard (BULLISH): `bar_ma20 > hard_stop_price`.
When MA8 > MA20 and MA20 > hard_stop_price, MA8 is automatically above hard_stop_price too.
Apply the same explicit guard `bar_ma8 > hard_stop_price` for safety.

BEARISH guard: current `bar_ma20 < or_low` → apply `bar_ma8 < or_low` when MA8 is active.
When MA8 < MA20 < or_low the guard is satisfied by implication, but keep the explicit check.

---

## Comparison vs Option B

| Dimension | Option B (move-threshold) | Option D (MA8 cross MA20) |
|---|---|---|
| Trigger | Price moved N × OR range past entry | MA8 risen above MA20 intraday |
| Market info used | Price distance (raw momentum) | MA relationship (momentum acceleration) |
| When it fires | As soon as price reaches threshold, regardless of MA state | Only when MA8 actually crosses (can be early or never) |
| Main risk | Triggers on noisy one-bar spikes that immediately reverse | May never trigger on slow steady trends where MA8 barely nudges MA20 |
| Correlation with B | High when N=1.0 (arm threshold ≈ MA cross on strong moves); diverges on slow or fast moves | — |

---

## Red Flags to Watch For After Running Tests

1. **Option D fires on bar 1 for most trades** — MA8 was already > MA20 at entry. This means
   Option D is functionally identical to always using MA8 from the start. Distinguish by
   counting upgrades that happen on bar 1 vs later.

2. **Option D rarely fires** — MA8 never crosses MA20 during most trades. Would be nearly
   identical to baseline. Check via `trailing_stop_ma8` count in exit_reason breakdown.

3. **Win rate drops significantly** — MA8 shaking out good trades before they run. Expected
   tradeoff is lower win rate but higher avg win; if both go negative, Option D is net negative.

4. **Option B and D produce nearly identical P&L** — the two triggers are highly correlated
   intraday. If so, Option B wins on simplicity (cleaner CLI, no MA crossover dependency).

---

## Test Matrix

All runs use the standard SOA config:
```
--top 3 --weights 50 30 20 --regime-filter --regime-ma 8
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
--reversal --bearish-reentry --bullish-reentry --doubledown --doubledown-start 5 --feed iex
```

| Config | Flag |
|---|---|
| Baseline | *(none)* |
| Option B after-arm | `--trailing-ma-switch after-arm` |
| Option B 1.5× | `--trailing-ma-switch after-target --trailing-ma-switch-factor 1.5` |
| Option D | `--trailing-ma-switch ma8-cross-ma20` |

Run periods: 2024, 2025, 2026 YTD.

Metrics: total return, win rate, EV/trade, avg win P&L, avg loss P&L, `trailing_stop_ma8`
count, `end_of_day` count.

---

## Implementation Scope (when ready to build)

### `op_momentum_backtest.py`
- Compute `df["MA8"]` alongside MA20/MA50/MA200
- Add `trailing_ma_switch: str = "none"` param to `compute_signals_with_backtest()`
- Add `use_ma8` one-way latch in primary loop (state-based: check `bar_ma8 > bar_ma20`)
- Apply same latch in reversal, BRE, BUE sub-loops (using `bar_ma8 < bar_ma20` for bearish)
- `exit_reason = "trailing_stop_ma8"` to distinguish from `"trailing_stop_ma20"`
- Add `--trailing-ma-switch ma8-cross-ma20` CLI choice

### `op_momentum_selector_backtest.py`
- Add `trailing_ma_switch` to `run_selector_backtest()` signature
- Pass through to `compute_signals_with_backtest()` call (line ~582)
- Add CLI flag

### Not in scope yet
- Live trade engine (`position_monitor.py`) — defer until backtest confirms positive edge

---

## Status

**Pending** — Option B (move-threshold) is being implemented first. Run the test matrix
above after Option B is in place, since Option B provides the `--trailing-ma-switch`
infrastructure. Option D would add `ma8-cross-ma20` as a new choice to the same flag.
