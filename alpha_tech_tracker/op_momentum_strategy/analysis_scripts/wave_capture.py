"""Wave capture: how much of a ticker's daily range each setup catches, and a walk-forward setup picker.

Score. A ticker moves its average daily range (ADR: the mean regular-hours high - low of the previous
`--adr-sessions` sessions, known before the open) through one or a few strong waves. A setup's capture on a
session is its net result in dollars per share (every trade of that setup and exit entered that session, after
costs) divided by that session's ADR; sessions without a trade count as 0, so the score rewards catching often and
catching much. As a diagnostic, the wave capture is the dollars caught divided by the session's waves in the
setup's direction (the sum of finished up waves for long setups, down waves for short setups, both for setups that
trade both sides), from the wave model run after the close; it is never used to pick.

Picker. Every `--hold-sessions` sessions it ranks every intraday setup x exit by its mean ADR capture over the
previous `--lookback-sessions` sessions and trades the top `--top` that are positive with at least `--min-trades`
trades; picks use only sessions before the pick. Events known at the previous close can end a block early:

  ticker MA     the ticker's daily close crossed its MA20 / MA50 / MA200 (up or down)
  QQQ MA        QQQ's daily close crossed its MA20 / MA50 / MA200
  QQQ trend     QQQ's trend state changed: up = close > MA20 and MA20 above its level 5 sessions earlier,
                down = close < MA20 and MA20 below it, else flat

Variants: `fixed` (schedule only), `repick` (any event re-picks and restarts the 2-week clock), `repick-ticker`,
`repick-qqq-ma`, `repick-qqq-trend` (one event family each), `aside-breakdown` (a downward event steps aside until
an upward event or the next scheduled pick, which re-picks), `aside-qqq-down` (re-pick on events, and no trades
while QQQ's trend is down).

Input: a setup report's trades.csv for the ticker (`wave_risk_reward_setup_report.py --tickers T --start <start
minus the look-back> --end ...`), which holds every setup with every exit.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_capture --ticker SNDK \\
    --trades backtest_result/wave_setups/2025-11-03_2026-10-23/trades.csv --start 2026-01-02 --end 2026-10-23
"""

import argparse
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import analyze_bars
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import _load_bars
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars

DEFAULT_OUT_ROOT = Path(__file__).resolve().parents[1] / "backtest_result" / "wave_capture"
MA_PERIODS = (20, 50, 200)
TREND_SLOPE_SESSIONS = 5
DAILY_HISTORY_DAYS = 420
POSITION_DOLLARS = 10000
VARIANTS = ("fixed", "repick", "repick-ticker", "repick-qqq-ma", "repick-qqq-trend", "aside-breakdown",
            "aside-qqq-down")


# ---------------------------------------------------------------------------
# Sessions: range, waves, ADR
# ---------------------------------------------------------------------------

def session_frame(bars, adr_sessions):
    """Per session: regular-hours range, ADR known before the open, and the finished waves' up / down sums."""
    days = pd.Series(bars.index.date, index=bars.index)
    ranges = bars.groupby(days.values).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    frame = pd.DataFrame({"range": ranges["high"] - ranges["low"], "close": ranges["close"]})
    frame["adr"] = frame["range"].rolling(adr_sessions, min_periods=adr_sessions).mean().shift(1)
    up, down, largest_up = {}, {}, {}
    for wave in analyze_bars(bars)["waves"]:
        direction = wave.direction()
        if direction not in ("up", "down"):
            continue
        day, size = wave.start.date(), float(wave.high - wave.low)
        bucket = up if direction == "up" else down
        bucket[day] = bucket.get(day, 0.0) + size
        if direction == "up":
            largest_up[day] = max(largest_up.get(day, 0.0), size)
    frame["up_waves"] = pd.Series(up)
    frame["down_waves"] = pd.Series(down)
    frame["largest_up"] = pd.Series(largest_up)
    return frame.fillna({"up_waves": 0.0, "down_waves": 0.0, "largest_up": 0.0})


# ---------------------------------------------------------------------------
# Daily context and events
# ---------------------------------------------------------------------------

def daily_context(closes):
    """Daily closes with MAs and QQQ-style trend state, indexed by date."""
    frame = pd.DataFrame({"close": closes})
    for period in MA_PERIODS:
        frame[f"ma{period}"] = frame["close"].rolling(period, min_periods=period).mean()
    rising = frame["ma20"] > frame["ma20"].shift(TREND_SLOPE_SESSIONS)
    falling = frame["ma20"] < frame["ma20"].shift(TREND_SLOPE_SESSIONS)
    frame["trend"] = "flat"
    frame.loc[(frame["close"] > frame["ma20"]) & rising, "trend"] = "up"
    frame.loc[(frame["close"] < frame["ma20"]) & falling, "trend"] = "down"
    return frame


def daily_events(context, label, include_trend):
    """{date: [(family, direction, text)]} for MA crosses (and trend changes) on each daily close."""
    events = {}
    previous = None
    for day, row in context.iterrows():
        if previous is not None:
            found = []
            for period in MA_PERIODS:
                ma, ma_before = row[f"ma{period}"], previous[f"ma{period}"]
                if pd.isna(ma) or pd.isna(ma_before):
                    continue
                if previous["close"] <= ma_before and row["close"] > ma:
                    found.append(("ma", "up", f"{label} crossed above MA{period}"))
                elif previous["close"] >= ma_before and row["close"] < ma:
                    found.append(("ma", "down", f"{label} crossed below MA{period}"))
            if include_trend and row["trend"] != previous["trend"]:
                direction = {"up": "up", "down": "down"}.get(row["trend"], "up" if previous["trend"] == "down" else "down")
                found.append(("trend", direction, f"{label} trend {previous['trend']} -> {row['trend']}"))
            if found:
                events[day] = found
        previous = row
    return events


def events_before_sessions(sessions, ticker_events, qqq_events):
    """{session: [(source, family, direction, text)]}: events on the last daily close before each session."""
    out = {}
    all_days = sorted(set(ticker_events) | set(qqq_events))
    for session in sessions:
        prior = [d for d in all_days if d < session]
        if not prior:
            continue
        last = prior[-1]
        previous_sessions = [s for s in sessions if s < session]
        if previous_sessions and last < previous_sessions[-1]:
            continue
        found = [("ticker",) + e for e in ticker_events.get(last, [])] + [("qqq",) + e for e in qqq_events.get(last, [])]
        if found:
            out[session] = found
    return out


# ---------------------------------------------------------------------------
# Setup captures
# ---------------------------------------------------------------------------

def load_trades(path, ticker):
    trades = pd.read_csv(path)
    trades = trades[(trades["ticker"] == ticker) & (trades["exit"] != "next open")].copy()
    trades["session"] = pd.to_datetime(trades["entry_time"].str[:10]).dt.date
    trades["dollars"] = trades["net_pct"] / 100 * trades["entry"]
    trades["candidate"] = trades["setup"] + " / " + trades["exit"]
    return trades


def capture_table(trades, sessions):
    """(capture in ADR, dollars per share, trade counts) as session x candidate frames, 0 where nothing traded."""
    dollars = trades.pivot_table(index="session", columns="candidate", values="dollars", aggfunc="sum")
    counts = trades.pivot_table(index="session", columns="candidate", values="dollars", aggfunc="count")
    pct = trades.pivot_table(index="session", columns="candidate", values="net_pct", aggfunc="sum")
    index = sessions.index
    dollars, counts, pct = (frame.reindex(index).fillna(0.0) for frame in (dollars, counts, pct))
    capture = dollars.div(sessions["adr"], axis=0)
    return capture, dollars, counts, pct


def candidate_sides(trades):
    sides = trades.groupby("candidate")["side"].agg(lambda s: set(s))
    return {c: ("long" if s == {1} else "short" if s == {-1} else "both") for c, s in sides.items()}


def wave_capture(dollars, sessions, sides):
    """Dollars caught / the waves in the setup's direction, per candidate (the after-the-fact diagnostic)."""
    out = {}
    for candidate in dollars.columns:
        side = sides.get(candidate, "both")
        waves = (sessions["up_waves"] if side == "long" else sessions["down_waves"] if side == "short"
                 else sessions["up_waves"] + sessions["down_waves"])
        total = waves.sum()
        out[candidate] = dollars[candidate].sum() / total if total else float("nan")
    return out


# ---------------------------------------------------------------------------
# Walk-forward picker
# ---------------------------------------------------------------------------

def pick(capture, counts, before, lookback, top, min_trades):
    """Top candidates by mean ADR capture over the `lookback` sessions before `before`; positive, >= min_trades."""
    window = capture.index[capture.index < before][-lookback:]
    if len(window) < lookback:
        return []
    score = capture.loc[window].mean()
    trades = counts.loc[window].sum()
    ranked = score[(score > 0) & (trades >= min_trades)].sort_values(ascending=False)
    picked = []
    for candidate in ranked.index:
        setup = candidate.split(" / ")[0]
        if any(p.split(" / ")[0] == setup for p in picked):
            continue
        picked.append(candidate)
        if len(picked) == top:
            break
    return picked


def _variant_trigger(variant, events):
    """(re-pick now, step aside now) for a session's events under a variant."""
    if not events:
        return False, False
    families = {"repick-ticker": lambda e: e[0] == "ticker",
                "repick-qqq-ma": lambda e: e[0] == "qqq" and e[1] == "ma",
                "repick-qqq-trend": lambda e: e[0] == "qqq" and e[1] == "trend"}
    if variant in ("repick", "aside-qqq-down"):
        return True, False
    if variant in families:
        return any(families[variant](e) for e in events), False
    if variant == "aside-breakdown":
        down = any(e[2] == "down" for e in events)
        up = any(e[2] == "up" for e in events)
        return up and not down, down
    return False, False


def walk_forward(capture, counts, pct, test_sessions, events, qqq_trend, variant, lookback, hold, top, min_trades):
    """Session rows: picks, ADR capture, % and $ at POSITION_DOLLARS per picked setup, and why it re-picked."""
    rows = []
    picks, since_pick, aside = [], None, False
    for session in test_sessions:
        repick_event, aside_event = _variant_trigger(variant, events.get(session))
        reason = ""
        if aside_event:
            aside, reason = True, "step aside"
        elif repick_event or since_pick is None or since_pick >= hold:
            reason = "event" if repick_event else "schedule"
            picks, since_pick, aside = pick(capture, counts, session, lookback, top, min_trades), 0, False
        qqq_down = variant == "aside-qqq-down" and qqq_trend.get(session) == "down"
        active = [] if aside or qqq_down else picks
        rows.append({"session": session, "picks": " + ".join(active) if active else "(aside)" if picks else "(none)",
                     "reason": reason, "events": "; ".join(e[3] for e in events.get(session, [])),
                     "capture": float(sum(capture.at[session, c] for c in active)),
                     "pct": float(sum(pct.at[session, c] for c in active)),
                     "dollars": float(sum(pct.at[session, c] for c in active) / 100 * POSITION_DOLLARS)})
        since_pick = (since_pick or 0) + 1
    return pd.DataFrame(rows)


def qqq_trend_before(sessions, qqq_context):
    out = {}
    days = list(qqq_context.index)
    for session in sessions:
        prior = [d for d in days if d < session]
        if prior:
            out[session] = qqq_context.at[prior[-1], "trend"]
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def candidate_report(capture, dollars, counts, pct, sessions, sides, test_sessions):
    rows = []
    wave = wave_capture(dollars.loc[test_sessions], sessions.loc[test_sessions], sides)
    for candidate in capture.columns:
        trades = counts.loc[test_sessions, candidate].sum()
        if not trades:
            continue
        rows.append({"candidate": candidate, "side": sides.get(candidate, ""), "trades": int(trades),
                     "adr_capture_per_session": capture.loc[test_sessions, candidate].mean(),
                     "wave_capture": wave[candidate], "total_pct": pct.loc[test_sessions, candidate].sum()})
    return pd.DataFrame(rows).sort_values("adr_capture_per_session", ascending=False)


def summarize_run(frame):
    traded = frame[~frame["picks"].str.startswith("(")]
    return {"sessions": len(frame), "traded": len(traded), "adr_capture_per_session": frame["capture"].mean(),
            "total_pct": frame["pct"].sum(), "dollars": frame["dollars"].sum(),
            "repicks": int((frame["reason"] != "").sum()), "max_drawdown": _drawdown(frame["dollars"].cumsum())}


def _drawdown(curve):
    if curve.empty:
        return 0.0
    return float((curve - curve.cummax().clip(lower=0)).min())


def by_month(frame):
    months = pd.to_datetime(frame["session"]).dt.strftime("%Y-%m")
    return frame.groupby(months).agg(capture=("capture", "mean"), pct=("pct", "sum"), dollars=("dollars", "sum"))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--trades", required=True, help="Setup report trades.csv covering the look-back too")
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="First test session")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="Last test session")
    parser.add_argument("--lookback-sessions", type=int, default=20)
    parser.add_argument("--hold-sessions", type=int, default=10, help="Re-pick on schedule every N sessions")
    parser.add_argument("--top", type=int, default=1, help="Setups traded at once (one exit per setup)")
    parser.add_argument("--min-trades", type=int, default=3, help="Trades a setup needs in the look-back")
    parser.add_argument("--adr-sessions", type=int, default=20)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--out-dir", help=f"Default: {DEFAULT_OUT_ROOT}/<ticker>_<start>_<end>")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    trades = load_trades(args.trades, args.ticker)
    first = trades["session"].min()
    bars = _load_bars(args.ticker, first, args.end, feed)
    bars = bars[(bars.index.date >= first - timedelta(days=45)) & (bars.index.date <= args.end)]
    sessions = session_frame(bars, args.adr_sessions)
    sessions = sessions[sessions.index >= first]
    capture, dollars, counts, pct = capture_table(trades, sessions)
    sides = candidate_sides(trades)
    test_sessions = [d for d in sessions.index if args.start <= d <= args.end]

    daily = fetch_daily_bars([args.ticker, "QQQ"], first - timedelta(days=DAILY_HISTORY_DAYS), args.end)
    contexts = {}
    for symbol in (args.ticker, "QQQ"):
        frame = daily[symbol]
        column = "Close" if "Close" in frame.columns else "close"
        closes = pd.Series([float(c) for c in frame[column]], index=[pd.Timestamp(d).date() for d in frame.index])
        contexts[symbol] = daily_context(closes[closes.index <= args.end])
    events = events_before_sessions(list(sessions.index), daily_events(contexts[args.ticker], args.ticker, False),
                                    daily_events(contexts["QQQ"], "QQQ", True))
    qqq_trend = qqq_trend_before(test_sessions, contexts["QQQ"])

    out_dir = Path(args.out_dir or DEFAULT_OUT_ROOT / f"{args.ticker}_{args.start}_{args.end}")
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    test = sessions.loc[test_sessions]
    lines = [f"# Wave capture: {args.ticker} {args.start} to {args.end}", "",
             f"{len(test_sessions)} sessions; median ADR {test['adr'].median():.2f} "
             f"({(test['adr'] / test['close']).median():.1%} of price); finished up waves per session median "
             f"{(test['up_waves'] / test['adr']).median():.2f} ADR, largest up wave median "
             f"{(test['largest_up'] / test['adr']).median():.2f} ADR.", ""]

    report = candidate_report(capture, dollars, counts, pct, sessions, sides, test_sessions)
    report.to_csv(out_dir / "candidates.csv", index=False)
    lines += ["## Every setup x exit over the whole test (hindsight: the best is an upper bound)", "",
              report.head(25).to_string(index=False, float_format=lambda x: f"{x:.3f}"), ""]

    results = OrderedDict()
    for variant in args.variants:
        run = walk_forward(capture, counts, pct, test_sessions, events, qqq_trend, variant, args.lookback_sessions,
                           args.hold_sessions, args.top, args.min_trades)
        run.to_csv(out_dir / f"walk_forward_{variant}.csv", index=False)
        results[variant] = run
    summary = pd.DataFrame({v: summarize_run(r) for v, r in results.items()}).T
    best = report.iloc[0]
    lines += [f"## Walk-forward picker (look-back {args.lookback_sessions}, re-pick every {args.hold_sessions} "
              f"sessions, top {args.top}, ${POSITION_DOLLARS:,} per setup)", "",
              summary.to_string(float_format=lambda x: f"{x:.3f}"), "",
              f"Hindsight best single setup: {best['candidate']} ({best['adr_capture_per_session']:.3f} ADR/session, "
              f"{best['total_pct']:+.2f}%).", ""]
    lines += ["## By month", ""]
    months = pd.concat({v: by_month(r)["pct"] for v, r in results.items()}, axis=1)
    lines += [months.to_string(float_format=lambda x: f"{x:+.2f}"), ""]
    picks = results["fixed"] if "fixed" in results else next(iter(results.values()))
    lines += ["## Picks (fixed schedule)", "",
              picks[picks["reason"] != ""][["session", "picks", "reason"]].to_string(index=False), ""]
    text = "\n".join(lines)
    (out_dir / "report.md").write_text(text)
    print(text)
    print(f"written to {out_dir}")


if __name__ == "__main__":
    main()
