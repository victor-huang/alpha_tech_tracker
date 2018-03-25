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


def generate_test_waves(wave_data_file='./tests/data/eog_down_wave.csv', start=None, end=None):
    df = pd.read_csv(wave_data_file)
    df.set_index('Date', inplace=True)

    if start and end:
        df = df[start:end]

    wave_df = df.rename(str.lower, axis='columns')
    wave = None
    all_waves = []

    for index, row in wave_df.iterrows():
        date = datetime.datetime.strptime(index, '%Y-%m-%d').date()

        if not wave:
            wave = Wave(date, row)
            all_waves.append(wave)
        else:
           new_wave = wave.count(date, row)

           if new_wave:
               all_waves.append(new_wave)
               wave = new_wave

    return all_waves


def test_c_wave_is_create_new_wave():
    all_waves = generate_test_waves(wave_data_file='./tests/data/eog_down_wave.csv', start='2016-12-13', end='2017-01-06')

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


def test_c_wave_summary():
    all_waves = generate_test_waves(wave_data_file='./tests/data/eog_down_wave.csv', start='2016-12-13', end='2017-01-06')

    summary = all_waves[0].summary()
    assert summary['length'] == 13
    assert summary['movement_in_percentage'].round(4) == -0.0736
