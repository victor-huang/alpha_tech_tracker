# Wave Setup Strategy in the Trade Engine — Implementation Plan

**Status:** Approved design; implementation started 2026-11-11 (see Progress). Steps resequenced 2026-11-11 so each commit is deployable.
**Owner decisions:** recorded in "Decisions" below — do not re-open them.
**Scope:** `alpha_tech_tracker/op_momentum_strategy/` — the wave setup monitor (`wave_setup_monitor.py`) and the trade
engine (`op_momentum_trade_engine.py` / `trade_engine.py` / `position_monitor.py`).

## Goal

Pull the trading logic of the wave setup monitor (alerts only today) into a reusable **strategy module**, and run that
same strategy inside the **trade engine**, which places and manages real orders. Share most of the code, keep it in
small modules, and keep the two programs independent:

- **The monitor** keeps sending alerts (Telegram + CSV) exactly as it does today.
- **The trade engine** gains a second strategy path, `--strategy wave-setups`, that trades the same signals with orders.
- **Ticker selection stays outside the engine.** The engine reads a ready-made list of tickers + setups (the monitor
  config JSON written by `analysis_scripts/ticker_screen.py --write-config`). It does execution and position
  management only.

## Decisions (from the user, 2026-11-11)

1. **Intraday setups first.** Overnight holds (overnight long, overnight short) are out of scope for the engine in
   this plan; the engine ignores them and logs that at start-up. The monitor keeps alerting them.
2. **Monitor and engine run independently** (own processes, own state files); they share only library code.
3. **Fixed position size:** a configurable total balance and a configurable number of slots;
   per-trade size = balance ÷ slots (research used $20,000 / 10 = $2,000). Skip an entry when every slot is full or the
   free balance is short.
4. **Alpaca first**, through the existing `ExecutionClient` abstraction, so TradeStation can be added later without
   touching the strategy.
5. **Package name `wave_strategy/`** (not `wave_setups/`, which would clash with the output folder
   `backtest_result/wave_setups/`).

Open question to confirm with the user before step B1 (recommendation in brackets): in mock / replay execution, fill
entries and exits at the strategy's reference price — the signal bar's close, the stop level, the close [recommended:
matches the monitor's alerts and the research backtests one-to-one] — rather than the engine's simulated mid-price.

## Context: why this strategy

Research is in `research/findings/wave_risk_reward_strategy_ticker_params_tunning.md` (Findings 40–45, recommendations
37–40). The plan in production on EC2 (alerts only):

- Tickers: picked monthly (`ticker_screen.py`: top 150 by dollar volume, 4%+ daily range, top 5 by the last 63 sessions
  of drive long + filtered overnight long; `--rank-shorts switched` is the candidate ranking). Prod currently watches 6
  hand-picked tickers from `monitor_configs/2026-11-09_prod.json`: MRNA SNDK APP SNPS SHOP AMD.
- Setups per ticker: `drive long`, `pullback long` (or `pullback long C1`), `overnight always`.
- Monitor flags on EC2 (crontab line 8, `CRON_TZ=America/New_York`, `0 0 * * 1-5 ... wave_setup_monitor restart`):
  `--market-data-source tradestation --workers 0 --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight`.
  The overnight short was dropped on 2026-11-11 (Finding 43). QQQ is no longer traded (commit a370d33): it is the gate
  and trend benchmark only (`--short-tickers` defaults to the config's tickers).
- Backtest sizing: $2,000 a trade, at most 10 open, 5 bps cost. 2026 to Nov 6 (switched ranking): +$7,090, worst
  drawdown −$2,543. Eight years: about +13% a year compounded on $20k.
- Options were studied and rejected for now (Finding 45): stock only.

Intraday setups the engine must trade (all held at most to the close):

| Setup | Entry | Stop / exit (from `LiveTrade.on_bar`, `EXIT_TEXT`) |
|---|---|---|
| `drive long` | green 09:30 bar, entry its close (09:35) | stop the bar's low; hold to the close (`eod`) |
| `drive long re-entry` (`--drive-reentry`, opt-in) | first close back above the stop-out level, before 15:00 | stop the low since the stop-out; `eod` |
| drive trail (`--drive-trail`, opt-in) | — | raises an open drive long's stop to each new confirmed dip low |
| `pullback long` / `pullback long C1` | wave pullback signal, entry the bar's close | stop + target, then trail (`target-trail`, 32% give-back) |
| box / bounce setups (if configured) | signal bar's close | `target` exit |
| `short drive` (`--short-setups drive`, gated) | red 09:30 bar, short its close | stop the bar's high; cover at the close |
| `short drive re-entry` | close back below the stop-out level, before `REENTRY_LATEST` | no stop; cover at the close |
| `short retest` (opt-in, weak) | sell limit at a rally-high retest | trailing stop; cover at the close |

Close decision: at `close_decision_bar` (default 15:45 bar, alert ~15:50) every open intraday trade is closed "at the
close (MOC)". Gates (`short_setups.gate_status`, from QQQ's previous daily closes) and trend filters
(`trend_filters.py`, from daily bars) are decided once at start-up.

## Current architecture (read before coding)

### `wave_setup_monitor.py` (1,719 lines)

Module-level pieces (lines ~219–500): holiday calendar, `is_trading_day`, `previous_trading_day`, `session_close`,
`SetupSpec` / `build_setup_spec` / `generate_config` / `refresh_report` / `load_config`, `period_start`,
`FiveMinAggregator`, `LiveTrade` (exit rules, `to_dict` / `from_dict`), `evaluate_setup` (runs `analyze_bars` in a
worker process), `InlineExecutor`. Then `class WaveSetupMonitor` (lines 501–1456) and CLI helpers
(`_load_daily_*`, `build_market_data_client`, `open_overnight_tickers`, `_run_monitor`, `parse_args`, `main`).

`WaveSetupMonitor` mixes three concerns:

- **I/O shell:** `prepare` (warm-up part), `_warmup`, `_run_backfill`, `start_stream`, `_history`, `send_signal_stats`,
  `_signal_stats_message`, `tick` (scheduling), `run`, `on_minute_bar`, `_on_five_min_bar`, `_refetch_bar`,
  `_watchdog`, `_schedule_backfill`, `_system_alert`, `_alert` (Telegram + CSV), `_load_state` / `_save_state` (file).
- **Information-only alerts:** reversal watch (`_rebuild_reversal_watch`, `_check_reversals`), signal stats.
- **Trading core** (move this): `_drive_tickers`, `_prepare_drive_trail`, `_rebuild_drive_trail`, `_open_drive_longs`,
  `_alert_raised`, `_drive_long_options`, `_trail_drive_long`, `_reenter_drive_long`, `_prepare_shorts`,
  `_prepare_trend_filters`, `_trend_blocked`, `_open_short`, `_check_shorts`, `_drive_short`, `_retest_short`,
  `_overnight_short_entry`, `_submit_evaluations`, `wait_pending`, `_on_evaluated`, `_open_trade`, `_update_trades`,
  `_close_alerts`, `_overnight_short_on`, `_skip_overnight_hold`, `_skip_trend_filtered`, `_overnight_entry`,
  `_pre_open_alerts`, `_catch_up_trades`, `_all_have_bar`, `_last_close`, `_session_summary`, the session-time fields
  (`_set_session_times`), the earnings windows / daily closes set-up inside `prepare`, the trade-closing part of
  `finish`, and the state dict (what `_save_state` writes, what `_load_state` restores).

**The seam:** every trading decision ends in `self._alert(trade, action, price, message, notify=..., ticker=...,
setup=...)` (or `_system_alert(message, level)`). Replace those calls with an **intent sent to a sink**; the monitor's
sink formats the identical alert. Setup evaluation is asynchronous (`executor.submit(evaluate_setup, ...)` with a
done-callback `_on_evaluated` that takes `self.lock`), so the core must **push** intents to a sink callback rather than
return them from `on_bar`.

**Bar-handling order to preserve** (`_handle_five_min_bar`): refetch first period → append bar → `_update_trades` →
`_drive_long_options` → `_check_reversals` → `_check_shorts` → `_submit_evaluations` (only before the decision bar) →
`_save_state`. Reversals sit in the middle; keep the alert order by splitting the core's bar handling into
`on_bar_exits(ticker, bar)` (update trades + drive options) and `on_bar_entries(ticker, bar)` (shorts + evaluations),
with the monitor calling exits → reversals → entries.

**Shared `alerted` set:** reversal alert keys and trading keys share one `alerted` set, saved in the state file. Keep
it owned by the strategy; the monitor's reversal code adds its keys to `strategy.alerted`.

### Trade engine

- `op_momentum_trade_engine.py` (217 lines): CLI entry (`run|start|stop|status|restart`), wires `cli/` (`args.py`,
  `clients.py`, `daemon.py`, `engine_builder.py`, `windows.py`) and `OpMomentumTradeEngine`.
- `trade_engine.py` (3,089 lines): `OpMomentumTradeEngine`, built entirely around the **opening-range momentum**
  strategy — trading windows (M1/A1/…, `WindowConfig`), per-window ticker selectors, `LiveSignalEngine`
  (`signal_engine.py`) emitting `SignalEvent`s with OR high/low, double-down, regime filter, re-entry watchers,
  `close_all("end_of_day")` at `EOD_EXIT_TIME`, session state per day (`session_state.py`). Replay:
  `run_replay(replay_date, tickers_override, bars_source, replay_exit_time)`, `run_replay_range(...)`.
- `position_monitor.py` (2,033 lines): `PositionMonitor(alpaca_client, signal_engine, mock_trade_execution, ...)`.
  `on_bar(ticker)` reads the latest bar from the signal engine and calls `_evaluate_stop(pos, close, high, low,
  bar_open, ma20, ma50, bar_time, volume, ma_fast=)` — **OR-strategy exit rules** (hard stop from OR range, MA20
  trailing, timed exits, double-down co-close). Reusable parts: `_close_position` / `_close_stock_position`,
  `close_all`, reconciliation thread (`_sync_open_position_qtys`, `_reconcile_stuck_positions`), fill-price polling,
  `print_status` / `print_summary`.
- `models.py`: `ActivePosition` (OR-shaped fields: `or_high`, `or_low`, `or_range`, `hard_stop_price`,
  `fallback_price`, `window_label`, `trade_type`, `shares`, …), `SignalEvent`, `WindowConfig`.
- Execution layer (reuse as is): `order_executor.place_stock_order(client, ticker, shares, order_action, mock=,
  signal_price=, feed=)` with 3-step fill escalation; actions `BUY_OPEN`, `SELL_CLOSE`, `SELL_SHORT`, `BUY_COVER`.
  `position_sizer.PositionSizer(client).compute_stock(ticker, stock_price, capital_weight=1, window_budget=, mock=,
  fractional=)` → `(shares, limit_price)`; passing `window_budget=<per-trade size>` sizes from a fixed amount.
  `trade_api/execution_client.ExecutionClient.place_stock_order(symbol, quantity, side, order_type, limit_price,
  time_in_force="DAY")`; Alpaca maps `time_in_force` to `TimeInForce` (CLS/OPG exist for later overnight work).
  `replay.is_replay_mode()`, `set_replay_clock(...)`.

## Target design

### New package `op_momentum_strategy/wave_strategy/`

| Module | Contents (moved from `wave_setup_monitor.py` unless noted) |
|---|---|
| `__init__.py` | re-exports the public names |
| `session.py` | `_MarketHolidayCalendar`, `is_trading_day`, `previous_trading_day`, `session_close`, `period_start`, `SessionTimes` (new small dataclass built from `_set_session_times`: `close_time`, `half_day`, `close_decision_bar`, `last_bar`, `close_alert_at`, `close_alert_latest`, `session_end`), constants `MARKET_OPEN`, `PRE_OPEN_ALERT`, `REGULAR_CLOSE`, `EARLY_CLOSE`, `BAR_MINUTES`, `AFTER_CLOSE_MINUTES` |
| `specs.py` | `SetupSpec`, `build_setup_spec`, `generate_config`, `refresh_report`, `load_config`, `EXIT_TEXT` |
| `bars.py` | `FiveMinAggregator`, `FLUSH_GRACE_SECONDS` |
| `trades.py` | `LiveTrade`, `evaluate_setup` (must stay a picklable top-level function — it runs in a `ProcessPoolExecutor`), `InlineExecutor` |
| `intents.py` (new) | `Intent` dataclass: `kind` ∈ {`enter`, `exit`, `move_stop`, `skip`, `info`, `system`}; `action` (the alert word: BUY, SHORT, SELL, COVER, SOLD, COVERED, RAISE STOP, LOWER STOP, SHORT LIMIT, SHORTED, SKIP); `trade` (LiveTrade or None); `ticker`; `setup`; `price`; `order` ∈ {`bar_close`, `stop`, `target`, `moc`, `moo`, `limit`, None} (how an executor would fill it); `message` (exact alert text); `notify` (bool); `level` (for system intents) |
| `strategy.py` (new class, moved methods) | `WaveSetupStrategy` — the trading core, no network or file I/O |

`WaveSetupStrategy` sketch:

```python
class WaveSetupStrategy:
    def __init__(self, setups_by_ticker, sink, executor=None, lock=None, releases_loader=load_releases,
                 daily_closes_loader=..., trend_daily_loader=..., short_setups=DEFAULT_SHORT_SETUPS,
                 short_gate="qqq-ma50", overnight_short_gate=None, short_tickers=None, extra_tickers=(),
                 drive_trail=False, drive_reentry=False, trend_filters=(), close_decision_bar=time(15, 45),
                 now=_now_et, intraday_only=False)
    # state: setups, tickers, bars, window_start, windows, daily_closes, trades, alerted, session, times,
    #        shorts_on/short_gate_text, overnight_short_on/overnight_short_text, short_watches, short_adr,
    #        drive_trackers, trend_blocked, pending
    def prepare(self, session, bars_by_ticker)        # earnings windows, daily closes, gates, trend filters,
                                                       # drive trail; call restore() before catch_up()
    def catch_up(self)                                 # replay today's warm-up bars through restored trades
    def on_bar_exits(self, ticker, bar)                # bar appended by the caller; stops / targets / trails
    def on_bar_entries(self, ticker, bar)              # shorts + async setup evaluations
    def on_pre_open(self)                              # 09:25 overnight exits (monitor only)
    def on_close_decision(self)                        # close intraday trades; overnight entries unless intraday_only
    def finish(self)                                   # close leftovers at the last close; returns summary text
    def wait_pending(self)
    def state(self) -> dict                            # {"session", "alerted", "done"?, "trades"}
    def restore(self, state: dict)                     # same-session vs next-session rules from _load_state
    def last_close(self, ticker); all_have_bar(self, bar_time)
```

`intraday_only=True` (engine) skips overnight entries in `on_close_decision` and ignores `next open` specs in
evaluations (they are already skipped there: `if spec.overnight ...: continue`).

### `wave_setup_monitor.py` after the move

`WaveSetupMonitor` keeps its constructor signature and builds `self.strategy = WaveSetupStrategy(..., sink=self._on_intent,
executor=self.executor, lock=self.lock, ...)`. It keeps streaming, warm-up, backfill, watchdog, reversal alerts, signal
stats, scheduling in `tick`, the state **file** (`_save_state` writes `strategy.state()` + `done`; `_load_state` calls
`strategy.restore`), the CLI and daemon. `_on_intent(intent)` calls the existing `_alert` / `_system_alert` with the
same arguments, so log lines, Telegram text and CSV rows are unchanged.

**Backward compatibility the tests need** (`tests/op_momentum_trade_engine/test_wave_setup_monitor.py`, ~170 tests,
must pass **unchanged**):

- Names imported from `wave_setup_monitor`: `FiveMinAggregator`, `LiveTrade`, `WaveSetupMonitor`, `build_setup_spec`,
  `evaluate_setup`, `generate_config`, `is_trading_day`, `load_config`, `open_overnight_tickers`, `parse_args`,
  `previous_trading_day`, `session_close` → re-export them. `test_ticker_screen.py` imports `load_config` from it too.
- Attributes the tests read or set on the monitor: `trades`, `bars`, `alerted`, `reversal_watches`, `short_watches`,
  `drive_trackers`, `trend_blocked`, `shorts_on`, `short_gate_text`, `overnight_short_on`, `overnight_short_text`,
  `overnight_short_gate`, `session_end`, `last_bar`, `client`, `client_lock`, `aggregator`, `backfill`,
  `last_minute_at`, `notify`; methods `prepare`, `tick`, `finish`, `run`, `start_stream`, `on_minute_bar`,
  `_on_five_min_bar`, `_submit_evaluations`, `_run_backfill`, `_update_trades`, `send_signal_stats`. Forward the
  strategy-owned ones with properties (with setters where tests assign, e.g. `monitor.trades = [...]`,
  `monitor.shorts_on = True`) and thin method wrappers.
- `mocker.patch.object(monitor_module, X)` targets: `evaluate_setup` (15 tests), `signal_stats` (7), `analyze_bars`,
  `fetch_daily_bars` (2), `build_market_data_client`, `load_config`, `generate_config`, `refresh_report`,
  `open_overnight_tickers`, `WaveSetupMonitor`, `_daemonize`, `_load_config`. A patch on the monitor module only
  affects code that looks the name up **in that module at call time**. For `evaluate_setup`: give the strategy an
  `evaluate_fn` provider (a zero-argument callable) that the monitor sets to its own method returning the module-level
  `evaluate_setup` looked up at call time (`globals()["evaluate_setup"]` inside `wave_setup_monitor`); the strategy
  calls `executor.submit(self.evaluate_fn(), job)`. The submitted function itself stays the top-level
  `evaluate_setup` (a lambda would not pickle for the process pool). Treat `analyze_bars`, `signal_stats` and
  `fetch_daily_bars` the same way wherever moved code uses them. If keeping a test unchanged turns out to be
  impossible, stop and ask the user before editing any test.

### Engine side

- `op_momentum_strategy/strategies/base.py` (new): `Strategy` protocol — `prepare`, `catch_up`, `on_bar_exits`,
  `on_bar_entries`, `on_close_decision`, `finish`, `state`, `restore`, `wait_pending`. Keep it minimal; the OR
  strategy is **not** refactored onto it in this plan.
- `op_momentum_strategy/wave_strategy_runner.py` (new): `WaveStrategyRunner`.
  - Inputs: config JSON path (tickers + setups, via `wave_strategy.specs.load_config`), strategy options (same flags as
    the monitor: `--short-setups`, `--short-gate`, `--short-tickers`, `--drive-trail`, `--drive-reentry`,
    `--trend-filters`, `--close-decision-bar`), `--wave-balance` (default 20000), `--wave-slots` (default 10),
    execution client, market data client, `mock_trade_execution`, state file
    (`logs/wave_strategy_engine_state.json`, separate from the monitor's).
  - Bars: reuse the monitor's warm-up + stream + 5-min aggregation. To share it, extract a `wave_strategy/feed.py`
    `BarFeed` from the monitor (warm-up, `on_minute_bar`, `FiveMinAggregator`, first-period refetch, backfill,
    watchdog) in step A4, keeping monitor attribute forwards for the tests (`client`, `aggregator`, `backfill`,
    `last_minute_at`, `_run_backfill`).
  - Sink `_on_intent(intent)`:
    - `enter`: skip unless a slot is free and `balance − open cost ≥ per-trade size`; size with
      `PositionSizer(client).compute_stock(ticker, price, window_budget=per_trade, mock=..., fractional=is_replay_mode())`;
      place with `order_executor.place_stock_order(client, ticker, shares, "BUY_OPEN" | "SELL_SHORT", mock=...,
      signal_price=intent.price)`; record an `ActivePosition` (stock, `shares`, `entry_stock_price`, `hard_stop_price`
      = the trade's stop, OR fields set to the entry price or 0, `window_label="WAVE"`, `reentry_type=None`); tell the
      strategy the real fill (`trade.entry = fill`), or keep the reference price in mock mode per the open question.
    - `exit`: close the matching position via `PositionMonitor._close_stock_position(pos, reason,
      exit_stock_price_override=intent.price)` (`SELL_CLOSE` / `BUY_COVER`).
    - `move_stop`: update `pos.hard_stop_price` (the strategy already checks stops on closed bars; the engine may also
      place a protective stop order later — out of scope).
    - `skip`, `info`, `system`: log + `_notify`.
  - Mapping between strategy trades and engine positions: key by `(ticker, setup, entry_time.isoformat())` — the same
    key shape the strategy uses in `alerted`.
  - Close: `on_close_decision` at the decision bar emits exits for all open intraday trades; then a final safety
    `close_all("end_of_day")` at `EOD_EXIT_TIME` for anything left.
  - Session start/stop, holidays, daemon handling: reuse `wave_strategy.session` and the engine's `cli/daemon.py`.
- `position_monitor.py` (decided: direct close — the runner calls `_close_stock_position` itself, no
  `position_monitor.py` change; the alternative below is kept for reference): add an injectable **exit policy** so wave positions reuse closing / reconciliation / summary
  code without the OR stop rules. Default policy = today's `_evaluate_stop` (no behaviour change). The wave policy
  returns "no exit" from bar evaluation (the strategy drives exits through intents). Alternatively the runner can call
  `_close_stock_position` directly and use `PositionMonitor` only for reconciliation and summaries — pick whichever
  needs fewer changes to `PositionMonitor`, and keep `test_position_monitor.py` and the trade engine tests unchanged.
- CLI: `op_momentum_trade_engine.py run|start|... --strategy wave-setups --wave-config logs/wave_setup_monitor_config.json
  --wave-balance 20000 --wave-slots 10 --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight
  [--mock-trade-execution] [--replay-date YYYY-MM-DD]`. Default `--strategy` stays the OR strategy. Add the flags in
  `cli/args.py`; branch in `_run_foreground` / `_run_daemon` to build `WaveStrategyRunner` instead of `build_engine`.
  Use a separate PID file (e.g. `logs/wave_strategy_engine.pid`) so it can run next to the OR engine and the monitor.
- Replay: `--replay-date` feeds that session's cached 5-min bars (warm-up from the prior sessions) through the runner
  with mock execution and `set_replay_clock`, so a day can be compared with the monitor's alert CSV.

## Steps (one commit each; tests first; run the full suite each step)

Sequenced so that **every commit leaves both the monitor and the OR trade engine deployable**. Monitor-only changes
(A1–A4) come first, engine-additive changes (B1–B3) after, so a regression points at one program. Commits marked 🚀
change code that a running prod process executes; tag each one (`git tag deploy-A1`, …) as the rollback point.

**Deploy windows.** Monitor: after the 16:00 close and before the 00:00 ET crontab restart (code is only reloaded on
restart; `restore()` picks up open overnight trades). OR engine: before the next `trade_engines.sh start`.

**Two-way state compatibility.** The new code must read a state file written by the old code **and the old code must
read one written by the new code**, so a 🚀 commit can be rolled back while an overnight trade is open.

**Shared modules.** The monitor imports `cli/clients.py`, `cli/daemon.py` and `config.py` from the engine side; any
edit there is a deploy of both programs. `cli/args.py` is engine-only.

| # | Commit | Prod impact | Deploy | Verify |
|---|---|---|---|---|
| A0 | Monitor replay harness + baseline CSVs | none (tooling) | — | — |
| A1 | Move module-level code into `wave_strategy/` | monitor imports | 🚀 low risk | harness CSVs identical; 09:25 / 09:35 alerts normal |
| A2 | Intent seam inside the current class | monitor alert path | 🚀 | harness CSVs identical; Telegram text unchanged |
| A3 | Extract `WaveSetupStrategy` + strategy unit tests | monitor core | 🚀 highest risk | harness identical; 1–2 day shadow run before switching the crontab |
| A4 | Extract `BarFeed` | monitor streaming | 🚀 | watchdog / backfill / refetch logs normal for a session |
| B1 | Strategy protocol + `WaveStrategyRunner` (mock + replay), not wired to the CLI | none reachable | anytime | parity replay vs the A0 baselines |
| B2 | `--strategy wave-setups` CLI branch, separate PID file | OR engine CLI | 🚀 | OR engine without the flag unchanged |
| B3 | Docs | none | anytime | — |

A0. **Monitor replay harness** (`analysis_scripts/wave_monitor_replay.py`): feeds a session's cached 1-minute bars
   through a real `WaveSetupMonitor` (`on_minute_bar` + `tick` on a fake clock, `--no-notify`, inline executor,
   temporary state / CSV files, warm-up from cached bars instead of the network) and writes the alert CSV. Record
   baseline CSVs for 3–5 sessions of 2026 (include a gated short day, e.g. 2026-11-11, and a quiet day) with the prod
   config and flags into `backtest_result/wave_strategy_refactor_baseline/`. Every later monitor step must reproduce
   them byte for byte.
A1. **Module moves only.** Create `wave_strategy/` with `session.py`, `specs.py`, `bars.py`, `trades.py` (incl.
   `evaluate_setup`, `InlineExecutor`); the monitor re-exports every moved name. No class changes.
   *Done when:* every existing test passes unchanged; harness CSVs identical.
A2. **Intent seam in place.** Add `wave_strategy/intents.py`; every trading `_alert` / `_system_alert` call in
   `WaveSetupMonitor` builds an `Intent` and calls `self._on_intent(intent)`, which calls `_alert` / `_system_alert`
   with the same arguments. Nothing moves between classes. *Done when:* tests unchanged; harness CSVs identical.
A3. **Extract `WaveSetupStrategy`** (`wave_strategy/strategy.py`) with `state()` / `restore()`, the monitor's
   forwarding properties and thin wrappers, the `evaluate_fn` provider. Add the strategy unit tests
   (`tests/op_momentum_trade_engine/test_wave_strategy.py`): drive long entry + stop, pullback target-trail, drive short
   + re-entry (gate on/off), drive trail raise, trend-filter skip, close decision, `intraday_only`, `state()` /
   `restore()` round trip, and old-format state files. *Done when:* tests unchanged + new tests pass; harness CSVs
   identical; a 1–2 session shadow run (`--no-notify`, own state / CSV / log / PID files) matches prod's CSV.
A4. **Extract `BarFeed`** (`wave_strategy/feed.py`: warm-up, `on_minute_bar`, aggregation, first-period refetch,
   backfill, watchdog), keeping monitor forwards (`client`, `aggregator`, `backfill`, `last_minute_at`,
   `_run_backfill`). *Done when:* tests unchanged; harness CSVs identical.
B1. **Engine runner** (`strategies/base.py`, `wave_strategy_runner.py`) with mock execution and replay, not reachable
   from the CLI. Close positions with `PositionMonitor._close_stock_position` directly and use `PositionMonitor` only
   for reconciliation / summaries (no change to `position_monitor.py`; the exit-policy hook is dropped unless that turns
   out impossible). Needs the fill-price open question answered first. Tests with a mock `ExecutionClient`: slot cap,
   balance cap, per-trade sizing, order actions, end-of-day close, restart restore. **Parity:** replay the A0 sessions
   through the runner in mock mode and compare entries / exits with the baseline CSVs.
B2. **CLI** — `--strategy wave-setups` and the wave flags in `cli/args.py`, branch in `_run_foreground` / `_run_daemon`,
   `logs/wave_strategy_engine.pid`. *Done when:* trade engine tests unchanged; OR engine replay without the flag
   unchanged.
B3. **Docs:** `guides/WAVE_STRATEGY_ENGINE_GUIDE.md` (or a section in the monitor guide), rows in
   `op_momentum_strategy/CLAUDE.md`, a note in the findings doc's recommendations.

**Prod rollout of the engine** (crontab changes, not commits, each confirmed with the user): mock mode on EC2 beside
the monitor for about a week, comparing trades with the monitor's alert CSV daily → Alpaca paper → live account.

## Progress

| Step | Status | Commit |
|---|---|---|
| A0 | done — baseline 2026-11-02..11 (8 sessions), `prod` 240 alert rows, `all_on` 365; replay deterministic | A0 commit |
| A1 | done — both variants byte-identical to the baseline; full suite green except the 2 known failures | A1 commit |
| A2 | done — every trading alert goes through `WaveSetupMonitor._on_intent(Intent)`; shell alerts (start-up, data outage / restored, reversal LOW? / HIGH?) still call `_alert` / `_system_alert`; byte-identical | A2 commit |
| A3 | next | |

### How to verify a monitor step (A1–A4)

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate; export PYTHONPATH=$PWD
B=alpha_tech_tracker/op_momentum_strategy/backtest_result/wave_strategy_refactor_baseline
M="python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay"
OUT=$(mktemp -d)
# once per machine (13 min on 9 workers); fills market_data/cache/wave_monitor_replay/
$M warm --bundle $B/bundle
$M run --bundle $B/bundle --out $OUT/prod -- --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight
$M run --bundle $B/bundle --out $OUT/all_on --restart-at 2026-11-05T11:02 2026-11-10T13:31 -- \
  --drive-trail --drive-reentry --short-setups drive overnight retest --short-gate always --trend-filters overnight pullback
$M compare $B/prod $OUT/prod && $M compare $B/all_on $OUT/all_on   # both must print "identical"
```

`prod` = the EC2 flags; `all_on` = every option on (drive trail / re-entry, all three shorts, gate `always`, both
trend filters) plus two mid-session restarts (catch-up, first-period refetch, state restore). The bundle and the
expected outputs were recorded with the pre-A1 monitor (commit bb5252b). With a warm cache a run takes ~30 s.

Later (not in this plan): overnight holds in the engine (carry-over state, MOC entries / MOO exits via
`time_in_force` CLS/OPG on Alpaca), TradeStation execution, protective stop orders at the broker.

## Working rules for this repo

- Python 3.8.18, pyenv virtualenv: `source ~/.pyenv/versions/alpha_tech_tracker/bin/activate`. No parenthesized
  multi-context `with` (3.10 syntax).
- Run everything from the repo root with `PYTHONPATH` set to it — `op_momentum_strategy/selectors.py` shadows the
  stdlib module otherwise.
  `PYTHONPATH=$PWD python -m pytest tests/op_momentum_trade_engine -q`
- Known failures before this work: 2 tests in `test_trade_engine_regime.py` (`_HOLD_WINDOW_MINUTES`). Everything else
  passes (about 3,340 tests in the full suite).
- Tests: pytest + `mocker`, one behaviour per test, grouped in test classes, prefer `mocker.patch`; unit tests use no
  network or database.
- Imports at the top of files; comments only where code is not self-explanatory.
- Before committing: `autoflake -i --remove-all-unused-imports <files>`. Commit messages end with the attribution line
  the session requires. The user pushes manually. Never touch the EC2 node (crontab, files, processes) without the
  user's explicit confirmation.
- Scripts that start a `ProcessPoolExecutor` need an `if __name__ == "__main__":` guard on macOS (spawn).
- Keep `evaluate_setup` a top-level function (process-pool pickling).
- Do not change alert wording, the monitor's CLI flags or defaults, or its state file format (EC2 depends on it; a
  restart must read a state file written by the old version, including open overnight trades).

## Risks

- **Silent behaviour change in the monitor** (alert order, a missed `alerted` key, lock scope). Mitigation: tests
  unchanged + byte-identical CSV comparison on replayed days (A0 harness) + a shadow run before deploying A3.
- **Patched names** no longer reaching moved code (see the `evaluate_setup` note).
- **Threading:** `_on_evaluated` runs on executor callback threads; the strategy must take the shared lock exactly where
  the monitor did (`with self.lock:` around `_on_evaluated` body and `_on_five_min_bar`).
- **Engine coupling:** `PositionMonitor` and `ActivePosition` are OR-shaped; prefer adding fields with defaults over
  changing existing ones, and keep OR tests unchanged.
- **Real orders:** default the runner to `--mock-trade-execution` in docs and first runs; live Alpaca paper trading
  before any live account.

## References

- Monitor guide: `guides/WAVE_SETUP_MONITOR_GUIDE.md`
- Research: `research/findings/wave_risk_reward_strategy_ticker_params_tunning.md` (Findings 40–45, recommendations
  37–40)
- Options study (rejected for now): Finding 45; `research/findings/option_strategy_optimization.md`
- Prior refactor plans for style: `dev/active/AUDIT_AND_REFACTOR_PLAN.md`, `dev/active/broker_abstraction_phase1_refactor.md`
