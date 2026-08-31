from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class BlockAwareTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    SimpleJWT's default login flow calls Django's authenticate(), whose
    ModelBackend silently returns None for is_active=False users — so a
    blocked account (see support/views.py SupportUserToggleActiveView)
    gets the exact same generic "No active account found with the given
    credentials" as a wrong password. That reads as "user not found" to
    someone whose account support just blocked, which is confusing and
    doesn't tell them what to do next.

    This checks for that specific case first — correct password, but
    is_active=False — before falling through to the normal flow, so a
    blocked user gets a clear, actionable message instead.
    """

    def validate(self, attrs):
        login_input = attrs.get(self.username_field)
        password = attrs.get('password')
        if login_input and password:
            from django.db.models import Q
            candidate = User.objects.filter(Q(email__iexact=login_input) | Q(username__iexact=login_input)).first()
            if candidate and not candidate.is_active and candidate.check_password(password):
                raise AuthenticationFailed('Your account has been blocked. Please contact support for help.')
        return super().validate(attrs)


class UserSerializer(serializers.ModelSerializer):
    """Public-facing profile representation (used on feed cards, member lists, etc.)"""

    # Same cap as RegisterSerializer below — this serializer is also used
    # for PATCH /api/users/me/, so without this override a username could
    # be edited back up to Django's default 150-char limit.
    username = serializers.CharField(min_length=3, max_length=20)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'headline', 'bio',
            'avatar', 'is_verified', 'email_confirmed', 'is_private', 'reputation_points', 'created_at',
            'first_name', 'last_name', 'date_of_birth', 'description',
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
    is_blocked = serializers.SerializerMethodField()       # have *I* blocked them
    has_blocked_me = serializers.SerializerMethodField()   # have *they* blocked me

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + [
            'post_count', 'follower_count', 'following_count',
            'is_following', 'follow_status', 'is_followed_by', 'communities',
            'is_blocked', 'has_blocked_me',
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

    def get_is_blocked(self, obj):
        me = self._request_user()
        if not me or me == obj:
            return False
        from .models import Block
        return Block.objects.filter(blocker=me, blocked=obj).exists()

    def get_has_blocked_me(self, obj):
        me = self._request_user()
        if not me or me == obj:
            return False
        from .models import Block
        return Block.objects.filter(blocker=obj, blocked=me).exists()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    username = serializers.CharField(min_length=3, max_length=20)
    first_name = serializers.CharField(required=True, max_length=16)
    last_name = serializers.CharField(required=True, max_length=16)
    date_of_birth = serializers.DateField(required=True)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    bio = serializers.CharField(required=False, allow_blank=True, default='', max_length=280)
    avatar = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password', 'role', 'headline',
            'first_name', 'last_name', 'date_of_birth', 'description', 'bio', 'avatar'
        ]

    def validate_first_name(self, value):
        import re
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("First name must contain letters only.")
        return value

    def validate_last_name(self, value):
        import re
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("Last name must contain letters only.")
        return value

    def validate(self, attrs):
        role = attrs.get('role', User.Role.STUDENT)
        dob = attrs.get('date_of_birth')
        if dob:
            from datetime import date
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if role == User.Role.STUDENT:
                if age >= 18:
                    raise serializers.ValidationError({"date_of_birth": "Students must be under 18 years old."})
            else:
                if age < 18:
                    raise serializers.ValidationError({"date_of_birth": "Non-students must be 18 years old or older."})
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            role=validated_data.get('role', User.Role.STUDENT),
            headline=validated_data.get('headline', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            date_of_birth=validated_data.get('date_of_birth'),
            bio=validated_data.get('bio', ''),
            description=validated_data.get('description', ''),
            avatar=validated_data.get('avatar'),
        )
        from .models import PasswordHistory
        PasswordHistory.objects.create(user=user, password_hash=user.password)
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate(self, attrs):
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode
        from django.contrib.auth import get_user_model
        from django.contrib.auth.hashers import check_password
        
        uid = attrs.get('uid')
        new_password = attrs.get('new_password')
        User = get_user_model()
        
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise serializers.ValidationError("Invalid or expired password reset link.")
            
        from django.contrib.auth.tokens import default_token_generator
        token = attrs.get('token')
        if not default_token_generator.check_token(user, token):
            raise serializers.ValidationError("Invalid or expired password reset link.")

        # Check against password history
        histories = user.password_history.all()[:3]
        for history in histories:
            if check_password(new_password, history.password_hash):
                raise serializers.ValidationError({"new_password": "You cannot reuse any of your last 3 passwords."})
                
        # Also check current password just in case it's not in the history yet
        if check_password(new_password, user.password):
            raise serializers.ValidationError({"new_password": "You cannot reuse your current password."})

        return attrs
