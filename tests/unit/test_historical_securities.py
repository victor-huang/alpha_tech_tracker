import pandas as pd

from alpha_tech_tracker.research.historical import securities as sec

T = pd.Timestamp


def _days(symbol, days, closes=None):
    return pd.DataFrame({"symbol": symbol, "day": pd.to_datetime(days),
                         "close": closes if closes is not None else [10.0] * len(days)})


def _listing(symbol, name, start=None, end=None, source="alphavantage", exchange="NYSE", status=None):
    return {"symbol": symbol, "name": name, "exchange": exchange, "asset_type": "Stock",
            "start": T(start) if start else pd.NaT, "end": T(end) if end else pd.NaT,
            "status": status, "source": source}


def _run(symbol, first, last, security=None):
    return pd.DataFrame([{"symbol": symbol, "first_day": T(first), "last_day": T(last), "days": 1,
                          "security": security or symbol}]).iloc[0]


class TestTradingRuns:
    def test_contiguous_days_make_one_run(self):
        runs = sec.trading_runs(_days("AAPL", ["2010-01-04", "2010-01-05", "2010-01-06"]))

        assert runs[["first_day", "last_day", "days"]].values.tolist() == [[T("2010-01-04"), T("2010-01-06"), 3]]

    def test_gap_over_a_year_splits_into_two_runs(self):
        runs = sec.trading_runs(_days("DELL", ["2013-10-28", "2013-10-29", "2015-01-23"]))

        assert runs["last_day"].tolist() == [T("2013-10-29"), T("2015-01-23")]

    def test_month_gap_with_price_break_splits(self):
        runs = sec.trading_runs(_days("X", ["2010-01-04", "2010-03-01"], [13.85, 31.30]))

        assert len(runs) == 2

    def test_month_gap_with_continuous_price_stays_one_run(self):
        runs = sec.trading_runs(_days("X", ["2010-01-04", "2010-03-01"], [10.0, 11.0]))

        assert len(runs) == 1

    def test_short_gap_with_price_break_stays_one_run(self):
        runs = sec.trading_runs(_days("X", ["2010-01-04", "2010-01-20"], [10.0, 30.0]), gap_days=30)

        assert len(runs) == 1

    def test_runs_never_span_two_symbols(self):
        days = pd.concat([_days("A", ["2010-01-04"]), _days("B", ["2010-01-05"])])

        assert sec.trading_runs(days)["symbol"].tolist() == ["A", "B"]

    def test_empty_input_gives_empty_runs(self):
        assert sec.trading_runs(_days("A", [])).empty


class TestLabelReused:
    def test_latest_run_keeps_plain_symbol(self):
        runs = sec.trading_runs(_days("DELL", ["2013-10-29", "2015-01-23"]))

        assert sec.label_reused(runs)["security"].tolist() == ["DELL~2013", "DELL"]

    def test_single_run_keeps_plain_symbol(self):
        runs = sec.trading_runs(_days("AAPL", ["2010-01-04"]))

        assert sec.label_reused(runs)["security"].tolist() == ["AAPL"]


class TestPlainSymbols:
    def test_drops_preferred_and_unit_symbols(self):
        listings = pd.DataFrame([_listing("BCV-P-A", "Bancroft pref"), _listing("BRK.B", "Berkshire"),
                                 _listing("AAPL", "Apple")])

        assert sec.plain_symbols(listings)["symbol"].tolist() == ["AAPL"]


class TestAlpacaListings:
    def test_keeps_ticker_spelled_na(self, tmp_path):
        path = tmp_path / "assets.csv"
        path.write_text("symbol,name,exchange,status,tradable\nNA,Nano Labs,NASDAQ,active,True\n")

        assert sec.alpaca_listings(str(path))["symbol"].tolist() == ["NA"]


class TestNormalize:
    def test_exchange_aliases(self):
        assert [sec.normalize_exchange(e) for e in ["NYSE MKT", "NYSE ARCA", "nasdaq", None]] == \
            ["AMEX", "ARCA", "NASDAQ", None]

    def test_name_drops_suffix_and_punctuation(self):
        assert sec.normalize_name("Apple Inc.") == sec.normalize_name("APPLE INC") == "APPLE"

    def test_name_of_missing_value_is_empty(self):
        assert sec.normalize_name(None) == ""


class TestNameForRun:
    def test_picks_listing_overlapping_the_run(self):
        listings = pd.DataFrame([_listing("WM", "Washington Mutual", "1990-01-01", "2008-09-26"),
                                 _listing("WM", "Waste Management", "2008-10-01")])

        name = sec.name_for_run(_run("WM", "2005-01-03", "2008-09-25"), {"WM": listings})

        assert name == "Washington Mutual"

    def test_falls_back_to_alpaca_name_for_latest_run(self):
        listings = pd.DataFrame([_listing("CELG", "Celgene", source="alpaca")])

        assert sec.name_for_run(_run("CELG", "2005-01-03", "2018-03-27"), {"CELG": listings}) == "Celgene"

    def test_no_fallback_for_former_owner_run(self):
        listings = pd.DataFrame([_listing("DELL", "Dell Technologies", source="alpaca")])

        assert sec.name_for_run(_run("DELL", "2005-01-03", "2013-10-29", "DELL~2013"), {"DELL": listings}) is None

    def test_unknown_symbol_has_no_name(self):
        assert sec.name_for_run(_run("ZZZ", "2005-01-03", "2006-01-03"), {}) is None


class TestIsOperating:
    def test_fund_is_not_operating(self):
        assert not sec.is_operating("SPDR S&P 500 ETF Trust")

    def test_company_is_operating(self):
        assert sec.is_operating("Celgene Corporation")

    def test_unknown_name_counts_as_operating(self):
        assert sec.is_operating(None)


class TestAttachCiks:
    def _frame(self, security="CELG", name="Celgene Corp"):
        return pd.DataFrame([{"symbol": "CELG", "security": security, "name": name}])

    def test_uses_current_ticker_for_latest_security(self):
        out = sec.attach_ciks(self._frame(), {"CELG": 816284}, {})

        assert out["cik"].tolist() == [816284]

    def test_uses_name_for_former_owner(self):
        out = sec.attach_ciks(self._frame(security="CELG~2010"), {"CELG": 1}, {"CELGENE": 816284})

        assert out["cik"].tolist() == [816284]

    def test_missing_when_neither_matches(self):
        out = sec.attach_ciks(self._frame(), {}, {})

        assert out["cik"].isna().all()


class TestSecNameCiks:
    def test_skips_names_shared_by_two_ciks(self, tmp_path):
        path = tmp_path / "lookup.txt"
        path.write_text("ACME INC:0000000001:\nACME CORP:0000000002:\nCELGENE CORP:0000816284:\n")

        assert sec.sec_name_ciks(str(path)) == {"CELGENE": 816284}


class TestListedOn:
    def test_counts_listing_alive_on_day(self):
        listings = pd.DataFrame([_listing("CELG", "Celgene", "1990-01-01", "2019-11-20", source="tiingo")])

        assert list(sec.listed_on(listings, T("2015-01-02"))) == ["CELG"]

    def test_skips_listing_ended_before_day(self):
        listings = pd.DataFrame([_listing("CELG", "Celgene", "1990-01-01", "2019-11-20", source="tiingo")])

        assert list(sec.listed_on(listings, T("2020-01-02"))) == []

    def test_skips_funds(self):
        listings = pd.DataFrame([_listing("SPY", "SPDR S&P 500 ETF Trust", "1993-01-29", source="tiingo")])

        assert list(sec.listed_on(listings, T("2015-01-02"))) == []

    def test_alphavantage_dates_never_override_tiingo(self):
        listings = pd.DataFrame([_listing("CELG", "Celgene", "1990-01-01", "2010-01-01", source="tiingo"),
                                 _listing("CELG", "Celgene", "1990-01-01", source="alphavantage")])

        assert list(sec.listed_on(listings, T("2015-01-02"))) == []

    def test_alphavantage_adds_symbols_tiingo_lacks(self):
        listings = pd.DataFrame([_listing("XYZ", "Xyz Inc", "2010-01-01", "2016-01-01", source="alphavantage")])

        assert list(sec.listed_on(listings, T("2015-01-02"))) == ["XYZ"]

    def test_skips_otc(self):
        listings = pd.DataFrame([_listing("XYZ", "Xyz Inc", "2000-01-01", source="tiingo", exchange="OTC")])

        assert list(sec.listed_on(listings, T("2015-01-02"))) == []


class TestCoverageByYear:
    def test_splits_missing_into_still_listed_and_gone(self):
        listings = pd.DataFrame([
            _listing("AAPL", "Apple", "1980-12-12", source="tiingo"),
            _listing("LIVE", "Live Co", "2000-01-01", source="tiingo"),
            _listing("GONE", "Gone Co", "2000-01-01", "2012-05-01", source="tiingo"),
        ])
        runs = pd.DataFrame([{"symbol": "AAPL", "first_day": T("1980-12-12"), "last_day": T("2018-03-27")}])

        row = sec.coverage_by_year(runs, listings, {"AAPL", "LIVE"}, years=[2010]).iloc[0]

        assert (row["listed"], row["wiki"], row["missing_still_listed"], row["missing_gone"]) == (3, 1, 1, 1)
