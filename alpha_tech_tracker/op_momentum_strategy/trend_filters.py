"""Opt-in trend filters for the wave setup monitor, decided on the daily bars before a session (ticker-tuning doc,
Finding 40). Chosen from 15 daily trend measures on six 2025-2026 up / down windows of the prod tickers; in-sample,
so they stay off until checked on other years.

  pullback     pullback long / pullback long C1 only while the ticker makes higher highs: its 10-session high
               above the 10 sessions before (+0.58% / +1.01% a trade kept vs -0.28% / -0.36% dropped)
  overnight    overnight holds only while QQQ is above its 50-day MA and up over the last 10 sessions
               (+0.21% a trade vs -0.06% for every night; the QQQ MA50 alone +0.03%)
  drive-short  drive shorts only while QQQ is below its 10-day EMA and the ticker is down over the last 20 sessions
               (+0.21% a trade vs -0.06%); studied without the QQQ MA50 short gate (`--short-gate always`)

Each frame function returns one row per daily close; a session uses the row of the close before it.
"""

import pandas as pd

TREND_FILTERS = ("pullback", "overnight", "drive-short")
PULLBACK_SETUPS = ("pullback long", "pullback long C1")
MARKET_TICKER = "QQQ"
HIGH_WINDOW = 10
MARKET_MA = 50
MARKET_RETURN_SESSIONS = 10
MARKET_EMA = 10
TICKER_RETURN_SESSIONS = 20


def market_trend(daily):
    """QQQ daily bars (close column, ascending dates) -> the overnight and drive-short market conditions per close."""
    close = daily["close"].astype(float)
    ma = close.rolling(MARKET_MA, min_periods=MARKET_MA).mean()
    ema = close.ewm(span=MARKET_EMA, adjust=False, min_periods=MARKET_EMA).mean()
    before = close.shift(MARKET_RETURN_SESSIONS)
    return pd.DataFrame({
        "close": close, "ma": ma, "ema": ema, "return": close / before - 1,
        "overnight_ok": (close > ma) & (close > before) & ma.notna() & before.notna(),
        "short_ok": (close < ema) & ema.notna(),
    }, index=daily.index)


def ticker_trend(daily):
    """A ticker's daily bars (high, close) -> its higher-high and 20-session-down conditions per close."""
    high, close = daily["high"].astype(float), daily["close"].astype(float)
    recent = high.rolling(HIGH_WINDOW, min_periods=HIGH_WINDOW).max()
    prior = recent.shift(HIGH_WINDOW)
    before = close.shift(TICKER_RETURN_SESSIONS)
    return pd.DataFrame({
        "high": recent, "prior_high": prior, "return": close / before - 1,
        "pullback_ok": (recent > prior) & prior.notna(),
        "short_ok": (close < before) & before.notna(),
    }, index=daily.index)


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


def drive_short_rule(market, ticker):
    """(allowed, reason) for a ticker's drive shorts from QQQ's and the ticker's last rows."""
    if market is None or pd.isna(market["ema"]):
        return False, f"{MARKET_TICKER} has too little daily history"
    if ticker is None or pd.isna(ticker["return"]):
        return False, "too little daily history"
    if not market["short_ok"]:
        return False, f"{MARKET_TICKER} {market['close']:.2f} above its {MARKET_EMA}-day EMA {market['ema']:.2f}"
    if not ticker["short_ok"]:
        return False, f"not down over {TICKER_RETURN_SESSIONS} sessions ({ticker['return'] * 100:+.1f}%)"
    return True, f"{ticker['return'] * 100:+.1f}% over {TICKER_RETURN_SESSIONS} sessions, {MARKET_TICKER} below its EMA"


def session_flags(trend, sessions, column):
    """{session: allowed} from the row of the close before each session (False without one)."""
    flags = trend[column].astype(bool)
    out = {}
    for session in sessions:
        before = flags[flags.index < session]
        out[session] = bool(before.iloc[-1]) if len(before) else False
    return out
