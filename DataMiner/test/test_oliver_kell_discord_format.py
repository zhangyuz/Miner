import os
from unittest import TestCase
from unittest.mock import patch

from dataminer._oliver_kell_discord_format import (
    format_oliver_kell_discord_message,
    notify_oliver_kell_analysis_if_configured,
)


class OliverKellDiscordFormatTestCase(TestCase):
    def test_format_contains_trade_day_and_tickers(self):
        text = format_oliver_kell_discord_message({
            'trade_day': '20260115',
            'methodology': 'oliver_kell',
            'summary': {'market_posture': 'risk-on', 'top_picks': ['NVDA'], 'avoid': []},
            'analysis': [{'ticker': 'NVDA', 'score': 88, 'verdict': 'watch'}],
        })
        self.assertIn('20260115', text)
        self.assertIn('NVDA', text)
        self.assertIn('## 📊 Wedge-Pop Analysis', text)
        self.assertNotIn('source:', text)
        self.assertNotIn('oliver_kell', text.split('\n')[0])

    def test_format_includes_reasoning_and_extra_fields(self):
        text = format_oliver_kell_discord_message({
            'trade_day': '20260115',
            'source': 'mongodb',
            'methodology': 'oliver_kell',
            'summary': {},
            'analysis': [{
                'ticker': 'AAPL',
                'score': 50,
                'verdict': 'pass',
                'trend_template': 'uptrend',
                'reasoning': ['First line', 'Second line'],
                'notes': 'from extra_fields',
            }],
        })
        self.assertNotIn('source:', text)
        self.assertNotIn('`oliver_kell`', text)
        self.assertIn('📈', text)
        self.assertIn('Trend', text)
        self.assertIn('**💬 Reasoning**', text)
        self.assertIn('• First line', text)
        self.assertIn('**🏷️ `notes`**', text)

    def test_per_ticker_ordered_by_score_desc(self):
        text = format_oliver_kell_discord_message({
            'trade_day': '20260115',
            'summary': {},
            'analysis': [
                {'ticker': 'LOW', 'score': 10, 'verdict': 'x'},
                {'ticker': 'HIGH', 'score': 100, 'verdict': 'x'},
                {'ticker': 'MID', 'score': 50, 'verdict': 'x'},
            ],
        })
        i_high = text.find('**`HIGH`**')
        i_mid = text.find('**`MID`**')
        i_low = text.find('**`LOW`**')
        self.assertLess(i_high, i_mid)
        self.assertLess(i_mid, i_low)

    def test_backticks_sanitized_in_inline_fields(self):
        text = format_oliver_kell_discord_message({
            'trade_day': '20260115',
            'summary': {'market_posture': 'risk`on` mixed', 'top_picks': [], 'avoid': []},
            'analysis': [{'ticker': 'NV`DA', 'score': 1, 'verdict': 'watch'}],
        })
        self.assertNotIn('`on`', text)
        self.assertIn("risk'on' mixed", text)
        self.assertIn("NV'DA", text)

    def test_market_posture_blockquote_truncates(self):
        long_posture = 'word ' * 120
        text = format_oliver_kell_discord_message({
            'trade_day': '20260115',
            'summary': {'market_posture': long_posture, 'top_picks': [], 'avoid': []},
            'analysis': [],
        })
        self.assertIn('> 📝', text)
        self.assertIn('…', text)
        self.assertLess(len(text), 900)

    def test_repr_truncated_without_splitting_mid_backtick(self):
        huge = {'k': 'x' * 2000}
        text = format_oliver_kell_discord_message({
            'trade_day': '20260115',
            'summary': {},
            'analysis': [{'ticker': 'Z', 'trend_template': huge}],
        })
        self.assertIn('…', text)
        self.assertLess(len(text), 2500)

    @patch('dataminer._oliver_kell_discord_format.send_discord_bot_messages')
    def test_notify_respects_env(self, mock_send):
        mock_send.return_value.ok = True
        os.environ['DISCORD_OLIVER_KELL_ENABLED'] = '1'
        os.environ['DISCORD_BOT_TOKEN'] = 'fake.token'
        os.environ['DISCORD_OLIVER_KELL_CHANNEL_IDS'] = '123456789012345678'
        os.environ['DISCORD_OLIVER_KELL_USER_IDS'] = ''
        try:
            notify_oliver_kell_analysis_if_configured({
                'trade_day': '20260115',
                'methodology': 'oliver_kell',
                'summary': {},
                'analysis': [{'ticker': 'AAPL', 'score': 1, 'verdict': 'watch'}],
            })
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            self.assertIn('## 📊 Wedge-Pop Analysis', args[0])
            self.assertIn('AAPL', args[0])
            self.assertEqual(kwargs['bot_token'], 'fake.token')
            self.assertEqual(kwargs['channel_ids'], ['123456789012345678'])
            self.assertEqual(kwargs['user_ids'], [])
        finally:
            for k in (
                'DISCORD_OLIVER_KELL_ENABLED',
                'DISCORD_BOT_TOKEN',
                'DISCORD_OLIVER_KELL_CHANNEL_IDS',
            ):
                os.environ.pop(k, None)

    @patch('dataminer._oliver_kell_discord_format.send_discord_bot_messages')
    def test_notify_skips_when_disabled(self, mock_send):
        os.environ['DISCORD_OLIVER_KELL_ENABLED'] = '0'
        os.environ['DISCORD_BOT_TOKEN'] = 'fake.token'
        os.environ['DISCORD_OLIVER_KELL_CHANNEL_IDS'] = '123'
        try:
            notify_oliver_kell_analysis_if_configured({'trade_day': 'x', 'analysis': []})
            self.assertFalse(mock_send.called)
        finally:
            for k in ('DISCORD_OLIVER_KELL_ENABLED', 'DISCORD_BOT_TOKEN', 'DISCORD_OLIVER_KELL_CHANNEL_IDS'):
                os.environ.pop(k, None)
