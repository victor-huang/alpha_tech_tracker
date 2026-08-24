"""Backtest OR-direction entries on tickers ranked by trailing win rate."""

import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    MARKET_OPEN,
    build_extension_caps,
    build_ma20_distance,
    build_regime_state,
    clamp_end_for_sip,
    classify_daily_trend,
    extension_blocks_entry,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    fetch_bars,
    fetch_daily_bars,
)
from alpha_tech_tracker.trade_api.alpaca_client.client import (
    AlpacaAPIClient,
    main_monthly_expiry,
)

DEFAULT_TICKERS = ["SNDK", "APP", "NVDA", "LLY", "MRNA", "COIN", "HOOD"]
SELECTION_SESSIONS = 10
WARMUP_CALENDAR_DAYS = 45
BENCHMARK_WARMUP_DAYS = 500  # MA200 on daily bars needs ~200 sessions of history
DEFAULT_EXIT_TIME = "14:15"
TRAILING_MA_PERIOD = 8
DAILY_MA_PERIOD = 20
TRAILING_DISABLED = 10 ** 6
OR_VOLUME_BASELINE = 20
EARLY_EXIT_MINUTES = 15  # the "+15m" hold used by the lifecycle dashboard
THRUST_STATES = {
    "bull": {"RECOVERY_ATTEMPT", "RECOVERY_CONFIRMED"},
    "bear": {"BREAKDOWN_ATTEMPT", "BREAKDOWN_CONFIRMED"},
}


def simulate_session(regular, or_bars, exit_time, trailing_ma, trailing_start_bars,
                     use_hard_stop, ma_period, stop_pct=None, confirm_ma=None):
    """Walk the session bar by bar: hard stop first, then the MA trailing exit.

    The stop sits `stop_pct` away from entry when given, otherwise at the opening
    range extreme. Within one bar the stop is assumed to trigger before the trail.
    """
    opening = regular.iloc[:or_bars]
    held = regular.iloc[or_bars:]
    held = held[held.index.time < exit_time]
    if held.empty:
        return None

    or_high = float(opening["High"].max())
    or_low = float(opening["Low"].min())
    or_mid = (or_high + or_low) / 2
    or_close = float(opening["Close"].iloc[-1])
    if or_close == or_mid:
        return None

    direction = "bull" if or_close > or_mid else "bear"
    if stop_pct is not None:
        stop_price = (
            or_close * (1 - stop_pct / 100)
            if direction == "bull"
            else or_close * (1 + stop_pct / 100)
        )
    else:
        stop_price = or_low if direction == "bull" else or_high
    best = or_close
    exit_price = None
    exit_reason = None
    exit_bar = None

    for position, (stamp, bar) in enumerate(held.iterrows()):
        if direction == "bull":
            best = max(best, float(bar["High"]))
            hit_stop = float(bar["Low"]) <= stop_price
        else:
            best = min(best, float(bar["Low"]))
            hit_stop = float(bar["High"]) >= stop_price

        if use_hard_stop and hit_stop:
            exit_price, exit_reason, exit_bar = stop_price, "hard_stop", stamp
            break

        ma_value = trailing_ma.get(stamp)
        if position >= trailing_start_bars and ma_value is not None and not pd.isna(ma_value):
            close = float(bar["Close"])
            crossed = close < ma_value if direction == "bull" else close > ma_value
            if crossed:
                exit_price = close
                exit_reason = f"trailing_ma{ma_period}"
                exit_bar = stamp
                break

    if exit_price is None:
        exit_price = float(held["Close"].iloc[-1])
        exit_reason = "time_exit"
        exit_bar = held.index[-1]

    move = (exit_price - or_close) if direction == "bull" else (or_close - exit_price)
    excursion = (best - or_close) if direction == "bull" else (or_close - best)
    or_volume = float(opening["Volume"].sum())
    confirm_value = confirm_ma.get(opening.index[-1]) if confirm_ma else None
    confirms = None
    if confirm_value is not None and not pd.isna(confirm_value):
        confirms = (
            or_close > confirm_value if direction == "bull" else or_close < confirm_value
        )
    return {
        "ma_confirms": confirms,
        "or_volume": or_volume,
        "or_range_pct": (or_high - or_low) / or_close * 100,
        "session": regular.index[0].date(),
        "direction": direction,
        "or_high": or_high,
        "or_low": or_low,
        "or_close": or_close,
        "stop_price": stop_price,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_bar": exit_bar.strftime("%H:%M"),
        "max_gain_pct": excursion / or_close * 100,
        "return_pct": move / or_close * 100,
    }


def build_session_outcomes(bars, or_bars, exit_time, trailing_start_bars, use_hard_stop,
                           ma_period, stop_pct=None, confirm_ma_period=None):
    """Simulate every session for one ticker, keyed by date."""
    period = ma_period if ma_period else 1
    trailing_ma = bars["Close"].rolling(period).mean().to_dict()
    confirm_ma = (
        bars["Close"].rolling(confirm_ma_period).mean().to_dict()
        if confirm_ma_period else None
    )
    outcomes = {}
    volume_history = []
    for _, frame in bars.groupby(bars.index.date):
        regular = frame[frame.index.time >= MARKET_OPEN]
        if len(regular) <= or_bars:
            continue
        outcome = simulate_session(
            regular, or_bars, exit_time, trailing_ma, trailing_start_bars, use_hard_stop,
            ma_period, stop_pct, confirm_ma
        )
        if outcome:
            prior = volume_history[-OR_VOLUME_BASELINE:]
            baseline = sum(prior) / len(prior) if prior else None
            outcome["or_vol_ratio"] = (
                outcome["or_volume"] / baseline if baseline else None
            )
            outcomes[outcome["session"]] = outcome
            volume_history.append(outcome["or_volume"])
    return outcomes


def build_regime_classes(daily: pd.DataFrame, slope_lookback: int = 5):
    """Label each session strong / consolidation / weak from PRIOR-session daily MAs.

    Strong needs price above a rising MA20 > MA50 > MA200 stack. Weak means price
    below the MA50. Everything else is consolidation.
    """
    if daily.empty:
        return {}
    close = daily["Close"]
    prior_close = close.shift(1)
    ma20 = close.rolling(20).mean().shift(1)
    ma50 = close.rolling(50).mean().shift(1)
    ma200 = close.rolling(200).mean().shift(1)
    ma50_rising = ma50 > ma50.shift(slope_lookback)

    classes = {}
    for stamp in daily.index:
        session = stamp.date() if hasattr(stamp, "date") else stamp
        if pd.isna(prior_close.get(stamp)) or pd.isna(ma50.get(stamp)):
            continue
        stacked = (
            not pd.isna(ma200[stamp])
            and prior_close[stamp] > ma20[stamp] > ma50[stamp] > ma200[stamp]
            and bool(ma50_rising[stamp])
        )
        if stacked:
            classes[session] = "strong"
        elif prior_close[stamp] < ma50[stamp]:
            classes[session] = "weak"
        else:
            classes[session] = "consolidation"
    return classes


def regime_blocks_entry(direction, benchmark_above_ma, mode):
    """Block signals that fight the benchmark's own daily trend."""
    if mode == "off" or benchmark_above_ma is None:
        return False
    if direction == "bull":
        return not benchmark_above_ma
    return benchmark_above_ma if mode == "both" else False


def thrust_waives_extension(direction, trend_label):
    """A fresh trend-change thrust is far from the MA20 by construction.

    Distance from the mean is the signal there, not a warning, so the extension
    gate should not veto the direction the thrust just established.
    """
    return bool(trend_label) and trend_label in THRUST_STATES[direction]


def trailing_median(outcome_for, ticker, sessions_before):
    """Median return over prior sessions only, mirroring the lifecycle Med% column."""
    prior = [outcome_for(ticker, day) for day in sessions_before]
    values = sorted(row["return_pct"] for row in prior if row)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def prefers_early_exit(early_for, main_for, ticker, sessions_before, edge_pp):
    """True when the +15m hold beat the full hold by `edge_pp` over prior sessions.

    Mirrors the lifecycle 15mWR-vs-EOD_WR spread: names that earn their edge in the
    first minutes and give it back later score higher on the early exit.
    """
    early = [early_for(ticker, day) for day in sessions_before]
    main = [main_for(ticker, day) for day in sessions_before]
    pairs = [(e, m) for e, m in zip(early, main) if e and m]
    if not pairs:
        return False
    early_wr = sum(1 for e, _ in pairs if e["return_pct"] > 0) / len(pairs) * 100
    main_wr = sum(1 for _, m in pairs if m["return_pct"] > 0) / len(pairs) * 100
    return (early_wr - main_wr) > edge_pp


def trailing_win_rate(outcome_for, ticker, sessions_before):
    prior = [outcome_for(ticker, day) for day in sessions_before]
    prior = [row for row in prior if row]
    if not prior:
        return None, 0
    wins = sum(1 for row in prior if row["return_pct"] > 0)
    return wins / len(prior) * 100, len(prior)


def load_put_call_ratios(pc_file, snapshot_ratios, mode):
    """Resolve the put/call source. `snapshot` reuses one reading for every session,
    which is a lookahead because Alpaca exposes only the latest open interest.
    """
    if mode == "off":
        return None, "disabled"
    if mode == "file":
        dated = {}
        with open(pc_file) as handle:
            for row in csv.DictReader(handle):
                dated[(date.fromisoformat(row["date"]), row["ticker"])] = float(
                    row["call_put_ratio"]
                )
        return dated, f"dated file ({len(dated)} rows)"
    return snapshot_ratios, "TODAY's snapshot applied to all sessions (LOOKAHEAD)"


def snapshot_call_put_ratios(client, tickers, expiry, band, spots):
    ratios = {}
    for ticker in tickers:
        spot = spots.get(ticker)
        if not spot:
            continue
        try:
            chain = client.get_options_open_interest(
                ticker, expiration_date=expiry, strikes_around_atm=band, reference_price=spot
            )
            ratios[ticker] = chain["call_put_ratio"]
        except Exception:
            continue
    return ratios


def pc_agrees(direction, ratio, call_bias, put_bias):
    if ratio is None:
        return False
    if direction == "bull":
        return ratio >= call_bias
    return ratio <= (1.0 / put_bias if put_bias else 0)


def run_backtest(config):
    trades = []
    blocked = defaultdict(int)
    timeline = config["timeline"]
    position_of = {day: i for i, day in enumerate(timeline)}
    for session in config["sessions"]:
        index = position_of[session]
        history = timeline[max(0, index - SELECTION_SESSIONS) : index]
        if len(history) < SELECTION_SESSIONS:
            blocked["insufficient_history"] += 1
            continue

        outcome_for = config["outcome_for"]
        ranked = []
        for ticker in config["tickers"]:
            if outcome_for(ticker, session) is None:
                continue
            win_rate, samples = trailing_win_rate(outcome_for, ticker, history)
            if win_rate is None or samples < SELECTION_SESSIONS // 2:
                continue
            if win_rate < config["min_win_rate"]:
                continue
            if config["min_median_pct"] is not None:
                median = trailing_median(outcome_for, ticker, history)
                if median is None or median < config["min_median_pct"]:
                    blocked["median_too_low"] += 1
                    continue
            tiebreak = outcome_for(ticker, session).get("or_vol_ratio") or 0.0
            ranked.append((win_rate, samples, tiebreak, ticker))

        ranked.sort(reverse=True)
        picks = [(w, s_, t) for w, s_, _, t in ranked[: config["top_n"]]]
        if not picks:
            continue

        eligible = []
        for win_rate, _, ticker in picks:
            outcome = outcome_for(ticker, session)
            exit_label = "main"
            if config["exit_by_spread"] and prefers_early_exit(
                config["early_for"], outcome_for, ticker, history, config["spread_edge_pp"]
            ):
                early = config["early_for"](ticker, session)
                if early:
                    outcome, exit_label = early, "early15m"
            direction = outcome["direction"]

            if regime_blocks_entry(
                direction, config["regime"].get(session), config["regime_mode"]
            ):
                blocked["regime_" + direction] += 1
                continue

            distance = config["ma20_distance"].get(ticker, {}).get(session)
            cap = config["max_distance"].get(ticker, {}).get(session)
            if extension_blocks_entry(direction, distance, cap):
                trend_label = (
                    config["trend_states"].get(ticker, {}).get(session, {}).get("label")
                )
                if config["thrust_waiver"] and thrust_waives_extension(
                    direction, trend_label
                ):
                    blocked["extension_waived_by_thrust"] += 1
                else:
                    blocked["ma20_extension"] += 1
                    continue

            if config["require_ma_confirm"] and not outcome.get("ma_confirms"):
                blocked["ma_confirm"] += 1
                continue

            min_vol = config["min_or_vol_ratio"]
            if min_vol:
                ratio = outcome.get("or_vol_ratio")
                if ratio is None:
                    blocked["or_vol_unknown"] += 1
                    continue
                if ratio < min_vol:
                    blocked["or_vol_low"] += 1
                    continue

            if config["min_or_range_pct"] and \
                    outcome["or_range_pct"] < config["min_or_range_pct"]:
                blocked["or_range_narrow"] += 1
                continue

            ratio = None
            if config["pc_mode"] != "off":
                source = config["pc_source"]
                ratio = (
                    source.get((session, ticker))
                    if config["pc_mode"] == "file"
                    else source.get(ticker)
                )
                if ratio is None:
                    blocked["no_pc_ratio"] += 1
                    continue
                if not pc_agrees(direction, ratio, config["call_bias"], config["put_bias"]):
                    blocked["pc_disagree"] += 1
                    continue

            eligible.append((win_rate, ticker, outcome, direction, ratio))

        if not eligible:
            continue

        divisor = len(eligible) if config["reallocate"] else len(picks)
        slot_capital = config["capital"] / divisor
        for win_rate, ticker, outcome, direction, ratio in eligible:
            trades.append(
                {
                    "session": session,
                    "ticker": ticker,
                    "direction": direction,
                    "prior_win_rate": win_rate,
                    "ma20_distance_pct": config["ma20_distance"].get(ticker, {}).get(session),
                    "call_put_ratio": ratio,
                    "or_vol_ratio": outcome.get("or_vol_ratio"),
                    "or_range_pct": outcome["or_range_pct"],
                    "regime": config["regime_of"](ticker, session) or "n/a",
                    "qqq_regime": config["regime_classes"].get(session, "n/a"),
                    "entry": outcome["or_close"],
                    "stop_price": outcome["stop_price"],
                    "exit_price": outcome["exit_price"],
                    "exit_reason": outcome["exit_reason"],
                    "exit_mode": exit_label,
                    "exit_bar": outcome["exit_bar"],
                    "return_pct": outcome["return_pct"] - config["cost_pct"],
                    "gross_return_pct": outcome["return_pct"],
                    "max_gain_pct": outcome["max_gain_pct"],
                    "pnl": slot_capital
                    * (outcome["return_pct"] - config["cost_pct"]) / 100,
                    "slot_capital": slot_capital,
                }
            )

    return trades, blocked


def summarise(trades, label):
    if not trades:
        return {"label": label, "trades": 0, "pnl": 0.0}
    wins = [t for t in trades if t["return_pct"] > 0]
    pnl = sum(t["pnl"] for t in trades)
    deployed = sum(t["slot_capital"] for t in trades)
    return {
        "label": label,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "pnl": pnl,
        "avg_return_pct": sum(t["return_pct"] for t in trades) / len(trades),
        "return_on_deployed_pct": pnl / deployed * 100 if deployed else 0,
        "best": max(trades, key=lambda t: t["return_pct"]),
        "worst": min(trades, key=lambda t: t["return_pct"]),
        "longs": sum(1 for t in trades if t["direction"] == "bull"),
        "shorts": sum(1 for t in trades if t["direction"] == "bear"),
    }


def _print_summary(summary, capital, cumulative=None):
    if not summary["trades"]:
        print(f"{summary['label']:>12}   no trades")
        return
    cum = ""
    if cumulative is not None:
        cum = f" {cumulative:>+11,.0f} {cumulative / capital * 100:>+8.1f}%"
    print(
        f"{summary['label']:>12} {summary['trades']:>7} {summary['longs']:>6}"
        f" {summary['shorts']:>7} {summary['win_rate']:>8.1f}%"
        f" {summary['avg_return_pct']:>+11.3f}% {summary['pnl']:>+12,.0f}"
        f" {summary['pnl'] / capital * 100:>+8.2f}%"
        f" {summary['return_on_deployed_pct']:>+10.2f}%{cum}"
    )


def _print_period_table(trades, capital, period, label):
    grouped = defaultdict(list)
    for trade in trades:
        grouped[period(trade["session"])].append(trade)

    print(
        f"\n{label:>12} {'trades':>7} {'long':>6} {'short':>7} {'win rate':>9}"
        f" {'avg return':>12} {'P&L $':>12} {'P&L %':>9} {'ret/deployed':>11}"
        f" {'cum P&L':>11} {'cum %':>9}"
    )
    running = 0.0
    for key in sorted(grouped):
        summary = summarise(grouped[key], key)
        running += summary["pnl"]
        _print_summary(summary, capital, running)
    total = summarise(trades, "TOTAL")
    _print_summary(total, capital, total["pnl"])
    print(
        f"\nstarting capital: ${capital:,.0f} per session, split equally across picks,"
        f" reset daily (no compounding)"
    )
    print(f"total return on the ${capital:,.0f} base: {total['pnl'] / capital * 100:+.1f}%")


def _week_key(session: date):
    monday = session - timedelta(days=session.weekday())
    return f"{monday} w{session.isocalendar()[1]:02d}"


def _print_exit_reason_table(trades):
    by_reason = defaultdict(list)
    for trade in trades:
        by_reason[trade["exit_reason"]].append(trade)

    print(
        f"\n{'exit reason':>18} {'n':>6} {'share':>7} {'win rate':>9}"
        f" {'avg return':>12} {'P&L $':>12}"
    )
    for reason, rows in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        stats = summarise(rows, reason)
        print(
            f"{reason:>18} {stats['trades']:>6} {stats['trades'] / len(trades) * 100:>6.1f}%"
            f" {stats['win_rate']:>8.1f}% {stats['avg_return_pct']:>+11.3f}%"
            f" {stats['pnl']:>+12,.0f}"
        )


def _print_ticker_table(trades):
    by_ticker = defaultdict(list)
    for trade in trades:
        by_ticker[trade["ticker"]].append(trade)

    print(f"\n{'ticker':>8} {'trades':>7} {'long':>6} {'short':>7} {'win rate':>9} {'P&L $':>12}")
    for ticker, rows in sorted(by_ticker.items(), key=lambda kv: -sum(t["pnl"] for t in kv[1])):
        stats = summarise(rows, ticker)
        print(
            f"{ticker:>8} {stats['trades']:>7} {stats['longs']:>6} {stats['shorts']:>7}"
            f" {stats['win_rate']:>8.1f}% {stats['pnl']:>+12,.0f}"
        )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--or-bars", type=int, default=3)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--min-win-rate", type=float, default=50.0)
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument(
        "--exit-time", default=DEFAULT_EXIT_TIME,
        help=f"Time exit in ET, HH:MM (default: {DEFAULT_EXIT_TIME} ET = 11:15 PT)",
    )
    parser.add_argument(
        "--trailing-start-bars", type=int, default=1,
        help="Bars after entry before the MA trailing exit becomes active",
    )
    parser.add_argument(
        "--no-hard-stop", action="store_true", help="Disable the OR-extreme hard stop"
    )
    parser.add_argument(
        "--no-trailing", action="store_true", help="Disable the MA trailing exit"
    )
    parser.add_argument(
        "--trailing-ma-period", type=int, default=TRAILING_MA_PERIOD,
        help=f"Period of the trailing MA on 5-min closes (default: {TRAILING_MA_PERIOD})",
    )
    parser.add_argument(
        "--stop-pct", type=float,
        help="Hard stop as a percent adverse move from entry; defaults to the OR extreme",
    )
    parser.add_argument(
        "--max-ma20-dist-adr", type=float, default=1.5,
        help="Block entries further from the daily MA20 than this multiple of the ticker's "
             "average daily range (default: 1.5). Pass 0 to disable",
    )
    parser.add_argument(
        "--max-ma20-dist-pct", type=float,
        help="Absolute percent cap on distance from the daily MA20; overrides the ADR multiple",
    )
    parser.add_argument(
        "--trail-strong", type=int,
        help="Trailing MA period on 5-min closes in a strong regime (0 = hold to the "
             "time exit). Enables regime-adaptive trailing together with the others",
    )
    parser.add_argument("--trail-consolidation", type=int)
    parser.add_argument("--trail-weak", type=int)
    parser.add_argument(
        "--min-or-vol-ratio", type=float, default=0.0,
        help="Require OR-window volume at least this multiple of the ticker's prior "
             f"{OR_VOLUME_BASELINE}-session OR-volume average (0 = off)",
    )
    parser.add_argument(
        "--min-or-range-pct", type=float, default=0.0,
        help="Require the OR range to be at least this percent of price (0 = off)",
    )
    parser.add_argument(
        "--require-ma-confirm", type=int, metavar="PERIOD",
        help="Require the OR close on the right side of this 5-min MA (e.g. 20)",
    )
    parser.add_argument(
        "--regime-gate", default="off", choices=["off", "longs", "both"],
        help="Block signals fighting the benchmark's PRIOR-close daily trend. "
             "'longs' blocks bull signals when the benchmark closed below its MA",
    )
    parser.add_argument(
        "--regime-source", default="stock", choices=["stock", "benchmark"],
        help="Whose daily MA stack picks the trailing period (default: the stock's own)",
    )
    parser.add_argument("--regime-symbol", default="QQQ")
    parser.add_argument("--regime-ma", type=int, default=DAILY_MA_PERIOD)
    parser.add_argument(
        "--no-reallocate", action="store_true",
        help="Size slots across the pre-filter picks, leaving filtered slots idle",
    )
    parser.add_argument("--pc-mode", default="off", choices=["off", "snapshot", "file"])
    parser.add_argument("--pc-file")
    parser.add_argument("--pc-band", type=int, default=12)
    parser.add_argument("--call-bias", type=float, default=1.2)
    parser.add_argument("--put-bias", type=float, default=1.2)
    parser.add_argument(
        "--thrust-waiver", action="store_true",
        help="Let a fresh RECOVERY/BREAKDOWN thrust override the MA20 extension gate "
             "in the thrust's own direction. Off by default",
    )
    parser.add_argument(
        "--exit-by-spread", action="store_true",
        help="Per ticker, switch to a +%d min hold when it beat the full hold on prior "
             "sessions (lifecycle 15mWR-vs-EOD spread). Off by default"
             % EARLY_EXIT_MINUTES,
    )
    parser.add_argument(
        "--spread-edge-pp", type=float, default=0.0,
        help="Win-rate points the early exit must beat the full hold by (default 0)",
    )
    parser.add_argument(
        "--min-median-pct", type=float,
        help="Require the trailing median return per selection to clear this percent "
             "(lifecycle Med% gate). Off by default",
    )
    parser.add_argument(
        "--cost-bps", type=float, default=0.0,
        help="Round-trip cost in basis points charged against every trade",
    )
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--weekly", action="store_true", help="Also print the weekly table")
    parser.add_argument("--csv-out")
    return parser.parse_args()


def main():
    args = parse_args()
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    exit_time = datetime.strptime(args.exit_time, "%H:%M").time()
    start_date = date.fromisoformat(args.start)
    end_date = clamp_end_for_sip(date.fromisoformat(args.end), feed)
    fetch_start = start_date - timedelta(days=WARMUP_CALENDAR_DAYS)

    client = AlpacaAPIClient(is_paper_trading=True)
    intraday = fetch_bars(args.tickers, fetch_start, end_date, allow_intraday=True, feed=feed)
    daily = fetch_daily_bars(
        args.tickers, start_date - timedelta(days=BENCHMARK_WARMUP_DAYS), end_date, feed=feed
    )

    trailing_start = TRAILING_DISABLED if args.no_trailing else args.trailing_start_bars
    regime_trail = {
        "strong": args.trail_strong,
        "consolidation": args.trail_consolidation,
        "weak": args.trail_weak,
    }
    adaptive = any(v is not None for v in regime_trail.values())
    if adaptive:
        regime_trail = {
            k: (v if v is not None else args.trailing_ma_period)
            for k, v in regime_trail.items()
        }
        periods = sorted(set(regime_trail.values()))
    else:
        periods = [args.trailing_ma_period]

    entry_minutes = 9 * 60 + 30 + args.or_bars * 5
    early_exit_time = time(
        (entry_minutes + EARLY_EXIT_MINUTES) // 60, (entry_minutes + EARLY_EXIT_MINUTES) % 60
    )
    outcomes_by_period = {p: {} for p in periods}
    early_by_period = {p: {} for p in periods}
    ma20_distance, max_distance, spots, stock_regime, trend_states = {}, {}, {}, {}, {}
    for ticker in args.tickers:
        bars = intraday.get(ticker, pd.DataFrame())
        daily_bars = daily.get(ticker, pd.DataFrame())
        if bars.empty:
            continue

        for period in periods:
            start_bars = TRAILING_DISABLED if (args.no_trailing or period == 0) else trailing_start
            outcomes_by_period[period][ticker] = build_session_outcomes(
                bars, args.or_bars, exit_time, start_bars, not args.no_hard_stop,
                period, args.stop_pct, args.require_ma_confirm
            )
            if args.exit_by_spread:
                early_by_period[period][ticker] = build_session_outcomes(
                    bars, args.or_bars, early_exit_time, start_bars,
                    not args.no_hard_stop, period, args.stop_pct, args.require_ma_confirm
                )
        stock_regime[ticker] = build_regime_classes(daily_bars)
        trend_states[ticker] = (
            classify_daily_trend(daily_bars) if args.thrust_waiver else {}
        )
        ma20_distance[ticker] = build_ma20_distance(daily_bars)
        max_distance[ticker] = build_extension_caps(
            daily_bars, args.max_ma20_dist_adr, args.max_ma20_dist_pct
        )
        if not daily_bars.empty:
            spots[ticker] = float(daily_bars["Close"].iloc[-1])

    regime, regime_classes = {}, {}
    if args.regime_gate != "off" or adaptive:
        bench = fetch_daily_bars(
            [args.regime_symbol],
            start_date - timedelta(days=BENCHMARK_WARMUP_DAYS),
            end_date,
            feed=feed,
        ).get(args.regime_symbol, pd.DataFrame())
        regime = build_regime_state(bench, args.regime_ma)
        regime_classes = build_regime_classes(bench)

    def regime_of(ticker, session):
        if args.regime_source == "stock":
            return stock_regime.get(ticker, {}).get(session)
        return regime_classes.get(session)

    def early_for(ticker, session):
        if not args.exit_by_spread:
            return None
        if not adaptive:
            return early_by_period[periods[0]].get(ticker, {}).get(session)
        label = regime_of(ticker, session) or "consolidation"
        return early_by_period.get(regime_trail.get(label), {}).get(ticker, {}).get(session)

    def outcome_for(ticker, session):
        if not adaptive:
            return outcomes_by_period[periods[0]].get(ticker, {}).get(session)
        label = regime_of(ticker, session) or "consolidation"
        period = regime_trail.get(label)
        return outcomes_by_period.get(period, {}).get(ticker, {}).get(session)

    all_sessions = sorted(
        {day for by_ticker in outcomes_by_period[periods[0]].values() for day in by_ticker}
    )
    sessions = [day for day in all_sessions if start_date <= day <= end_date]

    snapshot_ratios = {}
    if args.pc_mode == "snapshot":
        snapshot_ratios = snapshot_call_put_ratios(
            client, args.tickers, main_monthly_expiry(), args.pc_band, spots
        )
    pc_source, pc_note = load_put_call_ratios(args.pc_file, snapshot_ratios, args.pc_mode)

    trades, blocked = run_backtest(
        {
            "outcome_for": outcome_for,
            "regime_of": regime_of,
            "tickers": [t for t in args.tickers if t in outcomes_by_period[periods[0]]],
            "regime_classes": regime_classes,
            "require_ma_confirm": args.require_ma_confirm,
            "min_or_vol_ratio": args.min_or_vol_ratio,
            "min_or_range_pct": args.min_or_range_pct,
            "reallocate": not args.no_reallocate,
            "cost_pct": args.cost_bps / 100.0,
            "exit_by_spread": args.exit_by_spread,
            "spread_edge_pp": args.spread_edge_pp,
            "min_median_pct": args.min_median_pct,
            "trend_states": trend_states,
            "thrust_waiver": args.thrust_waiver,
            "early_for": early_for,
            "timeline": all_sessions,
            "sessions": sessions,
            "top_n": args.top,
            "min_win_rate": args.min_win_rate,
            "capital": args.capital,
            "ma20_distance": ma20_distance,
            "max_distance": max_distance,
            "pc_source": pc_source,
            "pc_mode": args.pc_mode,
            "call_bias": args.call_bias,
            "put_bias": args.put_bias,
            "regime": regime,
            "regime_mode": args.regime_gate,
        }
    )

    pt_hour = (exit_time.hour - 3) % 24
    print(f"\nOR + trailing-win-rate backtest | {start_date} → {end_date} | feed={args.feed}")
    print(f"entry 09:45 ET | time exit {exit_time.strftime('%H:%M')} ET"
          f" ({pt_hour:02d}:{exit_time.minute:02d} PT)")
    stop_label = (
        "OFF" if args.no_hard_stop
        else (f"{args.stop_pct:.2f}% from entry" if args.stop_pct is not None
              else "OR low (long) / OR high (short)")
    )
    if adaptive:
        trail_label = " | ".join(
            f"{k}=" + ("time exit" if v == 0 else f"MA{v}")
            for k, v in regime_trail.items()
        )
        print(f"hard stop: {stop_label} | trailing by regime: {trail_label}")
    else:
        print(f"hard stop: {stop_label}"
              f" | trailing: {'OFF' if args.no_trailing else 'MA%d' % args.trailing_ma_period}"
              f" after {args.trailing_start_bars} bar(s)")
    if args.min_or_vol_ratio:
        print(f"OR volume gate: >= {args.min_or_vol_ratio:g}x prior"
              f" {OR_VOLUME_BASELINE}-session OR-volume average")
    if args.min_or_range_pct:
        print(f"OR range gate: >= {args.min_or_range_pct:g}% of price")
    if args.require_ma_confirm:
        print(f"entry confirmation: OR close beyond the 5-min MA{args.require_ma_confirm}")
    if adaptive:
        if args.regime_source == "stock":
            counts = Counter(
                label for by_session in stock_regime.values() for label in by_session.values()
            )
            print(f"trailing regime source: each stock's own daily stack; mix {dict(counts)}")
        else:
            print(f"trailing regime source: {args.regime_symbol};"
                  f" mix {dict(Counter(regime_classes.values()))}")
    elif regime_classes:
        print(f"{args.regime_symbol} regime mix: {dict(Counter(regime_classes.values()))}")
    if args.max_ma20_dist_pct is not None:
        print(f"MA20 extension gate: flat {args.max_ma20_dist_pct:.2f}%")
    elif args.max_ma20_dist_adr:
        latest = {
            t: sorted(caps.items())[-1][1]
            for t, caps in sorted(max_distance.items()) if caps
        }
        shown = ", ".join(f"{t}={v:.1f}%" for t, v in latest.items())
        print(f"MA20 extension gate: {args.max_ma20_dist_adr:g}x rolling ADR"
              f" (prior 20 sessions); last values -> {shown}")
    else:
        print("MA20 extension gate: OFF")
    if args.regime_gate == "off":
        print("regime gate: OFF")
    else:
        above = sum(1 for v in regime.values() if v)
        print(f"regime gate: {args.regime_gate} vs {args.regime_symbol}"
              f" MA{args.regime_ma} on the PRIOR close"
              f" ({above}/{len(regime)} sessions above)")
    if args.thrust_waiver:
        print("thrust waiver: ON — RECOVERY/BREAKDOWN thrusts bypass the extension gate")
    if args.exit_by_spread:
        print(f"exit-by-spread: ON, early hold ends {early_exit_time.strftime('%H:%M')} ET,"
              f" edge threshold {args.spread_edge_pp:g}pp")
    if args.min_median_pct is not None:
        print(f"median gate: trailing median return must clear {args.min_median_pct:g}%")
    if args.cost_bps:
        print(f"cost charged: {args.cost_bps:g} bps round trip per trade")
    print(f"put/call gate: {pc_note}")
    print(f"sessions: {len(sessions)} | blocked entries: {dict(blocked) or 'none'}")

    if not trades:
        print("\nno trades")
        return

    if args.weekly:
        _print_period_table(trades, args.capital, _week_key, "week")
    _print_period_table(trades, args.capital, lambda d: d.strftime("%Y-%m"), "month")
    _print_exit_reason_table(trades)
    _print_ticker_table(trades)

    total = summarise(trades, "x")
    print(f"\nbest  {total['best']['ticker']} {total['best']['session']}"
          f" {total['best']['direction']} {total['best']['return_pct']:+.2f}%"
          f" ({total['best']['exit_reason']})")
    print(f"worst {total['worst']['ticker']} {total['worst']['session']}"
          f" {total['worst']['direction']} {total['worst']['return_pct']:+.2f}%"
          f" ({total['worst']['exit_reason']})")

    if args.csv_out:
        out_path = Path(args.csv_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)
        print(f"\nper-trade rows written to {out_path}")


if __name__ == "__main__":
    main()
