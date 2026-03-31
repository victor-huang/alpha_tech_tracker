import csv
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytz

from alpha_tech_tracker.op_momentum_strategy.bar_recorder import BarRecorder

ET = pytz.timezone("America/New_York")


def _make_bar(ticker, ts_et_str, open_, high, low, close, volume):
    """Build a mock Alpaca bar with a timezone-aware timestamp."""
    naive = datetime.strptime(ts_et_str, "%Y-%m-%d %H:%M:%S")
    ts = ET.localize(naive)
    bar = MagicMock()
    bar.symbol = ticker
    bar.timestamp = ts
    bar.open = open_
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    return bar


def _make_five_min_bar(ticker, ts_et_str, open_, high, low, close, volume):
    """Build a mock _FiveMinBar (already has an ET-aware timestamp)."""
    naive = datetime.strptime(ts_et_str, "%Y-%m-%d %H:%M:%S")
    bar = MagicMock()
    bar.symbol = ticker
    bar.timestamp = ET.localize(naive)
    bar.open = open_
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    return bar


class TestBarRecorderFileCreation:
    def test_creates_date_directory_on_first_write(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.0, 169.5, 170.5, 1000)
        recorder.record_1min("NVDA", bar, date(2026, 3, 31))

        assert (tmp_path / "2026-03-31").is_dir()

    def test_creates_1min_csv_file(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.0, 169.5, 170.5, 1000)
        recorder.record_1min("NVDA", bar, date(2026, 3, 31))

        assert (tmp_path / "2026-03-31" / "NVDA_1min.csv").exists()

    def test_creates_5min_csv_file(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = _make_five_min_bar("AMD", "2026-03-31 09:35:00", 120.0, 122.0, 119.5, 121.0, 5000)
        recorder.record_5min("AMD", bar, date(2026, 3, 31))

        assert (tmp_path / "2026-03-31" / "AMD_5min.csv").exists()

    def test_separate_files_per_ticker(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        session = date(2026, 3, 31)
        recorder.record_1min("NVDA", _make_bar("NVDA", "2026-03-31 09:31:00", 1, 2, 1, 1, 100), session)
        recorder.record_1min("AMD", _make_bar("AMD", "2026-03-31 09:31:00", 1, 2, 1, 1, 100), session)

        assert (tmp_path / "2026-03-31" / "NVDA_1min.csv").exists()
        assert (tmp_path / "2026-03-31" / "AMD_1min.csv").exists()


class TestBarRecorderCsvContent:
    def test_1min_csv_has_header_row(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.0, 169.5, 170.5, 1000)
        recorder.record_1min("NVDA", bar, date(2026, 3, 31))

        with open(tmp_path / "2026-03-31" / "NVDA_1min.csv") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_1min_csv_row_values(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.5, 169.5, 170.8, 1234)
        recorder.record_1min("NVDA", bar, date(2026, 3, 31))

        with open(tmp_path / "2026-03-31" / "NVDA_1min.csv") as f:
            rows = list(csv.reader(f))
        data = rows[1]
        assert data[0] == "2026-03-31 09:31:00"
        assert float(data[1]) == 170.0
        assert float(data[2]) == 171.5
        assert float(data[3]) == 169.5
        assert float(data[4]) == 170.8
        assert int(data[5]) == 1234

    def test_5min_csv_row_values(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = _make_five_min_bar("AMD", "2026-03-31 09:35:00", 120.0, 122.0, 119.0, 121.5, 5500)
        recorder.record_5min("AMD", bar, date(2026, 3, 31))

        with open(tmp_path / "2026-03-31" / "AMD_5min.csv") as f:
            rows = list(csv.reader(f))
        data = rows[1]
        assert data[0] == "2026-03-31 09:35:00"
        assert float(data[1]) == 120.0
        assert int(data[5]) == 5500

    def test_multiple_bars_append_to_same_file(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        session = date(2026, 3, 31)
        recorder.record_1min("NVDA", _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.0, 169.5, 170.5, 1000), session)
        recorder.record_1min("NVDA", _make_bar("NVDA", "2026-03-31 09:32:00", 170.5, 172.0, 170.0, 171.5, 1200), session)
        recorder.record_1min("NVDA", _make_bar("NVDA", "2026-03-31 09:33:00", 171.5, 173.0, 171.0, 172.0, 900), session)

        with open(tmp_path / "2026-03-31" / "NVDA_1min.csv") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 4  # header + 3 data rows
        assert rows[1][0] == "2026-03-31 09:31:00"
        assert rows[3][0] == "2026-03-31 09:33:00"

    def test_timestamps_written_in_et(self, tmp_path):
        """A bar arriving as UTC should be stored as ET in the CSV."""
        recorder = BarRecorder(base_dir=str(tmp_path))
        bar = MagicMock()
        bar.timestamp = datetime(2026, 3, 31, 13, 31, 0, tzinfo=timezone.utc)  # 9:31 AM ET
        bar.open = bar.high = bar.low = bar.close = 170.0
        bar.volume = 100
        recorder.record_1min("NVDA", bar, date(2026, 3, 31))

        with open(tmp_path / "2026-03-31" / "NVDA_1min.csv") as f:
            rows = list(csv.reader(f))
        assert rows[1][0] == "2026-03-31 09:31:00"


class TestBarRecorderAppendBehavior:
    def test_does_not_rewrite_header_when_file_already_exists(self, tmp_path):
        session = date(2026, 3, 31)
        path = tmp_path / "2026-03-31"
        path.mkdir()
        csv_path = path / "NVDA_1min.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            writer.writerow(["2026-03-31 09:30:00", 169.0, 170.0, 168.5, 169.5, 800])

        recorder = BarRecorder(base_dir=str(tmp_path))
        recorder.record_1min("NVDA", _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.0, 169.5, 170.5, 1000), session)

        with open(csv_path) as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(rows) == 3  # header + pre-existing row + new row


class TestBarRecorderClose:
    def test_close_flushes_and_releases_files(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        session = date(2026, 3, 31)
        recorder.record_1min("NVDA", _make_bar("NVDA", "2026-03-31 09:31:00", 170.0, 171.0, 169.5, 170.5, 1000), session)

        recorder.close()

        assert len(recorder._files) == 0
        assert len(recorder._writers) == 0

    def test_close_is_safe_to_call_when_no_files_opened(self, tmp_path):
        recorder = BarRecorder(base_dir=str(tmp_path))
        recorder.close()  # should not raise
