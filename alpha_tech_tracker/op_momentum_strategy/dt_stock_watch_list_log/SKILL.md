---
name: dt-stock-watch-list
description: Generate the daily day-trade stock watch list — opening-range stats, daily trend states, entry gates, option open interest and long/short candidates — into a dated folder under op_momentum_strategy/dt_stock_watch_list_log/. Use when asked for today's or a past session's watch list, ticker stats, or option OI snapshot.
---

# Daily stock watch list

## Run it

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.dt_watch_list_log
```

That writes four files into `dt_stock_watch_list_log/<as_of-date>/` and prints the
mechanical candidate lists. Takes 1-3 minutes; longer on a cold cache.

Useful flags:

| flag | default | when to use |
|---|---|---|
| `--tickers` | 18-name list in the script | different universe |
| `--weeks` | `1 2` | one OR table per window |
| `--rank-weeks` | longest `--weeks` | rank candidates on a different window |
| `--end YYYY-MM-DD` | today | review a past session |
| `--skip-options` | off | **required with a past `--end`** (see Pitfalls) |

## What lands in the folder

| file | |
|---|---|
| `ticker_stats.txt` | the full report, exactly as the CLI prints it |
| `watchlist.md` | gate state, mechanical long/short candidates, review notes |
| `option_open_interest.json` | OI at strike bands 12/16/20 for the main monthly expiry |
| `range_distribution.pdf` | 20-session daily range% histogram per ticker |

## Then review the candidates

The script ranks candidates **only** by average 15:50 return on the biased side.
That ranking has no demonstrated forecasting power, so finish the job by filling in
the `## Review notes` section of `watchlist.md`: keep, drop or replace each
candidate using the other columns, and say why. Check each against:

- **trend** — a `long-bias` name labelled `STRONG_DOWN` or `DOWNTREND` is a conflict.
  `RECOVERY_ATTEMPT` / `BREAKDOWN_CONFIRMED` mean a fresh volume thrust toward the
  MA200, which argues against shorting / buying into it.
- **C/P** — option open interest disagreeing with the side is a conflict. Above ~1.5
  is call-heavy (supports longs), below ~0.7 put-heavy (supports shorts).
- **vol** — opening volume ≥1.5x its own baseline was the strongest quality filter
  found in backtesting; below 1x is a caution.
- **intraday hit vs EOD hit** — high EOD with low intraday means small grinding wins,
  not momentum. Low EOD with high intraday means it travels then gives it back.
- **worst** — the worst session on that side. A positive `worst` means no losing
  session in the window.

`Blocked:` names are right-direction-but-unenterable (too far from the daily MA20, or
longs blocked by the benchmark regime). Report them; do not silently drop them.

## Pitfalls

- **Option OI is live-only.** Alpaca serves no historical open interest, so a past
  `--end` would attach *today's* OI to an old session. Always pass `--skip-options`
  with a past `--end`. This also makes each `option_open_interest.json` the only
  record of that day's figures — do not delete them.
- **SIP data lags.** Today's session is only available after 20:00 ET; before that the
  report clamps to the previous session. The folder is named for the clamped `as_of`
  date, which may be later than the last actual trading session — both are stated in
  the output.
- **Folder date ≠ session date.** Running pre-market on Monday produces an `as_of` of
  Sunday or Monday while the last session is Friday. Say which session the numbers
  describe when reporting.
- **Direction is not decided in advance.** A candidate only trades if its opening
  range closes on the biased side at 09:45. Never present candidates as positions.

## Reliability — state this when reporting

This is a screen of recent behaviour and current structure, not a forecast. A
walk-forward across 2023-2026 (4,293 trades) put ranking-based selection at +3.5bp
per trade against taking every signal — inside noise — and the `no-bias` group beat
the recommended names. The two filters that did survive testing are the MA20
extension gate and the benchmark regime gate on longs, both already applied.

The one relationship that replicated in all four years: average favourable excursion
runs 1.5-2.2% per trade while holding to 15:50 captures near zero. Any edge is in the
exit, not the pick.

Full detail: `../research/experiments/OR_WINRATE_STRATEGY_STUDY.md`.

## Underlying tools

| | |
|---|---|
| `analysis_scripts/dt_watch_list_log.py` | this driver |
| `analysis_scripts/ticker_stats_report.py` | the report; `collect_results()` is the reusable entry point |
| `trade_api/alpaca_client/client.py` | `get_options_open_interest()`, `main_monthly_expiry()` |
