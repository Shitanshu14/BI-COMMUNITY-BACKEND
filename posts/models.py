import uuid
from django.conf import settings
from django.db import models

from communities.models import Community
from setu_backend.imaging import compress_uploaded_image


class Post(models.Model):
    """
    A single feed item. Phase 2 collapses the content-type picker down to
    three top-level types — QUESTION / POST / POLL — matching the "All /
    Questions / Posts / Polls" feed tabs. What used to be separate
    KNOWLEDGE / PROJECT / RESOURCE post types are now just `tags` on a
    POST-type post (e.g. tags=["Knowledge", "Python", "OpenAI"]), so the
    composer stays 3 buttons wide instead of a 5+ option dropdown.
    """

    class PostType(models.TextChoices):
        QUESTION = 'question', 'Question'
        POST = 'post', 'Post'
        POLL = 'poll', 'Poll'

    # Suggested tags shown as quick-pick chips in the composer when creating
    # a POST-type post. Freeform tags are still allowed (see `tags` below) —
    # this is just what the UI offers by default.
    SUGGESTED_TAGS = ['Knowledge', 'Project', 'Resource']

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='posts')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')

    post_type = models.CharField(max_length=20, choices=PostType.choices, default=PostType.QUESTION)
    title = models.CharField(max_length=200)
    body = models.TextField()
    image = models.ImageField(upload_to='post_images/', blank=True, null=True)

    # Freeform labels for POST-type posts (Knowledge/Project/Resource/tech
    # stack, etc). Stored as a plain JSON list of short strings rather than
    # a separate Tag model — there's no tag browsing/filtering-by-tag
    # requirement yet, so a normalized table would be premature.
    tags = models.JSONField(default=list, blank=True)

    # Optional external links attached to a post (portfolio, live demo,
    # repo, article URL, Instagram — anything). Deliberately generic rather
    # than fixed "repo_url"/"live_url" fields: a Project post from a
    # developer might link a repo, one from an artist might link a
    # portfolio or Behance page. Stored as a flat list of "Label|||URL"
    # strings (see PostSerializer.links) so no extra table/migration is
    # needed if the shape ever needs to grow.
    links = models.JSONField(default=list, blank=True)

    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='liked_posts', blank=True
    )

    # Pinned posts (community admin/moderator only — see PostViewSet.pin).
    # Pinned posts float to the top of the feed (see get_queryset ordering).
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)

    # QUESTION-type posts only: the asker marks their own question solved
    # once they've got the answer they needed. One-way flag (no "unsolve")
    # — see PostViewSet.mark_solved — so the UI can safely swap the "Mark
    # solved" button for a permanent "Solved" badge instead of a toggle.
    is_solved = models.BooleanField(default=False)
    solved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            # Matches PostViewSet.get_queryset()'s community feed query
            # exactly (filter by community, order by pinned then recency) —
            # without this, that ordering falls back to a full sort once a
            # community has more than a page or two of posts.
            models.Index(fields=['community', '-is_pinned', '-created_at']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # `_committed` is False only for a file that was just attached in
        # this request (not yet written to storage) — this guard stops a
        # post whose *text* is being edited later from re-processing (and
        # re-compressing, lossily, again) an image that was already
        # resized on a previous save.
        if self.image and not self.image._committed:
            compress_uploaded_image(self.image)
        super().save(*args, **kwargs)

    @property
    def like_count(self):
        return self.likes.count()

    @property
    def comment_count(self):
        return self.comments.count()


class PostImage(models.Model):
    """One image in a post's gallery. A post can carry several of these
    (the composer's multi-image picker) and the feed renders them as a
    swipeable slider — see PostExtras/PostImageSlider on the frontend.
    `Post.image` (single, legacy) is kept for posts created before this
    model existed; new uploads always go through here instead."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='post_images/')
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'Image {self.order} for {self.post_id}'

    def save(self, *args, **kwargs):
        if self.image and not self.image._committed:
            compress_uploaded_image(self.image)
        super().save(*args, **kwargs)


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField()

    # Nested replies: null = top-level comment, set = a reply to another
    # comment on the same post. Any depth is allowed — the API/UI decide
    # how deep to visually indent (see posts/serializers.py CommentSerializer).
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies'
    )

    # Same pattern as Post.likes below — a plain M2M rather than a separate
    # "reaction type" model, since comments only ever get one kind of like
    # (a heart), matching the post-level like exactly.
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='liked_comments', blank=True
    )

    # QUESTION-type posts only: the asker can mark one comment as the
    # accepted answer (mirrors CircleAnswer.is_accepted). Only ever one
    # accepted comment per post — see PostViewSet.accept_comment, which
    # clears any previous accepted comment before setting the new one.
    is_accepted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_accepted', 'created_at']

    def __str__(self):
        return f'Comment by {self.author} on {self.post}'

    @property
    def like_count(self):
        return self.likes.count()


class PollOption(models.Model):
    """One selectable option on a POLL-type post. Created together with the
    post (2-6 options) when `post_type == 'poll'`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='poll_options')
    text = models.CharField(max_length=150)
    order = models.PositiveSmallIntegerField(default=0)

    votes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='poll_votes', blank=True, through='PollVote'
    )

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.text

    @property
    def vote_count(self):
        return self.votes.count()


class PollVote(models.Model):
    """Through-table so a user's vote can be looked up/changed — one vote
    per user per post (switching option moves the existing vote)."""

    option = models.ForeignKey(PollOption, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One vote per (post, user) — enforced in the view since `post` isn't
        # directly on this model; unique_together here just stops the exact
        # same option being voted twice by the same user.
        unique_together = ('option', 'user')


class SavedPost(models.Model):
    """A user bookmarking a post for later (the 🔖 Save action on a post
    card). Plain join table — `related_name='saved_by'` on the post side
    lets PostViewSet annotate is_saved the same way it annotates is_liked."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_posts')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='saved_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'post')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} saved {self.post}'
