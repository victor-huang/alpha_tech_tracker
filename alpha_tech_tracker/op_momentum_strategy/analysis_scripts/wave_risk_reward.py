"""Wave count, consolidation breakouts and risk/reward on 5-min bars.

Feeds regular-hours 5-min bars one at a time into `alpha_tech_tracker.wave.Wave`,
so every metric at a bar only uses data known at that bar's close. Waves never
span the overnight gap: the wave in progress is ended at each session's last bar
and the next session starts a fresh one. Wave history and stats carry across the
whole run, so the lookback window can reach back into earlier sessions.

Lookback   = the last `--lookback-waves` finished waves, or (with `--lookback-bars`)
             the most recent finished waves covering at least that many bars.
Box        = walking back from the latest finished wave, at least `--min-box-waves`
             consecutive waves each no bigger than `--small-wave-ratio` x the median
             lookback wave size, spanning no more than `--max-box-height-ratio` x
             that median. The box runs from their lowest low to their highest high.
Breakout   = first close above the box high (long). Breakdown = first close below
             the box low (short). Each box fires at most once per side. A signal on a
             session's first bar from a box formed in an earlier session is labelled
             a gap breakout/breakdown. A same-direction repeat in the same session is
             suppressed when its box edge sits within `--repeat-overlap-bars` x the
             session's average bar range of the edge that already fired, unless the
             opposite side fired in between.
Long R/R   = entry at the close, stop `--box-stop-ratio` x box height below the box
             high (default 0.2; 1.0 = box low), or the most recent down-wave low
             below price when no box is active. Target at entry + the larger of
             the box height and the median up-wave size of the lookback (median
             up-wave size alone without a box). Short R/R mirrors it. Risk is floored
             at `--min-risk-pct` of price so a close sitting on the stop cannot blow up
             the ratio.
Wave size  = a wave may only end once its range reaches `--min-wave-bar-ranges` x the
             average 5-min bar range % of the trailing `--volatility-window-bars` bars,
             so wave counts are comparable across tickers. `--min-wave-price-change`
             pins a fixed fraction instead.

Writes one interactive HTML chart per ticker (candles, MA 8/20/50/200, wave legs,
consolidation boxes, breakout/breakdown markers, long/short R/R panel) and prints
the latest snapshot.

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward \\
    --tickers NVDA TSLA --days 5
"""

import argparse
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from alpaca.data.enums import DataFeed
from plotly.subplots import make_subplots

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    MARKET_OPEN,
    SESSION_END,
    clamp_end_for_sip,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.wave import Wave

DEFAULT_TICKERS = ["NVDA"]
BAR_INTERVAL = timedelta(minutes=5)
MA_PERIODS = (8, 20, 50, 200)
MA_COLORS = {8: "#e377c2", 20: "#1f77b4", 50: "#ff7f0e", 200: "#9467bd"}
BARS_PER_SESSION = 78
WARMUP_SESSIONS = 5  # MA200 needs ~2.6 sessions; the rest seeds the wave lookback
DEFAULT_DAYS = 5
DEFAULT_LOOKBACK_WAVES = 10
RR_DISPLAY_CAP = 10.0
DEFAULT_BOX_STOP_RATIO = 0.2
SESSION_LENGTH_MS = int(6.5 * 3600 * 1000)
DEFAULT_MIN_WAVE_BAR_RANGES = 2.0
DEFAULT_OUT_DIR = Path("charts") / "wave_rr"


@dataclass
class WaveRiskRewardParams:
    lookback_waves: Optional[int] = DEFAULT_LOOKBACK_WAVES
    lookback_bars: Optional[int] = None
    min_box_waves: int = 3
    small_wave_ratio: float = 1.0
    max_box_height_ratio: float = 1.5
    min_risk_pct: float = 0.001
    box_stop_ratio: float = DEFAULT_BOX_STOP_RATIO
    minimum_wave_price_change: Optional[float] = None
    min_wave_bar_ranges: float = DEFAULT_MIN_WAVE_BAR_RANGES
    volatility_window_bars: int = BARS_PER_SESSION
    repeat_overlap_bars: float = 1.0


def regular_hours(bars):
    """Bars from 09:30 up to (not including) 16:00, renamed to lowercase OHLC columns."""
    times = bars.index.time
    frame = bars[(times >= MARKET_OPEN) & (times < SESSION_END)]
    return frame.rename(columns=str.lower)[["open", "high", "low", "close"]]


def add_moving_averages(bars, periods=MA_PERIODS):
    frame = bars.copy()
    for period in periods:
        frame[f"ma_{period}"] = frame["close"].rolling(period, min_periods=period).mean()
    return frame


def wave_start_price(wave):
    return float(wave.df["open"].iloc[0])


def wave_end_price(wave):
    direction = wave.direction()
    if direction == "up":
        return float(wave.high)
    if direction == "down":
        return float(wave.low)
    return float(wave.df["close"].iloc[-1])


def wave_end_time(wave):
    direction = wave.direction()
    if direction == "up":
        return wave.high_date
    if direction == "down":
        return wave.low_date
    return wave.df.index[-1]


def select_lookback_waves(finished_waves, lookback_waves=None, lookback_bars=None):
    """Most recent finished waves, oldest first, by wave count or by covered bar count."""
    if lookback_bars is None:
        return list(finished_waves[-lookback_waves:]) if lookback_waves else list(finished_waves)

    selected = []
    covered_bars = 0
    for wave in reversed(finished_waves):
        selected.append(wave)
        covered_bars += wave.length()
        if covered_bars >= lookback_bars:
            break
    return selected[::-1]


def find_consolidation(waves, min_box_waves, small_wave_ratio, max_box_height_ratio):
    """Box formed by the trailing run of small waves in `waves` (oldest first), or None."""
    if len(waves) < min_box_waves:
        return None

    median_size = statistics.median(wave.price_range() for wave in waves)
    if median_size <= 0:
        return None

    box_waves = []
    box_low = box_high = None
    for wave in reversed(waves):
        if wave.price_range() > small_wave_ratio * median_size:
            break
        low = wave.low if box_low is None else min(box_low, wave.low)
        high = wave.high if box_high is None else max(box_high, wave.high)
        if high - low > max_box_height_ratio * median_size:
            break
        box_waves.append(wave)
        box_low, box_high = low, high

    if len(box_waves) < min_box_waves:
        return None

    return {
        "start": box_waves[-1].start,
        "end": box_waves[0].df.index[-1],
        "low": float(box_low),
        "high": float(box_high),
        "num_waves": len(box_waves),
        "median_wave_size": float(median_size),
    }


def risk_reward(
    direction, entry, waves, box=None, min_risk_pct=0.001, box_stop_ratio=DEFAULT_BOX_STOP_RATIO
):
    """Stop, target and reward/risk for a long ("up") or short ("down") entry at `entry`.

    With a box the stop sits `box_stop_ratio` x box height back inside the box from the
    breakout edge (below the high for longs, above the low for shorts), and the target is
    the larger of the box height and the median wave size in the trade direction. Returns None when there is no stop on the losing side of `entry` or
    no wave history in the trade direction to size the target from.
    """
    is_long = direction == "up"
    stop = None
    if box:
        box_stop_distance = box_stop_ratio * (box["high"] - box["low"])
        stop = box["high"] - box_stop_distance if is_long else box["low"] + box_stop_distance
    else:
        swing_direction = "down" if is_long else "up"
        for wave in reversed(waves):
            swing = wave.low if is_long else wave.high
            if wave.direction() == swing_direction and (swing < entry if is_long else swing > entry):
                stop = float(swing)
                break

    target_sizes = [wave.price_range() for wave in waves if wave.direction() == direction]
    if stop is None or not target_sizes:
        return None

    risk = entry - stop if is_long else stop - entry
    if risk < 0:
        return None
    risk = max(risk, entry * min_risk_pct)
    reward = statistics.median(target_sizes)
    if box:
        reward = max(reward, box["high"] - box["low"])
    target = entry + reward if is_long else entry - reward

    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "reward": reward,
        "rr": reward / risk,
    }


def _end_wave_at_session_close(wave):
    wave.end = wave.df.index[-1]


def _new_wave(timestamp, bar, minimum_wave_price_change):
    return Wave(timestamp, bar, minimum_wave_price_change=minimum_wave_price_change)


def _repeat_is_suppressed(previous, edge, session, tolerance):
    return previous is not None and previous["session"] == session and abs(edge - previous["edge"]) < tolerance


def analyze_bars(bars, params=None):
    """Replay regular-hours bars (lowercase OHLC + MA columns) through Wave bar by bar.

    Returns the per-bar snapshot frame, every wave, the consolidation boxes seen and
    the breakout/breakdown signals. A box retires once the wave in progress grows past
    the small-wave size, so a trend leg that has not finished yet still ends the box.
    """
    params = params or WaveRiskRewardParams()
    waves = []
    boxes = []
    signals = []
    suppressed_signals = []
    snapshots = []
    current_box = None
    retired_box_keys = set()
    last_fired_by_direction = {}

    bar_range = bars["high"] - bars["low"]
    avg_bar_range_pct = (bar_range / bars["close"]).rolling(
        params.volatility_window_bars, min_periods=1
    ).mean()
    session_avg_bar_range = bar_range.groupby(bars.index.date).transform(
        lambda session: session.expanding().mean()
    )

    for timestamp, row in bars.iterrows():
        bar = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        session = timestamp.date()
        if params.minimum_wave_price_change is not None:
            min_wave_change = params.minimum_wave_price_change
        else:
            min_wave_change = params.min_wave_bar_ranges * float(avg_bar_range_pct[timestamp])

        is_session_open_bar = not waves or session != waves[-1].df.index[-1].date()
        if not waves:
            waves.append(_new_wave(timestamp, bar, min_wave_change))
        elif is_session_open_bar:
            _end_wave_at_session_close(waves[-1])
            new_wave = _new_wave(timestamp, bar, min_wave_change)
            waves[-1].next_wave = new_wave
            waves.append(new_wave)
        else:
            waves[-1].minimum_wave_price_change = min_wave_change
            new_wave = waves[-1].count(timestamp, bar, time_increment=BAR_INTERVAL)
            if new_wave:
                waves.append(new_wave)

        current_wave = waves[-1]
        lookback = select_lookback_waves(waves[:-1], params.lookback_waves, params.lookback_bars)
        box = find_consolidation(
            lookback, params.min_box_waves, params.small_wave_ratio, params.max_box_height_ratio
        )

        box_key = (box["start"], box["end"]) if box else None
        if box_key is None or box_key in retired_box_keys:
            current_box = None
        elif current_box is None or box_key != (current_box["start"], current_box["end"]):
            current_box = dict(box, active_until=timestamp, breakout_at=None, breakdown_at=None)
            boxes.append(current_box)
        else:
            current_box["active_until"] = timestamp
        active_box = current_box

        close = bar["close"]
        long_rr = risk_reward(
            "up", close, lookback, active_box, params.min_risk_pct, params.box_stop_ratio
        )
        short_rr = risk_reward(
            "down", close, lookback, active_box, params.min_risk_pct, params.box_stop_ratio
        )

        direction = None
        if current_box and current_box["breakout_at"] is None and close > current_box["high"]:
            current_box["breakout_at"] = timestamp
            direction = "breakout"
        elif current_box and current_box["breakdown_at"] is None and close < current_box["low"]:
            current_box["breakdown_at"] = timestamp
            direction = "breakdown"

        signal = None
        if direction:
            edge = current_box["high"] if direction == "breakout" else current_box["low"]
            tolerance = params.repeat_overlap_bars * float(session_avg_bar_range[timestamp])
            signal = {
                "time": timestamp,
                "signal": direction,
                "gap": is_session_open_bar and current_box["end"].date() < session,
                "price": close,
                "box_low": current_box["low"],
                "box_high": current_box["high"],
                "risk_reward": long_rr if direction == "breakout" else short_rr,
            }
            previous = last_fired_by_direction.get(direction)
            if _repeat_is_suppressed(previous, edge, session, tolerance):
                suppressed_signals.append(signal)
                signal = None
            else:
                signals.append(signal)
                last_fired_by_direction[direction] = {"edge": edge, "session": session}
                last_fired_by_direction.pop("breakdown" if direction == "breakout" else "breakout", None)

        if active_box and current_wave.price_range() > params.small_wave_ratio * active_box["median_wave_size"]:
            retired_box_keys.add(box_key)
            current_box = None

        snapshot = {
            "time": timestamp,
            "close": close,
            "wave_number": len(waves),
            "lookback_waves": len(lookback),
            "lookback_up_waves": sum(1 for wave in lookback if wave.direction() == "up"),
            "lookback_down_waves": sum(1 for wave in lookback if wave.direction() == "down"),
            "current_wave_direction": current_wave.direction(),
            "current_wave_length": current_wave.length(),
            "box_low": active_box["low"] if active_box else None,
            "box_high": active_box["high"] if active_box else None,
            "signal": _signal_label(signal) if signal else None,
            "min_wave_price_change": min_wave_change,
        }
        for period in MA_PERIODS:
            column = f"ma_{period}"
            if column in row:
                snapshot[column] = None if pd.isna(row[column]) else float(row[column])
        for side, result in (("long", long_rr), ("short", short_rr)):
            for field in ("stop", "target", "rr"):
                snapshot[f"{side}_{field}"] = result[field] if result else None
        snapshots.append(snapshot)

    if waves:
        snapshot_frame = pd.DataFrame(snapshots).set_index("time")
    else:
        snapshot_frame = pd.DataFrame()
    return {
        "snapshots": snapshot_frame,
        "waves": waves,
        "boxes": boxes,
        "signals": signals,
        "suppressed_signals": suppressed_signals,
    }


def _signal_label(signal):
    return f"gap {signal['signal']}" if signal["gap"] else signal["signal"]


def _fmt(value, spec=".2f"):
    return "n/a" if value is None or pd.isna(value) else format(value, spec)


def _bar_hover_text(snapshot):
    ma_text = " ".join(
        f"MA{period} {_fmt(snapshot.get(f'ma_{period}'))}" for period in MA_PERIODS
    )
    box_text = (
        f"box {_fmt(snapshot['box_low'])}-{_fmt(snapshot['box_high'])}"
        if snapshot["box_low"] is not None and not pd.isna(snapshot["box_low"]) else "no box"
    )
    return (
        f"close {_fmt(snapshot['close'])}<br>{ma_text}<br>"
        f"wave #{snapshot['wave_number']} {snapshot['current_wave_direction']}"
        f" ({snapshot['current_wave_length']} bars)<br>"
        f"lookback {snapshot['lookback_waves']} waves:"
        f" {snapshot['lookback_up_waves']} up / {snapshot['lookback_down_waves']} down<br>"
        f"{box_text}<br>"
        f"long R/R {_fmt(snapshot['long_rr'])} (stop {_fmt(snapshot['long_stop'])},"
        f" tgt {_fmt(snapshot['long_target'])})<br>"
        f"short R/R {_fmt(snapshot['short_rr'])} (stop {_fmt(snapshot['short_stop'])},"
        f" tgt {_fmt(snapshot['short_target'])})"
    )


def _chart_time(timestamp):
    """ET wall-clock time without tz, so plotly's hour rangebreaks line up with market hours."""
    return timestamp.tz_localize(None) if timestamp.tzinfo else timestamp


def _missing_session_opens(index):
    """09:30 of each weekday with no bars (holidays) between the first and last bar.

    Paired with a session-length `dvalue` so the holiday break covers only 09:30-16:00;
    a full-day break would overlap the overnight hour break, which plotly renders wrongly.
    """
    sessions = set(index.date)
    weekdays = pd.bdate_range(index[0].date(), index[-1].date())
    return [f"{day:%Y-%m-%d} 09:30" for day in weekdays if day.date() not in sessions]


def _wave_leg_trace(waves, direction, color):
    xs, ys, texts = [], [], []
    for wave in waves:
        if wave.direction() != direction:
            continue
        start, end = wave_start_price(wave), wave_end_price(wave)
        text = (
            f"{direction} wave {wave.start:%m-%d %H:%M} -> {wave_end_time(wave):%H:%M}<br>"
            f"{start:.2f} -> {end:.2f} ({(end / start - 1) * 100:+.2f}%, {wave.length()} bars)"
        )
        xs += [_chart_time(wave.start), _chart_time(wave_end_time(wave)), None]
        ys += [start, end, None]
        texts += [text, text, None]
    return go.Scatter(
        x=xs, y=ys, text=texts, hoverinfo="text", mode="lines+markers",
        line=dict(color=color, width=2), marker=dict(size=4), name=f"{direction} waves",
    )


def build_chart(ticker, bars, result, display_start):
    shown_bars = bars[bars.index >= display_start]
    snapshots = result["snapshots"].loc[shown_bars.index]
    waves = [wave for wave in result["waves"] if wave.start >= display_start]
    boxes = [box for box in result["boxes"] if box["active_until"] >= display_start]
    signals = [signal for signal in result["signals"] if signal["time"] >= display_start]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25]
    )
    times = shown_bars.index.tz_localize(None)
    fig.add_trace(go.Candlestick(
        x=times, open=shown_bars["open"], high=shown_bars["high"],
        low=shown_bars["low"], close=shown_bars["close"], name=ticker, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=times, y=snapshots["close"], mode="markers", marker=dict(opacity=0),
        text=[_bar_hover_text(row) for _, row in snapshots.iterrows()], hoverinfo="text",
        name="bar stats", showlegend=False,
    ), row=1, col=1)
    for period in MA_PERIODS:
        fig.add_trace(go.Scatter(
            x=times, y=shown_bars[f"ma_{period}"], mode="lines",
            line=dict(color=MA_COLORS[period], width=1), name=f"MA{period}", hoverinfo="skip",
        ), row=1, col=1)
    fig.add_trace(_wave_leg_trace(waves, "up", "#2ca02c"), row=1, col=1)
    fig.add_trace(_wave_leg_trace(waves, "down", "#d62728"), row=1, col=1)

    for box in boxes:
        fig.add_shape(
            type="rect", xref="x", yref="y", x0=_chart_time(max(box["start"], display_start)),
            x1=_chart_time(box["active_until"]), y0=box["low"], y1=box["high"],
            fillcolor="rgba(31, 119, 180, 0.15)", line=dict(color="rgba(31, 119, 180, 0.6)", width=1),
        )

    marker_styles = (
        ("breakout", "triangle-up", "#2ca02c"),
        ("breakdown", "triangle-down", "#d62728"),
        ("gap breakout", "triangle-up-open", "#2ca02c"),
        ("gap breakdown", "triangle-down-open", "#d62728"),
    )
    for kind, symbol, color in marker_styles:
        picked = [signal for signal in signals if _signal_label(signal) == kind]
        texts = []
        for signal in picked:
            rr = signal["risk_reward"]
            rr_text = (
                f"R/R {rr['rr']:.2f}  stop {rr['stop']:.2f}  target {rr['target']:.2f}" if rr else "R/R n/a"
            )
            texts.append(
                f"{kind} {signal['time']:%m-%d %H:%M} @ {signal['price']:.2f}<br>"
                f"box {signal['box_low']:.2f}-{signal['box_high']:.2f}<br>{rr_text}"
            )
        fig.add_trace(go.Scatter(
            x=[_chart_time(signal["time"]) for signal in picked], y=[signal["price"] for signal in picked],
            mode="markers", marker=dict(symbol=symbol, size=13, color=color, line=dict(width=2, color=color)),
            text=texts, hoverinfo="text", name=kind,
        ), row=1, col=1)

    for side, color in (("long", "#2ca02c"), ("short", "#d62728")):
        fig.add_trace(go.Scatter(
            x=times, y=snapshots[f"{side}_rr"].clip(upper=RR_DISPLAY_CAP), mode="lines",
            line=dict(color=color, width=1), name=f"{side} R/R",
        ), row=2, col=1)
    fig.add_shape(
        type="line", xref="paper", yref="y2", x0=0, x1=1, y0=1, y1=1,
        line=dict(color="grey", width=1, dash="dot"),
    )

    rangebreaks = [
        dict(bounds=["sat", "mon"]),
        dict(bounds=[16, 9.5], pattern="hour"),
        dict(values=_missing_session_opens(shown_bars.index), dvalue=SESSION_LENGTH_MS),
    ]
    fig.update_xaxes(rangebreaks=rangebreaks, rangeslider_visible=False)
    fig.update_yaxes(title_text="price", row=1, col=1)
    fig.update_yaxes(title_text=f"R/R (cap {RR_DISPLAY_CAP:g})", row=2, col=1)
    fig.update_layout(
        title=f"{ticker} waves, consolidation and risk/reward"
              f" ({shown_bars.index[0]:%Y-%m-%d} .. {shown_bars.index[-1]:%Y-%m-%d})",
        height=900, hovermode="closest",
    )
    return fig


def _print_ticker_summary(ticker, result, display_start, chart_path):
    snapshots = result["snapshots"]
    shown_waves = [wave for wave in result["waves"] if wave.df.index[-1] >= display_start]
    shown_signals = [signal for signal in result["signals"] if signal["time"] >= display_start]
    suppressed = [signal for signal in result["suppressed_signals"] if signal["time"] >= display_start]
    last = snapshots.iloc[-1]

    print("\n" + "=" * 100)
    print(
        f"{ticker}   {len(shown_waves)} waves"
        f" ({sum(1 for w in shown_waves if w.direction() == 'up')} up /"
        f" {sum(1 for w in shown_waves if w.direction() == 'down')} down)"
        f"   {sum(1 for s in shown_signals if s['signal'] == 'breakout')} breakouts"
        f"   {sum(1 for s in shown_signals if s['signal'] == 'breakdown')} breakdowns"
        f"   ({sum(1 for s in shown_signals if s['gap'])} gap, {len(suppressed)} repeats suppressed)"
    )
    print("=" * 100)
    for signal in shown_signals:
        rr = signal["risk_reward"]
        rr_text = f"R/R {rr['rr']:5.2f}  stop {rr['stop']:.2f}  target {rr['target']:.2f}" if rr else "R/R n/a"
        print(
            f"  {signal['time']:%Y-%m-%d %H:%M}  {_signal_label(signal):13}  @ {signal['price']:.2f}"
            f"  box {signal['box_low']:.2f}-{signal['box_high']:.2f}  {rr_text}"
        )
    print(f"latest {snapshots.index[-1]:%Y-%m-%d %H:%M}")
    print("  " + _bar_hover_text(last).replace("<br>", "\n  "))
    print(f"chart: {chart_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"Trailing sessions to display (default: {DEFAULT_DAYS})",
    )
    parser.add_argument("--end", help="Last session YYYY-MM-DD (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    lookback = parser.add_mutually_exclusive_group()
    lookback.add_argument(
        "--lookback-waves", type=int, default=DEFAULT_LOOKBACK_WAVES,
        help=f"Finished waves in the stats window (default: {DEFAULT_LOOKBACK_WAVES})",
    )
    lookback.add_argument(
        "--lookback-bars", type=int,
        help="Use the most recent finished waves covering at least this many bars instead",
    )
    parser.add_argument("--min-box-waves", type=int, default=3)
    parser.add_argument(
        "--small-wave-ratio", type=float, default=1.0,
        help="Box waves must be <= this x the median lookback wave size (default: 1.0)",
    )
    parser.add_argument(
        "--max-box-height-ratio", type=float, default=1.5,
        help="Box height must be <= this x the median lookback wave size (default: 1.5)",
    )
    parser.add_argument(
        "--box-stop-ratio", type=float, default=DEFAULT_BOX_STOP_RATIO,
        help="Stop distance back inside the box from the breakout edge, as a fraction of"
             f" box height (default: {DEFAULT_BOX_STOP_RATIO:g}; 1.0 = opposite box edge)",
    )
    parser.add_argument(
        "--min-risk-pct", type=float, default=0.001,
        help="Risk floor as a fraction of price (default: 0.001 = 0.1%%)",
    )
    parser.add_argument(
        "--min-wave-bar-ranges", type=float, default=DEFAULT_MIN_WAVE_BAR_RANGES,
        help="Wave minimum size before it may end, in average 5-min bar ranges"
             f" (default: {DEFAULT_MIN_WAVE_BAR_RANGES:g})",
    )
    parser.add_argument(
        "--volatility-window-bars", type=int, default=BARS_PER_SESSION,
        help=f"Trailing bars for the average bar range (default: {BARS_PER_SESSION})",
    )
    parser.add_argument(
        "--min-wave-price-change", type=float,
        help="Fixed wave minimum (high-low)/low, overriding --min-wave-bar-ranges",
    )
    parser.add_argument(
        "--repeat-overlap-bars", type=float, default=1.0,
        help="Suppress a same-direction repeat whose box edge is within this many session"
             " average bar ranges of the edge that fired (default: 1.0)",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


def main():
    args = parse_args()
    params = WaveRiskRewardParams(
        lookback_waves=None if args.lookback_bars else args.lookback_waves,
        lookback_bars=args.lookback_bars,
        min_box_waves=args.min_box_waves,
        small_wave_ratio=args.small_wave_ratio,
        max_box_height_ratio=args.max_box_height_ratio,
        min_risk_pct=args.min_risk_pct,
        box_stop_ratio=args.box_stop_ratio,
        minimum_wave_price_change=args.min_wave_price_change,
        min_wave_bar_ranges=args.min_wave_bar_ranges,
        volatility_window_bars=args.volatility_window_bars,
        repeat_overlap_bars=args.repeat_overlap_bars,
    )
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    requested_end = date.fromisoformat(args.end) if args.end else date.today()
    end_date = clamp_end_for_sip(requested_end, feed)
    start_date = end_date - timedelta(days=int((args.days + WARMUP_SESSIONS) * 1.6) + 5)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_bars = fetch_bars(args.tickers, start_date, end_date, allow_intraday=True, feed=feed)

    for ticker in args.tickers:
        raw_bars = all_bars.get(ticker)
        if raw_bars is None or raw_bars.empty:
            print(f"{ticker}: no bars between {start_date} and {end_date}")
            continue
        bars = add_moving_averages(regular_hours(raw_bars))
        sessions = sorted(set(bars.index.date))
        display_start = bars.index[bars.index.date >= sessions[-min(args.days, len(sessions))]][0]

        result = analyze_bars(bars, params)
        chart_path = out_dir / f"{ticker}_{display_start:%Y-%m-%d}_{bars.index[-1]:%Y-%m-%d}.html"
        build_chart(ticker, bars, result, display_start).write_html(str(chart_path))
        _print_ticker_summary(ticker, result, display_start, chart_path)


if __name__ == "__main__":
    main()
