from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import wave_setup_selection_research as research
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_selection_research import (
    momentum_keep,
    pick_setups,
    setup_features,
    simulate,
    ticker_features,
)

SESSIONS = np.array([date(2026, 1, 1) + timedelta(days=i) for i in range(80)], dtype=object)


def _candidate(setup, setup_type, tot63, n63=5, ma50gap=0.1, **extra):
    return dict({"ticker": "AMD", "setup": setup, "type": setup_type, "tot63": tot63, "n63": n63,
                 "ma50gap": ma50gap, "tot21": 1.0, "fwd5": 1.0}, **extra)


class TestSetupFeatures:
    def test_totals_count_only_the_lookback_before_the_decision_day(self):
        days = np.array([SESSIONS[5], SESSIONS[60], SESSIONS[70], SESSIONS[75]], dtype=object)
        returns = np.array([9.0, 1.0, 2.0, 50.0])

        features = setup_features(returns, days, SESSIONS, 72)

        assert (features["n63"], features["tot63"], features["tot10"]) == (2, pytest.approx(3.0), pytest.approx(2.0))

    def test_both_horizons_needs_one_and_three_month_gains(self):
        days = np.array([SESSIONS[20], SESSIONS[70]], dtype=object)
        returns = np.array([5.0, -1.0])

        assert setup_features(returns, days, SESSIONS, 75)["both_horizons"] == -np.inf


class TestTickerFeatures:
    def test_uses_only_bars_before_the_day(self):
        index = pd.Index([date(2026, 1, 1) + timedelta(days=i) for i in range(130)])
        closes = pd.Series(np.linspace(100, 229, 130), index=index)
        day = pd.DataFrame({"open": closes, "high": closes + 1, "low": closes - 1, "close": closes})

        features = ticker_features(day, index[121])

        assert features["ret20"] == pytest.approx(220 / 200 - 1)
        assert features["ret120"] == pytest.approx(220 / 100 - 1)


class TestPickSetups:
    def _group(self):
        return pd.DataFrame([
            _candidate("drive short", "short", 9.0), _candidate("drive long", "long", 4.0, ma50gap=-0.1),
            _candidate("overnight always", "overnight", 3.0), _candidate("overnight ma200", "overnight", 2.0),
            _candidate("bounce long", "long", 6.0, n63=2),
        ])

    def test_r0_ranks_all_types_one_per_family(self):
        picks = pick_setups(self._group(), rule="R0")

        assert [p["setup"] for p in picks] == ["drive short", "drive long", "overnight always"]

    def test_r1_keeps_long_and_overnight_only(self):
        assert [p["setup"] for p in pick_setups(self._group(), rule="R1")] == ["drive long", "overnight always"]

    def test_r2_needs_long_setups_above_ma50(self):
        assert [p["setup"] for p in pick_setups(self._group(), rule="R2")] == ["overnight always"]

    def test_r3_skips_unhealthy_types(self):
        picks = pick_setups(self._group(), rule="R3", type_health={"long": 2.0, "overnight": -1.0})

        assert [p["setup"] for p in picks] == ["drive long"]


class TestMomentumKeep:
    def test_keeps_the_top_tickers_positive_only(self):
        rows = pd.DataFrame({"ticker": ["A", "B", "C"], "ret20": [0.2, -0.1, 0.05]})

        assert momentum_keep(rows, "ret20", 3, positive_only=True) == ["A", "C"]


class TestSimulate:
    def test_dollars_per_week_and_capital_used(self, mocker):
        mocker.patch.object(research, "SLEEVE", 1000.0)
        frame = pd.DataFrame([
            _candidate("drive long", "long", 4.0, d=date(2026, 3, 2), period="calibration", fwd5=2.0, ret20=0.3),
            dict(_candidate("drive long", "long", 4.0, d=date(2026, 3, 2), period="calibration", fwd5=-1.0, ret20=-0.2),
                 ticker="META"),
        ])

        everyone = simulate(frame, "calibration", rule="R1")
        top_one = simulate(frame, "calibration", rule="R1", momentum="ret20", top_k=1)

        assert (everyone["total"], everyone["capital"]) == (pytest.approx(10.0), 20000.0)
        assert (top_one["total"], top_one["return_pct"]) == (pytest.approx(20.0), pytest.approx(0.2))
