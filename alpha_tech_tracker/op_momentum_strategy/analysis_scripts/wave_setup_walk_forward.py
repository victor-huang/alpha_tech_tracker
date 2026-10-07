"""Walk-forward setup rotation: pick each ticker's top setups on the last N sessions, trade the next M.

Reads a setup report's trades.csv (wave_risk_reward_setup_report; it must start at least
`--lookback-sessions` before `--start`). Only each setup's fixed exit (REPORT_EXITS) counts.

Every `--hold-sessions` sessions from `--start`, each ticker's setups are ranked by their total
over the previous `--lookback-sessions` sessions, and the top `--top` that made money are kept
(one per overlapping family, the monitor's rule: top_setups_by_ticker). Those setups are traded
for the next `--hold-sessions` sessions, then the ranking is redone.

Money: `--capital` per ticker, split equally into `--top` sleeves; every trade of a chosen setup
uses its sleeve (fixed size, not compounded): P&L $ = sleeve x net %. Sleeves without a chosen
setup stay in cash. A trade belongs to the session it was entered (overnight holds included).

Compared with buy & hold (the ticker from the first test session's open to the last close) and
with the hindsight pick (the top setups over the whole test window, traded the whole time).

Writes report.md, trades.csv and selections.csv to `--out-dir`
(default backtest_result/wave_setups/walk_forward_<start>_<end>_<lookback>-<hold>/).

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_walk_forward \\
    --report alpha_tech_tracker/op_momentum_strategy/backtest_result/wave_setups/2026-06-15_2026-10-06 \\
    --start 2026-07-06
"""

import argparse
import csv
from collections import OrderedDict
from datetime import date
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import _load_bars
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    REPORT_EXITS,
    top_setups_by_ticker,
    week_start,
)

DEFAULT_OUT_ROOT = Path(__file__).resolve().parent.parent / "backtest_result" / "wave_setups"


def load_trades(path):
    """Fixed-exit trades from a setup report's trades.csv, with an entry `day` column."""
    trades = pd.read_csv(path)
    trades = trades[[REPORT_EXITS.get(s) == e for s, e in zip(trades["setup"], trades["exit"])]].copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True).dt.tz_convert("America/New_York")
    trades["day"] = trades["entry_time"].dt.date
    return trades


def plan_blocks(sessions, start, lookback, hold):
    """[(lookback sessions, hold sessions), ...] stepping `hold` sessions at a time from `start`."""
    first = next(i for i, s in enumerate(sessions) if s >= start)
    if first < lookback:
        raise ValueError(f"need {lookback} sessions before {start}; the trades start at {sessions[0]}")
    blocks = []
    for i in range(first, len(sessions), hold):
        blocks.append((sessions[i - lookback:i], sessions[i:i + hold]))
    return blocks


def select_setups(trades, ticker, days, top_n):
    """The ticker's top setups by total over `days` (as top_setups_by_ticker ranks them)."""
    window = trades[(trades["ticker"] == ticker) & trades["day"].isin(set(days))]
    ranked = top_setups_by_ticker(window.to_dict("records"), top_n)
    return ranked.get(ticker, [])


def trade_block(trades, ticker, setups, days, sleeve):
    """Trades of the chosen setups entered on `days`, with their dollar P&L for one sleeve each."""
    chosen = trades[(trades["ticker"] == ticker) & trades["day"].isin(set(days)) & trades["setup"].isin(setups)].copy()
    chosen["pnl"] = chosen["net_pct"] / 100 * sleeve
    return chosen


def walk_forward(trades, tickers, sessions, start, lookback, hold, top_n, capital):
    """(traded rows, selection rows) for the rotation."""
    sleeve = capital / top_n
    traded, selections = [], []
    for look_days, hold_days in plan_blocks(sessions, start, lookback, hold):
        for ticker in tickers:
            picked = select_setups(trades, ticker, look_days, top_n)
            selections.append({"ticker": ticker, "from": hold_days[0], "to": hold_days[-1],
                               "lookback_from": look_days[0], "lookback_to": look_days[-1],
                               "setups": ", ".join(f"{s} ({total:+.2f}%)" for s, total in picked) or "cash"})
            traded.append(trade_block(trades, ticker, [s for s, _ in picked], hold_days, sleeve))
    return pd.concat(traded, ignore_index=True) if traded else pd.DataFrame(), selections


def hindsight(trades, tickers, test_days, top_n, capital):
    """Trades of each ticker's top setups over the whole test window (chosen with hindsight)."""
    sleeve = capital / top_n
    picks = {t: [s for s, _ in select_setups(trades, t, test_days, top_n)] for t in tickers}
    traded = pd.concat([trade_block(trades, t, picks[t], test_days, sleeve) for t in tickers], ignore_index=True)
    return traded, picks


def buy_and_hold(ticker, first, last, feed=DataFeed.SIP):
    bars = _load_bars(ticker, first, last, feed)
    window = bars[(bars.index.date >= first) & (bars.index.date <= last)]
    return (window["close"].iloc[-1] / window["open"].iloc[0] - 1) * 100


def period_table(traded, tickers, key, capital):
    """Dollar P&L by ticker x period, plus totals, from traded rows."""
    frame = traded.assign(period=[key(d) for d in traded["day"]])
    grid = frame.pivot_table(index="ticker", columns="period", values="pnl", aggfunc="sum").reindex(tickers).fillna(0.0)
    grid["Total"] = grid.sum(axis=1)
    grid.loc["All"] = grid.sum()
    return grid


def _money(value):
    return f"{'-' if value < 0 else ''}${abs(value):,.0f}"


def _render(grid, capital, label):
    columns = [c for c in grid.columns]
    head = [label(c) if c != "Total" else "Total" for c in columns]
    lines = ["| Ticker | " + " | ".join(head) + " |", "|---|" + "---|" * len(columns)]
    for ticker, row in grid.iterrows():
        base = capital * (len(grid) - 1) if ticker == "All" else capital
        cells = [f"{_money(v)} ({v / base * 100:+.1f}%)" for v in row]
        name = f"**{ticker}**" if ticker == "All" else ticker
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def build_report(traded, selections, hindsight_traded, hindsight_picks, holds, tickers, args, test_days):
    capital = args.capital
    lines = [f"# Walk-forward setup rotation {test_days[0]} .. {test_days[-1]}", "",
             f"Every {args.hold_sessions} sessions, each ticker trades its top {args.top} setups of the previous "
             f"{args.lookback_sessions} sessions (fixed exits, one per family, money-makers only). "
             f"${capital:,.0f} per ticker in {args.top} equal sleeves of ${capital / args.top:,.0f}; "
             f"fixed size per trade (not compounded); costs as in the report ({args.report}).", ""]

    total = traded.groupby("ticker")["pnl"].sum().reindex(tickers).fillna(0.0)
    hind = hindsight_traded.groupby("ticker")["pnl"].sum().reindex(tickers).fillna(0.0)
    lines += ["## Summary", "", "| Ticker | Walk-forward | Trades | Win | Hindsight top 3 | Buy & hold |",
              "|---|---|---|---|---|---|"]
    for t in tickers:
        mine = traded[traded["ticker"] == t]
        win = (mine["pnl"] > 0).mean() if len(mine) else 0.0
        lines.append(f"| {t} | {_money(total[t])} ({total[t] / capital * 100:+.1f}%) | {len(mine)} | {win:.0%} | "
                     f"{_money(hind[t])} ({hind[t] / capital * 100:+.1f}%) | "
                     f"{_money(holds[t] / 100 * capital)} ({holds[t]:+.1f}%) |")
    all_capital = capital * len(tickers)
    hold_total = sum(holds[t] / 100 * capital for t in tickers)
    lines.append(f"| **All (${all_capital:,.0f})** | **{_money(total.sum())} ({total.sum() / all_capital * 100:+.1f}%)** | "
                 f"{len(traded)} | {(traded['pnl'] > 0).mean():.0%} | {_money(hind.sum())} "
                 f"({hind.sum() / all_capital * 100:+.1f}%) | {_money(hold_total)} ({hold_total / all_capital * 100:+.1f}%) |")
    lines += ["", "Hindsight picks: " + "; ".join(f"{t}: {', '.join(p) or 'cash'}" for t, p in hindsight_picks.items()), ""]

    lines += ["## Monthly (walk-forward)", ""]
    lines += _render(period_table(traded, tickers, lambda d: f"{d:%Y-%m}", capital), capital, str)
    lines += ["", "## Weekly (walk-forward, week starting)", ""]
    lines += _render(period_table(traded, tickers, week_start, capital), capital, lambda w: f"{w:%m-%d}")

    by_setup = traded.groupby(["ticker", "setup"])["pnl"].agg(["count", "sum"]).reset_index()
    lines += ["", "## P&L by setup (walk-forward)", "", "| Ticker | Setup | Trades | P&L |", "|---|---|---|---|"]
    for _, row in by_setup.sort_values(["ticker", "sum"], ascending=[True, False]).iterrows():
        lines.append(f"| {row['ticker']} | {row['setup']} | {int(row['count'])} | {_money(row['sum'])} |")

    lines += ["", "## Selections", "", "| Period | Look-back | " + " | ".join(tickers) + " |",
              "|---|---|" + "---|" * len(tickers)]
    by_period = OrderedDict()
    for sel in selections:
        by_period.setdefault((sel["from"], sel["to"], sel["lookback_from"], sel["lookback_to"]), {})[sel["ticker"]] = sel
    for (first, last, look_first, look_last), picks in by_period.items():
        block = traded[(traded["day"] >= first) & (traded["day"] <= last)]
        cells = []
        for t in tickers:
            pnl = block[block["ticker"] == t]["pnl"].sum()
            cells.append(f"{picks[t]['setups']} → **{_money(pnl)}**")
        lines.append(f"| {first:%m-%d}..{last:%m-%d} | {look_first:%m-%d}..{look_last:%m-%d} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, help="Setup report folder (trades.csv) covering the look-back")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="First traded session")
    parser.add_argument("--end", type=date.fromisoformat, help="Last traded session (default: the report's last)")
    parser.add_argument("--tickers", nargs="+", help="Default: every ticker in the report")
    parser.add_argument("--lookback-sessions", type=int, default=10)
    parser.add_argument("--hold-sessions", type=int, default=10)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--capital", type=float, default=10000.0, help="Per ticker (default: 10000)")
    parser.add_argument("--out-dir")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    trades = load_trades(Path(args.report) / "trades.csv")
    tickers = args.tickers or list(OrderedDict.fromkeys(trades["ticker"]))
    trades = trades[trades["ticker"].isin(tickers)]
    end = args.end or max(trades["day"])
    sessions = sorted(d for d in set(trades["day"]) if d <= end)
    traded, selections = walk_forward(trades, tickers, sessions, args.start, args.lookback_sessions,
                                      args.hold_sessions, args.top, args.capital)
    test_days = [s for s in sessions if s >= args.start]
    hindsight_traded, hindsight_picks = hindsight(trades, tickers, test_days, args.top, args.capital)
    holds = {t: buy_and_hold(t, test_days[0], test_days[-1]) for t in tickers}

    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / (
        f"walk_forward_{test_days[0]}_{test_days[-1]}_{args.lookback_sessions}-{args.hold_sessions}")
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = ["ticker", "setup", "exit", "entry_time", "exit_time", "side", "entry", "exit_price", "outcome",
               "net_pct", "pnl"]
    traded.sort_values("entry_time")[columns].to_csv(out_dir / "trades.csv", index=False)
    with (out_dir / "selections.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "from", "to", "lookback_from", "lookback_to", "setups"])
        writer.writeheader()
        writer.writerows(selections)
    report = build_report(traded, selections, hindsight_traded, hindsight_picks, holds, tickers, args, test_days)
    (out_dir / "report.md").write_text(report)
    print(report)
    print(f"report.md, trades.csv and selections.csv written to {out_dir}")


if __name__ == "__main__":
    main()
