import pandas as pd

from alpha_tech_tracker.research.historical import validate as hv


def _closes(symbol, closes, start="2016-01-04"):
    return pd.DataFrame({"symbol": symbol, "day": pd.bdate_range(start, periods=len(closes)), "close": closes})


def _panel(rows):
    return pd.DataFrame(rows, columns=["symbol", "tier"])


class TestReturnAgreement:
    def test_identical_returns_on_different_bases_agree(self):
        out = hv.return_agreement(_closes("X", [10.0, 11.0, 12.0]), _closes("X", [5.0, 5.5, 6.0]))

        assert out.loc["X", "bad_days"] == 0

    def test_counts_days_that_differ(self):
        out = hv.return_agreement(_closes("X", [10.0, 11.0, 12.0]), _closes("X", [10.0, 10.0, 12.0]))

        assert out.loc["X", "bad_days"] == 2

    def test_only_symbols_in_both(self):
        out = hv.return_agreement(_closes("X", [1.0, 2.0]), _closes("Y", [1.0, 2.0]))

        assert out.empty


class TestComparePanels:
    def test_counts_added_and_dropped_by_tier(self):
        old = _panel([("AAPL", "Large"), ("ZZZ", "Small")])
        new = _panel([("AAPL", "Large"), ("CELG", "Large")])

        universe = hv.compare_panels(old, new)["universe"]

        assert universe.loc["Large"].tolist() == [1, 2, 1, 0]
        assert universe.loc["Small"].tolist() == [1, 0, 0, 1]

    def test_tier_agreement_counts_shared_names(self):
        old = _panel([("AAPL", "Large"), ("X", "Mid")])
        new = _panel([("AAPL", "Large"), ("X", "Large")])

        agreement = hv.compare_panels(old, new)["tier_agreement"]

        assert agreement.loc["Mid", "Large"] == 1


class TestCompareForwardTests:
    def test_puts_old_and_new_side_by_side(self):
        row = {"rule": "trend_template", "tier": "Large", "flagged_per_checkpoint": 55.0, "hit_rate": 0.07,
               "lift": 1.4, "vol_matched_lift": 1.2}
        new = dict(row, lift=1.3)

        out = hv.compare_forward_tests(pd.DataFrame([row]), pd.DataFrame([new]))

        assert out[["lift_old", "lift_new"]].values.tolist() == [[1.4, 1.3]]
