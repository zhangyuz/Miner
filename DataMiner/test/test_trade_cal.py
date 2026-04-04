import unittest

from dataminer import TradeCalendarShovel
from detonator import get_logger, make_db_connection
from mongoengine import disconnect_all

_logger = get_logger('TradeCalTestCase')


class TradeCalTestCase(unittest.TestCase):

    def setUp(self):
        make_db_connection()

    def tearDown(self):
        disconnect_all()

    def test_is_today_us_trade_day(self):
        tcs = TradeCalendarShovel.get_instance()
        _logger.info(f'is_today_us_trade_day:{tcs.is_today_us_trade_day()}')

    def test_last_us_trade_day_before_today(self):
        tcs = TradeCalendarShovel.get_instance()
        _logger.info(tcs.last_us_trade_day_before_today())

    def test_us_trade_dates_since(self):
        tcs = TradeCalendarShovel.get_instance()
        _logger.info(tcs.us_trade_dates_since('20231223', '20240102'))
        _logger.info(tcs.us_trade_dates_since('20250701'))

    def test_update_us_trade_calendar(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        tcs.update_us_trade_calendar()

    def test_last_closed_us_trade_date(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.info(tcs.last_closed_us_trade_date())
        from datetime import datetime
        _logger.info(f'{datetime.now().hour}')

    def test_update_hk_trade_calendar(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        tcs.update_hk_trade_calendar()

    def test_is_today_hk_trade_day(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.info(f'is_today_hk_trade_day:{tcs.is_today_hk_trade_day()}')

    def test_last_hk_trade_day_before_today(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.info(tcs.last_hk_trade_day_before_today())

    def test_hk_trade_dates_since(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.info(tcs.hk_trade_dates_since('20250721', '20250721'))

    def test_last_closed_hk_trade_date(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.info(tcs.last_closed_hk_trade_date())

    def test_is_mkt_open(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.info(tcs.is_mkt_open())

    def test_get_us_trade_date_N_days_ago(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.debug(tcs.get_us_trade_date_N_days_ago(10))

    def test_get_hk_trade_date_N_days_ago(self):
        tcs: TradeCalendarShovel = TradeCalendarShovel.get_instance()
        _logger.debug(tcs.get_hk_trade_date_N_days_ago(10))

    def tearDown(self):
        disconnect_all()


if __name__ == '__main__':
    unittest.main()
