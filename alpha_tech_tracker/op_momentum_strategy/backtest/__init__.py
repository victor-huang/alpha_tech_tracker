"""Support modules for the selector backtest.

Split out of the former single-file op_momentum_selector_backtest.py:

  constants.py  module-level constants (capital, regime-adaptive configs)
  weights.py    rank-weight parsing / normalization
  args.py       argparse definition (`_parse_args`)
  reporting.py  all terminal output — daily tables, stats blocks, summaries

`run_selector_backtest` and the capital-flow logic remain in
op_momentum_selector_backtest.py.
"""
