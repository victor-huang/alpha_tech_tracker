import pandas as pd

import alpha_tech_tracker.technical_analysis as ta

import ipdb

def load_from_csv():
    #  df = pd.read_csv('./tests/data/wfc.csv')
    df = pd.read_csv('./tests/data/fb.csv')
    adjusted_close_df = df[['Date', 'Adj Close']]
    adjusted_close_df.set_index('Date', inplace=True)

    result_df = ta.moving_average_summary([20, 50, 100, 150, 200], adjusted_close_df)
    ipdb.set_trace()
