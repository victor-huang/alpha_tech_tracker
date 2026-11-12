import json
from datetime import date, datetime

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.wave_strategy import strategy as strategy_module
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.intents import (
    BAR_CLOSE,
    ENTER,
    EXIT,
    MOC,
    MOVE_STOP,
    SKIP,
    STOP,
    SYSTEM,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import ET
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.specs import build_setup_spec
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.strategy import WaveSetupStrategy
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.trades import LiveTrade

SESSION = date(2026, 10, 6)
PRIOR = date(2026, 10, 5)


def _ts(text):
    return ET.localize(datetime.strptime(text, "%Y-%m-%d %H:%M"))


def _bar(text, o, h, l, c):
    return {"time": _ts(text), "open": o, "high": h, "low": l, "close": c}


def _prior_bars():
    index = pd.date_range(_ts("2026-10-05 09:30"), periods=78, freq="5min")
    return pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0}, index=index)


def _strategy(setups, **kwargs):
    intents = []
    strategy = WaveSetupStrategy({t: [build_setup_spec(s) for s in names] for t, names in setups.items()},
                                 sink=intents.append, releases_loader=lambda ticker: [], **kwargs)
    strategy.start_session(SESSION, {t: _prior_bars() for t in setups})
    strategy.prepare()
    return strategy, intents


def _feed(strategy, bar, ticker="AMD"):
    strategy.add_bar(ticker, bar)
    strategy.on_bar_exits(ticker, bar)
    strategy.on_bar_entries(ticker, bar)


def _signal(setup="drive long", signal="drive_long", time="2026-10-06 09:30", price=101.0, stop=100.0,
            target=103.0):
    return {"ticker": "AMD", "setup": setup, "signal": signal, "time": _ts(time), "price": price, "stop": stop,
            "target": target, "risk": price - stop, "rr": 2.0}


def _open_trade(**fields):
    defaults = dict(ticker="AMD", setup="drive long", exit_mode="eod", entry_time=_ts("2026-10-06 09:30"), side=1,
                    entry=101.0, stop=100.0, target=103.0, risk=1.0, last_bar=_ts("2026-10-06 09:30"))
    defaults.update(fields)
    return LiveTrade(**defaults)


def _kinds(intents):
    return [(i.kind, i.action, i.order) for i in intents]


class TestSetupEntries:
    def test_fired_signal_becomes_a_buy_at_the_bar_close(self, mocker):
        evaluate = mocker.Mock(return_value=[_signal()])
        strategy, intents = _strategy({"AMD": ["drive long"]}, evaluate_fn=lambda: evaluate)

        _feed(strategy, _bar("2026-10-06 09:30", 100.0, 101.2, 100.0, 101.0))

        assert _kinds(intents) == [(ENTER, "BUY", BAR_CLOSE)]
        assert intents[0].trade is strategy.trades[0]
        assert intents[0].price == 101.0

    def test_evaluation_result_is_persisted(self, mocker):
        persist = mocker.Mock()
        strategy, _ = _strategy({"AMD": ["drive long"]}, evaluate_fn=lambda: mocker.Mock(return_value=[_signal()]),
                                persist=persist)

        _feed(strategy, _bar("2026-10-06 09:30", 100.0, 101.2, 100.0, 101.0))

        persist.assert_called_once()

    def test_same_signal_enters_once(self, mocker):
        strategy, intents = _strategy({"AMD": ["drive long"]},
                                      evaluate_fn=lambda: mocker.Mock(return_value=[_signal()]))

        strategy.submit_evaluations("AMD", _ts("2026-10-06 09:30"))
        strategy.submit_evaluations("AMD", _ts("2026-10-06 09:30"))

        assert len(intents) == 1

    def test_no_evaluations_from_the_close_decision_bar_on(self, mocker):
        evaluate = mocker.Mock(return_value=[])
        strategy, _ = _strategy({"AMD": ["drive long"]}, evaluate_fn=lambda: evaluate)

        _feed(strategy, _bar("2026-10-06 15:45", 100.0, 100.0, 100.0, 100.0))

        evaluate.assert_not_called()


class TestExits:
    def test_stop_hit_exits_at_the_stop(self):
        strategy, intents = _strategy({"AMD": ["drive long"]}, evaluate_fn=lambda: lambda job: [])
        strategy.trades.append(_open_trade())

        _feed(strategy, _bar("2026-10-06 09:35", 100.5, 100.6, 99.5, 99.8))

        assert _kinds(intents) == [(EXIT, "SELL", STOP)]
        assert intents[0].price == 100.0

    def test_pullback_trail_gives_back_at_the_bar_close(self):
        strategy, intents = _strategy({"AMD": ["pullback long"]}, evaluate_fn=lambda: lambda job: [])
        strategy.trades.append(_open_trade(setup="pullback long", exit_mode="target-trail"))

        _feed(strategy, _bar("2026-10-06 09:35", 101.0, 104.5, 101.0, 104.0))
        _feed(strategy, _bar("2026-10-06 09:40", 104.0, 104.0, 102.5, 102.6))

        assert _kinds(intents) == [(EXIT, "SELL", BAR_CLOSE)]
        assert intents[0].message.startswith("SELL AMD | pullback long | giveback hit on the 09:40 bar")

    def test_close_decision_sells_open_intraday_trades_at_the_close(self):
        strategy, intents = _strategy({"AMD": ["drive long"]}, evaluate_fn=lambda: lambda job: [])
        strategy.add_bar("AMD", _bar("2026-10-06 15:45", 101.0, 101.5, 100.5, 101.2))
        strategy.trades.append(_open_trade())

        strategy.on_close_decision()

        assert _kinds(intents) == [(EXIT, "SELL", MOC)]
        assert intents[0].price == 101.2


class TestDriveShort:
    def test_red_first_bar_shorts_when_the_gate_is_on(self):
        strategy, intents = _strategy({"AMD": ["drive long"]}, short_setups=("drive",), short_gate="always",
                                      evaluate_fn=lambda: lambda job: [])

        _feed(strategy, _bar("2026-10-06 09:30", 101.0, 101.5, 99.0, 99.5))

        assert _kinds(intents) == [(ENTER, "SHORT", BAR_CLOSE)]
        assert intents[0].trade.stop == 101.5

    def test_no_short_when_the_gate_is_off(self):
        strategy, intents = _strategy({"AMD": ["drive long"]}, short_setups=("drive",), short_gate="off",
                                      evaluate_fn=lambda: lambda job: [])

        _feed(strategy, _bar("2026-10-06 09:30", 101.0, 101.5, 99.0, 99.5))

        assert intents == []

    def test_stopped_short_reenters_below_the_stop_out_level(self):
        strategy, intents = _strategy({"AMD": ["drive long"]}, short_setups=("drive",), short_gate="always",
                                      evaluate_fn=lambda: lambda job: [])

        _feed(strategy, _bar("2026-10-06 09:30", 101.0, 101.5, 99.0, 99.5))
        _feed(strategy, _bar("2026-10-06 09:35", 99.5, 102.0, 99.4, 101.8))
        _feed(strategy, _bar("2026-10-06 09:40", 101.8, 101.9, 100.5, 100.8))

        assert _kinds(intents) == [(ENTER, "SHORT", BAR_CLOSE), (EXIT, "COVER", STOP), (ENTER, "SHORT", BAR_CLOSE)]
        assert intents[2].setup == "short drive re-entry"


class TestDriveTrail:
    def test_new_dip_low_raises_the_drive_long_stop(self, mocker):
        strategy, intents = _strategy({"AMD": ["drive long"]}, drive_trail=True, evaluate_fn=lambda: lambda job: [])
        strategy.trades.append(_open_trade())
        mocker.patch.object(strategy.drive_trackers["AMD"], "turn", return_value=("up", 100.6))

        _feed(strategy, _bar("2026-10-06 09:35", 101.0, 101.5, 100.8, 101.2))

        assert _kinds(intents) == [(MOVE_STOP, "RAISE STOP", None)]
        assert strategy.trades[0].stop == 100.6


class TestOvernight:
    def test_trend_filter_skips_the_overnight_hold(self):
        strategy, intents = _strategy({"AMD": ["overnight always"]}, trend_filters=("overnight",),
                                      evaluate_fn=lambda: lambda job: [])
        strategy.add_bar("AMD", _bar("2026-10-06 15:45", 101.0, 101.5, 100.5, 101.2))

        strategy.on_close_decision()

        assert _kinds(intents) == [(SYSTEM, None, None), (SKIP, "SKIP", None)]

    def test_overnight_hold_buys_at_the_close(self):
        strategy, intents = _strategy({"AMD": ["overnight always"]}, evaluate_fn=lambda: lambda job: [])
        strategy.add_bar("AMD", _bar("2026-10-06 15:45", 101.0, 101.5, 100.5, 101.2))

        strategy.on_close_decision()

        assert _kinds(intents) == [(ENTER, "BUY", MOC)]

    def test_intraday_only_never_enters_overnight(self):
        strategy, intents = _strategy({"AMD": ["overnight always"]}, intraday_only=True,
                                      evaluate_fn=lambda: lambda job: [])
        strategy.add_bar("AMD", _bar("2026-10-06 15:45", 101.0, 101.5, 100.5, 101.2))

        strategy.on_close_decision()

        assert intents == []

    def test_intraday_only_still_closes_intraday_trades(self):
        strategy, intents = _strategy({"AMD": ["drive long"]}, intraday_only=True, evaluate_fn=lambda: lambda job: [])
        strategy.add_bar("AMD", _bar("2026-10-06 15:45", 101.0, 101.5, 100.5, 101.2))
        strategy.trades.append(_open_trade())

        strategy.on_close_decision()

        assert _kinds(intents) == [(EXIT, "SELL", MOC)]


class TestState:
    def test_round_trips_through_json_in_the_same_session(self):
        strategy, _ = _strategy({"AMD": ["drive long"]})
        strategy.trades.append(_open_trade())
        strategy.alerted.add("AMD|drive long|2026-10-06T09:30:00-04:00")
        saved = json.loads(json.dumps(strategy.state()))
        restored, _ = _strategy({"AMD": ["drive long"]})

        assert restored.restore(saved) is True
        assert restored.state() == strategy.state()

    def test_next_session_keeps_only_open_overnight_trades(self):
        saved = {"session": PRIOR.isoformat(), "alerted": ["x"], "trades": [
            _open_trade(entry_time=_ts("2026-10-05 09:30")).to_dict(),
            _open_trade(setup="overnight always", exit_mode="next open", status="pending", stop=None, target=None,
                        entry_time=_ts("2026-10-05 15:45")).to_dict()]}
        strategy, _ = _strategy({"AMD": ["drive long", "overnight always"]})

        assert strategy.restore(saved) is False
        assert [(t.setup, t.status) for t in strategy.trades] == [("overnight always", "open")]
        assert strategy.alerted == set()

    def test_reads_a_state_file_written_before_the_split(self):
        saved = {"session": SESSION.isoformat(), "alerted": ["AMD|drive long|2026-10-06T09:30:00-04:00"],
                 "done": {"pre_open": True, "close": False}, "trades": [_open_trade().to_dict()]}
        strategy, _ = _strategy({"AMD": ["drive long"]})

        strategy.restore(saved)

        assert strategy.state() == {key: saved[key] for key in ("session", "alerted", "trades")}


class TestStartSession:
    @pytest.mark.parametrize("prior_sessions, first", [(0, SESSION), (1, PRIOR)])
    def test_signal_window_starts_at_the_first_warm_up_session(self, prior_sessions, first):
        strategy = WaveSetupStrategy({"AMD": [build_setup_spec("drive long")]}, sink=lambda intent: None,
                                     releases_loader=lambda ticker: [])
        bars = _prior_bars() if prior_sessions else _prior_bars().iloc[0:0]

        strategy.start_session(SESSION, {"AMD": bars})

        assert strategy.window_start["AMD"] == ET.localize(datetime.combine(first, datetime.min.time()))

    def test_overnight_filter_short_of_daily_history_is_a_system_intent(self):
        intents = []
        strategy = WaveSetupStrategy({"AMD": [build_setup_spec("overnight ma200")]}, sink=intents.append,
                                     releases_loader=lambda ticker: [],
                                     daily_closes_loader=lambda tickers, session: {"AMD": [100.0] * 10})

        strategy.start_session(SESSION, {"AMD": _prior_bars()})

        assert _kinds(intents) == [(SYSTEM, None, None)]
        assert strategy_module.OVERNIGHT_MIN_DAILY_CLOSES > 10
