"""Price-derived factor frames from cached daily closes and dollar volume (bars have no open, so a "jump" is a
close-to-close move on heavy volume - usually an earnings or news reaction).

  * jump_held_60d    up-jump in the last 60 trading days, still holding at least half of it
  * jump_faded_60d   up-jump in the last 60 trading days that gave back more than half
  * drop_60d         down-jump (same thresholds) in the last 60 trading days
  * jumps_250d_2plus two or more up-jumps in the last 250 trading days
  * turnaround       1-year low at least 50% under the prior high, and back above the 200-day average after
                     being below it within the last 60 days
  * listed_lt_1y / listed_1_3y   trading-day age since the first cached bar (NaN where the cache start hides it)
  * gap_10d          an up-jump closing above the 20/50/200-day averages in the last 10 trading days
  * high_breakout_10d  a fresh 52-week-high close (none in the prior 60 days) above the 20/50/200-day averages in
                     the last 10 trading days
  * breakout_10d     either event in the last 10 trading days (since the previous checkpoint)
  * breakout_hold_60d  either event in the last 60 trading days, still closing above the 50-day average
  * breakout_strength_10d / _60d   strongest event in the window, as event-day return x volume ratio (the 60-day
                     one only while the close is above the 50-day average); NaN without an event
  * gap_hold_60d / high_hold_60d, gap_strength_*, high_base_*   the same split by event type; a 52-week-high
                     breakout is scored by its base length (trading days since the previous 52-week-high close)
  * ma_rising_8_20_50 / ma_rising_8_20_50_200   every listed moving average above its value MA_SLOPE_DAYS ago
  * base_building    8/20/50-day averages all rising and the close above the 50-day, while the 50-day is still under
                     the 200-day - a rebound building a base below the long-term average
"""
from typing import Dict

import numpy as np
import pandas as pd

JUMP_MIN_RETURN = 0.08
JUMP_MIN_SIGMA = 3.0
JUMP_MIN_VOLUME_RATIO = 3.0
JUMP_LOOKBACK = 60
JUMP_HELD_SHARE = 0.5
TURNAROUND_DEPTH = -0.5
TURNAROUND_RECLAIM_WINDOW = 60
AGE_CENSOR_BUFFER = 5
BREAKOUT_FRESH_DAYS = 10
BREAKOUT_HOLD_DAYS = 60
FRESH_HIGH_GAP_DAYS = 20
MA_SLOPE_DAYS = 5


def jump_days(close: pd.DataFrame, dollar_volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Boolean frames of up- and down-jumps: a big move for the stock on several times its normal volume."""
    daily = close.pct_change(fill_method=None)
    sigma = daily.rolling(60, min_periods=40).std().shift(1)
    share_volume = dollar_volume / close
    volume_ratio = share_volume / share_volume.rolling(50, min_periods=35).mean().shift(1)
    threshold = np.maximum(JUMP_MIN_RETURN, JUMP_MIN_SIGMA * sigma)
    heavy = volume_ratio >= JUMP_MIN_VOLUME_RATIO
    return {"up": (daily >= threshold) & heavy, "down": (daily <= -threshold) & heavy, "daily": daily,
            "volume_ratio": volume_ratio}


def factor_frames(close: pd.DataFrame, dollar_volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Daily (day x symbol) boolean factor frames; each uses only data up to that day."""
    c = close.ffill(limit=5)
    jumps = jump_days(c, dollar_volume)
    up = jumps["up"]
    pre_close = c.shift(1).where(up).ffill(limit=JUMP_LOOKBACK)
    jump_ret = jumps["daily"].where(up).ffill(limit=JUMP_LOOKBACK)
    recent_jump = pre_close.notna()
    held = c >= pre_close * (1 + JUMP_HELD_SHARE * jump_ret)

    ma200 = c.rolling(200, min_periods=160).mean()
    low_250 = c.rolling(250, min_periods=200).min()
    high_before = c.rolling(375, min_periods=250).max()
    above = c > ma200
    was_below = (~above & ma200.notna()).astype(float).rolling(TURNAROUND_RECLAIM_WINDOW, min_periods=1).max() > 0

    events = breakout_events(c, up)
    either = events["gap"] | events["high_breakout"]
    strength = (jumps["daily"] * jumps["volume_ratio"]).where(either)
    gap_strength = (jumps["daily"] * jumps["volume_ratio"]).where(events["gap"])
    high_base = events["base_days"].where(events["high_breakout"])
    above_ma50 = c > events["ma50"]
    return {
        "jump_held_60d": recent_jump & held,
        "jump_faded_60d": recent_jump & ~held,
        "drop_60d": jumps["down"].astype(float).rolling(JUMP_LOOKBACK, min_periods=1).max() > 0,
        "jumps_250d_2plus": up.astype(float).rolling(250, min_periods=1).sum() >= 2,
        "turnaround": (low_250 / high_before - 1 <= TURNAROUND_DEPTH) & above & was_below,
        "listed_lt_1y": listed_between(c, 0, 250),
        "listed_1_3y": listed_between(c, 250, 750),
        "gap_10d": _within(events["gap"], BREAKOUT_FRESH_DAYS),
        "high_breakout_10d": _within(events["high_breakout"], BREAKOUT_FRESH_DAYS),
        "breakout_10d": _within(either, BREAKOUT_FRESH_DAYS),
        "breakout_hold_60d": _within(either, BREAKOUT_HOLD_DAYS) & (c > events["ma50"]),
        "breakout_strength_10d": strength.rolling(BREAKOUT_FRESH_DAYS, min_periods=1).max(),
        "breakout_strength_60d": strength.rolling(BREAKOUT_HOLD_DAYS, min_periods=1).max().where(
            c > events["ma50"]),
        "gap_hold_60d": _within(events["gap"], BREAKOUT_HOLD_DAYS) & above_ma50,
        "high_hold_60d": _within(events["high_breakout"], BREAKOUT_HOLD_DAYS) & above_ma50,
        "gap_strength_10d": gap_strength.rolling(BREAKOUT_FRESH_DAYS, min_periods=1).max(),
        "gap_strength_60d": gap_strength.rolling(BREAKOUT_HOLD_DAYS, min_periods=1).max().where(above_ma50),
        "high_base_10d": high_base.rolling(BREAKOUT_FRESH_DAYS, min_periods=1).max(),
        "high_base_60d": high_base.rolling(BREAKOUT_HOLD_DAYS, min_periods=1).max().where(above_ma50),
        "ma_rising_8_20_50": ma_rising(c, (8, 20, 50)),
        "ma_rising_8_20_50_200": ma_rising(c, (8, 20, 50, 200)),
        "base_building": ma_rising(c, (8, 20, 50)) & (c > events["ma50"]) & (events["ma50"] < ma200),
    }


def ma_rising(close: pd.DataFrame, windows) -> pd.DataFrame:
    """True where every moving average in `windows` is above its value MA_SLOPE_DAYS earlier."""
    rising = pd.DataFrame(True, index=close.index, columns=close.columns)
    for w in windows:
        ma = close.rolling(w, min_periods=int(w * 0.8)).mean()
        rising &= ma > ma.shift(MA_SLOPE_DAYS)
    return rising


def _within(events: pd.DataFrame, days: int) -> pd.DataFrame:
    return events.astype(float).rolling(days, min_periods=1).max() > 0


def breakout_events(close: pd.DataFrame, up_jump: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Event days: an up-jump that closes above the 20/50/200-day averages, and the first 52-week-high close after
    FRESH_HIGH_GAP_DAYS without one, also above all three averages."""
    ma20 = close.rolling(20, min_periods=15).mean()
    ma50 = close.rolling(50, min_periods=40).mean()
    ma200 = close.rolling(200, min_periods=160).mean()
    above_all = (close > ma20) & (close > ma50) & (close > ma200)
    at_high = close >= close.rolling(250, min_periods=200).max()
    recent_high = at_high.astype(float).shift(1).rolling(FRESH_HIGH_GAP_DAYS, min_periods=1).max()
    return {"gap": up_jump & above_all, "high_breakout": at_high & (recent_high == 0) & above_all, "ma50": ma50,
            "base_days": days_since_previous(at_high)}


def days_since_previous(flags: pd.DataFrame, cap: int = 250) -> pd.DataFrame:
    """Trading days since the flag was last set before each day (capped; `cap` when never set)."""
    position = np.arange(len(flags), dtype=float)[:, None]
    last = pd.DataFrame(np.where(flags.shift(1, fill_value=False).values, position - 1, np.nan),
                        index=flags.index, columns=flags.columns).ffill()
    since = pd.DataFrame(position - last.values, index=flags.index, columns=flags.columns)
    return since.fillna(cap).clip(upper=cap)


def listed_between(close: pd.DataFrame, min_age: int, max_age: int) -> pd.DataFrame:
    """1.0 where the stock's trading-day age is in [min_age, max_age), 0.0 where it is not, NaN where unknown.

    Stocks already trading when the cache starts have an age of at least the days since then; their bucket is
    unknown until that lower bound reaches max_age.
    """
    position = np.arange(len(close))[:, None]
    first_pos = close.notna().values.argmax(axis=0)[None, :]
    age = position - first_pos
    in_range = (age >= min_age) & (age < max_age)
    censored = np.broadcast_to(first_pos <= AGE_CENSOR_BUFFER, age.shape)
    unknown = censored & (age < max_age)
    values = np.where(unknown, np.nan, in_range.astype(float))
    return pd.DataFrame(values, index=close.index, columns=close.columns)


def attach_factors(panel: pd.DataFrame, frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    p = panel.copy()
    checkpoints = sorted(p["checkpoint"].unique())
    for name, frame in frames.items():
        at = frame.reindex(index=checkpoints).stack().rename(name)
        at.index.names = ["checkpoint", "symbol"]
        p = p.merge(at.reset_index(), on=["checkpoint", "symbol"], how="left")
        p[name] = p[name].astype(float)
    return p
