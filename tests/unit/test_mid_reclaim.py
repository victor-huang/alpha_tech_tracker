import numpy as np
import pandas as pd

from alpha_tech_tracker.research.mid_reclaim import (
    FRESH_FIRST,
    VOLUME_SURGE,
    MidSetting,
    attach_features,
    order_candidates,
    reclaim_features,
    reclaim_list,
    run_reclaim_book,
    settings,
)

DAYS = pd.bdate_range("2025-01-01", periods=260)


def _list_panel(**overrides):
    row = {"checkpoint": DAYS[-1], "tier": "Mid", "symbol": "A", "above_averages": True, "days_since_reclaim": 10,
           "ma200_slope": 0.01, "rev_yoy": 0.30, "volume_surge": 1.5}
    row.update(overrides)
    return pd.DataFrame([row])


class TestReclaimFeatures:
    def _close(self):
        dip = np.r_[np.full(230, 100.0), np.full(20, 90.0), np.full(10, 120.0)]
        return pd.DataFrame({"A": dip}, index=DAYS)

    def test_counts_days_since_last_close_below_200_day(self):
        close = self._close()
        out = reclaim_features(close, pd.DataFrame(1.0, index=DAYS, columns=["A"]))

        assert out["days_since_reclaim"]["A"].iloc[-1] == 10

    def test_above_averages_after_the_reclaim(self):
        close = self._close()
        out = reclaim_features(close, pd.DataFrame(1.0, index=DAYS, columns=["A"]))

        assert bool(out["above_averages"]["A"].iloc[-1]) is True

    def test_volume_surge_compares_recent_to_prior_volume(self):
        volume = pd.DataFrame({"A": np.r_[np.full(250, 1.0), np.full(10, 3.0)]}, index=DAYS)
        out = reclaim_features(self._close(), volume)

        assert round(out["volume_surge"]["A"].iloc[-1], 6) == 3.0


class TestAttachFeatures:
    def test_reads_features_at_checkpoint_for_tier_rows_only(self):
        panel = pd.DataFrame({"checkpoint": [DAYS[-1], DAYS[-1]], "tier": ["Mid", "Large"], "symbol": ["A", "B"]})
        features = {"volume_surge": pd.DataFrame({"A": 2.0, "B": 5.0}, index=DAYS)}

        out = attach_features(panel, features)

        assert out[["symbol", "volume_surge"]].values.tolist() == [["A", 2.0]]


class TestReclaimList:
    def test_keeps_a_name_passing_every_rule(self):
        assert reclaim_list(_list_panel(), MidSetting()) == {DAYS[-1]: ["A"]}

    def test_drops_a_stale_reclaim(self):
        assert reclaim_list(_list_panel(days_since_reclaim=41), MidSetting()) == {}

    def test_drops_slow_sales_growth(self):
        assert reclaim_list(_list_panel(rev_yoy=0.20), MidSetting()) == {}

    def test_drops_a_falling_200_day(self):
        assert reclaim_list(_list_panel(ma200_slope=-0.001), MidSetting()) == {}

    def test_orders_by_volume_surge(self):
        panel = pd.concat([_list_panel(symbol="A", volume_surge=1.1), _list_panel(symbol="B", volume_surge=2.0)])

        assert reclaim_list(panel, MidSetting())[DAYS[-1]] == ["B", "A"]


class TestOrderCandidates:
    def test_volume_surge_keeps_list_order(self):
        assert order_candidates(["A", "B", "C"], {"A"}, VOLUME_SURGE) == ["A", "B", "C"]

    def test_fresh_first_moves_previously_held_names_back(self):
        assert order_candidates(["A", "B", "C"], {"A"}, FRESH_FIRST) == ["B", "C", "A"]


class TestRunReclaimBook:
    CPS = [DAYS[0], DAYS[5]]

    def _close(self, a, b):
        return pd.DataFrame({"A": a, "B": b}, index=DAYS[:10])

    def test_splits_equally_and_compounds(self):
        close = self._close(np.r_[np.full(5, 100.0), np.full(5, 110.0)], np.full(10, 100.0))

        book = run_reclaim_book({self.CPS[0]: ["A", "B"]}, close, self.CPS[:1], cost=0.0)

        assert round(book["ret"].iloc[0], 4) == 0.05

    def test_sells_a_name_that_leaves_the_list(self):
        close = self._close(np.full(10, 100.0), np.r_[np.full(6, 100.0), np.full(4, 50.0)])

        book = run_reclaim_book({self.CPS[0]: ["B"], self.CPS[1]: ["A"]}, close, self.CPS, cost=0.0)

        assert book["ret"].tolist() == [0.0, 0.0]

    def test_trailing_stop_sells_to_cash(self):
        close = self._close(np.r_[100.0, 120.0, 100.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0], np.full(10, 100.0))

        book = run_reclaim_book({self.CPS[0]: ["A"]}, close, self.CPS[:1], cost=0.0)

        assert book["exits"].iloc[0] == 1
        assert round(book["ret"].iloc[0], 4) == 0.0

    def test_limits_holdings_to_n(self):
        close = self._close(np.full(10, 100.0), np.full(10, 100.0))

        book = run_reclaim_book({self.CPS[0]: ["A", "B"]}, close, self.CPS[:1], n=1, cost=0.0)

        assert book["names"].iloc[0] == 1

    def test_fresh_first_buys_a_never_held_name_over_a_returning_one(self):
        cps = [DAYS[0], DAYS[5], DAYS[10]]
        close = pd.DataFrame({"A": np.full(15, 100.0), "B": np.r_[np.full(11, 100.0), np.full(4, 150.0)]},
                             index=DAYS[:15])
        lists = {cps[0]: ["A"], cps[2]: ["A", "B"]}

        book = run_reclaim_book(lists, close, cps, ranking=FRESH_FIRST, n=1, cost=0.0)

        assert round(book["ret"].iloc[2], 4) == 0.5

    def test_volume_surge_buys_the_returning_name_when_listed_first(self):
        cps = [DAYS[0], DAYS[5], DAYS[10]]
        close = pd.DataFrame({"A": np.full(15, 100.0), "B": np.r_[np.full(11, 100.0), np.full(4, 150.0)]},
                             index=DAYS[:15])
        lists = {cps[0]: ["A"], cps[2]: ["A", "B"]}

        book = run_reclaim_book(lists, close, cps, ranking=VOLUME_SURGE, n=1, cost=0.0)

        assert book["ret"].iloc[2] == 0.0

    def test_charges_cost_on_turnover(self):
        close = self._close(np.full(10, 100.0), np.full(10, 100.0))

        book = run_reclaim_book({self.CPS[0]: ["A"]}, close, self.CPS[:1], cost=0.01)

        assert round(book["ret"].iloc[0], 4) == -0.01


class TestSettings:
    def test_grid_covers_every_combination(self):
        assert len(settings()) == 54

    def test_recommended_setting_is_in_the_grid(self):
        assert MidSetting() in settings()
