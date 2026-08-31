import uuid
from django.conf import settings
from django.db import models

from communities.models import Community
from circles.models import Circle, CircleQuestion
from posts.models import Post


class Message(models.Model):
    """
    Real-time chat message — inside a community room (`community` set),
    inside a circle room (`circle` set), or a 1-on-1 direct message
    (`recipient` set). Exactly one of the three must be set; enforced in
    ChatConsumer/CircleChatConsumer/DMConsumer.save_message rather than a
    DB constraint since SQLite (local/dev) doesn't enforce CHECK
    constraints the same way Postgres does.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name='messages', null=True, blank=True
    )
    circle = models.ForeignKey(
        Circle, on_delete=models.CASCADE, related_name='messages', null=True, blank=True
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dm_received',
        null=True, blank=True,
    )
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_messages')
    body = models.TextField()

    # Sharing a community post, a circle Q&A question, or an invite to
    # join a community/circle straight into a chat message — WhatsApp's
    # "forward", but for in-app objects instead of a file. At most one of
    # these four is ever set on a given message. All use SET_NULL rather
    # than CASCADE: if the shared post/question/community/circle is later
    # deleted, the message itself should keep existing (just render as
    # "this content was removed") instead of the whole conversation
    # losing that message.
    shared_post = models.ForeignKey(
        Post, on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_in_messages'
    )
    shared_question = models.ForeignKey(
        CircleQuestion, on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_in_messages'
    )
    shared_community = models.ForeignKey(
        Community, on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_in_messages'
    )
    shared_circle = models.ForeignKey(
        Circle, on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_in_messages'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sender', 'recipient', 'created_at']),
            models.Index(fields=['recipient', 'sender', 'created_at']),
            # DMUnreadCountView polls exactly this filter shape every 20s
            # for every signed-in user (sidebar badge) — recipient+created_at
            # above doesn't help much when read_at is the selective column.
            models.Index(fields=['recipient', 'read_at']),
        ]

    def __str__(self):
        return f'{self.sender}: {self.body[:30]}'
