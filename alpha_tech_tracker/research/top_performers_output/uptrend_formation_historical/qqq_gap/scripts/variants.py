"""Large top-10 book with one setting changed at a time, for one year.

    python -m alpha_tech_tracker.research.historical.run_top_n variants.py <out_dir> 10 <year>
"""
import os
import pickle
import sys

import pandas as pd

sys.path.insert(0, "/private/tmp/claude-502/-Users-victorhuang-work-alpha-tech-tracker/1e4ca225-fabc-4686-930e-fabda8eb1c54/scratchpad/books")
import top_n_books as tb  # noqa: E402
from alpha_tech_tracker.research import selection_filters as sf  # noqa: E402
from alpha_tech_tracker.research.historical.securities import sec_ticker_ciks  # noqa: E402
from alpha_tech_tracker.research.sec_fundamentals import FundamentalsCache  # noqa: E402
from alpha_tech_tracker.research.selection_filters import parse_args, prepare_inputs, rank_variant  # noqa: E402
from alpha_tech_tracker.research.walk_forward_tuning import Setting, add_lookback_returns, variant_for  # noqa: E402

YEAR = int(sys.argv[3])
OUT_DIR = sys.argv[1]
TIER = "Large"
BASE = Setting(lookback=180, vol_power=0.5, clean=False, slots=True)


def everyone(p):
    return pd.Series(True, index=p.index)


VARIANTS = {
    "base": dict(setting=BASE),
    "no_stop": dict(setting=BASE, stop=10.0),
    "stop15": dict(setting=BASE, stop=0.15),
    "no_slots": dict(setting=BASE._replace(slots=False)),
    "lookback120": dict(setting=BASE._replace(lookback=120)),
    "lookback250": dict(setting=BASE._replace(lookback=250)),
    "lookback60": dict(setting=BASE._replace(lookback=60)),
    "raw_return": dict(setting=BASE._replace(vol_power=0.0)),
    "vol_power1": dict(setting=BASE._replace(vol_power=1.0)),
    "no_trend_filter": dict(setting=BASE, eligible=everyone),
    "top20": dict(setting=BASE, n=20),
    "top30": dict(setting=BASE, n=30),
    "rebalance_4w": dict(setting=BASE, every=2),
    "rebalance_8w": dict(setting=BASE, every=4),
}


if os.environ.get("VARIANT_PANEL_DIR"):
    # Alpaca years: CIKs from the SEC ticker file on disk, so nothing is sent to sec.gov
    _ciks = sec_ticker_ciks("/Users/victorhuang/work/alpha_tech_tracker_hist/market_data/historical/raw/sec/company_tickers.json")
    sf.FundamentalsCache = lambda root: FundamentalsCache(root, user_agent_for=lambda: "unused",
                                                          ticker_ciks=lambda agent: _ciks)


def main():
    extra = ["--panel-dir", os.environ["VARIANT_PANEL_DIR"]] if os.environ.get("VARIANT_PANEL_DIR") else []
    inputs = prepare_inputs(parse_args(["--years", str(YEAR)] + extra))
    end = f"{YEAR}-12-31"
    close = inputs.close.loc[:end]
    panel = add_lookback_returns(tb.prepare_recommended_panel(inputs.panel, inputs.close), inputs.close, (60, 120, 250))
    checkpoints = list(inputs.checkpoints)
    qqq = close["QQQ"][close.index >= checkpoints[0]]
    rows = [dict(year=YEAR, variant="QQQ", ret=qqq.iloc[-1] / qqq.iloc[0] - 1)]
    for name, v in VARIANTS.items():
        variant = variant_for(v["setting"])
        if "eligible" in v:
            variant = variant._replace(eligible=v["eligible"])
        tb.N = v.get("n", 10)
        ranked = rank_variant(panel, variant, 40)
        ranked = ranked[ranked["tier"] == TIER]
        cps = checkpoints[::v.get("every", 1)]
        symbols = sorted(set(ranked["symbol"]))
        eq, trades = tb.simulate(tb.ranked_picker(ranked), close[symbols], cps, v.get("stop", 0.25))
        dd = (eq / eq.cummax() - 1).min()
        rows.append(dict(year=YEAR, variant=name, ret=eq.iloc[-1] - 1, max_dd=dd, trades=len(trades),
                         win_rate=(trades["ret"] > 0).mean() if len(trades) else None))
        print(name, f"{eq.iloc[-1] - 1:.1%}", flush=True)
        if name == "base":
            with open(os.path.join(OUT_DIR, f"base_book_{YEAR}.pkl"), "wb") as f:
                pickle.dump({"equity": eq, "trades": trades, "qqq": qqq / qqq.iloc[0]}, f)
    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, f"variants_{YEAR}.csv"), index=False)


main()
