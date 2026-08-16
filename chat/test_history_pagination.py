from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Message

User = get_user_model()


class DMHistoryPaginationTests(TestCase):
    """
    DMHistoryView's queryset is already capped at [:50] — it's meant to
    return "the last 50 messages" as a flat list (see its docstring), not
    a paginated resource. But it's a plain generics.ListAPIView, which
    picks up the project-wide DEFAULT_PAGINATION_CLASS (PageNumberPagination,
    PAGE_SIZE=20) automatically — so the 50-item queryset gets paginated
    AGAIN on top of its own slice, and callers only ever see the first 20
    of those 50 messages, silently. Same bug shape for
    MessageHistoryView / CircleMessageHistoryView (community/circle chat).
    """

    def setUp(self):
        self.alice = User.objects.create_user(username="alice_hist", email="alice_hist@example.com", password="TestPass123!")
        self.bob = User.objects.create_user(username="bob_hist", email="bob_hist@example.com", password="TestPass123!")
        for i in range(35):
            Message.objects.create(sender=self.alice, recipient=self.bob, body=f"message {i}")

        self.client = APIClient()
        self.client.force_authenticate(user=self.bob)

    def test_history_returns_all_35_messages_not_just_a_page(self):
        resp = self.client.get(f"/api/chat/dm/{self.alice.id}/history/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        items = body if isinstance(body, list) else body.get("results", [])
        self.assertEqual(
            len(items), 35,
            f"expected all 35 messages (under the 50 cap), got {len(items)} — "
            f"DRF's default pagination is silently truncating the view's own [:50] slice",
        )
