#  from __future__ import absolute_import

from time import sleep
import os
import sys
#  import signal

from daemonize import Daemonize
import ipdb

from alpha_tech_tracker.strategy import SimpleStrategy


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
    new_strategy_1.simulate(start='2019-12-16', end='2019-12-20', use_saved_data=False, stream_data=False)

def start():
    #  while True:
        #  sleep(5)
    #  daemon = Daemonize(app="strategy_runner", pid=pid, action=run_strategy, foreground=False, verbose=True, logger=stdout_file)
    #  #  ipdb.set_trace()
    #  daemon.start()
    run_strategy()

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

