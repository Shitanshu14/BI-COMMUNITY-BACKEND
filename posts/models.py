import uuid
from django.conf import settings
from django.db import models

from communities.models import Community


class Post(models.Model):
    """
    A single feed item. MVP ships only QUESTION and KNOWLEDGE types
    (see strategy doc: 'start with Question/Knowledge post types only').
    PROJECT / RESOURCE / POLL exist in the model now so the schema doesn't
    need to change later, but the API/UI can restrict which ones are exposed.
    """

    class PostType(models.TextChoices):
        QUESTION = 'question', 'Question'
        KNOWLEDGE = 'knowledge', 'Knowledge'
        PROJECT = 'project', 'Project'          # Phase 2
        RESOURCE = 'resource', 'Resource'        # Phase 2
        POLL = 'poll', 'Poll'                    # Phase 2

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='posts')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')

    post_type = models.CharField(max_length=20, choices=PostType.choices, default=PostType.QUESTION)
    title = models.CharField(max_length=200)
    body = models.TextField()
    image = models.ImageField(upload_to='post_images/', blank=True, null=True)

    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='liked_posts', blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def like_count(self):
        return self.likes.count()

    @property
    def comment_count(self):
        return self.comments.count()


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment by {self.author} on {self.post}'
