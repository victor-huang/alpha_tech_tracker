from datetime import datetime
from decimal import Decimal
import uuid

class Order(object):
    def __init__(self, *, asset_type='stock', symbol, exchange, side, price, quantity, type, executed_price=None, executed_at=datetime.now(), status='open', strike_price=None, osi_key=None):
        self.id = uuid.uuid1()
        self.asset_type = asset_type # stock, option
        self.type = type # sell/buy
        self.status = status
        self.symbol = symbol
        self.side = side
        self.exchange = exchange
        self.price = price
        self.strike_price = strike_price
        self.osi_key = osi_key
        self.quantity = quantity
        self.executed_price = executed_price
        self.executed_at = executed_at
        self.fee = 0
        self.cost = 0

    def option_type(self):
        # e.g. osa_key = TSLA--231013C00240000
        if self.asset_type == 'option':
            symbol, reminder = self.osi_key.split('--')
            if 'C' in reminder:
                return 'call'
            else:
                return 'put'

class OrderEngine(object):
    def __init__(self, *, engine_name='mock', client=None):
        self.engine_name = engine_name
        if self.engine_name == 'mock':
            self.engine = MockOrderEngine()
        elif self.engine_name == 'etrade':
            self.engine = ETradeOrderEngine(client=client)

    def place(self, *args, **keyword_args):
        return self.engine.place(*args, **keyword_args)

    def cancel(self, order_id):
        return self.engine.cancel(order_id)

    def execute_orders(self):
        if isinstance(self.engine, MockOrderEngine):
            return self.engine.execute_orders()

    def find_order(self, order_id):
        return self.engine.find_order(order_id)

    def close_all_open_orders(self):
        return self.engine.close_all_open_orders()

    def sync_orders(self):
        return self.engine.sync_orders()



class MockOrderEngine():
    def __init__(self):
        self.orders = []

    def find_order(self, order_id):
        return next((x for x in self.orders if x.id == order_id), None)

    def place(self, *, asset_type='stock', symbol, exchange='mockEx', side, price, quantity, type, strike_price=None, osi_key=None, option_key=None):
        if asset_type == 'option' and strike_price == None:
            raise ValueError('strike_price needs to be set for Option')

        new_order = Order(asset_type=asset_type, side=side, symbol=symbol, exchange=exchange, price=price, quantity=quantity, type=type, strike_price=strike_price, osi_key=osi_key)

        self.orders.append(new_order)

        return new_order

    def cancel(self, id):
        order = next((x for x in self.orders if x.id == id), None)

        if order:
            order.status = 'canceled'

        return order != None

    def close_all_open_orders(self):
        for order in self.orders:
            if order.status == 'open':
                self.cancel(order.id)

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


class ETradeOrderEngine(MockOrderEngine):
    def __init__(self, client):
        self.orders = []
        self._client = client


    def place(self, *, asset_type='stock', symbol, exchange='mockEx', side, price, quantity, type, strike_price=None, osi_key=None, option_key=None):
        if asset_type == 'option' and strike_price == None:
            raise ValueError('strike_price needs to be set for Option')

        new_order = Order(asset_type=asset_type, side=side, symbol=symbol, exchange=exchange, price=price, quantity=quantity, type=type, strike_price=strike_price, osi_key=osi_key)


        if asset_type == 'option' and side == 'buy':
            order_action = 'BUY_OPEN'
            price_type = type.upper()

        if asset_type == 'option' and side == 'sell':
            order_action = 'SELL_CLOSE'
            price_type = type.upper()


        if asset_type == 'option' and order_action:
            order = self._client.place_option_order(
                symbol=symbol,
                option_key=option_key,
                price=price,
                order_action=order_action,
                price_type=price_type,
            )
            etrade_order_id = order['PlaceOrderResponse']['OrderIds'][0]['orderId']
            new_order.id = etrade_order_id
        else:
            raise ValueError(f"Asset Type: {asset_type} not supported.")

        self.orders.append(new_order)

        return new_order

    def get_smart_limit_order():
        pass


    def cancel(self, id):
        order = next((x for x in self.orders if x.id == id), None)

        if order:
            order.status = 'canceled'

        resp = self._client.cancel_order(order.id)
        return order != None

    def sync_orders(self):
        # check order satus and update them
        for order in self.orders:
            status_info = self._client.order_status(order.id)
            order_status = status_info['OrdersResponse']['Order'][0]['OrderDetail'][0]['status'].lower()
            order.status = order_status

            # get executed_at, executed_price, commission_fee, status
            print(f"Synced order: {order.id}, {status_info}")
