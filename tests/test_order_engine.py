from decimal import Decimal
import ipdb

from alpha_tech_tracker.order_engine import OrderEngine

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


