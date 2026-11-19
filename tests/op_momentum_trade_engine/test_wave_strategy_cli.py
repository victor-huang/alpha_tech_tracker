import json
import signal

import pytest

from alpha_tech_tracker.op_momentum_strategy import op_momentum_trade_engine as engine_cli
from alpha_tech_tracker.op_momentum_strategy.cli import wave as wave_cli
from alpha_tech_tracker.op_momentum_strategy.cli.args import WAVE_PID_FILE, parse_args
from alpha_tech_tracker.op_momentum_strategy.cli.daemon import _PID_FILE


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "monitor_config.json"
    path.write_text(json.dumps({"tickers": {
        "AMD": [{"setup": "drive long"}, {"setup": "overnight always"}],
        "APP": [{"setup": "pullback long C1"}],
    }}))
    return str(path)


def _wave_args(config_file, *extra):
    return parse_args(["run", "--strategy", "wave-setups", "--wave-config", config_file] + list(extra))


class TestParseArgs:
    def test_the_or_engine_is_the_default_with_its_own_pid_file(self):
        args = parse_args(["start"])

        assert (args.strategy, args.pid_file) == ("or", _PID_FILE)

    def test_wave_setups_uses_its_own_pid_file(self, config_file):
        assert _wave_args(config_file).pid_file == WAVE_PID_FILE

    def test_an_explicit_pid_file_is_kept(self, config_file):
        assert _wave_args(config_file, "--pid-file", "/tmp/x.pid").pid_file == "/tmp/x.pid"

    def test_wave_setups_takes_the_monitors_flags(self, config_file):
        args = _wave_args(config_file, "--short-setups", "drive", "--short-gate", "qqq-ma50-down10",
                          "--trend-filters", "overnight", "--wave-balance", "30000", "--wave-slots", "6")

        assert (args.short_setups, args.short_gate, args.trend_filters, args.wave_balance, args.wave_slots) == (
            ["drive"], "qqq-ma50-down10", ["overnight"], 30000, 6)

    def test_wave_setups_refuses_replay_flags(self, config_file):
        with pytest.raises(SystemExit):
            _wave_args(config_file, "--replay-date", "2026-11-13")


class TestWaveSetups:
    def test_keeps_the_configs_setups_including_overnight_ones(self, config_file):
        setups = wave_cli.wave_setups(_wave_args(config_file, "--no-short-setups"))

        assert {t: [s.name for s in specs] for t, specs in setups.items()} == {
            "AMD": ["drive long", "overnight always"], "APP": ["pullback long C1"]}

    def test_adds_the_short_tickers_when_shorts_are_on(self, config_file):
        setups = wave_cli.wave_setups(_wave_args(config_file, "--short-tickers", "AMD", "MU"))

        assert sorted(setups) == ["AMD", "APP", "MU"]

    def test_the_off_gate_turns_the_shorts_off(self, config_file):
        assert wave_cli.wave_short_setups(_wave_args(config_file, "--short-gate", "off")) == []


class TestBuildWaveRunner:
    def test_passes_the_cli_options_to_the_runner(self, config_file, mocker):
        runner_cls = mocker.patch("alpha_tech_tracker.op_momentum_strategy.wave_strategy_runner.WaveStrategyRunner")
        mocker.patch("alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor.build_market_data_client")
        args = _wave_args(config_file, "--short-setups", "drive", "--short-gate", "always", "--wave-balance", "10000",
                          "--wave-slots", "4", "--drive-trail")

        wave_cli.build_wave_runner(args, execution_client=None, mock=True)

        kwargs = runner_cls.call_args.kwargs
        assert (kwargs["mock"], kwargs["balance"], kwargs["slots"], kwargs["short_setups"], kwargs["short_gate"],
                kwargs["short_tickers"], kwargs["drive_trail"]) == (
            True, 10000, 4, ["drive"], "always", ["AMD", "APP"], True)


class TestRunWaveStrategy:
    def test_sigterm_stops_the_session_and_restores_the_previous_handler(self, config_file, mocker):
        runner = mocker.Mock()
        runner.run.side_effect = lambda: signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        mocker.patch.object(wave_cli, "build_wave_runner", return_value=runner)
        previous = signal.getsignal(signal.SIGTERM)

        wave_cli.run_wave_strategy(_wave_args(config_file), None, True)

        assert signal.getsignal(signal.SIGTERM) is previous


class TestEngineEntryPoint:
    def test_wave_setups_runs_the_wave_runner_in_mock_without_a_broker(self, config_file, mocker):
        mocker.patch.object(engine_cli, "_configure_logging")
        run_wave = mocker.patch.object(engine_cli, "run_wave_strategy")
        build_client = mocker.patch.object(engine_cli, "build_execution_client")
        args = _wave_args(config_file, "--mock-trade-execution")

        engine_cli._run_foreground(args, windows=[], log_file="unused.log")

        assert run_wave.call_args.args[1:] == (None, True)
        build_client.assert_not_called()

    def test_live_wave_setups_builds_the_execution_client(self, config_file, mocker):
        mocker.patch.object(engine_cli, "_configure_logging")
        mocker.patch.object(engine_cli, "_build_sip_quote_client")
        run_wave = mocker.patch.object(engine_cli, "run_wave_strategy")
        client = mocker.patch.object(engine_cli, "build_execution_client").return_value

        engine_cli._run_foreground(_wave_args(config_file), windows=[], log_file="unused.log")

        assert run_wave.call_args.args[1:] == (client, False)

    def test_the_or_engine_does_not_touch_the_wave_runner(self, mocker):
        mocker.patch.object(engine_cli, "_configure_logging")
        mocker.patch.object(engine_cli, "build_execution_client")
        mocker.patch.object(engine_cli, "_build_sip_quote_client")
        mocker.patch.object(engine_cli, "_build_contract_selector")
        build_engine = mocker.patch.object(engine_cli, "build_engine")
        run_wave = mocker.patch.object(engine_cli, "run_wave_strategy")

        engine_cli._run_foreground(parse_args(["run"]), windows=[], log_file="unused.log")

        build_engine.return_value.run.assert_called_once()
        run_wave.assert_not_called()

    def test_wave_setups_logs_to_its_own_file(self):
        assert "wave_strategy_engine_" in wave_cli.wave_log_file()
