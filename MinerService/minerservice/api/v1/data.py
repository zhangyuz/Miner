"""Data access endpoints"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from dataminer import MarketDataShovel, WedgePop, WedgePopAnalyzer
from dataminer.models import MarketPe
from detonator import make_db_connection, mongo_2_df
from fastapi import APIRouter
from marketbreadth import MarketBreadth

router = APIRouter(prefix='/data', tags=['data'])


@router.get('/mbs/{market_index}.json')
async def get_mbs(market_index: str = 'spx', start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]] | Dict[str, Any]:
    '''
    获取市场宽度分数
    :return:
    '''
    make_db_connection()
    return MarketBreadth.get_instance().get_market_breath(market_index=market_index, start_date=start_date,
                                                          end_date=end_date).dropna().drop(columns=['_id']).to_dict(orient='records')


@router.get('/market_pe/{index}.json')
async def get_market_pe(index: str = 'spx', start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    '''
    Get market PE data for visualization
    :param index: 'spx' or 'qqq'
    :param start_date: start date in YYYY-MM-DD format (optional)
    :param end_date: end date in YYYY-MM-DD format (optional)
    :return: dict with PE data and statistics
    '''
    make_db_connection()

    # Set default date range if not provided
    if not end_date:
        end_date = datetime.now(tz=pytz.timezone(
            'America/New_York')).strftime('%Y-%m-%d')
    if not start_date:
        # Default to 20 years ago
        start_date = (datetime.now(tz=pytz.timezone('America/New_York')
                                   ) - timedelta(days=365*20)).strftime('%Y-%m-%d')

    # Convert dates to datetime objects for querying
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')

    # Query the database
    query = {
        'idx': index,
        'trade_date__gte': start_dt,
        'trade_date__lte': end_dt
    }

    df = mongo_2_df(MarketPe.objects(**query).order_by('trade_date'))

    if df.empty:
        return {
            'index': index,
            'data': [],
            'stats': {
                'avg_20y': 0,
                'current_pe': 0,
                'min_pe': 0,
                'max_pe': 0
            }
        }

    # Convert to Highcharts format [timestamp, pe_value]
    data = []
    for _, row in df.iterrows():
        # Handle trade_date which might be a string from mongo_2_df
        if isinstance(row['trade_date'], str):
            # Parse the string date format from MongoDB
            # The scraper stores dates in format "2024,01,15,00,00,00,000000"
            try:
                # Try to parse the custom format used by the scraper
                dt = datetime.strptime(
                    row['trade_date'], '%Y,%m,%d,%H,%M,%S,%f')
            except ValueError:
                try:
                    # Try to parse ISO format as fallback
                    dt = datetime.fromisoformat(
                        row['trade_date'].replace('Z', '+00:00'))
                except ValueError:
                    # Fallback to other common formats
                    dt = datetime.strptime(
                        row['trade_date'], '%Y-%m-%d %H:%M:%S')
        else:
            # If it's already a datetime object
            dt = row['trade_date']

        timestamp = int(dt.timestamp() * 1000)  # Convert to milliseconds
        data.append([timestamp, float(row['pe'])])

    # Calculate statistics
    pe_values = df['pe'].values
    avg_20y = float(pe_values.mean())
    current_pe = float(pe_values[-1]) if len(pe_values) > 0 else 0
    min_pe = float(pe_values.min())
    max_pe = float(pe_values.max())

    return {
        'index': index,
        'data': data,
        'stats': {
            'avg_20y': avg_20y,
            'current_pe': current_pe,
            'min_pe': min_pe,
            'max_pe': max_pe
        }
    }


@router.get('/wedge_pop/latest.json', description='Get all wedge pop tickers of today')
async def get_wedge_pop_tickers_of_today() -> Dict[str, Any] | List[Any]:
    wedge_pop: WedgePop = WedgePop.get_instance()
    return wedge_pop.get_wedge_tickers_on_today()


@router.get('/wedge_pop/wedges.json', description='Get wedge pop tickers since 1 year ago')
async def get_wedge_pop_tickers() -> Dict[str, Any] | List[Any]:
    wedge_pop: WedgePop = WedgePop.get_instance()
    start_date = datetime.now(tz=pytz.timezone(
        'America/New_York')) - timedelta(days=365)
    return wedge_pop.get_wedge_tickers_since(start_date)


@router.get('/wedge_pop/stats.json', description='Get wedge pop stats')
async def get_wedge_pop_stats(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any] | List[Any]:
    wedge_pop: WedgePop = WedgePop.get_instance()
    return wedge_pop.get_wedge_stats(start_date=start_date, end_date=end_date)


@router.get('/wedge_pop/analysis.json', description='Get AI analysis of wedge pop tickers')
async def get_wedge_pop_analysis(date: Optional[str] = None) -> Dict[str, Any]:
    analyzer: WedgePopAnalyzer = WedgePopAnalyzer.get_instance()
    return analyzer.get_analysis(date=date) or {
        'success': False,
        'error': 'analysis_not_found',
        'trade_day': date,
        'analysis': [],
        'tickers': [],
        'methodology': 'oliver_kell',
    }


@router.get('/ohlcvw/{ticker}.json', description='Get OHLCVW data for a ticker, default to 3 years ago')
async def get_ohlcvw(ticker: str, start_date: Optional[str] = None, end_date: Optional[str] = None, interval: str = '1d') -> Dict[str, Any] | List[Any]:
    md: MarketDataShovel = MarketDataShovel.get_instance()
    if start_date is None:
        start_date = (datetime.now(tz=pytz.timezone(
            'America/New_York')) - timedelta(days=365*3)).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = (datetime.now(tz=pytz.timezone(
            'America/New_York'))).strftime('%Y-%m-%d')
    dailies_df = md.get_ticker_daily_info(
        ticker, start_date, end_date, interval=interval)
    dailies_df = dailies_df[['trade_date', 'ticker', 'open',
                             'high', 'low', 'close', 'volume', 'wedge_status']]
    return dailies_df.to_dict(orient='records')
