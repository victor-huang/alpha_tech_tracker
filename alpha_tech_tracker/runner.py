#  from __future__ import absolute_import

import threading
from time import sleep
import os
import sys
#  import signal

from daemonize import Daemonize
import ipdb

from alpha_tech_tracker.alpaca_engine import DataAggregator
from alpha_tech_tracker.strategy import SimpleStrategy
from alpha_tech_tracker.nvda_strategy import NVDAStrategy


pid = "./runner.pid"

#  class Logger(object):
    #  def __init__(self, file_name='runner.log'):
        #  self.terminal = sys.stdout
        #  self.log = open(file_name, "a")

    #  def write(self, message):
        #  self.terminal.write(message)
        #  self.log.write(message)

    #  def warning(self, message):
        #  self.terminal.write(message)
        #  self.log.write(message)

    #  def flush(self):
        #  #this flush method is needed for python 3 compatibility.
        #  #this handles the flush command by doing nothing.
        #  #you might want to specify some extra behavior here.
        #  pass

#  stdout_file = Logger()
#  stderr_file = Logger()

#  sys.stdout = stdout_file
#  sys.stderror = stderr_file

#  sys.stdout = stdout_file
#  keep_fds = [stdout_file, stderr_file]



def run_strategy():
    new_strategy_1 = SimpleStrategy(symbol='AMZN')
    new_strategy_2 = SimpleStrategy(symbol='NFLX')
    sim_thread_1 = threading.Thread(target=new_strategy_1.simulate, kwargs={ 'start': '2020-01-01', 'end': '2020-01-20', 'use_saved_data': False, 'stream_data': False })
    sim_thread_2 = threading.Thread(target=new_strategy_2.simulate, kwargs={'start': '2020-01-01', 'end': '2020-01-20', 'use_saved_data': False, 'stream_data': False })
    sim_thread_1.start()
    sim_thread_2.start()

    #  new_strategy_1 = SimpleStrategy(symbol='AMZN')
    #  new_strategy_1.simulate(start='2020-01-01', end='2020-01-10', use_saved_data=False, stream_data=True)
    #  new_strategy_2 = SimpleStrategy(symbol='NFLX')
    #  new_strategy_2.simulate(start='2020-01-01', end='2020-01-10', use_saved_data=False, stream_data=False)
    #  nvda_strategy = NVDAStrategy(symbol='NVDA')
    #  nvda_strategy.simulate(start='2020-01-01', end='2020-01-10', use_saved_data=False, stream_data=False)

    #  nvda_strategy.simulate(start='2018-01-01', end='2018-06-01', use_saved_data=False, stream_data=False)
    # loss  'pnl': Decimal('-1086.0000000000027853275242'),

    #  nvda_strategy.simulate(start='2018-01-01', end='2018-03-01', use_saved_data=False, stream_data=False)
    #  'pnl': Decimal('-242.99999999999926103555481'),
    #  nvda_strategy.simulate(start='2018-06-01', end='2018-11-01', use_saved_data=False, stream_data=False)
    # 'pnl': Decimal('-614.99999999999914734871710'),
    
    #  nvda_strategy.simulate(start='2018-12-01', end='2019-01-01', use_saved_data=False, stream_data=False)
    #  'pnl': Decimal('171.99999999999988631316228'),
    

    #  nvda_strategy.simulate(start='2017-01-01', end='2017-04-01', use_saved_data=False, stream_data=False)
    #  'pnl': Decimal('-223.99999999999948840923026'),
    #  nvda_strategy.simulate(start='2017-04-01', end='2017-08-01', use_saved_data=False, stream_data=False)
     #  'pnl': Decimal('-531.0000000000016484591469'),

    #  nvda_strategy.simulate(start='2017-08-01', end='2017-12-30', use_saved_data=False, stream_data=False)
     #  'pnl': Decimal('-1001.0000000000019326762412'),

    #  nvda_strategy.simulate(start='2019-12-01', end='2020-01-10', use_saved_data=False, stream_data=False)
    #  nvda_strategy.simulate(start='2019-10-11', end='2019-11-22', use_saved_data=False, stream_data=False)

    sim_thread_2.join()
    sim_thread_1.join()

def start():
    #  while True:
        #  sleep(5)
    #  daemon = Daemonize(app="strategy_runner", pid=pid, action=run_strategy, foreground=False, verbose=True, logger=stdout_file)
    #  #  ipdb.set_trace()
    #  daemon.start()

    DataAggregator.start_streaming_market_data(symbols=['AMZN', 'NFLX'])
    run_strategy()
    DataAggregator.stop_streaming_market_data()

def stop():
    #  daemon = Daemonize(app="strategy_runner", pid=pid, action=main, keep_fds=keep_fds)
    #  daemon.exit()
    pid_number = open(pid,'r').read()
    #  ipdb.set_trace()
    os.kill(int(pid_number), 15)

def main():
    action_map = {
        "start": start,
        #  "status": status,
        "stop": stop
    }

    action = sys.argv[1]
    daemon_action = action_map[action]

    if daemon_action:
        daemon_action()
    else:
        print('Unknown daemon action.')

main()

