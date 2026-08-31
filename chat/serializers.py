from rest_framework import serializers

from users.serializers import UserSerializer
from posts.models import Post
from circles.models import CircleQuestion, Circle
from communities.models import Community
from .models import Message


class SharedPostSerializer(serializers.ModelSerializer):
    """Compact read-only preview of a Post shared into a chat message —
    just enough to render a WhatsApp-style forwarded-post card without the
    receiving client needing a second round trip. Full detail (comments,
    poll options, etc.) is still only a tap away via `id` -> /posts/<id>."""
    author = serializers.CharField(source='author.username', read_only=True)
    community_name = serializers.CharField(source='community.name', read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'post_type', 'title', 'body', 'image', 'author', 'community', 'community_name',
            'like_count', 'comment_count', 'is_solved',
        ]


class SharedQuestionSerializer(serializers.ModelSerializer):
    """Compact preview of a Circle Q&A question shared into a message."""
    author = serializers.CharField(source='author.username', read_only=True)
    circle_name = serializers.CharField(source='circle.name', read_only=True)

    class Meta:
        model = CircleQuestion
        fields = ['id', 'title', 'body', 'author', 'circle', 'circle_name', 'is_solved', 'answer_count']


class SharedCommunitySerializer(serializers.ModelSerializer):
    """Compact preview of a Community shared into a message — powers the
    "join this community" invite card in chat."""
    class Meta:
        model = Community
        fields = ['id', 'name', 'description', 'icon', 'member_count']


class SharedCircleSerializer(serializers.ModelSerializer):
    """Compact preview of a Circle shared into a message. Circles are
    invite-only (see circles/models.py), so this card is what an existing
    member sends someone to say "come join us" — the recipient still needs
    a real CircleInvite to actually get in; this is just the nudge."""
    class Meta:
        model = Circle
        fields = ['id', 'name', 'description', 'icon', 'member_count']


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    recipient = UserSerializer(read_only=True)
    shared_post = SharedPostSerializer(read_only=True)
    shared_question = SharedQuestionSerializer(read_only=True)
    shared_community = SharedCommunitySerializer(read_only=True)
    shared_circle = SharedCircleSerializer(read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'community', 'circle', 'recipient', 'sender', 'body',
            'shared_post', 'shared_question', 'shared_community', 'shared_circle',
            'read_at', 'created_at',
        ]
        read_only_fields = ['id', 'sender', 'read_at', 'created_at']


class ConversationSerializer(serializers.Serializer):
    """One row per DM conversation partner — the person, their last message,
    and when it was sent. Built from a plain dict in DMConversationsView
    rather than a model, so this just declares the output shape."""
    user = UserSerializer()
    last_message = serializers.CharField()
    last_message_at = serializers.DateTimeField()
    unread = serializers.BooleanField()
