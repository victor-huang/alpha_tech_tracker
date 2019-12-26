from datetime import datetime
import json
import pprint
import threading
import queue
import os
import sys

import alpaca_trade_api as tradeapi
from alpaca_trade_api.polygon.entity import (
    Quote, Trade, Agg, Entity,
)
from alpaca_trade_api.polygon.stream2 import StreamConn as PolygonStreamConn
from alpaca_trade_api.stream2 import StreamConn


from alpha_tech_tracker.redis_client import redis_client

import ipdb
import pandas as pd
from pandas import Timestamp

key_id = os.environ.get('ALPACA_KEY_ID')
secret_key = os.environ.get('ALPACA_SECRET_KEY')

api = tradeapi.REST(key_id, secret_key)

# curl "https://api.polygon.io/v1/historic/quotes/SPY/2018-06-01?apiKey=$APCA_API_KEY_ID"

def now():
    now = datetime.now()

def test_api():
    # polygon/REST.historic_agg(size, symbol, _from=None, to=None, limit=None)
    # https://api.polygon.io/v2/aggs/ticker/AAPL/range/5/minute/2019-01-01/2019-02-01?apiKey=PKX2ZYMDG183VHH2VPYS
    df = api.polygon.historic_agg('minute', 'AMZN', limit=100).df

    ipdb.set_trace()

    # historic_agg_v2(self, symbol, multiplier, timespan, _from, to, unadjusted=False, limit=None)

    amzn_df = api.polygon.historic_agg_v2('AMZN', 5, 'minute', '2019-07-23', '2019-07-24').df
    # historic_trades(self, symbol, date, offset=None, limit=None):
    trades = api.polygon.historic_trades('AMZN', '2019-07-24')

    # snapshot data
    snapshot = api.polygon.snapshot('CMG')
    with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
        print(amzn_df)

def ts():
    return pd.Timestamp.now()

def debug(*args, **kwargs):
    print(ts(), " ", *args, file=sys.stderr, **kwargs)

async def on_data(conn, channel, data):
    #  if opt.debug or not (channel in ('AM', 'Q', 'A', 'T')):
    debug("debug: ", pprint.pformat(data))

def test_stream():
    conn = StreamConn(key_id=key_id, secret_key=secret_key)
    #  conn = PolygonStreamConn(key_id=key_id)

    #  conn.register(r'.*', on_data)
    on_data1 = conn.on(r'.*')(on_data)

    #  conn.run(['AM.*','XQ.*'])
    #  conn.run(['Q.*', 'T.*', 'AM.AMZN', 'A.*'])
    #  conn.run(['Q.AMZN'])
    conn.run(['AM.GOOGL'])
    # sample output
    #  Entity({'ev': 'status', 'message': 'subscribed to: A.*', 'status': 'success'})
    # [{"ev":"T","sym":"MSFT","p":114.178,"x":"5","s":270,"t":1564101092822, .... }]

    # aggregate minutes data into 5 mins in Redis and then save to csv
    # construct real time 5 mins trade data for technical analysis signals
    # integrate with moving average and 7 days historical data to find resistant and support levels

def get_historical_ochl_data(symbol, interval=5, start_date=str(now), end_date=str(now)):
    return api.polygon.historic_agg_v2(symbol, interval, 'minute', start_date, end_date).df

def save_ticker_min_agg_to_redis(agg_data):
    selected_agg_attributes = ['open', 'high', 'low', 'close', 'volume', 'start' , 'end']

    selected_agg_data = {k: v for k, v in agg_data._raw.items() if k in selected_agg_attributes}
    #  selected_agg_data['start'] = datetime.utcfromtimestamp(selected_agg_data['start'] / 1000)
    #  selected_agg_data['end'] = datetime.utcfromtimestamp(selected_agg_data['end'] / 1000)

    cache_key = agg_data.symbol.lower() + "_" + str(selected_agg_data['end'])
    redis_client.set_object(cache_key, selected_agg_data)

def save_ticker_min_agg_to_json(agg_data):
    #
    # save df to json df.to_json(file_path, orient='records')
    # pd.read_json('amzn_5min_sample.json', orient='records')

    selected_agg_attributes = ['open', 'high', 'low', 'close', 'volume', 'start' , 'end']
    selected_agg_data = {k: v for k, v in agg_data._raw.items() if k in selected_agg_attributes}

    data_dir = './market_data'
    #  file_name = agg_data.symbol.lower() + "_" + str(selected_agg_data['end'])
    file_name = agg_data.symbol.lower() + "_min_aggs"
    file_path = '{}/{}'.format(data_dir, file_name)

    f = open(file_path, "a+")
    f.write(json.dumps(selected_agg_data))
    f.write("\n")
    f.close


class DataAggregator(object):
    key_id = 'PKX2ZYMDG183VHH2VPYS'
    secret_key = 'HM6fKUfOVohXWj5JG1bD57hM6LE0xM5NaX9aoUCT'

    def __init__(self):
        self.raw_data_df = pd.DataFrame([], columns = ['open', 'high',
            'low', 'close', 'volume', ])
        self.aggregated_df = pd.DataFrame([], columns = ['open', 'high',
            'low', 'close', 'volume', ])
        self.handlers = {}
        self.selected_agg_attributes = ['open', 'high', 'low', 'close', 'volume', 'start' , 'end']

    def add(self, data):
        selected_data = {k: v for k, v in data._raw.items() if k in self.selected_agg_attributes}
        new_series = pd.Series(selected_data)
        new_series.name = Timestamp(new_series['end'], unit='ms', tz='America/New_York')
        self.raw_data_df = self.raw_data_df.append(new_series)
        latest_timestamp = self.raw_data_df.iloc[-1].name

        if len(self.raw_data_df) >= 5 and latest_timestamp.minute % 5 == 0:
            self.aggregate_to_5_minutes()

            for handler in self.handlers['5min']:
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

        aggregated_seires.name = self.raw_data_df.iloc[-1].name
        self.aggregated_df = self.aggregated_df.append(aggregated_seires)

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

        async def on_data_2(conn, channel, data):
            #  if opt.debug or not (channel in ('AM', 'Q', 'A', 'T')):
            debug("debug: ", pprint.pformat(data))

            if isinstance(data, Agg):
                save_ticker_min_agg_to_json(data)
                aggregator.add(data)

        #  ipdb.set_trace()
        conn = StreamConn(key_id=cls.key_id, secret_key=cls.secret_key)

        on_data1 = conn.on(r'.*')(on_data_2)

        #  conn.run(['Q.*', 'T.*', 'AM.AMZN', 'A.*'])
        #  conn.run(['AM.AMZN'])
        #  ipdb.set_trace()
        subscribe_channels = ['AM.{}'.format(symbol)]

        stream_thread = threading.Thread(target=conn.run, args=([subscribe_channels]))
        stream_thread.start()
        #  conn.run(['AM.AMZN'])
        #  data = {
            #  'average': 1937.4642,
            #  'close': 1940.09,
            #  'dailyopen': 1942,
            #  'end': 1564170660000,
            #  'high': 1940.651,
            #  'low': 1939.665,
            #  'open': 1940.16,
            #  'start': 1564170600000,
            #  'symbol': 'AMZN',
            #  'totalvolume': 4430955,
            #  'volume': 10000,
            #  'vwap': 1940.116
        #  }

        #  for i in range(7):
            #  agg_data = Agg(data)
            #  aggregator.add(agg_data)

            #  data['start'] += 60000
            #  data['end'] += 60000
            #  data['close'] += 1
            #  data['open'] -= 1
            #  data['high'] += 2
            #  data['low'] -= 1

        while True:
            try:
                print('waiting on data')
                data = new_agg_data_queue.get(timeout=timeout)
                time_index = data.name

                yield((time_index, data))
            except queue.Empty:
                print('Timeout on waiting new data')
                break

        conn.loop.call_soon_threadsafe(conn.loop.stop)
        print('Request to stop Event Loop')

        stream_thread.join()
        print('Waiting for market data stream thread to join')
