from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserSerializer(read_only=True)
    verb_display = serializers.CharField(source='get_verb_display', read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'actor', 'verb', 'verb_display', 'target_id', 'is_read', 'created_at']
        read_only_fields = fields
