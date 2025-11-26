"""
TODO:
    - make it a singleton class
    - improve db query performance
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from multiprocessing import Pool
from typing import Dict, Literal

import numpy as np
from detonator import (SingletonParent, get_logger, is_in_daemon,
                       make_db_connection, mongo_2_df, retry_mongo_operation)
from mongoengine import QuerySet
from pymongo import UpdateOne

from .models import IndexTickers, TickerDailyInfo

_logger = get_logger('Indicators')


def _get_since_trade_date_for_indicator(ticker: str, indicator: Literal['sma', 'ema'] = 'sma', interval: str = '1d',
                                        period: int = 20) -> datetime | None:
    """
    Generic function to get the since trade date for any indicator.
    TODO: check if the indicator is already calculated for the given ticker and interval.
    """
    ticker = ticker.upper()
    # First get the most recent document with the indicator
    query = {
        'ticker': ticker,
        'interval': interval
    }
    if indicator == 'ema':
        oldest_info = TickerDailyInfo.objects(
            **query).order_by('trade_date').limit(1).first()
        return oldest_info.trade_date if oldest_info else datetime(year=1970, month=1, day=1)
    latest_info: TickerDailyInfo = TickerDailyInfo.objects(
        **query).order_by('-trade_date').limit(1).first()

    # Use MongoEngine's proper syntax for existence checks
    query[f'{indicator}{period}__exists'] = True
    query[f'{indicator}{period}__ne'] = None

    # Use the compound index for efficient querying
    infos: QuerySet = TickerDailyInfo.objects(
        **query).order_by('-trade_date').limit(1)
    if infos.count() == 0:
        return datetime(year=1970, month=1, day=1)
    info: TickerDailyInfo = infos.first()
    if info.id == latest_info.id:
        return None

    # Then get the document that is 'period' days before
    query = {
        'ticker': ticker,
        'interval': interval,
        'trade_date__lte': info.trade_date
    }
    info = TickerDailyInfo.objects(
        **query).order_by('-trade_date').skip(period).first()
    if info is None:
        _logger.warning(
            'Illegal state _get_since_trade_date_for_indicator for %s (%s)', ticker, indicator)
        return datetime(year=1970, month=1, day=1)
    _logger.debug('since %s of %s for %s%d',
                  info.trade_date, ticker, indicator, period)
    return info.trade_date


def _calculate_indicator(ticker: str, indicator: Literal['sma', 'ema'] = 'sma', since: str | datetime | None = None,
                         interval: str = '1d', period: int = 20):
    _logger.info(
        'Calculating %s for %s since %s @ interval:%s period:%d', indicator, ticker, since, interval, period)
    start_time = datetime.now()
    ticker = ticker.upper()
    query = {'ticker': ticker, 'interval': interval}
    if since:
        query['trade_date__gte'] = since if isinstance(
            since, datetime) else datetime.strptime(since, '%Y%m%d')
    _logger.debug('query:%s', query)
    tickers = TickerDailyInfo.objects(**query).order_by('trade_date')
    tickers_df = mongo_2_df(tickers)
    _logger.info('Found %d documents for %s', len(tickers_df), ticker)

    if indicator == 'sma':
        values = tickers_df['close'].rolling(window=period).mean()
        tickers_df[f'sma{period}_t'] = values
        if f'sma{period}' not in tickers_df.columns:
            tickers_df[f'sma{period}'] = np.nan
        tickers_df = tickers_df[tickers_df[f'sma{period}_t'].notna(
        ) & tickers_df[f'sma{period}'].isna()]
    elif indicator == 'ema':
        values = tickers_df['close'].ewm(span=period, adjust=False).mean()
        tickers_df[f'ema{period}_t'] = values
        if f'ema{period}' not in tickers_df.columns:
            tickers_df[f'ema{period}'] = np.nan
        tickers_df = tickers_df[tickers_df[f'ema{period}_t'].notna(
        ) & tickers_df[f'ema{period}'].isna()]
    else:
        raise ValueError(f'Unsupported indicator: {indicator}')

    if len(tickers_df) > 0:
        _logger.info(
            f'{indicator}{period} for {ticker} @ {interval} since {since} is calculated')
    else:
        _logger.info(
            f'{indicator}{period} for {ticker} @ {interval} since {since} is already calculated')
        return

    # Create bulk operations
    bulk_operations = []
    for _, row in tickers_df.iterrows():
        # Create update operation without checking current value
        # Handle both ObjectId objects and string representations
        from bson import ObjectId
        if isinstance(row['_id'], ObjectId):
            object_id = row['_id']
        else:
            # Handle string representation from mongo_2_df
            object_id = ObjectId(row['_id']['$oid'])
        bulk_operations.append(
            UpdateOne(
                filter={'_id': object_id},
                update={
                    '$set': {f'{indicator}{period}': row[f'{indicator}{period}_t']}}
            )
        )
    if bulk_operations:
        _logger.info('Executing %d bulk operations for %s',
                     len(bulk_operations), ticker)
        # Log first few operations for debugging
        collection = TickerDailyInfo._get_collection()
        result = retry_mongo_operation(
            lambda: collection.bulk_write(bulk_operations, ordered=False),
            operation_name=f'bulk_write for {ticker} {indicator}{period}'
        )
        duration = (datetime.now() - start_time).total_seconds()
        _logger.info('Update completed in %.4f seconds. Modified: %d, Matched: %d',
                     duration, result.modified_count, result.matched_count)
    else:
        _logger.error(
            'No updates for %s %s%d, but it should not happen', ticker, indicator, period)


def _update_indicator_with_details(ticker: str, indicator: Literal['sma', 'ema'] = 'sma', interval: str = '1d',
                                   period: int = 20) -> bool:
    """
    Before calling this function, you should call update_tikers_daily_info.
    Updates the specified indicator for the given ticker.
    """
    _logger.info('Updating %s for %s @ interval:%s period:%d',
                 indicator, ticker, interval, period)
    try:
        since = _get_since_trade_date_for_indicator(
            ticker, indicator=indicator, interval=interval, period=period)
        if not since:
            _logger.info(
                'No need to update %s for %s%d, already up to date', ticker, indicator, period)
            return True
        _calculate_indicator(
            ticker, indicator=indicator, since=since,
            interval=interval, period=period)
        return True
    except Exception as e:
        _logger.error('Failed to update %s for %s',
                      indicator, ticker, exc_info=e)
        return False


def _update_ma_for_ticker(ticker: str) -> Dict[str, bool]:
    _logger.info('Updating sma for %s', ticker)
    make_db_connection()
    result = all(
        [
            _update_indicator_with_details(
                ticker, indicator='ema', interval='1d', period=10),
            _update_indicator_with_details(
                ticker, indicator='ema', interval='1d', period=20),
            _update_indicator_with_details(
                ticker, indicator='sma', interval='1d', period=10),
            _update_indicator_with_details(
                ticker, indicator='sma', interval='1d', period=20),
            _update_indicator_with_details(
                ticker, indicator='sma', interval='1d', period=50),
            _update_indicator_with_details(
                ticker, indicator='sma', interval='1d', period=200),
        ]
    )
    _logger.info('Updated sma for %s:%s', ticker, result)
    return {ticker: result}


def update_daily_ma_by_idx(index_name: str) -> bool:
    try:
        make_db_connection()
        index_tickers: IndexTickers = IndexTickers.objects(
            index_name=index_name).order_by('-as_of_date').limit(1).first()
        if not index_tickers:
            _logger.error('No index tickers found for %s', index_name)
            return False
        to_update = index_tickers.tickers
        for i in range(3):
            # retry for max 3 times
            _logger.info('Updating %s daily ma: %d -> %s',
                         index_name, i, to_update)
            temp_results: list = None
            if is_in_daemon():
                _logger.info('Using ThreadPoolExecutor')
                with ThreadPoolExecutor() as executor:
                    temp_results = list(executor.map(
                        _update_ma_for_ticker, to_update))
            else:
                _logger.info('Using Process Pool')
                with Pool(processes=os.cpu_count()) as p:
                    temp_results: list = p.map(
                        _update_ma_for_ticker, to_update)
            results = {}
            for r in temp_results:
                results.update(r)
            filtered_dict = {key: value for key,
                             value in results.items() if not value}
            to_update = list(filtered_dict.keys())
            if not to_update:
                return True
            else:
                _logger.info('Re-Updating %s daily ma: %s',
                             index_name, to_update)
        return False
    except Exception as e:
        _logger.error('Failed to update %s ma', index_name, exc_info=e)
        return False


class Indicators(SingletonParent):
    def __init__(self):
        make_db_connection()

    def update_spx_daily_ma(self) -> bool:
        return update_daily_ma_by_idx('spx')

    def update_daily_ma_by_idx(self, index_name: str) -> bool:
        return update_daily_ma_by_idx(index_name)

    def update_indicators_for_tickers(self, tickers: list[str]) -> bool:
        """
        Update indicators for the given list of tickers.
        :param tickers: List of ticker symbols.
        :return: Dictionary with ticker as key and update status as value.
        """
        results = {}
        for ticker in tickers:
            results[ticker] = _update_ma_for_ticker(ticker)
        return all(results.values())
