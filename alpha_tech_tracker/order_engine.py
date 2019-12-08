from datetime import datetime
from decimal import Decimal
import uuid

class Order(object):
    def __init__(self, *, asset_type='stock', symbol, exchange, side, price, quantity, type, executed_price=None, executed_at=datetime.now(), status='open', strike_price=None):
        self.id = uuid.uuid1()
        self.asset_type = asset_type # stock, option
        self.type = type # sell/buy
        self.status = status
        self.symbol = symbol
        self.side = side
        self.exchange = exchange
        self.price = price
        self.strike_price = strike_price
        self.quantity = quantity
        self.executed_price = executed_price
        self.executed_at = executed_at
        self.fee = 0
        self.cost = 0


class OrderEngine(object):
    def __init__(self, *, engine='mock'):
        if engine == 'mock':
            self.engine = MockOrderEngine()

    def place(self, *args, **keyword_args):
        return self.engine.place(*args, **keyword_args)

    def cancel(self, order_id):
        return self.engine.cancel(order_id)

    def execute_orders(self):
        if isinstance(self.engine, MockOrderEngine):
            return self.engine.execute_orders()

    def find_order(self, order_id):
        return self.engine.find_order(order_id)


class MockOrderEngine():
    def __init__(self):
        self.orders = []

    def find_order(self, order_id):
        return next((x for x in self.orders if x.id == order_id), None)

    def place(self, *, asset_type='stock', symbol, exchange='mockEx', side, price, quantity, type, strike_price=None):
        if asset_type == 'option' and strike_price == None:
            raise ValueError('strike_price needs to be set for Option')

        new_order = Order(asset_type=asset_type, side=side, symbol=symbol, exchange=exchange, price=price, quantity=quantity, type=type, strike_price=strike_price)

        self.orders.append(new_order)

        return new_order

    def cancel(self, id):
        order = next((x for x in self.orders if x.id == id), None)

        if order:
            self.orders.remove(order)

        return order != None

    def execute_orders(self):
        open_orders = [x for x in self.orders if x.status == 'open']

        for order in open_orders:
            if order.asset_type == 'option':
                order.cost = order.price * 100 + order.fee
            else:
                order.cost = order.price + order.fee

            order.status = 'executed'
            order.executed_price = order.price
            order.executed_at = datetime.now()

        return open_orders

