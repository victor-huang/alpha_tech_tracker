import pandas as pd

from alpha_tech_tracker.research.industry import IndustryCache, cap_per_industry, industry_of

CP = pd.Timestamp("2026-01-02")


def _ranked(symbols):
    return pd.DataFrame({"checkpoint": CP, "tier": "Large", "symbol": symbols,
                         "rank": [float(i + 1) for i in range(len(symbols))]})


class TestCapPerIndustry:
    def test_drops_lower_ranked_name_from_same_industry(self):
        out = cap_per_industry(_ranked(["MRNA", "BNTX", "FTNT"]), {"MRNA": "2836", "BNTX": "2836", "FTNT": "7372"})

        assert out["symbol"].tolist() == ["MRNA", "FTNT"]

    def test_reranks_kept_names(self):
        out = cap_per_industry(_ranked(["MRNA", "BNTX", "FTNT"]), {"MRNA": "2836", "BNTX": "2836", "FTNT": "7372"})

        assert out["rank"].tolist() == [1.0, 2.0]

    def test_never_drops_names_without_industry(self):
        out = cap_per_industry(_ranked(["A", "B"]), {})

        assert out["symbol"].tolist() == ["A", "B"]

    def test_allows_more_per_industry_when_raised(self):
        out = cap_per_industry(_ranked(["MRNA", "BNTX"]), {"MRNA": "2836", "BNTX": "2836"}, per_industry=2)

        assert out["symbol"].tolist() == ["MRNA", "BNTX"]

    def test_caps_each_checkpoint_separately(self):
        ranked = pd.concat([_ranked(["MRNA", "BNTX"]),
                            _ranked(["BNTX", "MRNA"]).assign(checkpoint=pd.Timestamp("2026-01-16"))])

        out = cap_per_industry(ranked, {"MRNA": "2836", "BNTX": "2836"})

        assert out["symbol"].tolist() == ["MRNA", "BNTX"]


class TestIndustryOf:
    def test_truncates_sic_to_digits(self):
        table = pd.DataFrame({"sic": ["2836", ""]}, index=["MRNA", "PDD"])

        assert industry_of(table, digits=2) == {"MRNA": "28"}


class TestIndustryCache:
    def _cache(self, tmp_path, mocker, ciks=None):
        fetch = mocker.Mock(return_value=("2836", "Biological Products"))
        cache = IndustryCache(str(tmp_path), user_agent_for=lambda: "agent",
                              ticker_ciks=lambda agent: ciks if ciks is not None else {"MRNA": 1682852},
                              fetch=fetch, pause=0)
        return cache, fetch

    def test_fetches_sic_by_cik(self, tmp_path, mocker):
        cache, fetch = self._cache(tmp_path, mocker)

        table = cache.load(["MRNA"])

        assert table.loc["MRNA", "sic"] == "2836"

    def test_does_not_refetch_cached_symbols(self, tmp_path, mocker):
        cache, fetch = self._cache(tmp_path, mocker)
        cache.load(["MRNA"])

        cache.load(["MRNA"])

        assert fetch.call_count == 1

    def test_caches_unlisted_symbol_with_empty_sic(self, tmp_path, mocker):
        cache, fetch = self._cache(tmp_path, mocker, ciks={})

        table = cache.load(["PDD"])

        assert table.loc["PDD", "sic"] == ""
