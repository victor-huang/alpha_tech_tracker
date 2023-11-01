import os
import asyncio
from datetime import date, datetime, time, timedelta
import json
import pprint
import threading
import queue
import os
import sys

import pandas as pd
from pandas import Timestamp
from pytz import timezone

from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.live import StockDataStream


key_id = os.environ.get('ALPACA_KEY_ID')
secret_key = os.environ.get('ALPACA_SECRET_KEY')


stock_client = StockHistoricalDataClient(key_id, secret_key)
wss_client = StockDataStream(key_id, secret_key)


def ts():
    return pd.Timestamp.now()

def debug(*args, **kwargs):
    print(ts(), " ", *args, file=sys.stderr, **kwargs)

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

    pass

def save_ticker_min_agg_to_json(agg_data):
    # save df to json df.to_json(file_path, orient='records')
    # pd.read_json('amzn_5min_sample.json', orient='records')

    selected_agg_attributes = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'start' , 'end']
    selected_agg_data = {k: v for k, v in agg_data.dict().items() if k in selected_agg_attributes}
    selected_agg_data['timestamp'] = selected_agg_data['timestamp'].isoformat()

    data_dir = './market_data'
    #  file_name = agg_data.symbol.lower() + "_" + str(selected_agg_data['end'])
    file_name = agg_data.symbol.lower() + "_min_aggs"
    file_path = '{}/{}'.format(data_dir, file_name)

    f = open(file_path, "a+")
    f.write(json.dumps(selected_agg_data))
    f.write("\n")
    f.close

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


class DataAggregator(object):
    generator_queues = []
    aggregators_by_symbol = {}

    def __init__(self):
        self.key_id = os.environ.get('ALPACA_KEY_ID')
        self.secret_key = os.environ.get('ALPACA_SECRET_KEY')

        self.raw_data_df = pd.DataFrame([], columns = ['open', 'high',
            'low', 'close', 'volume'])
        self.aggregated_df = pd.DataFrame([], columns = ['open', 'high',
            'low', 'close', 'volume'])
        self.handlers = {}
        self.selected_agg_attributes = ['open', 'high', 'low', 'close', 'volume', 'timestamp']

    def add(self, data):
        selected_data = {k: v for k, v in data.dict().items() if k in self.selected_agg_attributes}

        new_series = pd.Series(selected_data)
        new_series.reset_index(0, drop=True)
        new_series['timestamp'] = new_series['timestamp'].astimezone(timezone('America/New_York'))
        new_series.name = new_series['timestamp']
        self.raw_data_df.loc[new_series.name] = new_series

        latest_timestamp = self.raw_data_df.iloc[-1].name

        debug("debug: ", pprint.pformat(self.raw_data_df))
        
        # we start at 0, so accumuated 5 min at 04 and 09
        if len(self.raw_data_df) >= 5 and (latest_timestamp.minute % 10 == 4 or latest_timestamp.minute % 10 == 9) :
            self.aggregate_to_5_minutes()
            five_mins_handlers = self.handlers.get('5min')

            if five_mins_handlers:
                for handler in five_mins_handlers:
                    handler(self.aggregated_df.iloc[-1].copy())

    def aggregate_to_5_minutes(self):
        interval = 5

        aggregated_seires = pd.Series({
            'open': self.raw_data_df.iloc[-interval]['open'],
            'close': self.raw_data_df.iloc[-1]['close'],
            'low': min(self.raw_data_df[-interval:]['low']),
            'high': max(self.raw_data_df[-interval:]['high']),
            'volume': sum(self.raw_data_df[-interval:]['volume'])
        })

        aggregated_seires.name = self.raw_data_df.iloc[-5].name
        self.aggregated_df.loc[aggregated_seires.name] = aggregated_seires

        debug("debug: ", pprint.pformat(self.aggregated_df))

    def register(self, interval, fn):
        if interval not in ['5min']:
            raise ValueError("interval needs to be: ['5min']")

        if interval in self.handlers:
            self.handlers[interval].append(fn)
        else:
            self.handlers[interval] = [fn]

    @classmethod
    def fetch_5_mins_aggregated_data(cls, timeout=300, symbol=None):
        """
        timeout: default to 5 minutes second, if there is no more data in the next 5 mins,
            it will raise queue.Empty error
        :return: a generator that waits for the next 5 mins aggregate market data
        """

        if not symbol:
            raise ValueError("Symbol can not be None")

        new_agg_data_queue = queue.Queue()
        aggregator = DataAggregator()
        aggregator.register('5min', lambda data: new_agg_data_queue.put(data))

        async def on_data_2(data):
            debug("debug: ", pprint.pformat(data))
            save_ticker_min_agg_to_json(data)
            aggregator.add(data)

        async def bar_data_handler(data):
            debug(data)

        wss_client.subscribe_bars(on_data_2, symbol)


        stream_thread = threading.Thread(target=wss_client.run, args=())
        stream_thread.start()

        while True:
            try:
                debug('waiting on market data')
                data = new_agg_data_queue.get(timeout=timeout)
                time_index = data.name

                yield((time_index, data))
            except queue.Empty:
                debug('Timeout on waiting new market data')
                break

        conn.loop.call_soon_threadsafe(conn.loop.stop)
        debug('Request to stop Event Loop')

        stream_thread.join()
        debug('Waiting for market data stream thread to join')

    @classmethod
    def start_streaming_market_data(cls, timeout=300, symbols=[]):
        if not symbols:
            raise ValueError("Symbols can not be empty")

        cls.aggregators_by_symbol = {}
        cls.stop_streaming_thread = False

        for symbol in symbols:
            cls.aggregators_by_symbol[symbol] = DataAggregator()

        async def handle_streaming_minute_agg_data(data):
            debug("debug: ", pprint.pformat(data))
            save_ticker_min_agg_to_json(data)

            aggregator = cls.aggregators_by_symbol.get(data.symbol)

            if aggregator:
                aggregator.add(data)
            else:
                debug('No aggregator for symbol {}'.format(data.symbol))

        wss_client.subscribe_bars(handle_streaming_minute_agg_data, *symbols)

        stream_thread = threading.Thread(
                target=wss_client.run,
                args=()
        )

        cls.stream_thread = stream_thread
        cls.stream_thread.start()
        cls.handle_streaming_minute_agg_data = handle_streaming_minute_agg_data

    @classmethod
    def stop_streaming_market_data(cls):
        cls.stop_streaming_thread = True
        wss_client.stop()
        debug('Request to stop Event Loop')
        cls.stream_thread.join()

        for g_queue in cls.generator_queues:
            g_queue.put(None)


    @classmethod
    def build_mins_aggregated_data_generator(cls, symbol, timeout=300):
        agg_interval = '5min'
        new_agg_data_queue = queue.Queue()
        cls.generator_queues.append(new_agg_data_queue)
        aggregator = cls.aggregators_by_symbol[symbol]
        aggregator.register(agg_interval, lambda data: new_agg_data_queue.put(data))

        while True:
            debug('waiting on data')
            try:
                data = new_agg_data_queue.get(timeout=timeout)

                if data is not None:
                    time_index = data.name
                    yield((time_index, data))
                else:
                    debug('market data generator stoped')
                    break
            except queue.Empty:
                debug("Timeout getting data")
                break
