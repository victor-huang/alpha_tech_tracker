import json
import time
import threading
from unittest.mock import MagicMock

import alpha_tech_tracker.alpaca_engine as alpaca
from alpha_tech_tracker.alpaca_engine import DataAggregator

from alpaca_trade_api.polygon.entity import (
    Quote, Trade, Agg, Entity,
)
from alpha_tech_tracker.redis_client import redis_client

import pandas as pd
from pandas import Timestamp
import ipdb

def test_save_ticker_min_agg_to_redis():
    agg_data = Agg({
        'average': 1937.4642,
        'close': 1940.09,
        'dailyopen': 1942,
        'end': 1564170660000,
        'high': 1940.651,
        'low': 1939.665,
        'open': 1940.16,
        'start': 1564170600000,
        'symbol': 'AMZN',
        'totalvolume': 4430955,
        'volume': 13214,
        'vwap': 1940.116
    })

    alpaca.save_ticker_min_agg_to_redis(agg_data)
    #  ipdb.set_trace()
    assert redis_client.get_object(agg_data.symbol.lower() + '_' + str(agg_data._raw['end'])) != None


def test_save_ticker_min_agg_to_json():
    agg_data = Agg({
        'average': 1937.4642,
        'close': 1940.09,
        'dailyopen': 1942,
        'end': 1564170660000,
        'high': 1940.651,
        'low': 1939.665,
        'open': 1940.16,
        'start': 1564170600000,
        'symbol': 'AMZN',
        'totalvolume': 4430955,
        'volume': 13214,
        'vwap': 1940.116
    })

    alpaca.save_ticker_min_agg_to_json(agg_data)
    #  ipdb.set_trace()
    #  assert


def test_convert_realtime_data_to_5min_interval_data():
    data = {
        'average': 1937.4642,
        'close': 1940.09,
        'dailyopen': 1942,
        'end': 1564170660000,
        'high': 1940.651,
        'low': 1939.665,
        'open': 1940.16,
        'start': 1564170600000,
        'symbol': 'AMZN',
        'totalvolume': 4430955,
        'volume': 10000,
        'vwap': 1940.116
    }
    aggregator = DataAggregator()
    mock_fn = MagicMock()
    aggregator.register('5min', mock_fn)

    for i in range(7):
        agg_data = Agg(data)
        aggregator.add(agg_data)

        data['start'] += 60000
        data['end'] += 60000
        data['close'] += 1
        data['open'] -= 1
        data['high'] += 2
        data['low'] -= 1

    assert aggregator.aggregated_df.iloc[-1]['volume'] == 50000.0
    assert aggregator.aggregated_df.iloc[-1]['open'] == 1940.16
    assert aggregator.aggregated_df.iloc[-1]['close'] == 1944.09
    assert aggregator.aggregated_df.iloc[-1]['high'] == 1948.651
    assert aggregator.aggregated_df.iloc[-1]['low'] == 1935.665
    assert aggregator.aggregated_df.iloc[-1].name == Timestamp('2019-07-26 15:55:00-0400', tz='America/New_York')

    mock_fn.assert_called()

def test_stream():
    #  alpaca.test_stream()
    [print(x) for x in DataAggregator.fetch_5_mins_aggregated_data()]

def test_start_streaming_market_data():
    #  from alpha_tech_tracker.strategy import SimpleStrategy

    DataAggregator.start_streaming_market_data(symbols=['AMZN'])
    generator_lambd = lambda : print(['*' for x in DataAggregator.build_mins_aggregated_data_generator('AMZN')])

    thread = threading.Thread(target=generator_lambd)
    thread.start()
    time.sleep(2)

    alpaca.simulate_stream_minute_aggreated_market_data_from_file(
        './market_data/amzn_min_aggs',
        'AMZN',
        40
    )

    #  new_strategy_1 = SimpleStrategy(symbol='AMZN')
    #  new_strategy_1.simulate(start='2020-01-01', end='2020-01-02', use_saved_data=False, stream_data=True)

    #  ipdb.set_trace()
    # safely stops and cleanup
    DataAggregator.stop_streaming_market_data()
    thread.join()
