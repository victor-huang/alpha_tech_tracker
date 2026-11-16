"""Market cash rule (default since 2026-11-16): when to hold cash instead of the Large book / switch alternative.

Checked on every QQQ daily close and acted on the next session:
- Distribution day: QQQ closes up DIST_MAX_RETURN or less (flat or down) on volume above its prior 20-day average and
  above the day before.
- Exit: DIST_NEEDED+ distribution days in the last DIST_WINDOW sessions (counted only since the last re-entry) with QQQ
  closing below both its 50- and 200-day averages.
- Re-entry: a close back above the 50-day.
- Re-exit: after an exit, any later close below the 50-day goes back to cash, no new distribution days needed.
- Minimum stay: no re-exit or re-entry within MIN_STAY sessions of the previous switch (the first exit is not delayed).
- Disarm: once QQQ closes above both averages with the 50-day above the 200-day, re-exits stop until the next exit.
While in cash, hold T-bills / a money-market fund (shorting QQQ tested worse).

Backtest 2005-2026 (docs/qqq_gap_before_2018.md on the historical-data branch): the doubler switch with QQQ as its
alternative earns 21.8% a year with a -23% worst drawdown under this rule, against 20.0% / -26% under the previous rule
(cash while QQQ is below both its 50- and 200-day averages, `ma_rule`) and 20.6% / -55% with no cash rule.
"""
from typing import Tuple

import numpy as np
import pandas as pd

INDEX = "QQQ"
DIST_MAX_RETURN = 0.002
DIST_WINDOW = 25
DIST_NEEDED = 6
VOLUME_AVG_DAYS = 20
MIN_STAY = 10
FAST_MA, SLOW_MA = 50, 200


def distribution_days(close: pd.Series, volume: pd.Series) -> pd.Series:
    """True on a flat-or-down close with volume above the prior 20-day average and above the day before."""
    avg_volume = volume.rolling(VOLUME_AVG_DAYS).mean().shift(1)
    return ((close.pct_change() <= DIST_MAX_RETURN) & (volume > avg_volume) & (volume > volume.shift(1))).fillna(False)


def ma_rule(close: pd.Series) -> pd.Series:
    """The previous rule: in cash while QQQ closes below both its 50- and 200-day averages."""
    return (close < close.rolling(FAST_MA).mean()) & (close < close.rolling(SLOW_MA).mean())


def cash_rule(close: pd.Series, volume: pd.Series) -> pd.DataFrame:
    """Daily state of the rule: in_cash, armed (re-exits active), dist_count, the averages and the day's event
    ("exit", "re-exit", "re-enter" or "")."""
    ma50, ma200 = close.rolling(FAST_MA).mean(), close.rolling(SLOW_MA).mean()
    c, m50, m200 = close.values, ma50.values, ma200.values
    uptrend = (c > m50) & (c > m200) & (m50 > m200)
    is_dist = distribution_days(close, volume).astype(int).values
    n = len(c)
    in_cash_out, armed_out, count_out = np.zeros(n, bool), np.zeros(n, bool), np.zeros(n, int)
    events = [""] * n
    in_cash = armed = False
    last_entry, last_switch = 0, -10 ** 9
    for i in range(n):
        count = int(is_dist[max(i - DIST_WINDOW + 1, last_entry):i + 1].sum())
        can_switch = i - last_switch >= MIN_STAY
        if not in_cash:
            if armed and uptrend[i]:
                armed = False
            if count >= DIST_NEEDED and c[i] < m50[i] and c[i] < m200[i]:
                in_cash, armed, last_switch, events[i] = True, True, i, "exit"
            elif armed and c[i] < m50[i] and can_switch:
                in_cash, last_switch, events[i] = True, i, "re-exit"
        elif c[i] > m50[i] and can_switch:
            in_cash, last_entry, last_switch, events[i] = False, i + 1, i, "re-enter"
        in_cash_out[i], armed_out[i], count_out[i] = in_cash, armed, count
    return pd.DataFrame({"close": close, "ma50": ma50, "ma200": ma200, "dist_count": count_out,
                         "in_cash": in_cash_out, "armed": armed_out, "event": events}, index=close.index)


def last_event(state: pd.DataFrame) -> Tuple[pd.Timestamp, str]:
    """Day and kind of the latest exit / re-exit / re-entry, or (None, "") if there was none."""
    ev = state[state["event"] != ""]
    return (ev.index[-1], ev["event"].iloc[-1]) if len(ev) else (None, "")


def status_line(state: pd.DataFrame) -> str:
    """One-line summary of the rule on the last close, with the previous 50/200-day rule for comparison."""
    last = state.iloc[-1]
    day, kind = last_event(state)
    since = f" since {kind} on {day.date()}" if day is not None else ""
    side = "CASH" if last["in_cash"] else "INVESTED"
    old = "cash" if last["close"] < last["ma50"] and last["close"] < last["ma200"] else "invested"
    return (f"market cash rule (default): {side}{since} | {INDEX} {last['close']:.2f}, 50d {last['ma50']:.2f}, "
            f"200d {last['ma200']:.2f}, {last['dist_count']} distribution days in {DIST_WINDOW}, "
            f"re-exit {'armed' if last['armed'] else 'off'} | previous 50/200-day rule: {old}")
