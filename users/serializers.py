from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public-facing profile representation (used on feed cards, member lists, etc.)"""

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'headline', 'bio',
            'avatar', 'is_verified', 'email_confirmed', 'is_private', 'reputation_points', 'created_at',
        ]
        read_only_fields = ['id', 'is_verified', 'email_confirmed', 'reputation_points', 'created_at']


class UserProfileSerializer(UserSerializer):
    """
    Full profile view — GET /api/users/<id>/ — Instagram-style: post count,
    follower/following counts, and (relative to whoever is asking) whether
    they already follow this person / have a pending request / are followed
    back by them.
    """
    post_count = serializers.SerializerMethodField()
    follower_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    follow_status = serializers.SerializerMethodField()  # 'following' | 'requested' | None
    is_followed_by = serializers.SerializerMethodField()
    communities = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + [
            'post_count', 'follower_count', 'following_count',
            'is_following', 'follow_status', 'is_followed_by', 'communities',
        ]

    def get_post_count(self, obj):
        return obj.posts.count()

    def get_follower_count(self, obj):
        from follows.models import Follow
        return Follow.objects.filter(following=obj, status=Follow.Status.ACCEPTED).count()

    def get_following_count(self, obj):
        from follows.models import Follow
        return Follow.objects.filter(follower=obj, status=Follow.Status.ACCEPTED).count()

    def _request_user(self):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return request.user
        return None

    def get_is_following(self, obj):
        me = self._request_user()
        if not me or me == obj:
            return False
        from follows.models import Follow
        return Follow.objects.filter(follower=me, following=obj, status=Follow.Status.ACCEPTED).exists()

    def get_follow_status(self, obj):
        me = self._request_user()
        if not me or me == obj:
            return None
        from follows.models import Follow
        f = Follow.objects.filter(follower=me, following=obj).first()
        return f.status if f else None

    def get_is_followed_by(self, obj):
        me = self._request_user()
        if not me or me == obj:
            return False
        from follows.models import Follow
        return Follow.objects.filter(follower=obj, following=me, status=Follow.Status.ACCEPTED).exists()

    def get_communities(self, obj):
        from communities.serializers import CommunitySerializer
        return CommunitySerializer(obj.communities.all(), many=True, context=self.context).data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'role', 'headline']

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            role=validated_data.get('role', User.Role.STUDENT),
            headline=validated_data.get('headline', ''),
        )


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
