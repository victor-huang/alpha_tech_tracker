"""Single construction site for `OpMomentumTradeEngine`.

Previously the engine was constructed in two places in op_momentum_trade_engine.py
(foreground `run` and daemon `start`) from 83 identical keyword arguments that
differed by exactly one line — `mock_trade_execution`. Both call sites now go
through `build_engine`, so a new engine parameter is wired in one place.

The keyword block below is copied verbatim from the foreground `run` path; the
values that differed between the two call sites are function parameters.
"""
from alpaca.data.enums import DataFeed

from ..trade_engine import OpMomentumTradeEngine
from .clients import _build_market_data_client, _build_option_price_monitor


def build_engine(
    args,
    *,
    client,
    is_paper,
    mock_trade_execution,
    contract_selector,
    windows,
):
    """Return a configured OpMomentumTradeEngine.

    `mock_trade_execution` is passed explicitly because the two original call
    sites computed it differently: the foreground path ORs in replay mode
    (`args.mock_trade_execution or is_replay`), the daemon path uses
    `args.mock_trade_execution` alone. That difference is preserved by the
    callers rather than re-derived here.
    """
    return OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            mock_trade_execution=mock_trade_execution,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            daily_max_loss_usd=args.daily_max_loss,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weights=args.rank_weighted_sizing,
            windows=windows,
            trade_type=args.trade_type,
            contract_selector=contract_selector,
            option_price_monitor=_build_option_price_monitor(args, client, args.tickers, contract_selector),
            enable_reversal=args.reversal,
            reversal_max_bars=args.reversal_max_bars,
            enable_bearish_reentry=args.bearish_reentry,
            bearish_reentry_max_bars=args.bearish_reentry_max_bars,
            enable_bullish_reentry=args.bullish_reentry,
            bullish_reentry_max_bars=args.bullish_reentry_max_bars,
            top_n=args.top,
            lookback_days=args.lookback,
            min_ev=args.min_ev,
            replay_capital=args.capital,
            ws_reconnect_timeout=args.ws_reconnect_timeout,
            alpaca_feed=DataFeed.IEX if args.feed == "iex" else DataFeed.SIP,
            score_feed=DataFeed.IEX if args.score_feed == "iex" else DataFeed.SIP if args.score_feed == "sip" else None,
            enable_doubledown=args.doubledown,
            doubledown_start_min=args.doubledown_start_min,
            record_tradestation_feed=args.record_tradestation_feed,
            market_data_client=_build_market_data_client(args),
            force_run=args.force_run,
            reset_session=args.reset_session,
            reentry_after_next_window_returned=args.reentry_after_next_window_returned,
            trailing_ma_switch=args.trailing_ma_switch,
            trailing_ma_switch_factor=args.trailing_ma_switch_factor,
            trailing_ma_switch_period=args.trailing_ma_switch_period,
            ma_momentum_gate=args.ma_momentum_gate,
            score_entry_weight=args.score_entry_weight,
            score_avg_win_weight=args.score_avg_win_weight,
            score_win_rate_weight=args.score_win_rate_weight,
            score_rel_strength_weight=args.score_rel_strength_weight,
            score_ev_trend_weight=args.score_ev_trend_weight,
            normalize_or_by_adr=args.normalize_or_by_adr,
            min_pool_vote_to_trade=args.min_pool_vote_to_trade,
            ev_trend_days=args.ev_trend_days,
            qqq_or_weight=args.qqq_or_weight,
            dynamic_ev_gate=args.dynamic_ev_gate,
            dg_mode=args.dg_mode,
            dg_bull_threshold=args.dg_bull_threshold,
            dg_bear_threshold=args.dg_bear_threshold,
            dg_bull_exclude_pct=args.dg_bull_exclude_pct,
            dg_neutral_exclude_pct=args.dg_neutral_exclude_pct,
            dg_bear_exclude_pct=args.dg_bear_exclude_pct,
            dg_bull_min_wr=args.dg_bull_min_wr,
            dg_neutral_min_wr=args.dg_neutral_min_wr,
            dg_bear_min_wr=args.dg_bear_min_wr,
            dg_bull_min_wl=args.dg_bull_min_wl,
            dg_neutral_min_wl=args.dg_neutral_min_wl,
            dg_bear_min_wl=args.dg_bear_min_wl,
            adaptive_lookback=args.adaptive_lookback,
            al_bull_threshold=args.al_bull_threshold,
            al_bear_threshold=args.al_bear_threshold,
            al_bull_days=args.al_bull_days,
            al_neutral_days=args.al_neutral_days,
            al_bear_days=args.al_bear_days,
            direction_split_ev_gate=args.direction_split_ev_gate,
            ds_bull_min_ev=args.ds_bull_min_ev,
            ds_neutral_min_ev=args.ds_neutral_min_ev,
            ds_bear_min_ev=args.ds_bear_min_ev,
            min_score=args.min_score,
            enable_regime_engine=args.enable_regime_engine,
            regime_hold=args.regime_hold,
            disable_ma_stops_for_regime_hold=args.disable_ma_stops_for_regime_hold,
            selector_type=args.selector,
            direction_aware_scoring=args.direction_aware_scoring,
            fixed_signal_alloc=args.fixed_signal_alloc,
            extend_collection_bars=args.extend_collection_bars,
            min_hold_minutes=args.min_hold_minutes,
    )
