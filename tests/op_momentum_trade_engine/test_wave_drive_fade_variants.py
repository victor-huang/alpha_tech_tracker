from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_drive_fade_variants import FILTERS, evaluate


def _trade(day, side, net_pct, stretch=0.0, above_ma50=True, above_ma200=True, ticker="AMD"):
    return {"ticker": ticker, "day": day, "side": side, "buffer": 0.1, "exit": "target", "net_pct": net_pct,
            "ma200_stretch": stretch, "above_ma50": above_ma50, "above_ma200": above_ma200, "ret20": 0.0,
            "first_bar_ratio": 1.0, "gap_adr": 0.0}


class TestFilters:
    def test_ma200_stretch_counts_only_toward_the_average(self):
        trades = pd.DataFrame([_trade(date(2026, 1, 5), -1, 1.0, stretch=12.0),
                               _trade(date(2026, 1, 6), 1, 1.0, stretch=12.0)])

        assert list(FILTERS["MA200 stretch >= 10"](trades)) == [True, False]

    def test_correction_is_below_ma50_and_above_ma200(self):
        trades = pd.DataFrame([_trade(date(2026, 1, 5), -1, 1.0, above_ma50=False),
                               _trade(date(2026, 1, 6), -1, 1.0, above_ma50=False, above_ma200=False)])

        assert list(FILTERS["correction (below MA50, above MA200)"](trades)) == [True, False]


class TestEvaluate:
    def test_splits_results_into_calibration_and_test(self):
        trades = pd.DataFrame([_trade(date(2026, 1, 5), -1, 1.0), _trade(date(2026, 8, 3), -1, -2.0, ticker="META")])

        row = evaluate(trades, date(2026, 7, 2)).query("filter == 'none' and stop == 0.1 and exit == 'target'").iloc[0]

        assert (row["calibration_n"], row["calibration_total%"]) == (1, pytest.approx(1.0))
        assert (row["test_n"], row["test_total%"], row["test_tickers+"]) == (1, pytest.approx(-2.0), "0/1")
