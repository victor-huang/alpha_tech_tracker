import os
from datetime import date

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.industry_groups import IndustryCache, add_group_strength, normalize_industries

CP = pd.Timestamp("2026-03-02")


def _stock(symbol, ret_120d, trend=True):
    close = 100.0 if trend else 80.0
    return {"checkpoint": CP, "symbol": symbol, "close": close, "ma50": 90.0, "ma200": 85.0, "ma200_rising": True,
            "ret_120d": ret_120d, "ret_60d": ret_120d / 2}


def _panel_and_industries(groups):
    rows, labels = [], []
    for industry, returns in groups.items():
        for i, r in enumerate(returns):
            symbol = f"{industry}{i}"
            rows.append(_stock(symbol, r))
            labels.append({"symbol": symbol, "sector": "S", "industry": industry})
    return pd.DataFrame(rows), pd.DataFrame(labels)


class TestNormalizeIndustries:

    def test_converts_share_class_symbols_and_drops_blank_labels(self):
        rows = pd.DataFrame({"symbol": ["BRK/B", "NOLBL", "AAPL "], "sector": ["Finance", "", "Technology"],
                             "industry": ["Insurance", "", "Computers"]})

        result = normalize_industries(rows)

        assert result["symbol"].tolist() == ["BRK.B", "AAPL"]


class TestIndustryCache:

    def test_reuses_a_fresh_file_without_fetching(self, tmp_path, mocker):
        path = str(tmp_path / "industries.csv")
        pd.DataFrame({"symbol": ["NA"], "sector": ["S"], "industry": ["I"]}).to_csv(path, index=False)
        fetcher = mocker.Mock()

        table = IndustryCache(path, fetcher).load(date.today())

        fetcher.assert_not_called()
        assert table["symbol"].tolist() == ["NA"]

    def test_refetches_a_stale_file(self, tmp_path, mocker):
        path = str(tmp_path / "industries.csv")
        pd.DataFrame({"symbol": ["OLD"], "sector": ["S"], "industry": ["I"]}).to_csv(path, index=False)
        stale = pd.Timestamp("2025-01-01").timestamp()
        os.utime(path, (stale, stale))
        fetcher = mocker.Mock(return_value=pd.DataFrame({"symbol": ["NEW"], "sector": ["S"], "industry": ["I"]}))

        table = IndustryCache(path, fetcher).load(date(2026, 3, 2))

        assert table["symbol"].tolist() == ["NEW"]
        assert pd.read_csv(path)["symbol"].tolist() == ["NEW"]


class TestAddGroupStrength:

    def test_stocks_in_the_strongest_group_are_flagged_top(self):
        groups = {g: [0.1 * k] * 5 for k, g in enumerate("ABCDEFGHIJ")}
        panel, industries = _panel_and_industries(groups)

        result = add_group_strength(panel, industries).set_index("symbol")

        assert result.loc["J0", "group_top20_120d"] == 1.0
        assert result.loc["A0", "group_top20_120d"] == 0.0
        assert result.loc["A0", "group_bottom20_120d"] == 1.0

    def test_small_groups_and_unlabelled_stocks_get_no_score(self):
        groups = {g: [0.1] * 5 for g in "ABCD"}
        groups["TINY"] = [0.9, 0.9]
        panel, industries = _panel_and_industries(groups)
        panel = pd.concat([panel, pd.DataFrame([_stock("NOLABEL", 0.5)])], ignore_index=True)

        result = add_group_strength(panel, industries).set_index("symbol")

        assert np.isnan(result.loc["TINY0", "group_top20_120d"])
        assert np.isnan(result.loc["NOLABEL", "group_top20_120d"])

    def test_leader_must_beat_its_group_and_be_in_an_uptrend(self):
        groups = {g: [0.1 * k] * 5 for k, g in enumerate("ABCDEFGHIJ")}
        groups["J"] = [0.9, 0.9, 0.9, 0.9, 2.0]
        panel, industries = _panel_and_industries(groups)

        result = add_group_strength(panel, industries).set_index("symbol")

        assert result.loc["J4", "leader_in_top_group"] == 1.0
        assert result.loc["J0", "leader_in_top_group"] == 0.0
