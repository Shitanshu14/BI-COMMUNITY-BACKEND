import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for SETU.
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
