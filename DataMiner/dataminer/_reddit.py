import os

import praw
from detonator import SingletonParent, get_logger


class Reddit(SingletonParent):
    def __init__(self):
        super().__init__()
        self.logger = get_logger('Reddit')
        client_id = os.getenv('REDDIT_CLIENT_ID')
        client_secret = os.getenv('REDDIT_CLIENT_SECRET')
        user_agent = os.getenv('REDDIT_USER_AGENT')
        if not client_id or not client_secret or not user_agent:
            raise Exception(
                'REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT must be set')
        self.reddit = praw.Reddit(
            client_id=client_id, client_secret=client_secret, user_agent=user_agent)

    def build_comment_tree(self, comments, level=0, max_depth=None):
        """
        Build a hierarchical comment tree structure

        Args:
            comments: Reddit comment object or list of comments
            level: Current nesting level
            max_depth: Maximum depth to traverse (None for unlimited)

        Returns:
            List of comment dictionaries with nested replies
        """
        comment_tree = []

        # Handle both single comment and list of comments
        if hasattr(comments, 'list'):
            comment_list = comments.list()
        else:
            comment_list = comments if isinstance(
                comments, list) else [comments]

        for comment in comment_list:
            # Skip MoreComments objects and deleted/removed comments
            if hasattr(comment, 'body') and comment.body not in ['[deleted]', '[removed]']:
                comment_dict = {
                    "body": comment.body,
                    "author": str(comment.author) if comment.author else "[deleted]",
                    "score": comment.score,
                    "created_utc": comment.created_utc,
                    "comment_id": comment.id,
                    "level": level
                }

                # Recursively build replies if they exist and we haven't hit max depth
                if hasattr(comment, 'replies') and comment.replies and (max_depth is None or level < max_depth):
                    replies = self.build_comment_tree(
                        comment.replies, level + 1, max_depth)
                    if replies:  # Only add replies if there are any
                        comment_dict["replies"] = replies

                comment_tree.append(comment_dict)

        return comment_tree

    def get_posts_with_comment_forest(self, posts, max_depth=None):
        """
        Get posts with their complete comment forest in hierarchical format

        Args:
            posts: List of Reddit submission objects
            max_depth: Maximum comment depth to traverse

        Returns:
            List of dictionaries with post data and hierarchical comment forest
        """
        result = []

        for post in posts:
            # Build post data
            post_data = {
                "title": post.title,
                "body": post.selftext if post.selftext else "",
                "url": post.url,
                "score": post.score,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc,
                "author": str(post.author) if post.author else "[deleted]",
                "subreddit": str(post.subreddit),
                "post_id": post.id
            }

            # Build comment forest
            try:
                # Replace MoreComments to get all comments
                post.comments.replace_more(limit=0)

                # Build hierarchical comment tree
                comment_forest = self.build_comment_tree(
                    post.comments, max_depth=max_depth)

                # Add comment forest to post data
                if comment_forest:
                    post_data["replies"] = comment_forest

            except Exception as e:
                self.logger.error(
                    f"Error building comment forest for post '{post.title}': {e}")
                post_data["replies"] = []

            result.append(post_data)

        return result

    def fetch_posts_with_comment_forest(self, subreddits: str | list[str], limit: int = 100, max_depth: int = None):
        if isinstance(subreddits, str):
            subreddits = [subreddits]
        result = []
        for subreddit in subreddits:
            posts = self.reddit.subreddit(subreddit).new(limit=limit)
            result = result + \
                self.get_posts_with_comment_forest(posts, max_depth=max_depth)
        return result
