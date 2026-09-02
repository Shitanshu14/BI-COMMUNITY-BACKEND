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

    # Profile picture (the small circular badge on the card) and cover photo
    # (the wide banner behind it) are deliberately separate fields/uploads —
    # a community can change its logo without losing its banner and vice
    # versa. Both are plain ImageFields, and Django/Pillow already store and
    # serve animated .gif files exactly like any other image, so uploading a
    # "live" GIF as either one just works — the browser animates it in the
    # <img> tag with no extra backend plumbing required.
    icon = models.ImageField(upload_to='community_icons/', blank=True, null=True)
    cover_image = models.ImageField(upload_to='community_covers/', blank=True, null=True)

    rules = models.TextField(blank=True, help_text='One rule per line')
    is_public = models.BooleanField(default=True)

    class Category(models.TextChoices):
        TECHNOLOGY = 'technology', 'Technology'
        EDUCATION = 'education', 'Education'
        SOCIAL = 'social', 'Social'
        GAMING = 'gaming', 'Gaming'
        BUSINESS = 'business', 'Business'
        ENTERTAINMENT = 'entertainment', 'Entertainment'
        OTHER = 'other', 'Other'

    # Powers the category pills / "Popular Categories" filtering on the
    # Communities dashboard (Technology, Education, Social, Gaming,
    # Business, ...).
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)

    # Blue checkmark next to the name on official/featured communities —
    # purely cosmetic, set from the admin, no verification workflow behind it.
    is_verified = models.BooleanField(default=False)

    # A small vanity offset added on top of the *real* approved-member count
    # for display purposes only (e.g. so a freshly-seeded flagship community
    # can show "2.4K Members" instead of "1" without needing thousands of
    # fake user rows). Never affects permissions, joins, or anything
    # functional — see `member_count` below.
    member_count_boost = models.PositiveIntegerField(default=0)

    class JoinMode(models.TextChoices):
        OPEN = 'open', 'Open — join instantly'
        APPROVAL = 'approval', 'Registration required — an admin must approve'

    # "Registration based" community creation: when APPROVAL, tapping Join
    # doesn't grant membership right away — it creates a pending Membership
    # (see Membership.Status below) that a community admin/moderator has to
    # approve first. OPEN keeps the original one-tap join behaviour.
    join_mode = models.CharField(max_length=20, choices=JoinMode.choices, default=JoinMode.OPEN)

    # When true, the community is read-only: no new posts, comments, or
    # likes (see posts/views.py's `_check_not_on_hold` for enforcement).
    # Existing content stays fully visible — members can still browse and
    # stay in the community, they just can't post while support has this
    # flagged (e.g. investigating a spam wave, a dispute, before shutting
    # the community down entirely). Toggled from the support dashboard,
    # never by community members themselves.
    is_on_hold = models.BooleanField(default=False)

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
        # Only APPROVED memberships count as real members — someone with a
        # pending registration request hasn't joined yet, so they shouldn't
        # inflate the count or show up as "joined" anywhere. The vanity
        # boost (if any) is layered on top purely for display.
        return self.members_approved.count() + self.member_count_boost

    @property
    def members_approved(self):
        return self.members.filter(membership__status=Membership.Status.APPROVED)


class Membership(models.Model):
    """Through-table for Join/Leave logic (MVP feature #2)."""

    class Role(models.TextChoices):
        MEMBER = 'member', 'Member'
        MODERATOR = 'moderator', 'Moderator'
        ADMIN = 'admin', 'Admin'

    class Status(models.TextChoices):
        APPROVED = 'approved', 'Approved'
        # Only used for communities with join_mode=APPROVAL — the person
        # asked to join ("registered") but an admin hasn't approved them
        # yet, so they aren't a real member: no private posts, no chat,
        # not counted in member_count, not shown as "joined".
        PENDING = 'pending', 'Pending approval'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    community = models.ForeignKey(Community, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.APPROVED)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'community')

    def __str__(self):
        return f'{self.user} in {self.community} ({self.role}, {self.status})'
