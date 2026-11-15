from datetime import date

import pytest

from alpha_tech_tracker.research.historical import download as dl


def _response(mocker, status=200, json_body=None, text="", chunks=()):
    response = mocker.MagicMock(status_code=status, text=text)
    response.json.return_value = json_body
    response.iter_content.return_value = list(chunks)
    response.__enter__.return_value = response
    return response


def _export_body(status, link="https://s3.example/wiki.zip"):
    return {"datatable_bulk_download": {"file": {"status": status, "link": link,
                                                 "data_snapshot_time": "2026-02-03 04:33:38 UTC"}}}


class TestDownloadFile:
    def test_writes_streamed_chunks(self, mocker, tmp_path):
        mocker.patch.object(dl.requests, "get", return_value=_response(mocker, chunks=[b"ab", b"cd"]))
        path = tmp_path / "wiki" / "x.zip"

        dl.download_file("https://example/x.zip", str(path))

        assert path.read_bytes() == b"abcd"

    def test_leaves_no_partial_file(self, mocker, tmp_path):
        mocker.patch.object(dl.requests, "get", return_value=_response(mocker, chunks=[b"ab"]))
        path = tmp_path / "x.zip"

        dl.download_file("https://example/x.zip", str(path))

        assert not (tmp_path / "x.zip.part").exists()

    def test_skips_existing_file(self, mocker, tmp_path):
        get = mocker.patch.object(dl.requests, "get")
        path = tmp_path / "x.zip"
        path.write_bytes(b"old")

        assert dl.download_file("https://example/x.zip", str(path)) is False
        get.assert_not_called()


class TestRequest:
    def test_retries_on_rate_limit(self, mocker):
        ok = _response(mocker)
        get = mocker.patch.object(dl.requests, "get", side_effect=[_response(mocker, status=429), ok])

        assert dl._request("https://example", sleep=lambda s: None) is ok
        assert get.call_count == 2

    def test_retries_on_connection_error(self, mocker):
        ok = _response(mocker)
        mocker.patch.object(dl.requests, "get", side_effect=[dl.requests.ConnectionError("timed out"), ok])

        assert dl._request("https://example", sleep=lambda s: None) is ok

    def test_raises_after_last_connection_error(self, mocker):
        mocker.patch.object(dl.requests, "get", side_effect=dl.requests.ConnectionError("timed out"))

        with pytest.raises(dl.requests.ConnectionError):
            dl._request("https://example", sleep=lambda s: None)


class TestWikiExportLink:
    def test_returns_fresh_link(self, mocker):
        mocker.patch.object(dl.requests, "get", return_value=_response(mocker, json_body=_export_body("fresh")))

        assert dl.wiki_export_link("key", sleep=lambda s: None)["link"] == "https://s3.example/wiki.zip"

    def test_waits_while_export_is_being_created(self, mocker):
        get = mocker.patch.object(dl.requests, "get", side_effect=[
            _response(mocker, json_body=_export_body("creating", link=None)),
            _response(mocker, json_body=_export_body("fresh")),
        ])

        dl.wiki_export_link("key", sleep=lambda s: None)

        assert get.call_count == 2

    def test_gives_up_after_max_polls(self, mocker):
        mocker.patch.object(dl, "EXPORT_MAX_POLLS", 2)
        mocker.patch.object(dl.requests, "get",
                            return_value=_response(mocker, json_body=_export_body("creating", link=None)))

        with pytest.raises(RuntimeError):
            dl.wiki_export_link("key", sleep=lambda s: None)


class TestAlphavantageSnapshotDates:
    def test_moves_weekend_to_next_weekday(self):
        assert dl.alphavantage_snapshot_dates(2016, 2016) == [date(2016, 1, 4)]

    def test_keeps_weekday(self):
        assert dl.alphavantage_snapshot_dates(2019, 2019) == [date(2019, 1, 2)]


class TestDownloadAlphavantage:
    def test_writes_one_file_per_date_and_state(self, mocker, tmp_path):
        mocker.patch.dict(dl.os.environ, {"ALPHAVANTAGE_API_KEY": "k"})
        mocker.patch.object(dl, "alphavantage_snapshot_dates", return_value=[date(2019, 1, 2)])
        mocker.patch.object(dl.requests, "get", return_value=_response(mocker, text="symbol,name\nAAPL,Apple\n"))

        dl.download_alphavantage(str(tmp_path), sleep=lambda s: None)

        assert sorted(p.name for p in (tmp_path / "alphavantage").iterdir()) == [
            "listing_2019-01-02_active.csv", "listing_2019-01-02_delisted.csv"]

    def test_raises_on_api_error_text(self, mocker, tmp_path):
        mocker.patch.dict(dl.os.environ, {"ALPHAVANTAGE_API_KEY": "k"})
        mocker.patch.object(dl, "alphavantage_snapshot_dates", return_value=[date(2019, 1, 2)])
        mocker.patch.object(dl.requests, "get", return_value=_response(mocker, text="Invalid data parameter"))

        with pytest.raises(RuntimeError):
            dl.download_alphavantage(str(tmp_path), sleep=lambda s: None)


class TestDownloadSecCikLookup:
    def test_requires_contact_in_user_agent(self, mocker, tmp_path):
        mocker.patch.dict(dl.os.environ, {"SEC_USER_AGENT": "no contact"})

        with pytest.raises(RuntimeError):
            dl.download_sec_cik_lookup(str(tmp_path))
