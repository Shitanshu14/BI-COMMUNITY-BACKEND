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
            'avatar', 'is_verified', 'reputation_points', 'created_at',
        ]
        read_only_fields = ['id', 'is_verified', 'reputation_points', 'created_at']


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
