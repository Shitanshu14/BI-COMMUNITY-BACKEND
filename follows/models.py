import uuid
from django.conf import settings
from django.db import models


class Follow(models.Model):
    """
    One row per follow relationship (follower -> following).

    Public accounts: row is created with status=ACCEPTED immediately.
    Private accounts: row is created with status=PENDING and sits in the
    target's "follow requests" list until they accept/reject it (see
    follows/views.py).
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following_set'
    )
    following = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='follower_set'
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACCEPTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.follower} -> {self.following} ({self.status})'
