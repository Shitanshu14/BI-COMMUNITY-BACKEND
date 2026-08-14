import uuid
from django.conf import settings
from django.db import models


class Circle(models.Model):
    """
    A Circle, per the business architecture doc: "Private, invite-only,
    small verified-user group for collaboration and daily interaction."

    Unlike a Community (public/discoverable, admin-curated — see
    communities/models.py), a Circle:
      - is always private (no is_public toggle — it's the point of the model)
      - can be created by ANY authenticated user, not just staff/admins
      - only grows via invite (CircleInvite below), never open join/discovery
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.ImageField(upload_to='circle_icons/', blank=True, null=True)

    # Soft cap, not DB-enforced — "small" per the architecture doc. Kept as
    # a field (rather than a hardcoded constant) so a Pro-tier limit bump
    # (see Monetization sheet: "Pro ... more Circles, higher limits") can
    # vary this per circle later without a migration.
    max_members = models.PositiveIntegerField(default=50)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='circles_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='CircleMembership', related_name='circles'
    )

    class Meta:
        verbose_name_plural = 'Circles'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        return self.members.count()

    @property
    def is_full(self):
        return self.member_count >= self.max_members


class CircleMembership(models.Model):
    """Through-table. Owner = creator (or promoted); Member = everyone else."""

    class Role(models.TextChoices):
        MEMBER = 'member', 'Member'
        OWNER = 'owner', 'Owner'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    circle = models.ForeignKey(Circle, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'circle')

    def __str__(self):
        return f'{self.user} in {self.circle} ({self.role})'


class CircleInvite(models.Model):
    """
    A pending/resolved invitation into a Circle. This is the ONLY way to
    join a Circle (no public "discover + join" path — see Circle docstring),
    matching the "Circle Loop" from the architecture doc:
    Create -> Invite -> Signup -> Interaction.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    circle = models.ForeignKey(Circle, on_delete=models.CASCADE, related_name='invites')
    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='circle_invites_received'
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='circle_invites_sent'
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # A user can only have one *pending* invite outstanding per circle
        # at a time — re-inviting after a decline is allowed (that's a new
        # row), but you can't stack two pending invites to the same person.
        constraints = [
            models.UniqueConstraint(
                fields=['circle', 'invited_user'],
                condition=models.Q(status='pending'),
                name='unique_pending_invite_per_circle_user',
            )
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.invited_user} invited to {self.circle} ({self.status})'


class CircleEvent(models.Model):
    """
    A scheduled event/session for a Circle — call, meetup, deadline,
    whatever the group wants on a shared calendar. Any member can create
    one (not owner-only) since Circles are meant for tight collaboration
    between equals, not a broadcast channel.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    circle = models.ForeignKey(Circle, on_delete=models.CASCADE, related_name='events')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='circle_events_created'
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)

    # Deliberately a single freeform string, not separate
    # "physical address" / "video link" fields — a circle's event might be
    # a Zoom call, a Discord voice channel, or an actual coffee shop, and
    # forcing a choice between two field types just to store "wherever we
    # meet" would be over-engineering for a small-group scheduling feature.
    location = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    rsvps = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='CircleEventRSVP', related_name='circle_events_rsvped'
    )

    class Meta:
        ordering = ['starts_at']

    def __str__(self):
        return f'{self.title} ({self.circle})'

    @property
    def is_past(self):
        from django.utils import timezone
        return self.starts_at < timezone.now()

    @property
    def going_count(self):
        return self.rsvp_set.filter(status=CircleEventRSVP.Status.GOING).count()


class CircleEventRSVP(models.Model):
    class Status(models.TextChoices):
        GOING = 'going', 'Going'
        MAYBE = 'maybe', 'Maybe'
        DECLINED = 'declined', "Can't go"

    event = models.ForeignKey(CircleEvent, on_delete=models.CASCADE, related_name='rsvp_set')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GOING)
    responded_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('event', 'user')

    def __str__(self):
        return f'{self.user} -> {self.event} ({self.status})'


class CircleQuestion(models.Model):
    """
    A question posted inside a Circle. Circles are meant for tight-knit,
    ongoing collaboration, and a flat live chat log makes it hard to find
    "did anyone ever answer X" later — so alongside the live chat, a
    Circle also gets a lightweight Q&A board: post a question, members
    reply with answers, the asker (or the circle owner) can mark one
    answer as accepted.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    circle = models.ForeignKey(Circle, on_delete=models.CASCADE, related_name='questions')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='circle_questions'
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_solved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def answer_count(self):
        return self.answers.count()


class CircleAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(CircleQuestion, on_delete=models.CASCADE, related_name='answers')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='circle_answers'
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_accepted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_accepted', 'created_at']

    def __str__(self):
        return f'Answer by {self.author} on {self.question_id}'
