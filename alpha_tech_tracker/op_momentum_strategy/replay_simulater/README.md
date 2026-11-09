# Replay simulater

A single-page game that replays past sessions bar by bar with the wave setup monitor's alerts. You decide whether to
buy, short, close or hold on each 5-min bar; at the close the page compares your P&L with the system's trades.

Published copy (private to its owner): https://claude.ai/code/artifact/387c3ae7-cd8a-408c-ab44-548b915904f5

| File | What it is |
|---|---|
| `build_replay_simulater.py` | Builds the page: runs the setup report, picks the sessions, loads the bars, writes the HTML |
| `replay_simulater_template.html` | The page (layout, chart, controls, game logic) with a `__DATA__` placeholder |

## Rebuild

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# the monitor's config (its tickers and setups), sample of ~24 sessions
python -m alpha_tech_tracker.op_momentum_strategy.replay_simulater.build_replay_simulater \
  --config logs/wave_setup_monitor_config.json --start 2026-09-08 --end 2026-11-06 --out replay_simulater.html

# chosen tickers, the same setups for each, every ticker-day with a trade
python -m alpha_tech_tracker.op_momentum_strategy.replay_simulater.build_replay_simulater \
  --tickers MRNA SNDK SHOP --setups "drive long" "pullback long" --start 2026-10-01 --end 2026-11-06 --sessions all
```

| Option | Default | Meaning |
|---|---|---|
| `--config PATH` | — | Monitor config: tickers and each ticker's setups (overnight setups are skipped, the replay ends at the close) |
| `--tickers ...`, `--setups ...` | `drive long`, `pullback long` | Without a config: these setups for every ticker |
| `--start`, `--end` | required | Sessions to choose from |
| `--short-gate` | `qqq-ma50-down10` | Adds the monitor's drive short on days this gate is on (`qqq-ma50`, `qqq-ma200`, `always`, `off`) |
| `--sessions` | `sample` | `sample`: the 7 best and 5 worst system days, up to 6 from the last week, 6 spread over the rest; `all`: every ticker-day with a trade |
| `--report-dir DIR` | runs one | Reuse an existing setup report folder (`trades.csv`) instead of running a new one |
| `--out PATH` | `replay_simulater.html` | Output page |

The setup report takes a few minutes per ticker for two months; 5-min bars come from the backtest cache (Alpaca SIP).
`--sessions all` over two months is about 160 ticker-days and ~2 MB of HTML.

To republish to the same link, publish the built HTML with Claude Code's Artifact tool and pass the URL above as `url`
(from a new conversation it first reads the artifact). A publish without the URL creates a new page.

## How the page works

- **Data** sits in `<script type="application/json" id="data">` as a list of sessions:
  - `ticker`, `date`, `prevDate`, `gate` (short gate on that day)
  - `prev`: the previous session's bars, `[open, high, low, close, ma20, ma50, ma200, ma9]`
  - `bars`: today's bars, `["HH:MM", open, high, low, close, vwap, ma20, ma50, ma200, ma9]` (bar start time)
  - `signals`: the system's trades, `{setup, side, entryBar, entry, stop, exitText, exitBar, exitPrice, outcome, pct}`;
    bar indexes are into `bars`, `pct` is net of 5 bps
  - The moving averages are computed in the builder from a week of 5-min bars, so the 200-bar line is valid from the
    previous session's first bar. The page reads the bar arrays by position: keep `MA_LENGTHS` and the `MAS` table in
    the template in step.
- **Game rules** (template script): fills at the shown bar's close, $10,000 a trade (`NOTIONAL`), 5 bps round trip
  (`COST`), one position at a time, an open position is closed at the last bar. System alerts are emitted when their
  bar closes (`emit`); the exit alerts can be hidden with the checkbox.
- **Chart** (`drawChart`): canvas candles, MA / VWAP lines, system markers (▲ in, ■ out) and yours (● in, ◆ out). The
  view (`V`: bars shown, price fit, price zoom, line toggles) is kept in the browser's localStorage, as are the last
  12 results (`replay.history`).
- **Theme**: colour tokens at the top of the template's `<style>` for light and dark.
- **Shortcuts**: B buy, S short, C close, Space / → next bar, A next alert, E to the close; wheel = bars shown,
  Shift + wheel = price zoom.

Not modelled: the drive short's re-entry after a stop-out (no time in the setup report), overnight setups, and the
stop / target prices of pullback entries (the trades file does not keep them).
