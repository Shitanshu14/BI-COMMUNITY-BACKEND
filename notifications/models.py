import uuid
from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    In-app notification (bell icon in the mockups). Created by Celery tasks
    running in the background (see notifications/tasks.py) so the request
    that triggered it — a like, a comment, a verification decision —
    doesn't have to wait on this to finish.
    """

    class Verb(models.TextChoices):
        POST_LIKED = 'post_liked', 'liked your post'
        COMMENT_LIKED = 'comment_liked', 'liked your comment'
        POST_COMMENTED = 'post_commented', 'commented on your post'
        COMMENT_REPLIED = 'comment_replied', 'replied to your comment'
        COMMUNITY_JOINED = 'community_joined', 'joined your community'
        VERIFICATION_APPROVED = 'verification_approved', 'your verification was approved'
        VERIFICATION_REJECTED = 'verification_rejected', 'your verification was rejected'
        NEW_FOLLOWER = 'new_follower', 'started following you'
        FOLLOW_REQUESTED = 'follow_requested', 'requested to follow you'
        FOLLOW_ACCEPTED = 'follow_accepted', 'accepted your follow request'
        CIRCLE_INVITED = 'circle_invited', 'invited you to a circle'
        CIRCLE_INVITE_ACCEPTED = 'circle_invite_accepted', 'accepted your circle invite'
        CIRCLE_QUESTION_ANSWERED = 'circle_question_answered', 'answered your question'
        CIRCLE_ANSWER_ACCEPTED = 'circle_answer_accepted', 'accepted your answer'
        CIRCLE_EVENT_CREATED = 'circle_event_created', 'scheduled an event in a circle'
        ANSWER_ACCEPTED = 'answer_accepted', 'accepted your answer'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', help_text='Who triggered this notification, if anyone'
    )
    verb = models.CharField(max_length=30, choices=Verb.choices)

    # Generic-ish pointer back to the relevant object, kept simple (no
    # contenttypes framework) since the MVP only has posts/communities to
    # link to. `target_id` is whatever id is relevant for that verb.
    target_id = models.UUIDField(null=True, blank=True)

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # The bell icon polls "how many unread do I have" + "list my
            # notifications" against exactly this filter shape, so it's
            # one of the most frequently-run queries in the app.
            models.Index(fields=['recipient', 'is_read']),
        ]

    def __str__(self):
        return f'{self.recipient} — {self.get_verb_display()}'
