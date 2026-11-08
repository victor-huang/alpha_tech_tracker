"""Price-derived factor frames from cached daily closes and dollar volume (bars have no open, so a "jump" is a
close-to-close move on heavy volume - usually an earnings or news reaction).

  * jump_held_60d    up-jump in the last 60 trading days, still holding at least half of it
  * jump_faded_60d   up-jump in the last 60 trading days that gave back more than half
  * drop_60d         down-jump (same thresholds) in the last 60 trading days
  * jumps_250d_2plus two or more up-jumps in the last 250 trading days
  * turnaround       1-year low at least 50% under the prior high, and back above the 200-day average after
                     being below it within the last 60 days
  * listed_lt_1y / listed_1_3y   trading-day age since the first cached bar (NaN where the cache start hides it)
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


def jump_days(close: pd.DataFrame, dollar_volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Boolean frames of up- and down-jumps: a big move for the stock on several times its normal volume."""
    daily = close.pct_change(fill_method=None)
    sigma = daily.rolling(60, min_periods=40).std().shift(1)
    share_volume = dollar_volume / close
    volume_ratio = share_volume / share_volume.rolling(50, min_periods=35).mean().shift(1)
    threshold = np.maximum(JUMP_MIN_RETURN, JUMP_MIN_SIGMA * sigma)
    heavy = volume_ratio >= JUMP_MIN_VOLUME_RATIO
    return {"up": (daily >= threshold) & heavy, "down": (daily <= -threshold) & heavy, "daily": daily}


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

    return {
        "jump_held_60d": recent_jump & held,
        "jump_faded_60d": recent_jump & ~held,
        "drop_60d": jumps["down"].astype(float).rolling(JUMP_LOOKBACK, min_periods=1).max() > 0,
        "jumps_250d_2plus": up.astype(float).rolling(250, min_periods=1).sum() >= 2,
        "turnaround": (low_250 / high_before - 1 <= TURNAROUND_DEPTH) & above & was_below,
        "listed_lt_1y": listed_between(c, 0, 250),
        "listed_1_3y": listed_between(c, 250, 750),
    }


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
