from unittest import TestCase
from unittest.mock import MagicMock, patch

from detonator import chunk_discord_content, send_discord_bot_messages


class DiscordNotifyTestCase(TestCase):
    def test_chunk_empty(self):
        self.assertEqual(chunk_discord_content(''), [''])

    def test_chunk_short(self):
        self.assertEqual(chunk_discord_content('hello'), ['hello'])

    def test_chunk_splits_long(self):
        text = 'a' * 5000
        parts = chunk_discord_content(text, max_len=2000)
        self.assertTrue(all(len(p) <= 2000 for p in parts))
        self.assertEqual(''.join(parts).replace('\n', ''), text)

    @patch('detonator._discord_notify.time.sleep', autospec=True)
    @patch('detonator._discord_notify.requests.post')
    def test_post_retries_on_429_then_succeeds(self, mock_post, _mock_sleep):
        responses = []
        for _ in range(2):
            r429 = MagicMock()
            r429.status_code = 429
            r429.json.return_value = {'retry_after': 0.05}
            responses.append(r429)
        r200 = MagicMock()
        r200.status_code = 200
        r200.json.return_value = {}
        responses.append(r200)
        mock_post.side_effect = responses

        r = send_discord_bot_messages(
            'hello',
            bot_token='test.token.here',
            channel_ids=['123456789012345678'],
            user_ids=[],
        )
        self.assertTrue(r.ok)
        self.assertEqual(mock_post.call_count, 3)

    @patch('detonator._discord_notify.requests.post')
    def test_send_channel_only(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_post.return_value = mock_resp

        r = send_discord_bot_messages(
            'hello world',
            bot_token='test.token.here',
            channel_ids=['123456789012345678'],
            user_ids=[],
        )
        self.assertTrue(r.ok)
        self.assertEqual(mock_post.call_count, 1)
        url = mock_post.call_args[0][0]
        self.assertIn('/channels/123456789012345678/messages', url)

    @patch('detonator._discord_notify.requests.post')
    def test_send_dm_opens_then_posts(self, mock_post):
        def side_effect(url, **_kwargs):
            r = MagicMock()
            if '/users/@me/channels' in url:
                r.status_code = 200
                r.json.return_value = {'id': '999888777666555444'}
            else:
                r.status_code = 200
                r.json.return_value = {}
            return r

        mock_post.side_effect = side_effect

        r = send_discord_bot_messages(
            'hi',
            bot_token='test.token.here',
            channel_ids=[],
            user_ids=['111222333444555666'],
        )
        self.assertTrue(r.ok)
        self.assertGreaterEqual(mock_post.call_count, 2)

    def test_send_no_token(self):
        r = send_discord_bot_messages('x', bot_token='', channel_ids=['1'])
        self.assertFalse(r.ok)
        self.assertIn('token', r.errors[0].lower())

    def test_send_no_destinations(self):
        r = send_discord_bot_messages('x', bot_token='abc', channel_ids=[], user_ids=[])
        self.assertFalse(r.ok)
