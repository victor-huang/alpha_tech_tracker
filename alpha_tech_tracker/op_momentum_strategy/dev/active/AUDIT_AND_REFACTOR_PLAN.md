# op_momentum_strategy — Audit and Refactor Plan

**Status:** Proposed — not started
**Scope:** `alpha_tech_tracker/op_momentum_strategy/` — Python and Markdown only, logs excluded
**Baseline:** working tree at commit `b4e14fc`

**Goal:** Fix three defects that affect live trading today, then make live/backtest
divergence structurally impossible rather than a thing maintained by hand. Each phase is
independently valuable and safe to stop after. No big-bang rewrite.

---

## Codebase Shape

| Metric | Value |
|---|---|
| Python LOC (package) | 47,242 (30,314 top-level + 16,928 subdirs) |
| Test LOC | 36,139 |
| Markdown | 131 files, 47,513 lines |
| Commits touching package (12 mo) | 391 |

Churn maps almost exactly onto file size — the signature of files that are hard to change
because they are large, and large because everything gets added to them.

| File | Lines | Commits/12mo | Largest unit |
|---|---|---|---|
| `op_momentum_selector_backtest.py` | 4,814 | 101 | `run_selector_backtest` — 1,135 lines, 138 params |
| `trade_engine.py` | 3,522 | 157 | `OpMomentumTradeEngine` — 2,985 lines, 36 methods |
| `op_momentum_backtest.py` | 2,258 | 67 | `compute_signals_with_backtest` — 921 lines |
| `position_monitor.py` | 1,995 | 100 | `PositionMonitor` — 1,890 lines, 26 methods |
| `op_momentum_trade_engine.py` | 1,344 | 89 | 98 `add_argument` calls |

Five files = **13,933 lines, ~514 commits**. `OpMomentumTradeEngine.__init__` takes **83
parameters**. The backtest CLI defines **150 flags**; the live CLI defines 98.

### Co-change coupling

Adding `--min-hold-minutes` required **9 edits across 3 files**, four of them copy-paste
duplicates. That is the normal cost here, not an outlier:

- `op_momentum_trade_engine.py` + `trade_engine.py` change together in **56%** of CLI-file
  commits — the two engine-construction blocks are 83 kwargs repeated verbatim, differing
  by one line (`op_momentum_trade_engine.py:1088` vs `:1259`).
- `models.py` **never changes alone** — 87% of its commits also touch `position_monitor.py`.
- The two `PositionMonitor` construction sites (`trade_engine.py:3129`, `:3314`) differ by
  2 lines of 24, and the replay site silently drops `option_price_monitor`.

---

## Part 1 — Act Today

These three are independent of any refactor and should not wait for one. All three were
verified directly against the code.

### 1.1 Live Alpaca key committed to a public repository — CRITICAL

`victor-huang/alpha_tech_tracker` is **public**. Two distinct API keys appear across five
tracked files; four carry the `AK` prefix, which CLAUDE.md documents as a **live** trading
key. Commit `6622678`, already pushed to `origin/open_market_momentum_stategy`.

| Key type | File |
|---|---|
| AK — live | `op_momentum_strategy/chart_helped_stops.py` |
| AK — live | `analysis_scripts/analyze_aligned_trades.py` |
| AK — live | `analysis_scripts/analyze_stop_quality.py` |
| AK — live | `analysis_scripts/analyze_weekly_stock_trades.py` |
| PK — paper | `alpha_tech_tracker/alpaca_engine.py` |

**Order matters — rotate first, clean up second.** The key is exposed right now, so
revocation is the only step that stops the exposure.

1. Revoke both keys in the Alpaca dashboard.
2. Audit the live account for unauthorized activity.
3. Purge from history (`git filter-repo` or BFG) and force-push. Deleting the files is not
   enough; the values remain in history.
4. Migrate these scripts to env vars / `config.json`.
5. Uncomment `.env` in `.gitignore:27` — it is currently **not** ignored. (`config.json`
   is ignored, line 65.)

Per the project security rules, notify #team-product-security if this key touched anything
Carta-adjacent.

### 1.2 Session restore zeroes option P&L and disarms the daily loss limit — CRITICAL

`ActivePosition` declares 44 fields; `to_dict` (`models.py:119`) persists 39. Among the six
dropped is `closed_contracts` — and closing an option moves the size there
(`position_monitor.py:1067`: `contracts -= filled; closed_contracts += filled`), so a
closed position carries its real size *only* in the field that is not saved.

Verified round-trip:

```
IN MEMORY      closed_contracts=10  contracts=0   cap_pnl = $2000.00
AFTER RESTART  closed_contracts=0   contracts=0   cap_pnl = $0.00
                                   ==> P&L LOST: $2000.00
```

`_rebuild_window_returned` computes
`effective_contracts = closed_contracts if > 0 else contracts` (`trade_engine.py:1747`)
→ `0`. That value feeds not only window budgets but the risk limit at
`trade_engine.py:1774` (`self._daily_realized_pnl += cap_pnl`), read by
`_is_circuit_breaker_tripped` at `:1788`.

**Consequence:** after any mid-session restart, every previously closed option trade
rebuilds as $0. A day already down $3,000 restores as flat, and `--daily-max-loss`
(default $5,000, `config.py:61`) stops protecting the account.

Aggravating factors:

- **Options-only.** Stock P&L uses `slot_capital / entry * raw` and is unaffected. Options
  are the live default (`op_momentum_trade_engine.py:1069`).
- **Invisible to replay/backtest.** `_recover_session` returns early under
  `mock_trade_execution` (`trade_engine.py:1907`), so this path only ever executes with
  real money.
- **Untested.** No test round-trips a closed option position through the checkpoint.

The other five dropped fields — `close_order_failed`, `close_order_reconciled`,
`close_retry_count`, `close_alert_sent`, `reconcile_pending_count` — mean a stuck position
also loses its retry/alert state across a restart, so a failed close is never retried.

**Fix:** persist all six fields; add a round-trip test that closes an option, checkpoints,
restores, and asserts P&L and retry state survive.

### 1.3 Documented live command runs a different strategy than every backtest — CRITICAL

Five selection parameters have opposite defaults across the two CLIs. Feeding README.md's
exact documented production command through the real `parse_args` diverges on all five:

| Parameter | Live default | Backtest default |
|---|---|---|
| `dynamic_ev_gate` | `False` | `True` |
| `adaptive_lookback` | `False` | `True` |
| `direction_split_ev_gate` | `False` | `True` |
| `qqq_or_weight` | `0.0` | `0.30` |
| `top` | `2` (`MAX_ACTIVE_SYMBOLS`) | `3` |

The backtest provides `--no-*` off-switches and defaults these **on**; the live CLI is
`store_true`/off and relies on the operator remembering all five. The live help text admits
it — *"Pass this to match the backtest, which defaults it ON"* — making this a known,
undefended trap.

> **Verify your real invocation before treating this as live exposure.** Only the command
> documented in `README.md` was checked. If the EC2 launch passes these flags explicitly,
> there is no live divergence — but the defaults should still be unified in code rather
> than in operator memory. Fixed structurally by Phase 1.

---

## Part 2 — The Parity Problem

The project's central claim is that the same logic drives live trading and backtesting.
It does not. The logic is duplicated and maintained by hand, and it has drifted.

`op_momentum_selector_backtest.py` imports nothing from `signal_engine`,
`position_monitor`, `order_executor`, or `position_sizer`. Two full exit engines exist side
by side; `ma_open_range_momentum_screener.py` is a third.

Git history shows the maintenance cost directly: **43 commits** mention parity, drift, or
mismatch, and **13** are explicitly "port feature X from backtest into live engine" —
including `560d0af`, which ported seven features at once.

### Suspected drifts

Reported by survey pass; confirm each against the Phase 2 harness before acting.

| Concept | Backtest | Live | Issue |
|---|---|---|---|
| BRU re-entry trigger | `op_momentum_backtest.py:1077` | `position_monitor.py:619` | Backtest requires `close > or_high AND close > MA50`; live checks only `close > or_high`. Live takes trades the backtest rejects. |
| Exit fill price | `:640, :652, :704` | `position_monitor.py:490` | Backtest defaults to bar-close fill and its help text claims it "matches live engine behaviour"; live always uses the intrabar override. Comment asserts a parity the code contradicts. |
| `bars_held` | `:721` counts every bar | `position_monitor.py:505` skips zero-volume bars | Gates every re-entry type; sparse tickers diverge. |
| `stale_cut` | `:730` | — | Backtest-only. |
| `timed_exit` / regime hold | — | `position_monitor.py:465` | Live-only. |
| Bearish reversal (BULL→BEAR) | `:1036, :1179` | — | Backtest-only. |
| `max_loss_pct` on re-entry legs | absent | `position_monitor.py:361` | Live applies it to all positions; backtest does not apply it to REV/BRE/BRU. |
| Scoring weights | 18 passed | 5 passed (`trade_engine.py:2351`) | Remaining weights silently zero live. |
| `min_ev` boundary | `< min_ev` skip | `<= min_ev` skip | Diverges for any positive `--min-ev`. |
| Min hold | `min_hold_bars`, bar-indexed, does not suppress `max_loss` | `min_hold_minutes`, wall-clock, suppresses everything | **The feature shipped in `b4e14fc` cannot currently be backtested.** |

### No parity test exists

No test anywhere compares live output to backtest output. `test_full_day_simulation.py` is
the only true end-to-end test and asserts against a hand-typed golden fixture
(`fixtures/full_day_nvda_bullish.json`). `run_replay` — the path that would make parity
checking cheap — is never executed end-to-end by any test.

Stale cross-reference already observed: `position_monitor.py:429` cites "backtest lines
510, 525", which are now the signal-classification block. The hand-maintained parity link
has already broken.

---

## Part 3 — Test Suite

36,139 lines of tests against 47,242 of source is a healthy ratio. The problem is what
those lines assert.

### 3.1 73 tests have never run

`pytest-mock` is not installed and is **absent from `requirements.txt`** — not a local env
slip, but unreproducible for anyone. Every test taking the `mocker` fixture errors at setup.
The selection is unlucky:

| File | Dead tests | Coverage lost |
|---|---|---|
| `test_trade_engine_regime.py` | 22 | Regime gate blocking counter-trend entries; all 4 capital-allocation tests |
| `test_signal_engine.py` | 12 | Bull/bear fire conditions, volume gates |
| `test_trade_engine.py` | 12 | Win-rate selector ranking, 90-day fetch windows |
| `test_screener_regime_integration.py` | 9 | Screener regime gating |
| `test_regime_engine.py` | 8 | Regime aggregation/persistence |
| `test_ma_open_range_momentum_screener.py` | 5 | |
| `test_position_monitor.py` | 4 | `_sync_open_position_qtys` retry/backoff |
| `test_ticker_stats_report.py` | 1 | |

Also: 23 skips are all `pytest.mark.integration` — `bar_broadcaster.py` (390 LOC) has a
273-line test file and **zero executing tests**. Three failures in `test_eod_exit_time.py`
hit the live network via `_run_window_selectors` and account for ~80% of suite wall clock.

### 3.2 Fixtures encode states production cannot produce

This is why 1.2 survived a well-covered file. `test_trade_engine.py:3819`
(`_make_checkpoint_position`) builds positions with `contracts=2, closed_contracts=0` — a
shape a real restored closed option **can never have**. The tests pass; production is broken.

The circuit breaker's threshold logic *is* tested (`test_trade_engine.py:4212–4233`), but
every test sets `_daily_realized_pnl` directly, so nothing covers how that value is rebuilt —
exactly where the bug lives.

> Note: an earlier survey claimed the daily max-loss circuit breaker "does not exist in
> source." That is **false** — it exists at `trade_engine.py:1783` with three call sites and
> a $5,000 default, and is tested. The real gap is narrower, as described above.

### 3.3 Assertion quality

- **174 tests assert only mock call counts.** `test_position_monitor.py:5279`
  (`test_gives_up_after_max_attempts_and_logs_warning`) asserts nothing but
  `call_count == 3` — never that the position was left unsynced or a warning emitted.
- **166 sites assert on log text**, including `assert "  3" in caplog.text` and
  dollar-formatted strings like `"+$763.00"` rather than `pos.realized_pnl`.
- **Setup is forked, not shared.** `test_position_monitor.py` has **23 distinct
  `_make_monitor` variants**; `test_trade_engine.py` has 49 method-helpers and zero
  fixtures. conftest helpers are used by only 15 of 33 files.
- **478 hardcoded `date(20xx, …)` literals** plus 84 `datetime.now()` uses will rot.

### 3.4 Untested and load-bearing

`_shrink_shares_for_insufficient_buying_power` (`order_executor.py:38`) silently resizes
real orders — zero test references. Also untested: the broker reconciliation loop
(`position_monitor.py:1151`), `_absorb_partial`, `bar_broadcaster.py`, and both P&L audit
tools — the auditors are themselves unaudited.

---

## Part 4 — Documentation

131 files, 47,513 lines. The research logs are a genuine asset. The operational docs are
actively misleading.

### 4.1 Live ticker universe is misdocumented

| | CLAUDE.md claims | Actual (`op_momentum_selector.py:49`) |
|---|---|---|
| Documented, absent | SNDK, RH, FN | SNDK commented out ("price is too high"); RH/FN not present |
| Present, undocumented | — | **CHTR, JPM, TSLA** |

Three of 17 tickers wrong — 18% of the traded universe. The code contradicts itself: the
comment on `CRWV` reads *"replaced TSLA 2026-04-12 … TSLA peaked"* while `TSLA` sits two
lines above. **Confirm whether the TSLA re-add was deliberate.**

### 4.2 Other drift

- **Penny Pilot list inverted.** CLAUDE.md:319 lists SNDK/EXPE as Penny Pilot;
  `option_price_monitor.py:436` has them in `_NON_PENNY_PILOT_TICKERS` (with CHTR). Code is
  right; the doc is what someone would consult before "fixing" it, and wrong tick size
  causes live order rejections.
- **Every documented command is uncopyable.** 49 occurrences across 23 files use
  `PYTHONPATH=/Users/victorhuang/…`, missing the dot. **Zero** files have it right,
  including all three entry points.
- **Scoring formula wrong.** CLAUDE.md:482 documents 4 terms; `score_ticker()`
  (`op_momentum_selector.py:283`) takes 18 weight parameters. It also cites two `--score-*`
  flags that `op_momentum_selector.py` does not expose.
- **Stale parameters:** Top-N documented 3 / actual 2; lookback documented 60 / live engine
  30; `--regime-ma 8` presented as confirmed-best while every code default is 5.
- **Maps stale:** Test File Map lists 11 of 33 files; 25 top-level modules undocumented
  (incl. `regime_engine.py`, `replay.py`, `session_state.py`, `ma_open_range_momentum_screener.py`).
- **Bug trackers are archive:** `LIVE_ENGINE_GAPS.md` is 729 lines, ~89% closed. G36–G38
  collide against different content in `BUGS.md`.
- **Window labels forked four ways** across skills, CLAUDE.md, and guides — CLAUDE.md's
  A1/A2 are shifted two slots from the live `replay-year` skill.
- **`FINDINGS.md` is not an index** — 1,031 lines with 3 links, two of them broken.

### 4.3 Free fix

`op_momentum_selector_backtest.py --help` still crashes:

```
ValueError: unsupported format character '?' (0xd7) at index 247
```

Unescaped `%` at `op_momentum_selector_backtest.py:4243` — `"entry ± 80% × bar range"`.
Commit `200b832` fixed the live CLI and missed this file. One-character fix (`%` → `%%`).

---

## Part 5 — Scripts

61 analysis scripts + 24 top-level tools, ~25,300 LOC. Reported by survey; spot-checked.

- **~3,800–4,200 LOC is genuine copy-paste.** 12 scripts hand-build an Alpaca client
  instead of using the shared `fetch_bars`; five independent per-trade P&L implementations;
  10 log parsers for 3 formats; candlestick rendering written 5 times.
- **The 29 sweep scripts are structural clones** — 45% of lines non-unique, `_run_one`
  appears 21 times. One parameterized runner (~200 LOC) plus a config dict per study
  replaces **~80% of 3,601 LOC**.
- **15 sweeps are broken** — they set `PYTHONPATH=/Users/victorhuang/…`, so every
  subprocess exits `ModuleNotFoundError`. Same root cause as 4.2.
- **Correctness bug in a live tool:** `fetch_broker_pnl.py:126` charges fees for Alpaca but
  not TradeStation, so its "daily P&L" is not comparable across brokers.
- **Three files are misfiled core:** `contract_selector.py`, `option_price_monitor.py`,
  `mock_option_pricer.py` are imported by the engine itself.
- **19 files import `_apply_capital_flow` / `_parse_weights`** from the backtest. These
  private symbols are de facto public API and must be promoted before any refactor of
  `op_momentum_selector_backtest.py`.

---

## Part 6 — Refactor Plan

Ordered so each phase is independently valuable and safe to stop after. Phases 0–2 pay for
themselves regardless of whether the rest happens.

### Phase 0 — Stop the bleeding

**~1 day. No design decisions.**

1. Rotate leaked keys; purge history (§1.1).
2. Persist the six missing `ActivePosition` fields; add checkpoint round-trip test (§1.2).
3. Add `pytest-mock` to `requirements.txt`; fix whatever the 73 revived tests reveal —
   **expect real failures** (§3.1).
4. Escape `%` at `op_momentum_selector_backtest.py:4243` (§4.3).
5. Mock the network in `test_eod_exit_time.py` — recovers ~80% of suite wall clock.

**Exit criteria:** suite runs green with zero errors, offline, in under 30s.

### Phase 0.5 — Mechanical file decomposition

**Status: 0.5a, 0.5b, 0.5c DONE (commits `b6f3fcf`, `f316c01`, `b3a5e90`).**

| Step | File | Before | After | Test changes |
|---|---|---|---|---|
| 0.5a | `op_momentum_trade_engine.py` | 1,344 | 217 | 1 patch-path retarget |
| 0.5b | `op_momentum_selector_backtest.py` | 4,814 | 2,793 | none |
| 0.5c | `trade_engine.py` | 3,522 | 3,067 | 41 patch-path retargets |

Baseline held throughout: 3 failed (pre-existing network), 2,140 passed, 23 skipped,
73 errors (pre-existing, pytest-mock absent).

Two pre-existing crash bugs were fixed in passing (both in the backtest CLI, see §4.3
and below): `--help` raised `ValueError` on an unescaped `%`, and four
`parser.error(...)` calls in `__main__` raised `NameError` because `parser` was only
ever a local inside `_parse_args`.

> **Carry-over risk for Phase 0.** The 18 patch-path retargets in
> `test_trade_engine_regime.py` are **unverified** — every one sits in a
> `mocker`-fixture test, so none of them currently run. They were patching a module
> that no longer owns the function and would have broken silently once pytest-mock is
> installed. Re-run and confirm those specifically as part of Phase 0 step 3.

**~2–3 days. Pure moves — safe before the parity harness exists.**

Splittability is not size. The deciding metric is **what fraction of a file is one
indivisible unit**: a file that is 85–97% a single class cannot be split, only refactored
(which changes behavior and needs Phase 2 first). A file made of many independent
top-level functions is a package waiting to happen.

| File | Lines | Biggest unit | Importers | Verdict |
|---|---|---|---|---|
| `op_momentum_trade_engine.py` | 1,344 | `parse_args` 704L (**52%**) | **0** | **SPLIT — start here** |
| `op_momentum_selector_backtest.py` | 4,814 | CLI 1,022 + reporting 745 = **37%** peelable | 21 | SPLIT — peel CLI + reporting |
| `trade_engine.py` *(selectors only)* | 3,522 | `TickerSelector` + `WinRateTickerSelector` = 422L, **zero refs to engine class** | — | SPLIT — extract 2 classes |
| 6 standalone tools ¹ | 4,131 | standalone, 0 importers | 0 | DEFER — decide keep vs. archive first (§5) |
| `ma_open_range_momentum_screener.py` | 2,403 | max unit **11%**, 48 top-level funcs | 6 | LATER — most splittable, but it is the third copy of trading logic |
| `order_executor.py` | 1,038 | 2 twin funcs = 82% | 3 | LATER — split is a refactor; well covered (3,157 test LOC) |
| `op_momentum_selector.py` | 963 | `select_top_n` 344L (36%) | many | LATER |
| `op_momentum_backtest.py` | 2,258 | `compute_signals_with_backtest` 921L (41%) | — | **BLOCKED on Phase 2** — one function holds 4 re-entry simulators |
| `position_monitor.py` | 1,995 | `PositionMonitor` **95%** | — | **BLOCKED on Phase 2** |
| `signal_engine.py` | 1,044 | `LiveSignalEngine` **97%** | — | **BLOCKED on Phase 2** |
| `option_fair_price_tester.py` | 681 | class 73% | 0 | BLOCKED — class-dominated |
| `option_price_monitor.py` | 531 | class 63% | 3 | BLOCKED — class-dominated |

¹ `audit_pnl.py`, `audit_replay_pnl.py`, `fetch_ts_orders.py`, `fetch_alpaca_orders.py`,
`fair_price_backtest.py`, `option_fair_price_tester.py`.

**Method — every split follows the same rule:** move code, change nothing else, and leave
the original module as a re-export shim so all existing imports and tests keep working. The
split is verified by the **existing** suite passing untouched. No behavior change, no test
rewrites, no new logic.

#### 0.5a — `op_momentum_trade_engine.py`

Wins on every axis: 0 importers (it is a `__main__` entry point), no trading logic (52%
argparse + 18% helpers), #4 by churn (89 commits/12mo), and it holds the two duplicated
83-kwarg engine-construction blocks (`:1088`, `:1259`) that differ by one line — four of the
nine edits `--min-hold-minutes` required were in this file.

```
op_momentum_strategy/cli/
  __init__.py
  args.py            # parse_args, grouped by concern
  windows.py         # _parse_windows, _resolve_is_paper
  clients.py         # _build_market_data_client, _build_sip_quote_client,
                     #   _build_contract_selector, _build_option_price_monitor
  daemon.py          # _daemonize, PID handling, log rotation
  engine_builder.py  # ONE build_engine(args) replacing both duplicated blocks
op_momentum_trade_engine.py   # thin __main__ shim + re-exports
```

`engine_builder.py` is the seam into Phase 1: with one construction site, introducing
`StrategyConfig` becomes a local change rather than a 166-line edit across two blocks.

#### 0.5b — `op_momentum_selector_backtest.py` (partial)

Peel the two layers that contain no trading logic, leaving `run_selector_backtest` alone:

- `backtest/reporting.py` — 12 print/report/table/summary functions, 745L
- `backtest/args.py` — `_parse_args`, 1,022L

Removes **1,767 lines (37%)** from the largest file in the package without touching the
1,135-line core. The 21 external importers depend on `_apply_capital_flow` /
`_parse_weights`, not on these functions, so the shim keeps them working.

#### 0.5c — `trade_engine.py` (selectors only)

`TickerSelector` (265L) and `WinRateTickerSelector` (157L) contain **zero references** to
`OpMomentumTradeEngine` — verified by AST. Move both, plus `_next_trading_day` and
`_trading_days_in_range`, to `selectors.py` (~437L). The remaining 2,985-line god class is
untouched and stays blocked on Phase 2.

**Exit criteria for 0.5:** full suite passes with no test file modified; no `.py` over
1,400 lines except the four Phase-2-blocked files.

### Phase 1 — Unify defaults behind one config object

**~2–3 days. Highest risk-reduction per line changed.**

Define `StrategyConfig` as frozen dataclasses — `ScoringConfig`, `EvGateConfig`,
`ExitConfig`, `ReentryConfig`, `FeedConfig` — holding defaults **once**. Both CLIs build the
same object; engine and backtest both consume it. The existing `_dynamic_ev_gate_kwargs`
dict (`trade_engine.py:659`) is already a hand-rolled prototype of exactly this.

This collapses the 83-parameter constructor, deletes one of the two duplicated 83-kwarg CLI
blocks, and makes the five default divergences in §1.3 **structurally impossible**.

**Exit criteria:** one test asserting live and backtest resolve identical defaults for every
shared parameter. That test alone would have caught §1.3.

### Phase 2 — Pin parity with a golden-day harness

**~2–3 days. Do this before touching any shared logic.**

Pick 5–10 cached sessions covering: a long, a short, a stop-out, each re-entry type
(REV/BRE/BRU), and a double-down. Run each through both engines; assert identical trades and
P&L. Check outputs in as fixtures.

This is the safety net every later phase depends on, and it converts the §2 drift table from
opinion into a pass/fail list.

**Expect it to fail on first run — that failure is the deliverable.** Resolve each drift
deliberately (decide which side is correct) rather than making the harness pass.

### Phase 3 — Extract exit rules into one shared module

**~1 week. Guarded by Phase 2.**

Split `_evaluate_stop` (`position_monitor.py:346`, 162 lines) into:

- `ExitEvaluator` — pure; takes a position snapshot + bar, returns an exit intent
- `advance_on_bar` — explicit latching step (`hard_stop_armed`, `use_ma_fast`,
  `max_favorable_move`, `bars_held`, `trailing_arm_reached`)
- `ExitExecutor` — broker I/O, splitting the 424 lines of `_close_*_position`

Have **both** engines call `ExitEvaluator`. This is where hard stop, fallback, trailing MA,
MA-switch, min-hold, and re-entry triggers stop being two implementations.

Pure functions over value objects are far easier to test than the current mock-heavy setup,
so this phase improves §3.3 as a side effect rather than as extra work.

### Phase 4 — Execution adapter and injected clock

**~1 week.**

Replace 12 `is_replay_mode()` and 23 `mock_trade_execution` branches with three adapters —
live, mock, replay — behind one interface. Replace the module-global replay clock
(`replay.py:96`) with an injected one; that global is why `run_replay_range` must
save/restore `_replay_capital` and why replays cannot run in parallel in-process.

Then collapse `run` (`trade_engine.py:2954`) and `run_replay` (`:3221`) — currently 95%
structural copies — into one driver.

### Phase 5 — Capital accounting gets one home

**~3–4 days.**

Fold into a single `CapitalLedger`:

- the five copies of the cap-P&L formula (`trade_engine.py:1505, :1733, :1802, :1853`;
  `position_monitor.py:1835`)
- `_window_returned`, `_window_primary_deployed`, `_daily_realized_pnl`
- both `_get_window_budget` algorithms — including the 80-line branch labelled
  *"should not occur in normal operation"* (`trade_engine.py:2012`)

Money math in one auditable place, with the circuit breaker reading from it.

### Phase 6 — Prune scripts and docs

**~2–3 days. Parallelizable, low risk.**

Code:
- Promote `_apply_capital_flow` and `_parse_weights` to public API (19 callers).
- Move `contract_selector.py`, `option_price_monitor.py`, `mock_option_pricer.py` into the
  engine package; add tests.
- Replace 29 sweeps with one parameterized runner.
- Archive ~32 one-shot scripts whose answers live in research docs; delete the 15 broken ones.
- Delete `chart_helped_stops.py` regardless of disposition (§1.1).
- Fix `fetch_broker_pnl.py` fee asymmetry.

Docs:
- Fix 49 wrong `PYTHONPATH` occurrences.
- Correct CLAUDE.md: ticker pool, scoring formula, penny-pilot list, parameter table, File
  Map, Test File Map.
- Split bug trackers into open vs. archive; resolve the G36–G38 ID collision.
- Rebuild `FINDINGS.md` as a real index.
- Mark superseded research chains.

Treat CLAUDE.md as the one living reference and let research logs be an append-only
archive — they are valuable precisely because they are historical.

---

## Explicitly Out of Scope

- **Do not rewrite the backtest.** It encodes years of validated research. Phase 2's harness
  plus Phase 3's shared exit module gets the correctness benefit without risking that.
- **Do not reorganize the 5,941-line test files.** Their size is not the problem; fixtures
  encoding impossible states are (§3.2). Fix those as each area is touched.
- **Do not delete the research corpus.** ~78 of 131 docs are research logs. The cost is that
  supersession is unmarked, not that they exist.
- **Do not start with the god classes.** Splitting `OpMomentumTradeEngine` before the parity
  harness exists means refactoring 2,985 lines with no way to prove behavior was preserved.

---

## Verification Status

Verified directly against the code: §1.1, §1.2, §1.3, codebase shape and churn metrics,
§3.1 (test counts), §3.2, §4.1, §4.2 (PYTHONPATH count, penny-pilot), §4.3.

Reported by survey pass, worth confirming before acting: the §2 drift table, §3.3
assertion counts, §3.4, §5 duplication estimates and script dispositions.
