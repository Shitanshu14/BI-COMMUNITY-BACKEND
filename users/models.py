import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for BI Community.
    Extends Django's built-in auth so email login + verification fields work
    out of the box (matches the 'Verified Student/Professional' badge in the UI).
    """

    class Role(models.TextChoices):
        STUDENT = 'student', 'Student'
        PROFESSIONAL = 'professional', 'Professional'
        EDUCATOR = 'educator', 'Educator'
        ORGANISATION = 'organisation', 'Organisation'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    bio = models.CharField(max_length=280, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    # Denormalised "headline" shown under name on cards, e.g. "Class 11 Student"
    headline = models.CharField(max_length=100, blank=True)

    is_verified = models.BooleanField(default=False)
    reputation_points = models.PositiveIntegerField(default=0)

    # Grants access to the (separate, limited) support dashboard — NOT the
    # same as is_staff, which grants full Django Admin access. A support
    # team member logs in through the normal app login; this flag just
    # unlocks the extra "/support" screens in the frontend and the
    # /api/support/ endpoints on the backend.
    is_support = models.BooleanField(default=False)

    # Separate from `is_verified` (which is the admin-approved Student/
    # Professional/Educator badge). This just tracks whether the person
    # clicked the confirmation link sent to their email at signup.
    email_confirmed = models.BooleanField(default=False)

    # Instagram-style: public profile = anyone who taps Follow follows
    # instantly; private profile = the follow sits as a pending request
    # until the person approves it (see follows app).
    is_private = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email


class Block(models.Model):
    """
    One row per block relationship (blocker -> blocked). Blocking is
    one-directional to record ("who did the blocking"), but its *effect* is
    made mutual everywhere it's checked (posts/comments/search querysets
    exclude a user from both sides — see posts/views.py, users/views.py) so
    neither person sees the other's content once either one blocks.

    Blocking also immediately removes any existing follow relationship in
    either direction (see BlockUserView) so a block can't be worked around
    by an existing follow.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocking_set'
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocked_by_set'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.blocker} blocked {self.blocked}'
