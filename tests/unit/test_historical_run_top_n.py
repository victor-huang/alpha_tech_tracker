import pandas as pd
import pytest

from alpha_tech_tracker.research import selection_filters as sf
from alpha_tech_tracker.research.historical import run_top_n as rt
from alpha_tech_tracker.research.historical.data import HISTORICAL_CACHE_DIR, HistoricalData


@pytest.fixture
def restore_selection_filters(mocker):
    for name in ("AlpacaData", "BENCHMARKS", "FundamentalsCache", "parse_args"):
        mocker.patch.object(sf, name, getattr(sf, name))


class TestSecurityCiks:
    def test_maps_securities_with_a_cik(self, tmp_path):
        pd.DataFrame([{"security": "NA", "cik": 1}, {"security": "WM~2008", "cik": None}]).to_csv(
            tmp_path / "securities.csv", index=False)

        assert rt.security_ciks(str(tmp_path)) == {"NA": 1}


class TestInstall:
    def test_parse_args_points_at_historical_panels_and_cache(self, restore_selection_filters):
        rt.install({})

        args = sf.parse_args(["--years", "2016"])

        assert (args.panel_dir, args.cache_dir, args.today.isoformat()) == (rt.PANEL_DIR, HISTORICAL_CACHE_DIR,
                                                                              rt.DATA_END)

    def test_swaps_in_historical_data(self, restore_selection_filters):
        rt.install({})

        assert sf.AlpacaData is HistoricalData

    def test_fundamentals_use_security_ciks(self, restore_selection_filters):
        rt.install({"TWX": 1105705})

        assert sf.FundamentalsCache("/nowhere").ticker_ciks("agent") == {"TWX": 1105705}

    def test_benchmarks_without_iwm(self, restore_selection_filters):
        rt.install({})

        assert sf.BENCHMARKS == ["SPY", "QQQ"]
