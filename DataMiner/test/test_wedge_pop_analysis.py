import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

from dataminer._wedge_pop_analysis import WedgePopAnalyzer


class WedgePopAnalysisTestCase(TestCase):
    def test_build_prompt_contains_oliver_kell_criteria(self):
        analyzer = WedgePopAnalyzer.get_instance()
        tickers = ['NVDA', 'AAPL']
        ticker_data = {
            'NVDA': {'close': 100.0, 'volume': 12345},
            'AAPL': {'close': 200.0, 'volume': 23456},
        }

        prompt = analyzer._build_prompt(  # pylint: disable=protected-access
            tickers=tickers,
            ticker_data=ticker_data,
            day_key='20260101',
        )

        self.assertIn('Oliver Kell-inspired growth breakout methodology', prompt)
        self.assertIn('Trend template', prompt)
        self.assertIn('Relative strength', prompt)
        self.assertIn('STRICT JSON', prompt)
        self.assertIn('NVDA', prompt)
        self.assertIn('AAPL', prompt)

    @patch('dataminer._wedge_pop_analysis.run_gemini_prompt')
    @patch('dataminer._wedge_pop_analysis.WedgePop')
    @patch('dataminer._wedge_pop_analysis.TradeCalendarShovel')
    @patch.object(WedgePopAnalyzer, '_get_result_from_mongo')
    @patch.object(WedgePopAnalyzer, '_persist_analysis_records')
    @patch.object(WedgePopAnalyzer, '_get_ticker_snapshots')
    def test_analyze_persists_and_reads_mongo(
        self,
        mock_snapshots,
        mock_persist_records,
        mock_get_mongo,
        mock_cal,
        mock_wedge_pop,
        mock_run_gemini_prompt,
    ):
        mock_get_mongo.return_value = None
        mock_cal.get_instance.return_value.get_last_closed_trade_date_before.return_value = '20260101'

        mock_wedge = MagicMock()
        mock_wedge.get_wedge_tickers_on.return_value = ['NVDA']
        mock_wedge_pop.get_instance.return_value = mock_wedge
        mock_snapshots.return_value = {'NVDA': {'close': 100.0}}

        gemini_result = MagicMock()
        gemini_result.success = True
        gemini_result.output = json.dumps({
            'trade_day': '20260101',
            'summary': {'market_posture': 'constructive', 'top_picks': ['NVDA'], 'avoid': []},
            'analysis': [{'ticker': 'NVDA', 'score': 90, 'verdict': 'watch'}],
        })
        mock_run_gemini_prompt.return_value = gemini_result

        out_from_mongo = {
            'success': True,
            'trade_day': '20260101',
            'methodology': 'oliver_kell',
            'tickers': ['NVDA'],
            'analysis': [{'ticker': 'NVDA', 'score': 90.0, 'verdict': 'watch'}],
            'summary': {'market_posture': 'constructive', 'top_picks': ['NVDA'], 'avoid': []},
            'source': 'mongodb',
        }
        mock_get_mongo.side_effect = [None, out_from_mongo]

        analyzer = WedgePopAnalyzer.get_instance()
        result = analyzer.analyze_today()

        self.assertTrue(result['success'])
        self.assertEqual(result['trade_day'], '20260101')
        self.assertIn('analysis', result)
        self.assertEqual(result['analysis'][0]['ticker'], 'NVDA')
        self.assertTrue(mock_persist_records.called)
        self.assertEqual(mock_run_gemini_prompt.call_count, 1)
        mock_wedge.get_wedge_tickers_on.assert_called_once()

    @patch('dataminer._wedge_pop_analysis.WedgePop')
    @patch('dataminer._wedge_pop_analysis.TradeCalendarShovel')
    def test_empty_tickers_skips(self, mock_cal, mock_wedge_pop):
        mock_cal.get_instance.return_value.get_last_closed_trade_date_before.return_value = '20260101'

        mock_wedge = MagicMock()
        mock_wedge.get_wedge_tickers_on.return_value = []
        mock_wedge_pop.get_instance.return_value = mock_wedge

        analyzer = WedgePopAnalyzer.get_instance()
        result = analyzer.analyze_today()

        self.assertTrue(result['success'])
        self.assertEqual(result['trade_day'], '20260101')
        self.assertEqual(result['tickers'], [])
        self.assertEqual(result['summary']['market_posture'], 'no_wedge_pops')
