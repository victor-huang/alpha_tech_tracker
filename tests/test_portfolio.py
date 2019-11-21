from decimal import Decimal
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
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity)

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
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity)

    position_id = new_portfolio.positions[0].id

    new_portfolio.close_position(id=position_id, close_price=close_price)

    assert new_portfolio.positions[0].status == 'closed'
    assert new_portfolio.positions[0].close_price == close_price

def test_close_a_invalid_position():
    symbol = 'AMZN'
    open_price = 355
    close_price = 300
    quantity = 10
    new_portfolio = Portfolio()
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity)

    position = new_portfolio.close_position(id="not_exist", close_price=close_price)

    assert position == None
    assert new_portfolio.positions[0].status == 'open'

def test_calculate_pnl():
    symbol = 'AMZN'
    open_price = 100
    close_price = 80
    quantity = 10
    new_portfolio = Portfolio()
    new_portfolio.add_position(symbol=symbol, open_price=open_price, quantity=quantity)

    google_position = new_portfolio.add_position(symbol='GOOGL', open_price=100, quantity=1)

    position_id = new_portfolio.positions[0].id

    new_portfolio.close_position(id=position_id, close_price=close_price)
    new_portfolio.close_position(id=google_position.id, close_price=110)

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
