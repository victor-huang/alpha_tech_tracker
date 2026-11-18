from datetime import date, datetime, time
from types import SimpleNamespace

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.wave_strategy.feed import BarFeed
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import ET

SESSION = date(2026, 10, 6)


def _ts(text):
    return ET.localize(datetime.strptime(text, "%Y-%m-%d %H:%M"))


def _frame(day_closes):
    index = pd.DatetimeIndex([_ts(t) for t, _ in day_closes])
    closes = [c for _, c in day_closes]
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1.0}, index=index)


def _minute(text, price=1.0, symbol="AMD"):
    return SimpleNamespace(symbol=symbol, timestamp=_ts(text), open=price, high=price, low=price, close=price)


class _Clock:
    def __init__(self, text):
        self.value = _ts(text)

    def __call__(self):
        return self.value

    def set(self, text):
        self.value = _ts(text)


@pytest.fixture
def clock():
    return _Clock("2026-10-06 09:00")


@pytest.fixture
def client(mocker):
    return mocker.Mock(warmup=mocker.Mock(return_value={}), fetch_bars=mocker.Mock(return_value={}))


@pytest.fixture
def received():
    return {"bars": [], "backfills": [], "alerts": []}


def _feed(client, clock, received, start_at="2026-10-06 09:00"):
    feed = BarFeed(client, on_bar=lambda ticker, bar: received["bars"].append((ticker, bar)),
                   on_backfill=lambda gap_start, fetched: received["backfills"].append((gap_start, fetched)),
                   alert=received["alerts"].append, now=clock)
    feed.start_session(SESSION, ["AMD"], time(16, 0), _ts(start_at))
    return feed


class TestSessionBars:
    def test_before_the_open_warms_up_to_the_previous_close(self, client, clock, received):
        _feed(client, clock, received).session_bars(["AMD"], clock())

        assert client.warmup.call_args.args[2] == _ts("2026-10-05 16:00")

    def test_keeps_only_finished_regular_hours_bars(self, client, clock, received):
        client.warmup.return_value = {"AMD": _frame([("2026-10-06 08:00", 99.0), ("2026-10-06 09:30", 100.0),
                                                     ("2026-10-06 09:35", 101.0)])}
        clock.set("2026-10-06 09:38")

        bars = _feed(client, clock, received).session_bars(["AMD"], clock())["AMD"]

        assert list(bars.index) == [_ts("2026-10-06 09:30")]

    def test_a_ticker_without_history_gets_an_empty_frame(self, client, clock, received):
        bars = _feed(client, clock, received).session_bars(["AMD"], clock())

        assert bars["AMD"].empty

    def test_delayed_feed_warms_up_to_16_minutes_ago_and_schedules_a_backfill(self, client, clock, received):
        client.warmup.side_effect = [RuntimeError("subscription does not permit querying recent SIP data"), {}]
        clock.set("2026-10-06 11:00")
        feed = _feed(client, clock, received)

        feed.session_bars(["AMD"], clock())

        assert client.warmup.call_args.args[2] == _ts("2026-10-06 10:44")
        assert feed.backfill == (_ts("2026-10-06 10:44"), _ts("2026-10-06 11:00"))

    def test_other_warmup_errors_are_raised(self, client, clock, received):
        client.warmup.side_effect = RuntimeError("TradeStation error")

        with pytest.raises(RuntimeError):
            _feed(client, clock, received).session_bars(["AMD"], clock())


class TestStream:
    def test_minutes_of_other_tickers_and_outside_the_session_are_ignored(self, client, clock, received):
        feed = _feed(client, clock, received, start_at="2026-10-06 09:30")

        for bar in (_minute("2026-10-06 09:10"), _minute("2026-10-06 09:31", symbol="TSLA"),
                    _minute("2026-10-05 09:31"), _minute("2026-10-06 16:00")):
            feed.on_minute_bar(bar)
        feed.flush_due(_ts("2026-10-06 17:00"))

        assert received["bars"] == []

    def test_five_minutes_make_one_bar(self, client, clock, received):
        feed = _feed(client, clock, received, start_at="2026-10-06 09:30")

        for minute, price in zip(range(35, 40), (1.0, 3.0, 0.5, 2.0, 2.5)):
            feed.on_minute_bar(_minute(f"2026-10-06 09:{minute}", price))

        assert received["bars"] == [("AMD", {"time": _ts("2026-10-06 09:35"), "open": 1.0, "high": 3.0, "low": 0.5,
                                             "close": 2.5, "minutes": 5})]

    def test_the_period_streaming_started_in_is_refetched_whole(self, client, clock, received):
        client.fetch_bars.return_value = {"AMD": _frame([("2026-10-06 09:30", 7.0)])}
        feed = _feed(client, clock, received, start_at="2026-10-06 09:33")

        feed.on_minute_bar(_minute("2026-10-06 09:34", 1.0))

        assert received["bars"][0][1]["close"] == 7.0
        assert received["bars"][0][1]["minutes"] == 5

    def test_a_failed_refetch_keeps_the_streamed_minutes(self, client, clock, received):
        client.fetch_bars.side_effect = RuntimeError("down")
        feed = _feed(client, clock, received, start_at="2026-10-06 09:33")

        feed.on_minute_bar(_minute("2026-10-06 09:34", 1.0))

        assert (received["bars"][0][1]["close"], received["bars"][0][1]["minutes"]) == (1.0, 1)

    def test_later_periods_are_not_refetched(self, client, clock, received):
        feed = _feed(client, clock, received, start_at="2026-10-06 09:33")

        feed.on_minute_bar(_minute("2026-10-06 09:39"))

        client.fetch_bars.assert_not_called()


class TestOutage:
    def _started(self, client, clock, received):
        feed = _feed(client, clock, received)
        feed.start_stream()
        return feed

    def test_alerts_once_when_data_stops(self, client, clock, received):
        feed = self._started(client, clock, received)

        for stamp in ("2026-10-06 09:34", "2026-10-06 09:35", "2026-10-06 09:40"):
            clock.set(stamp)
            feed.watchdog(clock())

        assert received["alerts"] == ["no market data since 09:30; no alerts until it returns (check the feed / "
                                      "data subscription, see the log)"]

    def test_returning_data_alerts_and_schedules_a_backfill_of_the_gap(self, client, clock, received):
        feed = self._started(client, clock, received)
        clock.set("2026-10-06 09:40")
        feed.watchdog(clock())
        clock.set("2026-10-06 09:41")

        feed.on_minute_bar(_minute("2026-10-06 09:40"))

        assert received["alerts"][-1].startswith("market data restored at 09:41 after a gap from 09:30")
        assert feed.backfill == (_ts("2026-10-06 09:30"), _ts("2026-10-06 09:41"))

    def test_reconnects_at_most_every_timeout(self, client, clock, received):
        feed = self._started(client, clock, received)

        for stamp in ("2026-10-06 09:33", "2026-10-06 09:34", "2026-10-06 09:36"):
            clock.set(stamp)
            feed.watchdog(clock())

        assert client.reconnect.call_count == 2


class TestBackfill:
    def test_waits_until_the_gap_can_be_queried(self, client, clock, received):
        feed = _feed(client, clock, received)
        feed.schedule_backfill(_ts("2026-10-06 10:30"), _ts("2026-10-06 10:45"))

        feed.run_backfill(_ts("2026-10-06 11:00"))

        client.fetch_bars.assert_not_called()
        assert received["backfills"] == []

    def test_hands_over_the_gap_in_regular_hours_bars(self, client, clock, received):
        client.fetch_bars.return_value = {"AMD": _frame([("2026-10-06 10:35", 5.0)]), "TSLA": _frame([])}
        feed = _feed(client, clock, received)
        feed.schedule_backfill(_ts("2026-10-06 10:30"), _ts("2026-10-06 10:45"))

        feed.run_backfill(_ts("2026-10-06 11:01"))

        gap_start, fetched = received["backfills"][0]
        assert (gap_start, list(fetched), list(fetched["AMD"]["close"])) == (_ts("2026-10-06 10:30"), ["AMD"], [5.0])
        assert feed.backfill is None

    def test_a_failed_fetch_hands_over_none(self, client, clock, received):
        client.fetch_bars.side_effect = RuntimeError("down")
        feed = _feed(client, clock, received)
        feed.schedule_backfill(_ts("2026-10-06 10:30"), _ts("2026-10-06 10:45"))

        feed.run_backfill(_ts("2026-10-06 11:01"))

        assert received["backfills"] == [(_ts("2026-10-06 10:30"), None)]

    def test_overlapping_gaps_merge(self, client, clock, received):
        feed = _feed(client, clock, received)

        feed.schedule_backfill(_ts("2026-10-06 10:30"), _ts("2026-10-06 10:45"))
        feed.schedule_backfill(_ts("2026-10-06 10:40"), _ts("2026-10-06 11:00"))

        assert feed.backfill == (_ts("2026-10-06 10:30"), _ts("2026-10-06 11:00"))
