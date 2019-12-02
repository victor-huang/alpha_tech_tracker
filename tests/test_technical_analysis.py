import datetime
import numpy
from numpy.testing import assert_array_equal
import pandas as pd
import pytest
import ipdb

import alpha_tech_tracker.technical_analysis as ta
from alpha_tech_tracker.wave import Wave
import alpha_tech_tracker.alpaca_engine as data_source

# nice print settings
pd.set_option('display.expand_frame_repr', False)
pd.options.display.max_rows = 999

def test_moving_average():
    daily_price = {
        "2010-01-01": 10,
        "2010-01-02": 20,
        "2010-01-03": 30,
        "2010-01-04": 10,
        "2010-01-05": 10,
        "2010-01-06": 40
    }

    df = pd.DataFrame.from_dict(daily_price, orient='index').sort_index()

    ma_df = ta.moving_average(2, df)
    mv_key = 'mavg_2'
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
        "2010-01-06": 40
    }

    df = pd.DataFrame.from_dict(daily_price, orient='index').sort_index()

    ma_df = ta.moving_average_summary([2, 3], df)
    assert_array_equal(ma_df.columns, ['mavg_2', 'mavg_3'])
    assert ma_df.iloc(0)[5].get(0) == 25
    assert ma_df.iloc(0)[5].get(1) == 20


def test_detect_moving_average_trend():
    df = pd.read_csv('./tests/data/regn.csv')
    df.set_index('Date', inplace=True)
    df = df.filter(['Close'], axis=1)
    df.rename(str.lower, inplace=True)

    result_df = ta.detect_moving_average_trend(df)



def test_long_tail_reversal():
    # hammer
    price_data = [100.5, 99.5, 101, 98] # clost, open, high, low
    assert ta.long_tail_reversal(*price_data) == True


    # doji
    price_data = [100, 100, 101, 97] # clost, open, high, low
    assert ta.long_tail_reversal(*price_data) == True

    # daily movement too small
    price_data = [100, 100, 100.5, 99.8] # clost, open, high, low
    assert ta.long_tail_reversal(*price_data) == False


    # 250  2018-02-23  179.899994  183.389999  179.509995   183.289993
    price_data = [183.289993, 179.899994, 183.389999,  179.509995]
    assert ta.long_tail_reversal(*price_data) == False


def test_long_tail_reversal_bearish():
    # hammer
    price_data = [101, 102, 103, 101] # close, open, high, low
    assert ta.long_tail_reversal(*price_data, trend='down') == True


def test_long_tail_reversal_combo():
    price_data = [
        # clost, open, high, low
        [182, 182, 183.389999,  180.509995],
        [181, 182, 182.389999,  179.509995]
    ]

    assert ta.long_tail_reversal_combo(price_data) == True

def test_long_tail_reversal_combo_2():
    price_data = [
        # clost, open, high, low
        [1793.89, 1795.22, 1796.1197, 1792.6024],
        [1794.86, 1793.91, 1795.41, 1792.6]
    ]

    minimum = 0.01 / (12 * 8)
    assert ta.long_tail_reversal_combo(price_data, daily_movement_minimum=minimum) == True

def test_long_tail_reversal_combo_up_day_and_then_reversal():
    price_data = [
        # clost, open, high, low
        [1576.6933, 1572.84, 1577.57, 1572.715],
        [1576.7378, 1576.99, 1577.77, 1575.0448]
    ]

    minimum = 0.01 / (12 * 8)
    assert ta.long_tail_reversal_combo(price_data, daily_movement_minimum=minimum) == False

def test_engulfing_reversal():
    price_data = [
        # clost, open, high, low
        [101, 99, 100, 100],
        [103, 98, 103.3, 97.8]
    ]

    assert ta.engulfing_reversal(price_data) == True

    price_data = [
        [61.360001, 61.730000, 61.919998, 61.049999],
        [62.290001, 61.240002, 62.470001, 61.209999]
    ]

    assert ta.engulfing_reversal(price_data) == True


def test_piercing_reversal():
    # close, open, high, low
    price_data = [
        [98, 101, 101, 98],
        [100, 96, 100, 96]
    ]

    assert ta.piercing_reversal(price_data) == True

    price_data = [
        [100, 96, 100, 96],
        [97, 101, 101, 97]
    ]

    assert ta.piercing_reversal(price_data, trend='down') == True


def test_push_reversal():
    # close, open, high, low
    price_data = [
        [98, 101, 101, 98],
        [100.9, 97.8, 101, 97]
    ]

    assert ta.push_reversal(price_data) == True

    price_data = [
        [101, 96, 100, 96],
        [96.2, 101.3, 101.5, 96]
    ]

    assert ta.push_reversal(price_data, trend='down') == True


def test_gap_move():
    # good to use aapl as test data

    # gap up move
    price_data = [
        [100, 98, 101, 97],
        [104, 103.5, 104, 103.5]
    ]

    assert ta.gap_move(price_data) == True

    price_date = [
        [166.600006,  168.500000,  165.279999,  168.110001,  166.827652,  41393400],
        [174.000000,  174.259995,  171.119995,  172.500000,  171.184174,  59398600]
    ]

    assert ta.gap_move(price_data) == True

    # gap down move
    price_data = [
        [100, 98, 101, 97],
        [93, 95, 96, 93]
    ]
    assert ta.gap_move(price_data, trend='down') == True


def test_detect_reversal():
    #  df = pd.read_csv('./tests/data/aapl.csv')
    df = pd.read_csv('./tests/data/eog_down_wave.csv')
    df.set_index('Date', inplace=True)
    df = df['2016-12-13':'2017-08-18']
    #  df.index = range(len(df.index))
    df.reset_index(inplace=True)
    #  ipdb.set_trace()
    result = ta.detect_reversal(df)

def test_data_from_polygon_io():
    df = data_source.get_historical_ochl_data('AMZN', start_date='2019-07-23', end_date='2019-07-24')
    start_datetime = datetime.datetime.strptime('2019-07-23 9:30:00', '%Y-%m-%d %H:%M:%S')
    end_datetime = datetime.datetime.strptime('2019-07-24 16:00:00', '%Y-%m-%d %H:%M:%S')
    filter_df = df[start_datetime:end_datetime]
    filter_df.reset_index(inplace=True)

    result = ta.detect_reversal(filter_df)

    print(filter_df)

    filter_df.set_index('timestamp', inplace=True)
    wave_df = filter_df.rename(str.lower, axis='columns')
    wave = None
    all_waves = []

    ipdb.set_trace()

    for index, row in wave_df.iterrows():
        date = index # datetime.datetime.strptime(index, '%Y-%m-%d').date()

        if not wave:
            wave = Wave(date, row)
            all_waves.append(wave)
        else:
           new_wave = wave.count(date, row)

           if new_wave:
               all_waves.append(new_wave)
               wave = new_wave

    ipdb.set_trace()
    print('asdf')

