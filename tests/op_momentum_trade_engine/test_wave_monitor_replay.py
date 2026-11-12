import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy import wave_setup_monitor as wsm
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import wave_monitor_replay as replay

ET = wsm.ET
SESSION = date(2026, 11, 11)
WARMUP_SESSION = date(2026, 11, 10)


def _session_bars(day, start_price):
    stamps = pd.date_range(ET.localize(datetime.combine(day, wsm.MARKET_OPEN)), periods=78, freq="5min")
    prices = [start_price + 0.1 * i for i in range(len(stamps))]
    return pd.DataFrame({"open": prices, "high": [p + 0.5 for p in prices], "low": [p - 0.5 for p in prices],
                         "close": [p + 0.2 for p in prices]}, index=stamps)


def _bundle():
    bars = pd.concat([_session_bars(WARMUP_SESSION, 100.0), _session_bars(SESSION, 110.0)])
    days = [SESSION - timedelta(days=n) for n in range(300, 0, -1)]
    daily = pd.DataFrame({"high": [101.0] * len(days), "close": [100.0] * len(days)}, index=days)
    return replay.Bundle({"AMD": bars, "QQQ": bars.copy()}, {"AMD": daily, "QQQ": daily.copy()}, {"AMD": []})


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tickers": {"AMD": [{"setup": "drive long"}]}}))
    return path


@pytest.fixture
def no_signals(mocker):
    return mocker.patch.object(wsm, "evaluate_setup", return_value=[])


class TestBundle:
    def test_round_trips_through_its_folder(self, tmp_path):
        bundle = _bundle()
        bundle.releases = {"AMD": [ET.localize(datetime(2026, 11, 4, 16, 5))]}
        bundle.save(tmp_path)

        loaded = replay.Bundle.load(tmp_path)

        pd.testing.assert_frame_equal(loaded.bars["AMD"], bundle.bars["AMD"], check_freq=False)
        assert loaded.daily["AMD"].index[0] == bundle.daily["AMD"].index[0]
        assert loaded.releases == bundle.releases

    def test_daily_closes_stop_before_the_session(self):
        closes = _bundle().daily_closes_loader(["AMD", "MSFT"], SESSION)

        assert len(closes["AMD"]) == 300
        assert closes["MSFT"] == []

    def test_trend_daily_bars_stop_before_the_session(self):
        frame = _bundle().trend_daily_loader(["AMD"], SESSION - timedelta(days=10))["AMD"]

        assert max(frame.index) < SESSION - timedelta(days=10)
        assert list(frame.columns) == ["high", "close"]


class TestReplayClient:
    def test_history_is_the_bundle_between_start_and_end(self):
        client = replay.ReplayClient(_bundle())
        start = ET.localize(datetime.combine(SESSION, wsm.MARKET_OPEN))

        frame = client.fetch_bars(["AMD"], start, start + timedelta(minutes=5))["AMD"]

        assert list(frame.index) == [start]


class TestRunReplay:
    def test_monitor_rebuilds_every_streamed_session_bar(self, tmp_path, config, no_signals, mocker):
        built = mocker.spy(replay, "build_monitor")

        replay.run_replay(_bundle(), [SESSION], ["--config", str(config), "--no-short-setups"], tmp_path / "out")

        monitor = built.spy_return
        expected = _bundle().session_bars("AMD", SESSION)
        streamed = monitor.bars["AMD"][monitor.bars["AMD"].index.date == SESSION]
        pd.testing.assert_frame_equal(streamed, expected, check_freq=False)

    def test_writes_the_state_after_each_session(self, tmp_path, config, no_signals):
        out = replay.run_replay(_bundle(), [SESSION], ["--config", str(config), "--no-short-setups"], tmp_path / "out")

        state = json.loads((out / f"state_{SESSION}.json").read_text())
        assert state["session"] == SESSION.isoformat()
        assert not (out / "work").exists()

    def test_restart_stops_and_starts_a_fresh_monitor(self, tmp_path, config, no_signals):
        restart = ET.localize(datetime.combine(SESSION, datetime.strptime("12:00", "%H:%M").time()))

        out = replay.run_replay(_bundle(), [SESSION], ["--config", str(config), "--no-short-setups"],
                                tmp_path / "out", restarts=[restart])

        notes = (out / "notifications.txt").read_text()
        assert "[replay] process stop 2026-11-11 12:00" in notes
        assert "[replay] process start 2026-11-11 12:00" in notes

    def test_same_inputs_give_identical_outputs(self, tmp_path, config, no_signals):
        argv = ["--config", str(config), "--no-short-setups"]
        first = replay.run_replay(_bundle(), [SESSION], argv, tmp_path / "a")
        second = replay.run_replay(_bundle(), [SESSION], argv, tmp_path / "b")

        assert replay.compare_runs(first, second) == []


class TestCompareRuns:
    def test_reports_a_differing_file(self, tmp_path):
        for name, text in (("a", "x"), ("b", "y")):
            (tmp_path / name).mkdir()
            (tmp_path / name / "alerts.csv").write_text(text)

        assert replay.compare_runs(tmp_path / "a", tmp_path / "b") == ["alerts.csv: differs"]

    def test_reports_a_file_only_one_run_has(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "alerts.csv").write_text("x")

        assert replay.compare_runs(tmp_path / "a", tmp_path / "b") == [f"alerts.csv: only in {tmp_path / 'a'}"]


def _job(close=100.0, windows=None):
    bars = _session_bars(SESSION, close)
    return ("AMD", wsm.build_setup_spec("drive long"), bars, windows or {"reaction": set(), "eve": set()},
            bars.index[0])


class TestJobKey:
    def test_same_inputs_give_the_same_key(self):
        assert replay.job_key(_job()) == replay.job_key(_job())

    def test_different_bars_give_a_different_key(self):
        assert replay.job_key(_job(100.0)) != replay.job_key(_job(100.01))

    def test_different_earnings_windows_give_a_different_key(self):
        assert replay.job_key(_job()) != replay.job_key(_job(windows={"reaction": {SESSION}, "eve": set()}))


class TestEvaluationCache:
    def test_a_miss_evaluates_and_stores(self, tmp_path, mocker):
        evaluate = mocker.Mock(return_value=[{"setup": "drive long"}])
        cached = replay.EvaluationCache(tmp_path).wrap(evaluate)

        assert cached(_job()) == [{"setup": "drive long"}]
        evaluate.assert_called_once()

    def test_a_hit_skips_the_evaluation(self, tmp_path, mocker):
        replay.EvaluationCache(tmp_path).wrap(mocker.Mock(return_value=[]))(_job())
        evaluate = mocker.Mock(return_value=[])
        cache = replay.EvaluationCache(tmp_path)

        cache.wrap(evaluate)(_job())

        evaluate.assert_not_called()
        assert (cache.hits, cache.misses) == (1, 0)

    def test_run_replay_evaluates_through_the_cache(self, tmp_path, config, no_signals):
        cache = replay.EvaluationCache(tmp_path / "cache")

        replay.run_replay(_bundle(), [SESSION], ["--config", str(config), "--no-short-setups"], tmp_path / "out",
                          cache=cache)

        assert cache.misses == no_signals.call_count > 0
