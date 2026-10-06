import csv
import json
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy import wave_setup_monitor as monitor_module
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import TradeSimulator
from alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor import (
    FiveMinAggregator,
    LiveTrade,
    WaveSetupMonitor,
    build_setup_spec,
    evaluate_setup,
    generate_config,
    load_config,
)

ET = pytz.timezone("America/New_York")
SESSION = date(2026, 10, 6)


def _ts(text):
    return ET.localize(datetime.strptime(text, "%Y-%m-%d %H:%M"))


def _bar(text, o, h, l, c):
    return {"time": _ts(text), "open": o, "high": h, "low": l, "close": c}


class TestBuildSetupSpec:
    def test_box_label_keeps_only_its_signal_groups(self):
        spec = build_setup_spec("box break")

        assert spec.groups == frozenset({"narrow-box break", "wide-box break"})
        assert (spec.exit_mode, spec.params.box_signals) == ("target", True)

    def test_drive_long_uses_its_setup_options(self):
        spec = build_setup_spec("drive long")

        assert (spec.params.opening_drive, spec.params.box_signals, spec.exit_mode) == ("long", False, "eod")
        assert spec.groups is None

    def test_overnight_setup_is_flagged(self):
        assert build_setup_spec("overnight ma200").overnight

    def test_unknown_setup_is_an_error(self):
        with pytest.raises(ValueError):
            build_setup_spec("moon shot")


class TestGenerateConfig:
    def _report(self, tmp_path, rows):
        with (tmp_path / "trades.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["ticker", "setup", "exit", "net_pct"])
            writer.writeheader()
            writer.writerows(rows)
        return tmp_path

    def test_picks_each_tickers_best_setups_one_per_family(self, tmp_path):
        report = self._report(tmp_path, [
            {"ticker": "AMD", "setup": "overnight always", "exit": "next open", "net_pct": 9.0},
            {"ticker": "AMD", "setup": "overnight ma200", "exit": "next open", "net_pct": 8.0},
            {"ticker": "AMD", "setup": "drive long", "exit": "eod", "net_pct": 3.0},
            {"ticker": "AMD", "setup": "drive long", "exit": "target", "net_pct": 50.0},
            {"ticker": "AMD", "setup": "bounce long", "exit": "target", "net_pct": -1.0},
        ])

        config = generate_config(report, ["AMD"], top_n=3)

        assert [s["setup"] for s in config["tickers"]["AMD"]] == ["overnight always", "drive long"]

    def test_ticker_missing_from_the_report_is_an_error(self, tmp_path):
        report = self._report(tmp_path, [{"ticker": "AMD", "setup": "drive long", "exit": "eod", "net_pct": 1.0}])

        with pytest.raises(ValueError, match="META"):
            generate_config(report, ["AMD", "META"])

    def test_config_round_trips_through_load_config(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"tickers": {"AMD": [{"setup": "drive long"}, "pullback long C1"]}}))

        setups = load_config(path)

        assert [s.name for s in setups["AMD"]] == ["drive long", "pullback long C1"]


class TestFiveMinAggregator:
    def _collect(self):
        emitted = []
        return emitted, FiveMinAggregator(lambda ticker, bar: emitted.append((ticker, bar)))

    def test_emits_when_the_fifth_minute_arrives(self):
        emitted, aggregator = self._collect()
        for minute, price in enumerate([10.0, 11.0, 9.0, 10.5, 10.2]):
            aggregator.add("AMD", _ts(f"2026-10-06 09:3{minute}"), price, price + 0.1, price - 0.1, price)

        assert len(emitted) == 1
        bar = emitted[0][1]
        assert (bar["time"], bar["open"], bar["high"], bar["low"], bar["close"], bar["minutes"]) == (
            _ts("2026-10-06 09:30"), 10.0, 11.1, 8.9, 10.2, 5)

    def test_emits_an_incomplete_period_when_the_next_one_starts(self):
        emitted, aggregator = self._collect()
        aggregator.add("AMD", _ts("2026-10-06 09:31"), 10.0, 10.0, 10.0, 10.0)
        aggregator.add("AMD", _ts("2026-10-06 09:36"), 11.0, 11.0, 11.0, 11.0)

        assert [(b["time"], b["minutes"]) for _, b in emitted] == [(_ts("2026-10-06 09:30"), 1)]

    def test_flushes_a_period_after_the_grace(self):
        emitted, aggregator = self._collect()
        aggregator.add("AMD", _ts("2026-10-06 09:31"), 10.0, 10.0, 10.0, 10.0)

        aggregator.flush_due(_ts("2026-10-06 09:35"))
        assert emitted == []
        aggregator.flush_due(ET.localize(datetime(2026, 10, 6, 9, 35, 21)))
        assert len(emitted) == 1


class TestLiveTradeMatchesBacktest:
    @pytest.mark.parametrize("exit_mode", ["target", "target-trail", "giveback", "eod"])
    @pytest.mark.parametrize("side", [1, -1])
    def test_same_exit_as_the_trade_simulator(self, exit_mode, side):
        rng = np.random.default_rng(7 + side)
        for _ in range(40):
            closes = 100 + np.cumsum(rng.normal(0, 0.4, 20))
            opens = np.r_[closes[0], closes[:-1]]
            highs = np.maximum(opens, closes) + rng.uniform(0, 0.3, 20)
            lows = np.minimum(opens, closes) - rng.uniform(0, 0.3, 20)
            index = pd.date_range(_ts("2026-10-06 14:20"), periods=20, freq="5min")
            bars = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=index)
            entry = closes[0]
            stop, target = (entry - 0.6, entry + 0.8) if side == 1 else (entry + 0.6, entry - 0.8)
            signal = {"time": index[0], "signal": "breakout" if side == 1 else "breakdown", "gap": False,
                      "box_mode": "breakout", "reverses": None, "regime": "up",
                      "risk_reward": {"stop": stop, "target": target, "risk": 0.6}}
            expected = TradeSimulator(bars).run(signal, exit_mode)

            trade = LiveTrade(ticker="X", setup="s", exit_mode=exit_mode, entry_time=index[0], side=side,
                              entry=entry, stop=stop, target=target, risk=0.6, last_bar=index[0])
            for stamp, row in bars.iloc[1:].iterrows():
                outcome = trade.on_bar({"time": stamp, **{k: float(row[k]) for k in ("open", "high", "low", "close")}})
                if outcome:
                    break
            if trade.status == "open":
                trade.close_at(index[-1], closes[-1], "eod")

            assert (trade.outcome, trade.exit_time, trade.exit_price) == pytest.approx(
                (expected["outcome"], expected["exit_time"], expected["exit"]))


class TestLiveTradeState:
    def test_numpy_values_save_as_plain_json(self):
        trade = LiveTrade(ticker="AMD", setup="pullback long", exit_mode="target-trail", entry_time=_ts(
            "2026-10-06 10:00"), side=1, entry=np.float64(100.0), stop=99.0, target=101.0, risk=1.0,
            last_bar=_ts("2026-10-06 10:00"))
        trade.on_bar({"time": _ts("2026-10-06 10:05"), "open": np.float64(100.0), "high": np.float64(101.5),
                      "low": np.float64(99.8), "close": np.float64(101.2)})

        restored = LiveTrade.from_dict(json.loads(json.dumps(trade.to_dict())))

        assert (restored.target_reached, restored.peak, restored.last_bar) == (True, 101.2, _ts("2026-10-06 10:05"))


class TestEvaluateSetup:
    def test_keeps_only_signals_on_the_bar_and_in_the_setups_groups(self, mocker):
        bar_time = _ts("2026-10-06 10:00")
        rr = {"stop": 99.0, "target": 102.0, "risk": 1.0, "rr": 2.0}
        signals = [
            {"time": bar_time, "signal": "breakout", "gap": False, "box_mode": "breakout", "reverses": None,
             "price": 100.0, "risk_reward": rr},
            {"time": bar_time, "signal": "fade_long", "gap": False, "box_mode": "reversion", "reverses": None,
             "price": 100.0, "risk_reward": rr},
            {"time": _ts("2026-10-06 09:55"), "signal": "breakout", "gap": False, "box_mode": "breakout",
             "reverses": None, "price": 100.0, "risk_reward": rr},
        ]
        mocker.patch.object(monitor_module, "analyze_bars", return_value={"signals": signals})

        fired = evaluate_setup(("AMD", build_setup_spec("box break"), None, None, bar_time))

        assert [(f["signal"], f["time"]) for f in fired] == [("breakout", bar_time)]


class FakeClient:
    def __init__(self, history):
        self.history = history
        self.subscribed = None

    def warmup(self, tickers, start, end):
        return {t: self.history.get(t, pd.DataFrame()) for t in tickers}

    def fetch_bars(self, tickers, start, end):
        return {}

    def subscribe_bars(self, callback, *tickers):
        self.subscribed = tickers

    def start(self):
        pass

    def stop(self):
        pass

    def reconnect(self):
        pass


def _history(day_closes):
    """Capitalised 5-min bars: one bar per (timestamp text, close)."""
    index = pd.DatetimeIndex([_ts(t) for t, _ in day_closes])
    closes = [c for _, c in day_closes]
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1.0}, index=index)


class _Clock:
    def __init__(self, text):
        self.value = _ts(text)

    def __call__(self):
        return self.value

    def set(self, text):
        self.value = _ts(text)


def _monitor(tmp_path, setups, clock, history=None, releases=None, closes=None):
    alerts = []
    monitor = WaveSetupMonitor(
        {t: [build_setup_spec(s) for s in names] for t, names in setups.items()},
        FakeClient(history or {}), state_file=tmp_path / "state.json", alerts_dir=tmp_path,
        notify=alerts.append, now=clock, releases_loader=lambda t: (releases or {}).get(t, []),
        daily_closes_loader=lambda tickers, session: closes or {})
    return monitor, alerts


class TestMonitorSignals:
    def test_signal_opens_a_trade_and_alerts_buy(self, tmp_path, mocker):
        clock = _Clock("2026-10-06 09:20")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        signal = {"ticker": "AMD", "setup": "drive long", "signal": "drive_long", "time": _ts("2026-10-06 09:30"),
                  "price": 101.0, "stop": 100.0, "target": 103.0, "risk": 1.0, "rr": 2.0}
        mocker.patch.object(monitor_module, "evaluate_setup", return_value=[signal])

        clock.set("2026-10-06 09:35")
        monitor._on_five_min_bar("AMD", _bar("2026-10-06 09:30", 100.0, 101.2, 100.0, 101.0))

        assert alerts == ["[wave] BUY AMD | drive long | ~101.00 (09:30 bar close) | stop 100.00 | "
                          "hold to the close (stop only)"]
        assert monitor.trades[0].status == "open"

    def test_same_signal_is_not_alerted_twice(self, tmp_path, mocker):
        clock = _Clock("2026-10-06 09:35")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        signal = {"ticker": "AMD", "setup": "drive long", "signal": "drive_long", "time": _ts("2026-10-06 09:30"),
                  "price": 101.0, "stop": 100.0, "target": 103.0, "risk": 1.0, "rr": 2.0}
        mocker.patch.object(monitor_module, "evaluate_setup", return_value=[signal])

        monitor._submit_evaluations("AMD", signal["time"])
        monitor._submit_evaluations("AMD", signal["time"])

        assert len(alerts) == 1

    def test_stop_hit_alerts_sell(self, tmp_path):
        clock = _Clock("2026-10-06 10:00")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        monitor.trades.append(LiveTrade(ticker="AMD", setup="drive long", exit_mode="eod", entry_time=_ts(
            "2026-10-06 09:30"), side=1, entry=101.0, stop=100.0, target=103.0, risk=1.0,
            last_bar=_ts("2026-10-06 09:30")))

        monitor._update_trades("AMD", _bar("2026-10-06 09:35", 100.5, 100.6, 99.5, 99.8))

        assert alerts == ["[wave] SELL AMD | drive long | stop hit on the 09:35 bar @ 100.00 | -0.99%"]

    def test_no_entries_from_the_close_decision_bar_on(self, tmp_path, mocker):
        clock = _Clock("2026-10-06 15:50")
        monitor, _ = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        evaluate = mocker.patch.object(monitor, "_submit_evaluations")

        monitor._on_five_min_bar("AMD", _bar("2026-10-06 15:45", 100.0, 100.0, 100.0, 100.0))

        evaluate.assert_not_called()


class TestMonitorClose:
    def test_close_alert_closes_intraday_trades_and_buys_the_overnight_hold(self, tmp_path):
        clock = _Clock("2026-10-06 15:50")
        history = {"AMD": _history([("2026-10-06 15:45", 102.0)])}
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long", "overnight always"]}, clock, history)
        monitor.prepare()
        monitor.trades.append(LiveTrade(ticker="AMD", setup="drive long", exit_mode="eod", entry_time=_ts(
            "2026-10-06 09:30"), side=1, entry=101.0, stop=100.0, target=103.0, risk=1.0,
            last_bar=_ts("2026-10-06 15:45")))

        monitor.tick()

        assert alerts == [
            "[wave] SELL AMD | drive long | at the close (MOC) | +0.99% at 102.00",
            "[wave] BUY AMD | overnight always | at the close (MOC), ref 102.00 (15:45 bar) | sell at the next open",
        ]

    def test_waits_for_every_tickers_decision_bar(self, tmp_path):
        clock = _Clock("2026-10-06 15:50")
        history = {"AMD": _history([("2026-10-06 15:45", 102.0)]), "META": _history([("2026-10-06 15:40", 700.0)])}
        monitor, alerts = _monitor(tmp_path, {"AMD": ["overnight always"], "META": ["overnight always"]}, clock,
                                   history)
        monitor.prepare()

        monitor.tick()
        assert alerts == []
        clock.set("2026-10-06 15:51")
        monitor.tick()
        assert len(alerts) == 2

    def test_overnight_hold_skips_the_night_into_earnings(self, tmp_path):
        clock = _Clock("2026-10-06 15:50")
        history = {"AMD": _history([("2026-10-06 15:45", 102.0)])}
        monitor, alerts = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock, history,
                                   releases={"AMD": [datetime(2026, 10, 6, 16, 0)]})
        monitor.prepare()

        monitor.tick()

        assert alerts == ["[wave] SKIP AMD | overnight always | earnings release before the next open"]
        assert monitor.trades == []

    def test_overnight_ma200_filter_blocks_below_the_average(self, tmp_path):
        clock = _Clock("2026-10-06 15:50")
        history = {"AMD": _history([("2026-10-06 15:45", 90.0)])}
        monitor, alerts = _monitor(tmp_path, {"AMD": ["overnight ma200"]}, clock, history,
                                   closes={"AMD": [100.0] * 210})
        monitor.prepare()

        monitor.tick()

        assert alerts == []

    def test_last_bar_sets_the_overnight_entry_and_closes_intraday(self, tmp_path):
        clock = _Clock("2026-10-06 16:00")
        monitor, _ = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock)
        monitor.prepare()
        hold = LiveTrade(ticker="AMD", setup="overnight always", exit_mode="next open", entry_time=_ts(
            "2026-10-06 15:45"), side=1, entry=102.0, status="pending", last_bar=_ts("2026-10-06 15:45"))
        closing = LiveTrade(ticker="AMD", setup="drive long", exit_mode="eod", entry_time=_ts("2026-10-06 09:30"),
                            side=1, entry=101.0, stop=100.0, target=103.0, risk=1.0, status="closing",
                            last_bar=_ts("2026-10-06 15:45"))
        monitor.trades += [hold, closing]

        monitor._update_trades("AMD", _bar("2026-10-06 15:55", 102.0, 102.6, 101.9, 102.5))

        assert (hold.status, hold.entry) == ("open", 102.5)
        assert (closing.status, closing.exit_price, closing.outcome) == ("closed", 102.5, "close")


class TestMonitorNextMorning:
    def _hold(self):
        return LiveTrade(ticker="AMD", setup="overnight always", exit_mode="next open",
                         entry_time=_ts("2026-10-05 15:45"), side=1, entry=100.0, status="open",
                         last_bar=_ts("2026-10-05 15:55"))

    def test_restores_overnight_holds_and_alerts_sell_at_the_open(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps({"session": "2026-10-05", "alerted": ["x"],
                                                         "trades": [self._hold().to_dict()]}))
        clock = _Clock("2026-10-06 09:25")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock)
        monitor.prepare()

        monitor.tick()

        assert alerts == ["[wave] SELL AMD | overnight always | at the open (MOO before 09:28), bought 100.00 on 10-05"]
        assert monitor.alerted == set()

    def test_first_bar_closes_the_hold_at_the_open(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps({"session": "2026-10-05", "trades": [self._hold().to_dict()]}))
        clock = _Clock("2026-10-06 09:35")
        monitor, _ = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock)
        monitor.prepare()

        monitor._on_five_min_bar("AMD", _bar("2026-10-06 09:30", 103.0, 104.0, 102.0, 103.5))

        hold = monitor.trades[0]
        assert (hold.status, hold.exit_price, hold.outcome) == ("closed", 103.0, "next open")
        assert hold.pnl_pct() == pytest.approx(3.0)

    def test_restart_mid_session_catches_up_and_keeps_alerted_keys(self, tmp_path):
        trade = LiveTrade(ticker="AMD", setup="drive long", exit_mode="eod", entry_time=_ts("2026-10-06 09:30"),
                          side=1, entry=101.0, stop=100.0, target=103.0, risk=1.0, last_bar=_ts("2026-10-06 09:30"))
        (tmp_path / "state.json").write_text(json.dumps({"session": "2026-10-06", "alerted": ["AMD|drive long|k"],
                                                         "trades": [trade.to_dict()]}))
        history = {"AMD": _history([("2026-10-06 09:30", 101.0), ("2026-10-06 09:35", 99.0), ("2026-10-06 09:40", 99.5)])}
        clock = _Clock("2026-10-06 09:42")
        monitor, _ = _monitor(tmp_path, {"AMD": ["drive long"]}, clock, history)

        monitor.prepare()

        assert (monitor.trades[0].status, monitor.trades[0].outcome) == ("closed", "stop")
        assert "AMD|drive long|k" in monitor.alerted
        assert monitor.bars["AMD"].index[-1] == _ts("2026-10-06 09:35")


class TestWarmup:
    def test_before_the_open_warms_up_to_the_previous_close(self, tmp_path, mocker):
        clock = _Clock("2026-10-06 09:00")
        monitor, _ = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        warmup = mocker.spy(monitor.client, "warmup")

        monitor.prepare()

        assert warmup.call_args.args[2] == _ts("2026-10-05 16:00")

    def test_delayed_feed_warms_up_to_16_minutes_ago_and_backfills_later(self, tmp_path):
        clock = _Clock("2026-10-06 11:00")
        monitor, _ = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        calls = []

        def warmup(tickers, start, end):
            calls.append(end)
            if end > _ts("2026-10-06 10:45"):
                raise RuntimeError("subscription does not permit querying recent SIP data")
            return {"AMD": _history([("2026-10-06 10:35", 100.0)])}

        monitor.client.warmup = warmup
        monitor.client.fetch_bars = lambda tickers, start, end: {
            "AMD": _history([("2026-10-06 10:40", 101.0), ("2026-10-06 10:50", 102.0)])}
        monitor.prepare()

        assert calls == [_ts("2026-10-06 11:00"), _ts("2026-10-06 10:44")]
        clock.set("2026-10-06 11:10")
        monitor.tick()
        assert len(monitor.bars["AMD"]) == 1
        clock.set("2026-10-06 11:16")
        monitor.tick()
        assert list(monitor.bars["AMD"]["close"]) == [100.0, 101.0, 102.0]
        assert monitor.backfill is None


class TestOnMinuteBar:
    def test_ignores_pre_market_and_other_tickers(self, tmp_path):
        clock = _Clock("2026-10-06 09:00")
        monitor, _ = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        add = []
        monitor.aggregator.add = lambda *a: add.append(a)

        for symbol, stamp in (("AMD", "2026-10-06 09:10"), ("TSLA", "2026-10-06 09:31"), ("AMD", "2026-10-06 09:31")):
            monitor.on_minute_bar(SimpleNamespace(symbol=symbol, timestamp=_ts(stamp), open=1, high=1, low=1, close=1))

        assert [a[1] for a in add] == [_ts("2026-10-06 09:31")]
        assert monitor.last_minute_at is not None
