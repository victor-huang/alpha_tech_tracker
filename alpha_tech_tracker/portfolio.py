from datetime import datetime
from decimal import Decimal
import uuid

import ipdb

class Position(object):
    def __init__(self, *, open_price, symbol, quantity, type='stock', open_at=datetime.now(), close_price=None):
        self.status = 'open'
        self.id = uuid.uuid1()
        self.symbol = symbol
        self.quantity = quantity
        self.type = type
        self.open_price = Decimal(str(open_price))
        self.open_at = datetime.now()

        if close_price:
            self.close_price = Decimal(str(close_price))

        self.closed_at = None


class Portfolio(object):
    def __init__(self):
        self.positions = []

    def add_position(self, *, symbol, open_price, quantity, type='stock', open_at=datetime.now()):
        new_position = Position(symbol=symbol, open_price=open_price, quantity=quantity, type=type, open_at=open_at)
        self.positions.append(new_position)
        return new_position

    def close_position(self, *, id, close_price, closed_at=datetime.now()):
        found_position = next((x for x in self.positions if x.id == id), None)
        if found_position:
            found_position.status = 'closed'
            found_position.close_price = close_price
            found_position.closed_at = closed_at

        return found_position

    def calculate_pnl(self):
        summary_pnl = {
            'positions_pnl': [],
            'result': None,
            'pnl_percent': None
        }

        total_open = Decimal(0)
        total_close = Decimal(0)

        for position in self.positions:

            position_pnl = {
                'symbol': position.symbol,
                'total_open': position.quantity * position.open_price,
                'total_close': position.quantity * position.close_price
            }

            total_open += position_pnl['total_open']
            total_close += position_pnl['total_close']

            diff = position_pnl['total_close'] - position_pnl['total_open']

            if diff > 0:
                position_pnl['result'] = 'profit'
            elif diff < 0:
                position_pnl['result'] = 'loss'
            else:
                position_pnl['result'] = 'even'

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
        summary_pnl['pnl_percent'] = total_close / total_open - 1

        return summary_pnl
