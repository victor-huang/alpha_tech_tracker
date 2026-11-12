import pandas as pd

from alpha_tech_tracker.research.paper_lists import (
    DETAIL_COLUMNS,
    entry_checkpoints,
    hedge_list,
    latest_list,
    mid_list,
    paper_rules,
    ranked_from_lists,
)

CP1 = pd.Timestamp("2026-10-20")
CP2 = pd.Timestamp("2026-11-03")


def _book(held_by_checkpoint):
    return pd.DataFrame({"held": list(held_by_checkpoint.values())}, index=list(held_by_checkpoint.keys()))


def _panel(symbols):
    rows = [{"checkpoint": cp, "symbol": s, **{c: 1.0 for c in DETAIL_COLUMNS}} for cp in (CP1, CP2) for s in symbols]
    return pd.DataFrame(rows)


def _ranked(ranks):
    return pd.DataFrame([{"checkpoint": CP2, "symbol": s, "rank": r} for s, r in ranks.items()])


class TestLatestList:
    def test_marks_names_held_before_as_held(self):
        out = latest_list(_book({CP1: ["A"], CP2: ["A"]}), _ranked({"A": 1.0}), _panel(["A"]))

        assert out.set_index("symbol").loc["A", "status"] == "held"

    def test_marks_names_added_this_checkpoint_as_new(self):
        out = latest_list(_book({CP1: ["A"], CP2: ["A", "B"]}), _ranked({"A": 1.0, "B": 2.0}), _panel(["A", "B"]))

        assert out.set_index("symbol").loc["B", "status"] == "new"

    def test_lists_names_no_longer_held_as_dropped(self):
        out = latest_list(_book({CP1: ["A", "C"], CP2: ["A"]}), _ranked({"A": 1.0}), _panel(["A", "C"]))

        assert out.set_index("symbol").loc["C", "status"] == "dropped"

    def test_carries_latest_rank_and_details(self):
        out = latest_list(_book({CP1: [], CP2: ["A"]}), _ranked({"A": 3.0}), _panel(["A"]))

        row = out.iloc[0]
        assert (row["checkpoint"], row["rank"], row["ret_180d"]) == (CP2.date(), 3.0, 1.0)

    def test_treats_every_name_as_new_with_a_single_checkpoint(self):
        out = latest_list(_book({CP2: ["A"]}), _ranked({"A": 1.0}), _panel(["A"]))

        assert out["status"].tolist() == ["new"]

    def test_carries_entry_checkpoint_of_held_names(self):
        out = latest_list(_book({CP1: ["A"], CP2: ["A"]}), _ranked({"A": 1.0}), _panel(["A"]))

        assert out.iloc[0]["entry"] == CP1.date()


class TestEntryCheckpoints:
    def test_entry_is_start_of_unbroken_holding(self):
        cp0 = pd.Timestamp("2026-10-06")
        book = _book({cp0: ["A"], CP1: [], CP2: ["A"]})

        assert entry_checkpoints(book) == {"A": CP2}

    def test_entry_reaches_back_through_consecutive_checkpoints(self):
        cp0 = pd.Timestamp("2026-10-06")
        book = _book({cp0: ["A"], CP1: ["A"], CP2: ["A"]})

        assert entry_checkpoints(book) == {"A": cp0}


class TestPaperRules:
    def test_tracks_recommended_lists_and_previous_large_rule(self):
        assert {name: tier for name, (tier, _, _, _) in paper_rules().items()} == {
            "large_recommended": "Large", "large_previous": "Large", "large_top3": "Large",
            "small_recommended": "Small"}

    def test_large_top3_holds_three_names_with_the_large_stop(self):
        _, variant, exit_rule, n = paper_rules()["large_top3"]

        assert (n, exit_rule, variant.boost_groups) == (3, "trail25", ())

    def test_recommended_lists_use_trailing_stops(self):
        rules = paper_rules()

        assert (rules["large_recommended"][2], rules["small_recommended"][2]) == ("trail25", "trail15")


class TestHedgeList:
    def _panel(self):
        rows = [{"checkpoint": cp, "tier": "Large", "symbol": s, "ret_180d": r, "vol_60d": 0.04,
                 "dollar_volume_20d": 1e9, **{c: 1.0 for c in DETAIL_COLUMNS}}
                for cp in (CP1, CP2) for s, r in (("A", -0.5), ("B", 0.3))]
        return pd.DataFrame(rows)

    def _qqq(self, last_close):
        days = pd.bdate_range(end=CP2, periods=260)
        close = pd.Series(100.0, index=days)
        close.iloc[-1] = last_close
        return close

    def test_lists_weakest_names_at_the_last_checkpoint(self):
        out = hedge_list(self._panel(), self._qqq(100.0), [CP1, CP2])

        assert out["symbol"].tolist() == ["A", "B"] and out["checkpoint"].iloc[0] == CP2.date()

    def test_status_short_when_qqq_below_both_averages(self):
        out = hedge_list(self._panel(), self._qqq(50.0), [CP1, CP2])

        assert out["status"].iloc[0] == "short"

    def test_status_off_when_qqq_above_its_averages(self):
        out = hedge_list(self._panel(), self._qqq(100.0), [CP1, CP2])

        assert out["status"].iloc[0] == "off"


class TestRankedFromLists:
    def test_ranks_follow_list_order(self):
        out = ranked_from_lists({CP2: ["B", "A"]})

        assert out[["symbol", "rank"]].values.tolist() == [["B", 1], ["A", 2]]


class TestMidList:
    def _close(self, b_after_cp1=100.0):
        days = pd.bdate_range(CP1, CP2)
        b = [100.0 if d <= CP1 else b_after_cp1 for d in days]
        return pd.DataFrame({"A": 100.0, "B": b}, index=days)

    def test_keeps_a_name_still_listed_and_adds_a_new_one(self):
        out = mid_list({CP1: ["A"], CP2: ["A", "B"]}, self._close(), [CP1, CP2], _panel(["A", "B"]))

        assert dict(zip(out["symbol"], out["status"])) == {"A": "held", "B": "new"}

    def test_drops_a_name_that_left_the_list(self):
        out = mid_list({CP1: ["A", "B"], CP2: ["A"]}, self._close(), [CP1, CP2], _panel(["A", "B"]))

        assert dict(zip(out["symbol"], out["status"])) == {"A": "held", "B": "dropped"}

    def test_entry_is_the_first_checkpoint_held(self):
        out = mid_list({CP1: ["A"], CP2: ["A"]}, self._close(), [CP1, CP2], _panel(["A"]))

        assert out["entry"].iloc[0] == CP1.date()
