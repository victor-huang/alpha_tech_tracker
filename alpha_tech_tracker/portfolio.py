from datetime import datetime
from decimal import Decimal
import uuid
import pandas as pd

import ipdb

class Position(object):
    def __init__(self, *, open_price, symbol, quantity, type='stock', open_at=datetime.now(), close_price=None, close_at=None, open_order_id=None, close_order_id=None, osi_key=None, strike_price=None):
        self.status = 'open'
        self.id = uuid.uuid1()
        self.symbol = symbol
        self.quantity = quantity
        self.type = type
        self.open_price = Decimal(str(open_price))
        self.open_at = open_at
        self.open_order_id = open_order_id
        self.close_order_id = None
        self.osi_key = osi_key
        self.strike_price = strike_price

        if close_price:
            self.close_price = Decimal(str(close_price))

        self.closed_at = None

    def value(self):
        if self.closed_at:
            value = self.close_price * self.quantity
        else:
            value = self.open_price * self.quantity

        if type == 'option':
            value = value * 100

        return value


class Portfolio(object):
    def __init__(self):
        self.positions = []

    def find_position(self, position_id):
        return next((x for x in self.positions if x.id == position_id), None)

    def add_position(self, *, symbol, open_price, quantity, open_order_id, type='stock', open_at=datetime.now(), osi_key=None, strike_price=None):
        if open_order_id == None:
            raise ValueError('open_order_id can not be None')

        new_position = Position(symbol=symbol, open_price=open_price, quantity=quantity, type=type, open_at=open_at, open_order_id=open_order_id, osi_key=osi_key, strike_price=strike_price)
        self.positions.append(new_position)
        return new_position

    def close_position(self, *, id, close_price, close_order_id, closed_at=datetime.now()):
        found_position = self.find_position(id)

        if found_position:
            found_position.status = 'closed'
            found_position.close_price = close_price
            found_position.closed_at = closed_at
            found_position.close_order_id = close_order_id

        return found_position

    def bucket_positions_pnl_by_time(self):
        df = pd.DataFrame([vars(p) for p in self.positions])
        df.set_index('closed_at', inplace=True)

        def calculate_pl(row):
            if row['type'] == 'stock':
                return (row['close_price'] - row['open_price']) * row['quantity']
            else:  # Assuming other type is 'option' for this example
                return 100 * (row['close_price'] - row['open_price']) * row['quantity']

        df['P&L'] = df.apply(calculate_pl, axis=1)

        daily_pl = df.groupby(pd.Grouper(freq='D'))['P&L'].sum()
        weekly_pl = df.groupby(pd.Grouper(freq='W-SUN'))['P&L'].sum()
        monthly_pl = df.groupby(pd.Grouper(freq='M'))['P&L'].sum()

        return {
            'daily': daily_pl,
            'weekly': weekly_pl,
            'monthly': monthly_pl,
        }


    def calculate_pnl(self):
        summary_pnl = {
            'positions_pnl': [],
            'result': None,
            'pnl_percent': None,
            'number_of_profit_positions': 0,
            'number_of_loss_positions': 0,
            'max_loss': 0,
            'max_profit': 0
        }

        if not self.positions:
            return summary_pnl

        total_open = Decimal(0)
        total_close = Decimal(0)

        for position in self.positions:

            position_total_open = position.quantity * position.open_price
            position_total_close = position.quantity * position.close_price

            if position.type == 'option':
                position_total_open *= 100
                position_total_close *= 100

            position_pnl = {
                'open_at': position.open_at,
                'closed_at': position.closed_at,
                'symbol': position.symbol,
                'total_open': position_total_open,
                'total_close': position_total_close
            }

            total_open += position_pnl['total_open']
            total_close += position_pnl['total_close']

            diff = position_pnl['total_close'] - position_pnl['total_open']

            if diff > 0:
                position_pnl['result'] = 'profit'
                summary_pnl['number_of_profit_positions'] += 1

                if diff > summary_pnl['max_profit']:
                    summary_pnl['max_profit'] = diff

            elif diff < 0:
                position_pnl['result'] = 'loss'
                summary_pnl['number_of_loss_positions'] += 1

                if diff < summary_pnl['max_loss']:
                    summary_pnl['max_loss'] = diff
            else:
                position_pnl['result'] = 'even'

            if position.osi_key:
                position_pnl['osi_key'] = position.osi_key

            position_pnl['pnl'] = diff
            position_pnl['pnl_percent'] = position_pnl['total_close'] / position_pnl['total_open'] - 1
            summary_pnl['positions_pnl'].append(position_pnl)

        # total pnl summary
        total_diff = total_close - total_open

        if total_diff > 0:
            summary_pnl['result'] = 'profit'
        elif total_diff < 0:
            summary_pnl['result'] = 'loss'
        else:
            summary_pnl['result'] = 'even'

        summary_pnl['total_open'] = total_open
        summary_pnl['total_close'] = total_close
        summary_pnl['pnl'] = total_diff
        avg_total_open = total_open / len(self.positions)
        summary_pnl['pnl_percent'] = total_diff / avg_total_open

        return summary_pnl
