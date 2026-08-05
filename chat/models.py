import uuid
from django.conf import settings
from django.db import models

from communities.models import Community


class Message(models.Model):
    """
    Real-time chat message — either inside a community room (`community`
    set, `recipient` null) or a 1-on-1 direct message (`recipient` set,
    `community` null). Exactly one of the two must be set; enforced in
    ChatConsumer/DMConsumer.save_message rather than a DB constraint since
    SQLite (local/dev) doesn't enforce CHECK constraints the same way
    Postgres does.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name='messages', null=True, blank=True
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dm_received',
        null=True, blank=True,
    )
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sender', 'recipient', 'created_at']),
            models.Index(fields=['recipient', 'sender', 'created_at']),
        ]

    def __str__(self):
        return f'{self.sender}: {self.body[:30]}'
