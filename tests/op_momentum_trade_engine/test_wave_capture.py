from datetime import date, timedelta

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_capture import (
    _variant_trigger,
    capture_table,
    candidate_sides,
    daily_context,
    daily_events,
    events_before_sessions,
    load_trades,
    pick,
    walk_forward,
)

DAYS = [date(2026, 1, 5) + timedelta(days=i) for i in range(6)]


def _trades_csv(tmp_path, rows):
    path = tmp_path / "trades.csv"
    pd.DataFrame(rows, columns=["ticker", "setup", "exit", "entry_time", "side", "entry", "net_pct"]).to_csv(
        path, index=False)
    return path


def _row(setup, exit_mode, day, net_pct, side=1, entry=100.0, ticker="SNDK"):
    return [ticker, setup, exit_mode, f"{day} 09:35:00-05:00", side, entry, net_pct]


def _sessions(adr=2.0):
    return pd.DataFrame({"adr": adr}, index=DAYS)


class TestLoadTrades:
    def test_keeps_the_tickers_intraday_trades(self, tmp_path):
        path = _trades_csv(tmp_path, [_row("drive long", "eod", DAYS[0], 1.0),
                                      _row("overnight ma200", "next open", DAYS[0], 1.0),
                                      _row("drive long", "eod", DAYS[0], 1.0, ticker="AMD")])

        trades = load_trades(path, "SNDK")

        assert trades["candidate"].tolist() == ["drive long / eod"]
        assert trades["dollars"].tolist() == [1.0]


class TestCaptureTable:
    def test_capture_is_dollars_over_adr_with_zero_on_quiet_sessions(self, tmp_path):
        trades = load_trades(_trades_csv(tmp_path, [_row("drive long", "eod", DAYS[1], 1.0)]), "SNDK")

        capture, dollars, counts, pct = capture_table(trades, _sessions())

        assert capture["drive long / eod"].tolist() == [0.0, 0.5, 0.0, 0.0, 0.0, 0.0]

    def test_sides(self, tmp_path):
        trades = load_trades(_trades_csv(tmp_path, [_row("box break", "target", DAYS[0], 1.0, side=1),
                                                    _row("box break", "target", DAYS[1], 1.0, side=-1),
                                                    _row("drive short", "eod", DAYS[0], 1.0, side=-1)]), "SNDK")

        assert candidate_sides(trades) == {"box break / target": "both", "drive short / eod": "short"}


class TestPick:
    def _tables(self):
        capture = pd.DataFrame({"a / eod": [0.2, 0.2, 0.0, 0.0], "a / target": [0.3, 0.3, 0.0, 0.0],
                                "b / eod": [0.1, 0.1, 0.0, 0.0], "c / eod": [-0.5, 0.9, 0.0, 0.0]},
                               index=DAYS[:4])
        counts = pd.DataFrame(1.0, index=capture.index, columns=capture.columns)
        return capture, counts

    def test_best_positive_one_exit_per_setup(self):
        capture, counts = self._tables()

        assert pick(capture, counts, DAYS[2], 2, 2, 1) == ["a / target", "c / eod"]

    def test_needs_enough_trades(self):
        capture, counts = self._tables()

        assert pick(capture, counts, DAYS[2], 2, 1, 3) == []

    def test_uses_only_sessions_before_the_pick(self):
        capture, counts = self._tables()
        capture.loc[DAYS[2], "b / eod"] = 99.0

        assert pick(capture, counts, DAYS[2], 2, 1, 1) == ["a / target"]

    def test_short_history_picks_nothing(self):
        capture, counts = self._tables()

        assert pick(capture, counts, DAYS[1], 2, 1, 1) == []


class TestDailyEvents:
    def _context(self, closes):
        return daily_context(pd.Series(closes, index=[date(2025, 1, 1) + timedelta(days=i) for i in range(len(closes))]))

    def test_cross_above_ma20(self):
        context = self._context([100.0] * 25 + [90.0, 110.0])

        events = daily_events(context, "SNDK", include_trend=False)

        assert events[context.index[-1]] == [("ma", "up", "SNDK crossed above MA20")]

    def test_cross_below_ma20(self):
        context = self._context([100.0] * 25 + [110.0, 90.0])

        assert ("ma", "down", "SNDK crossed below MA20") in daily_events(context, "SNDK", False)[context.index[-1]]

    def test_trend_change_only_when_asked(self):
        context = self._context([100.0 + i for i in range(30)] + [80.0])

        with_trend = daily_events(context, "QQQ", include_trend=True)[context.index[-1]]

        assert any(e[0] == "trend" for e in with_trend)
        assert not any(e[0] == "trend" for e in daily_events(context, "QQQ", include_trend=False)[context.index[-1]])


class TestEventsBeforeSessions:
    def test_events_of_the_previous_close_reach_the_next_session(self):
        events = events_before_sessions(DAYS[:3], {DAYS[0]: [("ma", "down", "x")]}, {})

        assert events == {DAYS[1]: [("ticker", "ma", "down", "x")]}


class TestVariantTrigger:
    @pytest.mark.parametrize("variant,expected", [
        ("fixed", (False, False)),
        ("repick", (True, False)),
        ("repick-qqq-trend", (False, False)),
        ("aside-breakdown", (False, True)),
    ])
    def test_ticker_breakdown(self, variant, expected):
        assert _variant_trigger(variant, [("ticker", "ma", "down", "x")]) == expected

    def test_aside_breakdown_repicks_on_a_breakout(self):
        assert _variant_trigger("aside-breakdown", [("qqq", "ma", "up", "x")]) == (True, False)


class TestWalkForward:
    def _tables(self):
        capture = pd.DataFrame({"a / eod": [0.3, 0.3, 0.1, 0.1, 0.1, 0.1],
                                "b / eod": [0.1, 0.1, 0.4, 0.4, 0.4, 0.4]}, index=DAYS)
        counts = pd.DataFrame(1.0, index=DAYS, columns=capture.columns)
        return capture, counts, capture * 10

    def test_fixed_schedule_keeps_the_pick_for_the_block(self):
        capture, counts, pct = self._tables()

        run = walk_forward(capture, counts, pct, DAYS[2:], {}, {}, "fixed", 2, 10, 1, 1)

        assert run["picks"].tolist() == ["a / eod"] * 4

    def test_event_repicks_on_the_latest_look_back(self):
        capture, counts, pct = self._tables()

        run = walk_forward(capture, counts, pct, DAYS[2:], {DAYS[4]: [("qqq", "ma", "up", "x")]}, {}, "repick",
                           2, 10, 1, 1)

        assert run["picks"].tolist() == ["a / eod", "a / eod", "b / eod", "b / eod"]

    def test_step_aside_trades_nothing(self):
        capture, counts, pct = self._tables()

        run = walk_forward(capture, counts, pct, DAYS[2:], {DAYS[3]: [("ticker", "ma", "down", "x")]}, {},
                           "aside-breakdown", 2, 10, 1, 1)

        assert run["picks"].tolist()[1:] == ["(aside)"] * 3
        assert run["dollars"].tolist()[1:] == [0.0, 0.0, 0.0]
