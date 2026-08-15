from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from .tasks import notify

User = get_user_model()


class NotifyResilienceTests(TestCase):
    """
    Regression test for a real reliability gap: any view that triggers a
    notification (like, comment, join, follow, circle invite, verification
    decision...) used to call `create_notification.delay(...)` directly.
    `.delay()` talks to the Celery broker (Redis) to enqueue — if that
    connection is briefly down, `.delay()` raises right there, in the
    request thread, and an unrelated action (e.g. liking a post) would
    500 just because the notification pipe hiccupped. `notify()` wraps
    that so a broker outage degrades to "notification silently not sent"
    instead of "the actual action failed".
    """

    def test_notify_does_not_raise_when_broker_is_unreachable(self):
        recipient = User.objects.create_user(username='notify_target', email='notify_target@example.com', password='TestPass123!')

        with patch('notifications.tasks.create_notification.delay', side_effect=ConnectionError('broker unreachable')):
            try:
                notify(recipient_id=str(recipient.id), verb='post_liked', actor_id=None, target_id=None)
            except ConnectionError:
                self.fail('notify() let a broker ConnectionError propagate — this would 500 the calling request')
