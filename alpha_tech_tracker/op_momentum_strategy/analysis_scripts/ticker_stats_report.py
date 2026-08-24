"""Per-ticker opening-range, option-skew, volume and volatility stats."""

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path

import matplotlib
import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    fetch_bars,
    fetch_daily_bars,
)
from alpha_tech_tracker.trade_api.alpaca_client.client import (
    AlpacaAPIClient,
    main_monthly_expiry,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  headless backend must be set first

DEFAULT_TICKERS = ["SNDK", "APP", "NVDA", "LLY", "MRNA", "COIN", "HOOD"]
DEFAULT_BANDS = [12, 16, 20]
MARKET_OPEN = time(9, 30)
SESSION_END = time(16, 0)
MARKET_TIMEZONE = "America/New_York"
EXTENDED_HOURS_END = time(20, 0)
TREND_MA_PERIODS = (20, 50, 200)
TREND_SLOPE_LOOKBACK = 10
TREND_FLAT_PCT = 0.5
TREND_CROSS_LOOKBACK = 10
TREND_THRUST_VOL_MULT = 1.5
DAILY_HISTORY_DAYS = 500  # MA200 needs ~200 sessions
DAILY_MA_PERIOD = 20
EXTENSION_ADR_FACTOR = 1.5
MINUTES_BEFORE_CLOSE = 10
DAILY_STATS_SESSIONS = 20
SESSIONS_PER_WEEK = 5


def _fmt_ratio(value):
    return f"{value:.2f}" if value is not None else "n/a"


def resolve_followthrough_threshold(movement, absolute_pct: float, adr_factor):
    """Pick the follow-through bar: a fraction of the ticker's average daily range,
    or a flat percentage when no ADR factor is given or no daily history exists.
    """
    if adr_factor and movement and movement["avg_range_pct"]:
        return adr_factor * movement["avg_range_pct"], f"{adr_factor:g}xADR"
    return absolute_pct, "flat"


def latest_sip_date(now_et=None):
    """Newest date SIP will serve: today once extended hours have ended, else yesterday."""
    now_et = now_et or pd.Timestamp.now(tz=MARKET_TIMEZONE)
    today = now_et.date()
    if now_et.time() >= EXTENDED_HOURS_END:
        return today
    return today - timedelta(days=1)


def clamp_end_for_sip(end_date: date, feed: DataFeed, now_et=None):
    """SIP entitlements reject data newer than the last completed session.

    Extended hours end at 20:00 ET, so the current date becomes available then.
    """
    if feed != DataFeed.SIP:
        return end_date
    return min(end_date, latest_sip_date(now_et))


def build_ma20_distance(daily: pd.DataFrame):
    """Prior close distance from the daily MA20 in percent, known at signal time."""
    if daily.empty:
        return {}
    close = daily["Close"]
    prior_close = close.shift(1)
    prior_ma20 = close.rolling(DAILY_MA_PERIOD).mean().shift(1)
    distances = {}
    for stamp in daily.index:
        session = stamp.date() if hasattr(stamp, "date") else stamp
        if pd.isna(prior_ma20.get(stamp)) or pd.isna(prior_close.get(stamp)):
            continue
        distances[session] = (
            (prior_close[stamp] - prior_ma20[stamp]) / prior_ma20[stamp] * 100
        )
    return distances


def build_extension_caps(daily: pd.DataFrame, adr_factor, flat_pct):
    """Per-session cap on distance from the daily MA20.

    The ADR is a rolling mean of prior sessions only, so the cap in force on any
    given day never uses that day's range or anything after it.
    """
    if daily.empty:
        return {}
    range_pct = (daily["High"] - daily["Low"]) / daily["Open"] * 100
    prior_adr = range_pct.rolling(DAILY_STATS_SESSIONS).mean().shift(1)
    caps = {}
    for stamp in daily.index:
        session = stamp.date() if hasattr(stamp, "date") else stamp
        if flat_pct is not None:
            caps[session] = flat_pct
        elif adr_factor and not pd.isna(prior_adr.get(stamp)):
            caps[session] = adr_factor * prior_adr[stamp]
    return caps


def build_regime_state(daily: pd.DataFrame, ma_period: int):
    """Map session to whether the benchmark closed above its MA on the PRIOR session.

    Both the close and the moving average are shifted one session, so the value in
    force at 09:45 never uses the current day's data.
    """
    if daily.empty:
        return {}
    close = daily["Close"]
    prior_close = close.shift(1)
    prior_ma = close.rolling(ma_period).mean().shift(1)
    state = {}
    for stamp in daily.index:
        session = stamp.date() if hasattr(stamp, "date") else stamp
        if pd.isna(prior_ma.get(stamp)) or pd.isna(prior_close.get(stamp)):
            continue
        state[session] = bool(prior_close[stamp] > prior_ma[stamp])
    return state


def extension_blocks_entry(direction, distance_pct, max_distance_pct):
    """Skip entries stretched away from the daily MA20 in the trade's own direction."""
    if distance_pct is None or max_distance_pct is None:
        return False
    if direction == "bull":
        return distance_pct > max_distance_pct
    return distance_pct < -max_distance_pct


def _ma_slope_label(series, stamp, lookback, flat_pct):
    """up / flat / down for one moving average over `lookback` sessions."""
    now = series.get(stamp)
    then = series.shift(lookback).get(stamp)
    if now is None or then is None or pd.isna(now) or pd.isna(then) or then == 0:
        return None
    change = (now - then) / then * 100
    if change > flat_pct:
        return "up"
    if change < -flat_pct:
        return "down"
    return "flat"


def classify_daily_trend(daily: pd.DataFrame, lookback=TREND_SLOPE_LOOKBACK,
                         flat_pct=TREND_FLAT_PCT,
                         cross_lookback=TREND_CROSS_LOOKBACK,
                         thrust_vol_mult=TREND_THRUST_VOL_MULT):
    """Label each session's daily-chart trend from the prior close and MA slopes.

    STRONG_UP            all MAs rising, price above the MA50
    UP_PULLBACK          all MAs still rising, price back below the MA50
    UPTREND              price above the MA200, no MA falling
    RECOVERY_ATTEMPT     MAs still falling, but price reclaimed MA20 and MA50 on
                         heavy volume and has not yet retaken the MA200
    RECOVERY_CONFIRMED   the same thrust, now also above the MA200
    DOWN_BOUNCE          all MAs falling, price back above the MA50 without a thrust
    STRONG_DOWN          all MAs falling, price below the MA50
    BREAKDOWN_ATTEMPT    mirror of RECOVERY_ATTEMPT: MAs still rising, price lost
                         MA20 and MA50 on heavy volume, still above the MA200
    BREAKDOWN_CONFIRMED  the same thrust, now also below the MA200
    DOWNTREND            price below the MA200, no MA rising
    MIXED                none of the above
    """
    if daily.empty:
        return {}
    close = daily["Close"]
    prior_close = close.shift(1)
    mas = {period: close.rolling(period).mean().shift(1) for period in TREND_MA_PERIODS}

    ma50_raw = close.rolling(50).mean()
    was_below_ma50 = (close < ma50_raw).shift(1).rolling(cross_lookback).max()
    was_above_ma50 = (close > ma50_raw).shift(1).rolling(cross_lookback).max()
    if "Volume" in daily:
        vol_ratio = (daily["Volume"] / daily["Volume"].rolling(20).mean()).shift(1)
        thrust = vol_ratio.rolling(cross_lookback).max()
    else:
        thrust = pd.Series(index=daily.index, dtype=float)

    states = {}
    for stamp in daily.index:
        session = stamp.date() if hasattr(stamp, "date") else stamp
        price = prior_close.get(stamp)
        if price is None or pd.isna(price):
            continue
        levels = {period: mas[period].get(stamp) for period in TREND_MA_PERIODS}
        if any(v is None or pd.isna(v) for v in levels.values()):
            continue
        slopes = {
            period: _ma_slope_label(mas[period], stamp, lookback, flat_pct)
            for period in TREND_MA_PERIODS
        }
        if any(v is None for v in slopes.values()):
            continue

        values = list(slopes.values())
        all_up = all(v == "up" for v in values)
        all_down = all(v == "down" for v in values)
        none_down = not any(v == "down" for v in values)
        none_up = not any(v == "up" for v in values)
        above_ma50 = price > levels[50]
        above_ma200 = price > levels[200]
        above_ma20 = price > levels[20]
        thrust_ratio = thrust.get(stamp)
        heavy = thrust_ratio is not None and not pd.isna(thrust_ratio) \
            and thrust_ratio >= thrust_vol_mult
        reclaimed = bool(was_below_ma50.get(stamp)) and above_ma50 and above_ma20
        lost = bool(was_above_ma50.get(stamp)) and not above_ma50 and not above_ma20

        if all_up and above_ma50:
            label = "STRONG_UP"
        elif not none_up and heavy and lost:
            label = "BREAKDOWN_CONFIRMED" if not above_ma200 else "BREAKDOWN_ATTEMPT"
        elif all_up:
            label = "UP_PULLBACK"
        elif not none_down and heavy and reclaimed:
            label = "RECOVERY_CONFIRMED" if above_ma200 else "RECOVERY_ATTEMPT"
        elif all_down and not above_ma50:
            label = "STRONG_DOWN"
        elif all_down:
            label = "DOWN_BOUNCE"
        elif above_ma200 and none_down:
            label = "UPTREND"
        elif not above_ma200 and none_up:
            label = "DOWNTREND"
        else:
            label = "MIXED"

        states[session] = {
            "label": label,
            "slopes": slopes,
            "vs_ma50_pct": (price - levels[50]) / levels[50] * 100,
            "vs_ma200_pct": (price - levels[200]) / levels[200] * 100,
            "runway_to_ma200_pct": (levels[200] - price) / price * 100,
            "ma50_ma200_gap_pct": (levels[50] - levels[200]) / levels[200] * 100,
            "thrust_vol": None if thrust_ratio is None or pd.isna(thrust_ratio)
            else float(thrust_ratio),
        }
    return states


def gate_state(daily: pd.DataFrame, longs_allowed):
    """Latest entry-gate state: MA20 extension per side, plus the benchmark verdict."""
    distances = build_ma20_distance(daily)
    caps = build_extension_caps(daily, EXTENSION_ADR_FACTOR, None)
    if not distances or not caps:
        return {"longs_allowed": longs_allowed}
    session = max(distances)
    distance = distances[session]
    cap = caps.get(session)
    return {
        "session": session,
        "ma20_distance_pct": distance,
        "cap_pct": cap,
        "long_blocked": extension_blocks_entry("bull", distance, cap),
        "short_blocked": extension_blocks_entry("bear", distance, cap),
        "longs_allowed": longs_allowed,
    }


def build_watchlist(results, week_count, min_sessions=2):
    """Label each ticker by which side has paid recently, and whether it is enterable.

    The label describes the trailing window, not the next session: a walk-forward over
    73 sessions put these picks at a 51.5% hit rate against a 52.3% take-everything
    baseline, and the no-bias group beat both. Read the gate column for what is
    actionable and the label as context.
    """
    rows = []
    for ticker, stats in results.items():
        summary = stats["or_direction"].get(week_count)
        if not summary:
            rows.append({"ticker": ticker, "bucket": "no-data"})
            continue

        sides = []
        for side, key in (("long-bias", "bull"), ("short-bias", "bear")):
            row = summary[key]
            if row["days"] < min_sessions or row["avg_eod_pct"] is None:
                continue
            sides.append((row["avg_eod_pct"], side, key, row))
        if not sides:
            rows.append({"ticker": ticker, "bucket": "no-data"})
            continue

        edge, side, key, row = max(sides)
        gate = stats.get("gate", {})
        blocked = gate.get("long_blocked") if key == "bull" else gate.get("short_blocked")
        regime_blocked = key == "bull" and gate.get("longs_allowed") is False
        skew = stats["option_skew"]
        band = skew["bands"][0] if "error" not in skew and skew.get("bands") else None
        trend = stats["trend"]
        rows.append(
            {
                "ticker": ticker,
                "bucket": side if edge > 0 else "no-bias",
                "side": side,
                "edge": edge,
                "days": row["days"],
                "intraday_hit": row["followed_through"] / row["days"] * 100,
                "eod_hit": row["eod_wins"] / row["eod_scored"] * 100
                if row["eod_scored"] else None,
                "worst": row["worst_eod_pct"],
                "trend": trend[max(trend)]["label"] if trend else "n/a",
                "call_put": band["call_put"] if band else None,
                "vol_ratio": (stats["volume"] or {}).get("ratio"),
                "gate": "EXT" if blocked else ("REGIME" if regime_blocked else "ok"),
            }
        )
    return rows


def _print_watchlist(rows, week_count, regime_note):
    print("\n" + "=" * 108)
    print(f"RECENT BIAS & ENTRY GATES   (which side paid over the trailing"
          f" {week_count} week(s) — descriptive, not a forecast)")
    print(regime_note)
    print("=" * 108)
    print(
        f"{'':11}{'tkr':6} {'days':>5} {'intraday hit':>13} {'EOD hit':>8}"
        f" {'avg 15:50':>10} {'worst':>8} {'trend':>20} {'C/P':>6} {'vol':>7} {'gate':>7}"
    )
    order = {"long-bias": 0, "short-bias": 1, "no-bias": 2, "no-data": 3}
    for row in sorted(rows, key=lambda r: (order[r["bucket"]], -r.get("edge", 0))):
        if row["bucket"] == "no-data":
            print(f"{'':11}{row['ticker']:6}   no qualifying sessions")
            continue
        vol = row["vol_ratio"]
        vol_text = f"{vol:.2f}x" if vol else "n/a"
        eod = f"{row['eod_hit']:.0f}%" if row["eod_hit"] is not None else "n/a"
        print(
            f"{row['bucket']:>10} {row['ticker']:6} {row['days']:>5}"
            f" {row['intraday_hit']:>12.0f}% {eod:>8}"
            f" {row['edge']:>+9.2f}% {row['worst']:>+7.2f}%"
            f" {row['trend']:>20} {_fmt_ratio(row['call_put']):>6} {vol_text:>7}"
            f" {row['gate']:>7}"
        )
    print("\nintraday hit = share of sessions whose move in the OR's direction reached the"
          " follow-through bar (default 0.25xADR)")
    print("EOD hit      = share of sessions still profitable in that direction at 15:50")
    print("gate: EXT = too far from the daily MA20 to enter that side;"
          " REGIME = benchmark below its MA20 blocks longs")
    print("bias labels describe the trailing window only — a 73-session walk-forward"
          " found no forecasting edge over taking every signal")


def _print_trend_table(results, lookback, flat_pct):
    print("\n" + "=" * 104)
    print(f"DAILY TREND   (prior close vs MA20/50/200; slopes over {lookback} sessions,"
          f" flat band +/-{flat_pct:g}%)")
    print("runway = distance from price to the MA200 target;"
          " 50-200 gap = room between those MAs")
    print("=" * 104)
    print(
        f"{'tkr':6} {'trend':>20} {'MA20':>5} {'MA50':>5} {'MA200':>6}"
        f" {'vs MA50':>8} {'runway':>8} {'50-200 gap':>11} {'thrust':>7} {'as of':>12}"
    )
    for ticker, stats in results.items():
        trend = stats["trend"]
        if not trend:
            print(f"{ticker:6} {'insufficient history':>20}")
            continue
        latest = max(trend)
        row = trend[latest]
        arrows = {"up": "up", "down": "down", "flat": "flat"}
        thrust = row.get("thrust_vol")
        print(
            f"{ticker:6} {row['label']:>20}"
            f" {arrows[row['slopes'][20]]:>5} {arrows[row['slopes'][50]]:>5}"
            f" {arrows[row['slopes'][200]]:>6}"
            f" {row['vs_ma50_pct']:>+7.1f}% {row['runway_to_ma200_pct']:>+7.1f}%"
            f" {row['ma50_ma200_gap_pct']:>+10.1f}%"
            f" {(f'{thrust:.2f}x' if thrust else 'n/a'):>7} {str(latest):>12}"
        )


def _session_frames(bars: pd.DataFrame):
    for session_date, frame in bars.groupby(bars.index.date):
        yield session_date, frame


def _price_before_close(session_bars: pd.DataFrame, minutes_before: int):
    """Close of the last 5-min bar ending at or before `minutes_before` before 16:00."""
    cutoff = (
        datetime.combine(date.today(), SESSION_END) - timedelta(minutes=minutes_before)
    ).time()
    prior = session_bars[session_bars.index.time < cutoff]
    return float(prior["Close"].iloc[-1]) if not prior.empty else None


def session_or_outcome(regular: pd.DataFrame, or_bars: int, followthrough_pct: float):
    """Classify one session by where the opening window closed against its midpoint.

    Bull sessions close the window above the midpoint, bear sessions below it.
    Excursion and 15:50 returns are signed in the direction of the setup, so a
    positive number favours the trade on either side.
    """
    opening = regular.iloc[:or_bars]
    rest = regular.iloc[or_bars:]
    or_mid = (float(opening["High"].max()) + float(opening["Low"].min())) / 2
    or_close = float(opening["Close"].iloc[-1])
    if or_close == or_mid:
        return None

    direction = "bull" if or_close > or_mid else "bear"
    price_1550 = _price_before_close(regular, MINUTES_BEFORE_CLOSE)

    if direction == "bull":
        excursion = float(rest["High"].max()) - or_close
        eod_move = (price_1550 - or_close) if price_1550 is not None else None
    else:
        excursion = or_close - float(rest["Low"].min())
        eod_move = (or_close - price_1550) if price_1550 is not None else None

    max_gain_pct = excursion / or_close * 100
    return {
        "session": regular.index[0].date(),
        "direction": direction,
        "or_mid": or_mid,
        "or_close": or_close,
        "followed_through": max_gain_pct >= followthrough_pct,
        "max_gain_pct": max_gain_pct,
        "eod_pct": eod_move / or_close * 100 if eod_move is not None else None,
    }


def compute_or_direction_stats(
    bars: pd.DataFrame, or_bars: int, sessions: int, followthrough_pct: float
):
    """Split sessions into bull/bear by the opening-window close and score each side.

    Two hit rates come out of this. The intraday hit rate counts sessions whose move
    in the OR's direction reached the follow-through bar, so it measures whether the
    stock travelled meaningfully. The EOD hit rate counts sessions still profitable
    in that direction at 15:50, so it measures whether the move held.
    """
    per_session = []
    for _, frame in _session_frames(bars):
        regular = frame[frame.index.time >= MARKET_OPEN]
        if len(regular) <= or_bars:
            continue
        outcome = session_or_outcome(regular, or_bars, followthrough_pct)
        if outcome:
            per_session.append(outcome)

    recent = per_session[-sessions:]
    if not recent:
        return None

    summary = {"sessions": len(recent), "first": recent[0]["session"]}
    for direction in ("bull", "bear"):
        rows = [row for row in recent if row["direction"] == direction]
        scored = [row for row in rows if row["eod_pct"] is not None]
        gains = [row["max_gain_pct"] for row in rows]
        eods = [row["eod_pct"] for row in scored]
        summary[direction] = {
            "days": len(rows),
            "followed_through": sum(1 for row in rows if row["followed_through"]),
            "avg_max_gain_pct": sum(gains) / len(gains) if gains else None,
            "best_max_gain_pct": max(gains) if gains else None,
            "eod_wins": sum(1 for value in eods if value > 0),
            "eod_scored": len(eods),
            "avg_eod_pct": sum(eods) / len(eods) if eods else None,
            "best_eod_pct": max(eods) if eods else None,
            "worst_eod_pct": min(eods) if eods else None,
        }
    return summary


def compute_opening_volume_stats(bars: pd.DataFrame, or_bars: int, baseline_sessions: int):
    opening_volumes = []
    for session_date, frame in _session_frames(bars):
        regular = frame[frame.index.time >= MARKET_OPEN]
        if len(regular) < or_bars:
            continue
        opening_volumes.append((session_date, float(regular.iloc[:or_bars]["Volume"].sum())))

    if len(opening_volumes) < 2:
        return None

    latest_date, latest_volume = opening_volumes[-1]
    baseline = [vol for _, vol in opening_volumes[-(baseline_sessions + 1) : -1]]
    if not baseline:
        return None

    average = sum(baseline) / len(baseline)
    return {
        "session": latest_date,
        "first_window_volume": latest_volume,
        "baseline_avg": average,
        "baseline_sessions": len(baseline),
        "ratio": latest_volume / average if average else None,
    }


def compute_daily_movement_stats(daily: pd.DataFrame, sessions: int):
    """Summarise range% = (H-L)/open and drift% = (close-open)/open per session."""
    recent = daily.tail(sessions)
    if recent.empty:
        return None

    range_pct = ((recent["High"] - recent["Low"]) / recent["Open"] * 100).dropna()
    drift_pct = ((recent["Close"] - recent["Open"]) / recent["Open"] * 100).dropna()
    if range_pct.empty:
        return None

    return {
        "sessions": len(range_pct),
        "avg_range_pct": float(range_pct.mean()),
        "max_range_pct": float(range_pct.max()),
        "max_range_date": range_pct.idxmax(),
        "avg_drift_pct": float(drift_pct.mean()) if not drift_pct.empty else None,
        "avg_abs_drift_pct": float(drift_pct.abs().mean()) if not drift_pct.empty else None,
        "max_abs_drift_pct": float(drift_pct.abs().max()) if not drift_pct.empty else None,
        "max_drift_date": drift_pct.abs().idxmax() if not drift_pct.empty else None,
        "range_series": range_pct,
        "drift_series": drift_pct,
    }


def reference_price(client, ticker, daily: pd.DataFrame):
    """Live quote mid, falling back to the last daily close when quotes are empty."""
    try:
        quote = client.get_stock_quote(ticker)
        bid, ask = client._extract_bid_ask({ticker: quote}, ticker)
        if bid and ask:
            return (bid + ask) / 2, "quote-mid"
    except Exception:
        pass

    if not daily.empty:
        return float(daily["Close"].iloc[-1]), "daily-close"
    return None, "unavailable"


def compute_option_skew(client, ticker, expiry, bands, spot):
    """Call/put OI ratios per strike band. OI is the prior session's OCC figure."""
    widest = max(bands)
    try:
        chain = client.get_options_open_interest(
            ticker, expiration_date=expiry, strikes_around_atm=widest, reference_price=spot
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    strikes = [row["strike_price"] for row in chain["by_strike"]]
    atm_index = strikes.index(chain["atm_strike"])

    rows = []
    for band in sorted(bands):
        low = max(0, atm_index - band)
        selected = set(strikes[low : atm_index + band + 1])
        subset = [row for row in chain["by_strike"] if row["strike_price"] in selected]
        calls = sum(row["call_open_interest"] for row in subset)
        puts = sum(row["put_open_interest"] for row in subset)
        rows.append(
            {
                "band": band,
                "strikes": len(subset),
                "strike_low": min(selected),
                "strike_high": max(selected),
                "calls": calls,
                "puts": puts,
                "call_put": round(calls / puts, 2) if puts else None,
                "put_call": round(puts / calls, 2) if calls else None,
            }
        )

    return {
        "expiry": chain["expiration_date"],
        "atm_strike": chain["atm_strike"],
        "open_interest_date": chain["open_interest_date"],
        "bands": rows,
    }


def render_distribution_chart(movement_by_ticker, out_path: Path, sessions: int):
    tickers = [ticker for ticker, stats in movement_by_ticker.items() if stats]
    if not tickers:
        return None

    columns = min(3, len(tickers))
    rows = (len(tickers) + columns - 1) // columns
    fig, axes = plt.subplots(rows, columns, figsize=(5 * columns, 3.4 * rows), squeeze=False)

    for index, ticker in enumerate(tickers):
        stats = movement_by_ticker[ticker]
        ax = axes[index // columns][index % columns]
        ax.hist(stats["range_series"], bins=10, color="#4477aa", edgecolor="white")
        ax.axvline(
            stats["avg_range_pct"], color="#cc3311", linestyle="--",
            label=f"avg {stats['avg_range_pct']:.2f}%",
        )
        ax.axvline(
            stats["max_range_pct"], color="#ee7733", linestyle=":",
            label=f"max {stats['max_range_pct']:.2f}%",
        )
        ax.set_title(f"{ticker} — daily range% ({stats['sessions']} sessions)")
        ax.set_xlabel("range % of open")
        ax.set_ylabel("sessions")
        ax.legend(fontsize=8)

    for index in range(len(tickers), rows * columns):
        axes[index // columns][index % columns].axis("off")

    fig.suptitle(f"Daily range% distribution — trailing {sessions} sessions", y=1.0)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _print_or_direction_table(results, weeks):
    print("\n" + "=" * 128)
    print(
        "OR DIRECTION OUTCOMES   (bull = opening window closed above its midpoint;"
        " returns signed with the setup)"
    )
    print("intraday hit = the move reached the follow-through bar;"
          " EOD hit = still profitable at 15:50")
    print("=" * 128)
    for week_count in weeks:
        for direction in ("bull", "bear"):
            print(f"\n-- {direction.upper()} sessions, trailing {week_count} week(s) --")
            print(
                f"{'tkr':6} {'days':>5} {'share':>7} {'bar':>14} {'intraday hit':>15}"
                f" {'avg max gain':>13} {'best max gain':>14}"
                f" {'EOD hit':>15} {'avg 15:50':>10} {'best':>8} {'worst':>8}"
            )
            for ticker, stats in results.items():
                summary = stats["or_direction"].get(week_count)
                if not summary:
                    print(f"{ticker:6} no data")
                    continue

                row = summary[direction]
                if not row["days"]:
                    print(f"{ticker:6} {0:>5}   none")
                    continue

                share = row["days"] / summary["sessions"] * 100
                thru = (
                    f"{row['followed_through']:2}/{row['days']:<2}"
                    f" ({row['followed_through'] / row['days'] * 100:5.1f}%)"
                )
                win = (
                    f"{row['eod_wins']:2}/{row['eod_scored']:<2}"
                    f" ({row['eod_wins'] / row['eod_scored'] * 100:5.1f}%)"
                    if row["eod_scored"]
                    else "n/a"
                )
                bar = f"{stats['followthrough_pct']:.2f}% {stats['followthrough_basis']}"
                print(
                    f"{ticker:6} {row['days']:>5} {share:6.0f}% {bar:>14} {thru:>15}"
                    f" {row['avg_max_gain_pct']:12.2f}% {row['best_max_gain_pct']:13.2f}%"
                    f" {win:>15} {row['avg_eod_pct']:+9.2f}%"
                    f" {row['best_eod_pct']:+7.2f}% {row['worst_eod_pct']:+7.2f}%"
                )


def _print_option_skew_table(results):
    print("\n" + "=" * 104)
    print("MONTHLY OPTION OPEN-INTEREST SKEW")
    print("=" * 104)
    print(
        f"{'tkr':6} {'expiry':>11} {'spot':>9} {'src':>11} {'band':>5} {'strikes':>7}"
        f" {'strike range':>18} {'calls':>10} {'puts':>10} {'C/P':>6} {'P/C':>6}"
    )
    for ticker, stats in results.items():
        skew = stats["option_skew"]
        if "error" in skew:
            print(f"{ticker:6} ERROR: {skew['error'][:80]}")
            continue
        for row in skew["bands"]:
            strike_range = f"{row['strike_low']:.1f}-{row['strike_high']:.1f}"
            print(
                f"{ticker:6} {skew['expiry']:>11} {stats['spot']:9.2f} {stats['spot_source']:>11}"
                f" {row['band']:>5} {row['strikes']:>7} {strike_range:>18}"
                f" {row['calls']:10,} {row['puts']:10,}"
                f" {_fmt_ratio(row['call_put']):>6} {_fmt_ratio(row['put_call']):>6}"
            )

    oi_dates = sorted(
        {
            stats["option_skew"]["open_interest_date"]
            for stats in results.values()
            if "error" not in stats["option_skew"] and stats["option_skew"]["open_interest_date"]
        }
    )
    if oi_dates:
        print(f"\nopen interest as of: {', '.join(oi_dates)}")


def _print_volume_table(results, or_bars):
    print("\n" + "=" * 104)
    print(
        f"OPENING VOLUME   (first {or_bars} bars vs trailing"
        f" {DAILY_STATS_SESSIONS}-session average of the same window)"
    )
    print("=" * 104)
    print(
        f"{'tkr':6} {'session':>12} {'first window':>14} {'baseline avg':>14}"
        f" {'ratio':>8} {'vs normal':>11}"
    )
    for ticker, stats in results.items():
        row = stats["volume"]
        if not row:
            print(f"{ticker:6} no data")
            continue
        delta = f"{(row['ratio'] - 1) * 100:+.0f}%" if row["ratio"] else "n/a"
        print(
            f"{ticker:6} {str(row['session']):>12} {row['first_window_volume']:14,.0f}"
            f" {row['baseline_avg']:14,.0f} {row['ratio']:7.2f}x {delta:>11}"
        )


def _print_movement_table(results):
    print("\n" + "=" * 104)
    print(f"DAILY MOVEMENT   (trailing {DAILY_STATS_SESSIONS} sessions)")
    print("=" * 104)
    print(
        f"{'tkr':6} {'days':>5} {'avg range%':>11} {'max range%':>11} {'max range day':>14}"
        f" {'avg drift%':>11} {'avg |drift|%':>13} {'max |drift|%':>13} {'max drift day':>14}"
    )
    for ticker, stats in results.items():
        row = stats["movement"]
        if not row:
            print(f"{ticker:6} no data")
            continue
        print(
            f"{ticker:6} {row['sessions']:>5} {row['avg_range_pct']:11.2f}"
            f" {row['max_range_pct']:11.2f} {str(row['max_range_date'])[:10]:>14}"
            f" {row['avg_drift_pct']:+11.2f} {row['avg_abs_drift_pct']:13.2f}"
            f" {row['max_abs_drift_pct']:13.2f} {str(row['max_drift_date'])[:10]:>14}"
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument(
        "--weeks", nargs="+", type=int, default=[1, 4],
        help="Lookback windows in weeks for the OR-cross stats (default: 1 4)",
    )
    parser.add_argument("--or-bars", type=int, default=3, help="5-min bars in the opening window")
    parser.add_argument(
        "--bands", nargs="+", type=int, default=DEFAULT_BANDS,
        help="Strike counts each side of ATM for the option skew table",
    )
    parser.add_argument(
        "--followthrough-adr-factor", type=float, default=0.25,
        help="Follow-through bar as a fraction of each ticker's 20-session average daily "
             "range (default: 0.25). Pass 0 to use the flat --followthrough-pct instead",
    )
    parser.add_argument(
        "--followthrough-pct", type=float, default=0.8,
        help="Flat follow-through bar, used when the ADR factor is 0 or no daily history exists",
    )
    parser.add_argument("--expiry", help="Option expiry YYYY-MM-DD (default: main monthly)")
    parser.add_argument("--end", help="Last session to include YYYY-MM-DD (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument(
        "--trend-slope-lookback", type=int, default=TREND_SLOPE_LOOKBACK,
        help=f"Sessions used to measure each MA's slope (default: {TREND_SLOPE_LOOKBACK})",
    )
    parser.add_argument(
        "--trend-flat-pct", type=float, default=TREND_FLAT_PCT,
        help=f"Slope inside +/- this percent counts as flat (default: {TREND_FLAT_PCT})",
    )
    parser.add_argument(
        "--trend-cross-lookback", type=int, default=TREND_CROSS_LOOKBACK,
        help="Sessions in which an MA20/MA50 reclaim or loss still counts as recent",
    )
    parser.add_argument(
        "--trend-thrust-vol", type=float, default=TREND_THRUST_VOL_MULT,
        help="Volume multiple of the 20-day average that qualifies as a thrust",
    )
    parser.add_argument(
        "--skip-options", action="store_true",
        help="Skip the option OI section. Open interest is only available as a live "
             "snapshot, so skip it when reviewing a past --end date",
    )
    parser.add_argument(
        "--regime-symbol", default="QQQ",
        help="Benchmark whose prior close vs daily MA20 gates long entries",
    )
    parser.add_argument("--chart-out", help="Path for the range%% distribution chart")
    return parser.parse_args()


def main():
    args = parse_args()
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    requested_end = date.fromisoformat(args.end) if args.end else date.today()
    end_date = clamp_end_for_sip(requested_end, feed)
    expiry = date.fromisoformat(args.expiry) if args.expiry else main_monthly_expiry()

    max_sessions = max(max(args.weeks) * SESSIONS_PER_WEEK, DAILY_STATS_SESSIONS + 1)
    intraday_start = end_date - timedelta(days=int(max_sessions * 1.9) + 10)
    daily_start = end_date - timedelta(days=DAILY_HISTORY_DAYS)

    client = AlpacaAPIClient(is_paper_trading=True)
    benchmark = fetch_daily_bars(
        [args.regime_symbol], daily_start, end_date, feed=feed
    ).get(args.regime_symbol, pd.DataFrame())
    benchmark_regime = build_regime_state(benchmark, DAILY_MA_PERIOD)
    benchmark_allows_longs = (
        benchmark_regime[max(benchmark_regime)] if benchmark_regime else None
    )
    intraday = fetch_bars(args.tickers, intraday_start, end_date, allow_intraday=True, feed=feed)
    daily = fetch_daily_bars(args.tickers, daily_start, end_date, feed=feed)

    results = {}
    for ticker in args.tickers:
        bars = intraday.get(ticker, pd.DataFrame())
        daily_bars = daily.get(ticker, pd.DataFrame())
        spot, spot_source = reference_price(client, ticker, daily_bars)
        movement = (
            compute_daily_movement_stats(daily_bars, DAILY_STATS_SESSIONS)
            if not daily_bars.empty
            else None
        )
        threshold, threshold_basis = resolve_followthrough_threshold(
            movement, args.followthrough_pct, args.followthrough_adr_factor
        )

        results[ticker] = {
            "spot": spot,
            "spot_source": spot_source,
            "followthrough_pct": threshold,
            "followthrough_basis": threshold_basis,
            "or_direction": {
                week_count: compute_or_direction_stats(
                    bars, args.or_bars, week_count * SESSIONS_PER_WEEK, threshold
                )
                for week_count in sorted(args.weeks)
            } if not bars.empty else {},
            "volume": compute_opening_volume_stats(
                bars, args.or_bars, DAILY_STATS_SESSIONS
            ) if not bars.empty else None,
            "movement": movement,
            "gate": gate_state(daily_bars, benchmark_allows_longs),
            "trend": classify_daily_trend(
                daily_bars, args.trend_slope_lookback, args.trend_flat_pct,
                args.trend_cross_lookback, args.trend_thrust_vol,
            ) if not daily_bars.empty else {},
            "option_skew": {"error": "skipped"} if args.skip_options
            else (
                compute_option_skew(client, ticker, expiry, args.bands, spot)
                if spot else {"error": "no reference price"}
            ),
        }

    clamp_note = f" (clamped from {requested_end} for {args.feed})" if end_date != requested_end else ""
    print(f"\nReport through {end_date}{clamp_note} | feed={args.feed} | option expiry {expiry}")
    longest = max(args.weeks)
    if benchmark_allows_longs is None:
        regime_note = f"{args.regime_symbol} regime unavailable"
    else:
        regime_note = (
            f"{args.regime_symbol} closed"
            f" {'ABOVE' if benchmark_allows_longs else 'BELOW'} its daily MA20"
            f" -> longs {'allowed' if benchmark_allows_longs else 'BLOCKED'}"
        )
    _print_watchlist(build_watchlist(results, longest), longest, regime_note)
    _print_trend_table(results, args.trend_slope_lookback, args.trend_flat_pct)
    _print_or_direction_table(results, sorted(args.weeks))
    if not args.skip_options:
        _print_option_skew_table(results)
    _print_volume_table(results, args.or_bars)
    _print_movement_table(results)

    if args.chart_out:
        written = render_distribution_chart(
            {ticker: stats["movement"] for ticker, stats in results.items()},
            Path(args.chart_out),
            DAILY_STATS_SESSIONS,
        )
        if written:
            print(f"\nchart written to {written}")


if __name__ == "__main__":
    main()
