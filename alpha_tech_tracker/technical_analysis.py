import pandas as pd

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
