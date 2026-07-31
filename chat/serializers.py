from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Message


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'community', 'sender', 'body', 'created_at']
        read_only_fields = ['id', 'sender', 'created_at']
