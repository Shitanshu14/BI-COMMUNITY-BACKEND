from rest_framework import serializers

from communities.models import Community
from circles.models import Circle

from django.contrib.auth import get_user_model

User = get_user_model()


class SupportUserSerializer(serializers.ModelSerializer):
    """
    One row in the support dashboard's user table. Counts are annotated
    onto the queryset in the view (see SupportUserListView) rather than
    computed here as SerializerMethodFields — the same N+1 mistake fixed
    elsewhere in this codebase (see posts/serializers.py CommentSerializer
    history) would otherwise fire 3 extra queries per user in the list.
    """

    community_count = serializers.IntegerField(read_only=True)
    circle_count = serializers.IntegerField(read_only=True)
    post_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'avatar', 'headline',
            'is_verified', 'is_active', 'is_support', 'is_staff',
            'email_confirmed', 'created_at',
            'community_count', 'circle_count', 'post_count',
        ]
        read_only_fields = fields


class SupportCommunitySerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    def get_member_count(self, obj):
        return obj.member_count_val

    class Meta:
        model = Community
        fields = ['id', 'name', 'description', 'icon', 'is_public', 'created_at', 'member_count']
        read_only_fields = fields


class SupportCircleSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    def get_member_count(self, obj):
        return obj.member_count_val

    class Meta:
        model = Circle
        fields = ['id', 'name', 'description', 'icon', 'created_at', 'member_count']
        read_only_fields = fields


class SupportCommunityMemberSerializer(serializers.Serializer):
    """Flattens Membership -> user fields the table needs, plus their role
    *in this community* (member/moderator/admin) alongside their account
    status, so support can spot e.g. a moderator whose account got
    deactivated without switching screens."""
    id = serializers.UUIDField(source='user.id')
    username = serializers.CharField(source='user.username')
    email = serializers.EmailField(source='user.email')
    avatar = serializers.ImageField(source='user.avatar', allow_null=True)
    is_active = serializers.BooleanField(source='user.is_active')
    role = serializers.CharField()
    joined_at = serializers.DateTimeField()


class SupportCircleMemberSerializer(serializers.Serializer):
    id = serializers.UUIDField(source='user.id')
    username = serializers.CharField(source='user.username')
    email = serializers.EmailField(source='user.email')
    avatar = serializers.ImageField(source='user.avatar', allow_null=True)
    is_active = serializers.BooleanField(source='user.is_active')
    role = serializers.CharField()
    joined_at = serializers.DateTimeField()
