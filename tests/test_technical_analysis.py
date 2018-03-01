import numpy
from numpy.testing import assert_array_equal
import pandas as pd
import pytest
import ipdb

import alpha_tech_tracker.technical_analysis as ta

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

def test_detect_reversal():
    df = pd.read_csv('./tests/data/fb.csv')

    #  ipdb.set_trace()
    result = ta.detect_reversal(df)
