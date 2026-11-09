import pandas as pd

from alpha_tech_tracker.research.paper_lists import DETAIL_COLUMNS, entry_checkpoints, latest_list, paper_rules

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
        assert {name: tier for name, (tier, _, _) in paper_rules().items()} == {
            "large_recommended": "Large", "large_previous": "Large", "small_recommended": "Small"}

    def test_recommended_lists_use_trailing_stops(self):
        rules = paper_rules()

        assert (rules["large_recommended"][2], rules["small_recommended"][2]) == ("trail25", "trail15")
