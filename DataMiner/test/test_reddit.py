from unittest import TestCase

from dataminer import Reddit


class RedditTestCase(TestCase):
    def test_reddit(self):
        reddit = Reddit.get_instance()
        posts = reddit.fetch_posts_with_comment_forest(
            'wallstreetbets', limit=100)
        print(posts)
