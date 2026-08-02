from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Follow


class FollowRequestSerializer(serializers.ModelSerializer):
    """A pending follow request, shown in the recipient's requests inbox."""
    follower = UserSerializer(read_only=True)

    class Meta:
        model = Follow
        fields = ['id', 'follower', 'status', 'created_at']
        read_only_fields = fields
