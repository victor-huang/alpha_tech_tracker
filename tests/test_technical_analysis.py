import datetime

import numpy
import pandas as pd
import pytest
from numpy.testing import assert_array_equal

import alpha_tech_tracker.technical_analysis as ta
from alpha_tech_tracker.alpaca_py_engine import get_historical_stock_data
from alpha_tech_tracker.wave import Wave

# nice print settings
pd.set_option("display.expand_frame_repr", False)
pd.options.display.max_rows = 999


def test_moving_average():
    daily_price = {
        "2010-01-01": 10,
        "2010-01-02": 20,
        "2010-01-03": 30,
        "2010-01-04": 10,
        "2010-01-05": 10,
        "2010-01-06": 40,
    }

    df = pd.DataFrame.from_dict(daily_price, orient="index").sort_index()

    ma_df = ta.moving_average(2, df)
    mv_key = "mavg_2"
    assert numpy.isnan(ma_df.iloc(0)[0].get(mv_key))
    assert ma_df.iloc(0)[1].get(mv_key) == 15
    assert ma_df.iloc(0)[5].get(mv_key) == 25


def test_moving_average_summary():
    daily_price = {
        "2010-01-01": 10,
        "2010-01-02": 20,
        "2010-01-03": 30,
        "2010-01-04": 10,
        "2010-01-05": 10,
        "2010-01-06": 40,
    }

    df = pd.DataFrame.from_dict(daily_price, orient="index").sort_index()

    ma_df = ta.moving_average_summary([2, 3], df)
    assert_array_equal(ma_df.columns, ["mavg_2", "mavg_3"])
    assert ma_df.iloc(0)[5].get(0) == 25
    assert ma_df.iloc(0)[5].get(1) == 20


@pytest.mark.skip(reason="Test data file regn.csv is missing")
def test_detect_moving_average_trend():
    df = pd.read_csv("./tests/data/regn.csv")
    df.set_index("Date", inplace=True)
    df = df.filter(["Close"], axis=1)
    # Normalize column names to lowercase for consistency with API data
    df.columns = df.columns.str.lower()

    result_df = ta.detect_moving_average_trend(df)


def test_long_tail_reversal():
    # hammer
    price_data = [100.5, 99.5, 101, 98]  # clost, open, high, low
    assert ta.long_tail_reversal(*price_data) == True

    # doji
    price_data = [100, 100, 101, 97]  # clost, open, high, low
    assert ta.long_tail_reversal(*price_data) == True

    # daily movement too small
    price_data = [100, 100, 100.5, 99.8]  # clost, open, high, low
    assert ta.long_tail_reversal(*price_data) == False

    # 250  2018-02-23  179.899994  183.389999  179.509995   183.289993
    price_data = [183.289993, 179.899994, 183.389999, 179.509995]
    assert ta.long_tail_reversal(*price_data) == False


def test_long_tail_reversal_bearish():
    # hammer
    price_data = [101, 102, 103, 101]  # close, open, high, low
    assert ta.long_tail_reversal(*price_data, trend="down") == True


def test_long_tail_reversal_combo():
    price_data = [
        # clost, open, high, low
        [182, 182, 183.389999, 180.509995],
        [181, 182, 182.389999, 179.509995],
    ]

    assert ta.long_tail_reversal_combo(price_data) == True


def test_long_tail_reversal_combo_2():
    price_data = [
        # clost, open, high, low
        [1793.89, 1795.22, 1796.1197, 1792.6024],
        [1794.86, 1793.91, 1795.41, 1792.6],
    ]

    minimum = 0.01 / (12 * 8)
    assert (
        ta.long_tail_reversal_combo(price_data, daily_movement_minimum=minimum) == True
    )


def test_long_tail_reversal_combo_up_day_and_then_reversal():
    price_data = [
        # clost, open, high, low
        [1576.6933, 1572.84, 1577.57, 1572.715],
        [1576.7378, 1576.99, 1577.77, 1575.0448],
    ]

    minimum = 0.01 / (12 * 8)
    assert (
        ta.long_tail_reversal_combo(price_data, daily_movement_minimum=minimum) == False
    )


def test_engulfing_reversal():
    price_data = [
        # clost, open, high, low
        [101, 99, 100, 100],
        [103, 98, 103.3, 97.8],
    ]

    assert ta.engulfing_reversal(price_data) == True

    price_data = [
        [61.360001, 61.730000, 61.919998, 61.049999],
        [62.290001, 61.240002, 62.470001, 61.209999],
    ]

    assert ta.engulfing_reversal(price_data) == True


def test_piercing_reversal():
    # close, open, high, low
    price_data = [[98, 101, 101, 98], [100, 96, 100, 96]]

    assert ta.piercing_reversal(price_data) == True

    price_data = [[100, 96, 100, 96], [97, 101, 101, 97]]

    assert ta.piercing_reversal(price_data, trend="down") == True


def test_push_reversal():
    # close, open, high, low
    price_data = [[98, 101, 101, 98], [100.9, 97.8, 101, 97]]

    assert ta.push_reversal(price_data) == True

    price_data = [[101, 96, 100, 96], [96.2, 101.3, 101.5, 96]]

    assert ta.push_reversal(price_data, trend="down") == True


class TestPiercingReversalMinimum:
    # AMD 2026-02-10 09:45 and 09:50 ET, a wave low; the second body is 0.79% of its open, average 5-min bar 0.81
    AMD_PIERCING = [[214.72, 216.72, 217.05, 214.26], [216.40, 214.71, 217.00, 214.66]]

    def test_default_minimum_keeps_the_daily_1_5_percent(self):
        assert ta.piercing_reversal(self.AMD_PIERCING) is False

    def test_intraday_minimum_detects_the_5min_piercing(self):
        assert ta.piercing_reversal(self.AMD_PIERCING, daily_movement_minimum=0.81 / 216.40) is True


class TestPushReversalDoji:
    def test_first_candle_with_no_body_is_not_a_push(self):
        # close, open, high, low
        price_data = [[100, 100, 101, 99], [101.6, 100, 101.8, 99.9]]

        assert ta.push_reversal(price_data) is False

    def test_amd_5min_push_at_a_low(self):
        # AMD 2026-01-23 09:35 and 09:40 ET, a wave low, average 5-min bar 1.05
        price_data = [[259.08, 262.28, 263.10, 258.06], [262.83, 259.08, 263.00, 258.78]]

        assert ta.push_reversal(price_data, daily_movement_minimum=1.05 / 262.83) is True


class TestPiercingReversalBearish:
    # close, open, high, low
    UP_CANDLE = [102, 100, 102.2, 99.8]
    NO_MINIMUM = 0.0

    def test_opens_above_the_close_and_closes_below_the_midpoint(self):
        assert ta.piercing_reversal([self.UP_CANDLE, [100.6, 102.5, 102.8, 100.5]], trend="down", daily_movement_minimum=self.NO_MINIMUM) is True

    def test_close_above_the_midpoint_is_not_a_dark_cloud(self):
        assert ta.piercing_reversal([self.UP_CANDLE, [101.4, 102.5, 102.8, 101.3]], trend="down", daily_movement_minimum=self.NO_MINIMUM) is False

    def test_open_below_the_first_close_is_not_a_dark_cloud(self):
        assert ta.piercing_reversal([self.UP_CANDLE, [100.6, 101.9, 102.1, 100.5]], trend="down", daily_movement_minimum=self.NO_MINIMUM) is False

    def test_close_below_the_first_open_is_an_engulfing_not_a_dark_cloud(self):
        assert ta.piercing_reversal([self.UP_CANDLE, [99.5, 102.5, 102.8, 99.4]], trend="down", daily_movement_minimum=self.NO_MINIMUM) is False

    def test_needs_an_up_candle_first(self):
        assert ta.piercing_reversal([[100, 102, 102.2, 99.8], [100.6, 102.5, 102.8, 100.5]], trend="down", daily_movement_minimum=self.NO_MINIMUM) is False

    def test_second_body_below_the_minimum_is_not_a_signal(self):
        assert ta.piercing_reversal([self.UP_CANDLE, [101.2, 102.1, 102.3, 101.1]], trend="down", daily_movement_minimum=0.015) is False

    def test_amd_5min_dark_cloud_at_a_high(self):
        # AMD 2026-02-20 09:40 and 09:45 ET, a wave high, average 5-min bar 0.79
        price_data = [[202.64, 201.62, 203.50, 201.43], [201.68, 202.68, 203.09, 201.62]]

        assert ta.piercing_reversal(price_data, trend="down", daily_movement_minimum=0.79 / 201.68) is True


class TestConfirmedLongTailReversal:
    # close, open, high, low
    HAMMER = [100.5, 99.5, 101, 98]
    SHOOTING_STAR = [100.5, 100.2, 103, 100]

    def test_hammer_confirmed_by_a_close_above_its_high(self):
        price_data = [self.HAMMER, [101.5, 100.6, 101.8, 100.4]]

        assert ta.confirmed_long_tail_reversal(price_data) is True

    def test_hammer_without_a_close_above_its_high_is_not_confirmed(self):
        price_data = [self.HAMMER, [100.9, 100.6, 101.8, 100.4]]

        assert ta.confirmed_long_tail_reversal(price_data) is False

    def test_candle_that_is_not_a_long_tail_never_confirms(self):
        price_data = [[98.2, 100.8, 101, 98], [101.5, 100.6, 101.8, 100.4]]

        assert ta.confirmed_long_tail_reversal(price_data) is False

    def test_shooting_star_confirmed_by_a_close_below_its_low(self):
        price_data = [self.SHOOTING_STAR, [99.5, 100.4, 100.6, 99.3]]

        assert ta.confirmed_long_tail_reversal(price_data, trend="down") is True

    def test_shooting_star_without_a_close_below_its_low_is_not_confirmed(self):
        price_data = [self.SHOOTING_STAR, [100.1, 100.4, 100.6, 99.9]]

        assert ta.confirmed_long_tail_reversal(price_data, trend="down") is False

    def test_amd_5min_bottom_with_the_average_bar_as_minimum(self):
        # AMD 2026-10-13 11:35 and 11:40 ET, average 5-min bar 1.79
        price_data = [[586.05, 585.59, 586.66, 584.66], [587.55, 585.90, 588.13, 585.75]]

        assert ta.confirmed_long_tail_reversal(price_data, daily_movement_minimum=1.79 / 586.05) is True

    def test_amd_5min_top_with_the_average_bar_as_minimum(self):
        # AMD 2026-10-13 12:55 and 13:00 ET
        price_data = [[599.68, 600.37, 601.49, 599.55], [597.40, 599.61, 600.25, 596.50]]

        assert (
            ta.confirmed_long_tail_reversal(price_data, trend="down", daily_movement_minimum=1.79 / 599.68)
            is True
        )


class TestVolumeLongWickReversal:
    # close, open, high, low
    HAMMER = [100.5, 100.2, 101, 98]
    SHOOTING_STAR = [99.6, 99.9, 102, 99]

    def test_long_lower_wick_on_heavy_volume(self):
        assert ta.volume_long_wick_reversal(*self.HAMMER, volume=2000, average_volume=1000) is True

    def test_long_lower_wick_on_ordinary_volume_is_not_a_signal(self):
        assert ta.volume_long_wick_reversal(*self.HAMMER, volume=1400, average_volume=1000) is False

    def test_heavy_volume_with_a_short_lower_wick_is_not_a_signal(self):
        assert ta.volume_long_wick_reversal(100.5, 98.4, 101, 98, volume=2000, average_volume=1000) is False

    def test_long_upper_wick_on_heavy_volume_for_a_top(self):
        assert ta.volume_long_wick_reversal(*self.SHOOTING_STAR, volume=2000, average_volume=1000, trend="down") is True

    def test_long_lower_wick_does_not_count_for_a_top(self):
        assert ta.volume_long_wick_reversal(*self.HAMMER, volume=2000, average_volume=1000, trend="down") is False

    def test_thresholds_are_configurable(self):
        assert (
            ta.volume_long_wick_reversal(*self.HAMMER, volume=1400, average_volume=1000, volume_multiple=1.3, wick_ratio=0.7)
            is True
        )

    def test_candle_below_the_minimum_movement_is_not_a_signal(self):
        assert (
            ta.volume_long_wick_reversal(*self.HAMMER, volume=2000, average_volume=1000, daily_movement_minimum=0.05)
            is False
        )

    def test_flat_candle_or_missing_average_volume_is_not_a_signal(self):
        assert ta.volume_long_wick_reversal(100, 100, 100, 100, volume=2000, average_volume=1000) is False
        assert ta.volume_long_wick_reversal(*self.HAMMER, volume=2000, average_volume=0) is False

    def test_amd_5min_bottom(self):
        # AMD 2026-01-08 10:00 ET, a wave low: lower wick 66% of the range on 3.0x the previous 78 bars' volume
        assert ta.volume_long_wick_reversal(205.90, 206.20, 206.34, 205.05, volume=919412, average_volume=304333) is True

    def test_amd_5min_top(self):
        # AMD 2026-01-14 10:25 ET, a wave high: upper wick 57% of the range on 3.3x volume
        assert (
            ta.volume_long_wick_reversal(222.22, 222.86, 223.91, 222.08, volume=1607948, average_volume=487206, trend="down")
            is True
        )


def test_gap_move():
    # good to use aapl as test data

    # gap up move
    price_data = [[100, 98, 101, 97], [104, 103.5, 104, 103.5]]

    assert ta.gap_move(price_data) == True

    price_date = [
        [166.600006, 168.500000, 165.279999, 168.110001, 166.827652, 41393400],
        [174.000000, 174.259995, 171.119995, 172.500000, 171.184174, 59398600],
    ]

    assert ta.gap_move(price_data) == True

    # gap down move
    price_data = [[100, 98, 101, 97], [93, 95, 96, 93]]
    assert ta.gap_move(price_data, trend="down") == True


def test_detect_reversal():
    #  df = pd.read_csv('./tests/data/aapl.csv')
    df = pd.read_csv("./tests/data/eog_down_wave.csv")
    df.set_index("Date", inplace=True)
    df = df["2016-12-13":"2017-08-18"]
    #  df.index = range(len(df.index))
    df.reset_index(inplace=True)
    # Normalize column names to lowercase for consistency with API data
    df.columns = df.columns.str.lower()
    #  ipdb.set_trace()
    result = ta.detect_reversal(df)


@pytest.mark.skip(reason="Requires real Alpaca API data - mocked data doesn't match real wave patterns")
def test_data_from_polygon_io():
    df = get_historical_stock_data("AMZN", "2019-07-23", "2019-07-24")
    # Create timezone-aware datetimes to match API data (Eastern Time)
    import pytz
    eastern = pytz.timezone("America/New_York")
    start_datetime = eastern.localize(
        datetime.datetime.strptime("2019-07-23 9:30:00", "%Y-%m-%d %H:%M:%S")
    )
    end_datetime = eastern.localize(
        datetime.datetime.strptime("2019-07-24 16:00:00", "%Y-%m-%d %H:%M:%S")
    )
    filter_df = df[start_datetime:end_datetime]
    filter_df.reset_index(inplace=True)

    result = ta.detect_reversal(filter_df)

    print(filter_df)

    filter_df.set_index("timestamp", inplace=True)
    # Normalize column names to lowercase
    filter_df.columns = filter_df.columns.str.lower()
    wave = None
    all_waves = []

    for index, row in filter_df.iterrows():
        date = index

        if not wave:
            wave = Wave(date, row)
            all_waves.append(wave)
        else:
            new_wave = wave.count(date, row)

            if new_wave:
                all_waves.append(new_wave)
                wave = new_wave

    # Test should complete successfully
    assert len(all_waves) > 0
