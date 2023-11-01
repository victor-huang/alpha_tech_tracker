from alpha_tech_tracker.alpaca_py_engine import (
    DataAggregator,
    wss_client
)


"""
Example Dataframe from calling stream api

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


class TestDataAggregator:
    # integration test
    def test_straeming_5_min_aggregate_data(self):
        DataAggregator.fetch_5_mins_aggregated_data(symbol='TSLA')
        [print(x) for x in DataAggregator.fetch_5_mins_aggregated_data(symbol='TSLA')]

    # DataAggregator.start_streaming_market_data(symbols=['TSLA', 'QQQ'])


# integration test
def test_stream_client_and_data_handler():
    """
    https://alpaca.markets/docs/market-data/
    Sample test handel of stock quote and bar data
    """

    async def quote_data_handler(data):
        # quote data will arrive here
        #  symbol='TSLA' timestamp=datetime.datetime(2023, 9, 25, 15, 57, 59, 910132, tzinfo=datetime.timezone.utc) ask_exchange='V' ask_price=248.0 ask_size=2.0 bid_exchange='V' bid_price=245.9 bid_size=1.0 conditions=['R'] tape='C'
        print(data)

    async def bar_data_handler(data):
        # symbol='TSLA' timestamp=datetime.datetime(2023, 9, 25, 15, 57, tzinfo=datetime.timezone.utc) open=246.06 high=246.06 low=246.06 close=246.06 volume=195.0 trade_count=6.0 vwap=246.012872
        #  symbol='TSLA' timestamp=datetime.datetime(2023, 9, 25, 16, 0, tzinfo=datetime.timezone.utc) open=246.11 high=246.11 low=245.88 close=245.88 volume=473.0 trade_count=10.0 vwap=246.077019
        # bar data will arrive here
        print(data)

    async def updated_bar_data_handler(data):
        print(f"***{data}***")
        print(data)

    async def trade_data_handler(data):
        #symbol='TSLA' timestamp=datetime.datetime(2023, 9, 25, 16, 0, 3, 355190, tzinfo=datetime.timezone.utc) exchange='V' price=246.11 size=100.0 id=5143 conditions=['@'] tape='C'
        print(data)

    #  wss_client.subscribe_quotes(quote_data_handler, "TSLA")
    wss_client.subscribe_bars(bar_data_handler, "TSLA")
    wss_client.subscribe_updated_bars(updated_bar_data_handler, "TSLA")
    #  wss_client.subscribe_trades(quote_data_handler, "TSLA")
    wss_client.run()
