import os

from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime


#  trading_client = TradingClient('api-key', 'secret-key')

key_id = os.environ.get('ALPACA_KEY_ID')
secret_key = os.environ.get('ALPACA_SECRET_KEY')


stock_client = StockHistoricalDataClient(key_id, secret_key)


def test_stock_bar_data_api():
    stock_request_params = StockBarsRequest(
        symbol_or_symbols=["TSLA"],
        timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
        start=datetime.strptime("2023-09-01", '%Y-%m-%d'),
        end=datetime.strptime("2023-09-11", '%Y-%m-%d'),
    )

    bars = stock_client.get_stock_bars(stock_request_params)

    bars.df # to get the coodsponding dataframe

    import ipdb; ipdb.set_trace()
    # only use timestamp as index
    bars.df.reset_index(level=0, drop=True)
    df.index = df.index.tz_convert('America/New_York')

    pass


def get_historical_stock_data(ticker, start, end):
    stock_request_params = StockBarsRequest(
        symbol_or_symbols=[ticker],
        timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
        start=datetime.strptime(start, '%Y-%m-%d'),
        end=datetime.strptime(end, '%Y-%m-%d')
    )

    bars = stock_client.get_stock_bars(stock_request_params)
    df = bars.df.reset_index(level=0, drop=True)
    df.index = df.index.tz_convert('America/New_York')

    return df



##############

#  from alpaca.data.historical import CryptoHistoricalDataClient
#  from alpaca.data.requests import CryptoBarsRequest
#  from alpaca.data.timeframe import TimeFrame
#  from datetime import datetime

#  # no keys required for crypto data
#  client = CryptoHistoricalDataClient()

#  request_params = CryptoBarsRequest(
                        #  symbol_or_symbols=["BTC/USD", "ETH/USD"],
                        #  timeframe=TimeFrame.Day,
                        #  start=datetime(2022, 7, 1)
                 #  )

#  bars = client.get_crypto_bars(request_params)

"""
ipdb> test_data_df_list[0]
                        open     high      low    close  volume
2019-01-02 09:00:00  1473.01  1473.01  1461.42  1461.42    3233
2019-01-02 09:10:00  1465.67  1467.25  1465.67  1467.00     742
2019-01-02 09:40:00  1468.00  1468.00  1465.50  1465.50     678
2019-01-02 10:00:00  1472.15  1472.15  1472.15  1472.15     152
2019-01-02 10:05:00  1472.00  1472.00  1472.00  1472.00     240
...                      ...      ...      ...      ...     ...
2019-01-15 23:25:00  1685.31  1685.31  1684.67  1684.67    2139
2019-01-15 23:40:00  1685.00  1685.00  1685.00  1685.00     230
2019-01-15 23:45:00  1684.07  1684.07  1684.07  1684.07     127
2019-01-15 23:50:00  1684.00  1684.00  1684.00  1684.00     261
2019-01-15 23:55:00  1684.20  1684.20  1684.20  1684.20     276

[1483 rows x 5 columns]
ipdb> test_data_df_list[0][0]
*** KeyError: 0
ipdb> test_data_df_list[0].iloc[0]
open      1473.01
high      1473.01
low       1461.42
close     1461.42
volume    3233.00
Name: 2019-01-02 09:00:00, dtype: float64


                                      open    high     low   close    volume  trade_count        vwap
symbol timestamp                                                                                     
TSLA   2023-09-11 08:00:00+00:00  258.2500  259.02  254.60  258.75  249015.0       4229.0  257.973932
       2023-09-11 08:05:00+00:00  258.9000  259.51  258.50  259.50   98451.0       2157.0  258.974502
       2023-09-11 08:10:00+00:00  259.5300  261.60  259.49  261.00  220441.0       4018.0  260.571689
       2023-09-11 08:15:00+00:00  260.9100  263.00  260.63  262.82  179833.0       3805.0  262.001938
       2023-09-11 08:20:00+00:00  262.8200  263.00  262.02  262.71  109809.0       2320.0  262.593130
...                                    ...     ...     ...     ...       ...          ...         ...
       2023-09-12 23:35:00+00:00  267.6001  267.64  267.57  267.61   12866.0        168.0  267.604280
       2023-09-12 23:40:00+00:00  267.6100  267.66  267.61  267.66    9209.0        152.0  267.628149
       2023-09-12 23:45:00+00:00  267.6600  267.70  267.61  267.67   13653.0        225.0  267.655917
       2023-09-12 23:50:00+00:00  267.6400  267.69  267.55  267.65   20659.0        275.0  267.614288
       2023-09-12 23:55:00+00:00  267.6700  267.76  267.60  267.70   26514.0        387.0  267.698834

[384 rows x 7 columns]
ipdb> bars.df[0]
*** KeyError: 0
ipdb> bars.df.loc[0, :]
*** KeyError: 0
ipdb> bars.df.iloc[0, :]
open              258.250000
high              259.020000
low               254.600000
close             258.750000
volume         249015.000000
trade_count      4229.000000
vwap              257.973932
Name: (TSLA, 2023-09-11 08:00:00+00:00), dtype: float64

"""

