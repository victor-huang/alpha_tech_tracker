import datetime
import pandas as pd
from pandas import Series
import numpy as np

from alpha_tech_tracker.wave import Wave
import ipdb


def moving_average(window, df):
    """
        data frame should has two series: time, and value
    :return: a time serires data frame of the moving average
    """

    ma_df = df.rolling(window).mean()
    ma_df.columns = ['mavg_{}'.format(window)]
    return ma_df

def moving_average_summary(windows, df):
    """
        calculate multiple moving average based on specified window sizes
    :return: a data frame containing all moving average stats.
    """

    all_ma_df = None

    for moving_average_type in windows:
        ma_df = moving_average(moving_average_type, df)

        if all_ma_df is None:
            all_ma_df = ma_df
        else:
            all_ma_df = all_ma_df.join(ma_df)

    return all_ma_df


### Reversal Patterns ###

def long_tail_reversal(close, open, high, low, trend='up'):
    """
        try to detect if a chandle stick fall in the pattern of a doji, long-shadow and hammer
    """
    daily_movement_minimum = 0.01 # percentage

    detected = False
    mid_point = (high - low) / 2.0 + low

    # the move range needs to be large than percentage  of open price
    if abs((high - low)) / open < daily_movement_minimum:
        return False

    if trend == 'up':
        # both open and close need to above mid-point
        if open >= mid_point and close >= mid_point:
            detected = True
    else:
        if open <= mid_point and close <= mid_point:
            detected = True

    return detected


def long_tail_reversal_combo(price_data, trend='up'):
    """
    :price_data: a consecutive two days' price data array [(close, open, high, low)]
    """

    detected = False

    day_1_clos = price_data[0][0]
    day_2_low = price_data[1][-1]
    day_1_close = price_data[0][0]
    day_2_high = price_data[1][-2]

    if trend == 'up':
        if day_2_low < day_1_close and long_tail_reversal(*price_data[1], trend=trend):
            detected = True
    else:
        if day_2_high > day_1_close and long_tail_reversal(*price_data[1], trend=trend):
            detected = True

    return detected


def engulfing_reversal(price_data, trend='up'):
    detected = False

    first_candle_size = abs(price_data[0][1] - price_data[0][0])
    second_candle_size = abs(price_data[1][1] - price_data[1][0])
    second_day_price_diff = price_data[1][0] - price_data[1][1]
    is_second_day_open_lower = price_data[1][1] < price_data[0][0]
    is_second_day_open_higher = price_data[1][1] > price_data[0][0]
    is_second_day_close_higher = price_data[1][0] > price_data[0][0] and price_data[1][0] > price_data[0][1]
    is_second_day_close_lower = price_data[1][0] < price_data[0][1] and price_data[1][0] < price_data[0][0]


    if abs(price_data[1][3] - price_data[1][1]) + abs(price_data[1][2] -
            price_data[1][0]) > abs(second_day_price_diff) * 0.30:
        return False

    if second_candle_size > first_candle_size:
        if trend == 'up' and second_day_price_diff > 0 and is_second_day_open_lower and is_second_day_close_higher:
            detected = True
        if trend == 'down' and second_day_price_diff < 0 and is_second_day_open_higher and is_second_day_close_lower:
            detected = True

    return detected


def piercing_reversal(price_data, trend='up'):
    # data point order: close, open, high, low
    detected = False
    d = price_data
    daily_movement_minimum = 0.015 # percentage

    firt_day_candle_mid_point = abs(d[0][0] - d[0][1]) / 2.0

    is_first_day_down = d[0][0] < d[0][1]
    is_second_day_up = d[1][0] > d[1][1]

    is_second_candle_close_above_mid_point = d[1][0] > d[0][0] + firt_day_candle_mid_point
    is_second_candle_open_below_firt_day_close = d[1][1] < d[0][0]
    is_close_below_first_candle_open = d[1][0] < d[0][1]

    # the last day's move range needs to be large than percentage  of open price
    if abs((d[1][0] - d[1][1])) / d[1][1] < daily_movement_minimum:
        return False

    if is_first_day_down and trend == 'up':
        if is_second_candle_close_above_mid_point and is_second_candle_open_below_firt_day_close and is_close_below_first_candle_open:
            detected = True
    elif not is_first_day_down and trend == 'down':
        if not is_second_candle_close_above_mid_point and not is_second_candle_open_below_firt_day_close and not is_close_below_first_candle_open:
            detected = True

    return detected

def push_reversal(price_data, trend='up'):
    # data point order: close, open, high, low
    day1_price = price_data[0]
    day2_price = price_data[1]
    difference_tolerance = 0.2 # 20%
    candle_position_shift_tolerance = 0.005
    daily_price_movement_percentage = 0.015 # at least 1.5%
    detected = False

    first_candle_direction = day1_price[0] - day1_price[1]
    second_candle_direction = day2_price[0] - day2_price[1]

    day1_move_price_precentage = abs(first_candle_direction) / day1_price[0]
    day2_move_price_precentage = abs(second_candle_direction) / day2_price[0]

    # the first and second candle needs to move in differnet direction
    if first_candle_direction * second_candle_direction > 0:
        return False

    is_price_movement_within_range = abs(day1_move_price_precentage - day2_move_price_precentage) / day1_move_price_precentage < difference_tolerance
    is_daily_price_movement_large_enough = day2_move_price_precentage > daily_price_movement_percentage
    is_first_day_close_near_second_day_open = abs(day1_price[0] - day2_price[1]) / day1_price[0] < candle_position_shift_tolerance
    is_first_day_open_near_second_day_close = abs(day1_price[1] - day2_price[0]) / day1_price[1] < candle_position_shift_tolerance


    if trend == 'up' and second_candle_direction > 0 and is_price_movement_within_range and is_daily_price_movement_large_enough and is_first_day_open_near_second_day_close:
        detected = True

    if trend == 'down' and second_candle_direction < 0 and is_price_movement_within_range and is_daily_price_movement_large_enough and is_first_day_open_near_second_day_close:
        detected = True

    return detected


def gap_move(price_data, trend='up'):
    # data point order: close, open, high, low
    day1_price = price_data[0]
    day2_price = price_data[1]

    gap_percentage = 1
    detected = False

    if trend == 'up':
        if day2_price[1] > (day1_price[2] * (1 + gap_percentage / 100.0)) and day2_price[3] > day1_price[2]:
            detected = True
    else:
        if day2_price[1] < (day1_price[3] * (1 - gap_percentage / 100.0)) and day2_price[2] < day1_price[3]:
            detected = True

    return detected


def wave_detection(df):
    """ detecte the length and the waves in the given data frame period """
    """
    the wave object: {
        high: the hiest price,
        low: the lowest price,
        num_high: number of times high is updated
        num_low: number of time low is updated
        start: start date of the wave
        end: end date of the wave
    }
    """

    df = df.set_index('Date').rename(str.lower, axis='columns')
    wave = None
    all_waves = []

    for index, row in df.iterrows():
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


def detect_reversal(df):
    def test(row):
        ipdb.set_trace()

    def map_price_data(rows, detection=push_reversal):
        price_data = [
            [rows[0]['Close'], rows[0]['Open'], rows[0]['High'], rows[0]['Low']],
            [rows[1]['Close'], rows[1]['Open'], rows[1]['High'], rows[1]['Low']]
        ]

        #  return long_tail_reversal_combo(price_data, trend='down')
        return detection(price_data, trend='up')


    #  df['reversal'] = df.rolling(2, axis=0).apply(map_price_data)
    reversal_detected = []

    for index, row in df.iterrows():
        if index == 0:
            reversal_detected.append(False)
            continue

        rows = [df.iloc[index - 1], row]

        reversal_detected.append(map_price_data(rows, long_tail_reversal_combo))

    df['reversal'] = Series(reversal_detected, index=df.index)

    #  df['reversal'] = df.rolling(2, axis=0).apply(map_price_data)
    #  df['reversal'] = pd.rolling_apply(df, 2, map_price_data)
    #  ipdb.set_trace()

