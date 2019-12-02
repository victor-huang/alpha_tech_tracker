from datetime import time
from datetime import datetime
from datetime import timedelta
from decimal import Decimal

#  from functools import reduce
import pandas as pd
from pandas import Series
import pprint as pp
#  import numpy as np
import plotly.graph_objects as go

from alpha_tech_tracker.order_engine import OrderEngine
from alpha_tech_tracker.portfolio import Portfolio
from alpha_tech_tracker.signal import Signal
import alpha_tech_tracker.technical_analysis as ta
import alpha_tech_tracker.alpaca_engine as alpaca
from alpha_tech_tracker.wave import Wave

import ipdb

class Strategy(object):
    def __init__(self):
        pass

    def simulate(self, *, start, end):
        pass

    def check_buy_condition(self):
        pass

    def check_sell_condition(self):
        pass

    def close_all_open_positions(self):
        pass

    def signal_event_handler(self):
        pass

    def market_event_handler(self):
        pass

    def order_event_handler(self):
        pass


# good at up trend, good protection on sharp downtrend
# ok loos on long consolidation e.g (start='2019-08-06', end='2019-09-23')
class SimpleStrategy(Strategy):
    def __init__(self):
        # load 300 5-min interval data, so we can generate 200-d
        # moving average lines
        self.symbol = 'AMZN'
        self.prepare_market_data()
        self.signals_by_times = {}
        self.portfolio = Portfolio()
        self.active_positions = {}
        self.pending_positions_data_by_order = {}
        self.active_order_to_position_map = {}
        self.order_engine = OrderEngine()
        self.waves = []
        self.cached_waves_last_wave = {}

        self.maximum_position_loss = 3000
        self.buy_trigger_up_waves_ratio = 0.5
        #  self.buy_trigger_up_magnitude_ratio = 0.55 # v1 0.6
        self.buy_trigger_up_magnitude_ratio = 0.55 # v1 0.6

    def prepare_market_data(self):
        #  alpaca.get_historical_ochl_data('AMZN', start_date='2019-11-20', end_date='2019-11-23')
        # it has 4xx data points
        #  df = pd.read_json('./market_data/amzn_5min_sample.json')[:200]
        df = pd.read_json('./market_data/amzn_5min_2019-11-13_2019-11-23.json')
        #  df = alpaca.get_historical_ochl_data(self.symbol, start_date='2019-11-18', end_date='2019-11-23')[:200]

        close_price_df = df[['close']].copy()
        moving_avgs_df = ta.moving_average_summary([20, 50, 100, 200], close_price_df)
        self.market_data_df = df
        self.moving_avgs_df = moving_avgs_df

    def plot_data(self, df, chart_html_file_name='chart.html'):
        # getting y-axis to work
        # https://github.com/plotly/plotly.py/issues/932
        fig = go.Figure(data=[go.Candlestick(x=df.index,
                        open=df['open'],
                        high=df['high'],
                        low=df['low'],
                        close=df['close'])],
                        layout={
                            'xaxis': { 'rangeslider': { 'visible': False } }
                        }
        )
        fig.write_html(chart_html_file_name, auto_open=True)

    def set_trace_at(self, stop_at_time_str):
        if self.market_data_df[-1:].index[0] == datetime.strptime(stop_at_time_str, '%Y-%m-%d %H:%M:%S%z'):
            ipdb.set_trace()

    def export_data_to_json(self, symbol, start='', end=''):
        date_range = [
            ['2018-01-01', '2018-03-31'],
            ['2018-04-01', '2018-06-30'],
            ['2018-06-01', '2018-08-31'],
            ['2018-09-01', '2018-12-31']
            ['2019-01-01', '2019-03-31'],
            ['2019-04-01', '2019-06-30'],
            ['2019-06-01', '2019-08-31'],
            ['2019-09-01', '2019-12-31']
        ]

        for (start, end) in date_range:
            file_name = './test_data/{}_{}_{}.json'.format(symbol, start, end)
            print(file_name)
            ipdb.set_trace()
            df = alpaca.get_historical_ochl_data(symbol, start_date=start, end_date=end)
            df.to_json(file_name,  orient='index')

    def read_data_from_files(self, symbol, start='', end=''):
        date_range = [
            ['2018-01-01', '2018-03-31'],
            ['2018-04-01', '2018-06-30'],
            ['2018-06-01', '2018-08-31'],
            ['2018-09-01', '2018-12-31'],
            ['2019-01-01', '2019-03-31'],
            ['2019-04-01', '2019-06-30'],
            ['2019-06-01', '2019-08-31'],
            ['2019-09-01', '2019-12-31']
        ]

        loaded_data_df = pd.DataFrame()

        for (r_start, r_end) in date_range:
            file_name = './test_data/{}_{}_{}.json'.format(symbol, r_start, r_end)
            print(file_name)
            df = pd.read_json(file_name, orient='index')
            if df[start:end].empty:
                continue

            #  if loaded_data_df == None:
                #  loaded_data_df = df
            #  else:
            loaded_data_df = loaded_data_df.append(df[start:end])

        #  ipdb.set_trace()
        # set to Easten time zone
        loaded_data_df.index = loaded_data_df.index.tz_localize(0).tz_convert(-3600*4)
        return loaded_data_df

    # start='2019-11-13', end='2019-11-16' interestnig
    #  def simulate(self, *, start='2019-11-18', end='2019-11-23'):
    # down trend start='2019-07-22', end='2019-08-03'
    # down trend start='2019-11-08', end='2019-11-20'
    # down trend start='2019-05-23', end='2019-06-04'
    # up trend start='2019-09-30', end='2019-10-18')
    # up trend start='2019-06-03', end='2019-06-12'
    # up trend start='2019-06-28', end='2019-07-11')
    # up trend start='2019-03-08', end='2019-03-22' # highest profits
    # update trend start='2019-03-28', end='2019-04-24'
    # consolidation  start='2019-08-01', end='2019-09-17'
    # long uptrend test start='2019-03-13', end='2019-05-09'
    def simulate(self, *, start='2019-03-13', end='2019-05-09'):
        self.simulation_mode_on = True
        self.bullish_up_wave_move_size = 100 # 78 is the max wave length
        #  self.bullish_up_wave_magnitude_ratio = 0.6 # v1
        self.bullish_up_wave_magnitude_ratio = 0.6
        self.trade_counts_by_date = {}

        # the api need +1 day for end date
        end_date = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
        end_date_str = end_date.strftime('%Y-%m-%d')

        #  df = alpaca.get_historical_ochl_data(self.symbol, start_date=start, end_date=end_date_str)

        #  df.to_json('./amzn_2018_01_2018_03.json', orient='table')
        #  self.export_data_to_json('AMZN')
        df = self.read_data_from_files('AMZN', start=start, end=end_date_str)

        #  dfr = pd.read_json('./amzn_2018_01_2018_03.json',  orient='table')
        #  df.to_json('./amzn_5min_2019-11-13_2019-11-23')

        preload_data_period = 200
        #  future_market_data_df = df[preload_data_period + 1: preload_data_period + 200]
        future_market_data_df = df[1:]
        close_price_df = df[:preload_data_period][['close']].copy()
        moving_avgs_df = ta.moving_average_summary([20, 50, 150, 200], close_price_df)
        self.market_data_df = df[:1].copy()
        #  t_time = datetime.strptime('2019-11-22 13:45:00-0500', '%Y-%m-%d %H:%M:%S%z')
        #  self.market_data_df = df[:t_time].copy()
        self.moving_avgs_df = moving_avgs_df

        #  self.plot_data(df, chart_html_file_name='{}_chart_{}.html'.format(self.symbol, start + '_' + end)) # graph on

        for period_index, (index_timestamp, market_data_row) in enumerate(future_market_data_df.iterrows()):
            if self.is_after_hours(index_timestamp):
                continue
            if period_index <= preload_data_period:
                # preloading data until enough data to caculating moving average
                self.add_data_point_to_wave(index_timestamp, market_data_row)
                self.market_data_df.loc[index_timestamp] = market_data_row
                continue

            # generate signals

            print("{}, price: {}, market_data_size: {}".format(index_timestamp, market_data_row['close'], len(self.market_data_df)))
            self.market_data_event_handler(index_timestamp, market_data_row)

            signals = self.generate_signals(index_timestamp, market_data_row)

            if signals:
                print([s.__dict__ for s in signals])

            [self.signal_event_handler(s) for s in signals]
            #  # process orders
            #  order_event_handler()
            executed_orders = self.order_engine.execute_orders()

            for order in executed_orders:
                self.order_event_handler(order)

        for p in self.portfolio.positions:
            if p.status == 'open':
                p.close_price = Decimal(future_market_data_df[-1:]['close'][0])
                p.status == 'closed'

        pp.pprint(self.portfolio.calculate_pnl())

    # TODO:
    # wave count accrose days, which should not happen in 5-mins in intervals
    # return: the waves from oldest to latest order
    def waves_anlyasis(self, last_n_period=78, df=None): # 78, 5-mins periods is a trading day, 120 is a bit more than a day and a half
        df = self.market_data_df[-last_n_period:]
        wave = None
        all_waves = []

        for timestamp_index, row in df.iterrows():
            if not wave:
                wave = Wave(timestamp_index, row)
                all_waves.append(wave)
            else:
                new_wave = wave.count(timestamp_index, row,
                        time_increment=timedelta(minutes=5))

                if new_wave:
                    all_waves.append(new_wave)
                    wave = new_wave

        for w in all_waves[-20:]:
            summary = w.summary()
            print(summary)

        return all_waves

    def waves_for_last_n_period(self, n=120):
        all_waves = []
        total_time_period = 0

        #  self.set_trace_at('2019-03-11 10:05:00-0400')

        last_wave = self.waves[-1]
        key = (last_wave, n)

        # leverage cache to speed things up a bit
        if key not in self.cached_waves_last_wave:
            for w in reversed(self.waves[-20:]):
                summary = w.summary()
                print(summary)
                total_time_period += summary['length']
                all_waves.append(w)

                if total_time_period >= n:
                    break

            selected_waves_from_old_to_new = all_waves[::-1]
            self.cached_waves_last_wave[key] = selected_waves_from_old_to_new

            return selected_waves_from_old_to_new
        else:
            return self.cached_waves_last_wave[key]

    def add_data_point_to_wave(self, timestamp_index, current_data_row):
        if not self.waves:
            wave = Wave(timestamp_index, current_data_row)
            self.waves.append(wave)
        else:
            new_wave = self.waves[-1].count(timestamp_index, current_data_row,
                    time_increment=timedelta(minutes=5))
            if new_wave:
                self.waves.append(new_wave)

    def generate_signals(self, index_timestamp, current_data_row):
        price_data = self.df_to_price_data_array(self.get_latest_periods_market_data(index_timestamp, current_data_row, n=2))
        reversal_fns = { 
            'long_tail_reversal_combo': ta.long_tail_reversal_combo,
            #  'engulfing_reversal': ta.engulfing_reversal,
            #  'push_reversal': ta.push_reversal,
            'gap_move': ta.gap_move
        }

        signals = []

        for name, detection_fn in reversal_fns.items():
            if name == 'gap_move':
                daily_movement_minimum = 0.5 # 50%
            else:
                daily_movement_minimum = 0.01 / (12 * 8)

            if detection_fn(price_data, trend='up', daily_movement_minimum=daily_movement_minimum):
                # name, category, symbol=None, signaled_at=datetime.now()):
                signal_name = name + '-' + 'up_trend'
                signals.append(Signal(name=signal_name, category='ta', trend='up', symbol=self.symbol, signaled_at=index_timestamp))
            if detection_fn(price_data, trend='down', daily_movement_minimum=daily_movement_minimum):
                signal_name = name + '-' + 'down_trend'
                signals.append(Signal(name=signal_name, category='ta', trend='down', symbol=self.symbol, signaled_at=index_timestamp))

        return signals

    def get_latest_periods_market_data(self, index_timestamp, current_data_row, n=5):
        total_peridos = len(self.market_data_df)
        last_n_periods_df = self.market_data_df[total_peridos - n:].copy()
        last_n_periods_df.loc[index_timestamp] = current_data_row

        return last_n_periods_df[len(last_n_periods_df) - n:]

    def df_to_price_data_array(self, df):
        return [[r['close'], r['open'], r['high'], r['low']] for index, r in df.iterrows()]


    # return the potential upside target in price
    def upside_potential(self, current_price, waves=[]):
        last_n_price_data_df = self.market_data_df[-20:]
        last_n_price_data_df['close'].max() - current_price

        waves_stats = Wave.waves_stats(waves)
        upside_magnitudes = [ w.price_range() for w in waves[-5:] if w.direction() == 'up'] + [
                last_n_price_data_df['close'].max() - current_price]

        #  self.set_trace_at('2019-06-07 09:30:00-0400')
        #  self.set_trace_at('2018-02-20 10:00:00-0500')
        if waves_stats['up_waves_ratio'] > 0.6 and waves_stats['up_wave_move_length'] >= self.bullish_up_wave_move_size and waves_stats['up_magnitude_ratio'] > self.bullish_up_wave_magnitude_ratio:
            # up too much lately, take less risk
            return min(upside_magnitudes) * 0.95
        else:
            return max(upside_magnitudes) * 0.95

    def downside_risk(self, current_price, waves=[]):
        mavg_20_price = self.moving_avgs_df[-1:]['mavg_20'][0]

        if current_price < mavg_20_price:
            last_n_price_data_df = self.market_data_df[-10:]
            risk_price = last_n_price_data_df['close'].min()
        else:
            risk_price = mavg_20_price

        if current_price - risk_price == 0:
            return 0.01
        else:
            return (current_price - risk_price) * 1.1

    def risk_reward_ratio(self, current_price, waves=[]):
        return self.upside_potential(current_price, waves=waves) / self.downside_risk(current_price, waves=waves)

    def has_strong_buy_after_sell_off(self, waves_stats):
        return waves_stats['strong_up_wave_index'] > waves_stats['strong_down_wave_index'] and waves_stats['up_waves_ratio'] < 0.5 and waves_stats['up_magnitude_ratio'] > 0.38

    def check_buy_condition(self):
        current_price = self.market_data_df[-1:]['close'][0]
        waves = self.waves_for_last_n_period()
        waves_stats = Wave.waves_stats(waves)

        print("** Time at: {} , up: {}, down {}, ratio {}".format(self.current_time_period().isoformat(), self.upside_potential(current_price, waves=waves),
            self.downside_risk(current_price, waves=waves),
            self.risk_reward_ratio(current_price, waves=waves)))

        #  self.set_trace_at('2019-03-22 09:55:00-0400')
        #  self.set_trace_at('2019-03-22 11:15:00-0400')

        if self.risk_reward_ratio(current_price, waves=waves) > 1.5 and not self.active_positions and not self.is_close_to_after_hours() and not self.is_right_before_market_close():
            current_time_period = self.current_time_period()
            current_date = current_time_period.date()

            if current_date not in self.trade_counts_by_date:
                self.trade_counts_by_date[current_date] = 0
            elif self.trade_counts_by_date[current_date] >= 2:
                # don't make more than 2 trades per day
                print("Maximum trade per day reached")
                return

            #  self.set_trace_at('2019-06-07 09:30:00-0400')

            #  self.set_trace_at('2018-12-19 14:55:00-0400')

            if (waves_stats['up_waves_ratio'] >= self.buy_trigger_up_waves_ratio and waves_stats['up_magnitude_ratio'] > self.buy_trigger_up_magnitude_ratio) or self.has_strong_buy_after_sell_off(waves_stats):
                # open a new position
                new_order = self.order_engine.place(symbol=self.symbol, side='buy',
                        price=current_price, quantity=100, type='limit')

                #  self.set_trace_at('2019-06-07 09:30:00-0400')
                self.pending_positions_data_by_order[new_order.id] = {
                    #  'target_price': self.upside_potential(current_price) + current_price,
                    'target_price': self.upside_potential(current_price, waves=waves) + current_price,
                    'cut_loss_price': current_price - self.downside_risk(current_price),
                    'attempt_open_at': current_time_period                }

                self.active_order_to_position_map[new_order.id] = None
                print('Buy 100 stock at price {}, target price: {}, cut loss at: {}'.format(current_price, self.pending_positions_data_by_order[new_order.id]['target_price'], self.pending_positions_data_by_order[new_order.id]['cut_loss_price']))

                self.trade_counts_by_date[current_date] += 1

    def is_right_before_market_close(self):
        return self.market_data_df[-1:].index[0].strftime('%H:%M') == '15:55'

    def current_time_period(self):
        return self.market_data_df[-1:].index[0]

    def current_time_period_price(self):
        return self.market_data_df[-1:]['close'][0]

    def is_close_to_after_hours(self, current_timestamp=None):
        if not current_timestamp:
            current_time = self.current_time_period().time()
        else:
            current_time = current_timestamp.time()

        return  current_time > time(15, 55)

    def is_after_hours(self, current_timestamp=None):
        if not current_timestamp:
            current_time = self.current_time_period()
        else:
            current_time = current_timestamp.time()

        return  current_time > time(16, 0) or current_time < time(9, 30)

    def check_sell_condition(self):
        current_price = self.market_data_df[-1:]['close'][0]
        current_time_period = self.market_data_df[-1:]

        for position_id, targets in self.active_positions.items():
            waves = self.waves_for_last_n_period()
            waves_stats = Wave.waves_stats(waves)

            #  self.set_trace_at('2018-02-14 09:45:00-0500')
            if current_price >= targets['target_price'] or current_price <= targets['cut_loss_price'] or self.is_right_before_market_close() or self.is_waves_loosing_steam(position_id, waves=waves) or self.is_maximum_loss_reached(position_id):
                # close the position
                print('Close the position {} at price {}'.format(position_id, current_price))

                if position_id not in self.active_order_to_position_map.values():
                    new_order = self.order_engine.place(symbol=self.symbol, side='sell',
                            price=current_price, quantity=100, type='limit')

                    self.active_order_to_position_map[new_order.id] = position_id

    def is_maximum_loss_reached(self, position_id):
        position = self.portfolio.find_position(position_id)

        if (position.open_price - Decimal(self.current_time_period_price())) * 100 >= self.maximum_position_loss:
            return True

        return False

    def is_waves_loosing_steam(self, position_id, waves=[]):
        num_of_waves = 3
        current_price = self.current_time_period_price()
        position_target_data = self.active_positions[position_id]
        last_few_waves = waves[-num_of_waves:]

        if len(last_few_waves) < num_of_waves:
            return None
        else:
            position = self.portfolio.find_position(position_id)
            waves_stats = Wave.waves_stats(last_few_waves)

            #  {'up_waves_ratio': 0.3333333333333333, 'up_magnitude_ratio': 0.1453418167288059, 'number_of_up_waves': 1, 'number_of_down_waves': 2, 'up_wave_move_length': 2, 'down_wave_move_length': 17, 'strong_up_wave_index': -1, 'strong_down_wave_index': -1}
            is_down_wave_pickup_steam = waves_stats['up_wave_move_length'] * 3 < waves_stats['down_wave_move_length'] and waves_stats['up_magnitude_ratio'] < 0.2

            if last_few_waves[0].start > position.open_at and position.open_price > current_price or is_down_wave_pickup_steam:
                return True

    def close_all_open_positions(self):
        pass

    def signal_event_handler(self, signal):
        datetime_hash = signal.signaled_at

        if datetime_hash in self.signals_by_times:
            self.signals_by_times[datetime_hash].append(signal)
        else:
            self.signals_by_times[datetime_hash] = []

        if signal.trend == 'up':
            self.check_buy_condition()
        else:
            self.check_sell_condition()

    def update_market_data_related_stats(self, index_timestamp, market_data_row):
        self.market_data_df.loc[index_timestamp] = market_data_row

        close_price_df = self.market_data_df[['close']].copy()
        self.moving_avgs_df = ta.moving_average_summary([20, 50, 100, 200], close_price_df)

        self.add_data_point_to_wave(index_timestamp, market_data_row)

    def market_data_event_handler(self, index_timestamp, market_data_row):
        self.update_market_data_related_stats(index_timestamp, market_data_row)

        open_positions = [x for x in self.portfolio.positions if x.status == 'open']
        print("# of active positions: {}, open positions: {}, pending positions {}".format(
            len(self.active_positions), len(open_positions), len(self.pending_positions_data_by_order)))
        self.check_sell_condition()

    def order_event_handler(self, order):
        if self.active_order_to_position_map[order.id] == None:
            # add position
            if self.simulation_mode_on:
                open_at = self.pending_positions_data_by_order[order.id]['attempt_open_at']
            else:
                open_at = order.executed_at

            new_position = self.portfolio.add_position(symbol=order.symbol, open_price=Decimal(round(order.executed_price, 2)), quantity=order.quantity, open_at=open_at)

            self.pending_positions_data_by_order[order.id]
            self.active_positions[new_position.id] = self.pending_positions_data_by_order[order.id]
            del self.pending_positions_data_by_order[order.id]
            del self.active_order_to_position_map[order.id]
        else:
            # close position
            position_id = self.active_order_to_position_map[order.id]

            if self.simulation_mode_on:
                closed_at = self.current_time_period()
            else:
                closed_at = order.executed_at

            self.portfolio.close_position(id=position_id, close_price=Decimal(round(order.executed_price, 2)), closed_at=closed_at)

            del self.active_order_to_position_map[order.id]
            del self.active_positions[position_id]

