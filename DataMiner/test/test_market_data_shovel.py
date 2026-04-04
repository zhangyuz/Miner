import unittest
from datetime import datetime
from typing import Dict, List

from dataminer import MarketDataShovel
from detonator import make_db_connection
from mongoengine import disconnect_all
from pandas import DataFrame
from yfinance import Ticker as YTicker

from mongoengine import connect


class MarketDataShvelTestCase(unittest.TestCase):

    def setUp(self):
        connect(db='mongogo')
        # make_db_connection()

    def test_update_spx_tickers(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_spx_tickers(),
                        'Failed to update SPX tickers')

    def test_update_ndx_tickers(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_ndx_tickers(),
                        'Failed to update NDX tickers')

    def test_update_iwd_tickers(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_iwd_tickers(),
                        'Failed to update IWD tickers')

    def test_update_iwf_tickers(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_iwf_tickers(),
                        'Failed to update iwf tickers')

    def test_update_iwm_tickers(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_iwm_tickers(),
                        'Failed to update IWM tickers')

    def test_update_ticker_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_ticker_info('aapl')

    def test_update_ticker_daily_info_to_db(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        yticker = YTicker('^HSI')
        # md.fetch_ticker_daily_info_to_db(yticker, end_date='19861230')
        md.fetch_ticker_daily_info_to_db(
            yticker, start_date='19861230', end_date='20081230')

    def test_update_qqq_daily_info_to_db(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        yticker = YTicker('QQQ')
        md.fetch_ticker_daily_info_to_db(yticker)

    def test_update_iwm_daily_info_to_db(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_ticker_daily_info("IWM")

    def test_update_hsi_daily_info_to_db(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_ticker_daily_info("^HSI")

    def test_update_ticker_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_ticker_daily_info('TSLA')
        # md.update_ticker_daily_info('GOOGL')
        # md.update_ticker_daily_info('ZM')

    def test_get_latest_index_tickers(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        tickers = md.get_latest_index_tickers('spx')
        print(f'1tickers:{tickers}')
        print(f'2tickers:{list(tickers.tickers)}')

    def test_get_index_tickers_on(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        if it := md.get_index_tickers_on('spx'):
            print(it.tickers)
        else:
            print('Filed')

    def test_get_tickers_daily_info_on(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        print(md.get_tickers_daily_info_on(['AAPL', 'GOOGL'], '2024-01-12'))
        print(md.get_tickers_daily_info_on(
            ['AAPL', 'GOOGL'], datetime(year=2024, month=1, day=12)))

    def test_update_spx_tickers_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_spx_tickers_info()

    def test_update_ndx_tickers_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_ndx_tickers_info()

    def test_update_spx_tickers_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_spx_tickers_daily_info()

    def test_update_ndx_tickers_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_ndx_tickers_daily_info()

    def test_update_iwd_tickers_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_iwd_tickers_daily_info(),
                        'Failed to update IWD tickers daily info')

    def test_update_iwf_tickers_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_iwf_tickers_daily_info(),
                        'Failed to update iwf tickers daily info')

    def test_update_iwm_tickers_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_iwm_tickers_daily_info(),
                        'Failed to update IWM tickers daily info')

    def test_update_hsi_daily_info(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        self.assertTrue(md.update_hsi_daily_info(),
                        'Failed to update HSI daily info')

    def test_fetch_intraday_bars(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        df = md.fetch_bars(
            ['AAPL', 'GOOGL', 'MSFT'], period='1d', interval='30m')
        print(df)
        df = md.fetch_bars(
            ['AAPL', 'GOOGL', 'MSFT'], period='2d', interval='1d')
        print(df)
        self.assertTrue(len(df) == 234)

    def test_update_intraday_bars(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_intraday_bars(['AAPL', 'GOOGL', 'MSFT'], interval='5m')

    def test_update_intraday_bars_by_idx(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        md.update_intraday_bars_by_idx('ndx')

    def test_get_intraday_bars(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        bars: Dict[str, List[DataFrame]] = md.get_intraday_bars(
            ['AAPL', 'NVDA'], ['30m', '65m'])
        for i, ds in bars.items():
            print(i)
            for t, d in ds.items():
                print(t)
                print(d)

    def test_get_historical_bars(self):
        md: MarketDataShovel = MarketDataShovel.get_instance()
        bars: Dict[str, DataFrame] = md.get_historical_bars(
            ['AAPL', 'NVDA'], interval='1d', start_date='2024-01-01', end_date='2024-01-31')
        for t, d in bars.items():
            print(t)
            print(d)

    def tearDown(self):
        disconnect_all()


if __name__ == '__main__':
    unittest.main()
