from datetime import date, timedelta

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.trend_filters import (
    market_trend,
    overnight_rule,
    pullback_rule,
    session_flags,
    ticker_trend,
)

START = date(2025, 1, 1)


def _daily(closes):
    index = [START + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"high": [c + 1.0 for c in closes], "close": closes}, index=index)


RISING = _daily([100.0 + i for i in range(220)])
FALLING = _daily([320.0 - i for i in range(220)])


class TestMarketTrend:
    def test_overnight_ok_above_the_200_day_ma_and_up_over_10_sessions(self):
        assert market_trend(RISING)["overnight_ok"].iloc[-1]

    def test_no_overnight_when_falling(self):
        assert not market_trend(FALLING)["overnight_ok"].iloc[-1]

    def test_no_overnight_above_the_ma_but_down_over_10_sessions(self):
        closes = [100.0] * 195 + [130.0] * 15 + [128.0 - i for i in range(10)]

        row = market_trend(_daily(closes)).iloc[-1]

        assert row["close"] > row["ma"]
        assert not row["overnight_ok"]

    def test_no_overnight_up_over_10_sessions_but_below_the_ma(self):
        closes = [200.0] * 200 + [100.0 + i for i in range(20)]

        row = market_trend(_daily(closes)).iloc[-1]

        assert row["return"] > 0
        assert not row["overnight_ok"]

    def test_not_ok_without_200_closes(self):
        assert not market_trend(_daily([100.0 + i for i in range(150)]))["overnight_ok"].iloc[-1]


class TestTickerTrend:
    def test_pullback_ok_on_a_higher_10_session_high(self):
        assert ticker_trend(RISING)["pullback_ok"].iloc[-1]

    def test_no_pullback_on_a_lower_10_session_high(self):
        assert not ticker_trend(FALLING)["pullback_ok"].iloc[-1]

    def test_not_ok_without_enough_history(self):
        assert not ticker_trend(_daily([100.0 + i for i in range(15)]))["pullback_ok"].iloc[-1]


class TestRules:
    def test_overnight_rule_text(self):
        ok, text = overnight_rule(market_trend(RISING).iloc[-1])

        assert ok
        assert text == "QQQ 319.00, above its 200-day MA 219.50, +3.2% over 10 sessions"

    def test_overnight_rule_off_without_market_data(self):
        assert overnight_rule(None) == (False, "QQQ has too little daily history")

    def test_pullback_rule_reason(self):
        assert pullback_rule(ticker_trend(FALLING).iloc[-1]) == (False, "10-session high 111.00 vs 121.00 before")

    def test_pullback_rule_off_without_history(self):
        assert pullback_rule(None) == (False, "too little daily history")


class TestSessionFlags:
    def test_uses_the_close_before_the_session(self):
        trend = pd.DataFrame({"ok": [True, False]}, index=[date(2026, 3, 2), date(2026, 3, 3)])

        assert session_flags(trend, [date(2026, 3, 3), date(2026, 3, 4)], "ok") == {
            date(2026, 3, 3): True, date(2026, 3, 4): False}

    def test_false_without_an_earlier_close(self):
        trend = pd.DataFrame({"ok": [True]}, index=[date(2026, 3, 2)])

        assert session_flags(trend, [date(2026, 3, 2)], "ok") == {date(2026, 3, 2): False}
