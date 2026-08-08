import json
import os
import tempfile
from datetime import datetime, timedelta
from typing import Literal, Optional

import pytz
from dataminer import MarketDataShovel, WedgePop
from dataminer.models import MarketPe
from detonator import (IDX_COUNTRY_EXCHANGE_MAP, SingletonParent, get_logger,
                       make_db_connection, mongo_2_df)
from git import Repo
from git.remote import PushInfoList
from marketbreadth import MarketBreadth

REPO_URL = 'git@github.com:zhangyuz/Miner.git'

_logger = get_logger('Maintainer')


class GhPagesMaintainer(SingletonParent):
    def __init__(self, repo_url: str = REPO_URL, branch: str = 'main'):
        self.repo_url = repo_url
        self.branch = branch

    def _export_market_pe(self, index: Literal['spx', 'qqq', 'ndx', 'hsi'], file: str, start_date: str | None = None, end_date: str | None = None):
        _, _, timezone = IDX_COUNTRY_EXCHANGE_MAP[index]
        end_date = datetime.now(tz=timezone).strftime('%Y-%m-%d')
        # Default to 21 years ago
        start_date = (datetime.now(tz=timezone) -
                      timedelta(days=365*21)).strftime('%Y-%m-%d')

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
            data.append([timestamp, round(float(row['pe']), 2)])

        # Calculate statistics
        pe_values = df['pe'].values
        avg_20y = float(pe_values.mean())
        current_pe = float(pe_values[-1]) if len(pe_values) > 0 else 0
        min_pe = float(pe_values.min())
        max_pe = float(pe_values.max())

        result = {
            'index': index,
            'data': data,
            'stats': {
                'avg_20y': round(avg_20y, 2),
                'current_pe': current_pe,
                'min_pe': round(min_pe, 2),
                'max_pe': round(max_pe, 2)
            }
        }
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def _export_market_breadth(self, index: Literal['spx'], file: str, start_date: str = None, end_date: str = None):
        _, _, timezone = IDX_COUNTRY_EXCHANGE_MAP[index]
        if end_date:
            end_date = datetime.strptime(end_date, '%Y%m%d')
        else:
            end_date = datetime.now(tz=timezone)

        if start_date:
            start_date = datetime.strptime(start_date, '%Y%m%d')
        else:
            start_date = end_date - timedelta(days=36500)
        result = MarketBreadth.get_instance().get_market_breath(market_index=index, start_date=start_date,
                                                                end_date=end_date)
        result.drop(columns=['_id'], inplace=True)
        result = result.to_dict(orient='records')
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def _get_ohlcvw(self, ticker: str, start_date: Optional[str] = None, end_date: Optional[str] = None, interval: str = '1d'):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        if start_date is None:
            start_date = datetime.now(tz=pytz.timezone(
                'America/New_York')) - timedelta(days=365*3)
        if end_date is None:
            end_date = datetime.now(tz=pytz.timezone(
                'America/New_York'))
        dailies_df = md.get_ticker_daily_info(
            ticker, start_date, end_date, interval=interval)
        dailies_df = dailies_df[['trade_date', 'ticker', 'open',
                                 'high', 'low', 'close', 'volume', 'wedge_status']]
        dailies_df.dropna(inplace=True)
        return dailies_df.to_dict(orient='records')

    def _export_ohlcvw(self, file_of_wdges_pop: str, file_of_wdges_stats: str, dir_of_ohlcvw: str) -> bool:
        try:
            wedge_pop: WedgePop = WedgePop.get_instance()
            start_date = datetime.now(tz=pytz.timezone(
                'America/New_York')) - timedelta(days=365)
            tickers = wedge_pop.get_wedge_tickers_since(start_date)
            stats = wedge_pop.get_wedge_stats(start_date)
            with open(file_of_wdges_pop, 'w', encoding='utf-8') as f:
                json.dump(tickers, f, ensure_ascii=False, indent=2)
            with open(file_of_wdges_stats, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            for ticker in tickers:
                result = self._get_ohlcvw(ticker)
                with open(os.path.join(dir_of_ohlcvw, f'{ticker}.json'), 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            _logger.error(f"Failed to export ohlcvw: {e}")
            return False

    def _export_static_json(self, dir_of_miner: str):
        # Ensure all target directories exist
        data_api_dir = os.path.join(
            dir_of_miner, 'StkGuru', 'public', 'api', 'v1', 'data')
        os.makedirs(os.path.join(data_api_dir, 'market_pe'), exist_ok=True)
        os.makedirs(os.path.join(data_api_dir, 'mbs'), exist_ok=True)
        os.makedirs(os.path.join(data_api_dir, 'ohlcvw'), exist_ok=True)
        os.makedirs(os.path.join(data_api_dir, 'wedge_pop'), exist_ok=True)
        self._export_market_pe('spx', os.path.join(
            data_api_dir, 'market_pe', 'spx.json'))
        self._export_market_pe('hsi', os.path.join(
            data_api_dir, 'market_pe', 'hsi.json'))
        self._export_market_breadth('spx', os.path.join(
            data_api_dir, 'mbs', 'spx.json'))
        self._export_ohlcvw(os.path.join(data_api_dir, 'wedge_pop', 'wedges.json'),
                            os.path.join(
                                data_api_dir, 'wedge_pop', 'stats.json'),
                            os.path.join(data_api_dir, 'ohlcvw'))

    def update_gh_pages(self) -> bool:
        make_db_connection()
        try:
            # 1. Clone the repo to a temp directory
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Repo.clone_from(
                    url=self.repo_url, to_path=tmpdir, branch=self.branch,
                    depth=1, single_branch=True)
                # 2. Pull the latest code (should be up-to-date after clone)
                # Skip, since we are depth=1 and single_branch
                # repo.git.checkout(self.branch)
                # repo.remotes.origin.pull()
                _logger.debug(f'{os.listdir(tmpdir)}')

                # 3. Run static export to the checked-out repo
                self._export_static_json(tmpdir)

                # 4. Check for changes
                repo.git.add(A=True)
                if repo.is_dirty(untracked_files=True):
                    repo.index.commit(
                        f'Update static data exports {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
                    push_result: PushInfoList = repo.remotes.origin.push()
                    if len(push_result) == 0:
                        _logger.error(f'Push failed: no push results')
                        return False
                    else:
                        _logger.info(f'\n{repo.git.show("--stat")}\n')
                else:
                    # No changes to commit
                    _logger.info('No changes to commit')
                    return True

            return True
        except Exception as e:
            _logger.error(f"Failed to update gh-pages: {e}")
            return False
