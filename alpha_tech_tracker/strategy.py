from datetime import time
from datetime import datetime
from decimal import Decimal
#  from functools import reduce
import pandas as pd
from pandas import Series
import pprint as pp
#  import numpy as np

from alpha_tech_tracker.order_engine import OrderEngine
from alpha_tech_tracker.portfolio import Portfolio
from alpha_tech_tracker.signal import Signal
import alpha_tech_tracker.technical_analysis as ta
import alpha_tech_tracker.alpaca_engine as alpaca

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
        #  moving_avg_trends = ta.detect_moving_average_trend(close_price_df)

    # start='2019-11-13', end='2019-11-16' interestnig
    def simulate(self, *, start='2019-03-11', end='2019-03-18'):
        df = alpaca.get_historical_ochl_data(self.symbol, start_date=start, end_date=end)
        #  df.to_json('./amzn_5min_2019-11-13_2019-11-23')

        preload_data_period = 200
        #  future_market_data_df = df[preload_data_period + 1:preload_data_period + 101]
        future_market_data_df = df[preload_data_period + 1:]

        close_price_df = df[:preload_data_period][['close']].copy()
        moving_avgs_df = ta.moving_average_summary([20, 50, 100, 200], close_price_df)
        self.market_data_df = df[:preload_data_period].copy()
        self.moving_avgs_df = moving_avgs_df

        for index_timestamp, market_data_row in future_market_data_df.iterrows():
            #  if self.is_after_hours(index_timestamp):
                #  continue
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

            #  ipdb.set_trace()

        for p in self.portfolio.positions:
            if p.status == 'open':
                p.close_price = Decimal(future_market_data_df[-1:]['close'][0])
                p.status == 'closed'

        pp.pprint(self.portfolio.calculate_pnl())

    def generate_signals(self, index_timestamp, current_data_row):
        price_data = self.df_to_price_data_array(self.get_latest_periods_market_data(index_timestamp, current_data_row, n=2))
        reversal_fns = { 
            'long_tail_reversal_combo': ta.long_tail_reversal_combo
        }

        signals = []

        for name, detection_fn in reversal_fns.items():
            if detection_fn(price_data, trend='up'):
                # name, category, symbol=None, signaled_at=datetime.now()):
                signal_name = name + '-' + 'up_trend'
                signals.append(Signal(name=signal_name, category='ta', trend='up', symbol=self.symbol, signaled_at=index_timestamp))
            if detection_fn(price_data, trend='down'):
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
    def upside_potential(self, current_price):
        last_n_price_data_df = self.market_data_df[-20:]
        return last_n_price_data_df['close'].max() - current_price

    def downside_risk(self, current_price):
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

    def risk_reward_ratio(self, current_price):
        return self.upside_potential(current_price) / self.downside_risk(current_price)

    def check_buy_condition(self):
        current_price = self.market_data_df[-1:]['close'][0]

        print("** up: {}, down {}, ratio {}".format(self.upside_potential(current_price),
            self.downside_risk(current_price), self.risk_reward_ratio(current_price)))

        #  open_positions = [x for x in self.portfolio.positions if x.status == 'open']

        if self.risk_reward_ratio(current_price) > 1.5 and not self.active_positions and not self.is_close_to_after_hours():
            # open a new position
            new_order = self.order_engine.place(symbol=self.symbol, side='buy',
                    price=current_price, quantity=100, type='limit')
            #  new_position = self.portfolio.add_position(symbol=self.symbol, open_price=current_price,
                    #  quantity=100)
            self.pending_positions_data_by_order[new_order.id] = {
                'target_price': self.upside_potential(current_price) + current_price,
                'cut_loss_price': current_price - self.downside_risk(current_price)
            }

            self.active_order_to_position_map[new_order.id] = None
            print('Buy 100 stock at price {}, target price: {}, cut loss at: {}'.format(current_price, self.upside_potential(current_price) + current_price, current_price - self.downside_risk(current_price)))


    def is_right_before_market_close(self):
        return self.market_data_df[-1:].index[0].strftime('%H:%M') == '15:55'

    def current_time_period(self):
        return self.market_data_df[-1:].index[0]

    def is_close_to_after_hours(self, current_timestamp=None):
        if not current_timestamp:
            current_time = self.current_time_period().time()
        else:
            current_time = current_timestamp.time()

        return  current_time > time(15, 55) or current_time < time(9, 35)

    def is_after_hours(self, current_timestamp=None):
        if not current_timestamp:
            current_time = self.current_time_period()
        else:
            current_time = current_timestamp.time()

        return  current_time > time(16, 0) or current_time < time(9, 30)

    def check_sell_condition(self):
        current_price = self.market_data_df[-1:]['close'][0]
        current_time_period =  self.market_data_df[-1:]

        for position_id, targets in self.active_positions.items():
            if current_price >= targets['target_price'] or current_price <= targets['cut_loss_price'] or self.is_right_before_market_close():
                # close the position
                print('Close the position {} at price {}'.format(position_id, current_price))

                if position_id not in self.active_order_to_position_map.values():
                    new_order = self.order_engine.place(symbol=self.symbol, side='sell',
                            price=current_price, quantity=100, type='limit')

                    self.active_order_to_position_map[new_order.id] = position_id


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

    def market_data_event_handler(self, index_timestamp, market_data_row):
        self.market_data_df.loc[index_timestamp] = market_data_row
        close_price_df = self.market_data_df[['close']].copy()
        self.moving_avgs_df = ta.moving_average_summary([20, 50, 100, 200], close_price_df)

        open_positions = [x for x in self.portfolio.positions if x.status == 'open']
        print("# of active positions: {}, open positions: {}, pending positions {}".format(
            len(self.active_positions), len(open_positions), len(self.pending_positions_data_by_order)))
        self.check_sell_condition()

    def order_event_handler(self, order):
        if self.active_order_to_position_map[order.id] == None:
            # add position
            new_position = self.portfolio.add_position(symbol=order.symbol, open_price=Decimal(round(order.executed_price, 2)), quantity=order.quantity, open_at=order.executed_at)

            self.pending_positions_data_by_order[order.id]
            self.active_positions[new_position.id] = self.pending_positions_data_by_order[order.id]
            del self.pending_positions_data_by_order[order.id]
            del self.active_order_to_position_map[order.id]
        else:
            # close position
            position_id = self.active_order_to_position_map[order.id]
            self.portfolio.close_position(id=position_id, close_price=Decimal(round(order.executed_price, 2)), closed_at=order.executed_at)

            del self.active_order_to_position_map[order.id]
            del self.active_positions[position_id]

