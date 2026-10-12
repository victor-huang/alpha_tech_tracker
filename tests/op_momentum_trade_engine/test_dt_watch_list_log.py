from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.dt_watch_list_log import (
    _option_volume_spike_line,
)


def _volume(total, call, put, spike_sides):
    return {"option_volume": {
        "total_ratio": total, "call_ratio": call, "put_ratio": put, "spike_sides": spike_sides,
    }}


class TestOptionVolumeSpikeLine:
    def test_lists_spiking_tickers_with_side_ratios(self):
        results = {"PLTR": _volume(3.4, 3.9, 2.6, ["total", "call", "put"])}

        line = _option_volume_spike_line(results)

        assert line == "**Options-volume spikes**: PLTR (3.4x total, calls 3.9x, puts 2.6x)\n"

    def test_skips_tickers_without_a_spike(self):
        results = {"SPOT": _volume(1.1, 1.0, 1.2, [])}

        assert _option_volume_spike_line(results).startswith("No options-volume spikes")

    def test_shows_na_for_a_side_with_no_baseline(self):
        results = {"FN": _volume(2.5, 2.5, None, ["total", "call"])}

        assert "puts n/a" in _option_volume_spike_line(results)

    def test_ignores_error_rows(self):
        results = {"MDB": {"option_volume": {"error": "no daily bars"}}}

        assert _option_volume_spike_line(results).startswith("No options-volume spikes")
