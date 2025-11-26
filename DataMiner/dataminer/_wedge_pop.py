import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

import numpy as np
import pandas as pd
import pytz
from detonator import (SingletonParent, get_logger, make_db_connection,
                       mongo_2_df, retry_mongo_operation, run_parallel)
from pandas import DataFrame
from scipy.signal import find_peaks

from ._market_data_shovel import MarketDataShovel
from ._trade_cal import TradeCalendarShovel
from .models import TickerDailyInfo

_l = get_logger('WedgePop', level=logging.NOTSET)


class WedgeConfig:
    MIN_WEDGE_LEN = 3
    MAX_WEDGE_LEN = 15
    PEAK_DISTANCE = 3
    R_SQUARED_THRESHOLD = 0.75
    MIN_RELATIVE_VOLUME = 1.5
    ATR_PERIOD = 5
    VOLUME_ROLLING_WINDOW = 22
    BACKWARD_LOOKBACK_VOLUME_WINDOW = 22


class WedgePop(SingletonParent):

    def _prepare_data(self, ticker: str) -> DataFrame:
        cal = TradeCalendarShovel.get_instance()
        try:
            make_db_connection()
            last_closed_trade_date = cal.get_last_closed_trade_date_before(
                datetime.now(tz=pytz.timezone('America/New_York')))
            last_closed_trade_date = datetime.strptime(
                last_closed_trade_date, '%Y%m%d')
            ticker_info = TickerDailyInfo.objects(
                ticker=ticker, interval='1d', wedge_status__exists=True, trade_date__lte=last_closed_trade_date)
            if ticker_info.count() == 0:
                # Get all records ordered by trade_date for new tickers
                ticker_daily_info_list = TickerDailyInfo.objects(
                    ticker=ticker, interval='1d').order_by('trade_date')
            else:
                # Get the latest record with wedge_status
                latest_with_wedge = TickerDailyInfo.objects(
                    ticker=ticker, interval='1d', wedge_status__exists=True).order_by('-trade_date').limit(1).first()
                if latest_with_wedge is None:
                    _l.error(f"No latest with wedge found for ticker {ticker}")
                    return DataFrame()
                earliest_for_calculation = TickerDailyInfo.objects(ticker=ticker, interval='1d', trade_date__lte=latest_with_wedge.trade_date).order_by(
                    '-trade_date').skip(WedgeConfig.VOLUME_ROLLING_WINDOW*2).limit(1).first()
                if earliest_for_calculation is None:
                    _l.error(
                        f"No earliest for calculation found for ticker {ticker}")
                    return DataFrame()
                ticker_daily_info_list = TickerDailyInfo.objects(
                    ticker=ticker, interval='1d', trade_date__gte=earliest_for_calculation.trade_date, trade_date__lte=last_closed_trade_date).order_by('trade_date')

            data = mongo_2_df(ticker_daily_info_list)
            if data.empty:
                _l.error(f"No data found for ticker {ticker}")
                return DataFrame()
            data = data[['_id', 'trade_date', 'ticker', 'open', 'high',
                         'low', 'close', 'volume', 'ema10', 'ema20']]
            return data
        except Exception as e:
            _l.error(f"Error preparing data for ticker {ticker}: {str(e)}")
            return DataFrame()

    def _preprocess_data(self, bars: DataFrame) -> DataFrame:
        # --- Indicator Calculations ---
        # Average volume calculation.
        bars['avg_volume'] = bars['volume'].rolling(
            window=WedgeConfig.VOLUME_ROLLING_WINDOW).mean()

        # --- Calculate Average True Range (ATR) for Volatility/Risk ---
        # ATR is a measure of volatility. It helps assess risk for setting stop-losses.
        high_low = bars['high'] - bars['low']
        high_close = np.abs(bars['high'] - bars['close'].shift())
        low_close = np.abs(bars['low'] - bars['close'].shift())

        # Calculate True Range as the maximum of the three ranges
        true_range = pd.concat(
            [high_low, high_close, low_close], axis=1).max(axis=1)

        # Calculate ATR using exponential moving average
        bars['atr'] = true_range.ewm(
            alpha=1/WedgeConfig.ATR_PERIOD, adjust=False).mean()

        bars['atr_slope'] = bars['atr'].rolling(window=3).apply(
            lambda x: np.polyfit(range(len(x)), x, 1)[
                0] if len(x) >= 3 else np.nan
        )

        bars['ema_diff'] = bars['ema10'] - bars['ema20']
        # Calculate slope of EMA difference using polynomial fitting over a rolling window
        bars['ema_diff_slope'] = bars['ema_diff'].rolling(window=3).apply(
            lambda x: np.polyfit(range(len(x)), x, 1)[
                0] if len(x) >= 3 else np.nan
        )
        bars['is_above_emas'] = (bars['close'] > bars['ema10'] * 0.999) & (
            bars['close'] > bars['ema20'] * 0.999)
        bars['is_below_any_emas'] = (bars['close'] < bars['ema10'] * 1.001) | (
            bars['close'] < bars['ema20'] * 1.001)
        bars['was_below_emas'] = bars['is_below_any_emas'].shift(1)
        bars['is_below_emas'] = (bars['close'] < bars['ema10'] * 1.001) & (
            bars['close'] < bars['ema20'] * 1.001)
        bars['is_above_any_emas'] = (bars['close'] > bars['ema10'] * 0.999) | (
            bars['close'] > bars['ema20'] * 0.999)
        bars['was_above_emas'] = bars['is_above_any_emas'].shift(1)
        # Calculate relative volume safely, avoiding division by zero or NaN
        bars['is_high_rvol'] = (
            (bars['volume'] / bars['avg_volume'] >= WedgeConfig.MIN_RELATIVE_VOLUME) &
            (bars['avg_volume'].notna()) &
            (bars['avg_volume'] > 0)
        )
        return bars

    def _is_wedge_pop(self, is_above_emas: bool, was_below_emas: bool, ema_diff_slope: float, volume_increased: bool, atr_slope: float) -> bool:
        return is_above_emas and was_below_emas and ema_diff_slope > 0 and volume_increased and atr_slope < 0

    def _is_wedge_drop(self, is_below_emas: bool, was_above_emas: bool, ema_diff_slope: float, volume_increased: bool, atr_slope: float) -> bool:
        return is_below_emas and was_above_emas and ema_diff_slope < 0 and volume_increased

    def update_wedge_pop(self, ticker: str) -> bool:
        _l.info(f"Updating wedge pop for ticker {ticker}")
        data: DataFrame = self._prepare_data(ticker)
        if data.empty or len(data) < 2*WedgeConfig.VOLUME_ROLLING_WINDOW:
            _l.error(f"No enough data found for ticker {ticker}")
            return False
        data: DataFrame = self._preprocess_data(data)
        if data.empty or len(data) < 2*WedgeConfig.VOLUME_ROLLING_WINDOW:
            _l.error(f"No valid data for ticker {ticker}")
            return False
        for i in range(2*WedgeConfig.VOLUME_ROLLING_WINDOW, len(data)):
            _l.debug(
                f'i: {data.iloc[i]["ticker"]} on {data.iloc[i]["trade_date"]}')
            wedge_window = data.iloc[i -
                                     WedgeConfig.BACKWARD_LOOKBACK_VOLUME_WINDOW + 1: i + 1]
            vol_high_idx, _ = find_peaks(
                wedge_window['volume'], distance=WedgeConfig.BACKWARD_LOOKBACK_VOLUME_WINDOW)
            vol_increased = False
            for idx in vol_high_idx:
                avg_vol = wedge_window['avg_volume'].iloc[idx]
                if pd.notna(avg_vol) and avg_vol > 0:
                    if (wedge_window['volume'].iloc[idx] / avg_vol) >= 1.5:
                        vol_increased = True
                        break

            # Check current volume relative to average volume
            current_avg_vol = data['avg_volume'].iloc[i]
            if pd.notna(current_avg_vol) and current_avg_vol > 0:
                vol_increased = (
                    data['volume'].iloc[i] / current_avg_vol >= 1.5 or vol_increased)
            _l.debug(
                f'{data.iloc[i].to_dict()} vol_increased: {vol_increased}')
            if self._is_wedge_pop(data['is_above_emas'].iloc[i], data['was_below_emas'].iloc[i], data['ema_diff_slope'].iloc[i], vol_increased, data['atr_slope'].iloc[i]):
                data.loc[i, 'wedge_status'] = 'pop'
            elif self._is_wedge_drop(data['is_below_emas'].iloc[i], data['was_above_emas'].iloc[i], data['ema_diff_slope'].iloc[i], vol_increased, data['atr_slope'].iloc[i]):
                data.loc[i, 'wedge_status'] = 'drop'
            else:
                data.loc[i, 'wedge_status'] = 'none'
            # Handle both ObjectId objects and string representations
            from bson import ObjectId
            object_id = data['_id'].iloc[i]
            if isinstance(object_id, ObjectId):
                # Already an ObjectId object
                pass
            else:
                # Handle string representation from mongo_2_df
                object_id = ObjectId(object_id['$oid'])
            wedge_status_value = data['wedge_status'].iloc[i]
            result = retry_mongo_operation(
                lambda: TickerDailyInfo.objects(id=object_id).update(
                    wedge_status=wedge_status_value),
                operation_name=f'update wedge_status for {ticker} on {data.iloc[i]["trade_date"]}'
            )
            _l.info(
                f'{ticker} on {data.iloc[i]["trade_date"]} {object_id} to {wedge_status_value} result: {result}')
        return True  # Return True to indicate successful processing

    def update_wedge_pop_for_index(self, idx: Literal['spx', 'iwd', 'iwf', 'iwm']) -> bool:
        md: MarketDataShovel = MarketDataShovel.get_instance()
        tickers: List[str] = md.get_latest_index_tickers(idx).tickers
        results: List[bool] = run_parallel(self.update_wedge_pop, tickers)
        _l.debug(f'results: {all(results)}')
        return all(results)

    def get_wedge_tickers_on(self, day: str | datetime, status: Optional[List[str] | Literal['pop', 'drop', 'none']] = ['pop', 'drop'], country: str = 'us', exchange: str = 'XNYS') -> List[str]:
        make_db_connection()
        cal = TradeCalendarShovel.get_instance()
        day = cal.get_last_closed_trade_date_before(
            day, country=country, exchange=exchange)
        query = {
            'trade_date': datetime.strptime(day, '%Y%m%d'),
            'wedge_status__in': [status] if isinstance(status, str) else status
        }
        tickers: List[str] = TickerDailyInfo.objects(
            **query).distinct('ticker')
        return tickers

    def get_wedge_tickers_on_today(self) -> List[str]:
        return self.get_wedge_tickers_on(datetime.now(tz=pytz.timezone('America/New_York')))

    def get_wedge_tickers_since(self, start_date: str | datetime, end_date: Optional[str | datetime] = None) -> List[str]:
        if end_date is None:
            end_date = datetime.now(tz=pytz.timezone('America/New_York'))
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y%m%d')
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y%m%d')
        tickers: List[str] = TickerDailyInfo.objects(
            wedge_status__in=['pop', 'drop'], trade_date__gte=start_date, trade_date__lte=end_date).distinct('ticker')
        return tickers

    def get_wedge_stats(self, start_date: Optional[str | datetime] = None, end_date: Optional[str | datetime] = None) -> Dict[Any, Any] | List[Any]:
        make_db_connection()
        cal = TradeCalendarShovel.get_instance()
        if start_date is None:
            start_date = datetime.now(tz=pytz.timezone(
                'America/New_York')) - timedelta(days=365*2)
        if end_date is None:
            end_date = cal.last_closed_trade_date(
                country='us', exchange='XNYS')
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y%m%d')
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y%m%d')
        _l.info(f'start_date: {start_date}, end_date: {end_date}')
        cal_dates = cal.trade_dates_since(
            start_date=start_date-timedelta(days=1), end_date=end_date)
        cal_dates = sorted(cal_dates)
        full_stats = []
        for cal_date in cal_dates:
            stats = {'date': cal_date}
            pops = self.get_wedge_tickers_on(cal_date, status='pop')
            drops = self.get_wedge_tickers_on(cal_date, status='drop')
            stats['total'] = len(pops) + len(drops)
            stats['pop'] = pops or []
            stats['drop'] = drops or []
            stats['pop_pct'] = len(
                pops) / stats['total'] if stats['total'] > 0 else 0.0
            stats['pop_pct'] = round(stats['pop_pct'], 3)
            stats['drop_pct'] = len(
                drops) / stats['total'] if stats['total'] > 0 else 0.0
            stats['drop_pct'] = round(stats['drop_pct'], 3)
            full_stats.append(stats)
        return full_stats
