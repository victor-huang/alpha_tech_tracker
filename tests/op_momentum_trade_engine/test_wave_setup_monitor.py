import csv
import json
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy import wave_setup_monitor as monitor_module
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import TradeSimulator
from alpha_tech_tracker.op_momentum_strategy.reversal_watch import ReversalSignal
from alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor import (
    FiveMinAggregator,
    LiveTrade,
    WaveSetupMonitor,
    build_setup_spec,
    evaluate_setup,
    generate_config,
    is_trading_day,
    load_config,
    parse_args,
    previous_trading_day,
    session_close,
)

ET = pytz.timezone("America/New_York")
SESSION = date(2026, 10, 6)
FIXTURES = Path(__file__).parent / "fixtures"


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
            writer = csv.DictWriter(handle, fieldnames=["ticker", "setup", "exit", "net_pct", "entry_time"])
            writer.writeheader()
            writer.writerows([dict({"entry_time": "2026-09-01 10:00:00-04:00"}, **row) for row in rows])
        return tmp_path

    def test_types_limit_the_setups(self, tmp_path):
        report = self._report(tmp_path, [
            {"ticker": "AMD", "setup": "drive short", "exit": "eod", "net_pct": 9.0},
            {"ticker": "AMD", "setup": "drive long", "exit": "eod", "net_pct": 3.0},
        ])

        config = generate_config(report, ["AMD"], types=["long", "overnight"])

        assert [s["setup"] for s in config["tickers"]["AMD"]] == ["drive long"]
        assert config["types"] == ["long", "overnight"]

    def test_setups_need_the_minimum_trades(self, tmp_path):
        report = self._report(tmp_path, [
            {"ticker": "AMD", "setup": "bounce long", "exit": "target", "net_pct": 9.0},
            {"ticker": "AMD", "setup": "drive long", "exit": "eod", "net_pct": 1.0},
            {"ticker": "AMD", "setup": "drive long", "exit": "eod", "net_pct": 1.0},
        ])

        config = generate_config(report, ["AMD"], min_trades=2)

        assert [s["setup"] for s in config["tickers"]["AMD"]] == ["drive long"]

    def test_lookback_ranks_only_the_last_sessions(self, tmp_path):
        report = self._report(tmp_path, [
            {"ticker": "AMD", "setup": "bounce long", "exit": "target", "net_pct": 9.0,
             "entry_time": "2026-08-03 10:00:00-04:00"},
            {"ticker": "AMD", "setup": "drive long", "exit": "eod", "net_pct": 1.0,
             "entry_time": "2026-09-01 09:30:00-04:00"},
        ])

        config = generate_config(report, ["AMD"], lookback_sessions=1)

        assert [s["setup"] for s in config["tickers"]["AMD"]] == ["drive long"]
        assert config["window"] == "2026-09-01..2026-09-01"

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


def _monitor(tmp_path, setups, clock, history=None, releases=None, closes=None, **kwargs):
    alerts = []
    monitor = WaveSetupMonitor(
        {t: [build_setup_spec(s) for s in names] for t, names in setups.items()},
        FakeClient(history or {}), state_file=tmp_path / "state.json", alerts_dir=tmp_path,
        notify=alerts.append, now=clock, releases_loader=lambda t: (releases or {}).get(t, []),
        daily_closes_loader=lambda tickers, session: closes or {}, **kwargs)
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


def _amd_history(until):
    """AMD 5-min bars for 2026-08-31 and 2026-09-01 before `until`, as the market data client returns them."""
    frame = pd.read_csv(FIXTURES / "amd_5min_2026-09-01.csv", index_col="time")
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(ET)
    return frame[frame.index < _ts(until)].rename(columns=str.capitalize)


def _amd_bar(text):
    frame = pd.read_csv(FIXTURES / "amd_5min_2026-09-01.csv", index_col="time")
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(ET)
    return {"time": _ts(text), **frame.loc[_ts(text)].to_dict()}


def _reversal(text, side="bottom"):
    return ReversalSignal(ticker="AMD", time=_ts(text), side=side, pattern="push", price=100.0, extreme=99.5,
                          move_bars=3.2)


class TestReversalAlerts:
    def test_patterns_on_one_bar_send_one_alert(self, tmp_path):
        clock = _Clock("2026-09-01 10:30")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:30")})
        monitor.prepare()

        clock.set("2026-09-01 10:35")
        monitor._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))

        assert alerts == ["[wave] LOW? AMD | piercing + push | ~454.10 (10:30 bar close) | wave down 5.5 avg bars, "
                          "low 452.30"]

    def test_alert_is_logged_to_the_csv(self, tmp_path):
        clock = _Clock("2026-09-01 10:30")
        monitor, _ = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:30")})
        monitor.prepare()

        monitor._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))

        with (tmp_path / "wave_setup_alerts_2026-09-01.csv").open() as handle:
            row = list(csv.DictReader(handle))[-1]
        assert (row["ticker"], row["setup"], row["action"], row["price"]) == (
            "AMD", "reversal piercing + push", "LOW?", "454.095")

    def test_warm_up_bars_alert_nothing(self, tmp_path):
        clock = _Clock("2026-09-01 10:40")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:40")})

        monitor.prepare()

        assert alerts == []

    def test_restart_does_not_repeat_an_alert(self, tmp_path):
        clock = _Clock("2026-09-01 10:30")
        first, _ = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:30")})
        first.prepare()
        first._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))
        restarted, alerts = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:30")})
        restarted.prepare()

        restarted._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))

        assert alerts == []

    def test_turned_off_alerts_nothing(self, tmp_path):
        clock = _Clock("2026-09-01 10:30")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:30")},
                                   reversal_patterns=[])
        monitor.prepare()

        monitor._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))

        assert alerts == []

    def test_no_alert_on_the_sessions_last_bar(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 15:55")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 15:55")})
        monitor.prepare()
        mocker.patch.object(monitor.reversal_watches["AMD"], "update", return_value=[_reversal("2026-09-01 15:55")])

        monitor._on_five_min_bar("AMD", _bar("2026-09-01 15:55", 100.0, 100.2, 99.8, 100.0))

        assert alerts == []
        assert monitor.alerted == set()

    def test_no_alert_on_an_early_close_days_last_bar(self, tmp_path, mocker):
        clock = _Clock("2026-11-27 12:55")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock)
        monitor.prepare()
        mocker.patch.object(monitor.reversal_watches["AMD"], "update", return_value=[_reversal("2026-11-27 12:55")])

        monitor._on_five_min_bar("AMD", _bar("2026-11-27 12:55", 100.0, 100.2, 99.8, 100.0))

        assert alerts == []

    def test_a_low_and_a_high_on_one_bar_send_two_alerts(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 11:00")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock)
        monitor.prepare()
        mocker.patch.object(monitor.reversal_watches["AMD"], "update", return_value=[
            _reversal("2026-09-01 11:00", "bottom"), _reversal("2026-09-01 11:00", "top")])

        monitor._on_five_min_bar("AMD", _bar("2026-09-01 11:00", 100.0, 100.2, 99.8, 100.0))

        assert [a.split(" | ")[0] for a in alerts] == ["[wave] LOW? AMD", "[wave] HIGH? AMD"]

    def test_watch_error_does_not_block_the_setups(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 11:00")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        mocker.patch.object(monitor.reversal_watches["AMD"], "update", side_effect=ZeroDivisionError)
        evaluate = mocker.patch.object(monitor, "_submit_evaluations")

        monitor._on_five_min_bar("AMD", _bar("2026-09-01 11:00", 100.0, 100.2, 99.8, 100.0))

        evaluate.assert_called_once()
        assert alerts == []

    def test_watch_rebuild_error_turns_off_its_alerts(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 11:00")
        mocker.patch.object(monitor_module.ReversalWatch, "from_bars", side_effect=ValueError)
        monitor, _ = _monitor(tmp_path, {"AMD": []}, clock)

        monitor.prepare()

        assert monitor.reversal_watches == {}

    def test_no_alert_until_a_delayed_feed_gap_is_backfilled(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 11:00")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock)
        monitor.prepare()
        monitor.backfill = (_ts("2026-09-01 10:30"), _ts("2026-09-01 10:46"))
        mocker.patch.object(monitor.reversal_watches["AMD"], "update", return_value=[_reversal("2026-09-01 11:00")])

        monitor._on_five_min_bar("AMD", _bar("2026-09-01 11:00", 100.0, 100.2, 99.8, 100.0))

        assert alerts == []

    def test_out_of_order_bar_rebuilds_the_watch_silently(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 10:40")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _amd_history("2026-09-01 10:40")})
        monitor.prepare()
        monitor.bars["AMD"] = monitor.bars["AMD"].drop(_ts("2026-09-01 10:30"))
        stale = monitor.reversal_watches["AMD"]

        monitor._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))

        assert alerts == []
        assert monitor.reversal_watches["AMD"] is not stale

    def test_backfilled_bars_reach_the_watch(self, tmp_path):
        clock = _Clock("2026-10-06 11:16")
        monitor, _ = _monitor(tmp_path, {"AMD": []}, clock, history={"AMD": _history([("2026-10-06 10:35", 100.0)])})
        monitor.prepare()
        monitor.client.fetch_bars = lambda tickers, start, end: {"AMD": _history([("2026-10-06 10:40", 101.0)])}
        monitor.backfill = (_ts("2026-10-06 10:40"), _ts("2026-10-06 10:45"))

        monitor._run_backfill(clock())

        assert monitor.reversal_watches["AMD"].last_time == _ts("2026-10-06 10:40")

    def test_backfill_replay_alerts_nothing_and_later_bars_still_alert(self, tmp_path):
        clock = _Clock("2026-09-01 10:30")
        history = _amd_history("2026-09-01 10:30")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock,
                                   history={"AMD": history[history.index < _ts("2026-09-01 10:00")]})
        monitor.prepare()
        gap = history[history.index >= _ts("2026-09-01 10:00")]
        monitor.client.fetch_bars = lambda tickers, start, end: {"AMD": gap}
        monitor.backfill = (_ts("2026-09-01 10:00"), _ts("2026-09-01 10:14"))
        monitor._run_backfill(clock())

        monitor._on_five_min_bar("AMD", _amd_bar("2026-09-01 10:30"))

        assert len(alerts) == 1 and alerts[0].startswith("[wave] LOW? AMD | piercing + push")


class TestSignalStatsAlert:
    def _monitor(self, tmp_path, mocker, **kwargs):
        clock = _Clock("2026-10-06 09:00")
        history = {"AMD": _history([("2026-10-05 15:55", 100.0)]), "META": _history([("2026-10-05 15:55", 50.0)])}
        return _monitor(tmp_path, {"AMD": ["drive long"]}, clock, history=history, **kwargs)

    def test_sends_the_stats_at_start(self, tmp_path, mocker):
        monitor, alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD", "META"],
                                        stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        stats = mocker.patch.object(monitor_module, "signal_stats", return_value="signal stats ...")

        monitor.send_signal_stats()

        assert alerts == ["[wave] signal stats ..."]
        assert sorted(stats.call_args.args[0]) == ["AMD", "META"]

    def test_fetches_only_the_stats_tickers_it_does_not_monitor(self, tmp_path, mocker):
        monitor, _ = self._monitor(tmp_path, mocker, stats_tickers=["AMD", "META"],
                                   stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        mocker.patch.object(monitor_module, "signal_stats", return_value="signal stats ...")
        warmup = mocker.spy(monitor.client, "warmup")

        monitor.send_signal_stats()

        assert warmup.call_args.args[0] == ["META"]
        assert warmup.call_args.args[2] == _ts("2026-10-05 16:00")

    def test_error_is_logged_not_raised(self, tmp_path, mocker):
        monitor, alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD"],
                                        stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        mocker.patch.object(monitor_module, "signal_stats", side_effect=ValueError)

        monitor.send_signal_stats()

        assert alerts == []

    def test_missing_daily_closes_are_noted(self, tmp_path, mocker):
        def failing_loader(tickers, session):
            raise RuntimeError("no daily data")

        monitor, alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD"], stats_daily_loader=failing_loader)
        monitor.prepare()

        monitor.send_signal_stats()

        assert alerts[0].splitlines()[-1] == "overnight ma200: daily closes unavailable, no holds counted"

    def test_a_ticker_whose_history_fails_is_listed(self, tmp_path, mocker):
        monitor, alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD", "META"],
                                        stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        mocker.patch.object(monitor.client, "warmup", side_effect=RuntimeError("TradeStation error"))

        monitor.send_signal_stats()

        assert alerts[0].splitlines()[-1] == "no data: META"

    def test_sent_once_per_session(self, tmp_path, mocker):
        monitor, alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD"],
                                        stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        mocker.patch.object(monitor_module, "signal_stats", return_value="signal stats ...")
        monitor.send_signal_stats()
        restarted, restarted_alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD"],
                                                    stats_daily_loader=lambda tickers, session: {})
        restarted.prepare()

        restarted.send_signal_stats()

        assert (len(alerts), restarted_alerts) == (1, [])

    def test_history_requests_take_the_client_lock(self, tmp_path, mocker):
        monitor, _ = self._monitor(tmp_path, mocker, stats_tickers=["AMD", "META"],
                                   stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        mocker.patch.object(monitor_module, "signal_stats", return_value="signal stats ...")
        held = []
        monitor.client.warmup = lambda tickers, start, end: held.append(monitor.client_lock.locked()) or {}

        monitor.send_signal_stats()

        assert held == [True]

    def test_earnings_windows_reach_the_stats(self, tmp_path, mocker):
        release = ET.localize(datetime(2026, 10, 5, 16, 5))
        monitor, _ = self._monitor(tmp_path, mocker, stats_tickers=["AMD"], releases={"AMD": [release]},
                                   stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()
        stats = mocker.patch.object(monitor_module, "signal_stats", return_value="signal stats ...")

        monitor.send_signal_stats()

        assert date(2026, 10, 5) in stats.call_args.args[2]["AMD"]["eve"]

    def test_end_to_end_message(self, tmp_path, mocker):
        monitor, alerts = self._monitor(tmp_path, mocker, stats_tickers=["AMD"],
                                        stats_daily_loader=lambda tickers, session: {})
        monitor.prepare()

        monitor.send_signal_stats()

        assert alerts[0].splitlines()[0] == "[wave] signal stats, last 1 session (10-05 to 10-05), 1 ticker:"

    def test_run_starts_the_stats_thread(self, tmp_path, mocker):
        clock = _Clock("2026-10-06 16:10")
        monitor, _ = _monitor(tmp_path, {"AMD": []}, clock, stats_tickers=["AMD"])
        mocker.patch.object(monitor, "prepare")
        mocker.patch.object(monitor, "start_stream")
        mocker.patch.object(monitor, "finish")
        thread = mocker.patch.object(monitor_module.threading, "Thread")

        monitor.run()

        assert thread.call_args.kwargs["target"] == monitor.send_signal_stats
        thread.return_value.start.assert_called_once()


class TestLoadDailyCloseSeries:
    def test_closes_before_the_session_by_date(self, mocker):
        daily = pd.DataFrame({"close": [10.0, 11.0, 12.0]},
                             index=pd.to_datetime(["2026-10-02", "2026-10-05", "2026-10-06"]))
        mocker.patch.object(monitor_module, "fetch_daily_bars", return_value={"AMD": daily})

        closes = monitor_module._load_daily_close_series(["AMD", "META"], date(2026, 10, 6))

        assert closes["AMD"].to_dict() == {date(2026, 10, 2): 10.0, date(2026, 10, 5): 11.0}
        assert closes["META"].empty


class TestReversalAfterErrors:
    def test_watch_error_rebuilds_the_watch(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 11:00")
        monitor, _ = _monitor(tmp_path, {"AMD": []}, clock)
        monitor.prepare()
        broken = monitor.reversal_watches["AMD"]
        mocker.patch.object(broken, "update", side_effect=ZeroDivisionError)

        monitor._on_five_min_bar("AMD", _bar("2026-09-01 11:00", 100.0, 100.2, 99.8, 100.0))

        assert monitor.reversal_watches["AMD"] is not broken

    def test_failed_backfill_pauses_reversal_alerts(self, tmp_path, mocker):
        clock = _Clock("2026-09-01 11:30")
        monitor, alerts = _monitor(tmp_path, {"AMD": []}, clock)
        monitor.prepare()
        mocker.patch.object(monitor.client, "fetch_bars", side_effect=RuntimeError("down"))
        monitor.backfill = (_ts("2026-09-01 10:30"), _ts("2026-09-01 10:46"))
        monitor._run_backfill(clock())
        mocker.patch.object(monitor.reversal_watches["AMD"], "update", return_value=[_reversal("2026-09-01 11:30")])

        monitor._on_five_min_bar("AMD", _bar("2026-09-01 11:30", 100.0, 100.2, 99.8, 100.0))

        assert alerts == []


class TestReversalArguments:
    def test_all_patterns_by_default(self):
        args = parse_args(["run"])

        assert (args.reversal_patterns, args.no_reversal_alerts) == (["piercing", "push", "long_tail"], False)

    def test_chosen_patterns(self):
        assert parse_args(["run", "--reversal-patterns", "push", "piercing"]).reversal_patterns == ["push", "piercing"]

    def test_unknown_pattern_is_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(["run", "--reversal-patterns", "engulfing"])


class TestSignalStatsArguments:
    def test_the_21_setup_tape_tickers_by_default(self):
        args = parse_args(["run"])

        assert (len(args.stats_tickers), args.no_signal_stats) == (21, False)

    def test_chosen_tickers(self):
        assert parse_args(["run", "--stats-tickers", "AMD", "META"]).stats_tickers == ["AMD", "META"]

    def test_turned_off(self):
        assert parse_args(["run", "--no-signal-stats"]).no_signal_stats


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


class TestMarketCalendar:
    @pytest.mark.parametrize("day", [date(2027, 1, 18), date(2027, 2, 15), date(2026, 6, 19), date(2026, 11, 26)])
    def test_holidays_are_not_trading_days(self, day):
        assert not is_trading_day(day)

    def test_columbus_day_trades(self):
        assert is_trading_day(date(2026, 10, 12))

    def test_previous_trading_day_skips_the_weekend_and_mlk(self):
        assert previous_trading_day(date(2027, 1, 19)) == date(2027, 1, 15)

    @pytest.mark.parametrize("day, close", [
        (date(2026, 11, 27), time(13, 0)),
        (date(2026, 12, 24), time(13, 0)),
        (date(2025, 7, 3), time(13, 0)),
        (date(2026, 10, 6), time(16, 0)),
    ])
    def test_early_closes(self, day, close):
        assert session_close(day) == close


class TestEarlyCloseDay:
    def test_close_alert_moves_with_the_close_and_skips_the_overnight_hold(self, tmp_path):
        clock = _Clock("2026-11-27 12:50")
        history = {"AMD": _history([("2026-11-27 12:45", 102.0)])}
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long", "overnight always"]}, clock, history)
        monitor.prepare()
        monitor.trades.append(LiveTrade(ticker="AMD", setup="drive long", exit_mode="eod", entry_time=_ts(
            "2026-11-27 09:30"), side=1, entry=101.0, stop=100.0, target=103.0, risk=1.0,
            last_bar=_ts("2026-11-27 12:45")))

        monitor.tick()

        assert alerts == ["[wave] SELL AMD | drive long | at the close (MOC) | +0.99% at 102.00"]
        assert (monitor.last_bar, monitor.session_end) == (time(12, 55), time(13, 5))


class TestDataOutage:
    def _started(self, tmp_path, clock):
        monitor, alerts = _monitor(tmp_path, {"AMD": ["drive long"]}, clock)
        monitor.prepare()
        monitor.start_stream()
        return monitor, alerts

    def test_alerts_once_when_data_stops_and_again_when_it_returns(self, tmp_path):
        clock = _Clock("2026-10-06 09:00")
        monitor, alerts = self._started(tmp_path, clock)

        for stamp in ("2026-10-06 09:34", "2026-10-06 09:35", "2026-10-06 09:40"):
            clock.set(stamp)
            monitor.tick()
        assert alerts == ["[wave] no market data since 09:30; no alerts until it returns (check the feed / data "
                          "subscription, see the log)"]

        clock.set("2026-10-06 09:41")
        monitor.on_minute_bar(SimpleNamespace(symbol="AMD", timestamp=_ts("2026-10-06 09:40"), open=1, high=1, low=1,
                                              close=1))
        assert alerts[-1].startswith("[wave] market data restored at 09:41 after a gap from 09:30")
        assert monitor.backfill == (_ts("2026-10-06 09:30"), _ts("2026-10-06 09:41"))

    def test_reconnects_at_most_every_timeout(self, tmp_path, mocker):
        clock = _Clock("2026-10-06 09:00")
        monitor, _ = self._started(tmp_path, clock)
        reconnect = mocker.spy(monitor.client, "reconnect")

        for stamp in ("2026-10-06 09:33", "2026-10-06 09:34", "2026-10-06 09:36"):
            clock.set(stamp)
            monitor.tick()

        assert reconnect.call_count == 2


class TestLateStart:
    def _hold(self):
        return LiveTrade(ticker="AMD", setup="overnight always", exit_mode="next open",
                         entry_time=_ts("2026-10-05 15:45"), side=1, entry=100.0, status="open",
                         last_bar=_ts("2026-10-05 15:55"))

    def test_sell_alert_after_the_open_says_now(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps({"session": "2026-10-05", "trades": [self._hold().to_dict()]}))
        clock = _Clock("2026-10-06 11:00")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock)
        monitor.prepare()

        monitor.tick()

        assert "SELL AMD | overnight always | now (monitor started after the open)" in alerts[0]

    def test_exit_on_a_later_first_bar_is_marked_late(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps({"session": "2026-10-05", "trades": [self._hold().to_dict()]}))
        clock = _Clock("2026-10-06 11:05")
        monitor, _ = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock)
        monitor.prepare()

        monitor._on_five_min_bar("AMD", _bar("2026-10-06 11:00", 104.0, 104.0, 104.0, 104.0))

        assert (monitor.trades[0].outcome, monitor.trades[0].exit_price) == ("late open", 104.0)


class TestFinish:
    def test_state_is_saved_when_the_summary_notification_fails(self, tmp_path):
        clock = _Clock("2026-10-06 16:05")
        monitor, _ = _monitor(tmp_path, {"AMD": ["overnight always"]}, clock)
        monitor.prepare()
        monitor.trades.append(LiveTrade(ticker="AMD", setup="overnight always", exit_mode="next open",
                                        entry_time=_ts("2026-10-06 15:45"), side=1, entry=100.0, status="open",
                                        last_bar=_ts("2026-10-06 15:55")))

        def broken(message):
            raise OSError("telegram down")

        monitor.notify = broken
        monitor.finish()

        saved = json.loads((tmp_path / "state.json").read_text())
        assert [t["setup"] for t in saved["trades"]] == ["overnight always"]

    def test_missing_daily_history_is_reported_at_start(self, tmp_path):
        clock = _Clock("2026-10-06 09:00")
        monitor, alerts = _monitor(tmp_path, {"AMD": ["overnight ma200"]}, clock, closes={"AMD": [100.0] * 50})

        monitor.prepare()

        assert alerts == ["[wave] overnight moving-average filter has too little daily history for AMD; their "
                          "filtered overnight holds will not fire today"]


class TestStartOnMacOS:
    def test_start_launches_a_detached_run_instead_of_forking(self, tmp_path, mocker):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"tickers": {"AMD": ["drive long"]}}))
        mocker.patch.object(monitor_module.sys, "platform", "darwin")
        mocker.patch.object(monitor_module, "_load_config")
        daemonize = mocker.patch.object(monitor_module, "_daemonize")
        popen = mocker.patch.object(monitor_module.subprocess, "Popen", return_value=SimpleNamespace(pid=4321))
        log_file = str(tmp_path / "monitor.log")

        monitor_module.main(["start", "--config", str(config), "--pid-file", str(tmp_path / "m.pid"),
                             "--log-file", log_file, "--market-data-source", "tradestation"])

        daemonize.assert_not_called()
        command = popen.call_args.args[0]
        assert command[1:4] == ["-m", monitor_module.MODULE, "run"]
        assert command[-3:] == ["--detached", "--log-file", log_file]
        assert popen.call_args.kwargs["start_new_session"] is True


class TestConfigRefresh:
    def test_refresh_runs_the_setup_report_then_ranks_its_last_63_sessions(self, tmp_path, mocker):
        report_dir = tmp_path / "report"
        mocker.patch.object(monitor_module, "refresh_report", return_value=report_dir)
        generate = mocker.patch.object(monitor_module, "generate_config", return_value={
            "window": "w", "types": ["long"], "tickers": {}})
        config_path = tmp_path / "config.json"

        monitor_module.main(["config", "--refresh", "--tickers", "AMD", "META", "--types", "long", "overnight",
                             "--min-trades", "3", "--config", str(config_path), "--workers", "0"])

        assert monitor_module.refresh_report.call_args.args == (["AMD", "META"], 63, 1)
        assert generate.call_args.args == (str(report_dir), ["AMD", "META"], 3, ["long", "overnight"], 3, 63)
        assert json.loads(config_path.read_text())["window"] == "w"
