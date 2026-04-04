from datetime import date, datetime
from typing import List, Literal, Optional, Union

import exchange_calendars as xcals
import pandas as pd
import pytz
from detonator import (SingletonParent, df_2_mongo, get_logger,
                       make_db_connection, utc_to_target_tz)

from .models import TradeCalendar

_logger = get_logger('TradeCalendarShovel')


class TradeCalendarShovel(SingletonParent):
    """
    Trade calendar bars source
    """
    DEF_START_DATE = '19800101'
    EXCHANGE_TZ_MAP = {
        'XNYS': pytz.timezone('America/New_York'),
        'XHKG': pytz.timezone('Asia/Hong_Kong'),
    }

    def __init__(self) -> None:
        make_db_connection()

    def _get_cal_range_to_update(self, country: str = 'us', exchange: str = 'XNYS') -> tuple[str, str]:
        cal_date: TradeCalendar = TradeCalendar.objects(
            country=country, exchange=exchange).order_by('-cal_date').only('cal_date').first()
        end_date = datetime.now(
            self.EXCHANGE_TZ_MAP[exchange]).strftime('%Y%m%d')
        if cal_date:
            start_date = datetime.strptime(
                cal_date.cal_date, '%Y%m%d')
            return (start_date.strftime('%Y%m%d'), end_date)
        return (self.DEF_START_DATE, end_date)

    def update_hk_trade_calendar(self) -> bool:
        start_date, end_date = self._get_cal_range_to_update('hk', 'XHKG')
        return self.update_trade_calendar(country='hk', exchange='XHKG', start_date=start_date, end_date=end_date)

    def update_us_trade_calendar(self) -> bool:
        start_date, end_date = self._get_cal_range_to_update('us', 'XNYS')
        return self.update_trade_calendar(country='us', exchange='XNYS', start_date=start_date, end_date=end_date)

    def update_trade_calendar(self, country: str = 'us', exchange: str = 'XNYS', start_date: str = '19800101',
                              end_date: str = '20250712') -> bool:
        try:
            start_date, end_date = self._get_cal_range_to_update(
                country, exchange)
            # _logger.info(f'update_trade_calendar: {start_date} -> {end_date}')
            if start_date >= end_date:
                return True
            cal_df = xcals.get_calendar(
                exchange, start=start_date, end=end_date).schedule
            if not cal_df.empty:
                cal_df['is_open'] = True
                full_index = pd.date_range(
                    start=cal_df.index[0], end=cal_df.index[-1], freq='D')
                cal_df = cal_df.reindex(full_index)
                # Drop the row where index matches start_date
                cal_df['country'] = country
                cal_df['exchange'] = exchange
                if start_date in cal_df.index.strftime('%Y%m%d'):
                    drop_idx = cal_df.index[cal_df.index.strftime(
                        '%Y%m%d') == start_date]
                    cal_df = cal_df.drop(drop_idx)
                cal_df['cal_date'] = cal_df.index.strftime('%Y%m%d')
                cal_df['is_open'] = cal_df['is_open'].fillna(False)
                cal_df['open'] = cal_df['open'].dt.strftime(
                    '%Y,%m,%d,%H,%M,%S,%f')
                cal_df['break_start'] = cal_df['break_start'].dt.strftime(
                    '%Y,%m,%d,%H,%M,%S,%f')
                cal_df['break_end'] = cal_df['break_end'].dt.strftime(
                    '%Y,%m,%d,%H,%M,%S,%f')
                cal_df['close'] = cal_df['close'].dt.strftime(
                    '%Y,%m,%d,%H,%M,%S,%f')
                # _logger.debug(f'update_trade_calendar: {cal_df}')
                df_2_mongo(cal_df, TradeCalendar)
            else:
                _logger.warning(
                    f'update_trade_calendar: {start_date} -> {end_date} is empty')
                return False
        except Exception as e:
            _logger.error(f'update_us_trade_calendar failed: {e}')

    def is_today_us_trade_day(self) -> bool:
        return self.is_today_trade_day(country='us', exchange='XNYS')

    def is_today_hk_trade_day(self) -> bool:
        return self.is_today_trade_day(country='hk', exchange='XHKG')

    def is_today_trade_day(self, country: str = 'us', exchange: str = 'XNYS') -> bool:
        try:
            self.update_trade_calendar(country=country, exchange=exchange)
            today_date = datetime.now(
                self.EXCHANGE_TZ_MAP[exchange]).strftime('%Y%m%d')
            return TradeCalendar.objects(country=country, exchange=exchange,
                                         cal_date=today_date).first().is_open == True
        except Exception as e:
            _logger.error(f'is_today_us_trade_day failed: {e}')
            raise

    def last_us_trade_day_before_today(self) -> str:
        return self.last_trade_day_before_today(country='us', exchange='XNYS')

    def last_hk_trade_day_before_today(self) -> str:
        return self.last_trade_day_before_today(country='hk', exchange='XHKG')

    def last_trade_day_before_today(self, country: str = 'us', exchange: str = 'XNYS') -> str:
        try:
            self.update_trade_calendar(country=country, exchange=exchange)
            today_date = datetime.now(
                self.EXCHANGE_TZ_MAP[exchange]).strftime('%Y%m%d')
            return TradeCalendar.objects(country=country, exchange=exchange, cal_date__lt=today_date,
                                         is_open=True).order_by('-cal_date').first().cal_date
        except Exception as e:
            _logger.error(
                f'last_trade_day_before_today failed:{e}', stack_info=True)
            return ''

    def us_trade_dates_since(self, start_date: str | date | datetime,
                             end_date: str | date | datetime = '') -> List[str] | None:
        return self.trade_dates_since(country='us', exchange='XNYS', start_date=start_date, end_date=end_date)

    def hk_trade_dates_since(self, start_date: str | date | datetime,
                             end_date: str | date | datetime = '') -> List[str] | None:
        return self.trade_dates_since(country='hk', exchange='XHKG', start_date=start_date, end_date=end_date)

    def trade_dates_since(self, country: str = 'us', exchange: str = 'XNYS', start_date: str | date | datetime = '',
                          end_date: str | date | datetime = '') -> List[str] | None:
        if not isinstance(start_date, (str, date, datetime)):
            _logger.error(f'Illegal argument trade_date_since: {start_date}')
            return None
        start_date = start_date if isinstance(
            start_date, str) else start_date.strftime('%Y%m%d')
        if not end_date:
            end_date = self.last_closed_trade_date(
                country=country, exchange=exchange)
        end_date = end_date if isinstance(
            end_date, str) else end_date.strftime('%Y%m%d')
        try:
            self.update_trade_calendar(country=country, exchange=exchange)
            trade_dates = TradeCalendar.objects(cal_date__gt=start_date,
                                                cal_date__lte=end_date, country=country, exchange=exchange,
                                                is_open=True).order_by('-cal_date')
            return [t.cal_date for t in trade_dates]
        except Exception as e:
            _logger.error(
                f'Failed to us_trade_dates_since:{start_date} -> {end_date}', exc_info=e)
            return None

    def last_closed_us_trade_date(self) -> str | None:
        return self.last_closed_trade_date(country='us', exchange='XNYS')

    def last_closed_hk_trade_date(self) -> str | None:
        return self.last_closed_trade_date(country='hk', exchange='XHKG')

    def last_closed_trade_date(self, country: str = 'us', exchange: str = 'XNYS') -> str | None:
        """
        返回最近的已经收盘的交易日 YYYYmmdd
        """
        try:
            self.update_trade_calendar(country=country, exchange=exchange)
            today_date = datetime.now(self.EXCHANGE_TZ_MAP[exchange])
            this_cal_date: TradeCalendar = TradeCalendar.objects(country=country, exchange=exchange,
                                                                 cal_date=today_date.strftime('%Y%m%d')).first()
            if this_cal_date and this_cal_date.is_open and today_date > utc_to_target_tz(this_cal_date.close,
                                                                                         self.EXCHANGE_TZ_MAP[
                                                                                             exchange]):
                return this_cal_date.cal_date
            if not this_cal_date:
                _logger.warning(
                    f'{today_date} is not in trade calendar({country}, {exchange}, something may be wrong with bars source), use last trade day before today')
            return self.last_trade_day_before_today(country=country, exchange=exchange)
        except Exception as e:
            _logger.error(
                'Failed to get last_closed_us_trade_date', exc_info=e)
            return None

    def is_trade_day(self, date: str | datetime, country: str = 'us', exchange: str = 'XNYS') -> bool:
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y%m%d')
        return TradeCalendar.objects(cal_date=date.strftime('%Y%m%d'), is_open=True, country=country,
                                     exchange=exchange).first() is not None

    def get_last_closed_trade_date_before(self, day: str | datetime, country: str = 'us',
                                          exchange: str = 'XNYS') -> str:
        if isinstance(day, datetime):
            day = day.strftime('%Y%m%d')
        now = datetime.now(pytz.timezone('UTC'))
        return TradeCalendar.objects(cal_date__lte=day, is_open=True, country=country, exchange=exchange,
                                     close__lte=now).order_by('-cal_date').first().cal_date

    def is_mkt_open(self, dt: datetime | None = None, country: str = 'us', exchange: str = 'XNYS') -> bool:
        '''
        Check if the market is open at the given datetime
        Args:
            dt: datetime, utc datetime to check, if None, use current time
            country: str, country code, e.g. 'us', 'hk'
            exchange: str, exchange code, e.g. 'XNYS', 'XHKG'
        Returns:
            bool
        '''
        self.update_trade_calendar(country=country, exchange=exchange)
        dt = dt or datetime.now(pytz.timezone('UTC'))
        return TradeCalendar.objects(open__lte=dt, close__gte=dt, is_open=True, country=country,
                                     exchange=exchange).count() > 0

    def get_trade_date_N_days_before(self, n: int,the_date:Union[str, datetime, None] = None, country: Literal['us', 'hk'] = 'us',
                                  exchange: Literal['XNYS', 'XHKG'] = 'XNYS') -> Optional[str]:
        """
        Get the Nth trade date before the given date.
        TODO: define Literalexchange/country/ the_date as enum
        Args:
            n: int, number of days before the given date
            the_date: Union[str, datetime, None] = None, if str, it should be in format YYYYMMDD or YYYY-MM-DD
            country: Literal['us', 'hk'] = 'us', country code
            exchange: Literal['XNYS', 'XHKG'] = 'XNYS', exchange code
        Returns:
            Optional[str], the Nth trade date before the given date
        """
        if isinstance(the_date, datetime):
            the_date = the_date.strftime('%Y%m%d')
        last_closed_date = the_date or self.last_closed_trade_date(country=country, exchange=exchange)
        trade_dates = list(TradeCalendar.objects(cal_date__lte=last_closed_date, is_open=True, country=country,
                                                 exchange=exchange).order_by('-cal_date').limit(n))
        if trade_dates and len(trade_dates) == n:
            tc: TradeCalendar = trade_dates[-1]
            return tc.cal_date
        else:
            return None

    def get_us_trade_date_N_days_ago(self, n: int) -> Optional[str]:
        return self.get_trade_date_N_days_ago(n, country='us', exchange='XNYS')

    def get_hk_trade_date_N_days_ago(self, n: int) -> Optional[str]:
        return self.get_trade_date_N_days_ago(n, country='hk', exchange='XHKG')
