from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_rider import (
    DAYTYPE_BARS,
    day_type,
    flip_bars,
    ride,
    score,
    session_adr,
    short_pct,
    split_factors,
    wave_events,
)

ET = pytz.timezone("America/New_York")
DAY = date(2026, 10, 13)


def _time(i, day=DAY):
    return ET.localize(datetime.combine(day, time(9, 30)) + timedelta(minutes=5 * i))


def _bar(i, o, h, l, c, **extra):
    bar = {"time": _time(i), "open": o, "high": h, "low": l, "close": c, "turn": None, "dip_low": None,
           "low_stop": None, "high_signal": False, "adr": 10.0}
    bar.update(extra)
    return bar


def _flat(i, price, **extra):
    return _bar(i, price, price + 0.2, price - 0.2, price, **extra)


class TestDrive:
    def test_green_first_bar_held_to_the_close(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _flat(1, 102), _flat(2, 104)]

        assert ride("drive", bars) == [(_time(0), 101, _time(2), 104, "close")]

    def test_red_first_bar_no_trade(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100), _flat(1, 102), _flat(2, 104)]

        assert ride("drive", bars) == []

    def test_stopped_at_the_first_bars_low(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _bar(1, 100.5, 100.6, 99.0, 99.2), _flat(2, 104)]

        assert ride("drive", bars) == [(_time(0), 101, _time(1), 99.5, "stop")]

    def test_gap_below_the_stop_fills_at_the_open(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _bar(1, 99.0, 99.4, 98.5, 99.1), _flat(2, 104)]

        assert ride("drive", bars)[0][3] == 99.0


class TestTrailing:
    def test_stop_rises_to_each_new_dip_low(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _flat(1, 103), _flat(2, 104, turn="up", dip_low=102.0),
                _bar(3, 103, 103.1, 101.5, 101.8), _flat(4, 106)]

        assert ride("drive-trail", bars) == [(_time(0), 101, _time(3), 102.0, "stop")]

    def test_trail_rider_re_enters_on_a_turn_up(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _bar(1, 100, 100.1, 99.0, 99.3),
                _flat(2, 100, turn="up", dip_low=99.0), _flat(3, 103)]

        assert [t[4] for t in ride("trail", bars)] == ["stop", "close"]
        assert ride("trail", bars)[1][:2] == (_time(2), 100)


class TestTurnRiders:
    def test_turn_sells_the_next_turn_down(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100), _flat(1, 100, turn="up", dip_low=99.0), _flat(2, 103, turn="down"),
                _flat(3, 101)]

        assert ride("turn", bars) == [(_time(1), 100, _time(2), 103, "turn down")]

    def test_higher_low_skips_a_lower_dip(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100), _flat(1, 101, turn="up", dip_low=99.0), _flat(2, 100, turn="down"),
                _flat(3, 99, turn="up", dip_low=98.0), _flat(4, 100)]

        assert [t[0] for t in ride("higher-low", bars)] == [_time(1)]


class TestReversalRiders:
    def test_buys_a_low_signal_with_its_stop(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100), _flat(1, 100, low_stop=99.0), _flat(2, 102)]

        assert ride("reversal-close", bars) == [(_time(1), 100, _time(2), 102, "close")]

    def test_reversal_high_sells_the_first_high_signal(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100), _flat(1, 100, low_stop=99.0), _flat(2, 103, high_signal=True),
                _flat(3, 101)]

        assert ride("reversal-high", bars)[0][3:] == (103, "high signal")

    def test_two_leg_combo_adds_both_legs(self):
        bars = [_bar(0, 100, 101.5, 99.5, 101), _flat(1, 101, low_stop=100.0), _flat(2, 103)]

        assert len(ride("drive + reversal-trail", bars)) == 2


class TestDayType:
    def _morning(self, closes, adr=10.0):
        bars = [_bar(0, 100, max(100, closes[0]) + 0.1, min(100, closes[0]) - 0.1, closes[0], adr=adr)]
        bars += [_flat(i, c, adr=adr) for i, c in enumerate(closes[1:], start=1)]
        return bars + [_flat(len(bars), closes[-1], adr=adr)]

    def test_a_steady_rise_is_efficient(self):
        net, efficiency = day_type(self._morning([100 + i for i in range(1, DAYTYPE_BARS + 1)]))

        assert (net, efficiency) == (pytest.approx(1.2), pytest.approx(1.0))

    def test_back_and_forth_is_inefficient(self):
        closes = [101 if i % 2 else 100 for i in range(DAYTYPE_BARS)]

        assert day_type(self._morning(closes))[1] < 0.1

    def test_short_session_has_no_day_type(self):
        assert day_type([_flat(i, 100) for i in range(DAYTYPE_BARS)]) is None

    def test_cut_sells_the_drive_at_1030_on_a_chop_day(self):
        closes = [101] + [101 if i % 2 else 100.5 for i in range(1, DAYTYPE_BARS)]
        bars = self._morning(closes) + [_flat(DAYTYPE_BARS + 1, 105)]

        assert ride("daytype-cut E0.25 N0.2", bars)[0][2:] == (_time(DAYTYPE_BARS - 1), closes[-1], "chop at 10:30")

    def test_cut_holds_the_drive_on_a_trend_day(self):
        bars = self._morning([100 + i for i in range(1, DAYTYPE_BARS + 1)]) + [_flat(DAYTYPE_BARS + 1, 120)]

        assert ride("daytype-cut E0.25 N0.2", bars)[0][3:] == (120, "close")


class TestLimitEntries:
    def _session(self, dip_bar):
        bars = [_bar(0, 101, 101.5, 99.5, 100)] + [_flat(i, 102, vwap=101.0) for i in range(1, 6)]
        return bars + [dip_bar, _flat(7, 104, vwap=101.0)]

    def test_fills_at_the_previous_bars_vwap(self):
        bars = self._session(_bar(6, 101.8, 101.9, 100.8, 101.5, vwap=101.0))

        assert ride("limit-vwap b0.1", bars) == [(_time(6), 101.0, _time(7), 104, "close")]

    def test_bar_through_the_stop_counts_as_stopped(self):
        bars = self._session(_bar(6, 101.8, 101.9, 99.5, 100.0, vwap=101.0))

        assert ride("limit-vwap b0.1", bars) == [(_time(6), 101.0, _time(6), 100.0, "stop")]

    def test_dip_level_is_used_from_the_bar_after_its_turn(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100)] + [_flat(i, 102) for i in range(1, 6)]
        bars += [_bar(6, 101.5, 102.5, 100.1, 102.0, turn="up", dip_low=100.0), _flat(7, 104)]

        assert ride("limit-dip b0.1", bars) == []

    def test_dip_retest_fills_after_the_turn(self):
        bars = [_bar(0, 101, 101.5, 99.5, 100)] + [_flat(i, 102) for i in range(1, 5)]
        bars += [_flat(5, 102, turn="up", dip_low=100.0), _bar(6, 101.0, 101.1, 100.3, 100.8), _flat(7, 104)]

        assert ride("limit-dip b0.1", bars) == [(_time(6), 100.5, _time(7), 104, "close")]

    def test_no_fill_when_price_stays_above(self):
        assert ride("limit-vwap b0.1", self._session(_flat(6, 102, vwap=101.0))) == []


class TestReentry:
    def _stopped_then_back(self, recovery_close):
        return [_bar(0, 100, 101.5, 99.5, 101), _bar(1, 100, 100.1, 98.8, 99.0), _flat(2, 99.2),
                _flat(3, recovery_close), _flat(4, 103)]

    def test_re_buys_a_close_above_the_stop_out_level(self):
        trades = ride("reenter-stoplevel", self._stopped_then_back(100.0))

        assert trades[1] == (_time(3), 100.0, _time(4), 103, "close")

    def test_entry_rule_waits_for_the_original_entry(self):
        assert len(ride("reenter-entry", self._stopped_then_back(100.0))) == 1

    def test_re_entry_stop_is_the_low_since_the_stop_out(self):
        bars = self._stopped_then_back(100.0)[:4] + [_bar(4, 99.9, 100, 98.7, 98.9), _flat(5, 103)]

        assert ride("reenter-stoplevel", bars)[1][3:] == (98.8, "stop")

    def test_no_stop_variant_holds_to_the_close(self):
        bars = self._stopped_then_back(100.0)[:4] + [_bar(4, 99.9, 100, 98.0, 98.2), _flat(5, 103)]

        assert ride("reenter-stoplevel-nostop", bars)[1][3:] == (103, "close")

    def test_once_by_default(self):
        bars = self._stopped_then_back(100.0)[:4] + [_bar(4, 99.9, 100, 98.0, 98.2), _flat(5, 100.0), _flat(6, 103)]

        assert len(ride("reenter-stoplevel", bars)) == 2
        assert len(ride("reenter-stoplevel-x", bars)) == 3


class TestWaveEvents:
    def test_turn_up_carries_the_dips_wick_low(self):
        closes = [100 - i for i in range(10)] + [93 + i for i in range(10)]
        index = pd.DatetimeIndex([_time(i) for i in range(len(closes))])
        bars = pd.DataFrame({"open": closes, "high": [c + 0.3 for c in closes], "low": [c - 0.3 for c in closes],
                             "close": closes}, index=index)

        turns = [e for e in wave_events(bars, 3, 0.236, 1.5)[DAY] if e["turn"] == "up"]

        assert turns and turns[0]["dip_low"] == pytest.approx(90.7)


class TestScore:
    def test_capture_divides_dollars_by_adr_and_counts_empty_sessions(self):
        trades = {DAY: [(None, 100.0, None, 102.0, "close")]}

        result = score(trades, {DAY: 4.0, DAY + timedelta(days=1): 4.0}, [DAY, DAY + timedelta(days=1)], cost_bps=0)

        assert (result["trades"], result["total_pct"], result["capture"]) == (1, pytest.approx(2.0), pytest.approx(0.25))


class TestSessionAdr:
    def test_mean_range_of_previous_sessions(self):
        frames = []
        for k, rng in enumerate((2.0, 4.0, 6.0)):
            day = DAY + timedelta(days=k)
            index = pd.DatetimeIndex([_time(i, day) for i in range(2)])
            frames.append(pd.DataFrame({"high": [100 + rng, 100], "low": [100, 100]}, index=index))

        adr = session_adr(pd.concat(frames), 2)

        assert adr[DAY + timedelta(days=2)] == pytest.approx(3.0)


class TestSplitFactors:
    def _bars(self, closes):
        index = pd.DatetimeIndex([_time(0, d) for d in closes])
        return pd.DataFrame({"close": list(closes.values())}, index=index)

    def test_finds_an_unadjusted_4_for_1_split(self):
        days = (date(2026, 7, 1), date(2026, 7, 2))
        bars = self._bars({days[0]: 772.0, days[1]: 193.7})

        assert split_factors(bars, {days[0]: 193.2, days[1]: 194.0}) == {days[0]: 4}

    def test_ignores_ordinary_differences(self):
        bars = self._bars({DAY: 101.0})

        assert split_factors(bars, {DAY: 100.0}) == {}

    def test_a_session_off_the_ratio_keeps_the_previous_sessions_divisor(self):
        days = [date(2026, 7, 1) + timedelta(days=i) for i in range(4)]
        bars = self._bars({days[0]: 772.0, days[1]: 850.0, days[2]: 193.7, days[3]: 250.0})

        factors = split_factors(bars, {days[0]: 193.2, days[1]: 194.0, days[2]: 194.0, days[3]: 200.0})

        assert factors == {days[0]: 4, days[1]: 4}

    def test_a_session_off_the_ratio_before_the_first_match_takes_the_next_divisor(self):
        days = [date(2026, 7, 1) + timedelta(days=i) for i in range(2)]
        bars = self._bars({days[0]: 850.0, days[1]: 772.0})

        assert split_factors(bars, {days[0]: 194.0, days[1]: 193.2}) == {days[0]: 4, days[1]: 4}


class TestFlipForShorts:
    def _bars(self):
        index = pd.DatetimeIndex([_time(i) for i in range(3)])
        return pd.DataFrame({"open": [100.0, 99.0, 97.0], "high": [101.0, 99.5, 98.0], "low": [98.5, 97.0, 96.0],
                             "close": [99.0, 97.5, 96.5]}, index=index)

    def test_rallies_become_drops_and_highs_become_lows(self):
        flipped, k = flip_bars(self._bars())

        assert flipped["low"].iloc[0] == pytest.approx(k / 101.0)
        assert flipped["close"].is_monotonic_increasing

    def test_a_flipped_long_maps_back_to_the_real_short(self):
        flipped, k = flip_bars(self._bars())

        assert short_pct(k, flipped["close"].iloc[0], flipped["close"].iloc[2]) == pytest.approx((99.0 - 96.5) / 99.0 * 100)

    def test_drive_on_flipped_bars_is_a_drive_short(self):
        bars = self._bars()
        flipped, k = flip_bars(bars)
        events = [{"time": t, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "turn": None,
                   "dip_low": None, "low_stop": None, "high_signal": False} for t, r in flipped.iterrows()]

        (_, entry, _, exit_price, reason), = ride("drive", events)

        assert (k / entry, k / exit_price, reason) == (pytest.approx(99.0), pytest.approx(96.5), "close")
