"""
Background jobs that actually use Celery (see settings.CELERY_* + the
worker command in render.yaml / README). Called with .delay(...) from the
views that trigger them (posts/views.py like+comment, verification/admin.py
approve/reject, communities/views.py join) so the request that triggered
the notification returns immediately instead of waiting on this.
"""

import logging

from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

logger = logging.getLogger('setu_backend')


@shared_task
def create_notification(recipient_id, verb, actor_id=None, target_id=None):
    """
    Creates the Notification row, then pushes it over the recipient's
    Channels group (`notifications_<user_id>`) so the bell icon updates
    live if they're online, same as chat messages do.

    Call this via `notify(...)` below rather than `.delay(...)` directly.
    """
    from django.contrib.auth import get_user_model
    from .models import Notification
    from .serializers import NotificationSerializer

    User = get_user_model()

    # Don't notify someone about their own action (e.g. liking your own post).
    if actor_id and str(actor_id) == str(recipient_id):
        return

    try:
        recipient = User.objects.get(id=recipient_id)
    except User.DoesNotExist:
        logger.warning('create_notification: recipient %s does not exist', recipient_id)
        return

    notification = Notification.objects.create(
        recipient=recipient,
        actor_id=actor_id,
        verb=verb,
        target_id=target_id,
    )

    channel_layer = get_channel_layer()
    if channel_layer is not None:
        try:
            async_to_sync(channel_layer.group_send)(
                f'notifications_{recipient_id}',
                {
                    'type': 'notify',
                    'notification': NotificationSerializer(notification).data,
                },
            )
        except Exception:
            # The Notification row above is already saved — that's the
            # part that matters (it's what the bell icon's list/unread-count
            # endpoints read). The live push is a nice-to-have on top of
            # that, so a broker hiccup here shouldn't fail the whole task:
            # letting it propagate would mark this task "failed" and, on
            # Celery's automatic retry, re-run the whole function from the
            # top — creating a *second* Notification row for the same
            # event. Logging and moving on avoids both problems.
            logger.warning('create_notification: live push failed for %s (row already saved)', recipient_id, exc_info=True)

    return str(notification.id)


def notify(recipient_id, verb, actor_id=None, target_id=None):
    """
    Fire-and-forget entry point every view should call instead of
    `create_notification.delay(...)` directly.

    `.delay()` itself talks to the Celery broker (Redis) to enqueue the
    task — if that connection is momentarily down, `.delay()` can raise
    right there, synchronously, in the request that's doing something
    completely unrelated (liking a post, joining a community, accepting a
    circle invite...). A notification is inherently best-effort — nobody's
    like/comment/join should fail because the notifications pipe hiccupped.
    This wrapper catches exactly that and just logs it instead.
    """
    try:
        create_notification.delay(
            recipient_id=recipient_id, verb=verb, actor_id=actor_id, target_id=target_id,
        )
    except Exception:
        logger.warning(
            'notify: failed to enqueue notification (verb=%s, recipient=%s) — broker likely unreachable',
            verb, recipient_id, exc_info=True,
        )
