from decimal import Decimal
import datetime
from datetime import date
from dateutil import parser
import ipdb

from alpha_tech_tracker.portfolio import Portfolio

def test_create_an_instance_of_portfolio():
    new_portfolio = Portfolio()

    assert isinstance(new_portfolio, Portfolio)

def test_add_a_position():
    symbol = 'AMZN'
    open_price = 355
    quantity = 10
    new_portfolio = Portfolio()
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity, open_order_id='1')

    assert len(new_portfolio.positions) == 1
    assert new_portfolio.positions[0].symbol == symbol
    assert new_portfolio.positions[0].open_price == open_price
    assert new_portfolio.positions[0].quantity == quantity
    assert new_portfolio.positions[0].type == 'stock'
    assert new_portfolio.positions[0].status == 'open'

def test_close_a_position():
    symbol = 'AMZN'
    open_price = 355
    close_price = 300
    quantity = 10
    new_portfolio = Portfolio()
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity, open_order_id='1')

    position_id = new_portfolio.positions[0].id

    new_portfolio.close_position(id=position_id, close_price=close_price, close_order_id='1')

    assert new_portfolio.positions[0].status == 'closed'
    assert new_portfolio.positions[0].close_price == close_price

def test_close_a_invalid_position():
    symbol = 'AMZN'
    open_price = 355
    close_price = 300
    quantity = 10
    new_portfolio = Portfolio()
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity, open_order_id='1')

    position = new_portfolio.close_position(id="not_exist", close_price=close_price, close_order_id='1')

    assert position == None
    assert new_portfolio.positions[0].status == 'open'

def test_calculate_pnl():
    symbol = 'AMZN'
    open_price = 100
    close_price = 80
    quantity = 10
    new_portfolio = Portfolio()
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity, open_order_id='1')

    google_position = new_portfolio.add_position(symbol='GOOGL', open_price=100, quantity=1, open_order_id='2')

    position_id = new_portfolio.positions[0].id

    new_portfolio.close_position(id=position_id, close_price=close_price, close_order_id='1')
    new_portfolio.close_position(id=google_position.id, close_price=110, close_order_id='2')

    pnl_summary = new_portfolio.calculate_pnl()

    assert pnl_summary['positions_pnl'][0]['symbol'] == 'AMZN'
    assert pnl_summary['positions_pnl'][0]['result'] == 'loss'
    assert pnl_summary['positions_pnl'][0]['pnl'] == -200
    assert pnl_summary['positions_pnl'][0]['pnl_percent'] == Decimal('-0.2')

    assert pnl_summary['positions_pnl'][1]['symbol'] == 'GOOGL'
    assert pnl_summary['positions_pnl'][1]['result'] == 'profit'
    assert pnl_summary['positions_pnl'][1]['pnl'] == 10
    assert pnl_summary['positions_pnl'][1]['pnl_percent'] == Decimal('0.1')

    assert pnl_summary['total_open'] == 1100
    assert pnl_summary['total_close'] == 910
    assert pnl_summary['pnl'] == -190
    assert round(pnl_summary['pnl_percent'], 4) == Decimal('-0.1727')


def test_bucket_positions_pnl_by_time():
    symbol = 'AMZN'
    new_portfolio = Portfolio()
    starting_time = parser.parse('2023-03-06 12:12:12')
    new_portfolio.add_position(symbol=symbol, open_price=1, quantity=1, open_order_id='1', open_at=starting_time)
    new_portfolio.add_position(symbol=symbol, open_price=1, quantity=1, open_order_id='2', open_at=starting_time)

    # close position for the day in week
    for index, p in enumerate(new_portfolio.positions[0:2]):
        close_at = starting_time + datetime.timedelta(days=index)
        new_portfolio.close_position(id=p.id, closed_at=close_at, close_price=2, close_order_id=p.open_order_id)

    new_portfolio.add_position(symbol=symbol, open_price=5, quantity=1, open_order_id='3', open_at=starting_time)
    new_portfolio.add_position(symbol=symbol, open_price=5, quantity=1, open_order_id='4', open_at=starting_time)

    # close position for weeks in a month
    for index, p in enumerate(new_portfolio.positions[2:4]):
        close_at = starting_time + datetime.timedelta(weeks=index)
        new_portfolio.close_position(id=p.id, closed_at=close_at, close_price=10, close_order_id=p.open_order_id)

    new_portfolio.add_position(symbol=symbol, open_price=10, quantity=1, open_order_id='5', open_at=starting_time)
    new_portfolio.add_position(symbol=symbol, open_price=10, quantity=1, open_order_id='6', open_at=starting_time)

    # close position for monthes in a year
    for index, p in enumerate(new_portfolio.positions[4:6]):
        close_at = starting_time + datetime.timedelta(weeks=index * 4)
        new_portfolio.close_position(id=p.id, closed_at=close_at, close_price=20, close_order_id=p.open_order_id)


    result = new_portfolio.bucket_positions_pnl_by_time()

    assert result['daily']['2023-03-13'] == 5
    assert result['weekly']['2023-03-12'] == 17
    assert result['weekly']['2023-03-19'] == 5
    assert result['monthly']['2023-03-31'] == 22
    assert result['monthly']['2023-04-30'] == 10
