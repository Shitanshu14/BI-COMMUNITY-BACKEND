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
        async_to_sync(channel_layer.group_send)(
            f'notifications_{recipient_id}',
            {
                'type': 'notify',
                'notification': NotificationSerializer(notification).data,
            },
        )

    return str(notification.id)
