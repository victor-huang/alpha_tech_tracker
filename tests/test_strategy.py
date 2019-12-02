from decimal import Decimal
import ipdb

from alpha_tech_tracker.strategy import SimpleStrategy

def test_create_an_instance_of_simple_strategy():
    new_strategy = SimpleStrategy()

    assert isinstance(new_strategy, SimpleStrategy)


def test_strategy_simulation():
    new_strategy_1 = SimpleStrategy()
    new_strategy_2 = SimpleStrategy()


    # test uptrede
    #  new_strategy_1.simulate(start='2019-05-30', end='2019-07-22')
    #  new_strategy_1.simulate(start='2019-05-30', end='2019-07-11')
    # strong up waves test expected profit 3.5k+
    #  new_strategy_1.simulate(start='2019-03-06', end='2019-03-27')
    # new_strategy_2.simulate(start='2018-12-24', end='2019-01-09') has a loss need to improve

    # two big up waves, gains at 7k
    #  new_strategy_1.simulate(start='2019-03-06', end='2019-05-03')
    new_strategy_1.simulate(start='2018-12-06', end='2018-12-24')
    # two big up waves. gains at 4k
    #  new_strategy_2.simulate(start='2019-05-29', end='2019-07-12')
    # very big uptrend
    # $1500 - $1900 => 40k buy and hold, this profit 15k
    # new_strategy_2.simulate(start='2018-05-15', end='2018-10-05')


    s1_pnl = new_strategy_1.portfolio.calculate_pnl()
    #  ipdb.set_trace()
    # {'pnl': Decimal('-6585.000000000036379788073'),
    #  assert s1_pnl['pnl'] > 1000
    # test for down trend

    #  new_strategy_2.simulate(start='2019-07-23', end='2019-08-05')
    #  new_strategy_2.simulate(start='2019-04-26', end='2019-06-03')
    #  new_strategy_2.simulate(start='2019-11-01', end='2019-11-22')
    # new_strategy_2.simulate(start='2018-02-08', end='2018-03-14') need to check back

    #  new_strategy_2.simulate(start='2018-09-24', end='2018-12-24'), downtrend make money???
    #  new_strategy_2.simulate(start='2018-12-20', end='2019-01-16')


    #  new_strategy_2.simulate(start='2018-02-07', end='2018-03-13')
    #  new_strategy_2.simulate(start='2018-02-07', end='2018-02-15')
    #  new_strategy_2.simulate(start='2019-01-01', end='2019-04-01')
    #  new_strategy_2.simulate(start='2019-03-28', end='2019-08-01')
    #  new_strategy_2.simulate(start='2018-01-01', end='2018-01-30')
    #  s2_pnl = new_strategy_2.portfolio.calculate_pnl()
    #  # 'pnl': Decimal('2204.000000000019099388737'),
    #  #  assert s1_pnl['pnl'] < -400
    #  ipdb.set_trace()


# up trend test
#  new_strategy_up_trend.simulate(start='2018-01-01', end='2018-04-02')
#  new_strategy_up_trend.simulate(start='2018-04-01', end='2018-10-08')
#  new_strategy_up_trend.simulate(start='2018-04-01', end='2018-10-08')
#  new_strategy_up_trend.simulate(start='2018-12-23', end='2019-04-28')
#  new_strategy_up_trend.simulate(start='2019-12-23', end='2019-04-28')

# down trend test
#  new_strategy_down_trend.simulate(start='2018-10-07', end='2018-12-24')


#Note:
# delya wave length help in down trend performance??



#  {'closed_at': Timestamp('2019-03-29 10:50:00-0400', tz='America/New_York'),
#  'open_at': Timestamp('2019-03-29 10:15:00-0400', tz='America/New_York'),
#  'pnl': Decimal('-1034.9999999999909050529823'),
#  'pnl_percent': Decimal('-0.0057869723231757948283644523'),
#  'result': 'loss',
#  'symbol': 'AMZN',
#  'total_close': Decimal('177815.0000000000090949470177'),
#  'total_open': Decimal('178850.0')},
