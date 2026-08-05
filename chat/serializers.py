from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Message


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    recipient = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'community', 'recipient', 'sender', 'body', 'read_at', 'created_at']
        read_only_fields = ['id', 'sender', 'read_at', 'created_at']


class ConversationSerializer(serializers.Serializer):
    """One row per DM conversation partner — the person, their last message,
    and when it was sent. Built from a plain dict in DMConversationsView
    rather than a model, so this just declares the output shape."""
    user = UserSerializer()
    last_message = serializers.CharField()
    last_message_at = serializers.DateTimeField()
    unread = serializers.BooleanField()
