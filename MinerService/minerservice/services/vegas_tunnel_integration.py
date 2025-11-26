import logging
from datetime import time
from threading import Thread
from typing import Any, Callable, Dict, List, Optional

import pytz
from dataminer import MarketDataShovel, TradeCalendarShovel, VegasTunnel
from detonator import IntradayTaskScheduler, get_logger, make_db_connection
from pandas import DataFrame

from ..utils import plot_vegas_double_tunnel_signals, send_email


class VegasTunnelIntegration:
    INTERVALS = ['30m', '65m']

    def __init__(self, callback: Callable[[Dict[str, Dict[str, DataFrame]]], None] = None):
        self.callback: Callable[[
            Dict[str, Dict[str, DataFrame]]], None] = callback or self._default_callback
        self.logger = get_logger('VegraTunnelIntegration', logging.DEBUG)
        self.vegas = VegasTunnel.get_instance()
        self.intraday_task_scheduler = IntradayTaskScheduler(self.INTERVALS, func=self._interval_callback_thread_func,
                                                             start_time=time(hour=9, minute=30,
                                                                             tzinfo=pytz.timezone('America/New_York')),
                                                             end_time=time(hour=16,
                                                                           tzinfo=pytz.timezone('America/New_York')),
                                                             schedule_delay=-0.1)
        self.bars: Optional[Dict[str, Dict[str, DataFrame]]] = {}
        self.trade_calendar: Optional[TradeCalendarShovel] = TradeCalendarShovel.get_instance(
        )

    def _interval_callback(self, intervals: List[str]) -> Any:
        if not self.trade_calendar.is_mkt_open():
            self.logger.info(
                'Market not open, skipping update vegas tunnel signal...')
            return
        mds: MarketDataShovel = MarketDataShovel.get_instance()
        tickers = [t.upper().replace('.', '-')
                   for t in mds.get_latest_index_tickers(index_name='ndx').tickers]
        if not tickers:
            self.logger.error(
                'No tickers found for ndx, skipping for %s', intervals)
            return
        self.logger.info('Intervals: %s', intervals)
        if not intervals:
            return
        bars: Dict[str, Dict[str, DataFrame]] = self.vegas.update_signals(
            tickers=tickers, intervals=intervals)
        self.bars = bars
        self.logger.debug('Updated vegas: %s', self.bars.keys())
        self.callback(bars)
        for interval, ticker_bars in self.bars.items():
            self.logger.debug('Interval: %s -> %s',
                              interval, ticker_bars.keys())
            for ticker, bar in ticker_bars.items():
                self.logger.debug('Bar: %s -> %s', ticker, bar.shape)

    def _interval_callback_thread_func(self, intervals: List[str]) -> Any:
        t = Thread(target=self._interval_callback, args=(intervals,))
        t.start()

    def _default_callback(self, all_bars: Dict[str, Dict[str, DataFrame]]) -> None:
        interval_tickers = {}
        for interval, ticker_bars in all_bars.items():
            interval_tickers[interval] = []
            for ticker, bars in ticker_bars.items():
                last = bars.iloc[-1]
                last_last = bars.iloc[-2]
                if last['wedge_signal'] != 0 or last['vegas_signal'] != 0 or last_last['wedge_signal'] != 0 or \
                        last_last['vegas_signal'] != 0:
                    self.logger.debug(f'{ticker} -> signal{bars[-2:]}')
                    plot_vegas_double_tunnel_signals(bars, ticker, interval)
                    interval_tickers[interval].append(ticker)
        send_email(interval_tickers)

    @property
    def intervals(self) -> List[str]:
        return self.INTERVALS

    def interval_tickers(self, interval: str) -> List[str]:
        if interval in self.bars:
            return list(self.bars[interval].keys())
        else:
            self.logger.error('Interval %s not found', interval)
            return []

    def interval_ticker_bars(self, interval: str, ticker: str) -> DataFrame:
        if interval not in self.bars:
            self.logger.error('No bars for %s now, maybe later:', interval)
            return DataFrame()
        if ticker not in self.bars[interval]:
            self.logger.error(
                'Interval ticker %s %s not found', interval, ticker)
            return DataFrame()
        return self.bars[interval][ticker]

    def start(self):
        make_db_connection()
        self.intraday_task_scheduler.start()

    def stop(self):
        self.intraday_task_scheduler.stop()
