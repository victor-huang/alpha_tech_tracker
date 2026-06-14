# Backtest Param & Scoring Re-Tuning — Principles & Guidelines

**Purpose:** A disciplined process for deciding *when* and *how* to re-tune the
op_momentum selector's parameters and scoring formula — and, just as importantly,
when **not** to. Written to prevent the most common failure mode: overfitting the
config to the most recent painful stretch.

**Scope:** Applies to the selector backtest config (scoring weights, regime overlay,
gates, stops) — e.g. the `best_known` Option A/B stacks and the QQQ-regime overlay.

---

## First Principle: every "best config" is a fit to history — assume it will decay

The current best configs (`e0.60+ev15+rel0.15`, the bear overlay from Exp 25–27)
were optimized to maximize the **8-year sum** and **2022 bear-year protection**.
That optimization already "saw" 2019–2026. So the honest prior is:

> The config works **until the regime mix shifts to something underrepresented in
> that 8-year history.**

You cannot know in advance that it keeps working. You can only **monitor whether it
is still behaving inside its own backtested envelope**, and react when it is not.

---

## Know the config's expected envelope BEFORE going live

This is the step most often skipped. From the backtest you already have the
per-year / per-month distribution for the exact config. Turn it into a
**control chart** — the "this is normal" band:

- Worst historical month / year (e.g. this config: **2022 ≈ −28%** by design).
- Win-rate range (blended ~52%, but **per-week 0W/7L does occur** — it is in-band).
- EV-per-trade range, avg-win / avg-loss range.
- Known dead patches (e.g. **March 2026 dead week** from MA-lag mislabeling).

**A negative month inside the band is not a signal to retune.** 2022 returning −28%
is the strategy *working as designed*, not failing.

---

## When to tune vs. when to do nothing

### Do nothing (do not touch params) when:
- A single bad week, or a flat / no-trade stretch. A **zero week** (e.g. W12 Mar 2026)
  means a gate stopped you from trading — that is **participation**, often the
  *correct* behavior, not a loss.
- Drawdown is within the historical envelope for the current regime.

### Investigate (diagnose, do NOT yet tune) when one of these breaches the band:
- **Rolling EV-per-trade** drops below the backtest's per-regime range and *stays
  there* (a month+, not one week).
- **Win rate / avg-win-pct** drift below the backtested distribution while the regime
  looks like one the config historically handled well.
- **Walk-forward efficiency ratio collapses** (see `M1_WALKFORWARD_TEST.md`):
  `efficiency = OOS P&L ÷ oracle P&L`.
  - Near 1.0 → selection still predictive.
  - Near 0 → past config stopped generalizing.
  - **Negative → config is actively losing where the oracle still wins** ← the real
    "broken" signal.

### The distinction that matters
> Is the loss because the **edge disappeared**, or because **selection stopped
> tracking an edge that is still there?**

The **oracle ceiling** answers this. (2023 research: oracle +429% vs captured +38% —
the edge was always there; *ranking* was the bottleneck.) If the oracle is still
profitable while you lose, the signal exists and the **ranking/params** are the
problem — that is tunable. If the oracle also collapses, the edge itself is gone.

---

## The Re-Tune Protocol (only after a breach is confirmed real, not noise)

Never tune blind. Follow the same sequence used on the March 2026 dead weeks:

1. **Decompose the loss into a layer.** Is it:
   - *Selection* — wrong tickers (check oracle gap)?
   - *Entry* — signal / fill quality?
   - *Exit* — stops too tight / loose?
   - *Participation* — regime gate starving or over-trading?

   Example: March 2026 W12 had **zero trades** → exits/scoring were irrelevant; it was
   purely participation. Tuning the wrong layer is wasted overfitting.

2. **Require a mechanism hypothesis tied to what changed in the market.**
   "Returns went negative" is not a reason. "MAs lag in fast recoveries, so
   `full-only` mislabels recovery days as `true_bear`, where `no-bullish` kills the
   right bullish picks" *is*. **No mechanism → no change.** This is the single biggest
   guard against curve-fitting.

3. **Change ONE knob — the one with a regime rationale, not the one that best fits the
   bad stretch.** Prefer making a filter *conditional / adaptive* over deleting it
   (e.g. suppress bullish only on *confirmed* bear, not every MA-lagging day), or
   revert toward a simpler, more robust config.

4. **Two validation gates — both mandatory:**
   - **Walk-forward / in-sample:** clip data to *before* the unknown future
     (e.g. `--end 2026-03-13`). The change must help on data you would actually have had.
   - **Regression test against the regime the feature exists for:** re-run the years
     the param was added to protect (2022 for the bear overlay). Worked example:
     dropping `no-bullish` fixed March 2026 (**+3.3pp YTD**) but cost **−9.7pp in 2022**
     → a *failed* gate. A change must hold the wins it was protecting.

5. **Multi-year adoption bar.** Only promote a change that is **neutral-or-better across
   the full 8-year distribution**, not one that only rescues the current pain. Most
   candidates in the research log (`or_vol_ratio`, `frog`, `ev_shrink`, `52w-high`)
   improved one year and were **rejected** for hurting the 8yr sum. Match that bar.

---

## Structural Guard Rails

- **Sample-size honesty.** Two weeks — even a month — is too little to retune on.
  Demand a change survive multiple years and multiple regimes before it touches
  production.
- **Pre-register your triggers.** Decide the EV / win-rate / efficiency-ratio thresholds
  that justify a re-tune **before** the drawdown, so you don't rationalize after the
  fact. Reactive tuning on every dip is exactly how you overfit to the latest regime.
- **Champion / challenger — never hot-swap.** Run the new config in paper / replay
  alongside the live one for a few weeks. Promote only when the challenger's *live*
  behavior matches its backtest **and** beats the champion out-of-sample.
- **Scheduled re-validation beats reactive tuning.** Use the `reoptimize_trading_windows`
  skill and the walk-forward roll on a fixed cadence (monthly / quarterly) to *check*
  whether the config still generalizes — catch decay early instead of waiting for a
  painful drawdown to force a panicked, overfit change.

---

## The One-Line Rule

> Do not tune because returns went negative. Tune when the strategy is losing **where
> the oracle still profits** (edge intact, ranking broke) **or** when live metrics fall
> **outside the config's own backtested envelope** — and only after you can name the
> market mechanism that changed. Then change one regime-justified knob, prove it on
> walk-forward **and** against the regime it was meant to protect, and promote it via
> champion/challenger — never on the strength of the bad stretch alone.

---

## Worked Example: March 2026 Dead Weeks (reference)

| Step | Finding |
|---|---|
| Symptom | W12 (Mar 16–22) fired **0 trades**; W10 went 0W/7L. |
| Layer | **Participation** — regime gate, not exits/scoring. |
| Mechanism | `full-only` labels MA-lagging recovery days as `true_bear` (factor 1.0); `no-bullish` (selector_backtest.py:1791) then suppresses the bullish recovery picks. `latch=0d` → recovery-floor was inert (an early wrong guess). |
| Candidate fix | Make `no-bullish` conditional on a *confirmed* bear (MA20 slope still down), not every true_bear-classified day. |
| In-sample (Jan1–Mar13) | drop-no-bullish: +40.5% vs +35.5% baseline (**+4.9pp**) ✓ |
| 2022 regression | drop-no-bullish: **−2.96% vs +6.75%** (**−9.7pp**) ✗ — global drop fails the gate. |
| Verdict | Don't drop globally. Either accept the ~3pp March drag as 2022 insurance, or implement the *conditional* slope-up escape and re-validate on 2022 **and** 2026. |
