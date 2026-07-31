import uuid
from django.conf import settings
from django.db import models


class Community(models.Model):
    """
    A single community, e.g. 'AI Community'. Each has Feed | Chat | Members |
    Activities | Resources — this model backs the 'Feed' tab header info
    (member count, description, rules) seen in the mockups.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True)
    description = models.TextField(blank=True)
    icon = models.ImageField(upload_to='community_icons/', blank=True, null=True)
    rules = models.TextField(blank=True, help_text='One rule per line')
    is_public = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='communities_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='Membership', related_name='communities'
    )

    class Meta:
        verbose_name_plural = 'Communities'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        return self.members.count()


class Membership(models.Model):
    """Through-table for Join/Leave logic (MVP feature #2)."""

    class Role(models.TextChoices):
        MEMBER = 'member', 'Member'
        MODERATOR = 'moderator', 'Moderator'
        ADMIN = 'admin', 'Admin'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    community = models.ForeignKey(Community, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'community')

    def __str__(self):
        return f'{self.user} in {self.community} ({self.role})'
