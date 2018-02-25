import numpy
from numpy.testing import assert_array_equal
import pandas as pd
import pytest
import ipdb

import alpha_tech_tracker.technical_analysis as ta

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


