import uuid

from django.conf import settings
from django.db import models


class SupportTicket(models.Model):
    """
    A "contact support" submission. Deliberately NOT tied to requiring
    login — the two people most likely to need this are a blocked user
    (who by definition can't log in) and someone who forgot their
    password and the reset email isn't arriving. `username`/`email` are
    plain text the person types in, not a FK to User, since we can't
    assume they can authenticate to prove who they are.

    `user` is an optional best-effort link: if the submission came from
    someone who *is* logged in (the in-app "Contact support" entry point,
    as opposed to the logged-out one on the login page), we attach it so
    support can jump straight to that account.
    """

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        RESOLVED = 'resolved', 'Resolved'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets'
    )
    username = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f'{self.username or self.email or "anonymous"}: {self.message[:40]}'
