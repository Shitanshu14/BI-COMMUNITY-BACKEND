import uuid
from django.conf import settings
from django.db import models

from communities.models import Community


class Message(models.Model):
    """
    Real-time chat message inside a community (one chat room per community
    for MVP — matches the 'Chat' tab in the mockups; DMs can be added in Phase 2
    by making `community` nullable and adding a `recipient` field).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender}: {self.body[:30]}'
