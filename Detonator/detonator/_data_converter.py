import logging
from typing import Any, Type

import pandas as pd
from mongoengine import Document, NotUniqueError, QuerySet
from pandas import DataFrame, DatetimeIndex, PeriodIndex, TimedeltaIndex

from ._log import get_logger

_logger = get_logger('DataConverter', logging.NOTSET)


def dict_to_mongo(data: dict, doc: Type[Document], ingnore_not_unique_error=False):
    """
    Save dict to MongoDB
    :param data:
    :param doc:
    :return:
    """
    try:
        if data is not None and data:
            # doc.objects.insert(doc.objects.from_json(json.dumps(data)))
            doc(**data).save()
        else:
            _logger.warning('Empty dict not saved!')
    except NotUniqueError:
        if not ingnore_not_unique_error:
            raise


def df_2_mongo(data: DataFrame, doc: Type[Document], ingnore_not_unique_error=False):
    """
    Save DataFrame to MongoDB
    :param data:
    :param doc:
    :return:
    """
    try:
        if data is not None and data.shape[0] > 0:
            doc.objects.insert(doc.objects.from_json(
                data.to_json(orient='records')))
        else:
            _logger.warning('Empty DataFrame not saved!')
    except NotUniqueError:
        if not ingnore_not_unique_error:
            raise


def mongo_2_df(querySet: QuerySet) -> DataFrame:
    '''
    将数据库中查询到的数据转换为DataFrame,若无数据返回空的DataFrame
    '''
    # no_cache() prevents MongoEngine from holding all documents in its
    # internal queryset cache after iteration, which otherwise doubles
    # peak memory usage for large result sets.
    return DataFrame(list(querySet.no_cache().as_pymongo()))


# TODO: refactory the resamping functions as one

def _resample_ohlcv_session(bars: DataFrame, rule: Any) -> DataFrame:
    '''
    resample ohlcv, the column must include open/high/low/close/volume/timestamp
    '''
    # Anchor bins at 09:30 for this day
    _logger.debug('%s', rule)
    agg = {
        'ticker': 'first',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }

    day_midnight = bars.index[0].normalize()
    # this is us market open time in UTC
    session_start = day_midnight + pd.Timedelta(hours=13, minutes=30)
    return bars.resample(
        rule,  # "65min",
        origin=session_start,
        closed="left",
        label="left",
    ).agg(agg)


def resample_ohlcv(bars: DataFrame, rule) -> DataFrame:
    if bars.empty:
        _logger.warning('Empty DataFrame not saved!')
        return bars

    _logger.debug('%s \n rule: %s', bars.columns, rule)
    # Check if required columns exist
    required_columns = ['open', 'high', 'low', 'close', 'volume']

    if type(bars.index) in [DatetimeIndex, PeriodIndex, TimedeltaIndex]:
        if not all(col in bars.columns for col in required_columns):
            _logger.warning(
                'Columns %s not exist in DataFrame!', required_columns)
            return DataFrame()
    else:
        # Check if timestamp column exists and other required columns
        if 'timestamp' not in bars.columns or not all(col in bars.columns for col in required_columns):
            _logger.warning(
                'timestamp and columns %s not exist in DataFrame!', required_columns)
            return DataFrame()
        bars = bars.set_index('timestamp', drop=False)

    bars = (
        bars
        .groupby(bars.index.normalize())
        .apply(_resample_ohlcv_session, rule=rule)
        .droplevel(0)
        .dropna(how="all")
    )
    return bars


def resample_ohlcv_calendar(bars: DataFrame, freq: str) -> DataFrame:
    """
    Resample daily OHLCV bars to calendar-based periods like weekly ('W') or monthly ('M').

    Requirements:
    - Columns must include: 'open', 'high', 'low', 'close', 'volume'.
    - If index is not a Datetime-like index, a 'timestamp' column must exist.

    Aggregation:
    - open: first
    - high: max
    - low: min
    - close: last
    - volume: sum

    Examples:
    - freq='W' for weekly (period ends on Sunday by pandas default; for markets, 'W-FRI' or 'W-MON' might be preferred)
    - freq='M' for month-end; 'MS' for month-start
    - freq='Q' for quarter-end
    - freq='Y' or 'A' for year-end
    """
    if bars is None or bars.empty:
        _logger.warning('Empty DataFrame not saved!')
        return DataFrame()

    required_columns = ['open', 'high', 'low', 'close', 'volume']

    # Ensure datetime index
    if type(bars.index) not in [DatetimeIndex, PeriodIndex, TimedeltaIndex]:
        if 'timestamp' not in bars.columns:
            _logger.warning(
                'timestamp and columns %s not exist in DataFrame!', required_columns)
            return DataFrame()
        bars = bars.set_index('timestamp', drop=False)

    # Validate required columns
    if not all(col in bars.columns for col in required_columns):
        _logger.warning('Columns %s not exist in DataFrame!', required_columns)
        return DataFrame()

    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    if 'ticker' in bars.columns:
        agg['ticker'] = 'first'

    try:
        out = (
            bars
            .sort_index()
            .resample(freq, label='left', closed='left')
            .agg(agg)
            .dropna(how='all')
        )
        return out
    except Exception as exc:  # pragma: no cover
        _logger.exception('Failed to resample OHLCV to %s: %s', freq, exc)
        return DataFrame()
