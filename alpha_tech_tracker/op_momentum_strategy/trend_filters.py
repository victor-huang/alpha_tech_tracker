"""Opt-in trend filters for the wave setup monitor, decided on the daily bars before a session (ticker-tuning doc,
Finding 40). Off by default.

  overnight    overnight holds only while QQQ is above its 200-day MA and up over the last 10 sessions. Every night
               vs this rule, sum of trade %: 2020 +303 / +282, 2022 -579 / -56, 2025 +365 / +384, 2026 (to Nov 6)
               +92 / +57; four years +181 / +667. The MA200 keeps the holds out of a bear year (2022: 77 of
               2,707 nights); the 10-session return trims weak stretches. A QQQ MA50 version was +515.
  pullback     pullback long / pullback long C1 only while the ticker makes higher highs: its 10-session high
               above the 10 sessions before. Inconsistent: kept trades beat dropped ones in 2020 and 2022, not in
               2025 or out of sample in 2026, and kept trades made only +0.03 to +0.08% each.

A drive-short filter (QQQ below its 10-day EMA and the ticker down over 20 sessions) looked good on the six windows
it was picked on and failed in all four full years; it was removed.

Each frame function returns one row per daily close; a session uses the row of the close before it.
"""

import pandas as pd

TREND_FILTERS = ("pullback", "overnight")
PULLBACK_SETUPS = ("pullback long", "pullback long C1")
MARKET_TICKER = "QQQ"
HIGH_WINDOW = 10
MARKET_MA = 200
MARKET_RETURN_SESSIONS = 10


def market_trend(daily):
    """QQQ daily bars (close column, ascending dates) -> the overnight condition per close."""
    close = daily["close"].astype(float)
    ma = close.rolling(MARKET_MA, min_periods=MARKET_MA).mean()
    before = close.shift(MARKET_RETURN_SESSIONS)
    return pd.DataFrame({
        "close": close, "ma": ma, "return": close / before - 1,
        "overnight_ok": (close > ma) & (close > before) & ma.notna() & before.notna(),
    }, index=daily.index)


def ticker_trend(daily):
    """A ticker's daily bars (high column) -> its higher-high condition per close."""
    high = daily["high"].astype(float)
    recent = high.rolling(HIGH_WINDOW, min_periods=HIGH_WINDOW).max()
    prior = recent.shift(HIGH_WINDOW)
    return pd.DataFrame({"high": recent, "prior_high": prior, "pullback_ok": (recent > prior) & prior.notna()},
                        index=daily.index)


def overnight_rule(market):
    """(allowed, reason) for the overnight holds from QQQ's last market_trend row."""
    if market is None or pd.isna(market["ma"]) or pd.isna(market["return"]):
        return False, f"{MARKET_TICKER} has too little daily history"
    trend = (f"{MARKET_TICKER} {market['close']:.2f}, {'above' if market['close'] > market['ma'] else 'below'} its "
             f"{MARKET_MA}-day MA {market['ma']:.2f}, {market['return'] * 100:+.1f}% over {MARKET_RETURN_SESSIONS} sessions")
    return bool(market["overnight_ok"]), trend


def pullback_rule(ticker):
    """(allowed, reason) for a ticker's pullback longs from its last ticker_trend row."""
    if ticker is None or pd.isna(ticker["prior_high"]):
        return False, "too little daily history"
    return bool(ticker["pullback_ok"]), (f"{HIGH_WINDOW}-session high {ticker['high']:.2f} vs "
                                         f"{ticker['prior_high']:.2f} before")


def session_flags(trend, sessions, column):
    """{session: allowed} from the row of the close before each session (False without one)."""
    flags = trend[column].astype(bool)
    out = {}
    for session in sessions:
        before = flags[flags.index < session]
        out[session] = bool(before.iloc[-1]) if len(before) else False
    return out
