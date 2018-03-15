import datetime
import numpy
from numpy.testing import assert_array_equal
import pandas as pd
import pytest
import ipdb

from alpha_tech_tracker.wave import Wave

# nice print settings
pd.set_option('display.expand_frame_repr', False)
pd.options.display.max_rows = 999

def test_c_wave_is_create_new_wave():
    df = pd.read_csv('./tests/data/eog_down_wave.csv')
    df.set_index('Date', inplace=True)
    two_wave_df = df['2016-12-13':'2017-01-06'].rename(str.lower, axis='columns')
    wave = None
    all_waves = []

    for index, row in two_wave_df.iterrows():
        date = datetime.datetime.strptime(index, '%Y-%m-%d').date()

        if not wave:
            wave = Wave(date, row)
            all_waves.append(wave)
        else:
           new_wave = wave.count(date, row)

           if new_wave:
               all_waves.append(new_wave)
               wave = new_wave

    for wave in all_waves:
        s = wave.summary()
        print("Wave direction: {0}, gain: {1:.2f}, length {2}".format(wave.direction(),
            s['movement_in_percentage'], s['length']))
        print(wave.df)

    assert len(all_waves) == 2
    assert all_waves[0].start == datetime.date(2016, 12, 13)
    assert all_waves[0].end == datetime.date(2016, 12, 30)
    assert all_waves[0].high_date == datetime.date(2016, 12, 13)
    assert all_waves[0].high == 109.129997
    assert all_waves[0].low_date == datetime.date(2016, 12, 30)
    assert all_waves[0].low == 101.099998

    assert all_waves[1].start == datetime.date(2017, 1, 3)
    assert all_waves[1].end == None
