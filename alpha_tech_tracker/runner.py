import os
import sys
import threading
from time import sleep

from daemonize import Daemonize

from alpha_tech_tracker.alpaca_py_engine import DataAggregator
from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
from alpha_tech_tracker.tsla_strategy import SimpleStrategy as TslaBuyStrategy

pid = "./runner.pid"


def run_tsla_buy_run_strategy():
    client = EtradeAPIClient(selected_account_id="")
    client.authorize_session()

    is_streaming = True
    new_strategy_1 = TslaBuyStrategy(
        symbol="TSLA", skip_place_historical_trades=True, trade_api_client=client
    )
    sim_thread_1 = threading.Thread(
        target=new_strategy_1.simulate,
        kwargs={
            "start": "2023-10-13",
            "end": "2023-10-30",
            "use_saved_data": False,
            "stream_data": is_streaming,
        },
    )

    def keep_session_alive():
        while True:
            try:
                quote = client.get_option_quote(
                    "TSLA", "2023-11-24 s190", option_type="CALL"
                )
                print(f"Keep session alive checking for quote: {quote}")
                sleep(60)
            except Exception as e:
                print(f"Error: {e}")

    keep_oauth_session_alive_thread = threading.Thread(target=keep_session_alive)

    keep_oauth_session_alive_thread.start()
    sim_thread_1.start()
    sim_thread_1.join()
    keep_oauth_session_alive_thread.join()


def start():
    #  while True:
    #  sleep(5)
    #  daemon = Daemonize(app="strategy_runner", pid=pid, action=run_tsla_buy_run_strategy, foreground=False, verbose=True, logger=stdout_file)
    #  #  ipdb.set_trace()
    #  daemon.start()

    DataAggregator.start_streaming_market_data(symbols=["TSLA"])
    run_tsla_buy_run_strategy()
    DataAggregator.stop_streaming_market_data()


def stop():
    #  daemon = Daemonize(app="strategy_runner", pid=pid, action=main, keep_fds=keep_fds)
    #  daemon.exit()
    pid_number = open(pid, "r").read()
    #  ipdb.set_trace()
    os.kill(int(pid_number), 15)


def main():
    action_map = {
        "start": start,
        "stop": stop,
    }

    action = sys.argv[1]
    daemon_action = action_map[action]

    if daemon_action:
        daemon_action()
    else:
        print("Unknown daemon action.")


main()
