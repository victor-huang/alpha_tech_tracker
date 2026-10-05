from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    TradeSimulator,
    apply_costs,
    grade_legs,
    main,
    parse_args,
    run_backtest,
    signal_group,
    summarize,
    zigzag_legs,
)

MARKET_TZ = "America/New_York"
MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest"


def _timestamp(text):
    return pd.Timestamp(text, tz=MARKET_TZ)


def _bars(start, rows):
    """rows of (open, high, low, close) at 5-min spacing from `start`."""
    index = pd.date_range(_timestamp(start), periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def _signal(time, name="breakout", stop=99.0, target=102.0, risk=1.0, **overrides):
    signal = {
        "time": _timestamp(time),
        "signal": name,
        "gap": False,
        "price": 100.0,
        "box_mode": "breakout",
        "reverses": None,
        "regime": "up",
        "risk_reward": {"stop": stop, "target": target, "risk": risk},
    }
    signal.update(overrides)
    return signal


class TestSignalGroup:
    @pytest.mark.parametrize("overrides, group", [
        ({"signal": "drive_long"}, "opening drive"),
        ({"signal": "pullback_short"}, "wave pullback"),
        ({"gap": True}, "gap"),
        ({"signal": "fade_short"}, "fade"),
        ({"reverses": "fade_short"}, "stop-and-reverse"),
        ({"box_mode": "reversion"}, "wide-box break"),
        ({}, "narrow-box break"),
    ])
    def test_groups_signal_by_type(self, overrides, group):
        assert signal_group(_signal("2026-09-01 10:00", **overrides)) == group


class TestTradeSimulator:
    def test_long_exits_at_target(self):
        bars = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 102.5, 99.5, 101), (101, 101, 101, 101)])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00"), "target")

        assert (trade["outcome"], trade["exit"]) == ("target", 102.0)
        assert trade["gross_pct"] == pytest.approx(2.0)

    def test_long_exits_at_stop(self):
        bars = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 100.5, 98.5, 99.5)])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00"), "target")

        assert (trade["outcome"], trade["exit"]) == ("stop", 99.0)

    def test_gap_through_stop_fills_at_open(self):
        bars = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (98.0, 98.5, 97.5, 98.2)])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00"), "target")

        assert trade["exit"] == 98.0

    def test_bar_hitting_stop_and_target_counts_as_stop(self):
        bars = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 102.5, 98.5, 101)])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00"), "target")

        assert trade["outcome"] == "stop"

    def test_short_exits_at_stop_above_entry(self):
        bars = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 101.5, 99.8, 101)])
        signal = _signal("2026-09-01 10:00", name="breakdown", stop=101.0, target=98.0)

        trade = TradeSimulator(bars).run(signal, "target")

        assert (trade["outcome"], trade["side"]) == ("stop", -1)
        assert trade["gross_pct"] == pytest.approx(-1.0)

    def test_eod_exit_uses_session_close_not_next_session(self):
        bars = pd.concat([
            _bars("2026-09-01 15:50", [(100, 100, 100, 100), (100, 100.8, 99.5, 100.5)]),
            _bars("2026-09-02 09:30", [(110, 110, 110, 110)]),
        ])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 15:50"), "eod")

        assert (trade["outcome"], trade["exit"]) == ("eod", 100.5)
        assert trade["exit_time"] == _timestamp("2026-09-01 15:55")

    def test_giveback_exits_after_giving_back_share_of_peak_profit(self):
        closes = [100, 101, 102, 101.2, 100.5]
        bars = _bars("2026-09-01 10:00", [(c, c + 0.1, c - 0.1, c) for c in closes])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00", target=110.0), "giveback", 0.32, 0.25)

        assert (trade["outcome"], trade["exit"]) == ("giveback", 101.2)

    def test_giveback_waits_until_armed(self):
        closes = [100, 100.2, 100.1, 100.15]
        bars = _bars("2026-09-01 10:00", [(c, c + 0.05, c - 0.05, c) for c in closes])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00", target=110.0), "giveback", 0.32, 0.25)

        assert trade["outcome"] == "eod"

    def test_target_trail_holds_past_target_then_trails(self):
        closes = [100, 101, 102.5, 104, 103.4, 102.6]
        bars = _bars("2026-09-01 10:00", [(c, c + 0.1, c - 0.1, c) for c in closes])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00", target=102.0), "target-trail", 0.32, 0.25)

        assert (trade["outcome"], trade["exit"]) == ("giveback", 102.6)

    def test_target_trail_does_not_trail_before_target(self):
        closes = [100, 101, 101.5, 100.9, 101.2]
        bars = _bars("2026-09-01 10:00", [(c, c + 0.1, c - 0.1, c) for c in closes])

        trade = TradeSimulator(bars).run(_signal("2026-09-01 10:00", target=105.0), "target-trail", 0.32, 0.25)

        assert (trade["outcome"], trade["exit"]) == ("eod", 101.2)

    def test_signal_on_last_bar_of_session_is_not_traded(self):
        bars = _bars("2026-09-01 15:55", [(100, 100, 100, 100)])

        assert TradeSimulator(bars).run(_signal("2026-09-01 15:55"), "target") is None

    def test_signal_without_risk_reward_is_not_traded(self):
        bars = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 101, 99.5, 100.5)])

        assert TradeSimulator(bars).run(_signal("2026-09-01 10:00", risk_reward=None), "target") is None


class TestApplyCosts:
    def test_cost_comes_off_return_and_r(self):
        trade = {"gross_pct": 1.0, "entry": 100.0, "risk": 0.5}

        net = apply_costs(trade, cost_bps=10)

        assert net["net_pct"] == pytest.approx(0.9)
        assert net["net_r"] == pytest.approx(1.8)


class TestSummarize:
    def test_summarizes_net_returns(self):
        trades = [
            {"net_pct": 1.0, "net_r": 2.0, "outcome": "target"},
            {"net_pct": -0.5, "net_r": -1.0, "outcome": "stop"},
        ]

        summary = summarize(trades)

        assert (summary["trades"], summary["win"], summary["total_pct"]) == (2, 0.5, pytest.approx(0.5))
        assert summary["avg_r"] == pytest.approx(0.5)
        assert summary["outcomes"]["stop"] == 1

    def test_no_trades_is_none(self):
        assert summarize([]) is None


class TestZigzagLegs:
    def test_splits_on_reversal(self):
        closes = [100, 101, 103, 102.5, 101, 100, 102]

        assert zigzag_legs(closes, reversal=1.5) == [(0, 2, 1), (2, 5, -1), (5, 6, 1)]

    def test_small_wiggles_stay_in_one_leg(self):
        closes = [100, 101, 100.6, 102, 101.7, 103]

        assert zigzag_legs(closes, reversal=1.5) == [(0, 5, 1)]


class TestGradeLegs:
    def _leg(self):
        return {"start": _timestamp("2026-09-01 10:00"), "end": _timestamp("2026-09-01 11:00"),
                "direction": 1, "start_price": 100.0, "end_price": 104.0, "size": 4.0}

    def test_signal_with_leg_before_halfway_is_caught(self):
        signal = _signal("2026-09-01 10:15", price=101.0)
        trade = {"exit": 103.0, "entry": 101.0, "side": 1}

        row = grade_legs([self._leg()], [signal], {signal["time"]: trade})[0]

        assert row["caught"] is True
        assert row["capture"] == pytest.approx(0.5)

    def test_signal_after_halfway_is_late(self):
        signal = _signal("2026-09-01 10:40", price=103.0)

        row = grade_legs([self._leg()], [signal], {})[0]

        assert (row["caught"], row["late"]) == (False, True)

    def test_opposite_signal_counts_against_leg(self):
        signal = _signal("2026-09-01 10:15", name="fade_short", price=101.0)

        row = grade_legs([self._leg()], [signal], {})[0]

        assert (row["caught"], row["against"]) == (False, 1)


class TestRunBacktest:
    def _bars(self):
        return _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 102.5, 99.5, 101), (101, 101, 101, 101)])

    def test_only_signals_inside_window_are_traded(self, mocker):
        mocker.patch(f"{MODULE}.analyze_bars", return_value={"signals": [_signal("2026-09-01 10:00")]})
        args = parse_args(["--start", "2026-09-02"])
        args.end = date(2026, 9, 30)

        trades_by_exit, _, _ = run_backtest({"SNDK": self._bars()}, args)

        assert trades_by_exit["target"] == []

    def test_compare_exits_trades_every_exit_mode(self, mocker):
        mocker.patch(f"{MODULE}.analyze_bars", return_value={"signals": [_signal("2026-09-01 10:00")]})
        args = parse_args(["--start", "2026-09-01", "--compare-exits", "--cost-bps", "5"])
        args.end = date(2026, 9, 1)

        trades_by_exit, _, sessions = run_backtest({"SNDK": self._bars()}, args)

        assert set(trades_by_exit) == {"target", "target-trail", "giveback", "eod"}
        assert trades_by_exit["target"][0]["net_pct"] == pytest.approx(1.95)
        assert trades_by_exit["target"][0]["ticker"] == "SNDK"
        assert sessions == 1

    def test_strategy_options_reach_analyze_bars(self, mocker):
        analyze = mocker.patch(f"{MODULE}.analyze_bars", return_value={"signals": []})
        args = parse_args(["--start", "2026-09-01", "--opening-drive", "both", "--regime-switch", "off"])
        args.end = date(2026, 9, 1)

        run_backtest({"SNDK": self._bars()}, args)

        params = analyze.call_args.args[1]
        assert (params.opening_drive, params.regime_switch) == ("both", "off")


class TestMain:
    def test_prints_report_for_fetched_bars(self, mocker, capsys):
        raw = _bars("2026-09-01 10:00", [(100, 100, 100, 100), (100, 102.5, 99.5, 101), (101, 101, 101, 101)])
        mocker.patch(f"{MODULE}.fetch_bars", return_value={"SNDK": raw.rename(columns=str.capitalize)})
        mocker.patch(f"{MODULE}.analyze_bars", return_value={"signals": [_signal("2026-09-01 10:00")]})

        main(["--tickers", "SNDK", "--start", "2026-09-01", "--end", "2026-09-01", "--feed", "iex"])

        out = capsys.readouterr().out
        assert "Wave risk/reward backtest   SNDK   2026-09-01 .. 2026-09-01   exit=target" in out
        assert "trades    1" in out
