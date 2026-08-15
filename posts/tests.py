from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APITestCase

from communities.models import Community, Membership
from posts.models import Post, Comment

User = get_user_model()


def make_user(username, email):
    return User.objects.create_user(username=username, email=email, password="TestPass123!")


class PostSubtypeTests(APITestCase):
    """Regression suite for the Knowledge/Project/Resource composer fix —
    these post_type='post'+tags=[...] combos used to be silently rejected
    because the frontend sent the old post_type='knowledge' etc directly,
    which the ChoiceField no longer accepts."""

    def setUp(self):
        self.author = make_user("author1", "author1@example.com")
        self.community = Community.objects.create(name="Test Community")
        Membership.objects.create(user=self.author, community=self.community)
        self.client.force_authenticate(user=self.author)

    def test_question_post(self):
        resp = self.client.post("/api/posts/", {
            "post_type": "question", "title": "How do I center a div?",
            "body": "stuck for hours", "community": self.community.id,
        })
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_knowledge_post(self):
        resp = self.client.post("/api/posts/", {
            "post_type": "post", "title": "CSS guide", "body": "flexbox is great",
            "community": self.community.id, "tags": ["Knowledge"],
        }, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["tags"], ["Knowledge"])

    def test_project_post_with_generic_links(self):
        """A Project post must not assume a repo/live-site shape — an
        artist's project has neither. Links are freeform label+URL pairs."""
        resp = self.client.post("/api/posts/", {
            "post_type": "post", "title": "My art portfolio", "body": "made this",
            "community": self.community.id, "tags": ["Project"],
            "links": ["Portfolio|||https://myart.example.com", "Instagram|||https://instagram.com/me"],
        }, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(len(resp.json()["links"]), 2)

    def test_resource_post(self):
        resp = self.client.post("/api/posts/", {
            "post_type": "post", "title": "Great tool", "body": "useful find",
            "community": self.community.id, "tags": ["Resource"],
            "links": ["CSS Tricks|||https://css-tricks.com"],
        }, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_poll_post_and_voting(self):
        """Regression test for a real bug found & fixed: vote_count stayed
        0 in the vote response because the viewset's class-level
        prefetch_related('poll_options__votes') cache was reused instead
        of querying fresh (see posts/views.py PostViewSet.vote)."""
        resp = self.client.post("/api/posts/", {
            "post_type": "poll", "title": "Best language?", "body": "vote now",
            "community": self.community.id, "options": ["Python", "JavaScript"],
        }, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        post = resp.json()
        option_id = post["poll_options"][0]["id"]

        vote_resp = self.client.post(f"/api/posts/{post['id']}/vote/", {"option_id": option_id}, format="json")
        self.assertEqual(vote_resp.status_code, 200, vote_resp.content)
        voted_option = next(o for o in vote_resp.json()["options"] if o["id"] == option_id)
        self.assertEqual(voted_option["vote_count"], 1, "vote_count must reflect the vote just cast, not a stale cache")


class CommentNPlusOneTests(APITestCase):
    """Regression test for a real bug found & fixed: each top-level
    comment's replies used to run its own DB query (recursively, per
    nesting level) — see posts/views.py PostViewSet.comments and
    posts/serializers.py CommentSerializer.get_replies. Query count must
    now stay flat no matter how many comments/replies exist."""

    def setUp(self):
        self.author = make_user("author2", "author2@example.com")
        self.community = Community.objects.create(name="N+1 Test Community")
        Membership.objects.create(user=self.author, community=self.community)
        self.post = Post.objects.create(
            community=self.community, author=self.author, post_type=Post.PostType.QUESTION,
            title="Q", body="body",
        )
        self.client.force_authenticate(user=self.author)

    def _query_count_for_n_comments(self, n):
        Comment.objects.filter(post=self.post).delete()
        for i in range(n):
            top = Comment.objects.create(post=self.post, author=self.author, body=f"top {i}")
            Comment.objects.create(post=self.post, author=self.author, body=f"reply {i}", parent=top)

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(f"/api/posts/{self.post.id}/comments/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), n)
        return len(ctx.captured_queries)

    def test_query_count_does_not_scale_with_comment_count(self):
        queries_for_3 = self._query_count_for_n_comments(3)
        queries_for_15 = self._query_count_for_n_comments(15)
        self.assertEqual(
            queries_for_3, queries_for_15,
            f"query count grew with comment count ({queries_for_3} -> {queries_for_15}) — N+1 regression",
        )
