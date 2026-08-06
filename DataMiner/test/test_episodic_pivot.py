from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

import pandas as pd


def _daily_bars_with_ep_event() -> pd.DataFrame:
    rows = []
    start = datetime(2024, 1, 2)
    for i in range(80):
        price = 20.0
        rows.append({
            'trade_date': start + timedelta(days=i),
            'ticker': 'EPST',
            'open': price * 0.995,
            'high': price * 1.015,
            'low': price * 0.985,
            'close': price,
            'volume': 1_000_000,
        })
    rows.append({
        'trade_date': start + timedelta(days=80),
        'ticker': 'EPST',
        'open': 23.00,
        'high': 25.00,
        'low': 22.40,
        'close': 24.60,
        'volume': 8_000_000,
    })
    return pd.DataFrame(rows)


def _one_minute_intraday_bars() -> pd.DataFrame:
    start = datetime(2024, 3, 22, 9, 30)
    highs = [23.50, 23.60, 23.80, 23.70, 24.00, 26.00, 25.50]
    lows = [23.30, 23.35, 23.42, 23.40, 23.55, 24.10, 24.20]
    rows = []
    for i, (high, low) in enumerate(zip(highs, lows)):
        rows.append({
            'timestamp': start + timedelta(minutes=i),
            'open': low + 0.10,
            'high': high,
            'low': low,
            'close': high - 0.05,
            'volume': 100_000 + i,
        })
    return pd.DataFrame(rows)


class EpisodicPivotAnalyzerTestCase(TestCase):

    def test_exports_public_ep_api_from_dataminer_package(self):
        try:
            from dataminer import EpisodicPivotAnalyzer, EpisodicPivotConfig
        except ImportError as exc:
            self.fail(f'EP public API is not exported: {exc}')

        self.assertIsNotNone(EpisodicPivotAnalyzer)
        self.assertIsNotNone(EpisodicPivotConfig)

    def test_detects_earnings_ep_using_prior_volume_and_gap(self):
        try:
            from dataminer._episodic_pivot import (
                EpisodicPivotAnalyzer,
                EpisodicPivotCatalyst,
                EpisodicPivotConfig,
            )
        except ModuleNotFoundError as exc:
            self.fail(f'Episodic pivot module is missing: {exc}')

        catalyst = EpisodicPivotCatalyst(
            kind='earnings',
            revenue_growth_yoy=0.45,
            eps_growth_yoy=0.80,
            guidance_raised=True,
            headline='Quarterly revenue and EPS beat with raised guidance',
        )
        analyzer = EpisodicPivotAnalyzer(
            EpisodicPivotConfig(
                min_avg_dollar_volume=5_000_000,
                min_gap_pct=0.10,
                min_relative_volume=3.0,
                require_catalyst=True,
            )
        )

        signal = analyzer.analyze_daily_bars(
            _daily_bars_with_ep_event(),
            ticker='EPST',
            catalyst=catalyst,
        )

        self.assertIsNotNone(signal)
        self.assertTrue(signal.is_candidate)
        self.assertEqual('EPST', signal.ticker)
        self.assertAlmostEqual(0.15, signal.gap_pct, places=4)
        self.assertAlmostEqual(8.0, signal.relative_volume, places=2)
        self.assertAlmostEqual(1_000_000, signal.avg_volume, places=2)
        self.assertGreaterEqual(signal.score, 70)

    def test_rejects_low_relative_volume_with_explicit_reason(self):
        from dataminer._episodic_pivot import (
            EpisodicPivotAnalyzer,
            EpisodicPivotConfig,
        )

        bars = _daily_bars_with_ep_event()
        bars.loc[bars.index[-1], 'volume'] = 2_000_000
        analyzer = EpisodicPivotAnalyzer(
            EpisodicPivotConfig(
                min_avg_dollar_volume=5_000_000,
                min_gap_pct=0.10,
                min_relative_volume=3.0,
            )
        )

        signal = analyzer.analyze_daily_bars(bars, ticker='EPST')

        self.assertIsNotNone(signal)
        self.assertFalse(signal.is_candidate)
        self.assertAlmostEqual(2.0, signal.relative_volume, places=2)
        self.assertAlmostEqual(1_000_000, signal.avg_volume, places=2)
        self.assertIn('relative_volume_below_minimum', signal.reject_reasons)

    def test_builds_opening_range_plan_from_first_minutes_only(self):
        from dataminer._episodic_pivot import (
            EpisodicPivotAnalyzer,
            EpisodicPivotConfig,
        )

        analyzer = EpisodicPivotAnalyzer(
            EpisodicPivotConfig(
                min_avg_dollar_volume=5_000_000,
                opening_range_minutes=5,
            )
        )
        signal = analyzer.analyze_daily_bars(_daily_bars_with_ep_event(), ticker='EPST')

        plan = analyzer.build_opening_range_plan(signal, _one_minute_intraday_bars())

        self.assertTrue(plan.is_tradeable)
        self.assertAlmostEqual(24.00, plan.entry, places=2)
        self.assertAlmostEqual(23.30, plan.stop, places=2)
        self.assertLess(plan.risk_adr_multiple, 1.5)

    def test_reads_daily_bars_from_mongo_without_write_operations(self):
        from dataminer._episodic_pivot import EpisodicPivotAnalyzer

        analyzer = EpisodicPivotAnalyzer()
        query = MagicMock()
        raw_df = pd.DataFrame([
            {'trade_date': datetime(2024, 1, 3), 'ticker': 'EPST', 'open': 11, 'high': 12, 'low': 10, 'close': 11, 'volume': 2},
            {'trade_date': datetime(2024, 1, 2), 'ticker': 'EPST', 'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 1},
        ])

        with patch('dataminer._episodic_pivot.make_db_connection') as connect, \
                patch('dataminer._episodic_pivot.TickerDailyInfo') as ticker_daily_info, \
                patch('dataminer._episodic_pivot.mongo_2_df') as mongo_2_df:
            ticker_daily_info.objects.return_value = query
            query.order_by.return_value = query
            query.limit.return_value = query
            mongo_2_df.return_value = raw_df

            bars = analyzer.read_daily_bars_from_mongo('epst', lookback=2)

        connect.assert_called_once()
        ticker_daily_info.objects.assert_called_once_with(ticker='EPST', interval='1d')
        query.order_by.assert_called_once_with('-trade_date')
        query.limit.assert_called_once_with(2)
        query.update.assert_not_called()
        query.delete.assert_not_called()
        self.assertEqual([datetime(2024, 1, 2), datetime(2024, 1, 3)], list(bars['trade_date']))

    def test_scan_mongo_daily_bars_uses_read_only_loader(self):
        from dataminer._episodic_pivot import (
            EpisodicPivotAnalyzer,
            EpisodicPivotCatalyst,
            EpisodicPivotConfig,
        )

        analyzer = EpisodicPivotAnalyzer(
            EpisodicPivotConfig(min_avg_dollar_volume=5_000_000)
        )
        self.assertTrue(
            hasattr(analyzer, 'scan_mongo_daily_bars'),
            'scan_mongo_daily_bars should expose a read-only Mongo scanner',
        )
        catalyst = EpisodicPivotCatalyst(kind='earnings', guidance_raised=True)

        with patch.object(
            analyzer,
            'read_daily_bars_from_mongo',
            return_value=_daily_bars_with_ep_event(),
        ) as read_daily:
            result = analyzer.scan_mongo_daily_bars(
                ['epst'],
                lookback=90,
                catalysts={'EPST': catalyst},
            )

        read_daily.assert_called_once_with('EPST', lookback=90, end_date=None, interval='1d')
        self.assertEqual(['EPST'], list(result['ticker']))
        self.assertTrue(result.iloc[0]['is_candidate'])
