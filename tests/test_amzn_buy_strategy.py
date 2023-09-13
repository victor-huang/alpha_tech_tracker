from decimal import Decimal
import ipdb

from alpha_tech_tracker.strategy import SimpleStrategy

def test_create_an_instance_of_simple_strategy():
    new_strategy = SimpleStrategy(symbol='AMZN')

    assert isinstance(new_strategy, SimpleStrategy)


def test_strategy_simulation():
    new_strategy_1 = SimpleStrategy(symbol='AMZN')
    new_strategy_2 = SimpleStrategy(symbol='AMZN')

    new_strategy_1.simulate(start='2019-01-01', end='2019-01-15', use_saved_data=True, stream_data=False)

    return

    # test uptrede
    #  new_strategy_1.simulate(start='2019-05-30', end='2019-07-22')
    #  new_strategy_1.simulate(start='2019-05-30', end='2019-07-11')
    # strong up waves test expected profit 3.5k+
    #  new_strategy_1.simulate(start='2019-03-06', end='2019-03-27')
    # new_strategy_2.simulate(start='2018-12-24', end='2019-01-09') has a loss need to improve

    # two big up waves, gains at 7k
    #  new_strategy_1.simulate(start='2019-03-06', end='2019-05-03')
    # two big up waves. gains at 4k
    #  new_strategy_2.simulate(start='2019-05-29', end='2019-07-12')
    # very big uptrend
    # $1500 - $1900 => 40k buy and hold, this profit 15k
    # new_strategy_2.simulate(start='2018-05-15', end='2018-10-05')


    new_strategy_0 = SimpleStrategy(symbol='AMZN')
    new_strategy_0.simulate(start='2019-06-10', end='2019-07-11')
    print("**--**--up--(start='2019-06-10', end='2019-07-11'")
    # 'pnl': Decimal('2636.999999999966348696031'),
    #v2 'pnl': Decimal('3047.000000000002728484105'),

    new_strategy_00 = SimpleStrategy(symbol='AMZN')
    new_strategy_00.simulate(start='2019-03-13', end='2019-05-06')
    print("**--**--up--(start='2019-03-13', end='2019-05-06')")
    # 'pnl': Decimal('2636.999999999966348696031'),
    #v2  'pnl': Decimal('3839.999999999940882844383'),

    new_strategy_1 = SimpleStrategy(symbol='AMZN')
    new_strategy_1.simulate(start='2018-04-02', end='2018-09-08')
    print("**--**--up--(start='2018-04-02', end='2018-09-08')")
    # 'pnl': Decimal('9672.00000000000272848409'),
    #v2 'pnl': Decimal('3754.99999999992724042384'),
    
    new_strategy_2 = SimpleStrategy(symbol='AMZN')
    new_strategy_2.simulate(start='2018-01-03', end='2018-03-24')
    print("**--**--up--start='2018-01-03', end='2018-03-24'")
    # 'pnl': Decimal('1881.000000000062755134423'),
    #v2 'pnl': Decimal('4218.999999999937244865579'),


    new_strategy_3 = SimpleStrategy(symbol='AMZN')
    new_strategy_3.simulate(start='2018-03-12', end='2018-04-07')
    print("**--**--down--(start='2018-03-12', end='2018-04-07')")
    # 'pnl': Decimal('-525.999999999999090505298'),
    #v2 'pnl': Decimal('-920.000000000004547473509'),

    new_strategy_4 = SimpleStrategy(symbol='AMZN')
    new_strategy_4.simulate(start='2018-09-29', end='2018-11-24')
    print("**--**--down--(start='2018-09-24', end='2018-11-24')")
    # 'pnl': Decimal('5449.000000000000909494701'),
    #v2 'pnl': Decimal('4490.999999999985448084771'),

    new_strategy_4 = SimpleStrategy(symbol='AMZN')
    new_strategy_4.simulate(start='2019-07-15', end='2019-09-30')
    print("**--**--down--(start='2019-07-15', end='2019-10-06')")
    # 'pnl': Decimal('-2499.000000000000909494701'),
    #v2 'pnl': Decimal('767.000000000030013325161'),

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
