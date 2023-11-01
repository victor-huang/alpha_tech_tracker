from decimal import Decimal
import ipdb

from alpha_tech_tracker.order_engine import OrderEngine
from alpha_tech_tracker.order_engine import Order
from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient

def test_create_an_instance_of_order_engine():
    new_order_engine = OrderEngine()

    assert isinstance(new_order_engine, OrderEngine)

def test_place_a_trade_in_mock_engine():
    symbol = 'AMZN'
    order_type = 'market'
    side = 'buy'
    price = Decimal('12')
    quantity = 10

    new_order_engine = OrderEngine()
    new_order = new_order_engine.place(symbol=symbol, side=side, quantity=quantity, price=price, type=order_type)

    assert new_order.id != None
    assert new_order.status == 'open'
    assert new_order.symbol == symbol
    assert new_order.type == order_type
    assert new_order.side == side
    assert new_order.price == price
    assert new_order.quantity == quantity
    assert new_order.exchange == 'mockEx'

    new_order_engine.execute_orders()

    assert new_order.status == 'executed'
    assert new_order.executed_price == price
    assert new_order.executed_at != None

def test_cancel_a_place_order_in_mock_engine():
    symbol = 'AMZN'
    order_type = 'market'
    side = 'buy'
    price = Decimal('12')
    quantity = 10

    new_order_engine = OrderEngine()
    new_order = new_order_engine.place(symbol=symbol, side=side, quantity=quantity, price=price, type=order_type)

    assert new_order_engine.cancel(new_order.id) == True
    assert len(new_order_engine.engine.orders) == 0


class TestOrder():
    def test_option_type_return_correct_result(self):
        call_order = Order(asset_type='option', symbol='TSLA', osi_key='TSLA--231013C00240000', exchange='ABC', side='buy', price=1, quantity=1, type='sell')
        put_order = Order(asset_type='option', symbol='TSLA', osi_key='TSLA--231013P00240000', exchange='ABC', side='buy', price=1, quantity=1, type='sell')
        call_option_type = call_order.option_type()
        put_option_type = put_order.option_type()

        assert call_option_type == 'call'
        assert put_option_type == 'put'


# these are integration test that requires interaction with Etrade
class TestETradeOrderEngine():
    def test_should_be_able_to_place_a_trade(self):
        client = EtradeAPIClient(selected_account_id="")
        client.authorize_session()

        engine = OrderEngine(engine_name='etrade', client=client)
        symbol = 'TSLA'
        order_type = 'limit'
        side = 'buy'
        price = 1
        quantity = 10
        strike_price = 240
        option_key = '2023-10-20 s240'

        new_order = engine.place(symbol=symbol, side=side, asset_type='option', quantity=quantity, price=price, type=order_type, strike_price=strike_price, option_key=option_key)


        assert new_order.id is not None


    def test_sync_orders_should_update_order_status(self):
        client = EtradeAPIClient(selected_account_id="")
        client.authorize_session()

        engine = OrderEngine(engine_name='etrade', client=client)
        symbol = 'TSLA'
        order_type = 'smart_market'
        side = 'sell'
        quantity = 10
        strike_price = 240
        option_key = '2023-10-20 s230'
        price = None

        #  quote = client.get_option_quote(symbol, option_key, option_type="CALL")
        #  price_info = client.get_price_from_quote(quote)
        #  print(price_info)
        #  price = price_info['s-mid']

        new_order = engine.place(symbol=symbol, side=side, asset_type='option', quantity=quantity, price=price, type=order_type, strike_price=strike_price, option_key=option_key)
        engine.cancel(new_order.id)
        engine.sync_orders()

